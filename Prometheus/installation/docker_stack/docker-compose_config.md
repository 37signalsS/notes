# Конфигурация Docker Compose для стека мониторинга

## Определения

**Docker Compose для мониторинга** — это декларативный способ описания инфраструктуры наблюдения (Prometheus, Grafana, Alertmanager и экспортеры) в виде единого стека. Использование Compose обеспечивает повторяемость развёртывания, изоляцию компонентов и простоту управления жизненным циклом (запуск, обновление, масштабирование).

> **См. также:** [Обзор Docker Stack](./overview.md), [Docker Compose basics](../../../Docker/Docker_compose/docker_compose_file_example.md).

## Основные концепции

### Архитектура и сетевое взаимодействие

Все компоненты стека объединяются в выделенную bridge-сеть. Это обеспечивает изоляцию от других контейнеров на хосте и позволяет использовать встроенный DNS Docker для обращения к сервисам по их именам (например, `prometheus:9090`).

### Персистентность и тома

Для надежного хранения данных используются именованные тома (Named Volumes), которые сохраняют состояние TSDB Prometheus и базу данных Grafana даже после удаления контейнеров. Конфигурационные файлы монтируются через Bind Mounts в режиме `read-only`.

### Актуальные версии образов (Август 2026)

| Компонент | Образ | Версия | Примечание |
|---|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.13.1 | Поддержка OTLP и Auto-tuning |
| **Grafana** | `grafana/grafana` | v13.1.1 | Современный UI и Alloy-интеграция |
| **Alertmanager** | `prom/alertmanager` | v0.33.1 | API v2, расширенная маршрутизация |
| **Node Exporter** | `prom/node-exporter` | v1.12.1 | Метрики хоста (Linux/UNIX) |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.60.5 | Метрики ресурсов контейнеров |

## Практические сценарии

### Эталонный `compose.yml` (Production Ready)

Ниже представлена конфигурация, оптимизированная для стабильности и безопасности.

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: monitoring-prometheus
    restart: unless-stopped
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
      - '--web.enable-otlp-receiver'
      - '--auto-gomemlimit'
      - '--auto-gomaxprocs'
    volumes:
      - ./prometheus:/etc/prometheus:ro
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9090/-/healthy"]
      interval: 15s
      timeout: 5s
      retries: 3
    logging: &default-logging
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - monitoring-net
    deploy:
      resources:
        limits:
          memory: 2G

  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: monitoring-alertmanager
    restart: unless-stopped
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
    volumes:
      - ./alertmanager:/etc/alertmanager:ro
      - alertmanager_data:/alertmanager
    ports:
      - "9093:9093"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
    logging: *default-logging
    networks:
      - monitoring-net

  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: monitoring-node-exporter
    restart: unless-stopped
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    logging: *default-logging
    networks:
      - monitoring-net

  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.5
    container_name: monitoring-cadvisor
    restart: unless-stopped
    privileged: true
    devices:
      - /dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    logging: *default-logging
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:13.1.1
    container_name: monitoring-grafana
    restart: unless-stopped
    user: "472:472"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASS:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      - "3000:3000"
    depends_on:
      prometheus:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/api/health"]
      interval: 30s
    logging: *default-logging
    networks:
      - monitoring-net

volumes:
  prometheus_data:
  alertmanager_data:
  grafana_data:

networks:
  monitoring-net:
    driver: bridge
```

## Ключевые аспекты настройки

### Безопасность и изоляция

1.  **User ID (UID):** Grafana запускается с `user: "472:472"`. Это требует настройки прав на хосте при использовании bind mounts: `chown -R 472:472 ./grafana/data`.
2.  **Read-Only Root FS:** Рекомендуется монтировать конфигурационные файлы как `:ro`. Для Prometheus и Alertmanager это предотвращает случайное изменение настроек изнутри контейнера.
3.  **Привилегии:** `node-exporter` и `cadvisor` требуют глубокого доступа к ОС хоста. Используйте их только в доверенных средах.

### Оптимизация Prometheus v3

*   **`--auto-gomemlimit`**: Обязателен при установке `deploy.resources.limits.memory`. Позволяет Go Runtime лучше управлять GC и избегать OOM.
*   **`--web.enable-lifecycle`**: Позволяет применять изменения в `prometheus.yml` через `curl -X POST /-/reload` без перезагрузки контейнера.

### Управление логами

Секция `logging` с драйвером `json-file` и ограничением `max-size` предотвращает переполнение диска логами Docker-контейнеров, что критично для стабильности мониторинга.

## Рекомендации по эксплуатации

| Действие | Команда / Метод |
|---|---|
| **Запуск стека** | `docker compose up -d` |
| **Остановка с очисткой** | `docker compose down -v` (удаляет все тома с данными) |
| **Проверка конфига** | `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml` |
| **Просмотр ресурсов** | `docker stats` (мониторинг потребления CPU/RAM контейнерами) |

## Дополнительная информация

### Связанные темы

* [Обзор Docker Stack](./overview.md) — общая концепция и структура проекта.
* [Конфигурация Prometheus](./prometheus_config.md) — настройка сбора данных и алертинга.
* [Node Exporter (SSoT)](../../Exporters/node_exporter.md) — подробный разбор системных метрик.
* [cAdvisor (SSoT)](../../Exporters/cadvisor.md) — детализация мониторинга контейнеров.
* [Мониторинг Docker Engine](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с демоном Docker.

### Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Prometheus OOM** | Нет лимитов или `--auto-gomemlimit` | Добавьте лимиты в `deploy` и флаг запуска. |
| **cAdvisor 0 metrics** | Нет доступа к `docker.sock` | Проверьте монтирование `/var/run:/var/run:ro`. |
| **Grafana Login Fail** | Неверный пароль в `.env` | Проверьте переменную `GF_SECURITY_ADMIN_PASSWORD`. |
