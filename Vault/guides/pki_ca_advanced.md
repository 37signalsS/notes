# PKI и CA в Vault — продвинутые сценарии

## Определения

**PKI (Public Key Infrastructure)** — инфраструктура открытых ключей, обеспечивающая создание, распространение и управление цифровыми сертификатами. Vault предоставляет полноценный внутренний CA (Certificate Authority) для выдачи TLS/SSH сертификатов.

**Intermediate CA** — промежуточный центр сертификации, который подписан корневым CA (root CA). Intermediate CA используется для ежедневной выдачи сертификатов, что ограничивает радиус поражения при компрометации. Корневой CA хранится офлайн и используется только для подписи intermediate CA.

**Root CA** — корневой центр сертификации, самоподписанный сертификат, который является trust anchor всей иерархии. В production root CA хранится офлайн (HSM, air-gapped машина).

**ACME (Automatic Certificate Management Environment)** — протокол, позволяющий автоматически запрашивать и обновлять TLS-сертификаты (Let's Encrypt совместимый). Vault поддерживает ACME как альтернативу direct API.

**CRL (Certificate Revocation List)** — список отозванных сертификатов, который публикуется по определённому URL. Клиенты проверяют сертификат против CRL перед установкой соединения.

**OCSP (Online Certificate Status Protocol)** — протокол для проверки статуса отдельного сертификата в реальном времени. Более эффективен, чем CRL, для high-load сред.

**Cross-signing** — процесс подписи промежуточного CA другим корневым CA, обеспечивающий совместимость с разными trust store. Используется при миграции с одного CA на другой.

**CSR (Certificate Signing Request)** — запрос на подпись сертификата, содержащий публичный ключ и информацию о субъекте (CN, SAN, O, OU). Vault может обрабатывать CSR через endpoint `/pki/sign-role`.

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
4. **Ротация:** Vault автоматически обновляет сертификат до истечения срока (через `lease_renewal_threshold`).
5. **Отзыв:** При компрометации сертификат добавляется в CRL.

### Типы сертификатов

| Тип | Описание | Use case |
| :--- | :--- | :--- |
| **Server (TLS)** | Сертификат для серверов | HTTPS endpoints, API gateways |
| **Client (mTLS)** | Сертификат для клиентов | Взаимная TLS аутентификация |
| **SSH** | Сертификат для SSH | Вход на серверы (см. SSH Secrets Engine) |
| **Code Signing** | Подписание кода | Подписание артефактов, Docker images |

## Практические сценарии

### Сценарий 1: Установка Root CA и Intermediate CA

#### Шаг 1: Включение PKI Secrets Engine

```bash
vault secrets enable pki
vault secrets tune -max-lease-duration=87600h pki
```

`max-lease-duration=87600h` (10 лет) — стандартный срок для root CA.

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
# Включение промежуточного CA (на отдельном mount point)
vault secrets enable -path=pki_int pki
vault secrets tune -max-lease-duration=8760h pki_int

# Генерация CSR для intermediate CA
vault write pki_int/intermediate/generate/internal \
    common_name="Example Intermediate CA" \
    organization="Example Corp" \
    country="US" \
    ttl=8760h \
    key_type=rsa \
    key_bits=4096

# Подпись CSR корневым CA
vault write pki/root/sign-intermediate \
    csr=@/path/to/intermediate.csr \
    common_name="Example Intermediate CA" \
    organization="Example Corp" \
    country="US" \
    ttl=8760h

# Импорт подписанного сертификата
vault write pki_int/intermediate/set-signed \
    certificate=@/path/to/intermediate.crt
```

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

Vault может выступать как ACME-сервер для автоматической выдачи сертификатов:

```bash
# Включение ACME endpoint
vault write pki/config/acme enabled=true
```

Использование с cert-manager:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: vault-issuer
spec:
  vault:
    server: https://vault.example.com:8200
    path: pki_int/sign/example-dot-com
    auth:
      kubernetes:
        role: cert-manager-role
        serviceAccountName: cert-manager
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
```

### Сценарий 5: CRL и OCSP

#### Настройка CRL

```bash
# Включение CRL
vault write pki/config/crl \
    enabled=true \
    expiry=72h

# Проверка CRL endpoint
curl https://vault.example.com:8200/v1/pki/crl
# → -----BEGIN X509 CRL-----
```

#### Настройка OCSP

```bash
# Включение OCSP
vault write pki/config/ocsp \
    enabled=true \
    expiry=1h

# OCSP endpoint
curl https://vault.example.com:8200/v1/pki/ocsp
# → HTTP/1.0 200 OK
```

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

### Сценарий 8: Отзыв сертификата

```bash
# Просмотр выданных сертификатов (по serial number)
vault list pki_int/revoked

# Отзыв сертификата
vault write pki_int/revoke \
    serial_number=1a2b3c4d \
    reason="key compromise"

# Проверка CRL
curl https://vault.example.com:8200/v1/pki/crl | openssl crl -text -noout
```

## Лучшие практики

1. **Иерархия CA:** Используйте root CA (офлайн) + intermediate CA (онлайн). Никогда не выписывайте сертификаты напрямую от root CA.
2. **Короткий TTL:** Настраивайте TTL сертификатов минимально необходимым (24–72 часа для production).
3. **CRL/OCSP:** Включите CRL или OCSP для возможности отзыва скомпрометированных сертификатов.
4. **ACME:** Используйте ACME протокол для автоматизации выдачи сертификатов (cert-manager, Traefik).
5. **Key type:** Используйте RSA 2048+ или ECDSA P-256/P-384. Избегайте RSA 1024.
6. **Rotation:** Планируйте ротацию intermediate CA раз в 1–2 года.
7. **Audit:** Включите audit device для отслеживания всех операций выдачи сертификатов.
8. **Backup:** Регулярно бэкапируйте root CA (offline backup).

## Ограничения и известные проблемы

- **Root CA:** Потеря root CA означает невозможность выдачи новых сертификатов. Храните root CA в HSM или air-gapped машине.
- **CRL размер:** При большом количестве отозванных сертификатов CRL может стать очень большой. Используйте Delta CRL.
- **OCSP stapling:** Некоторые серверы (Nginx, Apache) требуют настройки OCSP stapling для производительности.
- **ACMEPath:** ACME endpoint требует HTTPS. Убедитесь, что TLS настроен корректно.
- **CSR validation:** Vault не валидирует CSR полностью. Убедитесь, что клиенты генерируют корректные CSR.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[SSH Secrets Engine](./ssh_secrets_engine.md)** — SSH-сертификаты через Vault.
*   **[Transit Engine — Политики](./transit-encryption-policies.md)** — шифрование как сервис.
*   **[Zero Trust](../zero_trust.md)** — роль PKI в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему статические сертификаты — антипаттерн.
*   [Официальная документация PKI Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/pki)
