# Методология тестирования производительности

## 1. Определения и типы тестирования

**Тестирование производительности** — это комплекс мероприятий, направленных на определение отзывчивости, масштабируемости, надежности и стабильности системы под заданной нагрузкой. В 2026 году оно рассматривается не как финальный этап перед релизом, а как непрерывный процесс (**Continuous Performance Testing**), интегрированный в CI/CD.

### Основные определения

| Термин | Определение |
| :--- | :--- |
| **NFR (Non-Functional Requirement)** | Требование к характеристикам системы, не связанным с конкретной функцией (latency, throughput, availability). |
| **Performance Budget** | Жёсткий лимит метрик (например, p95 latency < 300ms, bundle size < 200KB), который не может быть превышен при деплое. Реализуется через Quality Gates в пайплайне. |
| **Baseline** | Измеренный эталон производительности стабильной версии системы, с которым сравниваются последующие запуски для Detection регрессий. |
| **Load Profile (Workload Model)** | Описание трафика: распределение запросов по эндпоинтам, think-time, соотношение reads/writes, паттерны поведения пользователей. |
| **RPI (Reliability Performance Index)** | Сводный коэффициент, объединяющий Latency, Error Rate и Saturation в единый индикатор стабильности сервиса. |

### Виды нагрузочного тестирования

| Тип | Цель | Описание |
| :--- | :--- | :--- |
| **Нагрузочное (Load Testing)** | Проверка SLA | Оценка поведения системы под ожидаемой (проектной) нагрузкой. |
| **Стресс-тестирование (Stress Testing)** | Поиск предела | Определение «точки разлома» (breaking point) и поведения системы при деградации ресурсов. |
| **Тестирование стабильности (Endurance)** | Утечки ресурсов | Длительная нагрузка (часы/сутки) для выявления утечек памяти (Memory Leaks) и переполнения очередей. |
| **Пиковое (Spike Testing)** | Резкие всплески | Проверка способности системы справляться с мгновенным ростом нагрузки (например, маркетинговые акции). |
| **Масштабируемости (Scalability)** | Горизонтальный рост | Определение эффективности добавления новых узлов (nodes/pods) для обработки растущей нагрузки. |
| **Объемное (Volume Testing)** | Большие данные | Тестирование производительности при значительном увеличении объема данных в БД. |

### Ключевые метрики (SLI — Service Level Indicators)

1.  **Latency (Задержка):** Время ответа системы. Важно анализировать не среднее значение, а **перцентили** (P50, P95, P99), чтобы видеть «хвост» задержек (Tail Latency).
2.  **Throughput (Пропускная способность):** Количество транзакций или запросов в единицу времени (RPS, TPS).
3.  **Error Rate (Уровень ошибок):** Процент неуспешных запросов. При нагрузке ошибки часто возникают из-за таймаутов или нехватки ресурсов.
4.  **Saturation (Насыщение):** Степень использования ресурсов (CPU, RAM, Disk I/O, Network). Для анализа ресурсов используется **USE-метод** (Utilization, Saturation, Errors).

---

## 2. Основные концепции (2026)

### Performance-as-Code
Тестирование производительности описывается декларативно (как код), версионируется вместе с приложением и выполняется автоматически в пайплайне. Это позволяет выявлять деградацию на ранних этапах.

### Модели нагрузки (Workload Models)

*   **Closed Loop (Закрытый цикл):** Новые пользователи приходят только после завершения предыдущих запросов. Не отражает реальность современного веба.
*   **Open Loop (Открытый цикл / Arrival Rate):** Новые запросы приходят с заданной частотой, независимо от того, успела ли система ответить на предыдущие. Это стандарт для 2026 года, так как он позволяет имитировать реальные всплески и точно измерять задержки.

### Coordinated Omission

**Coordinated Omission (координированное упущение)** — методологическая ошибка нагрузочного тестирования, возникающая при использовании Closed Loop-модели. Когда система замедляется, инструмент тестирования «сбрасывает» планируемые запросы, вместо того чтобы отправлять их с фиксированной частотой. В результате перцентили завышаются и тест показывает ложную картину производительности. Для исключения ошибки используются Open Loop-инструменты (`constant-arrival-rate`, `ramping-arrival-rate`) или утилиты с фиксированным Rate (например, `wrk2`, `vegeta`).

### Test Impact Analysis (TIA) для производительности

Подход, при котором пайплайн запускает не все тесты, а только те, которые затрагивают изменённый код. Для Performance Testing это означает запуск только тех нагрузочных сценариев, которые покрывают затронутые эндпоинты или модули. Результат: сокращение времени CI и снижение нагрузки на стенд.

### Continuous Profiling под нагрузкой

Профилирование (CPU, Memory, Allocation) выполняется не в изоляции, а в процессе нагрузочного теста. Это позволяет сопоставить «горячие» участки кода (hot paths) с метриками Latency и Throughput. Инструменты: **Pyroscope**, **Parca**, `perf`, `async-profiler`.

### Error Budget для производительности

Принцип SRE: допустимая доля нарушений SLO (Error Budget) применяется не только к availability, но и к latency. Если p99-задержка превышает целевое значение более допустимого процента времени, бюджет «сгорает» и требуется остановка изменений для оптимизации.

### Regression Detection и Quality Gates
Эффективная методология требует разделения на абсолютные и относительные проверки.

| Тип порога | Назначение | Пример |
| :--- | :--- | :--- |
| **Абсолютный** | Соответствие жестким SLA. | `p(99) < 500ms` |
| **Относительный** | Обнаружение деградации относительно Baseline. | `current_p95 < baseline_p95 * 1.1` |
| **Бинарный** | Функциональная корректность. | `http_req_failed < 0.01` |

---

## 3. Жизненный цикл тестирования (PTLC)

1.  **Сбор требований (NFR):** Определение целевых показателей (SLA/SLO), Performance Budget и допустимого Error Budget для latency/throughput. Формирование Load Profile на основе реальных паттернов трафика (access logs, APM).
2.  **Подготовка среды:** 
    *   **Изоляция стенда:** отсутствие влияния других тестов, noisy neighbors и фоновых процессов на хосте.
    *   **Production-like конфигурация:** аппаратные характеристики, версии ПО, параметры ядра (sysctl), лимиты cgroup должны максимально совпадать с production.
    *   **Генерация реалистичного набора данных (Seeding)** в БД: объём, распределение индексов, горячие строки.
    *   **Настройка мониторинга:** Prometheus + Grafana для системных метрик (USE-метод), приложение-специфичные метрики, трейсинг (OpenTelemetry), логи ( Loki / файлы).
3.  **Разработка скриптов:** Описание сценариев на базе профиля нагрузки. Использование динамических данных (параметризация), коррекция Coordinated Omission через Open Loop-инструменты.
4.  **Выполнение (Execution):**
    *   **Warm-up:** Прогрев кэшей (page cache, buffer pool, JIT-компилятора, TLS-сессий).
    *   **Steady State:** Стабильная нагрузка в течение заданного времени. На этом этапе система должна стабильно работать в соответствии с SLA.
    *   **Cool-down:** Завершение запросов и сбор финальных метрик. Важно дождаться завершения всех активных соединений, иначе метрики будут искажены.
5.  **Анализ и отчетность:** Сравнение результатов с Baseline, поиск аномалий и узких мест. Валидация через USE-метод и PSI. Документирование findings в стандартизированном формате (severity, evidence, рекомендация).

### Canary-тестирование производительности

Для production-окружений с высоким риском применяют **канареечное нагрузочное тестирование**: новая версия получает малый процент трафика, одновременно с подачей инструментированной нагрузки. Метрики latency/error-rate канарейки сравниваются с контрольной группой через burn-rate или statistical hypothesis testing. При превышении порога — автоматический откат.

---

## 4. Инструментальный стек

### Нагрузочное тестирование и генераторы нагрузки

*   **k6:** [Основной инструмент](./k6_load_testing.md) для Performance Testing as Code (JS/TypeScript). Подходит для сложных сценариев, CI/CD и Open Loop-моделей.
*   **Locust:** Генератор нагрузки на Python с master-worker архитектурой. Удобен для API-heavy сценариев и быстрого прототипирования.
*   **wrk / wrk2:** Высокопроизводительный генератор HTTP-нагрузки на Lua-скриптах. `wrk2` добавляет фиксированный arrival rate для исключения Coordinated Omission.
*   **Vegeta:** CLI-утилита на Go для постоянной скорости атаки (constant rate). Идеальна для простых health-check и smoke-тестов производительности.
*   **Apache Bench (ab):** Простейший инструмент для быстрых ad-hoc проверок. Не рекомендуется для CI из-за отсутствия пороговых проверок и сложного парсинга вывода.
*   **ghz:** Специализированный инструмент для нагрузочного тестирования gRPC-сервисов. Поддерживает keepalive, metadata, бинарные protobuf-сообщения и детальную статистику latency.
*   **JMeter:** Классический Java-генератор (GUI-конструктор, JMX). Для enterprise/legacy, не-веб-протоколов (JDBC, JMS). Подробно: [JMeter](./jmeter_load_testing.md).
*   **Gatling:** JVM-генератор со Scala-DSL и открытой моделью нагрузки. Подробно: [Gatling](./gatling_load_testing.md).
*   **Yandex.Tank / Taurus:** Консольный генератор + YAML-обёртка; единый конфиг поверх JMeter/Gatling/Locust/k6. Подробно: [Yandex.Tank и Taurus](./yandex_tank_taurus.md).

### Распределённая генерация нагрузки (Distributed Load Testing)

Когда один экземпляр генератора не справляется (высокий RPS с одной машины, ресурсные ограничения) или нужно приблизить трафик к географическому распределению пользователей, используют **распределённую генерацию**:

*   Модель **master/agent**: master владеет тест-планом, агенты генерируют трафик, результаты агрегируются на мастере.
    *   **JMeter** — встроенные `jmeter-server` (порты RMI) + `-R host1,host2`.
    *   **Locust** — master + worker-узлы (в базовой архитектуре).
*   Модель **код/агр-обёртка поверх оркестратора**:
    *   **k6 + Kubernetes Operator** — оператор `grafana/k6-operator` создаёт init/worker DPs, синхронизирует старт (STARTPHASE init), собирает результаты мастера.
    *   **JMeter-кластер в Kubernetes** — статических агентов можно держать как Deployment/StatefulSet.
*   **Правила распределённых тестов:**
    1.  **Достаточность генераторов:** ресурсы агентов в разы превышают ресурсы цели; иначе агенты сами станут узким местом и исказят latency.
    2.  **Синхронизация старта:** все агенты начинают одновременно (по сигналу), иначе набегающий рамп «размазывается».
    3.  **Не перегружать сеть агрегации:** минимизировать объём сохраняемых результатов с агентов (агрегирование на мастере, а не полные raw-логи).
    4.  **Географическое распределение:** для маркетинговых/глобальных сервисов — кластеры генераторов в тех же регионах, что и пользователи (иначе network RTT искажает интерпретацию).
    5.  **Воспроизводимость:** фиксировать версии генераторов, артефакты конфигов, кол-во узлов — для сравнения прогонов.

Пример YAML запуска JMeter-мастера против агентов — в [JMeter (распределённый запуск)](./jmeter_load_testing.md#распределённый-запуск-distributed-testing).

### Профилирование и анализ

*   **Pyroscope / Parca:** Непрерывное профилирование (Continuous Profiling) CPU и allocations под нагрузкой. Позволяет сопоставить горячие пути кода с метриками Latency.
*   **perf / bpftrace / bcc-tools:** Статическое и динамическое профилирование на уровне ядра Linux. Для анализа off-CPU времени, системных вызовов и планировщика.
*   **Prometheus & Grafana:** Сбор системных и бизнес-метрик во время теста, визуализация трендов и построение базовой линии (baseline).
*   **OpenTelemetry:** Стандартизированный сбор трейсов и метрик из приложения для корреляции задержек с конкретными сервисами/запросами.

### Диагностика ресурсов

*   **PSI (Pressure Stall Information):** Анализ давления на CPU, память и I/O через `/proc/pressure/*`. Позволяет понять, какой ресурс стал узким местом, ещё до скачка latency.
*   **fio:** Гибкий инструмент для тестирования производительности блочного устройства. Определяет IOPS, latency и throughput для SSD/HDD/NVMe под разные паттерны (random/sequential, read/write).
*   **sysbench:** Мультифункциональный бенчмарк для CPU, память, потоки, базы данных (OLTP). Используется для быстрого smoke-теста серверов и СУБД.
*   **syswatch:** TUI-инструмент для first-look диагностики хоста во время теста. Сохраняет сессии (.swr) для пост-фактум анализа аномалий.

---

## 5. Практические сценарии

### Сценарий 1: Продвинутый скрипт k6 с Quality Gates

Скрипт имитирует модель Open Loop и проверяет как абсолютные пороги, так и корректность ответов.

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    constant_arrival: {
      executor: 'constant-arrival-rate',
      rate: 100,              // 100 запросов в секунду
      timeUnit: '1s',
      duration: '10m',
      preAllocatedVUs: 50,    // Заранее выделенные виртуальные пользователи
      maxVUs: 200,            // Максимальный предел
    },
  },
  thresholds: {
    'http_req_duration{status:200}': ['p(95)<200', 'p(99)<500'], // SLA по задержке
    'http_req_failed': ['rate<0.01'],                           // Ошибок менее 1%
  },
};

export default function () {
  const res = http.get('https://api.example.com/v1/resource');
  
  check(res, {
    'is status 200': (r) => r.status === 200,
    'body has data': (r) => r.json().data !== undefined,
  });

  sleep(0.5);
}
```

### Сценарий 2: Анализ системного давления (PSI) в Linux

Во время теста необходимо следить за метриками **Pressure Stall Information** в `/proc/pressure/`, чтобы понять, какой ресурс является узким местом.

```bash
# Проверка давления на CPU (среднее за 10, 60, 300 секунд)
cat /proc/pressure/cpu
# avg10 > 10.00 — признак того, что процессы ждут CPU, система перегружена.

# Проверка давления на IO
cat /proc/pressure/io
# avg10 > 5.00 — диск не успевает за запросами (высокий iowait).
```

Для сбора PSI-метрик в Prometheus используйте node_exporter с включенным коллектором `pressure`. Подробнее: [PSI в Linux](../Linux/Core/kernel/psi.md).

### Сценарий 3: HTTP-бенчмаркинг с помощью vegeta

Для быстрого ad-hoc бенчмаркинга простых HTTP-сервисов (health-check, status API) используйте `vegeta`. Он обеспечивает фиксированную скорость запросов (constant rate), исключая Coordinated Omission.

```bash
# Файл targets.txt (формат URL или JSON)
echo "GET https://api.example.com/health" > targets.txt

# Запуск: 50 RPS в течение 30 секунд
echo "POST https://api.example.com/v1/resource" | vegeta attack -rate=50 -duration=30s | vegeta report

# Экспорт в JSON для CI
echo "POST https://api.example.com/v1/resource" | vegeta attack -rate=50 -duration=30s -output=results.json
vegeta report -type=json results.json | jq .
```

**Интерпретация:** focus на `latencies.mean`, `latencies.p95`, `latencies.p99`, `errors`. Если `errors > 0` — проверьте логи приложения и сетевую доступность.

### Сценарий 4: Дисковый бенчмарк с помощью fio

Производительность диска критична для latency баз данных и сервисов хранения. Используйте `fio` для измерения IOPS и latency под паттерны, близкие к рабочей нагрузке.

```bash
# Random 4K read (OLTP-паттерн, 8 jobs, 30 секунд)
fio --name=randread_4k \
    --rw=randread --bs=4k --size=2G \
    --numjobs=8 --time_based --runtime=30s \
    --ioengine=libaio --direct=1 \
    --filename=/data/test.img

# Ключевые метрики для анализа:
# - iops: количество операций в секунду
# - lat_ns.mean / lat_ns.p99: средняя и 99-я перцентиль задержки
# - bw: пропускная способность (KB/s)
```

**Связь с SLI:** Если p99 latency диска превышает 2ms при OLTP-нагрузке, ожидайте рост задержек на уровне приложения даже при наличии page cache.

### Сценарий 5: Smoke-тест сервера и СУБД с помощью sysbench

`sysbench` позволяет быстро проверить предельные возможности CPU, памяти и диска, а также выполнить OLTP-тест для MySQL/PostgreSQL.

```bash
# CPU: 1 поток, 60 секунд, проверка primes
sysbench cpu --threads=1 --time=60 run

# Память: чтение/запись блоками 4K, 64 потока
sysbench memory --threads=64 --memory-block-size=4K --memory-total-size=100G run

# MySQL/PostgreSQL OLTP: 10 складов, 8 потоков, 30 секунд
sysbench oltp_read_write --tables=10 --threads=8 --time=30 \
     --db-driver=mysql --mysql-db=test run
```

**Ограничение:** sysbench использует Closed Loop-модель, поэтому для абсолютно точных перцентилей подключайте `constant-arrival-rate` из k6 или `wrk2`.

### Сценарий 6: Диагностика давления ресурсов через PSI и cgroup v2

Расширенная диагностика с привязкой к конкретным cgroup (контейнерам, системным сервисам).

```bash
# Общее давление на систему
cat /proc/pressure/cpu
cat /proc/pressure/io
cat /proc/pressure/memory

# Давление в конкретном cgroup (например, контейнер postgres)
cat /sys/fs/cgroup/postgres/io.pressure
cat /sys/fs/cgroup/postgres/cpu.pressure

# Разбор some vs full:
# some  — хотя бы одна задача заблокирована (конкуренция)
# full — все не-idle задачи заблокированы (критическое насыщение, thrashing)
```

**Интерпретация:** `full` для IO > 1% на steady state означает, что диск является узким местом и требуется переход на NVMe, оптимизация запросов или увеличение параллелизма.

### Сценарий 7: Continuous Profiling под нагрузкой с Pyroscope

Сопоставление горячих участков кода с метриками Latency позволяет быстро локализовать деградацию.

```bash
# Запуск Pyroscope в Docker (push model)
docker run -d \
  -p 4040:4040 \
  -v /tmp/pyroscope:/tmp/pyroscope \
  pyroscope/pyroscope:latest \
    pyroscope server

# Инжекция агента в приложение (Go пример)
# В коде приложения добавить:
# import _ "github.com/grafana/pyroscope-go"
# 
# pyroscope.Start(pyroscope.Config{
#     ApplicationName: "payment-service",
#     ServerAddress:   "http://pyroscope:4040",
#     ProfileTypes: []pyroscope.ProfileType{
#         pyroscope.ProfileCPU,
#         pyroscope.ProfileAllocSpace,
#     },
# })

# Параллельно запустить k6 нагрузку
k6 run -u 100 -d 5m script.js
```

**Анализ:** В Grafana UI сопоставьте flame graph с p99 Latency spike. Обычно узкие места находятся в системных вызовах (syscalls), GC-паузах или contention на мьютексах.

### Сценарий 8: Методология Baseline comparison и Regression Detection

Baseline — это эталонный запуск стабильной версии системы. Для построения baseline:

1. **Фиксация окружения:** версия образа, конфигурация ядра, параметры JVM/Go runtime, размер пула соединений.
2. **Запуск в однотипных условиях:** тот же Load Profile, тот же hardware, то же время суток (чтобы исключить фоновую нагрузку).
3. **Многократный запуск:** минимум 3 прогона, усреднение p95/p99 для исключения шума.
4. **Сохранение артефактов:** JSON/CSV с метриками, метаданные окружения, хэш конфигурации.

**Regression Detection в CI:**
```bash
# Пример: сравнение текущего p95 с baseline (bash + jq + bc)
CURRENT_P95=$(jq -r '.metrics.http_req_duration.values.p95' current.json)
BASELINE_P95=$(jq -r '.metrics.http_req_duration.values.p95' baseline.json)

# Допуск 10% (regression, если текущий > baseline * 1.1)
if (( $(echo "$CURRENT_P95 > $BASELINE_P95 * 1.1" | bc -l) )); then
  echo "REGRESSION: p95 ${CURRENT_P95}ms > baseline ${BASELINE_P95}ms (+10%)"
  exit 1
fi
```

---

## 6. Поиск и устранение узких мест (Troubleshooting)

| Проблема | Признаки | Возможные решения |
| :--- | :--- | :--- |
| **CPU Bound** | Высокая утилизация CPU, рост Latency при стабильном RPS. | Оптимизация алгоритмов, кэширование, горизонтальное масштабирование. |
| **Memory Bound** | Рост использования RAM, частые Garbage Collection, OOM Killer. | Поиск утечек, настройка лимитов памяти, оптимизация структур данных. |
| **I/O Bound** | Высокий Disk Wait, медленные операции чтения/записи. | Использование SSD/NVMe, оптимизация запросов к БД, Batch-записи. |
| **Network Bound** | Ошибки Connection Refused, рост сетевых задержек. | Тюнинг TCP-стека, HTTP/2+ Multiplexing, сжатие трафика (gRPC/Protobuf). |
| **Блокировки (Locks)** | Низкая утилизация ресурсов при высоком Latency. | Переход на асинхронную модель, оптимизация транзакций в БД, Connection Pooling. |
| **NUMA несоответствие** | Латентность растет при нагрузке на «чужое» NUMA-узле. | Привязка процессов/памяти к локальному NUMA-узлу (`numactl --cpunodebind=0 --membind=0`). |
| **Huge Pages отсутствуют** | Высокий TLB Miss Rate, рост CPU на ядре. | Включение 2MB/1GB Huge Pages в BIOS/ядерных параметрах. |
| **Cgroup Throttling** | `cpu.throttled` > 0 в `/sys/fs/cgroup/.../cpu.stat`. | Увеличение `cpu.max` (cgroup v2) или `cpu.cfs_quota_us`. |
| **TLS Handshake overhead** | Высокий `tls_handshake` latency на cold start. | Включение TLS False Start, session resumption, keepalive, аппаратное ускорение (AES-NI). |
| **TCP параметры** | Retransmit, 0win probes, малое CWND. | Тюнинг `net.core.somaxconn`, `net.ipv4.tcp_syncookies`, `tcp_slow_start_after_idle`, отключение `tcp_timestamps` при DDoS-риске. |
| **THP (Transparent Huge Pages)** | Latency spikes и stall из-за фрагментации. | Отключение THP: `echo never > /sys/kernel/mm/transparent_hugepage/enabled`. |
| **SoftIRQ / Network Interrupts** | Высокий `ksoftirqd` CPU на сетевых интерфейсах. | Отключение irqbalance, руская привязка прерываний (`set_irq_affinity`), увеличение `netdev_budget`. |

### Диагностический чек-лист (SRE-first)

1.  **Утилизация:** `top/htop` (CPU), `free -h` (RAM), `iostat -x 1` (disk), `sar -n DEV 1` (network).
2.  **Saturation:** `uptime` (load average), `cat /proc/pressure/*` (PSI), `vmstat 1` (swapping, iowait).
3.  **Ошибки:** `dmesg -T | tail -50` (OOM, hardware), `journalctl -u <service> --since "10 min ago"`, `netstat -s | grep -i error`.
4.  **Процессы:** `pidstat 1`, `ps aux --sort=-%cpu | head`, `perf top` (горячие функции).
5.  **Сеть:** `ss -s` (состояние сокетов), `nstat -s` (kernel network stats), `ethtool -S <iface>` (packet drops).

---

## 7. SRE-практики: Error Budget, Burn Rate и Alerting для производительности

Производительность — это reliability. Как и availability, latency и error rate управляются через SLO, SLI и Error Budget.

### SLI для производительности

| SLI | Измеряется через | Типичный SLO |
| :--- | :--- | :--- |
| **Latency** | p99 или p99.9 задержки запроса | < 500ms (99% запросов за 30 дней) |
| **Error Rate** | Доля запросов с кодом 5xx или timeout | < 0.1% |
| **Throughput** | RPS/ТPS в steady state | не падает ниже baseline > 95% |

### Burn Rate (скорость сгорания бюджета)

Burn Rate показывает, как быстро тратится Error Budget при текущем уровне нарушений SLO.

```text
Бюджет = 0.1% ошибок за 30 дней = ~43 секунды допустимого простоя.
Если ошибки идут со скоростью 1% в час, бюджет сгорает за 4.3 часа.
```

Для latency: если p99 > SLO в течение 5 минут каждый час, это критический burn rate.

### Multi-Window Burn Rate алерты (Prometheus)

Используйте несколько окон для детектирования как всплесков, так и медленных утечек:

```yaml
# Пример: latency p99 превышает 500ms
# Длинное окно (6ч) для медленной утечки, короткое (30м) для всплеска
groups:
  - name: performance_alerts
    rules:
      - alert: LatencyBurnRateHigh
        expr: |
          histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[30m]))
          > 500
          and
          histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[6h]))
          > 500
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Latency p99 превышает SLO (500ms)"
```

### SLO-based Deployment Gate

Canary-деплой продолжается, только если burn rate latency/error rate ниже порога:

```text
Деплой → Canary (5% трафика) → сбор метрик за 10 минут
↓
PromQL: histogram_quantile(0.99, rate(...[5m])) < 500ms
↓
Burn rate < 1.0 → увеличить трафик до 25%
Burn rate > 5.0 → остановка и откат
```

### Cleanup и отчетность

После каждого тестового цикла:
1. Остановить нагрузку и дождаться cool-down.
2. Архивировать артефакты: `.json` отчёты k6/vegeta, скриншоты Grafana, логи.
3. Удалить seeding-данные из тестовой БД (если они не идемпотентны).
4. Освободить ресурсы: завершить фоновые процессы мониторинга, остановить `syswatch --record`, демонтировать точки монтирования fio.

---

### См. также
- **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)** — Performance-as-Code, исполнители (executors), Coordinated Omission, выходные форматы, xk6.
- **[Нагрузочное тестирование с помощью Apache JMeter](./jmeter_load_testing.md)** — классический Java-генератор, distributed-запуск, JMX.
- **[Yandex.Tank и Taurus](./yandex_tank_taurus.md)** — YAML-обёртка поверх генераторов, профили нагрузки.
- **[Нагрузочное тестирование с помощью Gatling](./gatling_load_testing.md)** — JVM-генератор с открытой моделью нагрузки.
- **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — Quality Gates, Regression Detection, Test Impact Analysis (TIA), автоматизация нагрузочных тестов в GitLab CI и GitHub Actions.
- **[Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)** — k6, Locust, Vegeta, wrk2 в CI/CD: Docker-запуск, база сравнения (baseline), типичные ошибки и диагностика.
- **[Бенчмаркинг веб-серверов](../WebServers/webserver_benchmarking.md)** — низкоуровневые утилиты (wrk, ab, h2load), k6 для веб-серверов, выбор инструмента по задаче.
- **[Диагностика Tail Latency](../Linux/Diagnostics/Performance/diagnosing_tail_latency.md)** — глубокое погружение в борьбу с задержками, PSI, off-CPU анализ.
- **[Принципы тестирования веб-приложений](../WebServers/Concepts/web_performance/testing_principles.md)** — специфика фронтенда и RUM.
- **[Ключевые концепции производительности БД](../Databases/Concepts/database_performance_concepts.md)** — метрики и оптимизация СУБД.
- **[PSI (Pressure Stall Information)](../Linux/Core/kernel/psi.md)** — теория и практика анализа давления на ресурсы ядра Linux.
- **[Диагностика хоста через syswatch](../Linux/Diagnostics/Performance/syswatch.md)** — first-look TUI для SRE при расследовании инцидентов.
- **[Docker: оптимизация производительности](../Docker/Docker_performance_tuning.md)** — cgroups, PSI в контейнерах, resource limits.
