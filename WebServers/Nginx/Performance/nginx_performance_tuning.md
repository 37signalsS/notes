# Оптимизация производительности Nginx

**Актуально для:** Nginx 1.30.x (Stable) / 1.31.x (Mainline), Angie 1.10+ / 1.12.x, Linux Kernel 5.15+ / 6.x

---

## Определения

**Оптимизация производительности Nginx (Performance Tuning)** — комплексная инженерная процедура согласования архитектуры веб-сервера с возможностями оборудования (CPU, RAM, дисковая и сетевая подсистемы) и сетевого стека ядра Linux с целью максимизации пропускной способности (RPS/Throughput), минимизации сетевых задержек (Latency, TTFB) и исключения деградации сервиса при пиковых нагрузках.

**Рабочий процесс (Worker Process)** — непривилегированный процесс Nginx, выполняющий неблокирующий цикл обработки событий (Event Loop) и обслуживающий клиентские и upstream-соединения. Количество рабочих процессов определяется директивой `worker_processes`.

**Цикл обработки событий (Event Loop)** — ядро архитектуры Nginx. Рабочий процесс регистрирует файловые дескрипторы сокетов в системном мультиплексоре `epoll` (в Linux) и обрабатывает возникающие события ввода-вывода (готовность к чтению, записи, установлению соединения) без создания отдельных потоков или процессов на каждое соединение.

**SO_REUSEPORT (Директива `reuseport`)** — опция сокета в ядре Linux (начиная с ядра 3.9), позволяющая нескольким независимым процессам привязываться (`bind`) к одному и тому же IP-адресу и порту. Ядро операционной системы автоматически распределяет входящие TCP-соединения между слушающими сокетами воркеров на основе хэша 4-tuple/5-tuple пакета SYN.

**Zero-Copy** — технология передачи данных с блочного устройства (диска) напрямую в сетевой сокет через системный вызов `sendfile()`, минуя промежуточную буферизацию данных в адресном пространстве пользователя (user-space) и минимизируя переключения контекста процессора.

**kTLS (Kernel TLS)** — механизм ядра Linux, переносящий симметричное шифрование и дешифрование TLS-трафика (AES-GCM, ChaCha20-Poly1305) из пространства пользователя в ядро ОС. Позволяет объединить системный вызов `sendfile()` с TLS-шифрованием без промежуточного копирования данных в user-space.

**Асинхронный ввод-вывод и пулы потоков (`aio threads`)** — механизм делегирования потенциально блокирующих файловых операций чтения с диска в независимый пул потоков (`thread_pool`), предотвращающий остановку неблокирующего цикла событий воркера при промахах мимо кэша страниц ядра (Page Cache).

**Кэш открытых дескрипторов (`open_file_cache`)** — структура данных в оперативной памяти воркера, сохраняющая дескрипторы файлов, их размеры, метаданные inode и статус существования, что устраняет избыточные системные вызовы `open()`, `stat()` и `close()` при отдаче статических файлов.

**HTTP Keepalive и пулы соединений (Connection Pooling)** — механизм повторного использования одного TCP-соединения для последовательной передачи множества HTTP-запросов между клиентом и Nginx, а также между Nginx и upstream-серверами, устраняющий накладные расходы на тройное рукопожатие TCP (3-way handshake) и инициализацию TLS.

**Проблема «громоподобного стада» (Thundering Herd)** — ситуация, при которой по прибытии одного входящего соединения операционная система пробуждает все ожидающие процессы, но соединение достается только одному, а остальные тратят ресурсы CPU вхолостую. В современных ядрах Linux полностью решена на уровне `EPOLLEXCLUSIVE` и `SO_REUSEPORT`.

**Исчерпание эфемерных портов (Ephemeral Port Exhaustion)** — состояние операционной системы, при котором исчерпан диапазон локальных TCP-портов (`net.ipv4.ip_local_port_range`), используемых Nginx для исходящих соединений к бэкендам, обычно вызванное накоплением сокетов в состоянии `TIME_WAIT`.

**Очередь прослушивания (Listen Backlog)** — очередь ядра Linux для входящих TCP-соединений, завершивших 3-way handshake, но еще не извлеченных процессом Nginx с помощью системного вызова `accept()`.

---

## Основные концепции

### 1. Архитектура и процессная модель

Высокая производительность Nginx базируется на однопоточной событийно-ориентированной модели каждого рабочего процесса. В отличие от серверов с моделью process-per-request или thread-per-request, Nginx не расходует память на стек потока для каждого клиента и не страдает от дорогостоящих переключений контекста (context switches).

```text
                        ┌───────────────────────────────┐
                        │    Master Process (root)      │
                        │ Чтение конфига, bind сокетов  │
                        └───────┬───────────────┬───────┘
                                │ fork()        │ fork()
            ┌───────────────────▼──┐         ┌──▼───────────────────┐
            │  Worker Process #0   │         │  Worker Process #1   │
            │  epoll Event Loop    │         │  epoll Event Loop    │
            │  [CPU Core 0]        │         │  [CPU Core 1]        │
            └───────────┬──────────┘         └──────────┬───────────┘
                        │                               │
            ┌───────────▼──────────┐         ┌──────────▼───────────┐
            │ Клиенты & Upstreams  │         │ Клиенты & Upstreams  │
            └──────────────────────┘         └──────────────────────┘
```

#### Ключевые директивы процессной модели

- **`worker_processes auto;`**  
  Запускает по одному рабочему процессу на каждое доступное ядро CPU. Для выделенных bare-metal серверов это базовое значение.  
  > [!WARNING]
  > **Ловушка контейнеризации (Docker/Kubernetes) и CPU Throttling (CFS Quotas):**  
  > Внутри контейнера директива `auto` считывает физические ядра хоста (`/sys/devices/system/cpu/online`), игнорируя квоты cgroups. Если контейнеру выделен лимит `cpu: 2`, а хост имеет 64 ядра, Nginx запустит 64 воркера. При периоде планировщика `cpu.cfs_period_us = 100000` (100 мс) 64 воркера сожгут 200 мс процессорного времени за 3.1 мс, после чего ядро Linux заблокирует контейнер (throttling) на оставшиеся 96.9 мс периода. Это приводит к резким задержкам p99 и потере RPS.  
  > **Решение:** внутри контейнеров всегда жестко задавайте `worker_processes` равным целому числу выделенных ядер (например, `worker_processes 2;`), либо используйте скрипт авторасчета по квоте cgroups. Диагностика троттлинга: `cat /sys/fs/cgroup/cpu.stat | grep throttled`.
- **`worker_cpu_affinity auto;`**  
  Жестко привязывает каждый рабочий процесс к выделенному ядру CPU (affinity mask). Устраняет миграцию процессов между ядрами, сохраняет горячими процессорные кэши L1/L2/L3 и снижает латентность обработки пакетов.
- **`worker_connections` и математика емкости в Reverse Proxy**  
  Задает предельное число одновременных сетевых соединений (файловых дескрипторов в `epoll`), открываемых одним воркером.  
  *Расчет максимального числа параллельных запросов в режиме Reverse Proxy:*  
  $$\text{Max Concurrent Requests} = \frac{\text{worker\_processes} \times \text{worker\_connections}}{2} - \text{Overhead}$$  
  *Почему деление на 2:* на каждый входящий проксируемый запрос Nginx открывает 2 сокета — один для клиента, второй для upstream-бэкенда.  
  *Что составляет Overhead:*  
  1. Пул постоянных соединений к апстримам (`keepalive N`) и простаивающие клиентские сессии (`keepalive_timeout`).  
  2. Внутренние сокеты DNS-резолвера (`resolver`).  
  3. Дескрипторы сокетов отправки логов (`syslog:`) и открытых дисковых файлов.  
  Все они удерживают слоты в `worker_connections`. При исчерпании лимита Nginx сбрасывает новые запросы с ошибкой `worker_connections are not enough`.
- **`worker_rlimit_nofile`**  
  Задает жесткий лимит открытых файловых дескрипторов (`RLIMIT_NOFILE`) для рабочего процесса.  
  *Формула минимального значения:*  
  $$\text{worker\_rlimit\_nofile} \ge \text{worker\_connections} \times 2 + 1024$$  
  В production рекомендуется устанавливать от `65535` до `1048576` (при согласовании с лимитами ядра и systemd).
- **`worker_shutdown_timeout` и поведение сокетов при Reload**  
  Время принудительного завершения старых воркеров при бесшовной перезагрузке конфигурации (`nginx -s reload` / сигнал `SIGHUP`).  
  *Механика сокетов при reload:* Master-процесс валидирует конфиг, порождает новые рабочие процессы (создавая для них новые сокеты при `reuseport`), после чего отправляет старым воркерам сигнал `QUIT`. Старые воркеры закрывают слушающие сокеты и обслуживают уже принятые соединения вплоть до истечения `worker_shutdown_timeout` (рекомендуется `15s`–`30s`), после чего принудительно завершаются.  
  *Ограничение частых Reload:* При использовании `reuseport` в момент перезагрузки ядро распределяет новые SYN-пакеты между всеми открытыми сокетами, что при постоянных частых reload (например, в автоматических контроллерах) вызывает дисбаланс нагрузки. Для обновления бинарного файла Nginx на лету применяется [Zero-Downtime Binary Upgrade через `SIGUSR2`](../Core/nginx_build_from_source.md#4-бесшовное-обновление-бинарника-zero-downtime-upgrade).

---

### 2. Распределение соединений: `reuseport`, `multi_accept` и `accept_mutex`

Исторически распределение входящих сетевых соединений между воркерами Nginx вызывало блокировки и неравномерность нагрузки.

#### Сравнение механизмов обработки соединений

| Механизм | Принцип работы | Плюсы | Минусы / Ограничения |
| :--- | :--- | :--- | :--- |
| **`accept_mutex`** | Воркеры по очереди захватывают мьютекс в shared memory для вызова `accept()`. | Исключает thundering herd на старых ядрах Linux (< 3.9). | Создает жесткие блокировки на многоядерных машинах при высоком RPS. По умолчанию **выключен** (`off`) с Nginx 1.11.3. |
| **`multi_accept`** | По событию готовности сокета воркер извлекает все накопившиеся соединения в очереди за один проход. | Быстрее освобождает listen backlog ядра при взрывных всплесках трафика. | Без `reuseport` может привести к монополизации соединений одним воркером, пока остальные простаивают. |
| **`reuseport`** | Ядро создает отдельный слушающий сокет для каждого воркера (`SO_REUSEPORT`) и балансирует входящие SYN-пакеты. | Аппаратное/ядровое масштабирование, нулевые блокировки между процессами, идеальный RPS на 16+ ядрах. | Задается только один раз на конкретную пару `IP:port`. При reload возможны кратковременные перекосы распределения. |

```nginx
events {
    worker_connections 65535;
    use epoll;
    multi_accept on;
}

http {
    server {
        # Параметр reuseport указывается один раз для пары IP:port
        listen 80 default_server reuseport;
        listen 443 ssl default_server reuseport;
        ...
    }
}
```

> [!IMPORTANT]
> Параметр `reuseport` директивы `listen` доступен только в Linux (начиная с ядра 3.9) и DragonFly BSD. Если сконфигурировано несколько виртуальных хостов на одном порту, `reuseport` должен быть указан **строго в первом (или default_server) блоке `listen`**.

---

### 3. Сетевой стек, Zero-Copy и Kernel TLS (kTLS)

#### Взаимодействие `sendfile`, `tcp_nopush` и `tcp_nodelay`

При раздаче статических файлов и проксировании Nginx объединяет три системных механизма ядра:

1. **`sendfile on;`**  
   Активирует системный вызов `sendfile()`. Ядро передает данные напрямую из Page Cache в кольцевой буфер сетевого адаптера (TX ring buffer), исключая перенос данных в память процесса (`read()`) и последующую запись в сокет (`write()`).
2. **`sendfile_max_chunk 512k;`**  
   Ограничивает максимальный объем данных, передаваемый за один системный вызов `sendfile()`. Без этого параметра один быстрый клиент, скачивающий файл размером 10 ГБ, заблокирует рабочий процесс, вызвав рост задержек (latency spike) для остальных сотен клиентов на этом же воркере.
3. **`tcp_nopush on;`** (в Linux включает `TCP_CORK`)  
   Указывает ядру накапливать исходящие данные и отправлять полный HTTP-заголовок ответа вместе с началом содержимого файла в одном полном сетевом кадре (MTU), минимизируя оверхед на заголовки пакетов. Работает только совместно с `sendfile on;`.
4. **`tcp_nodelay on;`** (включает `TCP_NODELAY`)  
   Отключает алгоритм Нагла (Nagle's algorithm), предписывающий ожидать подтверждения (ACK) перед отправкой мелких порций данных. Критически важен для HTTP Keepalive, REST API, HTTP/2 и HTTP/3, где задержка отправки даже одного управляющего фрейма или заголовка приводит к росту задержки.
5. **`listen ... fastopen=256;` (TCP Fast Open, TFO)**  
   Позволяет клиентам начинать передачу данных (HTTP-запрос) непосредственно внутри первого пакета SYN, не дожидаясь завершения 3-way handshake. Экономит ровно один сетевой круговой интервал (1 RTT) до начала генерации ответа сервером. Требует включения в ядре Linux (`net.ipv4.tcp_fastopen = 3`). Параметр задает максимальную длину очереди незавершенных TFO-рукопожатий.

```text
Клиентский запрос ──► Nginx
                       │
                       ├─► [fastopen экономит 1 RTT при повторных подключениях]
                       ├─► [tcp_nopush накапливает заголовок + тело до размера MTU]
                       ├─► [sendfile передает данные Disk -> PageCache -> NIC]
                       └─► [tcp_nodelay немедленно сбрасывает финальный неполный пакет]
```

#### Kernel TLS (kTLS)

В стандартном TLS передача статики через `sendfile()` невозможна, так как данные должны быть зашифрованы в user-space библиотекой OpenSSL, что требует двух копирований (`диск -> RAM воркера -> сокет`).

kTLS решает эту проблему:
- Фаза рукопожатия (Handshake) и обмен ключами производятся в user-space (OpenSSL).
- Симметричные сессионные ключи шифрования передаются в ядро Linux через вызов `setsockopt(..., SOL_TLS, TLS_TX, ...)`.
- Ядро самостоятельно шифрует данные "на лету" при исполнении `sendfile()`.

**Требования для kTLS:**
- Ядро Linux 5.15+ (модуль `tls` загружен: `modprobe tls`).
- OpenSSL 3.0+ с флагом `enable-ktls` (или встроенный в дистрибутив).
- Nginx, собранный с поддержкой SSL (директива `ssl_conf_command Options KTLS;`).

```nginx
http {
    ssl_conf_command Options KTLS;

    server {
        listen 443 ssl reuseport;
        server_name cdn.example.com;

        sendfile on;
        sendfile_max_chunk 1m;
        tcp_nopush on;
        tcp_nodelay on;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
    }
}
```

---

### 4. Асинхронный ввод-вывод: `aio threads` и `directio`

Когда Nginx запрашивает файл с диска, и нужные страницы отсутствуют в оперативной памяти (промах Page Cache), системный вызов `read()` блокирует поток исполнения. В этот момент весь рабочий процесс замирает и не может обрабатывать сетевые события epoll тысяч других пользователей.

Решение — вынос дисковых операций в пулы системных потоков (Thread Pools):

```nginx
# В контексте main
thread_pool default threads=32 max_queue=65536;

http {
    # В контексте http, server или location
    aio threads=default;
    directio 8m;
    output_buffers 2 1m;
}
```

- **`thread_pool default threads=32 max_queue=65536;`** — создает пул из 32 потоков ОС для обработки дискового чтения с очередью задач.
- **`aio threads=default;`** — переводит чтение файлов в указанный пул потоков. Если данные уже в памяти, Nginx отдает их мгновенно через `sendfile`; если требуется обращение к накопителю — задача ставится в очередь потока, а воркер продолжает обрабатывать сеть.
- **`directio 8m;`** — для файлов размером $\ge$ 8 МБ включает прямой ввод-вывод (`O_DIRECT`), минуя Page Cache. Предотвращает вымывание полезного кэша оперативной памяти тяжелыми медиафайлами и резервными копиями.

---

### 5. Кэширование файловых дескрипторов (`open_file_cache`)

Каждое обращение к статическому файлу на диске требует вызовов `open()`, `fstat()` и последующего `close()`. При тысячах запросов в секунду это создает колоссальную нагрузку на VFS и блокировки inode ядра.

```nginx
http {
    open_file_cache          max=100000 inactive=30s;
    open_file_cache_valid    60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;
}
```

- **`max=100000`** — предельное число дескрипторов в памяти воркера. При переполнении наименее используемые элементы вытесняются по алгоритму LRU.
- **`inactive=30s`** — время жизни записи без обращений. Если за 30 секунд к файлу не обратились, дескриптор закрывается.
- **`open_file_cache_valid 60s`** — интервал времени, по истечении которого Nginx проверяет актуальность метаданных файла на диске (не изменился ли inode, размер или права).
- **`open_file_cache_min_uses 2`** — порог обращений за период `inactive`. Защищает кэш от засорения дескрипторами файлов, запрошенных однократно.
- **`open_file_cache_errors on`** — кэширует ошибки отсутствия файлов (`ENOENT`, `EACCES`), исключая повторные дисковые поиски при сканировании ботами несуществующих URI.

---

### 6. Keepalive и пулы соединений

Поддержание постоянных соединений снижает сетевой оверхед и задержку (RTT) за счет устранения повторных рукопожатий.

#### Keepalive с клиентами
- **`keepalive_timeout 65s;`** — время удержания соединения открытым в ожидании следующего запроса клиента.
- **`keepalive_requests 10000;`** — предельное количество запросов, обслуживаемых в рамках одного TCP-соединения перед его принудительным закрытием. В высоконагруженных окружениях дефолтное значение 1000 рекомендуется увеличивать до `10000`–`100000`, чтобы клиенты не тратили время на повторные TLS-хэндшейки.
- **`reset_timedout_connection on;`** — при наступлении таймаута сокет закрывается с отправкой TCP RST вместо стандартной 4-этапной процедуры FIN-ACK. Освобождает буферы сокета и дескриптор немедленно, не оставляя сокет в состоянии `FIN_WAIT1`/`FIN_WAIT2`.

#### Upstream Keepalive (пулинг к бэкендам)

> [!CAUTION]
> В Nginx Open Source постоянные соединения к `upstream` **выключены по умолчанию**. Если директива `keepalive` не задана явно в блоке `upstream`, Nginx работает с бэкендами по протоколу HTTP/1.0 и закрывает TCP-сокет после каждого запроса (`Connection: close`), что при высоком RPS приводит к мгновенному исчерпанию диапазона локальных портов (`Cannot assign requested address`).

```nginx
upstream app_backend {
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;

    # Максимальное количество неактивных соединений, сохраняемых в пуле каждого воркера
    keepalive 128;
    # Общее количество запросов через одно keepalive соединение
    keepalive_requests 10000;
    # Время простоя соединения в пуле
    keepalive_timeout 60s;
}

server {
    listen 80;

    location /api/ {
        proxy_pass http://app_backend;

        # Обязательные директивы для работы upstream keepalive:
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

### 7. Расчет буферов и потребления оперативной памяти

Неконтролируемое увеличение размеров буферов — главная причина аварийного завершения Nginx под нагрузкой механизмом ядра Linux OOM-Killer.

#### Формула оценки максимального потребления RAM

$$\text{RAM}_{\text{max}} = (\text{worker\_processes} \times \text{worker\_connections} \times \text{Буфер\_соединения}) + \text{Shared\_Memory} + \text{Page\_Cache}$$

Где базовый размер памяти на одно активное клиентское соединение складывается из:
- Сетевых буферов сокета ядра (`rmem`/`wmem`).
- Буферов заголовков: `client_header_buffer_size` (дефолт 1 КБ) + `large_client_header_buffers` (4 × 8 КБ).
- Буфера тела запроса: `client_body_buffer_size` (обычно 16–128 КБ).
- Буферов проксирования: `proxy_buffer_size` (4–8 КБ) + `proxy_buffers` (8 × 8 КБ = 64 КБ). Детальное управление поведением буферизации описано в руководстве по [буферизации и стримингу в Nginx](../Proxy/nginx_buffering_and_streaming.md).
- Буфера TLS: `ssl_buffer_size` (дефолт 16 КБ).

> [!TIP]
> **Оптимизация TTFB и RAM через `ssl_buffer_size`:**  
> Значение по умолчанию `ssl_buffer_size 16k;` оптимизировано под максимальную пропускную способность передачи больших файлов. Однако для интерактивных API и веб-страниц отправка блоков по 16 КБ задерживает передачу первого байта (TTFB), так как браузер не может начать разбор HTML/JSON до получения и расшифровки всего 16-килобайтного блока.  
> Установка `ssl_buffer_size 4k;` (или `8k;`) снижает TTFB на 20–40% и экономит до 12 КБ оперативной памяти на каждое активное TLS-соединение.

#### Оптимизация накладных расходов TLS-рукопожатий (Handshake Overhead)

1. **Dual-Stack сертификация (ECDSA + RSA):**  
   Асимметричные вычисления при TLS Handshake — одна из самых CPU-bound операций в веб-сервере. Сертификаты на эллиптических кривых ECDSA (P-256) в 3–5 раз быстрее вычисляют цифровую подпись и имеют в 3 раза меньший размер по сравнению с RSA-2048/4096. Настройка двух сертификатов в одном блоке `server` позволяет Nginx отдавать быстрый ECDSA современным клиентам и прозрачно использовать RSA для старых систем (детальная конфигурация представлена в [SSoT по виртуальным хостам TLS](../Security/TLS_SSL/nginx_tls_virtual_host_config.md#сценарий-1-production-виртуальный-хост-с-dual-stack-ecdsa--rsa-http2-и-http3)).
2. **Session Resumption в многонодовых кластерах (STEK):**  
   Директива `ssl_session_cache shared:SSL:...` кэширует сессии только в памяти одного хоста. Если кластер находится за L4-балансировщиком (Keepalived/IPVS), клиент при повторном подключении на соседнюю ноду вынужден проходить полное 2-RTT рукопожатие. Для ускорения соединений настраивается поддержка тикетов сессий (`ssl_session_tickets on;`) с единым файлом ключей `ssl_session_ticket_key`, синхронизируемым между всеми нодами кластера (детальная конфигурация представлена в [SSoT по глобальным параметрам TLS](../Security/TLS_SSL/nginx_tls_global_parameters.md#сценарий-2-высоконагруженный-кластер-с-ротацией-сессионных-тикетов-stek)).
3. **OCSP Stapling и DNS Resolver:**  
   Без директив `ssl_stapling on;` и `ssl_stapling_verify on;` браузер блокирует загрузку страницы на время выполнения отдельного синхронного HTTP-запроса к серверу удостоверяющего центра (100–400 мс). Включение Stapling позволяет Nginx прикреплять квитанцию валидности сертификата к Handshake. В блоке `http` обязательно объявляется локальный резолвер: `resolver 127.0.0.53 valid=300s ipv6=off; resolver_timeout 5s;`.

---

### 8. Отличия Nginx и Angie в контексте производительности

[Angie](../../Angie/angie_overview.md) — форк Nginx от оригинальной команды разработчиков, содержащий ряд архитектурных улучшений для производительности:

| Параметр / Функция | Nginx Open Source | Angie | Влияние на DevOps/SRE |
| :--- | :--- | :--- | :--- |
| **Балансировка `least_time`** | Только в коммерческом Nginx Plus | Доступна в Open Source (`least_time header\|last_byte`) | Направляет трафик на наименее загруженные бэкенды на основе реальной задержки RTT. |
| **Метрики производительности** | Базовый `stub_status` (7 метрик) | Модуль `status_zone` и встроенный эндпоинт `/metrics` | Нативный Prometheus-экспорт с разбивкой по виртуальным хостам и апстримам без сторонних демонов. |
| **Динамическое управление Upstream** | Требуется reload (`nginx -s reload`) | REST API для изменения весов и адресов на лету | Нулевой сброс кэшей и переинициализации воркеров при масштабировании бэкендов. |
| **Автоматический Upstream Keepalive** | Требует явной настройки `keepalive N` | Доступны оптимизированные дефолты и общие пулы | Меньше риск инцидентов с исчерпанием портов при первичной настройке. |

---

## Практические сценарии

### Сценарий 1: Производственный baseline для высоконагруженного Reverse Proxy и API Gateway

Конфигурация оптимизирована для серверов под нагрузкой от 20 000 до 100 000+ RPS. Включает `reuseport`, upstream keepalive, защиту от медленных клиентов и тюнинг TLS.

Файл: `/etc/nginx/nginx.conf`

```nginx
user nginx;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 1048576;
worker_shutdown_timeout 15s;
pcre_jit on;

events {
    worker_connections 65535;
    use epoll;
    multi_accept on;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # Логирование в буфер для минимизации дискового ввода-вывода
    log_format main_perf '$remote_addr - $remote_user [$time_local] "$request" '
                         '$status $body_bytes_sent "$http_referer" '
                         '"$http_user_agent" rt=$request_time uct="$upstream_connect_time" '
                         'uht="$upstream_header_time" urt="$upstream_response_time"';

    access_log /var/log/nginx/access.log main_perf buffer=64k flush=5s;
    error_log  /var/log/nginx/error.log warn;

    # Сетевой стек и Zero-Copy
    sendfile            on;
    sendfile_max_chunk  512k;
    tcp_nopush          on;
    tcp_nodelay         on;

    # Пулы соединений и таймауты
    keepalive_timeout         65s;
    keepalive_requests        10000;
    reset_timedout_connection on;
    client_body_timeout       10s;
    client_header_timeout     10s;
    send_timeout              10s;

    # Буферы клиентских запросов
    client_body_buffer_size      64k;
    client_max_body_size         16m;
    client_header_buffer_size    1k;
    large_client_header_buffers  4 8k;

    # Оптимизация TLS
    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_ciphers               TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache         shared:SSL:50m;
    ssl_session_timeout       1d;
    ssl_session_tickets       off;
    ssl_buffer_size           4k;

    # Пул бэкендов с постоянными соединениями
    upstream backend_cluster {
        zone backend_zone 64k;
        server 10.0.10.11:8080 max_fails=3 fail_timeout=10s;
        server 10.0.10.12:8080 max_fails=3 fail_timeout=10s;

        keepalive 256;
        keepalive_requests 10000;
        keepalive_timeout 60s;
    }

    server {
        listen 80 default_server reuseport;
        listen 443 ssl default_server reuseport;
        server_name api.example.com;

        ssl_certificate     /etc/ssl/certs/api.example.com.crt;
        ssl_certificate_key /etc/ssl/private/api.example.com.key;

        location / {
            proxy_pass http://backend_cluster;

            # Upstream keepalive
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            # Заголовки проксирования
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Буферизация ответов
            proxy_buffering           on;
            proxy_buffer_size         8k;
            proxy_buffers             16 8k;
            proxy_busy_buffers_size   16k;
            proxy_connect_timeout     3s;
            proxy_read_timeout        10s;
            proxy_send_timeout        10s;
        }

        # Эндпоинт мониторинга для Prometheus / Zabbix
        location /stub_status {
            stub_status;
            access_log off;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }
    }
}
```

---

### Сценарий 2: Высокопроизводительная раздача медиа и статики (Zero-Copy, Thread Pools, kTLS)

Специализированная конфигурация для статических хранилищ, CDN-узлов и отдачи крупных файлов.

```nginx
# Определение пула потоков на уровне main
thread_pool static_pool threads=64 max_queue=131072;

http {
    # Активация kTLS в OpenSSL
    ssl_conf_command Options KTLS;

    server {
        listen 443 ssl reuseport;
        server_name static.example.com;
        root /var/www/static;

        ssl_certificate     /etc/ssl/certs/static.crt;
        ssl_certificate_key /etc/ssl/private/static.key;

        # Zero-Copy и kTLS
        sendfile            on;
        sendfile_max_chunk  1m;
        tcp_nopush          on;
        tcp_nodelay         on;

        # Асинхронный I/O и обход Page Cache для больших файлов
        aio                 threads=static_pool;
        directio            8m;
        output_buffers      2 1m;

        # Кэш дескрипторов
        open_file_cache          max=200000 inactive=60s;
        open_file_cache_valid    120s;
        open_file_cache_min_uses 1;
        open_file_cache_errors   on;

        location / {
            try_files $uri =404;
            expires 30d;
            add_header Cache-Control "public, immutable";
            access_log off;
        }
    }
}
```

---

### Сценарий 3: Тюнинг ядра Linux под Nginx (`sysctl.d` и `systemd`)

Настройка операционной системы для исключения узких мест в очередях ядра, сокетах и лимитах дескрипторов.

#### Шаг 1: Конфигурация параметров ядра в `/etc/sysctl.d/99-nginx-performance.conf`

```ini
# Максимальный размер очереди невыбранных соединений listen() (должен соответствовать или превышать backlog в listen)
net.core.somaxconn = 65535

# Очередь входящих пакетов от сетевой карты до стека IP
net.core.netdev_max_backlog = 65535

# Максимальное количество сокетов, ожидающих завершения 3-way handshake (SYN-очередь)
net.ipv4.tcp_max_syn_backlog = 65535

# Безопасное переиспользование сокетов в состоянии TIME_WAIT для исходящих соединений (требует tcp_timestamps=1)
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_timestamps = 1

# Расширение диапазона эфемерных портов для исходящих запросов к upstream
net.ipv4.ip_local_port_range = 1024 65535

# Сокращение времени удержания сокета в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Интервалы keepalive на уровне ядра Linux
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5

# Отключение медленного старта после простоя соединения (критично для стабильного Keepalive в Web/API)
net.ipv4.tcp_slow_start_after_idle = 0

# Буферы приема и отправки данных сокетов (автоподстройка TCP и жесткие лимиты: 16 МБ max)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Алгоритм контроля перегрузки BBR и дисциплина очередей FQ
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Включение TCP Fast Open (TFO) для входящих и исходящих соединений (3 = client + server)
net.ipv4.tcp_fastopen = 3

# Глобальные лимиты открытых файлов на уровне ядра ОС
fs.file-max = 2097152
fs.nr_open = 2097152
```

> [!WARNING]
> Никогда не включайте параметр `net.ipv4.tcp_tw_recycle = 1`. Данный параметр нарушает работу клиентов, находящихся за общим корпоративным или провайдерским NAT (drop входящих SYN-пакетов из-за несовпадающих timestamps). В ядре Linux начиная с версии 4.12 параметр `tcp_tw_recycle` **полностью удален**.

#### Шаг 2: Настройка лимитов службы systemd

Файл: `/etc/systemd/system/nginx.service.d/override.conf`

```ini
[Service]
LimitNOFILE=1048576
LimitNPROC=524288
LimitMEMLOCK=infinity
# Защита от OOM-Killer: меньший приоритет на уничтожение процессом ядра
OOMScoreAdjust=-500
```

#### Шаг 3: Обход отслеживания соединений Netfilter (Conntrack Bypass через NOTRACK)

На серверах с трафиком от 50 000 до 200 000+ RPS подсистема `conntrack` ядра Linux становится узким местом: переполняется таблица состояний (`nf_conntrack: table full, dropping packet`), что приводит к отбрасыванию легитимных SYN-пакетов даже при низкой утилизации CPU.

Для публичных портов веб-сервера (80, 443) отслеживание состояний отключается в таблице `raw`:

```bash
# Для iptables:
sudo iptables -t raw -A PREROUTING -p tcp -m multiport --dports 80,443 -j NOTRACK
sudo iptables -t raw -A OUTPUT -p tcp -m multiport --sports 80,443 -j NOTRACK

# Для nftables (/etc/nftables.conf):
# table ip raw {
#     chain prerouting {
#         type filter hook prerouting priority raw; policy accept;
#         tcp dport { 80, 443 } notrack
#     }
#     chain output {
#         type filter hook output priority raw; policy accept;
#         tcp sport { 80, 443 } notrack
#     }
# }
```

#### Шаг 4: Применение параметров и валидация

```bash
# Применение параметров ядра без перезагрузки сервера
sysctl --system
# → Applying /etc/sysctl.d/99-nginx-performance.conf ...

# Применение изменений systemd
systemctl daemon-reload
systemctl restart nginx

# Проверка эффективных лимитов работающего master-процесса
cat /proc/$(pgrep -o nginx)/limits | grep "Max open files"
# → Max open files            1048576              1048576              files
```

---

### Сценарий 4: Привязка прерываний сетевой карты (IRQ), RPS/RFS и NUMA-тюнинг

На многопроцессорных bare-metal серверах с архитектурой NUMA (Non-Uniform Memory Access) обращение процессора к оперативной памяти соседнего сокета через шину межпроцессорного соединения (QPI/UPI) увеличивает задержки.

#### 1. Определение топологии NUMA
```bash
# Просмотр узлов NUMA и привязки CPU
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 4 5 6 7
# → node 1 cpus: 8 9 10 11 12 13 14 15

# Определение, к какому NUMA-узлу подключена сетевая карта
cat /sys/class/net/eth0/device/numa_node
# → 0
```

#### 2. Конфигурация привязки воркеров и прерываний
Если сетевой интерфейс `eth0` подключен к узлу NUMA 0, воркеры Nginx привязываются к ядрам узла 0, либо сетевые очереди распределяются равномерно:

```nginx
# Привязка 8 воркеров к ядрам 0-7 (NUMA node 0)
worker_processes 8;
worker_cpu_affinity 00000001 00000010 00000100 00001000 00010000 00100000 01000000 10000000;
```

Для распределения обработки сетевых пакетов на уровне ядра Linux без выделенного демона `irqbalance` настраивается RPS (Receive Packet Steering):

```bash
# Включение распределения очередей RX интерфейса eth0 по ядрам 0-7
for file in /sys/class/net/eth0/queues/rx-*/rps_cpus; do
    echo "000000ff" | sudo tee $file
done
# → 000000ff
```

---

### Сценарий 5: SRE-методология нагрузочного тестирования и поиска узких мест

Методика нагрузочного тестирования позволяет выявить предел производительности сервера до ввода в эксплуатацию.

```bash
# 1. Нагрузочное тестирование через wrk (HTTP/1.1 Keepalive, 12 потоков, 1000 соединений, 60 секунд)
wrk -t12 -c1000 -d60s --latency http://10.0.10.10/api/v1/health
# → Running 1m test @ http://10.0.10.10/api/v1/health
# →   12 threads and 1000 connections
# →   Requests/sec:  98421.34
# →   Latency   50%:   1.24ms
# →   Latency   99%:   4.15ms

# 2. Мониторинг отброшенных соединений в очередях ядра во время теста
netstat -s | grep -E "listen|overflowed"
# → 0 times the listen queue of a socket overflowed
# → 0 SYNs to LISTEN sockets dropped

# 3. Просмотр переполнения очереди сокета Nginx
ss -lnt '( sport = :80 or sport = :443 )'
# → State      Recv-Q  Send-Q   Local Address:Port
# → LISTEN     0       65535    0.0.0.0:80
# Примечание: Если Recv-Q > 0 и приближается к Send-Q — Nginx не успевает вызывать accept(),
# требуется включить reuseport или увеличить worker_processes.

# 4. Профилирование горячих функций ядра и Nginx через perf
perf top --pid=$(pgrep -d',' nginx)
# Позволяет выявить накладные расходы на копирование памяти, спинлоки или вызовы regex.
```

---

## Операции и команды

| Операция | Команда | Ожидаемый результат / Интерпретация |
| :--- | :--- | :--- |
| **Синтаксическая проверка** | `nginx -t` | `nginx: configuration file /etc/nginx/nginx.conf test is successful` |
| **Бесшовное применение конфигурации** | `nginx -s reload` | Обновление воркеров без сброса активных клиентских сессий. |
| **Проверка статуса воркеров и ядер** | `ps -eo pid,psr,comm \| grep nginx` | Распределение воркеров по отдельным ядрам (`PSR` уникален для каждого воркера). |
| **Проверка лимита открытых дескрипторов** | `cat /proc/$(pgrep -o nginx)/limits \| grep "open files"` | Значение `Max open files` равно параметру `worker_rlimit_nofile` (например, `1048576`). |
| **Мониторинг сокетов в реальном времени** | `ss -s` | Сводка: `TCP: estab N, closed M, timewait K`. Контроль отсутствия взрывного роста `timewait`. |
| **Проверка поддержки kTLS в ядре** | `cat /proc/crypto \| grep -i tls` | Наличие драйвера/алгоритма `tls` (`driver: tls-generic` или аппаратный offload). |
| **Проверка модуля ядра kTLS** | `lsmod \| grep tls` | Вывод: `tls 118784 0` (модуль загружен в ядро). |
| **Диагностика системных вызовов sendfile** | `strace -c -p $(pgrep -o nginx) -e trace=sendfile,writev,epoll_wait` | Статистика: преобладание `sendfile` над `writev` при раздаче статических файлов. |
| **Опрос встроенного статуса** | `curl -s http://127.0.0.1/stub_status` | `Active connections: 450 \n server accepts handled requests \n 150000 150000 3500000` |
| **Анализ сброшенных SYN-пакетов** | `nstat -az TcpExtListenOverflows TcpExtListenDrops` | Значения счетчиков должны быть равны `0` или не увеличиваться во времени. |

---

## Устранение неполадок

### 1. 100% CPU на одном или нескольких воркерах

**Симптом:** Утилита `top`/`htop` фиксирует 100% утилизацию ядра одним процессом Nginx, при этом сетевой трафик умеренный.

**Причины и диагностика:**
1. **Катастрофический возврат в регулярных выражениях (ReDoS):**
   Неоптимизированные конструкции в `location ~` или `rewrite` приводят к зависанию парсера PCRE.
   ```bash
   # Проверка активности компилятора PCRE JIT
   grep -i pcre_jit /etc/nginx/nginx.conf
   # Решение: включить pcre_jit on; оптимизировать регулярные выражения, заменить на префиксные location (^~).
   ```
2. **Динамическое сжатие Gzip на высоких уровнях:**
   Директива `gzip_comp_level` со значениями 6–9 перегружает процессор.  
   *Решение:* Снизить уровень до `1`–`3` для динамических ответов, либо использовать статическое предварительное сжатие gzip/brotli/zstd в CI/CD. Подробнее см. в [оптимизации сжатия в Nginx](./nginx_compression.md).

---

### 2. Ошибка «worker_connections are not enough»

**Симптом:** В `/var/log/nginx/error.log` фиксируются записи вида:  
`2026/10/16 12:00:00 [alert] 12345#12345: 65535 worker_connections are not enough while connecting to upstream`

**Причины и диагностика:**
1. Превышен лимит одновременных соединений на процесс. На каждый проксируемый запрос тратится два дескриптора.
2. Медленные бэкенды долго не отвечают, удерживая соединения открытыми.
3. Отсутствует upstream keepalive, из-за чего соединения скапливаются в очереди.

**Решение:**
1. Увеличить `worker_connections` в секции `events {}` и `worker_rlimit_nofile` в секции `main`.
2. Настроить пулинг `keepalive` в блоках `upstream`.
3. Уменьшить защитные таймауты `proxy_connect_timeout` (2–3 секунды) и `proxy_read_timeout` (10–15 секунд).

---

### 3. Ошибка «connect() failed (99: Cannot assign requested address)»

**Симптом:** При обращении к upstream Nginx возвращает ошибку HTTP 502, а в `error.log` появляется `Cannot assign requested address`.

**Причина:** Исчерпание пула локальных эфемерных TCP-портов. Nginx закрывает соединение к бэкенду после каждого запроса, сокеты переходят в состояние `TIME_WAIT` на 60 секунд, занимая кортеж `(src_ip, src_port, dst_ip, dst_port)`.

**Решение:**
1. **Обязательно включить upstream keepalive** в `upstream` (`keepalive 128;`) и добавить `proxy_http_version 1.1; proxy_set_header Connection "";`.
2. Расширить пул локальных портов в `/etc/sysctl.conf`:
   ```bash
   sysctl -w net.ipv4.ip_local_port_range="1024 65535"
   sysctl -w net.ipv4.tcp_tw_reuse=1
   ```
3. При необходимости взаимодействия с одним апстримом на экстремальных нагрузках — объявить в upstream несколько локальных IP-адресов бэкенда или настроить привязку через директиву `proxy_bind`.

---

### 4. Отказ в установке соединений («Connection refused» / дропы SYN-пакетов)

**Симптом:** Клиенты жалуются на обрывы соединений при всплеске посещаемости, в метриках растут тайм-ауты подключения.

**Диагностика:**
```bash
# Проверка счетчика переполнений очереди прослушивания
netstat -s | grep "listen queue"
# → 14502 times the listen queue of a socket overflowed
```

**Причина:** Значение системного вызова `listen(..., backlog)` в Nginx меньше интенсивности входящих соединений, либо параметр ядра `net.core.somaxconn` ограничивает очередь.

**Решение:**
1. Синхронизировать директиву `listen` с параметром ядра:
   ```nginx
   listen 443 ssl backlog=65535 reuseport;
   ```
2. Установить в sysctl:
   ```bash
   sysctl -w net.core.somaxconn=65535
   sysctl -w net.ipv4.tcp_max_syn_backlog=65535
   ```

---

### 5. Рост задержек (Latency Spikes / TTFB) при отдаче статики

**Симптом:** При высокой нагрузке время отдачи статических файлов скачкообразно вырастает с 2 мс до сотен миллисекунд.

**Диагностика:**
```bash
# Просмотр нагрузки на диск и времени ожидания I/O
iostat -xz 1
# Если %util > 80% или await > 10ms, дисковая подсистема перегружена
```

**Решение:**
1. Подключить пул потоков `thread_pool default threads=32 max_queue=65536;` и активировать `aio threads=default;`.
2. Включить `directio 8m;`, чтобы файлы размером более 8 МБ не вытесняли горячий кэш страниц из оперативной памяти.
3. Проверить параметры `open_file_cache`: кэширование дескрипторов предотвратит лишние дисковые обращения `stat()`.

---

### 6. OOM-Killer аварийно завершает Nginx

**Симптом:** В системном логе `dmesg` или `journalctl -k` появляется запись:  
`Out of memory: Killed process 12345 (nginx) total-vm:..., anon-rss:...`

**Причина:** Суммарный объем буферов соединений (`client_body_buffer_size`, `proxy_buffers`, `large_client_header_buffers`), помноженный на число активных клиентов, превысил физический объем доступной памяти сервера.

**Решение:**
1. Рассчитать память по формуле из раздела 7 и оптимизировать размеры буферов.
2. Установить директиву `proxy_max_temp_file_size` для предотвращения бесконтрольного роста временных буферов.
3. Снизить защитный коэффициент завершения процесса через systemd: `OOMScoreAdjust=-500`.

---

## Рекомендации

1. **Используйте `worker_processes auto;` и `worker_cpu_affinity auto;`** на выделенных серверах для минимизации миграции потоков между ядрами CPU и утилизации процессорных кэшей.
2. **Включайте `reuseport` на высоконагруженных сокетах** с входящим потоком более 10 000 RPS. Это исключает межпроцессорные блокировки и обеспечивает равномерное распределение трафика ядром.
3. **Всегда активируйте `keepalive` в блоках `upstream`** для микросервисов и API-шлюзов. Это предотвращает исчерпание диапазона портов и сокращает латентность запроса на время сетевого рукопожатия TCP и TLS.
4. **Не оставляйте `proxy_http_version` в значении по умолчанию (1.0).** Для поддержания постоянных соединений с бэкендами обязательна связка `proxy_http_version 1.1; proxy_set_header Connection "";`.
5. **Используйте системные пулы потоков (`aio threads`)** при отдаче статики с накопителей. Это устраняет блокировки цикла событий epoll при промахах Page Cache.
6. **Оптимизируйте TTFB через `ssl_buffer_size 4k;`** на интерактивных веб-ресурсах и API, что ускоряет дешифрование первого кадра браузером и снижает потребление RAM.
7. **Буферизуйте запись журнала доступа (`access_log ... buffer=64k flush=5s;`).** Синхронная запись логов на каждый запрос при 50 000 RPS способна полностью парализовать дисковую подсистему.
8. **Контролируйте параметры ядра Linux.** Любые настройки Nginx бесполезны, если `net.core.somaxconn` или `fs.file-max` блокируют входящие очереди и дескрипторы на уровне ОС.
9. **Отключайте `tcp_slow_start_after_idle`** в sysctl для предотвращения сброса окна перегрузки (congestion window) при периодических паузах между запросами в рамках одного Keepalive-соединения.
10. **Проводите нагрузочное тестирование перед внедрением.** Используйте утилиты `wrk` или `k6`, профилируйте сервер утилитой `perf` и отслеживайте метрики очередей `ss -lnt` и `nstat`.

---

## Дополнительная информация

### Связанные файлы в базе знаний

- **[Шейпинг трафика, Rate Limiting и защита от перегрузок (Backpressure)](./nginx_traffic_shaping_and_overload_protection.md)** — алгоритм Leaky Bucket (`burst`, `delay`, `nodelay`), лимиты соединений `limit_conn`, амортизация медленных клиентов и защита емкости бэкендов (`max_conns`, `queue`).
- **[Глобальные параметры TLS](../Security/TLS_SSL/nginx_tls_global_parameters.md)** — глубокая оптимизация сессионного кэша, синхронизация тикетов STEK в кластере и параметры OCSP Stapling.
- **[Конфигурация виртуальных хостов TLS](../Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — настройка Dual-Stack сертификатов (ECDSA + RSA), 0-RTT Early Data и разгрузка CPU.
- **[Анализ логов и декомпозиция таймингов](../Operations/nginx_log_analysis.md)** — высокопроизводительное логирование (`if=`, syslog UDP/UNIX), локализация задержек через `$request_time` и `$upstream_connect_time`.
- **[Интеграция с бэкендами: сокеты UDS против TCP](../Core/Location/integration_examples.md)** — сравнение производительности Unix Domain Sockets и TCP Loopback `127.0.0.1`.
- **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)** — архитектура мастер- и воркер-процессов, системные службы systemd, базовые директивы.
- **[Обзор Nginx](../Core/nginx_overview.md)** — общая процессная модель, роли веб-сервера, обработка сигналов.
- **[Буферизация и стриминг в Nginx](../Proxy/nginx_buffering_and_streaming.md)** — детальный разбор работы директив `proxy_buffering`, временных файлов и стриминга (SSE/gRPC).
- **[Оптимизация сжатия (Gzip, Brotli, Zstandard)](./nginx_compression.md)** — динамическое и статическое предварительное сжатие, уровни компрессии, разгрузка CPU.
- **[Конфигурация HTTP/2 и HTTP/3](./nginx_http_versions.md)** — многопоточность, мультиплексирование потоков, QUIC и `quic_bpf` с `reuseport`.
- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — пошаговый поиск причин деградации сервиса, дампы памяти и методология локализации сбоев.
- **[Кэширование в Nginx и Angie](./Caching/overview.md)** — архитектура серверного и клиентского кэширования, разделяемая память.
- **[Микрокэширование в Nginx](./Caching/microcaching.md)** — защита upstream-серверов от перегрузки кратковременным кэшированием на `tmpfs`.
- **[Настройка параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md)** — глубокий системный тюнинг файловых и сетевых параметров ядра Linux.
- **[Оптимизация TCP в Linux: Обзор](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — алгоритмы контроля перегрузки BBR/CUBIC, расчет BDP, настройка qdisc и очередей сетевых адаптеров.
- **[Обзор Angie](../../Angie/angie_overview.md)** — функционал форка Angie: динамические апстримы, встроенные метрики Prometheus и балансировка `least_time`.
