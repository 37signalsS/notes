# Непрерывное профилирование (Continuous Profiling) — Обзор

## Определения

**Непрерывное профилирование (Continuous Profiling / Always-on Profiling)** — это практика постоянного автоматизированного сбора данных о производительности приложений в производственной среде. В отличие от традиционного профилирования «по запросу», этот метод работает 24/7 с минимальным влиянием на систему (обычно <1-2% CPU).

В 2026 году непрерывное профилирование стало «четвертым столпом» наблюдаемости (Observability), дополняя метрики, логи и трейсы. Оно позволяет сопоставлять потребление ресурсов напрямую с функциями и строками исходного кода.

### Ключевые преимущества
*   **Ретроспективный анализ инцидентов:** Возможность увидеть состояние системы («посмотреть внутрь кода») за несколько минут до сбоя, даже если инцидент уже исчерпан.
*   **Детектирование регрессий производительности:** Автоматическое сравнение профилей разных версий ПО для выявления неэффективного кода до масштабного влияния на пользователей.
*   **Оптимизация облачных затрат (FinOps):** Точная идентификация функций, потребляющих избыточное количество ресурсов, для прицельной оптимизации и снижения счетов за облако.
*   **Zero-day Observability:** Анализ поведения сторонних библиотек и системных вызовов ядра без изменения их кода.

### Типы профилей

| Тип | Что измеряет | Когда использовать | Оверхед |
| :--- | :--- | :--- | :--- |
| **CPU Profile** | Время выполнения функций на CPU (user-space). | Поиск CPU-bound hotspot'ов. | Низкий (~1%) |
| **Wall-clock Profile** | Реальное время (включая ожидания: I/O, мьютексы, sleep). | Поиск Off-CPU bottleneck'ов (блокировки, I/O). | Средний (~2-3%) |
| **Memory Alloc** | Количество и размер аллокаций в куче. | Оптимизация GC pressure, поиск утечек. | Средний (~3-5%) |
| **Mutex Profile** | Время ожидания блокировок (mutex contention). | Оптимизация конкурентного кода. | Низкий (~1%) |
| **Block Profile** | Время ожидания каналов и semaphores (Go). | Диагностика горутинных блокировок. | Низкий (~1%) |
| **Off-CPU Profile** | Время, когда процесс НЕ выполнялся на CPU (I/O, sleep, locks). | Диагностика долгих запросов при низком CPU usage. | Средний (~2-3%) |

**Off-CPU vs CPU profiling:** Традиционный CPU profile показывает только функции, которые «сжигают» CPU. Но если запрос длится 5 секунд, а CPU utilization — 5%, проблема не в CPU, а в Off-CPU времени (ожидание I/O, блокировки, network latency). Off-CPU profiling показывает, где процесс проводит время вне CPU, что критично для диагностики tail latency.

### Классификация по способу внедрения

| Подход | Модификация кода | Языки | Охват | Оверхед |
| :--- | :--- | :--- | :--- | :--- |
| **eBPF (system-wide)** | Нет | Все (Go, Java, Python, C++, Rust) | Весь узел | <1% |
| **Language Agent (in-process)** | Да (библиотека) | Один язык | Один процесс | 1-3% |
| **Runtime Integration** | Да (runtime flag) | Go (pprof), JVM (JFR) | Один процесс | <1% |

---

## Базовые концепции

### Механизмы сбора: eBPF против Агентов

1.  **eBPF-профилирование (System-wide / Sidecar-less):**
    *   **Принцип работы:** Использует eBPF-программы (`perf_event`), загружаемые в ядро Linux. Они периодически (сэмплирование) прерывают выполнение процессов и считывают стек вызовов.
    *   **Преимущества:** Нулевая модификация кода (Zero-instrumentation), поддержка всех языков (Go, Rust, C++, Python, Java), видимость системных вызовов и работы ядра.
    *   **Сложность:** Требует поддержки символов (Symbolication) для перевода адресов памяти в имена функций.
2.  **Языковые агенты (In-process / SDK):**
    *   **Принцип работы:** Библиотека интегрируется в рантайм (JVM, Go Runtime, CPython).
    *   **Преимущества:** Доступ к внутренним структурам данных (аллокация объектов, состояние кучи, блокировки мьютексов).
    *   **Инструменты:** `pprof` (Go), `async-profiler` (Java), `py-spy` (Python).

### Стандарт OTLP Profiles и OTLP/Arrow
В 2026 году индустрия перешла на единый формат обмена данными профилирования:
*   **OTLP Profiles:** Часть спецификации OpenTelemetry, позволяющая передавать профили как стандартный сигнал телеметрии.
*   **Apache Arrow (OTLP/Arrow):** Использование колоночного формата данных для передачи профилей. Это снижает нагрузку на сеть в 5-10 раз и позволяет эффективно сжимать повторяющиеся стеки вызовов.

### Визуализация: Flame Graphs и Diff-анализ
*   **Flame Graphs (Графы пламени):** Иерархическая визуализация стеков вызовов, где ширина блока пропорциональна потребляемому ресурсу (CPU time, Memory alloc).
*   **Icicle Graphs:** Инвертированная версия Flame Graphs (стек растет сверху вниз).
*   **Diff Views:** Сравнение двух профилей (например, Baseline vs Canary). Красные зоны показывают рост потребления, зеленые — оптимизацию.

### Непрерывное профилирование по языкам

**Go (pprof — встроенный):**
Go имеет нативную поддержку профилирования через `net/http/pprof`. Для continuous profiling необходимо включить pprof HTTP endpoint и настроить его на сбор метрик.

```go
import _ "net/http/pprof"

func main() {
    // Запуск pprof endpoint на отдельном порту
    go func() {
        log.Println(http.ListenAndServe("localhost:6060", nil))
    }()
    // ... основной код приложения
}
```

```bash
# Сбор CPU-профиля за 30 секунд (on-demand для отладки)
curl -s http://localhost:6060/debug/pprof/profile?seconds=30 -o cpu.prof

# Сбор heap-профиля (аллокации памяти)
curl -s http://localhost:6060/debug/pprof/heap -o heap.prof

# Анализ через go tool pprof
go tool pprof -http=:8080 cpu.prof
```

**Для continuous profiling в production** рекомендуется использовать eBPF-подход (Alloy/Pyroscope) вместо pprof pull-модели, чтобы избежать открытия pprof-порта в публичном контуре.

**Java (async-profiler + JFR):**
Java-приложения профилируются через `async-profiler` (для on-demand) или JFR (Java Flight Recorder, для continuous).

```bash
# async-profiler: установка
wget https://github.com/async-profiler/async-profiler/releases/download/v3.0/async-profiler-3.0-linux-x64.tar.gz
tar xzf async-profiler-3.0-linux-x64.tar.gz

# Сбор CPU-профиля (30 секунд)
./profiler.sh -d 30 -f cpu_profile.html -o flamegraph <PID>

# Сбор Wall-clock профиля (включая Off-CPU)
./profiler.sh -d 30 -e wall -f wall_profile.html <PID>

# Сбор аллокаций памяти
./profiler.sh -d 30 -e alloc -f alloc_profile.html <PID>
```

**JFR для continuous profiling (встроенный в JDK 11+):**
```bash
# Запуск JFR в фоне (низкоуровневый overhead ~1-2%)
jcmd <PID> JFR.start name=continuous settings=profile duration=60s filename=recording.jfr

# Периодический сбор (каждые 5 минут, 10 секунд записи)
jcmd <PID> JFR.start name=periodic settings=profile delay=0s duration=10s filename=/tmp/jfr-%p.jfr
```

**Python (py-spy + Runtime Monitoring):**
Python-приложения профилируются через `py-spy` (zero-overhead, наружный агент) или встроенные `cProfile`/`tracemalloc`.

```bash
# py-spy: установка
pip install py-spy

# Смотреть топ процессов в реальном времени
py-spy top --pid <PID>

# Записать flamegraph (30 секунд)
py-spy record -o flamegraph.svg --duration 30 --pid <PID>

# Нативный профиль (включая C-расширения)
py-spy record --native -o native_flame.svg --duration 30 --pid <PID>
```

**Для continuous profiling Python** используйте eBPF-подход (Alloy/Pyroscope) или интеграцию через `pyroscope-python-sdk`:

```python
from pyroscope import PyroscopeAgent, tag

# Настройка continuous profiling
PyroscopeAgent.configure(
    application_name="my-python-app",
    server_address="http://pyroscope:4040",
    tags=tag(
        "service_name", "my-python-app",
        "environment", "production",
    ),
    sample_rate=100,  # 100 Hz
)
```

**C/C++ (perf + DWARF symbols):**
C/C++ приложения профилируются через `perf` (system-wide) или `gperftools` (in-process).

```bash
# perf: сбор CPU-профиля (включая kernel symbols)
sudo perf record -F 99 -g -p <PID> -- sleep 30

# Конвертация в flamegraph
sudo perf script | stackcollapse-perf.pl | flamegraph.pl > flame.svg

# Профилирование с Intel PT (Precision Tracing) — для детального анализа
sudo perf record -e intel_pt//u --filter 'filter main' -- ./app

# Профилирование scheduler events (Off-CPU анализ)
sudo perf record -e sched:sched_switch -g -p <PID> -- sleep 10
```

**Для continuous profiling C/C++** рекомендуется eBPF-подход (Parca, Pyroscope) — он не требует перекомпиляции и работает с любым бинарником при наличии символов.

---

## Технологический стек и инструменты (2026)

| Категория | Инструмент | Особенности |
| :--- | :--- | :--- |
| **Collector (Сбор)** | **Grafana Alloy** | Универсальный агент, поддерживающий eBPF и сбор `pprof` через HTTP. |
| **Storage (Хранение)** | **Grafana Pyroscope** | Лидер сегмента, интегрирован в LGTM-стек, поддерживает колоночное хранение. |
| **Storage (eBPF-native)** | **Parca** | Использует FrostDB, сфокусирован на максимально эффективном eBPF-профилировании. |
| **SaaS** | **Datadog / New Relic** | Простая настройка, глубокая интеграция с APM и логами. |

---

## Практические сценарии

### Сценарий 1: Исследование «фантомной» утечки CPU
После деплоя в пиковые часы нагрузка на CPU выросла на 20%, но общее количество запросов не изменилось.
1.  **Действие:** В Pyroscope открывается **Comparison View** для тегов `version=v1.10` и `version=v1.11`.
2.  **Анализ:** На Diff Flame Graph видно, что функция `InternalValidation` занимает на 18% больше места.
3.  **Причина:** Разработчик заменил простую проверку на тяжелую регулярку, которая вызывается на каждый запрос.
4.  **Решение:** Оптимизация регулярного выражения.

### Сценарий 2: Span-to-Profile (Связь с трейсами)
Трассировка в Tempo показывает, что конкретный запрос к API заказов длится 3 секунды.
1.  **Действие:** Нажатие кнопки **«View Profile»** в интерфейсе Grafana для данного `trace_id`.
2.  **Анализ:** Открывается Flame Graph, отфильтрованный только по времени выполнения этого конкретного спана.
3.  **Результат:** Видно, что 2.5 секунды поток находится в состоянии **Off-CPU** (ожидание блокировки `db.connection_pool`). Проблема не в коде, а в размере пула соединений.

### Сценарий 3: Профилирование памяти (Heap/Allocations)
Микросервис периодически падает по OOM (Out of Memory).
1.  **Действие:** Анализ профиля `alloc_objects` за 10 минут до падения.
2.  **Анализ:** Выявление функции, которая создает миллионы короткоживущих объектов, перегружая Garbage Collector.
3.  **Результат:** Переход на использование `sync.Pool` для переиспользования объектов.

---

## Архитектура и настройка (Grafana Alloy + Pyroscope)

Для реализации непрерывного профилирования в Kubernetes используется Grafana Alloy:

### 1. Сбор через pprof (Push/Pull)
```river
// Пример конфигурации Alloy для сбора профилей с Go-сервиса
pyroscope.scrape "default" {
  targets = [
    {"__address__" = "my-service:6060", "service_name" = "order-api"},
  ]
  forward_to = [pyroscope.write.backend.receiver]
}

pyroscope.write "backend" {
  endpoint {
    url = "http://pyroscope-server:4040"
  }
}
```

### 2. Сбор через eBPF (Sidecar-less)
Агент Alloy запускается как `DaemonSet` с привилегиями `CAP_SYS_ADMIN`:
*   Сканирует все процессы на ноде.
*   Извлекает стеки вызовов.
*   Автоматически добавляет метаданные Kubernetes (pod, namespace).

### 3. Настройка на bare-metal серверах (без Kubernetes)

Для on-premise инфраструктуры без Kubernetes continuous profiling настраивается через системные агенты:

**Вариант A: Pyroscope + eBPF agent на каждом сервере:**
```bash
# Установка Pyroscope CLI (для on-demand профилирования)
curl -fsSL https://dl.pyroscope.io/install.sh | sh

# Запуск eBPF-профилировщика (собирает все процессы на сервере)
sudo pyroscope exec --application-name server-web \
    --log-level info --server-address http://pyroscope-server:4040 \
    --spy-name ebpfspy --sample-rate 100 \
    --tags host=web-01 env=production
```

**Вариант B: Grafana Alloy на bare-metal:**
```bash
# Установка Alloy (curl)
curl -sL https://grafana.com/install/alloy.sh | sh

# Конфигурация /etc/alloy/config.alloy
cat > /etc/alloy/config.alloy << 'EOF'
discovery.process "local" {
  // Обнаружение всех процессов на сервере
}

pyroscope.scrape "local" {
  targets    = discovery.process.local.targets
  forward_to = [pyroscope.write.default.receiver]
}

pyroscope.write "default" {
  endpoint {
    url = "http://pyroscope-server:4040"
  }
}
EOF

# Запуск Alloy
systemctl enable alloy && systemctl start alloy
```

**Вариант C: systemd + pprof (для Go-сервисов):**
```bash
# Включение pprof endpoint через environment variable
# Добавить в systemd unit файл:
# Environment=PPROF_LISTEN_ADDR=localhost:6060

# Добавить в Go-код:
# import _ "net/http/pprof"
# go http.ListenAndServe(os.Getenv("PPROF_LISTEN_ADDR"), nil)

# Сбор профилей через cron (каждые 5 минут, 10-секундные выборки)
*/5 * * * * curl -s http://localhost:6060/debug/pprof/profile?seconds=10 | gzip > /var/profiles/cpu-$(date +\%Y\%m\%d-\%H\%M).prof.gz
```

### 4. Настройка в Docker (без Kubernetes)

Для Docker-контейнеров continuous profiling реализуется через:

**Вариант A: cAdvisor + Pyroscope (сбор с хоста):**
```yaml
# docker-compose.yml
version: '3.8'
services:
  pyroscope:
    image: grafana/pyroscope:latest
    ports:
      - "4040:4040"
    volumes:
      - pyroscope-data:/var/lib/pyroscope

  alloy:
    image: grafana/alloy:latest
    privileged: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/alloy:/etc/alloy
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    depends_on:
      - pyroscope

  app:
    image: my-app:latest
    # Порт pprof должен быть доступен с хоста
    ports:
      - "6060:6060"
    environment:
      - PPROF_LISTEN_ADDR=0.0.0.0:6060
```

**Вариант B: Настройка профилирования в Dockerfile:**
```dockerfile
# Добавление pprof endpoint в Go-приложение
FROM golang:1.22-alpine AS builder
RUN apk add --no-cache git
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app/myapp .

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /app/myapp /usr/local/bin/myapp

# Не удалять отладочные символы для профилирования!
# -s -w выше удаляет таблицу символов и DWARF — для профилируемого сервиса
# собирайте без них. -trimpath на символизацию не влияет: он убирает только
# пути файловой системы. Подробнее: profiling_deep_dive.md, раздел «Символизация»
EXPOSE 6060
CMD ["myapp"]
```

---

## Продакшен-настройка и Guardrails

### Пороги оверхеда

| Тип профиля | Максимальный оверхед | Частота сэмплирования | Действие при превышении |
| :--- | :--- | :--- | :--- |
| **CPU** | <1% | 100 Гц | Снизить до 49 Гц |
| **Wall-clock** | <3% | 100 Гц | Снизить до 49 Гц, отключить для non-critical сервисов |
| **Memory Alloc** | <5% | 50 Гц | Включить только для critical сервисов |
| **Mutex/Block** | <2% | 50 Гц | Включить только при инцидентах |
| **eBPF (system-wide)** | <1% | 49 Гц | Проверить конфигурацию eBPF programs |

### Правила безопасного профилирования

1.  **Никогда не включайте profарiling на Production без understanding оверхеда.** Начните с staging/test environments.
2.  **Ограничивайте scope:** Профилируйте только критические сервисы. Не нужен continuous profiling на каждом микросервисе.
3.  **Используйте sampling rate:** Стандарт — 100 Гц. Для highly loaded систем — 19-49 Гц.
4.  **Мониторьте сам overhead:** Добавьте алерт на рост CPU utilization >2% после включения profiling.
5.  **Храните профили с ограниченным TTL:** Не храните профили дольше 30 дней (consumes significant storage).
6.  **Tag everything:** `service_name`, `version`, `environment`, `host` — без тегов профили бесполезны.
7.  **Не публикуйте pprof-порт:** Используйте только eBPF-подход для production или ограничьте доступ через firewall.

### Настройка retention в Pyroscope

```bash
# Конфигурация retention через API
curl -X PUT http://pyroscope:4040/api/v1/settings \
  -H "Content-Type: application/json" \
  -d '{
    "defaults": {
      "storage": {
        "retention": "720h"
      }
    }
  }'

# Проверка текущих настроек
curl http://pyroscope:4040/api/v1/settings | jq .
```

---

## Алертинг и интеграция с мониторингом

### Алерты на аномалии в профилях

```yaml
# Пример Prometheus alerting rules на основе profiling данных
groups:
  - name: continuous_profiling_alerts
    rules:
      # Рост CPU utilization после деплоя
      - alert: CpuProfileRegression
        expr: |
          pyroscope_cpu_samples_total{service="my-app"} 
          / pyroscope_cpu_samples_total{service="my-app"} offset 1h > 1.3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "CPU profile regression detected for {{ $labels.service }}"

      # Рост allocated memory (potential leak)
      - alert: MemoryAllocationSpike
        expr: |
          rate(pyroscope_alloc_objects_total{service="my-app"}[5m]) 
          > 2 * rate(pyroscope_alloc_objects_total{service="my-app"}[5m] offset 1h)
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Memory allocation rate doubled for {{ $labels.service }}"

      # Off-CPU bottleneck (высокое время ожидания)
      - alert: HighOffCpuTime
        expr: |
          pyroscope_wall_samples_total{service="my-app", state="off-cpu"}
          / pyroscope_wall_samples_total{service="my-app"} > 0.7
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "{{ $labels.service }} spends >70% time Off-CPU"
```

### Интеграция с Grafana Dashboard

```json
{
  "panels": [
    {
      "title": "CPU Hotspots by Service",
      "type": "flamegraph",
      "targets": [{
        "expr": "pyroscope_cpu_samples_total{service=\"$service\"}",
        "format": "heatmap"
      }]
    },
    {
      "title": "Memory Alloc Rate",
      "type": "timeseries",
      "targets": [{
        "expr": "rate(pyroscope_alloc_objects_total{service=\"$service\"}[5m])",
        "legendFormat": "{{ function }}"
      }]
    }
  ]
}
```

---

## Рекомендации и решение проблем

### Символизация (Symbolication)
Без отладочных символов профили бесполезны (вместо имен функций будут адреса вроде `0x400f12`).
*   **Go:** Символизацию ломают флаги `-s -w`: они удаляют таблицу символов и DWARF, поэтому внешний бэкенд не может сопоставить профиль с бинарником. `-trimpath` на символизацию не влияет — он удаляет только пути файловой системы (полезно для воспроизводимых сборок). Со сведения 1.9 `runtime/pprof` встраивает имена функций в сам профиль, но бинарник для внешней символизации по-прежнему нужен.
*   **Java:** Используйте `async-profiler` с `-f <output>` вместо `-o flame` для получения HTML-файлов. Для JFR убедитесь, что `-XX:+PreserveFramePointer` включен.
*   **Python:** `py-spy` не требует символов — он работает через `/proc/<pid>/maps` и DWARF.
*   **C++/Rust:** Обеспечьте доступ профилировщика к `.debug` файлам или загружайте их в Pyroscope Symbol Server. При сборке используйте `-g` (gcc) или `-C debuginfo=2` (rustc).

### Управление оверхедом
1.  **Частота сэмплирования:** Стандарт — 100 Гц (100 раз в секунду). Для сверхнагруженных систем можно снизить до 19-49 Гц.
2.  **Выбор профилей:** CPU-профилирование практически бесплатно. Аллокация памяти и профилирование блокировок (`mutex`) имеют более высокий оверхед и должны включаться с осторожностью.
3.  **Тегирование:** Всегда добавляйте `service_name`, `version` и `environment`. Без них исторический анализ невозможен.
4.  **Off-CPU profiling:** Включайте только при необходимости (диагностика tail latency). Повышает overhead до 2-3%.
5.  **Дифференцированный подход:** Критические сервисы — full profiling. Non-critical — только CPU profiling.

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Профили не отображаются (hex-адреса)** | Отсутствие debug symbols | Go: убрать `-s -w` из ldflags. C++: добавить `-g`. Java: `async-profiler` с PrintAssembly |
| **Высокий overhead (>5%)** | Слишком высокая частота сэмплирования | Снизить частоту сэмплирования (`-f` в pprof, `sample_rate` в Pyroscope) |
| **Профили пустые (no data)** | eBPF-программы не загружены | Проверить `CAP_SYS_ADMIN`, `kernel.unprivileged_bpf_disabled=0`, версию ядра >= 5.4 |
| **Memory leak в профиле** | Утечка в самом profiling agent | Обновить агент, проверить issue tracker, отключить при необходимости |
| **Метаданные отсутствуют** | Не настроены теги | Добавить `service_name`, `version`, `environment` в конфигурацию profiling |
| **Slow symbolication** | Слишком большие бинарники | Настроить symbol server (Pyroscope Symbol Server), уменьшить размер бинарников (UPX) |
| **Pyroscope OOM** | Слишком много сервисов / высокий sample rate | Увеличить RAM, снизить sample rate, настроить retention |

---

## Дополнительная информация

### См. также
*   **[Профилирование: глубокое погружение](./Observability_and_Monitoring/profiling_deep_dive.md)** — on-demand профилирование (pprof, async-profiler, perf, py-spy).
*   **[eBPF — виртуальная машина ядра](../Linux/Core/kernel/ebpf.md)** — основа современного Sidecar-less профилирования.
*   **[Grafana Alloy — обзор](../Grafana/grafana_alloy_overview.md)** — настройка коллектора.
