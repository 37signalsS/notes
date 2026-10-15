# Настройка TLS в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Настройка TLS в Angie** — процесс конфигурирования криптографических протоколов TLS (Transport Layer Security 1.2 и 1.3) и QUIC в веб-сервере Angie для обеспечения конфиденциальности, целостности и аутентификации сетевого трафика.

**Angie** — высокопроизводительный веб-сервер (форк Nginx), развивающий функциональность ядра для высоконагруженных сред: нативная поддержка HTTP/3 (QUIC) с оптимизацией ядра Linux, встроенный модуль ACME для автоматизации сертификатов без внешних агентов, поддержка переменных в директивах путей к сертификатам и CRL, а также кэширование сертификатов в оперативной памяти рабочих процессов.

**HTTP/3 и QUIC (RFC 9000, RFC 9114)** — протокол прикладного уровня HTTP/3, функционирующий поверх транспортного протокола QUIC на базе UDP со встроенным шифрованием TLS 1.3. Устраняет блокировку начала очереди (Head-of-Line blocking) на транспортном уровне и ускоряет установку соединения до 0–1 RTT.

**Kernel TLS (kTLS)** — механизм ядра Linux (начиная с ветки 5.10+ в связке с OpenSSL 3.0+), переносящий операции симметричного шифрования и дешифрования данных TLS (Data Plane) из адресного пространства пользователя в ядро ОС. В сочетании с системным вызовом `sendfile()` обеспечивает прямую передачу зашифрованных страниц памяти из Page Cache в сетевой сокет (Zero-Copy).

**quic_bpf** — архитектурное расширение Angie на базе подсистемы Linux eBPF (Extended Berkeley Packet Filter) для сокетов `SO_REUSEPORT`. Обеспечивает детерминированную маршрутизацию входящих UDP-датаграмм QUIC к конкретному рабочему процессу по Connection ID (DCID), исключая разрыв активных сессий при плановой перезагрузке конфигурации (`graceful reload`).

**ssl_reject_handshake** — директива безопасного сброса TLS-рукопожатия на этапе `ClientHello`. Используется в конфигурациях виртуального сервера по умолчанию (`default_server`) для предотвращения утечки имен доменов и отсечения нелегитимных запросов с отсутствующим или неизвестным SNI.

**ssl_certificate_cache** — механизм хранения разобранных структур X.509-сертификатов и закрытых ключей в оперативной памяти рабочих процессов Angie. Устраняет избыточные системные вызовы `stat()` и `open()` при динамическом выборе сертификатов через переменные в массовом виртуальном хостинге.

**Session Resumption (Возобновление сессий)** — повторное использование предварительно согласованных криптографических ключей между клиентом и сервером. Реализуется через **Session ID** (кэш в разделяемой памяти сервера `ssl_session_cache`) или **Session Tickets** (зашифрованный криптографический тикет на стороне клиента, RFC 5077).

**0-RTT Early Data (TLS 1.3, RFC 8446)** — механизм отправки полезной нагрузки прикладного уровня (HTTP-запроса) в первом пакете клиента вместе с `ClientHello` при возобновлении сессии, сокращающий задержку до нуля миллисекунд. Требует обязательной защиты от атак повторного воспроизведения (Replay Attacks).

**OCSP Stapling (RFC 6066)** — механизм прикрепления сервером подписанного центром сертификации OCSP-ответа со статусом валидности сертификата к пакету `ServerHello`. Устраняет задержки прямых клиентских запросов к OCSP-респондерам и гарантирует конфиденциальность посещений.

**Постквантовая криптография (PQC, Post-Quantum Cryptography)** — гибридные алгоритмы обмена ключами (например, `X25519MLKEM768`, стандартизированный NIST как FIPS 203 ML-KEM), защищающие текущий зашифрованный трафик от ретроспективной дешифрации квантовыми компьютерами в будущем (стратегия «Harvest Now, Decrypt Later»).

Общие принципы протоколов TLS, параметры HSTS и устройство цепочек доверия описаны в базовых руководствах:
> **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**
> **[Глобальные параметры TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)**
> **[Диагностика SSL/TLS сертификатов](../../Security/Tools/ssl_certificate_diagnostics.md)**

---

## Базовые концепции и архитектура

### Архитектурные особенности TLS в Angie

Angie унаследовал асинхронную событийно-ориентированную многопроцессную архитектуру, где мастер-процесс (`master`) управляет жизненным циклом конфигурации и воркеров, а рабочие процессы (`worker`) независимо обрабатывают сетевые события через `epoll` (Linux).

```
[ Клиент (Браузер / Агент / curl) ]
               │
      TCP 443  │  UDP 443 (QUIC)
               ▼
[ Ядро Linux: eBPF Socket Filter (quic_bpf) + kTLS Data Plane ]
               │
        ┌──────┴──────────────────────────┐
        │ Маршрутизация по DCID / CPU     │
        ▼                                 ▼
[ Worker Process 1 (Angie) ]     [ Worker Process N (Angie) ]
 ├── TLS Engine (OpenSSL 3.x)     ├── TLS Engine (OpenSSL 3.x)
 ├── In-Memory Certificate Cache  ├── In-Memory Certificate Cache
 └── Shared Memory Zones (ssl_session_cache, dynamic zones, STEK keys)
```

**Ключевые преимущества Angie по сравнению с классическим Nginx:**
1. **Нативный QUIC и HTTP/3 в базовой поставке:** В отличие от Nginx, где поддержка HTTP/3 долгое время требовала экспериментальных веток или отдельной компиляции, в Angie стек HTTP/3 полностью интегрирован в ядро и протестирован для работы под высокими нагрузками.
2. **Бесшовный reload для QUIC (`quic_bpf`):** По умолчанию при `reload` сокеты UDP с флагом `SO_REUSEPORT` перебалансируются между старыми и новыми воркерами по 4-tuple (IP/порт клиента и сервера). Поскольку UDP не имеет состояния, пакеты одного QUIC-соединения могли попадать на новый воркер, не знающий состояния криптосессии, что приводило к сбросу соединения. Директива `quic_bpf on` загружает eBPF-программу, сопоставляющую Destination Connection ID (DCID) с дескриптором воркера-владельца.
3. **Динамические пути с переменными:** Директивы `ssl_certificate`, `ssl_certificate_key`, `ssl_crl` и `ssl_ocsp` поддерживают переменные (`$ssl_server_name`, `$host`), позволяя загружать сертификаты и списки отзыва на лету без сотен статических блоков `server`.
4. **Кэширование сертификатов (`ssl_certificate_cache`):** Для динамических сертификатов Angie парсит X.509 и RSA/ECDSA-ключи один раз и сохраняет их в памяти воркера на время `inactive`, исключая сотни тысяч чтений с диска на каждый запрос.
5. **Встроенный ACME-клиент:** Нативный модуль `acme` берет на себя получение и обновление сертификатов Let's Encrypt / Step-CA, перехватывает HTTP-01 проверки на уровне ядра и атомарно подменяет сертификаты в памяти без перезагрузки процессов (`reload`) и разрыва соединений.
6. **Автоматическая ротация сессионных тикетов:** Синхронизация и генерация ключей шифрования сессионных тикетов (STEK) между процессами воркеров выполняется автоматически.

### Жизненный цикл соединений: TLS 1.2, TLS 1.3 и QUIC

```
TCP + TLS 1.2 (2-RTT Handshake)
Client                       Server
  | ----- TCP SYN ------------> |
  | <---- TCP SYN+ACK --------- |
  | ----- TCP ACK ------------> | (Соединение TCP открыто)
  | ----- ClientHello --------> | (1-RTT)
  | <---- ServerHello + Cert -- |
  | ----- KeyExchange --------> | (2-RTT)
  | <---- Finished ------------ |
  | <==== HTTP Data (TLS) ====> |

TCP + TLS 1.3 (1-RTT Handshake)
Client                       Server
  | ----- TCP SYN ------------> |
  | <---- TCP SYN+ACK --------- |
  | ----- ClientHello + Keys -> | (1-RTT: Key Share отправлен сразу)
  | <---- ServerHello + Cert -- |
  | <==== HTTP Data (TLS) ====> | (Данные приложения шифруются)

QUIC / HTTP/3 (1-RTT поверх UDP)
Client                       Server
  | ===== Initial (ClientHello + Keys) ====> | (UDP Датаграмма)
  | <==== Handshake (ServerHello + Cert) === | (1-RTT: Сессия установлена)
  | <==== Short Header (HTTP/3 Data) ======> |

QUIC / TLS 1.3 0-RTT (Resumption)
Client                       Server
  | ===== Initial + 0-RTT HTTP Request ====> | (0-RTT: Данные в первом пакете!)
  | <==== Handshake + HTTP Response ======== |
```

### Механизм Kernel TLS (kTLS)

Классическая модель TLS передает открытые данные из дискового кэша ядра в пространство пользователя (user-space), где OpenSSL производит шифрование, после чего зашифрованный буфер копируется обратно в ядро для отправки в сетевую карту.

При активации `kTLS` и директивы `sendfile on`:
1. **Control Plane:** Рукопожатие TLS (Handshake), аутентификация по сертификату и обмен ключами производятся в user-space процессом Angie через OpenSSL.
2. **Передача ключей:** После согласования симметричные сессионные ключи (AES-GCM-128/256 или ChaCha20-Poly1305) передаются в стек сокета ядра Linux через `setsockopt(..., SOL_TLS, ...)`.
3. **Data Plane:** При вызове `sendfile()` страницы файла считываются ядром напрямую из Page Cache, шифруются криптографической подсистемой ядра (включая аппаратное ускорение CPU AES-NI) и передаются в сетевой драйвер минуя user-space (Zero-Copy). Снижение нагрузки на CPU при отдаче статики достигает 30–40%.

---

## Практические сценарии

### Сценарий 1: Продакшен-конфигурация Dual-Stack HTTP/2 и HTTP/3 (QUIC) с оптимизацией eBPF и GSO

Сценарий обеспечивает одновременное обслуживание клиентов по современным стандартам HTTP/2 (поверх TCP) и HTTP/3 (поверх UDP), с защитой от сканирования портов через `ssl_reject_handshake`.

**Требования к окружению:**
* Linux-ядро 5.10+ (для поддержки `quic_bpf` и UDP GSO).
* Открытые порты `443/tcp` и `443/udp` в межсетевом экране (nftables/iptables).

#### Шаг 1. Конфигурация виртуальных серверов Angie

Создайте файл конфигурации `/etc/angie/http.d/production_tls.conf`:

```nginx
# Виртуальный сервер по умолчанию: сброс неизвестных и прямых IP-запросов
server {
    listen 443 ssl default_server;
    listen 443 quic default_server reuseport;
    server_name _;

    # Завершать рукопожатие без отправки сертификата при неизвестном SNI
    ssl_reject_handshake on;

    access_log off;
    return 444;
}

# Основной продуктовый сервер
server {
    # Прием входящих соединений по TCP (HTTP/1.1 и HTTP/2)
    listen 443 ssl;
    http2 on;

    # Прием входящих датаграмм по UDP (HTTP/3 QUIC)
    # Параметр reuseport задается один раз на комбинацию IP:port в конфигурации
    listen 443 quic;

    server_name example.com www.example.com;

    # Сертификаты (цепочка fullchain и закрытый ключ)
    ssl_certificate     /etc/angie/ssl/example.com.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.key;

    # Анонс поддержки HTTP/3 для клиентов (браузеры кэшируют заголовок на 24 часа)
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # Аппаратное объединение сегментов UDP для разгрузки сетевого стека ядра
    quic_gso on;

    # Защита от амплификации и UDP-спуфинга через валидацию адреса (Retry token)
    quic_retry on;

    # Стабилизация соединений при hot-reload через сокетный eBPF-фильтр
    quic_bpf on;

    # Лимиты HTTP/3
    http3_max_concurrent_streams 256;

    location / {
        root /var/www/example.com/html;
        index index.html;
    }
}
```

#### Шаг 2. Проверка и применение конфигурации

```bash
# Проверка корректности синтаксиса
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Бесшовная перезагрузка конфигурации
sudo angie -s reload
```

#### Шаг 3. Верификация соединений TCP и UDP

```bash
# Проверка прослушивания портов 443 TCP и UDP
sudo ss -tulnp | grep :443
# → tcp   LISTEN 0      511          0.0.0.0:443       0.0.0.0:*    users:(("angie",pid=1234,fd=6))
# → udp   UNCONN 0      0            0.0.0.0:443       0.0.0.0:*    users:(("angie",pid=1234,fd=7))

# Проверка рукопожатия HTTP/2 через OpenSSL
openssl s_client -connect example.com:443 -servername example.com -alpn h2 < /dev/null 2>&1 | grep "ALPN"
# → ALPN protocol: h2

# Проверка протокола HTTP/3 через curl
curl --http3-only -I https://example.com/
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=86400
```

---

### Сценарий 2: Массовый виртуальный хостинг с динамической загрузкой сертификатов и кэшированием в RAM

Сценарий предназначен для сред с сотнями и тысячами доменов (SaaS, multi-tenant платформы). Исключает разрастание конфигурационных файлов и экономит системные ресурсы.

#### Шаг 1. Организация файловой структуры сертификатов

```bash
# Создание защищенных каталогов для хранения сертификатов
sudo mkdir -p /etc/angie/ssl/domains
sudo chown -R root:angie /etc/angie/ssl
sudo find /etc/angie/ssl -type d -exec chmod 750 {} +
sudo find /etc/angie/ssl -type f -name "*.key" -exec chmod 640 {} +
sudo find /etc/angie/ssl -type f -name "*.crt" -exec chmod 644 {} +
```

#### Шаг 2. Конфигурация виртуального хостинга

Создайте `/etc/angie/http.d/dynamic_vhosts.conf`:

```nginx
http {
    # Кэширование до 5000 X.509 сертификатов и ключей в оперативной памяти воркеров
    # Сертификаты, к которым не было обращений более 1 часа, удаляются из кэша
    ssl_certificate_cache max=5000 inactive=1h;

    # Валидация имени хоста из SNI для защиты от Path Traversal
    map $ssl_server_name $safe_domain {
        ~*^([a-z0-9_\-\.]+\.[a-z]{2,})$ $1;
        default                         "";
    }

    server {
        listen 443 ssl;
        server_name *.example.org;

        # Если имя SNI некорректно, сбрасываем соединение
        if ($safe_domain = "") {
            return 444;
        }

        # Динамическая загрузка сертификата на основе переменной SNI
        ssl_certificate     /etc/angie/ssl/domains/$safe_domain.crt;
        ssl_certificate_key /etc/angie/ssl/domains/$safe_domain.key;

        location / {
            root /var/www/vhosts/$safe_domain;
            try_files $uri $uri/ =404;
        }
    }
}
```

#### Шаг 3. Проверка работы динамического кэша

```bash
# Тестовое подключение к динамическому домену
openssl s_client -connect 127.0.0.1:443 -servername app1.example.org < /dev/null 2>&1 | grep "CN="
# → depth=0 CN = app1.example.org
# → verify return:1
```

> **SRE-заметка:** Если сертификат на диске был заменен скриптом или внешней системой управления ключами, старая копия останется в `ssl_certificate_cache` до истечения таймаута `inactive`. Для немедленного сброса кэша выполните `sudo angie -s reload`.

---

### Сценарий 3: Защищенный отказоустойчивый стек TLS (RSA + ECDSA, HSTS, OCSP Stapling, DH 2048)

Конфигурация наивысшего уровня безопасности (уровень А+ в Qualys SSL Labs) с поддержкой дуального стека сертификатов: быстрого эллиптического ECDSA для современных клиентов и классического RSA для обратной совместимости.

#### Шаг 1. Генерация параметров Диффи-Хеллмана (DH)

```bash
# Генерация файла параметров Диффи-Хеллмана (2048 бит)
sudo openssl dhparam -out /etc/angie/ssl/dhparam2048.pem 2048
# → Generating DH parameters, 2048 bit long safe prime, ... done
sudo chmod 644 /etc/angie/ssl/dhparam2048.pem
```

#### Шаг 2. Настройка усиленного TLS в `/etc/angie/http.d/hardened_tls.conf`

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name secure.example.com;

    # 1. Двойные сертификаты: ECDSA (приоритетный) и RSA (резервный)
    ssl_certificate         /etc/angie/ssl/secure.example.com_ecdsa.crt;
    ssl_certificate_key     /etc/angie/ssl/secure.example.com_ecdsa.key;

    ssl_certificate         /etc/angie/ssl/secure.example.com_rsa.crt;
    ssl_certificate_key     /etc/angie/ssl/secure.example.com_rsa.key;

    # 2. Протоколы: строгий отказ от уязвимых TLS 1.0 и 1.1
    ssl_protocols TLSv1.2 TLSv1.3;

    # 3. Наборы шифров TLS 1.2 с поддержкой PFS (Perfect Forward Secrecy)
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
    ssl_prefer_server_ciphers off;

    # 4. Наборы шифров TLS 1.3 (настраиваются через директиву OpenSSL)
    ssl_conf_command Ciphersuites TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256;

    # 5. Эллиптические кривые (включая гибридную постквантовую кривую OpenSSL 3.2+)
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;

    # 6. Параметры Диффи-Хеллмана для DHE-шифров
    ssl_dhparam /etc/angie/ssl/dhparam2048.pem;

    # 7. OCSP Stapling: сервер запрашивает статус отзыва и передает клиенту
    ssl_stapling on;
    ssl_stapling_verify on;
    # Доверенная корневая цепочка для валидации OCSP-ответа
    ssl_trusted_certificate /etc/angie/ssl/ca_chain.crt;
    resolver 127.0.0.1 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
    resolver_timeout 5s;

    # 8. Заголовок HSTS: принудительный переход на HTTPS на 2 года, включая поддомены
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # 9. Заголовки безопасности транспортного уровня
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    location / {
        root /var/www/secure;
    }
}
```

#### Шаг 3. Проверка статуса OCSP Stapling и шифров

```bash
# Проверка наличия OCSP-ответа в пакете рукопожатия
openssl s_client -connect secure.example.com:443 -servername secure.example.com -status < /dev/null 2>&1 | grep -A 17 "OCSP response:"
# → OCSP Response Data:
# →     OCSP Response Status: successful (0x0)
# →     Cert Status: good

# Проверка отключения устаревшего TLS 1.1
openssl s_client -connect secure.example.com:443 -tls1_1 < /dev/null 2>&1 | grep -i "handshake failure"
# → 14094410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure
```

---

### Сценарий 4: Высокопроизводительное возобновление сессий и безопасный 0-RTT Early Data

Оптимизация задержки рукопожатий (Handshake latency) для распределенного кластера серверов Angie с использованием кластерных ключей STEK и защищенного режима 0-RTT.

#### Шаг 1. Генерация и распространение ключей сессионных тикетов (STEK)

Для работы возобновления сессий в балансируемом кластере все ноды Angie должны обладать одинаковым ключом шифрования тикетов (48 байт: 16 байт имя ключа + 16 байт ключ шифрования AES-128 + 16 байт HMAC-SHA256):

```bash
# Генерация нового 48-байтного криптографического ключа
sudo openssl rand 48 -out /etc/angie/ssl/ticket_current.key
sudo chmod 640 /etc/angie/ssl/ticket_current.key
sudo chown root:angie /etc/angie/ssl/ticket_current.key

# Резервная копия предыдущего ключа (для плавной ротации без инвалидации клиентов)
sudo cp /etc/angie/ssl/ticket_current.key /etc/angie/ssl/ticket_previous.key
```

#### Шаг 2. Конфигурация сессий и 0-RTT в `/etc/angie/http.d/session_resumption.conf`

```nginx
# Ограничение частоты запросов для защиты от Replay-атак Early Data
limit_req_zone $binary_remote_addr zone=early_data_zone:10m rate=20r/s;

server {
    listen 443 ssl;
    http2 on;
    server_name api.example.com;

    ssl_certificate     /etc/angie/ssl/api.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/api.example.com.key;

    # 1. Кэш сессий в разделяемой памяти (32 МБ ~ 128 000 сессий)
    ssl_session_cache shared:SSL_API:32m;
    ssl_session_timeout 1d;

    # 2. Использование Session Tickets с кластерными ключами
    ssl_session_tickets on;
    # Первый ключ шифрует новые и расшифровывает старые тикеты
    ssl_session_ticket_key /etc/angie/ssl/ticket_current.key;
    # Второй ключ используется только для расшифровки ранее выданных тикетов
    ssl_session_ticket_key /etc/angie/ssl/ticket_previous.key;

    # 3. Активация 0-RTT ранних данных для TLS 1.3
    ssl_early_data on;

    location / {
        # Защита от Replay: 0-RTT разрешен только для безопасных идемпотентных методов
        # Если клиент пытается передать POST/PUT/DELETE в ранних данных — возвращаем 425 Too Early
        if ($ssl_early_data) {
            set $early_guard "${request_method}_EARLY";
        }

        # Блокировка опасных неидемпотентных запросов при 0-RTT
        if ($early_guard ~ "^(POST|PUT|DELETE|PATCH)_EARLY$") {
            return 425; # 425 Too Early (клиент обязан повторить запрос после полного рукопожатия)
        }

        # Ограничение частоты запросов Early Data
        limit_req zone=early_data_zone burst=10 nodelay;

        # Проброс заголовка приложению для информирования о статусе 0-RTT
        proxy_set_header Early-Data $ssl_early_data;
        proxy_pass http://backend_upstream;
    }
}
```

#### Шаг 3. Скрипт ротации ключей STEK (Cron / SRE Task)

Создайте `/usr/local/bin/angie_rotate_tickets.sh`:

```bash
#!/bin/bash
set -euo pipefail

SSL_DIR="/etc/angie/ssl"
CURRENT="$SSL_DIR/ticket_current.key"
PREVIOUS="$SSL_DIR/ticket_previous.key"
TMP_KEY="$SSL_DIR/ticket_new.tmp"

# Генерация нового 48-байтного ключа
openssl rand 48 -out "$TMP_KEY"
chmod 640 "$TMP_KEY"
chown root:angie "$TMP_KEY"

# Сдвиг ротации: текущий ключ становится предыдущим, новый — текущим
mv "$CURRENT" "$PREVIOUS"
mv "$TMP_KEY" "$CURRENT"

# Бесшовное применение ключей воркерами Angie
angie -s reload
```

---

### Сценарий 5: Максимальная пропускная способность со статикой через Kernel TLS (kTLS)

Сценарий для высоконагруженных узлов раздачи медиафайлов, видеостриминга или файловых архивов.

#### Шаг 1. Настройка ядра операционной системы

```bash
# Загрузка модуля ядра kTLS
sudo modprobe tls

# Проверка загрузки модуля
lsmod | grep tls
# → tls                   131072  0

# Автозагрузка модуля при старте ОС
echo "tls" | sudo tee /etc/modules-load.d/tls.conf
# → tls

# Активация kTLS через sysctl
sudo sysctl -w net.core.tls_enabled=1
# → net.core.tls_enabled = 1
echo "net.core.tls_enabled = 1" | sudo tee -a /etc/sysctl.d/99-ktls.conf
```

#### Шаг 2. Конфигурация Angie для kTLS

Создайте `/etc/angie/http.d/ktls_static.conf`:

```nginx
http {
    # Включение kTLS на уровне OpenSSL для поддерживаемых сокетов
    ssl_conf_command Options +KTLS;

    server {
        listen 443 ssl;
        http2 on;
        server_name cdn.example.com;

        ssl_certificate     /etc/angie/ssl/cdn.example.com.crt;
        ssl_certificate_key /etc/angie/ssl/cdn.example.com.key;

        # Симметричные шифры, аппаратно поддерживаемые kTLS в ядре Linux
        ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
        ssl_conf_command Ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384;

        # Обязательные опции передачи данных Zero-Copy
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;

        location /static/ {
            alias /var/www/cdn_data/;
            # Отключение буферизации для прямой передачи страниц памяти в сеть
            aio threads;
            directio 4m;
        }
    }
}
```

#### Шаг 3. Верификация работы kTLS

```bash
# Проверка счетчиков переданных байт через ядро kTLS
grep -E "TlsTxSw|TlsRxSw|TlsTxDevice" /proc/net/tls_stat
# → TlsTxSw: 458920150
# → TlsRxSw: 12040120

# Проверка параметров активного TLS-сокета утилитой ss
sudo ss -ti | grep -i "tls"
# → tls-tx-sw tls-rx-sw
```

---

### Сценарий 6: Интеграция со встроенным модулем ACME для автоматической ротации сертификатов

Angie берет на себя взаимодействие с удостоверяющим центром (Let's Encrypt или внутренний Step-CA), выполняя проверку HTTP-01 в ядре и мгновенно применяя выданный сертификат.

#### Конфигурация в `/etc/angie/http.d/acme_auto.conf`:

```nginx
http {
    # Внутренний или публичный DNS-резолвер для проверки адреса ACME Directory
    resolver 127.0.0.1 1.1.1.1 valid=300s;

    # Определение клиента ACME
    acme_client letsencrypt_prod {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        account_key /etc/angie/acme_account.key;
    }

    # HTTP-сервер для обработки перехвата HTTP-01 и общего редиректа
    server {
        listen 80;
        server_name portal.example.com;

        # Активация перехвата /.well-known/acme-challenge/ в ядре Angie
        acme letsencrypt_prod;

        # Все остальные запросы принудительно перенаправляются на HTTPS
        location / {
            return 301 https://$host$request_uri;
        }
    }

    # HTTPS-сервер, использующий автоматически управляемый сертификат
    server {
        listen 443 ssl;
        http2 on;
        server_name portal.example.com;

        # Привязка домена к клиенту ACME
        acme letsencrypt_prod;

        # Переменные сгенерированного и обновляемого в памяти сертификата
        ssl_certificate     $acme_cert_letsencrypt_prod;
        ssl_certificate_key $acme_cert_key_letsencrypt_prod;

        location / {
            root /var/www/portal;
        }
    }
}
```

Подробное руководство по выпуску Wildcard-сертификатов, авторизации DNS-01 через встроенный responder и привязке корпоративного EAB:
> **[Модуль ACME в Angie: полная конфигурация](./angie_acme_module.md)**

---

### Сценарий 7: Безопасное upstream-проксирование с валидацией TLS (Re-encryption)

В архитектуре Zero Trust трафик между фронтенд-сервером Angie и бэкендами обязан быть зашифрован и взаимно аутентифицирован.

```nginx
upstream secure_backend {
    zone backend_zone 64k;
    server 192.168.10.20:8443 max_fails=3 fail_timeout=10s;
    server 192.168.10.21:8443 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 443 ssl;
    http2 on;
    server_name service.example.com;

    ssl_certificate     /etc/angie/ssl/service.crt;
    ssl_certificate_key /etc/angie/ssl/service.key;

    location / {
        proxy_pass https://secure_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # 1. Валидация подлинности бэкенда по внутреннему корпоративному CA
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;
        proxy_ssl_trusted_certificate /etc/angie/ssl/corp_internal_ca.crt;

        # 2. Проверка соответствия имени хоста бэкенда в SNI
        proxy_ssl_server_name on;
        proxy_ssl_name backend.internal.example.com;

        # 3. Аутентификация самого Angie на бэкенде (mTLS клиентский сертификат)
        proxy_ssl_certificate     /etc/angie/ssl/frontend_client.crt;
        proxy_ssl_certificate_key /etc/angie/ssl/frontend_client.key;

        # 4. Переиспользование TLS-сессий с апстримами для экономии CPU
        proxy_ssl_session_reuse on;
        proxy_ssl_protocols TLSv1.2 TLSv1.3;
    }
}
```

---

## Операции и команды

### 1. Проверка синтаксиса и вывод конфигурации

```bash
# Проверка синтаксиса всех подключенных файлов конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка конфигурации с подробным дампом загруженных блоков
sudo angie -T | grep -E "ssl_|quic_|http2"
# → ssl_certificate /etc/angie/ssl/example.com.crt;
# → ssl_protocols TLSv1.2 TLSv1.3;
```

### 2. Бесшовное управление процессами (Zero Downtime)

```bash
# Перечитывание конфигурации и обновление сертификатов без прерывания соединений
sudo angie -s reload
# → отправлен сигнал HUP мастер-процессу

# Переоткрытие файлов логов (используется при logrotate)
sudo angie -s reopen

# Корректная остановка воркеров после завершения активных клиентских соединений
sudo angie -s quit
```

### 3. Диагностика TLS-соединений и сертификатов

```bash
# Тестирование рукопожатия, цепочки сертификатов и используемого шифра
openssl s_client -connect example.com:443 -servername example.com -showcerts < /dev/null
# → CONNECTED(00000003)
# → Certificate chain
# →  0 s:CN = example.com
# →    i:C = US, O = Let's Encrypt, CN = R3
# → ---
# → SSL handshake has read 3154 bytes and written 412 bytes
# → New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384

# Проверка срока действия локального сертификата на диске
openssl x509 -in /etc/angie/ssl/example.com.crt -noout -dates
# → notBefore=Oct 14 00:00:00 2026 GMT
# → notAfter=Jan 12 23:59:59 2027 GMT

# Сверка соответствия сертификата и закрытого ключа по их открытым экспонентам (MD5 модулей)
openssl x509 -noout -modulus -in /etc/angie/ssl/example.com.crt | openssl md5
# → (stdin)= a1b2c3d4e5f67890
openssl rsa -noout -modulus -in /etc/angie/ssl/example.com.key | openssl md5
# → (stdin)= a1b2c3d4e5f67890
# (Одинаковые хэши подтверждают соответствие ключа и сертификата)
```

### 4. Мониторинг метрик TLS через REST API Angie

Angie предоставляет детальные счетчики рукопожатий и возобновлений сессий через встроенный эндпоинт `/status/`:

```bash
# Получение TLS-статистики конкретного виртуального сервера
curl -s http://127.0.0.1:8080/status/http/server_zones/example_zone | jq .ssl
# → {
# →   "handshaked": 48291,
# →   "reuses": 38120,
# →   "timedout": 4,
# →   "failed": 12
# → }

# Проверка эффективности кэширования сессий (Reuse Ratio)
curl -s http://127.0.0.1:8080/status/http/server_zones/example_zone | jq '.ssl | (.reuses / .handshaked * 100)'
# → 78.93

# Мониторинг статуса ACME-сертификатов через API
curl -s http://127.0.0.1:8080/status/http/acme_clients/letsencrypt_prod | jq .
# → {
# →   "status": "ready",
# →   "certs": [
# →     {
# →       "domain": "portal.example.com",
# →       "expires": "2027-01-12T23:59:59Z",
# →       "state": "valid"
# →     }
# →   ]
# → }
```

### 5. Аудит безопасности и прав доступа к файлам

```bash
# Проверка прав доступа: закрытые ключи должны быть доступны только root и angie
ls -la /etc/angie/ssl/
# → -rw-r----- 1 root angie 1704 Oct 14 10:00 example.com.key
# → -rw-r--r-- 1 root root  3580 Oct 14 10:00 example.com.crt

# Экспресс-тест на уязвимости и соответствие стандартам через testssl.sh
testssl.sh --fast --pfs --hsts https://example.com/
# → Testing protocols via sockets except NPN and ALPN
# →  SSLv2      not offered (OK)
# →  SSLv3      not offered (OK)
# →  TLS 1      not offered (OK)
# →  TLS 1.1    not offered (OK)
# →  TLS 1.2    offered (OK)
# →  TLS 1.3    offered (OK): final
```

---

## Устранение неисправностей

### 1. Ошибки рукопожатия (Handshake Failure)

**Симптом:** В логе `/var/log/angie/error.log` фиксируется:
`SSL_do_handshake() failed (SSL: error:14094410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure)`

**Причины:**
1. Клиент и сервер не имеют общих поддерживаемых наборов шифров (Cipher Suites) или версий протокола.
2. Сервер использует директиву `ssl_reject_handshake on;`, а клиент подключился с неизвестным SNI или без него.

**Диагностика и решение:**
```bash
# 1. Проверка используемых сервером протоколов и шифров
sudo angie -T | grep -E "ssl_protocols|ssl_ciphers"

# 2. Тестирование с указанием точного SNI
openssl s_client -connect 127.0.0.1:443 -servername example.com -tls1_2

# 3. Если используется ssl_reject_handshake — убедитесь, что имя хоста
# клиента точно перечислено в server_name целевого виртуального сервера.
```

---

### 2. Ошибки цепочки сертификатов (Incomplete Chain / Untrusted CA)

**Симптом:** Браузеры или консольные утилиты выдают `SEC_ERROR_UNKNOWN_ISSUER` или `certificate verify failed (unable to get local issuer certificate)`.

**Причина:** Файл, указанный в директиве `ssl_certificate`, содержит только конечный сертификат узла (Leaf), без промежуточных сертификатов центра авторизации (Intermediate CA).

**Диагностика и решение:**
```bash
# Проверка глубины цепочки, отдаваемой сервером
openssl s_client -connect example.com:443 -servername example.com < /dev/null 2>&1 | grep "Certificate chain" -A 4
# Если отображается только 0 s:CN = ..., цепочка неполная!

# Решение: объедините сертификат домена и промежуточный сертификат CA в один fullchain-файл
# Важно: сертификат домена ВСЕГДА идет первым, промежуточный — вторым!
cat domain_leaf.crt intermediate_ca.crt > /etc/angie/ssl/example.com.crt

# Проверка синтаксиса и перезагрузка
sudo angie -t && sudo angie -s reload
```

---

### 3. Проблемы с HTTP/3 и QUIC (UDP 443)

**Симптом:** Браузеры поддерживают HTTP/3, но упорно загружают сайт по HTTP/2; утилита `curl --http3-only` завершается с таймаутом соединения.

**Причины:**
1. Заблокирован входящий UDP-трафик на порту 443 на хосте или внешнем файрволе.
2. Отсутствует заголовок `Alt-Svc`, из-за чего браузер не знает о поддержке HTTP/3.
3. Проблема MTU Black Hole: пакеты QUIC превышают Path MTU и отбрасываются маршрутизатором без отправки ICMP `Destination Unreachable (Fragmentation Needed)`.

**Диагностика и решение:**
```bash
# 1. Проверка правил nftables / iptables для входящего UDP 443
sudo iptables -L INPUT -n -v | grep 443
# Решение для iptables:
sudo iptables -A INPUT -p udp --dport 443 -j ACCEPT

# 2. Проверка заголовка Alt-Svc
curl -I https://example.com/ | grep -i alt-svc
# → alt-svc: h3=":443"; ma=86400

# 3. Если наблюдается потеря пакетов при больших размерах — временно отключите GSO:
# в блоке server: quic_gso off;
```

---

### 4. `ssl_certificate_cache` отдает устаревший сертификат после обновления

**Симптом:** Файлы на диске обновлены новым сертификатом, но браузеры продолжают получать старый сертификат.

**Причина:** `ssl_certificate_cache` сохраняет распарсенные криптографические объекты в адресном пространстве каждого рабочего процесса. Сервер не отслеживает `inotify`-события изменения файлов на диске для динамических путей.

**Диагностика и решение:**
```bash
# Проверка срока действия сертификата в ответе сервера
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates

# Решение: выполнить graceful reload мастер-процесса.
# Новые воркеры запускаются с пустым кэшем и перечитывают файлы с диска:
sudo angie -s reload

# Напоминание: НЕ пытайтесь удалять виртуальные файлы кэша на диске — кэш содержится исключительно в RAM!
```

---

### 5. Ошибки kTLS (`Options +KTLS`)

**Симптом:** В журнале ошибок появляется предупреждение `[warn] SSL_CONF_cmd("Options", "+KTLS") failed`.

**Причины:**
1. Не загружен модуль ядра `tls`.
2. OpenSSL скомпилирован без флага `enable-ktls` (или версия ниже 3.0).
3. Клиент согласовал шифр, не поддерживаемый драйвером kTLS (например, 3DES или устаревший CBC).

**Диагностика и решение:**
```bash
# 1. Проверка поддержки в ядре
sudo modprobe tls && ls -la /sys/module/tls

# 2. Проверка версии OpenSSL
openssl version
# → OpenSSL 3.0.7 (или выше)

# 3. Ограничьте наборы шифров исключительно современными GCM-шифрами:
# ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
```

---

### 6. Ошибки 0-RTT: статус 425 Too Early и Replay-атаки

**Симптом:** Клиенты получают ошибку `425 Too Early` или в бэкенд поступают дублирующиеся платежные/неидемпотентные запросы.

**Причина:** Спецификация RFC 8446 допускает перехват и повторную отправку ранних данных (0-RTT). Если бэкенд не готов к идемпотентной обработке, злоумышленник может дублировать операции.

**Решение:**
1. Разрешайте 0-RTT исключительно для безопасных методов `GET`, `HEAD`, `OPTIONS`.
2. Для всех остальных методов возвращайте код `425`, вынуждая клиента завершить 1-RTT рукопожатие перед передачей тела запроса:
   ```nginx
   if ($ssl_early_data) {
       set $early_check "${request_method}_EARLY";
   }
   if ($early_check ~ "^(POST|PUT|DELETE)_EARLY$") {
       return 425;
   }
   ```

---

## Лучшие практики

### 1. Безопасность и соответствие стандартам (Security Hardening)

* **Отказ от устаревших протоколов:** Полностью исключите `TLSv1` и `TLSv1.1`. Разрешайте только `TLSv1.2` и `TLSv1.3`.
* **Защита Default Server:** Всегда объявляйте блок `server` с параметром `default_server` и директивой `ssl_reject_handshake on;`. Это предотвращает раскрытие доменов при сканировании IP-адресов ботами.
* **Принцип наименьших привилегий:** Закрытые ключи (`*.key`) должны принадлежать пользователю `root` и группе `angie`, иметь маску прав `0640` или `0400`. Доступ на чтение посторонним пользователям системы категорически запрещен:
  ```bash
  sudo chown root:angie /etc/angie/ssl/*.key
  sudo chmod 640 /etc/angie/ssl/*.key
  ```
* **Принудительный HSTS:** Включайте заголовок `Strict-Transport-Security` с директивами `includeSubDomains` и `preload` только после успешного тестирования всех сервисов и поддоменов на HTTPS.

### 2. Производительность и оптимизация ресурсов

* **Размер `ssl_session_cache`:** 1 мегабайт разделяемой памяти вмещает около 4000 сессий. Для высоконагруженного кластера с 10 000 RPS достаточно зоны `shared:SSL:32m` (около 128 000 сессий).
* **Приоритет ECDSA-сертификатов:** Эллиптические сертификаты на базе кривой `prime256v1` (P-256) обеспечивают ту же криптостойкость, что и RSA-3072, но требуют в 4–5 раз меньше вычислительных ресурсов CPU во время математических операций рукопожатия.
* **Использование kTLS для статики:** Включайте `ssl_conf_command Options +KTLS;` в сочетании с `sendfile on;` на файловых хранилищах и CDN-нодах.
* **Аппаратная разгрузка UDP:** Директива `quic_gso on;` позволяет ядру передавать крупные буферы данных в сетевую карту единой операцией, экономя системные прерывания.

### 3. SRE и надежность эксплуатации

* **Проактивный мониторинг экспирации сертификатов:** Настройте регулярный сбор метрик через Prometheus Blackbox Exporter или API Angie (`/status/http/acme_clients/`). Установите пороги алертов: Warning — за 21 день, Critical — за 7 дней до истечения.
* **Автоматизированное тестирование в CI/CD:** Перед деплоем новой конфигурации в продакшен всегда запускайте проверку синтаксиса `angie -t` и сверку модулей сертификатов через тестовый контейнер или стейджинг-хост.
* **Синхронизация ключей STEK:** При наличии балансировщика нагрузки (L4/Keepalived/HAProxy) перед несколькими нодами Angie разворачивайте единый ключ тикетов сессий через Ansible или cron для 100% эффективности Session Resumption между серверами.

### 4. Продвинутое структурированное логирование TLS

Для построения дашбордов в Grafana и аудита безопасности в SIEM настройте детальный JSON-формат логов с криптографическими переменными:

```nginx
log_format tls_json escape=json '{'
    '"time_local":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"host":"$host",'
    '"request_method":"$request_method",'
    '"request_uri":"$request_uri",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time,'
    '"ssl_protocol":"$ssl_protocol",'
    '"ssl_cipher":"$ssl_cipher",'
    '"ssl_curve":"$ssl_curve",'
    '"ssl_session_reused":"$ssl_session_reused",'
    '"ssl_early_data":"$ssl_early_data",'
    '"ssl_server_name":"$ssl_server_name",'
    '"quic": "$http3"'
'}';

access_log /var/log/angie/tls_access.json tls_json;
```

---

## Дополнительная информация

### Постквантовая криптография (PQC) в Angie

Начиная с OpenSSL 3.2 и 3.3, доступна поддержка гибридных постквантовых механизмов инкапсуляции ключей (KEM), в частности `X25519MLKEM768` (ранее известного как `X25519Kyber768Draft00`). Данный механизм объединяет классическую эллиптическую кривую X25519 с решеточным квантово-устойчивым алгоритмом ML-KEM.

Для активации гибридного обмена ключами в Angie достаточно указать группу кривых в директиве `ssl_ecdh_curve`:

```nginx
ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
```

Если клиент поддерживает PQC (например, современные версии Chrome, Chromium, Firefox), рукопожатие автоматически согласует постквантовую защиту без изменения существующих сертификатов сервера.

### Логирование сессионных ключей (SSLKEYLOGFILE) для Wireshark

Для отладки сетевых аномалий и анализа зашифрованных дампов трафика Angie поддерживает запись симметричных ключей сессий в отдельный файл:

```nginx
http {
    # Директива доступна только при наличии прав root или соответствующей сборке
    ssl_keylog_file /var/log/angie/sslkeys.log;
}
```

> **Предупреждение по безопасности:** Файл `/var/log/angie/sslkeys.log` содержит закрытые симметричные ключи активных сессий пользователей. На продакшен-серверах директива должна быть строго отключена. При отладке ограничьте права на файл (`chmod 600`).

### Регламент аварийного отката конфигурации TLS

1. Создайте резервную копию рабочей конфигурации перед внесением правок:
   ```bash
   sudo cp -a /etc/angie /etc/angie.backup-$(date +%F)
   ```
2. В случае сбоя или некорректного применения новых сертификатов восстановите предыдущую версию:
   ```bash
   sudo cp -a /etc/angie.backup-2026-10-14/* /etc/angie/
   sudo angie -t
   sudo angie -s reload
   ```

---

## См. также

* **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — основы TLS, симметричное и асимметричное шифрование, цепочки сертификатов.
* **[Глобальные параметры TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)** — общие рекомендации по наборам шифров, HSTS и протоколам.
* **[Виртуальные хосты TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — архитектура SNI, разделение контекстов по портам и хостам.
* **[Диагностика и совместимость TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — матрица ошибок TLS-рукопожатий и методы их решения.
* **[Диагностика SSL/TLS сертификатов](../../Security/Tools/ssl_certificate_diagnostics.md)** — разбор форматов PEM/DER, валидация цепочек, проверка CRL и OCSP.
* **[Взаимная аутентификация (mTLS) в Angie](./angie_client_cert_auth.md)** — настройка двустороннего TLS для межсервисной аутентификации M2M.
* **[Модуль ACME в Angie: полная конфигурация](./angie_acme_module.md)** — автоматический выпуск и продление сертификатов Let's Encrypt и Step-CA.
* **[DNS over HTTPS (DoH) в Angie](./angie_doh_module.md)** — реализация защищенного шлюза DNS поверх HTTP/2 и HTTP/3.
* **[Диагностика DoS-защиты в Angie](./High_Load/dos_protection.md)** — отражение атак типа HTTP/2 Rapid Reset и QUIC Flood.
* **[Конфигурация HTTP/2 и HTTP/3 (Nginx и Angie)](../Nginx/Performance/nginx_http_versions.md)** — особенности работы с ALPN, мультиплексированием и окнами перегрузки.
* **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — заголовки безопасности, защита от Request Smuggling и CORS.
