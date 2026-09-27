# Cert-manager: Интеграция с HashiCorp Vault PKI

## Определения

**Vault PKI Secrets Engine** — плагин HashiCorp Vault, превращающий его в полноценный центр сертификации (CA). Позволяет настроить иерархию Root CA → Intermediate CA → Leaf Certificates с автоматическим выпуском и отзывом сертификатов.

**Vault Issuer** — тип Issuer в cert-manager, интегрированный с Vault PKI. Использует HTTP API Vault для выпуска сертификатов через протоколы SSH и X.509. Требует настройки аутентификации (Kubernetes Auth, AppRole, Token).

**Vault Kubernetes Auth** — метод аутентификации Vault, позволяющий подам Kubernetes (ServiceAccount) получать токены Vault без хранения секретов. Рекомендуется для production-сред.

**Vault PKI مرحله (Intermediate CA)** — схема, при которой Vault issuing CA подписан внешним Root CA (или наоборот). Позволяет интегрировать Vault в существующую PKI-инфраструктуру.

**Lease и Renewal** — механизм Vault для автоматического обновления токенов и сертификатов. cert-manager поддерживает автоматическое продление через Vault Lease API.

---

## Основные концепции

### Архитектура интеграции

```text
┌─────────────────────────────────────────────────┐
│                   Kubernetes                    │
│                                                 │
│  ┌─────────────┐      ┌──────────────────────┐  │
│  │ cert-manager│──────│ Vault Issuer         │  │
│  │ (controller)│      │ (Vault PKI Backend)  │  │
│  └──────┬──────┘      └──────────┬───────────┘  │
│         │                        │               │
│         ▼                        ▼               │
│  ┌─────────────┐      ┌──────────────────────┐  │
│  │ Certificate │      │ Kubernetes Auth      │  │
│  │ (CRD)       │      │ (ServiceAccount)     │  │
│  └─────────────┘      └──────────────────────┘  │
└────────────────────────────┬────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   HashiCorp Vault    │
                  │                      │
                  │  ┌────────────────┐  │
                  │  │ PKI Secrets    │  │
                  │  │ Engine         │  │
                  │  └────────────────┘  │
                  │                      │
                  │  ┌────────────────┐  │
                  │  │ Root CA        │  │
                  │  │ Intermediate CA│  │
                  │  └────────────────┘  │
                  └──────────────────────┘
```

### Методы аутентификации Vault

| Метод | Безопасность | Сложность | Применение |
| :--- | :--- | :--- | :--- |
| **Kubernetes Auth** | Высокий | Средняя | Production (рекомендуется) |
| **AppRole** | Средний | Низкая | CI/CD, внешние системы |
| **Token** | Низкий | Минимальная | Только dev/test |
| **JWT/OIDC** | Высокий | Высокая | Enterprise, SSO |

### Ключевые параметры Vault PKI

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `max_ttl` | Максимальный срок жизни сертификата | Root CA: 10 лет, Intermediate: 1 год |
| `ttl` | Срок жизни по умолчанию | Сервисы: 30 дней |
| `key_bits` | Размер ключа | ECDSA P-256 или Ed25519 |
| `key_type` | Тип ключа | `ec` (ECDSA) или `ed25519` |
| `allowed_domains` | Разрешенные домены | Ограничьте scope для безопасности |
| `allow_subdomains` | Разрешение поддоменов | `true` для внутренних сервисов |
| `allow_bare_domains` | Разрешение bare domains | `false` для предотвращения злоупотреблений |

---

## Практические сценарии

### Сценарий 1: Настройка Vault PKI Secrets Engine

#### Шаг 1: Включение PKI Secrets Engine

```bash
# Включение корневого PKI
vault secrets enable pki

# Настройка maxlength для корня (по умолчанию 72h)
vault secrets tune -max-lease-ttl=87600h pki

# Генерация корневого CA
vault write pki/root/generate/internal \
  common_name="Example Root CA" \
  ttl=87600h \
  key_bits=256 \
  key_type=ec

# Настройка URL для отзывов
vault write pki/config/urls \
  issuing_certificates="http://vault.example.com:8200/v1/pki/ca" \
  crl_distribution_points="http://vault.example.com:8200/v1/pki/crl"
```

#### Шаг 2: Создание Intermediate CA

```bash
# Включение промежуточного PKI
vault secrets enable -path=pki_int pki

# Настройка maxlength
vault secrets tune -max-lease-ttl=43800h pki_int

# Генерация CSR для промежуточного CA
vault write pki_int/intermediate/generate/internal \
  common_name="Example Intermediate CA" \
  key_bits=256 \
  key_type=ec

# Подпись промежуточного CA корневым CA
vault write pki/root/sign-intermediate \
  csr=@pki_int.csr \
  format=pem_bundle \
  ttl=43800h

# Сохранение подписанного сертификата
vault write pki_int/intermediate/set-signed \
  certificate=@signed_certificate.pem
```

#### Шаг 3: Создание Role для cert-manager

```bash
# Role для Ingress-сертификатов (публичные домены)
vault write pki_int/roles/ingress-cert \
  allowed_domains="example.com,example.org" \
  allow_subdomains=true \
  allow_bare_domains=false \
  max_ttl=720h \
  key_bits=256 \
  key_type=ec \
  key_usage="DigitalSignature,KeyEncipherment" \
  ext_key_usage="ServerAuth" \
  no_store=false

# Role для внутренних mTLS-сертификатов
vault write pki_int/roles/internal-mtls \
  allowed_domains="svc.cluster.local" \
  allow_subdomains=true \
  allow_bare_domains=false \
  max_ttl=720h \
  key_bits=256 \
  key_type=ed25519 \
  key_usage="DigitalSignature,KeyEncipherment" \
  ext_key_usage="ServerAuth,ClientAuth" \
  no_store=false

# Role для CA-сертификатов (isCA: true)
vault write pki_int/roles/ca-cert \
  allowed_domains="internal.ca" \
  allow_subdomains=true \
  max_ttl=8760h \
  key_bits=384 \
  key_type=ec \
  key_usage="CertSign,CRLSign" \
  ext_key_usage="" \
  no_store=false
```

### Сценарий 2: Настройка Kubernetes Auth в Vault

#### Шаг 1: Включение Kubernetes Auth

```bash
# Включение метода аутентификации
vault auth enable kubernetes

# Настройкаubernetes Auth
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc" \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt \
  token_reviewer_jwt=@/var/run/secrets/kubernetes.io/serviceaccount/token
```

#### Шаг 2: Создание Policy для cert-manager

```bash
# Policy для выпуска Ingress-сертификатов
vault policy write cert-manager-ingress - <<EOF
path "pki_int/issue/ingress-cert" {
  capabilities = ["create", "update"]
}
path "pki_int/revoke" {
  capabilities = ["create", "update"]
}
path "pki_int/cert/ca" {
  capabilities = ["read"]
}
EOF

# Policy для выпуска внутренних mTLS-сертификатов
vault policy write cert-manager-internal - <<EOF
path "pki_int/issue/internal-mtls" {
  capabilities = ["create", "update"]
}
path "pki_int/revoke" {
  capabilities = ["create", "update"]
}
path "pki_int/cert/ca" {
  capabilities = ["read"]
}
EOF
```

#### Шаг 3: Привязка Policy к ServiceAccount

```bash
# Создание role в Vault
vault write auth/kubernetes/role/cert-manager \
  bound_service_account_names=cert-manager \
  bound_service_account_namespaces=cert-manager \
  policies=cert-manager-ingress,cert-manager-internal \
  ttl=1h
```

### Сценарий 3: Vault Issuer для cert-manager

#### ClusterIssuer для публичных доменов

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: vault-issuer
spec:
  vault:
    path: pki_int/issue/ingress-cert
    server: https://vault.example.com:8200
    auth:
      kubernetes:
        role: cert-manager
        mountPath: /v1/auth/kubernetes
        serviceAccountRef:
          name: cert-manager
    # CA bundle Vault (если используется самоподписанный CA)
    caBundle: |
      -----BEGIN CERTIFICATE-----
      MIID...
      -----END CERTIFICATE-----
```

#### Issuer для внутренних mTLS (в namespace приложения)

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: vault-internal-issuer
  namespace: production
spec:
  vault:
    path: pki_int/issue/internal-mtls
    server: https://vault.example.com:8200
    auth:
      kubernetes:
        role: cert-manager-internal
        mountPath: /v1/auth/kubernetes
        serviceAccountRef:
          name: cert-manager
```

### Сценарий 4: Ingress с Vault Issuer

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: vault-secured-app
  annotations:
    cert-manager.io/cluster-issuer: "vault-issuer"
    cert-manager.io/private-key-algorithm: "ECDSA"
    cert-manager.io/private-key-rotation-policy: "Always"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-vault-tls
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

### Сценарий 5: Certificate с явным Vault Issuer (без ingress-shim)

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-service-cert
  namespace: production
spec:
  secretName: internal-service-tls
  issuerRef:
    name: vault-internal-issuer
    kind: Issuer
  commonName: internal-service.production.svc.cluster.local
  dnsNames:
  - internal-service
  - internal-service.production
  - internal-service.production.svc
  - internal-service.production.svc.cluster.local
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  duration: 720h    # 30 дней
  renewBefore: 168h # 7 дней
  usages:
  - server auth
  - client auth
```

---

## Дополнительная информация

### Диагностика интеграции Vault + cert-manager

```bash
# 1. Проверка доступности Vault
vault status

# 2. Проверка Policy cert-manager
vault policy read cert-manager-ingress

# 3. Проверка Role в Vault
vault read auth/kubernetes/role/cert-manager

# 4. Проверка доступности PKI endpoint
vault read pki_int/roles/ingress-cert

# 5. Тестовый выпуск сертификата
vault write pki_int/issue/ingress-cert \
  common_name=test.example.com \
  ttl=1h

# 6. Проверка статуса cert-manager
kubectl get certificate -n production
cmctl status certificate <name> -n production

# 7. Просмотр логов cert-manager (Vault API запросы)
kubectl logs -n cert-manager -l app=cert-manager --tail=100 | grep -i vault
```

### Типичные ошибки и решения

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | Неверный role или policy | Проверьте `vault read auth/kubernetes/role/cert-manager` |
| `vault is sealed` | Vault запечатан | Выполните `vault unseal` |
| `certificate not found` | PKI secrets engine не настроен | Проверьте `vault secrets list | grep pki` |
| `invalid token` | Token истек или невалиден | Обновите токен через Kubernetes Auth |
| `permission denied: create` | Policy не разрешает create | Добавьте `capabilities = ["create", "update"]` в policy |

### Best Practices

1. **Kubernetes Auth:** Используйте Kubernetes Auth вместо Token для автоматической аутентификации.
2. **Short-lived certificates:** Устанавливайте короткие TTL (30 дней) для сервисов, длительные для CA.
3. **Rotation Policy:** Включайте `rotationPolicy: Always` для автоматической ротации ключей.
4. **Vault HA:** Разверните Vault в HA-режиме для отказоустойчивости.
5. **Аудит:** Включите audit log в Vault для отслеживания всех запросов на выпуск сертификатов.
6. **Ограничение Role:** Используйте `allowed_domains` для ограничения scope каждой Role.
7. **Backup:** Регулярно бэкапьте Vault storage (не только PKI, но и все secrets).

### Смотрите также

- **[Cert-manager: Приватный CA](../Private_CA/index.md)** — архитектура внутренних CA.
- **[Cert-manager: Операции](../Administration/operations.md)** — мониторинг и алертинг.
- **[Vault: Интеграция с Kubernetes](../../../../Vault/guides/vault_kubernetes_integration.md)** — настройка Vault в Kubernetes.
