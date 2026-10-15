# Взаимная аутентификация клиентов (mTLS) в Angie

**Актуально для:** Angie 1.12.x

## Определения

**Взаимная аутентификация TLS (Mutual TLS, mTLS)** — криптографический протокол двусторонней проверки подлинности на транспортном (L4) и прикладном (L7) уровнях. В отличие от стандартного TLS (где только клиент проверяет подлинность сервера по его сертификату), при mTLS сервер также запрашивает, валидирует и аутентифицирует X.509-сертификат клиента. Это гарантирует аутентичность взаимодействующих сторон и обеспечивает нулевое доверие (Zero Trust) для межсервисного обмена (Machine-to-Machine, M2M), API-шлюзов и административных контуров.

**Angie** — современный высокопроизводительный веб-сервер (форк Nginx), поддерживающий расширенные возможности для TLS/mTLS: поддержку динамических переменных в путях к спискам отзыва (`ssl_crl`), кэширование сертификатов в памяти (`ssl_certificate_cache`), нативный модуль автоматизации сертификатов `acme` для контекстов HTTP и Stream (L4), а также мониторинг SSL-метрик в реальном времени через встроенный REST API (`ngx_http_api_module`).

**Частный центр сертификации (Private CA / Internal PKI)** — внутренняя инфраструктура открытых ключей, выпускающая и удостоверяющая сертификаты для хостов и клиентов внутри защищенного периметра. Публичные центры сертификации (такие как Let's Encrypt) не выдают сертификаты с расширением проверки подлинности клиента, поэтому для mTLS развертывается собственный CA (на базе OpenSSL, Easy-RSA, HashiCorp Vault или Step-CA).

**Цепочка доверия (Chain of Trust)** — последовательность криптографических сертификатов, начинающаяся от конечного клиентского сертификата (Leaf), проходящая через один или несколько промежуточных центров сертификации (Intermediate CA) и заканчивающаяся корневым доверенным центром (Root CA).

**Список отозванных сертификатов (CRL, Certificate Revocation List)** — подписанный центром сертификации список серийных номеров аннулированных сертификатов с датой отзыва и причиной компрометации. Проверяется сервером для немедленной блокировки доступа скомпрометированных клиентов.

**Протокол онлайн-проверки статуса сертификата (OCSP, Online Certificate Status Protocol)** — сетевой протокол (RFC 6960), позволяющий серверу в реальном времени опрашивать OCSP-респондер центра сертификации о статусе валидности конкретного клиентского сертификата без скачивания объемных файлов CRL.

**Расширенное использование ключа (EKU, Extended Key Usage)** — поле расширения стандарта X.509 v3, определяющее допустимые сценарии применения ключа. Для клиентского сертификата обязателен OID `1.3.6.1.5.5.7.3.2` (`id-kp-clientAuth`).

---

## Базовые концепции и архитектура

### Архитектура mTLS в Angie

Angie функционирует на базе асинхронной событийно-ориентированной архитектуры с разделением на мастер-процесс (`master process`) и рабочие процессы (`worker processes`). Криптографические операции рукопожатия TLS выполняются непосредственно в контексте рабочих процессов, эффективно распределяя вычислительную нагрузку по ядрам CPU и NUMA-узлам.

```
[ Клиент (M2M / Агент / Браузер) ]
              │
              │  1. TCP Handshake / UDP Datagram (QUIC)
              ▼
[ Master Process ] ─── Читает конфигурацию, запускает воркеры
              │
[ Worker Process (Angie) ]
              │  2. ClientHello (SNI, supported ciphers, TLS 1.3)
              │  3. ServerHello + Certificate + CertificateRequest
              │  4. Client Certificate + CertificateVerify + Finished
              │
              ├─► Валидация подписи цепочки по ssl_client_certificate
              ├─► Проверка глубины иерархии (ssl_verify_depth)
              ├─► Проверка срока действия (notBefore / notAfter)
              ├─► Проверка статуса отзыва (ssl_crl или ssl_ocsp)
              │
              ├─── [Успех: ssl_client_verify = SUCCESS]
              │          │
              │          ▼
              │     Проксирование на Upstream / L4 Stream Proxy
              │     (передача метаданных через HTTP-заголовки)
              │
              └─── [Ошибка: ssl_client_verify = FAILED / NONE]
                         │
                         ▼
                    HTTP 400 (Bad Request: The SSL certificate error)
                    или обработка в кастомном error_page 495/496
```

**Жизненный цикл mTLS-соединения:**
1. **Инициализация:** Клиент устанавливает TCP-соединение на порт сервера с директивой `listen ... ssl` (или UDP для `listen ... quic`).
2. **Запрос сертификата (`CertificateRequest`):** При активной директиве `ssl_verify_client on` (или `optional`) Angie в процессе TLS-рукопожатия направляет клиенту сообщение `CertificateRequest`, содержащее список доверенных Distinguished Names (DN) центров сертификации, сконфигурированных в `ssl_client_certificate`. В протоколе TLS 1.3 данный блок полностью зашифрован, исключая утечку структуры CA в пассивном трафике.
3. **Ответ клиента:** Клиент отправляет свой сертификат и доказательство владения закрытым ключом (`CertificateVerify`).
4. **Криптографическая валидация:** Angie проверяет:
   - Математическую валидность цифровой подписи клиентского сертификата открытым ключом CA;
   - Глубину вложенности промежуточных звеньев (`ssl_verify_depth`);
   - Временной диапазон действия (`Not Before` и `Not After`);
   - Наличие сертификата в локальном списке отзыва (`ssl_crl`) или через онлайн-запрос (`ssl_ocsp`).
5. **Авторизация и маршрутизация:** После завершения хэндшейка статус проверки сохраняется в переменной `$ssl_client_verify`. При успехе запрос маршрутизируется в `location` или L4-стрим; метаданные субъекта передаются на бэкенд через заголовки или переменные.

### Ключевые директивы конфигурации

| Директива | Контекст | Назначение | Особенности и поведение в Angie |
|:----------|:---------|:-----------|:--------------------------------|
| `ssl_client_certificate` | `http`, `server` | Путь к PEM-файлу со списком доверенных CA для валидации клиентов. | Имена CA из этого файла передаются клиенту в запросе `CertificateRequest`. |
| `ssl_verify_client` | `http`, `server`, `stream` | Режим верификации: `on`, `off`, `optional`, `optional_no_ca`. | Базовый переключатель политики обязательности клиентского сертификата. |
| `ssl_verify_depth` | `http`, `server`, `stream` | Предельная глубина валидации цепочки сертификатов (по умолчанию `1`). | Для инфраструктур с Intermediate CA требует установки значения `>= 2`. |
| `ssl_crl` | `http`, `server`, `stream` | Путь к файлу списка отозванных сертификатов (CRL). | **Поддерживает переменные** (Angie), что позволяет обновлять списки на лету без `reload`. |
| `ssl_certificate_cache` | `http`, `stream` | Кэширование сертификатов и CRL в оперативной памяти рабочих процессов. | Ускоряет валидацию при использовании переменных в `ssl_crl` и `ssl_certificate`. |
| `ssl_trusted_certificate` | `http`, `server`, `stream` | Путь к доверенным сертификатам CA для проверки ответов OCSP. | Обязателен при включении `ssl_ocsp`, если корневой CA не указан в клиенте. |
| `ssl_ocsp` | `http`, `server` | Включение проверки статуса клиентского сертификата через OCSP (`on`, `off`, `leaf`). | Режим `leaf` проверяет только конечный сертификат клиента. |
| `ssl_ocsp_cache` | `http`, `server` | Разделяемая память для кэширования OCSP-ответов (`shared:NAME:SIZE`). | Снижает задержки и нагрузку на внутренний OCSP-респондер. |

### Режимы проверки клиентских сертификатов

| Режим | Поведение сервера | Типовой сценарий применения |
|:------|:------------------|:----------------------------|
| `off` | Клиентский сертификат не запрашивается и не проверяется. | Публичные веб-сайты и открытые API. |
| `on` | Сертификат строго обязателен. Если клиент не предоставил сертификат или проверка провалена, рукопожатие прерывается (HTTP 400 / 495 / 496). | Защищенные межсервисные каналы, закрытые админки, критичные API. |
| `optional` | Сертификат запрашивается. Если клиент его передал — выполняется валидация. Если не передал — соединение устанавливается со статусом `$ssl_client_verify = NONE`. | Плавная миграция клиентов, комбинированная аутентификация (mTLS + Token). |
| `optional_no_ca` | Сертификат запрашивается и принимается без проверки доверия по CA. Статус `$ssl_client_verify` принимает значение `SUCCESS`. | Не рекомендуется в продакшене; переносит валидацию целиком на бэкенд. |

### Переменные клиентского сертификата

При успешном или опциональном рукопожатии Angie заполняет встроенные переменные, доступные в логах, директивах `map`, `rewrite` и `proxy_set_header`:

| Переменная | Формат / Значение | Назначение |
|:-----------|:------------------|:-----------|
| `$ssl_client_verify` | `SUCCESS`, `FAILED:<reason>`, `NONE` | Итоговый статус проверки подлинности. |
| `$ssl_client_s_dn` | Строка Distinguished Name субъекта (например, `/CN=payment-service/O=Company`) | Полный идентификатор клиента для аудита и авторизации. |
| `$ssl_client_s_dn_cn` | Common Name (CN) из Subject DN | Имя сервиса, логин оператора или FQDN клиента. |
| `$ssl_client_i_dn` | Distinguished Name издателя (CA) | Идентификатор центра сертификации, подписавшего клиентский ключ. |
| `$ssl_client_serial` | Шестнадцатеричная строка серийного номера | Точный аудит и сопоставление с базой выданных сертификатов. |
| `$ssl_client_fingerprint_sha256` | SHA-256 дайджест сертификата в hex | Безопасная привязка сессий и белый список конкретных отпечатков. |
| `$ssl_client_v_remain` | Целое число дней | Срок действия сертификата (дни до экспирации); используется для алертинга. |
| `$ssl_client_v_start` | Дата в формате ASN.1/строка | Момент начала действия сертификата (`notBefore`). |
| `$ssl_client_v_end` | Дата в формате ASN.1/строка | Момент окончания действия сертификата (`notAfter`). |
| `$ssl_client_raw_cert` | Сертификат в кодировке PEM (с URL-safe экранированием) | Передача полного тела сертификата в бэкенд для глубокого разбора. |

### Специфика и преимущества Angie в реализации mTLS

1. **Динамический `ssl_crl` с поддержкой переменных:** В классическом Nginx директива `ssl_crl` статична: при обновлении файла CRL на диске требуется вызывать `nginx -s reload`, что при частых блокировках создает лишнюю нагрузку на процессное дерево. В Angie путь к CRL может вычисляться динамически (например, `ssl_crl /etc/angie/ssl/$ssl_server_name/crl.pem;`), а изменения в файле подхватываются без перезагрузки процессов.
2. **Пул кэширования `ssl_certificate_cache`:** Для исключения постоянных дисковых операций ввода-вывода при динамических путях Angie кэширует разобранные структуры X.509 и CRL в оперативной памяти рабочих процессов с контролем времени жизни (`inactive`) и объема (`max`).
3. **mTLS в модуле Stream с нативным ACME:** Angie позволяет защищать TCP/UDP-потоки (СУБД, брокеры сообщений) взаимным TLS, при этом серверный сертификат может автоматически выпускаться и ротироваться через встроенный клиент `acme`, работающий с локальным Step-CA или HashiCorp Vault.
4. **Эксплуатационный мониторинг SSL-хэндшейков:** Через модуль `ngx_http_api_module` Angie в реальном времени собирает и отдает в JSON/Prometheus детальные счетчики по зонам статуса (`/status/http/server_zones/<zone>/ssl`): количество успешных рукопожатий (`handshaked`), повторно использованных сессий (`reuses`), таймаутов (`timedout`) и сбоев верификации (`failed`).

---

## Практические сценарии

### Сценарий 1: Развертывание локального PKI на Easy-RSA и базовая настройка mTLS

Классический сценарий изолированного защищенного контура для взаимодействия микросервисов. Создается двухуровневый центр сертификации (Root CA и Intermediate CA), выпускаются сертификаты сервера и клиента с правильными расширениями EKU.

#### 1.1 Развертывание PKI на выделенном сервере/директории

```bash
# Установка Easy-RSA в системе Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y easy-rsa openssl

# Создание изолированного каталога CA
mkdir -p ~/pki-ca && cd ~/pki-ca
make-cadir .
./easyrsa init-pki

# Инициализация Root CA (алгоритм ECDSA P-384)
./easyrsa --use-algo=ec --curve=secp384r1 build-ca nopass
# → CA creation complete and you may now import and sign cert requests.
# → Your new CA certificate is: ~/pki-ca/pki/ca.crt

# Выпуск сертификата веб-сервера Angie (serverAuth)
./easyrsa --use-algo=ec --curve=secp384r1 build-server-full angie-server.internal nopass
# → Database updated, Certificate created at: ~/pki-ca/pki/issued/angie-server.internal.crt

# Выпуск клиентского сертификата для сервиса платежей (clientAuth)
./easyrsa --use-algo=ec --curve=secp384r1 build-client-full payment-worker nopass
# → Database updated, Certificate created at: ~/pki-ca/pki/issued/payment-worker.crt

# Первичная генерация списка отзыва (CRL)
./easyrsa gen-crl
# → An updated CRL has been created.
# → CRL file: ~/pki-ca/pki/crl.pem
```

#### 1.2 Размещение файлов на сервере Angie

```bash
# Создание защищенных каталогов на хосте Angie
sudo mkdir -p /etc/angie/ssl/{certs,keys,ca}
sudo chmod 700 /etc/angie/ssl/keys

# Копирование сертификата сервера и ключа
sudo cp ~/pki-ca/pki/issued/angie-server.internal.crt /etc/angie/ssl/certs/server.crt
sudo cp ~/pki-ca/pki/private/angie-server.internal.key /etc/angie/ssl/keys/server.key

# Копирование корневого сертификата доверия и CRL
sudo cp ~/pki-ca/pki/ca.crt /etc/angie/ssl/ca/ca.crt
sudo cp ~/pki-ca/pki/crl.pem /etc/angie/ssl/ca/crl.pem

# Установка безопасных прав доступа
sudo chown -R root:angie /etc/angie/ssl
sudo chmod 640 /etc/angie/ssl/keys/server.key
sudo chmod 644 /etc/angie/ssl/certs/server.crt /etc/angie/ssl/ca/ca.crt /etc/angie/ssl/ca/crl.pem
```

#### 1.3 Конфигурация виртуального хоста Angie

```nginx
# /etc/angie/http.d/mtls_service.conf
server {
    listen 443 ssl;
    http2 on;
    server_name api.internal.example.com;

    # Сертификат и закрытый ключ сервера
    ssl_certificate     /etc/angie/ssl/certs/server.crt;
    ssl_certificate_key /etc/angie/ssl/keys/server.key;

    # Протоколы и шифры: приоритет TLS 1.3
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;

    # Настройка взаимной аутентификации (mTLS)
    ssl_client_certificate /etc/angie/ssl/ca/ca.crt;
    ssl_crl                /etc/angie/ssl/ca/crl.pem;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    # Сессионный кэш для снижения накладных расходов на хэндшейки
    ssl_session_cache   shared:SSL_MTLS:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Метрики L7 в API
    status_zone mtls_api_zone;

    location / {
        # Передача идентифицирующих заголовков в защищаемый бэкенд
        proxy_set_header X-Client-Verify   $ssl_client_verify;
        proxy_set_header X-Client-DN       $ssl_client_s_dn;
        proxy_set_header X-Client-CN       $ssl_client_s_dn_cn;
        proxy_set_header X-Client-Serial   $ssl_client_serial;
        proxy_set_header X-Client-SHA256   $ssl_client_fingerprint_sha256;

        proxy_pass http://127.0.0.1:8080;
    }

    # Логирование попыток доступа с детализацией сертификата
    access_log /var/log/angie/mtls_access.log combined;
    error_log  /var/log/angie/mtls_error.log warn;
}
```

---

### Сценарий 2: Динамическое обновление CRL без перезагрузки (zero-downtime revocation)

В высоконагруженных системах постоянный перезапуск Angie через `angie -s reload` для применения нового CRL нежелателен. Использование переменной в директиве `ssl_crl` и буфера `ssl_certificate_cache` позволяет Angie считывать актуальный файл CRL с диска в момент проверки, гарантируя немедленный отзыв доступа.

#### 2.1 Конфигурация Angie с динамическим CRL и кэшем

```nginx
# /etc/angie/http.d/dynamic_crl.conf
http {
    # Кэширование сертификатов и списков отзыва в оперативной памяти
    # max=1000 — до 1000 объектов, inactive=10m — инвалидация при неактивности
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        listen 443 ssl;
        server_name secure-gw.internal;

        ssl_certificate     /etc/angie/ssl/certs/server.crt;
        ssl_certificate_key /etc/angie/ssl/keys/server.key;

        ssl_client_certificate /etc/angie/ssl/ca/ca.crt;

        # Использование переменной активирует динамическое разрешение пути к CRL
        set $mtls_crl_path "/etc/angie/ssl/ca/crl.pem";
        ssl_crl $mtls_crl_path;

        ssl_verify_client on;
        ssl_verify_depth  2;

        location /api/ {
            proxy_pass http://backend_pool;
        }
    }
}
```

#### 2.2 Автоматизированный скрипт синхронизации CRL (systemd timer)

Скрипт загружает свежий CRL из хранилища CA, валидирует его синтаксис утилитой `openssl crl` и атомарно заменяет целевой файл через команду `mv`:

```bash
#!/usr/bin/env bash
# /usr/local/bin/sync-angie-crl.sh
set -euo pipefail

CRL_SOURCE_URL="http://ca.internal.local/crl/latest.crl"
TARGET_CRL="/etc/angie/ssl/ca/crl.pem"
TMP_CRL="/etc/angie/ssl/ca/crl.pem.tmp"

# Скачивание списка отзыва
curl -sSf -o "${TMP_CRL}" "${CRL_SOURCE_URL}"

# Проверка валидности формата PEM/CRL
if openssl crl -in "${TMP_CRL}" -noout 2>/dev/null; then
    chmod 644 "${TMP_CRL}"
    chown root:angie "${TMP_CRL}"
    # Атомарная замена файла
    mv -f "${TMP_CRL}" "${TARGET_CRL}"
    logger -t angie-crl "CRL successfully rotated without server reload."
else
    logger -t angie-crl -p user.err "Downloaded CRL is invalid or corrupted! Retaining existing CRL."
    rm -f "${TMP_CRL}"
    exit 1
fi
```

Юнит службы systemd:
```ini
# /etc/systemd/system/angie-crl-sync.service
[Unit]
Description=Sync and Validate Angie CRL
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/sync-angie-crl.sh
User=root
```

Таймер регулярного запуска:
```ini
# /etc/systemd/system/angie-crl-sync.timer
[Unit]
Description=Run Angie CRL Sync every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now angie-crl-sync.timer
```

---

### Сценарий 3: mTLS в модуле Stream (L4) с внутренней автоматизацией ACME

Защита прямого TCP-трафика к базе данных (например, PostgreSQL на порту 5432) через модуль Stream. Серверный сертификат Angie выпускается автоматически через внутренний ACME-сервер (Step-CA или Vault ACME directory), а клиенты проходят строгую аутентификацию по клиентским сертификатам.

```nginx
# /etc/angie/stream.d/postgres_mtls.conf
stream {
    resolver 192.168.1.1 192.168.1.2 valid=300s ipv6=off;

    # Клиент ACME для взаимодействия с корпоративным центром сертификации
    acme_client internal_pki {
        directory   https://step-ca.internal.local:9000/acme/acme/directory;
        challenge   http;
        key_type    ecdsa;
        key_bits    384;
        renew       15d;
        contact     mailto:sre-team@internal.local;
    }

    upstream postgres_backend {
        server 10.10.20.15:5432 max_fails=3 fail_timeout=10s;
        server 10.10.20.16:5432 backup;
    }

    server {
        listen 5432 ssl;

        # Использование автоматически ротируемых ACME-сертификатов
        ssl_certificate     $acme_cert_internal_pki;
        ssl_certificate_key $acme_cert_key_internal_pki;

        # Настройки проверки клиентских сертификатов на уровне L4
        ssl_client_certificate /etc/angie/ssl/ca/db_clients_ca.crt;
        ssl_crl                /etc/angie/ssl/ca/db_clients_crl.pem;
        ssl_verify_client      on;
        ssl_verify_depth       2;

        # Сессионный протокол
        ssl_protocols TLSv1.3;
        ssl_session_cache shared:PG_SSL:10m;
        ssl_session_timeout 4h;

        proxy_pass postgres_backend;
        proxy_timeout 1h;
        proxy_connect_timeout 5s;
    }
}
```

---

### Сценарий 4: Гранулярный контроль доступа и авторизация клиентов по DN/CN через map

Часто простой проверки подписи CA недостаточно: необходимо разграничить права сервисов. С помощью директивы `map` организуется таблица управления доступом на основе поля Common Name (`$ssl_client_s_dn_cn`) или отпечатка сертификата.

```nginx
# /etc/angie/http.d/rbac_mtls.conf
# Сопоставление CN клиента с ролью доступа
map $ssl_client_s_dn_cn $client_role {
    default                  "guest";
    "service-billing-worker" "admin";
    "service-order-processor" "writer";
    "service-reporting-bi"   "reader";
    "sre-debug-agent"        "admin";
}

# Матрица прав доступа к защищенным методам
map "$client_role:$request_method" $access_granted {
    "admin:GET"     1;
    "admin:POST"    1;
    "admin:PUT"     1;
    "admin:DELETE"  1;
    "writer:GET"    1;
    "writer:POST"   1;
    "writer:PUT"    1;
    "reader:GET"    1;
    default         0;
}

server {
    listen 443 ssl;
    server_name api-rbac.internal;

    ssl_certificate     /etc/angie/ssl/certs/server.crt;
    ssl_certificate_key /etc/angie/ssl/keys/server.key;

    ssl_client_certificate /etc/angie/ssl/ca/ca.crt;
    ssl_verify_client      on;

    location /v1/transactions/ {
        # Если статус проверки mTLS не SUCCESS — отклонить
        if ($ssl_client_verify != "SUCCESS") {
            return 403 '{"error": "Forbidden", "reason": "Client certificate invalid"}';
        }

        # Если у роли клиента нет прав на метод — вернуть 403
        if ($access_granted = 0) {
            return 403 '{"error": "Forbidden", "reason": "Insufficient role privileges"}';
        }

        proxy_set_header X-Role-Identified $client_role;
        proxy_pass http://backend_transactions;
    }
}
```

---

### Сценарий 5: Онлайн-проверка статуса клиентских сертификатов через OCSP

Для мгновенного отзыва без задержек синхронизации CRL настраивается прямая проверка через OCSP-респондер центра сертификации.

```nginx
# /etc/angie/http.d/mtls_ocsp.conf
server {
    listen 443 ssl;
    server_name portal.internal;

    ssl_certificate     /etc/angie/ssl/certs/server.crt;
    ssl_certificate_key /etc/angie/ssl/keys/server.key;

    # Корневой и промежуточные CA для проверки клиентов
    ssl_client_certificate  /etc/angie/ssl/ca/ca_bundle.crt;
    ssl_trusted_certificate /etc/angie/ssl/ca/ca_bundle.crt;
    ssl_verify_client       on;

    # Включение OCSP-проверки клиентских сертификатов
    ssl_ocsp on;
    ssl_ocsp_cache shared:CLIENT_OCSP_CACHE:20m;

    # Локальный DNS-резолвер для поиска OCSP-сервера
    resolver 192.168.1.10 192.168.1.11 valid=60s;
    resolver_timeout 3s;

    location / {
        proxy_pass http://internal_portal;
    }
}
```

---

### Сценарий 6: Защита административных и мониторинговых интерфейсов (API и Prometheus)

Изоляция служебных интерфейсов Angie (`/status/` и выгрузка конфигураций) только для авторизованных рабочих станций администраторов и Prometheus-коллектора.

```nginx
# /etc/angie/http.d/admin_interfaces.conf
server {
    listen 8443 ssl;
    server_name mgmt-node.internal;

    ssl_certificate     /etc/angie/ssl/certs/server.crt;
    ssl_certificate_key /etc/angie/ssl/keys/server.key;

    # Отдельный CA, выпускающий ключи только для персонала эксплуатации и систем мониторинга
    ssl_client_certificate /etc/angie/ssl/ca/admin_ca.crt;
    ssl_verify_client      on;
    ssl_verify_depth       1;

    # Ограничение по IP в дополнение к сертификату (Defense in Depth)
    allow 192.168.10.0/24;
    allow 127.0.0.1;
    deny all;

    # Angie REST API
    location /status/ {
        api /status/;
        api_config_files off;
    }

    # Метрики для Prometheus в формате OpenMetrics
    location /metrics {
        prometheus all;
    }
}
```

---

### Сценарий 7: Высокопроизводительный mTLS с Kernel TLS (kTLS) и TLS 1.3

При обслуживании сотен тысяч соединений накладные расходы на шифрование в пользовательском пространстве создают значительную нагрузку на CPU. Перенос шифрования в ядро Linux (kTLS) в связке с TLS 1.3 снимает эту проблему.

```nginx
# /etc/angie/http.d/highperf_mtls.conf
http {
    # Включение offload шифрования в ядро (требует ядра Linux 5.10+ и OpenSSL 3.0+)
    ssl_conf_command Options +KTLS;

    server {
        listen 443 ssl fastopen=256;
        server_name ingress-fast.internal;

        ssl_certificate     /etc/angie/ssl/certs/server.crt;
        ssl_certificate_key /etc/angie/ssl/keys/server.key;

        ssl_client_certificate /etc/angie/ssl/ca/ca.crt;
        ssl_verify_client      on;

        # TLS 1.3 единственный протокол для максимальной скорости хэндшейка
        ssl_protocols TLSv1.3;
        ssl_ciphers   TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;

        # Буферизация и сессии
        ssl_session_cache   shared:HIGHPERF_SSL:50m;
        ssl_session_timeout 2h;
        ssl_session_tickets off;

        location / {
            proxy_pass http://backend_stream;
            proxy_buffering on;
        }
    }
}
```

---

### Сценарий 8: Архитектура разделения трафика: mTLS и локальные Health Checks

При установке директивы `ssl_verify_client on;` локальные проверки жизнеспособности (от балансировщиков HAProxy, Keepalived или агентов мониторинга) завершаются ошибкой, поскольку эти агенты обычно не передают сертификат клиента. Решением является разделение портов: продуктивный внешний порт защищен mTLS, а локальный порт `127.0.0.1` открыт только для Health Check.

```nginx
# /etc/angie/http.d/split_ports.conf
# 1. Внешний порт с обязательным клиентским сертификатом
server {
    listen 443 ssl;
    server_name service.internal;

    ssl_certificate     /etc/angie/ssl/certs/server.crt;
    ssl_certificate_key /etc/angie/ssl/keys/server.key;

    ssl_client_certificate /etc/angie/ssl/ca/ca.crt;
    ssl_verify_client      on;

    location / {
        proxy_pass http://app_cluster;
    }
}

# 2. Локальный порт только для Liveness / Readiness проверок без mTLS
server {
    listen 127.0.0.1:8081;
    server_name localhost;

    access_log off;

    location = /healthz {
        # Быстрая проверка состояния процесса и бэкенда
        return 200 "OK\n";
    }

    location = /livez {
        return 200 "HEALTHY\n";
    }
}
```

---

## Операции и команды

### Управление процессом Angie

```bash
# Проверка синтаксиса файлов конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка конфигурации с детальным дампом всех подключенных блоков и путей к сертификатам
sudo angie -T | grep -E "ssl_client|ssl_crl|ssl_verify"
# → ssl_client_certificate /etc/angie/ssl/ca/ca.crt;
# → ssl_crl /etc/angie/ssl/ca/crl.pem;
# → ssl_verify_client on;

# Бесшовная перезагрузка конфигурации master-процессом (Zero Downtime)
sudo angie -s reload
# → отправлен сигнал SIGHUP; старые воркеры корректно дообслуживают соединения

# Ротация лог-файлов
sudo angie -s reopen
```

### Управление PKI и сертификатами через Easy-RSA и OpenSSL

```bash
# Просмотр детальных параметров клиентского сертификата (Subject, Issuer, Сроки, EKU)
openssl x509 -in client.crt -text -noout | grep -E "Subject:|Issuer:|Not After|TLS Web Client"
# → Subject: C=RU, O=Enterprise, CN=payment-worker
# → Issuer: C=RU, O=Enterprise, CN=Internal Root CA
# → Not After : Dec 12 12:00:00 2026 GMT
# → TLS Web Client Authentication

# Верификация соответствия открытого ключа в сертификате и закрытого ключа
[ "$(openssl x509 -noout -modulus -in client.crt | openssl sha256)" = "$(openssl ec -noout -modulus -in client.key 2>/dev/null || openssl rsa -noout -modulus -in client.key | openssl sha256)" ] && echo "Key matches Certificate"
# → Key matches Certificate

# Полная валидация цепочки доверия от клиента до Root CA через OpenSSL
openssl verify -CAfile /etc/angie/ssl/ca/ca.crt /etc/angie/ssl/certs/client.crt
# → /etc/angie/ssl/certs/client.crt: OK

# Проверка срока действия сертификата в секундах до экспирации
openssl x509 -in client.crt -checkend 86400 -noout
# → Certificate will not expire within 86400 seconds (1 days)
```

### Проверка и отладка mTLS-соединений (curl и openssl s_client)

```bash
# Тестирование успешного mTLS-подключения через curl
curl -v --cacert /etc/angie/ssl/ca/ca.crt \
     --cert /etc/angie/ssl/certs/client.crt \
     --key /etc/angie/ssl/keys/client.key \
     https://api.internal.example.com/
# → < HTTP/1.1 200 OK
# → < X-Client-Verify: SUCCESS
# → < X-Client-CN: payment-worker

# Тестирование отказа при отсутствии клиентского сертификата
curl -s -o /dev/null -w "%{http_code}\n" --cacert /etc/angie/ssl/ca/ca.crt https://api.internal.example.com/
# → 400

# Детальная отладка TLS-рукопожатия через OpenSSL s_client
openssl s_client -connect api.internal.example.com:443 \
                 -servername api.internal.example.com \
                 -CAfile /etc/angie/ssl/ca/ca.crt \
                 -cert /etc/angie/ssl/certs/client.crt \
                 -key /etc/angie/ssl/keys/client.key \
                 -brief
# → CONNECTION ESTABLISHED
# → Protocol version: TLSv1.3
# → Ciphersuite: TLS_AES_256_GCM_SHA384
# → Peer certificate: CN = api.internal.example.com
# → Verification: OK

# Просмотр списка CA, запрошенных сервером в CertificateRequest
openssl s_client -connect api.internal.example.com:443 \
                 -servername api.internal.example.com \
                 -CAfile /etc/angie/ssl/ca/ca.crt 2>&1 | grep -A 5 "Acceptable client certificate CA names"
# → Acceptable client certificate CA names
# → /CN=Internal Root CA/O=Enterprise
```

### Управление списками отзыва (CRL)

```bash
# Отзыв скомпрометированного клиентского сертификата в Easy-RSA
cd ~/pki-ca
./easyrsa revoke payment-worker
# → Revoking Certificate 04A1B2C3D4...
# → Database updated.

# Генерация обновленного CRL-файла
./easyrsa gen-crl
# → An updated CRL has been created: ~/pki-ca/pki/crl.pem

# Просмотр серийных номеров отозванных сертификатов в файле CRL
openssl crl -in /etc/angie/ssl/ca/crl.pem -text -noout | grep -A 2 "Serial Number:"
# → Serial Number: 04A1B2C3D4
# → Revocation Date: Oct 14 10:20:00 2026 GMT

# Проверка клиентского сертификата против актуального CRL
openssl verify -crl_check -CAfile /etc/angie/ssl/ca/ca.crt -CRLfile /etc/angie/ssl/ca/crl.pem client.crt
# → error 23 at 0 depth lookup: certificate revoked
```

### Мониторинг SSL/mTLS метрик через Angie API

```bash
# Получение счетчиков SSL-хэндшейков по виртуальному хосту
curl -s http://127.0.0.1:8443/status/http/server_zones/mtls_api_zone/ssl | jq .
# → {
# →   "handshaked": 15420,
# →   "reuses": 12890,
# →   "timedout": 2,
# →   "failed": 14
# → }

# Сбор метрик сбоев хэндшейка в Prometheus
curl -s http://127.0.0.1:8443/metrics | grep -E "angie_http_server_ssl"
# → angie_http_server_ssl_handshakes_total{server_zone="mtls_api_zone"} 15420
# → angie_http_server_ssl_reuses_total{server_zone="mtls_api_zone"} 12890
# → angie_http_server_ssl_failed_total{server_zone="mtls_api_zone"} 14
```

---

## Диагностика и устранение неполадок

### Типичные ошибки и коды статуса mTLS

| Симптом / Сообщение в логе | Причина | Способ локализации и исправление |
|:---------------------------|:--------|:---------------------------------|
| **HTTP 400** / `No required SSL certificate was sent` (в логе: `client sent no required SSL certificate`) | Клиент не передал сертификат, либо сертификат клиента был отфильтрован клиентом из-за несовпадения CA. | Проверить передачу флагов `--cert` и `--key` на клиенте. Убедиться, что `ssl_client_certificate` на сервере содержит CA клиента. Настроить `error_page 496` для кастомного JSON-ответа. |
| **HTTP 400** / `The SSL certificate error` (в логе: `client SSL certificate verify error: (20:unable to get local issuer certificate)`) | Неполная цепочка доверия: сервер не может построить путь от Leaf-сертификата клиента до Root CA. | Добавить промежуточный Intermediate CA в файл `ssl_client_certificate`. Проверить глубину: `ssl_verify_depth 2;` или более. |
| `client SSL certificate verify error: (23:certificate revoked)` | Сертификат клиента включен в список отозванных (`ssl_crl`). | Клиент заблокирован регламентно. Проверить серийный номер: `openssl crl -in crl.pem -text` и `$ssl_client_serial` в логах. |
| `client SSL certificate verify error: (9:certificate is not yet valid)` | Системные часы клиента или сервера рассинхронизированы (время отстает от `Not Before`). | Проверить статус службы времени: `timedatectl status` и настроить синхронизацию NTP/Chrony на всех узлах. |
| `client SSL certificate verify error: (10:certificate has expired)` | Истек срок действия клиентского сертификата (`Not After`). | Перевыпустить клиентский сертификат. Настроить мониторинг метрики `$ssl_client_v_remain`. |
| `client SSL certificate verify error: (11:CRL is not yet valid)` | Файл CRL имеет дату выпуска в будущем относительно текущего системного времени сервера. | Исправить системное время на CA и хосте Angie. Проверить даты: `openssl crl -in crl.pem -noout -lastupdate -nextupdate`. |
| `peer closed connection in SSL handshake` / `alert unknown CA (48)` | Клиент отклонил серверный сертификат, либо сервер разорвал хэндшейк из-за неподдерживаемого CA. | Проверить доверенный корневой сертификат на стороне клиента и наличие актуального Root/Intermediate CA в конфигурации. |

### Пошаговый алгоритм локализации сбоев

```
Сбой mTLS-соединения
         │
         ├──► 1. Проверить код ответа клиента (400, 495, 496, 497 или TLS Alert)
         │
         ├──► 2. Изучить error.log Angie с уровнем warn/info:
         │        tail -n 50 /var/log/angie/mtls_error.log | grep -i ssl
         │
         ├──► 3. Запустить ручной тест с детальным выводом:
         │        openssl s_client -connect host:443 -cert client.crt -key client.key -CAfile ca.crt
         │
         ├──► 4. Проверить статус переменной $ssl_client_verify в access.log:
         │        - NONE    ─► Клиент не отправляет сертификат
         │        - FAILED  ─► Ошибка в цепочке CA, экспирация или отзыв в CRL
         │        - SUCCESS ─► mTLS прошел, проблема на уровне приложения/L7
         │
         └──► 5. Проверить соответствие EKU:
                  openssl x509 -in client.crt -text | grep "TLS Web Client Authentication"
```

### Анализ логов Angie и системного окружения

Для детального расследования инцидентов mTLS рекомендуется включить специализированный формат журнала доступа в `/etc/angie/angie.conf`:

```nginx
log_format mtls_audit '$remote_addr - [$time_local] "$request" '
                      'status=$status bytes=$body_bytes_sent '
                      'ssl_ver=$ssl_protocol ssl_cipher=$ssl_cipher '
                      'client_verify="$ssl_client_verify" '
                      'client_cn="$ssl_client_s_dn_cn" '
                      'client_serial="$ssl_client_serial" '
                      'days_left="$ssl_client_v_remain"';

access_log /var/log/angie/mtls_audit.log mtls_audit;
```

Команды оперативного анализа журнала:
```bash
# Выявление всех клиентов, чьи сертификаты отклонены
grep 'client_verify="FAILED' /var/log/angie/mtls_audit.log | tail -n 20

# Поиск сертификатов, срок действия которых завершится в ближайшие 7 дней
awk -F'days_left="' '{print $2}' /var/log/angie/mtls_audit.log | awk '$1 < 7 && $1 != "" {print $0}'

# Отслеживание клиентов, не передавших сертификат (NONE)
grep 'client_verify="NONE"' /var/log/angie/mtls_audit.log | head -n 10
```

---

## Лучшие практики

### Безопасность

1. **Исключительно Private CA для клиентских сертификатов:** Никогда не используйте публичные доверенные хранилища (типа Mozilla Root Store или системный `/etc/ssl/certs/ca-certificates.crt`) в директиве `ssl_client_certificate`. В противном случае любой субъект в мире, получивший валидный публичный сертификат от любого доверенного CA, сможет пройти mTLS-аутентификацию на сервере.
2. **Обязательное разделение Root и Intermediate CA:** Корневой ключ Root CA должен храниться offline (на защищенном съемном носителе или в изолированном HSM/Vault). Все рабочие сертификаты серверов и клиентов выпускаются промежуточным Intermediate CA.
3. **Строгая валидация EKU (Extended Key Usage):** При генерации клиентских сертификатов удостоверяйтесь в наличии флага `clientAuth` (`1.3.6.1.5.5.7.3.2`). Сертификаты с одним лишь `serverAuth` должны отклоняться.
4. **Безопасные права файловой системы:**
   ```bash
   chmod 700 /etc/angie/ssl/keys
   chmod 600 /etc/angie/ssl/keys/*.key
   chmod 644 /etc/angie/ssl/certs/*.crt /etc/angie/ssl/ca/*.crt /etc/angie/ssl/ca/*.pem
   chown -R root:angie /etc/angie/ssl
   ```
5. **Приоритет TLS 1.3:** Протокол TLS 1.3 шифрует процедуру обмена сертификатами (включая `CertificateRequest`), скрывая имена внутренних центров сертификации от сетевых анализаторов и предотвращая профилирование инфраструктуры.

### Жизненный цикл и автоматизация SRE

1. **Короткоживущие клиентские сертификаты:** Ограничивайте срок действия клиентских сертификатов (TTL 30–90 дней). Автоматизируйте перевыпуск и доставку через локальные утилиты или агенты конфигурации.
2. **Алертинг по сроку действия:** Настройте мониторинг переменной `$ssl_client_v_remain`. Если до истечения действия остается менее 14 дней, генерируйте предупреждение в мониторинге для предотвращения внезапных отказов сервисов.
3. **Автоматическая дистрибуция CRL:** Распространяйте обновленные списки CRL через cron или systemd-таймеры каждые 15–30 минут, проверяя корректность файла перед атомарной заменой (`mv`).

### Производительность и оптимизация ресурсов

1. **Активация `ssl_certificate_cache`:** При использовании переменных в путях к сертификатам или спискам отзыва всегда настраивайте директиву `ssl_certificate_cache max=... inactive=...;`. Это исключает непрерывные системные вызовы `stat()` и `open()` на каждый входящий запрос.
2. **Сессионный кэш TLS:** Обязательно настраивайте разделяемый кэш `ssl_session_cache shared:SSL:10m;` с тайм-аутом `1d;` и отключенными тикетами `ssl_session_tickets off;`. Это обеспечивает быстрое возобновление сессий (Session Resumption) без повторения ресурсоемких асимметричных операций.
3. **Kernel TLS (kTLS):** Для высоконагруженных прокси-узлов задействуйте разгрузку шифрования в ядро Linux (`ssl_conf_command Options +KTLS;`), снижая потребление CPU и число переключений контекста.

### Эксплуатационная надежность и регламент отката

1. **Регламент валидации перед применением:** Любое изменение конфигурации должно сопровождаться проверкой:
   ```bash
   sudo angie -t && sudo angie -s reload
   ```
2. **Процедура оперативного отката:**
   При возникновении проблем с доступом клиентов после изменения конфигурации:
   ```bash
   # Восстановление предыдущей рабочей версии
   sudo cp /etc/angie/http.d/mtls_service.conf.bak /etc/angie/http.d/mtls_service.conf
   sudo angie -t && sudo angie -s reload
   ```
3. **Временная аварийная деградация:** Если отказ вызван повреждением CRL или недоступностью OCSP, переведите директиву проверки в режим `ssl_verify_client optional;` на время восстановления центра сертификации, чтобы не прерывать обслуживание критичного трафика.

---

## Дополнительная информация

### Ограничения и архитектурные особенности

1. **Статичность `ssl_client_certificate`:** В отличие от `ssl_crl` и `ssl_certificate`, путь в директиве `ssl_client_certificate` не поддерживает переменные. Список доверенных центров сертификации загружается мастер-процессом при чтении конфигурации. Для обновления доверенного набора CA требуется выполнение `angie -s reload`.
2. **Публичный ACME и Client Auth:** Общедоступные центры сертификации Let's Encrypt и ZeroSSL выпускают сертификаты строго для `serverAuth` (проверка доменного имени). Получить сертификат клиента через публичный ACME невозможно; для интеграции модуля `acme` с клиентскими сертификатами необходимо разворачивать собственный ACME-совместимый CA (HashiCorp Vault, Smallstep Step-CA).
3. **Размер буфера заголовков:** При передаче сырого сертификата клиента на бэкенд через `proxy_set_header X-Client-Cert $ssl_client_raw_cert;` размер заголовков запроса существенно возрастает. При необходимости увеличьте директивы `large_client_header_buffers` и `proxy_buffer_size`.

### См. также

- [Настройка TLS в Angie (базовая конфигурация)](./angie_tls_setup.md)
- [Модуль автоматизации сертификатов ACME в Angie](./angie_acme_module.md)
- [Мониторинг состояния и параметров Angie через HTTP API](./angie_monitoring/angie_monitoring_api.md)
- [Системные переменные Angie](./angie_variables.md)
- [Обзор веб-сервера Angie](./angie_overview.md)
- [Настройка взаимной аутентификации (mTLS) в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)
- [Обзор протоколов TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)
- [Диагностика SSL/TLS сертификатов с помощью OpenSSL](../../Security/Tools/ssl_certificate_diagnostics.md)
- [Архитектура и управление внутренним PKI в HashiCorp Vault](../../Vault/concepts.md)
