# Управление секретами в Traefik: Vault, environment variables, patterns

## Определения

**Vault Provider** — провайдер, читающий секреты из HashiCorp Vault (KV v1/v2) и передающий их в динамическую конфигурацию Traefik.

**Vault PKI** — внутренний PKI-бэкенд Vault, выдающий сертификаты для внутренних сервисов.

**Environment variable injection** — передача секретов через переменные окружения процесса Traefik с использованием Go-шаблонов.

**Docker Secret / K8s Secret** — нативные механизмы секретов Docker Swarm и Kubernetes.

**External secrets operator** — оператор Kubernetes (External Secrets, Vault Operator), синхронизирующий секреты из Vault в K8s Secret.

## Базовые концепции

### Источники секретов для Traefik

Traefik может получать секреты из:
1. **Файловая система** (`usersFile`, `rootCAs`) — права `600`, владелец процесс Traefik.
2. **Docker Secrets / K8s Secrets** — нативные секреты оркестратора.
3. **Vault (KV Provider)** — чтение из Vault KV store.
4. **Vault PKI (cert resolver)** — автоматическая выдача сертификатов от Vault CA.
5. **Environment variables** — через Go-шаблоны в File provider.

### Vault KV Provider

Traefik читает KV-парары из Vault как динамическую конфигурацию. Путь к ключу соответствует структуре конфигурации Traefik.

### Vault PKI как Certificate Resolver

Vault может выступать как ACME-совместимый сервер, выдающий сертификаты для внутренних доменов.

### Безопасность

- Секреты никогда не логируются Traefik.
- Vault token должен иметь минимальные права (read-only на конкретный путь).
- TLS между Traefik и Vault обязателен в production.

## Практические сценарии

### Сценарий 1: Vault KV Provider (BasicAuth из Vault)

```yaml
# static config
providers:
  vault:
    endpoint: "https://vault.example.com:8200"
    rootKey: "traefik"
    token: "s.xxxxx"
    tls:
      ca: /etc/traefik/vault-ca.crt
```

```bash
# В Vault: создание секрета
vault kv put secret/traefik/http/middlewares/admin-auth/basicAuth/users \
  admin:$2y$10$...

# Структура в Vault:
# secret/traefik/http/middlewares/admin-auth/basicAuth/users = "admin:$2y$10$..."
# secret/traefik/http/routers/app/tls/certResolver = "myresolver"
```

### Сценарий 2: Environment variables через Go-шаблоны

```yaml
# /etc/traefik/dynamic/backend.yml (динамический файл)
http:
  middlewares:
    admin-auth:
      basicAuth:
        users:
        - "{{ env "TRAEFIK_ADMIN_HASH" }}"
```

```bash
# systemd unit
[Service]
Environment="TRAEFIK_ADMIN_HASH=$2y$10$..."
```

```yaml
# docker-compose.yml
services:
  traefik:
    environment:
      TRAEFIK_ADMIN_HASH: "${ADMIN_HASH}"
```

### Сценарий 3: Vault PKI как Certificate Resolver

```yaml
# static config
certificatesResolvers:
  vault-pki:
    vault:
      url: "https://vault.example.com:8200"
      auth:
        token: "s.xxxxx"
      role: "traefik-role"
```

```bash
# В Vault: включение PKI secrets engine
vault secrets enable pki
vault secrets tune -max-lease-ttl=8760h pki

# Создание корневого CA
vault pki root-generate -common-name "Vault Root CA" -ttl 8760h

# Создание intermediate CA
vault pki intermediate-generate -common-name "Vault Intermediate CA" -ttl 43800h

# Создание role
vault write pki_int/roles/traefik-role \
  allowed_domains="example.com,*.example.com" \
  allow_subdomains=true \
  max_ttl=720h
```

### Сценарий 4: External Secrets Operator (Kubernetes)

```yaml
# ExternalSecret
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: traefik-admin-auth
  namespace: traefik
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: traefik-admin-auth
    creationPolicy: Owner
  data:
  - secretKey: users
    remoteRef:
      key: traefik
      property: admin-hash
```

```yaml
# Middleware использует K8s Secret
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: admin-auth
  namespace: traefik
spec:
  basicAuth:
    secret: traefik-admin-auth
```

### Сценарий 5: Vault Agent Injector (Kubernetes)

```yaml
# annotations для pod Traefik
spec:
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "traefik-role"
        vault.hashicorp.com/agent-inject-secret-config: "secret/traefik/config"
        vault.hashicorp.com/agent-inject-template-config: |
          {{- with secret "secret/traefik/config" -}}
          {{ .Data.data.config | base64Decode }}
          {{- end }}
```

### Сценарий 6: Rotation токенов Vault

```bash
# Создание нового токена
vault token create -policy=traefik-policy -ttl=24h -renewable

# Обновление токена в Traefik (rolling restart)
kubectl rollout restart deployment/traefik -n traefik
```

## Операции и команды

```bash
# Проверка Vault Provider
kubectl logs -n traefik deployment/traefik | grep -i vault

# Проверка токена Vault
vault token lookup s.xxxxx

# Проверка политики Vault
vault policy read traefik-policy

# Вывод секрета из Vault
vault kv get secret/traefik/http/middlewares/admin-auth/basicAuth/users
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Vault Provider не подключается** | Неверный endpoint, токен истек, TLS | Проверьте endpoint, токен, CA сертификат |
| **Секрет не найден** | Неверный `rootKey`, нет прав на путь | Проверьте rootKey, политику Vault |
| **Токен истек** | TTL токена истек, нет auto-renew | Используйте renewable токены, Vault Agent |
| **BasicAuth не работает** | Secret не найден, формат хеша неверный | Проверьте Secret, htpasswd формат |
| **Certificate resolver не работает** | Vault PKI не настроен, role не существует | Настройте PKI, создайте role |

## Рекомендации

- Никогда не храните токены Vault в коде или Git. Используйте внешние секреты (External Secrets, Vault Operator).
- Права Vault: минимальные, read-only на конкретный `rootKey`.
- TLS между Traefik и Vault обязателен в production.
- Для K8s используйте External Secrets Operator или Vault Agent Injector.
- Ротация токенов: настраивайте TTL и renewable, автоматически обновляйте через rolling restart.
- Файловые секреты (`usersFile`, `rootCAs`) — только для небольших конфигураций или legacy.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — провайдеры конфигурации.
- [Провайдеры KV-хранилищ](./traefik-providers-kv-stores.md) — Consul, etcd, Redis, ZooKeeper.
- [TLS Options и mTLS](./traefik-tls-options.md) — сертификаты и TLS.
- [Middleware для безопасности](./traefik-middlewares-security.md) — BasicAuth, usersFile.
- [Vault Guides](../../Vault/guides/vault_agent/injector.md) — Vault Agent Injector.
- [Cert-manager Vault integration](../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/vault_integration.md) — Vault PKI с cert-manager.
