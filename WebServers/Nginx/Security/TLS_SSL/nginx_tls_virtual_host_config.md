# Конфигурация виртуальных хостов TLS в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x – 1.30.x (Mainline), OpenSSL 3.0+ / 3.5+, Linux Kernel 5.15+ / 6.x

## Определения

**Виртуальный хост TLS (`server`)** — логический блок конфигурации Nginx, определяющий правила сетевого взаимодействия, криптографические параметры и логику маршрутизации запросов для конкретного доменного имени, группы доменов или IP-адреса. Параметры внутри блока `server` переопределяют или дополняют настройки глобального контекста `http`, формируя изолированный профиль безопасности для каждого обслуживаемого сервиса.

**Server Name Indication (SNI)** — расширение протокола TLS (RFC 6066), передающее доменное имя запрашиваемого ресурса в открытом виде внутри сообщения `ClientHello` на первом этапе рукопожатия. Позволяет веб-серверу однозначно сопоставить входящее TCP/UDP-соединение с нужным блоком `server` и предъявить клиенту соответствующий цифровой сертификат до расшифровки прикладных HTTP-заголовков. Без SNI сервер на одном IP-адресе может использовать только один сертификат по умолчанию. Теория протокола: **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)**.

**Область видимости директив (Scope)** — уровень иерархии конфигурации Nginx, регламентирующий границы применения директивы:
- **`http`** (глобальный): формирует базовую линию безопасности (`ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`, `ssl_ecdh_curve`, `ssl_buffer_size`).
- **`server`** (хостовый): привязывает сертификаты и ключи к конкретному домену (`ssl_certificate`, `ssl_certificate_key`), переопределяет политики рукопожатия, активирует ECH (`ssl_ech_file`), 0-RTT (`ssl_early_data`), локальный OCSP Stapling и защитные барьеры (`ssl_reject_handshake`).
- **`location`** (маршрутный): локально управляет аутентификацией клиентов (mTLS через `ssl_verify_client`) и специфичными параметрами обработки трафика.

**Защита сервера по умолчанию (`ssl_reject_handshake`)** — директива Nginx (начиная с версии 1.19.4), принудительно обрывающая TLS-рукопожатие на стадии обработки `ClientHello` без отправки серверного сертификата, если запрашиваемый SNI не соответствует ни одному сконфигурированному виртуальному хосту или клиент обращается напрямую по IP-адресу.

**Двойной стек сертификатов (Dual Certificate Stack)** — архитектурная схема, при которой в одном блоке `server` одновременно объявляются современный сертификат на базе эллиптических кривых (ECDSA) и классический сертификат RSA. Nginx автоматически определяет возможности криптографической библиотеки клиента и отдает легковесный ECDSA-сертификат, прозрачно переключаясь на RSA для устаревших систем.

**Encrypted Client Hello (ECH)** — расширение TLS 1.3 (RFC 9460), обеспечивающее полное шифрование структуры `ClientHello`, включая поле SNI. Устраняет утечку метаданных о посещаемом домене в сторону сетевых провайдеров и инспекционных шлюзов. Требует наличия OpenSSL 4.0+ и поддержки DNS-записей HTTPS/SVCB. Архитектурный базис: **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)**.

**0-RTT Early Data** — механизм ускоренного возобновления сессий в TLS 1.3, позволяющий клиенту отправить полезную нагрузку первого HTTP-запроса одновременно с `ClientHello`. Сокращает задержку Time To First Byte (TTFB), но подвержен атакам повторного воспроизведения (Replay Attacks), что требует жесткого разграничения идемпотентных и неидемпотентных запросов на уровне веб-сервера и бэкенда.

**Предварительно загруженный OCSP Stapling (`ssl_stapling_file`)** — директива Nginx, позволяющая указать локальный файл с готовым подписанным OCSP-ответом от удостоверяющего центра. Критически важна для изолированных контуров (DMZ, Air-Gapped сети), где у воркеров Nginx отсутствует прямой исходящий доступ в интернет к OCSP-респондерам CA.

**Несоответствие SNI и Host (Domain Fronting / SNI Mismatch)** — ситуация, при которой доменное имя в SNI (на этапе TLS) не совпадает со значением заголовка `Host` во входящем HTTP-запросе. В инфраструктурах с повышенными требованиями к безопасности подобный трафик блокируется с кодом HTTP `421 Misdirected Request`.

---

## Архитектура и основные концепции

### Иерархия наследования параметров TLS

В архитектуре Nginx директивы блока `server` не объединяются с директивами блока `http`, а полностью замещают их при повторном объявлении:

```text
┌────────────────────────────────────────────────────────┐
│                      Блок http                         │
│  Глобальная политика:                                  │
│  - ssl_protocols TLSv1.2 TLSv1.3;                      │
│  - ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:...';    │
│  - ssl_session_cache shared:SSL:20m;                   │
│  - ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1;    │
└───────────┬────────────────────────────────┬───────────┘
            │ наследуется                    │ переопределяется
            ▼                                ▼
┌───────────────────────────┐  ┌───────────────────────────┐
│ server (api.example.com)  │  │ server (legacy.example.com│
│ - ssl_certificate         │  │ - ssl_certificate         │
│ - ssl_certificate_key     │  │ - ssl_certificate_key     │
│ [использует глобальные    │  │ - ssl_protocols TLSv1.2;  │
│  протоколы и шифры]       │  │   [полностью замещает     │
│                           │  │    глобальный список]     │
└───────────────────────────┘  └───────────────────────────┘
```

**Правило переопределения:** если внутри `server` объявлена директива `ssl_ciphers`, глобальный список шифров полностью аннулируется для данного хоста. Для централизованного управления безопасностью специфичные директивы (`ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`) задаются в `http`, а в `server` объявляются только уникальные атрибуты: сертификаты, ключи, ECH, 0-RTT и правила отсечения трафика.

### Жизненный цикл и алгоритм SNI-маршрутизации

Маршрутизация входящего HTTPS-соединения проходит две последовательные фазы: криптографическую (L4/L5) и протокольную (L7).

```text
Клиент                         Nginx (Master/Worker)
  │                                      │
  ├────── TCP Handshake (SYN-ACK) ───────┤
  │                                      │
  ├────── TLS ClientHello (с SNI) ──────►│ 1. Извлечение SNI
  │                                      │ 2. Поиск по listen IP:PORT
  │                                      │ 3. Сопоставление SNI с server_name
  │                                      │    - Точное совпадение
  │                                      │    - Префиксная маска (*.example.com)
  │                                      │    - Постфиксная маска (mail.*)
  │                                      │    - Регулярное выражение (~...)
  │                                      │    - Fallback -> default_server
  │                                      │ 4. Выбор сертификата (ECDSA/RSA)
  │                                      │
  │◄───── TLS ServerHello + Cert ────────┤ (Или обрыв: ssl_reject_handshake)
  │                                      │
  ├────── Завершение TLS Handshake ──────┤
  │                                      │
  ├────── HTTP/2 или HTTP/1.1 Запрос ───►│ 5. Чтение заголовка Host:
  │       (Host: api.example.com)        │ 6. Валидация: Host == SNI?
  │                                      │    - Совпадает: проксирование
  │                                      │    - Расхождение: 421 Misdirected
  │◄───── HTTP Ответ / 421 Error ────────┤
```

#### Порядок сопоставления `server_name`
При поступлении сообщения `ClientHello` Nginx выбирает блок `server` для заданного сокета `IP:PORT` по строгому алгоритму:
1. **Точное совпадение доменного имени:** `server_name example.com;`.
2. **Самое длинное совпадение с маской в начале имени:** `server_name *.example.com;`.
3. **Самое длинное совпадение с маской в конце имени:** `server_name mail.*;`.
4. **Первое совпавшее регулярное выражение:** `server_name ~^(?<subdomain>.+)\.example\.com$;` (в порядке объявления в конфигурационных файлах).
5. **Хост по умолчанию (`default_server`):** если совпадений не найдено или клиент не передал расширение SNI. Если параметр `default_server` не указан явно, сервером по умолчанию становится первый объявленный блок `server` для данного `IP:PORT`.

### Защита Default Server (`ssl_reject_handshake`)

По умолчанию при запросе неизвестного хоста или прямом обращении по IP Nginx отдает сертификат сервера по умолчанию. Это приводит к двум угрозам:
1. **Утечка доменных имен:** автоматические сканеры сети, подключаясь к публичному IP-адресу по порту 443, получают валидный сертификат компании и раскрывают доменные имена внутренних сервисов.
2. **Невалидные сессии:** клиенты получают предупреждение `ERR_CERT_COMMON_NAME_INVALID`, засоряя логи ошибками и создавая ложные срабатывания мониторинга.

Директива `ssl_reject_handshake on;` решает эту проблему: Nginx отклоняет рукопожатие на фазе `ClientHello`, отправляя TLS Alert `unrecognized_name` (Alert 112) или `handshake_failure` (Alert 40), не передавая клиенту никаких сертификатов.

### Выбор сертификата в Dual-Stack конфигурации

При объявлении двух сертификатов (ECDSA и RSA) внутри одного блока `server` выбор между ними делегируется криптографической библиотеке (OpenSSL) в момент обработки `ClientHello`:

1. **Анализ расширений клиента:** сервер проверяет расширения `signature_algorithms` и поддерживаемые группы эллиптических кривых (`supported_groups`).
2. **Определение приоритета:** если клиент заявляет поддержку алгоритмов ECDSA (например, `ecdsa_secp256r1_sha256`) и хотя бы одного включенного ECDSA-шифра, сервер предъявляет сертификат ECDSA.
3. **Fallback на RSA:** если клиент поддерживает только классические алгоритмы (устаревшие версии библиотек, старые встраиваемые системы), предъявляется RSA-сертификат.
4. **Порядок директив:** хотя OpenSSL выбирает сертификат на основе алгоритмов клиента, в конфигурации Nginx принято первой указывать директиву с ECDSA-сертификатом для упрощения аудита.

### Мультипротокольные слушатели (TCP + UDP)

Современная конфигурация высоконагруженного виртуального хоста объединяет TCP-слушатели (HTTP/1.1 и HTTP/2) и UDP-слушатели (HTTP/3 на базе протокола QUIC):

```nginx
# TCP слушатели (IPv4 и IPv6)
listen 443 ssl;
listen [::]:443 ssl;
http2 on;

# UDP слушатели QUIC (IPv4 и IPv6)
listen 443 quic;
listen [::]:443 quic;
http3 on;
```

> [!WARNING]
> Начиная с Nginx 1.25.1, параметр `http2` в директиве `listen` объявлен устаревшим (`deprecated`). Попытка использования `listen 443 ssl http2;` приводит к предупреждению компилятора конфигурации `nginx -t`. Стандартом является раздельное использование флага `ssl` в `listen` и отдельной директивы `http2 on;`.

Параметр `reuseport` на сокете 443 разрешается указывать только **один раз** для конкретной комбинации `IP:PORT`. Повторное указание `reuseport` в других блоках `server` вызовет фатальную ошибку парсинга при перезагрузке службы.

### Архитектура OCSP Stapling на уровне виртуального хоста

OCSP Stapling на уровне хоста снимает нагрузку с клиентских устройств и устраняет задержки при резолвинге статуса отзыва сертификата. Реализуется двумя методами:

1. **Динамический онлайн-опрос:** Nginx самостоятельно обращается к OCSP URL, извлеченному из секции Authority Information Access (AIA) сертификата. Требует обязательного объявления директивы `resolver` с валидными локальными DNS-серверами:
   ```nginx
   ssl_stapling on;
   ssl_stapling_verify on;
   resolver 10.0.0.2 10.0.0.3 valid=300s;
   resolver_timeout 5s;
   ```
2. **Автономная подача через файл (`ssl_stapling_file`):** в защищенных или изолированных сетевых контурах (DMZ/Air-Gapped), где серверам запрещен прямой доступ во внешние сети, файл OCSP-ответа генерируется внешней регламентной задачей и монтируется в файловую систему Nginx:
   ```nginx
   ssl_stapling on;
   ssl_stapling_verify on;
   ssl_stapling_file /var/run/nginx/ocsp/example_com.der;
   ```

### 0-RTT Early Data и предотвращение Replay-атак

TLS 1.3 0-RTT позволяет возобновить сессию без ожидания завершения полного рукопожатия, отправляя HTTP-запрос в первом сетевом пакете.
- **Угроза безопасности:** сетевой злоумышленник может перехватить зашифрованный пакет 0-RTT и отправить его серверу повторно. Если запрос выполняет мутирующую операцию (списание средств, изменение пароля, отправка сообщения), транзакция будет продублирована.
- **Стратегия защиты:** запросы с Early Data разрешаются исключительно для идемпотентных методов (`GET`, `HEAD`, `OPTIONS`). При попытке передать неидемпотентный метод (`POST`, `PUT`, `DELETE`) сервер обязан вернуть HTTP-статус `425 Too Early`, требуя от клиента повторить запрос по стандартному защищенному каналу после завершения рукопожатия.

---

## Практические сценарии

### Сценарий 1: Production виртуальный хост с Dual-Stack (ECDSA + RSA), HTTP/2 и HTTP/3

Комплексный профиль виртуального хоста, обеспечивающий максимальную скорость для современных клиентов и обратную совместимость с устаревшими системами.

```nginx
# /etc/nginx/conf.d/example.com.conf

server {
    # TCP-слушатели для HTTP/1.1 и HTTP/2
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # UDP-слушатели для HTTP/3 (QUIC)
    listen 443 quic;
    listen [::]:443 quic;
    http3 on;

    server_name example.com www.example.com;

    # Основной сертификат ECDSA (кривая P-256)
    ssl_certificate         /etc/ssl/certs/example.com.ecdsa.fullchain.pem;
    ssl_certificate_key     /etc/ssl/private/example.com.ecdsa.key;

    # Резервный сертификат RSA (длина ключа 4096 бит)
    ssl_certificate         /etc/ssl/certs/example.com.rsa.fullchain.pem;
    ssl_certificate_key     /etc/ssl/private/example.com.rsa.key;

    # Защита от UDP-амплификации в QUIC
    quic_retry on;

    # Реклама протокола HTTP/3 клиентам через заголовок ответа
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # Политика HSTS (2 года, включая поддомены, предварительная загрузка)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Заголовки базовой защиты от атак браузерного уровня
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    # Автономный OCSP Stapling для виртуального хоста
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/ssl/certs/example.com.chain.pem;
    resolver 10.0.0.10 10.0.0.11 valid=300s;
    resolver_timeout 5s;

    root /var/www/example.com/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }

    # Локация обслуживания статических файлов с Zero-Copy через kTLS
    location /static/ {
        alias /var/www/example.com/static/;
        sendfile on;
        sendfile_max_chunk 1m;
        tcp_nopush on;
        tcp_nodelay on;
        aio threads;
    }
}
```

### Сценарий 2: Защищенный `default_server` (`ssl_reject_handshake`)

Конфигурация ловушки по умолчанию. Перехватывает весь нелегитимный трафик (прямые обращения по IP-адресу, бот-сканеры, неизвестные доменные имена) и обрывает соединение до отправки сертификата.

```nginx
# /etc/nginx/conf.d/00-default.conf

# Блокировка HTTP (порт 80)
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Завершение соединения без ответа (сброс TCP RST)
    return 444;
}

# Блокировка HTTPS (порт 443 TCP)
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Принудительный сброс TLS-рукопожатия на стадии ClientHello
    ssl_reject_handshake on;
}

# Блокировка QUIC / HTTP/3 (порт 443 UDP)
server {
    listen 443 quic default_server;
    listen [::]:443 quic default_server;
    server_name _;

    # Отклонение QUIC рукопожатия
    ssl_reject_handshake on;
}
```

### Сценарий 3: Защищенный редирект HTTP → HTTPS с поддержкой ACME

Шаблон перенаправления трафика на защищенный порт с сохранением путей для прохождения валидации ACME HTTP-01 и защитой от бесконечных циклов за обратными прокси.

```nginx
# /etc/nginx/conf.d/redirect.conf

server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Исключение для локальной валидации Let's Encrypt / Certbot
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        allow all;
    }

    # Постоянный редирект на HTTPS с сохранением метода (308 для POST/PUT данных)
    location / {
        return 308 https://$host$request_uri;
    }
}
```

### Сценарий 4: Защита от Domain Fronting и SNI-спуфинга

Предотвращает атаки, при которых клиент устанавливает TLS-соединение к разрешенному домену (например, `public.example.com`), а внутри зашифрованного канала передает заголовок `Host: internal-admin.example.com`.

```nginx
# /etc/nginx/conf.d/secure_api.conf

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name api.example.com;

    ssl_certificate     /etc/ssl/certs/api.example.com.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;

    # Валидация соответствия SNI и прикладного заголовка Host
    if ($ssl_server_name != $host) {
        # 421 Misdirected Request предписывает клиенту открыть новое соединение
        return 421 "Misdirected Request: SNI mismatch\n";
    }

    location / {
        proxy_pass http://backend_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### Сценарий 5: Виртуальный хост в изолированном контуре (Air-Gapped / DMZ)

Использование автономного OCSP Stapling без обращения к внешним респондерам CA во время обработки входящего запроса.

```nginx
# /etc/nginx/conf.d/isolated_vhost.conf

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name dmz.internal.local;

    ssl_certificate     /etc/ssl/certs/dmz.internal.local.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/dmz.internal.local.key;

    # Включение OCSP Stapling через локально синхронизируемый файл
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/ssl/certs/internal_ca_chain.pem;
    ssl_stapling_file /var/cache/nginx/ocsp/dmz.internal.local.ocsp.der;

    location / {
        proxy_pass http://192.168.10.50:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Сценарий 6: API хост с безопасным 0-RTT Early Data

Оптимизация задержки рукопожатия TLS 1.3 с аппаратной защитой от атак повторного воспроизведения.

```nginx
# /etc/nginx/conf.d/fast_api.conf

# Отображение безопасных методов для фильтрации 0-RTT
map $request_method $is_unsafe_method {
    GET     0;
    HEAD    0;
    OPTIONS 0;
    default 1;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name api-fast.example.com;

    ssl_certificate     /etc/ssl/certs/api-fast.example.com.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/api-fast.example.com.key;

    # Активация 0-RTT Early Data на уровне виртуального хоста
    ssl_early_data on;

    location / {
        # Если запрос поступил в 0-RTT и является мутирующим — требуем повторить
        if ($ssl_early_data) {
            set $block_early "${is_unsafe_method}";
        }
        if ($block_early = "1") {
            return 425 "Too Early: non-idempotent method in 0-RTT rejected\n";
        }

        proxy_pass http://api_backend;
        # Передаем статус Early Data приложению для внутренней проверки
        proxy_set_header Early-Data $ssl_early_data;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Сценарий 7: ECH (Encrypted Client Hello) с OpenSSL 4.0+

Защита метаданных SNI от перехвата на сетевом уровне с использованием гибридного постквантового шифрования.

```nginx
# /etc/nginx/conf.d/ech_vhost.conf

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name secure-privacy.example.com;

    ssl_certificate     /etc/ssl/certs/secure-privacy.example.com.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/secure-privacy.example.com.key;

    # Конфигурация ключей ECH (генерируется через OpenSSL)
    ssl_ech_file /etc/nginx/ech/secure_privacy.ech;

    location / {
        proxy_pass http://backend_privacy;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Сценарий 8: Изолированный виртуальный хост Health Check / Metrics

Разделение внешнего публичного TLS-трафика и служебных проверок инфраструктуры. Позволяет мониторингу опрашивать веб-сервер без выполнения ресурсоемкого TLS-рукопожатия и без влияния mTLS-ограничений.

```nginx
# /etc/nginx/conf.d/internal_status.conf

server {
    # Привязка исключительно к локальному интерфейсу обратной петли
    listen 127.0.0.1:8080;
    listen [::1]:8080;
    server_name localhost;

    # Отключение логирования служебных запросов мониторинга
    access_log off;

    # Проверка жизнеспособности сервиса (Liveness/Readiness probe)
    location /healthz {
        default_type text/plain;
        return 200 "healthy\n";
    }

    # Метрики Nginx (требует ngx_http_stub_status_module)
    location /nginx_status {
        stub_status;
        allow 127.0.0.1;
        allow ::1;
        deny all;
    }
}
```

### Сценарий 9: Пакетное обслуживание сотен виртуальных хостов и оптимизация хеш-таблиц

При размещении сотен доменных имен в отдельных конфигурационных файлах Nginx строит внутренние хеш-таблицы для быстрого поиска `server_name`. При превышении лимитов Nginx завершает работу с ошибкой. Настройка глобального хеша в `nginx.conf`:

```nginx
# /etc/nginx/nginx.conf (блок http)
http {
    # Увеличение размера корзины при длинных именах или большом количестве хостов
    server_names_hash_bucket_size 128;
    server_names_hash_max_size 4096;
    # ...
}
```

Пример шаблонного виртуального хоста для поддоменов с использованием регулярного выражения:

```nginx
# /etc/nginx/conf.d/wildcard_tenant.conf

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # Захват имени арендатора в именованную переменную
    server_name ~^(?<tenant>[a-z0-9-]+)\.platform\.internal$;

    # Единый Wildcard-сертификат
    ssl_certificate     /etc/ssl/certs/wildcard.platform.internal.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/wildcard.platform.internal.key;

    location / {
        proxy_pass http://tenant_backend;
        proxy_set_header X-Tenant-ID $tenant;
        proxy_set_header Host $host;
    }
}
```

---

## Операции и команды

### Валидация и перезагрузка конфигурации

```bash
# 1. Проверка синтаксиса конфигурационных файлов
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Детальный дамп объединенной конфигурации (поиск дублирующихся server_name)
sudo nginx -T | grep -E "server_name|listen"

# 3. Graceful reload службы без разрыва активных TLS-сессий
sudo systemctl reload nginx
# Или прямая отправка сигнала главному процессу:
sudo kill -HUP $(cat /var/run/nginx.pid)

# 4. Проверка состояния сокетов (TCP и UDP)
sudo ss -tlpn 'sport = :443'
sudo ss -ulpn 'sport = :443'
```

### Проверка SNI, сертификатов и протоколов через `openssl s_client`

```bash
# Проверка сопоставления конкретного виртуального хоста по SNI
openssl s_client -connect 127.0.0.1:443 -servername example.com -brief
# → CONNECTION ESTABLISHED
# → Protocol version: TLSv1.3
# → Ciphersuite: TLS_AES_256_GCM_SHA384
# → Peer certificate: CN = example.com

# Проверка защитного обрыва рукопожатия без SNI (default_server drop)
openssl s_client -connect 127.0.0.1:443 -noservername -brief
# → 4047702896:error:0A000410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure:...
# → Alert 40/112 подтверждает срабатывание ssl_reject_handshake on

# Проверка приоритета отдачи ECDSA-сертификата
openssl s_client -connect example.com:443 -servername example.com \
  -tls1_3 -sigalgs "ecdsa_secp256r1_sha256" 2>&1 | grep "Server public key"
# → Server public key is 256 bit EC

# Проверка резервного RSA-сертификата (принудительное отключение ECDSA-алгоритмов)
openssl s_client -connect example.com:443 -servername example.com \
  -tls1_3 -sigalgs "rsa_pss_rsae_sha256" 2>&1 | grep "Server public key"
# → Server public key is 4096 bit RSA

# Проверка статуса OCSP Stapling в рукопожатии
openssl s_client -connect example.com:443 -servername example.com -status -noout 2>&1 | grep -A5 "OCSP Response Data"
# → OCSP Response Status: successful (0x0)
# → Cert Status: good

# Проверка согласования протокола ALPN (HTTP/2)
openssl s_client -connect example.com:443 -servername example.com -alpn h2 </dev/null 2>&1 | grep "ALPN protocol"
# → ALPN protocol: h2

# Проверка поддержки HTTP/3 (QUIC)
curl --http3 -v -I https://example.com 2>&1 | grep -E "HTTP/3|alt-svc"
# → < HTTP/3 200
# → < alt-svc: h3=":443"; ma=86400
```

### Инвентаризация и аудит сертификатов виртуальных хостов

Скрипт системного аудитора для проверки срока действия всех локальных сертификатов, объявленных в виртуальных хостах Nginx:

```bash
#!/usr/bin/env bash
# /usr/local/bin/check_nginx_vhost_certs.sh
set -euo pipefail

echo "=== Проверка сертификатов виртуальных хостов Nginx ==="
printf "%-35s %-20s %-10s\n" "Файл сертификата" "Действителен до" "Осталось дней"
echo "----------------------------------------------------------------------"

# Поиск всех файлов сертификатов в активной конфигурации
grep -rhE "^\s*ssl_certificate\s+" /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null \
  | awk '{print $2}' | tr -d ';' | sort -u | while read -r cert_path; do
    if [[ -f "$cert_path" ]]; then
        end_date=$(openssl x509 -enddate -noout -in "$cert_path" | cut -d= -f2)
        end_epoch=$(date -d "$end_date" +%s)
        now_epoch=$(date +%s)
        days_left=$(( (end_epoch - now_epoch) / 86400 ))

        printf "%-35s %-20s %-10d\n" "$(basename "$cert_path")" "$end_date" "$days_left"
    else
        echo "Файл не найден: $cert_path"
    fi
done
```

Пример вывода:
```text
=== Проверка сертификатов виртуальных хостов Nginx ===
Файл сертификата                    Действителен до      Осталось дней
----------------------------------------------------------------------
example.com.ecdsa.fullchain.pem     Dec 20 12:00:00 2026 64
example.com.rsa.fullchain.pem       Dec 20 12:00:00 2026 64
api.example.com.fullchain.pem       Nov 15 08:30:00 2026 29
```

### Настройка расширенного TLS-аудит логирования

Добавление детальных параметров TLS-сессий виртуальных хостов в лог-файл (настраивается в блоке `http` `nginx.conf`):

```nginx
log_format vhost_tls_audit escape=json '{'
    '"time_local":"$time_local",'
    '"remote_addr":"$remote_addr",'
    '"vhost":"$server_name",'
    '"host_header":"$host",'
    '"sni":"$ssl_server_name",'
    '"protocol":"$ssl_protocol",'
    '"cipher":"$ssl_cipher",'
    '"curve":"$ssl_curves",'
    '"session_reused":"$ssl_session_reused",'
    '"early_data":"$ssl_early_data",'
    '"alpn":"$ssl_alpn_protocol",'
    '"status":"$status",'
    '"request_time":"$request_time"'
'}';

server {
    server_name example.com;
    access_log /var/log/nginx/example_com_tls.json vhost_tls_audit;
}
```

Анализ аномалий в журнале аудита:

```bash
# Подсчет запросов с несовпадением SNI и Host (потенциальный Domain Fronting)
jq -r 'select(.sni != "" and .sni != .host_header) | [.sni, .host_header] | @tsv' /var/log/nginx/example_com_tls.json | sort | uniq -c

# Распределение используемых протоколов и кривых обмена ключами
jq -r '[.protocol, .curve] | @tsv' /var/log/nginx/example_com_tls.json | sort | uniq -c | sort -rn
```

---

## Устранение неполадок

### Матрица типовых сбоев виртуальных хостов

| Ошибка в логе / Симптом | Вероятная причина | Инструмент диагностики | Метод устранения |
| :--- | :--- | :--- | :--- |
| `SSL_do_handshake() failed: alert handshake failure (40)` | Запрос поступил на `default_server` с директивой `ssl_reject_handshake on;` из-за отсутствия SNI или опечатки в имени. | `openssl s_client -connect IP:443 -servername <host>` | Проверить соответствие `server_name` запрашиваемому домену; для тестовых клиентов явно указывать заголовок SNI. |
| `[warn] the "http2" parameter of the "listen" directive is deprecated` | Использование устаревшего синтаксиса `listen 443 ssl http2;` в Nginx 1.25.1+. | `nginx -t` | Заменить параметр на флаг `listen 443 ssl;` и объявить отдельную директиву `http2 on;`. |
| `421 Misdirected Request` | Клиент переиспользовал существующее HTTP/2-соединение для другого хоста, либо сработала проверка `$ssl_server_name != $host`. | `curl -v -I --http2 --resolve ...` | Нормальное поведение при защите от Domain Fronting. Клиент обязан открыть новое TLS-соединение. |
| `425 Too Early` | Клиент отправил неидемпотентный запрос (`POST`/`PUT`) в составе 0-RTT Early Data. | Проверить значение переменной `$ssl_early_data` в логе. | Ограничить использование Early Data исключительно безопасными методами (`GET`/`HEAD`) на клиенте. |
| `certificate verify failed: unable to get local issuer certificate` | В `ssl_certificate` указан только конечный сертификат (Leaf) без промежуточных центров (Intermediate CA). | `openssl s_client -showcerts` | Объединить конечный сертификат и цепочку CA: `cat cert.pem intermediate.pem > fullchain.pem`. |
| `no "ssl_certificate" is defined for the "listen ... ssl"` | В блоке `server` объявлен порт с флагом `ssl`, но отсутствуют пути к файлам сертификата и ключа. | `nginx -t` | Добавить валидные пути `ssl_certificate` и `ssl_certificate_key` в блок `server`. |
| `could not build server_names_hash, you should increase server_names_hash_bucket_size` | Большое количество виртуальных хостов или длинные доменные имена переполнили корзину хеш-таблицы. | Ошибка при запуске `nginx -t` | Увеличить параметры в блоке `http`: `server_names_hash_bucket_size 128;` и `server_names_hash_max_size 4096;`. |
| `ssl_stapling: no data / resolver failed` | DNS-сервер недоступен, либо в сертификате отсутствует ссылка на OCSP responder (AIA). | `openssl x509 -noout -text -in cert.pem \| grep -A2 "Authority Information"` | Настроить директиву `resolver` с корректным локальным IP; для закрытых контуров применить `ssl_stapling_file`. |
| `BIO_new_file(...) failed: Permission denied` | Рабочий процесс Nginx (`nginx`/`www-data`) не имеет прав чтения приватного ключа. | `ls -la /etc/ssl/private/` | Установить права `0600` на ключи и владельца `root:root`. Master-процесс Nginx читает ключи до сброса привилегий воркеров. |

### Пошаговый алгоритм локализации сбоев виртуального хоста

```text
[Проблема: клиент получает ошибку при установке HTTPS-соединения]
                           │
                           ▼
             Выполнить: sudo nginx -t
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
   [Синтаксическая ошибка]         [Синтаксис корректен]
   - Опечатка в директиве          │
   - Отсутствует файл ключа        ▼
   - Дубликат reuseport            Выполнить: openssl s_client -connect IP:443 -servername <domain>
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
           [Handshake failure]           [Handshake успешен]
           - Проверить SNI               - Проверить ответ HTTP (curl -v -I)
           - Проверить ssl_protocols     - Проверить статус 421/425
           - Сработал reject_handshake   - Проверить upstream/backend
```

---

## Рекомендации и лучшие практики

### Чеклист надежности и безопасности виртуальных хостов (2026)

- [ ] **Изоляция неизвестных запросов:** Первый сервер в конфигурации для порта 443 TCP/UDP объявляет `default_server` и содержит директиву `ssl_reject_handshake on;`.
- [ ] **Синтаксис протоколов:** Параметр `http2` вынесен из директивы `listen` в отдельную команду `http2 on;`.
- [ ] **Dual-Stack сертификация:** Для критически важных публичных хостов объявлены две пары сертификатов — ECDSA (P-256) и RSA (4096 бит).
- [ ] **Целостность цепочки:** В директиве `ssl_certificate` указан файл полной цепочки (Leaf + Intermediate). Корневой сертификат исключен.
- [ ] **Безопасность ключей:** Приватные ключи имеют права доступа `0600`, принадлежат пользователю `root` и размещены в каталоге `/etc/ssl/private/` с правами `0700`.
- [ ] **OCSP Stapling:** Настроен с привязкой локального доверенного резолвера (`resolver`) либо через предварительно загружаемый файл (`ssl_stapling_file`).
- [ ] **HSTS:** Заголовок `Strict-Transport-Security` включен с флагом `always` и периодом не менее 1 года (`31536000`).
- [ ] **HTTP/3 QUIC:** Включена директива `quic_retry on;`, передан заголовок `Alt-Svc`, UDP-порт 443 открыт на межсетевом экране.
- [ ] **Защита от Replay:** Использование `ssl_early_data on;` сопровождается передачей заголовка `Early-Data` бэкенду и фильтрацией мутирующих методов.
- [ ] **Защита от Domain Fronting:** Настроена проверка `$ssl_server_name` и возвращается код `421` при расхождении с `$host`.

### Zero-Downtime процедура ротации сертификатов

При плановой или экстренной замене сертификатов виртуального хоста необходимо гарантировать непрерывность обработки пользовательских сессий:

1. **Атомарное размещение файлов:** Записывайте новые файлы сертификатов и ключей с временными именами, после чего выполняйте атомарное переименование (`mv`):
   ```bash
   install -m 0600 -o root -g root new_key.pem /etc/ssl/private/example.com.key.new
   install -m 0644 -o root -g root new_chain.pem /etc/ssl/certs/example.com.fullchain.pem.new
   mv /etc/ssl/private/example.com.key.new /etc/ssl/private/example.com.key
   mv /etc/ssl/certs/example.com.fullchain.pem.new /etc/ssl/certs/example.com.fullchain.pem
   ```
2. **Предварительное тестирование:** Ни при каких обстоятельствах не выполняйте перезагрузку службы без предварительного валидатора:
   ```bash
   sudo nginx -t
   ```
3. **Безопасная перезагрузка (Graceful Reload):**
   ```bash
   sudo systemctl reload nginx
   ```
   *Механизм:* Master-процесс перечитывает файлы конфигурации и ключи под правами `root`, создает новый пул воркеров с обновленным TLS-контекстом и отправляет сигнал `SIGQUIT` старым воркерам. Старые воркеры корректно завершают обслуживание ранее открытых соединений и освобождают память.

### Оптимизация ресурсов и производительности

| Область | Настройка | Эффект для SRE / DevOps |
| :--- | :--- | :--- |
| **Вычислительная сложность** | Приоритет ECDSA (кривая P-256) | Снижение утилизации CPU на операциях асимметричного рукопожатия в 3–5 раз по сравнению с RSA-2048/4096. |
| **Память воркеров** | `server_names_hash_bucket_size` | Предотвращение сбоев компиляции конфигурации при сотнях виртуальных хостов. |
| **Zero-Copy отдача** | kTLS (`sendfile on;`) | Разгрузка контекстных переключений между user-space и kernel-space при отдаче статики по HTTPS. |
| **Сетевая задержка (TTFB)** | OCSP Stapling + HTTP/2 Multiplexing | Исключение задержек клиентов на опрос CA, устранение Head-of-Line Blocking на прикладном уровне. |

---

## Дополнительная информация

### См. также

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура подсистемы TLS, kTLS, гибридный постквантовый обмен ключами и жизненный цикл соединения.
*   **[Глобальные параметры TLS в Nginx](./nginx_tls_global_parameters.md)** — централизованная настройка шифров, протоколов, кэширования сессий в блоке `http`.
*   **[Настройка mTLS в Nginx](./nginx_mtls_configuration.md)** — взаимная аутентификация клиентов, списки отзыва (CRL) и клиентский OCSP.
*   **[Диагностика и устранение неполадок TLS в Nginx](./nginx_tls_troubleshooting_and_compatibility.md)** — анализ дампов трафика, матрица совместимости клиентов, расшифровка TLS Alerts.
*   **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md)** — детальная оптимизация QUIC, UDP-сокетов и параметров протоколов.
*   **[Интеграция Nginx с Let's Encrypt и Certbot](../../Scenarios/nginx_with_letsencrypt.md)** — автоматизация выпуска и обновления сертификатов, хуки systemd.
*   **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)** — фундаментальные основы рукопожатия, криптографические примитивы и спецификации RFC.
*   **[PKI — инфраструктура открытых ключей](../../../../Security/Concepts/pki_overview.md)** — иерархия доверия, корневые и промежуточные центры сертификации.
