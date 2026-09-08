# Метрики рантайма приложений -- Языковая специфика

## Определения

**Метрики рантайма (Runtime Metrics)** -- системные показатели, генерируемые средой выполнения приложения (виртуальной машиной, интерпретатором или рантаймом языка). Они отражают внутренние механизмы процесса: управление памятью (Heap, Non-Heap), работу планировщика (Scheduler), состояние потоков (Threads) и эффективность сборщика мусора (GC). Метрики рантайма позволяют выявить проблемы производительности, недоступные при стандартном мониторинге хоста или контейнера, -- например, блокировку Event Loop в Node.js или конкуренцию за GIL в Python.

**Stop-the-world (STW)** -- состояние рантайма (особенно JVM и Go), при котором выполнение всех прикладных потоков приостанавливается для выполнения системных задач, чаще всего -- фаз сборки мусора. Длительные STW-паузы напрямую влияют на P99 задержку. Современные 수집щики (ZGC, Shenandoah) минимизируют STW до sub-millisecond, но классические (Serial, CMS) могут вызывать паузы в десятки и сотни миллисекунд.

**Конкуренция за потоки (Thread Contention)** -- ситуация, когда несколько потоков одновременно пытаются получить доступ к общему ресурсу (мьютексу или секции кода), что приводит к простоям и снижению производительности при росте нагрузки. Измеряется через time-to-synchronized-operation и глубину очереди блокировок.

**Осведомлённость о контейнерах (Container Awareness)** -- способность рантайма корректно определять и соблюдать лимиты ресурсов (CPU, RAM), установленные через механизмы `cgroups` (v1/v2), предотвращая аномальное поведение или принудительное завершение процесса ядром (OOMKiller). Рантаймы без container awareness могут игнорировать лимиты контейнера и потреблять ресурсы хоста, что приводит к непредсказуемому OOM Kill.

**Garbage Collection (GC)** -- автоматический менеджер памяти, освобождающий неиспользуемую память. Основные стратегии: поколенческая (Generational -- молодые объекты собираются часто, старые -- реже), конкурентная (работает параллельно с приложением, минимизируя STW) и референс-счётинг (используется в Python, Ruby). Ключевые параметры тюнинга: отношение GC к CPU (`GOGC` в Go),soft-лимит памяти (`GOMEMLIMIT`), процент.heap от доступной RAM (`MaxRAMPercentage` в JVM).

---

## Основные концепции

В 2026 году мониторинг рантаймов базируется на глубокой интеграции с ядром Linux и современными стандартами наблюдаемости:

1.  **Иерархия ресурсов (Cgroups v2):** Мониторинг должен учитывать не только абсолютные значения, но и «давление» на ресурсы через **[PSI (Pressure Stall Information)](../../Linux/Core/kernel/psi.md)**. Cgroups v2 (единая иерархия) является стандартом для Kubernetes 1.25+ и современных дистрибутивов (Ubuntu 22.04+, RHEL 9+). Рантаймы должны корректно читать `memory.max`, `cpu.max` и `io.max` из cgroupfs.

2.  **Методология RED:** Рантайм-метрики позволяют найти причину деградации RED-показателей (например, GC-паузы увеличивают Duration). Если Request Rate стабилен, а Error Rate растет совместно с ростом GC Time -- проблема в памяти, а не в трафике.

3.  **Методология USE:** Применяется для оценки «здоровья» внутренних пулов (например, пула потоков или очереди планировщика). Утизация = количество активных потоков / размер пула. Насыщение = длина очереди задач. Ошибки = количество rejected/failed tasks.

4.  **Синергия с профилированием:** Метрики рантайма указывают *что* тормозит (например, рост `go_mutex_wait_duration`), а **[непрерывное профилирование](../continuous_profiling.md)** показывает *где именно* в коде находится проблемный мьютекс. Комбинация метрик + профилей -- основа modern SRE-диагностики.

5.  **Конфигурация рантайма для контейнеров:** Правильная настройка параметров памяти и CPU критична для предотвращения OOM Kill и throttling. Каждый язык имеет свои особенности (см. разделы ниже).

---

## Конфигурация рантайма для контейнеров

Корректная настройка рантайма -- первый шаг к стабильной работе в контейнерах. Ошибка в конфигурации приводит к OOM Kill (exit code 137) или CPU throttling.

### JVM (Java)

Современные JVM (11+) нативно поддерживают container awareness через чтение `cgroupfs`. Ключевые параметры:

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-XX:MaxRAMPercentage=75.0` | Процент от лимита RAM контейнера для Heap | Использовать вместо фиксированного `-Xmx` |
| `-XX:+UseZGC` | Низко-латентный GC (Java 15+) | Паузы < 1мс, рекомендуется для latency-critical |
| `-XX:+UseZGC -XX:+ZGenerational` | Поколенческий ZGC (Java 21+) | Еще лучшая производительность для аллокаций |
| `-XX:+UseShenandoahGC` | Альтернатива ZGC | Паузы < 10мс |

**Пример конфигурации контейнера:**
```bash
java -XX:MaxRAMPercentage=75.0 \
     -XX:+UseZGC \
     -XX:+ZGenerational \
     -jar application.jar
```

*Подробности: [Docker best practices for Java](../../Docker/Dockerfile/Docker_best_practices/java.md).*

### Go (Golang)

Начиная с Go 1.25, рантайм автоматически считывает лимиты CPU из cgroups (v1/v2), делая ручную настройку `GOMAXPROCS` избыточной. Однако `GOMEMLIMIT` по-прежнему требует явного задания:

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `GOMEMLIMIT=90%RAM` | Мягкий лимит памяти для GC | 80-90% от `limits.memory` контейнера |
| `GOGC=100` | Отношение новых аллокаций к GC (по умолчанию) | Увеличить до 200+ для снижения частоты GC |
| `GOMAXPROCS` | Количество потоков планировщика (P) | Auto в Go 1.25+; ранее -- `uber-go/automaxprocs` |

**Пример Dockerfile:**
```dockerfile
ENV GOMEMLIMIT=450MiB
ENV GOGC=100
```

*Подробности: [Docker best practices for Go](../../Docker/Dockerfile/Docker_best_practices/go.md), [Метрики рантайма Go](../../Prometheus/Exporters/extensibility/go_runtime_metrics.md).*

### Node.js

Node.js не имеет нативной container awareness для памяти. V8 использует собственные лимиты `max_old_space_size`, которые по умолчанию не привязаны к cgroups:

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--max-old-space-size=<MB>` | Максимальный размер V8 Heap | 70-80% от лимита RAM контейнера |
| `--max-semi-space-size=<MB>` | Размер young generation | По умолчанию адекватно; увеличить при частых minor GC |
| Worker Threads | Параллельные вычисления | Каждый воркер имеет свой V8 Heap |

**Пример конфигурации:**
```bash
node --max-old-space-size=384 application.js
# При лимите контейнера 512MiB: 384MB = 75%
```

*Подробности: [Docker best practices for Node.js](../../Docker/Dockerfile/Docker_best_practices/nodejs.md).*

### Python

Python 3.14+ улучшил container awareness, но для тяжелых приложений рекомендуется ручная настройка аллокатора:

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `MALLOC_ARENA_MAX=2` | Ограничение arenas аллокатора glibc | Снижение RSS overhead |
| `PYTHONDONTWRITEBYTECODE=1` | Отключение компиляции .pyc | Экономия I/O в контейнерах |
| No-GIL (Python 3.13+) | Режим без GIL | Требует мониторинга thread contention вместо GIL |

*Подробности: [Docker best practices for Python](../../Docker/Dockerfile/Docker_best_practices/python.md).*

### .NET

.NET имеет нативную поддержку cgroups v2. Ключевые параметры:

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `DOTNET_gcServer=0` | Потребительский GC (меньше памяти) | Для < 2 CPU ядер |
| `DOTNET_gcServer=1` | Серверный GC (больше параллелизма) | Для 2+ ядер |
| `DOTNET_GCHeapHardLimit` | Жесткий лимит Heap в байтах | 75% от лимита RAM контейнера |

*Подробности: [Docker best practices for .NET](../../Docker/Dockerfile/Docker_best_practices/dotnet.md).*

---

## Метрики по языкам программирования

### 1. Java (JVM)
Современная JVM (Java 21, 25+) ориентирована на низкие задержки и эффективную работу в контейнерах. JVM автоматически определяет количество ядер и объем памяти через `cgroupfs` (v1/v2).

#### Ключевые метрики

| Категория | Метрика | Анализ и критические пороги |
| :--- | :--- | :--- |
| **GC** | `jvm_gc_pause_seconds` | Длительность STW. Для ZGC/Shenandoah норма < 1мс. Для G1GC -- < 200мс. |
| **GC Thrashing** | `rate(jvm_gc_pause_seconds_sum[5m])` | Если GC time > 10% CPU time -- проблема с памятью. |
| **Hiccups** | `jvm_runtime_hiccups_seconds` | **Критично для SRE:** Измеряет время «замирания» рантайма из-за внешних факторов (CPU троттлинг, контекстные переключения). |
| **Safepoints** | `jvm_runtime_safepoint_time_seconds` | Время приостановки всех потоков. Рост указывает на проблемы синхронизации или JIT-деоптимизацию. |
| **Native Memory** | `jvm_native_memory_total_bytes` | Память вне управления JVM (Direct Buffer, JNI). Причина «скрытых» OOM. |
| **Heap** | `jvm_memory_used_bytes` | Текущий объем Heap. Сравнивать с `jvm_memory_max_bytes`. |
| **Metaspace** | `jvm_memory_pool_bytes` | Память для классов и метаданных. Рост = утечка классов (для OTel/Java агентов). |

#### Диагностика GC

```bash
# Включить логирование GC (для анализа в-development)
java -Xlog:gc*:file=gc.log:time,uptime,level,tags -jar app.jar

# Просмотр текущего GC алгоритма
java -XX:+PrintFlagsFinal -version 2>&1 | grep -i "use.*gc"
# → useZGC := true
```

**PromQL -- детекция GC Thrashing:**
```promql
# Детекция GC Thrashing (когда GC занимает более 10% времени CPU)
rate(jvm_gc_pause_seconds_sum[5m]) / (rate(container_cpu_usage_seconds_total[5m]) or rate(process_cpu_seconds_total[5m])) > 0.1
```

**PromQL -- корреляция GC с памятью:**
```promql
# Рост GC time при приближении к лимиту памяти
jvm_memory_used_bytes / jvm_memory_max_bytes > 0.85
  and
rate(jvm_gc_pause_seconds_sum[5m]) > 0.05
```

### 2. Go (Golang)
Метрики Go 1.22+ предоставляют глубокий доступ к планировщику через `runtime/metrics`. В Go 1.24+ доступны нативные гистограммы для задержек.

#### Ключевые метрики

| Категория | Метрика | Анализ и критические пороги |
| :--- | :--- | :--- |
| **Планировщик** | `go_sched_latencies_seconds` | Время ожидания горутины в очереди. Рост = нехватка CPU или проблема с `GOMAXPROCS`. |
| **Горутины** | `go_goroutines` | Текущее кол-во. Линейный рост = Goroutine Leak. Стабильный уровень -- индикатор здорового приложения. |
| **Мьютексы** | `go_mutex_wait_duration_seconds` | Время простоя на блокировках. Критично для многопоточных API. |
| **Heap** | `go_memstats_heap_alloc_bytes` | Текущий объем Heap. Рост выше `GOMEMLIMIT` приводит к агрессивному GC. |
| **Sys** | `go_memstats_sys_bytes` | Общая память, выделенная у ОС. Включает heap, стеки, кэши. |
| **GC Cycles** | `go_gc_duration_seconds` | Статистика по паузам GC. Использовать `quantile(0.99)` для P99. |

#### Диагностика Go

```bash
# Просмотр текущих значений GOMAXPROCS и GOMEMLIMIT
go env GOMAXPROCS GOMEMLIMIT
# → 4
# → 4294967296 (4 GiB)

# Профилирование горутин (pprof)
curl -s http://localhost:6060/debug/pprof/goroutine?debug=1 | head -30
```

**PromQL -- детекция утечек горутин:**
```promql
# Поиск утечек горутин (рост за час > 20%)
go_goroutines / (go_goroutines offset 1h) > 1.2
```

**PromQL -- конкуренция за мьютексы:**
```promql
# Среднее время ожидания на мьютексах > 1мс
rate(go_mutex_wait_duration_seconds_sum[5m]) / rate(go_mutex_wait_duration_seconds_count[5m]) > 0.001
```

*Детальный разбор: **[Метрики рантайма Go](../../Prometheus/Exporters/extensibility/go_runtime_metrics.md)**.*

### 3. Node.js
Основной фокус -- Event Loop, так как его блокировка парализует все приложение. В отличие от JVM и Go, Node.js单线程 для прикладного кода, что делает метрики Event Loop критичными.

#### Ключевые метрики

| Категория | Метрика | Анализ и критические пороги |
| :--- | :--- | :--- |
| **Event Loop** | `nodejs_eventloop_lag_seconds` | Лаг цикла. > 100мс -- критическая деградация. > 500мс -- приложение фактически не отвечает. |
| **Event Loop Lag (p99)** | `nodejs_eventloop_lag_p99_seconds` | 99-й перцентиль. Высокий p99 при нормальном среднем = редкие, но тяжелые блокировки. |
| **V8 Heap** | `nodejs_heap_space_size_used_bytes` | Расход памяти по сегментам (read_only, pointer, old, code, large_object). |
| **External Memory** | `nodejs_external_memory_bytes` | Буферы и C++ объекты (Buffer, WASM). Часто причина утечек за пределы V8. |
| **Active Handles** | `nodejs_active_handles_total` | Количество активных handle (TCP, timers). Рост = утечка соединений или таймеров. |

#### Диагностика Node.js

```bash
# Проверка текущего max-old-space-size
node -e "console.log(process.memoryUsage())"
# → { rss: 52428800, heapTotal: 35651584, heapUsed: 21487120, external: 1234567 }

# Включить диагностику Event Loop
NODE_DEBUG=event_loop node application.js
```

**PromQL -- детекция блокирующего I/O:**
```promql
# Детекция блокирующего I/O (лаг > 200мс)
nodejs_eventloop_lag_seconds > 0.2
```

**PromQL -- утечка памяти за пределы V8:**
```promql
# External memory растет линейно
deriv(nodejs_external_memory_bytes[30m]) > 0
```

### 4. Python (3.13+ Free-threaded)
С приходом режима **No-GIL** (PEP 703, Python 3.13+), мониторинг смещается от GIL к конкуренции потоков. В режиме по умолчанию (с GIL) основная проблема -- CPU-bound задачи в одном потоке.

#### Ключевые метрики

| Категория | Метрика | Анализ и критические пороги |
| :--- | :--- | :--- |
| **GIL** | `python_gil_contention_total` | Время борьбы за блокировку (в GIL-режиме). Рост = CPU-bound нагрузка. |
| **Threads** | `python_thread_contention_seconds` | Борьба за общие объекты (в No-GIL режиме). Аналог `go_mutex_wait_duration`. |
| **AsyncIO** | `python_asyncio_active_tasks` | Количество активных корутин. Стабильный рост = утечка задач. |
| **GC** | `python_gc_objects` | Количество объектов в поколениях. Рост = утечка памяти. |

#### Диагностика Python

```bash
# Профилирование через py-spy (без GIL overhead)
py-spy top --pid <PID>
py-spy record -o flamegraph.svg --duration 30 --pid <PID>

# Проверка текущего GIL contention
python -c "import sys; print(sys._getframe())"
```

*Подробнее: [Профилирование Python](./profiling_deep_dive.md).*

### 5. Rust (Tokio)
Асинхронные рантаймы (Tokio) требуют мониторинга планировщика задач. Rust не имеет GC, поэтому фокус смещается на конкуренцию за мьютексы и задержки планировщика.

#### Ключевые метрики

| Категория | Метрика | Анализ и критические пороги |
| :--- | :--- | :--- |
| **Tokio Tasks** | `tokio_task_count` | Количество активных задач. Стабильный рост = утечка. |
| **Scheduling Delay** | `tokio_task_scheduling_delay_seconds` | Задержка перед запуском задачи. Индикатор перегрузки worker threads. |
| **Worker Threads** | `tokio_worker_count` | Количество активных worker threads. Должно быть равно `tokio::runtime::Builder::worker_threads`. |
| **Poll Duration** | `tokio_task_poll_duration_seconds` | Время выполнения одного poll. Длительные poll блокируют event loop. |

#### Диагностика Rust/Tokio

```bash
# tokio-console -- real-time мониторинг задач
cargo install tokio-console
tokio-console http://localhost:6669

# Проверка количества worker threads
# В коде: tokio::runtime::Builder::new_multi_thread().worker_threads(4)
```

### 6. .NET (Core)
Современный .NET предоставляет богатые метрики через `EventCounters` или `OpenTelemetry`. Рантайм нативно поддерживает cgroups v2 и корректно определяет количество ядер.

#### Ключевые метрики

| Категория | Метрика | Анализ и критические пороги |
| :--- | :--- | :--- |
| **GC** | `dotnet_gc_pause_ratio` | Процент времени, затраченный на GC. > 5% -- проблема. |
| **GC Heap** | `dotnet_gc_heap_size_bytes` | Размер Heap. Сравнивать с `DOTNET_GCHeapHardLimit`. |
| **ThreadPool** | `dotnet_threadpool_queue_length` | Глубина очереди задач в пуле потоков. Рост > 5 минут = утечка. |
| **ThreadPool** | `dotnet_threadpool_thread_count` | Количество рабочих потоков. Должно адаптироваться к нагрузке. |
| **Exceptions** | `dotnet_exceptions_thrown_total` | Частота выброса исключений. Частые исключения = проблема в коде. |
| **Lock Contention** | `dotnet_monitor_lock_contention_count` | Количество конфликтов блокировок. |

#### Диагностика .NET

```bash
# dotnet-counters -- real-time метрики
dotnet-counters monitor -p <PID> \
  --counters System.Runtime,Microsoft.AspNetCore.Hosting

# dotnet-trace -- запись трассировки
dotnet-trace collect -p <PID> --duration 00:00:30
```

---

## Диагностика и устранение неполадок

### Таблица типичных проблем

| Проблема | Причина по метрикам | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **Рост P99 при низком CPU** | Рост `go_mutex_wait` или `jvm_runtime_safepoint_time` | `go tool pprof http://localhost:6060/debug/pprof/mutex`; `jcmd <pid> Thread.print` | Провести профилирование блокировок (Mutex Profiling), оптимизировать критические секции. |
| **OOMKilled при малом Heap** | Рост `jvm_native_memory` или `nodejs_external_memory` | `docker inspect --format='{{.State.OOMKilled}}' <container>`; `cat /sys/fs/cgroup/memory.max` | Проверить использование Direct Buffers, JNI или нативных модулей C++. Увеличить лимиты контейнера или настроить `MaxRAMPercentage`/`GOMEMLIMIT`. |
| **GC Thrashing** | Высокий `jvm_gc_pause_seconds_sum` при росте `jvm_memory_used` | `jcmd <pid> GC.heap_info`; `curl -s localhost:6060/debug/pprof/heap` | Увеличить `-Xmx`/`MaxRAMPercentage`, проверить код на создание миллионов короткоживущих объектов, внедрить объектные пулы. |
| **Event Loop Freeze** | Высокий `nodejs_eventloop_lag` | `node --prof application.js`; Flamegraph через `0x` | Найти в коде синхронные операции (JSON.parse огромных объектов, синхронное чтение файлов, CPU-intensive вычисления). |
| **Goroutine Leak** | Линейный рост `go_goroutines` | `curl -s localhost:6060/debug/pprof/goroutine?debug=1` | Найти горутины, которые заблокированы на `select` без `context.Done()` или на канале без reader. |
| **Thread Starvation (.NET)** | Рост `dotnet_threadpool_queue_length` | `dotnet-trace collect -p <PID>` с `System.Threading.ThreadPoolEventSource` | Проверить синхронные вызовы `Task.Result`/`Task.Wait()` в ThreadPool потоках. Перейти на `async/await`. |

### Пошаговый workflow диагностики

1.  **Определите язык рантайма** -- какой стек используется (JVM, Go, Node.js, Python, .NET).
2.  **Проверьте лимиты контейнера** -- `docker stats --no-stream` или `kubectl top pod`.
3.  **Соберите метрики рантайма** -- убедитесь, что экспортеры настроены и данные поступают.
4.  **Корреляция с RED/USE** -- сопоставьте рантайм-метрики с задержкой, ошибками и нагрузкой.
5.  **Профилирование** -- используйте flamegraph для точного поиска узкого места.
6.  **Валидация исправления** -- после изменений повторите измерения и убедитесь в стабильности.

---

## Практические сценарии

### Интеграция с OpenTelemetry (OTel)
В 2026 году рекомендуется использовать OTel SDK для унификации сбора метрик рантайма:

*   **Exemplars:** Связывайте аномальные выбросы метрик с конкретными Trace ID (например, тяжелый SQL-запрос вызвал GC Spike). Пример: если `jvm_gc_pause_seconds` spike совпадает с Trace ID тяжелого запроса -- корень проблемы в аллокациях внутри этого запроса.
*   **Semantic Conventions:** Используйте стандартные префиксы `process.runtime.*` для кросс-языковой совместимости. Метрики с этими префиксами автоматически коррелируются в Grafana и Datadog.

### Настройка экспортеров метрик рантайма

#### JVM: Micrometer + Prometheus

```yaml
# application.yml (Spring Boot)
management:
  endpoints:
    web:
      exposure:
        include: prometheus,health
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true
    tags:
      application: ${spring.application.name}
```

```xml
<!-- pom.xml: зависимость для runtime metrics -->
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

**Валидация:**
```bash
curl -s localhost:8080/actuator/prometheus | grep "jvm_gc_pause_seconds"
# → jvm_gc_pause_seconds_count{action="end of major GC",area="heap",} 42.0
```

#### Go: client_golang

```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
    // Автоматически регистрирует Go runtime metrics
    reg := prometheus.DefaultRegisterer
    _ = reg // GoCollector уже зарегистрирован

    http.Handle("/metrics", promhttp.Handler())
    http.ListenAndServe(":2112", nil)
}
```

**Валидация:**
```bash
curl -s localhost:2112/metrics | grep "go_goroutines"
# → go_goroutines 42
```

#### Node.js: prom-client

```javascript
const client = require('prom-client');

// Собирает метрики Event Loop, heap, GC
client.collectDefaultMetrics({ prefix: 'nodejs_' });

app.get('/metrics', async (req, res) => {
    res.set('Content-Type', client.register.contentType);
    res.end(await client.register.metrics());
});
```

**Валидация:**
```bash
curl -s localhost:9090/metrics | grep "nodejs_eventloop_lag_seconds"
# → nodejs_eventloop_lag_seconds 0.001234
```

### Настройка алертинга на базе SLO
Избегайте алертинга на «шумные» метрики. Используйте комбинированные условия:

1.  **Memory Saturation (JVM):** Алертить, если `jvm_memory_used_bytes / jvm_memory_max_bytes > 0.9` AND `rate(jvm_gc_pause_seconds_sum[5m]) > 0.1`.
2.  **Thread Exhaustion (.NET):** Алертить, если `dotnet_threadpool_queue_length` растет более 5 минут подряд.
3.  **Goroutine Leak (Go):** Алертить, если `go_goroutines / (go_goroutines offset 1h) > 1.3`.
4.  **Event Loop Block (Node.js):** Алертить, если `nodejs_eventloop_lag_seconds > 0.5` более 2 минут.
5.  **GC Thrashing (Go):** Алертить, если `rate(go_gc_duration_seconds_sum[5m]) > 0.1`.

### Валидация работы рантайма в контейнере

```bash
# Проверка что JVM видит лимиты контейнера
docker run --rm -m 512m openjdk:21 java -XshowSettings:all -version 2>&1 | grep -i "memory\|cpu"
# → Max Heap Size: 128M (auto-detected)
# → Available processors: 2

# Проверка что Go видит GOMAXPROCS
docker run --rm -m 512m --cpus=2 golang:1.25 go env GOMAXPROCS
# → 2

# Проверка потребления памяти процесса
docker stats --no-stream <container>
# → MEM USAGE / LIMIT
# → 345MiB / 512MiB
```

---

## Дополнительная информация

### См. также
*   **[Методологии мониторинга (RED, USE)](./monitoring_methodologies.md)**
*   **[Наблюдаемость в контейнерах](./observability_in_containers.md)**
*   **[Давление на ресурсы (PSI)](../../Linux/Core/kernel/psi.md)**
*   **[Непрерывное профилирование](../continuous_profiling.md)**
