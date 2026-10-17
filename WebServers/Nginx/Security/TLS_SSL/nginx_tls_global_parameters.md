# Глобальные параметры TLS в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x – 1.30.x (Mainline), OpenSSL 3.0+ / 3.5+, Linux Kernel 5.15+ / 6.x

## Определения

**Глобальные параметры TLS** — директивы конфигурации, объявляемые в блоке `http` файла `nginx.conf`, которые определяют базовую политику безопасности, параметры шифрования и оптимизации производительности для всех виртуальных хостов (`server`). Централизация настроек на уровне `http` устраняет дублирование директив, исключает риск человеческой ошибки при добавлении новых доменов и обеспечивает сквозное соответствие инфраструктурным стандартам безопасности.

**Область видимости директивы (Scope)** — контекст конфигурации Nginx, определяющий границы действия директивы:
- **`http`** (глобальный): задает параметры по умолчанию для всех виртуальных хостов (`ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`, `ssl_session_timeout`, `ssl_ecdh_curve`, `ssl_stapling`, `ssl_buffer_size`, `ssl_conf_command`).
- **`server`** (уровень хоста): переопределяет или дополняет глобальные параметры для конкретного доменного имени или IP-адреса (`ssl_certificate`, `ssl_certificate_key`, `ssl_early_data`, `ssl_reject_handshake`).
- **`location`** (локальный): ограничен директивами аутентификации клиента (`ssl_verify_client`) и проксирования.

**Разделяемая зона памяти (`shared:NAME:SIZE`)** — область оперативной памяти, аллоцируемая через механизм shared memory (`shmget` / `mmap`) и доступная всем рабочим процессам (worker processes) Nginx через внутренний slab-аллокатор. Используется для хранения общего кэша TLS-сессий (`ssl_session_cache`) и кэша ответов OCSP (`ssl_ocsp_cache`).

**Perfect Forward Secrecy (PFS)** — свойство криптографического протокола, гарантирующее, что компрометация долгосрочного закрытого ключа сервера не позволяет расшифровать ранее перехваченный сетевой трафик. В Nginx обеспечивается использованием эфемерных алгоритмов обмена ключами (ECDHE). Теория протокола: **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)**.

**Session ID vs Session Tickets (STEK)** — два механизма возобновления TLS-сессий без выполнения полного асимметричного рукопожатия:
- **Session ID (RFC 5246):** сервер сохраняет состояние соединения в локальной разделяемой памяти (`ssl_session_cache`) и возвращает клиенту 32-байтный идентификатор. Сохраняет PFS при перезапуске и очистке кэша.
- **Session Tickets (RFC 5077 / RFC 8446):** сервер шифрует параметры сессии симметричным ключом (Session Ticket Encryption Key, STEK) и передает зашифрованный тикет клиенту. Позволяет возобновлять сессии между разными серверами в кластере при синхронизации файлов ключей (`ssl_session_ticket_key`).

**OCSP Stapling** — механизм оптимизации проверки статуса цифрового сертификата (RFC 6066 / RFC 6960), при котором Nginx асинхронно запрашивает подписанный OCSP-ответ у удостоверяющего центра (CA) и передает его клиенту в структуре сообщения ServerHello. Избавляет клиента от необходимости выполнять отдельный DNS- и HTTP-запрос к responder CA, снижая задержку установки соединения (TLS Handshake Latency) и исключая утечку посещаемых доменов третьей стороне. Архитектура PKI: **[PKI — инфраструктура открытых ключей](../../../../Security/Concepts/pki_overview.md)**.

**kTLS (Kernel TLS)** — механизм ядра Linux (начиная с Kernel 4.17/5.10+), позволяющий перенести операции симметричного шифрования и дешифрования TLS (AES-GCM, ChaCha20-Poly1305) из пространства пользователя (user-space) в ядро. Это позволяет Nginx использовать системный вызов `sendfile()` для отдачи статических файлов напрямую из pagecache в сетевой сокет в режиме Zero-Copy.

**Hybrid PQC (Post-Quantum Cryptography)** — гибридные схемы обмена ключами, сочетающие классическую эллиптическую криптографию (X25519) и постквантовые алгоритмы инкапсуляции ключей (ML-KEM-768, стандартизированный NIST FIPS 203, ранее Kyber). В Nginx с библиотекой OpenSSL 3.5+ и 4.0+ гибридный обмен ключами поддерживается через директиву `ssl_ecdh_curve`.

**Размер TLS-записи (`ssl_buffer_size`)** — размер блока данных (TLS record), формируемого сервером перед шифрованием и отправкой в TCP-сокет. Варьируется от 256 байт до 16 КБ. Оказывает прямое влияние на показатель Time To First Byte (TTFB) на клиенте.

---

## Архитектура и основные концепции

### Иерархия наследования директив TLS

Конфигурация TLS в Nginx строго иерархична. Блок `http` выступает корнем для всех веб-сервисов:

```text
┌────────────────────────────────────────────────────────┐
│                      Блок http                         │
│  Глобальная политика: ssl_protocols, ssl_ciphers,      │
│  ssl_session_cache, ssl_stapling, ssl_buffer_size,      │
│  ssl_ecdh_curve, ssl_conf_command, resolver            │
└───────────┬────────────────────────────────┬───────────┘
            │ наследуется                    │ наследуется
            ▼                                ▼
┌───────────────────────────┐  ┌───────────────────────────┐
│     server (Хост A)       │  │     server (Хост B)       │
│ ssl_certificate           │  │ ssl_certificate           │
│ ssl_certificate_key       │  │ ssl_certificate_key       │
│ [наследует параметры http]│  │ ssl_ciphers (переопределен)│
└───────────────────────────┘  └───────────────────────────┘
```

**Критическое правило наследования Nginx:** директивы TLS не объединяются, а полностью замещаются. Если внутри блока `server` объявлена директива `ssl_ciphers`, глобальный список шифров из блока `http` для этого хоста полностью игнорируется. Если директива не объявлена в `server`, действует значение из блока `http`.

### Модель памяти и Slab-аллокатор кэша сессий

Nginx использует многопроцессную архитектуру без общих потоков исполнения (shared-nothing between workers). Каждый рабочий процесс (`worker`) обслуживает свои клиентские соединения. Без общей разделяемой памяти сессия, созданная процессом `worker 1`, не может быть возобновлена процессом `worker 2`, что приводило бы к принудительным повторным полным рукопожатиям при балансировке запросов операционной системой.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        Master Процесс Nginx                             │
│   (Инициализирует сегмент shared memory при старте или reload)          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
      ┌──────────────────────────────┼──────────────────────────────┐
      ▼                              ▼                              ▼
┌──────────────┐              ┌──────────────┐              ┌──────────────┐
│   Worker 1   │              │   Worker 2   │              │   Worker 3   │
└──────┬───────┘              └──────┬───────┘              └──────┬───────┘
       │                             │                             │
       └─────────────────────────────┼─────────────────────────────┘
                                     ▼
        ┌────────────────────────────────────────────────────────┐
        │       Shared Memory Zone: ssl_session_cache            │
        │             (например, shared:SSL:20m)                 │
        │  ┌──────────────────────────────────────────────────┐  │
        │  │ Red-Black Tree (поиск сессии по 32-байтному ID)  │  │
        │  ├──────────────────────────────────────────────────┤  │
        │  │ LRU Queue (вытеснение устаревших записей)        │  │
        │  ├──────────────────────────────────────────────────┤  │
        │  │ Slab Allocator (пулы слотов 128B / 256B / 512B)   │  │
        │  └──────────────────────────────────────────────────┘  │
        └────────────────────────────────────────────────────────┘
```

#### Механизм хранения сессии
1. В разделяемой зоне памяти Nginx организует красно-черное дерево (Red-Black Tree) для быстрого бинарного поиска сессии по 32-байтному ключу (Session ID).
2. Очередь LRU (Least Recently Used) отслеживает время последнего обращения к сессии. При исчерпании свободных блоков памяти старейшие неиспользуемые сессии вытесняются принудительно, даже если их таймаут `ssl_session_timeout` еще не истек.
3. Каждая запись содержит: Session ID, Master Secret (48 байт), информацию о протоколе, согласованном шифре, метаданные и метку времени. Размер одной записи составляет от 250 до 500 байт в зависимости от версии OpenSSL.

#### Расчет емкости памяти для `ssl_session_cache`
1 мегабайт shared memory в Nginx вмещает порядка 4 000 сессий.

| Размер зоны | Вместимость сессий | Рекомендуемый профиль нагрузки | Расчетная память RAM |
| :--- | :--- | :--- | :--- |
| `shared:SSL:1m` | ~4 000 | Тестовые стенды, внутренние утилиты | 1 МБ |
| `shared:SSL:10m` | ~40 000 | Стандартный production (до 1 000 RPS) | 10 МБ |
| `shared:SSL:20m` | ~80 000 | Нагруженные порталы (1 000 – 5 000 RPS) | 20 МБ |
| `shared:SSL:50m` | ~200 000 | Крупные API-шлюзы (5 000 – 15 000 RPS) | 50 МБ |
| `shared:SSL:100m`| ~400 000 | Граничные балансировщики (15 000+ RPS) | 100 МБ |

### Режимы возобновления сессий: Session ID vs Session Tickets

```text
Режим: Session ID (ssl_session_cache shared:SSL:10m; ssl_session_tickets off;)
Клиент                                                    Nginx (Worker)
  │ 1. ClientHello                                              │
  ├────────────────────────────────────────────────────────────►│
  │ 2. ServerHello + Certificate + Handshake Finished           │
  │    [Session ID: a1b2c3d4...]                                │
  │◄────────────────────────────────────────────────────────────┤
  │    (Сессия сохраняется в локальной shared memory Nginx)    │
  │ 3. ClientHello [Session-Resume: a1b2c3d4...] (1-RTT)        │
  ├────────────────────────────────────────────────────────────►│ (Поиск в shared memory)
  │ 4. ServerHello + Finished                                   │
  │◄────────────────────────────────────────────────────────────┤
```

- **Session Cache (Session ID):** наиболее безопасный вариант. Ключи шифрования хранятся исключительно в оперативной памяти сервера и никогда не покидают хост. Полностью обеспечивает Perfect Forward Secrecy.
- **Session Tickets (RFC 5077):** сервер шифрует состояние сессии симметричным ключом (Session Ticket Encryption Key, STEK). Если на сервере включена директива `ssl_session_tickets on;`, но не настроена ротация файла `ssl_session_ticket_key`, Nginx генерирует временный STEK в памяти master-процесса при старте.
  - *Проблема кластера:* Если перед несколькими узлами Nginx стоит L4-балансировщик нагрузки (Keepalived, IPVS, HAProxy), клиент при повторном подключении может попасть на соседнюю ноду. Если ноды не имеют одинакового ключа STEK, тикет будет отклонен, и произойдет деградация до полного рукопожатия (Full Handshake).
  - *Решение для кластера:* централизованная генерация и синхронизация файлов `ssl_session_ticket_key` по защищенному каналу.

### Протоколы и шифры

#### `ssl_protocols`
Задает допустимые версии TLS. Стандарт безопасности:
```nginx
ssl_protocols TLSv1.2 TLSv1.3;
```
- **Запрещены:** `SSLv2`, `SSLv3`, `TLSv1`, `TLSv1.1`. Протоколы официально объявлены устаревшими (RFC 7568, RFC 8996) из-за фундаментальных архитектурных уязвимостей (POODLE, BEAST, CRIME) и отсутствия поддержки современных аутентифицированных шифров (AEAD).

#### `ssl_ciphers`
Директива определяет список доступных шифров для протокола **TLS 1.2**.
В протоколе **TLS 1.3** наборы шифров (Ciphersuites) стандартизированы жестко и не настраиваются через директиву `ssl_ciphers`. В TLS 1.3 OpenSSL по умолчанию использует шифры:
1. `TLS_AES_256_GCM_SHA384`
2. `TLS_CHACHA20_POLY1305_SHA256`
3. `TLS_AES_128_GCM_SHA256`

Для TLS 1.2 применяются исключительно шифры класса AEAD (Authenticated Encryption with Associated Data) с эллиптическим обменом ключами:
```nginx
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
```

#### `ssl_prefer_server_ciphers`
- **`off` (стандарт):** клиент предлагает поддерживаемые алгоритмы, и сервер выбирает наиболее эффективный с точки зрения клиента. Это критически важно: мобильные устройства и встраиваемые системы без аппаратного блока AES-NI выбирают ChaCha20-Poly1305, что снижает нагрузку на процессор клиента и уменьшает задержки.
- **`on` (legacy):** сервер принудительно навязывает свой порядок шифров. Применялось в эпоху уязвимости CBC-шифров для принудительного использования RC4 или AES-CBC. В современных AEAD-окружениях не требуется.

### Эллиптические кривые и постквантовая криптография (`ssl_ecdh_curve`)

Директива `ssl_ecdh_curve` задает список кривых для эфемерного обмена ключами ECDHE:
- `X25519` — быстрая и безопасная кривая Монтгомери (RFC 7748).
- `prime256v1` (NIST P-256) — широко распространенная кривая для совместимости с корпоративными клиентами.
- `secp384r1` (NIST P-384) — используется в высокозащищенных контурах с сертификатами ECDSA P-384.
- `X25519MLKEM768` (ранее X25519Kyber768) — гибридная постквантовая схема в OpenSSL 3.5+. Комбинирует классический обмен X25519 и алгоритм инкапсуляции ключей ML-KEM-768, нейтрализуя угрозу атак «Harvest Now, Decrypt Later».

Приоритетная строка для Nginx:
```nginx
ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
```

### Параметры Диффи-Хеллмана (`ssl_dhparam`)

Директива `ssl_dhparam` указывает путь к файлу с параметрами Диффи-Хеллмана для классических DHE-шифров (например, `DHE-RSA-AES128-GCM-SHA256`).
- **Современная практика:** DHE практически вытеснен ECDHE (на базе эллиптических кривых). ECDHE работает в 2-4 раза быстрее и не требует предварительной генерации тяжелых параметров.
- Если инфраструктура требует поддержки устаревших клиентов, использующих DHE, запрещено использовать стандартные параметры разрядностью 1024 бит (уязвимость Logjam). Обязательно использование безопасных простых чисел длиной не менее 2048 бит:
```bash
openssl dhparam -out /etc/nginx/ssl/dhparam2048.pem 2048
```

### Размер буфера TLS (`ssl_buffer_size`) и kTLS

```text
1. ssl_buffer_size 16k (По умолчанию):
   [--------- 16 КБ TLS Record Layer ---------]  ──► Клиент получает и расшифровывает
   (Браузер ждет наполнения всех 16 КБ перед тем, как передать первый чанк HTML парсеру)

2. ssl_buffer_size 4k (Оптимизация задержки TTFB):
   [-- 4 КБ --] ──► Немедленная расшифровка ──► Рендеринг DOM начался
   [-- 4 КБ --] ──► Потоковая обработка
```

- **`ssl_buffer_size 16k` (дефолт):** максимальный размер записи по стандарту TLS. Оптимален для непрерывной передачи объемных статических файлов (видео, образы, архивы), так как минимизирует накладные расходы на заголовки TLS-записей (5 байт заголовка + MAC/auth tag на каждые 16 КБ).
- **`ssl_buffer_size 4k` (или `8k`):** уменьшает размер блока данных. Браузер получает и расшифровывает первые 4 КБ HTML/CSS немедленно, не дожидаясь доставки остальных пакетов. Это сокращает Time To First Byte (TTFB) и First Contentful Paint (FCP) на 20–40% на мобильных и высоконагруженных сетях.

#### kTLS (Kernel TLS Offload)
kTLS переносит симметричное шифрование в стек сетевой подсистемы ядра Linux:
1. Рукопожатие (Handshake) и согласование ключей по-прежнему выполняет Nginx и OpenSSL в user-space.
2. После установки ключей дескриптор сокета переводится в режим ULP TLS (`setsockopt(fd, SOL_TLS, ...)`).
3. При отправке файла через директиву `sendfile on;` ядро берет страницы из дискового кэша (pagecache) и шифрует их на лету аппаратно или программно в ядре перед помещением в буфер сетевой карты (NIC TX ring). Исключается копирование данных в память процесса Nginx и обратный системный вызов `write()`.

### OCSP Stapling и оффлайн-режим (Air-Gapped)

Для работы `ssl_stapling` на глобальном уровне Nginx выполняет следующие действия:
1. При старте или периодически (раз в 1–3 часа) master/worker процесс считывает URL OCSP-ответчика из расширения Authority Information Access (AIA) серверного сертификата.
2. Выполняет DNS-запрос через адреса, указанные в директиве `resolver`.
3. Запрашивает статус сертификата по HTTP и сохраняет подписанный ответ CA в памяти.
4. При рукопожатии передает этот кэшированный ответ клиенту в блоке `CertificateStatus`.

```nginx
ssl_stapling on;
ssl_stapling_verify on;
resolver 127.0.0.53 192.168.1.1 valid=300s ipv6=off;
resolver_timeout 5s;
```
*Параметр `ipv6=off`:* критически важен в enterprise-сетях без настроенной маршрутизации IPv6. Предотвращает зависание Nginx на попытках резолвить AAAA-записи OCSP-респондера.

**Оффлайн-режим для изолированных контуров (Air-Gapped):**
В закрытых периметрах (без прямого выхода в интернет) автоматический запрос к внешним респондерам невозможен. Для таких сред Nginx поддерживает директиву `ssl_stapling_file`, позволяющую передавать предварительно выгруженный статический файл OCSP-ответа.

### Защита Default Server (`ssl_reject_handshake`)

По умолчанию, если клиент обращается по IP-адресу или передает в SNI неизвестный хост, Nginx отправляет сертификат первого объявленного виртуального хоста (`default_server`). Это приводит к утечке внутренних доменных имен сканерам портов и ботнетам.

Директива `ssl_reject_handshake on;` (доступна с Nginx 1.19.4+) принудительно обрывает рукопожатие на стадии ClientHello:
```nginx
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
}
```
Сертификат клиенту не передается, соединение немедленно закрывается с ошибкой TLS alert (`unrecognized_name`), процессорное время на шифрование не расходуется.

---

## Практические сценарии и конфигурация

### Сценарий 1: Эталонная глобальная конфигурация `nginx.conf` (High-Load Hardened Production)

Конфигурация для высоконагруженных bare-metal серверов и виртуальных машин. Включает TLS 1.3/1.2, гибридные PQC-кривые, оптимизацию TTFB, кэш сессий и защиту от сканирования.

```nginx
# /etc/nginx/nginx.conf

user www-data;
worker_processes auto;
worker_rlimit_nofile 65535;
pid /run/nginx.pid;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # --- Оптимизация сети и файлового ввода-вывода ---
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65s;
    keepalive_requests 1000;

    # --- Безопасность версии сервера ---
    server_tokens off;

    # =========================================================================
    # ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ TLS / SSL
    # =========================================================================

    # 1. Протоколы: строго современные версии, исключая SSLv3, TLS 1.0, 1.1
    ssl_protocols TLSv1.2 TLSv1.3;

    # 2. Наборы шифров для TLS 1.2 (только безопасные AEAD алгоритмы)
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';

    # 3. Приоритет шифра: off позволяет клиенту выбирать эффективный шифр (ChaCha20 на мобильных)
    ssl_prefer_server_ciphers off;

    # 4. Эллиптические кривые и постквантовый гибридный обмен (OpenSSL 3.5+)
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;

    # 5. Управление кэшем сессий (Session ID возобновление в shared memory)
    # 20m = ~80 000 сессий, срок жизни сессии 1 сутки
    ssl_session_cache shared:SSL:20m;
    ssl_session_timeout 1d;

    # 6. Сессионные тикеты отключены для гарантии Perfect Forward Secrecy
    ssl_session_tickets off;

    # 7. Оптимизация задержки TTFB (размер TLS-записи 4 КБ вместо 16 КБ)
    ssl_buffer_size 4k;

    # 8. Интеграция с Kernel TLS (Linux 5.10+, OpenSSL 3.0+ с флагом enable-ktls)
    ssl_conf_command Options +KTLS;

    # 9. Глобальный OCSP Stapling (асинхронная проверка сертификатов)
    ssl_stapling on;
    ssl_stapling_verify on;
    # Корпоративный или локальный DNS-резолвер с отключением медленного IPv6
    resolver 127.0.0.53 192.168.1.10 valid=300s ipv6=off;
    resolver_timeout 5s;

    # --- Формат структурированного логирования для аудита безопасности ---
    log_format tls_json escape=json '{'
        '"time_local":"$time_local",'
        '"remote_addr":"$remote_addr",'
        '"request_method":"$request_method",'
        '"request_uri":"$request_uri",'
        '"status":$status,'
        '"bytes_sent":$bytes_sent,'
        '"request_time":$request_time,'
        '"ssl_protocol":"$ssl_protocol",'
        '"ssl_cipher":"$ssl_cipher",'
        '"ssl_curve":"$ssl_curve",'
        '"ssl_curves":"$ssl_curves",'
        '"ssl_session_reused":"$ssl_session_reused",'
        '"ssl_server_name":"$ssl_server_name"'
    '}';

    access_log /var/log/nginx/access_tls.json tls_json;
    error_log /var/log/nginx/error.log warn;

    # =========================================================================
    # ЗАЩИТА DEFAULT SERVER (Отказ в рукопожатии без валидного SNI)
    # =========================================================================
    server {
        listen 443 ssl default_server;
        listen [::]:443 ssl default_server;
        server_name _;
        ssl_reject_handshake on;
    }

    # Подключение виртуальных хостов
    include /etc/nginx/conf.d/*.conf;
}
```

---

### Сценарий 2: Многоузловой кластер с синхронизацией ключей Session Tickets (STEK)

В распределенном кластере (2 и более серверов Nginx за L4-балансировщиком нагрузки) использование `ssl_session_tickets off;` приводит к тому, что клиент, подключаясь повторно и попадая на соседний сервер, выполняет полное рукопожатие. Для ускорения 0-RTT/1-RTT соединений настраивается синхронизация ключей STEK.

#### Конфигурация Nginx
```nginx
# В блоке http файла /etc/nginx/nginx.conf
ssl_session_cache shared:SSL:50m;
ssl_session_timeout 1d;

# Включение тикетов с использованием явных ключей шифрования
ssl_session_tickets on;
ssl_session_ticket_key /etc/nginx/ssl/tickets/ticket_current.key;
ssl_session_ticket_key /etc/nginx/ssl/tickets/ticket_previous.key;
```
*Принцип работы:* Первый ключ используется для шифрования новых тикетов и дешифрования. Второй (previous) — только для дешифрования старых тикетов, выданных до ротации.

#### Bash-скрипт автоматической ротации ключей STEK (`/usr/local/bin/rotate_stek.sh`)
Скрипт генерирует 80-байтный криптографически стойкий ключ (16 байт ID + 32 байта AES-256 + 32 байта HMAC-SHA256) и обновляет ноды кластера.

```bash
#!/usr/bin/env bash
set -euo pipefail

KEY_DIR="/etc/nginx/ssl/tickets"
CLUSTER_NODES=("node01.internal" "node02.internal" "node03.internal")

mkdir -p "${KEY_DIR}"
chmod 700 "${KEY_DIR}"

# Ротация локальных ключей: текущий становится предыдущим
if [[ -f "${KEY_DIR}/ticket_current.key" ]]; then
    mv -f "${KEY_DIR}/ticket_current.key" "${KEY_DIR}/ticket_previous.key"
fi

# Генерация нового 80-байтного ключа
openssl rand 80 > "${KEY_DIR}/ticket_current.key"
chmod 600 "${KEY_DIR}"/ticket_*.key
chown -R root:www-data "${KEY_DIR}"

# Распространение ключей по узлам кластера по защищенному SSH
for node in "${CLUSTER_NODES[@]}"; do
    if [[ "${node}" != "$(hostname -f)" ]]; then
        scp -q -p "${KEY_DIR}"/ticket_*.key "root@${node}:${KEY_DIR}/"
        ssh "root@${node}" "nginx -t && systemctl reload nginx"
    fi
done

# Применение на текущей ноде
nginx -t && systemctl reload nginx
```

Запуск по расписанию через systemd timer раз в 12 часов.

---

### Сценарий 3: Изолированный enterprise-контур (Air-Gapped) со статическим OCSP

В средах без выхода в интернет удостоверяющий центр выпускает сертификаты внутри периметра, либо используются публичные сертификаты, но серверы Nginx изолированы от сети. Стандартный `ssl_stapling` завершится ошибкой таймаута DNS.

```nginx
http {
    # ... общие директивы ...

    # Глобальный доверенный CA-бандл для проверки OCSP ответов
    ssl_trusted_certificate /etc/nginx/pki/internal_chain_ca.pem;

    # OCSP Stapling включен глобально
    ssl_stapling on;
    ssl_stapling_verify on;

    # В виртуальном хосте подключается предварительно выгруженный статический ответ
    server {
        listen 443 ssl;
        server_name app.corp.internal;

        ssl_certificate /etc/nginx/ssl/app.corp.internal.crt;
        ssl_certificate_key /etc/nginx/ssl/app.corp.internal.key;

        # Статический файл с ответом OCSP, доставленный службой управления конфигурацией
        ssl_stapling_file /etc/nginx/ssl/ocsp_responses/app.corp.internal.ocsp.der;
    }
}
```

Команда получения DER-ответа на хосте с доступом в интернет для последующей доставки на air-gapped ноду:
```bash
openssl ocsp -issuer /path/to/intermediate_ca.pem \
             -cert /path/to/server_cert.pem \
             -url http://ocsp.internal-ca.local:8888 \
             -respout /tmp/app.corp.internal.ocsp.der -noverify
```

---

### Сценарий 4: Системный тюнинг ядра Linux для TLS (Sysctl & Limits)

Высокая интенсивность TLS-рукопожатий требует расширения системных очередей TCP и оптимизации буферов сокетов.

Файл конфигурации `/etc/sysctl.d/99-nginx-tls.conf`:
```ini
# Максимальный размер очереди не принятых сокетов (listen backlog)
net.core.somaxconn = 65535

# Максимальное количество запоминаемых запросов на соединение (SYN flood защита и емкость)
net.ipv4.tcp_max_syn_backlog = 3240000

# Разрешение повторного использования сокетов TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# TCP Fast Open (значение 3 включает TFO для входящих и исходящих соединений)
net.ipv4.tcp_fastopen = 3

# Отключение сброса окна перегрузки после простоя (сохраняет скорость при TLS keepalive)
net.ipv4.tcp_slow_start_after_idle = 0

# Загрузка модуля ядра для kTLS при старте
# (требует строки tls в /etc/modules-load.d/tls.conf)
```

Применение параметров ядра:
```bash
sudo sysctl --system
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_max_syn_backlog = 3240000
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.tcp_fastopen = 3
# → net.ipv4.tcp_slow_start_after_idle = 0
```

Проверка и загрузка модуля ядра `tls`:
```bash
sudo modprobe tls
lsmod | grep -E '^tls\s'
# → tls                   114688  0
```

---

## Операции и команды

### Управление службой и валидация

```bash
# 1. Проверка синтаксиса конфигурации и валидности сертификатов
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Полный дамп скомпилированной конфигурации (проверка глобальных блоков http)
sudo nginx -T | grep -E "ssl_protocols|ssl_ciphers|ssl_session_cache"
# → ssl_protocols TLSv1.2 TLSv1.3;
# → ssl_session_cache shared:SSL:20m;

# 3. Применение изменений без разрыва активных соединений (Graceful Reload)
sudo systemctl reload nginx

# 4. Проверка статуса службы
systemctl status nginx --no-pager
```

### Диагностика криптографических возможностей окружения

```bash
# Проверка наличия инструкций аппаратного шифрования AES-NI в CPU
lscpu | grep -i aes
# → Flags: ... aes ...

# Проверка версии OpenSSL и параметров сборки
openssl version -a
# → OpenSSL 3.5.0 8 Apr 2025 (Library: OpenSSL 3.5.0)

# Список шифров TLS 1.3, поддерживаемых локальной библиотекой OpenSSL
openssl list -tls1.3-cipher-algorithms
# → TLS_AES_256_GCM_SHA384
# → TLS_CHACHA20_POLY1305_SHA256
# → TLS_AES_128_GCM_SHA256

# Проверка поддержки гибридной кривой ML-KEM в OpenSSL
openssl ecparam -list_curves | grep -iE "mlkem|kyber"
# → X25519MLKEM768

# Проверка поддержки kTLS на уровне сокета в ядре
cat /proc/sys/net/ipv4/tcp_available_ulp
# → tls
```

### Валидация глобальных параметров на работающем сервере

```bash
# 1. Комплексная проверка протокола, шифра и статуса OCSP Stapling
openssl s_client -connect 127.0.0.1:443 -servername example.com -status < /dev/null 2>&1 | \
  grep -E "Protocol|Cipher|OCSP Response Status"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful (0x0)

# 2. Проверка изоляции default_server (сброс рукопожатия без валидного SNI)
openssl s_client -connect 127.0.0.1:443 < /dev/null 2>&1 | grep -i "handshake failure"
# → 4075549024:error:14094410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure:...

# 3. Проверка повторного использования сессий (Session Resumption via Session ID)
openssl s_client -connect 127.0.0.1:443 -servername example.com -reconnect < /dev/null 2>&1 | \
  grep "Reused"
# → Reused, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
# → Reused, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
# → Reused, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384

# 4. Проверка статистики kTLS в ядре Linux
cat /proc/net/tls_stat
# → TlsTxSw: 15420
# → TlsRxSw: 0
# → TlsTxDevice: 0
# → TlsRxDevice: 0
```

### SRE-анализ логов и расчет метрик

Используя лог `/var/log/nginx/access_tls.json`, администратор может рассчитывать ключевые показатели качества TLS:

```bash
# Расчет коэффициента повторного использования сессий (Session Reuse Rate)
# Переменная $ssl_session_reused возвращает 'r' при успешном возобновлении и '.' при полном рукопожатии
jq -r '.ssl_session_reused' /var/log/nginx/access_tls.json | sort | uniq -c
# → 85000 r
# → 15000 .
# Расчет: 85000 / (85000 + 15000) = 85.0% попаданий в кэш

# Распределение используемых версий протокола TLS
jq -r '.ssl_protocol' /var/log/nginx/access_tls.json | sort | uniq -c | sort -rn
# → 92000 TLSv1.3
# →  8000 TLSv1.2

# Топ-5 используемых шифров
jq -r '.ssl_cipher' /var/log/nginx/access_tls.json | sort | uniq -c | sort -rn | head -5
# → 65000 TLS_AES_256_GCM_SHA384
# → 27000 TLS_AES_128_GCM_SHA256
# →  5000 ECDHE-RSA-AES128-GCM-SHA256
# →  3000 TLS_CHACHA20_POLY1305_SHA256
```

---

## Устранение неполадок

### Матрица инцидентов и диагностических процедур

| Симптом / Ошибка в логе | Вероятная первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `could not allocate new session in shared memory zone "SSL"` | Размер разделяемой памяти `ssl_session_cache` недостаточен для текущего объема RPS. Старые сессии вытесняются с задержкой. | Проверить частоту появления ошибки в `error.log`. Сравнить текущий RPS с емкостью зоны памяти. | Увеличить размер зоны памяти: `ssl_session_cache shared:SSL:50m;`. Выполнить `systemctl reload nginx`. |
| `SSL: error:14094410:SSL routines:sslv3 alert handshake failure` | Клиент и сервер не имеют пересекающихся шифров или версий протоколов; либо клиент запросил недопустимый SNI на default_server. | Выполнить: `openssl s_client -connect IP:443 -tls1_2 -cipher 'DES-CBC3-SHA'`. Проверить `$ssl_server_name`. | Если ошибка возникает на легитимных legacy-клиентах, проверить, требуется ли включение Intermediate профиля шифров. Если на default_server — это штатная работа `ssl_reject_handshake`. |
| `no shared cipher` | Директива `ssl_ciphers` содержит синтаксическую ошибку либо все указанные шифры не поддерживаются библиотекой OpenSSL. | Проверить вывод команды `nginx -t` и сверить список шифров: `openssl ciphers -v '<строка_из_nginx>'`. | Скорректировать строку `ssl_ciphers`, исключив опечатки и устаревшие несовместимые алгоритмы. |
| `OCSP response: no response sent` или `ssl_stapling: no data` | Не настроен DNS-резолвер в блоке `http`, резолвер недоступен, либо порт 53/UDP заблокирован firewall. | `nginx -T \| grep resolver`. Проверить доступность DNS: `dig @<resolver_ip> <ocsp_host>`. | Добавить в блок `http`: `resolver 127.0.0.53 valid=300s ipv6=off; resolver_timeout 5s;`. Открыть доступ к DNS на firewall. |
| `certificate status: response has expired` | Ответ OCSP-респондера устарел, либо серверное системное время рассинхронизировано. | Проверить системное время: `timedatectl status`. Проверить ответ OCSP: `openssl ocsp ...`. | Синхронизировать системные часы по NTP (`chronyd` / `systemd-timesyncd`). Проверить доступность OCSP responder удостоверяющего центра. |
| `cannot load certificate ... BIO_new_file() failed` | Файл сертификата или закрытого ключа отсутствует, либо права доступа запрещают чтение процессу `worker`. | Проверить права: `namei -l /etc/nginx/ssl/server.key`. Проверить пользователя Nginx: `ps aux \| grep nginx`. | Установить права: ключи `600` (владелец `root`), сертификаты `644`, родительские каталоги `750` (`root:www-data`). |
| `Reused: No` при повторных запросах в кластере | Рассинхронизация ключей сессионных тикетов (`ssl_session_ticket_key`) между серверами за балансировщиком. | Сравнить контрольные суммы: `sha256sum /etc/nginx/ssl/tickets/ticket_*.key` на всех серверах кластера. | Запустить скрипт ротации ключей STEK (`rotate_stek.sh`) и синхронизировать файлы ключей по всем серверам. |
| `kTLS not working` / отсутствие прироста производительности | Модуль ядра `tls` не загружен, ядро Linux < 5.10, либо библиотека OpenSSL собрана без флага `enable-ktls`. | `lsmod \| grep tls`, `cat /proc/net/tls_stat`. Проверить вывод `nginx -V 2>&1 \| grep -i ktls`. | Выполнить `modprobe tls`, добавить `tls` в `/etc/modules`. Убедиться в наличии `ssl_conf_command Options +KTLS;` и `sendfile on;`. |

### Диагностический алгоритм при деградации задержки рукопожатия (Handshake Latency)

```text
Всплеск задержки (Handshake Latency Spike)
   │
   ├──► 1. Проверить процент повторного использования сессий (Session Reuse Rate)
   │      - Если показатель < 70%, проверить error.log на предмет:
   │        "could not allocate new session in shared memory zone"
   │      - Решение: увеличить размер shared memory (с 10m до 20m/50m).
   │
   ├──► 2. Проверить задержки DNS-резолвинга OCSP
   │      - Если resolver отвечает медленно (> 100ms), Nginx worker блокируется при обновлении stapling.
   │      - Решение: переключить resolver на локальный кэширующий DNS (dnsmasq / unbound / 127.0.0.53).
   │      - Обязательно добавить флаг ipv6=off в директиву resolver.
   │
   ├──► 3. Проверить утилизацию процессора (CPU Throttling / SoftIRQ)
   │      - Проверить наличие инструкций AES-NI: lscpu | grep aes
   │      - Если процессор без AES-NI, убедиться, что ssl_prefer_server_ciphers off;
   │        (клиенты используют ChaCha20-Poly1305 вместо программного AES).
   │
   └──► 4. Проверить размер TLS-буфера
          - Если для интерактивных страниц установлен дефолтный ssl_buffer_size 16k,
            уменьшить до 4k для сокращения TTFB.
```

---

## Рекомендации и лучшие практики

### Чек-лист соответствия глобальных параметров стандарту (2026 Baseline)

- [ ] **Протоколы:** разрешены исключительно `TLSv1.2 TLSv1.3;`. Протоколы SSLv3, TLS 1.0, 1.1 отключены в исходной конфигурации.
- [ ] **Шифры:** для TLS 1.2 используются только аутентифицированные шифры AEAD (AES-GCM, ChaCha20-Poly1305). Шифры CBC, 3DES и RC4 полностью исключены.
- [ ] **Выбор шифра клиентом:** директива `ssl_prefer_server_ciphers off;` активна, обеспечивая энергоэффективность мобильных клиентов.
- [ ] **Эллиптические кривые:** настроена поддержка современных и постквантовых кривых (`ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;`).
- [ ] **Кэширование сессий:** настроена зона `ssl_session_cache shared:SSL:SIZE;` с расчетом объема под пиковый RPS.
- [ ] **Сессионные тикеты:** либо явно отключены (`ssl_session_tickets off;`) для гарантии PFS, либо настроена автоматическая синхронизация и ротация файлов `ssl_session_ticket_key` по кластеру.
- [ ] **OCSP Stapling:** включен на уровне блока `http` (`ssl_stapling on; ssl_stapling_verify on;`) вместе с надежным локальным `resolver` и параметром `ipv6=off`.
- [ ] **Задержка TTFB:** размер буфера `ssl_buffer_size` снижен до `4k` (или `8k`) на веб-ресурсах и API.
- [ ] **Kernel TLS:** включен `ssl_conf_command Options +KTLS;` при наличии ядра Linux 5.10+ и директивы `sendfile on;`.
- [ ] **Default Server:** первый сервер в конфигурации перехватывает трафик без SNI и выполняет `ssl_reject_handshake on;`.
- [ ] **Информационная безопасность:** директива `server_tokens off;` скрывает точную версию Nginx.
- [ ] **Права на файловую систему:** приватные ключи имеют маску `0600`, сертификаты `0644`, директории `0750` (`root:www-data`).

### Процедура безопасного обновления глобальной конфигурации

1. Внести изменения в тестовую ветку репозитория конфигурации.
2. Проверить синтаксис на целевом хосте:
   ```bash
   sudo nginx -t
   ```
3. Проверить отсутствие конфликта директив и переопределений в виртуальных хостах:
   ```bash
   sudo nginx -T | grep -n "ssl_ciphers"
   ```
4. Выполнить перезагрузку без простоя:
   ```bash
   sudo systemctl reload nginx
   ```
5. Проконтролировать журнал событий на предмет предупреждений и ошибок:
   ```bash
   sudo journalctl -u nginx --since "2 minutes ago" --no-pager
   ```
6. Выполнить проверку тестового запроса с внешнего клиента или curl:
   ```bash
   curl -Iv --tlsv1.3 https://127.0.0.1 -H "Host: example.com"
   ```

### План аварийного отката (Rollback Procedure)

При возникновении массовых сбоев рукопожатия у клиентов после обновления параметров:
```bash
# 1. Восстановление резервной копии конфигурационного файла
sudo cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf

# 2. Валидация восстановленной конфигурации
sudo nginx -t

# 3. Перезагрузка рабочих процессов
sudo systemctl reload nginx

# 4. Проверка восстановления доступности сервиса
openssl s_client -connect 127.0.0.1:443 -servername example.com < /dev/null
```

---

## Дополнительная информация

### Связанные документы базы знаний

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектурные принципы, жизненный цикл TLS-рукопожатия, ALPN, SNI, управление сертификатами.
*   **[Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)** — настройка блоков `server`, привязка сертификатов, dual-stack ECDSA+RSA, ECH и 0-RTT.
*   **[Диагностика TLS/SSL в Nginx и совместимость клиентов](./nginx_tls_troubleshooting_and_compatibility.md)** — расширенный траблшутинг, отладка рукопожатий и матрица совместимости браузеров/клиентов.
*   **[Настройка Mutual TLS (mTLS) в Nginx](./nginx_mtls_configuration.md)** — взаимная аутентификация клиентов по сертификатам, валидация CRL и списков отзыва.
*   **[Оптимизация производительности Nginx](../../Performance/nginx_performance_tuning.md)** — тонкий тюнинг рабочих процессов, пулов соединений, сетевых буферов и системных вызовов ядра Linux.
*   **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)** — фундаментальная криптографическая теория протокола TLS, алгоритмы шифрования и структуры сообщений.
*   **[PKI — инфраструктура открытых ключей](../../../../Security/Concepts/pki_overview.md)** — принципы работы центров сертификации, форматы X.509, цепочки доверия и протокол OCSP.
