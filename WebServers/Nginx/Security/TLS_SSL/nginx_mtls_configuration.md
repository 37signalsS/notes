# Настройка Mutual TLS (mTLS) в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x – 1.30.x (Mainline), OpenSSL 3.0+ / 3.5+, Linux Kernel 5.15+ / 6.x

## Определения

**Mutual TLS (mTLS)** — механизм взаимной криптографической аутентификации на транспортном уровне (L4/L7). В отличие от стандартного одностороннего TLS, где только клиент проверяет подлинность сервера, mTLS требует от клиента предъявить валидный сертификат X.509, подписанный доверенным центром сертификации (CA). Это обеспечивает строгую аутентификацию и целостность при межсервисном взаимодействии (Machine-to-Machine, M2M), администрировании узлов и защите API без передачи статических паролей или токенов в открытом виде.

**Chain of Trust (Цепочка доверия)** — иерархический путь криптографической валидации от конечного клиентского сертификата через промежуточные центры сертификации (Intermediate CA) до доверенного корневого центра (Root CA). Nginx проверяет подпись каждого звена и соответствие глубины иерархии значению директивы `ssl_verify_depth`.

**Private CA (Внутренний центр сертификации)** — выделенная инфраструктура PKI (на базе OpenSSL, HashiCorp Vault on-prem, CFSSL или Smallstep step-ca), управляемая системными администраторами для выпуска сертификатов узлов и клиентов внутри защищенного контура. Публичные коммерческие удостоверяющие центры и Let's Encrypt не выпускают клиентские сертификаты с назначением Client Authentication.

**CRL (Certificate Revocation List)** — подписанный центром сертификации список серийных номеров отозванных сертификатов с датой отзыва и причиной. В Nginx список отзыва подключается директивой `ssl_crl` и считывается в оперативную память при старте или перезагрузке конфигурации (`nginx -s reload`).

**OCSP (Online Certificate Status Protocol)** — сетевой протокол (RFC 6960) проверки статуса валидности конкретного сертификата в реальном времени через запрос к OCSP-ответчику (OCSP responder). Позволяет мгновенно аннулировать доступ скомпрометированного клиента без перегрузки полных списков CRL.

**EKU (Extended Key Usage) и Key Usage (KU)** — расширения стандарта X.509 v3, определяющие допустимые сферы криптографического применения ключа. Для mTLS клиентский сертификат обязан содержать EKU `clientAuth` (OID `1.3.6.1.5.5.7.3.2`) и KU `digitalSignature`.

**Distinguished Name (DN) и SAN (Subject Alternative Name)** — структурированные поля идентификации субъекта в сертификате. DN содержит атрибуты `CN` (Common Name), `O` (Organization), `OU` (Organizational Unit), `C` (Country). SAN содержит альтернативные имена: DNS-имена, IP-адреса, URI (например, SPIFFE ID в zero-trust сетях) или email-адреса.

**CertificateVerify (RFC 8446)** — критическое сообщение рукопожатия TLS 1.3, в котором клиент передает серверу цифровую подпись под всеми предшествующими сообщениями сессии, вычисленную с помощью своего закрытого ключа. Подтверждает владение закрытым ключом (Proof of Possession), соответствующим переданному открытому сертификату.

**Graceful Reload (`SIGHUP` / `nginx -s reload`)** — перезагрузка конфигурации Nginx без остановки сервера и без разрыва активных клиентских TCP-соединений. Мастер-процесс перечитывает файлы конфигурации, сертификаты и CRL, запускает новые рабочие процессы (workers), после чего корректно гасит старые процессы по завершении обработки текущих запросов.

---

## Архитектура и базовые концепции

### Жизненный цикл mTLS-соединения (TLS 1.3)

В протоколе TLS 1.3 рукопожатие с взаимной аутентификацией оптимизировано до 1-RTT, а чувствительные метаданные клиента и список доверенных CA защищены шифрованием:

```text
Клиент                                                    Nginx (Worker)
  │                                                             │
  │ 1. ClientHello (Шифры, группы KeyShare, SNI)               │
  ├────────────────────────────────────────────────────────────►│
  │                                                             │ 2. Выбор параметров,
  │                                                             │    генерация ключей сессии
  │ 3. ServerHello + EncryptedExtensions                        │
  │    + Certificate (Серверный Leaf + Intermediate CA)         │
  │    + CertificateRequest (Список доверенных CA DNs)         │
  │    + CertificateVerify (Подпись сервера)                    │
  │    + Finished                                               │
  │◄────────────────────────────────────────────────────────────┤
  │ 4. Клиент валидирует сертификат сервера                     │
  │                                                             │
  │ 5. Certificate (Клиентский Leaf + Intermediate CA)          │
  │    + CertificateVerify (Подпись транскрипта ключом клиента) │
  │    + Finished                                               │
  ├────────────────────────────────────────────────────────────►│
  │                                                             │ 6. Валидация Nginx:
  │                                                             │    - Проверка подписи цепочки
  │                                                             │    - Глубина (ssl_verify_depth)
  │                                                             │    - Срок действия NotBefore/After
  │                                                             │    - EKU clientAuth
  │                                                             │    - Статус отзыва (CRL / OCSP)
  │                                                             │ 7. Формирование переменных
  │                                                             │    ($ssl_client_verify и др.)
  │ 8. Защищенный прикладной обмен (HTTP GET/POST или TCP L4)   │
  │◄═══════════════════════════════════════════════════════════►│
```

#### Ключевые этапы валидации в Nginx

1. **CertificateRequest:** При включенной директиве `ssl_verify_client on` (или `optional`) Nginx отправляет клиенту список отличительных имен (DN) доверенных центров сертификации, сформированный из файла `ssl_client_certificate`. В TLS 1.3 этот блок передается внутри зашифрованного контекста рукопожатия, исключая утечку структуры внутренней PKI пассивному наблюдателю.
2. **Proof of Possession:** Получив клиентский сертификат, Nginx проверяет подпись в сообщении `CertificateVerify`. Без валидного закрытого ключа злоумышленник не сможет завершить рукопожатие, даже если перехватит чужой открытый клиентский сертификат.
3. **Криптографическая верификация:** Библиотека OpenSSL в контексте воркера Nginx строит цепочку от клиентского сертификата до одного из доверенных CA. Если промежуточный CA не найден в `ssl_client_certificate`, либо нарушен лимит `ssl_verify_depth`, рукопожатие прерывается с фатальным TLS-алертом (`unknown CA` или `certificate verify failed`).
4. **Контроль отзыва:** Если настроена директива `ssl_crl`, OpenSSL сверяет серийный номер сертификата со списком отозванных. Если настроена директива `ssl_ocsp`, Nginx отправляет асинхронный запрос к OCSP responder (с сохранением ответа в `ssl_ocsp_cache`).
5. **Фиксация контекста:** По результатам проверки Nginx инициализирует набор встроенных переменных (`$ssl_client_verify`, `$ssl_client_s_dn`, `$ssl_client_serial` и др.), которые могут использоваться в директивах `map`, директивах логирования `log_format` и передаваться бэкендам через заголовки `proxy_set_header`.

---

### Архитектура процессов Nginx и обработка mTLS

Nginx обрабатывает mTLS в многопроцессной архитектуре «Master — Workers»:
- **Master Process:** Запускается от имени суперпользователя (`root`). Считывает конфигурационные файлы, открывает сетевые порты (`listen 443 ssl`), загружает с диска сертификаты, приватные ключи сервера и файл списков отзыва `ssl_crl` в память.
- **Worker Processes:** Выполняются от непривилегированного пользователя (обычно `nginx` или `www-data`). Непосредственно выполняют криптографические операции рукопожатия, проверку подписей сертификатов, кэширование TLS-сессий и маршрутизацию запросов.
- **Особенность статического CRL в стандартном Nginx:** Директива `ssl_crl` считывает файл с диска в оперативную память **только в момент запуска или reload**. Изменение файла `crl.pem` на диске не блокирует скомпрометированный сертификат автоматически до выполнения `nginx -s reload`. (В отличие от форка Angie, где директива `ssl_crl` поддерживает динамические переменные и автоматическое перечитывание через `ssl_certificate_cache`).
- **Kernel TLS (kTLS):** При сборке OpenSSL 3.0+ с поддержкой kTLS и загруженном модуле ядра Linux (`tls`), Nginx выполняет симметричное шифрование/дешифрование данных непосредственно в ядре, что снижает нагрузку на CPU и исключает копирование буферов user-space при отдаче статических файлов (`sendfile on`).

---

### Директивы конфигурации mTLS

Директивы модуля `ngx_http_ssl_module` (HTTP) и `ngx_stream_ssl_module` (L4 Stream):

| Директива | Контекст | Допустимые значения | Назначение и поведение |
| :--- | :--- | :--- | :--- |
| `ssl_client_certificate` | `http`, `server`, `stream` | Путь к PEM-файлу | Задает файл с доверенными сертификатами Root и Intermediate CA. Сертификаты из этого файла отправляются клиенту в списке допустимых центров в `CertificateRequest`. |
| `ssl_verify_client` | `http`, `server`, `stream` | `off`, `on`, `optional`, `optional_no_ca` | Режим проверки клиентского сертификата. См. детальное описание режимов ниже. |
| `ssl_verify_depth` | `http`, `server`, `stream` | Целое число (по умолч. `1`) | Максимальная глубина проверки цепочки сертификатов клиента. При использовании иерархии Root CA → Intermediate CA → Client необходимо установить значение не менее `2`. |
| `ssl_crl` | `http`, `server`, `stream` | Путь к PEM-файлу | Указывает файл со списком отозванных сертификатов (CRL). Клиенты с сертификатами из этого списка получают отказ в соединении. |
| `ssl_ocsp` | `http`, `server`, `stream` | `off`, `on`, `leaf` | Включает проверку статуса отзыва клиентского сертификата через протокол OCSP. Значение `leaf` проверяет только конечный клиентский сертификат; `on` проверяет всю цепочку. |
| `ssl_ocsp_cache` | `http`, `stream` | `off`, `shared:NAME:SIZE` | Создает разделяемую между воркерами зону памяти для кэширования OCSP-ответов, снижая нагрузку на OCSP responder центра сертификации. |
| `ssl_ocsp_responder` | `http`, `server`, `stream` | `http://URL` | Переопределяет URL OCSP-ответчика, игнорируя адрес, указанный в расширении AIA (Authority Information Access) клиентского сертификата. |
| `ssl_trusted_certificate` | `http`, `server`, `stream` | Путь к PEM-файлу | Содержит доверенные сертификаты CA для валидации ответов OCSP responder. В отличие от `ssl_client_certificate`, данный список **не отправляется** клиенту в `CertificateRequest`. |

#### Режимы директивы `ssl_verify_client`

1. `off` (по умолчанию) — клиентский сертификат не запрашивается.
2. `on` — клиент обязан предоставить сертификат; соединение разрывается с ошибкой `400 Bad Request (No required SSL certificate was sent)`, если сертификат отсутствует или не прошел валидацию по цепочке CA.
3. `optional` — клиентский сертификат запрашивается, но не является обязательным для завершения TLS-рукопожатия. Если клиент предоставил сертификат, он обязан пройти полную криптографическую валидацию по CA. Если клиент не предоставил сертификат, рукопожатие успешно завершается, а переменная `$ssl_client_verify` принимает значение `NONE`. Режим используется для выборочной защиты отдельных location или для бесконфликтного пропуска health checks.
4. `optional_no_ca` — клиентский сертификат запрашивается, но Nginx **не выполняет** его валидацию по доверенным CA. Рукопожатие завершается успешно даже с самоподписанным сертификатом клиента. Сертификат передается в бэкенд (через `$ssl_client_escaped_cert` или `$ssl_client_raw_cert`), где приложение или njs-скрипт выполняет собственную верификацию.

---

### Переменные mTLS и передача метаданных в апстрим

Модуль `ngx_http_ssl_module` предоставляет встроенные переменные для логирования, маршрутизации и проброса идентичности клиента в защищаемые сервисы:

| Переменная | Формат / Возможные значения | Описание и сценарии применения |
| :--- | :--- | :--- |
| `$ssl_client_verify` | `SUCCESS`, `FAILED:reason`, `NONE` | Результат проверки клиентского сертификата. Используется в проверках `if ($ssl_client_verify != SUCCESS)` и таблицах `map`. |
| `$ssl_client_s_dn` | Строка RFC 2253 (например, `CN=app-01,OU=DevOps,O=Company,C=RU`) | Полный Subject Distinguished Name сертификата клиента. Основной идентификатор для аудита. |
| `$ssl_client_s_dn_legacy` | Формат OpenSSL (например, `/C=RU/O=Company/OU=DevOps/CN=app-01`) | Устаревший формат Subject DN (через слеши) для обратной совместимости с legacy-приложениями. |
| `$ssl_client_i_dn` | Строка RFC 2253 | Полный Issuer Distinguished Name (DN центра сертификации, подписавшего клиентский сертификат). |
| `$ssl_client_serial` | Шестнадцатеричная строка (например, `1002A4B89C`) | Серийный номер сертификата клиента. Удобен для трекинга сессий и точечного отзыва. |
| `$ssl_client_fingerprint` | 40-символьный SHA-1 хеш (в hex) | Отпечаток (хеш) клиентского сертификата в формате SHA-1. |
| `$ssl_client_raw_cert` | PEM-строка с переносами строк | Полный текст клиентского сертификата в формате PEM. |
| `$ssl_client_escaped_cert` | URL-encoded PEM-строка | Клиентский сертификат в кодировке PEM, экранированный для безопасной передачи в HTTP-заголовках без риска header splitting. |
| `$ssl_client_v_start` | Время в формате ASN.1 (например, `260501000000Z`) | Дата начала действия клиентского сертификата (`Not Before`). |
| `$ssl_client_v_end` | Время в формате ASN.1 | Дата окончания срока действия клиентского сертификата (`Not After`). |
| `$ssl_client_v_remain` | Целое число (дни) | Количество дней до истечения срока действия клиентского сертификата. Критично для SRE-мониторинга и превентивного алерта. |

#### Извлечение Common Name (CN) в Nginx OSS vs Angie

> **Важное архитектурное различие:** В форке Angie переменная `$ssl_client_s_dn_cn` доступна из коробки. В официальном **Nginx OSS** переменная `$ssl_client_s_dn_cn` **отсутствует**. Попытка ее прямого использования в Nginx OSS приведет к ошибке конфигурации: `unknown "ssl_client_s_dn_cn" variable`.
>
> Для извлечения CN в чистом Nginx используется регулярное выражение в директиве `map` на уровне блока `http`:

```nginx
# Извлечение Common Name (CN) из строки Subject DN в Nginx OSS
map $ssl_client_s_dn $ssl_client_cn {
    default "";
    ~CN=(?<extracted_cn>[^,/]+) $extracted_cn;
}

# Извлечение Organization (O) из строки Subject DN
map $ssl_client_s_dn $ssl_client_org {
    default "";
    ~O=(?<extracted_o>[^,/]+) $extracted_o;
}
```

---

## Практические сценарии

### Сценарий 1: Развертывание локальной двухзвенной PKI (OpenSSL) для mTLS

В соответствии со стандартами информационной безопасности, корневой CA (Root CA) должен храниться изолированно (offline). Выпуск сертификатов узлов и клиентов производится исключительно через промежуточный CA (Intermediate CA).

```bash
# 1. Подготовка структуры каталогов
mkdir -p /etc/nginx/pki/{root,intermediate,clients}
cd /etc/nginx/pki
chmod 700 root intermediate clients

# 2. Генерация Offline Root CA (ECDSA P-384, срок 10 лет)
openssl ecparam -name secp384r1 -genkey -out root/root-ca.key
chmod 400 root/root-ca.key

openssl req -x509 -new -nodes -key root/root-ca.key -sha384 -days 3650 \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Internal Infrastructure/CN=Infrastructure Root CA" \
  -out root/root-ca.crt
# → root/root-ca.crt создан

# 3. Генерация Intermediate CA (ECDSA P-384, срок 5 лет)
openssl ecparam -name secp384r1 -genkey -out intermediate/intermediate-ca.key
chmod 400 intermediate/intermediate-ca.key

openssl req -new -key intermediate/intermediate-ca.key -sha384 \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Internal Infrastructure/OU=Security/CN=Internal mTLS Intermediate CA" \
  -out intermediate/intermediate-ca.csr

# Подпись Intermediate CA корневым сертификатом с расширениями CA:TRUE
cat << 'EOF' > intermediate/ca_ext.cnf
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, digitalSignature, cRLSign, keyCertSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
EOF

openssl x509 -req -in intermediate/intermediate-ca.csr \
  -CA root/root-ca.crt -CAkey root/root-ca.key -CAcreateserial \
  -out intermediate/intermediate-ca.crt -days 1825 -sha384 \
  -extfile intermediate/ca_ext.cnf
# → intermediate/intermediate-ca.crt: OK

# 4. Формирование бандла доверенных CA для Nginx
# Включает Intermediate CA и Root CA
cat intermediate/intermediate-ca.crt root/root-ca.crt > intermediate/ca-chain.crt
chmod 644 intermediate/ca-chain.crt

# 5. Выпуск клиентского сертификата (ECDSA P-384, срок 90 дней)
openssl ecparam -name secp384r1 -genkey -out clients/client-01.key
chmod 600 clients/client-01.key

openssl req -new -key clients/client-01.key -sha384 \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Internal Infrastructure/OU=Services/CN=payment-processor-01" \
  -out clients/client-01.csr

cat << 'EOF' > clients/client_ext.cnf
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
EOF

openssl x509 -req -in clients/client-01.csr \
  -CA intermediate/intermediate-ca.crt -CAkey intermediate/intermediate-ca.key -CAcreateserial \
  -out clients/client-01.crt -days 90 -sha384 \
  -extfile clients/client_ext.cnf
# → clients/client-01.crt: OK

# 6. Экспорт в формат PKCS#12 (.p12) для прикладных клиентов и curl
openssl pkcs12 -export \
  -in clients/client-01.crt -inkey clients/client-01.key \
  -certfile intermediate/ca-chain.crt \
  -out clients/client-01.p12 -passout pass:SecretClientPass123
chmod 600 clients/client-01.p12
```

---

### Сценарий 2: Базовый продуктивный HTTPS виртуальный хост с mTLS и защитой заголовков

Конфигурация реверс-прокси с mTLS-аутентификацией, передачей метаданных сертификата во внутренний сервис и обязательной санитаризацией заголовков от несанкционированной подделки (header spoofing):

```nginx
# /etc/nginx/conf.d/mtls_api.conf

# Извлечение Common Name из Subject DN
map $ssl_client_s_dn $ssl_client_cn {
    default "";
    ~CN=(?<extracted_cn>[^,/]+) $extracted_cn;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name api.internal.example.com;

    # Серверный сертификат (Leaf + Intermediate CA)
    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Протоколы и шифры
    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Конфигурация mTLS
    ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    # Список отзыва сертификатов
    ssl_crl                /etc/nginx/pki/crl.pem;

    # Параметры сессий
    ssl_session_cache shared:SSL_MTLS:20m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Безопасность
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;

    location / {
        proxy_pass http://backend_upstream;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Защита от spoofing: очистка потенциально поддельных клиентских заголовков
        proxy_set_header X-Client-Verified   "";
        proxy_set_header X-Client-DN         "";
        proxy_set_header X-Client-CN         "";
        proxy_set_header X-Client-Serial     "";
        proxy_set_header X-Client-Cert       "";

        # Передача доверенных метаданных mTLS из контекста веб-сервера
        proxy_set_header X-Client-Verified   $ssl_client_verify;
        proxy_set_header X-Client-DN         $ssl_client_s_dn;
        proxy_set_header X-Client-CN         $ssl_client_cn;
        proxy_set_header X-Client-Serial     $ssl_client_serial;
        proxy_set_header X-Client-Cert       $ssl_client_escaped_cert;
    }
}
```

---

### Сценарий 3: Выборочная аутентификация (Selective mTLS через `optional`)

Сценарий необходим, когда один и тот же виртуальный хост обслуживает публичную документацию, эндпоинты проверки жизнеспособности (`/healthz`) и защищенные API-методы управления:

```nginx
# /etc/nginx/conf.d/selective_mtls.conf

server {
    listen 443 ssl;
    http2 on;
    server_name gateway.example.com;

    ssl_certificate     /etc/nginx/ssl/gateway.crt;
    ssl_certificate_key /etc/nginx/ssl/gateway.key;

    # Режим optional: TLS-рукопожатие завершается для всех клиентов
    ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
    ssl_verify_client      optional;
    ssl_verify_depth       2;

    # 1. Публичный эндпоинт статуса (доступен без сертификата)
    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "healthy\n";
    }

    # 2. Публичные ресурсы
    location /public/ {
        proxy_pass http://public_service;
    }

    # 3. Защищенный приватный API: принудительная валидация сертификата
    location /api/v1/private/ {
        # Если клиент не предоставил валидный сертификат, отдаем 403 Forbidden
        if ($ssl_client_verify != SUCCESS) {
            return 403 '{"error":"Forbidden: valid client mTLS certificate required"}\n';
        }

        proxy_pass http://internal_api;
        proxy_set_header Host $host;
        proxy_set_header X-Client-DN $ssl_client_s_dn;
    }
}
```

---

### Сценарий 4: Ролевая авторизация (RBAC) на основе атрибутов сертификата

Одной лишь проверки подписи CA часто недостаточно: необходимо гарантировать, что конкретный клиент имеет право обращаться к определенному эндпоинту. Авторизация настраивается через директиву `map`:

```nginx
# /etc/nginx/conf.d/mtls_rbac.conf

# Извлечение CN клиента
map $ssl_client_s_dn $client_cn {
    default "";
    ~CN=(?<extracted_cn>[^,/]+) $extracted_cn;
}

# Таблица сопоставления CN клиента и его роли в системе
map $client_cn $client_role {
    default                  "unauthorized";
    "payment-processor-01"   "finance";
    "order-service-node-01"  "orders";
    "sre-admin-console"      "superuser";
}

# Матрица доступа к административной зоне
map $client_role $has_admin_access {
    default       0;
    "superuser"   1;
}

server {
    listen 443 ssl;
    server_name core.example.com;

    ssl_certificate         /etc/nginx/ssl/core.crt;
    ssl_certificate_key     /etc/nginx/ssl/core.key;
    ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    # Общий API для авторизованных сервисов
    location /api/ {
        if ($client_role = "unauthorized") {
            return 403 "Access Denied: Unrecognized client identity\n";
        }
        proxy_pass http://core_backend;
        proxy_set_header X-Client-Role $client_role;
    }

    # Административный API: доступен только роли superuser
    location /admin/ {
        if ($has_admin_access = 0) {
            return 403 "Access Denied: Insufficient privileges for admin API\n";
        }
        proxy_pass http://admin_backend;
        proxy_set_header X-Admin-Operator $client_cn;
    }
}
```

---

### Сценарий 5: Разрешение конфликта mTLS и локальных Health Checks

Балансировщики нагрузки (HAProxy, Keepalived), локальные агенты мониторинга (Consul, Zabbix) или скрипты systemd обычно не имеют клиентских сертификатов. При `ssl_verify_client on` любые их запросы на порт 443 завершаются ошибкой `400 Bad Request`.

**Архитектурное решение SRE:** Выделение изолированного локального слушателя (listener) без TLS/mTLS, привязанного строго к loopback-интерфейсу `127.0.0.1`:

```nginx
# /etc/nginx/conf.d/service_with_healthcheck.conf

# 1. Внутренний незащищенный порт только для локальных health checks
server {
    listen 127.0.0.1:8081;
    server_name localhost;

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "healthy\n";
    }

    location = /nginx_status {
        stub_status;
        access_log off;
        allow 127.0.0.1;
        deny all;
    }
}

# 2. Внешний продуктивный порт со строгим mTLS
server {
    listen 443 ssl;
    server_name service.example.com;

    ssl_certificate         /etc/nginx/ssl/service.crt;
    ssl_certificate_key     /etc/nginx/ssl/service.key;
    ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    location / {
        proxy_pass http://app_cluster;
    }
}
```

---

### Сценарий 6: mTLS в потоковом модуле Stream (L4) для TCP-сервисов

Защита прямого TCP-трафика баз данных (PostgreSQL, MySQL, Redis) или брокеров очередей без привязки к протоколу HTTP:

```nginx
# /etc/nginx/nginx.conf (секция stream)

stream {
    upstream postgresql_backend {
        server 10.0.10.15:5432 max_fails=3 fail_timeout=10s;
        server 10.0.10.16:5432 backup;
    }

    server {
        listen 15432 ssl;
        proxy_pass postgresql_backend;

        # TLS сервера
        ssl_certificate     /etc/nginx/ssl/db_proxy.crt;
        ssl_certificate_key /etc/nginx/ssl/db_proxy.key;
        ssl_protocols       TLSv1.3 TLSv1.2;

        # Клиентская аутентификация L4
        ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
        ssl_verify_client      on;
        ssl_verify_depth       2;
        ssl_crl                /etc/nginx/pki/crl.pem;

        # Таймауты сессии
        proxy_connect_timeout 5s;
        proxy_timeout         1h;
    }
}
```

---

### Сценарий 7: Автоматизация ротации CRL через systemd timer

Поскольку Nginx OSS загружает CRL в память исключительно при старте или перезагрузке, отзыв скомпрометированного клиентского сертификата требует доставки свежего CRL-файла и вызова `nginx -s reload`.

#### 1. Скрипт синхронизации CRL (`/usr/local/bin/update-nginx-crl.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

CRL_URL="http://ca.internal.example.com/crl/intermediate-ca.crl"
TEMP_CRL="/tmp/crl_download.pem"
TARGET_CRL="/etc/nginx/pki/crl.pem"
CA_CERT="/etc/nginx/pki/intermediate/intermediate-ca.crt"

# 1. Скачивание нового CRL
curl -fsSL --connect-timeout 10 --max-time 30 "$CRL_URL" -o "$TEMP_CRL"

# 2. Криптографическая валидация CRL перед установкой
# Проверка синтаксиса и подписи центром сертификации
if ! openssl crl -in "$TEMP_CRL" -noout > /dev/null 2>&1; then
    echo "ERROR: Загруженный файл не является валидным CRL" >&2
    rm -f "$TEMP_CRL"
    exit 1
fi

if ! openssl crl -in "$TEMP_CRL" -noout -CAfile "$CA_CERT" > /dev/null 2>&1; then
    echo "ERROR: Подпись CRL не совпадает с доверенным CA" >&2
    rm -f "$TEMP_CRL"
    exit 1
fi

# 3. Атомарное обновление файла
chmod 644 "$TEMP_CRL"
mv -f "$TEMP_CRL" "$TARGET_CRL"

# 4. Проверка конфигурации Nginx и graceful reload
if nginx -t > /dev/null 2>&1; then
    systemctl reload nginx
    echo "SUCCESS: CRL успешно обновлен, Nginx перезагружен ($(date -u))"
else
    echo "ERROR: Ошибка проверки синтаксиса Nginx, reload отменен" >&2
    exit 1
fi
```

#### 2. Конфигурация systemd unit и timer

`/etc/systemd/system/nginx-crl-update.service`:
```ini
[Unit]
Description=Update Nginx mTLS Certificate Revocation List (CRL)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/update-nginx-crl.sh
User=root
```

`/etc/systemd/system/nginx-crl-update.timer`:
```ini
[Unit]
Description=Run Nginx mTLS CRL update hourly

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
RandomizedDelaySec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация таймера
chmod +x /usr/local/bin/update-nginx-crl.sh
systemctl daemon-reload
systemctl enable --now nginx-crl-update.timer
systemctl list-timers nginx-crl-update.timer
# → NEXT                         LEFT        LAST PASSED UNIT                     ACTIVATES
# → Sat 2026-10-17 17:05:00 UTC  58min left  n/a         nginx-crl-update.timer   nginx-crl-update.service
```

---

### Сценарий 8: Онлайн-проверка отзыва клиентских сертификатов через OCSP

Для мгновенного отзыва доступа без ожидания плановой регенерации CRL используется протокол OCSP.

```nginx
# /etc/nginx/conf.d/mtls_ocsp.conf

http {
    # Общий кэш для OCSP-ответов по клиентским сертификатам
    ssl_ocsp_cache shared:CLIENT_OCSP_CACHE:20m;

    server {
        listen 443 ssl;
        server_name secure-api.example.com;

        ssl_certificate         /etc/nginx/ssl/server.crt;
        ssl_certificate_key     /etc/nginx/ssl/server.key;

        ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
        # Доверенные CA для проверки подписей ответов OCSP
        ssl_trusted_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
        ssl_verify_client      on;
        ssl_verify_depth       2;

        # Включение OCSP-проверки клиентского сертификата
        ssl_ocsp on;
        # Опционально: принудительный адрес OCSP responder (если отсутствует в сертификате)
        # ssl_ocsp_responder http://ocsp.internal.example.com:8888;

        # DNS-резолвер для сетевых запросов Nginx к OCSP responder
        resolver 10.0.0.2 10.0.0.3 valid=300s;
        resolver_timeout 3s;

        location / {
            proxy_pass http://backend;
        }
    }
}
```

---

### Сценарий 9: Современная криптография и Post-Quantum Cryptography (PQC) в TLS 1.3

OpenSSL 3.5 LTS+ поддерживает гибридные постквантовые алгоритмы обмена ключами (в соответствии с FIPS 203 / ML-KEM). Это обеспечивает защиту mTLS-трафика от атак класса «Store Now, Decrypt Later»:

```nginx
# Глобальная настройка в блоке http
http {
    ssl_protocols TLSv1.3 TLSv1.2;

    # Гибридная постквантовая группа X25519MLKEM768 совместно с классическими эллиптическими кривыми
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;

    # Отключение устаревших сессионных билетов при mTLS
    ssl_session_tickets off;
}
```

---

## Операции и команды

### Валидация и управление службой Nginx

```bash
# 1. Проверка синтаксиса конфигурации (обязательно перед reload)
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Вывод директив mTLS из текущей активной конфигурации
nginx -T 2>/dev/null | grep -E 'ssl_client|ssl_verify|ssl_crl|ssl_ocsp'
# → ssl_client_certificate /etc/nginx/pki/intermediate/ca-chain.crt;
# → ssl_verify_client on;
# → ssl_verify_depth 2;
# → ssl_crl /etc/nginx/pki/crl.pem;

# 3. Безопасное перечитывание конфигурации (graceful reload)
systemctl reload nginx
```

---

### Тестирование mTLS через curl

```bash
# 1. Успешный запрос с клиентским сертификатом (отдельные PEM-файлы)
curl -s -o /dev/null -w "%{http_code}\n" \
  --cert /etc/nginx/pki/clients/client-01.crt \
  --key /etc/nginx/pki/clients/client-01.key \
  --cacert /etc/nginx/pki/intermediate/ca-chain.crt \
  https://api.internal.example.com/api/v1/resource
# → 200

# 2. Запрос с использованием зашифрованного PKCS#12 контейнера (.p12)
curl -s -o /dev/null -w "%{http_code}\n" \
  --cert-type P12 \
  --cert /etc/nginx/pki/clients/client-01.p12:SecretClientPass123 \
  --cacert /etc/nginx/pki/intermediate/ca-chain.crt \
  https://api.internal.example.com/api/v1/resource
# → 200

# 3. Негативный тест: запрос без клиентского сертификата (ожидается 400 Bad Request)
curl -s -o /dev/null -w "%{http_code}\n" \
  --cacert /etc/nginx/pki/intermediate/ca-chain.crt \
  https://api.internal.example.com/api/v1/resource
# → 400

# 4. Негативный тест с подробным выводом TLS-рукопожатия
curl -v --cacert /etc/nginx/pki/intermediate/ca-chain.crt \
  https://api.internal.example.com/api/v1/resource 2>&1 | grep -E '< HTTP|SSL certificate error'
# → < HTTP/1.1 400 Bad Request
```

---

### Диагностика TLS-рукопожатия через `openssl s_client`

```bash
# 1. Полноценное тестирование рукопожатия с отображением цепочки
openssl s_client -connect api.internal.example.com:443 \
  -cert /etc/nginx/pki/clients/client-01.crt \
  -key /etc/nginx/pki/clients/client-01.key \
  -CAfile /etc/nginx/pki/intermediate/ca-chain.crt \
  -servername api.internal.example.com -tls1_3
# → Verification: OK
# → Acceptable client certificate CA names:
# → /C=RU/ST=Moscow/L=Moscow/O=Internal Infrastructure/OU=Security/CN=Internal mTLS Intermediate CA

# 2. Проверка, запрашивает ли сервер сертификат клиента (CertificateRequest)
echo | openssl s_client -connect api.internal.example.com:443 \
  -CAfile /etc/nginx/pki/intermediate/ca-chain.crt \
  -servername api.internal.example.com 2>&1 | grep -A 2 "Acceptable client certificate CA names"
# → Acceptable client certificate CA names
# → /C=RU/O=Internal Infrastructure/OU=Security/CN=Internal mTLS Intermediate CA
```

---

### Инспекция сертификатов, CRL и OCSP

```bash
# 1. Проверка срока действия клиентского сертификата
openssl x509 -in /etc/nginx/pki/clients/client-01.crt -noout -dates -subject -issuer
# → notBefore=Oct 17 00:00:00 2026 GMT
# → notAfter=Jan 15 00:00:00 2027 GMT
# → subject=C=RU, ST=Moscow, L=Moscow, O=Internal Infrastructure, OU=Services, CN=payment-processor-01
# → issuer=C=RU, ST=Moscow, L=Moscow, O=Internal Infrastructure, OU=Security, CN=Internal mTLS Intermediate CA

# 2. Проверка расширения EKU (наличие clientAuth)
openssl x509 -in /etc/nginx/pki/clients/client-01.crt -noout -ext extendedKeyUsage
# → X509v3 Extended Key Usage:
# →     TLS Web Client Authentication

# 3. Проверка соответствия открытого сертификата и приватного ключа
[ "$(openssl x509 -noout -pubkey -in client-01.crt | openssl sha256)" = \
  "$(openssl pkey -pubout -in client-01.key | openssl sha256)" ] && echo "Keys MATCH" || echo "MISMATCH"
# → Keys MATCH

# 4. Проверка клиентского сертификата против цепочки CA и CRL
openssl verify -crl_check \
  -CAfile /etc/nginx/pki/intermediate/ca-chain.crt \
  -CRLfile /etc/nginx/pki/crl.pem \
  /etc/nginx/pki/clients/client-01.crt
# → /etc/nginx/pki/clients/client-01.crt: OK

# 5. Просмотр отозванных серийных номеров в CRL
openssl crl -in /etc/nginx/pki/crl.pem -text -noout | grep -A 2 "Serial Number"
# → Serial Number: 1002A4B89C
# →     Revocation Date: Oct 17 12:00:00 2026 GMT

# 6. Запрос статуса сертификата у OCSP responder
openssl ocsp \
  -issuer /etc/nginx/pki/intermediate/intermediate-ca.crt \
  -cert /etc/nginx/pki/clients/client-01.crt \
  -url http://ocsp.internal.example.com:8888 \
  -CAfile /etc/nginx/pki/intermediate/ca-chain.crt
# → Response verify OK
# → /etc/nginx/pki/clients/client-01.crt: good
```

---

### SRE-мониторинг и аудит mTLS

#### 1. Расширенный формат логов аудита mTLS

Добавьте в блок `http` файла `/etc/nginx/nginx.conf`:

```nginx
log_format mtls_audit escape=json '{'
    '"time_local":"$time_local",'
    '"remote_addr":"$remote_addr",'
    '"request":"$request",'
    '"status":$status,'
    '"body_bytes_sent":$body_bytes_sent,'
    '"ssl_protocol":"$ssl_protocol",'
    '"ssl_cipher":"$ssl_cipher",'
    '"ssl_verify":"$ssl_client_verify",'
    '"client_serial":"$ssl_client_serial",'
    '"client_dn":"$ssl_client_s_dn",'
    '"client_v_remain":$ssl_client_v_remain'
'}';

access_log /var/log/nginx/mtls_access.log mtls_audit;
```

#### 2. Анализ логов на сбои аутентификации

```bash
# Просмотр 10 последних неудачных попыток mTLS
grep -v '"ssl_verify":"SUCCESS"' /var/log/nginx/mtls_access.log | tail -n 10

# Подсчет сбоев по типам ошибок OpenSSL
tail -n 1000 /var/log/nginx/error.log | grep "client SSL certificate verify error" | \
  awk -F': ' '{print $NF}' | sort | uniq -c | sort -nr
# → 42 (20:unable to get local issuer certificate)
# → 12 (23:certificate revoked)
# →  5 (10:certificate has expired)
```

#### 3. Мониторинг срока действия клиентских сертификатов (Prometheus Node Exporter)

Bash-скрипт `/usr/local/bin/check-client-certs-exporter.sh` для генерации метрик в формате Prometheus textfile collector:

```bash
#!/usr/bin/env bash
set -euo pipefail

TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"
OUTPUT_FILE="${TEXTFILE_DIR}/nginx_client_certs.prom.$$"
FINAL_FILE="${TEXTFILE_DIR}/nginx_client_certs.prom"
CERTS_DIR="/etc/nginx/pki/clients"

mkdir -p "$TEXTFILE_DIR"

cat << 'EOF' > "$OUTPUT_FILE"
# HELP nginx_client_certificate_expiry_days Days remaining until client certificate expires
# TYPE nginx_client_certificate_expiry_days gauge
EOF

for cert in "$CERTS_DIR"/*.crt; do
    [ -f "$cert" ] || continue
    cn=$(openssl x509 -in "$cert" -noout -subject | sed -n 's/.*CN = \([^,]*\).*/\1/p')
    end_date=$(openssl x509 -in "$cert" -noout -enddate | cut -d= -f2)
    end_epoch=$(date -d "$end_date" +%s)
    now_epoch=$(date +%s)
    days_remain=$(( (end_epoch - now_epoch) / 86400 ))
    echo "nginx_client_certificate_expiry_days{client_cn=\"${cn}\"} ${days_remain}" >> "$OUTPUT_FILE"
done

mv -f "$OUTPUT_FILE" "$FINAL_FILE"
```

---

## Устранение неполадок

### Сводная таблица ошибок mTLS

| Ошибка в логах Nginx / Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не отправил сертификат при `ssl_verify_client on`. Либо клиентское ПО не нашло подходящий сертификат под предложенный список CA. | `curl -v` без ключей `--cert` и `--key`. | Передать сертификат и ключ на клиенте. Проверить, что CA в `ssl_client_certificate` совпадает с эмитентом сертификата клиента. |
| `client SSL certificate verify error: (20:unable to get local issuer certificate)` | Nginx не может построить цепочку доверия: в `ssl_client_certificate` отсутствует промежуточный CA (Intermediate CA). | `openssl verify -CAfile ca-chain.crt client.crt` | Объединить Intermediate CA и Root CA в один файл: `cat intermediate.crt root.crt > ca-chain.crt` и указать его в `ssl_client_certificate`. |
| `client SSL certificate verify error: (21:unable to verify the first certificate)` | Сертификат клиента подписан неизвестным CA, либо передан неполный бандл цепочки. | `openssl x509 -in client.crt -noout -issuer` | Проверить значение `ssl_client_certificate` и сопоставить с `Issuer` клиентского сертификата. |
| `client SSL certificate verify error: (23:certificate revoked)` | Серийный номер сертификата клиента включен в список отозванных (`ssl_crl`), либо отозван через OCSP. | `openssl crl -in crl.pem -text -noout` | Легитимный отказ доступа. Для восстановления выпустить новый клиентский сертификат. |
| `client SSL certificate verify error: (10:certificate has expired)` | Истек срок действия клиентского сертификата (`Not After` в прошлом). | `openssl x509 -in client.crt -noout -dates` | Провести регламентную ротацию и перевыпустить клиентский сертификат. |
| `client SSL certificate verify error: (9:certificate is not yet valid)` | Сертификат еще не вступил в силу (`Not Before` в будущем), либо на сервере Nginx рассинхронизировано системное время. | `timedatectl status` | Синхронизировать часы узла через `chrony` или `systemd-timesyncd`. |
| `client SSL certificate verify error: (26:unsupported certificate purpose)` | Сертификат клиента не содержит расширения EKU `clientAuth` (например, выдан только как `serverAuth`). | `openssl x509 -in client.crt -noout -ext extendedKeyUsage` | Перевыпустить сертификат с расширением `extendedKeyUsage = clientAuth`. |
| `client SSL certificate verify error: (18:self signed certificate)` | Клиент предоставил самоподписанный сертификат при `ssl_verify_client on`. | `openssl x509 -in client.crt -noout -issuer -subject` | Подписать клиентский CSR доверенным Intermediate CA. |
| `certificate verify error: (27:certificate not trusted)` | Превышена допустимая глубина цепочки доверия. | Сравнить количество звеньев в цепочке со значением `ssl_verify_depth`. | Увеличить значение `ssl_verify_depth` (например, до `2` или `3`). |
| `OCSP responder query failure` / `no response` | Nginx не может связаться с OCSP responder по сети, либо резолвер вернул ошибку. | `curl -v http://ocsp.internal:8888` | Проверить директиву `resolver` в Nginx, сетевую доступность порта ответчика и корректность URL в AIA. |
| `alert handshake failure (40)` | Клиент и сервер не согласовали общую версию TLS или набор шифров; либо клиент прервал соединение после `CertificateRequest`. | `openssl s_client -connect ... -msg` | Согласовать версии протоколов (`ssl_protocols TLSv1.3 TLSv1.2`) и cipher suites. |

---

### Пошаговый алгоритм расследования инцидентов mTLS

```text
[ ИНЦИДЕНТ: Клиент получает ошибку при подключении ]
                         │
                         ▼
        [ Шаг 1: Проверка HTTP-кода ответа ]
         ├── 400 Bad Request ─────────► Клиент не передал сертификат, либо эмитент не в списке CA
         ├── 403 Forbidden ───────────► Nginx отверг сертификат по правилам map / RBAC в location
         └── TCP Reset / Alert 40 ────► Несовпадение TLS-версий / отказ на этапе Handshake
                         │
                         ▼
        [ Шаг 2: Анализ логов ошибки Nginx ]
         tail -n 50 /var/log/nginx/error.log | grep -i "client SSL"
                         │
                         ├─► Код 20/21: Ошибка цепочки CA ──► Проверить ssl_client_certificate
                         ├─► Код 23: Сертификат отозван ──► Проверить CRL / OCSP
                         ├─► Код 10: Сертификат просрочен ──► Ротация клиентского сертификата
                         └─► Код 26: Нет EKU clientAuth ────► Перевыпуск с расширением clientAuth
                         │
                         ▼
        [ Шаг 3: Локальное воспроизведение через CLI ]
         openssl s_client -connect host:443 -cert client.crt -key client.key -CAfile ca.crt
```

---

## Рекомендации и лучшие практики

### Чеклист безопасности и надежности mTLS

- [ ] **Протокол TLS 1.3:** Использовать TLS 1.3 как основной протокол. В TLS 1.3 блок `CertificateRequest` шифруется, защищая список доверенных внутренних CA от пассивного сетевого перехвата.
- [ ] **Изоляция Root CA:** Приватный ключ корневого CA (`root-ca.key`) никогда не размещается на продуктивных серверах Nginx. Он хранится на отчуждаемом носителе или в изолированном хранилище секретов.
- [ ] **Глубина цепочки (`ssl_verify_depth`):** При двухуровневой схеме (Root → Intermediate → Leaf) всегда явно устанавливать `ssl_verify_depth 2;`. По умолчанию значение равно `1`, что приведет к ошибкам при проверке сертификатов от промежуточных CA.
- [ ] **Расширение EKU `clientAuth`:** Выпускать клиентские сертификаты строго с расширением `extendedKeyUsage = clientAuth`. Назначение `serverAuth` в клиентских сертификатах является нарушением стандартов безопасности.
- [ ] **Контроль отзыва (Revocation):** Использовать автоматизированную доставку CRL по таймеру (systemd timer) либо OCSP-проверку в реальном времени. Внедрив mTLS без механизма отзыва, система остается уязвимой в случае утери клиентского ключа.
- [ ] **Защита от спуфинга заголовков:** Перед добавлением метаданных `$ssl_client_*` в `proxy_set_header`, всегда явно очищать входящие одноименные заголовки от клиента, чтобы исключить внедрение фиктивных идентификаторов.
- [ ] **Изоляция Health Checks:** Никогда не отключать mTLS глобально ради мониторинга. Использовать выделенный listener на `127.0.0.1:8081` или режим `ssl_verify_client optional` с точечной проверкой `$ssl_client_verify` в защищенных location.
- [ ] **Ограничение прав на файловой системе:**
  ```bash
  chmod 600 /etc/nginx/ssl/*.key /etc/nginx/pki/*/*.key
  chmod 644 /etc/nginx/ssl/*.crt /etc/nginx/pki/*/*.crt /etc/nginx/pki/*.pem
  chmod 750 /etc/nginx/pki
  chown -R root:root /etc/nginx/pki
  ```
- [ ] **Сессионные билеты (Session Tickets):** При mTLS рекомендуется отключать сессионные билеты (`ssl_session_tickets off;`), используя серверный кэш сессий `ssl_session_cache shared:SSL:20m;`. Это предотвращает возобновление сессий скомпрометированными клиентами без повторной проверки клиентского сертификата в CRL/OCSP.
- [ ] **Rate Limiting по клиентам:** Использовать серийный номер клиентского сертификата для индивидуального лимитирования запросов: `limit_req_zone $ssl_client_serial zone=client_limit:10m rate=50r/s;`.

---

### Производительность и оптимизация

1. **Эллиптическая криптография (ECDSA):** Использование ключей ECDSA (P-256 или P-384) вместо RSA-4096 сокращает размер сертификата в 3 раза и ускоряет фазу вычисления подписи при TLS Handshake в 4–6 раз при эквивалентной криптостойкости.
2. **Размер буфера TLS (`ssl_buffer_size 4k`):** По умолчанию размер буфера равен 16 КБ. Уменьшение до 4 КБ снижает показатель Time To First Byte (TTFB) при передаче небольших ответов в API-сервисах.
3. **Разделяемый кэш OCSP:** Директива `ssl_ocsp_cache shared:CLIENT_OCSP:20m;` на 20 МБ способна хранить более 100 000 кэшированных OCSP-ответов, предотвращая лавинообразные запросы к OCSP responder при высокой частоте новых рукопожатий.
4. **Kernel TLS (kTLS):** Для высоконагруженных прокси-серверов активируйте kTLS на уровне OpenSSL через `/etc/ssl/openssl.cnf` (`Options = +KTLS`) и ядро Linux (`modprobe tls`).

---

## Дополнительная информация

### Связанные документы базы знаний

- **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — общая архитектура подсистемы TLS, ALPN, HSTS и глобальные директивы.
- **[Защита Upstream TLS и mTLS к бэкендам](./nginx_upstream_tls_and_mtls.md)** — взаимная аутентификация и проверка сертификатов при проксировании Nginx к внутренним микросервисам.
- **[Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)** — настройка блоков `server`, dual-stack сертификаты и SNI.
- **[Устранение неполадок TLS и совместимость](./nginx_tls_troubleshooting_and_compatibility.md)** — диагностика проблем согласования шифров, протоколов и дампы рукопожатий.
- **[Защищенный репозиторий APT с mTLS](../../Scenarios/secure_apt_repository_guide.md)** — комплексный сценарий применения mTLS для дистрибуции системных пакетов.
- **[Клиентская аутентификация в Angie](../../Angie/angie_client_cert_auth.md)** — реализация mTLS в веб-сервере Angie с динамическим `ssl_crl` и встроенным `$ssl_client_s_dn_cn`.
- **[Инфраструктура открытых ключей (PKI)](../../../../Security/Concepts/pki_overview.md)** — архитектура центров сертификации, форматы X.509 и алгоритмы подписи.
- **[Двухуровневый CA на OpenSSL](../../../../Security/Tools/openssl_ca/two_tier/overview.md)** — развертывание производственной PKI с разделением Root и Intermediate CA.
- **[Диагностика SSL/TLS сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)** — утилиты анализа x509, проверка хэшей modulus и форматов PKCS.
- **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)** — теоретический анализ спецификаций TLS 1.3 (RFC 8446) и рукопожатия.
