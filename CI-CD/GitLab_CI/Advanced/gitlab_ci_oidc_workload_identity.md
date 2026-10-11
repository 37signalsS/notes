# OIDC и Workload Identity в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

**OIDC (OpenID Connect)** — расширение протокола OAuth 2.0, предоставляющее идентификационные данные (ID Token) в формате JWT. Используется для аутентификации без передачи секретов.

**Workload Identity Federation** — модель Zero Trust, при которой рабочая нагрузка (раннер, pod, service account) получает краткоживущий токен (JWT), привязанный к её identity. Внешний провайдер (Vault, Consul, внутренний API) проверяет токен и выдаёт временные credentials.

**ID Token** — краткоживущий JWT, содержащий claims о identity workloads. В GitLab CI генерируется через блок `id_tokens` в `.gitlab-ci.yml`. Срок действия равен таймауту задачи или 5 минутам при отсутствии таймаута.

**`id_tokens`** — нативный механизм GitLab (стандарт с 15.7+), заменивший устаревший `CI_JOB_JWT`. Позволяет генерировать токены с настраиваемой аудиторией (`aud`).

**instance_oidc_token** — глобальная настройка GitLab Server, включающая генерацию OIDC токенов для CI jobs. Доступна с GitLab 17.0+.

**workload_oidc_token** — настройка на уровне проекта/группы, включающая workload identity для CI jobs. Доступна с GitLab 17.0+.

**Fulcio** — корневой CA сертификат Sigstore. Выдаёт сертификаты, привязанные к identity (email, GitLab runner, workload identity).

**Rekor** — transparency log Sigstore. Записывает все подписи для аудита и верификации.

**Vault JWT auth** — метод аутентификации в Vault через JWT токен. Поддерживает GitLab CI JWT, Kubernetes service account JWT.

**Consul JWT Auth Method** — универсальный метод headless-аутентификации в Consul с использованием любых подписанных JWT-токенов. Часто используется для интеграции с CI/CD.

**Bound Claims** — набор ограничений в роли внешнего провайдера (Vault, Consul), гарантирующий, что токен будет принят только от конкретного проекта или ветки GitLab.

## Основные концепции

### Архитектура Workload Identity в GitLab CI/CD

```
GitLab CI Job
  ├── id_tokens (short-lived, GitLab-issued JWT)
  │   ├── Vault JWT auth (self-hosted)
  │   ├── Consul JWT auth (self-hosted)
  │   ├── Internal REST API (self-hosted)
  │   ├── Database credential broker (Vault + self-hosted DB)
  │   ├── Message queue auth (Vault + self-hosted Kafka/RabbitMQ)
  │   └── Kubernetes service account token exchange (self-hosted K8s)
  └── Temporary credentials (job timeout или 5 минут)
```

### Сравнение методов аутентификации в GitLab CI/CD

| Метод | Токен | Время жизни | Секреты в CI | Сложность | Рекомендация |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CI_JOB_TOKEN** | Встроенный | Job lifetime | Нет | Низкая | Для GitLab-internal операций |
| **Project Access Token** | PAT | До отзыва | Да (в переменных) | Низкая | Для внешних API |
| **Deploy Token** | PAT | До отзыва | Да (в переменных) | Низкая | Для registry |
| **OIDC / Workload Identity** | JWT | Job timeout / 5 мин | Нет | Средняя | Для Vault, Consul, внутренних сервисов |
| **SSH ключ** | Private key | До отзыва | Да (в переменных) | Средняя | Для legacy систем |

### OIDC flow в GitLab CI/CD

```
1. GitLab Server подготавливает JWT (id_tokens)
   ├── iss: https://gitlab.example.com
   ├── sub: project_path:mygroup/myproject:ref_type:branch:ref:main
   ├── aud: https://vault.example.com (или другой провайдер)
   ├── exp: now + job timeout / 5 минут
   └── nbf: now

2. CI Job использует JWT для запроса credentials
   ├── Vault: JWT auth method
   ├── Consul: JWT auth method
   ├── Internal API: OIDC token introspection
   └── K8s: service account token exchange

3. Внешний провайдер проверяет JWT
   ├── Проверка подписи (GitLab public key via JWKS)
   ├── Проверка claims (sub, aud, exp, bound claims)
   └── Выдача временных credentials

4. CI Job использует временные credentials
   ├── Vault: dynamic secret
   ├── Consul: ACL token
   ├── Internal API: bearer token
   └── K8s: service account token
```

### Claims в GitLab CI JWT

| Claim | Значение | Пример |
| :--- | :--- | :--- |
| `iss` | Issuer | `https://gitlab.example.com` |
| `sub` | Subject | `project_path:mygroup/myproject:ref_type:branch:ref:main` |
| `aud` | Audience | `https://vault.example.com` |
| `exp` | Expiration | `now + job timeout / 5 мин` |
| `iat` | Issued At | `1700000000` |
| `nbf` | Not Before | `1700000000` |
| `jti` | JWT ID | `unique-id` |
| `namespace_id` | GitLab namespace | `12345` |
| `namespace_path` | GitLab namespace path | `mygroup` |
| `project_id` | GitLab project | `67890` |
| `project_path` | GitLab project path | `mygroup/myproject` |
| `user_id` | GitLab user | `11111` |
| `user_login` | GitLab username | `deploy-bot` |
| `user_email` | GitLab user email | `deploy@example.com` |
| `user_access_level` | Access level (16.9+) | `30` |
| `pipeline_id` | Pipeline ID | `22222` |
| `pipeline_source` | Pipeline source | `push` |
| `job_id` | Job ID | `33333` |
| `ref` | Git ref | `main` |
| `ref_type` | Ref type | `branch` |
| `ref_protected` | Protected flag | `true` |
| `environment` | Environment name | `production` |
| `environment_protected` | Environment protected | `true` |
| `deployment_tier` | Deployment tier (15.2+) | `production` |

## Предварительные требования

**Инфраструктура:**
- GitLab 17.0+ (self-managed или GitLab.com)
- GitLab Runner с поддержкой `id_tokens`
- Внешний провайдер: Vault 1.15+, Consul 1.19+, внутренний API с OIDC support, Kubernetes 1.27+
- TLS-сертификаты для всех endpoints (GitLab, Vault, Consul, внутренние сервисы)

**Переменные CI/CD:**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `VAULT_ADDR` | Variable | URL Vault сервера |
| `VAULT_AUTH_ROLE` | Variable | Имя роли JWT-аутентификации в Vault |
| `CONSUL_HTTP_ADDR` | Variable | URL Consul сервера |
| `CONSUL_AUTH_ROLE` | Variable | Имя роли JWT в Consul |

**Базовые знания:**
- GitLab CI/CD: stages, variables, `id_tokens`, `secrets`
- OIDC/JWT: структура токена, claims, подпись RS256
- HashiCorp Vault: политики, роли, KV v2
- Consul: ACL, роли, политики
- Kubernetes: ServiceAccount, RBAC, токены

## Практические сценарии

### Сценарий 1: Vault через JWT auth (self-hosted)

**Настройка в Vault (one-time):**
```bash
# Включение JWT auth method
vault auth enable jwt

# Настройка доверия к GitLab JWKS
vault write auth/jwt/config \
  jwks_url="https://gitlab.example.com/-/jwks" \
  bound_issuer="https://gitlab.example.com"

# Создание политики
vault policy write gitlab-app-policy - <<EOF
path "secret/data/projects/my-app/common" { capabilities = ["read"] }
path "secret/data/projects/my-app/production/*" { capabilities = ["read"] }
EOF

# Создание роли с bound claims
vault write auth/jwt/role/gitlab-prod-role \
  role_type="jwt" \
  policies="gitlab-app-policy" \
  token_ttl="15m" \
  bound_claims_type="glob" \
  bound_claims='{
    "namespace_path": "my-org/backend/api-service",
    "ref_protected": "true",
    "ref": "main",
    "environment": "production"
  }' \
  user_claim="user_email"
```

**Интеграция в GitLab CI:**
```yaml
variables:
  VAULT_ADDR: "https://vault.example.com"
  VAULT_AUTH_ROLE: "gitlab-prod-role"

get_secrets:
  stage: .pre
  image: vault:latest
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - |
      export VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=$VAULT_AUTH_ROLE jwt=$VAULT_ID_TOKEN)
      vault kv get -format=json secret/projects/my-app/db_config > secrets.json
  artifacts:
    paths:
      - secrets.json
```

**Валидация:**
```bash
# Проверка роли
vault read auth/jwt/role/gitlab-prod-role

# Проверка токена
vault token lookup $VAULT_TOKEN | jq '.data.policies, .data.lease_duration'

# Проверка access к секрету
vault kv get secret/projects/my-app/db_config
```

Для детального развёртывания Vault в Kubernetes, настройки Vault Secrets Operator (VSO) и интеграции с GitLab Runner см. **[Интеграция GitLab CI и HashiCorp Vault в Kubernetes](../Tutorials/vault_kubernetes_integration.md)**.

### Сценарий 2: Consul через JWT auth (self-hosted)

**Настройка в Consul (one-time):**
```bash
# Включение JWT auth method
consul acl auth-method create -type jwt -name gitlab-ci \
  -description "GitLab CI JWT auth" \
  -config '{
    "JWKSURL": "https://gitlab.example.com/-/jwks",
    "BoundIssuer": "https://gitlab.example.com",
    "ClaimMappings": {
      "namespace_path": "consul_namespace",
      "project_path": "consul_service"
    }
  }' \
  -token "<MANAGEMENT_TOKEN>"

# Создание роли
consul acl role create -name gitlab-ci-role -description "GitLab CI role" \
  -policy-name "service-write" \
  -auth-method gitlab-ci \
  -binding-rule 'Value.project_path == "mygroup/myproject" && Value.ref == "main"' \
  -token "<MANAGEMENT_TOKEN>"
```

**Интеграция в GitLab CI:**
```yaml
variables:
  CONSUL_HTTP_ADDR: "https://consul.example.com:8500"
  CONSUL_AUTH_METHOD: "gitlab-ci"
  CONSUL_AUTH_ROLE: "gitlab-ci-role"

register_service:
  stage: deploy
  image: consul:latest
  id_tokens:
    CONSUL_JWT:
      aud: https://consul.example.com
  script:
    - |
      # Аутентификация через JWT
      CONSUL_TOKEN=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"auth_method\":\"$CONSUL_AUTH_METHOD\",\"bearer_token\":\"$CONSUL_JWT\",\"meta\":{\"pipeline\":\"$CI_PIPELINE_ID\"}}" \
        "$CONSUL_HTTP_ADDR/v1/acl/login" | jq -r '.SecretID')

      # Регистрация сервиса
      curl -X PUT "$CONSUL_HTTP_ADDR/v1/agent/service/register" \
        -H "X-Consul-Token: $CONSUL_TOKEN" \
        -d '{
          "Name": "myapp",
          "Port": 8080,
          "Check": {
            "HTTP": "http://localhost:8080/health",
            "Interval": "10s"
          }
        }'
```

**Валидация:**
```bash
# Проверка auth method
consul acl auth-method read -name gitlab-ci -token "<MANAGEMENT_TOKEN>"

# Проверка роли
consul acl role read -name gitlab-ci-role -token "<MANAGEMENT_TOKEN>"

# Проверка токена
consul acl token read -self -token "<SECRET_ID>"
```

### Сценарий 3: Внутренний REST API (self-hosted)

**Настройка на стороне внутреннего API (one-time):**
```python
# Пример middleware для FastAPI (Python)
from fastapi import FastAPI, Request
from jose import jwt, JWTError
import requests

app = FastAPI()
GITLAB_JWKS_URL = "https://gitlab.example.com/-/jwks"
JWKS = requests.get(GITLAB_JWKS_URL).json()

@app.middleware("http")
async def oidc_auth(request: Request, call_next):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return Response(status_code=401)
    
    token = auth_header.replace("Bearer ", "")
    try:
        payload = jwt.decode(
            token,
            JWKS,
            algorithms=["RS256"],
            issuer="https://gitlab.example.com",
            audience="https://internal-api.example.com"
        )
        request.state.identity = payload
    except JWTError:
        return Response(status_code=401)
    
    return await call_next(request)
```

**Интеграция в GitLab CI:**
```yaml
variables:
  INTERNAL_API_URL: "https://internal-api.example.com"

deploy_config:
  stage: deploy
  image: alpine/curl:latest
  id_tokens:
    API_ID_TOKEN:
      aud: https://internal-api.example.com
  script:
    - |
      curl -X POST "$INTERNAL_API_URL/v1/deploy" \
        -H "Authorization: Bearer $API_ID_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"service": "myapp", "version": "$CI_COMMIT_SHA"}'
```

**Валидация:**
```bash
# Декодирование токена для отладки
echo $API_ID_TOKEN | cut -d. -f2 | base64 -d | jq .

# Проверка токена через API
curl -H "Authorization: Bearer $API_ID_TOKEN" \
  "$INTERNAL_API_URL/v1/health"
```

### Сценарий 4: База данных через Vault (self-hosted)

**Настройка в Vault (one-time):**
```bash
# Включение database secrets engine
vault secrets enable database

# Настройка PostgreSQL connection
vault write database/config/my-postgres \
  plugin_name=postgresql-database-plugin \
  allowed_roles="myapp-role" \
  connection_url="postgresql://{{username}}:{{password}}@db.example.com:5432/myapp" \
  username="vault-admin" \
  password="vault-admin-password"

# Создание роли
vault write database/roles/myapp-role \
  db_name=my-postgres \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}';" \
  default_ttl="1h" \
  max_ttl="24h"
```

**Интеграция в GitLab CI:**
```yaml
variables:
  VAULT_ADDR: "https://vault.example.com"
  VAULT_AUTH_ROLE: "gitlab-db-role"

get_db_credentials:
  stage: .pre
  image: vault:latest
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - |
      export VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=$VAULT_AUTH_ROLE jwt=$VAULT_ID_TOKEN)
      
      # Получение dynamic credentials
      CREDS=$(vault read database/creds/myapp-role -format=json)
      export DB_USER=$(echo $CREDS | jq -r '.data.username')
      export DB_PASS=$(echo $CREDS | jq -r '.data.password')
      
      # Использование
      psql "postgresql://$DB_USER:$DB_PASS@db.example.com:5432/myapp" \
        -c "SELECT 1;"
```

**Валидация:**
```bash
# Проверка credentials
vault read database/creds/myapp-role

# Проверка leases
vault lease lookup database/creds/myapp-role/<lease_id>
```

### Сценарий 5: Message Queue через Vault (self-hosted)

**Настройка в Vault (one-time):**
```bash
# Включение RabbitMQ secrets engine
vault secrets enable rabbitmq

# Настройка connection
vault write rabbitmq/config/connection \
  connection_uri="https://rabbitmq.example.com:15671/api/" \
  username="vault-admin" \
  password="vault-admin-password"

# Создание role
vault write rabbitmq/roles/myapp-role \
  vhosts="myapp-vhost" \
  queues="myapp-queue" \
  configure_glob="myapp-.*" \
  write_glob="myapp-.*" \
  read_glob="myapp-.*"
```

**Интеграция в GitLab CI:**
```yaml
variables:
  VAULT_ADDR: "https://vault.example.com"
  VAULT_AUTH_ROLE: "gitlab-mq-role"

get_mq_credentials:
  stage: .pre
  image: vault:latest
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - |
      export VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=$VAULT_AUTH_ROLE jwt=$VAULT_ID_TOKEN)
      
      # Получение credentials
      CREDS=$(vault read rabbitmq/creds/myapp-role -format=json)
      export MQ_USER=$(echo $CREDS | jq -r '.data.username')
      export MQ_PASS=$(echo $CREDS | jq -r '.data.password')
      
      # Использование
      curl -u "$MQ_USER:$MQ_PASS" \
        "https://rabbitmq.example.com:15671/api/queues/myapp-vhost"
```

### Сценарий 6: Kubernetes service account + GitLab OIDC (self-hosted)

**Настройка ServiceAccount:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: gitlab-ci-sa
  namespace: gitlab-ci
  annotations:
    workload.identity/gitlab.com/subject: "project_path:mygroup/myproject:ref_type:branch:ref:main"
    workload.identity/gitlab.com/audience: "https://gitlab.example.com"
```

**Интеграция в GitLab CI:**
```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  id_tokens:
    K8S_SA_TOKEN:
      aud: https://gitlab.example.com
  script:
    - |
      # Exchange JWT на service account token
      kubectl apply -f k8s/
  kubernetes:
    namespace: gitlab-ci
    service_account: gitlab-ci-sa
```

### Сценарий 7: Подпись образов через OIDC (Cosign keyless)

```yaml
variables:
  COSIGN_EXPERIMENTAL: "1"

sign_image:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v2.4.0
  id_tokens:
    COSIGN_ID_TOKEN:
      aud: https://fulcio.sigstore.dev
  script:
    - |
      # Keyless подпись через GitLab OIDC
      cosign sign --yes \
        --certificate-identity-regexp '^https://gitlab\.example.com/org/.*$' \
        --certificate-oidc-issuer https://gitlab.example.com \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: always
```

## Валидация и проверка

### Проверка ID Token

```bash
# Декодирование payload
echo $VAULT_ID_TOKEN | cut -d. -f2 | base64 -d | jq .

# Проверка подписи через JWKS
curl -s "$GITLAB_URL/-/jwks" | jq '.'

# Проверка срока действия
echo $VAULT_ID_TOKEN | cut -d. -f2 | base64 -d | jq '.exp, .iat'
```

### Проверка Vault JWT auth

```bash
# Проверка конфигурации
vault read auth/jwt/config

# Проверка роли
vault read auth/jwt/role/gitlab-prod-role

# Проверка токена
vault token lookup $VAULT_TOKEN | jq '.data.policies, .data.lease_duration'

# Проверка access
vault kv get secret/projects/my-app/db_config
```

### Проверка Consul JWT auth

```bash
# Проверка auth method
consul acl auth-method read -name gitlab-ci -token "<MANAGEMENT_TOKEN>"

# Проверка роли
consul acl role read -name gitlab-ci-role -token "<MANAGEMENT_TOKEN>"

# Проверка токена
consul acl token read -self -token "<SECRET_ID>"
```

### Проверка GitLab Runner

```bash
# Проверка конфигурации Runner
gitlab-runner verify

# Проверка поддержки id_tokens
gitlab-runner list

# Проверка логов Runner
gitlab-runner run --debug
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` от Vault/Consul | JWT не прошёл валидацию | Проверьте `iss`, `sub`, `aud` claims и `bound_claims` |
| `JWT expired` | `exp` < текущее время | Увеличьте таймаут задачи или ускорьте pipeline |
| `Vault: permission denied` | JWT не имеет нужных claims | Проверьте `bound_claims` в Vault role |
| `Consul: permission denied` | Несоответствие binding rule | Проверьте `binding-rule` в Consul role |
| `Token audience mismatch` | `aud` не совпадает | Значение `aud` в `.gitlab-ci.yml` должно совпадать с провайдером |
| `JWKS fetch failed` | Vault/Consul не видит GitLab | Проверьте DNS, firewall, self-signed сертификаты |
| `Cosign: certificate not found` | Fulcio недоступен | Проверьте `COSIGN_EXPERIMENTAL=1` и GitLab OIDK конфигурацию |
| `Kubernetes: token exchange failed` | SA не привязана к GitLab OIDC | Проверьте annotations в ServiceAccount |
| `ID token issuance is disabled` | Путь проекта использовался ранее | Обратитесь к администратору GitLab для разблокировки |

## Ограничения и крайние случаи

**Время жизни токена:**
- ID Token истекает через таймаут задачи или 5 минут при отсутствии таймаута
- Для long-running задач (>6 минут) настройте `timeout` в задаче
- Vault/Consul credentials должны запрашиваться внутри той же задачи, где используется токен

**Bound Claims и масштабирование:**
- При >100 проектов используйте `bound_claims_type="glob"` для масок
- Для мульти-Tenant GitLab настройте разные `bound_issuer` в разных ролях
- `ref_protected` доступен только для защищённых веток/тегов

**Self-hosted GitLab:**
- При использовании self-signed сертификатов добавьте CA в доверенное хранилище Vault/Consul
- JWKS endpoint: `https://gitlab.example.com/-/jwks`
- Если сетевой доступ невозможен, используйте статический `jwt_validation_pubkeys` (требует ручной ротации)

**Vault:**
- Batch tokens не записываются на диск — используйте для high-load сред
- Ротация ключей GitLab происходит автоматически каждые 90 дней
- Для CI/CD задач используйте `token_ttl` не более 30 минут

**Consul:**
- OIDC Auth Method доступен только в Enterprise версии
- JWT Auth Method работает в Community Edition
- Bound claims в Consul используют glob-маски, а не exact match

## Лучшие практики

### Безопасность

1. **Используйте `id_tokens` вместо `CI_JOB_JWT`:** `CI_JOB_JWT` удалён в GitLab 18.0.
2. **Ограничьте scope JWT:** Настройте `aud` и `bound_claims` на минимально необходимые.
3. **Используйте short-lived credentials:** TTL 15-30 минут максимум для CI/CD задач.
4. **Включите аудит:** Включите audit logging в Vault/Consul для трассируемости.
5. **Ротируйте ключи:** Регулярная ротация ключей JWKS (автоматически каждые 90 дней).
6. **Least Privilege:** Назначайте минимум прав на уровне bound claims и политик.

### Эксплуатация (DevOps/SRE)

1. **Мониторьте OIDC failures:** Алерты на 401/403 от внешних провайдеров.
2. **Мониторьте Vault/Consul метрики:** Доступность API, latency, количество активных токенов.
3. **Настройте SLO:** Доступность Vault/Consul API (например, 99.9% uptime).
4. **Кэшируйте секреты:** На стороне приложения, но не дольше TTL токена.
5. **Используйте batch tokens:** Для high-load сред CI/CD.
6. **Тестируйте в staging:** Перед использованием в production протестируйте OIDC flow.
7. **Версионируйте политики:** Храните IAM/Vault/Consul политики в Git.

### Sysadmin

1. **Включите `workload_oidc_token` на уровне группы:** Централизованное управление.
2. **Настройте network policies:** Ограничьте доступ к Vault/Consul/JWKS только из CI/CD сетей.
3. **Настройте TLS:** Все endpoints (GitLab, Vault, Consul, внутренние сервисы) должны использовать валидные TLS-сертификаты.
4. **Резервное копирование:** Регулярное резервное копирование Vault (Raft snapshot) и Consul (snapshot).
5. **Аудит JWT usage:** Логи всех аутентификаций через OIDC.
6. **Мониторьте transparency log:** Проверяйте Rekor на аномалии (при использовании Cosign).

### Разработка (Dev)

1. **Используйте OIDC вместо статических секретов:** Без секретов, проще в эксплуатации.
2. **Тестируйте в feature branches:** Используйте `ref_protected: "false"` для тестовых сред.
3. **Используйте `spec:inputs` для конфигурации:** Типизированные параметры для OIDC конфигурации.

## Очистка и откат

### Отзыв Vault токенов

```bash
# Отзыв конкретного токена по accessor
vault token revoke -accessor <token_accessor>

# Отзыв всех токенов роли
vault write -f auth/jwt/role/<role>/token/revoke

# Полная очистка сессий
vault token revoke -accessor $(vault token lookup -format=json | jq -r '.data.accessor')
```

### Удаление Consul роли

```bash
# Удаление роли
consul acl role delete -name gitlab-ci-role -token "<MANAGEMENT_TOKEN>"

# Отключение auth method
consul acl auth-method delete -name gitlab-ci -token "<MANAGEMENT_TOKEN>"
```

### Очистка GitLab CI/CD

```bash
# Удаление переменных через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables/VAULT_ADDR"

# Удаление секретов из Vault
vault kv delete -versions=0 secret/projects/<project-path>/
```

## Дополнительная информация

### Связанные файлы

- **[Переменные и секреты GitLab CI/CD](../Concepts/gitlab_ci_variables_secrets.md)** — управление переменными, OIDC, `id_tokens`
- **[Интеграция GitLab CI и HashiCorp Vault в Kubernetes](../Tutorials/vault_kubernetes_integration.md)** — детальное руководство по Vault + K8s + OIDC
- **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — методология управления секретами
- **[Система управления доступом Consul](../Consul/consul_acl.md)** — Consul ACL, JWT Auth Method
- **[Zero Trust Architecture в Vault](../../../Vault/zero_trust.md)** — принципы Zero Trust
- **[CI_JOB_TOKEN Security](../Advanced/ci_job_token_security.md)** — безопасность токенов в GitLab CI
- **[SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md)** — Cosign, Sigstore
- **[Resource Group и контроль пайплайнов](../Advanced/resource_group_and_pipeline_control.md)** — управление параллелизмом

### Внешние ресурсы

- [GitLab: OpenID Connect (OIDC) Authentication Using ID Tokens](https://docs.gitlab.com/ee/ci/secrets/id_token_authentication.html)
- [GitLab: Connect to cloud services](https://docs.gitlab.com/ee/ci/cloud_services/index.html)
- [HashiCorp Vault: JWT Auth Method](https://developer.hashicorp.com/vault/docs/auth/jwt)
- [HashiCorp Consul: JWT Auth Method](https://developer.hashicorp.com/consul/docs/security/acl/auth-methods)
- [Sigstore: Cosign](https://docs.sigstore.dev/cosign/overview/)
