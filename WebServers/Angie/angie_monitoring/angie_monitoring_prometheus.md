# Мониторинг Angie — интеграция с Prometheus

**Актуально для:** Angie 1.12.x / Prometheus 2.x, 3.x

## Определения

**Нативный экспорт метрик (модуль `ngx_http_prometheus_module`)** — встроенный механизм Angie, позволяющий серверу самостоятельно формировать и отдавать данные телеметрии в форматах Prometheus Text format (версия 0.0.4) и OpenMetrics (версия 1.0.0). Работает без сторонних процессов и sidecar-экспортеров (`nginx-prometheus-exporter`).

**`prometheus_template`** — директива контекста `http` веб-сервера Angie, задающая правила трансляции внутренних структур разделяемой памяти и путей REST API (`/status/`) в имена метрик, метки (labels), типы (counter, gauge) и описания (help).

**`$p8s_value`** — специальная внутренняя системная переменная Angie, доступная внутри блока `prometheus_template`. Содержит числовое или строковое значение показателя, извлеченное по соответствующему пути API. При необходимости может трансформироваться через директиву `map`.

**`prometheus_all.conf`** — конфигурационный файл из базовой поставки Angie (каталог `/etc/angie/`), содержащий готовый шаблон `prometheus_template all { ... }`. Включает набор общеупотребимых метрик сервера: соединения, серверные зоны, апстримы, slab-память и резолверы DNS.

**OpenMetrics** — открытый стандарт передачи метрик, принятый в экосистеме CNCF и поддерживаемый Prometheus 2.x/3.x. Поддерживает строгую типизацию, единицы измерения (`unit`), описания (`help`) и передачу сэмплов с квантилями и бакетами гистограмм.

**Shared Memory Zones (Зоны разделяемой памяти)** — области RAM (`status_zone`, `metric_zone`, `zone`), доступные всем рабочим процессам (worker processes) Angie. Служат первоисточником данных для сбора метрик в реальном времени с нулевой блокировкой дискового ввода-вывода.

**Scrape (Скрейпинг)** — периодический опрос эндпоинта метрик веб-сервера сервером сбора данных (Prometheus или VictoriaMetrics) по протоколу HTTP/HTTPS с интервалом `scrape_interval`.

**SRE Golden Signals (Четыре золотых сигнала SRE)** — ключевые метрики надежности сервиса: Latency (задержка), Traffic (нагрузка/RPS), Errors (ошибки, процент 5xx/4xx) и Saturation (насыщение ресурсов: соединения, память slab-зон).

**PromQL** — язык аналитических запросов Prometheus, используемый для агрегации временных рядов, расчета скоростей изменений (`rate`), вычисления процентилей (`histogram_quantile`) и оценки условий алертинга.

**Recording Rules (Правила предвычисления)** — правила Prometheus, выполняющие фоновый расчет тяжелых PromQL-выражений по расписанию и сохраняющие результат как новый компактный временной ряд.

**Alerting Rules (Правила алертинга)** — правила Prometheus, непрерывно проверяющие пороговые условия и отправляющие уведомления о сбоях в компонент Alertmanager.

**File-based Service Discovery (`file_sd_configs`)** — механизм Prometheus для автоматического обнаружения и обновления списка опрашиваемых узлов инфраструктуры через локальные JSON/YAML-файлы без перезапуска демона Prometheus.

**Grafana Dashboard ID 20719** — официальный готовый дашборд для визуализации метрик Angie в Grafana, разработанный компанией «Веб-Сервер».

---

## Базовые концепции

### Архитектура нативного экспорта

В классической архитектуре с внешним экспортером (`nginx-prometheus-exporter`) сторонний процесс опрашивает текстовый `stub_status` или парсит JSON API, сериализует данные и отдает их Prometheus. Это создает дополнительный сетевой сокет, накладные расходы на контекстные переключения и лишнюю нагрузку на CPU при частых опросах.

В Angie экспорт реализован нативно через модуль `ngx_http_prometheus_module`:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              Angie Server                              │
│                                                                        │
│  ┌───────────────────────┐             ┌────────────────────────────┐  │
│  │ Shared Memory (RAM)   │             │   prometheus_template      │  │
│  │ ├─ status_zone        │             │   ├─ all (prometheus_all)  │  │
│  │ ├─ metric_zone        │────────────>│   └─ custom_templates      │  │
│  │ ├─ upstream zones     │             └─────────────┬──────────────┘  │
│  │ └─ slab / resolvers   │                           │                 │
│  └───────────────────────┘                           ▼                 │
│                                            ┌───────────────────┐       │
│                                            │  location = /p8s  │       │
│                                            │  prometheus all;  │       │
│                                            └─────────┬─────────┘       │
└──────────────────────────────────────────────────────┼─────────────────┘
                                                       │ HTTP GET /p8s
                                                       ▼
                                         ┌───────────────────────────┐
                                         │  Prometheus Server TSDB   │
                                         │  (Pull scrape: 15s)       │
                                         └───────────────────────────┘
```

1. **Запись в память:** Рабочие процессы (`worker processes`) атомарно инкрементируют счетчики и задержки в разделяемой памяти в фазе логирования запроса (`NGX_HTTP_LOG_PHASE`).
2. **Формирование потока:** При поступлении запроса от Prometheus на URL с директивой `prometheus <template>` модуль обходит дерево объектов в оперативной памяти согласно регулярным выражениям из `prometheus_template`.
3. **Генерация ответа:** Модуль напрямую форматирует текстовый поток OpenMetrics / Prometheus Text format в буфер сетевого сокета без промежуточной сериализации в JSON.

### Механика шаблонов `prometheus_template`

Шаблон описывается в контексте `http` и содержит правила отображения:

```nginx
prometheus_template <имя_шаблона> {
    '<имя_метрики>{<метка>="$1"}' <переменная>
        [path=<путь_сопоставления>]
        [type=counter|gauge]
        ['help=<текст_описания>'];
}
```

- **`<имя_метрики>`**: Имя временного ряда в Prometheus. Метки задаются в фигурных скобках `{...}`. В метках разрешено использовать статические строки, capture-группы (`$1`, `$2` из регулярного выражения `path`) и стандартные переменные Angie (например, `$angie_version`, `$server_addr`).
- **`<переменная>`**: Значение, которое подставляется в качестве сэмпла. Чаще всего используется системная переменная `$p8s_value`. Если переменная вычисляется в пустую строку (`""`), метрика не включается в вывод.
- **`path=<путь_сопоставления>`**:
  - `path=<точный_путь>` — точное совпадение с ключом внутреннего API (например, `path=/connections/accepted`).
  - `path=~<регулярное_выражение>` — сопоставление по регулярному выражению PCRE (например, `path=~^/http/server_zones/([^/]+)/requests/total$`). Захваченные группы становятся доступны как `$1`, `$2`.
  - `path=<путь_со_слэшем>/` — если путь оканчивается на слэш, значением метрики становится количество элементов в соответствующем объекте или массиве (например, количество активных зон).
- **`type=`**: Тип метрики (`counter` или `gauge`). Влияет на строку заголовка `# TYPE`.
- **`help=`**: Описание метрики для строки `# HELP`.

### Маппинг строковых состояний через `map`

Многие параметры во внутреннем API Angie имеют строковый тип (`up`, `down`, `unavailable`). Prometheus оперирует исключительно числами (float64). Для трансляции статусов используется связка директивы `map` и переменной `$p8s_value`:

```nginx
map $p8s_value $upstream_peer_state_code {
    up           1;
    unavailable  2;
    down         0;
    default      -1;
}

prometheus_template upstream_health {
    'angie_http_upstream_peer_status{upstream="$1",peer="$2"}' $upstream_peer_state_code
        path=~^/http/upstreams/([^/]+)/peers/([^/]+)/state$
        type=gauge
        'help=Operational state of the upstream peer: 1=up, 0=down, 2=unavailable';
}
```

### Жизненный цикл метрик

```
1. Конфигурация    -> Компиляция правил prometheus_template в память при старте/reload
2. Трафик          -> Воркеры фиксируют события в shared memory (status_zone, metric_zone)
3. Опрос (Scrape)  -> Prometheus отправляет HTTP GET /p8s с заголовком Accept: application/openmetrics-text
4. Генерация       -> ngx_http_prometheus_module строит OpenMetrics-ответ из RAM за 1-5 мс
5. Сохранение      -> Prometheus валидирует сэмплы, сохраняет в WAL и индексирует в TSDB
6. Агрегация       -> Recording/Alerting rules вычисляют производные PromQL и триггерят алерты
```

---

## Практические сценарии

### Сценарий 1: Базовая настройка нативного экспорта (шаблон `all`)

Настройка веб-сервера для сбора стандартных метрик через файл `prometheus_all.conf` на выделенном интерфейсе управления.

```nginx
# /etc/angie/angie.conf

user angie;
worker_processes auto;
error_log /var/log/angie/error.log warn;
pid /run/angie.pid;

events {
    worker_connections 4096;
    use epoll;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;

    # 1. Загрузка стандартных определений метрик (шаблон 'all')
    include /etc/angie/prometheus_all.conf;

    # 2. Обязательное включение status_zone для сбора метрик по виртуальным хостам
    server {
        listen 80;
        server_name app.example.internal;

        status_zone app_production;

        location / {
            proxy_pass http://app_backends;
        }
    }

    upstream app_backends {
        zone app_backends 512k;
        server 192.168.10.11:8080 max_fails=3 fail_timeout=10s;
        server 192.168.10.12:8080 max_fails=3 fail_timeout=10s;
    }

    # 3. Выделенный сервер телеметрии на loopback/management IP
    server {
        listen 127.0.0.1:9113;
        listen 10.100.0.15:9113; # Внутренний IP ноды
        server_name _;

        # Отключение логирования скрейп-запросов, чтобы не забивать access.log
        access_log off;

        location = /p8s {
            # Активация набора метрик 'all'
            prometheus all;

            # Ограничение доступа к метрикам
            allow 127.0.0.1;
            allow 10.100.0.50; # IP-адрес Prometheus сервера
            deny all;
        }
    }
}
```

### Сценарий 2: Защита эндпоинта метрик через Basic Auth и TLS (mTLS)

В корпоративных средах без выделенного Management VLAN эндпоинт метрик защищается с помощью взаимной аутентификации TLS (mTLS) или Basic Authentication.

```nginx
# Защита эндпоинта через HTTP Basic Auth и mTLS
server {
    listen 9443 ssl;
    server_name metrics.node01.internal;

    ssl_certificate /etc/angie/ssl/metrics.crt;
    ssl_certificate_key /etc/angie/ssl/metrics.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # mTLS: проверка сертификата сервера Prometheus
    ssl_client_certificate /etc/angie/ssl/prometheus_ca.crt;
    ssl_verify_client on;

    location = /metrics {
        prometheus all;

        # Дополнительная авторизация по паролю
        auth_basic "Prometheus Scrape Protected";
        auth_basic_user_file /etc/angie/.htpasswd_prometheus;
    }
}
```

Конфигурация скрейпинга в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "angie-mtls"
    scheme: https
    metrics_path: "/metrics"
    basic_auth:
      username: "prometheus-scraper"
      password_file: "/etc/prometheus/secrets/angie_scrape_password"
    tls_config:
      ca_file: "/etc/prometheus/certs/ca.crt"
      cert_file: "/etc/prometheus/certs/prom-client.crt"
      key_file: "/etc/prometheus/certs/prom-client.key"
      insecure_skip_verify: false
    static_configs:
      - targets: ["metrics.node01.internal:9443"]
```

### Сценарий 3: Пользовательские метрики и гистограммы задержек

Связка `metric_zone` с пользовательским шаблоном `prometheus_template` для экспорта персентилей задержек бэкендов в формате Prometheus Histogram.

```nginx
http {
    include /etc/angie/prometheus_all.conf;

    # 1. Зона гистограммы времени отклика бэкендов (бакеты в секундах)
    metric_zone backend_latency:8m histogram 0.01 0.05 0.1 0.25 0.5 1.0 2.5 5.0
        expire=on discard_key=expired;

    # 2. Зона для подсчета кодов бизнес-событий (например, чекаут)
    metric_zone checkout_events:4m count expire=on;

    # 3. Пользовательский шаблон для экспорта
    prometheus_template custom_business_telemetry {
        # Экспорт бакетов гистограммы задержки
        'angie_upstream_latency_seconds_bucket{service="$1",le="$2"}' $p8s_value
            path=~^/http/metric_zones/backend_latency/metrics/([^/]+)/histogram/([^/]+)$
            type=counter
            'help=Upstream latency response time histogram buckets in seconds';

        # Экспорт счетчиков бизнес-операций
        'angie_business_checkout_total{status="$1"}' $p8s_value
            path=~^/http/metric_zones/checkout_events/metrics/([^/]+)$
            type=counter
            'help=Total count of business checkout operations by result status';
    }

    server {
        listen 80;
        server_name api.example.internal;

        status_zone api_gateway;

        location /api/v1/checkout {
            proxy_pass http://checkout_pool;

            # Фиксация времени отклика в гистограмме
            metric backend_latency checkout_service=$upstream_response_time on=end;

            # Фиксация бизнес-статуса из заголовка ответа бэкенда
            metric checkout_events $upstream_http_x_order_status on=end;
        }

        location = /p8s {
            # Одновременная отдача стандартных и кастомных метрик
            prometheus all custom_business_telemetry;

            allow 127.0.0.1;
            allow 10.100.0.50;
            deny all;
        }
    }
}
```

### Сценарий 4: Конфигурация Prometheus с File-based Service Discovery (`file_sd`)

Для bare-metal и виртуальных инфраструктур без облачных провайдеров наилучшим решением является файловый механизм обнаружения узлов (`file_sd_configs`). Это позволяет изменять список веб-серверов скриптами автоматизации (Ansible, bash) без перезагрузки Prometheus.

```yaml
# /etc/prometheus/prometheus.yml

global:
  scrape_interval: 15s
  scrape_timeout: 10s
  evaluation_interval: 15s

rule_files:
  - "/etc/prometheus/rules/angie_recording.yml"
  - "/etc/prometheus/rules/angie_alerts.yml"

scrape_configs:
  - job_name: "angie-cluster"
    metrics_path: "/p8s"
    scheme: "http"

    file_sd_configs:
      - files:
          - "/etc/prometheus/targets/angie_nodes/*.json"
        refresh_interval: 30s

    # Фильтрация и стандартизация меток на стороне Prometheus
    metric_relabel_configs:
      # Исключение неиспользуемых метрик slab-слотов для снижения кардинальности TSDB
      - source_labels: [__name__]
        regex: "angie_slabs_pages_slots_(reqs|fails)"
        action: drop

      # Нормализация метки зоны
      - source_labels: [zone]
        target_label: environment
        regex: ".*_prod.*"
        replacement: "production"
```

Пример файла целей `/etc/prometheus/targets/angie_nodes/web_servers.json`:

```json
[
  {
    "targets": [
      "10.100.0.11:9113",
      "10.100.0.12:9113",
      "10.100.0.13:9113"
    ],
    "labels": {
      "datacenter": "dc1",
      "role": "frontend-proxy",
      "cluster": "prod-web"
    }
  }
]
```

### Сценарий 5: Recording Rules для SRE Golden Signals

Предвычисление ключевых характеристик в фоновом режиме снижает нагрузку на Prometheus TSDB при отрисовке нагруженных дашбордов Grafana.

```yaml
# /etc/prometheus/rules/angie_recording.yml

groups:
  - name: angie.golden_signals
    interval: 15s
    rules:
      # 1. Traffic: суммарный RPS по зонам виртуальных хостов
      - record: angie:server_zone_requests:rate5m
        expr: sum by (instance, zone) (rate(angie_http_server_zones_requests_total[5m]))

      # 2. Errors: процент ответов 5xx по отношению к общему объему запросов
      - record: angie:server_zone_errors_5xx:ratio5m
        expr: >
          sum by (instance, zone) (rate(angie_http_server_zones_responses_total{status=~"5.."}[5m]))
          /
          sum by (instance, zone) (rate(angie_http_server_zones_requests_total[5m]))

      # 3. Latency: 95-й персентиль времени отклика бэкендов
      - record: angie:upstream_latency_p95:seconds5m
        expr: >
          histogram_quantile(0.95, sum by (le, instance, service) (rate(angie_upstream_latency_seconds_bucket[5m])))

      # 4. Latency: 99-й персентиль времени отклика бэкендов
      - record: angie:upstream_latency_p99:seconds5m
        expr: >
          histogram_quantile(0.99, sum by (le, instance, service) (rate(angie_upstream_latency_seconds_bucket[5m])))

      # 5. Saturation: утилизация свободных страниц в slab-зонах памяти
      - record: angie:slab_memory_used:ratio
        expr: >
          angie_slabs_pages_used
          /
          (angie_slabs_pages_used + angie_slabs_pages_free)
```

### Сценарий 6: Alerting Rules для Alertmanager

Готовые правила мониторинга критических состояний веб-сервера.

```yaml
# /etc/prometheus/rules/angie_alerts.yml

groups:
  - name: angie.alerts
    rules:
      - alert: AngieInstanceDown
        expr: up{job="angie-cluster"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Веб-сервер Angie недоступен на {{ $labels.instance }}"
          description: "Prometheus не может получить метрики с эндпоинта {{ $labels.instance }}/p8s более 1 минуты."

      - alert: AngieHighErrorRate5xx
        expr: angie:server_zone_errors_5xx:ratio5m > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Высокая доля ошибок 5xx на зоне {{ $labels.zone }}"
          description: "Уровень серверных ошибок 5xx на узле {{ $labels.instance }} составляет {{ $value | humanizePercentage }} (порог 5%) в течение 2 минут."

      - alert: AngieHighLatencyP95
        expr: angie:upstream_latency_p95:seconds5m > 1.0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "P95 задержка сервиса {{ $labels.service }} превысила 1 секунду"
          description: "95-й персентиль задержки бэкенда на {{ $labels.instance }} равен {{ $value | humanizeDuration }}."

      - alert: AngieUpstreamPeerDown
        expr: angie_http_upstreams_peers_state{state="down"} == 1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Бэкенд {{ $labels.peer }} в пуле {{ $labels.upstream }} отключен"
          description: "Сервер {{ $labels.peer }} перешел в состояние DOWN по результатам проверок доступности."

      - alert: AngieSlabMemoryNearExhaustion
        expr: angie:slab_memory_used:ratio > 0.90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Память slab-зоны {{ $labels.zone }} заполнена более чем на 90%"
          description: "Утилизация slab-памяти на {{ $labels.instance }} достигла {{ $value | humanizePercentage }}. Необходим пересчет лимитов зоны."
```

### Сценарий 7: Автоматизированное подключение официального дашборда Grafana 20719

В bare-metal окружениях дашборд подключается через механизм автоматического провижининга Grafana.

Конфигурационный файл провижининга `/etc/grafana/provisioning/dashboards/angie.yaml`:

```yaml
apiVersion: 1

providers:
  - name: "Angie Web Server"
    orgId: 1
    folder: "Web Infrastructure"
    type: file
    disableDeletion: false
    updateIntervalSeconds: 60
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards/angie
```

Загрузка дашборда через CLI:

```bash
# Создание каталога для дашборда
sudo mkdir -p /var/lib/grafana/dashboards/angie

# Загрузка последней ревизии официального дашборда ID 20719
sudo curl -sSL https://grafana.com/api/dashboards/20719/revisions/latest/download \
    -o /var/lib/grafana/dashboards/angie/angie_dashboard_20719.json

# Установка прав владельца
sudo chown -R grafana:grafana /var/lib/grafana/dashboards/angie

# Перезапуск службы Grafana
sudo systemctl restart grafana-server
# → ● grafana-server.service - Grafana instance
# →    Active: active (running)
```

---

## Операции и команды

### 1. Верификация эндпоинта экспорта Angie

```bash
# Проверка HTTP-заголовков и протокола ответа эндпоинта
curl -s -D - -o /dev/null http://127.0.0.1:9113/p8s
# → HTTP/1.1 200 OK
# → Server: Angie/1.12.3
# → Content-Type: application/openmetrics-text; version=1.0.0; charset=utf-8
# → Connection: close

# Просмотр первых строк выгрузки
curl -sf http://127.0.0.1:9113/p8s | head -n 12
# → # TYPE angie_connections_accepted counter
# → # HELP angie_connections_accepted The total number of accepted client connections.
# → angie_connections_accepted 1845920
# → # TYPE angie_connections_active gauge
# → # HELP angie_connections_active The current number of active client connections.
# → angie_connections_active 42
# → # TYPE angie_connections_idle gauge
# → # HELP angie_connections_idle The current number of idle client connections.
# → angie_connections_idle 15
# → # TYPE angie_connections_dropped counter
# → # HELP angie_connections_dropped The total number of dropped client connections.
# → angie_connections_dropped 0

# Подсчет количества уникальных метрик в экспорте
curl -s http://127.0.0.1:9113/p8s | grep -v '^#' | cut -d'{' -f1 | cut -d' ' -f1 | sort -u | wc -l
# → 28
```

### 2. Валидация метрик с помощью `promtool`

Утилита `promtool` из пакета Prometheus валидирует синтаксис OpenMetrics и структуру экспортируемых серий:

```bash
# Валидация потока метрик Angie через stdin
curl -sf http://127.0.0.1:9113/p8s | promtool check metrics
# → Checking /dev/stdin
# → SUCCESS: 28 metric types found, 142 total series validated

# Валидация синтаксиса конфигурации Prometheus
promtool check config /etc/prometheus/prometheus.yml
# → Checking /etc/prometheus/prometheus.yml
# →   SUCCESS: 2 rule files found
# →  SUCCESS: /etc/prometheus/prometheus.yml syntax OK

# Валидация файлов правил PromQL
promtool check rules /etc/prometheus/rules/angie_recording.yml /etc/prometheus/rules/angie_alerts.yml
# → Checking /etc/prometheus/rules/angie_recording.yml
# →   SUCCESS: 5 rules found
# → Checking /etc/prometheus/rules/angie_alerts.yml
# →   SUCCESS: 5 rules found
```

### 3. Диагностика состояния целей через Prometheus HTTP API

```bash
# Проверка статуса скрейпинга инстансов Angie
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="angie-cluster") | {instance: .labels.instance, health: .health, lastScrape: .lastScrape, scrapeDuration: .lastScrapeDuration}'
# → {
# →   "instance": "10.100.0.11:9113",
# →   "health": "up",
# →   "lastScrape": "2026-10-14T14:35:00Z",
# →   "scrapeDuration": 0.00312
# → }

# Мгновенный запрос PromQL к Prometheus API для проверки суммарного RPS
curl -s -G 'http://localhost:9090/api/v1/query' \
    --data-urlencode 'query=sum(rate(angie_http_server_zones_requests_total[1m]))' | jq '.data.result[] | {value: .value[1]}'
# → {
# →   "value": "1284.6"
# → }
```

### 4. Проверка модулей веб-сервера Angie

```bash
# Проверка наличия встроенного модуля prometheus
angie -V 2>&1 | grep -o 'with-http_prometheus_module'
# → with-http_prometheus_module

# Проверка синтаксиса конфигурации и путей include
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка загруженных директив prometheus через полный дамп конфигурации
angie -T | grep -E 'prometheus_template|prometheus '
# → prometheus_template all {
# → prometheus all;
```

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
|:---|:---|:---|:---|
| **Ошибка: `unknown directive "prometheus"`** | Angie собран без модуля `ngx_http_prometheus_module` (был указан флаг `--without-http_prometheus_module`). | `angie -V 2>&1 \| grep prometheus` | Установить официальный бинарный пакет Angie из репозитория `angie.software` или пересобрать сервер без флага `--without`. |
| **Пустой ответ или отсутствие метрик серверов/апстримов** | В блоках `server` отсутствует `status_zone`, а в `upstream` нет директивы `zone`. Метрики по умолчанию собираются только для именованных зон. | `curl -s http://127.0.0.1:9113/p8s \| grep server_zones` возвращает пустоту. | Добавить директиву `status_zone <name>;` в блоки `server` и директиву `zone <name> <size>;` в блоки `upstream`. |
| **Prometheus Target находится в состоянии DOWN** | Firewall (`nftables`/`iptables`) блокирует порт 9113, либо неверно указан IP-адрес/интерфейс в `listen`. | `nc -zv <angie_ip> 9113` с хоста Prometheus. Проверка `ss -tulpn \| grep 9113` на сервере Angie. | Разрешить порт в локальном межсетевом экране: `sudo ufw allow from <prom_ip> to any port 9113 proto tcp`. Проверить директиву `allow` в блоке `location /p8s`. |
| **Ошибка HTTP 403 Forbidden при скрейпинге** | Сработали директивы ограничения доступа `allow`/`deny` внутри `location /p8s`. | В логе `/var/log/angie/error.log` запись `access forbidden by rule`. | Добавить IP-адрес Prometheus сервера в директивы `allow <prom_ip>;` перед `deny all;`. |
| **Ошибка синтаксиса `parse error` в promtool** | Ошибка в кастомном `prometheus_template`: незакрытые кавычки, спецсимволы в именах меток или неэкранированные слеши. | `curl -sf http://localhost:9113/p8s \| promtool check metrics` покажет точный номер строки с ошибкой. | Исправить регулярные выражения и имена меток в `prometheus_template`. Имена метрик должны соответствовать шаблону `[a-zA-Z_:][a-zA-Z0-9_:]*`. |
| **Scrape timeout (таймаут опроса цели)** | Объем экспортируемых метрик слишком велик из-за сотен тысяч уникальных ключей в `metric_zone` (высокая кардинальность). | В логах Prometheus: `context deadline exceeded`. Время генерации ответа `time curl -s http://localhost:9113/p8s > /dev/null` превышает `scrape_timeout`. | Добавить параметр `expire=on discard_key=expired` в директивы `metric_zone`. Отфильтровать ненужные метрики в `prometheus.yml` через `metric_relabel_configs` (действие `drop`). |
| **Сброс значений счетчиков до нуля** | Перезапуск процесса Angie (`systemctl restart angie`). Разделяемая память resides исключительно в RAM. | Проверка времени старта процесса: `ps -eo pid,lstart,cmd \| grep angie`. | Это штатное поведение разделяемой памяти. Для сохранения истории используйте Prometheus TSDB. Для применения изменений конфигурации используйте reload (`angie -s reload` или `systemctl reload angie`), который сохраняет память зон. |

---

## Лучшие практики

### Безопасность и изоляция

1. **Не публиковать порт телеметрии наружу:** Директива `listen` для эндпоинта Prometheus должна быть привязана исключительно к интерфейсу `127.0.0.1` или выделенному интерфейсу внутренней сервисной сети (Management LAN/VLAN).
2. **Многоуровневый контроль доступа:** Комбинируйте сетевую фильтрацию на уровне ядра ОС (`iptables`/`nftables`), директивы Angie `allow <prom_ip>; deny all;` и HTTP Basic Authentication для межсетевого взаимодействия.
3. **Отключение access_log для /p8s:** Частые запросы скрейпинга (каждые 5-15 секунд) раздувают журналы доступа. Указывайте `access_log off;` внутри сервера телеметрии.

### Управление кардинальностью (Cardinality) и памятью

1. **Исключение неконтролируемых ключей в `metric_zone`:** Никогда не используйте полный URI (`$request_uri`) или заголовки `Cookie`/`Authorization` в качестве ключей зон метрик. Это порождает миллионы уникальных серий и приводит к деградации Prometheus TSDB (Out of Memory).
2. **Политика вытеснения устаревших ключей:** При использовании динамических ключей (например, GeoIP или User-Agent) всегда объявляйте зоны с параметром `expire=on discard_key=expired`:
   ```nginx
   metric_zone geo_stats:10m count expire=10m discard_key=expired;
   ```
3. **Фильтрация метрик на коллекторе:** Если инфраструктуре не требуется посекундная статистика по каждому отдельному размеру slab-слотов, отсекайте их в `prometheus.yml`:
   ```yaml
   metric_relabel_configs:
     - source_labels: [__name__]
       regex: "angie_slabs_pages_slots_.*"
       action: drop
   ```

### Надежность и эксплуатация (SRE)

1. **Согласование таймаутов:** Устанавливайте `scrape_timeout` на стороне Prometheus равным 60-70% от `scrape_interval` (например, `scrape_interval: 15s`, `scrape_timeout: 10s`). Это защищает от наложения циклов сбора при пиковых нагрузках на сервер.
2. **Алертинг на Recording Rules:** Всегда настраивайте правила оповещений в Alertmanager на предварительно вычисленные временные ряды из `Recording Rules` (`angie:server_zone_errors_5xx:ratio5m`), а не на "сырые" функции `rate(...)`. Это обеспечивает стабильность вычислений и защищает от кратковременных выбросов.
3. **Валидация конфигурации в CI/CD:** Перед деплоем новой конфигурации Angie или правил PromQL на продуктовые серверы обязательно запускайте:
   - `angie -t` — проверка директив веб-сервера.
   - `promtool check config <path>` — валидация конфигурации Prometheus.
   - `promtool check rules <path>` — синтаксическая проверка правил алертинга и предвычислений.

---

## Дополнительная информация

### Сравнение методов мониторинга Angie

| Критерий | Нативный Prometheus (`/p8s`) | Console Light / API (`/api/`) | Внешний `nginx-prometheus-exporter` |
|:---|:---|:---|:---|
| **Архитектурный оверхед** | Нулевой (прямое чтение из Shared RAM) | Минимальный (веб-интерфейс в браузере) | Дополнительный сторонний процесс, порт и парсинг JSON |
| **Глубина хранения** | Долгосрочная (месяцы/годы в Prometheus TSDB) | Отсутствует (только текущие значения) | Долгосрочная в TSDB |
| **Автоматический алертинг** | Да (Alertmanager, Alerting Rules) | Нет (только визуальный контроль) | Да (Alertmanager) |
| **Формат данных** | OpenMetrics / Prometheus Text format | REST JSON API | Prometheus Text format |
| **Назначение в SRE** | Анализ трендов, SLA/SLO, Capacity Planning | Оперативный траблшутинг в реальном времени | Устаревший легаси-механизм для Nginx |

### Ограничения архитектуры

1. **Pull-модель:** Prometheus должен иметь прямой сетевой маршрут к IP-адресу и порту инстанса Angie. В закрытых периметрах без прямого доступа требуется настройка проксирования или реверс-туннелей.
2. **Неперсистентность Shared Memory:** При полной остановке процесса Angie (`stop`/`start`) данные счетчиков в разделяемой памяти сбрасываются. Исторические тренды сохраняются только в базе Prometheus TSDB.
3. **Разделение зон ответственности:** Модуль `ngx_http_prometheus_module` собирает метрики исключительно сетевой и прикладной активности самого Angie. Метрики операционной системы хоста (утилизация CPU, дисковой подсистемы, памяти ядра) должны собираться стандартным системным `node_exporter`.

### Связанные материалы в базе знаний

- [Основные концепции мониторинга](./angie_monitoring_concepts.md) — расчет памяти, структуры `status_zone` и архитектура Shared Memory.
- [Пользовательские метрики и их экспорт](./angie_monitoring_custom_metrics.md) — детальный синтаксис `metric_zone`, `metric_complex_zone`, вычисление APDEX и шаблоны `prometheus_template`.
- [Настройка Console Light и API](./angie_monitoring_console.md) — развертывание встроенного веб-интерфейса реального времени.
- [Работа с конфигурацией через REST API](./angie_monitoring_api.md) — структура JSON эндпоинтов `/status/` и динамическое управление.
- [Возможности Angie Pro](./angie_monitoring_pro.md) — кластерная синхронизация зон и активные проверки зон `upstream_probe`.

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Пользовательские метрики и их экспорт](./angie_monitoring_custom_metrics.md)
- [Настройка Console Light и API](./angie_monitoring_console.md)
- [Работа с конфигурацией через REST API](./angie_monitoring_api.md)
- [Возможности Angie Pro](./angie_monitoring_pro.md)
