# Vector: Производительность и профилирование

**Актуально для:** Vector 0.58.0

## Определения

- **Profiling** — процесс сбора данных о том, как Vector расходует CPU и память, с помощью `pprof` endpoint или внешних инструментов (`perf`, `strace`).
- **Benchmark** — управляемый тест производительности для определения пропускной способности и выявления узких мест.
- **Capacity Planning** — расчёт необходимых ресурсов (vCPU, memory, disk) на основе ожидаемой нагрузки.
- **Hot Path** — часть конвейера, которая обрабатывает каждое событие (например, VRL-трансформ в `remap`). Оптимизация hot path даёт наибольший эффект.
- **Tail Latency** — высокие перцентили (p95, p99) задержки обработки событий. Часто вызываются GC-паузами (в других системах) или lock contention.

## Профилирование

### Встроенный pprof endpoint

Vector предоставляет pprof-интерфейс через внутренний API (порт 8686):

```toml
# Включение internal API для profiling
[api]
enabled = true
address = "127.0.0.1:8686"
```

```bash
# 1. CPU profile (30 секунд)
curl -o cpu.prof http://localhost:8686/debug/pprof/profile?seconds=30

# 2. Memory profile (heap)
curl -o mem.prof http://localhost:8686/debug/pprof/allocs

# 3. Goroutine profile
curl -o goroutine.prof http://localhost:8686/debug/pprof/goroutine

# 4. Анализ профиля
go tool pprof cpu.prof
# (pprof) top10          # топ-10 функций по CPU
# (pprof) web           # граф вызовов в браузере
# (pprof) trace         # трейс выполнения
```

> **Важно:** pprof endpoint доступен только на `127.0.0.1`. Для удалённого доступа используйте SSH tunnel:
> ```bash
> ssh -L 8686:127.0.0.1:8686 vector@host
> ```

### Профилирование через perf

Для системного профилирования (включая userspace + kernel):

```bash
# CPU profiling с perf
sudo perf record -g -F 99 -p $(pidof vector) -- sleep 30
sudo perf script > perf.txt

# Генерация flamegraph
git clone https://github.com/brendangregg/FlameGraph.git
./FlameGraph/compat/perf fold | ./FlameGraph/stackcollapse-perf.pl | ./FlameGraph/flamegraph.pl > vector.svg
```

### Метрики для диагностики производительности

```bash
# 1. Запрос метрик в реальном времени
curl -s http://localhost:8686/metrics | grep -E "buffer_size|sent_events|received_events|latency"

# 2. Использование vector top
vector top --human-metrics
# → Events Out: 1500/s
# → Buffer Size: 5 MiB
# → Errors: 0
# → Latency (ms): avg=5 p95=12 p99=45

# 3. Диагностика VRL latency
vector top --components 'remap_*' --columns 'events_out,events_dropped,processed_bytes,latency'
```

**Ключевые метрики для профилирования:**

| Метрика | Что значит | Порог |
| :--- | :--- | :--- |
| `component_latency_seconds{quantile="0.95"}` | p95 задержка обработки одного события | > 10ms — VRL узкое место |
| `component_latency_seconds{quantile="0.99"}` | p99 задержка | > 50ms — проблема в sink |
| `component_buffer_fill_fraction` | Заполненность буфера (0-1) | > 0.9 — backpressure |
| `process_cpu_usage_ratio` | CPU usage (0-1) | > 0.8 — нехватка vCPU |
| `process_memory_usage_bytes` | RSS памяти | растёт без останова — memory leak |
| `vector_build_info` | Версия, коммит | inventory check |

## Benchmark

### Синтетический benchmark

```bash
# 1. Генерация нагрузки через file source
# Создаём файл с 1M JSON-сообщений
seq 1 1000000 | jq -c '{message: ., level: "info", ts: "2026-01-01T00:00:00Z"}' > /tmp/bench.jsonl

# 2. Минимальная конфигурация Vector для benchmark
# vector-benchmark.toml
```

```toml
data_dir = "/tmp/vector-bench"
api.enabled = true
api.address = "127.0.0.1:8686"

[sources.bench_in]
type = "file"
include = ["/tmp/bench.jsonl"]
start_at_beginning = true
ignore_older = 0

[transforms.parse]
type = "remap"
inputs = ["bench_in"]
source = '. = parse_json(.message)'

[sinks.console_out]
type = "console"
inputs = ["parse"]
encoding.codec = "json"

# Отключаем buffering для чистого benchmark
[sinks.console_out.buffer]
type = "memory"
```

```bash
# 3. Запуск benchmark с измерением времени
START=$(date +%s)
vector --config vector-benchmark.toml --threads 4
# vector обрабатывает файл и завершается
END=$(date +%s)
ELAPSED=$((END - START))
echo "Processed 1M events in ${ELAPSED}s"
echo "Throughput: $((1000000 / ELAPSED)) events/sec"
```

### Tuning hot path

#### VRL optimization

```vrl
# ПЛОХО: parse_json! abort при ошибке
. = parse_json!(.message)

# ХОРОШО: graceful handling + early exit
parsed, err = parse_json(.message)
if err != null {
    .parse_error = true
} else {
    . = parsed
}

# ПЛОХО: regex на каждый вызов
pattern = parse_regex(.message, r'...')  # компилируется каждый раз

# ХОРОШО: использовать литерал регулярного выражения
matched, err = parse_regex(.message, r'^(?P<ip>\d+\.\d+\.\d+\.\d+)')
```

#### Batch tuning

```toml
[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "http://loki:3100"

# Оптимизация batch для high-throughput
[sinks.loki.batch]
max_events = 10000         # больше batch = меньше запросов
timeout_secs = 2           # не слишком большой — latency
max_bytes = 10485760       # 10 MiB batch

# Оптимизация concurrency
[sinks.loki.request]
concurrency = "adaptive"
max_concurrency = 20
timeout_secs = 30
```

**Тюнинг batch в зависимости от sink:**

| Sink | max_events | timeout_secs | max_bytes | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| Loki | 10000 | 2 | 10 MiB | High throughput |
| Elasticsearch | 500 | 5 | 5 MiB | Avoid OOM ES |
| Kafka | 10000 | 1 | 1 MiB | Latency-critical |
| ClickHouse | 100000 | 10 | 20 MiB | Batch-optimized |

## Capacity Planning

### Расчёт ресурсов

**Формула:**

```
events_per_sec = log_volume_bytes_per_sec / avg_event_size
vCPU_agent = events_per_sec * avg_event_size / 25_000_000  # 25 MiB/s/vCPU
vCPU_aggregator = events_per_sec * avg_event_size / 10_000_000  # 10 MiB/s/vCPU (тяжелее VRL)
memory = vCPU * 2 GiB  # стартовая точка
disk_buffer = peak_throughput_bytes_per_sec * 10_min / 0.7  # 30% резерв
```

**Пример расчёта для 50K events/sec:**

```
avg_event_size = 512 bytes
throughput = 50000 * 512 = 25.6 MiB/s

vCPU_agent (50 хостов):
  per_host = (50000/50) * 512 / 25_000_000 = 0.02 vCPU → 1 vCPU (минимум)
  memory = 2 GiB

vCPU_aggregator:
  events_per_host = 1000 events/sec
  vCPU = 1000 * 512 / 10_000_000 = 0.05 → 1 vCPU
  memory = 4 GiB (на VRL и enrichment)

disk_buffer (10 минут data, 30% overhead):
  = 25.6 MiB/s * 600s * 1.3 = ~193 MiB
  → round up to 512 MiB на каждый aggregator
```

### Автоматическое масштабирование (K8s HPA)

```yaml
# HorizontalPodAutoscaler для Vector Aggregator
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vector-aggregator-hpa
  namespace: observability
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vector-aggregator
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: vector_buffer_utilization
      target:
        type: AverageValue
        averageValue: "0.8"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
```

## Операции и команды

### Performance debugging workflow

```bash
# 1. Быстрая диагностика: vector top
vector top
# → Смотрите: Events Out, Buffer Size, Errors, Latency

# 2. Анализ узкого места
vector tap normalize
# → Если latency высокий — проблема в VRL

# 3. Profiling CPU
curl -o /tmp/cpu.prof http://localhost:8686/debug/pprof/profile?seconds=30
go tool pprof -top /tmp/cpu.prof

# 4. Memory profiling
curl -o /tmp/allocs.prof http://localhost:8686/debug/pprof/allocs
go tool pprof -top /tmp/allocs.prof

# 5. Проверка системных метрик
# CPU
top -b -n1 -p $(pidof vector) | tail -1
# Memory (RSS)
ps -o pid,rss,vsz,comm -p $(pidof vector)
# Open files
ls /proc/$(pidof vector)/fd | wc -l
# Context switches
cat /proc/$(pidof vector)/status | grep -i voluntary
```

### Thread tuning

Vector использует thread pool для обработки событий. Число потоков можно настроить:

```bash
# Явное указание числа потоков
vector --config /etc/vector/vector.yaml --threads 4
# → threads = 2 * num_cpus + 1 по умолчанию

# В конфигурации (глобальная опция)
[global]
threads = 4
```

## Устранение неполадок

### Высокая latency (p95 > 10ms)

**Диагностика:**

```bash
# 1. Проверка latency по компонентам
vector top --columns 'component,latency,events_out'
# → Выявляем компонент с высокой latency

# 2. Если проблема в remap (VRL):
vector tap normalize --duration_ms 5000
# → Просмотр время обработки событий

# 3. CPU profiling
curl -s http://localhost:8686/debug/pprof/profile?seconds=30 -o /tmp/cpu.prof
go tool pprof -top /tmp/cpu.prof
# → Ищем hot-функции VRL
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Сложный VRL (parse_regex, parse_grok) | Заменить на специализированный парсер (`parse_json`, `parse_syslog`) |
| Большой enrichment table | Использовать `map`-операции вместо `get_enrichment_table_record` для bulk-операций |
| Высокая cardinality (метки в Loki) | Добавить `tag_cardinality_limit` transform перед sink |
| Маленький batch | Увеличить `batch.max_events` и `batch.max_bytes` |
| Низкая concurrency | Включить `request.concurrency = "adaptive"` |

### Memory leak (RSS растёт без останова)

**Диагностика:**

```bash
# 1. Слежим за ростом памяти
watch -n 5 'ps -o pid,rss,vsz -p $(pidof vector)'

# 2. Memory profiling
curl -o /tmp/allocs.prof http://localhost:8686/debug/pprof/allocs
go tool pprof -top /tmp/allocs.prof

# 3. Проверка размера enrichment tables
curl -s http://localhost:8686/metrics | grep "enrichment_table"
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Enrichment table без TTL | Добавить `refresh_interval_secs` для периодической перезагрузки |
| Enrichment table с wildcard | Использовать `tag_cardinality_limit` для ограничения |
| Большие события в buffer | Установить `max_event_size` на source |
| Memory buffer без лимита | Перейти на `buffer.type = "disk"` с `max_size` |

### Disk I/O bottleneck

**Диагностика:**

```bash
# 1. Проверка I/O wait
iostat -x 1 5

# 2. Проверка нагрузки на disk buffer
curl -s http://localhost:8686/metrics | grep "buffer_disk"
# → vector_buffer_disk_writes_total, vector_buffer_disk_read_bytes_total

# 3. Проверка filesystem
df -h /var/lib/vector
ls -la /var/lib/vector/buffers/
```

## Лучшие практики

### VRL-оптимизация

1.  **Avoid `parse_grok` where `parse_json` or `parse_syslog` suffices** — специализированные парссеры работают на порядок быстрее.
2.  **Не используйте `to_regex()` в hot path** — компилируйте regex один раз через литерал `r'pattern'` или `parse_regex!`.
3.  **Кэшируйте enrichment tables** в памяти, а не делайте HTTP-запросы для каждого события.
4.  **Нормализуйте timestamp рано** — не откладывайте на later stages.

### Оптимизация buffers

1.  **Disk buffer для production** — `when_full = "block"` для критичных пайплайнов (garantee at-least-once).
2.  **Memory buffer для non-critical** — для debug/info логов, где потеря допустима.
3.  **Размер disk buffer** = `throughput * 10min * 1.3` (30% резерв).

### Производительность на уровне sink

1.  **Batch optimization:** `max_events = 10000`, `timeout_secs = 2` для high-throughput sinks.
2.  **Adaptive concurrency:** `concurrency = "adaptive"` с `max_concurrency = 20` для HTTP sinks.
3.  **Compression:** `compression = "gzip"` для текстовых форматов — снижает сетевой трафик на 60-80%.

### Profiling в CI/CD

```bash
# Добавьте в CI проверку performance регрессии
vector --config vector.toml --test-mode  # benchmark mode
# → сравнение throughput с baseline
```

## Дополнительная информация

- **Production capacity planning:** [Vector Overview — Производительность](./vector_overview.md#производительность-и-capacity-planning)
- **Архитектура deployment:** [Vector Production Deployment](./vector_production_deployment.md)
- **Надёжность:** [Vector Reliability](./vector_reliability.md)
- **Профилирование в Linux:** [perf — Performance Events](../Linux/Diagnostics/Performance/perf.md), [Flame Graphs](../Linux/Diagnostics/Processes/thread_cpu_troubleshooting.md)
- **Контейнерная производительность:** [Docker native metrics](../Docker/Docker_metrics/docker_native_metrics.md)
- **Continuous profiling:** [Непрерывное профилирование](../Concepts/continuous_profiling.md)
- **Официальная документация:** [Vector Monitoring](https://vector.dev/docs/administration/monitoring/)