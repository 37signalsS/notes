# Security Hardening для Jaeger

**Актуально для:** Jaeger v2.x

**Security Hardening для Jaeger** — это комплекс мер по защите инфраструктуры распределенной трассировки от несанкционированного доступа, утечек конфиденциальных данных, DoS-атак и компрометации смежных систем. В production-окружениях трейсы агрегируют детализированную информацию о внутренней топологии микросервисов, межсервисных вызовах, параметрах SQL-запросов и HTTP-заголовках. Отсутствие эшелонированной защиты превращает observability-платформу в вектор разведки для злоумышленника.

Начиная с архитектуры **Jaeger v2**, построенной на ядре OpenTelemetry Collector, безопасность организуется на базе стандартизированных компонентов OTel: взаимной аутентификации (mTLS), расширений авторизации (`bearertokenauth`), процессоров очистки данных (`transform` с OTTL), строгой изоляции процессов в Linux (systemd sandbox) и контейнерах Kubernetes (Pod Security Standards `restricted`), сетевой изоляции (NetworkPolicy default-deny), а также разграничения прав доступа к хранилищу (ClickHouse RBAC) и централизованного управления секретами через HashiCorp Vault.

Вся архитектура и практические примеры ориентированы на on-premise и bare-metal инфраструктуру без использования публичных облачных сервисов (cloud-agnostic / private infrastructure).

Смежные разделы:
* Развертывание и конфигурация оператора: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Настройка транспортных протоколов: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* Внутреннее устройство подсистем: **[Архитектура Jaeger v2](./jaeger_architecture.md)**
* Безопасность интерфейса и API: **[Jaeger Query API](./jaeger_query_api.md)**
* Отказоустойчивость: **[High Availability и DR](./jaeger_high_availability.md)**

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **mTLS (Mutual TLS)** | Двусторонняя криптографическая аутентификация, при которой клиент и сервер взаимно проверяют X.509-сертификаты, выданные доверенным удостоверяющим центром (CA) |
| **RBAC (Role-Based Access Control)** | Модель разграничения доступа на основе ролей, определяющая допустимые операции субъекта в кластере Kubernetes, операционной системе и СУБД |
| **NetworkPolicy** | Декларативная спецификация Kubernetes, управляющая входящим и исходящим трафиком подов на уровне L3/L4 через CNI-плагин (Calico, Cilium) |
| **Pod Security Standards (Restricted)** | Официальный стандарт безопасности Kubernetes, запрещающий привилегированные контейнеры, эскалацию прав, монтирование хостовых путей и требующий non-root пользователя |
| **OTTL (OpenTelemetry Transformation Language)** | Декларативный язык преобразования телеметрии, используемый в `transformprocessor` для модификации, маскирования и удаления чувствительных полей спанов |
| **bearertokenauth** | Расширение OpenTelemetry Collector / Jaeger v2, валидирующее Bearer-токены в заголовках `Authorization` входящих gRPC и HTTP OTLP-запросов |
| **Systemd Sandboxing** | Механизм изоляции сервиса в Linux через директивы systemd (`ProtectSystem`, `ProtectHome`, `PrivateTmp`, `CapabilityBoundingSet`, `NoNewPrivileges`) |
| **External Secrets Operator (ESO)** | Kubernetes-оператор, синхронизирующий секреты из внешних хранилищ (HashiCorp Vault) в нативные объекты `Secret` кластера |
| **Least Privilege (Принцип минимальных привилегий)** | Концепция безопасности, при которой каждому компоненту предоставляются строго минимальные права, необходимые для выполнения его задач |
| **Defense in Depth (Эшелонированная защита)** | Стратегия безопасности, использующая многоуровневые барьеры защиты (сеть, транспорт, приложение, данные, ядро ОС) |

---

## Базовые концепции

### Архитектура безопасности и модель угроз

Распределенная трассировка собирает телеметрию со всех уровней прикладного стека. Компрометация коллектора или хранилища спанов предоставляет атакующему полный граф вызовов инфраструктуры.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ВЕКТОРЫ АТАК НА JAEGER                            │
└─────────────────────────────────────────────────────────────────────────────┘
  [Неавторизованный клиент] ──(1. Инъекция фиктивных спанов / DoS)──┐
                                                                    ▼
  [Скомпрометированный под] ──(2. Перехват спанов в транзите)─▶ [Jaeger Collector]
                                                                    │
  [Атака на Query API / UI] ──(3. Несанкционированное чтение)───────┼─(4. Утечка PII)
                                                                    ▼
  [Внутренний нарушитель]   ──(5. Эксплуатация прав СУБД)──────▶ [ClickHouse]
```

| Угроза | Вектор атаки | Последствия | Механизм защиты |
| :--- | :--- | :--- | :--- |
| **Утечка архитектуры и PII** | Неавторизованный доступ к Jaeger Query API или перехват OTLP-трафика | Раскрытие структуры микросервисов, внутренних IP, токенов сессий, персональных данных клиентов | Защита Query через обратный прокси с OIDC/mTLS; маскирование PII через OTTL `transform`; шифрование трафика через mTLS |
| **Инъекция спанов (Spoofing)** | Отправка фиктивных трейсов злоумышленником на открытый порт 4317/4318 | Искажение метрик задержек, ложные срабатывания алертов, маскировка вредоносной активности | Аутентификация OTLP через `bearertokenauth` или mTLS с проверкой CN/SAN сертификата |
| **Отказ в обслуживании (DoS)** | Массовая отправка высококардинальных трейсов или объемных payload | Исчерпание памяти (OOM) коллектора, деградация дисковой подсистемы хранилища | Процессор `memory_limiter`, лимиты `batch`, сетевые ограничения пропускной способности, rate limiting |
| **Компрометация хранилища** | Прямой доступ к ClickHouse/Elasticsearch минуя Jaeger Query | Чтение сырых спанов, удаление исторических данных (TRUNCATE/DROP) | Раздельные учетные записи `jaeger_writer` и `jaeger_reader` с запретом DDL; шифрование блочных устройств (LUKS) |
| **Побег из контейнера (Container Escape)** | Эксплуатация уязвимости в парсерах телеметрии коллектора | Доступ к хостовой операционной системе, перехват контроля над нодой | Linux Capabilities dropping (`drop: [ALL]`), `readOnlyRootFilesystem: true`, seccomp-профиль `RuntimeDefault` |

### Модель углубленной защиты (Defense in Depth)

Харденинг Jaeger v2 реализуется послойно:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. Уровень хоста и ОС (Bare-Metal / Linux Node)                         │
│    - non-root пользователь (UID/GID 10001)                              │
│    - systemd sandboxing (ProtectSystem=strict, PrivateTmp=true)         │
│    - Linux Capabilities: BoundingSet= (сброс всех привилегий)           │
├─────────────────────────────────────────────────────────────────────────┤
│ 2. Сетевой уровень (Network Isolation)                                  │
│    - Kubernetes NetworkPolicy: default-deny ingress/egress              │
│    - Белые списки IP-адресов и строгая изоляция по неймспейсам          │
├─────────────────────────────────────────────────────────────────────────┤
│ 3. Транспортный уровень (Transport Security)                            │
│    - mTLS (TLS 1.3, TLS 1.2 с безопасными Cipher Suites)                │
│    - Автоматическая ротация сертификатов через cert-manager / Vault     │
├─────────────────────────────────────────────────────────────────────────┤
│ 4. Прикладной уровень (Application & Ingestion Security)                 │
│    - Проверка входящих токенов: bearertokenauth                         │
│    - Защита Query UI/API: обратный прокси (OAuth2-Proxy / Keycloak)     │
│    - Защита от OOM: процессор memory_limiter                            │
├─────────────────────────────────────────────────────────────────────────┤
│ 5. Уровень очистки данных (Data Sanitization & Scrubbing)               │
│    - Удаление заголовков Authorization, Cookie, Token                   │
│    - Регулярные выражения OTTL для маскирования паролей и номеров карт   │
├─────────────────────────────────────────────────────────────────────────┤
│ 6. Уровень хранилища (Storage Hardening)                                │
│    - Least Privilege RBAC в ClickHouse (отдельные роли Writer / Reader) │
│    - Запрет DDL-команд (DROP, TRUNCATE, ALTER)                          │
│    - Аудит запросов в system.query_log                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Сквозная настройка взаимного TLS (mTLS) для OTLP и ClickHouse

**Контекст:** Требуется обеспечить криптографическую защиту каналов передачи данных: от прикладных микросервисов к Jaeger Collector (OTLP gRPC/HTTP) и от коллектора к СУБД ClickHouse по нативному защищенному протоколу (порт 9440). Plaintext-порты (4317 без TLS, 9000 ClickHouse) должны быть закрыты.

#### 1. Создание внутреннего CA и сертификатов через OpenSSL

```bash
# Создание директории для PKI
mkdir -p /etc/jaeger/pki && cd /etc/jaeger/pki

# 1. Генерация корневого центра сертификации (Root CA)
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 1095 \
  -subj "/C=RU/ST=Moscow/O=Infrastructure/CN=Internal-Observability-CA" \
  -out ca.crt
# → Certificate generated: ca.crt

# 2. Подготовка конфигурации для сертификата Jaeger Collector
cat <<'EOF' > collector.ext
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = jaeger-collector
DNS.2 = jaeger-collector.observability
DNS.3 = jaeger-collector.observability.svc
DNS.4 = jaeger-collector.observability.svc.cluster.local
IP.1 = 127.0.0.1
EOF

# Генерация ключа и сертификата Jaeger Collector
openssl genrsa -out collector.key 2048
openssl req -new -key collector.key -out collector.csr \
  -subj "/C=RU/ST=Moscow/O=Infrastructure/CN=jaeger-collector.observability.svc"
openssl x509 -req -in collector.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out collector.crt -days 365 -sha256 -extfile collector.ext
# → Signature ok, certificate created: collector.crt

# 3. Подготовка конфигурации для сертификата ClickHouse Storage
cat <<'EOF' > clickhouse.ext
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = clickhouse
DNS.2 = clickhouse.observability
DNS.3 = clickhouse.observability.svc
DNS.4 = clickhouse.observability.svc.cluster.local
IP.1 = 127.0.0.1
EOF

openssl genrsa -out clickhouse.key 2048
openssl req -new -key clickhouse.key -out clickhouse.csr \
  -subj "/C=RU/ST=Moscow/O=Infrastructure/CN=clickhouse.observability.svc"
openssl x509 -req -in clickhouse.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out clickhouse.crt -days 365 -sha256 -extfile clickhouse.ext
# → Signature ok, certificate created: clickhouse.crt

# 4. Установка строгих прав на ключи
chmod 600 *.key
chmod 644 *.crt
```

#### 2. Конфигурация Jaeger v2 (OpenTelemetry Collector)

В конфигурационном файле коллектора указываются пути к сертификатам и включается принудительная проверка клиентских сертификатов (`client_ca_file`).

```yaml
# /etc/jaeger/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        tls:
          cert_file: /etc/jaeger/pki/collector.crt
          key_file: /etc/jaeger/pki/collector.key
          client_ca_file: /etc/jaeger/pki/ca.crt
          min_version: "1.3"
      http:
        endpoint: 0.0.0.0:4318
        tls:
          cert_file: /etc/jaeger/pki/collector.crt
          key_file: /etc/jaeger/pki/collector.key
          client_ca_file: /etc/jaeger/pki/ca.crt
          min_version: "1.3"

processors:
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20
  batch:
    send_batch_size: 4096
    timeout: 1s

extensions:
  healthcheckv2:
    endpoint: "127.0.0.1:13133"
  jaeger_storage:
    backends:
      clickhouse_secure:
        clickhouse:
          endpoint: "tcp://clickhouse.observability.svc:9440?secure=true&skip_verify=false"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "${env:CLICKHOUSE_WRITER_PASSWORD}"
          connection_params:
            dial_timeout: "5s"
            compress: "lz4"
          tls:
            ca_file: /etc/jaeger/pki/ca.crt
            cert_file: /etc/jaeger/pki/collector.crt
            key_file: /etc/jaeger/pki/collector.key

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_secure
    queue:
      num_consumers: 8
      queue_size: 2000

service:
  extensions: [healthcheckv2, jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

#### 3. Валидация mTLS-соединений

```bash
# Проверка отклонения соединения без клиентского сертификата (ожидается ошибка handshake)
openssl s_client -connect 127.0.0.1:4317 -CAfile /etc/jaeger/pki/ca.crt </dev/null
# → 140324843259712:error:14094412:SSL routines:ssl3_read_bytes:sslv3 alert bad certificate:../ssl/record/rec_layer_s3.c:1543:SSL alert number 42

# Проверка успешного mTLS handshake с предоставлением валидного клиентского сертификата
openssl s_client -connect 127.0.0.1:4317 \
  -CAfile /etc/jaeger/pki/ca.crt \
  -cert /etc/jaeger/pki/collector.crt \
  -key /etc/jaeger/pki/collector.key </dev/null
# → Verify return code: 0 (ok)
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384

# Проверка защищенного подключения к ClickHouse Native TLS (порт 9440)
openssl s_client -connect clickhouse.observability.svc:9440 \
  -CAfile /etc/jaeger/pki/ca.crt \
  -cert /etc/jaeger/pki/collector.crt \
  -key /etc/jaeger/pki/collector.key </dev/null
# → Verify return code: 0 (ok)
# → Protocol  : TLSv1.3
```

---

### Сценарий 2: Аутентификация OTLP спанов через токен (`bearertokenauth`)

**Контекст:** В распределенной системе микросервисы отправляют трейсы через OTLP HTTP/gRPC. Чтобы предотвратить инъекцию спанов со стороны недоверенных процессов или сканеров сети, требуется аутентификация через заголовок `Authorization: Bearer <token>`.

#### 1. Конфигурация коллектора с расширением `bearertokenauth`

```yaml
# /etc/jaeger/config-auth.yaml
extensions:
  healthcheckv2:
    endpoint: "127.0.0.1:13133"
  jaeger_storage:
    backends:
      clickhouse_prod:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "${env:CH_PASSWORD}"

  # Расширение аутентификации по статическому или ротируемому токену
  bearertokenauth:
    token: "${env:OTLP_INGEST_BEARER_TOKEN}"

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        auth:
          authenticator: bearertokenauth
      http:
        endpoint: 0.0.0.0:4318
        auth:
          authenticator: bearertokenauth

processors:
  batch:
    timeout: 1s

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_prod

service:
  # bearertokenauth обязательно регистрируется в секции extensions
  extensions: [healthcheckv2, jaeger_storage, bearertokenauth]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
```

#### 2. Валидация аутентификации

```bash
# 1. Попытка отправки спана без токена авторизации (ожидается HTTP 401 Unauthorized)
curl -i -X POST http://127.0.0.1:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
# → HTTP/1.1 401 Unauthorized
# → content-length: 19
# → content-type: text/plain; charset=utf-8
# → 401 Unauthorized

# 2. Попытка отправки спана с неверным токеном
curl -i -X POST http://127.0.0.1:4318/v1/traces \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer InvalidSecretToken" \
  -d '{"resourceSpans":[]}'
# → HTTP/1.1 401 Unauthorized
# → 401 Unauthorized

# 3. Успешная отправка спана с легитимным токеном
export OTLP_TOKEN="SuperSecretProductionIngestKey2026"
curl -i -X POST http://127.0.0.1:4318/v1/traces \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OTLP_TOKEN}" \
  -d '{"resourceSpans":[]}'
# → HTTP/1.1 200 OK
# → content-length: 2
# → content-type: application/json
# → {}
```

---

### Сценарий 3: Защита от утечки PII и маскирование секретов в спанах (Data Redaction)

**Контекст:** Разработчики сервисов могут случайно передавать в атрибутах спанов конфиденциальные данные: пароли, токены авторизации в заголовках, номера кредитных карт, номера телефонов или токены сессий. Необходимо настроить автоматическую санитизацию данных на стороне коллектора до их сохранения в хранилище.

#### 1. Конфигурация процессора `transform` с OTTL

```yaml
processors:
  transform:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          # Удаление высокорисковых HTTP-заголовков из атрибутов спанов
          - delete_key(attributes, "http.request.header.authorization")
          - delete_key(attributes, "http.request.header.cookie")
          - delete_key(attributes, "http.request.header.set-cookie")
          - delete_key(attributes, "http.request.header.x-api-key")

          # Маскирование Bearer-токенов в любых строковых атрибутах
          - replace_all_patterns(attributes, "value", "(?i)bearer\\s+[a-zA-Z0-9_\\-\\.]+", "Bearer [REDACTED]")

          # Маскирование паролей в SQL-запросах (атрибут db.statement)
          - replace_pattern(attributes["db.statement"], "(?i)password\\s*=\\s*'[^']+'", "password='[REDACTED]'")
          - replace_pattern(attributes["db.statement"], "(?i)password\\s*=\\s*\"[^\"]+\"", "password=\"[REDACTED]\"")

          # Маскирование номеров кредитных карт (16 цифр с дефисами или пробелами)
          - replace_all_patterns(attributes, "value", "\\b(?:\\d[ -]*?){13,16}\\b", "[REDACTED_PAN]")

          # Маскирование номеров телефонов (+7 или 8 с 10 цифрами)
          - replace_all_patterns(attributes, "value", "(\\+7|8)[- ]?\\(?\\d{3}\\)?[- ]?\\d{3}[- ]?\\d{2}[- ]?\\d{2}", "[REDACTED_PHONE]")
```

#### 2. Валидация маскирования

```bash
# Отправка тестового спана, содержащего пароль в SQL и персональный номер телефона
curl -s -X POST http://127.0.0.1:4318/v1/traces \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OTLP_TOKEN}" \
  -d '{
    "resourceSpans": [{
      "scopeSpans": [{
        "spans": [{
          "traceId": "5b832c2d4279e4f5cd64694eb3b0ce3e",
          "spanId": "f714273c12ae4a09",
          "name": "SELECT user_credentials",
          "kind": 1,
          "attributes": [
            {"key": "db.statement", "value": {"stringValue": "SELECT * FROM users WHERE login='admin' AND password='SuperPassword123'"}},
            {"key": "user.contact", "value": {"stringValue": "Call client at +7-999-123-45-67"}}
          ]
        }]
      }]
    }]
  }'
# → {}

# Проверка записи в ClickHouse (убеждаемся, что данные замаскированы)
clickhouse-client --query "
  SELECT
    span_name,
    mapFilter((k, v) -> k IN ('db.statement', 'user.contact'), span_attributes) AS sanitized_attributes
  FROM jaeger_v2.spans
  WHERE trace_id = '5b832c2d4279e4f5cd64694eb3b0ce3e'
  FORMAT Vertical"
# → Row 1:
# → ──────
# → span_name:            SELECT user_credentials
# → sanitized_attributes: {'db.statement':'SELECT * FROM users WHERE login=\'admin\' AND password=\'[REDACTED]\'','user.contact':'Call client at [REDACTED_PHONE]'}
```

---

### Сценарий 4: Защита Jaeger Query UI и API через обратный прокси с аутентификацией

**Контекст:** Встроенный компонент Jaeger Query UI / API (порт 16686) не содержит базы учетных записей пользователей и системы разграничения прав. Прямой доступ к порту 16686 недопустим. Требуется настроить обратный прокси NGINX с проверкой HTTP Basic Auth или интеграцией с корпоративным OIDC-провайдером (Keycloak) через OAuth2-Proxy.

#### 1. Конфигурация NGINX Reverse Proxy с взаимной аутентификацией и Basic Auth

```nginx
# /etc/nginx/conf.d/jaeger-query-security.conf
upstream jaeger_query_backend {
    server 127.0.0.1:16686;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name jaeger.internal.infra;

    # TLS-сертификаты прокси
    ssl_certificate           /etc/nginx/ssl/jaeger-proxy.crt;
    ssl_certificate_key       /etc/nginx/ssl/jaeger-proxy.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_ciphers               ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;

    # Настройки безопасности HTTP-заголовков
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;" always;

    # Аутентификация администраторов и SRE
    auth_basic "Jaeger Internal Tracing UI - Authentication Required";
    auth_basic_user_file /etc/nginx/.htpasswd_jaeger;

    # Ограничение частоты запросов для защиты от перебора
    limit_req zone=jaeger_limit burst=20 nodelay;

    location / {
        proxy_pass http://jaeger_query_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # Тайм-ауты проксирования
        proxy_connect_timeout 5s;
        proxy_read_timeout    60s;
        proxy_send_timeout    60s;
    }

    # Логирование доступа в формате JSON для SIEM
    access_log /var/log/nginx/jaeger_access_audit.log combined;
}
```

#### 2. Генерация паролей и проверка доступа

```bash
# Создание учетной записи администратора в файле паролей
htpasswd -B -c /etc/nginx/.htpasswd_jaeger sre_admin
# New password: StrongAdminPassword2026!
# Re-type new password: StrongAdminPassword2026!
# → Adding password for user sre_admin

# Перезапуск NGINX
nginx -t && systemctl reload nginx
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 1. Попытка входа без учетных данных (ожидается 401 Unauthorized)
curl -k -I https://jaeger.internal.infra/
# → HTTP/2 401
# → server: nginx
# → www-authenticate: Basic realm="Jaeger Internal Tracing UI - Authentication Required"

# 2. Успешный вход с авторизацией
curl -k -I -u sre_admin:StrongAdminPassword2026! https://jaeger.internal.infra/
# → HTTP/2 200
# → content-type: text/html; charset=utf-8
```

---

### Сценарий 5: Сетевая изоляция в Kubernetes с NetworkPolicy (Default Deny)

**Контекст:** В Kubernetes-кластере необходимо изолировать namespace `observability`, где запущен Jaeger. По умолчанию любой pod в кластере не должен иметь возможности подключиться к коллектору, UI или хранилищу ClickHouse, если ему явно не предоставлены права.

```yaml
# 1. Запрет всего входящего и исходящего трафика по умолчанию (Default-Deny)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jaeger-default-deny-all
  namespace: observability
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
# 2. Правила доступа для Jaeger Collector
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jaeger-collector-allow-traffic
  namespace: observability
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем прием OTLP трафика только от приложений с меткой allow-tracing=true
    - from:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              allow-tracing: "true"
      ports:
        - protocol: TCP
          port: 4317 # OTLP gRPC
        - protocol: TCP
          port: 4318 # OTLP HTTP
    # Разрешаем опрос метрик только агенту Prometheus
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 8888 # Internal metrics
  egress:
    # Разрешаем исходящий трафик только к ClickHouse (порт 9440 TLS)
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: clickhouse
      ports:
        - protocol: TCP
          port: 9440
    # Разрешаем DNS-резолв в CoreDNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

#### Валидация применения сетевых политик

```bash
# Применение NetworkPolicy
kubectl apply -f jaeger-network-policy.yaml -n observability
# → networkpolicy.networking.k8s.io/jaeger-default-deny-all created
# → networkpolicy.networking.k8s.io/jaeger-collector-allow-traffic created

# Проверка блокировки: запуск пода без разрешающей метки
kubectl run test-unauthorized --namespace=default --image=busybox:1.36 --rm -it --restart=Never -- nc -zvw3 jaeger-collector.observability 4317
# → nc: jaeger-collector.observability (10.96.120.45:4317): Connection timed out

# Проверка доступа: запуск пода с меткой allow-tracing=true
kubectl run test-authorized --namespace=default --labels="allow-tracing=true" --image=busybox:1.36 --rm -it --restart=Never -- nc -zvw3 jaeger-collector.observability 4317
# → jaeger-collector.observability (10.96.120.45:4317) open
```

---

### Сценарий 6: Управление секретами и автоматическая ротация сертификатов (Vault + cert-manager)

**Контекст:** Исключение хранения статичных паролей и закрытых ключей в Git и ручного обновления сертификатов. Синхронизация паролей выполняется из on-premise инсталляции HashiCorp Vault через External Secrets Operator, а сертификаты выпускаются и ротируются cert-manager с привязкой к Vault PKI.

#### 1. Синхронизация секретов через External Secrets Operator

```yaml
# Подключение к локальному HashiCorp Vault
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: vault-onprem-backend
spec:
  provider:
    vault:
      server: "https://vault.internal.infra:8200"
      path: "secret"
      version: "v2"
      caProvider:
        type: ConfigMap
        name: internal-ca-bundle
        namespace: external-secrets
        key: ca.crt
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "observability-secrets-role"
          serviceAccountRef:
            name: "eso-sa"
            namespace: "external-secrets"
---
# Определение секрета для Jaeger
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: jaeger-storage-credentials
  namespace: observability
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-onprem-backend
    kind: ClusterSecretStore
  target:
    name: jaeger-storage-secret
    creationPolicy: Owner
  data:
    - secretKey: CLICKHOUSE_WRITER_PASSWORD
      remoteRef:
        key: observability/clickhouse
        property: writer_password
```

#### 2. Автоматическая ротация TLS-сертификатов через cert-manager

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: jaeger-collector-tls-cert
  namespace: observability
spec:
  secretName: jaeger-collector-tls-secret
  duration: 1440h    # 60 дней
  renewBefore: 360h  # Автоматическое перевыпускание за 15 дней до окончания срока
  isCA: false
  privateKey:
    algorithm: RSA
    encoding: PKCS1
    size: 4096
    rotationPolicy: Always
  usages:
    - server auth
    - client auth
  dnsNames:
    - jaeger-collector
    - jaeger-collector.observability
    - jaeger-collector.observability.svc
    - jaeger-collector.observability.svc.cluster.local
  issuerRef:
    name: vault-pki-issuer
    kind: ClusterIssuer
```

#### Валидация синхронизации и статуса сертификата

```bash
# 1. Проверка синхронизации секрета из Vault
kubectl get externalsecret jaeger-storage-credentials -n observability
# → NAME                         STORE                  REFRESH INTERVAL   STATUS         READY
# → jaeger-storage-credentials   vault-onprem-backend   1h                 SecretSynced   True

# 2. Проверка состояния сертификата cert-manager
kubectl describe certificate jaeger-collector-tls-cert -n observability
# → Status:
# →   Conditions:
# →     Last Transition Time:  2026-10-12T14:30:00Z
# →     Message:               Certificate is up to date and has not expired
# →     Reason:                Ready
# →     Status:                True
# →     Type:                  Ready
# →   Not After:               2026-12-11T14:30:00Z
# →   Renewal Time:            2026-11-26T14:30:00Z
```

---

### Сценарий 7: Харденинг на уровне операционной системы и контейнеров

**Контекст:** Ограничение поверхности атаки процесса Jaeger. При компрометации бинарного файла процесс не должен получить доступ к файловой системе хоста, возможности запуска подпроцессов или повышения привилегий.

#### 1. Systemd Sandboxing для Bare-Metal / Виртуальных машин

```ini
# /etc/systemd/system/jaeger.service.d/hardening.conf
[Service]
# Запуск от непривилегированного пользователя
User=jaeger
Group=jaeger

# Защита файловой системы
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

# Каталоги, доступные только на запись (логи и временные сокеты)
ReadWritePaths=/var/log/jaeger /var/run/jaeger
ReadOnlyPaths=/etc/jaeger

# Изоляция адресных пространств и прав
NoNewPrivileges=true
MemoryDenyWriteExecute=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Сброс всех Linux Capabilities кроме привязки к привилегированным портам (если требуется)
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
```

#### 2. Pod Security Context для Kubernetes (Restricted Profile)

```yaml
# Фрагмент манифеста Pod / Deployment для Jaeger Collector
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: jaeger-collector
          image: jaegertracing/jaeger:2.3.0
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: tmp-dir
              mountPath: /tmp
            - name: config-volume
              mountPath: /etc/jaeger
              readOnly: true
      volumes:
        - name: tmp-dir
          emptyDir: {}
        - name: config-volume
          configMap:
            name: jaeger-collector-config
```

#### Валидация профиля безопасности

```bash
# 1. Проверка оценки безопасности systemd-юнита в Linux
systemd-analyze security jaeger.service
# → Overall exposure level for jaeger.service: 1.2 OK (Protected)

# 2. Проверка ограничений в запущенном Kubernetes-контейнере
kubectl exec -it deployment/jaeger-collector -n observability -- touch /root/test.txt
# → touch: /root/test.txt: Read-only file system

kubectl exec -it deployment/jaeger-collector -n observability -- id
# → uid=10001(jaeger) gid=10001(jaeger) groups=10001(jaeger)
```

---

### Сценарий 8: Разграничение привилегий и аудит в ClickHouse (Least Privilege RBAC)

**Контекст:** Collector производит только запись спанов, а Query выполняет только их чтение. Предоставление коллектору прав суперпользователя (`default` без пароля с полными правами) создает риск уничтожения базы. Необходимо настроить ролевую модель и аудит обращений.

#### 1. Настройка учетных записей и ролей в ClickHouse

```sql
-- Подключение под администратором СУБД
-- clickhouse-client --user admin --password

-- 1. Создание роли для записи спанов (Collector)
CREATE ROLE IF NOT EXISTS jaeger_collector_role;
GRANT SELECT, INSERT ON jaeger_v2.* TO jaeger_collector_role;

-- 2. Создание роли для чтения спанов (Query UI / API)
CREATE ROLE IF NOT EXISTS jaeger_query_role;
GRANT SELECT ON jaeger_v2.* TO jaeger_query_role;

-- 3. Создание пользователей с паролями SHA256
CREATE USER IF NOT EXISTS jaeger_writer
  IDENTIFIED WITH sha256_password BY 'StrongWriterSecret2026!'
  DEFAULT ROLE jaeger_collector_role;

CREATE USER IF NOT EXISTS jaeger_reader
  IDENTIFIED WITH sha256_password BY 'StrongReaderSecret2026!'
  DEFAULT ROLE jaeger_query_role;

-- 4. Запрет изменения структуры данных для сервисных ролей (защита от DDL)
REVOKE DROP, ALTER, TRUNCATE ON jaeger_v2.* FROM jaeger_collector_role;
REVOKE DROP, ALTER, TRUNCATE ON jaeger_v2.* FROM jaeger_query_role;
```

#### 2. Аудит запросов через `system.query_log`

В ClickHouse аудит всех входящих запросов сохраняется в системную таблицу `system.query_log`. Для проверки попыток неавторизованного доступа выполняется регулярный мониторинг:

```bash
# Проверка попытки выполнения запрещенной операции (DROP TABLE) пользователем jaeger_writer
clickhouse-client --user jaeger_writer --password 'StrongWriterSecret2026!' \
  --query "DROP TABLE jaeger_v2.spans"
# → Code: 497. DB::Exception: jaeger_writer: Not enough privileges. Cannot execute query in row 1: DROP TABLE jaeger_v2.spans. (ACCESS_DENIED)

# Поиск инцидентов безопасности в журнале аудита ClickHouse
clickhouse-client --query "
  SELECT
    event_time,
    user,
    client_hostname,
    exception_code,
    query
  FROM system.query_log
  WHERE exception_code = 497
    AND event_time >= now() - INTERVAL 1 HOUR
  ORDER BY event_time DESC
  LIMIT 5
  FORMAT TabSeparatedWithNames"
# → event_time          user           client_hostname   exception_code query
# → 2026-10-12 14:45:10 jaeger_writer  collector-node-01 497            DROP TABLE jaeger_v2.spans
```

---

## Операции и команды

Практический справочник для SRE и системных администраторов по проверке и аудиту безопасности Jaeger.

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка срока действия TLS-сертификата** | `openssl x509 -in /etc/jaeger/pki/collector.crt -noout -dates` | `notBefore=Oct 12 10:00:00 2026 GMT`<br>`notAfter=Oct 12 10:00:00 2027 GMT` |
| **Проверка поддержки только TLS 1.3 на порту OTLP** | `openssl s_client -connect 127.0.0.1:4317 -tls1_2 </dev/null` | Handshake failure (подключение отклонено при запрете TLS 1.2) |
| **Проверка прав RBAC сервисного аккаунта в K8s** | `kubectl auth can-i delete pods --as=system:serviceaccount:observability:jaeger-collector` | `no` |
| **Инспекция сетевых политик подов Jaeger** | `kubectl get networkpolicy -n observability` | Отображение политик `jaeger-default-deny-all` и правил Ingress |
| **Проверка Seccomp и UID в запущенном контейнере** | `kubectl get pod -n observability -l app.kubernetes.io/name=jaeger-collector -o jsonpath='{.items[0].spec.securityContext}'` | `{"fsGroup":10001,"runAsNonRoot":true,"runAsUser":10001,"seccompProfile":{"type":"RuntimeDefault"}}` |
| **Аудит безопасности systemd службы** | `systemd-analyze security jaeger.service` | `EXPOSURE: 1.2 OK` |
| **Аудит отклоненных соединений в логах Collector** | `journalctl -u jaeger -n 100 --no-pager \| grep -E "(tls: bad certificate\|authentication failed)"` | Фиксация заблокированных неавторизованных запросов |
| **Проверка метрик сброса памяти коллектора** | `curl -s http://127.0.0.1:8888/metrics \| grep otelcol_processor_refused_spans` | Числовой счетчик спанов, отброшенных `memory_limiter` при перегрузке |

---

## Диагностика и устранение неисправностей

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`x509: certificate signed by unknown authority`** | Сертификат клиента или сервера подписан CA, отсутствующим в доверенном бандле (`client_ca_file` / `ca_file`) | Проверить цепочку сертификатов:<br>`openssl verify -CAfile /etc/jaeger/pki/ca.crt /etc/jaeger/pki/collector.crt` | Смонтировать актуальный `ca.crt` в контейнер и указать путь в параметрах `client_ca_file` ресивера и `ca_file` клиента |
| **`remote error: tls: bad certificate`** | Клиентский сервис не передает клиентский сертификат, либо его срок действия истек | В логах Jaeger Collector:<br>`grep -i "bad certificate" /var/log/jaeger/collector.log` | Настроить отправку клиентского сертификата на стороне OTel SDK приложения; проверить срок действия через `openssl x509 -enddate` |
| **`401 Unauthorized` при отправке спанов** | Токен в заголовке `Authorization: Bearer` не совпадает со значением в расширении `bearertokenauth` | Отправить тестовый запрос:<br>`curl -v -H "Authorization: Bearer $TOKEN" http://collector:4318/v1/traces` | Синхронизировать значение токена в переменной окружения `OTLP_INGEST_BEARER_TOKEN` и в конфигурации микросервиса |
| **`Connection timed out` к портам 4317/4318** | Трафик блокируется `NetworkPolicy` в Kubernetes или `iptables`/`nftables` на хосте | Выполнить сетевой тест:<br>`kubectl run net-test --image=busybox --rm -it --restart=Never -- nc -zvw2 jaeger-collector 4317` | Добавить лейбл отправителя в разрешающий `podSelector` или проверить открытость портов в `iptables -L -n -v` |
| **`CrashLoopBackOff: open /etc/jaeger/...: permission denied`** | Процесс запущен под UID 10001, а файлы конфигурации или ключи имеют владельца `root` с правами `0600` | Проверить права на сервере:<br>`ls -la /etc/jaeger/pki/` | Сменить владельца ключей на пользователя процесса:<br>`chown -R 10001:10001 /etc/jaeger/pki` и установить права `600` на `.key` |
| **`CrashLoopBackOff: Read-only file system`** | При включенном `readOnlyRootFilesystem: true` процесс пытается писать временные файлы в локальный корень | Изучить логи старта:<br>`kubectl logs deployment/jaeger-collector -n observability` | Смонтировать `emptyDir` том в `/tmp` и другие рабочие каталоги записи |
| **`ClickHouse exception: ACCESS_DENIED`** | Учетная запись `jaeger_writer` не имеет прав `INSERT` в таблицу `spans` или пытается выполнить DDL | Проверить журнал ClickHouse:<br>`SELECT * FROM system.query_log WHERE exception_code != 0 ORDER BY event_time DESC LIMIT 5` | Назначить гранты через администратора:<br>`GRANT INSERT, SELECT ON jaeger_v2.* TO jaeger_collector_role` |
| **Утечка токенов в спанах** | Ошибка синтаксиса в правилах OTTL процессора `transform` или неверный контекст (`span` vs `resource`) | Проверить отфильтрованные данные в ClickHouse:<br>`SELECT span_attributes FROM jaeger_v2.spans WHERE mapContains(span_attributes, 'http.request.header.authorization')` | Исправить регулярные выражения в `transformprocessor`, проверить регистрацию процессора в `pipelines.traces.processors` |

---

## Лучшие практики

1. **mTLS между всеми узлами инфраструктуры:** Исключите использование plaintext-портов (4317, 4318, 9000, 16686). Используйте TLS 1.3 с взаимной проверкой сертификатов для всех межузловых взаимодействий.
2. **Аутентификация OTLP Ingestion:** Защищайте входные шлюзы трассировки токенами (`bearertokenauth`) или mTLS, чтобы предотвратить инъекцию спанов и фальсификацию метрик.
3. **Очистка данных на входе (Data Redaction):** Настройте процессор `transform` с OTTL для немедленного маскирования и удаления паролей, Bearer-токенов, cookies и номеров банковских карт до записи в хранилище.
4. **Сетевой периметр Default-Deny:** Внедряйте Kubernetes NetworkPolicy, блокирующие весь трафик по умолчанию. Открывайте только необходимые порты между верифицированными сервисами.
5. **Изоляция интерфейса Jaeger Query:** Никогда не публикуйте Jaeger Query UI напрямую во внешнюю сеть. Защищайте веб-интерфейс обратным прокси (NGINX, OAuth2-Proxy) с OIDC-аутентификацией (Keycloak) или строгим Basic Auth.
6. **Запуск от непривилегированного пользователя:** Применяйте профиль `restricted` в Kubernetes и директивы `ProtectSystem=strict`, `NoNewPrivileges=true`, `PrivateTmp=true` в systemd на bare-metal.
7. **Принцип наименьших привилегий в СУБД:** Разделяйте учетные записи для записи (`jaeger_writer`) и чтения (`jaeger_reader`). Категорически запрещайте DDL-операции (`DROP`, `TRUNCATE`, `ALTER`).
8. **Автоматическая ротация секретов и ключей:** Не храните статичные сертификаты на дисках бессрочно. Используйте связку cert-manager и HashiCorp Vault для ротации сертификатов с интервалом не более 60–90 дней.
9. **Защита от отказа в обслуживании (DoS):** Всегда конфигурируйте процессор `memory_limiter` в начале пайплайна, чтобы коллектор сбрасывал нагрузку при дефиците RAM вместо аварийного завершения по OOMKilled.
10. **Регулярный аудит журналов:** Анализируйте системные журналы аудита (NGINX access audit, ClickHouse `system.query_log`, события Kubernetes Audit) для своевременного обнаружения попыток сканирования и эскалации привилегий.

---

## Дополнительная информация

**Смежные разделы:**
* Развертывание в кластере: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Протоколы и конфигурация OTLP: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* Архитектурные особенности v2: **[Архитектура Jaeger v2](./jaeger_architecture.md)**
* Эксплуатация Query API: **[Jaeger Query API](./jaeger_query_api.md)**
* Отказоустойчивость: **[High Availability и DR](./jaeger_high_availability.md)**
* Оптимизация бэкенда: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
* Безопасность СУБД: **[Безопасность и разграничение прав в ClickHouse](../Databases/ClickHouse/clickhouse-security.md)**
* Управление секретами: **[HashiCorp Vault: Обзор и архитектура](../Vault/overview.md)**
* Интеграция секретов в K8s: **[Внешние менеджеры секретов в Kubernetes](../Kubernetes/Base/secrets/external_managers.md)**
* Харденинг системных служб: **[Управление привилегиями и безопасность systemd](../Linux/SystemAdministration/privilege_management.md)**

**Официальная документация:**
* [Jaeger Tracing Security Documentation](https://www.jaegertracing.io/docs/latest/security/)
* [OpenTelemetry Collector Security Best Practices](https://opentelemetry.io/docs/collector/security/)
* [OpenTelemetry Transformation Language (OTTL)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/pkg/ottl)
* [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
