# GitHub API: REST, GraphQL, Rate Limits и Пагинация

**Актуально для:** GitHub REST API 2026-03-10, GraphQL API (current schema), октябрь 2026; для GitHub Enterprise Server — 3.22+ (API версии отстают на 1–2 версии)

GitHub предоставляет два API: **REST API** и **GraphQL API**. REST — классический подход с endpoint-ами, возвращающими JSON и поддерживающими pagination через `Link` header. GraphQL — позволяет запрашивать ровно те данные, которые нужны, в одном запросе (меньше over-fetching и round-trips). Оба API аутентифицируются через Fine-grained PAT, classic PAT, GitHub App, или через `GITHUB_TOKEN` (внутри Actions).

## Определения

- **REST API**: HTTP-интерфейс с endpoint-ами вида `GET /repos/{owner}/{repo}/issues`. Версионируется через заголовок `X-GitHub-Api-Version` (текущая: `2026-03-10`). Поддерживает JSON, pagination через Link header, rate limiting.
- **GraphQL API**: GraphQL-интерфейс с одним endpoint `POST /graphql`. Позволяет запрашивать вложенные/связанные данные в одном запросе. Schema introspection доступен через `GET /graphql` или GraphQL introspection query.
- **Rate Limit**: Ограничение на количество запросов/points в час. Различается по типу аутентификации (см. раздел «Rate Limit — как это работает»).
- **Pagination**: Механизм разбивки результатов на страницы. REST — через `page`/`per_page` params или Link header; GraphQL — через `edges` и `pageInfo` с cursor-based подходом.
- **Conditional Request**: HTTP-кэширование через `ETag`/`If-None-Match` и `Last-Modified`/`If-Modified-Since`. GitHub возвращает `304 Not Modified` при неизменённых данных — не тратит primary rate limit.
- **Fine-grained PAT**: Токен с ограниченными правами на конкретные репозитории и actions. Рекомендуемый тип PAT, заменяет classic PAT.
- **GitHub App**: Аутентификация через App (JWT → Installation Token) для headless-доступа. Масштабируемые лимиты для Enterprise Cloud.
- **GITHUB_TOKEN**: Встроенный токен в GitHub Actions, scoped к репозиторию. Лимит: 1,000 req/hr (15,000 для Enterprise Cloud).

## Предварительные требования

- **gh CLI** (GitHub CLI) v2.40+ для примеров команд
- **curl** + **jq** для raw HTTP запросов
- **Аутентификация**: Fine-grained PAT (рекомендуется), classic PAT, GitHub App Installation Token, или `GITHUB_TOKEN` в Actions
- **Сеть**: доступ к `api.github.com` (или вашему GES endpoint)

## Архитектура и аутентификация

### Модели аутентификации

```text
┌─────────────────────────────────────────────────────────────┐
│  Fine-grained PAT (рекомендуемый)                          │
│  Classic PAT (legacy)                                       │
│  GitHub App (JWT → Installation Token)                     │
│  OAuth App (user-to-server)                                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
              ┌───────────────────────────────┐
              │ GITHUB_TOKEN (внутри Actions) │
              │ 1,000 req/hr per repo         │
              │ 15,000 req/hr для GHE Cloud   │
              └───────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        │                                       │
REST API (https://api.github.com)         GraphQL API (https://api.github.com/graphql)
Headers:                                   Headers:
  Accept: application/vnd.github+json         Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2026-03-10            Authorization: Bearer <token>
  Authorization: Bearer <token>               Content-Type: application/json
```

### Rate Limit — как это работает (Primary Rate Limits)

#### REST API

| Тип аутентификации | Лимит (req/hour) | Примечания |
|---|---|---|
| Unauthenticated (по IP) | 60 | Только публичные данные |
| Fine-grained / Classic PAT | 5,000 | Per user |
| GitHub App (installation token, не GHE Cloud) | 5,000 | +50/hr за репозиторий >20, +50/hr за пользователя >20, макс 12,500 |
| GitHub App (installation token, GHE Cloud) | 15,000 | Per installation |
| OAuth App (client credentials для public data) | 5,000 | 15,000 для GHE Cloud |
| GITHUB_TOKEN в Actions | 1,000 | Per repository; 15,000 для GHE Cloud |

#### GraphQL API

| Тип аутентификации | Лимит (points/hour) |
|---|---|
| Пользователь (PAT, OAuth, App user token) | 5,000 (10,000 для GHE Cloud) |
| GitHub App Installation (не GHE Cloud) | 5,000 (+50 за repo>20, +50 за user>20, макс 12,500) |
| GitHub App Installation (GHE Cloud) | 10,000 |
| GITHUB_TOKEN в Actions | 1,000 (15,000 для GHE Cloud) |

**Расчёт points для GraphQL (primary):**
1. Сложите количество запросов для каждого уникального connection (предполагая достижение `first`/`last` лимитов)
2. Разделите на **100** и округлите до целого
3. Минимум **1 point** на любой запрос

**Secondary Rate Limits** (общие для REST и GraphQL):
- Max 100 concurrent requests
- Max 900 points/min для REST endpoints, 2,000 points/min для GraphQL endpoint
- Max 90 секунд CPU time / 60 секунд real time (max 60 сек для GraphQL)
- Max 80 content-generating req/min, 500/hr
- Max 2,000 OAuth token requests/hr

**Проверка rate limit:**
- REST: `GET /rate_limit` (не тратит primary limit, может тратить secondary) или response headers `x-ratelimit-*`
- GraphQL: `query { rateLimit { limit remaining used resetAt } }` или headers `x-ratelimit-*`
- **Важно**: headers `x-ratelimit-*` — авторитетный источник, могут отличаться от `/rate_limit` endpoint

**Conditional requests**: если сервер возвращает `ETag`/`Last-Modified`, сохраняйте и отправляйте `If-None-Match`/`If-Modified-Since` — `304 Not Modified` не тратит primary rate limit.

## Практические сценарии

### Сценарий 1: Базовый REST API с pagination

```bash
# 1. Получить список issue с pagination (per_page=100 максимум)
gh api /repos/{owner}/{repo}/issues \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  -f state=open \
  -f per_page=100 \
  --jq '.[] | {number: .number, title: .title, created_at: .created_at}'

# 2. Автоматическая pagination через Link header (следуем rel="next")
page=1
while true; do
  result=$(gh api "/repos/{owner}/{repo}/issues?state=open&per_page=100&page=$page" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2026-03-10" \
    --jq '.[] | "\(.number)\t\(.title)"')
  echo "$result"
  # Проверить Link header на наличие next page
  has_next=$(gh api "/repos/{owner}/{repo}/issues?state=open&per_page=100&page=$page" \
    -I -H "Accept: application/vnd.github+json" \
    --jq '.headers."link"' | grep -o 'rel="next"')
  if [ -z "$has_next" ]; then break; fi
  ((page++))
done
# → ожидаемый вывод: табуляция-разделённые number и title всех open issues
```

### Сценарий 2: GraphQL API — эффективный запрос данных

```bash
# Один GraphQL-запрос вместо 5-ти REST-вызовов
# Расход points: репозитории (1) + issues (100/100=1) + PR (5/100=0→1) = ~3 points
gh api graphql -f query='
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    name
    stargazerCount
    issues(first: 10, states: OPEN) {
      nodes { number title createdAt }
      totalCount
    }
    pullRequests(first: 5, states: MERGED) {
      nodes { number title mergedAt }
    }
  }
}
' -f owner='owner' -f name='repo' \
  -H "X-GitHub-Api-Version: 2026-03-10"
# → ожидаемый вывод: JSON с repository.name, stargazerCount, issues.nodes[], pullRequests.nodes[]
```

### Сценарий 3: Conditional requests с ETag (экономия rate limit)

```bash
# 1. Первый запрос — получаем ETag и Last-Modified
response=$(gh api /repos/{owner}/{repo} -I \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10")
etag=$(echo "$response" | grep -i '^etag:' | cut -d' ' -f2 | tr -d '\r')
last_modified=$(echo "$response" | grep -i '^last-modified:' | cut -d' ' -f2- | tr -d '\r')
# → eTag: "abc123def456..."  Last-Modified: Wed, 25 Oct 2023 19:17:59 GMT

# 2. Повторный запрос с If-None-Match (или If-Modified-Since)
updated=$(gh api /repos/{owner}/{repo} \
  -H "If-None-Match: $etag" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10")
# → 304 Not Modified (если не изменился) — НЕ тратит primary rate limit
# → 200 OK с новыми данными (если изменился) — тратит 1 request
```

### Сценарий 4: Управление rate limit (primary + secondary)

```bash
# Проверить текущий статус primary rate limit через headers (авторитетный источник)
gh api /rate_limit -I --jq '.headers | {limit: ."x-ratelimit-limit", remaining: ."x-ratelimit-remaining", reset: ."x-ratelimit-reset", resource: ."x-ratelimit-resource"}'
# → { "limit": "5000", "remaining": "4872", "reset": "1760187600", "resource": "core" }

# GraphQL rate limit check
gh api graphql -f query='{ rateLimit { limit remaining used resetAt } }'
# → { "limit": 5000, "remaining": 4950, "used": 50, "resetAt": "2026-10-11T13:00:00Z" }

# Если remaining < 100 — circuit breaker: пауза до reset
# Для secondary rate limits: пауза 1+ сек между mutative запросами, избегайте >100 concurrent
```

### Сценарий 5: Аутентификация через Fine-grained PAT

```bash
# Создать fine-grained PAT через UI: Settings → Developer settings → Fine-grained tokens → Generate new token
# Права: Repository access (select repos), Permissions (minimal needed: Contents read, Issues read, etc.)

# Использовать для скриптов
export GH_TOKEN="ghp_xxxxxxxxxxxx"  # fine-grained PAT
gh api /user --jq '.login'  # аутентифицированный запрос
# → "your-username"

# В workflow (.github/workflows/api-call.yml)
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check repo info via API
        run: |
          gh api /repos/${{ github.repository }} \
            -H "X-GitHub-Api-Version: 2026-03-10" \
            --jq '.stargazer_count'
        env:
          GH_TOKEN: ${{ secrets.FINE_GRAINED_PAT }}  # используйте secrets, не vars!
```

### Сценарий 6: Аутентификация через GitHub App (для production/headless)

```bash
# 1. Создать JWT для App (App-level, exp < 10 min)
# (см. [github_apps.md](./github_apps.md) для полной инструкции)
JWT=$(jwt encode \
  --secret @private-key.pem \
  --alg RS256 \
  --sub APP_ID \
  --exp "10 minutes")

# 2. Получить Installation Token (valid 1 hour)
INSTALL_TOKEN=$(curl -s -X POST \
  -H "Authorization: Bearer $JWT" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/app/installations/12345/access_tokens \
  | jq -r .token)

# 3. Использовать токен для API (REST или GraphQL)
gh api -H "Authorization: Bearer $INSTALL_TOKEN" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  /repos/{owner}/{repo} --jq '.name'
# → "repo-name"
```

### Сценарий 7: Bulk операции с pagination + GraphQL (cursor-based)

```bash
# GraphQL с pagination (используя cursor) — эффективнее для больших выборок
# first: 100, after: cursor
gh api graphql -f query='
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $after, states: OPEN) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url }
    }
  }
}
' -f owner='owner' -f name='repo' -F after=null
# → первый запрос: after=null, получаем pageInfo.endCursor
# В цикле, пока pageInfo.hasNextPage = true,
# подставлять endCursor как $after в следующем запросе
```

### Сценарий 8: REST API pagination через Link header (robust production pattern)

```bash
# Production-ready pagination: парсим Link header, следуем rel="next"
fetch_all_pages() {
  local url="$1"
  local results=()
  
  while [ -n "$url" ]; do
    response=$(gh api "$url" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2026-03-10" \
      -I --jq '.')
    
    # Extract data from body
    body=$(echo "$response" | sed -n '/^{/,/^}/p')
    results+=("$body")
    
    # Extract next page URL from Link header
    link=$(echo "$response" | grep -i '^link:' | head -1)
    if echo "$link" | grep -q 'rel="next"'; then
      url=$(echo "$link" | sed -n 's/.*<\([^>]*\)>; rel="next".*/\1/p')
    else
      url=""
    fi
  done
  
  printf '%s\n' "${results[@]}"
}

# Usage
fetch_all_pages "/repos/{owner}/{repo}/issues?state=open&per_page=100" | jq -s 'add'
```

## Команды и API-операции

### REST API — ключевые endpoint-ы

| Категория | Endpoint | Описание |
|---|---|---|
| Repositories | `GET /repos/{owner}/{repo}` | Инфо о репозитории |
| Issues | `GET /repos/{owner}/{repo}/issues` | Список issue |
| Pull Requests | `GET /repos/{owner}/{repo}/pulls` | Список PR |
| Commits | `GET /repos/{owner}/{repo}/commits` | Список коммитов |
| Actions | `GET /repos/{owner}/{repo}/actions/runs` | Workflow runs |
| Runners | `GET /repos/{owner}/{repo}/actions/runners` | Self-hosted runners |
| Alerts | `GET /repos/{owner}/{repo}/dependabot/alerts` | Dependabot alerts |
| Contents | `GET /repos/{owner}/{repo}/contents/{path}` | Чтение файла |
| Branches | `GET /repos/{owner}/{repo}/branches` | Список веток |
| Rate Limit | `GET /rate_limit` | Статус rate limit (не тратит primary) |
| Meta | `GET /meta` | IP ranges для Actions runners, Git, etc. |

**Обязательные заголовки для REST API:**
```
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2026-03-10
Authorization: Bearer <token>
```

### GraphQL API

```graphql
# Получить репозиторий + issues + последние PR за один запрос
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    name
    stargazerCount
    issues(first: 10, states: OPEN) {
      totalCount
      nodes { number title createdAt }
    }
    pullRequests(first: 5, states: MERGED) {
      nodes { number title mergedAt }
    }
  }
  # Rate limit info
  rateLimit {
    limit
    remaining
    used
    resetAt
  }
}
```

### Пагинация

**REST** (Link header + query params):
| Параметр | Описание |
|---|---|
| `page` | Номер страницы (начиная с 1) |
| `per_page` | Кол-во элементов на странице (max 100, значения >100 автоматически урезаются до 100) |
| `Link` header | Ссылки на `next`, `prev`, `first`, `last` страницы. **Авторитетный способ** навигации. |
| `before`/`after` | Для некоторых endpoints (например, commits) вместо `page` |

**GraphQL** (cursor-based, Relay spec):
| Параметр | Описание |
|---|---|
| `first:` | Кол-во элементов с начала (1-100) |
| `after: "<cursor>"` | Cursor для forward pagination (из `pageInfo.endCursor`) |
| `last:` | Кол-во элементов с конца (1-100) |
| `before: "<cursor>"` | Cursor для backward pagination |
| `pageInfo.hasNextPage` | Есть ли следующая страница |
| `pageInfo.endCursor` | Cursor конца текущей страницы |
| `pageInfo.hasPreviousPage` / `startCursor` | Для backward pagination |

**Важно:** GraphQL требует `first` или `last` на любом connection. Максимум 500,000 nodes на один запрос.

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `403 rate limit exceeded` + `x-ratelimit-remaining: 0` | Превышен primary rate limit | Использовать conditional requests (ETag/Last-Modified); добавить `sleep` до `x-ratelimit-reset`; использовать GraphQL; увеличить `per_page` до 100; для Enterprise — GitHub App |
| `403` / `429` с `retry-after` | Secondary rate limit (concurrent, points/min, CPU time, content creation) | Пауза `retry-after` секунд; экспоненциальный backoff; сериализовать запросы; пауза 1с между mutative запросами |
| `401 Bad credentials` | PAT истёк, неверный, или неверный тип токена | Обновить токен; `gh auth login`; для App — refresh JWT; проверить формат `Bearer <token>` |
| `404 Not Found` на существующем ресурсе | Токен не имеет нужного scope или репо приватный/внутри организации с SSO | Проверить Fine-grained PAT права (repository access + permissions); для private repo с SSO — авторизовать токен в SSO; `visibility=internal` в search API |
| `422 Validation Failed` | Неверные параметры запроса / JSON body | Проверить `Content-Type: application/json`; валидность JSON; required поля; enum значения |
| GraphQL `null` в поле с `errors` | Нет прав на поле (scope) или поле deprecated | Добавить scope в токен; проверить schema introspection; обновить запрос под текущую схему |
| `409 Conflict` при создании | Ресурс уже существует | DELETE → recreate, или использовать upsert паттерн (PATCH если поддерживается) |
| `410 Gone` на endpoint | API версия устарела, endpoint удалён | Обновить `X-GitHub-Api-Version` на поддерживаемую; проверить [API versions](https://docs.github.com/en/rest/overview/api-versions) |
| Pagination "застревает" / дубликаты | `per_page` > 100 (авто-урезание), или неверный парсинг Link header | Использовать `per_page=100` максимум; следовать Link header cursor; не конструировать URL вручную |
| `502` / `504` timeout | Запрос >10 сек (GraphQL) или сервер перегружен | Упростить запрос (меньше `first`, меньше nesting); повторить позже; проверить githubstatus.com |

## Валидация и проверка результатов

После выполнения API-запросов проверяйте:

```bash
# 1. HTTP status code
gh api /repos/{owner}/{repo} -I --jq '.headers | .status'
# → ожидается: "200 OK" или "304 Not Modified"

# 2. Rate limit headers
gh api /repos/{owner}/{repo} -I --jq '.headers | {remaining: ."x-ratelimit-remaining", reset: ."x-ratelimit-reset"}'
# → remaining > 0, reset в будущем

# 3. Conditional request success
gh api /repos/{owner}/{repo} -H "If-None-Match: $etag" -I --jq '.headers.status'
# → "304 Not Modified" = успех кэширования, rate limit не потрачен

# 4. GraphQL errors в ответе 200
gh api graphql -f query='{ viewer { login } }' --jq '.errors // "no errors"'
# → "no errors" или массив ошибок с message/path/extensions
```

## Лучшие практики

1. **Fine-grained PAT вместо classic PAT**: granular права, ограниченная область действия (конкретные репозитории), auto-expiry (30/60/90 дней или custom).

2. **Conditional requests с ETag/Last-Modified**: экономит primary rate limit при частых запросах к неизменяющимся данным. `304 Not Modified` не тратит лимит.

3. **GraphQL для связанных данных**: один запрос вместо N REST-вызовов — экономит rate limit и время. Используйте `rateLimit { cost }` для предсказания стоимости.

4. **Pagination `per_page=100` (REST) / `first: 100` (GraphQL)**: минимизирует количество запросов при больших выборках. Следуйте `Link` header / `pageInfo` cursor.

5. **Circuit breaker для primary rate limit**: если `x-ratelimit-remaining < 100`, пауза до `x-ratelimit-reset`.

6. **Secondary rate limits avoidance**: 
   - Пауза ≥1 сек между `POST`/`PATCH`/`PUT`/`DELETE` запросами
   - Избегайте >100 concurrent запросов
   - Очередь запросов вместо параллельности

7. **GITHUB_TOKEN внутри Actions**: используйте `${{ secrets.GITHUB_TOKEN }}` (автоматически создаётся) для API-вызовов внутри workflow — не нужен PAT. Лимит: 1,000/hr (15,000 GHE Cloud).

8. **GitHub App для production/headless**: Installation Token — предпочтительнее PAT. Масштабируемые лимиты (до 15,000/hr для GHE Cloud), короткий TTL (1 час), revocable.

9. **API versioning**: для REST используйте заголовок `X-GitHub-Api-Version: 2026-03-10` (текущая). `Accept: application/vnd.github+json` обязателен. Для GES — соответствующая версия.

10. **Webhooks вместо polling**: подпишитесь на webhook events вместо опроса API — экономит rate limit, даёт real-time уведомления.

11. **Не парсите URLs вручную**: используйте поля `number`, `id`, `html_url` из ответа. Link header — единственный способ навигации pagination.

12. **Обработка 404 для приватных ресурсов**: GitHub возвращает 404 вместо 403 для приватных ресурсов без доступа. Сначала проверьте аутентификацию/авторизацию.

## Edge Cases и ограничения

- **GraphQL node limit**: 500,000 nodes на запрос. При превышении — partial results + error.
- **GraphQL timeout**: 10 секунд max. При timeout — 502/504, points списываются в следующем часе.
- **REST `per_page` > 100**: не ошибка, автоматически урезается до 100. Можно получить меньше результатов чем ожидаете.
- **Link header `last` отсутствует**: для некоторых endpoints (большие коллекции) `last` не рассчитывается. Используйте `rel="next"` до конца.
- **Rate limit headers варьируются**: GitHub обрабатывает запросы в разных регионах, `x-ratelimit-remaining` может отличаться между ответами. Доверяйте headers, не `/rate_limit` endpoint.
- **Search API特殊limits**: `GET /search/*` имеют более строгие лимиты (30 req/min для authenticated).
- **Git LFS отдельный bucket**: 300 req/min (unauth), 3,000 req/min (auth) — отдельно от REST API.
- **Enterprise Server API lag**: GES 3.22 соответствует REST API ~2022-11-28 или старше. Проверяйте changelog вашей версии.

## Дополнительная информация

- **[GitHub CLI](./github_cli.md)** — `gh api` для REST и GraphQL запросов из терминала.
- **[GitHub Apps](./github_apps.md)** — JWT, Installation Token, аутентификация для integration-приложений.
- **[GitHub Enterprise Admin](./github_enterprise_admin.md)** — SCIM, SSO, IP allowlist для enterprise-уровня API.
- **[GitHub Webhooks](./github_webhooks.md)** — настройка webhooks вместо polling.
- **Официальная документация**: 
  - [REST API](https://docs.github.com/en/rest) — endpoints, guides, best practices
  - [GraphQL API](https://docs.github.com/en/graphql) — schema, guides, rate limits
  - [API Versions](https://docs.github.com/en/rest/overview/api-versions) — поддерживаемые версии, breaking changes
  - [Rate Limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) — primary/secondary limits
  - [Pagination](https://docs.github.com/en/rest/guides/using-pagination-in-the-rest-api) — Link header, per_page
  - [Best Practices](https://docs.github.com/en/rest/guides/best-practices-for-using-the-rest-api) — conditional requests, webhooks, caching
