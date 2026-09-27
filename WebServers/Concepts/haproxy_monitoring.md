# Мониторинг HAProxy

## Определения

**Prometheus Native Exporter (PROMEX)** — встроенный модуль Prometheus-экспортёра, активируемый директивой `http-request use-service prometheus-exporter` и компилируемый с флагом `USE_PROMEX=1`.

**Runtime API** — UNIX-сокет `/var/lib/haproxy/admin.sock` для управления состоянием балансировщика в реальном времени без перезагрузки конфигурации.

**OpenTelemetry filter** — нативный фильтр HAProxy 3.4+ для отправки трейсов, метрик и логов в OTLP-совместимые коллекторы.

**Stick Table** — структура данных в оперативной памяти для хранения состояний (session persistence, rate limiting, защита от DDoS).

**Golden Signals** — четыре ключевых метрики: latency, traffic, errors, saturation.

**RED Method** — три ключевых метрики для HTTP-сервисов: rate, errors, duration.

**USE Method** — четыре ключевых метрики для ресурсов: utilization, saturation, errors.

---

## Основные концепции

### Встроенные метрики Prometheus (PROMEX)

PROMEX активируется директивой `http-request use-service prometheus-exporter` и доступен на эндпоинте `/metrics`.

**Ключевые метрики:**
- `haproxy_backend_up` — доступность бэкенда (0/1).
- `haproxy_backend_active_servers` — число активных серверов.
- `haproxy_backend_weight` — вес бэкенда.
- `haproxy_backend_current_connections` — число текущих соединений.
- `haproxy_frontend_requests_total` — общее число запросов.
- `haproxy_frontend_http_requests_total` — число HTTP-запросов.
- `haproxy_frontend_bytes_in_total` — число полученных байт.
- `haproxy_frontend_bytes_out_total` — число отправленных байт.
- `haproxy_frontend_current_connections` — число текущих соединений.
- `haproxy_frontend_connections_total` — общее число соединений.
- `haproxy_server_requests_total` — общее число запросов на сервер.
- `haproxy_server_current_connections` — число текущих соединений на сервер.
- `haproxy_server_bytes_in_total` — число полученных байт на сервер.
- `haproxy_server_bytes_out_total` — число отправленных байт на сервер.
- `haproxy_server_check_status` — статус health check (0/1).

### Runtime API

Runtime API управляет состоянием балансировщика в реальном времени через UNIX-сокет.

**Ключевые команды:**
- `show info` — общая информация о балансировщике.
- `show stat` — детальная статистика по frontend/backend/server.
- `show servers state` — состояние серверов.
- `show backend` — конфигурация бэкенда.
- `show frontend` — конфигурация фронтенда.
- `set server <backend>/<server> state <up|down|maint|drain>` — изменение состояния сервера.
- `set server <backend>/<server> weight <N>` — изменение веса сервера.
- `add acl <name> <value>` — добавление значения в ACL.
- `clear acl <name> <value>` — удаление значения из ACL.

### OpenTelemetry filter

OpenTelemetry filter отправляет трейсы, метрики и логи в OTLP-совместимые коллекторы.

**Ключевые параметры:**
- `otlp-traces` — отправка трейсов.
- `otlp-metrics` — отправка метрик.
- `otlp-logs` — отправка логов.
- `service.name` — имя сервиса.
- `service.version` — версия сервиса.

---

## Практические сценарии

### Сценарий 1: Настройка PROMEX

```haproxy
global
    log /dev/log local0 debug
    log-tag haproxy
    daemon
    master-worker
    maxconn 4096
    nbthread 4
    cpu-map auto:1/1-4 0-3

defaults
    log global
    mode http
    option httplog
    timeout connect 5s
    timeout client 50s
    timeout server 50s

frontend http_frontend
    bind *:80
    mode http
    http-request use-service prometheus-exporter if { path /metrics }
    default_backend http_backend

backend http_backend
    mode http
    balance roundrobin
    option forwardfor
    server web01 192.168.1.10:8080 check
    server web02 192.168.1.11:8080 check
```

**Ключевые моменты:**
- `http-request use-service prometheus-exporter if { path /metrics }` — активация PROMEX.
- `/metrics` — эндпоинт для Prometheus.
- Доступ к `/metrics` должен быть ограничен внутренней сетью.

### Сценарий 2: Настройка Runtime API

```bash
# Включение Runtime API в HAProxy
echo "show info" | socat stdio /var/lib/haproxy/admin.sock
# → MemAlloc, MaxMemory, ...

# Просмотр статистики
echo "show stat" | socat stdio /var/lib/haproxy/admin.sock
# → CSV с детальной статистикой

# Изменение состояния сервера
echo "set server http_backend/web01 state drain" | socat stdio /var/lib/haproxy/admin.sock
# → сервер переходит в режим drain

# Изменение веса сервера
echo "set server http_backend/web01 weight 50" | socat stdio /var/lib/haproxy/admin.sock
# → вес сервера изменен на 50
```

**Ключевые моменты:**
- Runtime API доступен через UNIX-сокет `/var/lib/haproxy/admin.sock`.
- Для доступа к сокету требуются права `user haproxy`.
- В production ограничьте доступ к сокету через `chmod 660`.

### Сценарий 3: Настройка OpenTelemetry filter

```haproxy
global
    log /dev/log local0 debug
    log-tag haproxy
    daemon
    master-worker
    maxconn 4096
    nbthread 4
    cpu-map auto:1/1-4 0-3

    # OpenTelemetry
    otel-trace /var/lib/haproxy/otel.sock service.name=haproxy service.version=1.0
    otel-metric /var/lib/haproxy/otel.sock service.name=haproxy service.version=1.0

defaults
    log global
    mode http
    option httplog
    timeout connect 5s
    timeout client 50s
    timeout server 50s

frontend http_frontend
    bind *:80
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance roundrobin
    option forwardfor
    server web01 192.168.1.10:8080 check
    server web02 192.168.1.11:8080 check
```

**Ключевые моменты:**
- `otel-trace` и `otel-metric` активируют OpenTelemetry.
- `/var/lib/haproxy/otel.sock` — UNIX-сокет для OpenTelemetry.
- OpenTelemetry доступен в HAProxy 3.4+.

### Сценарий 4: Мониторинг через Grafana

```bash
# Установка HAProxy Exporter
git clone https://github.com/prometheus/haproxy_exporter.git
cd haproxy_exporter
go build

# Запуск экспортера
./haproxy_exporter --haproxy.master-worker --haproxy.scrape-uri=unix:/var/lib/haproxy/admin.sock
```

**Grafana Dashboard:**
- ID: 2582 (HAProxy Stats).
- Визуализация: соединения, запросы, ошибки, latency.

### Сценарий 5: Алерты Prometheus

```yaml
groups:
  - name: haproxy_alerts
    rules:
      - alert: HAProxyBackendDown
        expr: haproxy_backend_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Backend {{ $labels.backend }} is down"
          description: "Backend {{ $labels.backend }} has been down for more than 1 minute"

      - alert: HAProxyHighErrorRate
        expr: rate(haproxy_frontend_http_requests_total{status=~"5.."}[5m]) / rate(haproxy_frontend_http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.frontend }}"
          description: "Error rate is {{ $value | humanizePercentage }} on {{ $labels.frontend }}"

      - alert: HAProxyHighLatency
        expr: histogram_quantile(0.95, rate(haproxy_frontend_request_duration_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High latency on {{ $labels.frontend }}"
          description: "95th percentile latency is {{ $value }}s on {{ $labels.frontend }}"

      - alert: HAProxyNoAvailableServers
        expr: haproxy_backend_active_servers == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "No available servers in {{ $labels.backend }}"
          description: "Backend {{ $labels.backend }} has no available servers"
```

### Сценарий 6: Сбор логов в Loki

```bash
# Установка Promtail
wget https://github.com/grafana/loki/releases/download/v3.0.0/promtail-linux-amd64.zip
unzip promtail-linux-amd64.zip

# Конфигурация Promtail
cat > /etc/promtail/config.yml <<EOF
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: haproxy
    static_configs:
      - targets:
          - localhost
        labels:
          job: haproxy
          __path__: /var/log/haproxy.log
EOF

# Запуск Promtail
promtail -config.file=/etc/promtail/config.yml
```

### Сценарий 7: Использование Stick Table для мониторинга

```haproxy
backend http_backend
    mode http
    balance roundrobin

    # Stick table для отслеживания запросов
    stick-table type ip size 100k expire 1m store http_req_rate(10s)

    # Отслеживание запросов по IP
    http-request track-sc src table http_backend

    # Алерт при превышении 10 запросов в секунду
    http-request deny if { sc_http_req_rate(10s) gt 10 }

    server web01 192.168.1.10:8080 check
    server web02 192.168.1.11:8080 check
```

**Ключевые моменты:**
- `stick-table` хранит счетчики.
- `http-request track-sc` отслеживает запросы.
- `sc_http_req_rate(10s)` — скорость за последние 10 секунд.
- `http-request deny` — отклонение запроса с кодом 403.

---

## Дополнительная информация

### Чек-лист настройки мониторинга HAProxy

- [ ] **PROMEX:** активирован на `/metrics`, доступ ограничен внутренней сетью.
- [ ] **Runtime API:** доступ через UNIX-сокет, права `user haproxy`.
- [ ] **OpenTelemetry:** активирован, трейсы отправляются в OTLP-коллектор.
- [ ] **Prometheus:** экспорт метрик, алерты на ошибки, latency, доступность бэкендов.
- [ ] **Grafana:** дашборд с ключевыми метриками (соединения, запросы, ошибки, latency).
- [ ] **Логи:** сбор в Loki/ELK, алерты на ошибки TLS, 5xx.
- [ ] **Сертификаты:** алерты на истечение срока действия TLS-сертификатов.

### См. также

- **[HAProxy Overview](../haproxy_overview.md) — архитектура HAProxy, алгоритмы, наблюдаемость.
- **[Наблюдаемость HTTP-сервисов](../../Networking/Protocols/HTTP/http_monitoring_observability.md) — RED method, Golden Signals.
- **[Сбор логов в Loki](../../Monitoring/Logging/loki_overview.md) — архитектура Loki.
- **[Prometheus](../../Monitoring/Metrics/prometheus_overview.md) — основы Prometheus.
- **[Grafana](../../Monitoring/Visualization/grafana_overview.md) — визуализация метрик.
- **[OpenTelemetry](../../Monitoring/Observability/opentelemetry_overview.md) — основы OpenTelemetry.
- **[HAProxy Documentation](https://www.haproxy.org/doc/3.4/configuration.html)** — официальная документация HAProxy.
- **[HAProxy PROMEX](https://www.haproxy.org/doc/3.4/configuration.html#promex)** — документация PROMEX.
- **[HAProxy Runtime API](https://www.haproxy.org/doc/3.4/configuration.html#runtime)** — документация Runtime API.
