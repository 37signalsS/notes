# Инструменты для бенчмаркинга веб-серверов

**Актуально для:** Linux Kernel 5.15+ / 6.x, wrk 4.2+, wrk2, h2load 1.70+, k6 2.3+, oha 1.16+

## Определения

**Бенчмаркинг веб-сервера (Web Server Benchmarking)** — процесс контролируемого экспериментального измерения предельных возможностей серверного программного обеспечения (Nginx, Angie, Apache, Envoy, HAProxy) и аппаратной платформы под искусственно создаваемой входящей сетевой нагрузкой.

**Ключевые метрики производительности:**
- **RPS (Requests Per Second) / QPS (Queries Per Second):** количество успешно завершенных HTTP-запросов, обработанных сервером за одну секунду.
- **CPS (Connections Per Second):** количество вновь установленных сетевых соединений (TCP handshake + TLS handshake) в секунду. Критический показатель для оценки накладных расходов сетевого стека ядра и криптографических библиотек.
- **Latency (Задержка):** время отклика сервера. Различают:
  - **TTFB (Time to First Byte):** время от отправки первого байта запроса клиентом до получения первого байта ответа от сервера (включает время передачи по сети и генерации ответа бэкендом).
  - **TTLB (Time to Last Byte):** полное время от начала отправки запроса до вычитывания клиентом последнего байта тела ответа.
- **Throughput (Пропускная способность):** объем полезных данных, передаваемых по сети в единицу времени (Мбит/с или МБ/с). Зависит от размера ответов, эффективного MTU, окон TCP и протокольных заголовков.
- **Concurrency (Конкурентность):** число одновременно открытых и поддерживаемых клиентских сетевых соединений или виртуальных пользователей (VU), одновременно взаимодействующих с сервером.
- **Percentile (Перцентиль):** статистический показатель распределения задержки. Перцентиль $pX$ означает, что $X\%$ всех выполненных запросов имели задержку, не превышающую данное значение ($p50$ — медиана, $p95$, $p99$, $p99.9$ — хвостовые задержки).
- **Tail Latency (Хвостовая задержка):** задержка в крайних перцентилях ($p99$, $p99.9$), обусловленная системными прерываниями, паузами сборщика мусора (GC), блокировками дискового I/O, переполнением очередей сокетов или сменой контекста планировщика ОС.
- **Saturation (Насыщение):** степень исчерпания критических ресурсов системы (очередей сокетов, дескрипторов файлов, полосы пропускания интерфейса, CPU runqueue), при превышении которой задержка начинает расти экспоненциально при постоянном или падающем RPS.
- **Jitter (Джиттер задержки):** статистическая вариация задержки между последовательными пакетами или запросами.

**Модели генерации нагрузки:**

1. **Закрытый цикл (Closed Loop / Concurrency-based):** режим, в котором новый запрос отправляется только после получения ответа на предыдущий запрос в рамках фиксированного пула воркеров/потоков. Если сервер замедляет ответы, нагрузчик автоматически снижает скорость отправки. Примеры: `ab`, базовый `wrk`, `hey`.
2. **Открытый цикл (Open Loop / Rate-based / Arrival Rate):** режим, в котором запросы генерируются со строго детерминированной частотой (например, 5000 RPS) независимо от времени отклика сервера. При замедлении сервера количество незавершенных запросов в полете растет, отражая реальное поведение распределенных интернет-пользователей. Примеры: `wrk2` (форк `wrkx`), `Vegeta`, `k6` (с исполнителями `constant-arrival-rate` и `ramping-arrival-rate`).

**Скоординированный пропуск (Coordinated Omission):**
Методологическая ошибка измерений, возникающая в генераторах закрытого цикла. Если один запрос блокируется сервером на 5 секунд, весь поток нагрузчика простаивает и не отправляет запланированные запросы. В итоговой статистике фиксируется одна длительная задержка, а тысячи запросов, которые должны были быть отправлены в этот период и также столкнуться с задержкой, просто не регистрируются. Это приводит к искусственному занижению хвостовых перцентилей ($p95$, $p99$) и ложному заключению о стабильности сервиса.

---

## Основные концепции и архитектура

### Принципы корректного тестирования веб-серверов

Для получения воспроизводимых и объективных результатов необходимо соблюдать следующие правила изоляции и методологии:

```text
+───────────────────────────+                 +───────────────────────────+
|   Load Generator Host     |                 |     Target Web Server     |
|   (wrk2 / h2load / k6)    |                 |   (Angie / Nginx / Envoy) |
|                           |                 |                           |
|  [ CPU Affinity: Core 0-3]|                 |  [ CPU Affinity: Core 0-7]|
|  [ local_port_range ]     |   Isolated L2   |  [ somaxconn / backlog ]  |
|  [ tcp_tw_reuse = 1 ]     | 10/25/40 Gbps   |  [ access_log off / tmpfs]|
|  [ iptables NOTRACK ]     |◄───────────────►|  [ epoll / multi-worker ] |
|  [ ulimit -n 1000000 ]    |                 |  [ ulimit -n 1000000 ]    |
+───────────────────────────+                 +───────────────────────────+
```

1. **Физическое разделение хостов:** Нагрузочный генератор и тестируемый веб-сервер обязаны размещаться на физически раздельных хостах (или как минимум на выделенных гипервизорах с пиннингом vCPU к раздельным NUMA-узлам). Запуск нагрузчика на `localhost` или внутри одного Docker-демона на том же сервере искажает измерения: генератор конкурирует за CPU и кэш L3 с веб-сервером, а сетевой трафик замыкается через loopback в обход реальных сетевых драйверов, прерываний и очередей NIC.
2. **Разделение CPS и RPS профилей:**
   - **Тест пропускной способности (RPS):** использует постоянные Keep-Alive соединения (HTTP/1.1) или мультиплексированные сессии (HTTP/2, HTTP/3). Измеряет эффективность epoll/kqueue, парсинга HTTP, маршрутизации и отдачи контента.
   - **Тест емкости соединений (CPS):** генерирует новые TCP/TLS соединения на каждый запрос (`Connection: close`). Измеряет предельную производительность ядра при обработке SYN-пакетов, создании TCB (Transmission Control Block) и криптографическую скорость выполнения TLS-рукопожатий.
3. **Расчет сетевого бюджета (Network Saturation Budget):**
   Перед проведением теста статики или объемных ответов необходимо сопоставить ожидаемый RPS с физической пропускной способностью интерфейса:
   $$\text{Throughput (бит/с)} = \text{RPS} \times (\text{Размер ответа в байтах} + \text{Размер заголовков}) \times 8$$
   Например, отдача файла размером 64 КБ при 20 000 RPS требует полосы $64 \times 1024 \times 20000 \times 8 \approx 10.48\text{ Гбит/с}$. На 10-гигабитном линке узким местом станет физический сетевой адаптер, а не веб-сервер.
4. **Протокольная специфика (HTTP/1.1 vs HTTP/2 vs HTTP/3):**
   - **HTTP/1.1:** подвержен Head-of-Line Blocking на уровне приложения. Требует сотен и тысяч параллельных TCP-сокетов для высокой конкурентности.
   - **HTTP/2:** мультиплексирует десятки потоков (streams) внутри одного TCP-соединения. Устраняет необходимость тысяч открытых сокетов, но подвержен Head-of-Line Blocking на уровне TCP при потере пакетов.
   - **HTTP/3 (QUIC over UDP):** устраняет TCP Head-of-Line Blocking и поддерживает 0-RTT рукопожатия, однако обработка UDP на уровне ядра Linux требует в 2–3 раза больше процессорных циклов на пакет, чем аппаратный TCP offload (TSO/GRO).
5. **Изоляция I/O и вспомогательных сервисов:**
   На время стресс-теста обязательно отключается дисковая запись журнала доступа (`access_log off;`) либо лог направляется в `/dev/null` или `tmpfs`. В противном случае бенчмаркинг упрется в синхронный дисковый I/O или блокировки буфера файловой системы.
6. **Контроль базовой линии (Baseline) и прогрев (Warm-up):**
   Перед записью результатов необходим этап прогрева (30–60 секунд). Он позволяет разогреть кэш процессора, заполнить пул сессий TLS, инициализировать пулы соединений и файловые дескрипторы.

---

### Архитектура генераторов нагрузки

Генераторы нагрузки существенно различаются внутренней реализацией циклов обработки событий (event loops) и планировщиков:

| Класс движка | Представители | Внутренняя архитектура | Достоинства | Ограничения |
| :--- | :--- | :--- | :--- | :--- |
| **C/C++ Event-driven** | `wrk`, `wrk2`, `h2load` | Асинхронный event loop (`epoll`/`kqueue`), POSIX threads, отсутствие сборщика мусора. | Предельный RPS на ядро CPU, минимальный overhead памяти, стабильные задержки без GC-всплесков. | Ограниченная логика ветвления сценариев (скриптинг через Lua). |
| **Go Goroutine-based** | `k6`, `vegeta`, `bombardier`, `ghz` | M:N планировщик Go-рантайма, легковесные goroutines. | Удобство оркестрации, нативная поддержка complex flows, gRPC, WebSocket, кросс-платформенность. | Возможны кратковременные микропаузы GC при экстремальных нагрузках (>100k RPS на одном хосте). |
| **Rust Async** | `oha` | Асинхронный рантайм Tokio, zero-cost abstractions, строгий контроль памяти. | Высокий RPS, отсутствие GC, наглядный TUI в реальном времени, низкое потребление RAM. | Меньше возможностей для сложного многоэтапного сценарного тестирования. |

---

### Системный тюнинг ядра Linux для бенчмаркинга

При генерации и приеме экстремальных нагрузок (от 50 000 до 1 000 000+ RPS) стандартные параметры ядра Linux приводят к исчерпанию портов, переполнению сокетных очередей и дропу пакетов. Настройка применяется на хосте нагрузчика и на сервере.

#### 1. Лимиты файловых дескрипторов

Каждый сетевой сокет в Linux является файловым дескриптором. При нехватке лимита приложения завершаются с ошибкой `Too many open files` (`EMFILE`).

```bash
# Проверка текущего жесткого и мягкого лимита процесса
ulimit -Sn; ulimit -Hn
# → 1024
# → 1048576

# Установка лимита в текущей сессии
ulimit -n 1048576
ulimit -n
# → 1048576

# Глобальный системный лимит ядра (/etc/sysctl.d/99-limits.conf)
sysctl -w fs.file-max=2097152
# → fs.file-max = 2097152
```

Для системных служб под управлением systemd создается drop-in конфигурация `/etc/systemd/system/<service_name>.service.d/override.conf`:
```ini
[Service]
LimitNOFILE=1048576
LimitNPROC=512000
```

#### 2. Настройка сетевого стека TCP/IP (sysctl)

Файл `/etc/sysctl.d/99-benchmarking.conf`:
```sysctl
# Расширение диапазона эфемерных портов для нагрузчика (до 64511 портов)
net.ipv4.ip_local_port_range = 1024 65535

# Безопасное переиспользование сокетов в состоянии TIME_WAIT для исходящих подключений
net.ipv4.tcp_tw_reuse = 1

# Сокращение времени удержания сокета в FIN-WAIT-2 до освобождения памяти
net.ipv4.tcp_fin_timeout = 15

# Максимальный размер очереди полностью установленных соединений (Accept queue)
net.core.somaxconn = 65535

# Максимальный размер очереди полуоткрытых соединений (SYN queue / backlog)
net.ipv4.tcp_max_syn_backlog = 65535

# Максимальный размер очереди пакетов на сетевом интерфейсе до передачи в стек
net.core.netdev_max_backlog = 65535

# Отключение медленного старта TCP после простоя (сохранение окна перегрузки)
net.ipv4.tcp_slow_start_after_idle = 0

# Включение алгоритма контроля перегрузки BBR (или CUBIC)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Буферы приема и отправки сокетов (min, default, max) в байтах
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
```

Применение конфигурации:
```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/99-benchmarking.conf ...
# → net.ipv4.ip_local_port_range = 1024 65535
# → net.ipv4.tcp_tw_reuse = 1
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_max_syn_backlog = 65535
```

#### 3. Отключение conntrack (Connection Tracking)

Модуль `nf_conntrack` отслеживает состояние каждого пакета для сетевого экрана (iptables/nftables). При интенсивном нагрузочном тестировании таблица состояний переполняется, ядро начинает безвозвратно сбрасывать входящие пакеты (`dmesg: nf_conntrack: table full, dropping packet`), что ошибочно принимается за падение веб-сервера.

Решение: отключение трекинга для портов бенчмаркинга:
```bash
# Проверка заполненности таблицы conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count; cat /proc/sys/net/netfilter/nf_conntrack_max
# → 1240
# → 262144

# Отключение conntrack для тестового трафика (порт 80/443) через таблицу raw
sudo iptables -t raw -A PREROUTING -p tcp -m multiport --dports 80,443 -j NOTRACK
sudo iptables -t raw -A OUTPUT -p tcp -m multiport --sports 80,443 -j NOTRACK

# Проверка правил
sudo iptables -t raw -L -n -v
# → Chain PREROUTING (policy ACCEPT 120 packets, 8400 bytes)
# → pkts bytes target     prot opt in     out     source      destination
# →    0     0 CT         tcp  --  *      *       0.0.0.0/0   0.0.0.0/0   multiport dports 80,443 CT notrack
```

#### 4. Аппаратный тюнинг: прерывания, кольцевые буферы и NUMA

```bash
# Увеличение размера кольцевых буферов RX/TX сетевой карты до максимума
sudo ethtool -G eth0 rx 4096 tx 4096
# → Ring parameters for eth0:
# → RX: 4096, TX: 4096

# Фиксация CPU Frequency Governor в режим максимальной производительности
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
# → performance

# Запуск процесса с привязкой к конкретным ядрам CPU (Core Pinning)
taskset -c 0-3 wrk -t4 -c200 -d30s http://192.168.10.20/
```

---

### Сравнительный обзор инструментов

| Инструмент | Язык | Поддерживаемые протоколы | Модель нагрузки | Ключевая сфера применения |
| :--- | :--- | :--- | :--- | :--- |
| **wrk** | C | HTTP/1.1 | Closed Loop | Максимальный RPS, оценка предельного насыщения CPU веб-сервера. Поддержка Lua. |
| **wrk2 / wrkx** | C | HTTP/1.1 | Open Loop (Rate-based) | Измерение задержки под контролируемой нагрузкой, построение гистограмм HDR. |
| **h2load** | C++ | HTTP/1.1, HTTP/2, HTTP/3 (QUIC) | Closed / Multiplexed | Стандарт для тестирования мультиплексирования HTTP/2 и UDP/QUIC (часть nghttp2). |
| **k6** | Go / JS | HTTP/1.1, HTTP/2, gRPC, WebSocket | Open & Closed Loop | Комплексные SRE-сценарии, Quality Gates, CI/CD, гибкая бизнес-логика. |
| **oha** | Rust | HTTP/1.1, HTTP/2, HTTP/3 | Open & Closed Loop | Быстрый ad-hoc анализ в терминале с графическим TUI в реальном времени. |
| **Vegeta** | Go | HTTP/1.1, HTTP/2 | Open Loop (Arrival Rate) | Строго детерминированный RPS, сохранение сырых результатов в бинарный формат. |
| **Bombardier** | Go | HTTP/1.1, HTTP/2 | Closed Loop | Высокопроизводительная замена `ab` с нативным fast-http клиентом. |
| **ab** | C | HTTP/1.1 | Closed Loop | Legacy инструмент (ApacheBench). Однопоточный, только для базового smoke-теста. |
| **ghz** | Go | gRPC | Open & Closed Loop | Специализированный генератор для профилирования и нагрузки gRPC сервисов. |
| **fortio** | Go | HTTP/1.1, HTTP/2, gRPC | Open & Closed Loop | Легковесный нагрузчик с веб-интерфейсом и экспортом в Prometheus. |

---

## Практические сценарии

### Сценарий 1: Измерение максимальной пропускной способности (Raw RPS) с wrk

Утилита `wrk` спроектирована для выжимания предельного количества запросов в секунду на минимальном объеме системных ресурсов. Она использует многопоточный неблокирующий I/O на базе `epoll`.

#### Подготовка Lua-скрипта для динамических POST-запросов (`payload.lua`)

```lua
-- payload.lua — генерация динамических HTTP POST-запросов
wrk.method = "POST"
wrk.headers["Content-Type"] = "application/json"
wrk.headers["Connection"] = "keep-alive"

local counter = 0

function request()
    counter = counter + 1
    local body = string.format('{"request_id": %d, "timestamp": %d}', counter, os.time())
    wrk.body = body
    return wrk.format(nil, nil, nil, body)
end

function response(status, headers, body)
    if status ~= 200 then
        io.write(string.format("Error response status: %d\n", status))
    end
end
```

#### Запуск теста с замером задержки

```bash
# Запуск: 4 потока ОС, 200 постоянных соединений, длительность 30 секунд
wrk -t4 -c200 -d30s --latency -s payload.lua http://192.168.10.20/api/v1/event
# → Running 30s test @ http://192.168.10.20/api/v1/event
# →   4 threads and 200 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     1.85ms  721.43us  18.42ms   88.14%
# →     Req/Sec    27.12k     1.84k   31.20k    72.50%
# →   Latency Distribution
# →      50%    1.68ms
# →      75%    2.10ms
# →      90%    2.74ms
# →      99%    4.35ms
# →   3241088 requests in 30.02s, 562.74MB read
# → Requests/sec: 107964.12
# → Transfer/sec:     18.75MB
```

Параметры:
- `-t4`: запуск 4 рабочих потоков (рекомендуется равнять количеству физических ядер генератора).
- `-c200`: поддержание пула из 200 одновременных постоянных TCP-соединений.
- `-d30s`: продолжительность активной фазы тестирования.
- `--latency`: вывод детальной статистики перцентилей задержки.

---

### Сценарий 2: Тестирование фиксированного темпа (Open Loop) с wrk2 и Vegeta

В отличие от стандартного `wrk`, `wrk2` отправляет запросы со строго заданной скоростью, что предотвращает ошибку Coordinated Omission.

#### Тестирование фиксированного RPS через wrk2

```bash
# Запуск wrk2 с частотой 15 000 RPS, 2 потока, 100 соединений, тест 60 секунд
wrk -t2 -c100 -d60s -R15000 --latency http://192.168.10.20/healthz
# → Running 1m test @ http://192.168.10.20/healthz
# →   2 threads and 100 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     1.12ms  420.10us  24.18ms   92.40%
# →     Req/Sec     7.50k   180.20     8.10k    84.00%
# →   Latency Distribution (HdrHistogram - Raw Latency)
# →      50.000%    1.02ms
# →      75.000%    1.25ms
# →      90.000%    1.60ms
# →      99.000%    2.48ms
# →      99.900%    8.14ms
# →      99.990%   18.20ms
# →   899982 requests in 1.00m, 145.92MB read
# → Requests/sec:  14999.70
# → Transfer/sec:      2.43MB
```

#### Детерминированный тест с Vegeta

Vegeta позволяет сохранять сырые результаты каждого запроса в бинарный файл для последующего математического анализа и построения графиков.

```bash
# Генерация нагрузки: 5000 RPS в течение 30 секунд с сохранением результатов
echo "GET http://192.168.10.20/healthz" | vegeta attack -rate=5000/1s -duration=30s > results.bin

# Построение текстового статистического отчета
vegeta report results.bin
# → Requests      [total, rate, throughput]         150000, 5000.04, 4999.98
# → Duration      [total, attack, wait]             30.000s, 29.999s, 1.15ms
# → Latencies     [min, mean, 50, 90, 95, 99, max]  620us, 1.24ms, 1.08ms, 1.72ms, 2.15ms, 4.80ms, 45.12ms
# → Bytes In      [total, mean]                     25500000, 170.00
# → Bytes Out     [total, mean]                     0, 0.00
# → Success       [ratio]                           100.00%
# → Status Codes  [code:count]                      200:150000

# Построение гистограммы задержек
vegeta report -type='hist[0,1ms,2ms,5ms,10ms,20ms]' results.bin
# → Bucket           #       %       SLA
# → [0s,     1ms]    68420   45.61%  45.61%
# → [1ms,    2ms]    72100   48.07%  93.68%
# → [2ms,    5ms]    8940    5.96%   99.64%
# → [5ms,    10ms]   480     0.32%   99.96%
# → [10ms,   20ms]   52      0.03%   100.00%
# → [20ms,   +Inf]   8       0.01%   100.00%
```

---

### Сценарий 3: Бенчмаркинг мультиплексирования HTTP/2 и HTTP/3 (h2load)

Утилита `h2load` (компонент `nghttp2`) предназначена для валидации протоколов нового поколения. Она измеряет способность веб-сервера мультиплексировать сотни запросов внутри ограниченного числа сокетов.

#### Тестирование HTTP/2 с мультиплексированием стримов

```bash
# 50 000 запросов через 20 постоянных TCP-соединений с 50 параллельными стримами в каждом
h2load -n 50000 -c 20 -m 50 --h2 https://192.168.10.20/index.html
# → starting benchmark...
# → spawning thread #0: 20 total client(s). 50000 total requests
# → progress: 100% done
# → 
# → finished in 0.82s, 60975.61 req/s, 72.15MB/s
# → requests: 50000 total, 50000 started, 50000 done, 50000 succeeded, 0 failed, 0 errored, 0 timeout
# → status codes: 50000 2xx, 0 3xx, 0 4xx, 0 5xx
# → traffic: 60.54MB (63480000) total, 820.00KB (839680) headers (space savings 74.20%), 58.82MB (61680000) data
# →                      min         max        mean      median      sd
# → time for request:    1.20ms     28.40ms     8.12ms      7.40ms    3.15ms
# → time to first byte:  2.10ms     31.10ms     9.80ms      8.90ms    3.40ms
```

Параметры:
- `-n 50000`: суммарный объем запросов.
- `-c 20`: количество параллельно открытых TCP-клиентов.
- `-m 50`: максимальное количество одновременных потоков (`SETTINGS_MAX_CONCURRENT_STREAMS`) в одном соединении.
- `--h2`: принудительное согласование протокола HTTP/2 через TLS ALPN.

#### Тестирование HTTP/3 (QUIC over UDP)

```bash
# Тест HTTP/3: 20 000 запросов через UDP-сокеты
h2load -n 20000 -c 50 -m 20 --npn-list h3 https://192.168.10.20/
# → starting benchmark...
# → spawning thread #0: 50 total client(s). 20000 total requests
# → progress: 100% done
# → 
# → finished in 0.95s, 21052.63 req/s, 24.85MB/s
# → requests: 20000 total, 20000 started, 20000 done, 20000 succeeded, 0 failed, 0 errored, 0 timeout
# → status codes: 20000 2xx, 0 3xx, 0 4xx, 0 5xx
# →                      min         max        mean      median      sd
# → time for request:    1.45ms     35.12ms    11.20ms      9.80ms    4.20ms
```

> [!NOTE]
> При тестировании HTTP/3 отслеживайте утилизацию CPU на сервере командой `mpstat -P ALL 1`. Высокое время в `%soft` указывает на насыщение драйвера обработки UDP-пакетов ядром Linux.

---

### Сценарий 4: Тестирование производительности CPS (Connections Per Second) и TLS Handshake

Тест направлен на оценку стоимости криптографических операций и времени рукопожатия TLS (RSA vs ECDSA, OpenSSL vs AWS-LC).

#### 1. Подготовка легковесного эндпоинта в Nginx / Angie

Конфигурация `/etc/nginx/conf.d/bench_tls.conf`:
```nginx
server {
    listen 443 ssl default_server reuseport;
    server_name bench.local;

    ssl_certificate     /etc/ssl/certs/bench_ecdsa.crt;
    ssl_certificate_key /etc/ssl/private/bench_ecdsa.key;
    ssl_protocols       TLSv1.3;
    ssl_ciphers         TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;

    # Отключение дискового ввода-вывода
    access_log off;

    location /zero {
        return 200 "";
    }
}
```

#### 2. Запуск нагрузочного теста в режиме `Connection: close`

Для измерения CPS необходимо принудительно отключать Keep-Alive, чтобы каждый запрос инициировал новый TCP 3-way handshake и полный TLS handshake:

```bash
# Использование oha с отключенным Keep-Alive
oha -n 20000 -c 100 --disable-keepalive https://192.168.10.20/zero
# → Summary:
# →   Success rate: 100.00%
# →   Total:        4.5210 secs
# →   Slowest:      0.0842 secs
# →   Fastest:      0.0120 secs
# →   Average:      0.0224 secs
# →   Requests/sec: 4423.80
# → 
# → Response time histogram:
# →   0.012 [1]    |
# →   0.019 [8412] |■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
# →   0.026 [9840] |■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
# →   0.034 [1420] |■■■■■
# →   0.041 [280]  |■
# →   0.084 [47]   |
# → 
# → Latency distribution:
# →   10% in 0.0162 secs
# →   50% in 0.0210 secs
# →   90% in 0.0289 secs
# →   99% in 0.0482 secs
```

При 4423 CPS сервер производит более 4400 полных асимметричных криптографических операций в секунду. Сравнение ECDSA (кривая secp256r1 или Ed25519) с классическим RSA-2048 демонстрирует 3–4 кратное превосходство эллиптических кривых по CPS при идентичной загрузке ядер CPU.

---

### Сценарий 5: Интерактивный TUI-анализ в реальном времени с oha

Утилита `oha` (написанная на Rust) обеспечивает моментальную обратную связь в консоли без необходимости запуска внешних систем визуализации.

```bash
# Запуск с ограничением частоты 2000 QPS, 50 соединений, длительность 20 секунд
oha -z 20s -q 2000 -c 50 --latency-correction https://192.168.10.20/api/status
# → Summary:
# →   Success rate: 100.00%
# →   Total:        20.0012 secs
# →   Slowest:      0.0152 secs
# →   Fastest:      0.0008 secs
# →   Average:      0.0021 secs
# →   Requests/sec: 1999.88
# → 
# → Latency distribution:
# →   10% in 0.0012 secs
# →   25% in 0.0015 secs
# →   50% in 0.0019 secs
# →   75% in 0.0024 secs
# →   90% in 0.0031 secs
# →   95% in 0.0038 secs
# →   99% in 0.0062 secs
```

Флаг `--latency-correction` активирует математическую компенсацию Coordinated Omission.

---

### Сценарий 6: Комплексный SRE-тест с k6 (Performance-as-Code)

Тестирование с использованием декларативного сценария `load_test.js` с жесткими критериями качества (Quality Gates):

```javascript
// load_test.js — открытый цикл нагрузки с проверкой порогов SLO
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    constant_rate_test: {
      executor: 'constant-arrival-rate',
      rate: 3000,              // Целевая нагрузка: 3000 RPS
      timeUnit: '1s',
      duration: '1m',
      preAllocatedVUs: 100,    // Предварительно выделенные виртуальные пользователи
      maxVUs: 300,             // Предел масштабирования VU при росте задержки
    },
  },
  thresholds: {
    // 95% запросов должны выполняться быстрее 50 мс
    http_req_duration: ['p(95)<50', 'p(99)<150'],
    // Доля сетевых или HTTP-ошибок строго менее 0.1%
    http_req_failed: ['rate<0.001'],
  },
};

export default function () {
  const params = {
    headers: {
      'Accept': 'application/json',
      'User-Agent': 'k6-benchmark-agent/2.3',
    },
    timeout: '2s',
  };

  const res = http.get('http://192.168.10.20/api/data', params);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'content present': (r) => r.body && r.body.length > 0,
  });
}
```

Запуск теста в консоли:
```bash
k6 run --summary-trend-stats="min,avg,med,p(95),p(99),max" load_test.js
# →           /\      |‾‾| /‾‾/   /‾‾/   
# →      /\  /  \     |  |/  /   /  /    
# →     /  \/    \    |     (   /   ‾‾\  
# →    /          \   |  |\  \ |  (‾)  | 
# →   / __________ \  |__| \__\ \_____/ .io
# → 
# →      execution: local
# →      scenarios: (100.00%) 1 scenario, 300 max VUs, 1m30s max duration:
# →               * constant_rate_test: 3000.00 iterations/s for 1m0s (maxVUs: 100-300)
# → 
# →      ✓ status is 200
# →      ✓ content present
# → 
# →      checks.........................: 100.00% ✓ 360000      ✗ 0     
# →      http_req_duration..............: min=1.12ms avg=4.15ms med=3.80ms p(95)=8.40ms p(99)=18.20ms max=64.10ms
# →      http_req_failed................: 0.00%   ✓ 0           ✗ 180000
# →      http_reqs......................: 180000  2999.85/s
# →      vus............................: 100     min=100       max=100 
```

При нарушении порогов `thresholds` процесс `k6` завершается с ненулевым кодом возврата (`exit code 99`), что позволяет автоматически блокировать пайплайны развертывания при деградации производительности.

---

### Сценарий 7: Бенчмаркинг gRPC эндпоинтов с ghz

Инструмент `ghz` предназначен для нагрузочного тестирования RPC-сервисов, использующих Protocol Buffers поверх HTTP/2.

```bash
# Тест gRPC вызова с передачей JSON-полезной нагрузки
ghz --insecure \
  --proto=./order_service.proto \
  --call=orders.OrderService.GetOrder \
  --data='{"order_id": 42001}' \
  --concurrency=50 \
  --total=50000 \
  --cpus=4 \
  192.168.10.20:50051
# → Summary:
# →   Count:        50000
# →   Total:        2.84 s
# →   Slowest:      14.20 ms
# →   Fastest:      0.65 ms
# →   Average:      2.80 ms
# →   Requests/sec: 17605.63
# → 
# → Response time histogram:
# →   0.65  [1]     |
# →   2.00  [18420] |■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
# →   3.36  [26100] |■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
# →   4.71  [4800]  |■■■■■■■■
# →   14.20 [679]   |■
# → 
# → Latency distribution:
# →   10 % in 1.40 ms
# →   50 % in 2.65 ms
# →   90 % in 4.10 ms
# →   99 % in 7.80 ms
# → 
# → Status code distribution:
# →   [OK]   50000 responses
```

> [!IMPORTANT]
> При тестировании gRPC в инфраструктуре с балансировщиками L4 (например, IPVS или базовые TCP-прокси) все запросы одного соединения `ghz` будут направляться на один и тот же целевой узел. Для равномерного распределения нагрузки между подами/серверами необходим L7-балансировщик (Envoy, Angie, HAProxy).

---

## Операции и команды

### Сводная матрица типовых команд запуска

| Задача | Инструмент | Команда |
| :--- | :--- | :--- |
| **Smoke-тест доступности** | `ab` | `ab -n 1000 -c 10 -k http://192.168.10.20/` |
| **Предельный RPS (Keep-Alive)** | `wrk` | `wrk -t4 -c200 -d30s --latency http://192.168.10.20/` |
| **Задержка Open Loop (HDR)** | `wrk2` | `wrk -t4 -c100 -d60s -R10000 --latency http://192.168.10.20/` |
| **Потоки HTTP/2 multiplexing** | `h2load` | `h2load -n 100000 -c 50 -m 100 --h2 https://192.168.10.20/` |
| **Протокол HTTP/3 (QUIC)** | `h2load` | `h2load -n 50000 -c 50 -m 20 --npn-list h3 https://192.168.10.20/` |
| **Тест CPS (новые соединения)** | `oha` | `oha -n 20000 -c 100 --disable-keepalive https://192.168.10.20/zero` |
| **Ad-hoc интерактивный тест** | `oha` | `oha -z 30s -q 2500 -c 50 https://192.168.10.20/` |
| **Строгий Rate-тест в файл** | `vegeta` | `echo "GET http://192.168.10.20/" \| vegeta attack -rate=5000 -duration=30s > out.bin` |
| **gRPC сервис с proto** | `ghz` | `ghz --insecure --proto=app.proto --call=pkg.Svc.Method -c 50 -n 20000 192.168.10.20:50051` |
| **Quality Gate в пайплайне** | `k6` | `k6 run --out json=metrics.json test_scenario.js` |

---

### Контейнеризированный запуск генераторов (Docker / Podman)

Запуск нагрузочных агентов в контейнерах гарантирует стандартизацию окружения и библиотек:

```bash
# 1. k6 в контейнере с пробросом скриптов и выгрузкой результатов
docker run --rm -i \
  --network host \
  -v $(pwd)/scripts:/scripts:ro \
  -v $(pwd)/reports:/reports \
  grafana/k6:latest run /scripts/load_test.js --out json=/reports/result.json

# 2. oha в контейнере
docker run --rm -it \
  --network host \
  ghcr.io/hatoo/oha:latest -z 30s -c 100 -q 1000 https://192.168.10.20/

# 3. vegeta в контейнере
docker run --rm -i \
  --network host \
  peterevans/vegeta:latest sh -c \
  "echo 'GET http://192.168.10.20/' | vegeta attack -rate=2000 -duration=20s | vegeta report"
```

> [!CAUTION]
> При использовании Docker флаг `--network host` обязателен. Стандартный сетевой мост Docker (`bridge`) выполняет трансляцию сетевых адресов (NAT/iptables), что снижает предельный RPS в 2–4 раза и искусственно искажает сетевые задержки.

---

### Автоматизация комплексного бенчмаркинга (`run_benchmark.sh`)

Скрипт выполняет поэтапный стресс-тест веб-сервера с параллельным фоновым сбором метрик утилизации ресурсов ядра через `vmstat` и `ss`:

```bash
#!/usr/bin/env bash
# run_benchmark.sh — автоматизированный прогон бенчмарка с фиксацией системных метрик
set -euo pipefail

TARGET_URL="${1:?Usage: $0 <target_url> [threads] [concurrency] [duration_sec] [rate]}"
THREADS="${2:-4}"
CONCURRENCY="${3:-100}"
DURATION="${4:-30}"
RATE="${5:-5000}"
OUT_DIR="./benchmark_results_$(date +%Y%m%d_%H%M%S)"

mkdir -p "$OUT_DIR"
echo "=== Начало тестирования: $TARGET_URL ==="
echo "Параметры: Threads=$THREADS, Conn=$CONCURRENCY, Duration=${DURATION}s, TargetRate=$RATE"

# Проверка базовой доступности целевого узла
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$TARGET_URL" || true)
if [[ "$HTTP_CODE" != "200" ]]; then
    echo "Ошибка: Целевой адрес вернул код $HTTP_CODE вместо 200 OK"
    exit 1
fi

# Фоновый сбор системной телеметрии (раз в секунду)
vmstat 1 "$DURATION" > "$OUT_DIR/system_vmstat.log" 2>&1 &
VMSTAT_PID=$!

ss -s > "$OUT_DIR/sockets_before.log"

# Запуск нагрузки (wrk2 при наличии rate, иначе стандартный wrk)
echo "Генерация нагрузки..."
if command -v wrk2 &> /dev/null && [ "$RATE" -gt 0 ]; then
    wrk2 -t"$THREADS" -c"$CONCURRENCY" -d"${DURATION}s" -R"$RATE" --latency "$TARGET_URL" | tee "$OUT_DIR/wrk_report.txt"
else
    wrk -t"$THREADS" -c"$CONCURRENCY" -d"${DURATION}s" --latency "$TARGET_URL" | tee "$OUT_DIR/wrk_report.txt"
fi

wait "$VMSTAT_PID" || true
ss -s > "$OUT_DIR/sockets_after.log"

echo "=== Тестирование завершено. Артефакты сохранены в: $OUT_DIR ==="
```

---

## Устранение неисправностей

### 1. Низкий RPS при возрастании количества потоков/соединений

| Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- |
| **Сетевой лимит интерфейса** | `ethtool eth0 \| grep Speed`, `iftop -i eth0` | Рассчитать объем трафика; включить сжатие (Brotli/Gzip) или агрегировать каналы (LACP/Bonding). |
| **CPU Bottleneck генератора** | `htop`, `pidstat -p $(pgrep wrk) 1` | Генератор уперся в 100% CPU. Разнести потоки на разные ядра (`taskset`), увеличить число генераторных нод. |
| **Сброс пакетов кольцевого буфера** | `ethtool -S eth0 \| grep -E 'drop\|rx_missed'` | Увеличить размер очередей: `ethtool -G eth0 rx 4096 tx 4096`. |
| **Перегрузка одного ядра прерываниями (SoftIRQ)** | `mpstat -P ALL 1` (высокий `%soft` на Core 0) | Настроить RPS/RFS (Receive Packet Steering) или включить RSS в драйвере NIC: [RSS, RPS, RFS в Linux](../Linux/Networking/Concepts/rss_rps_rfs.md). |
| **Логирование на диск** | `iostat -xz 1` (%util близко к 100%) | Отключить `access_log` на сервере или перенести логи в `tmpfs`. |

---

### 2. Аномально высокие перцентили задержки ($p99$ / $p99.9$)

| Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- |
| **Coordinated Omission** | Использование `ab` или `wrk` при тестировании медленных эндпоинтов | Переключиться на генераторы открытого цикла: `wrk2` (с флагом `-R`), `Vegeta` или `k6` (`constant-arrival-rate`). |
| **GC-паузы бэкенда** | Логи сборщика мусора, мониторинг JVM/Go/Node.js | Настроить параметры аллокации памяти, включить low-latency GC (ZGC/Shenandoah в Java). |
| **Межядерная конкуренция (NUMA)** | `numastat -c`, `numactl --hardware` | Привязать воркеры веб-сервера и генератора к локальным NUMA-нодам (`numactl --cpunodebind=0`). |
| **Блокировка epoll воркеров** | `perf top -p $(pgrep nginx)` | Проверить сторонние синхронные модули Nginx/Angie (например, синхронные вызовы DNS или обращение к диску). |

---

### 3. Ошибки соединений (Connection refused, Reset by peer, TIME_WAIT)

| Симптом / Ошибка | Первопричина | Диагностика | Метод устранения |
| :--- | :--- | :--- | :--- |
| `Cannot assign requested address` (`EADDRNOTAVAIL`) | Исчерпание диапазона локальных эфемерных портов на стороне генератора. | `ss -s \| grep TIME-WAIT` (более 30 000 сокетов). | `sysctl -w net.ipv4.tcp_tw_reuse=1`<br>`sysctl -w net.ipv4.ip_local_port_range="1024 65535"` |
| `Connection reset by peer` (`ECONNRESET`) | Переполнение очереди `listen` (Accept queue) на стороне сервера. | `netstat -s \| grep -i "listen drops"` | Увеличить `net.core.somaxconn=65535` и параметр `backlog` в директиве `listen 80 backlog=65535;` веб-сервера. |
| Пакетные потери без роста задержки | Переполнение таблицы отслеживания сетевых соединений conntrack. | `dmesg \| grep nf_conntrack`<br>`cat /proc/sys/net/netfilter/nf_conntrack_count` | Добавить правила `NOTRACK` в iptables или увеличить `net.netfilter.nf_conntrack_max=1048576`. |
| `Too many open files` (`EMFILE`) | Процесс достиг лимита файловых дескрипторов. | `cat /proc/<PID>/limits \| grep "open files"` | Задать `LimitNOFILE=1048576` в systemd и директиву `worker_rlimit_nofile 1048576;` в конфиге веб-сервера. |
| SYN flood dropped | Срабатывание защиты от SYN-флуда при тесте CPS. | `netstat -s \| grep -i "syncookies"` | Временно отключить `net.ipv4.tcp_syncookies=0` в изолированной тестовой сети и увеличить `tcp_max_syn_backlog=65535`. |

---

### Диагностический алгоритм локализации узкого места

```text
[ Старт: RPS перестал расти при увеличении Concurrency ]
                        │
                        ▼
            [ Проверка CPU на нагрузчике ]
             htop / pidstat
             ├── Использовано > 90% CPU ──► Добавить ядра генератору или еще один хост
             └── Загрузка CPU < 80%
                        │
                        ▼
            [ Проверка сети интерфейса ]
             iftop / ethtool -S
             ├── Дропы / насыщение линка ──► Увеличить Ring Buffers, включить LACP
             └── Сеть свободна
                        │
                        ▼
            [ Проверка CPU и прерываний на сервере ]
             mpstat -P ALL 1
             ├── %soft > 40% (прерывания) ──► Настроить RPS/RFS, разнести IRQ сетевой карты
             ├── %user/%system = 100% ─────► Предел производительности воркеров веб-сервера
             └── CPU свободен (< 50%)
                        │
                        ▼
            [ Проверка системных очередей сокетов ]
             ss -lnt / dmesg
             ├── listen drops растут ──────► Увеличить somaxconn и listen backlog
             ├── conntrack full ───────────► Включить iptables NOTRACK
             └── TIME-WAIT exhaustion ─────► Включить tcp_tw_reuse = 1
```

---

## Лучшие практики

### Методология SRE для нагрузочного тестирования веб-серверов

1. **Изоляция сети на уровне L2:**
   Проводите тестирование в выделенном VLAN или через прямой кабельный патчкорд между сетевыми картами 10/25/40 GbE без промежуточных офисных коммутаторов, межсетевых экранов и роутеров с NAT. Промежуточные stateful-файрволы гарантированно искажают перцентили задержки.
2. **Исключение дискового логирования:**
   Для измерения чистой сетевой производительности сервера создайте изолированный блок:
   ```nginx
   location /benchmark-probe {
       access_log off;
       return 200 "OK\n";
   }
   ```
   Если требуется проверить производительность отдачи статических файлов, используйте `root /dev/shm/static;` (память tmpfs), чтобы исключить латентность контроллера SSD/NVMe.
3. **Обязательная фаза прогрева (Warm-up):**
   Никогда не учитывайте первые 30–60 секунд теста. За это время:
   - Происходит инициализация кэша сессий TLS.
   - Выделяются буферы операционной системы и страницы памяти.
   - Процессор выходит на номинальную турбо-частоту (`cpufreq governor`).
4. **Статистическая достоверность:**
   - Выполняйте серию минимум из 3–5 идентичных прогонов.
   - Разброс медианной задержки между прогонами не должен превышать 5–7%. Больший разброс свидетельствует о наличии паразитной нагрузки в сети или троттлинге CPU.
   - Длительность замера должна составлять не менее 60 секунд для стабилизации $p99$, и не менее 300 секунд для $p99.9$.
5. **Мониторинг хоста по методу USE во время теста:**
   Параллельно с нагрузкой на веб-сервере собираются метрики:
   - **Utilization:** утилизация процессорных ядер воркерами (`pidstat -u 1`).
   - **Saturation:** длина очереди выполнения (`runqueue` в `vmstat`) и количество полуоткрытых сокетов (`ss -s`).
   - **Errors:** счетчики ошибок сетевых интерфейсов (`netstat -s`, `ip -s link`).
6. **Версионирование базовой линии (Baseline):**
   Сохраняйте результаты в JSON-формате вместе с хэшем коммита конфигурации сервера, версией ядра Linux и аппаратным профилем. Это обеспечивает автоматическое обнаружение регрессий при обновлении веб-сервера.
7. **Очистка стенда (Cleanup):**
   После завершения масштабных тестов принудительно очищайте зависшие сокеты, сбрасывайте правила `NOTRACK` в iptables и возвращайте штатные настройки журналирования.

---

### Выбор инструмента по задаче

```text
Какая главная цель тестирования?
├── Максимальный сырой RPS веб-сервера на HTTP/1.1
│   └── wrk (минимальный оверхед, C/epoll)
├── Оценка реальных перцентилей задержки (SLA / Tail Latency)
│   └── wrk2 или Vegeta (Open Loop модель, защита от Coordinated Omission)
├── Мультиплексирование потоков в HTTP/2 или тестирование HTTP/3 (QUIC)
│   └── h2load (нативный nghttp2 стек, поддержка QUIC over UDP)
├── Быстрая ручная проверка с графиками в консоли
│   └── oha (TUI интерфейс, Rust/Tokio)
├── Тестирование емкости новых подключений (CPS) и криптографии TLS
│   └── oha или wrk с Connection: close и замером CPU
├── Высоконагруженные RPC микросервисы
│   └── ghz (специализирован для Protobuf и gRPC)
└── Комплексные SRE-сценарии, пайплайны CI/CD, Quality Gates
    └── k6 (Performance-as-Code, thresholds, сценарии arrival-rate)
```

---

## Дополнительная информация

### См. также

- [Принципы тестирования производительности веб-приложений](./Concepts/web_performance/testing_principles.md) — различия Lab Data, Field Data (RUM) и серверного бенчмаркинга.
- [Настройка Angie для высоких нагрузок](./Angie/High_Load/index.md) — архитектурные оптимизации, тюнинг воркеров, reuseport и epoll.
- [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md) — внедрение Quality Gates, автоматизация порогов и регрессионный анализ в пайплайнах.
- [Нагрузочное тестирование с помощью k6](../Testing/k6_load_testing.md) — детальное руководство по синтаксису сценариев k6, исполнителям и метрикам.
- [Методология тестирования производительности](../Testing/performance_testing_methodology.md) — теория нагрузочного тестирования, классификация тестов и метрики SLI/SLO.
- [RSS, RPS, RFS в Linux](../Linux/Networking/Concepts/rss_rps_rfs.md) — многопоточная обработка сетевых пакетов на уровне ядра Linux и распределение прерываний.
- [Диагностика HTTP-задержек](../Linux/Diagnostics/Networking/curl_network_diagnostics.md) — профилирование фаз соединения (DNS, TCP, TLS handshake, TTFB) с помощью curl.
