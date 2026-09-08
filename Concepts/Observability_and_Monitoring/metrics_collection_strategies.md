# Стратегии сбора метрик

## Определения

**Стратегии сбора метрик** -- архитектурные подходы к организации передачи телеметрических данных от источников (приложений, серверов, оборудования) к системе мониторинга и хранения (TSDB). Выбор стратегии определяет сетевую архитектуру, требования к безопасности (Firewall/NAT), масштабируемость системы наблюдаемости (Observability) и характерные точки отказа.

**Основные подходы:**

- **Pull-модель (скрейпинг):** система мониторинга активно запрашивает данные у источников. Стандарт -- Prometheus Text / OpenMetrics.
- **Push-модель (отправка):** источники или локальные агенты самостоятельно отправляют данные. В 2026 году основным стандартом является **Native OTLP Ingest**.
- **Сбор из логов (Log-to-Metrics):** числовые показатели генерируются путем анализа текстовых журналов событий (через Vector или Loki).
- **Hybrid (Remote Write 2.0):** локальный агент собирает данные (pull) и пересылает их в удаленное хранилище (push) с использованием современных протоколов оптимизации трафика.

**См. также:** [Определения Observability](./observability_definitions.md), [Четыре столпа Observability](./four_pillars_of_observability.md), [Методологии мониторинга (RED, USE)](./monitoring_methodologies.md).

---

## Базовые концепции

### 1. Pull-модель (Scraping)

Центральный сервер мониторинга (например, Prometheus) периодически опрашивает список известных ему целей (targets) по протоколу HTTP.

**Характеристики:**
- **Централизованное управление:** вся конфигурация (интервалы сбора, правила фильтрации) хранится в одном месте.
- **Защита от перегрузки:** сервер сам контролирует темп сбора и не может быть "завален" входящим трафиком от тысяч инстансов.
- **Простота отладки:** эндпоинты метрик (например, `/metrics`) доступны для ручной проверки обычным браузером или `curl`.
- **Service Discovery:** идеально подходит для сред с динамическим обнаружением сервисов (Kubernetes, Consul). Подробнее о принципах работы см. в [обзоре Service Discovery](../service-discovery-overview.md).
- **Автоматическое обнаружение "мертвых" целей:** метрика `up == 0` доступна мгновенно (при Push-модели это непонятно -- приложение молчит или просто нет трафика).

**Эволюция в 2026:** В Prometheus 3.x скрейпинг поддерживает **Native Histograms** (высокоточные перцентили без взрывного роста кардинальности), метаданные в формате UTF-8 и OpenMetrics с Exemplars.

**Когда использовать Pull-модель:**
- Статическая или динамическая среда с HTTP-эндпоинтами (Kubernetes, VM-кластеры).
- Требуется централизованный контроль частоты сбора и потребления ресурсов.
- Важна возможность "увидеть" метрики через браузер (`curl http://target:8080/metrics`).

**Когда НЕ использовать:**
- Источники за NAT/Firewall без входящего доступа ( Push или Hybrid).
- Задачи, завершающиеся быстрее интервала скрейпинга ( Pushgateway или Push).
- Протоколы, отличные от HTTP (MQTT, gRPC) --requires Push или Collector.

### 2. Push-модель (Native Ingest)

Приложение или специализированный агент инициирует сетевое соединение и отправляет пакеты данных на сервер сбора.

**Характеристики:**
- **Работа за NAT:** источникам данных достаточно иметь исходящий доступ в интернет или корпоративную сеть.
- **Serverless и Batch:** единственный способ мониторинга короткоживущих функций (AWS Lambda) или задач, которые завершаются быстрее интервала опроса.
- **Native OTLP Ingest:** В 2026 году TSDB (Prometheus, VictoriaMetrics) принимают данные напрямую по протоколу OTLP (gRPC/HTTP), что устраняет необходимость в промежуточных экспортерах.
- **Real-time:** данные отправляются сразу после возникновения события (актуально для StatsD -- текстового протокола поверх UDP для сверхбыстрой передачи счетчиков).

**Недостатки:**
- **Риск "шторма" входящих данных** при резком росте нагрузки (Backpressure).
- **Сложность контроля целостности данных:** если приложение молчит, непонятно -- оно упало или просто нет трафика (в Pull-модели это решается метрикой `up`).
- **Дублирование данных:** если приложение отправляет данные с двух инстансов, возможны дубли (Pull-модель ограничивает это расписанием).

### 3. Гибридный подход и Remote Write 2.0

Локальный легковесный агент (vmagent, Grafana Alloy, OTel Collector) собирает метрики методом **Pull**, агрегирует их, сжимает и отправляет по протоколу **Remote Write 2.0** (Push) в центральное хранилище.

**Преимущества 2026 года:**
- **String Interning (RW 2.0):** Повторяющиеся имена меток передаются как короткие ID, что снижает трафик на **60%** и потребление RAM на **90%**.
- **OTLP/Arrow:** Использование колоночного сжатия Apache Arrow для передачи телеметрии снижает нагрузку на сеть в 5-10 раз.
- **Надежность (WAL):** Агенты используют локальный буфер на диске (Write Ahead Log), гарантируя доставку данных (At-least-once) даже при длительных обрывах связи.
- **Безопасность:** центральное хранилище не нуждается в доступе ко всем сегментам сети, достаточно разрешить входящий трафик от доверенных агентов.

### 4. Сбор из логов (Log-to-Metrics)

Генерация метрик из текстовых логов с помощью агента (Vector, Fluent Bit, Loki Log Pipeline). Используется для Legacy-приложений без нативной поддержки метрик или для генерации бизнес-метрик (количество ошибок оплаты, частота特定ных событий).

**Преимущества:**
- Не требует изменений кода приложения.
- Позволяет генерировать метрики из "старых" лог-форматов (Apache Combined, syslog).
- Централизованное управление правилами парсинга.

**Недостатки:**
- Задержка (latency) между событием и появлением метрики ( зависит от частоты анализа логов).
- Зависимость от качества парсинга (логи без структуры сложны для анализа).
- Дополнительная нагрузка на агент.

**Подробнее:** [Методологии мониторинга: Log-to-Metrics](./monitoring_methodologies.md).

### Сравнительный анализ моделей

| Критерий | Pull (Scraping) | Push (OTLP/StatsD) | Remote Write 2.0 (Hybrid) | Log-to-Metrics |
| :--- | :--- | :--- | :--- | :--- |
| **Инициатор** | Сервер | Источник | Агент | Агент |
| **Сетевой поток** | Входящий к источнику | Исходящий от источника | Исходящий от агента | Исходящий от агента |
| **Контроль нагрузки** | **Максимальный** | Низкий (на клиенте) | Высокий (буфер агента) | Средний |
| **Надежность доставки** | Средняя (потеря при Down) | Низкая (без ретраев) | **Высокая (WAL/Retry)** | Средняя |
| **Сложность конфига** | Низкая | Средняя | Высокая | Средняя |
| **Основной инструмент** | Prometheus | Zabbix, StatsD, OTel SDK | VictoriaMetrics, Mimir, Alloy | Vector, Fluent Bit |
| **Задержка данных** | Интервал скрейпинга | Мгновенно | <1с (с WAL) | Зависит от частоты анализа |

---

## Практические сценарии

### Сценарий 1: Мониторинг в Kubernetes

**Рекомендуемая стратегия:** **Pull (Prometheus / vmagent)**.
Использование Kubernetes API для автоматического обнаружения подов (Service Discovery). Сбор метрик происходит по внутренней сети кластера, что минимизирует накладные расходы на сетевую связность.

**Валидация:**
1. Проверить статус целей в Prometheus UI: Status -> Targets (должны быть `UP`).
2. Выполнить `curl -s <pod_ip>:8080/metrics` для проверки доступности эндпоинта.
3. Проверить количество целей: `prometheus_sd_discovered_targets_total`.

**Пример конфигурации Prometheus с Relabeling:**

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      # Оставить только поды с аннотацией prometheus.io/scrape: "true"
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      # Подменить порт из аннотации
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}
      # Добавить namespace в лейблы
      - source_labels: [__meta_kubernetes_namespace]
        action: replace
        target_label: namespace
```

**Мета-лейблы Kubernetes SD (для Relabeling):**

| Лейбл | Описание |
| :--- | :--- |
| `__meta_kubernetes_pod_name` | Имя пода |
| `__meta_kubernetes_namespace` | Namespace |
| `__meta_kubernetes_pod_ip` | IP-адрес пода |
| `__meta_kubernetes_pod_label_<label_name>` | Лейбл пода |
| `__meta_kubernetes_pod_annotation_<annotation_name>` | Аннотация пода |
| `__meta_kubernetes_pod_container_port_number` | Порт контейнера |

### Сценарий 2: Глобальный мониторинг распределенных ЦОД

**Рекомендуемая стратегия:** **Hybrid (Remote Write 2.0)**.
В каждом дата-центре устанавливается локальный коллектор, который собирает метрики и пересылает их в единый "Monitoring Hub" через защищенный туннель.

**Валидация:**
1. Проверить метрику `prometheus_remote_storage_samples_total` (отправлено) на агенте.
2. Сравнить с `vm_rows_inserted_total` на стороне VictoriaMetrics для подтверждения отсутствия потерь.
3. Мониторить `prometheus_remote_storage_samples_retried_total` (повторные отправки).

**Пример конфигурации vmagent с Remote Write:**

```yaml
# /etc/victoriametrics/vmagent.yml
scrape_configs:
  - job_name: 'node-exporters'
    static_configs:
      - targets: ['dc1-node1:9100', 'dc1-node2:9100']
    scrape_interval: 15s

remote_write:
  - url: "http://victoriametrics-cluster:8480/insert/0/prometheus/api/v1/write"
    queue_config:
      max_samples_per_send: 10000
      batch_send_deadline: 5s
      max_shards: 30
    tls_config:
      cert_file: /etc/vmagent/tls/client.crt
      key_file: /etc/vmagent/tls/client.key
```

**Мониторинг качества Remote Write:**

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `vmagent_remotewrite_queues_filled_percentage` | Заполнение очереди отправки | >80% -- тревога |
| `vmagent_remotewrite_dropped_rows_total` | Потерянные строки | >0 -- критично |
| `prometheus_remote_storage_samples_retried_total` | Повторные попытки | Рост -- проблема с сетью |

### Сценарий 3: IoT и Edge Computing

**Рекомендуемая стратегия:** **Push (OTLP / MQTT)**.
Устройства с нестабильным каналом связи самостоятельно отправляют телеметрию по мере доступности сети.

**Валидация:**
1. Отправить тестовую метрику через `otel-cli`: `otel-cli metric counter --name device_health --value 1`.
2. Убедиться в появлении данных в Grafana Explore.
3. Проверить логи OTLP-ресивера на наличие ошибок декодирования.

**Пример: MQTT Bridge для OTLP:**

```
[MQTT Broker] <--отправка--> [OTLP Collector with MQTT Receiver] --remote_write--> [TSDB]
```

### Сценарий 4: Сбор бизнес-метрик из логов (Log-to-Metrics)

Используется для Legacy-приложений. Агент (Vector, Fluent Bit) анализирует Access Logs и генерирует метрики `http_requests_total`.

**Пример конфигурации Vector для Log-to-Metrics:**

```toml
# vector.toml
[sources.apache_logs]
type = "file"
include = ["/var/log/apache2/access.log"]
read_from = "beginning"

[transforms.parse_access_log]
type = "remap"
inputs = ["apache_logs"]
source = '''
  . = parse_apache_combined!(.message)
'''

[transforms.log_to_metrics]
type = "log_to_metrics"
inputs = ["parse_access_log"]
metrics:
  - type: "counter"
    field: "status"
    name: "http_requests_total"
    tags:
      method: "{{ method }}"
      status: "{{ status }}"
      path: "{{ path }}"

[sinks.prometheus_export]
type = "prometheus_exporter"
inputs = ["log_to_metrics"]
address: "0.0.0.0:9598"
```

**Валидация:**
1. Проверить логи агента на наличие ошибок парсинга (`parse_errors_total`).
2. Выполнить запрос к приложению и убедиться в инкременте счетчика: `curl http://localhost:9598/metrics | grep http_requests_total`.

### Сценарий 5: Краткоживущие задачи (Batch Jobs)

**Рекомендуемая стратегия:** **Push (Prometheus Pushgateway)**.
Задачи, которые завершаются быстрее стандартного интервала скрейпинга (15-30с), не могут быть пойманы Pull-моделью.

**Пример конфигурации Pushgateway:**

```bash
# Задача отправляет метрику по завершении
echo "batch_job_duration_seconds 42.5" | \
  curl --data-binary @- http://pushgateway:9091/metrics/job/batch_etl/instance/worker01

# Пример с таймстемпом и лейблами
echo "# TYPE batch_processed_rows counter
batch_processed_rows{job=\"etl\",table=\"users\"} 1500" | \
  curl --data-binary @- http://pushgateway:9091/metrics/job/batch_etl/instance/worker01
```

**Валидация:**
1. Открыть Pushgateway UI: `http://pushgateway:9091/#/metrics`.
2. Проверить появление метрики в Prometheus: `batch_processed_rows{job="batch_etl"}`.

**Важно:** Pushgateway не должен использоваться для приложений с длительным временем жизни -- используйте Push (OTLP) или Pull (Prometheus) напрямую.

### Сценарий 6: Сбор метрик через OTel Collector

**Рекомендуемая стратегия:** **Hybrid (OTel Collector as Agent)**.
OTel Collector выступает в роли унифицированного агента, принимающего данные по OTLP (Push) и экспортирующих в TSDB через Remote Write или OTLP.

**Пример конфигурации OTel Collector (config.yaml):**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 10000
  memory_limiter:
    check_interval: 5s
    limit_mib: 512
    spike_limit_mib: 128
  resource:
    attributes:
      - key: environment
        value: production
        action: upsert

exporters:
  prometheusremotewrite:
    endpoint: "http://victoriametrics:8480/insert/0/prometheus/api/v1/write"
    resource_to_telemetry_conversion:
      enabled: true
  debug:
    verbosity: detailed

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch, resource]
      exporters: [prometheusremotewrite, debug]
```

**Валидация:**
1. Проверить логи OTel Collector на наличие ошибок отправки.
2. Убедиться в появлении метрик в VictoriaMetrics/Prometheus.
3. Проверить потребление памяти: `otelcol_process_runtime_memory_alloc_bytes`.

---

## Управление кардинальностью при сборе

**Кардинальность (Cardinality)** -- количество уникальных комбинаций лейблов у метрики. Высокая кардинальность (миллионы рядов) -- основная причина переполнения TSDB и роста стоимости хранения.

### Причины взрыва кардинальности

| Источник | Пример | Проблема |
| :--- | :--- | :--- |
| **User ID / Session ID** | `http_requests_total{user_id="u-1234567"}` | 1M+ уникальных значений |
| **Request ID / Trace ID** | `http_requests_total{trace_id="abc..."}` | Уникальны для каждого запроса |
| **Timestamp** | `log_entries_total{timestamp="2026-08-27T14:32:01Z"}` | Каждый лог -- уникальный лейбл |
| **Высокочастотные логи** | `app_events_total{message="Connection refused"}` | Текстовые сообщения как лейблы |

### Методы контроля кардинальности

**1. Relabeling на этапе скрейпинга (Prometheus):**

```yaml
scrape_configs:
  - job_name: 'high-cardinality-app'
    metric_relabel_configs:
      # Удалить высококардинальные лейблы
      - source_labels: [__name__]
        regex: 'http_requests_total'
        target_label: user_id
        action: labeldrop
      # Оставить только нужные комбинации
      - source_labels: [user_id]
        regex: '.*'
        action: labeldrop
```

**2. Relabeling на этапе отправки (Vector):**

```toml
[transforms.drop_high_cardinality]
type = "remap"
inputs = ["raw_metrics"]
source = '''
  # Удалить лейбл trace_id если он существует
  del(.trace_id)
  del(.request_id)
'''
```

**3. Использование Structured Metadata (Loki 3.x):**
Для логов -- уникальные значения (session_id, user_id) хранятся как метаданные, а не как лейблы, что позволяет фильтровать и искать по ним без увеличения индекса.

**Подробнее:** [Метки и кардинальность (Prometheus)](../../Prometheus/concepts/labels_and_cardinality.md).

---

## Безопасность сбора метрик

### Транспортная безопасность

| Протокол | Шифрование | Аутентификация | Когда использовать |
| :--- | :--- | :--- | :--- |
| **HTTP (Pull)** | TLS (HTTPS) | Basic Auth, mTLS | Скрейпинг по внутренней сети |
| **gRPC (OTLP)** | TLS | Token, mTLS | Отправка между ЦОД |
| **Remote Write** | TLS | Token, OIDC (v2.0) | Агент -> центральное хранилище |
| **UDP (StatsD)** | Нет | Нет | Только для внутренних сред |

### Пример: TLS при скрейпинге (Prometheus)

```yaml
scrape_configs:
  - job_name: 'secure-targets'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/ca.crt
      cert_file: /etc/prometheus/client.crt
      key_file: /etc/prometheus/client.key
      insecure_skip_verify: false  # В проде всегда false
    basic_auth:
      username: prometheus
      password_file: /etc/prometheus/password
```

### Пример: mTLS для Remote Write (Prometheus 3.x)

```yaml
remote_write:
  - url: "https://mimir.example.com/api/v1/push"
    tls_config:
      cert_file: /etc/prometheus/tls/client.crt
      key_file: /etc/prometheus/tls/client.key
      ca_file: /etc/prometheus/tls/ca.crt
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/token
```

**Подробнее:** [Безопасность Prometheus](../../Prometheus/security.md).

---

## Настройка интервалов сбора

### Рекомендации по scrape_interval

| Тип метрик | Интервал | Обоснование |
| :--- | :--- | :--- |
| **HTTP-запросы (API)** | 10-15с | Баланс между точностью и нагрузкой. |
| **Системные метрики (CPU, RAM)** | 15-30с | Медленные процессы,足够的 granularity. |
| **Метрики БД (connection pool)** | 15-30с | Не меняются чаще. |
| **Бизнес-метрики (orders/sec)** | 15-60с | Зависит от скорости бизнес-процессов. |
| **Внешние проверки (Blackbox)** | 30-60с | Проверки доступности, не требуют sub-second. |
| **Kubernetes Pod** | 30s | Динамическая среда, но 30s достаточно для большинства случаев. |

### Формула выбора scrape_interval

```
scrape_interval >= max(
  min_actionable_interval,     # Минимальный интервал, при котором алерт имеет смысл
  target_response_time * 10,    # Не скрейпить быстрее, чем 10x время ответа
  network_rtt * 100            # Учет сетевой задержки для больших расстояний
)
```

**Практическое правило:** `scrape_timeout` должен быть в 2-3 раза меньше `scrape_interval`, чтобы избежать перекрытия скрейпингов.

### Влияние scrape_interval на ресурсы

| Интервал | Целей (на 1 инстанс Prometheus) | RAM (approx.) | Disk (30 дней) |
| :--- | :--- | :--- | :--- |
| **15s** | ~10,000 | ~8 GB | ~50 GB |
| **30s** | ~20,000 | ~4 GB | ~25 GB |
| **60s** | ~40,000 | ~2 GB | ~12 GB |

---

## Горизонтальное масштабирование сбора

### Шардирование (Sharding) скрейпинга

При количестве целей >10,000 один инстанс Prometheus не справляется со скрейпингом. Решение -- распределение целей между несколькими инстансами.

**Методы шардирования:**

1. **Prometheus Operator (Kubernetes):** параметр `spec.shards` в ресурсе `Prometheus`.
2. **Hashmod Relabeling:** консистентное хэширование целей по `__address__` с распределением по N шардам.
3. **Внешние агенты:** vmagent / Grafana Alloy с балансировкой между инстансами.

**Пример hashmod-шардирования (2 шарда):**

```yaml
# Shard 0
scrape_configs:
  - job_name: 'sharded'
    relabel_configs:
      - source_labels: [__address__]
        modulus: 2
        target_label: __tmp_hash
        action: hashmod
      - source_labels: [__tmp_hash]
        regex: 0
        action: keep

# Shard 1 -- аналогично, с regex: 1
```

### Federation для глобального представления

**Federation** -- механизм агрегации метрик с нескольких Prometheus-серверов в один.

```yaml
# Конфигурация федерального Prometheus
scrape_configs:
  - job_name: 'federation'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{job=~".+"}'  # Все метрики с job
        - 'up'           # Метрика доступности
    static_configs:
      - targets:
          - 'prometheus-dc1:9090'
          - 'prometheus-dc2:9090'
```

**Подробнее:** [Масштабирование Prometheus](../../Prometheus/scaling/overview.md).

---

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ingestion Lag (Задержка)** | Очередь в Remote Write или медленная индексация. | Увеличить количество шардов отправки (`max_shards`). Проверить IOPS хранилища. |
| **Data Gaps (Пропуски)** | Интервал скрейпинга больше времени жизни пода. | Уменьшить `scrape_interval` до 5-15с или перейти на Push-модель. |
| **Backpressure** | Агент не успевает отправлять данные, буфер полон. | Увеличить лимиты RAM агента. Включить дисковую буферизацию (disk-backed queue). |
| **Scrape Timeout** | Приложение долго генерирует страницу `/metrics`. | Оптимизировать код экспортера. Увеличить `scrape_timeout` в конфиге Prometheus. |
| **Stale Targets (Залипшие цели)** | Цель перестала отвечать, но не удалена из конфига. | Проверить Service Discovery. Использовать `relabel_configs` с `action: keep` по меткам. |
| **High Cardinality (Высокая кардинальность)** | Лейблы с уникальными значениями (user_id, request_id). | Удалить лейблы через `metric_relabel_configs`. Использовать Structured Metadata (Loki). |
| **Duplicate Metrics (Дублирование)** | Два Prometheus скрейпят одну цель (при HA без dedup). | Включить deduplication: `-dedup.minScrapeInterval` (VictoriaMetrics) или Thanos Query. |
| **OTLP Connection Refused** | OTel Collector не принимает данные. | Проверить endpoint (`0.0.0.0:4317` vs `127.0.0.1:4317`). Убедиться в наличии `receivers` в конфиге. |
| **Remote Write 401/403** | Ошибка аутентификации при отправке. | Проверить токен/сертификат. Убедиться в наличии `authorization` блока в `remote_write`. |

---

## Протоколы передачи данных

### Сравнение протоколов

| Протокол | Транспорт | Формат | Сжатие | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus Text** | HTTP | Текст | gzip | Pull-модель, совместимость с Prometheus. |
| **OpenMetrics** | HTTP | Текст (расширенный) | gzip | Pull + Native Histograms, Exemplars. |
| **OTLP/gRPC** | gRPC | Protobuf | gzip, zstd | Push/Pull, все сигналы (метрики, логи, трейсы). |
| **OTLP/HTTP** | HTTP | Protobuf | gzip, zstd | Push/Pull, ограниченные сети. |
| **OTLP/Arrow** | gRPC | Apache Arrow | Colocated | Высокопроизводительная передача (5-10x сжатие). |
| **Remote Write 1.0** | HTTP | Protobuf | snappy | Агент -> TSDB (legacy, все еще поддерживается). |
| **Remote Write 2.0** | HTTP | Protobuf | zstd | Агент -> TSDB (String Interning, -60% трафика). |
| **StatsD** | UDP/TCP | Текст | Нет | Сверхбыстрые счетчики (без guarantee доставки). |

### Рекомендации по выбору

1. **Для новых проектов:** OTLP/gRPC или Remote Write 2.0.
2. **Для существующих Prometheus:** Remote Write 2.0 (совместимость с v2.x и v3.x).
3. **Для короткоживущих задач:** Pushgateway + Remote Write 2.0.
4. **Для IoT/Edge:** OTLP/HTTP (максимальная совместимость с прокси/файрволами).

---

## Дополнительная информация

### Метамониторинг (Meta-Monitoring)

Сбор метрик о самом процессе сбора -- критически важен для обнаружения потерь данных.

| Метрика | Описание | Инструмент |
| :--- | :--- | :--- |
| `up` | Доступность цели скрейпинга | Prometheus |
| `prometheus_scrape_duration_seconds` | Время скрейпинга | Prometheus |
| `vmagent_remotewrite_queues_filled_percentage` | Заполнение очереди отправки | vmagent |
| `otelcol_exporter_send_failed_spans` | Ошибки отправки OTel | OTel Collector |

**Подробнее:** [Meta-Monitoring](./meta-monitoring.md).

### См. также

- **[Метрики: детали](./metrics_deep_dive.md)** -- типы данных, Native Histograms, PromQL.
- **[Проектирование высоконагруженного мониторинга](./designing_high-load_monitoring_in_distributed_systems.md)** -- архитектура для больших данных.
- **[Концепции SRE: SLA, SLO, SLI](../sre_concepts_main.md)** -- метрики как основа для SLO.
