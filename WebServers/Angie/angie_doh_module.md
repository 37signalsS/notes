# DNS over HTTPS (DoH) в Angie: модуль ngx_http_doh_module

**Актуально для:** Angie 1.12.x (модуль включен в базовую поставку начиная с Angie 1.12.0)

## Определения

**Модуль `doh` (`ngx_http_doh_module`)** — встроенный модуль HTTP-подсистемы веб-сервера Angie (начиная с версии 1.12.0), реализующий шлюз DNS over HTTPS (DoH) в соответствии со спецификацией RFC 8484. Принимает DNS-запросы от клиентов по безопасным протоколам HTTP/1.1, HTTP/2 и HTTP/3 (QUIC), транслирует их вышестоящим DNS-серверам (BIND, Unbound, PowerDNS, Knot, CoreDNS) по классическим сетевым протоколам UDP или TCP (порт 53) и возвращает клиентам сформированные ответы.

**DoH (DNS over HTTPS, RFC 8484)** — протокол безопасной инкапсуляции DNS-сообщений в поток HTTPS (порт 443/TCP, 443/UDP при HTTP/3). Защищает DNS-трафик от перехвата, модификации (DNS spoofing/poisoning) и транзитной цензуры провайдерами связи на участке между клиентом (браузер, stub-резолвер операционной системы) и промежуточным шлюзом.

**Формат DNS Wire Format (`application/dns-message`)** — бинарный формат представления DNS-сообщений (RFC 1035), используемый в качестве MIME-типа тела запросов и ответов в протоколе DoH. Передаётся в теле HTTP POST-запроса в исходном бинарном виде либо в параметре строки запроса `?dns=<base64url>` при использовании метода GET.

**Query ID Randomization** — защитный механизм Angie, заменяющий оригинальный двухбайтовый идентификатор транзакции (`ID`) в заголовке DNS-запроса псевдослучайным значением перед отправкой на upstream-сервер и восстанавливающий исходный клиентский ID в ответе. Защищает DNS-сессию от атак подделки ответов со стороны неавторизованных узлов (off-path response spoofing) при использовании ненадежного UDP-транспорта.

**Прозрачная привязка (`doh_bind ... transparent`)** — механизм сетевого уровня Linux (`IP_TRANSPARENT`), позволяющий процессам Angie отправлять DNS-пакеты к upstream-серверам от имени реального IP-адреса удаленного клиента (`$remote_addr`). Применяется в корпоративных сетях для сохранения аналитики, работы Split-Horizon DNS и распределения политик (Views/ACL) на внутренних DNS-серверах.

**Keepalive Connection Pooling (DNS over TCP)** — пул постоянно открытых TCP-соединений между Angie и upstream-резолверами, исключающий накладные расходы на трёхстороннее рукопожатие (3-way handshake) при обработке очередей запросов по протоколу TCP.

---

## Базовые концепции и архитектура

### Архитектура и принцип работы

Модуль `ngx_http_doh_module` функционирует внутри контекста `http` веб-сервера Angie и выступает в роли специализированного прокси-терминатора L7:

```
[ Клиент (Браузер / ОС / stub-резолвер) ]
                 │
                 │ HTTPS (HTTP/2 / HTTP/3 QUIC)
                 ▼
[ Angie (DoH Gateway, порт 443) ]
  ├── 1. TLS Termination & HTTP Decoding
  ├── 2. Rate Limiting (limit_req) & ACL (allow/deny)
  ├── 3. Валидация размера сообщения (doh_max_size)
  ├── 4. Randomization Query ID (защита от spoofing)
  ├── 5. Выбор upstream по алгоритмам балансировки
                 │
                 ├── UDP 53 (по умолчанию / быстрый путь)
                 └── TCP 53 (Keepalive пул / fallback при TC=1)
                 ▼
[ Upstream DNS Cluster (BIND / Unbound / Knot / PowerDNS) ]
                 │
                 │ Ответ DNS (wire format)
                 ▼
[ Angie ]
  ├── 6. Проверка валидности ответа (RCODE, длина)
  ├── 7. Восстановление исходного Query ID клиента
  ├── 8. Извлечение min(TTL) -> генерация заголовка Cache-Control
  └── 9. Установка Content-Type: application/dns-message
                 │
                 │ HTTP 200 OK + Payload
                 ▼
[ Клиент (получение готового DNS-ответа) ]
```

### Обработка HTTP-методов и структуры сообщений

1. **Метод POST:**
   - Клиент передает бинарное DNS-сообщение в теле HTTP-запроса с заголовком `Content-Type: application/dns-message`.
   - Angie считывает тело запроса, проверяет его размер на соответствие директиве `doh_max_size` (по умолчанию размер страницы оперативной памяти — 4 КБ) и пересылает полезную нагрузку в upstream-сокет.
2. **Метод GET:**
   - Клиент передает DNS-запрос через аргумент строки запроса `dns` в формате Base64URL без знаков заполнения (`=`):
     `https://doh.example.com/dns-query?dns=AAABAAABAAAAAAAAA3d3dwdleGFtcGxlA2NvbQAAAQAB`
   - Angie декодирует Base64URL в бинарный wire format и передает на DNS-сервер.
3. **Обработка DNS-статусов (RCODE) и HTTP-кодов:**
   - В соответствии с RFC 8484, если upstream-сервер вернул DNS-ответ с ненулевым статусом (например, `NXDOMAIN`, `SERVFAIL`, `REFUSED`), Angie **возвращает клиенту HTTP-статус 200 OK**. Значение `RCODE` сохраняется внутри бинарного DNS-сообщения.
   - Ненулевой `RCODE` является корректным DNS-ответом и **не вызывает** повторную попытку опроса следующего сервера по условию `invalid_response` директивы `doh_next_upstream`.
4. **Управление кэшированием и заголовками:**
   - Angie автоматически парсит ответ DNS, определяет минимальный TTL среди всех возвращенных ресурсных записей (секций Answer, Authority, Additional) и формирует заголовок ответа `Cache-Control: max-age=<min_ttl>`.
   - Если записи не содержат валидного TTL или ответ пуст, выставляется `Cache-Control: no-store`.
   - Модуль самостоятельно устанавливает заголовок `Content-Type: application/dns-message`. В ручном добавлении заголовка через директиву `add_header` нет необходимости.

### Транспортная модель работы с апстримами (`doh_transport`)

Директива `doh_transport` определяет выбор сетевого протокола при обращении к DNS-серверам:

*   `auto` (по умолчанию): если в пуле `keepalive` группы `upstream` есть готовое свободное TCP-соединение, запрос направляется по TCP. Если свободного соединения нет, запрос отправляется по UDP. Если DNS-сервер вернул ответ с установленным флагом усечения `TC` (Truncated, когда размер DNS-ответа превышает 512 байт без EDNS0 или лимит буфера EDNS0), Angie автоматически повторяет запрос к этому же серверу по TCP.
*   `udp`: все запросы отправляются исключительно по UDP. В случае получения усеченного ответа (`TC=1`) ситуация считается ошибкой, и повторный запрос по TCP не выполняется.
*   `tcp`: все запросы к DNS-серверам передаются строго по протоколу TCP. Режим устраняет проблемы с фрагментацией UDP в нестабильных сетях, но требует обязательной настройки пула `keepalive` в блоке `upstream` во избежание деградации производительности.

### Защита от подделки запросов (Query ID Randomization)

В классическом DNS по UDP существует риск атак подделки пакетов (DNS Cache Poisoning / Kaminsky attack). Модуль `doh` в Angie генерирует случайный идентификатор транзакции при отправке UDP-дейтаграммы на апстрим и восстанавливает оригинальный ID клиента перед отправкой HTTPS-ответа.

> [!NOTE]
> Встроенный генератор случайных чисел для Query ID не является криптографически стойким. DNS-серверы, на которые проксируются запросы, должны размещаться в доверенной сети (localhost, локальная сеть предприятия, изолированный VLAN) под вашим полным контролем.

### Директивы модуля

| Директива | Контекст | Значение по умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| `doh_pass` | `location`, `if in location` | — | Задает адрес DNS-сервера (IP:порт, доменное имя) или имя upstream-группы. Единственная обязательная директива в location. |
| `doh_transport` | `http`, `server`, `location` | `auto` | Выбирает транспортный протокол взаимодействия с DNS-сервером: `auto`, `udp` или `tcp`. |
| `doh_bind` | `http`, `server`, `location` | `off` | Привязывает исходящие соединения к конкретному локальному IP-адресу. Параметр `transparent` включает отправку от имени `$remote_addr`. |
| `doh_buffer_size` | `http`, `server`, `location` | `16k` | Размер буфера для чтения DNS-ответа от апстрима (минимум 512 байт). |
| `doh_max_size` | `http`, `server`, `location` | размер страницы ОС (4 КБ) | Максимальный допустимый размер входящего DNS-сообщения от клиента (минимум 12 байт). |
| `doh_connect_timeout`| `http`, `server`, `location` | `60s` | Таймаут установки соединения с DNS-сервером по TCP. Не влияет на время удержания в пуле keepalive. |
| `doh_send_timeout` | `http`, `server`, `location` | `60s` | Таймаут передачи запроса DNS-серверу между двумя последовательными операциями записи. |
| `doh_read_timeout` | `http`, `server`, `location` | `60s` | Таймаут ожидания ответа от DNS-сервера между двумя последовательными операциями чтения. |
| `doh_socket_keepalive`| `http`, `server`, `location` | `off` | Включает опцию `SO_KEEPALIVE` для исходящих TCP-сокетов к DNS-серверу. |
| `doh_next_upstream` | `http`, `server`, `location` | `error timeout` | Условия переключения на следующий сервер upstream-группы: `error`, `timeout`, `invalid_response`, `off`. |
| `doh_next_upstream_tries` | `http`, `server`, `location` | `0` | Лимит количества попыток передачи запроса другим серверам группы (`0` — без ограничений). |
| `doh_next_upstream_timeout`| `http`, `server`, `location` | `0` | Максимальное суммарное время для повторных попыток переключения на следующий сервер (`0` — отключено). |

---

## Практические сценарии

### Сценарий 1: Корпоративный отказоустойчивый DoH-шлюз (Production Baseline)

Организация защищенного шлюза с поддержкой HTTP/2 и HTTP/3, кластером локальных DNS-резолверов (BIND/Unbound), пулом постоянных соединений и контролем таймаутов.

```nginx
http {
    # Пул локальных upstream DNS-серверов
    upstream dns_resolvers {
        server 127.0.0.1:53   max_fails=3 fail_timeout=10s;
        server 192.168.1.10:53 max_fails=3 fail_timeout=10s;
        server 192.168.1.11:53 backup;

        # Пул постоянных TCP-соединений для doh_transport auto / tcp
        keepalive 64;
        keepalive_requests 10000;
        keepalive_timeout 60s;
    }

    server {
        # Поддержка классического TLS и QUIC (HTTP/3)
        listen 443 ssl;
        listen 443 quic reuseport;
        server_name doh.corp.internal;

        # TLS-сертификаты
        ssl_certificate     /etc/ssl/angie/doh.corp.internal.crt;
        ssl_certificate_key /etc/ssl/angie/doh.corp.internal.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;

        # Анонс поддержки HTTP/3 клиентам через заголовок Alt-Svc
        add_header Alt-Svc 'h3=":443"; ma=86400';

        # Основная точка обработки DoH-запросов по RFC 8484
        location /dns-query {
            doh_pass dns_resolvers;

            # Автоматический транспорт: UDP для быстрых запросов,
            # TCP из пула keepalive либо fallback при усечении (TC=1)
            doh_transport auto;

            # Оптимизация таймаутов для быстрого отказа и переключения
            doh_connect_timeout       2s;
            doh_send_timeout          3s;
            doh_read_timeout          3s;

            # Переключение на следующий сервер при сбоях и невалидных ответах
            doh_next_upstream         error timeout invalid_response;
            doh_next_upstream_tries   3;
            doh_next_upstream_timeout 5s;

            # Ограничение размера DNS-запроса (защита от переполнения буфера)
            doh_max_size              4k;
            doh_buffer_size           16k;

            # Отключение логирования успешных DNS-запросов для снижения IOPS
            # или перенаправление в отдельный буферизованный лог
            access_log /var/log/angie/doh_access.log combined buffer=64k flush=5s;
        }
    }
}
```

### Сценарий 2: Защита от DoS, ограничение методов и списки доступа (ACL)

DoH-серверы часто подвергаются атакам типа «отказ в обслуживании» (DoS) и попыткам генерации паразитного трафика. В данном сценарии настраивается жесткий Rate Limiting, ограничение HTTP-методов и допуск только доверенных подсетей.

```nginx
http {
    # Зона ограничения частоты запросов: 50 запросов в секунду на один IP-адрес
    limit_req_zone $binary_remote_addr zone=doh_req_limit:10m rate=50r/s;
    # Зона ограничения параллельных соединений
    limit_conn_zone $binary_remote_addr zone=doh_conn_limit:10m;

    upstream local_unbound {
        server 127.0.0.1:53;
        keepalive 32;
    }

    server {
        listen 443 ssl;
        server_name doh.example.com;

        ssl_certificate     /etc/ssl/angie/doh.crt;
        ssl_certificate_key /etc/ssl/angie/doh.key;

        location /dns-query {
            # 1. Списки доступа: разрешаем корпоративные сети, запрещаем остальные
            allow 10.0.0.0/8;
            allow 172.16.0.0/12;
            allow 192.168.0.0/16;
            allow 127.0.0.1;
            deny all;

            # 2. Ограничение HTTP-методов: только GET и POST регламентированы RFC 8484
            limit_except GET POST {
                deny all;
            }

            # 3. Лимиты соединений и частоты запросов
            limit_req zone=doh_req_limit burst=20 nodelay;
            limit_conn doh_conn_limit 10;
            limit_req_status 429;
            limit_conn_status 429;

            doh_pass local_unbound;
            doh_transport auto;
            doh_max_size 4k;
        }
    }
}
```

### Сценарий 3: Прозрачное проксирование IP-адреса клиента (`doh_bind ... transparent`)

В архитектурах со Split-Horizon DNS, BIND Views или фильтрацией на основе GeoIP вышестоящему DNS-серверу требуется реальный IP-адрес клиента. С помощью параметра `transparent` исходящие дейтаграммы отправляются с оригинальным адресом источника.

#### 1. Системные требования ядра Linux и права процесса

Для работы `transparent` worker-процессам Angie требуются привилегии `CAP_NET_RAW` и `CAP_NET_ADMIN`. В дистрибутивах Linux с systemd переопределите параметры сервиса:

```bash
# Создание override-файла для сервиса Angie
sudo systemctl edit angie
```

Добавьте блок наделения правами:

```ini
[Service]
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
```

#### 2. Маршрутизация ответов в сетевом стеке Linux (Policy Routing)

Так как пакеты отправляются от IP-адреса клиента, обратные ответы от DNS-сервера должны заворачиваться обратно в стек сокетов Angie через таблицу маршрутизации:

```bash
# Создание правила маршрутизации для локально перехватываемого трафика
sudo ip rule add fwmark 1 lookup 100
sudo ip route add local 0.0.0.0/0 dev lo table 100

# Маркировка пакетов через iptables (или nftables)
sudo iptables -t mangle -A PREROUTING -p udp --sport 53 -j MARK --set-mark 1
sudo iptables -t mangle -A PREROUTING -p tcp --sport 53 -j MARK --set-mark 1
```

#### 3. Конфигурация в Angie

```nginx
http {
    upstream authoritative_dns {
        server 192.168.10.5:53;
        keepalive 16;
    }

    server {
        listen 443 ssl;
        server_name doh.example.com;

        ssl_certificate     /etc/ssl/angie/doh.crt;
        ssl_certificate_key /etc/ssl/angie/doh.key;

        location /dns-query {
            # Проксирование с подменой IP источника на реальный адрес клиента
            doh_bind $remote_addr transparent;

            doh_pass authoritative_dns;
            doh_transport tcp; # Для прозрачного TCP-проксирования
            doh_socket_keepalive on;
        }
    }
}
```

### Сценарий 4: DoH с автоматическими сертификатами через модуль ACME

Использование встроенного в Angie клиента [ACME](./angie_acme_module.md) позволяет полностью отказаться от внешних скриптов ротации сертификатов (Certbot, `acme.sh`) и обновлять TLS-сертификаты в оперативной памяти на лету без перезагрузки процессов.

```nginx
http {
    resolver 127.0.0.1 valid=300s;

    # Настройка встроенного ACME-клиента
    acme_client letsencrypt_doh {
        directory https://acme-v02.api.letsencrypt.org/directory;
        challenge http;
        key_type  ecdsa;
        renew     14d;
        contact   mailto:admin@example.com;
    }

    upstream local_dns {
        server 127.0.0.1:53;
        keepalive 32;
    }

    server {
        listen 80;
        server_name doh.example.com;

        # Активация обработчика проверок HTTP-01
        acme letsencrypt_doh;

        # Перенаправление клиентского трафика на HTTPS
        location / {
            return 301 https://$host$request_uri;
        }
    }

    server {
        listen 443 ssl;
        listen 443 quic reuseport;
        server_name doh.example.com;

        # Использование динамических переменных сертификатов ACME
        acme letsencrypt_doh;
        ssl_certificate     $acme_cert_letsencrypt_doh;
        ssl_certificate_key $acme_cert_key_letsencrypt_doh;

        location /dns-query {
            doh_pass local_dns;
            doh_transport auto;
        }
    }
}
```

### Сценарий 5: Метрики и структурированное логирование для SRE-мониторинга

Организация сбора метрик производительности DoH (задержка ответов апстримов, распределение HTTP-кодов, объемы переданных данных) для передачи в Prometheus и Grafana.

```nginx
http {
    # Формат структурированного JSON-логирования
    log_format doh_json escape=json '{'
        '"time_local":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request_method":"$request_method",'
        '"request_uri":"$request_uri",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_length":$request_length,'
        '"request_time":$request_time,'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"upstream_response_time":"$upstream_response_time",'
        '"pipe":"$pipe"'
    '}';

    upstream dns_pool {
        server 127.0.0.1:53;
    }

    server {
        listen 443 ssl;
        server_name doh.example.com;

        ssl_certificate     /etc/ssl/angie/doh.crt;
        ssl_certificate_key /etc/ssl/angie/doh.key;

        location /dns-query {
            doh_pass dns_pool;
            access_log /var/log/angie/doh_structured.log doh_json;
        }

        # Эндпоинт экспорта метрик для Prometheus (внутренний порт или IP)
        location /metrics {
            allow 127.0.0.1;
            allow 192.168.1.0/24;
            deny all;

            prometheus all;
        }
    }
}
```

---

## Операции и команды

### Проверка синтаксиса и перезагрузка службы

```bash
# Валидация синтаксиса конфигурационных файлов Angie
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Бесшовная перезагрузка конфигурации (graceful reload)
sudo systemctl reload angie

# Проверка статуса сервиса
sudo systemctl status angie
# → Active: active (running) since Tue 2026-10-14 10:00:00 MSK; 3h 40min ago
```

### Тестирование через `dig` с поддержкой DoH (BIND 9.18+)

Современные версии утилиты `dig` поддерживают отправку запросов по протоколам DoH и DoT напрямую:

```bash
# Запрос A-записи домена example.com через DoH-эндпоинт Angie
dig @127.0.0.1 -p 443 example.com A +https +https-paths=/dns-query +tls-ca=/etc/ssl/certs/ca-certificates.crt
# → ;; Got answer:
# → ;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 31456
# → ;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
# → ;; ANSWER SECTION:
# → example.com.        300     IN      A       93.184.215.14
# → ;; Query time: 4 msec
# → ;; SERVER: 127.0.0.1#443(HTTPS)
```

### Тестирование через `kdig` (Knot DNS)

```bash
# Подробный запрос через HTTPS с проверкой TLS-сессии
kdig -d @doh.corp.internal +https=/dns-query example.com A
# → ;; DEBUG: Connecting to 192.168.1.10:443
# → ;; DEBUG: TLS handshake completed
# → ;; From 192.168.1.10@443(HTTPS) in 3.1 ms
# → example.com.        300     IN      A       93.184.215.14
```

### Тестирование через `doggo`

```bash
# Тестирование резолвинга через DoH
doggo example.com --nameserver https://doh.example.com/dns-query
# → NAME          TYPE  CLASS  TTL   ADDRESS
# → example.com.  A     IN     300s  93.184.215.14
```

### Тестирование методом GET по RFC 8484 (`curl`)

Запрос методом GET с Base64URL-кодированным бинарным DNS-пакетом:

```bash
# Запрос A-записи домена www.example.com
curl -v "https://doh.example.com/dns-query?dns=AAABAAABAAAAAAAAA3d3dwdleGFtcGxlA2NvbQAAAQAB"
# → < HTTP/2 200 
# → < content-type: application/dns-message
# → < cache-control: max-age=300
# → < content-length: 49
```

### Тестирование методом POST по RFC 8484 (`curl`)

Отправка бинарного запроса через POST:

```bash
# Генерация бинарного пакета запроса (A-запись example.com) и отправка в POST
printf '\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01' | \
curl -s -X POST --data-binary @- \
     -H "Content-Type: application/dns-message" \
     -H "Accept: application/dns-message" \
     "https://doh.example.com/dns-query" | hexdump -C
# → 00000000  00 00 81 80 00 01 00 01  00 00 00 00 07 65 78 61  |.............exa|
# → 00000010  6d 70 6c 65 03 63 6f 6d  00 00 01 00 01 c0 0c 00  |mple.com........|
# → 00000020  01 00 01 00 00 01 2c 00  04 5d b8 d7 0e           |......,...]...|
```

### Проверка сетевых сокетов и доступности апстримов

```bash
# Проверка слушаемых сетевых портов веб-сервера
ss -tulpn | grep -E 'angie|443'
# → tcp  LISTEN 0  511  0.0.0.0:443  0.0.0.0:*  users:(("angie",pid=1234,fd=6))
# → udp  UNCONN 0  0    0.0.0.0:443  0.0.0.0:*  users:(("angie",pid=1234,fd=7))

# Проверка сетевой связности с upstream DNS-сервером
nc -zvu 127.0.0.1 53
# → Connection to 127.0.0.1 53 port [udp/domain] succeeded!

nc -zvt 127.0.0.1 53
# → Connection to 127.0.0.1 53 port [tcp/domain] succeeded!
```

---

## Устранение неисправностей

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **HTTP 400 Bad Request** | Длина входящего DNS-сообщения меньше 12 байт или превышает лимит `doh_max_size`; некорректный Base64URL в GET-запросе. | `grep -E "doh message is too big|doh.*failed" /var/log/angie/error.log` | Увеличить `doh_max_size` (например, `doh_max_size 8k;`), проверить формат строки запроса клиента. |
| **HTTP 405 Method Not Allowed** | Клиент обратился неподдерживаемым HTTP-методом (PUT, DELETE, HEAD, OPTIONS). | Проверка поля `$request_method` в access-логе. | RFC 8484 регламентирует исключительно методы `GET` и `POST`. Исправить логику клиента. |
| **HTTP 502 Bad Gateway** | Upstream DNS-сервер недоступен, отклонил соединение или вернул поврежденный пакет; сработал `doh_connect_timeout`. | `grep "connect() failed" /var/log/angie/error.log` | Проверить работу BIND/Unbound (`systemctl status named`), убедиться в корректности IP и порта в `upstream`. |
| **HTTP 504 Gateway Timeout** | Апстрим не ответил в пределах `doh_read_timeout` или `doh_send_timeout`. | `grep "upstream timed out" /var/log/angie/error.log` | Проверить сетевые маршруты, загрузку DNS-резолвера или увеличить значения таймаутов `doh_read_timeout 5s;`. |
| **Обрыв больших ответов (Truncated)** | Используется `doh_transport udp;`, а DNS-ответ превышает размер буфера UDP (флаг `TC=1`). | В error.log фиксируется `truncated response`. | Переключить режим на `doh_transport auto;` или `doh_transport tcp;`. |
| **Заголовок `Cache-Control: no-store`** | DNS-ответ содержит ошибку (например, `SERVFAIL`) либо не имеет ресурсных записей с положительным TTL. | Проверить ответ через `dig @upstream domain` на наличие секций Answer и значений TTL. | Это штатное поведение протокола RFC 8484: при невозможности вычислить TTL кэширование запрещается. |
| **Ошибка запуска `doh_bind ... transparent`** | У процесса Angie отсутствуют права `CAP_NET_RAW` / `CAP_NET_ADMIN` в ядре Linux. | В error.log: `bind(...) failed (1: Operation not permitted)`. | Добавить `AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN` в systemd unit Angie, перечитать конфигурацию `systemctl daemon-reload`. |
| **Клиент сообщает об ошибке TLS** | Истек срок действия сертификата, отсутствует промежуточный CA (неполная цепочка). | `openssl s_client -connect doh.example.com:443 -servername doh.example.com` | Обновить сертификат, проверить работу ACME-клиента, объединить промежуточные сертификаты в bundle. |

---

## Лучшие практики

### Производительность и оптимизация сети

1. **Активация HTTP/2 и HTTP/3 (QUIC):**
   DNS-запросы в DoH генерируются пачками при загрузке веб-страниц. HTTP/1.1 с последовательными запросами приводит к задержкам Head-of-Line Blocking. Использование HTTP/2 и HTTP/3 позволяет мультиплексировать десятки DNS-запросов в рамках одной TLS-сессии без накладных расходов.
2. **Использование пула постоянных соединений (`keepalive`):**
   При работе в режимах `doh_transport auto;` и `doh_transport tcp;` обязательно настраивайте `keepalive 32;` (или `64`) в блоке `upstream`. Повторное использование уже открытых TCP-сокетов снижает RTT на величину тройного рукопожатия TCP.
3. **Размещение рекурсора на локальном хосте (`127.0.0.1:53`):**
   Для максимальной скорости размещайте локальный кэширующий DNS-сервер (Unbound или BIND) на том же сервере, где функционирует Angie. Связь через loopback-интерфейс гарантирует сетевую задержку менее 0.5 мс.
4. **Отказ от избыточных директив:**
   Не прописывайте вручную `add_header Content-Type "application/dns-message";` и `add_header Cache-Control ...` внутри DoH-локации. Модуль формирует их автоматически в строгом соответствии с RFC 8484.

### Безопасность

1. **Защита от DNS Amplification и DoS-атак:**
   Ограничивайте частоту запросов с помощью модуля `limit_req` (директива `limit_req zone=doh_limit burst=20 nodelay;`).
2. **Ограничение разрешенных HTTP-методов:**
   Блокируйте любые непредусмотренные методы с помощью `limit_except GET POST { deny all; }`.
3. **Изоляция upstream-сети:**
   Не направляйте DoH-запросы через незащищенный публичный интернет по открытому UDP-порту 53 к сторонним серверам. Внутренний сегмент DNS должен быть защищен или изолирован в локальной сети, так как Query ID Randomization в Angie не является криптографически стойким.
4. **Контроль доступа к приватным резолверам:**
   Если DoH-сервер обслуживает внутреннюю инфраструктуру компании, используйте директивы `allow` и `deny` либо взаимную аутентификацию по клиентским сертификатам mTLS (`ssl_verify_client on;`).

---

## Дополнительная информация

### Требования к сборке и операционной системе

*   **Версия:** Модуль `ngx_http_doh_module` доступен в веб-сервере Angie начиная с версии **1.12.0**.
*   **Сборка:** Входит в состав стандартных бинарных deb/rpm-пакетов и официальных Docker-образов. При ручной сборке из исходников компилируется автоматически; отключается параметром `./configure --without-http_doh_module`.
*   **Совместимость с ОС:** Linux (ядра 3.x, 4.x, 5.x, 6.x), FreeBSD. Для прозрачного проксирования `transparent` требуется ядро Linux с поддержкой `CONFIG_NETFILTER_TPROXY`.

### Стандарты и спецификации

*   **RFC 8484:** DNS Queries over HTTPS (DoH) — базовый стандарт протокола.
*   **RFC 1035:** Domain Names - Implementation and Specification — бинарный wire format DNS-сообщений.
*   **RFC 8467:** Padding Policies for Extension Mechanisms for DNS — выравнивание длины DNS-пакетов для предотвращения анализа трафика по длине.
*   **RFC 9230:** Oblivious DNS over HTTPS (ODoH) — концепция проксирования DoH с разделением идентификатора клиента и тела запроса.

---

## См. также

*   **[Автоматические TLS-сертификаты в Angie: модуль ACME](./angie_acme_module.md)** — автоматизация выпуска и ротации TLS-сертификатов без перезагрузки процессов.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — конфигурирование протоколов TLS 1.2/1.3, шифров и оптимизация рукопожатий.
*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы балансировки upstream-групп, параметры `max_fails` и `keepalive`.
*   **[Управление доступом в Angie](./angie_access_control.md)** — разграничение прав доступа по IP-адресам и сетям.
*   **[Логирование в Angie](./angie_logging.md)** — настройка структурированного JSON-логирования и сбор метрик.
*   **[BIND: серверная настройка DoT и DoH](../../Linux/Networking/Services/BIND/dot-doh-server.md)** — развертывание и эксплуатация DNS over HTTPS на стороне BIND 9.18+.
*   **[Безопасность DNS: DoH, DoT, DoQ](../../Networking/Protocols/DNS/dns_security.md)** — сравнительный анализ протоколов шифрования DNS-трафика.