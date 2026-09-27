# Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx

## Определения

**Модуль stream в Nginx** — расширение функциональности Nginx, предоставляющее возможности для балансировки нагрузки и проксирования трафика на транспортном уровне (L4). Позволяет работать с протоколами, не основанными на HTTP: базами данных (MySQL, PostgreSQL), DNS, NTP, SSH и другими.

**L4 (Transport Layer)** — уровень модели OSI, на котором Nginx работает с TCP/UDP-сессиями, оперируя IP-адресами и портами без разбора содержимого трафика (за исключением TLS SNI/ALPN при включенном `ssl_preread`).

**L7 (Application Layer)** — уровень модели OSI, где Nginx обрабатывает HTTP-трафик: заголовки, cookies, тело запроса, URI. Подробнее о принципах балансировки на этом уровне: [Обзор балансировки в Nginx](./Load_Balancing/overview_concepts.md).

**SNI (Server Name Indication)** — расширение протокола TLS, позволяющее клиенту указать имя хоста во время handshake. Начиная с Nginx 1.25.5, модуль `stream` поддерживает директиву `server_name` для маршрутизации на основе SNI.

**SSL Pre-read** — режим анализа Client Hello без терминации TLS. Позволяет извлекать SNI, выбранный протокол и ALPN-список для маршрутизации трафика на L4.

**Proxy Protocol** — протокол для передачи реального IP-адреса клиента через балансировщик, работающий на L4. Используется, когда Nginx стоит за внешним L4-балансировщиком (HAProxy, IPVS) и не может получить IP напрямую из TCP-соединения. Подробнее: [Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md).

**Upstream (L4)** — именованная группа бэкенд-серверов в блоке `stream`, между которыми распределяется нагрузка. Алгоритмы балансировки и параметры `max_fails`/`fail_timeout` аналогичны HTTP-блоку. Подробнее: [Алгоритмы балансировки](./Load_Balancing/algorithms.md).

**Зона (zone)** — разделяемая память для хранения состояния upstream-группы между рабочими процессами. Критична для корректной работы `least_conn` и sticky-сессий. В блоке `stream` поддерживается начиная с Nginx 1.25.5.

## Основные концепции и архитектура

### Сравнение L4 и L7 проксирования

| Характеристика | L4 (Transport Layer) | L7 (Application Layer) |
| :--- | :--- | :--- |
| **Уровень модели OSI** | Layer 4 (TCP, UDP) | Layer 7 (HTTP, HTTPS, gRPC) |
| **Единица обработки** | Сессия или пакет | Запрос и ответ |
| **Разбор содержимого** | Отсутствует (кроме TLS SNI/ALPN) | Полный (заголовки, cookies, тело) |
| **Накладные расходы** | Минимальные (высокая производительность) | Более высокие (анализ прикладного уровня) |
| **Возможности** | Балансировка, ограничение соединений, SSL Passthrough | Кэширование, модификация URI, WAF, rewrite |
| **Директивы доступа** | `allow`/`deny` по IP | `allow`/`deny` + `auth_request` + `limit_req` |

### Архитектура процесса обработки L4-соединения в Nginx

Понимание жизненного цикла TCP/UDP-сессии необходимо для диагностики проблем производительности и таймаутов.

1.  **Прием соединения:** Клиент открывает TCP-соединение с Nginx. Воркер регистрирует событие в Event Loop (epoll/kqueue). Для UDP — принимает первый пакет и создает виртуальную сессию.
2.  **Выбор server-блока:** Nginx сопоставляет IP:Port с блоком `server`. Если включен `ssl_preread`, на этом этапе анализируется Client Hello для извлечения SNI.
3.  **Выбор upstream-сервера:** При наличии `proxy_pass` Nginx выбирает сервер из группы `upstream` по настроенному алгоритму (Round Robin, `least_conn` и др.). Без `zone` балансировка работает некорректно при нескольких воркерах.
4.  **Установка соединения с бэкендом:** Берется соединение из пула (если настроено) или создается новое TCP/TLS-соединение. Для UDP создается виртуальная сессия к выбранному бэкенду.
5.  **Проксирование:** Nginx передает данные между клиентом и бэкендом. Буферизация отключена по умолчанию (пакетный режим), что минимизирует задержку. При включенном `ssl_preread` расшифровка не выполняется.
6.  **Возврат клиенту:** Данные передаются клиенту в потоковом режиме. Соединение либо закрывается по таймауту, либо возвращается в пул (для TCP).
7.  **Обновление счетчиков:** Увеличиваются счетчики для выбранного upstream-сервера, если настроена `zone` или `status_zone` (Angie/Nginx Plus).

### Конфигурация и основные директивы

Блок `stream` располагается на верхнем уровне `nginx.conf`, на том же уровне иерархии, что и `http`. Базовая структура:

```nginx
# /etc/nginx/nginx.conf
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/nginx/stream-access.log basic;

    include /etc/nginx/stream.d/*.conf;
}
```

> **Примечание:** Подробное описание структуры конфигурации и блоков приведено в [Установка и базовая настройка Nginx](../Core/nginx_setup.md).

### Логирование в модуле stream

По умолчанию логирование в модуле `stream` отключено. Настраивается через директиву `access_log`. В этом режиме фиксируются параметры сессии, а не отдельных запросов.

**Ключевые переменные:**

| Переменная | Описание |
| :--- | :--- |
| `$remote_addr` / `$remote_port` | IP-адрес и порт клиента. |
| `$time_local` | Локальное время в формате `dd/mmm/yyyy:hh:mm:ss`. |
| `$protocol` | Используемый протокол (`TCP` или `UDP`). |
| `$status` | Статус сессии (`200` — успешно, `403` — доступ запрещен, `500` — внутренняя ошибка). |
| `$bytes_sent` / `$bytes_received` | Количество отправленных/полученных байтов. |
| `$session_time` | Продолжительность сессии в секундах с точностью до миллисекунд. |
| `$upstream_addr` | IP и порт бэкенда, обработавшего сессию. |
| `$upstream_connect_time` | Время установления соединения с бэкендом. |
| `$upstream_first_byte_time` | Время до получения первого байта данных от бэкенда. |
| `$ssl_preread_server_name` | Имя сервера из SNI (требует `ssl_preread on`). |
| `$ssl_preread_protocol` | Самая высокая версия протокола SSL/TLS, поддерживаемая клиентом. |
| `$ssl_preread_alpn_protocols` | Список протоколов ALPN, присланных клиентом. |

### Безопасность и контроль доступа

В модуле `stream` доступны стандартные механизмы ограничения доступа по IP-адресам, аналогичные модулю `http`.

```nginx
server {
    listen 12345;

    allow 192.168.1.0/24;
    allow 10.0.0.0/8;
    deny all;

    proxy_pass backend_service;
}
```

### Ограничение подключений

В контексте `stream` можно ограничивать количество одновременных подключений (`limit_conn`), но нельзя ограничить частоту запросов (`limit_req`), так как на этом уровне понятие HTTP-запроса отсутствует.

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=per_ip:10m;

    server {
        listen 12345;
        limit_conn per_ip 10; # До 10 подключений с одного IP
        proxy_pass backend_service;
    }
}
```

> **Примечание:** В отличие от HTTP-блока, в `stream` директива `limit_conn` применяется к TCP/UDP-сессиям, а не к запросам.

### Оптимизация производительности

Для высоконагруженных L4-сервисов (например, прокси для баз данных) критически важна минимальная задержка и эффективное использование ресурсов.

**Директивы оптимизации:**

| Директива | Описание | Рекомендация |
| :--- | :--- | :--- |
| `tcp_nodelay on;` | Отключает алгоритм Нагла (Nagle). По умолчанию `on`. | Критично для интерактивных протоколов и БД. |
| `proxy_buffer_size <size>;` | Размер буфера для чтения заголовков ответа. | Обычно 16k достаточно; увеличивать для больших заголовков. |
| `proxy_download_rate` / `proxy_upload_rate` | Ограничение скорости передачи данных на уровне сессии. | Использовать для защиты от исчерпания полосы. |
| `proxy_bind <address> [transparent];` | Привязка исходящих соединений к конкретному IP. `transparent` позволяет бэкенду видеть IP клиента. | Требует настройки маршрутизации на уровне ОС. |
| `proxy_requests <number>;` | (UDP) Количество клиентских запросов, после которых сессия закрывается. | Обязательно для UDP-сервисов. |
| `listen ... deferred;` | (Linux) Включает `TCP_DEFER_ACCEPT`. | Полезно для минимизации ложных соединений. |
| `worker_processes auto;` | Масштабирование на все ядра CPU. | Стандарт для производительности. |

## Практические сценарии

### Проксирование PostgreSQL (TCP) с балансировкой Master/Slave

Сценарий распределения нагрузки между master-сервером БД (для записи) и slave-серверами (для чтения).

**Пример конфигурации (`/etc/nginx/stream.d/postgresql.conf`):**

```nginx
# Группа для мастера (запись)
upstream pg_master {
    server 10.0.0.10:5432 max_fails=3 fail_timeout=30s;
}

# Группа для слейвов (чтение)
upstream pg_slave {
    zone pg_slave_zone 64k;
    server 10.0.0.11:5432 weight=2 max_fails=3 fail_timeout=30s;
    server 10.0.0.12:5432 weight=1 max_fails=3 fail_timeout=30s;
}

# Сервер для записи (Master)
server {
    listen 5433;
    proxy_pass pg_master;
    proxy_connect_timeout 1s;
    proxy_timeout 1h;

    limit_conn_zone $binary_remote_addr zone=per_ip_master:10m;
    limit_conn per_ip_master 5;
}

# Сервер для чтения (Slaves)
server {
    listen 5434;
    proxy_pass pg_slave;
    proxy_connect_timeout 5s;
    proxy_timeout 1h;
}
```

**Разбор конфигурации:**

1.  **Таймауты:**
    - `proxy_connect_timeout` — время ожидания установления TCP-соединения с бэкендом (по умолчанию `60s`).
    - `proxy_timeout` — время между двумя операциями чтения или записи (по умолчанию `10m`). Для БД и SSH важно ставить большие значения (часы), чтобы избежать обрыва длинных сессий.
2.  **Health Checks:**
    - **Пассивные проверки (OSS):** Nginx отслеживает ошибки соединения. Если сервер не отвечает `max_fails` раз в течение `fail_timeout`, он помечается как недоступный.
    - **Активные проверки (Angie/Nginx Plus):** Nginx сам отправляет периодические запросы («пробы») к бэкендам через директиву `health_check`.
3.  **Ограничения:** `limit_conn` предотвращает исчерпание пула соединений БД одним клиентом.

### Проксирование MySQL (TCP) с балансировкой Master/Slave

Аналогично PostgreSQL, но с учетом особенностей MySQL-протокола.

```nginx
upstream mysql_master {
    server 10.0.0.10:3306 max_fails=3 fail_timeout=30s;
}

upstream mysql_slave {
    zone mysql_slave_zone 64k;
    server 10.0.0.11:3306 weight=2 max_fails=3 fail_timeout=30s;
    server 10.0.0.12:3306 weight=1 max_fails=3 fail_timeout=30s;
}

server {
    listen 3307;
    proxy_pass mysql_slave;
    proxy_connect_timeout 5s;
    proxy_timeout 1h;
}
```

### Проксирование DNS (UDP)

Nginx может проксировать UDP-трафик, например для DNS-серверов.

```nginx
# /etc/nginx/stream.d/udp_dns.conf
upstream dns_servers {
    zone dns_upstreams 64k;
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp;
    listen 53 tcp;

    proxy_responses 1; # Ожидание одного ответа от бэкенда
    proxy_timeout 3s;

    proxy_pass dns_servers;
}
```

**Особенности:**

- `listen ... udp` — указывает на прослушивание UDP-трафика.
- `proxy_responses <number>` — задает количество ожидаемых ответов от бэкенда перед закрытием UDP-сессии.
- `proxy_requests <number>` — задает количество запросов от клиента, после которых сессия закрывается.
- `proxy_timeout` — для UDP определяет время ожидания ответа.

### Проксирование SSH

Проксирование SSH через Nginx позволяет централизовать доступ к внутренним серверам, логировать сессии и ограничивать подключения.

```nginx
upstream ssh_cluster {
    zone ssh_zone 64k;
    server 10.0.0.20:22;
    server 10.0.0.21:22 backup; # Резервный сервер
}

server {
    listen 2222 tcp;

    limit_conn_zone $binary_remote_addr zone=per_ip_ssh:10m;
    limit_conn per_ip_ssh 3;

    proxy_pass ssh_cluster;
    proxy_timeout 1h;
    proxy_connect_timeout 5s;
}
```

### Маршрутизация на основе SNI и ALPN (Nginx 1.25.5+)

С версии 1.25.5 Nginx поддерживает виртуальные серверы в модуле `stream` через SNI. Также можно использовать переменные `ssl_preread` для сложной маршрутизации через `map`.

```nginx
stream {
    ssl_preread on;

    map $ssl_preread_alpn_protocols $backend_pool {
        "h2"      http2_backend;
        "http/1.1" http1_backend;
        default    generic_backend;
    }

    server {
        listen 443;
        server_name db.example.com;
        proxy_pass db_backend;
    }

    server {
        listen 443;
        proxy_pass $backend_pool;
    }
}
```

Это позволяет использовать один IP и порт 443 для проксирования разных TCP-сервисов, разделяя их по доменному имени или версии протокола.

### Передача соединения между модулями (pass)

Модуль `ngx_stream_pass_module` позволяет передать принятое соединение в другой модуль (http, mail) напрямую. Это эффективнее, чем `proxy_pass` на локальный адрес.

```nginx
stream {
    server {
        listen 443 ssl;
        ssl_certificate /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;

        pass 127.0.0.1:8000;
    }
}

http {
    server {
        listen 127.0.0.1:8000;
        location / {
            return 200 "Hello from HTTP via Stream pass!";
        }
    }
}
```

### SSL/TLS терминация на L4

Nginx принимает зашифрованные соединения, расшифровывает их и проксирует трафик в открытом виде на бэкенд.

```nginx
# /etc/nginx/stream.d/ssl_termination.conf
upstream web_backend {
    server 127.0.0.1:9001;
}

server {
    listen 9443 ssl;
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    proxy_pass web_backend;
}
```

### SSL Pre-read (маршрутизация TLS vs SSH)

Функция SSL Pre-read позволяет Nginx анализировать начало TCP-соединения (Client Hello) и определять тип трафика или имя сервера (SNI) без терминации SSL.

**Пример: мультиплексирование HTTPS и SSH на порту 443**

```nginx
# /etc/nginx/stream.d/ssl_preread.conf
map $ssl_preread_server_name $backend_by_sni {
    hostnames;
    default         ssh_backend;
    www.example.com http_backend;
}

upstream http_backend { server 127.0.0.1:8080; }
upstream ssh_backend { server 127.0.0.1:22; }

server {
    listen 443;
    ssl_preread on;
    proxy_pass $backend_by_sni;
}
```

### Использование Proxy Protocol

Proxy Protocol передает исходный IP клиента через прокси к бэкенду. Подробнее: [Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md).

```nginx
# Фронтенд-балансировщик
server {
    listen 982;
    proxy_pass 127.0.0.1:820 proxy_protocol;
}

# Бэкенд-сервер (другой Nginx)
server {
    listen 820 proxy_protocol;

    set_real_ip_from 127.0.0.0/8;
    real_ip_header proxy_protocol;

    access_log /var/log/nginx/proxy-protocol-access.log basic;
}
```

## Операции и команды

### Валидация конфигурации

```bash
# Проверка синтаксиса перед применением
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Применение изменений без потери соединений (graceful reload)
nginx -s reload
# → signal reload started
```

### Диагностика upstream через переменные в логах

Добавьте в `log_format` upstream-переменные для трассировки L4-сессий:

```nginx
log_format upstream_debug '$remote_addr - [$time_local] '
                          '$upstream_addr $upstream_status $upstream_response_time';
```

Ключевые переменные upstream для L4:

| Переменная | Описание |
| :--- | :--- |
| `$upstream_addr` | IP и порт бэкенда, обработавшего сессию. |
| `$upstream_connect_time` | Время установки TCP-соединения с бэкендом. |
| `$upstream_first_byte_time` | Время до получения первого байта данных от бэкенда. |
| `$upstream_bytes_sent` | Объем данных, отправленных бэкенду. |
| `$upstream_bytes_received` | Объем данных, полученных от бэкенда. |

### Анализ логов и статистики

```bash
# Распределение сессий по бэкендам (требуется $upstream_addr в логе)
awk '{print $NF}' /var/log/nginx/stream-access.log | sort | uniq -c | sort -rn | head -n 10
# → 1500 10.0.0.1:5432
# → 1480 10.0.0.2:5432

# Поиск сессий с аномально долгим ответом бэкенда
awk '$upstream_first_byte_time > 1.0 {print $0}' /var/log/nginx/stream-access.log | head -n 20

# Поиск ошибок upstream в логе ошибок
grep -E "upstream|connect() failed|connection refused" /var/log/nginx/error.log | tail -n 50

# Проверка TCP-соединений к бэкенду
ss -tnp | grep nginx | grep :5432
# → ESTAB 0 0 10.0.0.5:54322 10.0.0.1:5432 users:(("nginx",pid=1234,fd=5))
```

### Проверка состояния upstream (Angie / Nginx Plus)

```bash
# Запрос детальной статистики через REST API (Angie / Nginx Plus)
curl -s http://127.0.0.1:8080/api/6/http/upstreams/pg_slave
# → JSON с метриками по каждому бэкенду: active connections, responses, errors

# Проверка stub_status (Nginx OSS, только для http-блока)
curl -s http://127.0.0.1:8080/nginx_status
# → Active connections: 2
```

### Тестирование failover

```bash
# Остановить один бэкенд и проверить переключение
systemctl stop postgresql@node1

# Проверить, что сессии идут на оставшиеся узлы
tail -f /var/log/nginx/stream-access.log

# Вернуть узел и проверить, что Nginx снова начал отправлять на него трафик
systemctl start postgresql@node1
```

## Диагностика и устранение неполадок

### Типичные ошибки L4

| Симптом | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| `connection refused` на все сессии | Все бэкенды недоступны или `upstream` указан с ошибкой | `nc -zv 10.0.0.10 5432` — проверить доступность бэкенда; `nginx -T \| grep upstream` — проверить конфигурацию |
| `connection refused` на отдельные сессии | Один бэкенд недоступен, исчерпан `max_conns` или сработал `fail_timeout` | `grep` в `error.log` за записи о маркировке `down`; проверить, не установлен ли флаг `down` вручную |
| Таймаут сессии | Бэкенд не ответил за `proxy_timeout`; утечка соединений на бэкенде | Увеличить `proxy_timeout`; `ss -s` — проверить количество сокетов в `TIME_WAIT`; проверить нагрузку на бэкенд (`top`, `htop`) |
| `503 Service Unavailable` при нагрузке | Все серверы достигли лимитов соединений | Увеличить `limit_conn`; добавить серверы в `upstream`; проверить `worker_connections` |
| Дисбаланс нагрузки | Неправильный `weight`, `ip_hash` за NAT, `least_conn` с быстрыми ошибками | Проверить веса; исключить неработающие бэкенды через `max_fails` |
| Нет доступа к порту снаружи | Файрвол блокирует порт, Nginx не слушает ожидаемый интерфейс | `ss -tlnp \| grep nginx`; `iptables -L -n` или `firewall-cmd --list-all` |
| `upstream sent too big header` | Бэкенд прислал слишком много заголовков | Увеличить `proxy_buffer_size` и `proxy_buffers` |
| `no user in group list` при запуске | Пользователь, указанный в `user`, не существует | `id nginx` — проверить наличие пользователя; `cat /etc/group` — проверить группы |
| Потеря пакетов UDP | `proxy_requests` слишком мал, `proxy_timeout` исчерпан | Увеличить `proxy_timeout`; проверить `proxy_requests` |
| `SSL_do_handshake` failed | Несовпадение версий TLS, неверный сертификат, закрытый порт | `openssl s_client -connect host:port`; проверить `ssl_certificate` и `ssl_certificate_key` |

### Диагностические команды

```bash
# Фактическая конфигурация upstream (распарсенная nginx)
nginx -T | grep -A 20 "upstream"

# Проверка, что Nginx слушает ожидаемые порты
ss -tlnp | grep nginx

# Поиск ошибок SSL между Nginx и бэкендом
grep -E "SSL_do_handshake|certificate verify failed" /var/log/nginx/error.log

# Проверка количества соединений Nginx в состоянии TIME_WAIT
ss -ant state time-wait '( dport = :5432 )' | wc -l

# Мониторинг количества открытых файловых дескрипторов nginx
cat /proc/$(pgrep -f "nginx: worker")/limits | grep "open files"
```

## Лучшие практики

### Производительность

1.  **Настраивайте `worker_processes` по количеству ядер CPU.** Используйте `worker_processes auto;` и `worker_cpu_affinity auto;` для привязки воркеров к ядрам, что минимизирует переключения контекста и использует L1/L2 кэши процессора.
2.  **Устанавливайте `worker_rlimit_nofile` минимум в 2× `worker_connections`.** На каждое проксируемое соединение тратятся два дескриптора: клиент + бэкенд.
3.  **Используйте `zone` для всех upstream-групп.** Без `zone` Nginx не сохраняет состояние соединений между рабочими процессами, что приводит к некорректной балансировке.
4.  **Включайте `tcp_nodelay on;` для интерактивных протоколов и БД.** Отключение алгоритма Нагла снижает задержку при передаче небольших пакетов.
5.  **Для UDP-сервисов всегда указывайте `proxy_timeout` и `proxy_requests`.** Без этих параметров UDP-сессия может висеть открытой indefinitely, приводя к утечке ресурсов.

### Эксплуатация (SRE)

1.  **Логируйте upstream-переменные в stream-логах.** Добавьте `$upstream_addr`, `$upstream_connect_time`, `$upstream_first_byte_time` в `log_format`. Это основа для трассировки запросов и расчета SLA.
2.  **Настраивайте алертинг на рост `fail_timeout` срабатываний.** Частые переключения бэкендов указывают на нестабильность инфраструктуры. Используйте `error.log` и access-логи.
3.  **Тестируйте failover регулярно.** Периодически проверяйте, что `max_fails` и `fail_timeout` корректно переключают трафик при отключении бэкенда. Документируйте RTO (Recovery Time Objective) для сценариев отказа.
4.  **Мониторите дисбаланс.** Дисбаланс более чем на 20% при использовании Round Robin или `least_conn` указывает на проблему с весами или медленный бэкенд.
5.  **Резервное копирование конфигурации.** Перед изменением алгоритмов или параметров upstream создайте бэкап и проверяйте конфигурацию через `nginx -t`.
6.  **Изолируйте management-интерфейсы.** Если используете `stub_status` или REST API (Angie/Plus), ограничьте доступ к ним firewall-правилами или директивами `allow/deny`.
7.  **Используйте `status_zone` (Angie/Nginx Plus) для детальной статистики.** Это позволяет собирать метрики по каждому upstream и виртуальному хосту без сторонних модулей.

### Безопасность

1.  **Никогда не полагайтесь на L4-балансировку как на механизм безопасности.** Для контроля доступа используйте `allow`/`deny`, `limit_conn` или отдельный фаервол.
2.  **Явно указывайте `max_fails` и `fail_timeout`** для каждого сервера в `upstream`. Без этих параметров Nginx по умолчанию использует `max_fails=1` и `fail_timeout=10s`, что может привести к частым переключениям при временных сбоях.
3.  **Не используйте `backup`-серверы для активной нагрузки.** Они предназначены только для аварийного переключения и имеют более низкий приоритет.
4.  **Ограничивайте количество соединений с одного IP.** Используйте `limit_conn_zone` и `limit_conn` для защиты от DDoS и исчерпания пула соединений.
5.  **Используйте `proxy_bind transparent` с осторожностью.** Этот параметр позволяет бэкенду видеть реальный IP клиента, но требует корректной настройки маршрутизации на уровне ОС и может быть небезопасен.

## Дополнительная информация

### См. также

- [Установка и базовая настройка Nginx](../Core/nginx_setup.md) — структура конфигурации, блок `stream`, системные лимиты.
- [Балансировка и проксирование L4 в Angie](../../Angie/l4_balancing_and_proxying.md) — Angie-расширения: активные проверки, `status_zone`, slow start.
- [Мониторинг Nginx с VTS, Prometheus и Grafana](../Operations/nginx_vts_monitoring_setup.md) — детальная статистика по виртуальным хостам и upstream-группам.
