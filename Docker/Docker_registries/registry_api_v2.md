# Registry HTTP API v2: прямая работа с реестром

**Актуально для:** OCI Distribution Spec 1.0/1.1, Docker 24.x–29.x, Harbor 2.11+, GitLab Registry 16.6+, skopeo v1.14+–v1.23+

## Предварительные требования

Перед выполнением практических сценариев убедитесь, что окружение готово:

- **Доступ к реестру**: публичный (Docker Hub, GHCR) или приватный (Harbor, GitLab Registry, Nexus). Для приватных — учётные данные (`REGISTRY_USER` / `REGISTRY_PASS`).
- **Утилиты**: `curl` (HTTP-запросы), `jq` (парсинг JSON), `base64` (Basic Auth). Опционально: `skopeo` ≥ 1.14, `crane` (daemonless-альтернативы).
- **Сетевой доступ** к реестру по HTTPS (443). Для air-gapped — настроенный прокси или локальный реестр.
- **Базовые навыки**: HTTP-методы (GET/POST/PUT/PATCH/DELETE), заголовки `Authorization`, JSON.

## Определения

- **Registry API v2** — REST API реестра контейнеров, определённый [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec). Эндпоинты вида `/v2/<name>/...` для операций с манифестами, blobs и тегами. Реализован всеми OCI-совместимыми реестрами (Docker Hub, Harbor, GitLab, Nexus, ECR, GHCR).
- **Token Auth (Bearer)** — схема аутентификации: клиент сначала получает токен от сервера авторизации (auth server), затем отправляет его в заголовке `Authorization: Bearer <token>`. Используется Docker Hub, GHCR, Harbor (опционально), GitLab.
- **Basic Auth** — схема аутентификации: логин:пароль, закодированные в base64, в заголовке `Authorization: Basic <base64>`. Используется приватными реестрами (Harbor, Nexus) и `docker login`.
- **WWW-Authenticate** — HTTP-заголовок в ответе `401`, указывающий клиенту, какой auth server и scope использовать. Именно его парсит `docker`/`containerd` при pull из приватного реестра.
- **Scope** — строка прав доступа в token auth: `repository:<name>:<actions>`, где actions — `pull`, `push`, `*`. Токен выдаётся на конкретный scope; без нужного scope операция отклоняется с `DENIED`.
- **Blob** — content-addressable объект (слой или config), адресуемый SHA256-дайджестом. Операции: `GET` (скачать), `HEAD` (проверить существование), `POST`/`PATCH`/`PUT` (загрузить).
- **Manifest** — JSON-документ, описывающий образ. Операции: `GET` (получить), `PUT` (записать/перезаписать), `DELETE` (удалить — не все реестры поддерживают).
- **Rate Limit** — политика реестра, ограничивающая количество pull-операций за период. Docker Hub: 100 pull/6h (анонимный), 200 pull/6h (авторизованный бесплатный), 5000 pull/6h (Pro). При превышении — `429 Too Many Requests`.
- **Pull-Through Cache** — режим реестра (Harbor Proxy Cache, Nexus docker-proxy), при котором запросы к upstream-реестру проксируются и кэшируются локально. Снижает задержку, экономит трафик и защищает от rate limiting.

## Основные концепции

### Поток аутентификации (как работает `docker login` и pull)

При обращении к приватному реестру (или Docker Hub) клиент выполняет **двухфазный** обмен:

```text
Клиент                          Реестр                    Auth Server
  │                                │                            │
  ├─ GET /v2/ ───────────────────►│                            │
  │◄── 401 + WWW-Authenticate ────│                            │
  │    (realm, service, scope)     │                            │
  │                                │                            │
  ├─ GET <realm>?service=...&scope=... ──────────────────────►│
  │◄── 200 + {"token": "..."} ─────────────────────────────────│
  │                                │                            │
  ├─ GET /v2/<name>/manifests/<ref> ─►│                       │
  │    Authorization: Bearer <token>  │                       │
  │◄── 200 + manifest ──────────────│                            │
```

1. **Пробный запрос** `GET /v2/` — проверка поддержки API v2. Анонимный доступ даёт `200 {}`; требующий авторизации — `401` с заголовком `WWW-Authenticate: Bearer realm="https://auth.docker.io/token",service="registry.docker.io"`.
2. **Запрос токена** — клиент обращается к `realm` (auth server) с параметрами `service` и `scope`. Для Docker Hub: `https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull`.
3. **Авторизованный запрос** — повторный запрос к реестру с `Authorization: Bearer <token>`.

**Basic Auth** (приватные реестры): `docker login` сохраняет credentials в `~/.docker/config.json`; клиент отправляет `Authorization: Basic base64(user:pass)` напрямую, без отдельного auth server.

### Эндпоинты Registry API v2

| Эндпоинт | Метод | Назначение |
| :--- | :--- | :--- |
| `/v2/` | GET | Проверка поддержки API v2 |
| `/v2/<name>/tags/list` | GET | Список тегов репозитория |
| `/v2/<name>/manifests/<reference>` | GET | Получить манифест (по тегу или дайджесту) |
| `/v2/<name>/manifests/<reference>` | PUT | Записать/перезаписать манифест |
| `/v2/<name>/manifests/<reference>` | DELETE | Удалить манифест (не все реестры) |
| `/v2/<name>/blobs/<digest>` | GET | Скачать blob (слой/config) |
| `/v2/<name>/blobs/<digest>` | HEAD | Проверить существование blob (без скачивания) |
| `/v2/<name>/blobs/uploads/` | POST | Начать загрузку blob (монолитный или chunked) |
| `/v2/<name>/blobs/uploads/<uuid>` | PATCH | Загрузить фрагмент blob (chunked) |
| `/v2/<name>/blobs/uploads/<uuid>?digest=<digest>` | PUT | Завершить загрузку blob |

`<name>` — полный путь репозитория: `library/nginx`, `myproject/app`. `<reference>` — тег (`1.27`) или дайджест (`sha256:...`).

### Коды ошибок

Реестр возвращает JSON с массивом `errors`:

```json
{"errors": [{"code": "MANIFEST_UNKNOWN", "message": "manifest unknown", "detail": {...}}]}
```

| Код | HTTP | Значение | Типичная причина |
| :--- | :--- | :--- | :--- |
| `UNAUTHORIZED` | 401 | Требуется авторизация | Нет/просрочен токен, неверный scope |
| `DENIED` | 403 | Доступ запрещён | Нет прав на scope (pull vs push), неверный пользователь |
| `NAME_UNKNOWN` | 404 | Репозиторий не существует | Опечатка в имени, нет push-прав |
| `MANIFEST_UNKNOWN` | 404 | Манифест не найден | Неверный тег/дайджест, тег удалён |
| `BLOB_UNKNOWN` | 404 | Blob не найден | Слой удалён GC, неверный дайджест |
| `TAG_INVALID` | 400 | Невалидный тег | Некорректный формат тега |
| `SIZE_INVALID` | 400 | Невалидный размер | Размер blob не совпадает с заявленным |
| `DIGEST_INVALID` | 400 | Невалидный дайджест | Дайджест не совпадает с содержимым |
| `UNSUPPORTED` | 405 | Операция не поддерживается | DELETE манифеста отключён в реестре |

### Rate Limiting (Docker Hub)

Docker Hub ограничивает анонимные и авторизованные pull-ы. Заголовки ответа:

```bash
curl -I https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → HTTP/2 200
# → RateLimit-Limit: 200;w=21600
# → RateLimit-Remaining: 187
# → RateLimit-Reset: 1724342400
```

- `RateLimit-Limit` — максимум запросов за окно (`w` — окно в секундах, 21600 = 6 часов).
- `RateLimit-Remaining` — остаток.
- `RateLimit-Reset` — Unix-time сброса окна.
- При превышении — `429 Too Many Requests` с `Retry-After`.

**Решения:** `docker login` (увеличивает лимит), pull-through cache (Harbor Proxy Cache), локальное зеркало.

## Практические сценарии

### Сценарий 1: Проверка доступности и поддержки API v2

Первый шаг диагностики — отделить проблемы сети/TLS от проблем авторизации.

```bash
# Анонимный доступ
curl -s https://registry-1.docker.io/v2/
# → {} (пустой JSON = API v2 поддерживается)

# Приватный реестр (Basic Auth)
curl -s -u "$REGISTRY_USER:$REGISTRY_PASS" https://harbor.local/v2/
# → {}

# С TLS-проблемой
curl -v https://harbor.local/v2/ 2>&1 | grep -E "SSL|certificate"
# → SSL certificate problem: self signed certificate (→ добавить --insecure или CA)
```

**Валидация:** `200 {}` — реестр доступен и поддерживает API v2. `401` с `WWW-Authenticate` — нужна авторизация. Ошибка SSL/TLS — проблема сертификата, не реестра.

### Сценарий 2: Token auth — получение и использование токена

Полный цикл для Docker Hub (аналогично для GHCR, Harbor с token auth).

```bash
# 1. Получить токен для pull
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)

# 2. Использовать токен для запроса манифеста
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" \
  https://registry-1.docker.io/v2/library/nginx/manifests/1.27 | jq '{schemaVersion, mediaType, manifests: [.manifests[]? | {platform: .platform, digest}]}'
# → {
# →   "schemaVersion": 2,
# →   "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
# →   "manifests": [{"platform": {"architecture": "amd64", "os": "linux"}, "digest": "sha256:..."}]
# → }

# 3. Проверить rate limit
curl -sI -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/1.27 | grep -i ratelimit
# → RateLimit-Limit: 200;w=21600
# → RateLimit-Remaining: 187
```

**Валидация:** токен — JWT (три части, разделённые точками); манифест возвращается с `200`; заголовки `RateLimit-*` присутствуют.

### Сценарий 3: Список тегов репозитория

```bash
# Docker Hub (через токен)
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://registry-1.docker.io/v2/library/nginx/tags/list?n=10" | jq '{name, tags: .tags[:10]}'
# → {"name": "library/nginx", "tags": ["1.27", "1.27-alpine", "1.27-slim", ...]}

# Приватный реестр (Basic Auth)
curl -s -u "$REGISTRY_USER:$REGISTRY_PASS" \
  "https://harbor.local/v2/myproject/app/tags/list" | jq .tags
# → ["v1.2.3", "v1.2.4", "sha-9f3a1c2", "production"]
```

**Валидация:** JSON содержит `name` и массив `tags`. Пагинация — параметры `n` (количество) и `last` (последний тег предыдущей страницы).

### Сценарий 4: Получение и удаление манифеста

```bash
# Получить манифест по дайджесту (детерминированно)
DIGEST="sha256:f6a02b669bf8e59b20d361e148045a5f15915a7704b4df915340156f4a883a45"
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.manifest.v1+json" \
  "https://registry-1.docker.io/v2/library/nginx/manifests/$DIGEST" | jq '{config, layers}'

# Удалить манифест (Harbor, если включён DELETE)
curl -s -X DELETE -u "$REGISTRY_USER:$REGISTRY_PASS" \
  "https://harbor.local/v2/myproject/app/manifests/$DIGEST"
# → 202 Accepted (Harbor) или 405/UNSUPPORTED (если DELETE отключён)
```

**Валидация:** `GET` по дайджесту возвращает тот же манифест, что и по тегу (если тег указывает на этот дайджест). `DELETE` поддерживается не всеми реестрами (Docker Hub не поддерживает; Harbor — при включённой опции).

### Сценарий 5: Проверка существования blob (HEAD)

Экономит трафик — проверяет наличие слоя без скачивания.

```bash
# HEAD запрос к blob
curl -sI -H "Authorization: Bearer $TOKEN" \
  "https://registry-1.docker.io/v2/library/nginx/blobs/sha256:9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0"
# → HTTP/2 200
# → Content-Length: 32654
# → Docker-Content-Digest: sha256:9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0

# Несуществующий blob
curl -sI -H "Authorization: Bearer $TOKEN" \
  "https://registry-1.docker.io/v2/library/nginx/blobs/sha256:0000000000000000000000000000000000000000000000000000000000000000"
# → HTTP/2 404
# → {"errors":[{"code":"BLOB_UNKNOWN","message":"blob unknown to registry",...}]}
```

**Валидация:** `200` + `Docker-Content-Digest` — blob существует; `404` + `BLOB_UNKNOWN` — blob удалён или дайджест неверен.

### Сценарий 6: Отладка авторизации (401/403)

Когда `docker pull` падает с `unauthorized` — диагностика через API напрямую.

```bash
# 1. Проверить, что реестр требует auth
curl -sI https://harbor.local/v2/ | grep -i www-authenticate
# → WWW-Authenticate: Bearer realm="https://harbor.local/service/token",service="harbor-registry"

# 2. Получить токен с правильным scope
TOKEN=$(curl -s -u "$REGISTRY_USER:$REGISTRY_PASS" \
  "https://harbor.local/service/token?service=harbor-registry&scope=repository:myproject/app:pull" | jq -r .token)

# 3. Проверить, что токен валиден (декодировать JWT payload)
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{access, expiration}'
# → {"access": [{"type": "repository", "name": "myproject/app", "actions": ["pull"]}], "expiration": 1724342400}

# 4. Если 403 DENIED — scope не включает нужное действие
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://harbor.local/v2/myproject/app/manifests/latest"
# → {"errors":[{"code":"DENIED","message":"requested access to the resource is denied"}]}
# → Решение: запросить scope с push или проверить права пользователя в Harbor
```

**Валидация:** JWT payload содержит `access` с нужным `actions` (`pull`/`push`). `DENIED` при валидном токене — проблема прав пользователя, не токена.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `401 UNAUTHORIZED` без `WWW-Authenticate` | Реестр требует Basic Auth | Используйте `-u user:pass` или `docker login` |
| `401 UNAUTHORIZED` с `WWW-Authenticate: Bearer` | Нет токена или просрочен | Получите токен от `realm` с правильным `scope` |
| `403 DENIED` при валидном токене | Нет прав на scope | Проверьте `actions` в JWT; запросите `push` или права в реестре |
| `404 MANIFEST_UNKNOWN` | Неверный тег/дайджест | `curl .../tags/list` для актуальных тегов; проверьте дайджест |
| `404 BLOB_UNKNOWN` | Слой удалён GC | Перепушьте образ; проверьте retention policy реестра |
| `429 Too Many Requests` | Превышен rate limit Docker Hub | `docker login`, pull-through cache, локальное зеркало; проверьте `RateLimit-Remaining` |
| `405 UNSUPPORTED` на DELETE | Реестр не поддерживает удаление | Harbor: включите DELETE в project settings; Docker Hub не поддерживает |
| `SSL certificate problem` | Самоподписанный/просроченный сертификат | Добавьте CA в систему или `--insecure` (только для тестов) |
| `x509: certificate signed by unknown authority` | CA реестра не в системном хранилище | Установите CA: `cp ca.crt /usr/local/share/ca-certificates/ && update-ca-certificates` |
| Пустой `tags` при `tags/list` | Репозиторий существует, но тегов нет или нет прав на list | Проверьте `NAME_UNKNOWN` vs пустой список; проверьте scope `pull` |

## Рекомендации и очистка

**Лучшие практики:**
- Для диагностики pull-ошибок начинайте с `curl -sI /v2/` — это отделяет сетевые/TLS-проблемы от проблем авторизации и реестра.
- Всегда проверяйте `RateLimit-Remaining` при массовых pull-ах в CI — исчерпание лимита Docker Hub ломает пайплайны непредсказуемо.
- Для приватных реестров используйте pull-through cache (Harbor Proxy Cache) — это снимает rate limiting, снижает задержку и даёт локальный контроль над артефактами.
- При отладке `401/403` декодируйте JWT-токен (`cut -d. -f2 | base64 -d`) — это показывает, какой `scope` и `actions` реально выданы, и экономит время на поиск проблем прав.
- Не используйте `DELETE` манифестов как способ очистки — поддержка зависит от реестра; предпочтительнее retention policy и GC (Harbor).
- Для daemonless-операций (CI-раннеры без Docker-демона) используйте `skopeo`/`crane` — они реализуют Registry API v2 напрямую и не требуют `docker login`.

**Очистка окружения:**
```bash
# Сбросить сохранённые credentials (если тестировали docker login)
docker logout registry.example.com
# → Removing login credentials for registry.example.com
```

## Особые случаи и ограничения

- **DELETE манифеста**: поддерживается Harbor (при включённой опции), GitLab Registry, Nexus; **не поддерживается** Docker Hub и GHCR. Удаление манифеста не освобождает blobs — они удаляются только GC реестра.
- **PUT манифеста**: требует, чтобы все referenced blobs (config + layers) уже были загружены в реестр; иначе — `BLOB_UNKNOWN`. Это основа `docker push`: сначала blobs, потом манифест.
- **Chunked upload** (`POST` → `PATCH` → `PUT`): нужен для больших blobs (>некоторого порога) или ненадёжных сетей; монолитный `POST` + `PUT?digest=` — для малых. `skopeo`/`crane` выбирают автоматически.
- **Token expiry**: токены краткоживущие (обычно 1–24 часа). CI-пайплайны должны запрашивать токен на каждый job, а не кэшировать надолго.
- **Scope granularity**: токен выдаётся на конкретный `repository:<name>:<actions>`; один токен не даёт прав на другие репозитории. Для нескольких репозиториев — несколько scope в одном запросе (`scope=repository:a:pull&scope=repository:b:pull`).
- **OCI 1.1 Referrers**: эндпоинт `/v2/<name>/referrers/<digest>` (GET) возвращает аттестации (SBOM, provenance), прикреплённые к манифесту. Поддерживается Harbor 2.11+, GHCR, GitLab 16.6+.
- **Kubernetes pull**: kubelet обращается к реестру напрямую из host network namespace — NetworkPolicy пода **не влияет** на pull; влияют только правила хоста. Полная цепочка pull-операции (kubelet → CRI → registry) описана в **[Ошибках загрузки образов](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)**.

## Примечания по версиям

- **OCI Distribution Spec 1.0**: базовая спецификация (endpoints, auth, blobs, manifests). Поддерживается всеми современными реестрами.
- **OCI Distribution Spec 1.1**: добавлены Referrers API, OCI Artifacts, zstd. Поддерживается Harbor 2.11+, GHCR, GitLab 16.6+.
- **Docker Hub rate limits**: 100 pull/6h (анонимный), 200 pull/6h (авторизованный бесплатный), 5000 pull/6h (Pro). Проверяйте заголовки `RateLimit-*`.
- **`skopeo` ≥ 1.14**: daemonless-реализация Registry API v2; `skopeo inspect`, `skopeo copy`, `skopeo delete` (где поддерживается).

## Дополнительная информация

- **Спецификация**: [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec) — полный reference эндпоинтов, auth flow, error codes.
- **Структура образа** (manifest, config, layers, media types) — **[OCI Image Spec: структура образа изнутри](../Docker_fs/images/oci_image_spec.md)**.
- **Pull lifecycle в Kubernetes** (kubelet → CRI → registry, imagePullSecrets, image GC) — **[Ошибки загрузки образов](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)**.
- **Daemonless-операции с образами** (`skopeo`, `crane`) — **[Перенос и экспорт образов](../Docker_fs/images/diagnostics_transfer.md)**.
- **Harbor** (установка, GC, retention, replication) — **[Harbor: обзор реестра](../Docker_registries/Harbor/overview.md)**.

### См. также

- **[Основы Docker-образов](../Docker_fs/images/docker_images_basics.md)** — теги, дайджесты, манифесты на уровне Docker CLI.
- **[Версионирование и тегирование образов](../Docker_registries/image_versioning_and_tagging.md)** — стратегии именования.
- **[Реестры Docker](../docker_registries.md)** — обзор реестров и выбор.
