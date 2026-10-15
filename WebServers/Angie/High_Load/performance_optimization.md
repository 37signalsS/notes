# Оптимизация производительности Angie

**Актуально для:** Angie 1.12.x (включая Angie PRO для расширенной балансировки и мониторинга)

## Определения

**Оптимизация производительности (Performance Optimization)** — комплекс системных, архитектурных и конфигурационных мер, направленных на максимизацию пропускной способности сервера (RPS — Requests Per Second, Throughput) и минимизацию времени отклика (Latency, TTFB — Time To First Byte) при контролируемом и предсказуемом потреблении системных ресурсов (CPU, RAM, Disk I/O, Network).

**Inflight Requests** — запросы, принятые сервером и переданные бэкендам в обработку, по которым ещё не завершена передача ответа клиенту. Учёт inflight-запросов критичен для предотвращения лавинообразной перегрузки медленных upstream-серверов.

**Kernel TLS (kTLS)** — механизм переноса операций симметричного шифрования и дешифрования TLS (AES-GCM, ChaCha20-Poly1305) непосредственно в ядро Linux. Это позволяет механизму `sendfile()` передавать зашифрованные файлы из Page Cache напрямую в TCP-сокет без двойного копирования между пространством ядра и пользователя.

**Событийно-ориентированная модель (Event-driven Architecture)** — модель неблокирующей обработки соединений, при которой рабочий поток регистрирует дескрипторы сокетов в системном интерфейсе ввода-вывода (`epoll` в Linux, `kqueue` в BSD/macOS) и обрабатывает события асинхронно без накладных расходов на контекстные переключения потоков ОС.

**Zero-Copy** — передача данных между накопителем и сетевым сокетом без промежуточного копирования в адресное пространство процесса (user space). В Angie реализуется через системный вызов `sendfile()`, функции ядра `splice()` и `tee()`.

**SO_REUSEPORT** — опция сокета Linux, позволяющая нескольким независимым процессам или потокам привязываться к одному порту. Ядро распределяет входящие TCP-соединения и UDP-датаграммы между слушающими сокетами на основе хэша 4-tuple (IP/порт источника и назначения), исключая конкуренцию процессов за один сокет.

**Head-of-Line Blocking (HOL)** — задержка очереди, при которой обработка последующих пакетов или запросов блокируется задержкой предыдущего. В HTTP/2 возникает на транспортном уровне TCP при потере пакета; в HTTP/3 (QUIC) устранена за счёт независимых потоков поверх UDP.

**Thundering Herd** — лавинообразное одновременное обращение сотен параллельных клиентов к бэкенду за одним ресурсом (например, в момент инвалидации или холодного старта кэша). В Angie предотвращается директивами `proxy_cache_lock` и разгрузкой фонового обновления `proxy_cache_use_stale updating`.

**Пропускная способность (Throughput)** — объём данных или число запросов, успешно обработанных сервером за единицу времени. Измеряется в RPS (Requests Per Second) или бит/с (Mbps/Gbps).

**Задержка (Latency / TTFB / TTLB)**:
- **TTFB (Time To First Byte)** — интервал от отправки первого байта клиентского запроса до получения первого байта ответа.
- **TTLB (Time To Last Byte)** — полное время доставки ответа клиенту до закрытия соединения или завершения потока.

**Coordinated Omission** — феномен искажения результатов нагрузочного тестирования, при котором инструмент генерации нагрузки задерживает отправку новых запросов, пока ожидает ответа на предыдущие, что занижает реальные показатели задержки high-percentile (p99/p99.9). Инструменты `wrk2` и `k6` корректируют этот эффект.

**NUMA (Non-Uniform Memory Access)** — архитектура многопроцессорных серверов, где доступ процессора к локальному банку памяти происходит быстрее, чем к памяти других сокетов. Неоптимальное распределение процессов Angie по NUMA-узлам вызывает деградацию пропускной способности шин QPI/UPI.

**RSS / RPS / RFS / XPS** — механизмы масштабирования сетевого ввода-вывода в ядре Linux:
- **RSS (Receive Side Scaling)** — аппаратная балансировка пакетов по RX-очередям сетевой карты.
- **RPS (Receive Packet Steering)** — программное распределение входящих пакетов по ядрам CPU.
- **RFS (Receive Flow Steering)** — привязка сетевых очередей к ядрам, на которых выполняется обрабатывающее приложение.
- **XPS (Transmit Packet Steering)** — интеллектуальный выбор TX-очереди передающей сетевой карты в зависимости от ядра CPU.

**TCP BBR (Bottleneck Bandwidth and RTT)** — алгоритм управления перегрузкой TCP, моделирующий узкое место канала и минимальный RTT вместо реагирования на потерю пакетов (в отличие от Reno/Cubic), что предотвращает забивание буферов (bufferbloat) и снижает p99 latency.

**Direct I/O** — режим прямого ввода-вывода с блочного устройства в память процесса в обход кэша страниц ядра (Page Cache), исключающий вымывание полезного кэша при чтении гигантских файлов (видео, дистрибутивы).

**SRE Golden Signals** — четыре базовые метрики надёжности и производительности сервиса: задержка (Latency), объём входящего трафика (Traffic), частота ошибок (Errors) и степень насыщения ресурсов (Saturation).

---

## Базовые концепции

### Архитектура процессов Angie

Angie использует многопроцессную событийно-ориентированную архитектуру:

```
+------------------------------------------------------------------------+
|                          Master Process (root)                         |
|  - Чтение конфигурации (/etc/angie/angie.conf)                         |
|  - Открытие привилегированных сетевых портов (80, 443)                  |
|  - Управление воркерами (сигналы SIGHUP, SIGUSR2, SIGWINCH, SIGQUIT)   |
+-----------------------------------+------------------------------------+
                                    |
          +-------------------------+-------------------------+
          |                         |                         |
+---------v----------+    +---------v----------+    +---------v----------+
|  Worker Process 0  |    |  Worker Process 1  |    |  Worker Process N  |
|  (epoll event loop)|    |  (epoll event loop)|    |  (epoll event loop)|
+---------+----------+    +---------+----------+    +---------+----------+
          |                         |                         |
+---------v-------------------------v-------------------------v----------+
|                 Разделяемая память (POSIX Shared Memory)               |
|  - limit_req_zone (счётчики Leaky Bucket)                              |
|  - limit_conn_zone (активные сессии клиентов)                          |
|  - proxy_cache keys_zone (хэш-индексы кэшированных объектов)           |
|  - upstream zone (статусы, счетчики least_time inflight, dynamic API)  |
|  - status_zone / prometheus (атомарные метрики OpenMetrics)            |
+------------------------------------------------------------------------+
         ^                                                 ^
         |                                                 |
+--------+-----------+                            +--------+-----------+
| Cache Manager      |                            | Cache Loader       |
| (очистка по TTL)   |                            | (индексация диска) |
+--------------------+                            +--------------------+
```

1. **Master-процесс:** Управляет конфигурацией, создаёт и контролирует дочерние процессы, связывает сокеты. Не участвует в передаче сетевого трафика.
2. **Worker-процессы:** Выполняются от непривилегированного пользователя (`angie`). В неблокирующем цикле событий обслуживают тысячи одновременных сетевых соединений. Число процессов привязывается к числу физических ядер: `worker_processes auto;`.
3. **Cache Manager и Cache Loader:** Фоновые вспомогательные процессы. Loader один раз при старте или перезагрузке считывает структуру кэша с диска в разделяемую память; Manager периодически удаляет устаревшие и редко запрашиваемые объекты по достижении `max_size`.
4. **Разделяемая память (POSIX Shared Memory):** Выделяется master-процессом при старте через `mmap(MAP_SHARED)`. Позволяет независимым процессам-воркерам атомарно обмениваться счётчиками лимитов, состояниями бэкендов и метриками.

### Событийный цикл и мультиплексирование ввода-вывода

В основе производительности Angie лежит неблокирующий асинхронный цикл ввода-вывода (event loop):

- **epoll (Linux):** Стандарт для Linux-систем. Поддерживает режимы Level-Triggered (LT) и Edge-Triggered (ET). Angie использует `epoll` с флагом `EPOLLEXCLUSIVE` (при отсутствии `SO_REUSEPORT`) или сбалансированные слушающие сокеты ядра через `SO_REUSEPORT`.
- **multi_accept on;** При наличии директивы воркер за один системный вызов `accept4()` забирает из очереди все ожидающие соединения, уменьшая количество контекстных переключений при резких всплесках трафика.
- **worker_connections:** Максимальное число открытых сетевых сокетов на один воркер (включая как клиентские соединения, так и соединения к бэкендам upstream). Суммарная емкость по дескрипторам ограничивается `worker_rlimit_nofile`.

### Ключевые возможности Angie для высокой нагрузки

1. **Продвинутая балансировка (`least_time`):** Направляет запросы бэкендам с минимальным временем ответа с обязательным контролем незавершённых запросов (`inflight`), предотвращая лавинообразные перегрузки при деградации отдельных узлов.
2. **Аппаратный стек HTTP/3 и eBPF:** Опция `quic_bpf on;` загружает в ядро eBPF-программу `SO_ATTACH_REUSEPORT_CBPF`/`EBPF`, привязывающую UDP-пакеты сессии QUIC (Connection ID) к конкретному воркеру. Сессии клиентов не рвутся при `angie -s reload`. Опция `quic_gso on;` активирует Generic Segmentation Offload для передачи UDP-пакетов крупными блоками до 64 КБ силами NIC.
3. **Нативное сжатие Zstd:** Встроенная поддержка алгоритма Zstandard (`zstd on;`) обеспечивает степень сжатия на уровне Gzip/Brotli при 2–3-кратном снижении нагрузки на CPU.
4. **Нативная наблюдаемость без сайдкаров:** Модуль `prometheus` формирует метрики OpenMetrics напрямую из разделяемой памяти, исключая внешние экспортеры и сетевые задержки сбора статистики.
5. **Кластерная синхронизация зон (Angie PRO):** Передача состояния зон `limit_req`, `limit_conn` и сессий между нодами кластера по протоколу TCP/Stream для исключения локальных перекосов.

### Управление памятью, NUMA и Page Cache

1. **NUMA (Non-Uniform Memory Access):** На серверах с двумя и более CPU-сокетами оперативная память физически разделена. Обращение ядра процессора к чужому узлу NUMA увеличивает задержку доступа к памяти на 30–50%. Для серверов с высокой интенсивностью сетевого ввода-вывода процессы Angie и сетевые прерывания NIC привязываются к ядрам соответствующего сокета через `worker_cpu_affinity` и настройки systemd `CPUAffinity`.
2. **Transparent Huge Pages (THP):** Механизм динамического объединения страниц памяти по 2 МБ в ядре Linux. В High Load средах фоновый поток `khugepaged` вызывает всплески задержек (compaction pauses) и фрагментацию памяти. Для Angie и баз данных THP отключается на уровне операционной системы.
3. **Page Cache и Zero-Copy:** При раздаче статических файлов вызов `sendfile()` считывает данные из Page Cache ядра напрямую в сетевой сокет. Буферизация в пользовательском пространстве отсутствует. Для предотвращения монополизации шины памяти одним большим файлом применяется директива `sendfile_max_chunk 1m;`.
4. **Direct I/O:** При раздаче файлов размером более нескольких мегабайт (видео, образы, архивы) системный кэш страниц вымывается. Директива `directio 8m;` включает прямой доступ к накопителю без загрязнения Page Cache.

### Теория очередей и алгоритмы ограничения скорости

Angie реализует алгоритм **Leaky Bucket (двойное ведро с утечкой)** через директивы `limit_req_zone` и `limit_req`. Правильное понимание математики задержек критично для стабильности:

- **`rate`:** Скорость обработки запросов (утечки ведра).
- **`burst`:** Вместимость ведра для приема кратковременных всплесков без отклонения.
- **`nodelay`:** Немедленная передача burst-запросов на обработку при наличии места в ведре без искусственного удержания в очереди.
- **Формула Кингмана (Kingman's formula):** Среднее время ожидания в очереди $W_q$ при коэффициенте утилизации ресурсов $\rho$:

$$W_q \approx \left(\frac{\rho}{1 - \rho}\right) \cdot \left(\frac{c_a^2 + c_s^2}{2}\right) \cdot \tau$$

Где $\rho$ — утилизация системы, $c_a, c_s$ — коэффициенты вариации входящего потока и времени обслуживания, $\tau$ — среднее время обработки. При росте $\rho > 0.85$ время задержки растет экспоненциально. Настройка лимитов Angie должна отсекать трафик с запасом 15–20% до точки насыщения бэкендов.

---

## Практические сценарии

### Сценарий 1: Системный тюнинг ядра Linux (sysctl, network & memory)

Максимальная производительность Angie невозможна без согласованной настройки сетевого стека, файловых дескрипторов и подсистемы памяти ядра Linux.

#### 1.1. Конфигурация параметров ядра `/etc/sysctl.d/90-angie-highload.conf`

```ini
# Максимальное количество открытых дескрипторов файлов в системе
fs.file-max = 2097152

# Очередь сокетов в состоянии LISTEN (должна быть >= директивы backlog в Angie)
net.core.somaxconn = 65535

# Максимальная очередь входящих сетевых пакетов драйвера NIC
net.core.netdev_max_backlog = 250000

# Диапазон локальных (эфемерных) портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 1024 65535

# Безопасное повторное использование TCP-сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Время удержания сокета в состоянии FIN-WAIT-2 (снижение с дефолтных 60с)
net.ipv4.tcp_fin_timeout = 15

# Запрет сброса окна TCP Slow Start после простоя (критично для Keep-Alive сессий)
net.ipv4.tcp_slow_start_after_idle = 0

# Очередь полуоткрытых соединений (SYN backlog)
net.ipv4.tcp_max_syn_backlog = 65535

# Алгоритм контроля перегрузки TCP BBR с планировщиком fair-queuing (fq)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# TCP Fast Open: разрешение приема и отправки данных в SYN-пакетах (3 = клиент + сервер)
net.ipv4.tcp_fastopen = 3

# Busy Poll: опрос сетевых сокетов без контекстных переключений ядра (в микросекундах)
net.core.busy_poll = 50
net.core.busy_read = 50

# Максимальные и системные буферы приема и отправки TCP (min, default, max в байтах)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Снижение агрессивности сброса памяти в swap
vm.swappiness = 10
```

#### 1.2. Персистентное отключение Transparent Huge Pages (THP)

Файл `/etc/tmpfiles.d/thp.conf` (применяется systemd-tmpfiles без выполнения скриптов):

```ini
w /sys/kernel/mm/transparent_hugepage/enabled - - - - never
w /sys/kernel/mm/transparent_hugepage/defrag - - - - never
```

Альтернатива на уровне загрузчика в `/etc/default/grub`:
```bash
GRUB_CMDLINE_LINUX_DEFAULT="transparent_hugepage=never"
```

#### 1.3. Применение и валидация

```bash
# Применение параметров sysctl
sysctl --system
# → * Applying /etc/sysctl.d/90-angie-highload.conf ...

# Применение правил tmpfiles для THP
systemd-tmpfiles --create /etc/tmpfiles.d/thp.conf

# Проверка текущего состояния THP
cat /sys/kernel/mm/transparent_hugepage/enabled
# → always madvise [never]

# Проверка работы алгоритма BBR
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr
```

Подробнее о параметрах ядра: **[Тюнинг параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md)**.

---

### Сценарий 2: Многопоточность и асинхронный ввод-вывод (AIO и Thread Pools)

При обращении к дискам операция `read()` может заблокировать единственный поток воркера, остановив обработку тысяч клиентских соединений. Вынесение дискового I/O в пулы потоков изолирует задержки накопителей.

```nginx
# Контекст main
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 1048576;

# Пул потоков для тяжелых операций чтения/записи
thread_pool dio_pool threads=32 max_queue=65536;

events {
    worker_connections 65536;
    use epoll;
    multi_accept on;
}

http {
    # Базовые параметры Zero-Copy
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Ограничение размера чанка при sendfile для предотвращения монополизации шины памяти
    sendfile_max_chunk 1m;

    # Асинхронный ввод-вывод через настроенный пул потоков
    aio threads=dio_pool;

    server {
        listen 80;
        server_name static.example.internal;

        root /var/www/static;

        location /files/ {
            # Для файлов свыше 8 МБ включается прямой доступ к диску без Page Cache
            directio 8m;
            aio threads=dio_pool;
            open_file_cache off;
        }

        location /assets/ {
            # Для мелких файлов работает кэширование дескрипторов и Page Cache
            open_file_cache max=50000 inactive=60s;
            open_file_cache_valid 60s;
            open_file_cache_min_uses 2;
            open_file_cache_errors on;
        }
    }
}
```

**Валидация работы пулов потоков:**
```bash
# Проверка наличия созданных потоков в процессах Angie
ps -T -p $(pgrep -f "angie: worker" | head -1)
# → PID   SPID  TTY      TIME     CMD
# → 23145 23145 ?        00:00:12 angie
# → 23145 23146 ?        00:00:00 angie
# → 23145 23147 ?        00:00:00 angie

# Проверка отсутствия очередей и блокировок ввода-вывода через strace
strace -f -p $(pgrep -f "angie: worker" | head -1) -e trace=io_submit,io_getevents 2>&1 | head -n 5
# → io_submit(0x..., 1, [0x...]) = 1
```

---

### Сценарий 3: Аппаратное ускорение TLS через Kernel TLS (kTLS)

При передаче тяжелых ответов по HTTPS процессор тратит до 30–40% циклов на симметричное шифрование в user space и перекладывание буферов. kTLS передает эту задачу ядру, позволяя использовать `sendfile()` совместно с TLS.

#### 3.1. Подготовка операционной системы

```bash
# Загрузка модуля ядра
modprobe tls

# Персистентная загрузка модуля при старте ОС
echo "tls" > /etc/modules-load.d/tls.conf

# Проверка поддержки интерфейса в ядре
ls -ld /sys/kernel/tls
# → drwxr-xr-x 2 root root 0 Oct 14 12:00 /sys/kernel/tls
```

#### 3.2. Конфигурация Angie

```nginx
http {
    # Включение kTLS на уровне OpenSSL 3.0+
    ssl_conf_command Options +KTLS;

    # Современные симметричные шифры с аппаратным ускорением AES-NI
    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Кэширование сессий TLS для предотвращения повторных рукопожатий
    ssl_session_cache shared:SSL:50m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    server {
        listen 443 ssl reuseport;
        server_name api.example.internal;

        ssl_certificate /etc/angie/ssl/server.crt;
        ssl_certificate_key /etc/angie/ssl/server.key;

        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;

        location /download/ {
            root /var/storage;
            sendfile_max_chunk 1m;
        }
    }
}
```

**Валидация:**
```bash
# Проверка наличия флага kTLS на установленном сокете
ss -ti '( sport = :443 )' | grep -E "tls|ktls"
# → tls_tx tls_rx ktls_tx

# Проверка глобальных счетчиков переданных байт через kTLS в ядре
cat /proc/net/tls_stat
# → TlsCurrTxSw 142
# → TlsTxSwBytes 859423104
```

Подробнее о TLS-конфигурациях: **[Настройка TLS в Angie](../angie_tls_setup.md)**.

---

### Сценарий 4: Тюнинг HTTP/3 (QUIC), eBPF и Generic Segmentation Offload

Протокол HTTP/3 работает поверх UDP. При нагрузках свыше 100 000 пакетов в секунду (PPS) операционная система может испытывать потери UDP-датаграмм в буферах сокетов. Angie решает эту проблему комбинацией eBPF и GSO.

```nginx
# В основном контексте main (требуются права root или CAP_BPF / CAP_NET_ADMIN)
quic_bpf on;

events {
    worker_connections 65536;
    use epoll;
}

http {
    server {
        # Порт TCP для fallback и TLS
        listen 443 ssl reuseport;
        # Порт UDP для QUIC с увеличенными сетевыми буферами ядра
        listen 443 quic reuseport rcvbuf=4m sndbuf=4m;

        http2 on;
        http3 on;

        # Разрешение аппаратной сегментации UDP на уровне сетевой карты (GSO)
        quic_gso on;

        # Передача клиентам информации о поддержке HTTP/3
        add_header Alt-Svc 'h3=":443"; ma=86400' always;

        ssl_certificate /etc/angie/ssl/quic.crt;
        ssl_certificate_key /etc/angie/ssl/quic.key;

        location / {
            root /var/www/html;
        }
    }
}
```

**Валидация:**
```bash
# Проверка прослушивания UDP-сокетов воркерами
ss -ulpn | grep angie
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("angie",pid=23145,fd=12),("angie",pid=23146,fd=13))

# Проверка отсутствия ошибок отсутствия eBPF в логе
grep -i "quic_bpf" /var/log/angie/error.log || echo "eBPF loaded cleanly"
# → eBPF loaded cleanly

# Проверка успешного HTTP/3 соединения через curl
curl -I --http3 https://api.example.internal:443/ --cacert /etc/angie/ssl/ca.crt
# → HTTP/3 200
```

---

### Сценарий 5: Продвинутая балансировка и плавный старт (least_time и keepalive к бэкендам)

Использование алгоритма `least_time` с параметром `inflight` динамически защищает бэкенды от каскадного падения при всплесках нагрузки. Постоянный пул соединений исключает накладные расходы на TCP/TLS handshakes к upstream.

```nginx
http {
    upstream backend_cluster {
        # Зона разделяемой памяти для хранения состояний серверов (обязательна)
        zone upstream_api 2m;

        # Балансировка по наименьшему времени ответа (полный ответ) с учетом запросов в обработке
        least_time last_byte inflight;

        # Параметры upstream-узлов
        server 192.168.10.11:8080 max_conns=500 max_fails=3 fail_timeout=10s slow_start=30s;
        server 192.168.10.12:8080 max_conns=500 max_fails=3 fail_timeout=10s slow_start=30s;
        server 192.168.10.13:8080 backup;

        # Пул постоянных TCP-соединений к каждому воркеру
        keepalive 128;
        keepalive_requests 10000;
        keepalive_timeout 65s;
        keepalive_time 1h;
    }

    server {
        listen 80;
        server_name proxy.example.internal;

        location /api/ {
            proxy_pass http://backend_cluster;

            # Использование HTTP/1.1 и сброс заголовка Connection для работы keepalive к бэкенду
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

            # Тюнинг буферов проксирования для предотвращения записи во временные файлы на диск
            proxy_buffering on;
            proxy_buffer_size 16k;
            proxy_buffers 16 32k;
            proxy_busy_buffers_size 64k;
            proxy_temp_file_write_size 64k;

            # Таймауты upstream взаимодействия
            proxy_connect_timeout 2s;
            proxy_send_timeout 10s;
            proxy_read_timeout 10s;
            proxy_next_upstream error timeout invalid_header http_502 http_503;
            proxy_next_upstream_tries 2;
        }
    }
}
```

**Валидация через REST API Angie:**
```bash
# Получение детальной статистики по узлам балансировки
curl -s http://127.0.0.1:8080/api/status/http/upstreams/backend_cluster/ | jq '.peers[] | {server, state, active, requests, responses_total: .responses.total}'
# → {
# →   "server": "192.168.10.11:8080",
# →   "state": "up",
# →   "active": 42,
# →   "requests": 154230,
# →   "responses_total": 154230
# → }
```

---

### Сценарий 6: Нативная наблюдаемость (Prometheus и REST API)

Angie позволяет собирать метрики производительности нативно без внешних сторонних экспортеров.

```nginx
http {
    # Подключение стандартного файла сопоставления метрик Angie
    include prometheus_all.conf;

    server {
        listen 127.0.0.1:8080;
        server_name localhost;

        # Зона сбора статистики по данному виртуальному хосту
        status_zone internal_status;

        # Встроенный JSON REST API мониторинга
        location /status/ {
            api /status/;
            allow 127.0.0.1;
            deny all;
        }

        # Эндпоинт экспорта для сервера Prometheus
        location = /p8s {
            prometheus all;
            allow 127.0.0.1;
            allow 10.0.10.0/24; # Сеть скрейпинга Prometheus
            deny all;
        }
    }
}
```

**Валидация:**
```bash
# Проверка отдачи метрик OpenMetrics
curl -s http://127.0.0.1:8080/p8s | grep -E "angie_http_requests_total|angie_nginx_process_cpu_seconds_total" | head -n 4
# → # HELP angie_http_requests_total Total number of HTTP requests
# → # TYPE angie_http_requests_total counter
# → angie_http_requests_total{status_zone="internal_status"} 842012
# → angie_nginx_process_cpu_seconds_total 145.24

# Проверка состояния кэшей через REST API
curl -s http://127.0.0.1:8080/api/status/http/caches/ | jq 'keys'
# → [ "ram_cache" ]
```

Подробнее: **[Мониторинг Angie через Prometheus](../angie_monitoring/angie_monitoring_prometheus.md)** и **[REST API мониторинга Angie](../angie_monitoring/angie_monitoring_api.md)**.

---

### Сценарий 7: Оптимизация RPS при исчерпании ресурсов CPU и отсутствии бюджета

Когда вертикальное масштабирование невозможно (все CPU загружены на 100%, нет бюджета на закупку серверов), прирост RPS достигается только снижением накладных расходов на каждый запрос.

#### 7.1. Диагностика узких мест (CPU Profiling)

```bash
# 1. Проверка давления на CPU через PSI (Pressure Stall Information)
cat /proc/pressure/cpu
# → some avg10=12.45 avg60=8.10 avg300=5.02 total=14523640
# Значение avg10 > 10% указывает на то, что процессы простаивают в ожидании CPU.

# 2. Анализ соотношения времени в user space (us) и kernel space (sy)
mpstat -P ALL 1 3
# Если sy > 25%, ядро тратит время на прерывания, системные вызовы и блокировки.

# 3. Анализ системных вызовов в реальном времени с помощью perf
perf top -g --ns --all-cpus
# Позволяет локализовать горячие точки (например, memcpy, spinlock, tcp_v4_rcv).
```

#### 7.2. Распределение сетевых прерываний (RPS/RFS/XPS)

На многоядерных машинах один интерфейс может загружать ядро CPU0 на 100% сетевыми прерываниями, в то время как остальные ядра свободны.

```bash
# Включение RPS (распределение пакетов по всем 16 ядрам интерфейса eth0)
for queue in /sys/class/net/eth0/queues/rx-*; do
    echo "ffff" > "$queue/rps_cpus"
done

# Увеличение размера очереди пакетов для RFS
sysctl -w net.core.rps_sock_flow_entries=65536
for queue in /sys/class/net/eth0/queues/rx-*; do
    echo 4096 > "$queue/rps_flow_cnt"
done
```

#### 7.3. Конфигурация Angie для максимальной экономии CPU

```nginx
# main context
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 1048576;
pcre_jit on;

events {
    worker_connections 65536;
    use epoll;
    multi_accept on;
}

http {
    # Исключение копирования данных и минимизация системных вызовов
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;
    tcp_nodelay on;

    # Минимизация аллокаций памяти под клиентские заголовки
    client_header_buffer_size 1k;
    large_client_header_buffers 4 4k;
    client_body_buffer_size 16k;

    # Кэширование файловых дескрипторов (исключает open/stat/close на каждый статический запрос)
    open_file_cache max=50000 inactive=60s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # Сжатие Zstd (уровень 3: отличный компромисс между степенью сжатия и расходом CPU)
    zstd on;
    zstd_comp_level 3;
    zstd_types text/plain text/css application/json application/javascript;

    # Быстрый сброс соединений, нарушающих протокол
    reset_timedout_connection on;
    client_header_timeout 5s;
    client_body_timeout 5s;
    send_timeout 5s;

    server {
        listen 443 ssl reuseport;
        http2 on;

        ssl_certificate /etc/angie/ssl/prod.crt;
        ssl_certificate_key /etc/angie/ssl/prod.key;
        ssl_conf_command Options +KTLS;

        location / {
            root /var/www/optimized;
            # 304 Not Modified без обращения к диску
            etag on;
        }
    }
}
```

---

### Сценарий 8: Systemd-тюнинг и cgroups v2

Для предотвращения уничтожения воркеров демоном OOM Killer и снятия системных ограничений на количество сокетов сервис Angie изолируется в cgroups.

#### Файл `/etc/systemd/system/angie.service.d/override.conf`:

```ini
[Service]
# Лимит на файловые дескрипторы (сокеты + файлы)
LimitNOFILE = 1048576

# Лимит на число процессов и потоков
LimitNPROC = 65536

# Максимальное число задач в cgroup
TasksMax = 65536

# Лимиты оперативной памяти (cgroups v2)
MemoryMax = 12G
MemoryHigh = 10G

# Приоритет ввода-вывода и процесса (nice -10 дает больший квант CPU)
Nice = -10
CPUSchedulingPolicy = other
CPUSchedulingPriority = 0

# Защита master-процесса от аварийного завершения OOM Killer (-1000 — полный запрет)
OOMScoreAdjust = -500

# Автоматический перезапуск при падении
Restart = on-failure
RestartSec = 2s
```

**Применение и валидация:**
```bash
# Перезагрузка юнитов systemd
systemctl daemon-reload
systemctl restart angie

# Проверка примененных лимитов процесса
systemctl show angie --property=LimitNOFILE,MemoryMax,TasksMax,Nice
# → LimitNOFILE=1048576
# → MemoryMax=12884901888
# → TasksMax=65536
# → Nice=-10

# Проверка OOM Score конкретного воркера
cat /proc/$(pgrep -f "angie: worker" | head -1)/oom_score_adj
# → -500
```

---

### Сценарий 9: Кэширование в tmpfs (RAM-backed proxy_cache) и микрокэширование

Для сверхнагруженных API-эндпоинтов чтение кэша даже с быстрого NVMe-накопителя создает системные вызовы и прерывания. Размещение кэша в `tmpfs` переносит данные в оперативную память.

```nginx
http {
    # Путь к кэшу в оперативной памяти (/dev/shm)
    proxy_cache_path /dev/shm/angie_ram_cache
                     levels=1:2
                     keys_zone=ram_cache:64m
                     max_size=2g
                     inactive=120s
                     use_temp_path=off;

    upstream api_service {
        server 127.0.0.1:9000;
        keepalive 64;
    }

    server {
        listen 80;
        server_name api.example.internal;

        location /api/v1/catalog {
            proxy_pass http://api_service;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            # Включение кэширования в RAM
            proxy_cache ram_cache;
            proxy_cache_key "$request_method$request_uri";

            # Микрокэш на 5 секунд (сглаживает пики в тысячи RPS)
            proxy_cache_valid 200 5s;
            proxy_cache_valid 404 1s;

            # Защита от Thundering Herd: только один запрос идет на бэкенд, остальные ждут в очереди
            proxy_cache_lock on;
            proxy_cache_lock_timeout 2s;
            proxy_cache_lock_age 5s;

            # Отдача устаревшего кэша во время обновления или при сбоях бэкенда
            proxy_cache_use_stale error timeout updating http_500 http_502 http_503;
            proxy_cache_background_update on;

            # Информационный заголовок для отладки
            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

**Валидация:**
```bash
# Проверка наличия каталогов кэша в /dev/shm
ls -ld /dev/shm/angie_ram_cache
# → drwx------ 3 angie angie 60 Oct 14 12:00 /dev/shm/angie_ram_cache

# Проверка работы микрокэша через curl
curl -I http://api.example.internal/api/v1/catalog
# → X-Cache-Status: MISS
curl -I http://api.example.internal/api/v1/catalog
# → X-Cache-Status: HIT
```

---

### Сценарий 10: Нагрузочное тестирование и учет Coordinated Omission

Тестирование стандартным инструментом `ab` или некорректно настроенным `wrk` скрывает задержки p99/p99.9 из-за Coordinated Omission. Рекомендуется использовать `wrk2` или `k6`.

#### Тестирование через wrk2 с фиксированным RPS:

```bash
# Скрипт генерации POST-запросов (post.lua)
cat << 'EOF' > /tmp/post.lua
wrk.method = "POST"
wrk.body   = '{"client_id":12345,"action":"query"}'
wrk.headers["Content-Type"] = "application/json"
EOF

# Запуск теста: 4 потока, 200 соединений, длительность 60 секунд, целевой рейт 20 000 RPS
wrk -t4 -c200 -d60s -R20000 -s /tmp/post.lua --latency https://api.example.internal/api/v1/catalog
```

**Ожидаемый вывод:**
```
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%    1.82ms
 75.000%    2.45ms
 90.000%    4.12ms
 99.000%    8.94ms
 99.900%   16.50ms
 99.990%   28.30ms
Requests/sec:  20000.12
Transfer/sec:     45.20MB
```

Подробнее о методиках тестирования: **[Методология тестирования производительности](../../../Testing/performance_testing_methodology.md)**.

---

### Сценарий 11: Мониторинг, алертинг и SRE Golden Signals

Конфигурация правил алертинга для Prometheus Alertmanager на основе встроенных метрик Angie.

#### Файл `/etc/prometheus/rules/angie_performance.yml`:

```yaml
groups:
  - name: angie.performance.rules
    rules:
      # Задержка p99 в секундах
      - record: job:angie_http_latency:p99
        expr: histogram_quantile(0.99, sum(rate(angie_metric_rt_hist_bucket[5m])) by (le))

      # Число запросов в секунду на одно ядро процессора
      - record: job:angie_rps_per_core
        expr: sum(rate(angie_http_requests_total[2m])) / count(count(node_cpu_seconds_total{mode="system"}) by (cpu))

      # Доля 5xx ответов
      - record: job:angie_5xx_error_ratio
        expr: sum(rate(angie_http_requests_total{status=~"5.."}[2m])) / sum(rate(angie_http_requests_total[2m]))

  - name: angie.performance.alerts
    rules:
      - alert: AngieHighLatencyP99
        expr: job:angie_http_latency:p99 > 0.300
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "P99 latency Angie превышает 300мс"
          description: "Текущее значение P99: {{ $value | humanizeDuration }}. Проверьте загрузку upstream и дисковых буферов."

      - alert: AngieHighErrorRate5xx
        expr: job:angie_5xx_error_ratio > 0.02
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Доля ошибок 5xx превышает 2%"
          description: "Текущий уровень ошибок: {{ $value | humanizePercentage }}."

      - alert: AngieWorkerConnectionsExhaustion
        expr: (sum(angie_http_connections_active) / (count(angie_nginx_process_cpu_seconds_total) * 65536)) > 0.80
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Утилизация worker_connections превышает 80%"
          description: "Свободные дескрипторы близки к исчерпанию. Возможна утечка соединений или DoS."
```

---

### Сценарий 12: Расчет емкости (Capacity Planning) и сайзинг системных ресурсов

Инженерный расчет аппаратных требований для поддержки целевого профиля нагрузки.

#### 1. Закон Литтла (Little's Law)
Определяет число параллельно открытых соединений $N$ при заданном RPS $\lambda$ и средней длительности обработки $W$:

$$N = \lambda \cdot W$$

*Пример:* Нагрузка 50 000 RPS, среднее время обработки запроса с учетом сетевого RTT и бэкенда $W = 40\text{ мс } (0.04\text{ с})$.
$$N_{\text{active}} = 50000 \cdot 0.04 = 2000\text{ активных соединений}$$

С учетом Keep-Alive (клиенты удерживают соединение 60 секунд после завершения запроса) число одновременных TCP-сокетов возрастает кратно. При 10 запросах на соединение:
$$N_{\text{total}} = \frac{50000}{10} \cdot 60 = 300000\text{ одновременных клиентских TCP-соединений}$$

#### 2. Расчет системных файловых дескрипторов
Каждое проксируемое соединение требует минимум 2 дескриптора (клиентский сокет + upstream сокет), плюс запас на чтение статических файлов, логи и пайпы:

$$\text{worker\_rlimit\_nofile} \ge (N_{\text{total}} \cdot 2) \cdot 1.3$$
Для 300 000 клиентских соединений:
$$\text{worker\_rlimit\_nofile} \ge 300000 \cdot 2 \cdot 1.3 = 780000\text{ дескрипторов}$$
Рекомендуемое значение в конфигурации: `worker_rlimit_nofile 1048576;`.

#### 3. Расчет оперативной памяти под сетевые сокеты
Память сокета складывается из структуры ядра `struct sock`, структур Angie и буферов `tcp_wmem`/`tcp_rmem`:

$$\text{RAM}_{\text{conn}} \approx S_{\text{angie}} (3\text{ КБ}) + \text{tcp\_rmem\_default} (87\text{ КБ}) + \text{tcp\_wmem\_default} (65\text{ КБ}) \approx 155\text{ КБ на соединение}$$
Для 300 000 соединений:
$$\text{RAM}_{\text{sockets}} \approx 300000 \cdot 155\text{ КБ} \approx 46.5\text{ ГБ оперативной памяти}$$

#### 4. Расчет разделяемой памяти (Shared Memory)
- **`limit_req_zone`:** 64 байта на IP-адрес. Зона размером 10 МБ вмещает $\approx 160000$ уникальных IP.
- **`proxy_cache keys_zone`:** 128 байт на один кэшированный объект в памяти. Зона 64 МБ вмещает $\approx 500000$ объектов.

---

### Сценарий 13: Сжатие трафика и высокопроизводительная отдача статики

Сжатие снижает утилизацию сетевой полосы, но расходует процессорные циклы. Оптимальная конфигурация сочетает динамическое сжатие API через Zstd и статическую отдачу предварительно сжатых файлов фронтенда.

```nginx
http {
    # 1. Zero-Copy отдача
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # 2. Кэш метаданных файлов
    open_file_cache max=50000 inactive=60s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # 3. Нативное сжатие Zstd (для современных клиентов и API)
    zstd on;
    zstd_comp_level 3;
    zstd_min_length 1024;
    zstd_types text/plain text/css application/json application/javascript
               application/xml image/svg+xml font/woff2;

    # 4. Gzip для совместимости с устаревшими клиентами
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript
               application/xml image/svg+xml font/woff2;

    server {
        listen 443 ssl reuseport;
        server_name cdn.example.internal;

        ssl_certificate /etc/angie/ssl/cdn.crt;
        ssl_certificate_key /etc/angie/ssl/cdn.key;

        root /var/www/static;

        # Отдача предварительно сжатых файлов без нагрузки на CPU
        location /assets/ {
            gzip_static on; # Отдает .gz при наличии заголовка Accept-Encoding: gzip
            # При наличии скомпилированного модуля brotli: brotli_static on;

            expires 30d;
            add_header Cache-Control "public, max-age=2592000, immutable" always;
            access_log off;
        }

        # Отдача тяжелого медиа-контента через Direct I/O
        location /media/ {
            directio 8m;
            aio threads=dio_pool;
            sendfile_max_chunk 2m;
            access_log off;
        }
    }
}
```

---

### Сценарий 14: Тюнинг сетевых очередей и буферов сетевой карты (NIC Ring Buffers & Offloading)

На скоростях 10G/25G/40G/100G Ethernet дефолтные кольцевые буферы сетевой карты (Ring Buffers) переполняются за доли миллисекунды при всплесках пакетов, вызывая отбрасывание пакетов (packet drops) на уровне драйвера до передачи в стек ядра Linux.

```bash
# 1. Просмотр текущих и максимальных размеров кольцевых буферов
ethtool -g eth0
# → Ring parameters for eth0:
# → Pre-set maximums:
# → RX:        4096
# → TX:        4096
# → Current hardware settings:
# → RX:        1024
# → TX:        1024

# 2. Увеличение очередей до аппаратного максимума
ethtool -G eth0 rx 4096 tx 4096

# 3. Проверка аппаратных оффлоадов (Hardware Offloading)
ethtool -k eth0 | grep -E "tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload"
# → tcp-segmentation-offload: on
# → generic-segmentation-offload: on
# → generic-receive-offload: on

# 4. Проверка дропов пакетов на интерфейсе
ethtool -S eth0 | grep -E "drop|miss|error" | grep -v ": 0"
# → rx_dropped: 0
# → tx_dropped: 0
```

Для персистентного сохранения параметров сетевой карты создается udev-правило или конфигурация `systemd-networkd`:
`/etc/systemd/network/10-eth0.link`:
```ini
[Match]
OriginalName = eth0

[Link]
ReceiveBufferSize = 4096
TransmitBufferSize = 4096
```

---

## Операции и команды

Сводная таблица ключевых команд системного инженера для оперативной диагностики и управления производительностью Angie:

| Задача | Команда | Назначение и ожидаемый результат |
|---|---|---|
| **Валидация синтаксиса** | `angie -t` | Проверка целостности всех конфигурационных файлов. `# → angie: configuration file ... test is successful` |
| **Грациозный reload** | `angie -s reload` | Перечитывание конфигурации без сброса активных соединений. `# → master process forks new workers` |
| **Смена бинарника** | `kill -USR2 $(cat /run/angie.pid)` | Zero-downtime обновление бинарного файла Angie на лету. `# → запуск нового master процесса` |
| **Инспекция сокетов** | `ss -lntp '( sport = :80 or sport = :443 )'` | Проверка очередей `Send-Q` и `Recv-Q`. При `Recv-Q > 0` очередь сокета переполнена. |
| **Анализ задержек сокетов** | `ss -ti '( sport = :443 )'` | Вывод RTT, minRTT, алгоритма перегрузки (bbr), флагов kTLS. |
| **Мониторинг прерываний** | `watch -n1 "cat /proc/interrupts \| grep -E 'eth\|rx\|tx'"` | Контроль равномерности распределения сетевых прерываний по ядрам. |
| **Оценка давления CPU** | `cat /proc/pressure/cpu` | Измерение PSI (Pressure Stall Information). При `avg10 > 10%` процессор перегружен. |
| **Проверка статуса upstream** | `curl -s http://127.0.0.1:8080/api/status/http/upstreams/<name>/ \| jq` | Вывод счетчиков `active`, `requests`, `fails` по каждому бэкенду. |
| **Скрейпинг метрик** | `curl -s http://127.0.0.1:8080/p8s` | Получение нативных метрик в текстовом формате OpenMetrics. |
| **Сброс Page Cache** | `echo 3 > /proc/sys/vm/drop_caches` | Экстренная очистка дискового кэша ядра (только для тестирования холодного старта!). |

---

## Устранение неисправностей

### Матрица симптомов и решений

| Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| **Рост Recv-Q в `ss -lnt`** | Переполнение очереди `backlog` слушающего сокета | `ss -lnt` показывает `Recv-Q` равный `Send-Q` | Увеличить `net.core.somaxconn` в sysctl и параметр `backlog=65535` в директиве `listen`. |
| **Ошибки `1024: Too many open files`** | Превышен лимит файловых дескрипторов процесса | `grep "open files" /var/log/angie/error.log` | Увеличить `worker_rlimit_nofile` в Angie и `LimitNOFILE` в `override.conf` systemd. |
| **Высокий sy% (>30%) в top** | Забивание одного ядра сетевыми прерываниями (hot core) | `cat /proc/interrupts`, `mpstat -P ALL 1` | Настроить RPS/RFS на сетевой карте, включить `SO_REUSEPORT`, отключить `irqbalance` при ручной привязке. |
| **Каскадные ошибки 502/504** | Исчерпание емкости upstream-серверов | `/api/status/http/upstreams/` показывает рост `active` и `fails` | Настроить `least_time last_byte inflight`, ограничить `max_conns`, включить микрокэш `proxy_cache`. |
| **Задержки p99 скачут до секунд** | Compaction pauses в Transparent Huge Pages | `cat /proc/vmstat \| grep compact` | Персистентно отключить THP через `/etc/tmpfiles.d/thp.conf` (`w ... never`). |
| **Ошибки `packet receive errors` в UDP** | Переполнение буфера сокета при HTTP/3 | `netstat -su \| grep "buffer errors"` | Увеличить `rcvbuf=4m` в директиве `listen ... quic`, поднять `net.core.rmem_max` в sysctl. |
| **Запись во временные файлы на диск** | Ответ бэкенда превышает размер буферов проксирования | `grep "an upstream response is buffered to a temporary file" /var/log/angie/error.log` | Увеличить `proxy_buffers` и `proxy_buffer_size`, чтобы ответы помещались в RAM. |

### Экстренный план реагирования (Emergency Runbook)

При внезапной деградации пропускной способности или лавинообразном росте задержек:

```
[Алерт: P99 Latency > 500ms или 5xx Rate > 5%]
                         |
                         v
       +------------------------------------+
       | 1. Экспресс-анализ ресурсов        |
       | - cat /proc/pressure/cpu           |
       | - ss -lnt (проверка Recv-Q)        |
       | - top -b -n1 | head -n 15          |
       +-----------------+------------------+
                         |
           +-------------+-------------+
           |                           |
    [CPU-bound: us ~ 100%]       [I/O / Network bound]
           |                           |
           v                           v
+--------------------------+ +--------------------------+
| 2A. Включение аварийного | | 2B. Разгрузка диска/сети |
|     микрокэша в RAM      | | - Включение directio     |
| - proxy_cache_valid 200  | | - Отключение access_log  |
|   на 2-5 секунд          | | - Включение TCP BBR      |
| - proxy_cache_lock on    | |                          |
+--------------------------+ +--------------------------+
           |                           |
           +-------------+-------------+
                         |
                         v
       +------------------------------------+
       | 3. Грациозное перечитывание        |
       |    angie -t && angie -s reload     |
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       | 4. Проверка стабилизации метрик    |
       | - watch -n1 'ss -s'                |
       | - curl /p8s | grep requests_total  |
       +------------------------------------+
```

1. **Изоляция источника перегрузки:** Выяснить, где образовалось узкое место:
   ```bash
   # Проверка давления на CPU, память и I/O
   cat /proc/pressure/{cpu,memory,io}
   ```
2. **Включение экстренной защиты бэкендов:**
   Если бэкенды перегружены, активировать микрокэш на 3 секунды в оперативной памяти:
   ```nginx
   # Временная директива в /etc/angie/conf.d/emergency.conf
   proxy_cache_valid 200 3s;
   proxy_cache_lock on;
   proxy_cache_use_stale error timeout updating;
   ```
   Применить: `angie -s reload`.
3. **Отключение некритичных подсистем:**
   При дефиците дискового ввода-вывода временно отключить запись журнала доступа:
   ```nginx
   access_log off;
   ```
4. **Контроль восстановления:**
   ```bash
   # Мониторинг стабилизации числа соединений
   watch -n1 'ss -s'
   ```

---

## Лучшие практики

### Рекомендации по оптимизации

1. **PCRE JIT:** Всегда активируйте `pcre_jit on;` в основном контексте. Это компилирует регулярные выражения в машинный код во время старта, ускоряя парсинг сложных правил `location` и `rewrite` на 20–40%.
2. **Буферизация access_log:** Никогда не используйте синхронную запись логов под нагрузкой свыше 10 000 RPS. Настраивайте буферизацию: `access_log /var/log/angie/access.log combined buffer=64k flush=5s;`.
3. **Keepalive к бэкендам:** Каждое новое TCP-соединение к локальному бэкенду тратит 3 системных вызова ядра и 2 переключения контекста. Пул `keepalive 64;` в блоке `upstream` сокращает задержку на 30–50%.
4. **Аппаратные оффлоады:** Убедитесь, что сетевые адаптеры используют TSO (TCP Segmentation Offload), GSO и GRO. Это позволяет ядру оперировать крупными блоками данных (до 64 КБ) вплоть до передачи в чип сетевой карты.
5. **Изоляция ядер процессора:** На специализированных балансировщиках используйте параметр загрузчика ядра `isolcpus` или утилиту `numactl`, чтобы закрепить воркеры Angie на конкретных ядрах, изолировав их от системных демонов.

### Архитектурные антипаттерны в High Load

- **Синхронное логирование на диск без буферизации:** Приводит к блокировке воркеров при задержках дисковой подсистемы (iowait).
- **Чрезмерно раздутые буферы клиентов:** Установка `client_body_buffer_size 1m;` при 50 000 соединений приведет к мгновенному исчерпанию оперативной памяти и аварийному завершению через OOM Killer. Буферы должны покрывать 95% типичных запросов (16–32 КБ), а редкие тяжелые запросы сбрасываться во временные файлы.
- **Отсутствие Keep-Alive к upstream-серверам:** Проксирование с постоянным пересозданием соединений перегружает стек ядра бэкенда тысячами сокетов в `TIME_WAIT`.
- **Игнорирование Coordinated Omission:** Использование инструментов нагрузочного тестирования с синхронной блокирующей моделью создает ложное ощущение низкой задержки сервиса.
- **Включение Swap под высокой нагрузкой:** При активной работе с памятью сброс даже нескольких сотен мегабайт страниц в swap-раздел приводит к лавинообразным задержкам на миллисекунды и деградации p99.

### Чек-лист готовности к высокой нагрузке (Production Readiness)

- [ ] В `angie.conf` установлены `worker_processes auto;` и `worker_cpu_affinity auto;`
- [ ] Параметр `worker_rlimit_nofile` установлен в значение $\ge 1048576$
- [ ] `worker_connections` в блоке `events` составляет не менее $65536$
- [ ] Включены `sendfile on;`, `tcp_nopush on;` и `tcp_nodelay on;`
- [ ] Настроен кэш файловых дескрипторов `open_file_cache`
- [ ] Включено сжатие Zstd (`zstd on;`, уровень 3) для текстовых форматов и API
- [ ] Включен пул постоянных соединений `keepalive` в блоках `upstream`
- [ ] Для HTTPS активирован kTLS (`ssl_conf_command Options +KTLS;`) при поддержке ядра
- [ ] Для HTTP/3 настроены `quic_bpf on;` и `quic_gso on;` с буферами `rcvbuf=4m sndbuf=4m`
- [ ] В sysctl настроены `net.core.somaxconn = 65535` и `net.ipv4.tcp_tw_reuse = 1`
- [ ] Алгоритм контроля перегрузки переведен на `bbr` с дисциплиной `fq`
- [ ] Отключен Transparent Huge Pages (THP) через `/etc/tmpfiles.d/thp.conf`
- [ ] Кольцевые буферы сетевой карты (Ring Buffers) увеличены до максимума (`ethtool -G rx 4096 tx 4096`)
- [ ] В systemd настроен `override.conf` с `LimitNOFILE=1048576` и `OOMScoreAdjust=-500`
- [ ] Настроен экспорт метрик Prometheus через модуль `prometheus all;`
- [ ] Проведено валидационное тестирование инструментом `wrk2` или `k6` с анализом p95/p99 задержек

---

## Дополнительная информация

- [Архитектура высокой нагрузки и защита от атак в Angie](./index.md) — обзорная архитектура и эшелонированная защита
- [Защита от DoS-атак в Angie](./dos_protection.md) — rate-limiting, blacklisting и фильтрация L7
- [Мониторинг Angie через Prometheus](../angie_monitoring/angie_monitoring_prometheus.md) — интеграция метрик OpenMetrics
- [REST API мониторинга Angie](../angie_monitoring/angie_monitoring_api.md) — динамическая статистика и управление бэкендами
- [Тюнинг параметров ядра Linux (sysctl)](../../../Linux/Core/kernel/sysctl.md) — фундаментальное руководство по параметрам `/proc/sys/`
- [Linux RSS, RPS, RFS и XPS](../../../Linux/Networking/Concepts/rss_rps_rfs.md) — многопоточное масштабирование сетевых очередей ядра
- [Методология тестирования производительности](../../../Testing/performance_testing_methodology.md) — планирование тестов и анализ распределения задержек
- [Законы масштабируемости](../../../Concepts/High_Availability/scalability_laws.md) — закон Амдала и закон Универсальной масштабируемости Гюнтера (USL)
- [Настройка TLS в Angie](../angie_tls_setup.md) — параметры безопасности и производительности шифрования
- [Балансировка нагрузки HTTP в Angie](../angie_http_load_balancing.md) — алгоритмы распределения запросов к upstream
