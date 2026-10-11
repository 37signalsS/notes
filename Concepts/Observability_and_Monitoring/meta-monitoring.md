# Мета-мониторинг: мониторинг систем наблюдаемости

**Актуально для:** Prometheus 3.x, VictoriaMetrics 1.52.x, Loki 3.x, Alertmanager 0.27.x, Vector 0.44.x, Fluent Bit 5.1.x, Zabbix 8.0.x

## Определения

**Мета-мониторинг (Meta-monitoring)** — стратегия и набор инструментов для контроля работоспособности самой системы наблюдаемости (Observability). Основная задача — гарантировать, что при выходе из строя основной системы мониторинга, сбое в пайплайне обработки данных или отказе цепочки доставки уведомлений, ответственные инженеры будут оповещены через независимые каналы.

**Основные термины:**

- **Самомониторинг (Self-monitoring):** способность инструмента наблюдать за собственными внутренними показателями (использование кучи/heap, задержки очередей, ошибки парсинга, количество активных временных рядов).
- **Переключатель мертвеца (Dead Man's Switch):** механизм инвертированного алертинга, который срабатывает при *отсутствии* ожидаемого сигнала (heartbeat) в течение заданного интервала. Это единственный способ подтвердить работоспособность всей цепочки: от сбора данных до доставки уведомления.
- **Внешний наблюдатель (External Watchdog):** независимая система или сервис (часто SaaS), проверяющая доступность основной системы мониторинга и прохождение тестовых алертов извне.
- **Сердцебиение (Heartbeat):** регулярный сигнал («keep-alive»), отправляемый компонентом для подтверждения своей жизнеспособности. Теоретические основы механизмов описаны в разделе **[Механизмы Failover и Heartbeat](../High_Availability/ha_failover_mechanisms.md)**.
- **Задержка приема (Ingestion Lag):** время между моментом возникновения события в источнике и моментом его доступности для запроса в хранилище (TSDB, Log store). Критичный показатель для мета-мониторинга пайплайнов.

## Предварительные требования

Перед внедрением мета-мониторинга убедитесь, что инфраструктура соответствует следующим условиям:

- **NTP-синхронизация:** все узлы мониторинга должны иметь синхронизированное время (расхождение < 1 секунды). Сдвиг часового пояса или рассинхронизация NTP приводят к ложным срабатываниям watchdog и неверным расчетам ingestion lag.
- **Сетевая связность:** между узлами мета-мониторинга и основным кластером открыты порты 9090 (Prometheus), 9093 (Alertmanager), 3100 (Loki), 9598 (Vector), 9200 (Fluent Bit exporter).
- **Достаточные ресурсы:** отдельный Prometheus для мета-мониторинга должен иметь выделенные ресурсы, не зависящие от основного кластера. Рекомендуется минимум 2 CPU, 4 GB RAM и SSD-накопитель для TSDB.
- **Разделение ответственности:** назначены инженеры, ответственные за watchdog-канал (SMS, телефонный звонок), независимо от основного канала алертинга.
- **Документированные runbook:** для каждого watchdog-алерта существует runbook с инструкциями по ручному подтверждению работоспособности системы.

## Базовые концепции

### Причины отказа систем мониторинга

Система мониторинга — это высоконагруженное распределенное приложение, подверженное специфическим рискам:

1.  **Переполнение хранилища (Disk Full):** TSDB (Prometheus, VictoriaMetrics, ClickHouse) переходят в режим `read-only` или аварийно завершаются при нехватке места. Это «тихий» отказ, так как процессы могут оставаться запущенными.
2.  **Сетевая изоляция (Network Partition):** агенты сбора (exporters) доступны, но сервер мониторинга отрезан от сети или системы уведомлений (Slack, Telegram, email).
3.  **Взрыв кардинальности (Cardinality Explosion):** резкий рост уникальных меток (например, запись IP-адресов клиентов или динамических ID в лейблы) приводит к перерасходу RAM, замедлению запросов и OOM (Out of Memory).
4.  **Тихий отказ (Silent Failure):** процесс мониторинга работает, но данные не собираются из-за зависания Service Discovery (например, проблемы с API Kubernetes) или блокировки пайплайна (Backpressure).
5.  **Ложные сайленсы (Silences):** ошибочно настроенное правило подавления алертов может "заглушить" критические инциденты на неопределенный срок.

### Мета-мониторинг для различных сигналов

Наблюдаемость состоит не только из метрик, поэтому мета-мониторинг должен охватывать все сигналы:

- **Логи (Logging Pipeline):** мониторинг очередей в Vector/Fluentd. Если `buffer_usage` достигает 100%, логи начинают отбрасываться или замедляют приложение. Необходимо отслеживать ошибки парсинга (`parse_errors_total`) и задержку записи в хранилище (Loki, Elasticsearch).
- **Трассировки (Tracing):** мониторинг дропа спанов (`spans_dropped_total`) в OTel Collector. Из-за высокого объема данных трейсинг часто первым страдает от нехватки ресурсов.
- **Метрики (Metrics):** мониторинг времени вычисления правил (`prometheus_rule_group_last_duration_seconds`) и ошибок удаленной записи (`remote_write_failed_samples_total`).

### Иерархия мета-мониторинга

Кто мониторит мониторинг?

- **Уровень 1 (Внутренний):** экспорт метрик рантайма (Go metrics, GC, Goroutines) и прикладных метрик самого сервера.
- **Уровень 2 (Перекрестный):** кластеры мониторинга в разных зонах доступности следят друг за другом. Например, Prometheus в `Region-A` опрашивает `/metrics` у Prometheus в `Region-B`.
- **Уровень 3 (Внешний):** легковесные скрипты (Python/Go) или специализированные self-hosted решения (Healthchecks.io, Uptime Kuma), проверяющие только факт прохождения алертов.

## Архитектурные подходы

### 1. Алерт «Watchdog» (Dead Man's Switch)

Самый надежный метод проверки всей цепочки: `Data Source → Alert Rule → Alertmanager → Notification Provider`.

1.  В системе мониторинга создается алерт с условием, которое *всегда* истинно (например, `vector(1)`).
2.  Этот алерт направляется во внешнюю систему раз в N минут.
3.  Если внешняя система не получает уведомление в течение окна ожидания (например, 5 минут), она инициирует инцидент через независимый канал (SMS, звонок, Telegram через другого бота).

### 2. Мультирегиональный перекрестный мониторинг

В распределенных инфраструктурах используется схема «кольцевого» мониторинга:

- **Узел A** мониторит **Узел B**.
- **Узел B** мониторит **Узел C**.
- **Узел C** мониторит **Узел A**.

Это исключает ситуацию, когда мониторинг всей инфраструктуры "ослепнет" из-за падения одной центральной точки. Важно, чтобы алерты от разных узлов уходили через разных провайдеров или сетевые маршруты.

### 3. Мониторинг пайплайна уведомлений

Важно отслеживать не только наличие данных, но и работоспособность Alertmanager:

- **Мониторинг сайленсов (Silences):** сбор метрик о количестве активных сайленсов (`alertmanager_silences_active`). Аномальное количество сайленсов — повод для проверки, не скрыты ли важные ошибки.
- **Мониторинг подавления (Inhibition):** проверка того, что правила подавления (Inhibition rules) не блокируют важные алерты из-за слишком широких селекторов.
- **Здоровье интеграций:** отслеживание ошибок HTTP-запросов к провайдерам уведомлений (`alertmanager_notifications_failed_total`).

### 4. Синтетический мониторинг (Synthetics)

Проверка доступности интерфейсов мониторинга (Grafana UI, Prometheus API) с точки зрения пользователя. Если API хранилища недоступно, инженеры не смогут провести диагностику, даже если алерт пришел. Проверки выполняются внешними агентами (Blackbox Exporter) из разных географических точек.

## Практические сценарии

### Сценарий 1: Watchdog в Prometheus

Настройка алерта, подтверждающего работоспособность пайплайна.

**Правило в Prometheus:**

```yaml
groups:
- name: meta-monitoring
  rules:
  - alert: Watchdog
    expr: vector(1)
    for: 1m
    labels:
      severity: critical
      meta_target: healthchecks_io
    annotations:
      summary: "Healthcheck heartbeat for external monitoring"
```

**Конфигурация Alertmanager:**
Алерт `Watchdog` направляется через Webhook на эндпоинт внешнего сервиса (например, `https://hc-ping.com/<uuid>`).

### Сценарий 2: Самомониторинг VictoriaMetrics (vmagent)

`vmagent` — эффективный сборщик, который должен мониторить себя сам для предотвращения потери данных при Remote Write.

**Ключевые метрики для алертинга:**

- `vm_rpc_errors_total`: ошибки передачи данных между компонентами.
- `vmagent_remotewrite_queues_filled_percentage`: заполнение очередей на отправку. Если 100% — данные начинают теряться (backpressure).
- `vmagent_remotewrite_dropped_rows_total`: прямой показатель потери данных из-за невозможности отправить их в хранилище.

### Сценарий 3: Самомониторинг Zabbix

Zabbix использует [Internal checks](../../Zabbix/zabbix_troubleshooting_and_performance_tuning.md) для контроля внутренних процессов:

- `zabbix[process,poller,avg,busy]`: загрузка поллеров.
- `zabbix[wcache,values,avg]`: скорость записи значений в БД.

**Критический триггер:** `Zabbix queue is too large` — указывает на то, что время обработки метрик превышает скорость их поступления (Bottle-neck в БД или нехватка воркеров).

### Сценарий 4: Мониторинг латентности алертов (Alertmanager)

**Задача:** убедиться, что алерты доставляются вовремя.

**Метрика:** `alertmanager_notifications_failed_total` и `alertmanager_notification_latency_seconds_bucket`.

**Правило:**
```yaml
- alert: AlertmanagerHighNotificationLatency
  expr: histogram_quantile(0.99, rate(alertmanager_notification_latency_seconds_bucket[5m])) > 30
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Alertmanager notification latency is high"
```

### Сценарий 5: Мониторинг пайплайна логов (Vector + Loki)

**Задача:** обеспечить надежную доставку логов из Vector в Loki и отслеживать backpressure.

**Ключевые метрики Vector для мета-мониторинга:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `vector_buffer_utilization` | Заполненность буфера (0-1) | > 0.8 (warning), > 0.95 (critical) |
| `vector_buffer_bytes` | Размер буфера в байтах | > 80% от max_size |
| `vector_component_errors_total` | Ошибки компонента | Рост > 0 за 5 минут |
| `vector_component_discarded_events_total` | Отброшенные события | > 0 (critical) |
| `vector_sink_requests_failed` | Неудачные попытки отправки | > 3 за 5 минут |

**Алерт-правило для Prometheus:**
```yaml
groups:
- name: vector-meta-monitoring
  rules:
  - alert: VectorBufferHighUtilization
    expr: vector_buffer_utilization > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Vector buffer utilization > 80%"
      
  - alert: VectorEventsDiscarded
    expr: rate(vector_component_discarded_events_total[5m]) > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Vector is discarding events - data loss imminent"
```

**Метрики Loki для мета-мониторинга:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `loki_ingester_streams_created_total` | Потоки, создаваемые в ingester | Рост аномалий |
| `loki_ingester_chunk_entries` | Записи в чанках | Снижение активности |
| `loki_query_duration_seconds` | Время выполнения запросов | p99 > 10s |
| `loki_ingester_memory_chunks` | Чанки в памяти | > 80% от лимита |

### Сценарий 6: Самомониторинг Prometheus сервера

**Задача:** гарантировать, что Prometheus собирает метрики и выполняет правила.

**Ключевые метрики:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `prometheus_tsdb_head_series` | Активные временные ряды | Рост > 20% за час |
| `prometheus_tsdb_head_chunks` | Чанки в head | > 80% от max_chunks |
| `prometheus_rule_group_last_duration_seconds` | Время выполнения правила | > interval правила |
| `prometheus_notifications_failed_total` | Ошибки уведомлений | > 0 за 5 минут |
| `prometheus_notifications_queue_length` | Длина очереди уведомлений | > 1000 |

**Алерт-правило:**
```yaml
groups:
- name: prometheus-meta-monitoring
  rules:
  - alert: PrometheusRuleEvaluationSlow
    expr: prometheus_rule_group_last_duration_seconds > prometheus_rule_group_interval_seconds
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Prometheus rule evaluation is slower than interval"
      
  - alert: PrometheusNotificationsFailing
    expr: rate(prometheus_notifications_failed_total[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Prometheus notifications are failing"
```

### Сценарий 7: Мониторинг Fluent Bit DaemonSet в Kubernetes

**Задача:** обеспечить сбор логов со всех нод и отслеживать потери.

**Ключевые метрики Fluent Bit:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `fluentbit_output_errors_total` | Ошибки вывода | > 0 за 5 минут |
| `fluentbit_output_retries_total` | Повторные попытки | Рост > 10 за минуту |
| `fluentbit_output_bytes_total` | Объем отправленных данных | Снижение > 50% |
| `fluentbit_input_records_total` | Входящие записи | Снижение > 30% |

**Пример Deployment для мета-мониторинга Fluent Bit:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit-monitoring
  namespace: logging
spec:
  selector:
    matchLabels:
      app: fluent-bit-monitoring
  template:
    metadata:
      labels:
        app: fluent-bit-monitoring
    spec:
      containers:
      - name: prometheus-exporter
        image: prom/fluent-bit-exporter:v0.5.0
        ports:
        - containerPort: 9200
          name: metrics
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 100m
            memory: 128Mi
```

### Сценарий 8: Мониторинг VictoriaMetrics (кластерный режим)

**Задача:** обеспечить надежность сбора и хранения метрик в кластере VictoriaMetrics.

**Ключевые метрики для кластера:**

| Компонент | Метрика | Описание |
| :--- | :--- | :--- |
| **vmselect** | `vm_active_queries` | Активные запросы |
| **vmselect** | `vm_slow_queries` | Медленные запросы |
| **vminsert** | `vm_rows_inserted_total` | Вставленные строки |
| **vminsert** | `vm_dropped_rows_total` | Отброшенные строки |
| **vmstorage** | `vm_rows` | Всего строк в хранилище |
| **vmstorage** | `vm_parts` | Количество частей |

**Алерт-правило:**
```yaml
groups:
- name: victoriametrics-meta-monitoring
  rules:
  - alert: VictoriaMetricsDroppedRows
    expr: rate(vm_dropped_rows_total[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "VictoriaMetrics is dropping rows - data loss"
      
  - alert: VictoriaMetricsActiveQueriesHigh
    expr: vm_active_queries > 1000
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Too many active queries in VictoriaMetrics"
```

### Сценарий 9: Внешний watchdog на bare-metal (Healthchecks.io self-hosted)

**Задача:** реализовать Dead Man's Switch без облачных сервисов.

**Варианты self-hosted решений:**

| Решение | Описание | Протокол |
| :--- | :--- | :--- |
| **[Healthchecks.io](https://healthchecks.io/)** (self-hosted) | Python-приложение, проверяет heartbeat | HTTP/ICMP |
| **[Cronitor](https://cronitor.io/)** (self-hosted) | Альтернатива Healthchecks | HTTP |
| **Custom Script** | Скрипт на Python/Go, проверяющий endpoint | HTTP/SMTP |

**Пример Docker Compose для self-hosted Healthchecks.io:**
```yaml
version: '3.8'
services:
  healthchecks:
    image: healthchecks/healthchecks:v3.0
    ports:
      - "8000:8000"
    environment:
      - SITE_ROOT=http://localhost:8000
      - SITE_NAME=Meta-Monitoring
      - DEFAULT_FROM_EMAIL=alerts@example.com
      - EMAIL_HOST=smtp.example.com
      - EMAIL_PORT=587
      - EMAIL_HOST_USER=alerts@example.com
      - EMAIL_HOST_PASSWORD=secret
    volumes:
      - healthchecks-data:/var/lib/healthchecks
    restart: unless-stopped

volumes:
  healthchecks-data:
```

**Конфигурация Alertmanager для отправки heartbeat:**
```yaml
receivers:
- name: watchdog
  webhook_configs:
  - url: 'http://healthchecks:8000/ping/your-uuid-here'
    send_resolved: true
    
route:
  routes:
  - match:
      meta_target: healthchecks_io
    receiver: watchdog
    group_wait: 0s
    group_interval: 1m
    repeat_interval: 1m
```

### Сценарий 10: Мониторинг выполнения резервного копирования (Backup Dead Man's Switch)

**Задача:** гарантировать, что скрипты резервного копирования выполняются по расписанию и не "забываются" в crontab.

**Проблема:** обычный запуск скрипта в cron не даёт информации о том, работает ли он. Если скрипт упадёт до начала бэкапа, или зависнет, или cron перестанет работать — об этом можно не узнать до момента восстановления.

**Решение — Dead Man's Switch для бэкапов:**

На каждое успешное выполнение скрипта отправляется "пинг" во внешнюю систему. Если пинг не приходит в ожидаемое временное окно — система инициирует алерт.

**Интеграция с Healthchecks.io:**

```bash
# Внутри скрипта, либо через pipe в cron-команде
curl -fsS -m 10 --retry 5 -o /dev/null https://healthchecks.io/ping/efe3-da-ffdsfsd-qqsdfsf
```

**Измерение времени выполнения:**

Сервис умеет замерять время выполнения скрипта. Отправляем пинг в начале и в конце:

```bash
# Начало выполнения
curl -fsS -m 10 --retry 3 https://healthchecks.io/ping/start/your-uuid-here

# Выполнение бэкапа
pg_dump -Fc mydb > /backups/mydb.dump

# Успешное завершение
curl -fsS -m 10 --retry 3 https://healthchecks.io/ping/your-uuid-here

# Или через pipe в cron:
# */30 * * * * /usr/local/bin/backup.sh | curl -fsS -m 10 --retry 5 -o /dev/null https://healthchecks.io/ping/your-uuid-here
```

**Запись логов ошибок:**

Через POST-запрос можно передать текст ошибки для диагностики:

```bash
# Если бэкап упал с ошибкой
curl -fsS -m 10 --retry 3 \
  -X POST \
  -d "Ошибка: pg_dump завершился с кодом $?" \
  https://healthchecks.io/ping/your-uuid-here/fail
```

**Альтернативные сервисы:**

| Сервис | Особенности |
| :--- | :--- |
| **[Healthchecks.io](https://healthchecks.io/)** | Self-hosted, HTTP/ICMP, подробная документация |
| **[Cronitor](https://cronitor.io/)** | Self-hosted, HTTP, простой API |
| **Custom Script** | Скрипт на Python/Go, проверяющий endpoint | HTTP/SMTP |

**Пример cron-задачи с мониторингом:**

```bash
# crontab -e
0 2 * * * /usr/local/bin/pg_backup.sh >> /var/log/pg_backup.log 2>&1 && \
  curl -fsS -m 10 --retry 5 -o /dev/null https://healthchecks.io/ping/your-uuid-here
```

**См. также:**
* [Автоматизация резервного копирования PostgreSQL](../../Databases/PostgreSQL/Operations/backup_automation.md) — практическая реализация бэкапов с метриками.
* [Стратегии резервного копирования БД](../../Databases/Concepts/backups.md) — теоретические основы (3-2-1, PITR).

## Ограничения и крайние случаи

### Внешний watchdog недоступен

Если внешний watchdog (Healthchecks.io, Uptime Kuma) сам выходит из строя, мета-мониторинг теряет независимый канал. **Решение:** разворачивайте watchdog в отдельном дата-центре или используйте несколько независимых провайдеров (SMS + телефонный звонок + отдельный бот в Telegram).

### Рассинхронизация времени (NTP drift)

Watchdog и ingestion lag критически зависят от точности часов. При сдвиге > 5 секунд:
- Watchdog-алерты срабатывают ложноположительно или пропускают реальные простои.
- Метрики ingestion lag показывают отрицательные или аномально высокие значения.

**Диагностика:**
```bash
# Проверка расхождения времени
chronyc tracking
# Или
ntpstat
```

### Сетевые разветвления (Network Partition)

При разделении сети на два изолированных сегмента:
- Сегмент A может продолжать собирать метрики, но не доставляет алерты.
- Сегмент B получает алерты, но не имеет данных для принятия решения.

**Решение:** размещайте watchdog в третьем, независимом сетевом сегменте, и используйте мультирегиональный cross-scrape.

### Взрыв кардинальности во время инцидента

При массовом отказе (например, отказ всех нод в зоне) количество серий метрик может возрасти в 10–100 раз. TSDB может переполниться RAM и начать дропать данные именно в момент, когда мета-мониторинг наиболее нужен.

**Меры противодействия:**
- Ограничьте `max_series_per_target` и `max_series_per_metric` в Prometheus.
- Используйте `metric_relabel_configs` для отсечения неинформативных меток при высоком уровне кардинальности.
- Настройте отдельный алерт на `prometheus_tsdb_head_series` с порогом ниже лимита.

### Alertmanager Cluster Split-Brain

При потере quorum (меньше 50% узлов + 1) кластер Alertmanager перестает корректно группировать и доставлять алерты. Каждый узел может считать себя лидером.

**Решение:** всегда разворачивайте Alertmanager нечетным количеством узлов (3 или 5). Используйте внешний load balancer с проверкой готовности (`/-/ready`) для роутинга трафика.

### Зависание scrape-запроса

Если target зависает и не отвечает на scrape-запрос в течение `scrape_timeout`, Prometheus помечает его как `down`, но при этом пул воркеров может быть заблокирован ожиданием таймаута.

**Решение:** устанавливайте `scrape_timeout` явно (менее `scrape_interval`). Используйте `body_size_limit` для защиты от неограниченного роста ответа.

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Watchdog не срабатывает** | Проблема в цепочке Alertmanager → Webhook | Проверить логи Alertmanager, убедиться в доступности внешнего эндпоинта. |
| **Растет Ingestion Lag** | Нехватка ресурсов CPU/IOPS в хранилище | Увеличить лимиты ресурсов, включить шардирование (sharding) или уменьшить частоту сбора (scrape interval). |
| **Cardinality Explosion** | Неконтролируемое добавление меток в приложении | Использовать `relabel_configs` для удаления динамических меток, ограничить количество серий на таргет. |
| **Backpressure в агентах** | Хранилище не успевает принимать данные | Оптимизировать производительность TSDB, проверить сетевую пропускную способность. |
| **Watchdog-алерт не доходит** | Блокировка HTTP-запросов firewall или proxy | Проверить маршрутизацию, белые списки firewall, настройки proxy. |
| **Prometheus не собирает метрики** | Проблемы с Service Discovery или DNS | Проверить `up` метрику, логи Prometheus, доступность target'ов. |
| **Vector buffer переполнен** | Loki/Elasticsearch не принимает данные | Проверить здоровье хранилища, увеличить buffer.max_size, оптимизировать производительность запросов. |
| **Loki не индексирует логи** | Переполнение_ingester или проблемы с чанками | Проверить `loki_ingester_memory_chunks`, увеличить лимиты памяти. |
| **Alertmanager теряет алерты** | Переполнение очереди или ошибки интеграций | Проверить `alertmanager_notifications_queue_length`, оптимизировать route rules. |
| **Фейковые алерты (False Positives)** | Нестабильные target'ы или network jitter | Добавить `for` duration в правила, использовать `label_replace` для стабилизации. |
| **DDoS на мета-мониторинг** | Чрезмерно частые scrape-запросы | Ограничить `scrape_interval`, использовать discovery limits, настроить rate limiting. |
| **Временные сбои watchdog** | Микросервисы временно недоступны | Увеличить `repeat_interval`, настроить `group_wait` для агрегации. |

### Диагностические команды

```bash
# Prometheus: проверка состояния
curl -s http://localhost:9090/-/healthy
# → "Prometheus Server is Healthy."

# Поиск нездоровых target'ов
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health!="up")'
# → JSON с health: "down" или "unknown" для проблемных target'ов

# Alertmanager: проверка статуса
curl -s http://localhost:9093/-/healthy
# → "OK"

# Количество активных алертов
curl -s http://localhost:9093/api/v2/alerts | jq 'length'
# → Число активных алертов (0 при нормальной работе)

# Vector: проверка метрик буфера
curl -s http://localhost:9598/metrics | grep "vector_buffer"
# → vector_buffer_utilization{component="...", ...} 0.0–1.0

# Loki: проверка готовности
curl -s http://localhost:3100/ready
# → "ready"

# Список доступных лейблов
curl -s http://localhost:3100/loki/api/v1/labels | jq '.data'
# → Массив строк с именами лейблов

# Fluent Bit: проверка статуса
fluent-bit -L
# → Вывод списка сервисов и их статусов (INPUT/OUTPUT/FILTER)

# kubectl: диагностика DaemonSet
kubectl get daemonset -n logging
# → NAME                   DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE

# Логи Fluent Bit за последние 100 строк
kubectl logs -n logging -l app=fluent-bit --tail=100
# → Логи с уровнями INFO/WARN/ERROR
```

## Лучшие практики

### Systemd-юниты для компонентов мониторинга

Все критичные компоненты мониторинга должны запускаться через systemd с соответствующими параметрами:

```ini
# /etc/systemd/system/prometheus.service
[Unit]
Description=Prometheus Monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.retention.size=50GB \
  --web.console.templates=/usr/share/prometheus/consoles \
  --web.console.libraries=/usr/share/prometheus/console_libraries
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/victoriametrics.service
[Unit]
Description=VictoriaMetrics
After=network-online.target

[Service]
Type=simple
User=vmstorage
Group=vmstorage
ExecStart=/usr/bin/vmstorage \
  -storageDataPath=/var/lib/victoriametrics \
  -retentionPeriod=30d \
  -memory.allowedPercent=30
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Ротация логов компонентов мониторинга

```bash
# /etc/logrotate.d/prometheus
/var/log/prometheus/*.log {
  daily
  rotate 30
  compress
  delaycompress
  missingok
  notifempty
  create 0640 prometheus prometheus
  postrotate
    systemctl reload prometheus > /dev/null 2>&1 || true
  endscript
}

# /etc/logrotate.d/alertmanager
/var/log/alertmanager/*.log {
  daily
  rotate 30
  compress
  delaycompress
  missingok
  notifempty
  create 0640 alertmanager alertmanager
  postrotate
    systemctl reload alertmanager > /dev/null 2>&1 || true
  endscript
}
```

### Стратегия резервного копирования данных мониторинга

| Компонент | Метод бэкапа | Рекомендуемая частота | Хранение |
| :--- | :--- | :--- | :--- |
| **Prometheus TSDB** | `promtool tsdb dump` или копирование директории | Ежедневно | 30 дней |
| **VictoriaMetrics** | Встроенное реплицирование или бэкап снапшотов | Ежедневно | 30 дней |
| **Loki chunks** | Копирование директории chunks + индексы | Ежедневно | 30 дней |
| **Alertmanager** | Конфигурационные файлы + базу данных silences | После изменений | Git |
| **Grafana** | Экспорт дашбордов + база данных | Ежедневно | 30 дней |

**Пример скрипта бэкапа Prometheus:**
```bash
#!/bin/bash
# /usr/local/bin/backup_prometheus.sh
BACKUP_DIR="/backups/prometheus"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Создание снапшота
curl -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot

# Копирование снапшота
SNAPSHOT=$(ls -t /var/lib/prometheus/snapshots/ | head -1)
tar -czf $BACKUP_DIR/prometheus_$TIMESTAMP.tar.gz -C /var/lib/prometheus/snapshots $SNAPSHOT

# Ротация старых бэкапов
find $BACKUP_DIR -name "prometheus_*.tar.gz" -mtime +$RETENTION_DAYS -delete

# Отправка heartbeat
curl -fsS -m 10 --retry 3 https://healthchecks.io/ping/your-uuid-here
```

### Рекомендации по развертыванию

| Аспект | Рекомендация |
| :--- | :--- |
| **Сеть** | Изолируйте компоненты мониторинга в отдельный VLAN. Ограничьте доступ к `/metrics` только сетью мониторинга. |
| **Аутентификация** | Включите TLS для всех компонентов. Используйте mTLS между Prometheus и Alertmanager. |
| **Ресурсы** | Выделяйте не менее 4GB RAM и 2 CPU для Prometheus на 100k активных метрик. VictoriaMetrics требует на 30-50% меньше ресурсов. |
| **Хранилище** | Используйте SSD/NVMe для TSDB. Хранилище должно быть в 2-3 раза больше ожидаемого объема raw данных (с учетом compression). |
| **HA** | Разворачивайте пару Prometheus в разных зонах доступности с cross-scrape. Alertmanager должен работать в кластере минимум из 3 узлов. |
| **Резервное копирование** | Настраивайте автоматический бэкап TSDB ежедневно. Тестируйте восстановление ежемесячно. |
| **Мониторинг мониторинга** | Отдельный Prometheus для мета-мониторинга не должен зависеть от основного кластера. Используйте внешний watchdog. |

### Безопасность

- **Сеть:** Размещайте компоненты мониторинга в изолированном сегменте. Используйте firewall для ограничения доступа к портам 9090, 9093, 3100, 9200.
- **Аутентификация:** Включите базовую аутентификацию или OAuth2 для Grafana. Для Prometheus используйте TLS-клиентские сертификаты.
- **Секреты:** Храните пароли и токены в HashiCorp Vault или аналогичном системе, а не в конфигурационных файлах.
- **Аудит:** Включите аудит запросов к API Prometheus и Alertmanager. Логируйте все изменения конфигурации.

## Дополнительная информация

### Чек-лист мета-мониторинга

- [ ] Настроен алерт "Watchdog" с проверкой внешней системой (Dead Man's Switch).
- [ ] Мониторится свободное место на дисках всех узлов TSDB и лог-агрегаторов.
- [ ] Настроены алерты на `up == 0` для всех критических экспортеров и агентов.
- [ ] Отслеживается `Ingestion Lag` (задержка появления данных).
- [ ] Мониторится количество активных сайленсов в Alertmanager.
- [ ] Проверяется лимит открытых дескрипторов файлов (`fd_utilization`) для процессов мониторинга.
- [ ] Настроен мониторинг API хранилища (Synthetics).
- [ ] Внешний watchdog работает без зависимости от основного мониторинга.
- [ ] Настроен мониторинг буферов агентов (Vector, Fluent Bit).
- [ ] Проверяется латентность уведомлений Alertmanager.
- [ ] Настроены алерты на cardinality explosion в Prometheus/VictoriaMetrics.
- [ ] Мониторится производительность запросов к хранилищу (Loki, Elasticsearch).

### SLO для системы мониторинга

Для критических систем рекомендуется внедрять Service Level Objectives (SLO) на сам мониторинг:

- **Availability:** 99.9% времени сервер мониторинга должен отвечать на запросы.
- **Alert Latency:** 95% алертов должны быть доставлены провайдеру уведомлений в течение 30 секунд после срабатывания правила.
- **Data Freshness:** 99% метрик должны иметь возраст не более 60 секунд.
- **Buffer Utilization:** буферы агентов не должны превышать 80% заполненности.
- **Ingestion Lag:** задержка появления данных в хранилище не должна превышать 30 секунд.

### Архитектурные паттерны мета-мониторинга

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Self-contained** | Каждый компонент мониторит себя сам | Малые системы, простые инфраструктуры |
| **Cross-region** | Компоненты в разных зонах мониторят друг друга | Средние системы, высокая доступность |
| **External watchdog** | Внешняя система проверяет heartbeat | Критические системы, compliance |
| **Hybrid** | Комбинация всех трех паттернов | Large-scale, mission-critical |

### Инструменты для мета-мониторинга

| Инструмент | Назначение | Тип |
| :--- | :--- | :--- |
| **[Healthchecks.io](https://healthchecks.io/)** | Dead Man's Switch, heartbeat мониторинг | Self-hosted |
| **[Uptime Kuma](https://uptime.kuma.pet/)** | Мониторинг uptime, heartbeat | Self-hosted |
| **[Cachet](https://cachethq.io/)** | Статус-страницы, инциденты | Self-hosted |
| **[Prometheus](https://prometheus.io/)** | Сбор и хранение метрик | Self-hosted |
| **[VictoriaMetrics](https://victoriametrics.com/)** | Высокопроизводительное хранилище метрик | Self-hosted |
| **[Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)** | Маршрутизация и группировка алертов | Self-hosted |
| **[Grafana](https://grafana.com/)** | Визуализация метрик и логов | Self-hosted |

### Мета-мониторинг для bare-metal инфраструктуры

В отсутствие специализированных облачных сервисов необходимо реализовывать мета-мониторинг самостоятельно:

**Рекомендуемый стек:**

1. **Сбор метрик:** Prometheus (pull-модель) + Node Exporter + процессорные экспортеры.
2. **Хранение метрик:** VictoriaMetrics (single-node или кластер) или Thanos.
3. **Алертинг:** Alertmanager с интеграциями в self-hosted решения (Healthchecks.io, Uptime Kuma).
4. **Визуализация:** Grafana с дашбордами для мета-мониторинга.
5. **Логирование:** Loki + Vector/Fluent Bit для логов компонентов мониторинга.
6. **Внешний watchdog:** Healthchecks.io (self-hosted) или Uptime Kuma.

**Пример Docker Compose для полного стека мета-мониторинга:**
```yaml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus:v3.2.0
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    restart: unless-stopped

  alertmanager:
    image: prom/alertmanager:v0.27.0
    ports:
      - "9093:9093"
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml
    restart: unless-stopped

  grafana:
    image: grafana/grafana:v12.0.0
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana
    restart: unless-stopped

  loki:
    image: grafana/loki:3.2.0
    ports:
      - "3100:3100"
    volumes:
      - loki-data:/loki
    restart: unless-stopped

  healthchecks:
    image: healthchecks/healthchecks:v3.0
    ports:
      - "8000:8000"
    environment:
      - SITE_ROOT=http://localhost:8000
      - SITE_NAME=Meta-Monitoring
    volumes:
      - healthchecks-data:/var/lib/healthchecks
    restart: unless-stopped

volumes:
  prometheus-data:
  grafana-data:
  loki-data:
  healthchecks-data:
```

### См. также

- **[Методологии мониторинга](./monitoring_methodologies.md)** — RED, USE и Golden Signals.
- **[Механизмы Failover и Heartbeat](../High_Availability/ha_failover_mechanisms.md)** — теория отказоустойчивости.
- **[Управление инцидентами](./incident_management.md)** — реагирование на инциденты в системе мониторинга.
- **[Детекция аномалий](./anomaly_detection.md)** — обнаружение аномалий в самой системе мониторинга.
- **[Зрелость сервиса и готовность к production](./service_maturity_production_readiness.md)** — meta-monitoring readiness.
- **[Наблюдаемость баз данных](./database_observability.md)** — мониторинг баз данных как часть meta-monitoring.
- **[Проектирование высоконагруженного мониторинга](./designing_high-load_monitoring_in_distributed_systems.md)** — архитектура шардирования и федерации.
- **[Наблюдаемость Vector](../../Vector/vector_overview.md#мониторинг-самого-vector)** — мониторинг пайплайнов передачи логов.
- **[Loki: обзор](../../Loki/loki_overview.md)** — хранилище логов и его мета-мониторинг.
- **[Prometheus: обзор](../../Prometheus/overview.md)** — основы Prometheus и самомониторинг.
- **[VictoriaMetrics: обзор](../../VictoriaMetrics/overview.md)** — высокопроизводительное хранилище метрик.
- **[Рекомендации по алертингу](./monitoring_alerting_recommendations.md)** — настройка Alertmanager и борьба с Alert Fatigue.
- **[Наблюдаемость в контейнерах](./observability_in_containers.md)** — мониторинг Kubernetes и Docker.
- **[Четыре столпа Observability](./four_pillars_of_observability.md)** — фундаментальные концепции наблюдаемости.
