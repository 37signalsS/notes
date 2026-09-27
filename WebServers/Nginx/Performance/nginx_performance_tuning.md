# Оптимизация производительности Nginx

## Определения

**Оптимизация производительности Nginx** — комплексный процесс настройки архитектуры веб-сервера, параметров ядра Linux и сетевого стека для достижения максимальной пропускной способности (throughput) и минимальных задержек (latency) при обработке трафика.

**Worker process** — независимый дочерний процесс Nginx, обрабатывающий соединения в неблокирующем цикле событий (event loop). Количество воркеров определяется директивой `worker_processes`.

**Event Loop (цикл событий)** — ядро архитектуры Nginx. Воркер регистрирует события (accept, read, write) в epoll/kqueue и обрабатывает их по готовности, без выделения потока на каждое соединение.

**Zero-Copy** — технология передачи данных с диска напрямую в сетевой интерфейс через системный вызов `sendfile()`, минуя копирование в адресное пространство приложения и лишние переходы между режимами ядра.

**open_file_cache** — механизм кэширования дескрипторов файлов, их размеров и времени модификации в оперативной памяти. Ускоряет отдачу мелкой статики за счет сокращения количества системных вызовов `stat()`.

**Keepalive (HTTP persistent connection)** — механизм повторного использования одного TCP-соединения для нескольких HTTP-запросов, снижающий накладные расходы на установку соединения (handshake).

**kTLS (Kernel TLS)** — перенос симметричного шифрования (AES-GCM, ChaCha20-Poly1305) из пользовательского пространства в ядро Linux. Позволяет использовать `sendfile()` вместе с TLS, исключая двойное копирование данных.

## Основные концепции

### Архитектура и процессная модель

Производительность Nginx определяется тремя факторами: количество воркеров, эффективность Event Loop и оптимальность взаимодействия с ядром.

*   **`worker_processes auto;`** — создает один процесс на каждое доступное ядро CPU. Это baseline для всех современных конфигураций. Для систем с NUMA учитывайте расположение ядер: `worker_cpu_affinity` позволяет привязать воркеры к конкретным ядрам и их локальной памяти.
*   **`worker_rlimit_nofile`** — мягкий лимит дескрипторов файлов для воркеров. Должен превышать `worker_connections` минимум в 2 раза, так как на каждое проксируемое соединение тратится два дескриптора (клиент + бэкенд). Рекомендуемое значение: `65535` или выше.
*   **`worker_shutdown_timeout`** — время на корректное завершение воркера при перезагрузке конфигурации. Предотвращает "подвешивание" старых процессов при долгих соединениях (gRPC, WebSocket, HTTP/3). Значение по умолчанию — `0` (ожидать завершения без ограничений), для production рекомендуется `10s` или `30s`.
*   **`worker_priority`** — приоритет планировщика для воркеров. На загруженных серверах можно установить `worker_priority -10` или `nice` для повышения приоритета Nginx относительно других сервисов.

### Сетевой стек и ввод-вывод

Современный baseline (2026) — полная асинхронность дисковых и сетевых операций, минимизация копирований между пространствами.

*   **`sendfile on;`** — включает Zero-Copy. Критически важен для статики и pre-compressed файлов. В сочетании с TLS работает через kTLS (см. ниже).
*   **`sendfile_max_chunk 512k;`** — ограничивает объем данных за один вызов `sendfile()`. Предотвращает монополизацию воркера одним быстрым клиентом, скачивающим тяжелый файл. Значение `0` отключает ограничение (не рекомендуется для публичных серверов).
*   **`aio threads=default;`** — включает асинхронный дисковый I/O через пулы потоков ядра. Предотвращает блокировку Event Loop при чтении данных, отсутствующих в Page Cache. Критично для высоконагруженных систем с большим объемом статики.
*   **`tcp_nopush on;`** — отправляет заголовки HTTP и начало файла в одном TCP-пакете (TCP_CORK). Эффективно только с `sendfile on;`.
*   **`tcp_nodelay on;`** — отключает алгоритм Нагла (Nagle). Критично для HTTP/2 и HTTP/3, где задержка отправки мелких фреймов управления замедляет весь поток. В паре с `tcp_nopush` работает корректно: `tcp_nopush` собирает пакеты при записи, `tcp_nodelay` мгновенно отправляет их при сбросе.
*   **`reset_timedout_connection on;`** — принудительно закрывает соединения по таймауту, освобождая дескрипторы и память воркера.

### open_file_cache

Кэширует дескрипторы файлов, их размеры и время модификации. Радикально ускоряет отдачу мелкой статики (favicon, robots.txt, CSS, JS) на системах с большим количеством файлов.

```nginx
http {
    open_file_cache          max=10000 inactive=20s;
    open_file_cache_valid    30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;
}
```

*   **`max=10000`** — максимальное количество элементов в кэше. Значение должно покрывать количество часто отдаваемых файлов.
*   **`inactive=20s`** — время неиспользования, после которого элемент удаляется из кэша.
*   **`open_file_cache_valid 30s`** — интервал проверки актуальности кэшированных данных (inode, размер). При изменении файла на диске Nginx обнаружит это в течение указанного времени.
*   **`open_file_cache_min_uses 2`** — минимальное количество обращений для попадания в кэш. Исключает "шум" от редко запрашиваемых файлов.
*   **`open_file_cache_errors on`** — кэширует ошибки отсутствия файлов (`ENOENT`), защищая файловую систему от шумного трафика ботов.

### Keepalive и пулы соединений

С версии Nginx 1.19.10 значение `keepalive_requests` по умолчанию увеличено до `1000`. С версии 1.29.7 keepalive к бэкендам включен по умолчанию с лимитом `32` соединений на воркер.

```nginx
http {
    keepalive_timeout  65s;
    keepalive_requests 1000;
    reset_timedout_connection on;

    upstream backend {
        server 10.0.0.1:8080;
        server 10.0.0.2:8080;

        keepalive 32;
        keepalive_timeout 60s;
        keepalive_requests 1000;
    }

    server {
        listen 80;

        location / {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
        }
    }
}
```

**Важно:** Для работы `keepalive` в `upstream` необходимо:
1.  Установить `proxy_http_version 1.1;` (HTTP/1.0 не поддерживает keepalive по умолчанию).
2.  Очистить заголовок `Connection`: `proxy_set_header Connection "";`.
3.  Убедиться, что бэкенд не закрывает соединения агрессивно (его `keepalive_timeout` должен быть не меньше, чем у Nginx).

### Kernel TLS (kTLS)

kTLS переносит симметричное шифрование в ядро Linux, что позволяет использовать `sendfile()` вместе с TLS и исключить копирование данных между пространствами.

**Требования:**
*   **Ядро Linux:** 4.13+ (базовая поддержка), 5.2+ (рекомендуется).
*   **OpenSSL:** 3.0+ с опцией сборки `enable-ktls`.
*   **Nginx:** 1.21.4+ (поддержка `SSL_sendfile()` с kTLS).

**Ограничения:**
*   На-loaded системах (высокий RPS) kTLS может конфликтовать с фреймированием HTTP/2 в user-space. Тестируйте на производственных профилях нагрузки.
*   NIC offload (`TLS_HW`) работает только для TLS 1.2. Для TLS 1.3 используется software mode (`TLS_SW`) в ядре.
*   Не поддерживается для соединений, маршрутизируемых через tun/tap, VXLAN, wireguard.

```nginx
http {
    ssl_conf_command Options KTLS;

    server {
        listen 443 ssl;
        ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;
        sendfile on;
        tcp_nopush on;
    }
}
```

## Практические сценарии

### Сценарий 1: Базовая конфигурация для высоконагруженного сервера

Полный baseline для отдачи статики и проксирования.

```nginx
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 65535;
    multi_accept on;
    use epoll;
}

http {
    # MIME-типы
    include       mime.types;
    default_type  application/octet-stream;

    # Zero-Copy и сетевой стек
    sendfile            on;
    sendfile_max_chunk  512k;
    tcp_nopush          on;
    tcp_nodelay         on;

    # Асинхронный дисковый I/O
    aio                 threads=default;

    # Кэширование дескрипторов
    open_file_cache          max=10000 inactive=20s;
    open_file_cache_valid    30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;

    # Keepalive
    keepalive_timeout  65s;
    keepalive_requests 1000;
    reset_timedout_connection on;

    server {
        listen 80;
        server_name example.com;
        root /var/www/html;

        location / {
            try_files $uri $uri/ =404;
        }

        location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
            expires 365d;
            add_header Cache-Control "public, immutable" always;
            access_log off;
        }
    }
}
```

### Сценарий 2: Валидация производительности

Используйте `curl` и системные утилиты для проверки:

```bash
# Проверка конфигурации
nginx -t
# → test is successful

# Проверка Zero-Copy (статистика sendfile)
ss -tnp | grep nginx
curl -I http://example.com/large-file.zip
# В логах access.log должно отсутствовать время "writing" для статики

# Проверка open_file_cache
curl http://127.0.0.1/nginx_status
# При включенном stub_status: "open file cache: 1024/10000"

# Проверка worker affinity
ps -o pid,psr,comm -p $(pgrep nginx)
# Каждый worker должен быть привязан к своему ядру (при worker_cpu_affinity)

# Проверка keepalive
ss -tn state established '( dport = :80 )' | wc -l
# Должен расти при множестве запросов от одного клиента
```

### Сценарий 3: Интеграция с systemd и лимитами

Для production-систем настройте лимиты через systemd, чтобы они не сбрасывались при перезагрузке:

```ini
# /etc/systemd/system/nginx.service.d/limits.conf
[Service]
LimitNOFILE=65535
LimitNPROC=65536
```

```bash
# Применение
systemctl daemon-reload
systemctl restart nginx

# Проверка
cat /proc/$(pgrep -o nginx)/limits | grep "open files"
# → Max open files            65535                65535                files
```

### Сценарий 4: kTLS в production

Включение kTLS с проверкой совместимости:

```bash
# Проверка поддержки kTLS в ядре
cat /proc/crypto | grep -i tls
# Должен присутствовать алгоритм tls(aead)

# Проверка OpenSSL
openssl list -providers | grep -i tls
# → name: OpenSSL TLS Provider

# Включение kTLS в Nginx
nginx -t
# → test is successful (ошибка компиляции OpenSSL без ktls приведет к ошибке здесь)

# Перезагрузка
nginx -s reload
```

### Сценарий 5: Тюнинг ядра Linux под Nginx (sysctl)

Высокая нагрузка на Nginx упирается не только в конфиг, но и в параметры сетевого стека ядра. Без системных лимитов даже правильный `worker_connections` не даст трафика — узким местом станут queue backlog и исчерпание портов.

```bash
# /etc/sysctl.d/99-nginx.conf
net.core.somaxconn = 65535                    # очередь accept (должен быть ≥ backlog в listen)
net.core.netdev_max_backlog = 16384           # очередь пакетов сетевого устройства
net.ipv4.tcp_max_syn_backlog = 65535          # очередь SYN до установки соединения
net.ipv4.tcp_tw_reuse = 1                     # переиспользование TIME_WAIT для исходящих
net.ipv4.ip_local_port_range = 1024 65535     # диапазон эфемерных портов (для исходящих к upstream)
net.ipv4.tcp_fin_timeout = 30                 # сокращение длительности TIME_WAIT
net.ipv4.tcp_keepalive_time = 600             # таймаут keepalive TCP (для штатного соединения)
net.ipv4.tcp_slow_start_after_idle = 0        # отключить медленный старт после простоя (для API)
```

Применение и проверка:

```bash
sysctl --system
sysctl net.core.somaxconn
# → net.core.somaxconn = 65535
```

```nginx
# В nginx.conf должны совпадать с настройками ядра:
listen 80 backlog=65535;    # backlog ≤ net.core.somaxconn
worker_rlimit_nofile 65535; # ≤ fs.file-max / LimitNOFILE в systemd
worker_connections 65535;
```

Ориентиры:

- **`fs.file-max`** (или `fs.nr_open`) — глобальный лимит открытых файлов в системе; если Nginx упирается в «too many open files», проверьте и `ulimit` процесса, и `fs.file-max`, и `systemd LimitNOFILE` (см. Сценарий 3).
- **`net.core.somaxconn`** влияет на глубину очереди соединений; превышение даёт `connection refused` под всплеском.
- Для **исходящих** соединений (к апстримам) критичен `ip_local_port_range` и `tcp_fin_timeout`, иначе на холодном `keepalive`-пуле возникает `connect() failed (99: Cannot assign requested address)`.

Подробно про лимиты файлов и влияние на воркеры — см. [Установку и базовую настройку](../Core/nginx_setup.md) и [Диагностику Nginx](../Operations/nginx_troubleshooting.md).

## Операции и команды

| Задача | Команда / Директива | Ожидаемый результат |
| :--- | :--- | :--- |
| Проверка конфигурации | `nginx -t` | `test is successful` |
| Применение конфигурации | `nginx -s reload` | Graceful reload без потерь соединений |
| Проверка worker процессов | `ps -eo pid,psr,comm | grep nginx` | Worker'ы на отдельных ядрах |
| Статистика соединений | `ss -tnp \| grep nginx` | Список активных соединений |
| Лимиты дескрипторов | `cat /proc/$(pgrep -o nginx)/limits \| grep "open files"` | `65535` или выше |
| open_file_cache | `curl http://127.0.0.1/nginx_status` | `open file cache: N/10000` |
| Проверка sendfile | `strace -p $(pgrep -o nginx) -e trace=sendfile` | Системные вызовы `sendfile()` при отдаче статики |
| Проверка kTLS | `openssl list -providers \| grep -i tls` | Наличие TLS Provider |
| Graceful restart | `systemctl reload nginx` | `Reloading Nginx... done.` |
| Проверка keepalive | `ss -tn state established '( dport = :80 )'` | Несколько соединений от одного IP |
| Мониторинг RPS | `cat /var/log/nginx/access.log \| tail -n 1000 \| awk '{print $4}' \| sort \| uniq -c \| sort -rn \| head` | Распределение запросов по секундам |

## Устранение неполадок

### Высокий CPU usage в воркерах

**Симптом:** `top` показывает `%CPU` на уровне 100% на одном или нескольких воркерах, хотя запросы простые.

**Причины и диагностика:**

1.  **Динамическое сжатие на высоком уровне:**
    ```bash
    # Проверка уровня gzip
    grep gzip_comp_level /etc/nginx/nginx.conf
    # Рекомендуется 1–2 для динамического контента
    ```

2.  **Блокирующий I/O:**
    ```bash
    # Проверка активных файловых дескрипторов
    ls /proc/$(pgrep -o nginx)/fd | wc -l
    # Резкий рост может указывать на утечку дескрипторов
    ```

3.  **Некорректный worker_connections:**
    ```bash
    # Сравнение лимита и фактического использования
    cat /proc/$(pgrep -o nginx)/limits | grep "open files"
    ss -s | grep sockets
    ```

**Решение:**
*   Переместите сжатие в CI/CD (pre-compression). Подробнее: [Оптимизация сжатия в Nginx](./nginx_compression.md).
*   Убедитесь, что `aio threads` включен для дискового I/O.
*   Увеличьте `worker_processes` при наличии свободных ядер.

### 502/504 на статику

**Симптом:** Nginx возвращает 502/504 на запросы к статическим файлам, которые существуют на диске.

**Причины и диагностика:**

1.  **Исчерпание `worker_connections`:**
    ```bash
    grep worker_connections /etc/nginx/nginx.conf
    ss -s | grep -i "estab listen"
    ```

2.  **Ошибки файловой системы:**
    ```bash
    dmesg | tail -n 50
    # Ищите "input/output error", "readdir", "ext4"
    ```

3.  **Некорректные права доступа:**
    ```bash
    ls -la /var/www/html/path/to/file
    # Nginx работает от пользователя nginx (не root)
    ```

**Решение:**
*   Увеличьте `worker_connections` и `worker_rlimit_nofile`.
*   Проверьте `open_file_cache_errors on` для защиты от ботов.
*   Убедитесь, что `user nginx` имеет права на чтение файлов.

### Падение worker процессов (SIGSEGV, SIGABRT)

**Симптом:** В `error.log` появляются `worker process N exited on signal 11 (SIGSEGV)`.

**Диагностика:**
```bash
# Проверка последних ошибок
tail -n 100 /var/log/nginx/error.log | grep -E "signal|assert|panic"

# Проверка версии Nginx на наличие известных CVE
nginx -v 2>&1
# Сравните с https://nginx.org/en/security_advisories/
```

**Решение:**
*   Обновите Nginx до последней стабильной версии (1.30.x на момент 2026 года).
*   Отключите проблемные модули (например, `ngx_http_ssi_module`, если не используется).
*   Включите core dump для глубокой диагностики: `worker_rlimit_core 512M;`.

### Высокий TTFB (Time To First Byte)

**Симптом:** `curl -o /dev/null -w "%{time_starttransfer}\n" http://example.com` показывает >200ms на статику.

**Диагностика:**
```bash
# Сравнение отдачи через Nginx и напрямую
time curl -s -o /dev/null -w "%{time_total}\n" http://example.com/large-file
time cat /var/www/html/large-file > /dev/null
```

**Решение:**
*   Убедитесь, что `sendfile on;` включен.
*   Проверьте `aio threads` для дисков без Page Cache.
*   Для SSD: отключите `aio` и используйте `directio` только для исключительных случаев.
*   Проверьте фрагментацию файловой системы: `filefrag -v /var/www/html/large-file`.

### OOM-Killer убивает Nginx

**Симптом:** В `dmesg` появляются `Out of memory: Kill process ... (nginx)`.

**Причина:** Nginx потребляет больше памяти, чем выделено `worker_rlimit_nofile` × размер буферов + shared memory зоны.

**Решение:**
*   Уменьшите `worker_rlimit_nofile` до разумных пределов (например, 65536).
*   Увеличьте `proxy_buffer_size` и `proxy_buffers` только при необходимости (по умолчанию часто достаточно).
*   Настройте `oom_score_adj` для Nginx: `systemctl edit nginx` → `[Service] OOMScoreAdjust=-500`.

## Рекомендации

1.  **Используйте `worker_processes auto;`** как baseline. Не задавайте значение вручную, кроме особых случаев (NUMA, container cgroups).
2.  **Включайте `sendfile on;` и `tcp_nopush on;`** для всех серверов, отдающих статику или pre-compressed файлы.
3.  **Настраивайте `open_file_cache`** при количестве файлов >1000. Это снижает нагрузку на inode cache ядра.
4.  **Используйте `aio threads=default;`** на системах с HDD или медленными SSD, где Page Cache не справляется с объемом.
5.  **Увеличивайте `worker_rlimit_nofile` через systemd**, а не через `ulimit` в скриптах запуска. Это гарантирует применение лимита при старте.
6.  **Не повышайте уровень сжатия gzip выше 2** для динамического контента. Для статики используйте pre-compression (Brotli/Zstd) в CI/CD.
7.  **Тестируйте kTLS на production-профиле** перед включением. На некоторых NIC/ядровых конфигурациях производительность может снизиться.
8.  **Используйте upstream `keepalive`** при проксировании. Это исключает повторный handshake на каждый запрос.
9.  **Мониторьте `ss -s` и `/proc/net/sockstat`** для своевременного обнаружения исчерпания портов или дескрипторов.
10. **Обновляйте Nginx регулярно.** Версия 1.30.x (stable) и 1.31.x (mainline) получают исправления CVE и улучшения производительности.

## Дополнительная информация

### Связанные файлы

*   [Кэширование в Nginx и Angie](./Caching/overview.md) — серверное и клиентское кэширование.
*   [Оптимизация сжатия (Gzip, Brotli, Zstandard)](./nginx_compression.md) — динамическое и статическое сжатие.
*   [Адаптивная доставка изображений](./nginx_adaptive_content.md) — статическая доставка AVIF/WebP/JPEG XL.
*   [Конфигурация HTTP/2 и HTTP/3](./nginx_http_versions.md) — настройка QUIC и HTTP/3.
*   [Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md) — методология поиска неполадок.
*   [Тюнинг параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md) — сетевые и файловые лимиты.
*   [Оптимизация TCP в Linux](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — BBR, qdisc, RSS/RPS.
*   [Обзор Nginx](../Core/nginx_overview.md) — архитектура, процессная модель, роли веб-сервера.
*   [Обзор Angie](../../Angie/angie_overview.md) — форк с расширенными функциями (динамические апстримы, мониторинг).

### Отличия Nginx и Angie в контексте производительности

Nginx Open Source и Angie разделяют ядро, но отличаются набором модулей и стратегией releases:

*   **Nginx (F5):** стабильная (1.30.x) и mainline (1.31.x) ветки. Акцент на стабильность и безопасность. kTLS, HTTP/3, Multipath TCP доступны в mainline.
*   **Angie:** форк от оригинальной команды. Включает `least_time` (балансировка по времени ответа), `status_zone` с оптимизированной общей памятью (Angie 1.12), динамические апстримы. Выбор зависит от требований к мониторингу и скорости выхода фиксов.
