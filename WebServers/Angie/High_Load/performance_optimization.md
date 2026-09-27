# Оптимизация производительности Angie

## Определения

**Оптимизация производительности (Performance Optimization)** — комплекс конфигурационных и архитектурных мер, направленных на повышение пропускной способности сервера (RPS — Requests Per Second) и минимизацию задержек (Latency, TTFB — Time To First Byte) при наиболее эффективном использовании аппаратных ресурсов (CPU, RAM, Disk I/O, Network).

**Inflight Requests** — запросы, которые уже приняты сервером и находятся в процессе обработки, но ответ по которым еще не отправлен полностью. Учет этого показателя критичен для предотвращения перегрузки медленных бэкендов.

**Kernel TLS (kTLS)** — технология переноса операций симметричного шифрования TLS непосредственно в ядро ОС, что позволяет использовать механизм `sendfile()` для передачи данных по HTTPS без лишних копирований между пространством ядра и пользователя.

**Событийно-ориентированная модель (Event-driven Architecture)** — архитектура, при которой поток обработки не блокируется на операциях ввода-вывода, а регистрирует обратные вызовы (callbacks) на события (прием данных, закрытие соединения). В Angie реализована через неблокирующий event loop на основе `epoll` (Linux), `kqueue` (BSD/macOS) или `io_uring` (Linux 5.1+).

**Zero-Copy** — технология передачи данных без лишнего копирования между пространством ядра и пользовательским пространством. В Angie реализуется через системные вызовы `sendfile()`, `splice()`, `tee()`.

**Head-of-Line Blocking (HOL)** — явление, при котором один медленный запрос блокирует отправку всех последующих запросов в рамках одного соединения (в HTTP/2) или одной очереди. В контексте Angie HOL может возникать на уровне worker'а при использовании HTTP/2 или при блокировке воркера тяжелым запросом.

**Thundering Herd** — эффект массового одновременного обращения множества клиентов к одному ресурсу (например, при истечении TTL кэша), что создает пиковую нагрузку на бэкенд. В Angie предотвращается через `proxy_cache_lock` и распределение запросов во времени.

**Пропускная способность (Throughput)** — количество запросов или объем данных, обработанных сервером за единицу времени, обычно измеряемый в RPS (Requests Per Second) или Mbps.

**Задержка (Latency)** — время обработки одного запроса, обычно измеряемое как TTFB (Time To First Byte) или полное время ответа (TTLB).

---

## Базовые концепции

### Архитектура процессов Angie

Angie наследует событийно-ориентированную многопроцессную модель Nginx, расширенную уникальными возможностями:

1.  **Master-процесс:** Читает конфигурацию, управляет воркерами, выполняет привилегированные операции (bind, setuid). Отвечает за грациозную перезагрузку (`reload`) без остановки обслуживания.
2.  **Worker-процессы:** Обрабатывают соединения в неблокирующем event loop. Количество обычно равно числу ядер CPU (`worker_processes auto;`). Каждый воркер обрабатывает тысячи соединений в одном потоке, что исключает накладные расходы на контекстные переключения.
3.  **Разделяемая память (Shared Memory):** Используется для зон (`zone`), кэша (`proxy_cache`), состояний балансировки и метрик. Размер ограничен параметром `worker_shm_zone_size` и доступной памятью.

### Событийный цикл и I/O мультиплексирование

Angie использует неблокирующий event loop для обработки тысяч соединений в одном потоке:

- **epoll (Linux):** Стандарт для современных Linux-систем. Поддерживает edge-triggered (ET) и level-triggered (LT) режимы. ET-режим требует аккуратной обработки (чтение до `EAGAIN`), но обеспечивает минимальные накладные расходы.
- **kqueue (BSD/macOS):** Аналог epoll в системах семейства BSD. Поддерживает дополнительные события (vnode, process).
- **io_uring (Linux 5.1+):** Новейший интерфейс асинхронного I/O, позволяющий отложить операции чтения/записи и получать уведомления через очередь. В Angie пока не используется на уровне конфигурации, но может быть задействован через системные вызовы в сторонних модулях.

**Важность:** Переключение на `io_uring` может дать прирост 10-20% при работе с дисками, но требует Linux 5.1+ и поддержки в ядре.

### Уникальные возможности Angie для оптимизации

1.  **Продвинутая балансировка (`least_time`):** Выбор бэкенда не просто по количеству соединений, а по реальному времени отклика с учетом незавершенных запросов (`inflight`).
2.  **Эффективный QUIC (eBPF):** Использование `quic_bpf` для привязки UDP-пакетов к конкретным воркерам, что обеспечивает стабильность сессий HTTP/3 даже при `reload` конфигурации.
3.  **Нативное сжатие Zstd:** Встроенная поддержка алгоритма Zstandard, обеспечивающего лучший баланс между CPU и степенью сжатия по сравнению с Gzip/Brotli.
4.  **Кластерная осведомленность:** Возможность синхронизации состояний (лимиты, сессии) между узлами кластера для предотвращения "локальных" перегрузок.
5.  **Нативная наблюдаемость:** Поддержка OpenTelemetry (OTel) и встроенный экспорт в Prometheus без накладных расходов на sidecar-контейнеры.

### Управление памятью и NUMA

**Transparent Huge Pages (THP):** Включен по умолчанию в большинстве дистрибутивов, но может вызывать фрагментацию памяти и задержки (compaction pauses) под нагрузкой. Для высоконагруженных систем рекомендуется отключить THP:

```bash
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```

**Huge Pages:** Для систем с большим кэшем Angie (например, `proxy_cache` на десятки GB) использование фиксированных hugepages (2MB или 1GB) может снизить нагрузку на TLB (Translation Lookaside Buffer).

**NUMA (Non-Uniform Memory Access):** В многосокетных серверах память разделена по узлам. Для предсказуемой производительности worker'ы Angie должны быть привязаны к ядрам того же NUMA-узла, где находится память, используемая модулями. Это достигается через `numactl` или `worker_cpu_affinity` в сочетании с настройками `systemd`.

### Алгоритмы ограничения скорости (Rate Limiting)

Angie реализует алгоритм **Leaky Bucket (Bucket Tokens)** через директивы `limit_req_zone` и `limit_conn_zone`. Понимание алгоритма критично для правильной настройки:

- **`rate`:** Определяет скорость "протекания" ведер (запросов в секунду). Запросы, превышающие эту скорость, сталкиваются с ограничением.
- **`burst`:** Размер "ведра", который позволяет принять кратковременный всплеск запросов.
- **`nodelay`:** Принудительная обработка burst-запросов без задержки, но с риском исчерпания ресурсов.

**Kingman-эффект:** При утилизации ресурсов >85% среднее время ожидания растет экспоненциально. Поэтому `limit_req` настраивается с запасом 20-30% от реальной емкости бэкенда.

---

## Практические сценарии

### Сценарий 1: Системный тюнинг (sysctl)

Максимальная производительность Angie невозможна без настройки параметров ядра Linux, управляющих сетевым стеком.

**Пример конфигурации `/etc/sysctl.d/90-angie.conf`:**

```bash
# Увеличение очереди прослушиваемых сокетов (согласовать с backlog в Angie)
net.core.somaxconn = 65535

# Расширение диапазона эфемерных портов для исходящих соединений
net.ipv4.ip_local_port_range = 1024 65535

# Быстрое переиспользование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Запрет сброса TCP Slow Start после простоя (критично для Keep-Alive API)
net.ipv4.tcp_slow_start_after_idle = 0

# Использование алгоритма BBRv3 для управления перегрузкой
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# RPS/RFS: распределение сетевых прерываний по ядрам
net.core.netdev_max_backlog = 250000

# Busy Poll: снижение задержки при малой нагрузке
net.core.busy_poll = 50
net.core.busy_read = 50

# Максимальное количество открытых файлов в системе
fs.file-max = 2097152

# Отключение THP для предотвращения задержек compaction
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```

Применение: `sysctl --system`. Подробнее см. в разделе **[Тюнинг параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md)**.

---

### Сценарий 2: Многопоточность и асинхронный I/O

Для раздачи тяжелого контента или работы с медленными дисками необходимо выносить блокирующие операции в отдельные пулы потоков.

```nginx
# В основном контексте (main)
thread_pool dio_pool threads=32 max_queue=65536;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    sendfile on;
    tcp_nopush on;
    
    # Асинхронный ввод-вывод через пулы потоков
    aio threads=dio_pool;
    
    # Ограничение размера чанка при sendfile (предотвращает забивание шины данных одним воркером)
    sendfile_max_chunk 1m;

    server {
        location /static/video/ {
            # Использование Direct I/O для обхода Page Cache при работе с большими файлами
            directio 8m;
            aio threads=dio_pool;
        }
    }
}
```

**Валидация:**
```bash
# Проверка использования пулов потоков
ss -ltnp | grep angie
# → workers должны слушать порт, потоки dio_pool не отражаются в ss

# Мониторинг очереди пула (через Prometheus или strace)
strace -p $(pgrep angie | head -1) -e trace=io_getevents
```

---

### Сценарий 3: Оптимизация TLS через Kernel TLS (kTLS)

kTLS радикально снижает нагрузку на CPU при передаче данных через HTTPS.

```nginx
http {
    # Требует поддержки в ядре (modprobe tls) и OpenSSL 3.0+
    ssl_conf_command Options +KTLS;

    server {
        listen 443 ssl;
        ssl_certificate /etc/angie/ssl/fullchain.pem;
        ssl_certificate_key /etc/angie/ssl/privkey.pem;

        # kTLS работает максимально эффективно в связке с sendfile
        sendfile on;
        tcp_nopush on;
    }
}
```

**Валидация:**
```bash
# Проверка поддержки kTLS в ядре
modprobe tls
ls /sys/kernel/tls/
# → /sys/kernel/tls/  (наличие директории означает поддержку)

# Проверка через openssl
openssl s_client -connect localhost:443 -tls1_3
# → В выводе должен присутствовать "KTLS" или "Cipher: TLS_AES_256_GCM_SHA384"

# Сравнение CPU до/после kTLS
pidstat -p $(pgrep angie) 1 5
# → us% должен снизиться на 20-40% при heavy HTTPS трафике
```

---

### Сценарий 4: Тюнинг HTTP/3 и eBPF

В отличие от Nginx, Angie использует eBPF для сохранения QUIC-сессий при перезагрузке процесса.

```nginx
# В основном контексте (main)
quic_bpf on;

http {
    server {
        listen 443 quic reuseport;
        http3 on;

        # Generic Segmentation Offload для UDP (снижает нагрузку на CPU)
        quic_gso on;
        
        # Информирование клиента о поддержке HTTP/3
        add_header Alt-Svc 'h3=":443"; ma=86400';
    }
}
```

**Валидация:**
```bash
# Проверка доступности QUIC
curl -I --http3-only https://example.com/
# → HTTP/3 200

# Проверка UDP порта
ss -u -l | grep :443
# → UNCONN 0 0 *:quic *:*

# Проверка логов QUIC ошибок
grep -i "quic" /var/log/angie/error.log
# → [crit] ... quic_bpf not supported (если ядро старое)
```

Подробнее: **[Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../../Nginx/Performance/nginx_http_versions.md)**.

---

### Сценарий 5: Продвинутая балансировка и плавный старт

Использование `least_time` с учетом незавершенных запросов позволяет обходить бэкенды, которые начинают деградировать.

```nginx
upstream backend_api {
    zone upstream_api 1m;
    
    # inflight: учитывать запросы в обработке (самый точный метод для High Load)
    # last_byte: расчет по времени получения полного ответа
    least_time last_byte inflight;
    
    # slow_start: постепенный ввод сервера в работу (защита от "шока" холодного кэша)
    server 10.0.0.1:8080 slow_start=30s;
    server 10.0.0.2:8080 slow_start=30s;

    # Поддержание постоянных соединений с бэкендами
    keepalive 64;
    keepalive_requests 1000;
    keepalive_timeout 65s;
}
```

**Валидация:**
```bash
# Проверка состояния upstream через API
curl -s http://127.0.0.1:8080/api/6/http/upstreams/backend_api | jq '.servers[] | {addr: .server, state: .state, inflight: .requests.current}'
# → inflight должен распределяться равномерно, state = "healthy"

# Проверка slow_start: после перезапуска бэкенда RPS растет плавно
watch -n1 'curl -s http://127.0.0.1:8080/api/6/http/upstreams/backend_api | jq ".servers[] | {state, requests}'
```

---

### Сценарий 6: Нативная наблюдаемость (Prometheus и OTel)

Angie позволяет собирать метрики без внешних агентов, что снижает Latency на сбор статистики.

```nginx
http {
    # Нативный экспорт в Prometheus
    prometheus api /p8s;

    server {
        listen 127.0.0.1:8080;
        
        location /status {
            # Встроенный API (JSON формат)
            api /status/;
            allow 127.0.0.1;
            deny all;
        }

        location /p8s {
            # Эндпоинт для скрейпинга Prometheus
            prometheus;
        }
    }
}
```

**Валидация:**
```bash
# Проверка метрик Prometheus
curl -s http://127.0.0.1:8080/p8s | grep -E "angie_http_requests_total|angie_nginx_process_cpu_seconds_total"
# → metric name, value, labels

# Проверка JSON API
curl -s http://127.0.0.1:8080/api/6/http/requests | jq '.requests | {total, current, handled}'
```

---

### Сценарий 7: Оптимизация RPS при исчерпании ресурсов CPU и отсутствии бюджета

Когда вертикальное масштабирование невозможно (нет свободных CPU, нет бюджета на новые инстансы), прирост RPS достигается только за счет **повышения эффективности** текущих ресурсов.

#### 7.1. Диагностика: подтверждение CPU-bound

```bash
# 1. PSI — давление на CPU (среднее за 10с > 10% = перегруз)
cat /proc/pressure/cpu

# 2. top/htop — утилизация пользовательского пространства (us) vs системного (sy)
# sy > 30% — накладные расходы ядра (системные вызовы, прерывания, контекстные переключения)
# us ~ 100% — нагрузка от бизнес-логики приложения

# 3. perf top — горячие функции в user-space
perf top -g --ns --all-cpus

# 4. bpftrace — системные вызовы
bpftrace -e 'tracepoint:syscalls:sys_enter_* { @[probe] = count(); }'
```

#### 7.2. Оптимизация на уровне ОС и сети (бесплатно, высокий ROI)

| Мера | Эффект | Команда / Конфиг |
|------|--------|------------------|
| **RPS/RFS (Receive Packet/ Flow Steering)** | Распределение сетевых прерываний по ядрам, снятие горячего ядра CPU0 | `echo ffffffff > /sys/class/net/eth0/queues/rx-0/rps_cpus` |
| **XPS (Transmit Packet Steering)** | Привязка TX очередей к ядрам, обрабатывающим приложение | `echo ffffffff > /sys/class/net/eth0/queues/tx-0/xps_cpus` |
| **IRQ Affinity** | Жесткая привязка прерываний NIC к выделенным ядрам | `irqbalance --banlist=0-3` (оставить ядра 0-3 под приложение) |
| **TCP BBR v3** | Снижение ретрансляций, лучшее использование полосы | `net.ipv4.tcp_congestion_control=bbr` |
| **SO_REUSEPORT** | Множественные сокеты прослушивания на одном порту, балансировка в ядре | `reuseport` в `listen` директиве Angie |
| **Busy Poll / busy_read** | Опрос сокетов в пользовательском пространстве без системных вызовов | `net.core.busy_poll=50`, `net.core.busy_read=50` |

**Пример sysctl для high-RPS без бюджета:**
```bash
# /etc/sysctl.d/99-rps-optimization.conf
net.core.netdev_max_backlog = 250000
net.core.somaxconn = 65535
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
net.ipv4.tcp_fastopen = 3
net.core.busy_poll = 50
net.core.busy_read = 50
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_slow_start_after_idle = 0
# RPS/RFS настраивается динамически через /sys/class/net/
```

#### 7.3. Оптимизация Angie/Nginx конфигурации

```nginx
# main context
worker_processes auto;
worker_cpu_affinity auto;        # Привязка воркеров к ядрам
worker_rlimit_nofile 1048576;    # Дескрипторы

# _thread_pool для асинхронного I/O (не блокирует event loop)
thread_pool default threads=32 max_queue=65536;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    # Zero-copy + kTLS = минимальный CPU на шифрование/передачу
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;
    tcp_nodelay on;
    aio threads=default;

    # kTLS (OpenSSL 3.0+, Linux 4.13+)
    ssl_conf_command Options KTLS;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;

    # HTTP/2 оптимизация
    http2_max_concurrent_streams 128;
    http2_max_requests 1000;

    # reuseport — балансировка входящих соединений ядром
    server {
        listen 443 ssl http2 reuseport;
        listen 443 quic reuseport;  # HTTP/3
        http3 on;
        quic_gso on;                # GSO для UDP (CPU offload)
    }

    # Сжатие Zstd — лучший ratio/CPU чем gzip/brotli
    zstd on;
    zstd_comp_level 3;              # Баланс скорость/сжатие

    # Кэш дескрипторов файлов
    open_file_cache max=20000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # Ограничение буферов — предотвращает OOM и забивание CPU memcpy
    client_body_buffer_size 16k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 4k;
}
```

#### 7.4. Архитектурные паттерны без затрат

| Паттерн | Что делает | Результат |
|---------|------------|-----------|
| **Кэширование на уровне Angie** (`proxy_cache`, `proxy_cache_valid`) | Снижает запросы к бэкенду на 60-90% для читаемых данных | RPS растет пропорционально hit-rate, CPU бэкенда освобождается |
| **Кэширование ответов в `shared_dict` (lua/shared memory)** | Микро-кэш для часто меняющихся данных (конфиг, фичи) | Исключает лишние RPC к config-service |
| **Connection Pooling к бэкендам** (`keepalive`, `keepalive_requests`) | Исключает накладные расходы TCP/TLS handshake на каждый запрос | -30-50% CPU на proxying, -Latency |
| **Request Coalescing** (`proxy_cache_lock`, `proxy_cache_use_stale updating`) | Объединяет одновременные запросы за одним и тем же ключом | Предотвращает thundering herd при cold cache |
| **Rate Limiting на входе** (`limit_req_zone`, `limit_conn_zone`) | Защищает от перегрузки, гарантирует качество обслуживания | Предотвращает Kingman-эффект при U→100% |

#### 7.5. Применение на уровне приложения (если есть доступ к коду)

1.  **Профилирование (Continuous Profiling — Pyroscope/Parca):** Найти top-5 функций по CPU-time.
2.  **Алгоритмическая оптимизация:** O(N²) → O(N log N), убрать N+1 запросы к БД.
3.  **Кэширование в памяти приложения:** LRU-кэш для горячих вычислений.
4.  **Batch-обработка:** Объединение мелких операций в батчи (DB bulk insert, pipeline Redis).
5.  **Асинхронность:** Перевод блокирующих вызовов в async/await, пулы потоков для CPU-bound задач.

#### 7.6. Чек-лист верификации (валидация без нагрузочного стенда)

```bash
# 1. Сравнить CPU utilization до/после на той же нагрузке
# Цель: us% снизился, sy% не вырос

# 2. Проверить IRQ баланс
cat /proc/interrupts | grep -E "eth|rx|tx"
# Прерывания должны равномерно распределяться по ядрам приложения

# 3. Проверить очередь сокетов
ss -ltni | grep -E "Send-Q|Recv-Q"
# Send-Q/Recv-Q должны быть близки к 0 в steady state

# 4. Метрики Angie (Prometheus)
# angie_http_requests_total / rate(angie_nginx_process_cpu_seconds_total[5m])
# → RPS per CPU core. Цель: > 10k RPS/core на статике, > 2k RPS/core на proxy
```

#### 7.7. Когда оптимизации исчерпаны — стратегия выхода

Если после всех мер RPS всё равно не устраивает и **нет бюджета на железо**:
1.  **Деградация функционала:** Отключить некритичные фичи (рекомендации, аналитика, тяжелые отчеты) под флагом.
2.  **Приоритизация трафика:** `limit_req` с `burst` и `nodelay` для VIP-клиентов, `dryrun` для остальных.
3.  **Клиентская оптимизация:** Внедрить `ETag`/`If-None-Match`, `Cache-Control: immutable` для статики — снижает входящий RPS.
4.  **Архитектурный сдвиг:** Перевод части нагрузки в async (очереди, webhook'и) — сглаживает пики, не требует пиковых ресурсов.

---

### Сценарий 8: Systemd-тюнинг и cgroups

Правильная настройка systemd-сервиса предотвращает проблемы с дескрипторами, памятью и приоритетом процессов.

```ini
# /etc/systemd/system/angie.service.d/override.conf
[Service]
LimitNOFILE = 1048576
LimitNPROC = 65536
MemoryMax = 8G
MemoryHigh = 6G
CPUQuota = 800%
TasksMax = 4096
IOWeight = 100
Nice = -10
OOMScoreAdjust = -500
Restart = on-failure
RestartSec = 5s
```

**Валидация:**
```bash
# Применение изменений
systemctl daemon-reload
systemctl restart angie

# Проверка лимитов
systemctl show angie | grep -E "LimitNOFILE|MemoryMax|CPUQuota|TasksMax"
# → LimitNOFILE=1048576, MemoryMax=8G, CPUQuota=800%, TasksMax=4096

# Проверка приоритета
ps -o pid,ni,pri,comm -p $(pgrep angie | head -1)
# → NI = -10 (высокий приоритет)
```

---

### Сценарий 9: Кэширование в tmpfs (RAM-backed cache)

Для горячих данных (конфигурация, небольшие статические файлы) использование tmpfs исключает дисковые I/O.

```nginx
http {
    proxy_cache_path /dev/shm/angie_cache levels=1:2 keys_zone=ram_cache:64m max_size=512m inactive=60s use_temp_path=off;

    server {
        location /api/v1/config {
            proxy_cache ram_cache;
            proxy_cache_valid 200 10s;
            proxy_cache_use_stale error timeout updating;
            proxy_pass http://config-service:8080;
        }
    }
}
```

**Валидация:**
```bash
# Проверка использования tmpfs
df -h /dev/shm
# → /dev/shm 8G 256M 7.8G 4% /dev/shm

# Проверка hit-rate
curl -s http://127.0.0.1:8080/api/6/http/caches/ram_cache | jq '.bytes | {total, free}'
# → total должен расти при MISS, free уменьшаться
```

---

### Сценарий 10: Бенчмаркинг и нагрузочное тестирование

Структурированный подход к тестированию производительности с учетом Coordinated Omission.

```bash
# wrk2 — сценарий Lua для имитации реального трафика
wrk -t4 -c100 -d30s -s post.lua https://api.example.com/endpoint

# post.lua
wrk.method = "POST"
wrk.body = '{"key":"value"}'
wrk.headers["Content-Type"] = "application/json"

# Ожидаемый вывод:
# Requests/sec: ~12500
# Latency P50 = 2.3ms, P95 = 8.1ms, P99 = 15.2ms
```

**Валидация:**
```bash
# Проверка percentile-метрик в Prometheus
curl -s http://localhost:9090/api/v1/query?query=histogram_quantile\(0.99,sum\(rate\(angie_http_request_duration_seconds_bucket[5m]\)\)by\(le\)\)
# → P99 latency должен быть стабильным

# Проверка Coordinated Omission
# wrk2 автоматически учитывает CO, в отличие от стандартного wrk
# Сравните P99: wrk2 показывает реальные задержки при перегрузке
```

---

### Сценарий 11: Мониторинг и алертинг (Prometheus)

Конфигурация правил алертинга для proactive обнаружения деградации.

```yaml
# /etc/prometheus/rules/angie_performance.yml
groups:
  - name: angie.performance
    rules:
      - record: angie:rps_per_cpu
        expr: sum(rate(angie_http_requests_total[5m])) / sum(angie_nginx_process_cpu_seconds_total)

      - record: angie:latency_p99
        expr: histogram_quantile(0.99, sum(rate(angie_http_request_duration_seconds_bucket[5m])) by (le))

      - record: angie:error_rate_5xx
        expr: sum(rate(angie_http_requests_total{code=~"5.."}[5m])) / sum(rate(angie_http_requests_total[5m]))

  - name: angie.alerts
    rules:
      - alert: AngieHighLatency
        expr: angie:latency_p99 > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P99 latency Angie > 500ms"
          description: "Текущий P99: {{ $value }}s. Проверьте worker_processes, backend latency, и сетевые прерывания."

      - alert: AngieLowRPSperCPU
        expr: angie:rps_per_cpu < 2000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "RPS per CPU упал ниже 2000"
          description: "Текущий RPS/core: {{ $value }}. Возможна деградация кэша, bloat в network buffers, или проблемы с ядром."

      - alert: AngieHighErrorRate
        expr: angie:error_rate_5xx > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Более 5% ошибок 5xx"
          description: "Текущий error rate: {{ $value }}. Проверьте health check бэкендов и лимиты limit_req."
```

---

### Сценарий 12: Планирование мощности (Capacity Planning)

Расчет параметров для горизонтального и вертикального масштабирования с запасом на пики.

**Формула вертикального масштабирования:**
```
Рекомендуемое worker_processes = ceil(Пиковые параллельные запросы × 1.3)
```

Где 1.3 — запас на 30% на пики и сбои.

**Пример расчета:**
- 10000 RPS пик, средняя Latency 50ms, Keep-Alive 100 запросов на соединение
- Параллельные соединения = 10000 × 0.05 = 500
- С запасом 30%: ceil(500 × 1.3) = 650 воркеров
- При 8 ядрах CPU: worker_processes = 8, worker_connections = 650 / 8 ≈ 82
- На практике: worker_processes auto; worker_connections 4096;

**Формула размера shared memory:**
```
shared_memory ≥ (кол-во зон × размер зоны) + (размер кэша / 2)
```

Пример: 10 зон по 10MB + кэш 1GB → shared_memory ≥ 10×10MB + 512MB = 612MB

---

### Сценарий 13: Сжатие трафика и отдача статики

#### Сжатие ответов (gzip / brotli / zstd)

Компрессия снижает исходящий трафик (и ёмкость CDN/полосы), но тратит CPU на каждый ответ. Выбор алгоритма:

*   **gzip** — универсально совместимый, самый распространённый. Хорош для текстовых MIME (HTML/CSS/JS/JSON/XML/SVG).
*   **zstd** — лучший баланс ratio/CPU и высокая скорость; нативен в Angie (`zstd on;`). Для API рекомендуется в первую очередь.
*   **brotli** — лучшая степень сжатия, но для Angie подключается внешним динамическим модулем (`ngx_brotli_filter`). Обычный выбор для HTML/статики при наличии свободного CPU.

```nginx
http {
    # gzip — базовый уровень (по типам контента)
    gzip on;
    gzip_types text/plain text/css application/json application/javascript
               application/xml image/svg+xml font/woff2 text/xml;
    gzip_min_length 1024;
    gzip_comp_level 5;
    gzip_vary on;   # Vary: Accept-Encoding для корректной работы CDN/кэша

    # zstd — нативный для Angie, для API
    zstd on;
    zstd_comp_level 3;

    # brotli (только если собран модуль ngx_brotli_filter)
    # brotli on;
    # brotli_comp_level 5;
}
```

**Важно:** компрессия и HTTP/2/3 мультиплексирование сочетаются плохо для потоковых ответов (SSE) — для `text/event-stream` сжатие отключайте. Детали серверного сжатия — [Nginx: сжатие](../../Nginx/Performance/nginx_compression.md).

#### Отдача предварительно сжатых файлов (gzip_static / brotli_static)

Для статики заранее положите рядом с файлом версию `.gz`/`.br` (например, при сборке фронтенда). Angie отдаст сжатый файл без расходования CPU:

```nginx
location ^~ /static/ {
    gzip_static on;   # отдаем /static/app.js.gz, если Accept-Encoding: gzip
    expires 30d;
    add_header Cache-Control "public, immutable";
    access_log off;
}
```

Требуется модуль `ngx_http_gzip_static_module`. Преимущество: нулевой CPU на сжатие, крайне высокий RPS на статике.

#### Тюнинг отдачи файлов (kernel + buffer)

```nginx
http {
    sendfile on;                 # zero-copy отдача файлов через ядро
    tcp_nopush on;               # отправка ответа одним пакетом (при sendfile)
    tcp_nodelay on;              # отключает задержку Nagle для keep-alive

    # Кэш дескрипторов открытых файлов
    open_file_cache max=20000 inactive=60s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    server {
        location /media/ {
            # AIO для больших файлов и директории с RAID
            aio threads;
            directio 4m;         # включать direct I/O для файлов > 4MB
            happy_eyeballs on;
        }
    }
}
```

*   `sendfile` — отдача файла без копирования в userspace; для SSD/RAID.
*   `aio threads` — асинхронное I/O для больших файлов (не блокирует event loop).
*   `directio 4m` — для файлов крупнее 4MB использует direct I/O (обход page cache) — актуально при CDN-раздаче видео/архивов.

Полный сценарий отдачи статики (root/alias, MIME, X-Accel-Redirect) — [Nginx: serving files](../../Nginx/Core/Location/serving_files.md).

#### Кэш-контроль для статики

```nginx
location ^~ /static/ {
    expires 30d;                        # Cache-Control: max-age=2592000
    add_header Cache-Control "public, immutable" always;  # хэшированный бандл
    etag on;
    if_modified_since exact;            # экономия трафика (304 Not Modified)
}
```

Для файлов с хэшем в имени (`app.a1b2c3.js`) используйте `immutable` — браузер не будет слать условные запросы. Для статики без хэша — `max-age=600` и условные запросы через `etag`/`Last-Modified`.

---

## Устранение неисправностей (Troubleshooting)

### Типичные проблемы и диагностика

| Симптом | Возможная причина | Диагностика | Решение |
|---------|-------------------|-------------|---------|
| Высокий p99 latency при низком RPS | Деградация бэкенда, TCP retransmit | `ss -ti` на Angie и бэкенде | Проверить сеть, увеличить `keepalive_timeout` |
| Резкие 502/503 | Переполнение очереди бэкенда, `worker_connections` исчерпан | `error_log`, `upstream_status` в access log | Увеличить `worker_connections`, настроить `max_conns` (Angie PRO) |
| Angie не использует все ядра CPU | `worker_cpu_affinity` не настроен, `irqbalance` конфликтует | `top -H`, `/proc/interrupts` | Настроить `worker_cpu_affinity`, отключить `irqbalance` |
| Ошибки TLS handshake | Устаревшие cipher suites, несовместимость kTLS | `openssl s_client -connect host:443` | Обновить OpenSSL, проверить `ssl_conf_command` |
| Всплески latency при reload | `worker_shutdown_timeout` слишком мал | `error_log` при `reload` | Увеличить `worker_shutdown_timeout` до 60s |
| Высокий sy% (>30%) | Накладные расходы ядра (прерывания, syscalls) | `pidstat -t`, `/proc/interrupts` | Настроить IRQ affinity, RPS/RFS |
| OOM при включенном кэше | `proxy_cache_path` без ограничений | `dmesg | grep -i oom` | Указать `max_size` в `proxy_cache_path`, настроить `MemoryMax` в systemd |

### Экстренные процедуры реагирования (Runbook)

При резком падении производительности:

1.  **Идентификация источника:**
    ```bash
    # Топ процессов по CPU
    top -b -n1 -p $(pgrep angie | tr '\n' ',' | sed 's/,$//')
    
    # Проверка сетевых прерываний
    cat /proc/interrupts | grep -E "eth|rx|tx" | awk '{print $1, $2, $NF}'
    ```

2.  **Немедленная разгрузка:**
    ```nginx
    # Включение dry-run для limit_req
    limit_req_zone $binary_remote_addr zone=emergency:10m rate=1000r/s;
    # Если реальный rate был 2000r/s, временно снизить до 1000r/s
    ```

3.  **Снижение качества обслуживания:**
    ```bash
    # Отключение тяжелых фич через API Angie (если поддерживается)
    curl -X POST http://127.0.0.1:8080/api/6/http/config -d '{"zstd":"off"}'
    ```

4.  **Восстановление:**
    ```bash
    # Грациозный возврат к нормальной конфигурации
    angie -s reload
    
    # Мониторинг восстановления
    watch -n1 'ss -s | grep estab'
    ```

## Лучшие практики

### Рекомендации по тюнингу

1.  **PCRE JIT:** Всегда включайте `pcre_jit on;` для ускорения регулярных выражений.
2.  **Open File Cache:** `open_file_cache max=10000 inactive=60s;` — кэширование дескрипторов открытых файлов значительно снижает количество системных вызовов при раздаче статики.
3.  **Сжатие Zstd:** Используйте `zstd on;` вместо Gzip для API-ответов, это дает выигрыш до 20-30% по трафику при меньшем потреблении CPU.
4.  **Бенчмаркинг:** В 2026 году для High Load тестов рекомендуется использовать `wrk2` или `k6`, так как они корректно учитывают Coordinated Omission.
5.  **multi_accept on;** — воркер забирает все доступные соединения из очереди за один вызов, снижая количество системных вызовов.
6.  **worker_shutdown_timeout** — увеличение времени graceful shutdown при долгих соединениях (WebSocket, gRPC streaming).

### Чек-лист высокой нагрузки

- [ ] `worker_processes auto;` и `worker_cpu_affinity auto;` настроены
- [ ] `worker_rlimit_nofile` >= 100000
- [ ] Включен `sendfile on;` и `tcp_nopush on;`
- [ ] Настроен `open_file_cache` для статики
- [ ] Включено сжатие `zstd on;` или `gzip on;`
- [ ] `keepalive_timeout` и `keepalive_requests` настроены под профиль трафика
- [ ] Настроены таймауты: `client_header_timeout`, `client_body_timeout`, `send_timeout`
- [ ] Для HTTPS: `ssl_conf_command Options +KTLS;` и `ssl_ciphers` без legacy
- [ ] Настроен мониторинг `status_zone` или Prometheus экспорт
- [ ] Настроены лимиты `limit_req` и `limit_conn` с `sync` для кластера
- [ ] Проведено тестирование `wrk2`/`k6` с percentile-анализом (p95, p99, p99.9)
- [ ] Systemd-сервис имеет `LimitNOFILE` >= 1000000
- [ ] `worker_shutdown_timeout` настроен на длительные соединения
- [ ] Проксируемый трафик использует `reuseport` и `keepalive` к бэкендам
- [ ] Настроены алерты на P99 latency и RPS per CPU

---

## См. также

- [Оптимизация производительности Nginx](../../Nginx/Performance/nginx_performance_tuning.md) — общие принципы тюнинга веб-серверов
- [Серверное кэширование и производительность](../../Nginx/Performance/Caching/proxy_caching.md)
- [Оптимизация сжатия в Nginx](../../Nginx/Performance/nginx_compression.md)
- [Конфигурация HTTP/2 и HTTP/3 в Nginx и Angie](../../Nginx/Performance/nginx_http_versions.md)
- [Защита от DoS-атак в Angie](./dos_protection.md)
- [Обзор возможностей Angie](../angie_overview.md)
- [Балансировка нагрузки HTTP в Angie](../angie_http_load_balancing.md)
- [Методология тестирования производительности](../../../Testing/performance_testing_methodology.md)
- [Законы масштабируемости](../../../Concepts/High_Availability/scalability_laws.md)
- [Linux RSS/RPS/RFS](../../../Linux/Networking/Concepts/rss_rps_rfs.md)
