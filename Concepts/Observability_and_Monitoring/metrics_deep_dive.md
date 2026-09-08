# Метрики: глубокое погружение

## Определения

**Метрики (Metrics)** — числовое представление данных о состоянии, работоспособности и поведении системы, собираемых через регулярные промежутки времени в виде **временных рядов** (time series). Они агрегируют атомарные события, превращая их в статистические показатели, пригодные для визуализации, анализа трендов и автоматического оповещения.

**Временной ряд (Time Series)** — последовательность значений одной метрики, идентифицируемая уникальным именем и набором меток (labels). Пример: `http_requests_total{method="POST", code="200"}`.

**Назначение:**
- **Проактивный мониторинг:** Выявление деградации системы до наступления инцидента.
- **Оптимизация затрат (FinOps):** Анализ использования ресурсов для точного сайзинга инфраструктуры.
- **SLA/SLO/SLI:** Количественная оценка надежности сервисов. Подробнее в разделе **[Концепции SRE: SLA, SLO, SLI](../sre_concepts_main.md)**.
- **Observability 2.0:** Использование метрик как первого этапа диагностики с последующим переходом к **[трассировкам](./traces_deep_dive.md)** через механизмы **Exemplars**.

**Ключевой принцип:** Метрики обеспечивают максимальную масштабируемость и скорость обработки за счет потери детализации отдельных запросов (контекста), которую восполняют логи и трейсы.

**См. также:** [Четыре столпа Observability](./four_pillars_of_observability.md) — фундаментальные концепции наблюдаемости.

## Базовые концепции

### Типы метрик (Prometheus & OpenTelemetry)

В современной инфраструктуре выделяют пять основных типов данных:

| Тип | Описание | Особенности |
| :--- | :--- | :--- |
| **Counter (Счётчик)** | Значение только растёт | Используется для подсчёта событий (запросы, ошибки). Применяется с функцией `rate()`. |
| **Gauge (Измеритель)** | Текущее значение («термометр») | Может расти и уменьшаться (температура, использование RAM, размер очереди). |
| **Histogram (Гистограмма)** | Распределение по бакетам | Традиционные гистограммы требуют ручной настройки границ (buckets), что порождает высокую кардинальность. |
| **Native Histograms** | Гистограммы с плавающей сеткой | **Стандарт 2026 года.** Используют экспоненциальные бакеты. Снижают кардинальность и повышают точность перцентилей без ручной настройки. |
| **Summary** | Квантили на стороне клиента | Точны для одного процесса, но **не подлежат агрегации** между несколькими инстансами. |

### Модели сбора данных (Ingestion Models)

Выбор модели влияет на сетевую топологию и надежность доставки:
1.  **Pull (Скрейпинг):** Сервер мониторинга сам опрашивает эндпоинты приложений.
    - **Плюсы:** Контроль нагрузки на стороне сервера, легкое обнаружение "живых" целей (метрика `up`).
    - **Минусы:** Требует прямой сетевой видимости от сервера к подам.
2.  **Push:** Приложение само отправляет данные в коллектор или шлюз (Pushgateway).
    - **Плюсы:** Работает за NAT/Firewall, подходит для короткоживущих задач (Batch jobs).
    - **Минусы:** Риск перегрузки коллектора всплеском трафика.
3.  **Remote Write:** Агент (Prometheus Agent, Grafana Alloy) собирает данные локально и пересылает их пачками в центральное хранилище. Оптимально для высоконагруженных систем.

### Жизненный цикл метрик (Metrics Lifecycle)

Управление объемом данных требует стратегии хранения:
- **Ingestion:** Прием сырых данных с высоким разрешением (например, каждые 15 сек).
- **Rollup / Downsampling:** Агрегация старых данных в более крупные интервалы (например, 1 точка в минуту через 30 дней) для экономии места.
- **Retention:** Удаление данных по истечении срока (обычно 15-30 дней для сырых метрик, годы для агрегированных).

### Характеристики метрик

| Характеристика | Описание | Следствие |
| :--- | :--- | :--- |
| **Масштабируемость** | Константный объем данных на ряд | Подходят для систем с миллионами RPS. |
| **Эффективность transport** | **OTLP/Arrow** | В 2026 году метрики передаются через Apache Arrow, что снижает потребление сети в 5-10 раз. |
| **Корреляция** | **Exemplars** | Прямая ссылка из точки на графике метрики на конкретный `trace_id`. |
| **UTF-8 Support** | Поддержка любых символов | В Prometheus 3.x и VictoriaMetrics метрики могут содержать точки, дефисы и спецсимволы (совместимость с OTel). |

### Управление кардинальностью (Cardinality)

**Кардинальность** — количество уникальных временных рядов, порождаемых комбинациями лейблов (labels).

**Взрыв кардинальности (Cardinality Explosion):**
Добавление уникальных ID (user_id, session_id, IP-адрес) в лейблы приводит к лавинообразному росту потребления RAM в TSDB и замедлению всех запросов.

**Методы борьбы:**
- **Relabeling:** Удаление или агрегация "тяжелых" лейблов на этапе сбора.
- **Recording Rules:** Предварительное вычисление тяжелых запросов в новые метрики с меньшей кардинальностью.
- **Ограничения (Limits):** Установка лимитов на количество серий (Series Limit) на уровне таргета в Prometheus.
- **Инструментарий:** Для анализа «пухлых» метрик используйте `promtool tsdb analyze` или нативные панели Cardinality Explorer в VictoriaMetrics. Для проактивного обнаружения всплесков в реальном времени используйте [vmestimator](../../VictoriaMetrics/vmestimator.md).

## Практические сценарии

### Сценарий 1: Инструментирование через OpenTelemetry (Python)

В 2026 году рекомендуется использовать OTel SDK для отправки метрик напрямую в коллектор или Prometheus 3.x.

```python
from opentelemetry import metrics

# Получаем счетчик
meter = metrics.get_meter("order-service")
order_counter = meter.create_counter(
    "orders_total",
    description="Total number of processed orders",
    unit="1"
)

def process_order(customer_type):
    # Бизнес-логика
    order_counter.add(1, {"customer.type": customer_type, "env": "prod"})
```

**Валидация:**
1. Запустить приложение и выполнить несколько заказов.
2. Проверить наличие метрики в Prometheus: `orders_total{env="prod"}`.
3. Убедиться, что значение соответствует количеству выполненных заказов.

### Сценарий 2: Развертывание инфраструктурного мониторинга (Docker)

Использование Node Exporter v1.12.x в Docker Compose с поддержкой новых метаданных.

```yaml
services:
  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: node-exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    deploy:
      resources:
        limits:
          memory: 128M
```

**Валидация:**
1. Выполнить `docker compose up -d`.
2. Проверить доступность эндпоинта: `curl -s localhost:9100/metrics | grep node_cpu_seconds_total`.

### Сценарий 3: Настройка Native Histograms в Prometheus 3.x

Для включения высокоточных гистограмм в конфигурации скрейпинга:

```yaml
scrape_configs:
  - job_name: 'api-service'
    native_histograms: true # Включение сбора экспоненциальных бакетов
    static_configs:
      - targets: ['api:8080']
```

**Валидация:**
1. Проверить в веб-интерфейсе Prometheus (Status -> Targets), что таргет опрашивается успешно.
2. Выполнить запрос `http_request_duration_seconds` (без суффикса `_bucket`). Вы должны увидеть сложный объект с множеством бакетов.

### Сценарий 4: PromQL для алертинга (Common Patterns)

Использование стандартных паттернов для обнаружения проблем:

1.  **Скорость ошибок (Error Rate):**
    `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05`
2.  **Задержка (p99 Latency) через Native Histograms:**
    `histogram_quantile(0.99, rate(http_request_duration_seconds[5m])) > 2`

### Сценарий 5: FinOps: Поиск дорогих метрик

Выявление метрик, занимающих больше всего места в памяти:
`topk(10, count by (__name__) ({__name__=~".+"}))` — в VictoriaMetrics / Prometheus для анализа кардинальности по именам метрик.

### Сценарий 6: Мониторинг инфраструктуры с помощью Prometheus и Node Exporter (bare-metal)

**Задача:** Настроить мониторинг физических серверов без использования Kubernetes.

**Конфигурация Prometheus для bare-metal:**
```yaml
# /etc/prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "node_rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['server1:9100', 'server2:9100', 'server3:9100']
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.+):(.+)'
        target_label: instance
        replacement: '${1}'
        
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Правила алертинга для bare-metal (node_rules.yml):**
```yaml
groups:
- name: node-alerts
  rules:
  - alert: NodeDown
    expr: up{job="node"} == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Node {{ $labels.instance }} is down"
      
  - alert: HighCPU
    expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High CPU on {{ $labels.instance }}: {{ $value }}%"
      
  - alert: DiskSpaceLow
    expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 20
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Low disk space on {{ $labels.instance }}: {{ $value }}% free"
```

**Валидация:**
1. Запустить Prometheus: `prometheus --config.file=/etc/prometheus/prometheus.yml`
2. Проверить цели: `curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="node")'`
3. Выполнить запрос: `node_cpu_seconds_total{instance="server1:9100"}`

### Сценарий 7: Recording Rules для оптимизации сложных запросов

**Задача:** Оптимизировать сложные PromQL запросы, которые нагружают Prometheus при визуализации.

**Создание Recording Rules:**
```yaml
groups:
- name: node-recording-rules
  interval: 30s
  rules:
  - record: node:cpu_utilization:ratio
    expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
    
  - record: node:memory_utilization:ratio
    expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
    
  - record: node:disk_utilization:ratio
    expr: (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100
```

**Использование в Grafana:**
```promql
# Вместо сложного запроса:
100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Использовать простой запрос с recording rule:
node:cpu_utilization:ratio
```

**Валидация:**
1. Загрузить правила: `promtool check rules node_rules.yml`
2. Проверить в Prometheus: `node:cpu_utilization:ratio`
3. Сравнить производительность запросов (должно быть быстрее)

### Сценарий 8: Настройка Remote Write для горизонтального масштабирования

**Задача:** Масштабировать систему мониторинга с использованием Remote Write.

**Архитектура:**
```
Prometheus (сбор) → Remote Write → VictoriaMetrics (хранение)
     ↓
  Alertmanager (алерты)
```

**Конфигурация Prometheus с Remote Write:**
```yaml
# /etc/prometheus/prometheus.yml
global:
  scrape_interval: 15s

remote_write:
  - url: "http://victoriametrics:8428/api/v1/write"
    queue_config:
      max_samples_per_send: 10000
      batch_send_deadline: 5s
      max_shards: 30
      capacity: 10000
    write_relabel_configs:
      - source_labels: [__name__]
        regex: 'node_.*'
        action: keep
```

**Валидация:**
1. Проверить метрики Remote Write: `prometheus_remote_storage_samples_total`
2. Мониторить очередь: `prometheus_remote_storage_queue_length`
3. Проверить данные в VictoriaMetrics: `http_requests_total{job="node"}`

### Сценарий 9: Мета-мониторинг пайплайна метрик

**Задача:** Обеспечить мониторинг самого Prometheus и пайплайна метрик.

**Ключевые метрики для мета-мониторинга Prometheus:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `prometheus_tsdb_head_series` | Количество активных серий | > 10M (cardinality explosion) |
| `prometheus_tsdb_head_chunks` | Количество чанков в памяти | > 50M (high memory usage) |
| `prometheus_scrape_duration_seconds` | Длительность скрейпинга | > scrape_interval |
| `prometheus_config_last_reload_successful` | Последняя перезагрузка конфига | == 0 (config reload failed) |
| `prometheus_notifications_queue_length` | Длина очереди алертов | > 100 (alerting pipeline stuck) |

**Алерт-правило для мета-мониторинга:**
```yaml
groups:
- name: prometheus-meta-monitoring
  rules:
  - alert: PrometheusHighMemory
    expr: process_resident_memory_bytes / (1024*1024) > 4000
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Prometheus memory usage > 4GB"
      
  - alert: PrometheusHighScrapeDuration
    expr: prometheus_scrape_duration_seconds > 15
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Prometheus scrape duration > 15s"
      
  - alert: PrometheusConfigReloadFailed
    expr: prometheus_config_last_reload_successful == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Prometheus config reload failed"
```

**Валидация:**
1. Проверить метрики: `curl -s http://localhost:9090/metrics | grep prometheus_`
2. Мониторить использование памяти: `process_resident_memory_bytes`
3. Проверить состояние TSDB: `prometheus_tsdb_head_series`

### Сценарий 10: Интеграция метрик с логами через Exemplars

**Задача:** Связать метрики с конкретными примерами ошибок в логах.

**Конфигурация Exemplars в OTel SDK (Python):**
```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import Counter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# Создание счетчика с поддержкой Exemplars
error_counter = meter.create_counter(
    "http_requests_total",
    description="Total HTTP requests",
    unit="1"
)

# Добавление Exemplar к метрике
error_counter.add(
    1,
    attributes={"http.status_code": 500, "http.method": "GET"},
    exemplars={"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"}
)
```

**Результат:**
1. На графике в Grafana видна точка с ошибкой
2. Клик по точке открывает трассировку с полным контекстом
3. Корреляция метрик → трассировок → логов

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Пропуски на графиках (Gaps)** | Медленный скрейпинг или падение агента | Проверить метрики `up` и `scrape_duration_seconds`. Увеличить таймаут скрейпинга. |
| **Cardinality Explosion** | Динамические значения в лейблах | Удалить лейблы с высокой кардинальностью через `relabel_config`. Включить лимиты на серии. |
| **Медленные запросы (Slow Queries)** | Сложные Regex или огромные диапазоны времени | Использовать Recording Rules для предварительной агрегации. Проверить индексы в TSDB. |
| **Stale Data (Залипшие данные)** | Ошибка Remote Write или завершение процесса без удаления метрики | Проверить логи `vmagent` или Prometheus. Использовать `keep-alive` настройки. |
| **Высокое потребление RAM** | Много активных серий или сложные запросы | Оптимизировать лейблы, использовать Recording Rules, увеличить память сервера. |
| **Медленные скрейпы** | Много метрик на целевом эндпоинте | Разделить scrape_configs, увеличить parallelism, оптимизировать экспортер. |
| **Проблемы с Remote Write** | Сетевые задержки или проблемы с очередью | Проверить метрики `prometheus_remote_storage_samples_total`, оптимизировать queue_config. |
| **Дублирование метрик** | Несколько Prometheus опрашивают одни цели | Использовать иерархическую federation или оптимизировать scrape_configs. |
| **Проблемы с Alertmanager** | Потеря алертов или ложные срабатывания | Проверить метрики `prometheus_notifications_queue_length`, оптимизировать правила. |
| **Сломанные Recording Rules** | Ошибка в PromQL запросе | Проверить синтаксис: `promtool check rules rules.yml`. |
| **Высокая задержка TSDB** | Много данных или медленный диск | Оптимизировать retention, использовать SSD, оптимизировать compaction. |
| **Проблемы с кардинальностью** | Уникальные ID в лейблах | Удалить dynamic labels, использовать aggregation, настроить limits. |

### Диагностические команды

```bash
# Prometheus: проверка конфигурации
promtool check config /etc/prometheus/prometheus.yml

# Prometheus: проверка правил
promtool check rules /etc/prometheus/rules/*.yml

# Prometheus: проверка TSDB
promtool tsdb analyze /path/to/tsdb

# Prometheus: проверка запросов
promtool query instant http://localhost:9090 'up'

# VictoriaMetrics: проверка данных
curl -s http://localhost:8428/api/v1/query?query=http_requests_total

# VictoriaMetrics: проверка кардинальности
curl -s http://localhost:8428/api/v1/label/__name__/values | jq 'length'

# Node Exporter: проверка метрик
curl -s localhost:9100/metrics | grep node_cpu_seconds_total

# Alertmanager: проверка состояния
curl -s http://localhost:9093/api/v2/alerts | jq 'length'

# kubectl: диагностика Prometheus
kubectl get pods -n monitoring -l app=prometheus
kubectl logs -n monitoring -l app=prometheus --tail=100

# Проверка Remote Write
curl -s http://localhost:9090/api/v1/query?query=prometheus_remote_storage_samples_total
```

## Дополнительная информация

### Методологии мониторинга

1.  **RED (для Сервисов):** **R**equests, **E**rrors, **D**uration.
2.  **USE (для Ресурсов):** **U**tilization, **S**aturation, **E**rrors.
3.  **Four Golden Signals (Google SRE):** Latency, Traffic, Errors, Saturation.

### Экономика и оптимизация (Cost Optimization)

- **Native Histograms vs Traditional:** Переход на Native Histograms в Prometheus 3.x экономит до 40% дискового пространства за счет отказа от множества отдельных временных рядов для каждого бакета.
- **Remote Write 2.0:** Используйте Remote Write 2.0 для передачи метрик в VictoriaMetrics или Grafana Mimir — это снижает накладные расходы на метаданные.
- **Retention Policies:** Настраивайте агрегацию (downsampling) в VictoriaMetrics для хранения исторических данных с меньшей детализацией.

### Лучшие практики

1.  **Единицы измерения:** Всегда используйте базовые единицы (seconds, bytes). Добавляйте суффикс к имени метрики (`request_duration_seconds`).
2.  **Доступность:** Метрика `up` генерируется самим Prometheus — используйте её для базовых алертов о падении сервиса.
3.  **Лейблы:** Не используйте более 10-15 лейблов на одну метрику.
4.  **Exemplars:** Включайте передачу `trace_id` в метриках для мгновенного перехода к трассировкам при обнаружении аномалий на графике.
5.  **Recording Rules:** Используйте для оптимизации сложных запросов, которые выполняются часто.
6.  **Валидация конфигурации:** Регулярно проверяйте конфигурацию с помощью `promtool check config`.
7.  **Мониторинг пайплайна:** Настройте мета-мониторинг для самого Prometheus и компонентов пайплайна.
8.  **Версионирование правил:** Храните recording rules и alerting rules в Git для отслеживания изменений.
9.  **Тестирование алертов:** Регулярно проверяйте, что алерты срабатывают корректно.
10. **Документирование метрик:** Ведите каталог метрик с описанием их назначения и использования.

### Чек-лист по внедрению метрик

- [ ] Определены ключевые метрики для сервисов (RED, USE, Golden Signals)
- [ ] Настроен Prometheus с оптимальными интервалами скрейпинга
- [ ] Настроены Recording Rules для сложных запросов
- [ ] Настроен Alertmanager с правилами алертинга
- [ ] Интегрированы метрики с логами и трассировками (Exemplars)
- [ ] Настроен мета-мониторинг пайплайна метрик
- [ ] Определены политики хранения (retention, downsampling)
- [ ] Настроены алерты на критические проблемы (cardinality explosion, high memory)
- [ ] Документированы метрики и их использование
- [ ] Проведено обучение команды работе с PromQL

### Архитектурные паттерны сбора метрик

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Pull (Prometheus)** | Сервер опрашивает эндпоинты | Статическая инфраструктура, Kubernetes |
| **Push (Agent)** | Агент отправляет метрики | Динамические среды, за NAT/Firewall |
| **Remote Write** | Локальный сбор + центральное хранение | Высоконагруженные системы |
| **Federation** | Иерархический сбор | Много кластеров, глобальная видимость |

### Стоимость и производительность

| Метрика | Prometheus | VictoriaMetrics | Влияние |
| :--- | :--- | :--- | :--- |
| **CPU overhead** | 1-5% | 0.5-2% | Зависит от объема данных |
| **Memory overhead** | 10-50 ГБ | 5-20 ГБ | Зависит от количества серий |
| **Storage requirements** | 1-10 ГБ/день | 0.5-5 ГБ/день | Зависит от сэмплирования |
| **Query performance** | 100 мс - 10 с | 10 мс - 1 с | Зависит от сложности запроса |

### См. также

- **[Prometheus: обзор](../../Prometheus/overview.md)** — стабильная версия 3.x LTS.
- **[VictoriaMetrics: обзор](../../VictoriaMetrics/overview.md)** — высокопроизводительное хранилище 2026 года.
- **[vmestimator](../../VictoriaMetrics/vmestimator.md)** — проактивная оценка кардинальности в реальном времени.
- **[Логи: детали](./logs_deep_dive.md)** — корреляция метрик с событиями.
- **[Трассировки: детали](./traces_deep_dive.md)** — глубокая диагностика через Exemplars.
- **[Мониторинг Node.js](../../Prometheus/Exporters/NodeJS/nodejs_monitoring.md)** — специфика мониторинга Node.js приложений.
- **[Мониторинг Kubernetes](../Observability_and_Monitoring/observability_in_containers.md)** — мониторинг в контейнерных средах.
- **[Alertmanager: обзор](../../Prometheus/alertmanager.md)** — настройка алертинга и уведомлений.
- **[Концепции SRE: SLA, SLO, SLI](../sre_concepts_main.md)** — определение уровня сервиса.
