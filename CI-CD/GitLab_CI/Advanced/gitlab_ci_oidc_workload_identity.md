# OIDC и Workload Identity в GitLab CI/CD

**Актуально для:** GitLab 17.0–19.x (CI_JOB_JWT удалён в 18.0; `id_tokens` — единственный механизм OIDC).

## Определения

**OIDC (OpenID Connect)** — расширение протокола OAuth 2.0, предоставляющее идентификационные данные (ID Token) в формате JWT. Используется для аутентификации без передачи секретов.

**Workload Identity Federation** — модель Zero Trust, при которой рабочая нагрузка (раннер, pod, service account) получает краткоживущий токен (JWT), привязанный к её identity. Внешний провайдер (Vault, Consul, внутренний API) проверяет токен и выдаёт временные credentials.

**ID Token** — краткоживущий JWT, содержащий claims о identity workloads. В GitLab CI генерируется через блок `id_tokens` в `.gitlab-ci.yml`. Срок действия равен таймауту задачи или 5 минутам при отсутствии таймаута.

**`id_tokens`** — нативный механизм GitLab (стандарт с 15.7+), заменивший устаревший `CI_JOB_JWT`. Позволяет генерировать токены с настраиваемой аудиторией (`aud`). Срок действия равен таймауту задачи или 5 минутам при отсутствии таймаута.

**OIDC Token Issuance (instance-level)** — настройка GitLab Server (`Settings → CI/CD → Token Access`), включающая выдачу ID Token для CI jobs на уровне инстанса. Доступна с GitLab 17.0+.

**OIDC Token Issuance (group/project-level)** — настройка `Workload Identity Federation` на уровне группы/проекта (`Settings → CI/CD → Token Access`), управляет выдачей токенов в конкретных областях. Доступна с GitLab 17.0+.

**`ci_id_token_sub_claim_components`** — API-параметр проекта (Projects API), определяющий порядок компонентов в `sub` claim. По умолчанию `["project_path", "ref_type", "ref"]`. Позволяет использовать `project_id` или `job_project_id` вместо `project_path` для защиты от namespace-reclamation атак. Доступна с GitLab 18.4+.

**`Fulcio`** — корневой CA сертификат Sigstore. Выдаёт сертификаты, привязанные к identity (email, GitLab runner, workload identity).

**`Rekor`** — transparency log Sigstore. Записывает все подписи для аудита и верификации.

**Vault JWT auth** — метод аутентификации в Vault через JWT токен (`auth/jwt` или `auth/oidc`). Поддерживает GitLab CI ID Token, Kubernetes service account JWT. Для JWT с `aud` claim требует `bound_audiences` в роли (Vault 1.17+).

**Consul JWT Auth Method** — метод аутентификации в Consul (`-type jwt`), использующий подписанные JWT-токены. Часто используется для headless-аутентификации из CI/CD. Требует отдельной настройки `ClaimMappings` для раскрытия claims и `binding-rule` для привязки к ролям.

**Bound Claims** — набор ограничений в роли внешнего провайдера (Vault, Consul), гарантирующий, что токен будет принят только от конкретного проекта или ветки GitLab.

**Claim** — отдельное поле (атрибут) внутри JWT payload. GitLab передаёт свы­детельствующие данные о проекте, ветке, пользователе, pipeline и runner.

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

| Claim | Когда | Пример |
| :--- | :--- | :--- |
| `iss` | Всегда | `https://gitlab.example.com` |
| `sub` | Всегда (настраивается через Projects API: `ci_id_token_sub_claim_components`) | `project_path:mygroup/myproject:ref_type:branch:ref:main` |
| `aud` | Всегда | `https://vault.example.com` |
| `exp` | Всегда | `now + job timeout / 5 мин` |
| `iat` | Всегда | `1700000000` |
| `nbf` | Всегда | `1700000000` |
| `jti` | Всегда | `235b3a54-b797-45c7-ae9a-f72d7bc6ef5b` |
| `namespace_id` | Всегда | `72` |
| `namespace_path` | Всегда | `mygroup` |
| `project_id` | Всегда | `67890` |
| `project_path` | Всегда | `mygroup/myproject` |
| `job_project_id` | Всегда (18.4+) | `67890` |
| `job_project_path` | Всегда (18.4+) | `mygroup/myproject` |
| `job_namespace_id` | Всегда (18.4+) | `72` |
| `user_id` | Пользователь запустил | `11111` |
| `user_login` | Пользователь запустил | `deploy-bot` |
| `user_email` | Пользователь запустил | `deploy@example.com` |
| `user_access_level` | Пользователь запустил (16.9+) | `30` — Developer |
| `user_identities` | Пользователь запустил | `[{"provider":"github","extern_uid":"2435223452345"}]` |
| `pipeline_id` | Всегда | `22222` |
| `pipeline_source` | Всегда | `push` |
| `job_id` | Всегда | `33333` |
| `job_source` | Всегда | `pipeline` |
| `job_config` | Всегда | `{"url":".../.gitlab-ci.yml@..."}` |
| `ref` | Всегда | `main` |
| `ref_type` | Всегда | `branch` |
| `ref_path` | Всегда (16.0+) | `refs/heads/main` |
| `ref_protected` | Всегда | `true` |
| `environment` | Job с environment | `production` |
| `environment_protected` | Job с environment | `true` |
| `deployment_tier` | Job с environment (15.2+) | `production` |
| `environment_action` | Job с environment (18.7+) | `start` |
| `groups_direct` | Всегда | `["mygroup/mysubgroup", ...]` |
| `runner_id` | Всегда | `42` |
| `runner_environment` | Всегда | `self-hosted` |
| `sha` | Всегда | `714a629c0b40...` |
| `project_visibility` | Всегда | `public` |
| `ci_config_ref_uri` | Всегда | `gitlab.example.com/mygroup/myproject//.gitlab-ci.yml@refs/heads/main` |
| `ci_config_sha` | Всегда | `714a629c0b40...` |

> **`ci_id_token_sub_claim_components`:** через Projects API можно изменить порядок компонентов `sub`, используя неизменяемые ID (`project_id`, `job_project_id`) вместо путей. Это защищает от namespace-reclamation атак, когда переименованный/перемещённый проект унаследует trust policies предыдущего владельца. Пример: `["project_id", "ref_type", "ref"]` → `sub: project_id:67890:ref_type:branch:ref:main`.

## Предварительные требования

**Инфраструктура:**
- GitLab 17.0+ (self-managed или GitLab.com); Vault 1.17+ (требуется `bound_audiences` для JWT с `aud` claim); Consul 1.22+ (JWT auth method); внутренний API с OIDC/JWKS support; Kubernetes 1.27+
- GitLab Runner 17.0+ с поддержкой `id_tokens`
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
  oidc_discovery_url="https://gitlab.example.com" \
  bound_issuer="https://gitlab.example.com"

# Создание политики
vault policy write gitlab-app-policy - <<EOF
path "secret/data/projects/my-app/common" { capabilities = ["read"] }
path "secret/data/projects/my-app/production/*" { capabilities = ["read"] }
EOF

# Создание роли с bound claims
# Важно: bound_audiences обязан совпадать с aud в id_tokens (Vault 1.17+)
vault write auth/jwt/role/gitlab-prod-role \
  role_type="jwt" \
  policies="gitlab-app-policy" \
  token_ttl="15m" \
  bound_audiences="https://vault.example.com" \
  bound_claims_type="glob" \
  bound_claims='{
    "project_path": "my-org/backend/api-service",
    "ref_protected": "true",
    "ref": "main"
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
      vault kv get -format=json secret/projects/my-app/production/db_config > secrets.json
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
vault kv get secret/projects/my-app/production/db_config
```

Для детального развёртывания Vault в Kubernetes, настройки Vault Secrets Operator (VSO) и интеграции с GitLab Runner см. **[Интеграция GitLab CI и HashiCorp Vault в Kubernetes](../Tutorials/vault_kubernetes_integration.md)**.

### Сценарий 1.1: Environment-specific роли (Development / Production)

Сценарий 1 показывает одну роль. Для реальной инфраструктуры удобно иметь отдельную роль на каждую среду с разной политикой доступа и TTL. Здесь — два режима: `Development` (ветки `dev`/`feat/*`, TTL 1h) и `Production` (только ветки `rel/*`, TTL 30m). Конфиг `oidc_discovery_url`/`bound_issuer` из Сценария 1 уже задан — здесь только роли, политики и клиентская часть.

**Политики Vault** (только `read`, никогда `create`/`update`/`delete`):

```hcl
# Политика app-development
path "Microservices/data/+/Development/*" {
  capabilities = ["read"]
}
path "common-secret/data/Development/*" {
  capabilities = ["read"]
}

# Политика app-production
path "Microservices/data/+/Production/*" {
  capabilities = ["read"]
}
path "common-secret/data/Production/*" {
  capabilities = ["read"]
}
```

> `*` — суффиксный glob Vault (только в конце пути); `+` — wildcard для одного сегмента пути (см. [документацию Vault](https://developer.hashicorp.com/vault/docs/concepts/policies)). Пути политик используют KV v2-конвенцию с `/data/`.

**Роли:**

```bash
# Роль для Development — ветки dev и feat/*, TTL 1h
vault write auth/jwt/role/access-Development \
  role_type="jwt" \
  bound_audiences="https://vault.test.antonnovikov.com" \
  user_claim="user_login" \
  bound_claims_type="glob" \
  bound_claims='{"project_path": ["mygroup/backend/*"], "ref": ["dev", "feat/*"]}' \
  policies="app-development" \
  token_ttl="1h" \
  token_max_ttl="2h"

# Роль для Production — только ветки rel/*, TTL 30m
vault write auth/jwt/role/access-Production \
  role_type="jwt" \
  bound_audiences="https://vault.test.antonnovikov.com" \
  user_claim="user_login" \
  bound_claims_type="glob" \
  bound_claims='{"project_path": ["mygroup/backend/*"], "ref": ["rel/*"]}' \
  policies="app-production" \
  token_ttl="30m" \
  token_max_ttl="1h"
```

Ключевые моменты:

- `bound_claims_type="glob"` включает glob-сопоставление: `feat/*` и `rel/*` работают как маски, `dev` — как точное значение.
- `bound_claims.ref` ограничивает, с каких веток можно деплоить: `dev, feat/*` для Development и `rel/*` для Production.
- `bound_claims.project_path` (маска `mygroup/backend/*`) позволяет нескольким сервисам одной группы использовать одну роль.
- TTL 30m для Production — CI job должен завершиться в этом окне; для Development допущено 1h.
- `bound_audiences` обязан совпадать с `aud`, указанной в блоке `id_tokens` на стороне GitLab CI — иначе Vault вернёт `invalid audience`.

**Сторона CI/CD.** YAML-якорь `&auth_jwt` объявляется один раз и переиспользуется в каждом deploy job — меняется только `APP_ENV`:

```yaml
variables:
  VAULT_ADDR: https://vault.test.antonnovikov.com
  DOCKER_IMAGE: registry.example.com/ci-images/vault-cli:1.0.1

.auth:jwt: &auth_jwt |
  export VAULT_TOKEN="$(vault write -field=token auth/jwt/login \
    role=access-${APP_ENV} \
    jwt=$VAULT_ID_TOKEN)"
  vault kv get -field=kubeconfig_${NAMESPACE} common-secret/${APP_ENV} > kube_config
  chmod 600 kube_config
  export KUBECONFIG=kube_config

deploy_dev:
  image: ${DOCKER_IMAGE}
  stage: deploy
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.test.antonnovikov.com
  before_script:
    - *auth_jwt
  script:
    - helm upgrade --install ...
  variables:
    APP_ENV: Development
    NAMESPACE: app

deploy_prod:
  image: ${DOCKER_IMAGE}
  stage: deploy
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.test.antonnovikov.com
  before_script:
    - *auth_jwt
  script:
    - helm upgrade --install ...
  variables:
    APP_ENV: Production
    NAMESPACE: app
  rules:
    - if: $CI_COMMIT_REF_NAME =~ /^rel\//
```

> **Примечание:** устаревшая переменная `CI_JOB_JWT` (удалена в GitLab 18.0) заменена нативным блоком `id_tokens` с `VAULT_ID_TOKEN`. Аудитория (`aud`) в `id_tokens` обязана совпадать с `bound_audiences` роли.

**Kubeconfig из Vault.** Вместо хранения `kubeconfig` в CI-переменной GitLab (в UI он виден открытым текстом) — кладётся в Vault под `common-secret/<env>/kubeconfig_<cluster>` и забирается при деплое:

```bash
export VAULT_TOKEN="$(vault write -field=token auth/jwt/login \
  role=access-${APP_ENV} jwt=$VAULT_ID_TOKEN)"
vault kv get -field=kubeconfig_${NAMESPACE} common-secret/${APP_ENV} > kube_config
chmod 600 kube_config
export KUBECONFIG=kube_config
```

`kubeconfig` содержит service account token с правом `helm upgrade` строго в одном namespace. Никакого `cluster-admin` и никакого постоянного доступа к shell.

**Кастомный CI-образ.** Образ `vault-cli` собирает `vault`, `consul-template`, `helm`, `kubectl` и `curl`. Тег в `DOCKER_IMAGE` зафиксирован — каждый deploy job получает одинаковое окружение независимо от изменений в upstream:

```dockerfile
FROM hashicorp/vault:1.15
RUN apk add --no-cache curl helm kubectl
COPY --from=hashicorp/consul-template:0.33 /bin/consul-template /bin/consul-template
```

**Валидация:**

```bash
# Список ролей
vault list auth/jwt/role

# Детали роли
vault read auth/jwt/role/access-Development
vault read auth/jwt/role/access-Production

# Декодировать claims JWT (без проверки подписи)
echo $VAULT_ID_TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool

# Проверка выданного токена
vault token lookup $VAULT_TOKEN | jq '.data.policies, .data.lease_duration'
```

**Что нельзя сделать с токеном.** Ограничения, которые обеспечиваются комбинацией `bound_claims`, политик `read`-only и короткого TTL:

| Возможность | Статус | Обоснование |
| :--- | :--- | :--- |
| Доступ к секретам другой среды | Невозможно | `bound_claims` роли не пропустит токен другой среды |
| Использовать токен после завершения job | Нет | TTL истёк (30m для Production) |
| Деплой prod с feature-ветки | Нет | `bound_claims.ref` допускает только `rel/*` |
| Изменить секреты в Vault | Нет | политика выдаёт только `read` |
| Доступ к секретам других проектов | Нет | `project_path` в `bound_claims` ограничен |

Типичные ошибки: `bound claim mismatch` (ref/project_path не совпадают с ролью), `role not found` (опечатка в `APP_ENV`) и `invalid audience` (`bound_audiences` ≠ `aud` в `id_tokens`) — см. также [Устранение неполадок](#устранение-неполадок).

### Сценарий 2: Consul через JWT auth (self-hosted)

**Настройка в Consul (one-time):**

Consul использует трёхэтапную модель: auth method → binding rule → role. В отличие от Vault, `binding-rule` управляется отдельной командой, а не флагом `consul acl role create`.

```bash
# 1. Создание JWT auth method
consul acl auth-method create -type jwt -name gitlab-ci \
  -description "GitLab CI JWT auth" \
  -config '{
    "JWKSURL": "https://gitlab.example.com/-/jwks",
    "BoundIssuer": "https://gitlab.example.com",
    "BoundAudiences": ["https://consul.example.com"],
    "ClaimMappings": {
      "project_path": "project_path",
      "ref": "ref"
    }
  }' \
  -token "<MANAGEMENT_TOKEN>"

# 2. Создание роли (политики доступа)
consul acl role create -name gitlab-ci-role -description "GitLab CI service role" \
  -policy-name "service-write" \
  -token "<MANAGEMENT_TOKEN>"

# 3. Создание binding rule — связывает auth method с ролью по claims
consul acl binding-rule create \
  -method gitlab-ci \
  -selector 'Value.project_path == "mygroup/myproject" && Value.ref == "main"' \
  -bind-type role \
  -bind-name gitlab-ci-role \
  -token "<MANAGEMENT_TOKEN>"
```

> **ClaimMappings:** карта маппит claim-имена из JWT на атрибуты Consul. Без неё claims недоступны в селекторе `Value.*`. Здесь `project_path` и `ref` пробраскиваются с теми же именами — селектор может использовать `Value.project_path` и `Value.ref` напрямую. `BoundAudiences` обязателен для проверки `aud` claim (совпадает с `aud` в блоке `id_tokens`).

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
       # Аутентификация через JWT (Consul API использует PascalCase в JSON)
       CONSUL_TOKEN=$(curl -s -X POST \
         -H "Content-Type: application/json" \
         -d "{\"AuthMethod\":\"$CONSUL_AUTH_METHOD\",\"BearerToken\":\"$CONSUL_JWT\",\"Meta\":{\"pipeline\":\"$CI_PIPELINE_ID\"}}" \
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
from fastapi import FastAPI, Request, Response
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
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
    except (JWTError, ExpiredSignatureError):
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

### Сценарий 6: Kubernetes через GitLab OIDC (self-hosted)

В self-hosted Kubernetes API server настраивается как OIDC relying party с GitLab в качестве issuer. JWT от GitLab используется напрямую как Bearer token для `kubectl`.

**Настройка Kubernetes API server (one-time):**
```bash
# Параметры OIDC в kube-apiserver
--oidc-issuer-url=https://gitlab.example.com
--oidc-username-claim=email
--oidc-username-prefix="gitlab:"
--oidc-groups-claim=groups_direct
--oidc-client-id=kubernetes
--oidc-ca-file=/path/to/gitlab-ca.crt
```

**Настройка RBAC в Kubernetes:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gitlab-ci-deployer
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["pods", "pods/portforward"]
  verbs: ["get", "list", "create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gitlab-ci-deployer-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: gitlab-ci-deployer
subjects:
- kind: User
  name: "gitlab:deploy@example.com"
  apiGroup: rbac.authorization.k8s.io
- kind: Group
  name: "mygroup/myproject"
  apiGroup: rbac.authorization.k8s.io
```

**Интеграция в GitLab CI:**
```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  id_tokens:
    K8S_ID_TOKEN:
      aud: kubernetes  # должен совпадать с --oidc-client-id в kube-apiserver
  script:
    - |
      # Использование GitLab JWT напрямую как Bearer token
      kubectl --token=$K8S_ID_TOKEN --server=https://k8s-api.example.com \
        apply -f k8s/
      kubectl --token=$K8S_ID_TOKEN \
        rollout status deployment/myapp
  variables:
    KUBECONFIG: ""  # используем --token вместо kubeconfig
```

> **`aud` обязан совпадать с `--oidc-client-id`** в kube-apiserver, иначе Kubernetes отклонит токен.

### Сценарий 7: Подпись образов через OIDC (Cosign keyless)

```yaml
variables:
  COSIGN_EXPERIMENTAL: "1"

sign_image:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v3.1.3
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
vault kv get secret/projects/my-app/production/db_config
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
| `Token audience mismatch` | `aud` не совпадает | Значение `aud` в `.gitlab-ci.yml` должно совпадать с `bound_audiences`/`BoundAudiences` провайдера |
| `JWKS fetch failed` | Vault/Consul не видит GitLab | Проверьте DNS, firewall, self-signed сертификаты; для self-signed добавьте CA в trust store |
| `Cosign: certificate not found` | Fulcio недоступен | Проверьте `COSIGN_EXPERIMENTAL=1` и подключение к `fulcio.sigstore.dev` |
| `Kubernetes: token rejected` | `aud` ≠ `--oidc-client-id` или RBAC не настроен | Проверьте совпадение `aud` и `--oidc-client-id`; создайте ClusterRole+ClusterRoleBinding для GitLab identity |
| `ID token issuance is disabled` | Путь проекта ранее использовался (reclaimed path) | Обратитесь к администратору GitLab; настройте `ci_id_token_sub_claim_components` с `project_id` первым |
| `invalid audience` | `bound_audiences` ≠ `aud` в `id_tokens` | Синхронизируйте значения; в Vault 1.17+ `bound_audiences` обязателен при наличии `aud` claim |
| `bound claim mismatch` | Claims не соответствуют ролям | Проверьте `project_path`/`ref`/`ref_protected` в bound_claims |
| `Vault: role not found` | Опечатка в `VAULT_AUTH_ROLE` | Проверьте имя роли в Vault и переменную `VAULT_AUTH_ROLE` в CI/CD |
| `Consul: auth method not found` | `ClaimMappings` не включает нужные claims | Добавьте claims в `ClaimMappings`; проверьте имя `-method` в binding-rule |
| `OIDC token not generated` | `id_tokens` не задан или настройка выключена | Проверьте `id_tokens` в `.gitlab-ci.yml`; админ включил OIDC Token Issuance в `Settings → CI/CD → Token Access` |
| `Merge request pipeline denied` | `ref_protected: false` в MR pipeline | Добавьте `ref_protected` в `sub` claim components или bound_claims через `ci_id_token_sub_claim_components` API |

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
- Ротация ключей GitLab: Vault автоматически запрашивает новые ключи из JWKS каждый `jwks_url` refresh interval; `oidc_discovery_url` обновляет кэш каждые 10 мин
- Для CI/CD задач используйте `token_ttl` не более 30 минут
- `bound_claims_type="glob"` позволяет использовать `*` в значениях claims

**Consul:**
- JWT Auth Method работает в Community Edition с Consul 1.8.0+; OIDC Auth Method (для интерактивного SSO) — Enterprise только
- `BoundAudiences` обязателен — без него любой токен от GitLab пройдёт аутентификацию
- `ClaimMappings` требуется для каждого claim, используемого в `binding-rule` selector
- Binding rules и роли управляются отдельно (binding-rule связывает auth-method с ролью)

**Self-hosted GitLab — ограничения подписи:**
- Если сеть недоступна, используйте статический `jwt_validation_pubkeys` в Vault/Consul config — **требует ручной ротации** при смене ключей GitLab

## Лучшие практики

### Безопасность

1. **Используйте `id_tokens` вместо `CI_JOB_JWT`:** `CI_JOB_JWT` удалён в GitLab 18.0.
2. **Ограничьте scope JWT:** Настройте `aud` и `bound_claims` на минимально необходимые.
3. **Используйте short-lived credentials:** TTL 15-30 минут максимум для CI/CD задач.
4. **Включите аудит:** Включите audit logging в Vault/Consul для трассируемости.
5. **Ротируйте ключи:** Регулярная ротация ключей JWKS (автоматически каждые 90 дней).
6. **Least Privilege:** Назначайте минимум прав на уровне bound claims и политик.

### Эксплуатация (DevOps/SRE)

1. **Мониторьте OIDC failures:** Алерты на 401/403 от Vault/Consul. Метрика: `vault_jwt_auth_failures_total`, `consul_acl_auth_method_login_failures`.
2. **Мониторьте Vault/Consul метрики:** Доступность API (HTTP 2xx), latency (`vault_core_handle_activate_seconds`), количество активных токенов (`vault_token_count`).
3. **SLO:** Доступность Vault/Consul API — 99.9% uptime. Алерт при `http_request_duration_seconds{quantile="0.95"} > 1s` или `up == 0`.
4. **Мониторьте JWKS latency:** Vault/Consul должен получать ключи GitLab в ≤1s; алерт при `vault_jwks_fetch_failures_total > 0`.
5. **Кэшируйте секреты:** На стороне приложения, но не дольше TTL токена.
6. **Используйте batch tokens:** Для high-load сред CI/CD (меньше записей в storage).
7. **Тестируйте в staging:** Перед использованием в production протестируйте OIDC flow.
8. **Версионируйте политики:** Храните IAM/Vault/Consul политики в Git с CI-проверкой (OPA/Sentinel).
9. **Аудит токенов:** Vault audit device (`file` или `syslog`) логирует все `auth/jwt/login` запросы с `request_id`, `time`, `path`, `policy_override`.
10. **Отслеживание ротации ключей GitLab:** JWKS ключи ротируются, Vault периодически их запрашивает. Мониторьте `vault_jwks_cache_age_seconds` чтобы убедиться, что кэш не устарел.

### Sysadmin

1. **Включите OIDC Token Issuance на уровне группы:** Централизованное управление через `Settings → CI/CD → Token Access` на уровне группы/инстанса.
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

### Удаление Consul конфигурации

```bash
# Удаление binding rule (связывает auth-method с ролью)
consul acl binding-rule delete -method gitlab-ci -token "<MANAGEMENT_TOKEN>"

# Удаление роли
consul acl role delete -name gitlab-ci-role -token "<MANAGEMENT_TOKEN>"

# Отключение auth method (удаляет связанные binding rules автоматически)
consul acl auth-method delete -name gitlab-ci -token "<MANAGEMENT_TOKEN>"
```

> **Важно:** удаление auth method автоматически удаляет все связанные binding rules. Удаляйте binding rules в первую очередь только для аудита, затем роль, затем auth method.

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
- **[Система управления доступом Consul](../../../Consul/consul_acl.md)** — Consul ACL, JWT Auth Method
- **[Zero Trust Architecture в Vault](../../../Vault/zero_trust.md)** — принципы Zero Trust
- **[CI_JOB_TOKEN Security](../Advanced/ci_job_token_security.md)** — безопасность токенов в GitLab CI
- **[SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md)** — Cosign, Sigstore
- **[Resource Group и контроль пайплайнов](../Advanced/resource_group_and_pipeline_control.md)** — управление параллелизмом

### Внешние ресурсы

- [GitLab: OpenID Connect (OIDC) Authentication Using ID Tokens](https://docs.gitlab.com/ee/ci/secrets/id_token_authentication.html)
- [GitLab: Use HashiCorp Vault secrets in GitLab CI/CD](https://docs.gitlab.com/ee/ci/secrets/hashicorp_vault.html)
- [GitLab: Projects API (`ci_id_token_sub_claim_components`)](https://docs.gitlab.com/ee/api/projects.html#save_edit_project)
- [HashiCorp Vault: JWT Auth Method](https://developer.hashicorp.com/vault/docs/auth/jwt)
- [HashiCorp Vault: Convert CI_JOB_JWT to ID Tokens](https://docs.gitlab.com/ee/ci/secrets/convert-to-id-tokens.html)
- [HashiCorp Consul: JWT Auth Method](https://developer.hashicorp.com/consul/docs/secure/acl/auth-methods/jwt)
- [HashiCorp Consul: ACL Binding Rules](https://developer.hashicorp.com/consul/commands/acl/binding-rule/create)
- [Sigstore: Cosign keyless signing](https://docs.sigstore.dev/cosign/overview/)
