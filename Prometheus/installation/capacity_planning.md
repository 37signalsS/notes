# Capacity Planning для Prometheus

## Определения

**Capacity Planning** — процесс расчета требуемых вычислительных ресурсов (CPU, RAM, Disk I/O, сеть) для Prometheus на основе текущей и прогнозируемой нагрузки. Правильный sizing предотвращает OOMKill, троттлинг CPU и переполнение TSDB.

**Active Series (Активные ряды)** — количество уникальных комбинаций меток (label set), хранимых в Head Block (оперативная память). Ключевой показатель потребления ресурсов.

**Cardinality (Кардинальность)** — количество уникальных значений метки. Высокая cardinality (например, `user_id` с миллионами значений) приводит к взрывному росту active series.

**Bytes per Series** — количество байт, потребляемых одним временным рядом в памяти. Для Prometheus v3.x: 6-8 байт на серию.

> **См. также:** [Labels and Cardinality](../concepts/labels_and_cardinality.md) — управление кардинальностью; [TSDB](../concepts/tsdb.md) — внутреннее устройство хранилища; [Resource Sizing (Kubernetes)](../kubernetes/operator/resource_sizing.md) — sizing для K8s.

## Основные концепции

### Формулы расчёта ресурсов

#### RAM (Оперативная память)

```
RAM (MB) = 2000 + (active_series × bytes_per_series)
```

| Active Series | Bytes/Series | Итого RAM | Рекомендация |
|---|---|---|---|
| 100K | 8 | 2.8 GB | 4 GB |
| 500K | 8 | 6 GB | 8 GB |
| 1M | 8 | 10 GB | 16 GB |
| 5M | 8 | 42 GB | 64 GB |
| 10M | 8 | 82 GB | 128 GB |

> **Формула из [Resource Sizing](../kubernetes/operator/resource_sizing.md:26):** `RAM (GB) = 2 + (0.001 × active_series)`

#### Disk (Диск)

```
Disk (GB) = (active_series × bytes_per_sample × samples_per_day × retention_days) / 10^9
```

Где:
- `bytes_per_sample` ≈ 1-2 байта (сжатые блоки)
- `samples_per_day` = 86400 / scrape_interval (при `scrape_interval: 15s` = 5760)
- `retention_days` = настроенный `storage.tsdb.retention.time`

**Пример для 1M series, scrape_interval=15s, retention=15d:**

```
Disk = (1,000,000 × 1.5 × 5760 × 15) / 10^9 = 129.6 GB
```

| Active Series | Scrape Interval | Retention | Диск |
|---|---|---|---|
| 100K | 15s | 15d | ~13 GB |
| 500K | 15s | 15d | ~65 GB |
| 1M | 15s | 15d | ~130 GB |
| 1M | 15s | 30d | ~260 GB |
| 5M | 15s | 15d | ~648 GB |

#### CPU

```
CPU (cores) = 2 + (0.0005 × active_series)
```

| Active Series | CPU Cores | Рекомендация |
|---|---|---|
| 100K | 2.05 | 2 cores |
| 500K | 2.25 | 4 cores |
| 1M | 2.5 | 4 cores |
| 5M | 4.5 | 8 cores |
| 10M | 7 | 8-16 cores |

### Влияние scrape_interval на ресурсы

| Scrape Interval | Samples/день (1M series) | Disk/день | RAM Head Block |
|---|---|---|---|
| 10s | 8.64B | 12.6 GB | ~8 GB |
| 15s | 5.76B | 8.4 GB | ~8 GB |
| 30s | 2.88B | 4.2 GB | ~8 GB |
| 60s | 1.44B | 2.1 GB | ~8 GB |

> **Вывод:** Уменьшение `scrape_interval` с 15s до 10s увеличивает потребление диска на 50%, но RAM Head Block не меняется (зависит от active series, а не от частоты скрейпинга).

### Методика определения active_series

#### Способ 1: Через TSDB Status (Web UI)

```
Prometheus UI → Status → TSDB Status → Head Stats → "num series"
```

#### Способ 2: Через метрику

```promql
prometheus_tsdb_head_series
```

#### Способ 3: Через promtool

```bash
promtool tsdb analyze /var/lib/prometheus/
# → Estimated TSDB Head size:
#   Series: 845,231
#   Min time: 2026-09-01T00:00:00Z
#   Max time: 2026-09-20T12:00:00Z
```

### Прогнозирование роста

```
Прогноз active_series через 6 месяцев = current × (1 + monthly_growth_rate)^6
```

| Тип инфраструктуры | Месячный рост | Через 6 месяцев |
|---|---|---|
| Стабильный production | 2-5% | +12-30% |
| Активная разработка | 10-20% | +80-300% |
| Микросервисы (частый deploy) | 5-10% | +33-77% |

## Практические сценарии

### Сценарий 1: Sizing нового сервера Prometheus

**Входные данные:**
- 200 серверов, на каждом ~500 метрик (Node Exporter)
- Приложения: 50 сервисов, ~200 метрик каждый
- `scrape_interval`: 15s
- `retention.time`: 15d

**Расчет:**

```
Active Series = (200 × 500) + (50 × 200) = 100,000 + 10,000 = 110,000

RAM = 2000 + (110,000 × 8) = 2,880 MB ≈ 3 GB → Рекомендуется 8 GB (с запасом)
Disk = (110,000 × 1.5 × 5760 × 15) / 10^9 = 14.3 GB → Рекомендуется 50 GB SSD
CPU = 2 + (0.0005 × 110,000) = 2.55 → 4 cores
```

**Итоговая рекомендация:** 4 CPU, 8 GB RAM, 50 GB SSD.

### Сценарий 2: Проверка текущего использования

```bash
# 1. Проверка active series
curl -s http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series | jq '.data.result[0].value[1]'
# → "845231"

# 2. Проверка потребления RAM
curl -s http://localhost:9090/api/v1/query?query=process_resident_memory_bytes | jq '.data.result[0].value[1]'
# → "4294967296" (4 GB)

# 3. Проверка размера TSDB на диске
du -sh /var/lib/prometheus/
# → 85G

# 4. Проверка скорости записи
curl -s http://localhost:9090/api/v1/query?query=rate(prometheus_tsdb_head_samples_appended_total[5m]) | jq '.data.result[0].value[1]'
# → "12500" (samples/sec)
```

### Сценарий 3: Аварийный сценарий — взрыв кардинальности

**Признаки:**
- `prometheus_tsdb_head_series` растет экспоненциально
- `process_resident_memory_bytes` приближается к лимиту
- PromQL-запросы замедляются

**Диагностика:**

```bash
# Найти метрику с высокой кардинальностью
curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq 'length'
# → 12847 (количество уникальных имен метрик)

# Найти метку с высокой кардинальностью
promtool tsdb analyze /var/lib/prometheus/ 2>&1 | grep "highest cardinality"
# → Label: "request_id" with Value Count: 2,450,000
```

**Решение:**

```yaml
# Добавить в prometheus.yml
scrape_configs:
  - job_name: 'problematic-app'
    metric_relabel_configs:
      # Удалить высококардинальную метку
      - source_labels: [__name__]
        regex: 'http_request_duration_seconds.*'
        action: keep
      # Удалить метку request_id
      - source_labels: [request_id]
        regex: '.+'
        action: labeldrop
```

## Дополнительная информация

### Ключевые метрики для мониторинга capacity

```promql
# Количество активных серий
prometheus_tsdb_head_series

# Потребление RAM процессом
process_resident_memory_bytes

# Размер WAL на диске
prometheus_tsdb_wal_size_bytes

# Размер хранилища
prometheus_tsdb_storage_blocks_bytes

# Скорость записи сэмплов
rate(prometheus_tsdb_head_samples_appended_total[5m])

# Утилизация CPU
rate(process_cpu_seconds_total[5m])
```

### Recording rules для capacity planning

```yaml
# /etc/prometheus/rules/capacity_planning.yml
groups:
  - name: capacity_planning
    interval: 1m
    rules:
      - record: prometheus:active_series:count
        expr: prometheus_tsdb_head_series

      - record: prometheus:ram_usage_bytes:current
        expr: process_resident_memory_bytes

      - record: prometheus:disk_usage_bytes:current
        expr: prometheus_tsdb_storage_blocks_bytes + prometheus_tsdb_wal_size_bytes

      - record: prometheus:samples_per_second:rate5m
        expr: rate(prometheus_tsdb_head_samples_appended_total[5m])
```

### Alert rules для capacity

```yaml
# /etc/prometheus/rules/capacity_alerts.yml
groups:
  - name: capacity_alerts
    rules:
      - alert: PrometheusHighActiveSeries
        expr: prometheus_tsdb_head_series > 1000000
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High active series: {{ $value }}"

      - alert: PrometheusNearOOM
        expr: process_resident_memory_bytes / (node_memory_MemTotal_bytes * on(instance) group_left() node_uname_info) > 0.8
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus using >80% of available memory"

      - alert: PrometheusWalTooLarge
        expr: prometheus_tsdb_wal_size_bytes > 5368709120  # 5 GB
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "WAL size exceeds 5 GB: {{ $value | humanize1024 }}"
```

### Флаги тюнинга (Performance Tuning Flags)

| Флаг | Описание | Рекомендуемое значение | Влияние |
| :--- | :--- | :--- | :--- |
| `--storage.tsdb.wal-compression` | Сжатие WAL (snappy) | `true` | Снижает размер WAL на 60-80% |
| `--query.max-samples` | Лимит сэмплов на запрос | `50000000` (по умолчанию) | Защита от тяжёлых запросов |
| `--query.max-concurrency` | Макс. параллельных запросов | `20` | баланс между нагрузкой и отзывчивостью |
| `--query.timeout` | Таймаут PromQL-запроса | `2m` | Защита от зависших запросов |
| `--query.lookback-delta` | Окно поиска для instant queries | `5m` | Увеличить при задержках скрейпинга |
| `--storage.tsdb.min-block-duration` | Мин. длительность блока | `2h` | Не менять без понимания последствий |
| `--storage.tsdb.max-block-duration` | Макс. длительность блока | `2h` | Увеличить при compaction stall |
| `--storage.tsdb.out-of-order.time-window` | Окно для OOO-данных | `0s` (выключено) | Включить при задержках в сети |
| `--runtime.gomaxprocs` | Количество ядер Go | Auto | Установить при контейнеризации |
| `--enable-feature=agent` | Режим агента | Не включен | Включить для edge-узлов |

**Пример полного запуска с тюнингом:**

```bash
prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.retention.size=50GB \
  --storage.tsdb.wal-compression=true \
  --storage.tsdb.min-block-duration=2h \
  --storage.tsdb.max-block-duration=2h \
  --storage.tsdb.out-of-order.time-window=1h \
  --query.max-concurrency=20 \
  --query.max-samples=50000000 \
  --query.timeout=2m \
  --query.lookback-delta=5m \
  --web.enable-lifecycle \
  --web.enable-otlp-receiver \
  --web.listen-address=127.0.0.1:9090
```

### Рекомендации SRE

1. **Мониторьте `prometheus_tsdb_head_series`** — это главный индикатор потребления ресурсов.
2. **Фиксируйте `scrape_interval`** — уменьшение с 15s до 10s увеличивает disk на 50%.
3. **Контролируйте cardinality** — используйте `metric_relabel_configs` для удаления высококардинальных меток.
4. **Планируйте с запасом** — выделяйте RAM с 30-50% запасом от расчетного значения.
5. **Тестируйте нагрузку** — перед продакшен-развертыванием проверьте TSDB на нагрузочном тесте.
6. **Включите WAL compression** — `--storage.tsdb.wal-compression=true` снижает нагрузку на диск.
7. **Настройте GOMEMLIMIT** — в контейнерах устанавливайте на 85-90% от `limits.memory`.
8. **Используйте Native Histograms** — для снижения кардинальности распределений (до 40% экономии).
9. **Разделяйте WAL и Blocks** — если возможно, вынесите WAL на быстрый NVMe SSD.
10. **Настройте OOO window** — при известных задержках в сети включите `--storage.tsdb.out-of-order.time-window`.

## См. также

*   **[Labels and Cardinality](../concepts/labels_and_cardinality.md)** — управление кардинальностью меток.
*   **[TSDB](../concepts/tsdb.md)** — внутреннее устройство хранилища.
*   **[Resource Sizing (Kubernetes)](../kubernetes/operator/resource_sizing.md)** — sizing для K8s.
*   **[Capacity Planning (общий)](../../Concepts/capacity-planning.md)** — методология планирования ресурсов.
