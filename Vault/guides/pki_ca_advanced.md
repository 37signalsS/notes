# PKI и CA в Vault — продвинутые сценарии

> **Актуально для:** Vault Enterprise/PKI 2.x (latest 2.1.2; ветка 1.16.x+ поддерживается)

## Определения

**PKI (Public Key Infrastructure)** — инфраструктура открытых ключей, обеспечивающая создание, распространение и управление цифровыми сертификатами. Vault предоставляет полноценный внутренний CA (Certificate Authority) для выдачи TLS/SSH сертификатов.

**Intermediate CA** — промежуточный центр сертификации, который подписан корневым CA (root CA). Intermediate CA используется для ежедневной выдачи сертификатов, что ограничивает радиус поражения при компрометации. Корневой CA хранится офлайн и используется только для подписи intermediate CA.

**Root CA** — корневой центр сертификации, самоподписанный сертификат, который является trust anchor всей иерархии. В production root CA хранится офлайн (HSM, air-gapped машина).

**ACME (Automatic Certificate Management Environment)** — протокол, позволяющий автоматически запрашивать и обновлять TLS-сертификаты (Let's Encrypt совместимый). Vault поддерживает ACME как альтернативу direct API. Требует Enterprise (с версии 1.15+).

**CRL (Certificate Revocation List)** — список отозванных сертификатов, который публикуется по определённому URL. Клиенты проверяют сертификат против CRL перед установкой соединения.

**OCSP (Online Certificate Status Protocol)** — протокол для проверки статуса отдельного сертификата в реальном времени. Более эффективен, чем CRL, для high-load сред. Настраивается через параметры `ocsp_disable` и `ocsp_expiry` в `/pki/config/crl`.

**Cross-signing** — процесс подписи промежуточного CA другим корневым CA, обеспечивающий совместимость с разными trust store. Используется при миграции с одного CA на другой.

**CSR (Certificate Signing Request)** — запрос на подпись сертификата, содержащий публичный ключ и информацию о субъекте (CN, SAN, O, OU). Vault может обрабатывать CSR через endpoint `/pki/sign-role`.

**Tidy** — фоновая операция очистки хранилища сертификатов: удаление просроченных сертификатов, записей об отзыве и过期нтных issuer-ов. Настраивается через `/pki/config/auto-tidy`.

**Auto-rebuild** — периодическая автоматическая перестройка CRL при помощи параметров `auto_rebuild` и `auto_rebuild_grace_period` в `/pki/config/crl`. Рекомендуется вместо ручного вызова `/pki/crl/rotate`.

**Delta CRL** — приращённый CRL, содержащий только изменения с момента последнего полного CRL. Требует включения `auto_rebuild`.

**Unified CRL (Enterprise)** — кросс-кластерный CRL, объединяющий отзывы со всех performance replication кластеров. Настраивается через параметр `unified_crl` в `/pki/config/crl`.

## Основные концепции

### Архитектура PKI в Vault

Vault PKI Secrets Engine состоит из нескольких компонентов:

1. **Root CA:** Самоподписанный корневой сертификат. Генерируется один раз и хранится в Vault.
2. **Intermediate CA:** Промежуточный сертификат, подписанный root CA. Используется для ежедневной выдачи сертификатов.
3. **Roles:** Определяют политики выдачи сертификатов (разрешённые домены, TTL, типы ключей).
4. **Certificates:** Выданные сертификаты с автоматической ротацией.
5. **CRL/OCSP:** Механизмы отзыва сертификатов.

### Жизненный цикл сертификата

1. **Запрос:** Приложение запрашивает сертификат через `vault write pki/issue/role common_name=...`
2. **Выдача:** Vault проверяет политику роли, генерирует ключ (или принимает CSR), подписывает сертификат и возвращает его вместе с CA-цепочкой.
3. **Использование:** Приложение использует сертификат для TLS/mTLS.
4. **Ротация:** Vault Agent автоматически обновляет сертификат до истечения срока (через lease renewal или шаблонизацию)
5. **Отзыв:** При компрометации сертификат добавляется в CRL.

### Типы сертификатов

| Тип | Описание | Use case |
| :--- | :--- | :--- |
| **Server (TLS)** | Сертификат для серверов | HTTPS endpoints, API gateways |
| **Client (mTLS)** | Сертификат для клиентов | Взаимная TLS аутентификация |
| **SSH** | Сертификат для SSH | Вход на серверы (см. SSH Secrets Engine) |
| **Code Signing** | Подписание кода | Подписание артефактов, Docker images |

### Key Types и их ограничения

| Key Type | Поддерживаемые размеры | Примечания |
| :--- | :--- | :--- |
| **RSA** | 2048 (default), 3072, 4096, 8192 | Универсальная поддержка; 2048 минимум |
| **ECDSA** | 224, 256 (default), 384, 521 | Более короткие ключи при эквивалентной безопасности |
| **Ed25519** | N/A | Быстрая подпись, минимальные ключи |
| **ML-DSA** | ml-dsa-44, ml-dsa-65, ml-dsa-87 | Post-kвантовая криптография (Vault 1.15+) |

## Практические сценарии

### Сценарий 1: Установка Root CA и Intermediate CA

#### Шаг 1: Включение PKI Secrets Engine

```bash
vault secrets enable pki
vault secrets tune -max-lease-ttl=87600h pki
```

`max-lease-ttl=87600h` (10 лет) — стандартный срок для root CA.

#### Шаг 2: Генерация Root CA

```bash
vault write pki/root/generate/internal \
    common_name="Example Root CA" \
    organization="Example Corp" \
    country="US" \
    ttl=87600h \
    key_type=rsa \
    key_bits=4096 \
    exclude_cn_from_sans=true
# → Key             Value
# → certificate     -----BEGIN CERTIFICATE-----
# → issuing_ca      -----BEGIN CERTIFICATE-----
# → serial_number   1a2b3c4d
```

#### Шаг 3: Настройка URLs

```bash
vault write pki/config/urls \
    issuing_certificates="https://vault.example.com:8200/v1/pki/ca" \
    crl_distribution_points="https://vault.example.com:8200/v1/pki/crl"
```

#### Шаг 4: Создание Intermediate CA

```bash
# 4.1. Включение промежуточного CA (на отдельном mount point)
vault secrets enable -path=pki_int pki
vault secrets tune -max-lease-duration=8760h pki_int

# 4.2. Генерация CSR для intermediate CA
vault write pki_int/intermediate/generate/internal \
    common_name="Example Intermediate CA" \
    organization="Example Corp" \
    country="US" \
    ttl=8760h \
    key_type=rsa \
    key_bits=4096 > pki_intermediate.csr
# (CSR сохраняется в файл для передачи root CA)

# 4.3. Подпись CSR корневым CA
vault write pki/root/sign-intermediate \
    csr=@/path/to/intermediate.csr \
    common_name="Example Intermediate CA" \
    organization="Example Corp" \
    country="US" \
    format=pem_bundle \
    ttl=8760h > signed_intermediate.crt

# 4.4. Импорт подписанного сертификата
vault write pki_int/intermediate/set-signed \
    certificate=@/path/to/signed_intermediate.crt
```

**Важно:** `generate/internal` возвращает CSR в ответе, а приватный ключ остаётся внутри Vault. CSR нужно сохранить в файл, подписать его через `sign-intermediate`, затем импортировать результат обратно через `set-signed`.

### Сценарий 2: Выдача TLS-сертификатов

#### Создание роли

```bash
vault write pki_int/roles/webapp \
    allowed_domains="example.com,*.example.com" \
    allow_bare_domains=true \
    allow_subdomains=true \
    allow_glob_domains=true \
    allow_any_name=false \
    enforce_hostnames=true \
    max_ttl="720h" \
    ttl="720h" \
    key_type=rsa \
    key_bits=2048 \
    key_usage=["Digital Signature","Key Encipherment"] \
    ext_key_usage=["Server Auth"] \
    require_cn=true \
    allowed_uri_sans=["spiffe://example.com/*"]
```

#### Выдача сертификата

```bash
vault write pki_int/issue/webapp \
    common_name="app.example.com" \
    dns_names=["app.example.com","www.example.com"] \
    ip_sans=["10.0.0.1","192.168.1.1"] \
    ttl="24h"
# → Key             Value
# → certificate     -----BEGIN CERTIFICATE-----
# → issuing_ca      -----BEGIN CERTIFICATE-----
# → private_key     -----BEGIN RSA PRIVATE KEY-----
# → serial_number   1a2b3c4d
# → lease_id        pki_int/issue/webapp/abc123...
# → lease_duration  86400
```

#### Обработка CSR (если клиент генерирует ключ)

```bash
vault write pki_int/sign/webapp \
    csr=@/path/to/client.csr \
    common_name="app.example.com" \
    ttl="24h"
```

### Сценарий 3: mTLS с клиентскими сертификатами

```bash
# Роль для клиентских сертификатов
vault write pki_int/roles/client \
    allowed_domains="client.example.com" \
    allow_bare_domains=true \
    max_ttl="720h" \
    key_type=ec \
    key_bits=256 \
    key_usage=["Digital Signature","Key Agreement"] \
    ext_key_usage=["Client Auth"] \
    require_cn=true

# Выдача клиентского сертификата
vault write pki_int/issue/client \
    common_name="service-client" \
    ttl="720h"
```

Настройка Nginx для mTLS:

```nginx
server {
    listen 443 ssl;
    server_name app.example.com;

    ssl_certificate     /etc/nginx/server.crt;
    ssl_certificate_key /etc/nginx/server.key;
    ssl_client_certificate /etc/nginx/ca.crt;
    ssl_verify_client on;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
}
```

### Сценарий 4: ACME протокол (Let's Encrypt совместимый)

Vault выступает как ACME-сервер для автоматической выдачи сертификатов.

#### Шаг 1: Настройка mount tuning

```bash
# ACME клиенты требуют ответные заголовки Link, Location, Replay-Nonce
vault secrets tune \
    -allowed-response-headers=Link \
    -allowed-response-headers=Location \
    -allowed-response-headers=Replay-Nonce \
    pki/
```

#### Шаг 2: Настройка кластера и ACME

```bash
# Настройка пути кластера (для AIA URL templating)
vault write pki/config/cluster path="https://vault.example.com:8200/v1/pki"

# Включение ACME с EAB и ограничением ролей
vault write pki/config/acme \
    enabled=true \
    default_directory_policy="role:web-app" \
    eab_policy="if-required-by-dir" \
    allowed_roles="web-app,api-server"
```

#### Шаг 3: Создание EAB токена для клиента

```bash
vault write -f pki/acme/new-eab
# → Key        Value
# → key_id     abc123...
# → hmac_key   def456...
```

#### Шаг 4: Использование с cert-manager

```bash
# Использование с cert-manager (через Vault Issuer)
kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: vault-issuer
spec:
  vault:
    server: https://vault.example.com:8200
    path: pki_int/sign/webapp
    auth:
      tokenSecretRef:
        name: vault-token
        key: token
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: prod
spec:
  secretName: example-com-tls
  issuerRef:
    name: vault-issuer
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - "*.example.com"
EOF
```

### Сценарий 5: CRL и OCSP

#### Настройка CRL

```bash
# Включение CRL с авто-перестроением (auto_rebuild) и delta CRL
vault write pki/config/crl \
    disable=false \
    expiry="72h" \
    auto_rebuild=true \
    auto_rebuild_grace_period="12h" \
    enable_delta=true

# Проверка CRL endpoint
curl https://vault.example.com:8200/v1/pki/crl
# → -----BEGIN X509 CRL-----

# Ручной запуск перестроения CRL
vault write pki/crl/rotate
```

#### Настройка OCSP

```bash
# OCSP управляется через параметры в /pki/config/crl
# ocsp_disable=false означает что OCSP включён
# ocsp_expiry задаёт срок жизни OCSP ответа
vault write pki/config/crl \
    ocsp_disable=false \
    ocsp_expiry="1h"

# Проверка OCSP endpoint
curl https://vault.example.com:8200/v1/pki/ocsp
# → HTTP/1.0 200 OK
```

**Важно:** OCSP не имеет отдельного эндпоинта конфигурации. Параметры `ocsp_disable` и `ocsp_expiry` являются частью `/pki/config/crl`.

### Сценарий 6: Cross-signing (миграция CA)

При переходе с одного CA на другой:

```bash
# 1. Создание нового intermediate CA
vault secrets enable -path=new_pki pki
vault write new_pki/intermediate/generate/internal \
    common_name="New Intermediate CA" \
    ttl=8760h

# 2. Подпись нового CA старым root CA
vault write pki/root/sign-intermediate \
    csr=@/path/to/new_intermediate.csr \
    ttl=8760h

# 3. Импорт подписанного сертификата
vault write new_pki/intermediate/set-signed \
    certificate=@/path/to/new_intermediate.crt

# 4. Переход на новый CA
# Обновите TrustedUserCAKeys / TrustedUserCA на серверах
# Старые сертификаты остаются валидными до истечения TTL
```

### Сценарий 7: Автоматическая ротация сертификатов

Vault Agent автоматически обновляет сертификаты:

```hcl
template {
  source      = "/vault/templates/tls.ctmpl"
  destination = "/etc/nginx/tls/server.crt"

  # Автоматический перезапуск Nginx при обновлении сертификата
  command = ["nginx", "-s", "reload"]
}
```

Шаблон `tls.ctmpl`:

```
{{- with pkiCert "pki_int/issue/webapp" "common_name=app.example.com" -}}
-----BEGIN CERTIFICATE-----
{{ .Data.Certificate }}
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
{{ .Data.IssuingCA }}
-----END CERTIFICATE-----
{{- end -}}
```

### Сценарий 8: Отзыв сертификата и очистка хранилища

```bash
# Просмотр отозванных сертификатов (по serial number)
vault list pki_int/certs/revoked
# → Keys
# → ----
# → 1a:2b:3c:4d:...

# Отзыв сертификата по serial number
vault write pki_int/revoke \
    serial_number="1a:2b:3c:4d:..."
# → Key             Value
# → revocation_time  1433269787

# Отзыв сертификата по самому сертификату (PEM)
vault write pki_int/revoke \
    certificate="-----BEGIN CERTIFICATE-----..."

# Ручной запуск tidy для очистки просроченных записей
vault write pki/tidy \
    tidy_cert_store=true \
    tidy_revoked_certs=true \
    safety_buffer="720h"
```

### Сценарий 9: Автоматическая очистка (tidy) и мониторинг (SRE)

```bash
# Настройка автоматической очистки (auto-tidy)
vault write pki/config/auto-tidy \
    enabled=true \
    interval_duration="43200s" \
    tidy_cert_store=true \
    tidy_revoked_certs=true \
    tidy_revoked_cert_issuer_associations=true \
    tidy_expired_issuers=true \
    issuer_safety_buffer="8760h" \
    safety_buffer="1440h" \
    revocation_queue_safety_buffer="720h"

# Просмотр статуса tidy
vault read pki/config/auto-tidy
# → enabled                 true
# → interval_duration       43200
# → issuer_safety_buffer    8760h
# → safety_buffer           1440h
# → tidy_cert_store         true
# → tidy_revoked_certs      true
# → ...

# Просмотр статуса выполнения tidy
vault read pki/tidy/status
# → error                    <nil>
# → message                  Tidying certificate store: ...
# → revoked_cert_deleted_count  0
# → cert_store_deleted_count    2
# → state                    Finished
# → time_started             2024-01-15T14:52:13.510Z
```

### Сценарий 10: ACL-политики для PKI операторов (devops)

```hcl
# Политика оператора PKI (только для администраторов)
path "pki_int/roles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "pki_int/sign/*" {
  capabilities = ["update"]
}

path "pki_int/issue/*" {
  capabilities = ["update"]
}

path "pki_int/revoke" {
  capabilities = ["update"]
}

path "pki_int/certs/revoked" {
  capabilities = ["read", "list"]
}

path "pki_int/config/crl" {
  capabilities = ["read", "update"]
}

path "pki_int/config/auto-tidy" {
  capabilities = ["read", "update"]
}

# Service account (приложения) — только выдача сертификатов
path "pki_int/issue/webapp" {
  capabilities = ["update"]
}

path "pki_int/sign/webapp" {
  capabilities = ["update"]
}
```

```bash
# Применение политики оператора
vault policy write pki-operator pki-operator.hcl

# Создание AppRole для приложений
vault write auth/approle/role/webapp \
    token_policies="pki-app" \
    secret_id_ttl="0" \
    secret_id_num_uses="10"
```

## Операции и команды

### CLI команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `vault secrets enable pki` | Включить PKI secrets engine | `vault secrets enable -path=pki pki` |
| `vault secrets tune` | Настройка mount (TTL, headers) | `vault secrets tune -max-lease-ttl=720h pki` |
| `vault write pki/root/generate/internal` | Создать root CA | `vault write pki/root/generate/internal common_name=RootCA ttl=87600h` |
| `vault write pki_int/intermediate/generate/internal` | Создать intermediate CSR | `vault write pki_int/intermediate/generate/internal common_name=IntCA ttl=8760h` |
| `vault write pki/root/sign-intermediate` | Подписать intermediate | `vault write pki/root/sign-intermediate csr=@int.csr format=pem_bundle` |
| `vault write pki_int/intermediate/set-signed` | Импорт подписанного cert | `vault write pki_int/intermediate/set-signed certificate=@signed.crt` |
| `vault write pki_int/roles/<role>` | Создать роль | `vault write pki_int/roles/webapp allowed_domains=example.com` |
| `vault write pki_int/issue/<role>` | Выдача сертификата | `vault write pki_int/issue/webapp common_name=app.example.com` |
| `vault write pki_int/sign/<role>` | Подпись CSR | `vault write pki_int/sign/webapp csr=@req.csr common_name=app.example.com` |
| `vault write pki/config/urls` | Настройка AIA/CRL URLs | `vault write pki/config/urls issuing_certificates=... crl_distribution_points=...` |
| `vault write pki/config/crl` | Конфигурация CRL/OCSP | `vault write pki/config/crl disable=false expiry=72h auto_rebuild=true` |
| `vault write pki/config/acme` | Включить ACME | `vault write pki/config/acme enabled=true default_directory_policy="role:web"` |
| `vault write pki/revoke` | Отозвать сертификат | `vault write pki/revoke serial_number="1a:2b:3c"` |
| `vault list pki_int/certs/revoked` | Список отозванных | `vault list pki_int/certs/revoked` |
| `vault write pki/tidy` | Ручная очистка | `vault write pki/tidy tidy_cert_store=true safety_buffer="720h"` |
| `vault write pki/config/auto-tidy` | Автоматическая очистка | `vault write pki/config/auto-tidy enabled=true tidy_cert_store=true` |
| `vault read pki/tidy/status` | Статус tidy | `vault read pki/tidy/status` |

### API эндпоинты

| Метод | Путь | Описание | Ключевые параметры |
| :--- | :--- | :--- | :--- |
| `LIST` | `/pki/roles` | Список ролей | — |
| `GET` | `/pki/roles/:name` | Просмотр роли | `name` |
| `POST` | `/pki/roles/:name` | Создать/обновить роль | `allowed_domains`, `max_ttl`, `key_type`, `key_usage`, `ext_key_usage` |
| `POST` | `/pki/issue/:name` | Выдача сертификата | `common_name`, `dns_names`, `ip_sans`, `uri_sans`, `ttl` |
| `POST` | `/pki/sign/:name` | Подпись CSR | `csr`, `common_name`, `ttl` |
| `POST` | `/pki/revoke` | Отзыв сертификата | `serial_number` или `certificate` |
| `LIST` | `/pki/certs/revoked` | Список отозванных сертификатов | — |
| `POST` | `/pki/config/urls` | AIA/CRL URLs | `issuing_certificates`, `crl_distribution_points`, `ocsp_servers` |
| `GET/POST` | `/pki/config/crl` | Конфиг CRL/OCSP | `disable`, `expiry`, `auto_rebuild`, `ocsp_disable`, `ocsp_expiry` |
| `POST` | `/pki/config/acme` | Конфиг ACME | `enabled`, `default_directory_policy`, `eab_policy` |
| `POST` | `/pki/tidy` | Ручная очистка | `tidy_cert_store`, `tidy_revoked_certs`, `safety_buffer` |
| `GET/POST` | `/pki/config/auto-tidy` | Авто-очистка | `enabled`, `interval_duration`, `tidy_cert_store`, `safety_buffer` |
| `GET` | `/pki/tidy/status` | Статус tidy | — |

### Параметры ролей

| Параметр | Тип | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `allowed_domains` | list | [] | Разрешённые домены для сертификатов |
| `allow_bare_domains` | bool | false | Разрешить bare domains |
| `allow_subdomains` | bool | false | Разрешить поддомены |
| `allow_glob_domains` | bool | false | Разрешить glob patterns |
| `allow_any_name` | bool | false | Разрешить любое имя (осторожно!) |
| `enforce_hostnames` | bool | true | Проверять имена хостов |
| `max_ttl` | string | "" | Максимальный TTL сертификата |
| `ttl` | string | "" | TTL по умолчанию |
| `key_type` | string | rsa | rsa, ec, ed25519, ml-dsa |
| `key_bits` | int | 0 | Размер ключа (RSA: 2048/3072/4096/8192, EC: 224/256/384/521) |
| `key_usage` | list | ["DigitalSignature",...] | Key Usage constraints |
| `ext_key_usage` | list | [] | Extended Key Usage (например, "Server Auth", "Client Auth") |
| `require_cn` | bool | true | Требовать common_name |

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error making API request: ... 400 Bad Request` при `pki/config/acme` | ACME требует настройки mount tuning | Выполнить `vault secrets tune -allowed-response-headers=Link -allowed-response-headers=Location -allowed-response-headers=Replay-Nonce pki/` |
| `no handler for route "/pki/config/ocsp"` | OCSP настраивается через `/pki/config/crl`, а не отдельный endpoint | Использовать `ocsp_disable` и `ocsp_expiry` параметры в `/pki/config/crl` |
| `invalid parameter "enabled" in pki/config/crl` | Параметр `enabled` не используется; вместо него `disable=false` | `vault write pki/config/crl disable=false expiry=72h` |
| `unsupported parameter "reason" in pki/revoke` | `/pki/revoke` не принимает параметр `reason` | Использовать `vault write pki/revoke serial_number=...` без `reason` |
| `path pki_int/revoked does not exist` | Правильный путь — `pki_int/certs/revoked` | `vault list pki_int/certs/revoked` |
| `certificate serial number not found in CRL` | CRL не обновлён после отзыва | Вызвать `vault write pki/crl/rotate` или включить `auto_rebuild=true` |
| `OCSP response: unauthorized` | OCSP отключён | Включить через `vault write pki/config/crl ocsp_disable=false` |
| `intermediate certificate not properly signed` при `set-signed` | CSR не подписан или подпись неверна | Проверить что `sign-intermediate` использовался для подписи, а не `issue` |
| `error looking up issuer: no issuer found` | Intermediate не импортирован корректно | Убедиться что `certificate=@signed_intermediate.crt` содержит полностью подписанный сертификат |
| `mount pki_int is not a valid mount` | Mount не включён | `vault secrets enable -path=pki_int pki` |
| `TTL exceeds max` | Запрошенный TTL превышает `max_ttl` роли | Увеличить `max_ttl` роли или уменьшить запрошенный TTL |
| `tidy status shows errors` | Ошибки в хранилище (storage backend) | Проверить health storage backend; рассмотреть ручную очистку с `safety_buffer=0` |
| `CRL file слишком большой` | Много отозванных сертификатов | Использовать delta CRL (`enable_delta=true`) + tidy |
| `ocsp_expiry is not a valid parameter` на старых версиях | `ocsp_expiry` добавлен в Vault 1.14+ | На более ранних версиях используйте только `ocsp_disable` |

## Лучшие практики

1. **Иерархия CA:** Используйте root CA (офлайн) + intermediate CA (онлайн). Никогда не выписывайте сертификаты напрямую от root CA.
2. **Короткий TTL:** Настраивайте TTL сертификатов минимально необходимым (24–72 часа для production).
3. **CRL/OCSP:** Включите CRL с `auto_rebuild=true` и OCSP для возможности отзыва скомпрометированных сертификатов. Используйте delta CRL для больших развертываний.
4. **ACME:** Используйте ACME протокол для автоматизации выдачи сертификатов (cert-manager, Caddy, Traefik). Всегда включайте EAB для production.
5. **Key type:** Используйте RSA 2048+ или ECDSA P-256/P-384. Избегайте RSA 1024. Для новых развёртываний рассмотрите Ed25519.
6. **Rotation:** Планируйте ротацию intermediate CA раз в 1–2 года. Используйте cross-signing для плавного перехода.
7. **Auto-tidy:** Всегда включайте автоматическую очистку (`/pki/config/auto-tidy`) с `safety_buffer` не менее 30 дней для production.
8. **Audit:** Включите audit device для отслеживания всех операций выдачи и отзыва сертификатов.
9. **Backup:** Регулярно бэкапируйте root CA (offline backup) и конфигурацию PKI через Snapshot API.
10. **Monitoring:** Настраивайте алерты на истечение TTL корневого сертификата и длительные операции tidy. Используйте Vault telemetry для отслеживания метрик PKI.
11. **ACL policies:** Ограничьте доступ к `pki_int/sign/*`, `pki_int/revoke`, и `pki_int/config/*` через ACL-политики. Приложения должны иметь доступ только к `pki_int/issue/<role>`.
12. **AIA URL templating:** Используйте `enable_aia_url_templating=true` для multi-issuer развёртываний, чтобы CRL/OCSP URLs автоматически подставляли issuer ID.

## Ограничения и известные проблемы

- **Root CA:** Потеря root CA означает невозможность выдачи новых сертификатов. Храните root CA в HSM или air-gapped машине.
- **CRL размер:** При большом количестве отозванных сертификатов CRL может стать очень большой. Используйте Delta CRL (`enable_delta=true` + `auto_rebuild=true`).
- **OCSP stapling:** Некоторые серверы (Nginx, Apache) требуют настройки OCSP stapling для производительности.
- **ACMEPath:** ACME endpoint требует тонкой настройки mount tuning (`Link`, `Location`, `Replay-Nonce` заголовки) и не работает в OSS без Enterprise.
- **CSR validation:** Vault не валидирует CSR полностью. Убедитесь, что клиенты генерируют корректные CSR.
- **Tidy и простои:** Длинные операции tidy могут блокировать другие операции PKI. Планируйте tidy на off-peak часы.
- **Cross-namespace:** Intermediate CA не может быть подписана root CA из другого namespace без дополнительной конфигурации.
- **Max lease duration:** `max-lease-ttl` на mount конфигурирует верхний предел для всех сертификатов. Убедитесь, что он достаточно велик для корневых сертификатов (обычно 10 лет).
- **Unified CRL (Enterprise):** Требует Vault Enterprise license или HCP Plus cluster. В CE наблюдается кластерная изоляция CRL.
- **ML-DSA:** Поддержка post-kвантовых ключей доступна с Vault 1.15+, но ACME не поддерживает ML-DSA.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[SSH Secrets Engine](./ssh_secrets_engine.md)** — SSH-сертификаты через Vault.
*   **[Transit Engine — Политики](./transit-encryption-policies.md)** — шифрование как сервис.
*   **[Zero Trust](../zero_trust.md)** — роль PKI в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему статические сертификаты — антипаттерн.
*   [Официальная документация PKI Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/pki)
*   [PKI Secrets Engine API](https://developer.hashicorp.com/vault/api-docs/secret/pki)
*   [PKI Setup Guide](https://developer.hashicorp.com/vault/docs/secrets/pki/setup)