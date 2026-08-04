# Интеграция Docker с Prometheus

## Определения

**Интеграция Docker с Prometheus** — процесс настройки экспорта метрик Docker Engine и запущенных контейнеров в формате, совместимом с Prometheus. Это позволяет централизованно собирать, хранить и анализировать данные о состоянии инфраструктуры, производительности демона Docker и работе приложений.

## Основные концепции

Эффективный мониторинг контейнеризированной среды требует сбора данных на четырех уровнях:

1.  **Уровень Docker Engine:** Статистика самого демона (количество контейнеров, образов, ошибки сборки, состояние пула памяти). Сбор выполняется через встроенный экспортер.
2.  **Уровень инфраструктуры контейнеров:** Детальные метрики потребления ресурсов (CPU, RAM, Network, I/O) каждым отдельным контейнером. Сбор выполняется через **[cAdvisor](../../Prometheus/Exporters/cadvisor.md)**.
3.  **Уровень хост-машины:** Ресурсы ОС (диски, сеть хоста, системные службы).
    * **[Node Exporter (SSoT)](../../Prometheus/Exporters/node_exporter.md)** — основной источник данных о "железе".
4.  **Уровень приложения:** Внутренние показатели бизнес-логики. Сбор выполняется путем инструментирования кода или через Sidecar-экспортеры.

## Практические сценарии

### 1. Настройка встроенного экспортера Docker Engine

Docker Engine имеет встроенный эндпоинт метрик в формате Prometheus (порт `9323`).

**Настройка (`/etc/docker/daemon.json`):**

```json
{
  "metrics-addr": "0.0.0.0:9323",
  "experimental": true
}
```

*   `metrics-addr`: Адрес прослушивания. Для безопасности внутри закрытой сети или `127.0.0.1`.
*   `experimental`: Требуется для доступа к метрикам **Buildkit** (статистика сборок) и **containerd** (внутреннее состояние рантайма).

**Перезапуск и проверка:**
```bash
sudo systemctl restart docker
curl -s http://localhost:9323/metrics | grep docker_engine
```

### 2. Мониторинг Buildkit (сборка образов)

При включенном `experimental: true` становятся доступны метрики процесса сборки образов. Они позволяют отслеживать:
*   Количество активных сборок.
*   Использование кеша сборки.
*   Ошибки и время выполнения этапов.

Метрики начинаются с префикса `buildkit_`.

### 3. Конфигурация Prometheus

Существует два основных способа подключения Docker к Prometheus:

#### Способ А: Статическая конфигурация (Simple)
Подходит для фиксированного количества хостов.

```yaml
scrape_configs:
  - job_name: 'docker-engine'
    static_configs:
      - targets: ['192.168.1.10:9323']
```

#### Способ Б: Service Discovery (Dynamic)
Использование `docker_sd_config` позволяет Prometheus автоматически обнаруживать контейнеры, если у него есть доступ к Docker Socket.

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_config:
      - host: unix:///var/run/docker.sock # Или TCP адрес
    relabel_configs:
      # Пример: собирать метрики только с контейнеров с определенной меткой
      - source_labels: [__meta_docker_container_label_monitor]
        regex: true
        action: keep
```

### 4. Мониторинг в режиме Docker Swarm

В режиме Swarm рекомендуется использовать `dockerswarm_sd_config`. Это позволяет автоматически обнаруживать все узлы кластера и собирать метрики с каждого демона Docker.

*   **Метрики Swarm:** Состояние сервисов, количество реплик (`desired`/`running`).
*   **Discovery:** Prometheus подключается к менеджеру и получает список всех рабочих узлов (workers/managers).

### 5. Визуализация в Grafana

Для нативных метрик Docker Engine рекомендуется использовать стандартные дашборды из Grafana Cloud:
*   **Dashboard ID: 1229** (Docker Engine Metrics) — CPU, RAM, активность контейнеров.
*   **Dashboard ID: 10619** (Docker Engine & Containerd) — расширенная статистика.

## Безопасность

*   **TLS для метрик:** В высокозащищенных средах эндпоинт метрик должен быть защищен TLS. Docker поддерживает это через те же сертификаты, что и для Docker API (`tlscacert`, `tlscert`, `tlskey`).
*   **Сетевое ограничение:** Используйте Firewall для ограничения доступа к порту `9323` только с IP-адресов серверов Prometheus.
*   **RBAC в Swarm:** В Swarm-режиме доступ к метрикам менеджеров должен быть строго ограничен, так как они содержат информацию о всей топологии кластера.

## Дополнительная информация

### Связанные темы
- **[Нативные метрики Docker (stats/df)](./docker_native_metrics.md)** — быстрая диагностика без Prometheus.
- **[cAdvisor (Container Advisor)](../../Prometheus/Exporters/cadvisor.md)** — глубокий сбор метрик ресурсов контейнеров.
- **[Node Exporter](../../Prometheus/Exporters/node_exporter.md)** — мониторинг ресурсов хоста.
- **[Конфигурация Prometheus в Docker Stack](../../Prometheus/installation/docker_stack/prometheus_config.md)** — примеры `prometheus.yml`.
- **[Типы метрик Prometheus](../../Prometheus/concepts/metric_types/overview.md)** — понимание Counters, Gauges и Histograms.
