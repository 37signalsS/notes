# Интеграция Docker с Prometheus

**Актуально для:** Docker Engine 20.10+, Prometheus 3.x

## Определения

**Docker Engine Metrics** — встроенный экспортер метрик демона Docker в формате Prometheus, доступный на порту `9323`. Экспортирует стандартный Prometheus-реестр демона (префиксы `engine_daemon_`, `builder_`, `logger_`, `swarm_`, `go_`, `process_`): информацию о движке, счётчики действий, состояния контейнеров, health-check'и, метрики сборки, логирования и Swarm. Per-container метрики не предоставляет — для них нужен cAdvisor. Полный перечень метрик: [Справочник метрик Docker Engine](./docker_engine_metrics_reference.md).

**Примечание:** Эндпоинт `9323` обслуживает стандартный Prometheus-реестр демона: `engine_daemon_*`, `builder_*`, `logger_*`, `swarm_*` (при Swarm) и Go-runtime метрики (`go_*`, `process_*`). Per-container метрики и метрики BuildKit-даемона/containerd на этом эндпоинте не экспортируются — для них используются cAdvisor и собственные эндпоинты `buildkitd` и containerd. Полный перечень: [Справочник метрик Docker Engine](./docker_engine_metrics_reference.md).

**docker_sd_config** — механизм Service Discovery Prometheus для автоматического обнаружения контейнеров через Docker Engine API. Требует доступ к Docker socket.

**dockerswarm_sd_config** — механизм Service Discovery Prometheus для автоматического обнаружения узлов, задач и сервисов в кластере Docker Swarm.

**metric_relabel_configs** — набор правил Prometheus для фильтрации, переименования и отсечения метрик перед записью в TSDB. Используется для снижения кардинальности и удаления инфраструктурных метрик.

## Предварительные требования

- **Docker Engine:** 20.10 или выше (рекомендуется 24.0+)
- **Prometheus:** 3.x (актуальная версия на 2026 год)
- **Доступ:** Docker socket (`/var/run/docker.sock`) или TCP API (2375/2376 с TLS)
- **Сеть:** Порты `9323` (метрики демона) и `8080` (cAdvisor) должны быть доступны для Prometheus
- **Безопасность:** В production используйте TLS или Unix socket с ограниченными правами (`chmod 660`, группа `docker`)

## Практические сценарии

### 1. Включение Docker Engine Metrics

Начиная с Docker 20.10, параметр `metrics-addr` работает без включения `experimental`. Флаг `experimental` не добавляет на порт 9323 метрик BuildKit или containerd — включайте его только если требуются экспериментальные функции демона.

**Настройка (`/etc/docker/daemon.json`):**

```json
{
  "metrics-addr": "127.0.0.1:9323"
}
```

*   `metrics-addr`: адрес прослушивания. Для production используйте `127.0.0.1` или закрытую сеть. `0.0.0.0` допустим только в изолированных сегментах.
*   `experimental`: не требуется для базовых метрик демона. Включайте только при необходимости BuildKit/containerd метрик.

**Перезапуск и проверка:**

```bash
sudo systemctl restart docker
curl -s http://localhost:9323/metrics | grep engine_daemon
# → HELP engine_daemon_engine_info ...
# → TYPE engine_daemon_engine_info gauge
```

### 2. Что экспортирует эндпоинт 9323

Эндпоинт обслуживает стандартный Prometheus-реестр демона (`engine_daemon_*`, `builder_*`, `logger_*`, `swarm_*`, `go_*`, `process_*`). Согласно документации Docker: «Currently, you can only monitor Docker itself. You can't currently monitor your application using the Docker target».

- **Per-container метрики** (CPU, RAM, Network, I/O) — через **[cAdvisor](./docker_cadvisor_deployment.md)**.
- **Метрики BuildKit-даемона** — через собственный эндпоинт `buildkitd` (отдельный процесс), не через порт 9323. Метрики сборки демона (`builder_builds_triggered_total`, `builder_builds_failed_total`) на 9323 есть.
- **Метрики containerd** — через собственный эндпоинт containerd, не через порт 9323.

*Примечание:* Флаг `experimental: true` в `daemon.json` включает экспериментальные функции демона, но не добавляет метрик BuildKit/containerd на порт 9323. Не включайте его без необходимости.

### 3. Статическая конфигурация Prometheus

Подходит для фиксированного количества хостов.

```yaml
scrape_configs:
  - job_name: 'docker-engine'
    static_configs:
      - targets: ['192.168.1.10:9323']
    metrics_path: /metrics
    scrape_interval: 15s
```

*   `scrape_interval`: для production используйте `15s` или `30s`. Интервал `1s` создает избыточную нагрузку на TSDB.
*   `metrics_path`: по умолчанию `/metrics`.

### 4. Динамическое обнаружение: docker_sd_config

Использование `docker_sd_config` позволяет Prometheus автоматически обнаруживать контейнеры через Docker Engine API.

**Вариант А: Unix socket (рекомендуется)**

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      - source_labels: [__meta_docker_container_label_prometheus_enable]
        regex: 'true'
        action: keep
      - source_labels: [__meta_docker_container_name]
        target_label: container
        replacement: '${1}'
```

**Вариант Б: TCP сокет с TLS**

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: tcp://docker-host:2376
        tls_config:
          ca_file: /etc/prometheus/ca.pem
          cert_file: /etc/prometheus/client.pem
          key_file: /etc/prometheus/client-key.pem
    relabel_configs:
      - source_labels: [__meta_docker_container_label_prometheus_enable]
        regex: 'true'
        action: keep
```

**Важные метки `__meta_docker_*`:**
- `__meta_docker_container_name` — имя контейнера
- `__meta_docker_container_label_<name>` — метки контейнера
- `__meta_docker_network_name` — имя сети
- `__meta_docker_swarm_service_name` — имя сервиса (только в Swarm)

### 5. Docker Swarm: dockerswarm_sd_config

В режиме Swarm используйте `dockerswarm_sd_config` для автоматического обнаружения всех узлов кластера и сбора метрик с каждого демона Docker.

```yaml
scrape_configs:
  - job_name: 'swarm-nodes'
    dockerswarm_sd_configs:
      - host: unix:///var/run/docker.sock
        role: nodes
    relabel_configs:
      - source_labels: [__meta_dockerswarm_node_label_monitor]
        regex: 'true'
        action: keep
```

**Роли для `dockerswarm_sd_configs`:**
- `nodes` — узлы кластера (менеджеры и воркеры)
- `services` — сервисы Swarm
- `tasks` — задачи (запущенные контейнеры сервисов)
- `networks` — сети Swarm

### 6. Снижение кардинальности: metric_relabel_configs

Сбор метрик со всех контейнеров может создавать высокую кардинальность в Prometheus TSDB. Используйте `metric_relabel_configs` для отсечения инфраструктурных метрик.

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    metric_relabel_configs:
      # Отбросить метрики без имени контейнера
      - source_labels: [container_name]
        regex: '^$'
        action: drop
      # Отбросить инфраструктурные сети
      - source_labels: [network_name]
        regex: 'bridge|host|none|container'
        action: drop
      # Оставить только используемые метрики
      - regex: 'container_(cpu|memory|network|blkio)_.*'
        action: keep
```

### 7. Production-конфигурация

Полный пример `prometheus.yml` для production-среды:

```yaml
global:
  scrape_interval: 30s
  evaluation_interval: 30s
  external_labels:
    cluster: 'docker-prod-01'
    datacenter: 'dc-east'

scrape_configs:
  - job_name: 'docker-engine'
    static_configs:
      - targets: ['localhost:9323']
    metrics_path: /metrics
    scrape_interval: 30s

  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      - source_labels: [__meta_docker_container_label_prometheus_enable]
        regex: 'true'
        action: keep
      - source_labels: [__meta_docker_container_name]
        target_label: container
        replacement: '${1}'
      - source_labels: [__meta_docker_container_label_env]
        target_label: env
    metric_relabel_configs:
      - source_labels: [container_name]
        regex: '^$'
        action: drop
      - source_labels: [network_name]
        regex: 'bridge|host|none|container'
        action: drop
```

### 8. Безопасность

- **TLS для метрик:** Эндпоинт `9323` — plain HTTP, встроенной поддержки TLS нет. В high-security средах ставьте перед ним TLS-терминирующий reverse proxy (nginx/Caddy) или используйте SSH-tunnel. Сертификаты Docker API (`tlscacert`, `tlscert`, `tlskey`) защищают сам API (порт 2376), но не эндпоинт метрик.

**TLS-терминация через nginx (пример):**

```nginx
# /etc/nginx/conf.d/docker-metrics.conf
server {
    listen 9324 ssl;
    ssl_certificate     /etc/nginx/certs/metrics.crt;
    ssl_certificate_key /etc/nginx/certs/metrics.key;
    allow 10.0.0.0/24;   # сеть Prometheus
    deny all;
    location /metrics {
        proxy_pass http://127.0.0.1:9323;
    }
}
```

```yaml
# prometheus.yml — скрейп через TLS-прокси
scrape_configs:
  - job_name: 'docker-engine'
    static_configs:
      - targets: ['docker-host:9324']
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/ca.pem
```

- **Сетевое ограничение:** Firewall должен разрешать порт `9323` только с IP-адресов Prometheus серверов.
- **Права на socket:** Unix socket `/var/run/docker.sock` должен иметь права `660` и принадлежать группе `docker`. Prometheus должен быть членом этой группы.
- **RBAC в Swarm:** В Swarm-режиме доступ к метрикам менеджеров содержит информацию о всей топологии кластера. Ограничьте доступ через Swarm RBAC и network encryption.

### 9. Маршрутизация Docker-алертов через Alertmanager

Алерты Prometheus (см. [Справочник метрик Docker Engine](./docker_engine_metrics_reference.md) и [cAdvisor](../../Prometheus/Exporters/cadvisor.md)) маршрутизируются через Alertmanager: группировка, inhibition, silencing. Пример маршрутизации для Docker-стека:

```yaml
# alertmanager.yml
route:
  receiver: 'default'
  group_by: ['alertname', 'cluster', 'instance']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    # Docker-алерты: группировать по хосту, не спамить при массовом OOM
    - match:
        alertname: ContainerOomKilled
      receiver: 'pager'
      group_by: ['instance']
      group_wait: 1m
      repeat_interval: 1h
    # Падение демона Docker — критично, повтор каждые 5 минут
    - match:
        alertname: DockerEngineDown
      receiver: 'pager'
      repeat_interval: 5m
    # Предупреждения — дежурный канал, не pager
    - match:
        severity: warning
      receiver: 'slack'

receivers:
  - name: 'default'
  - name: 'pager'
  - name: 'slack'

# Silence для плановых работ: docker node drain
# curl -X POST http://alertmanager:9093/api/v2/silences -d '{
#   "matchers": [{"name": "instance", "value": "docker-host-01", "isRegex": false}],
#   "startsAt": "2026-10-04T20:00:00Z", "endsAt": "2026-10-04T22:00:00Z",
#   "createdBy": "sre", "comment": "planned node maintenance"
# }'
```

Полный справочник Alertmanager (grouping, inhibition, silencing, API v2): [Alertmanager](../../Prometheus/alertmanager.md). Docker Compose-конфигурация Alertmanager: [Конфигурация Alertmanager для Docker Compose](../../Prometheus/installation/docker_stack/docker_compose_alertmanager_config.md).

### 10. Capacity planning для Docker-метрик

Оценка нагрузки на Prometheus от Docker-мониторинга перед развёртыванием:

**Оценка active series:**
- cAdvisor: ~50–100 серий на контейнер (зависит от подсистем: cpu, memory, network, diskIO, process, sched).
- Engine Metrics: ~10–20 серий на хост.
- Node Exporter: ~1–3K серий на хост.

**Формулы Prometheus** (полный справочник: [Capacity Planning](../../Prometheus/installation/capacity_planning.md)):

```
RAM (MB) = 2000 + (active_series × 8)
Disk (GB) = (active_series × bytes_per_sample × samples_per_day × retention_days) / 10^9
CPU (cores) = 2 + (0.0005 × active_series)
```

**Пример: 10 хостов × 50 контейнеров × 80 серий = 40K серий:**

```
RAM  = 2000 + 40000 × 8        ≈ 320 MB → рекомендация 4 GB (с headroom)
Disk = 40000 × 1.5 × 5760 × 30 / 10^9 ≈ 10.4 GB при scrape_interval 15s, retention 30d
```

**Практики:**
- `scrape_interval: 30s` для Engine Metrics и Node Exporter, `10–15s` для cAdvisor — экономит ~50% диска vs 15s везде.
- `metric_relabel_configs` (сценарий 6) снижает кардинальность на 40–60%.
- `--storage.tsdb.retention.size=10GB` — защита от переполнения диска (вместо/вместе с retention.time).
- Для оценки cardinality «на живую» используйте `curl -s http://prometheus:9090/api/v1/status/tsdb | jq '.data.headStats.numSeries'`.

### 11. Сбор метрик через OpenTelemetry Collector

Альтернатива Prometheus-стеку в OTel-инфраструктуре. OTel Collector (дистрибуция contrib) предоставляет два релевантных receiver'а:

**dockerstats receiver** — опрашивает API `/containers/<id>/stats` (Docker API 1.25+), метрики: `container.cpu.usage.total`, `container.cpu.utilization`, `container.memory.*`, `container.network.io.*`, `container.blkio.*`. Стабильность: alpha.

**hostmetrics receiver** — метрики хоста (cpu, disk, load, filesystem, memory, network, processes) — аналог Node Exporter.

```yaml
# config.yaml OTel Collector (contrib)
receivers:
  docker_stats:
    endpoint: unix:///var/run/docker.sock
    collection_interval: 10s
    timeout: 5s
    container_labels_to_metric_labels:
      com.docker.compose.service: service
      env: env
    excluded_images:
      - cadvisor
      - prometheus
  host_metrics:
    collection_interval: 30s
    scrapers:
      cpu:
      memory:
      disk:
      filesystem:
      network:

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  batch:
    timeout: 10s

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"   # обратная совместимость: отдаёт метрики в Prometheus-формате
  otlp:
    endpoint: "otel-backend:4317"

service:
  pipelines:
    metrics:
      receivers: [docker_stats, host_metrics]
      processors: [memory_limiter, batch]
      exporters: [prometheus, otlp]
```

**Требования:** доступ к `/var/run/docker.sock` (монтирование в контейнер Collector), образ `otel/opentelemetry-collector-contrib`. Для сбора host-метрик из контейнера смонтируйте `/:/hostfs:ro` и задайте `host_metrics.root_path: /hostfs`. Деплой Collector в Docker Compose: [OpenTelemetry: Collector в не-Kubernetes средах](../../OpenTelemetry/collector_without_kubernetes.md).

### 12. Метрики Docker Swarm

`dockerswarm_sd_config` (сценарий 5) обеспечивает обнаружение узлов, но метрики самого Swarm (состояние нод, менеджеров, задач) в Prometheus-формате нативно не экспортируются. Паттерн — textfile collector Node Exporter:

```bash
# /etc/node_exporter/textfile_collector/swarm.prom (на manager-узле, по cron)
# → генерация метрик из docker node ls
docker node ls --format '{{.Hostname}} {{.Status}} {{.Availability}}' | while read host status avail; do
  echo "swarm_node_info{host=\"$host\",availability=\"$avail\"} 1"
  [ "$status" = "Ready" ] && echo "swarm_node_ready{host=\"$host\"} 1" || echo "swarm_node_ready{host=\"$host\"} 0"
done > /var/lib/node_exporter/textfile_collector/swarm.prom
```

```promql
# Число нод не в состоянии Ready
sum(swarm_node_ready) < count(swarm_node_ready)

# Задачи сервиса не в состоянии Running (через docker service ps + textfile)
```

Диагностика кворума и Raft: `docker node ls --filter role=manager`, `docker info --format '{{.Swarm.Cluster.RemoteManagers}}'` — подробнее в [Swarm: Продвинутые темы](../../Docker_swarm/swarm_advanced_topics.md).

### 13. Многохостовой мониторинг Docker

Для сбора метрик с N Docker-хостов центральным Prometheus:

- **Прямой доступ (pull):** cAdvisor и Engine Metrics на каждом хосте, `static_configs` или `file_sd_configs` со списком хостов. Требует открытых портов 8080/9323 для сети мониторинга.
- **За NAT / строгий firewall:** reverse SSH-tunnel или Prometheus Agent Mode + `remote_write` с каждого хоста.
- **Полное руководство** (топологии, mTLS, jump-host, WireGuard, Agent Mode): [Мониторинг удалённых хостов из Docker Stack](../../Prometheus/installation/docker_stack/remote_hosts_monitoring.md).

## Валидация

```bash
# Проверка доступности метрик демона
curl -s http://localhost:9323/metrics | head -20
# → engine_daemon_engine_info ...

# Проверка docker_sd_config
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="docker-containers")'
# → {"job":"docker-containers","instance":"...","health":"up"}

# Проверка метрик конкретного контейнера
curl -s 'http://localhost:9090/api/v1/query?query=container_cpu_usage_seconds_total' | jq '.data.result[].metric.container'

# Проверка кардинальности
curl -s http://localhost:9090/api/v1/status/tsdb | jq '.data.headStats.numSeries'
```

## Диагностика и устранение неполадок

1. **Порт 9323 закрыт**
   - **Причина:** `metrics-addr` не настроен или Docker не перезапущен.
   - **Решение:** Проверьте `daemon.json`, выполните `systemctl restart docker`, убедитесь что порт слушается: `ss -tlnp | grep 9323`.

2. **Отсутствуют метрики container_\***
   - **Причина:** cAdvisor не развернут или не добавлен в `scrape_configs`.
   - **Решение:** Docker Engine Metrics предоставляют только метрики демона и платформы (`engine_daemon_*`, `builder_*`, `logger_*`, `swarm_*`). Для per-container метрик необходим cAdvisor. См. [Деплой cAdvisor](./docker_cadvisor_deployment.md).

3. **docker_sd_config не обнаруживает контейнеры**
   - **Причина:** Нет доступа к Docker socket или контейнеры не имеют метки `prometheus_enable=true`.
   - **Решение:** Проверьте права на `/var/run/docker.sock`, добавьте метки к контейнерам: `docker run -l prometheus_enable=true ...`.

4. **Высокая кардинальность в TSDB**
   - **Причина:** Сбор метрик со всех контейнеров без фильтрации.
   - **Решение:** Добавьте `metric_relabel_configs` для отсечения пустых контейнеров и инфраструктурных сетей.

5. **Prometheus 3.x перестал скрейпить**
   - **Причина:** В Prometheus 3.x порт не угадывается автоматически. Если `__address__` не содержит порт, скрейпинг завершается ошибкой.
   - **Решение:** Явно укажите порт в `__address__` через relabeling или в статической конфигурации.

6. **OOM kill не фиксируется**
   - **Причина:** Docker Engine Metrics не включают OOM events в реальном времени.
   - **Решение:** Используйте `docker events --filter 'event=oom'` для оперативного алертинга или cAdvisor с метрикой `container_oom_events_total` (см. [cAdvisor](../../Prometheus/Exporters/cadvisor.md)).

7. **Троттлинг CPU не виден в метриках**
   - **Причина:** Docker Engine Metrics не экспортируют детали троттлинга.
   - **Решение:** Читайте `cpu.stat` напрямую из cgroup контейнера или используйте cAdvisor с метрикой `container_cpu_cfs_throttled_seconds_total`.

## Лучшие практики

- **Используйте `127.0.0.1:9323`** вместо `0.0.0.0` для `metrics-addr` в production. Проксируйте доступ через SSH tunnel или firewall.
- **Не включайте `experimental: true`** без необходимости. Он включает экспериментные функции демона, но не добавляет метрик на порт 9323.
- **Используйте `metric_relabel_configs`** для снижения кардинальности на 40-60%. Отсекайте пустые контейнеры и инфраструктурные сети.
- **Маркируйте контейнеры меткой** `prometheus_enable=true` вместо сбора метрик со всех контейнеров. Это снижает нагрузку и кардинальность.
- **Используйте Unix socket** вместо TCP для `docker_sd_config` wherever possible. TCP без TLS передает данные в открытом виде.
- **Настройте `scrape_interval: 30s`** для Docker Engine Metrics. Интервал 1s не нужен для демон-статистики и создает лишнюю нагрузку.
- **Мониторьте сам Prometheus** через его же метрики (`prometheus_tsdb_head_series`, `prometheus_rule_group_last_duration_seconds`). При деградации Prometheus теряет глаза на всю инфраструктуру.
- **Используйте `dockerswarm_sd_config`** в Swarm-средах вместо статического перечисления узлов. Это автоматически подхватывает новые воркеры.
- **Защищайте порт 9323** firewall или TLS-прокси (nginx/Caddy) — эндпоинт метрик plain HTTP, сертификаты Docker API его не защищают (см. сценарий 8).
- **Регулярно обновляйте Prometheus** (не реже квартала). Каждая версия исправляет утечки памяти в SD и relabeling.

## Дополнительная информация

Эффективный мониторинг контейнеризированной среды требует сбора данных на четырех уровнях:

1. **Docker Engine Metrics (этот файл):** агрегированная статистика демона (`engine_daemon_*`, `builder_*`, `logger_*`, `swarm_*`).
2. **cAdvisor:** детальные per-container метрики CPU, RAM, Network, I/O.
3. **Node Exporter:** метрики хоста (диски, сеть, системные службы).
4. **Приложение:** внутренние показатели бизнес-логики через Sidecar-экспортеры.

- **[Нативные метрики Docker (stats/cgroups)](./docker_native_metrics.md)** — SSoT: CLI `docker stats`, PSI, диагностика троттлинга, чтение cgroups напрямую.
- **[cAdvisor: развертывание и сбор метрик](./docker_cadvisor_deployment.md)** — деплой cAdvisor, `docker_sd_config`, конфигурация сбора и интеграция с Prometheus.
- **[Справочник метрик Docker Engine](./docker_engine_metrics_reference.md)** — полный перечень метрик порта 9323 с версиями и алертами.
- **[Grafana для Docker-метрик](./docker_grafana_dashboards.md)** — дашборды, провиженинг, алерты, корреляция метрик с логами.
- **[Docker метрики: вопросы на собеседованиях](./docker_metrics_interview_qa.md)** — краткие ответы на вопросы SRE-собеседований.
- **[Конфигурация Docker daemon](../docker_daemon_config.md)** — SSoT: полный справочник `daemon.json`, включая `metrics-addr`, `experimental`, `features.buildkit`.
- **[Docker Engine Metrics vs cAdvisor](../../Prometheus/Exporters/cadvisor.md)** — сравнение источников метрик, Grafana дашборды (ID 1229, 10619).
- **[Service Discovery и relabeling](../../Prometheus/service_discovery_and_relabeling.md)** — SSoT: полный справочник `docker_sd_configs`, `dockerswarm_sd_configs`, `relabel_configs`, особенности Prometheus 3.x.
- **[Alertmanager](../../Prometheus/alertmanager.md)** — маршрутизация, группировка, silencing алертов.
- **[Capacity Planning для Prometheus](../../Prometheus/installation/capacity_planning.md)** — формулы RAM/Disk/CPU, влияние scrape_interval.
- **[Мониторинг удалённых хостов](../../Prometheus/installation/docker_stack/remote_hosts_monitoring.md)** — многохостовой сбор метрик (топологии, mTLS, Agent Mode).
- **[OpenTelemetry: Collector в не-Kubernetes средах](../../OpenTelemetry/collector_without_kubernetes.md)** — деплой OTel Collector в Docker Compose.
- **[Node Exporter](../../Prometheus/Exporters/node_exporter.md)** — метрики хоста (диски, сеть, системные службы).
- **[Контрольные группы (cgroups)](../../Linux/Core/cgroups.md)** — теоретическая база механизмов ограничения ресурсов.

**См. также:**
- **[Prometheus конфигурация в Docker Stack](../../Prometheus/installation/docker_stack/prometheus_config.md)** — примеры `prometheus.yml`.
- **[Docker Stack мониторинга](../../Prometheus/installation/docker_stack/overview.md)** — полный стек мониторинга на Docker.
- **[Grafana Дашборды](../../Grafana/grafana-dashboards.md)** — визуализация метрик Docker Engine и cAdvisor.
