# Compaction и Retention в Grafana Loki

## Определения

**Compactor (Компактор)** — фоновый процесс Loki, объединяющий мелкие файлы индексов (TSDB) и чанки в более крупные, удаляющий дубликаты и применяющий политики retention (удаление старых данных). Компактор работает асинхронно и критичен для поддержания производительности запросов и контроля размера хранилища.

**Retention Policy (Политика удержания)** — правило, определяющее, как долго данные хранятся в Loki и когда они удаляются. Управляется параметром `retention_period` в `limits_config`. Применяется фоновым компактором, который сканирует индекс и удаляет чанки старше указанного возраста.

**Compaction Interval (Интервал компакции)** — частота запуска процесса компакции. По умолчанию 10 минут. Меньший интервал ускоряет удаление данных и объединение файлов, но увеличивает нагрузку на CPU и сеть.

**Retention Delete Delay (Задержка удаления)** — время ожидания перед физическим удалением данных после пометки компактором. По умолчанию 2 часа. Позволяет отменить удаление при ошибке.

**Retention Delete Worker Count (Количество воркеров удаления)** — параллельные процессы, удаляющие данные из объектного хранилища. Увеличивайте при больших объемах данных (>1 ТБ/день).

**Max Query Length (Максимальная длина запроса)** — ограничение временного диапазона LogQL запроса. Должен быть больше `retention_period`, иначе исторические данные будут недоступны.

---

## Основные концепции

### Жизненный цикл данных и компакции

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Ingester   │────▶│  Flush      │────▶│  S3/GCS     │────▶│  Compactor  │
│  (чанки в   │     │  (сброс в  │     │  (хранилище)│     │  (объединение│
│   памяти)   │     │   S3)       │     │             │     │   +удаление) │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                                       │                    │
       │                                       │                    ▼
       │                                       │            ┌─────────────┐
       │                                       │            │  Удаление   │
       │                                       │            │  старых     │
       │                                       │            │  чанков     │
       │                                       │            └─────────────┘
       │                                       │
       └───────────────────────────────────────┘
              Запросы от Querier
```

### Параметры компакции и их влияние

| Параметр | Значение по умолчанию | Влияние | Рекомендация |
| :--- | :--- | :--- | :--- |
| `compaction_interval` | 10m | Частота объединения файлов | 10–30m для production; 1m для dev |
| `retention_enabled` | false | Включение автоматического удаления | **true** для production |
| `retention_delete_delay` | 2h | Задержка перед физическим удалением | 1–4h; увеличьте при большом объеме |
| `retention_delete_worker_count` | 150 | Параллельные воркеры удаления | 150–500 для >1 ТБ/день |
| `retention_period` | 0 (бессрочно) | Срок хранения данных | 7–30d для оперативных логов |
| `max_query_length` | 721h (30d) | Максимальный диапазон запроса | Должен быть > retention_period |

### Взаимосвязь retention_period и max_query_length

**Правило:** `max_query_length` должен быть как минимум на 1 час больше `retention_period`. Если `retention_period: 744h` (31 день), установите `max_query_length: 745h` или больше. Иначе пользователи не смогут запрашивать данные за весь период хранения.

### Компакция индексов (TSDB)

В Loki 3.x с TSDB Index компакция выполняет:
1. **Объединение индексных файлов:** Мелкие файлы индексов (создаваемые каждые 24 часа) объединяются в крупные.
2. **Удаление дубликатов:** При репликации (`replication_factor > 1`) одни и те же данные могут храниться в нескольких копиях. Компактор удаляет дубли.
3. **Применение retention:** Помечает чанки старше `retention_period` для удаления.
4. **Очистка объектного хранилища:** Удаляет помеченные чанки из S3/GCS.

### Компакция чанков

Компактор не объединяет чанки (в отличие от Elasticsearch force merge). Чанки создаются инжестерами и остаются неизменными. Объединение мелких чанков не требуется, так как Loki читает только необходимые для запроса чанки через индекс.

---

## Практические сценарии

### Сценарий 1: Базовая конфигурация retention (Single Binary)

```yaml
# loki.yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 30d       # Хранить логи 30 дней
  max_query_length: 721h      # Максимальный запрос — 30 дней + 1 час
  ingestion_rate_mb: 10
  max_query_series: 5000

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150

# Для filesystem retention работает только через compactor
# В production используйте S3/GCS
```

### Сценарий 2: Production retention с S3 (Simple Scalable)

```yaml
# loki.yaml (Simple Scalable mode)
auth_enabled: true

common:
  path_prefix: /loki
  storage:
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      bucketnames: loki-data
  replication_factor: 3
  ring:
    kvstore:
      store: memberlist

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: s3
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 744h       # 31 день
  max_query_length: 745h       # 31 день + 1 час
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32
  max_query_series: 5000
  allow_structured_metadata: true

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
  compaction_interval: 10m

# Write компоненты
write:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 2
      memory: 4Gi

# Read компоненты
read:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 4Gi
    limits:
      cpu: 4
      memory: 8Gi

# Backend (включая Compactor)
backend:
  replicas: 2
  persistence:
    enabled: true
    size: 10Gi
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2
      memory: 2Gi
```

### Сценарий 3: Разные retention для разных namespace (пер-tenant limits)

Loki не поддерживает глобальные retention policies на уровне namespace напрямую. Однако можно реализовать через комбинацию механизмов:

**Вариант 1: Один retention_period + pipeline стадии на агенте**

На стороне Alloy/Fluent Bit настройте сбор разных namespace с разными метками и используйте recording rules для агрегации:

```yaml
# Alloy: namespace "audit" → метка env=audit
# Alloy: namespace "app" → метка env=prod

# В recording rules Loki:
groups:
  - name: audit-metrics
    interval: 5m
    rules:
      - record: audit_logs:count
        expr: |
          sum(count_over_time({env="audit"} [5m]))
        labels:
          retention: long
```

**Вариант 2: Разные инстансы Loki для разных retention**

Запустите два кластера Loki с разными retention:
- **Loki-ops:** `retention_period: 7d` для DEBUG/INFO логов
- **Loki-audit:** `retention_period: 365d` для аудит-логов

Агенты маршрутизируют логи в разные инстансы через несколько OUTPUT.

### Сценарий 4: Capacity planning для retention

**Расчет объема хранилища:**

```bash
# 1. Определить средний объем логов в день
rate(loki_distributor_sent_bytes_total[7d]) * 86400 / 1024 / 1024 / 1024
# → ГБ/день

# 2. Умножить на retention (в днях)
# Пример: 50 ГБ/день * 30 дней = 1500 ГБ = 1.5 ТБ

# 3. Добавить overhead индекса (~10-20%)
# 1.5 ТБ * 1.15 = 1.725 ТБ

# 4. Умножить на replication_factor
# 1.725 ТБ * 3 (replication_factor) = 5.175 ТБ
```

**Таблица рекомендаций:**

| Объем логов/день | Retention | Replication | Итого хранилище | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| 10 ГБ | 7 дней | 1 | 70 ГБ | Single Binary + filesystem |
| 50 ГБ | 30 дней | 3 | 4.5 ТБ | Simple Scalable + S3 |
| 200 ГБ | 30 дней | 3 | 18 ТБ | Simple Scalable + S3 |
| 500 ГБ | 7 дней | 3 | 10.5 ТБ | Simple Scalable + S3 + aggressive retention |
| 1 ТБ+ | 30 дней | 3 | 90+ ТБ | Distributed + S3 + tiered storage |

### Сценарий 5: Мониторинг компакции

**Ключевые метрики:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `loki_compactor_compactions_total` | Количество выполненных компакций | Рост должен быть стабильным |
| `loki_compactor_retention_deletes_total` | Количество удалений по retention | Рост при наличии старых данных |
| `loki_compactor_retention_dry_runs_total` | Dry-run удалений (проверка) | Должен совпадать с реальными удалениями |
| `loki_compactor_bytes_processed_total` | Объем обработанных данных | Мониторинг для планирования |
| `loki_compactor_blockbusters_seconds` | Время компакции | P99 > 30m → проблема |

**Прометеус-правила:**

```yaml
groups:
  - name: loki-compactor
    rules:
      - alert: LokiCompactorStuck
        expr: |
          time() - loki_compactor_last_successful_run_timestamp_seconds > 3600
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Loki Compactor hasn't run successfully in 1 hour"
          description: "Last successful compaction was {{ $value | humanizeDuration }} ago"

      - alert: LokiRetentionNotWorking
        expr: |
          rate(loki_compactor_retention_deletes_total[1h]) == 0
          and
          count_over_time({job="loki"} [24h]) > 0
        for: 6h
        labels:
          severity: warning
        annotations:
          summary: "Loki retention not deleting old data"
          description: "No retention deletions in 6 hours but data exists"
```

### Сценарий 6: Тюнинг compactor для высокой нагрузки

Для кластеров с > 500 ГБ/день:

```yaml
compactor:
  working_directory: /loki/compactor
  compaction_interval: 5m           # Чаще (по умолчанию 10m)
  retention_enabled: true
  retention_delete_delay: 1h        # Короче (по умолчанию 2h)
  retention_delete_worker_count: 500 # Больше воркеров (по умолчанию 150)
```

**Дополнительные ресурсы для Compactor:**

```yaml
backend:
  replicas: 3           # Больше реплик для распределения нагрузки
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 4
      memory: 4Gi
```

### Сценарий 7: Включение retention на существующем кластере

Если retention был выключен и данные накопились:

```bash
# 1. Обновите конфигурацию Loki
# Добавьте:
# compactor:
#   retention_enabled: true
#   retention_delete_delay: 2h

# 2. Перезапустите Loki (rolling update)
helm upgrade loki grafana-community/loki \
  --namespace logging \
  -f loki_values.yaml

# 3. Проверьте начало удаления
curl -s http://localhost:3100/metrics | grep loki_compactor_retention_deletes_total
# → Рост метрики означает начало удаления

# 4. Проверьте уменьшение объема S3
aws s3 ls s3://loki-data/ --summarize --recursive | grep "Total Size"
# → Размер должен уменьшаться
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Данные не удаляются** | `retention_enabled: false` или compactor не запущен | Включите `retention_enabled: true`, проверьте логи compactor |
| **Compactor потребляет много CPU** | Слишком частый interval или много данных | Увеличьте `compaction_interval`, добавьте ресурсы |
| **Slow query после компакции** | Компакция перезаписывает индекс во время запроса | Компакция не блокирует запросы, но может замедлять I/O |
| **"Stuck compaction"** | Compactor не может записать в S3 | Проверьте права доступа, quota, сетевую доступность S3 |
| **Retention удаляет слишком много** | `retention_period` установлен неправильно | Проверьте `retention_period` и `max_query_length` |
| **Disk переполняется в compactor** | `working_directory` на диске с недостаточным местом | Выделите отдельный диск ≥ 50 GB для compactor |
| **"Entry out of order" после retention** | Данные были частично удалены | Проверьте consistency retention удаления |

---

## Дополнительная информация

### Лучшие практики

1. **Всегда включайте retention в production:** Бесконечное хранение приводит к росту стоимости и снижению производительности.
2. **Устанавливайте `max_query_length > retention_period`:** Минимум на 1 час больше, иначе пользователи не смогут запрашивать данные за весь период.
3. **Мониторьте compactor через метрики:** `loki_compactor_compactions_total`, `loki_compactor_retention_deletes_total`.
4. **Размещайте compactor на быстрых дисках:** SSD/NVMe для `working_directory`.
5. **Тестируйте retention:** Сначала в dev/test, затем в production.
6. **Не устанавливайте слишком короткий retention:** Для production минимум 7 дней, для аудита — 90+ дней.
7. **Регулярно проверяйте размер S3:** Используйте `aws s3 ls --summarize` для контроля.
8. **Версионирование конфигурации:** Храните retention policies в Git.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-конфигурация
- [Backup и восстановление LGTM](../Kubernetes/Installation/LGTM_Stack/lgtm_backup_disaster_recovery.md) — стратегии бэкапа
- [Оптимизация LGTM стека](../Kubernetes/Installation/LGTM_Stack/lgtm_performance_tuning.md) — общие принципы
