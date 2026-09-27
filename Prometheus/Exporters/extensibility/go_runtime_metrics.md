# Метрики рантайма Go приложений в Prometheus

## Определения

**Метрики рантайма Go** — набор системных показателей, экспортируемых через библиотеку `client_golang`, которые отражают внутреннее состояние виртуальной машины Go: сборщик мусора (GC), планировщик горутин, управление памятью и системные потоки.

Эти метрики позволяют диагностировать проблемы производительности на уровне языка (например, блокировки планировщика или неэффективную работу с кучей), которые недоступны при стандартном мониторинге хоста или контейнера.

**GOMEMLIMIT** — параметр рантайма (актуализирован в Go 1.24), устанавливающий «мягкий» предел памяти. Это позволяет рантайму более агрессивно запускать GC при приближении к лимиту и возвращать память операционной системе, предотвращая OOM (Out of Memory) в средах с жесткими ограничениями (например, Kubernetes Pods).

**runtime/metrics** — современный иерархический API в Go, предоставляющий более детальные данные по сравнению с устаревшим `runtime.ReadMemStats`. Включает гистограммы задержек и показатели использования CPU различными частями рантайма.

**См. также:** [Клиентские библиотеки Prometheus](./client_libraries.md), [Создание собственных экспортеров](./custom_exporters.md).

## Основные концепции

### Предварительные требования

Перед инструментации приложения убедитесь, что компоненты соответствуют минимальным версиям:

| Компонент | Минимальная версия | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| **Go** | 1.21 | 1.24+ | Go 1.21+ требуется для полного доступа к `runtime/metrics`; Go 1.24+ включает нативные гистограммы для задержек GC и планировщика |
| **client_golang** | v1.11.0 | v1.21.0+ | Версии ниже v1.11.0 не экспортируют `runtime/metrics`; v1.21.0+ добавляет поддержку нативных гистограмм |
| **Prometheus** | 2.45 | 3.0+ | Prometheus 3.0+ поддерживает UTF-8 в именах метрик и нативные гистограммы без ручной настройки бакетов |
| **Kernel / OS** | Linux 4.15+ | 5.15+ | Требуется для корректной работы cgroups v2 и чтения `memory.max` |

**Требуемые пакеты в go.mod:**
```go
module github.com/yourorg/yourapp

go 1.24

require github.com/prometheus/client_golang v1.21.0
```

### Стандартные метрики (доступны из коробки)

Библиотека `prometheus/client_golang` автоматически регистрирует базовый набор метрик через `NewGoCollector`. В современных приложениях рекомендуется использовать `NewGoCollector` с настройками, включающими расширенные показатели.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `go_goroutines` | Gauge | Текущее количество активных горутин. Ключевой индикатор утечек. |
| `go_threads` | Gauge | Количество системных потоков (OS threads), созданных рантаймом. |
| `go_memstats_heap_alloc_bytes` | Gauge | Память на куче (heap), занятая «живыми» объектами. |
| `go_memstats_sys_bytes` | Gauge | Общая системная память, запрошенная у ОС (включает heap, стеки, кэши). |
| `go_memstats_heap_objects` | Gauge | Общее количество объектов на куче. Влияет на длительность сканирования GC. |
| `go_memstats_gc_sys_bytes` | Gauge | Память, выделенная под метаданные сборщика мусора. Рост может указывать на утечки в рантайме. |
| `go_memstats_stack_sys_bytes` | Gauge | Память, выделенная под стеки горутин (включая неиспользуемые сегменты). |
| `go_memstats_buck_hash_sys_bytes` | Gauge | Память, используемая хеш-таблицей профилировщика (bucket map). |
| `go_gc_duration_seconds` | Summary | Длительность пауз Stop-the-world (STW) при сборке мусора. |
| `go_info` | Gauge | Информационная метрика с версией Go и архитектурой (значение всегда 1). |

### Метрики runtime/metrics API (Go 1.21+)

При включении расширенного режима экспортируются дополнительные метрики из иерархического API `runtime/metrics`:

| Метрика Prometheus | Путь runtime/metrics | Тип | Описание |
| :--- | :--- | :--- | :--- |
| `go_sched_latencies_seconds` | `/sched/latencies:seconds` | Histogram | Задержки планировщика. Смещение в сторону высоких значений указывает на нехватку CPU или проблему с `GOMAXPROCS`. |
| `go_mutex_wait_duration_seconds` | `/sync/mutex/wait/total:seconds` | Counter | Суммарное время, которое горутины провели в ожидании освобождения мьютексов. |
| `go_gc_pause_total_seconds` | `/gc/pause-total:seconds` | Counter | Суммарное время пауз Stop-the-world за всё время работы процесса. |
| `go_gc_heap_frag_bytes` | `/gc/heap/fragments:bytes` | Gauge | Объем фрагментированной памяти на куче, которую рантайм не может уплотнить. |
| `go_gc_gogc_percent` | `/gc/gogc:percent` | Gauge | Текущее значение отношения `GOGC`. Полезна для корреляции с частотой GC. |
| `go_memstats_heap_inuse_bytes` | `/memory/classes/heap/inuse:bytes` | Gauge | Объем памяти кучи, фактически используемый объектами (в отличие от `heap_alloc`, включает неочищенные объекты). |
| `go_memstats_stack_inuse_bytes` | `/memory/classes/heap/inuse:bytes` | Gauge | Объем памяти стеков, фактически используемый горутинами. |

### Поддержка возможностей Prometheus 3.0+

1.  **Native Histograms (Нативные гистограммы):**
    Современные версии `client_golang` позволяют экспортировать метрики `runtime/metrics` (например, задержки планировщика или GC) в формате нативных гистограмм. Это обеспечивает высокую точность квантилей без руальной настройки бакетов.

2.  **UTF-8 и точки в именах:**
    С выходом Prometheus 3.0 и поддержкой UTF-8, метрики Go могут транслироваться в стиле OpenTelemetry с использованием точек вместо подчеркиваний (например, `go.sched.latencies.seconds`), что упрощает интеграцию в гетерогенных средах.

3.  **Динамическая конфигурация GC:**
    Метрика `/gc/gogc:percent` позволяет в реальном времени отслеживать, как изменение переменных окружения влияет на поведение приложения в runtime.

### Регистрация расширенных метрик в коде

Для использования всех возможностей `runtime/metrics` в Go 1.24+ используйте следующий подход:

```go
package main

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "net/http"
)

func main() {
    reg := prometheus.NewRegistry()

    reg.MustRegister(prometheus.NewGoCollector(
        prometheus.GoCollectorOptions{
            RuntimeMetricSummationFilter: func(name string) bool { return true },
        },
    ))

    http.Handle("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
    http.ListenAndServe(":8080", nil)
}
```

**Пояснение к параметрам:**
- `RuntimeMetricSummationFilter` — фильтр, определяющий, какие пути `runtime/metrics` экспортируются. Возврат `true` включает все доступные метрики.
- `promhttp.HandlerFor` — создает обработчик для кастомного реестра; позволяет контролировать формат экспозиции и обработку ошибок.

## Практические сценарии

### Пошаговая настройка экспозиции метрик

**Шаг 1. Добавление зависимости**
```bash
go get github.com/prometheus/client_golang@latest
```

**Шаг 2. Инициализация реестра и коллектора**

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
    reg := prometheus.NewRegistry()

    goCollector := prometheus.NewGoCollector(
        prometheus.GoCollectorOptions{
            RuntimeMetricSummationFilter: func(name string) bool { return true },
        },
    )
    reg.MustRegister(goCollector)

    http.Handle("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
    http.ListenAndServe(":8080", nil)
}
```

**Шаг 3. Настройка контейнера (Dockerfile)**

```dockerfile
FROM golang:1.25-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app/server .

FROM alpine:latest
RUN apk --no-cache add ca-certificates
COPY --from=builder /app/server /app/server

ENV GOMEMLIMIT=450MiB
ENV GOGC=100

EXPOSE 8080
ENTRYPOINT ["/app/server"]
```

**Шаг 4. Настройка systemd-сервиса (на хосте)**

```ini
# /etc/systemd/system/go-app.service
[Unit]
Description=Go Application with Prometheus Metrics
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/go-app
ExecStart=/opt/go-app/server
Environment=GOMEMLIMIT=450MiB
Environment=GOGC=100
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now go-app
```

**Шаг 5. Проверка конфигурации окружения**

```bash
# Проверка видимых рантаймом значений
go env GOMAXPROCS GOMEMLIMIT GOGC
# → GOMAXPROCS=8
# → GOMEMLIMIT=450MiB
# → GOGC=100

# Проверка лимитов cgroup (внутри контейнера)
cat /sys/fs/cgroup/memory.max
# → 500000000 (500 MiB)
```

### Валидация работоспособности

**Через curl:**

```bash
curl -s http://localhost:8080/metrics | grep "go_goroutines"
# → go_goroutines 42

curl -s http://localhost:8080/metrics | grep "go_gc_duration_seconds"
# → go_gc_duration_seconds{quantile="0.5"} 0.00012
# → go_gc_duration_seconds{quantile="0.99"} 0.00045
# → go_gc_duration_seconds_sum 0.1234
# → go_gc_duration_seconds_count 1234

curl -s http://localhost:8080/metrics | grep "go_sched_latencies_seconds"
# → go_sched_latencies_seconds_bucket{le="0.0001"} 1245
# → go_sched_latencies_seconds_sum 0.5678
# → go_sched_latencies_seconds_count 2345
```

**PromQL — проверка сбора метрик:**

```promql
# Убедитесь, что метрики поступают в Prometheus
up{job="go-app"} == 1

# Проверка базовых метрик
go_goroutines > 0
go_info == 1
```

### 1. Утечка горутин (Goroutine Leak)

**Признак:** Монотонный линейный рост `go_goroutines` без выхода на плато при стабильной нагрузке.

**Наблюдения:**
- `go_threads` — обычно остается стабильным, так как горутины в Go мультиплексируются.
- `go_sched_latencies_seconds` — гистограмма может показывать рост задержек при переполнении очереди планировщика.
- **Детекция:** Если количество горутин растет пропорционально количеству запросов, но не падает после их завершения — утечка подтверждена.
- **Причина:** Заблокированные каналы, отсутствие `context.Cancel()` или бесконечные циклы без условий выхода.

**PromQL — детекция утечек:**

```promql
# Рост горутин на 20% за час
go_goroutines / (go_goroutines offset 1h) > 1.2

# Детекция скачков при старте
changes(go_goroutines[5m]) > 50
```

**Диагностика:**

```bash
# Получение дампа горутин
curl -s http://localhost:8080/debug/pprof/goroutine?debug=1 > goroutine_dump.txt

# Фильтрация заблокированных горутин
grep -A 5 "goroutine [0-9]* \[" goroutine_dump.txt | grep -E "chan|select|semacquire"
```

**Решение:**
- Добавить `context.WithTimeout` или `context.WithCancel` во все операции, ожидающие внешних ресурсов.
- Использовать `errgroup.WithContext` для группировки горутин с общим таймаутом.
- Настроить алерт на линейный рост `go_goroutines` в течение 15–30 минут.

### 2. Давление на сборщика мусора (GC Pressure)

**Сценарий:** Интенсивное создание короткоживущих объектов с большим количеством указателей.

**Наблюдения:**
- `go_memstats_heap_alloc_bytes` — высокая базовая нагрузка на heap.
- `go_gc_cycles_total` — резкий рост частоты циклов сборки.
- `go_gc_duration_seconds_sum` — суммарное время GC растет пропорционально нагрузке.
- `/cpu/classes/gc/total:seconds` — значительная доля CPU тратится на работу рантайма, а не бизнес-логики.
- **Вывод:** Высокий GC Pressure ведет к троттлингу приложения. Решение — переиспользование объектов через `sync.Pool`.

**PromQL — детекция GC Thrashing:**

```promql
# GC занимает более 10% CPU времени
rate(go_gc_duration_seconds_sum[5m])
  / rate(go_gc_duration_seconds_sum[5m] + go_sched_latencies_seconds_sum[5m]) > 0.1

# Частота циклов GC выше 10 в секунду
rate(go_gc_cycles_total[1m]) > 10
```

**Решение:**
- Внедрить `sync.Pool` для часто создаваемых объектов (буферы, структуры запросов).
- Увеличить `GOGC` до 200–500 для снижения частоты циклов GC (при наличии достаточной памяти).
- Проверить код на анонимные boxing/unboxing интерфейсов.

### 3. Задержки планировщика (Scheduler Latency)

**Признак:** Приложение «тормозит» при наличии свободных ресурсов CPU.

**Наблюдения:**
- `go_sched_latencies_seconds` — гистограмма показывает смещение в сторону высоких значений (мс).
- `go_goroutines` — может оставаться стабильным, несмотря на деградацию задержки.
- **Причина:** Горутины слишком долго ждут в очереди на выполнение. Часто вызвано избыточным использованием CGO или системными вызовами, блокирующими потоки планировщика.
- **Решение:** Профилирование блокировок (`go tool pprof --block`).

**Диагностика:**

```bash
# CPU-профиль (30 секунд)
go tool pprof -http=:8080 http://localhost:8080/debug/pprof/profile?seconds=30

# Блокировки
go tool pprof -http=:8080 http://localhost:8080/debug/pprof/block

# Трассировка планировщика
go tool trace http://localhost:8080/debug/pprof/trace?seconds=5
```

### 4. Конкуренция за мьютексы (Mutex Contention)

**Признак:** Низкая утилизация CPU при плохой масштабируемости под нагрузкой.

**Наблюдения:**
- `go_mutex_wait_duration_seconds` — рост суммарного времени ожидания.
- **Анализ:** Метрика показывает, сколько времени горутины проводят в ожидании освобождения блокировок.
- **Оптимизация:** Уменьшение критических секций, переход на `atomic` операции или использование `RWMutex`.

**PromQL — детекция contention:**

```promql
# Среднее время ожидания на мьютексах > 1мс
rate(go_mutex_wait_duration_seconds_sum[5m])
  / rate(go_mutex_wait_duration_seconds_count[5m]) > 0.001
```

**Диагностика:**

```bash
# Профиль мьютексов
go tool pprof -http=:8080 http://localhost:8080/debug/pprof/mutex
```

### 5. Лимит памяти и фрагментация

**Сценарий:** Приложение потребляет больше памяти, чем ожидалось, несмотря на низкий `HeapAlloc`.

**Наблюдения:**
- `go_memstats_sys_bytes` растет значительно быстрее `go_memstats_heap_alloc_bytes`.
- `go_gc_heap_frag_bytes` — высокий уровень фрагментации.
- `go_memstats_stack_sys_bytes` — рост может указывать на создание тысяч горутин с большими стеками.
- **Интерпретация:** Рантайм удерживает память у ОС «на всякий случай» или из-за невозможности уплотнения кучи. В Go 1.24 `GOMEMLIMIT` помогает рантайму чаще возвращать такие фрагменты через `madvise`.

**Диагностика:**

```bash
# Текущие лимиты cgroup
cat /sys/fs/cgroup/memory.max
cat /sys/fs/cgroup/memory.current

# Сравнение с видимыми для Go лимитами
go env GOMEMLIMIT
```

### Типичные ошибки и устранение неполадок

| Проблема | Причина по метрикам | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **Утечка горутин** | Линейный рост `go_goroutines` | `curl -s localhost:8080/debug/pprof/goroutine?debug=1` | Найти горутины, заблокированные на `select` без `context.Done()` или на канале без reader. |
| **OOMKilled при малом Heap** | `go_memstats_sys_bytes` растет, `GOMEMLIMIT` не задан или задан ниже `limits.memory` | `docker inspect --format='{{.State.OOMKilled}}' <container>`; `cat /sys/fs/cgroup/memory.max` | Установить `GOMEMLIMIT=80-90%` от лимита RAM. Проверить аллокации вне кучи (CGO, стеки). |
| **GC Thrashing** | Высокий `go_gc_duration_seconds_sum` при росте `go_memstats_heap_alloc_bytes` | `curl -s localhost:8080/debug/pprof/heap` | Увеличить `GOGC`, внедрить объектные пулы (`sync.Pool`), проверить код на создание миллионов короткоживущих объектов. |
| **Высокая латентность при низком CPU** | Рост `go_mutex_wait_duration_seconds` или `go_sched_latencies_seconds` | `go tool pprof http://localhost:8080/debug/pprof/mutex`; `go tool trace` | Провести профилирование блокировок, оптимизировать критические секции, перейти на `atomic` операции. |
| **Рост RSS без роста Heap** | `go_memstats_sys_bytes` >> `go_memstats_heap_alloc_bytes` | `cat /proc/<PID>/smaps`; `go tool pprof http://localhost:8080/debug/pprof/heap` | Проверить фрагментацию кучи (`go_gc_heap_frag_bytes`), увеличить `GOMEMLIMIT`, рассмотреть рестарт по расписанию. |

### Рекомендации и лучшие практики

1.  **GOMEMLIMIT:**
    Устанавливайте `GOMEMLIMIT` на 10–20% ниже `limits.memory` контейнера. Оставшиеся 10–20% необходимы для стеков горутин, метаданных рантайма и аллокаций вне кучи.

2.  **GOGC:**
    По умолчанию `GOGC=100` (GC запускается при удвоении heap). Для приложений с большим запасом памяти можно увеличить до 200–500, снижая частоту GC.

3.  **Scrape Interval:**
    Используйте интервал скрапинга 15–30 секунд. Для метрик `go_gc_duration_seconds` (Summary) короткий интервал важен для точности квантилей.

4.  **Cardinality:**
    Метрики рантайма Go имеют фиксированный набор лейблов (обычно только `job`, `instance`). Не добавляйте к ним высококардинальные лейблы (например, `user_id`, `trace_id`).

5.  **Graceful Shutdown:**
    При завершении работы приложения метрики автоматически помечаются как `stale`. Убедитесь, что HTTP-сервер закрывается корректно (`http.Server.Shutdown`), чтобы `promhttp` успел экспортировать stale markers.

6.  **Multi-process (Fork):**
    Если приложение форкается (например, через `os/exec`), убедитесь, что дочерний процесс не унаследовал HTTP-сервер с `/metrics`. Используйте `prometheus.ProcessCollector` для сбора метрик самого процесса (PID, открытые файлы, дескрипторы).

### Особенности и граничные случаи

1.  **Взаимодействие с cgroups:**
    Go 1.25+ автоматически считывает `cpu.max` из cgroups v2 и корректирует `GOMAXPROCS`. Однако `GOMEMLIMIT` по-прежнему требует явного задания. Для автоматического расчета используйте библиотеку `uber-go/automemlimit`:

    ```bash
    go get github.com/uber-go/automemlimit
    ```

2.  **Высокая кардинальность нативных гистограмм:**
    При включении всех `runtime/metrics` количество временных рядов может вырасти в 10–100 раз. Оцените нагрузку на Prometheus TSDB перед деплоем в production.

3.  **CGO и внешние аллокации:**
    Метрики `go_memstats_*` не учитывают память, выделенную через CGO (например, библиотеки `libvips`, `openssl`). Для мониторинга внешней памяти используйте `process_resident_memory_bytes` (node_exporter) и сравнивайте с `go_memstats_sys_bytes`.

4.  **GOMEMLIMIT и In-Place Pod Resize:**
    При динамическом изменении лимитов памяти пода (Kubernetes In-Place Resize) `GOMEMLIMIT` не обновляется автоматически. Используйте `automemlimit` для отслеживания изменений в `/sys/fs/cgroup/memory.max`.

5.  **Stale Markers при рестарте:**
    При обновлении деployment в Kubernetes Prometheus получает `stale NaN` для всех метрик при остановке старого pod. Убедитесь, что алерты имеют достаточный `for:` duration (не менее 2–3 scrape intervals), чтобы не срабатывать на transient stale.

6.  **Summary vs Histogram:**
    Метрика `go_gc_duration_seconds` является `Summary` и вычисляет квантили на стороне клиента. При изменении числа вызовов между scrapes квантили могут пересчитываться. Для детерминированного мониторинга используйте `Histogram` (нативные гистограммы в Prometheus 3.0+), если приложение экспортирует GC задержки через `runtime/metrics`.

## Рекомендации по визуализации

*   **Логарифмическая шкала:** Используйте для `go_goroutines` и `go_sched_latencies_seconds`. Это позволяет видеть одновременно и нормальное состояние, и аномальные выбросы.
*   **Стековые графики (Stacking):** Для метрик памяти (`go_memstats_heap_alloc_bytes`, `go_memstats_stack_sys_bytes`, `go_memstats_buck_hash_sys_bytes`) для наглядного понимания распределения ресурсов.
*   **Rate vs Absolute:** Для счетчиков (Counter) всегда используйте `rate()` или `irate()`. Абсолютные значения счетчиков рантайма бесполезны для диагностики в моменте.
*   **Heatmap для гистограмм:** Используйте `go_sched_latencies_seconds` в виде heatmap для визуализации эволюции задержек планировщика под нагрузкой.

## Дополнительная информация

*   [Тестирование экспортеров](./exporter_testing.md) — бенчмарки Go экспортеров и профилирование.
*   [Надежность экспортеров](./exporter_reliability.md) — graceful degradation для Go экспортеров.
*   [Официальный список метрик runtime/metrics](https://pkg.go.dev/runtime/metrics) — эталонный справочник путей.
*   [Руководство по GC в Go](https://go.dev/doc/gc-guide) — детальное описание работы GOMEMLIMIT и папок памяти.
*   [Инструментация приложений](./client_libraries.md) — общие подходы к сбору метрик.
*   [Метрики рантайма приложений — языковая специфика](../../Concepts/Observability_and_Monitoring/application_runtime_metrics.md) — кросс-языковое сравнение метрик (Go, JVM, Node.js, Python, .NET).
*   [Протокол OTLP](../../OpenTelemetry/otlp_protocol.md) — использование бинарных форматов для передачи метрик рантайма.
