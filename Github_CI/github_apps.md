# GitHub Apps: глубокое погружение

**Актуально для:** GitHub Apps, октябрь 2026 (App Manifest flow, Private key JWT auth, Installation tokens stateless format `ghs_APPID_JWT` ~520 chars, Granular permissions, Webhook delivery — no auto-retry)

GitHub App — это первоклассный актор на платформе GitHub, обладающий собственной идентичностью, гранулярными правами и возможностью установки на уровне организации или пользователя. В отличие от OAuth Apps (действующих от лица пользователя) и PAT (личных токенов), GitHub Apps являются предпочтительным способом автоматизации для CI/CD, security tools и платформенной интеграции.

## Определения

- **GitHub App**: Приложение, зарегистрированное в GitHub (Settings → Developer settings → GitHub Apps), имеющее `App ID`, `Client ID`, приватный ключ (PEM, RSA 2048+ бит) и набор запрашиваемых прав (`permissions`).
- **Installation**: Акт установки App в конкретный аккаунт (User) или организацию (Organization). Каждая установка получает уникальный `Installation ID`.
- **Installation Token**: Короткоживущий токен доступа (TTL 1 час), выпускаемый для конкретной установки через `POST /app/installations/{installation_id}/access_tokens`. Имеет только те права, что настроены в App, и может быть дополнительно сужен при выпуске (`permissions` / `repositories` в теле запроса). **С апреля 2026 формат — stateless `ghs_APPID_JWT` (~520 символов)**, обратная совместимость сохраняется; токены старого формата (40 chars) работают до истечения TTL.
- **Private Key (PEM)**: RSA-ключ (2048+ бит), скачиваемый один раз при создании App. Используется для подписи JWT при аутентификации как App (не как установка). Хранится только в секретах (GitHub Actions Secrets, Vault, 1Password).
- **JWT (JSON Web Token)**: Токен, подписанный приватным ключом App (`RS256`), с claims: `iat` (issued at, **рекомендуется 60 сек в прошлом** для clock skew), `exp` (expires at, **макс. 10 минут**), `iss` (Issuer — **Client ID рекомендован**, или App ID). Нужен для получения Installation Token и для операций на уровне App (список установок, управление вебхуками).
- **Webhook Secret**: Секрет, настроенный в App, для HMAC-SHA256 подписи вебхук-пейлоадов (`X-Hub-Signature-256` заголовок). Обязателен для верификации подлинности доставки.
- **App Manifest**: JSON-манифест для быстрой регистрации App через URL (`https://github.com/settings/apps/new?manifest=<base64url>`), используется для дистрибуции шаблонов.
- **Granular Permissions**: Права разбиты по категориям (Contents, Issues, Pull Requests, Checks, Deployments, Pages, Secrets, Administration, Metadata, Actions, Dependabot alerts, Organization members/teams) и уровням (No access / Read-only / Read & Write). Настраиваются при регистрации App; установка наследует их, токен можно сузить дальше.
- **OAuth App vs GitHub App**: OAuth App действует от имени пользователя (user-to-server), GitHub App — от своего имени (server-to-server). App может работать без вовлечения пользователя после установки.
- **GitHub App в Ruleset Bypass**: Installation Token, добавленный в bypass-лист ruleset (Settings → Rules → Rulesets), позволяет обходить защиту веток/тегов для автоматизации. В UI отображается как "GitHub App".
- **Rate Limits (Primary)**: Installation Token лимиты — 5,000 req/hr (не GHE Cloud), масштабируется +50/hr за репозиторий >20 и +50/hr за пользователя >20, потолок 12,500; для GHE Cloud — 15,000 req/hr per installation. GraphQL: 5,000 points/hr (10,000 GHE Cloud). Secondary limits: 100 concurrent, 900 points/min REST / 2,000 points/min GraphQL, 90s CPU/60s real time, 80 content-generating req/min.

## Предварительные требования

- **GitHub CLI** (gh) v2.40+ для примеров CLI
- **curl** + **jq** для raw HTTP запросов
- **Приватный ключ App (PEM)**: RSA 2048+ бит, скачанный при создании App, хранится только в секретах
- **App ID / Client ID**: из настроек App (Settings → Developer settings → GitHub Apps → App name)
- **Установка App**: App должен быть установлен в целевую организацию/аккаунт с нужными правами
- **Сеть**: доступ к `api.github.com` (или вашему GES endpoint)
- **Для вебхуков**: публичный HTTPS endpoint с валидным TLS, доступный из интернета; настроенный `Webhook Secret`
- **Для Actions**: `actions/create-github-app-token@v3` экшен; `APP_CLIENT_ID` (vars), `APP_PRIVATE_KEY` (secrets)

## Архитектура и потоки аутентификации

### 1. Аутентификация как App (App-level) → JWT
Используется для: получение списка установок (`GET /app/installations`), создание токена установки, управление вебхуками App, чтение конфигурации App.

```text
Private Key (PEM) → Sign JWT (RS256, claims: iss=APP_ID, iat, exp≤10min)
      ↓
Authorization: Bearer <JWT>
      ↓
GitHub API (App endpoints)
```

### 2. Аутентификация как Установка (Installation-level) → Installation Token
Используется для: все операции над репозиториями, к которым установлен App (Git API, Issues, PR, Checks, Deployments, Actions, Packages).

```text
JWT (App-level) → POST /app/installations/{installation_id}/access_tokens
      ↓
Installation Token (opaque, ~1h TTL)
      ↓
Authorization: Bearer <Installation Token>
      ↓
GitHub API (Repository/Org endpoints)
```

### 3. Сужение прав токена установки (Token Scoping)
При выпуске токена можно передать `permissions` и `repositories` — токен получит только подмножество прав App и доступ только к указанным репозиториям.

```json
POST /app/installations/12345/access_tokens
{
  "permissions": { "contents": "write", "issues": "read" },
  "repositories": ["repo-a", "repo-b"]
}
```
### 4. Webhook Delivery

GitHub доставляет события на настроенный `Webhook URL` (HTTPS, публичный). Формат: `POST` с JSON-телом, заголовки: `X-GitHub-Event`, `X-GitHub-Delivery` (UUID), `X-Hub-Signature-256` (HMAC-SHA256 от тела по `Webhook Secret`), `X-GitHub-Hook-ID`, `X-GitHub-Hook-Installation-Target-Type`, `X-GitHub-Hook-Installation-Target-ID`.

**Важно:** GitHub **НЕ выполняет автоматическую повторную доставку** (redelivery) неудачных вебхуков. Если сервер недоступен, отвечает не 2xx, или таймаут >10 секунд — доставка помечается как failed. Повторную доставку можно инициировать вручную через UI (App Settings → Advanced → Recent Deliveries → Redeliver) или через API (`POST /app/hook/deliveries/{delivery_id}/attempts` с JWT). Для надежности: идемпотентная обработка по `X-GitHub-Delivery` + внешняя очередь (Kafka, SQS) или GitHub App webhook forwarding (`smee.io` для разработки). В UI доступны доставки за последние 3 дня.

## Конфигурация App

### Права (Permissions) — полный список категорий

| Категория | Уровни | Типичные сценарии |
|---|---|---|
| **Contents** | Read / Read & Write | Git operations, releases, packages |
| **Issues** | Read / Read & Write | Issue automation, triage bots |
| **Pull Requests** | Read / Read & Write | PR automation, reviewers, labels |
| **Checks** | Read / Read & Write | CI/CD status, annotations |
| **Deployments** | Read / Read & Write | Deployment status, environments |
| **Pages** | Read / Read & Write | GitHub Pages publishing |
| **Secrets** | Read / Read & Write | Actions/Dependabot secrets management |
| **Administration** | Read / Read & Write | Repo settings, rulesets, branches (⚠️ high risk) |
| **Metadata** | Read only | Read-only access to public metadata |
| **Actions** | Read / Read & Write | Workflow runs, artifacts, runners |
| **Dependabot alerts** | Read / Read & Write | Security alerts automation |
| **Members** | Read / Read & Write | Org membership management |
| **Organization projects** | Read / Read & Write | Project boards |
| **Team discussions** | Read / Read & Write | Team discussions |
| **Repository hooks** | Read / Read & Write | Webhook management |
| **Single file** | Read / Read & Write | Доступ к конкретному файлу (`.github/dependabot.yml` etc.) |

**Принцип**: запрашивайте минимум прав. При установке выбирайте "All repositories" или "Only select repositories". Для cross-repo автоматизации — организация-уровень с "All repositories".

### Webhook Events — выбор событий

| Событие | Когда срабатывает | Типичное использование |
|---|---|---|
| `push` | Пуш коммитов/тегов | CI trigger, artifact build |
| `pull_request` | PR opened/closed/synchronize/reopened | PR checks, reviewers, labels |
| `pull_request_review` | Review submitted/dismissed | Merge gates |
| `check_run` / `check_suite` | CI status changes | Status aggregation |
| `workflow_run` / `workflow_job` | Actions workflow/job events | Downstream triggers |
| `deployment` / `deployment_status` | Deployment events | CD pipelines |
| `release` | Release published/edited | Changelog, notifications |
| `repository` | Created/deleted/archived/renamed | Auto-configuration of new repos |
| `installation` | App installed/uninstalled | Setup/cleanup |
| `installation_repositories` | Repos added/removed from installation | Dynamic repo access |
| `organization` | Org-level changes (member, team, repo) | Org governance |
| `member` | User added/removed from org | Access auditing |
| `team` / `team_add` | Team changes | Permission sync |

**Рекомендация**: включайте только нужные события — уменьшает нагрузку на ваш endpoint и шум.

## Практические сценарии

### Сценарий 1: Регистрация GitHub App через манифест (App Manifest)

**Предварительные требования**: Админ-доступ к организации/аккаунту для установки.

`app-manifest.json`:
```json
{
  "name": "CI Automation Bot",
  "url": "https://github.com/my-org/ci-automation-bot",
  "hook_attributes": {
    "url": "https://webhook.example.com/github",
    "active": true
  },
  "redirect_url": "https://github.com/my-org/ci-automation-bot/callback",
  "callback_urls": ["https://github.com/my-org/ci-automation-bot/callback"],
  "description": "Automation for CI/CD, releases, and dependency updates",
  "public": false,
  "default_events": ["push", "pull_request", "workflow_run", "check_run", "deployment"],
  "default_permissions": {
    "contents": "write",
    "issues": "write",
    "pull_requests": "write",
    "checks": "write",
    "deployments": "write",
    "metadata": "read",
    "secrets": "write",
    "actions": "read",
    "administration": "read"
  },
  "optional_events": ["repository", "organization", "workflow_job"],
  "optional_permissions": {
    "members": "read",
    "team_discussions": "read"
  }
}
```

Установка: откройте `https://github.com/settings/apps/new?manifest=$(cat app-manifest.json | base64 -w0)` в браузере → выберите целевую организацию → Authorize. После установки: сохраните `App ID`, `Client ID`, скачайте Private Key (PEM), запишите `Webhook Secret`.

**Валидация**: `curl -H "Authorization: Bearer <JWT>" https://api.github.com/app/installations` возвращает список установок с `id` и `account.login`.

### Сценарий 2: Получение Installation Token в GitHub Actions (actions/create-github-app-token)

**Предварительные требования**: App установлен в репозиторий/организацию с правами `Contents: Read and write` (минимум); `APP_CLIENT_ID` (vars), `APP_PRIVATE_KEY` (secrets).

```yaml
jobs:
  use-app-token:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Generate App Installation Token
        id: app-token
        uses: actions/create-github-app-token@v3
        with:
          client-id: ${{ vars.APP_CLIENT_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}
          permission-contents: write
          permission-pull-requests: write
          permission-issues: read
      - name: Use token for git push
        uses: actions/checkout@v4
        with:
          token: ${{ steps.app-token.outputs.token }}
          persist-credentials: true
      - run: |
          git config user.name "ci-bot[bot]"
          git config user.email "123456+ci-bot[bot]@users.noreply.github.com"
          echo "auto-update" >> generated.txt
          git add generated.txt
          git commit -m "chore: auto-update [skip ci]"
          git push
```

- `client-id` (не `app-id`) — актуальный вход с v3 экшена (app-id deprecated).
- `permission-*` входы сужают токен до нужного минимума (principle of least privilege).
- Токен валиден 1 час; экшен кэширует его на время джобы.

**Валидация**: в логах `git push` виден успех; в UI коммит от `ci-bot[bot]`; `gh api /repos/{owner}/{repo}/commits/main` показывает `author.type: "Bot"`.

### Сценарий 3: App-токен для обхода Ruleset / Branch Protection (Bypass Actor)

**Предварительные требования**: Ruleset настроен на защиту `main` (Required Status Checks, No Force Push); App установлен в организацию; у App права `Contents: Read and write`.

1. В Settings → Rules → Rulesets → целевой Ruleset → раздел "Bypass list" → Add bypass actor → **GitHub App** → выберите установленный App.
2. В воркфлоу используйте Installation Token (как в Сценарии 2) для `git push` в защищённую ветку.

```yaml
- uses: actions/create-github-app-token@v3
  id: app-token
  with:
    client-id: ${{ vars.APP_CLIENT_ID }}
    private-key: ${{ secrets.APP_PRIVATE_KEY }}
    permission-contents: write
- uses: actions/checkout@v7
  with:
    token: ${{ steps.app-token.outputs.token }}
    persist-credentials: true
- run: git push origin HEAD:main
```

**Валидация**: Push проходит без `GH013: Repository rule violations found`; в аудит-логе организации событие `git.push` с `actor_type: "GitHub App"`.

### Сценарий 4: Публикация пакетов в GHCR/npm через App (Trusted Publishing / OIDC)

Для GHCR: App-токен с `packages: write` работает как классический `docker/login-action` с `GITHUB_TOKEN`. Для npm trusted publishing — используйте `id-token: write` + OIDC (App не нужен, достаточно `GITHUB_TOKEN` с OIDC). App полезен, когда реестр не поддерживает OIDC или нужна централизованная идентичность бота.

```yaml
permissions:
  id-token: write      # для OIDC (npm trusted publishing)
  contents: read
  packages: write      # для GHCR через App-токен
steps:
  - uses: actions/create-github-app-token@v3
    id: app-token
    with:
      client-id: ${{ vars.APP_CLIENT_ID }}
      private-key: ${{ secrets.APP_PRIVATE_KEY }}
      permission-packages: write
      permission-contents: read
  - uses: docker/login-action@v4
    with:
      registry: ghcr.io
      username: ${{ github.actor }}
      password: ${{ steps.app-token.outputs.token }}
  - uses: docker/build-push-action@v7
    with:
      push: true
      tags: ghcr.io/${{ github.repository }}:${{ github.ref_name }}
```

### Сценарий 5: Обработка вебхуков App (HMAC verification, idempotency)

**Предварительные требования**: Webhook URL доступен из интернета; настроен `Webhook Secret` в App.

```python
# FastAPI пример (Python 3.11+)
from fastapi import FastAPI, Request, Header, HTTPException
import hmac, hashlib, json, os

app = FastAPI()
WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"].encode()

@app.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_github_delivery: str = Header(None),
    x_hub_signature_256: str = Header(None)
):
    body = await request.body()
    # 1. Verify HMAC
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256 or ""):
        raise HTTPException(401, "Invalid signature")
    # 2. Idempotency key = delivery ID
    event = json.loads(body)
    # process event...
    return {"status": "ok", "delivery": x_github_delivery}
```

- `X-Hub-Signature-256` — единственный надёжный способ верификации (IP-диапазоны GitHub меняются).
- `X-GitHub-Delivery` — ключ идемпотентности: сохраняйте в Redis/БД с TTL > retry window (например, 7 дней) и игнорируйте дубликаты.
- События `ping` (тестовый) — отвечайте 200 OK сразу.

### Сценарий 6: Автоматизация установки App в новые репозитории организации

App установлен на уровне организации → автоматически доступен во всех текущих и будущих репозиториях (если не ограничено "Repository selection" при установке). Для автоматической настройки прав в новых репозиториях используйте `repository` webhook событие + App Installation Token с `administration: write`:

```yaml
on:
  repository:
    types: [created]
jobs:
  configure-app-access:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v3
        id: app-token
        with:
          client-id: ${{ vars.APP_CLIENT_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}
          permission-administration: write
          permission-contents: read
      - name: Enable App for repo (if needed)
        run: |
          # App уже имеет доступ к org-репозиториям; этот шаг — пример изменения настроек репозитория
          gh api -X PATCH repos/${{ github.repository }} \
            -f allow_auto_merge=true \
            -f delete_branch_on_merge=true \
            -H "Authorization: Bearer ${{ steps.app-token.outputs.token }}"
```

### Сценарий 7: Генерация JWT для App-level API (без экшена)

Для скриптов вне Actions (VM, контейнеры, серверы) — генерация JWT на лету:

```bash
#!/usr/bin/env bash
# generate-app-jwt.sh — генерация JWT для GitHub App
# Требует: openssl, jq, base64 (GNU или BSD)
# Usage: ./generate-app-jwt.sh <APP_CLIENT_ID> <PRIVATE_KEY_PEM_FILE>

set -euo pipefail

CLIENT_ID="${1:?APP_CLIENT_ID required}"
PEM_FILE="${2:?Private key PEM file required}"

# Header
header='{"alg":"RS256","typ":"JWT"}'
header_b64=$(echo -n "$header" | openssl base64 -A | tr '+/' '-_' | tr -d '=')

# Payload: iat = 60 сек в прошлом (clock skew), exp = 10 мин, iss = Client ID
now=$(date +%s)
iat=$((now - 60))
exp=$((now + 600))
payload=$(jq -nc --argjson iat "$iat" --argjson exp "$exp" --arg iss "$CLIENT_ID" \
  '{iat: $iat, exp: $exp, iss: $iss}')
payload_b64=$(echo -n "$payload" | openssl base64 -A | tr '+/' '-_' | tr -d '=')

# Sign
signing_input="${header_b64}.${payload_b64}"
signature=$(echo -n "$signing_input" | openssl dgst -sha256 -sign "$PEM_FILE" | openssl base64 -A | tr '+/' '-_' | tr -d '=')

echo "${signing_input}.${signature}"
```

```python
# Python 3.11+ alternative (requires PyJWT[crypto])
import jwt, time, sys

client_id = sys.argv[1]
with open(sys.argv[2], 'rb') as f:
    private_key = f.read()

payload = {
    'iat': int(time.time()) - 60,   # 60 sec in past for clock skew
    'exp': int(time.time()) + 600,  # 10 min max
    'iss': client_id                # Client ID (recommended) or App ID
}
token = jwt.encode(payload, private_key, algorithm='RS256')
print(token)
```

**Валидация**: `curl -H "Authorization: Bearer $JWT" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2026-03-10" https://api.github.com/app/installations` → возвращает JSON массив установок.

### Сценарий 8: Ручная повторная доставка вебхуков (Redelivery)

GitHub не делает авто-редилевери. Для production — cron-джоба, которая проверяет и ределеверит failed deliveries:

```yaml
# .github/workflows/webhook-redelivery.yml
on:
  schedule:
    - cron: '*/15 * * * *'  # каждые 15 минут
permissions:
  contents: read
jobs:
  redeliver-failed:
    runs-on: ubuntu-latest
    steps:
      - name: Generate App JWT
        id: jwt
        uses: actions/create-github-app-token@v3
        with:
          client-id: ${{ vars.APP_CLIENT_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}
      - name: Redeliver failed webhook deliveries
        env:
          GH_TOKEN: ${{ steps.jwt.outputs.token }}
          APP_ID: ${{ vars.APP_CLIENT_ID }}
        run: |
          # Используем gh api с JWT для вызова App webhook endpoints
          last_check=$(gh variable get LAST_WEBHOOK_REDELIVERY 2>/dev/null || date -d '24 hours ago' +%s)
          current_time=$(date +%s)
          
          # Получить доставки после last_check
          deliveries=$(gh api /app/hook/deliveries \
            --jq "[.[] | select(.delivered_at | fromdateiso8601 > $last_check and .status != \"OK\") | .id]")
          
          for delivery_id in $(echo "$deliveries" | jq -r '.[]'); do
            echo "Redelivering $delivery_id..."
            gh api -X POST /app/hook/deliveries/$delivery_id/attempts
          done
          
          # Обновить переменную
          gh variable set LAST_WEBHOOK_REDELIVERY --body "$current_time"
```

**Примечание**: `gh variable` требует `gh` 2.40+ и права `variables: write` в workflow permissions.

### Сценарий 9: Миграция на stateless Installation Tokens (ghs_APPID_JWT)

С апреля 2026 GitHub выпускает stateless токены (~520 chars, префикс `ghs_`). Если ваш код ожидает 40-символьные токены — обновите валидацию:

```bash
# Проверка формата токена
TOKEN="ghs_..."
if [[ ${#TOKEN} -gt 100 && $TOKEN == ghs_* ]]; then
  echo "Stateless token format detected (OK)"
elif [[ ${#TOKEN} -eq 40 ]]; then
  echo "Legacy token format (works until expiry)"
else
  echo "Unexpected token format"
fi
```

**Что нужно проверить**:
- Длина колонок БД / полей секретов (≥ 600 chars)
- Прокси / API gateway: не обрезают ли `Authorization` header
- Логирование / redaction правила: совпадают ли с `ghs_[A-Z0-9_]+`
- Временный header `X-GitHub-Stateless-S2S-Token` deprecated 30 Nov 2026

## Команды и API-операции

### REST API — ключевые endpoint-ы

| Операция | Endpoint / CLI | Назначение |
|---|---|---|
| Создать JWT (App auth) | `github-app-token generate --app-id <ID> --private-key <PEM>` (custom script) | Получить JWT для App-level API |
| Получить Installation Token | `POST /app/installations/{id}/access_tokens` | Токен для работы с репозиториями (scope via `permissions`, `repositories`, `repository_ids`) |
| Список установок | `GET /app/installations` | Инвентаризация установок App |
| Получить App манифест | `GET /app/manifest` | Экспорт конфигурации |
| Создать App из манифеста | `POST /app-manifests/{code}/conversions` | OAuth flow для манифеста |
| Список вебхуков App | `GET /app/hook/config` | Конфигурация вебхука |
| Обновить вебхук App | `PATCH /app/hook/config` | Смена URL/секрета |
| Проверить подпись вебхука | HMAC-SHA256(body, secret) | Валидация входящих событий |
| Список доставок вебхука | `GET /app/hook/deliveries` | История доставок (последние 3 дня) |
| Повторная доставка | `POST /app/hook/deliveries/{delivery_id}/attempts` | Ручной redelivery (требует JWT) |
| Получить конкретную доставку | `GET /app/hook/deliveries/{delivery_id}` | Детали доставки для отладки |

**Обязательные заголовки для App endpoints:**
```
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2026-03-10
Authorization: Bearer <JWT>          # для App-level endpoints
Authorization: Bearer <Installation Token>  # для Installation endpoints
```

### CLI (`gh`)

```bash
# Installation management
gh api /app/installations --jq '.[].id'                    # список installation IDs
gh api /app/installations/12345/access_tokens -X POST \
  -f permissions='{"contents":"write","issues":"read"}'  # выпуск токена с суженными правами
gh api /app/installations/12345/access_tokens -X POST \
  -f repositories='["repo-a","repo-b"]'                  # токен только для конкретных репо

# App info
gh api /app --jq '{id, name, slug, owner}'               # информация о самом App
gh api /app/manifest                                     # текущий манифест

# Webhook config
gh api /app/hook/config                                  # текущий URL + secret
gh api -X PATCH /app/hook/config -f url="https://new.url" -f secret="newsecret"

# Webhook deliveries (последние 3 дня)
gh api /app/hook/deliveries --jq '.[] | {id: .id, event: .event, status: .status, delivered_at: .delivered_at}'
gh api -X POST /app/hook/deliveries/12345/attempts       # ределеверить конкретную доставку
```

### GraphQL — App-related queries

```graphql
# Получить App и его установки
query($appId: ID!) {
  organization(login: "my-org") {
    githubApps(first: 10) {
      nodes {
        id
        name
        slug
        installations(first: 20) {
          nodes {
            id
            target { login }
            repositories(first: 100) { totalCount }
          }
        }
      }
    }
  }
}

# Rate limit для Installation Token
query { rateLimit { limit remaining used resetAt } }
```

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `401 Bad credentials` на JWT | Приватный ключ не соответствует App ID; часы сервера рассинхронизированы (JWT `exp`/`iat`); неверный `iss` (App ID vs Client ID) | Проверить PEM файл; синхронизировать NTP; `iat` на 60 сек в прошлом; использовать **Client ID** в `iss` |
| `403 Resource not accessible by integration` | У App нет прав на ресурс; токен выпущен без нужного `permission`; ресурс не входит в scope установки | Добавить permission в App settings или в запрос токена; проверить `repositories`/`repository_ids`; переустановить App с "All repositories" |
| `404 Not Found` на `/app/installations/{id}/access_tokens` | Installation ID неверен или App не установлен в целевую организацию | Проверить `gh api /app/installations`; убедиться, что App установлен; проверить `target_type` (User vs Organization) |
| Вебхук не доставляется (нет логов) | URL недоступен (firewall, DNS); TLS ошибка; сервер не отвечает 2xx за 10 сек | Проверить доступность `curl -v <URL>`; логи сервера; `X-GitHub-Delivery` в UI App (Advanced → Recent Deliveries) |
| `X-Hub-Signature-256` mismatch | Секрет в App settings не совпадает с переменной окружения обработчика; encoding issue | Синхронизировать секрет; проверить encoding (raw bytes vs base64); тело запроса не модифицировано перед verify |
| Токен установки истекает посередине длинной джобы | TTL 1 час; джоба дольше | Разбить на короче джобы; использовать `actions/create-github-app-token` который кэширует токен на время джобы |
| App не видит новые репозитории организации | При установке выбрано "Only select repositories" | Переустановить App с "All repositories" или добавить репозиторий вручную в установке |
| `actions/create-github-app-token` fails: `private key format` | PEM содержит лишние переносы строк / неверный формат | Ключ должен быть PKCS#1 или PKCS#8 PEM (`-----BEGIN RSA PRIVATE KEY-----` или `-----BEGIN PRIVATE KEY-----`); в YAML использовать `|` block scalar |
| Stateless token (`ghs_...`) не принимается вашим кодом | Валидация ожидает 40-символьный legacy формат | Обновить проверки длины (≥600 chars); прокси/API gateway не должны обрезать `Authorization` header; логирование/redaction правила под `ghs_[A-Z0-9_]+` |
| `X-GitHub-Stateless-S2S-Token` header игнорируется | Header deprecated 30 Nov 2026 | Убрать зависимость от временного header; все токены теперь stateless по умолчанию |
| Webhook deliveries не ределеверятся автоматически | GitHub НЕ делает авто-редилевери | Настроить cron-джобу (см. Сценарий 8) или использовать внешнюю очередь; UI доступен только за последние 3 дня |
| `409 Conflict` на `POST /app-manifests/{code}/conversions` | Manifest code уже использован или истёк (1 час TTL) | Сгенерировать новый manifest URL; code одноразовый |
| Rate limit 403 на App endpoints | Primary/Secondary rate limits для Installation Token | См. Rate Limits в Определениях; circuit breaker при `remaining < 100`; пауза 1с между mutative запросами |

## Валидация и проверка результатов

После настройки App и выполнения операций проверяйте:

```bash
# 1. JWT валиден и работает
JWT=$(./generate-app-jwt.sh "$CLIENT_ID" "$PEM_FILE")
curl -s -H "Authorization: Bearer $JWT" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  https://api.github.com/app/installations | jq '.[].id'
# → возвращает массив installation IDs

# 2. Installation Token работает и имеет правильные права
INSTALL_TOKEN=$(gh api /app/installations/12345/access_tokens -X POST \
  -f permissions='{"contents":"write"}' --jq '.token')
curl -s -H "Authorization: Bearer $INSTALL_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  https://api.github.com/repos/{owner}/{repo} | jq '.permissions.contents'
# → "write"

# 3. Webhook HMAC verification работает
# Отправить тестовый ping через UI App (Advanced → Recent Deliveries → Redeliver ping)
# → ваш endpoint должен вернуть 200 OK

# 4. Rate limit headers
gh api /app/installations/12345/access_tokens -X POST -I \
  --jq '.headers | {limit: ."x-ratelimit-limit", remaining: ."x-ratelimit-remaining"}'
# → remaining > 0

# 5. Stateless token format check
TOKEN="ghs_..."
if [[ ${#TOKEN} -gt 100 && $TOKEN == ghs_* ]]; then
  echo "OK: Stateless token format"
fi
```

## Лучшие практики

1. **Всегда используйте GitHub App вместо PAT** для автоматизации: гранулярные права, аудит, независимость от пользователя, поддержка bypass в rulesets.
2. **Сужайте токен установки** при выпуске (`permission-*` входы экшена или `permissions`/`repositories` в API) — минимум прав на задачу (principle of least privilege).
3. **Храните Private Key (PEM) только в секретах** (GitHub Actions Secrets, Vault, 1Password, AWS Secrets Manager); никогда не коммитьте в репозиторий; не логируйте.
4. **Версионируйте App Manifest** в репозитории (как код) — воспроизводимая установка в новые организации; используйте `optional_permissions` для прогрессивного расширения.
5. **Настраивайте Webhook Secret** и всегда верифицируйте `X-Hub-Signature-256` — единственная защита от поддельных вебхуков (IP ranges меняются).
6. **Идемпотентность вебхуков** по `X-GitHub-Delivery` — сохраняйте delivery ID с TTL ≥ 7 дней (покрывает retry window).
7. **Монитьте вебхук доставки** в UI App (Advanced → Recent Deliveries) — ловите системные сбои доставки; настройте алерты на failed deliveries.
8. **Для CI/CD: App + Installation Token + Ruleset Bypass** — эталонный паттерн записи в защищённые ветки/теги.
9. **Ротируйте Private Key** периодически (Settings → Developer settings → GitHub Apps → Edit → Generate private key); старый ключ перестаёт работать сразу — планируйте ротацию.
10. **Избегайте `administration: write`** в токене, если не нужно менять настройки репозитория — высокий риск при компрометации.
11. **Используйте Client ID в JWT `iss` claim** (не App ID) — рекомендовано GitHub, работает с Enterprise Managed Users.
12. **JWT `iat` = 60 сек в прошлом** — защита от clock skew между вашим сервером и GitHub.
13. **Для production вебхуков: внешняя очередь** (Kafka, SQS, Redis Streams) + consumer с retry/backoff — GitHub не делает авто-редилевери.
14. **Проверяйте stateless token совместимость** (≥600 chars в БД/секретах/логах/прокси) — миграция завершена октябрь 2026.
15. **Ограничивайте `repositories` при выпуске токена** для cross-repo задач — токен только для нужных репо, даже если App имеет доступ ко всем.
16. **Actions: `actions/create-github-app-token@v3`** — используйте `permission-*` входы, не передавайте полный набор прав установки.
17. **App-level operations (JWT) только для управления App** — не используйте для репозиторий операций; для репо — всегда Installation Token.

## Edge Cases и ограничения

- **JWT TTL**: макс. 10 минут; нельзя продлить — генерируйте новый перед каждым использованием или кэшируйте с запасом.
- **Installation Token TTL**: 1 час точно; нельзя продлить — выдавайте новый токен.
- **App Manifest code TTL**: 1 час; одноразовый — после конвертации в App code инвалидируется.
- **Webhook deliveries UI**: только последние 3 дня; старее — недоступны через UI и API.
- **Max 500 repositories** в `repositories`/`repository_ids` при выпуске токена.
- **Enterprise-level scale sets (ARC)**: поддерживают только PAT (classic), GitHub App недоступен.
- **`X-GitHub-Stateless-S2S-Token` header**: deprecated 30 Nov 2026 — не полагайтесь на него.
- **Private Key rotation**: старый ключ сразу невалиден — нужен blue/green деплой или координированная ротация.
- **OAuth App vs GitHub App**: OAuth App = user-to-server (действует от пользователя); GitHub App = server-to-server (действует от себя). Не смешивайте.

## Дополнительная информация

- **[Git-автоматизация](./Git_Automation.md)** — использование App-токена для push, bypass rulesets, бот-коммиты.
- **[Управление секретами](./secrets_management.md)** — иерархия токенов, `permissions`, OIDC.
- **[GitHub Webhooks](./github_webhooks.md)** — общие webhook события, retry policy, HMAC verification для repository/org webhooks.
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — вебхук-события (`repository_dispatch`, `workflow_run`) и их триггеры.
- **[Оптимизация](./Optimization.md)** — контроль одновременных запусков ботов через `concurrency`.
- **[Синтаксис Workflow](./Workflow_Syntax.md)** — контексты `github`, `needs`, `steps` для передачи токенов между задачами.
- **[GitHub API](./github_api.md)** — REST/GraphQL endpoints, rate limits, pagination, conditional requests.
- **[Actions Runner Controller](./actions_runner_controller.md)** — ARC аутентификация через GitHub App (repo/org-level scale sets).
- **Официальная документация**: 
  - [GitHub Apps](https://docs.github.com/en/apps/creating-github-apps) — создание, настройка, манифесты
  - [Authenticating as a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app) — JWT, Installation Tokens
  - [Generating a JWT](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app) — `iat` 60 сек в прошлом, `iss` = Client ID
  - [Installation Access Tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app) — stateless format, permissions scoping
  - [Webhook events](https://docs.github.com/en/webhooks/webhook-events-and-payloads) — полный список событий и payloads
  - [Handling failed webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries) — нет авто-редилевери, ручной процесс
  - [Rate limits for GitHub Apps](https://docs.github.com/en/rest/apps/apps?apiVersion=2026-03-10) — primary/secondary limits
  - [Changelog: Stateless tokens](https://github.blog/changelog/2026-10-02-stateless-github-app-installation-tokens-rolled-out/) — okt 2026 rollout complete