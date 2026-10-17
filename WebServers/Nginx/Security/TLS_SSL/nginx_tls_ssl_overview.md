# Обзор TLS/SSL в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x – 1.30.x (Mainline), OpenSSL 3.0+ / 3.5+, Linux Kernel 5.15+ / 6.x

## Определения

**TLS (Transport Layer Security) в Nginx** — программный криптографический уровень веб-сервера, обеспечивающий шифрование трафика, проверку подлинности сервера (аутентификацию) и контроль целостности передаваемых данных. Базовым отраслевым стандартом является **TLS 1.3** (RFC 8446), обеспечивающий ускоренное установление соединения за один круговой сетевой цикл (1-RTT) и исключающий уязвимые алгоритмы шифрования. Протокол TLS 1.2 сохраняется исключительно для обратной совместимости с устаревшими клиентами.

**Цепочка сертификатов (Certificate Chain / Full Chain)** — иерархическая последовательность цифровых сертификатов X.509, связывающая конечный сертификат сервера (Leaf Certificate) с доверенным корневым центром сертификации (Root CA) через один или несколько промежуточных центров (Intermediate CA). В Nginx требуется передача полной цепочки в едином файле в строгом порядке: сначала сертификат сервера, затем промежуточные сертификаты. Корневой сертификат в файл не включается, так как он содержится в локальном хранилище доверия клиента.

**Server Name Indication (SNI)** — расширение протокола TLS (RFC 6066), передающее доменное имя запрашиваемого виртуального хоста в открытом виде в структуре сообщения `ClientHello`. Позволяет Nginx определить целевой блок `server` и отправить клиенту соответствующий сертификат до завершения криптографического рукопожатия, обеспечивая совместную работу сотен независимых HTTPS-сайтов на едином IP-адресе.

**Application-Layer Protocol Negotiation (ALPN)** — расширение TLS (RFC 7301), позволяющее клиенту и серверу согласовать протокол прикладного уровня (например, `h2` для HTTP/2 или `http/1.1`) непосредственно на этапе TLS-рукопожатия без дополнительных сетевых RTT.

**HTTP Strict Transport Security (HSTS)** — механизм политики безопасности (RFC 6797), передаваемый через HTTP-заголовок ответа `Strict-Transport-Security`, который предписывает браузеру обращаться к указанному домену и его поддоменам исключительно по защищенному протоколу HTTPS, предотвращая атаки типа SSL Stripping и Man-in-the-Middle при первичных переходах по незащищенным ссылкам.

**Возобновление сессий (Session Resumption: Session ID & Session Tickets)** — механизмы повторного установления защищенного соединения между клиентом и Nginx без выполнения ресурсоемкой асимметричной криптографии:
- **Session ID (RFC 5246):** сервер сохраняет криптографический контекст в разделяемой памяти рабочих процессов (`ssl_session_cache shared:SSL:...`) и передает клиенту 32-байтный идентификатор.
- **Session Tickets (RFC 5077 / RFC 8446):** состояние сессии шифруется симметричным ключом (Session Ticket Encryption Key, STEK) и хранится на стороне клиента. В многосерверных кластерах без централизованной синхронизации STEK тикеты отключают (`ssl_session_tickets off`) для соблюдения Perfect Forward Secrecy.

**OCSP Stapling** — механизм оптимизации проверки статуса цифрового сертификата (RFC 6066 / RFC 6960), при котором Nginx самостоятельно и асинхронно опрашивает OCSP-респондер удостоверяющего центра, кэширует подписанный ответ с меткой времени и «прикрепляет» (staples) его к сообщению `ServerHello`. Это избавляет клиентские приложения от выполнения блокирующих DNS- и HTTP-запросов к сторонним серверам CA, ускоряя время установки соединения и защищая приватность пользователей.

**Encrypted Client Hello (ECH)** — расширение TLS 1.3 (RFC 9460), шифрующее всё сообщение `ClientHello`, включая поле SNI. Устраняет фундаментальную брешь в приватности, предотвращая перехват доменного имени интернет-провайдерами и межсетевыми экранами. Требует наличия публичного ключа ECH в DNS-записи HTTPS/SVCB домена.

**Гибридный постквантовый обмен ключами (Hybrid PQC / ML-KEM-768)** — криптографический механизм защиты трафика от атак типа «Harvest Now, Decrypt Later» (HNDL), при которых зашифрованный сегодня трафик перехватывается для последующей расшифровки на квантовых компьютерах. Nginx с OpenSSL 3.5+ и 4.0+ использует гибридные схемы (например, `X25519MLKEM768`), объединяющие классическую эллиптическую криптографию X25519 и квантово-устойчивый алгоритм инкапсуляции ключей ML-KEM (Kyber, стандартизирован NIST FIPS 203).

**Kernel TLS (kTLS)** — подсистема ядра Linux (начиная с версий 5.10+ / 6.x), позволяющая перенести фазу симметричного потокового шифрования и дешифрования (AES-GCM, ChaCha20-Poly1305) из пространства пользователя (user-space Nginx) напрямую в сетевой стек ядра. Обеспечивает работу системного вызова `sendfile()` в режиме Zero-Copy при отдаче статических файлов по HTTPS.

**Perfect Forward Secrecy (PFS)** — свойство криптографического протокола, гарантирующее, что компрометация долговременного закрытого ключа сервера не позволит злоумышленнику расшифровать ранее перехваченные сессии. Достигается за счет использования эфемерных кривых (ECDHE), где уникальные сессионные ключи генерируются заново для каждого соединения и уничтожаются после его закрытия.

**Двойной стек сертификатов (Dual Certificate Stack)** — архитектурная конфигурация виртуального хоста Nginx, в которой одновременно объявляются современный сертификат на базе эллиптических кривых (ECDSA) и классический сертификат RSA. Nginx автоматически отдает легковесный и производительный ECDSA-сертификат клиентам с его поддержкой, прозрачно переключаясь на RSA для устаревших систем.

---

## Архитектура и основные концепции

### Архитектура подсистемы TLS в Nginx

Nginx функционирует на основе многопроцессной архитектуры master-worker с неблокирующим событийным циклом (Event Loop на базе `epoll` в Linux). Архитектура обработки TLS встроена в эту модель следующим образом:

```text
                               Клиент
                                 │
                   [TCP SYN] / [UDP Datagram]
                                 ▼
                     Сетевой стек ядра Linux
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
                 ▼ (kTLS TX: sendfile Zero-Copy) ▼ (Симметричный трафик)
        ┌────────────────────────────────────────────────────────┐
        │                 Nginx Worker Process                   │
        │                                                        │
        │  ┌──────────────────┐           ┌───────────────────┐  │
        │  │   Модуль TLS     │◄─────────►│  Библиотека       │  │
        │  │ (ngx_http_ssl)   │           │  OpenSSL 3.x/4.x  │  │
        │  └────────┬─────────┘           └───────────────────┘  │
        │           │                                            │
        └───────────┼────────────────────────────────────────────┘
                    │ IPC через атомарные операции и мьютексы
                    ▼
        ┌────────────────────────────────────────────────────────┐
        │          Разделяемая память (Shared Memory)            │
        │                                                        │
        │  ┌─────────────────────────┐  ┌─────────────────────┐  │
        │  │ Кэш сессий (Slab-аллок.)│  │ Кэш OCSP-ответов    │  │
        │  │  shared:SSL:20m         │  │  ssl_ocsp_cache     │  │
        │  └─────────────────────────┘  └─────────────────────┘  │
        └────────────────────────────────────────────────────────┘
```

1. **Разделение уровней конфигурации**:
   - **Контекст `http` (глобальный)**: Задает базовую политику безопасности, наборы протоколов (`ssl_protocols`), глобальные шифронаборы (`ssl_ciphers`), параметры разделяемой памяти для сессий (`ssl_session_cache`) и глобальные параметры OCSP Stapling.
   - **Контекст `server` (виртуальный хост)**: Определяет параметры конкретного домена — пути к сертификатам и закрытым ключам (`ssl_certificate`, `ssl_certificate_key`), активацию ECH (`ssl_ech_file`), 0-RTT (`ssl_early_data`) и индивидуальные правила отсечения нежелательного трафика (`ssl_reject_handshake`).
   - *Важное правило*: В Nginx списки директив не склеиваются. Если директива шифров или протоколов переопределена внутри `server`, значение из `http` для этого хоста полностью игнорируется.

2. **Взаимодействие с OpenSSL и криптографическими движками**:
   - Асимметричное шифрование (обмен ключами ECDHE/PQC, верификация цифровой подписи) выполняется в user-space воркера Nginx с использованием библиотеки OpenSSL.
   - Каждый рабочий процесс управляет собственным пулом соединений, но обращается к единому сегменту разделяемой памяти (Shared Memory Zone) для поиска кэшированных TLS-сессий.

3. **Slab-аллокатор разделяемой памяти сессий**:
   - При использовании `ssl_session_cache shared:SSL:20m` Nginx выделяет 20 МБ общей памяти, управляемой внутренним slab-аллокатором.
   - 1 МБ памяти вмещает около 4000 сессий. Зона размером 20 МБ способна удерживать до 80 000 параллельных сессий, защищая CPU серверов от повторных полных рукопожатий при перераспределении соединений между воркерами операционной системой.

### Жизненный цикл TLS-соединения

Процесс взаимодействия между клиентом и Nginx при использовании современных протоколов TLS 1.3 и TLS 1.2:

```text
Клиент                                                      Nginx Worker
  │                                                               │
  │ 1. TCP SYN                                                    │
  ├──────────────────────────────────────────────────────────────►│
  │ 2. TCP SYN-ACK                                                │
  │◄──────────────────────────────────────────────────────────────┤
  │ 3. TCP ACK                                                    │
  ├──────────────────────────────────────────────────────────────►│
  │                                                               │
  │ ─── ФАЗА РУКОПОЖАТИЯ TLS 1.3 (1-RTT) ──────────────────────── │
  │                                                               │
  │ 4. ClientHello [CipherSuites, KeyShare(ECDHE/ML-KEM), SNI]    │
  ├──────────────────────────────────────────────────────────────►│
  │    (Nginx: парсинг SNI -> выбор vhost -> генерация KeyShare   │
  │     -> чтение OCSP Staple -> подпись ServerHello)             │
  │                                                               │
  │ 5. ServerHello [KeyShare, SelectedCipher]                     │
  │    {EncryptedExtensions [ALPN: h2]}                           │
  │    {Certificate [Full Chain: Leaf + Intermediate]}            │
  │    {CertificateVerify [ECDSA/RSA-PSS Signature]}              │
  │    {Finished}                                                 │
  │◄──────────────────────────────────────────────────────────────┤
  │                                                               │
  │ ─── ЗАЩИЩЕННЫЙ КАНАЛ (Симметричное шифрование) ────────────── │
  │                                                               │
  │ 6. {Finished} + HTTP Request (GET /index.html)                │
  ├──────────────────────────────────────────────────────────────►│
  │    (При kTLS: ядро расшифровывает пакет -> Nginx читает       │
  │     запрос -> вызывает sendfile() -> ядро шифрует статику     │
  │     напрямую из pagecache в сетевой сокет)                    │
  │                                                               │
  │ 7. HTTP Response (200 OK + Payload)                           │
  │◄──────────────────────────────────────────────────────────────┤
```

### Сравнение TLS 1.2 и TLS 1.3 в Nginx

| Критерий | TLS 1.2 | TLS 1.3 |
| :--- | :--- | :--- |
| **Задержка рукопожатия** | 2-RTT (два круговых цикла) | 1-RTT (один цикл) / 0-RTT при возобновлении |
| **Управление наборами шифров** | Настраивается через `ssl_ciphers` (длинные строки вида `ECDHE-ECDSA-AES128-GCM-SHA256:...`) | Алгоритмы стандартизированы жестко в OpenSSL (`TLS_AES_256_GCM_SHA384`, `TLS_AES_128_GCM_SHA256`, `TLS_CHACHA20_POLY1305_SHA256`). Директива `ssl_ciphers` на них не влияет. |
| **PFS (Perfect Forward Secrecy)** | Опционально (зависит от конфигурации `ssl_ciphers`) | **Обязательно на уровне стандарта**. Статический обмен ключами RSA исключен. |
| **Безопасность шифрования** | Разрешены CBC-режимы, RC4, 3DES, SHA-1 (требуют явного отключения) | Только authenticated AEAD-шифры (GCM, Poly1305, CCM) |
| **Приватность метаданных** | Сертификат сервера и расширения передаются открытым текстом | Сертификат сервера и расширения полностью зашифрованы |

### Kernel TLS (kTLS) и Zero-Copy передача статики

В традиционной схеме обслуживания HTTPS-запросов процесс Nginx выполняет системные вызовы `read()` для чтения файла с диска в память пространства пользователя, шифрует буфер силами библиотеки OpenSSL с помощью CPU, после чего передает зашифрованные данные ядру через системный вызов `write()`. Это порождает двойное копирование данных в оперативной памяти и постоянные переключения контекста CPU (context switches).

При включении kTLS (`ssl_conf_command Options +KTLS;`):
1. Асимметричное рукопожатие и согласование сессионных ключей происходят в user-space Nginx через OpenSSL.
2. После завершения рукопожатия симметричные ключи шифрования и номер последовательности (IV) передаются в контекст сокета ядра Linux через системный вызов `setsockopt(..., SOL_TLS, ...)`.
3. При отдаче статических файлов Nginx выполняет системный вызов `sendfile()`. Ядро Linux перекачивает страницы памяти напрямую из файлового дискового кэша (Page Cache) в сетевой сокет, выполняя симметричное шифрование (AES-NI / ARM Crypto) на лету средствами ядра без копирования данных в пространство пользователя (Zero-Copy).
4. Экономия ресурсов CPU на высоконагруженных шлюзах отдачи статики достигает 30–40%, а пропускная способность сокета возрастает до физического лимита сетевого интерфейса.

### Encrypted Client Hello (ECH)

Стандартное расширение SNI передает запрашиваемое доменное имя в открытом виде в первом же IP-пакете рукопожатия, что позволяет внешним системам мониторинга и цензуры фильтровать или анализировать трафик. ECH решает эту проблему разделением `ClientHello` на две части:
- **ClientHelloOuter**: Незащищенное внешнее сообщение, содержащее публичный фиктивный домен (front-end domain).
- **ClientHelloInner**: Зашифрованное внутреннее сообщение, содержащее реальный домен виртуального хоста.

Для работы ECH:
1. Nginx генерирует конфигурацию ECH с открытым ключом, которая публикуется в авторитетном DNS в виде записи типа `HTTPS` / `SVCB` (параметр `ech=...`).
2. Клиент, поддерживающий ECH, перед отправкой TCP-запроса запрашивает DNS-запись HTTPS, извлекает публичный ключ сервера и шифрует ClientHelloInner.
3. Nginx принимает запрос, расшифровывает ClientHelloInner с помощью закрытого ключа (`ssl_ech_file`) и направляет запрос в соответствующий виртуальный хост.

### Постквантовая криптография (PQC) в Nginx

Современные стандарты безопасности требуют внедрения защиты от атак класса HNDL. В OpenSSL 3.5 LTS+ и OpenSSL 4.0 реализован гибридный механизм обмена ключами, поддерживаемый Nginx через директиву `ssl_ecdh_curve`:
- Схема **X25519MLKEM768**: сочетает проверенную временем эллиптическую кривую X25519 и квантово-устойчивый алгоритм ML-KEM-768.
- Даже если в будущем алгоритм ML-KEM будет скомпрометирован математически, защита соединения останется на уровне надежности классического X25519.
- *Нюанс для SRE*: Постквантовые открытые ключи имеют больший размер (~1184 байта для ML-KEM-768 против 32 байт для X25519), что увеличивает размер сообщения `ClientHello` и требует контроля фрагментации TCP-пакетов и параметров MTU на граничных маршрутизаторах.

### Динамический размер записей TLS (`ssl_buffer_size`)

По умолчанию Nginx отправляет данные блоками размером 16 КБ (максимальный размер TLS-записи). 
- **Проблема задержки (Latency/TTFB)**: Клиентский браузер не может начать обработку данных до тех пор, пока не получит и не расшифрует TLS-запись целиком. Если соединение только установлено, а окно перегрузки TCP (congestion window, `cwnd`) невелико, запись размером 16 КБ разбивается на несколько TCP-сегментов (MSS ~1460 байт). Любая потеря сегмента блокирует дешифрование всего блока, увеличивая задержку Time To First Byte (TTFB).
- **Решение**: Установка директивы `ssl_buffer_size 4k` (или адаптивный размер через сторонние модули) снижает задержку первого байта для HTML/CSS/API-ответов, гарантируя, что запись помещается в стартовое окно TCP. Для массивных потоковых данных или отдачи тяжелых медиафайлов значение увеличивают обратно до `16k` для минимизации накладных расходов CPU на заголовки TLS-записей.

---

## Практические сценарии

### Сценарий 1: Проверка готовности окружения и зависимостей (SRE Pre-Flight)

Перед развертыванием или модификацией TLS-инфраструктуры системный администратор обязан проверить системные компоненты:

```bash
# 1. Проверка версии Nginx и версии скомпилированной библиотеки OpenSSL
nginx -V 2>&1 | grep -E -o '(nginx/[0-9.]+|built with OpenSSL [0-9.a-z\-]+)'
# → nginx/1.26.2
# → built with OpenSSL 3.5.1

# 2. Проверка наличия модуля ALPN и HTTP/3 (QUIC)
nginx -V 2>&1 | tr ' ' '\n' | grep -E 'http_ssl_module|http_v2_module|http_v3_module'
# → --with-http_ssl_module
# → --with-http_v2_module
# → --with-http_v3_module

# 3. Проверка поддержки и загрузки модуля kTLS в ядре Linux
uname -r
# → 6.8.0-49-generic

sudo modprobe tls
# → (exit code 0, модуль ядра успешно загружен)

lsmod | grep tls
# → tls                   135168  0
```

### Сценарий 2: Выпуск и сборка двойного стека сертификатов (ECDSA + RSA)

Для обеспечения максимальной производительности современных клиентов при сохранении резервной совместимости с legacy-системами настраивается выпуск двух независимых пар сертификатов с использованием утилиты Certbot:

```bash
# 1. Создание каталога для прохождения HTTP-01 ACME-челленджей
sudo mkdir -p /var/www/letsencrypt
sudo chown -R www-data:www-data /var/www/letsencrypt
sudo chmod 755 /var/www/letsencrypt
# → (exit code 0)

# 2. Выпуск основного производительного ECDSA-сертификата (P-256)
sudo certbot certonly --webroot -w /var/www/letsencrypt \
  -d example.com -d www.example.com \
  --key-type ecdsa --elliptic-curve prime256v1 --non-interactive --agree-tos -m admin@example.com
# → Successfully received certificate.
# → Certificate is saved at: /etc/letsencrypt/live/example.com/fullchain.pem
# → Key is saved at:         /etc/letsencrypt/live/example.com/privkey.pem

# 3. Выпуск резервного RSA-сертификата (3072 бит)
sudo certbot certonly --webroot -w /var/www/letsencrypt \
  -d example.com -d www.example.com \
  --cert-name example.com-rsa \
  --key-type rsa --rsa-key-size 3072 --non-interactive --agree-tos -m admin@example.com
# → Successfully received certificate.
# → Certificate is saved at: /etc/letsencrypt/live/example.com-rsa/fullchain.pem
# → Key is saved at:         /etc/letsencrypt/live/example.com-rsa/privkey.pem

# 4. Проверка корректности порядка сертификатов в сформированной цепочке Full Chain
openssl crl2pkcs7 -nocrl -certfile /etc/letsencrypt/live/example.com/fullchain.pem | \
  openssl pkcs7 -print_certs -noout | grep -E 'subject=|issuer='
# → subject=CN = example.com
# → issuer=C = US, O = Let's Encrypt, CN = E6
# → subject=C = US, O = Let's Encrypt, CN = E6
# → issuer=C = US, O = Internet Security Research Group, CN = ISRG Root X1
```

### Сценарий 3: Настройка защищенного виртуального хоста с Dual Stack, HSTS и HTTP/2

Конфигурация рабочего виртуального хоста `/etc/nginx/conf.d/example.com.conf` с наследованием глобальных политик шифрования и безопасным перенаправлением трафика:

```nginx
# Перенаправление незащищенного HTTP-трафика на HTTPS с сохранением ACME-маршрута
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Обслуживание валидации Let's Encrypt без принудительного HTTPS-редиректа
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type "text/plain";
        allow all;
    }

    # Постоянный редирект для всех остальных запросов
    location / {
        return 301 https://$host$request_uri;
    }
}

# Основной защищенный виртуальный хост HTTPS
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name example.com www.example.com;

    # 1. Основной стек сертификатов: ECDSA
    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # 2. Резервный стек сертификатов: RSA (fallback для устаревших клиентов)
    ssl_certificate     /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;

    # Защитный заголовок HSTS (2 года, включая поддомены, с поддержкой Preload)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Защита от утечки MIME-типов и Clickjacking на уровне заголовков
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    root /var/www/example.com/html;
    index index.html;

    # Отдача статики с максимальной эффективностью (sendfile + kTLS)
    location /static/ {
        alias /var/www/example.com/static/;
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Сценарий 4: Настройка нативной поддержки HTTP/3 (QUIC) поверх UDP

Интеграция HTTP/3 в блок `server` наряду с классическим TCP-сокетом:

```nginx
server {
    # Стандартный TCP TLS 1.3 / HTTP/2 сокет
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # Нативный QUIC / HTTP/3 сокет поверх UDP
    listen 443 quic reuseport;
    listen [::]:443 quic reuseport;
    http3 on;

    server_name example.com;

    # Сертификаты
    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # Защита от UDP-амплификации и подмены IP-адресов
    quic_retry on;

    # Анонсирование поддержки HTTP/3 через заголовок Alt-Svc (кеширование на 24 часа)
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Сценарий 5: Изолированный виртуальный хост Default Drop (`ssl_reject_handshake`)

Защита инфраструктуры от автоматического сканирования портов, перебора доменов и утечки сертификатов при обращении по прямому IP-адресу сервера:

```nginx
# Перехватчик любых обращений к неопределенным хостам на порту 443
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Немедленный сброс TLS-рукопожатия на этапе ClientHello без передачи сертификата
    ssl_reject_handshake on;
}
```

### Сценарий 6: Автоматизация ротации сертификатов и SRE-хук проверки

Для исключения сбоев в production при обновлении сертификатов настраивается хук systemd / Certbot, проверяющий целостность новой конфигурации перед перезагрузкой:

```bash
# 1. Создание скрипта безопасной перезагрузки /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
sudo tee /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh > /dev/null << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Проверка корректности конфигурации Nginx с новыми сертификатами
if /usr/sbin/nginx -t > /dev/null 2>&1; then
    /usr/bin/systemctl reload nginx
    logger -t certbot-reload "Nginx configuration verified and reloaded successfully."
else
    logger -s -t certbot-reload "CRITICAL: Nginx config test failed after certificate renewal. Reload aborted."
    exit 1
fi
EOF

# 2. Установка прав на исполнение
sudo chmod 750 /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
# → (exit code 0)

# 3. Тестовый сухой прогон обновления сертификатов
sudo certbot renew --dry-run
# → Processing /etc/letsencrypt/renewal/example.com.conf
# → Simulating renewal of an existing certificate for example.com and www.example.com
# → The dry run was successful.
```

---

## Операции и команды

### Управление службой и жизненным циклом Nginx

| Действие | Команда | Описание и SRE-контекст |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `sudo nginx -t` | Полная валидация всех конфигурационных файлов и проверка доступности файлов ключей. |
| **Вывод всей конфигурации** | `sudo nginx -T` | Дамп единого скомпилированного конфига Nginx (удобно для аудита директив TLS). |
| **Graceful Reload** | `sudo systemctl reload nginx` | Перезагрузка конфигурации воркеров без разрыва существующих TLS-соединений. |
| **Переоткрытие логов** | `sudo nginx -s reopen` | Переоткрытие дескрипторов файлов логов (отправка сигнала `USR1`). |
| **Бесшовный апгрейд бинарника** | `sudo kill -USR2 $(cat /run/nginx.pid)` | Запуск нового master-процесса без прекращения обслуживания входящих TLS-сессий. |
| **Плавное завершение старых воркеров** | `sudo kill -WINCH $(cat /run/nginx.pid.oldbin)` | Корректная остановка воркеров старого бинарника после успешного прогрева нового. |

### Диагностика параметров и рукопожатия TLS

```bash
# 1. Проверка синтаксиса конфигурации перед применением изменений
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Безопасное применение изменений без прерывания трафика
sudo systemctl reload nginx
# → (exit code 0, конфигурация применена)

# 3. Комплексная проверка согласованного протокола, шифра и статуса OCSP Stapling
openssl s_client -connect 127.0.0.1:443 -servername example.com -status < /dev/null 2>&1 | \
  grep -E '(Protocol|Cipher    :|OCSP Response Status|Peer signature)'
# → OCSP Response Status: successful (0x0)
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → Peer signature type: ECDSA

# 4. Проверка передачи полной цепочки сертификатов (наличие Leaf и Intermediate)
openssl s_client -connect 127.0.0.1:443 -servername example.com -showcerts < /dev/null 2>&1 | \
  grep -E '^[ 0-9]+ s:|i:'
# →  0 s:CN = example.com
# →    i:C = US, O = Let's Encrypt, CN = E6
# →  1 s:C = US, O = Let's Encrypt, CN = E6
# →    i:C = US, O = Internet Security Research Group, CN = ISRG Root X1

# 5. Тестирование принудительного использования TLS 1.3
openssl s_client -connect 127.0.0.1:443 -servername example.com -tls1_3 < /dev/null 2>&1 | \
  grep "Secure Session"
# → New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384

# 6. Проверка поддержки HTTP/3 (QUIC) через сетевой стек
ss -ulpn | grep :443
# → UNCONN 0      0            0.0.0.0:443       0.0.0.0:*    users:(("nginx",pid=14201,fd=8))

# 7. Тестирование отдачи заголовка Alt-Svc через curl с поддержкой HTTP/3
curl --http3 -sI https://example.com --resolve example.com:443:127.0.0.1 | grep -i alt-svc
# → alt-svc: h3=":443"; ma=86400

# 8. Проверка срока действия установленного сертификата на диске
openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -dates
# → notBefore=Jan 15 00:00:00 2026 GMT
# → notAfter=Apr 15 23:59:59 2026 GMT
```

### Мониторинг и аудит TLS-метрик (SRE Observability)

Для глубокого анализа качества трафика, выявления устаревших клиентов и мониторинга попыток атак в блок `http` добавляется выделенный формат аудита TLS:

```nginx
# Формат расширенного аудита безопасности TLS
log_format tls_audit '$remote_addr - $remote_user [$time_local] '
                     '"$request" $status $body_bytes_sent '
                     'proto=$ssl_protocol cipher=$ssl_cipher '
                     'curves=$ssl_curves session_reused=$ssl_session_reused '
                     'sni=$ssl_server_name early_data=$ssl_early_data';

server {
    listen 443 ssl;
    server_name example.com;

    access_log /var/log/nginx/tls_audit.log tls_audit;
}
```

Анализ логов штатными утилитами командной строки:

```bash
# Подсчет распределения используемых протоколов TLS
awk -F'proto=' '{print $2}' /var/log/nginx/tls_audit.log | awk '{print $1}' | sort | uniq -c | sort -rn
# → 14520 TLSv1.3
# →  1230 TLSv1.2

# Проверка эффективности кэширования сессий (Session Reuse Rate)
awk -F'session_reused=' '{print $2}' /var/log/nginx/tls_audit.log | awk '{print $1}' | sort | uniq -c
# → 11800 r      # (возобновленные сессии - cache hit)
# →  3950 .      # (полные рукопожатия - cache miss)
```

---

## Устранение неполадок

### Матрица типовых ошибок TLS в Nginx

| Симптом / Ошибка в логе | Вероятная первопричина | Метод локализации | Решение |
| :--- | :--- | :--- | :--- |
| `SSL_do_handshake() failed: no shared cipher` | Клиент и сервер не имеют общих поддерживаемых шифров (например, legacy-клиент требует CBC, а сервер разрешает только AEAD). | `openssl ciphers -v` на сервере и `grep ssl_ciphers /etc/nginx/nginx.conf`. | Добавить в `ssl_ciphers` совместимый AEAD-шифр или проверить, что `ssl_protocols` разрешает `TLSv1.2`. |
| `SSL_do_handshake() failed: alert handshake failure (40)` | Клиент не передал имя хоста через SNI, не сошлись версии протоколов, либо запрос попал на хост с `ssl_reject_handshake on`. | `openssl s_client -connect ...` с параметром `-servername` и без него. | Убедиться, что клиент поддерживает SNI. Проверить сопоставление `server_name` и сертификата. |
| `unable to get local issuer certificate` | В директиве `ssl_certificate` указан только сертификат хоста (`cert.pem`) вместо полной цепочки (`fullchain.pem`). | `openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt cert.pem` выдает ошибку уровня 1. | Объединить конечный сертификат и промежуточные сертификаты CA в один файл в правильном порядке. |
| `cannot load certificate ... Permission denied` | Рабочие процессы Nginx (`worker_processes`, пользователь `www-data` или `nginx`) не имеют прав на чтение каталога с приватными ключами. | `namei -l /etc/letsencrypt/live/example.com/privkey.pem`. | Настроить права доступа: группа `www-data`, права `0640` на файл ключа, `0750` на директории. |
| `ssl_stapling: no data` или `OCSP responder timed out` | Nginx не может разрешить DNS-имя OCSP-респондера или фаервол блокирует исходящие UDP/TCP запросы на порт 53 / 80. | `cat /etc/resolv.conf`, проверка наличия директивы `resolver` внутри блока `http`. | Задать директиву `resolver 127.0.0.1 8.8.8.8 valid=300s;` в блоке `http` и открыть исходящий трафик. |
| `0-RTT early data rejected` (HTTP статус `425 Too Early`) | Бэкенд-сервер отклоняет повторные небезопасные запросы (POST/PUT), переданные клиентом в структуре Early Data. | Проверить заголовки: `grep Early-Data /var/log/nginx/access.log`. | Передавать `$ssl_early_data` в заголовке `Early-Data` бэкенду и разрешать 0-RTT только для идемпотентных методов (`GET`, `HEAD`). |
| `cannot load certificate key ... key values mismatch` | Приватный ключ не соответствует открытому ключу в загруженном сертификате. | Сравнить контрольные суммы модулей: `openssl x509 -noout -modulus ...` и `openssl rsa -noout -modulus ...`. | Перевыпустить сертификат или восстановить правильный файл закрытого ключа из резервной копии. |

### Пошаговые сценарии устранения инцидентов

#### 1. Инцидент: Разорванная цепочка доверия (Missing Intermediate Certificate)

*Симптом*: Десктопные браузеры открывают сайт корректно (так как кэшируют промежуточные сертификаты), а мобильные клиенты, curl и бэкенд-сервисы возвращают ошибку `SSL certificate problem: unable to get local issuer certificate`.

```bash
# 1. Диагностика: проверка количества сертификатов, отдаваемых сервером
openssl s_client -connect 127.0.0.1:443 -servername example.com < /dev/null 2>&1 | grep "Certificate chain" -A 4
# → Certificate chain
# →  0 s:CN = example.com
# →    i:C = US, O = Let's Encrypt, CN = E6
# (Цепочка обрывается на уровне 0, Intermediate CA отсутствует!)

# 2. Локализация: проверка файла, указанного в конфигурации Nginx
grep -rn "ssl_certificate " /etc/nginx/conf.d/example.com.conf
# → 12:    ssl_certificate /etc/letsencrypt/live/example.com/cert.pem;

# 3. Устранение: замена одиночного сертификата cert.pem на полную цепочку fullchain.pem
sudo sed -i 's/cert.pem/fullchain.pem/g' /etc/nginx/conf.d/example.com.conf

# 4. Проверка синтаксиса и перезагрузка
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
sudo systemctl reload nginx

# 5. Верификация исправленной цепочки
openssl s_client -connect 127.0.0.1:443 -servername example.com < /dev/null 2>&1 | grep "Certificate chain" -A 6
# → Certificate chain
# →  0 s:CN = example.com
# →    i:C = US, O = Let's Encrypt, CN = E6
# →  1 s:C = US, O = Let's Encrypt, CN = E6
# →    i:C = US, O = Internet Security Research Group, CN = ISRG Root X1
```

#### 2. Инцидент: Ошибка прав доступа к закрытому ключу при запуске

*Симптом*: После ручного копирования ключей или восстановления из резервной копии команда `nginx -t` завершается фатальной ошибкой `BIO_new_file() failed (SSL: error:0200100D:system library:fopen:Permission denied)`.

```bash
# 1. Диагностика прав на закрытый ключ и цепочку родительских каталогов
sudo namei -l /etc/nginx/ssl/live/example.com/privkey.pem
# → f: /etc/nginx/ssl/live/example.com/privkey.pem
# → Drwxr-xr-x root root /
# → drwxr-xr-x root root etc
# → drwxr-xr-x root root nginx
# → drwx------ root root ssl
# → -rw------- root root privkey.pem
# (Пользователь worker-процесса www-data не может прочитать каталог ssl и файл privkey.pem!)

# 2. Исправление владельцев и прав доступа по принципу наименьших привилегий
sudo chown -R root:www-data /etc/nginx/ssl
sudo find /etc/nginx/ssl -type d -exec chmod 750 {} \;
sudo find /etc/nginx/ssl -type f -name "*.pem" -exec chmod 640 {} \;

# 3. Повторная проверка синтаксиса
sudo -u www-data nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
```

---

## Рекомендации и лучшие практики

### Чеклист промышленной безопасности TLS (Production Baseline)

- [ ] **Протоколы**: Устаревшие протоколы SSLv2, SSLv3, TLSv1.0, TLSv1.1 принудительно отключены. Разрешены исключительно `TLSv1.2 TLSv1.3`.
- [ ] **Шифронаборы**: В директиве `ssl_ciphers` объявлены только стойкие AEAD-алгоритмы (AES-GCM, ChaCha20-Poly1305). Шифры с режимом CBC, алгоритмами 3DES, RC4 и хэшем SHA-1 исключены.
- [ ] **PFS и квантовая устойчивость**: Настроена директива `ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;` для поддержки гибридного постквантового обмена ключами.
- [ ] **Цепочка доверия**: Директива `ssl_certificate` указывает на файл полной цепочки (Leaf + Intermediate CA). Корневой сертификат исключен для экономии сетевого MTU.
- [ ] **OCSP Stapling**: Директивы `ssl_stapling on;` и `ssl_stapling_verify on;` активированы в блоке `http`, настроен надежный локальный DNS-резолвер (`resolver 127.0.0.1 ... valid=300s;`).
- [ ] **HSTS**: Заголовок `Strict-Transport-Security` объявлен со сроком не менее 1 года (`max-age=63072000`) с параметрами `includeSubDomains; preload`.
- [ ] **Сессионные тикеты (STEK)**: `ssl_session_tickets off;` для гарантии Perfect Forward Secrecy, либо организована автоматическая синхронизация файлов ключей между серверами фермы.
- [ ] **Кэш сессий**: Выделена разделяемая зона памяти `ssl_session_cache shared:SSL:20m;` с тайм-аутом `ssl_session_timeout 1d;`.
- [ ] **Аппаратное ускорение и Zero-Copy**: Активирован kTLS через `ssl_conf_command Options +KTLS;` при работе на ядрах Linux 5.15+/6.x.
- [ ] **Защита от сканирования SNI**: Настроен виртуальный хост `default_server` с директивой `ssl_reject_handshake on;`.
- [ ] **Минимизация утечки метаданных**: Отключена передача версии веб-сервера через `server_tokens off;`.
- [ ] **Права на файловой системе**: Права на файлы закрытых ключей ограничены значением `0640` (владелец `root:www-data`), директории — `0750`.
- [ ] **Автоматизация ротации**: Таймеры обновления сертификатов (systemd timer) настроены с обязательным выполнением проверочного хука `nginx -t` перед отправкой сигнала `reload`.

### SRE-рекомендации по тюнингу производительности

1. **Размер кэша сессий (`ssl_session_cache`)**:
   - Расчет объема: 1 МБ памяти вмещает примерно 4000 сессионных записей.
   - Для сервера с пиковой нагрузкой 5 000 новых рукопожатий в секунду и средним временем жизни сессии 1 час (3600 с):
     $$\text{Требуемая емкость} = 5000 \times 3600 \times \text{Session Reuse Ratio} \approx 100\,000 \text{ активных сессий}$$
   - Оптимальный размер: `ssl_session_cache shared:SSL:25m;` (вмещает ~100 000 сессий).

2. **Защита от TLS Exhaustion DoS-атак**:
   - TLS-рукопожатие с асимметричной криптографией потребляет в 5–7 раз больше ресурсов CPU сервера, чем клиента.
   - Для предотвращения исчерпания вычислительных ресурсов воркеров входящие соединения на порт 443 лимитируются с помощью модуля `ngx_http_limit_conn_module`:
     ```nginx
     limit_conn_zone $binary_remote_addr zone=ssl_per_ip:10m;
     
     server {
         listen 443 ssl;
         limit_conn ssl_per_ip 50;
         limit_conn_status 429;
     }
     ```

3. **Оптимизация сетевых буферов**:
   - Для снижения задержки первого байта (TTFB) устанавливается `ssl_buffer_size 4k;`.
   - Включаются опции сокета `tcp_nodelay on;` (отключение алгоритма Нейгла для мгновенной отправки заголовков) и `tcp_nopush on;` (пакетирование полных MSS перед отправкой через `sendfile`).

### Эталонный конфигурационный блок `http` (`/etc/nginx/nginx.conf`)

Централизованный эталон глобальных параметров безопасности для включения в базовую конфигурацию веб-сервера:

```nginx
http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # 1. Протоколы и наборы шифров
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
    ssl_prefer_server_ciphers off;

    # 2. Криптографические кривые и постквантовый гибридный обмен
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;

    # 3. Кэширование TLS-сессий (PFS-first подход)
    ssl_session_cache shared:SSL:20m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # 4. OCSP Stapling и системный резолвер
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 127.0.0.1 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 3s;

    # 5. Оптимизация задержки и Zero-Copy Offload
    ssl_buffer_size 4k;
    ssl_conf_command Options +KTLS;

    # 6. Общая безопасность
    server_tokens off;

    # Включение виртуальных хостов
    include /etc/nginx/conf.d/*.conf;
}
```

---

## Дополнительная информация

### См. также

- **[Глобальные параметры TLS в Nginx](./nginx_tls_global_parameters.md)** — детальный справочник параметров уровня `http` (`ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`, `ssl_stapling`).
- **[Конфигурация виртуальных хостов TLS в Nginx](./nginx_tls_virtual_host_config.md)** — параметры уровня `server`, SNI-маршрутизация, настройка ECH и 0-RTT Early Data.
- **[Диагностика TLS/SSL в Nginx и совместимость клиентов](./nginx_tls_troubleshooting_and_compatibility.md)** — методики устранения неполадок рукопожатия, матрицы клиентской совместимости и захват трафика.
- **[Настройка mTLS в Nginx](./nginx_mtls_configuration.md)** — реализация взаимной аутентификации по сертификатам (Mutual TLS) для внутренних сервисов и API.
- **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)** — автоматизация жизненного цикла сертификатов, ACME-клиенты и таймеры systemd.
- **[Харденинг Nginx: systemd и SELinux](../nginx_systemd_selinux_hardening.md)** — песочницы systemd, политики SELinux и ограничение системных привилегий веб-сервера.
- **[Оптимизация производительности Nginx](../../Performance/nginx_performance_tuning.md)** — тюнинг параметров ядра Linux, сокетов, пулов соединений и режима Zero-Copy.
- **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md)** — тонкая настройка мультиплексирования, QUIC-стека и транспортных потоков.
- **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)** — фундаментальная теория криптографических рукопожатий, AEAD-шифров и математических моделей безопасности.
