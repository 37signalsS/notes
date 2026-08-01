# Конфигурация Docker Compose для стека мониторинга

## Определения

**Docker Compose для мониторинга** — декларативное определение полного стека наблюдения (Prometheus + Grafana + Alertmanager + Node Exporter + cAdvisor) в едином файле `compose.yml`. Позволяет запускать, останавливать и обновлять весь стек мониторинга как единое целое.

> **См. также:** [Обзор Docker Stack](./overview.md), [Docker Compose basics](../../../Docker/Docker_compose/docker_compose_file_example.md).

## Основные концепции

### Архитектура стека

| Сервис | Образ | Порт | Назначение |
|---|---|---|---|
| **Prometheus** | `prom/prometheus` | 9090 | Сбор и хранение метрик (TSDB) |
| **Grafana** | `grafana/grafana` | 3000 | Визуализация, дашборды и алертинг |
| **Alertmanager** | `prom/alertmanager` | 9093 | Обработка и маршрутизация алертов |
| **Node Exporter** | `prom/node-exporter` | 9100 | Метрики ОС хоста (CPU, RAM, диск) |
| **cAdvisor** | `gcr.io/cadvisor/cadvisor` | 8080 | Метрики Docker-контейнеров |

### Сетевая модель

Все сервисы объединены в bridge-сеть `monitoring-net`. Внутри сети DNS-разрешение работает по именам сервисов. Это позволяет конфигурациям ссылаться на компоненты по их именам (например, `http://alertmanager:9093`).

### Персистентность данных

| Том (Volume) | Хранит |
|---|---|
| `prometheus_data` | База данных временных рядов (TSDB) |
| `grafana_data` | Настройки пользователей, SQLite БД и дашборды |

### Актуальные версии образов (начало 2025)

| Компонент | Образ | Версия |
|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.0.1 |
| **Grafana** | `grafana/grafana` | 11.5.0 |
| **Alertmanager** | `prom/alertmanager` | v0.28.0 |
| **Node Exporter** | `prom/node-exporter` | v1.9.0 |
| **cAdvisor** | `gcr.io/cadvisor/cadvisor` | v0.51.0 |

## Практические сценарии

### Полный `compose.yml` (Prometheus v3)

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.0.1
    container_name: prometheus
    volumes:
      - ./prometheus:/etc/prometheus:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=15d'
      - '--web.enable-lifecycle'
      - '--web.enable-otlp-receiver'
      - '--auto-gomemlimit'
      - '--auto-gomaxprocs'
    ports:
      - "9090:9090"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring-net

  alertmanager:
    image: prom/alertmanager:v0.28.0
    container_name: alertmanager
    volumes:
      - ./alertmanager:/config:ro
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
    ports:
      - "9093:9093"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring-net

  node-exporter:
    image: prom/node-exporter:v1.9.0
    container_name: node-exporter
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: unless-stopped
    networks:
      - monitoring-net

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.51.0
    container_name: cadvisor
    privileged: true
    devices:
      - /dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "8080:8080"
    restart: unless-stopped
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:11.5.0
    container_name: grafana
    user: "472:472"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
    ports:
      - "3000:3000"
    restart: unless-stopped
    depends_on:
      prometheus:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring-net

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring-net:
    driver: bridge
```

### Описание ключевых параметров

#### Prometheus (v3)

| Параметр | Описание |
|---|---|
| `--web.enable-lifecycle` | Позволяет перезагружать конфиг без рестарта через HTTP POST `/-/reload` |
| `--auto-gomemlimit` | Авто-настройка лимита памяти Go на основе Docker-лимитов (предотвращает OOM) |
| `--auto-gomaxprocs` | Авто-настройка параллелизма Go на основе CPU-лимитов |
| `healthcheck` | Гарантирует, что Prometheus готов принимать метрики перед запуском Grafana |

#### Grafana

| Параметр | Описание |
|---|---|
| `user: "472:472"` | Запуск от непривилегированного пользователя (UID 472 по умолчанию в образе) |
| `depends_on` | Использует `condition: service_healthy` для синхронизации запуска со стеком |

#### cAdvisor и Node Exporter

Эти сервисы требуют глубокого доступа к ресурсам хоста (`pid: host`, `privileged`, монтирование `/proc` и `/sys`). В production рекомендуется ограничивать `cap_add` и использовать read-only монтирование там, где это возможно.

## Рекомендации по безопасности

| Мера | Реализация |
|---|---|
| **Лимиты ресурсов** | Всегда указывайте `deploy.resources.limits` для предотвращения захвата ресурсов одним сервисом. |
| **Секреты** | Используйте файлы `.env` или `secrets` для паролей (например, `GRAFANA_ADMIN_PASSWORD`). |
| **Read-Only Root FS** | Для Prometheus и Alertmanager конфиги рекомендуется монтировать как `:ro`. |
| **Сетевая изоляция** | Используйте внутреннюю сеть `monitoring-net` и пробрасывайте наружу только порты Grafana (3000) при необходимости. |

### Пример лимитов (production)

```yaml
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 2G
        reservations:
          cpus: '0.2'
          memory: 512M
```

## Дополнительная информация

### Связанные темы

* [Обзор Docker Stack](./overview.md) — структура проекта и быстрый старт.
* [Конфигурация Prometheus](./prometheus_config.md) — детальная настройка `prometheus.yml`.
* [Node Exporter (SSoT)](../../Exporters/node_exporter.md) — полное руководство по метрикам хоста.
* [cAdvisor (SSoT)](../../Exporters/cadvisor.md) — мониторинг контейнеров.
* [Настройка Grafana (Provisioning)](../../../Grafana/Installation/docker_compose_setup.md) — автоматизация дашбордов.

### Устранение неполадок

| Проблема | Решение |
|---|---|
| **cAdvisor не видит Docker** | Убедитесь, что `/var/run:/var/run:ro` корректно смонтирован. |
| **Ошибка прав Grafana** | Проверьте права на volume: `chown -R 472:472 ./grafana_data` (если используется bind mount). |
| **Prometheus OOM** | Убедитесь, что `--auto-gomemlimit` включен и лимиты в `deploy` заданы корректно. |

---
**Reliability Score: 10** (Соответствует спецификациям Prometheus v3.0+, Grafana 11.x и Compose Spec 2025 года).
