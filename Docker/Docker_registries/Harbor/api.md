# Harbor: REST API

**Актуально для:** Harbor 2.15.x (2.15.2 — текущий релиз, 2.15.3-rc2 — кандидат)

## Определения

* **Harbor API v2.0**: REST API управления Harbor — проекты, артефакты, пользователи, робот-аккаунты, репликация, GC, аудит-логи. Base URL: `/api/v2.0`.
* **Swagger UI (API Explorer)**: Интерактивная документация и тестовый клиент API, встроенный в Harbor Portal.
* **Пагинация**: Механизм разбиения списковых ответов: параметры `page` и `page_size`, заголовки `X-Total-Count` и `Link`.
* **Basic Auth**: Схема аутентификации API — `Authorization: Basic base64(user:password)`. Для автоматизации используется робот-аккаунт (`robot$<project>+<name>`).
* **X-Request-Id**: Заголовок трассировки запроса — передаётся в ответе, используется для поиска в логах Harbor.

## Основные концепции

### Доступ к API

| Способ | URL | Особенности |
| :--- | :--- | :--- |
| **Из Portal** | Кнопка **Harbor API** внизу левого меню | Запросы выполняются от имени текущей сессии |
| **Напрямую** | `https://<harbor_host>/devcenter-api-2.0` | Swagger UI; кнопка **Authorize** — Basic Auth |
| **Спецификация** | `api/v2.0/swagger.yaml` в репозитории goharbor/harbor | Офлайн-просмотр в Swagger Editor |

### Пагинация

Все списковые эндпоинты принимают `page` (номер страницы, начинается с 1) и `page_size` (размер страницы, **по умолчанию 10, максимум 100**), а также `sort` и `q` (фильтр). Ответ содержит заголовки:

* `X-Total-Count` — общее число записей;
* `Link` — URL предыдущей и следующей страницы.

### Аутентификация

```bash
# Пользователь
curl -sk -u "admin:$HARBOR_ADMIN_PASS" "https://harbor.corp.local/api/v2.0/projects"

# Робот-аккаунт (рекомендуется для CI/CD)
curl -sk -u 'robot$production+ci-bot:$ROBOT_SECRET' \
  "https://harbor.corp.local/api/v2.0/projects/production/repositories"
```

## Практические сценарии

### Сценарий 1: Swagger UI

1. Откройте `https://harbor.corp.local/devcenter-api-2.0`.
2. **Authorize** → введите `username:password` (или логин/секрет робот-аккаунта) → **Authorize** → **Close**.
3. Разверните нужную группу эндпоинтов (project, artifact, auditlog, retention, system) и выполните запрос прямо из UI — ответ и curl-команда видны сразу.

### Сценарий 2: Пагинация (паттерн для скриптов)

```bash
# Сбор всех проектов с учётом пагинации
PAGE=1
while :; do
  RESP=$(curl -sk -u "admin:$PASS" \
    "https://harbor.corp.local/api/v2.0/projects?page=$PAGE&page_size=100")
  echo "$RESP" | jq -r '.[].name'
  COUNT=$(echo "$RESP" | jq 'length')
  [ "$COUNT" -lt 100 ] && break
  PAGE=$((PAGE + 1))
done

# Заголовки пагинации
curl -skI -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects?page=1&page_size=2" | \
  grep -iE "x-total-count|link"
# → X-Total-Count: 42
# → Link: <...page=2&page_size=2>; rel="next"
```

### Сценарий 3: Типовые операции

```bash
# --- Проекты ---
# Список проектов с фильтром по имени
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects?name=myproject" | jq '.[].name'

# Проверка, что имя проекта свободно (HEAD)
curl -skI -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects?project_name=myproject"
# → 404 — имя свободно; 200 — занято

# Создание приватного проекта
curl -sk -u "admin:$PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/projects" \
  -H "Content-Type: application/json" \
  -d '{"project_name":"staging","public":false}'
# → 201 Created

# --- Артефакты ---
# Список артефактов с тегами и обзором сканирования
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?with_tag=true&with_scan_overview=true" | \
  jq '.[] | {digest, tags: [.tags[].name]}'

# Фильтры q для артефактов (синтаксис из swagger.yaml):
#   tags=*        — только тегированные
#   tags=nil      — только без тегов
#   tags=~v       — нечёткое совпадение тега "v"
#   tags=v        — точное совпадение тега
#   labels=(1,2)  — артефакты с обоими лейблами (по ID)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?q=tags=nil" | jq 'length'

# Копирование артефакта между репозиториями (в пределах инстанса)
curl -sk -u "admin:$PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/projects/prod/repositories/my-app/artifacts?from=myproject/my-app:v1.3.0"
# → 201 Created

# Удаление артефакта по digest
curl -sk -u "admin:$PASS" -X DELETE \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts/sha256:abcd..."
# → 200 OK (место освобождается после GC)

# --- Робот-аккаунты ---
# Создание робот-аккаунта (pull+push)
curl -sk -u "admin:$PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/robots" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-bot","project_id":3,"access":[{"resource":"repository","action":"pull"},{"resource":"repository","action":"push"}],"duration":86400}'
# → 201 Created, секрет показывается ОДИН раз в поле "secret"

# Обновление робот-аккаунта (PATCH — изменить name/description/access/duration)
curl -sk -u "admin:$PASS" -X PATCH \
  "https://harbor.corp.local/api/v2.0/robots/42" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-bot-renamed"}'

# Обновление/ротация секрета робот-аккаунта (PATCH .../secret)
curl -sk -u "admin:$PASS" -X PATCH \
  "https://harbor.corp.local/api/v2.0/robots/42/secret" \
  -H "Content-Type: application/json" \
  -d '{}'
# → 200, тело {"secret": "robot$..."} — новый секрет

# --- Garbage Collection ---
# API: GET /system/gc — история выполнений (пагинация).
# Запуск GC через API НЕДОСТУПЕН — только UI (Administration → Clean Up → GC Now) или расписание.
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/system/gc" | jq '.[] | {id, job_status}'

# --- Системная информация ---
curl -sk "https://harbor.corp.local/api/v2.0/systeminfo" | jq '{harbor_version, auth_mode, registry_url}'
curl -sk "https://harbor.corp.local/api/v2.0/health"
# → {"status":"healthy"}
```

### Сценарий 4: Аудит-логи через API

```bash
# Последние операции (системный админ видит все)
# Текущий эндпоинт — /auditlog-exts (эндпоинт /audit-logs deprecated)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts?page=1&page_size=50&sort=-timestamp" | \
  jq '.[] | {timestamp: .timestamp, username, operation, resource}'

# Типы событий аудит-лога
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts/events" | jq .
# → ["pull artifact","push artifact","delete artifact","create user", ...]
```

### Сценарий 5: Отчёт по квотам проектов

```bash
# Квоты хранятся отдельно от проекта — через /quotas.
# Сначала получить project_id по имени, затем квоту по reference=project&reference_id=<id>:
PID=$(curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects?name=myproject" | jq -r '.[0].project_id')
QID=$(curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/quotas?reference=project&reference_id=$PID" | jq -r '.[0].id')

# Детали квоты: лимит (hard) и текущее использование (used), в байтах
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/quotas/$QID" | jq '{id, hard, used}'

# Обновление квоты (PUT /quotas/{id}), тело: {"hard": {"storage": <bytes>}}
curl -sk -u "admin:$PASS" -X PUT \
  "https://harbor.corp.local/api/v2.0/quotas/$QID" \
  -H "Content-Type: application/json" \
  -d '{"hard": {"storage": 107374182400}}'

# Список всех квот (reference: project или global)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/quotas?reference=project" | jq '.[] | {id, ref, hard}'
```

> Квота задаётся в **байтах** (1 GiB = 1073741824). По умолчанию все проекты — без ограничений (`-1`).
> `Project` не содержит поля `quota` — квоты 获取аются отдельным запросом к `/quotas`.

### Сценарий 6: Официальный Harbor CLI

Альтернатива curl — официальный CLI (goharbor/harbor-cli): команды `login`, `logout`, `user`, `password`, `version`, `project`, `project member`, `project robot`, `project config`, `project logs`, `project preheat`, `project search`, `project summary`, `project view`, `artifact`, `artifact tags`, `artifact label`, `artifact scan`, `repo`, `tag`, `tag immutable`, `tag retention`, `label`, `quota`, `registry`, `replication`, `robot`, `webhook`, `cve-allowlist`, `scanner`, `schedule`, `scan all`, `vulnerability`, `health`, `info`, `instance`, `config`, `context`, `ldap`, `logs`, `jobservice`.

```bash
# Установка (бинарник или контейнер registry.goharbor.io/harbor-cli/harbor-cli)
harbor login harbor.corp.local -u admin --password-stdin <<< "$PASS"
# → logged in

# Список проектов и артефактов
harbor project list
harbor artifact list myproject/my-app

# Системный CVE allowlist
harbor cve-allowlist list

# Здоровье компонентов
harbor health

# Очереди Job Service (admin)
harbor jobservice queues list
```

> CLI хранит конфиг в `$HOME/.config/harbor-cli/config.yaml`; пароль шифруется AES-256 (ключ — `HARBOR_ENCRYPTION_KEY`). Полный список команд: [Harbor CLI Docs](https://goharbor.io/cli-docs/cli-docs).

## Валидация

```bash
# API жив
curl -sk -o /dev/null -w "%{http_code}" "https://harbor.corp.local/api/v2.0/ping"
# → 200

# Авторизация работает
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/projects" | jq 'length'
# → число проектов

# Пагинация корректна
curl -skI -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/projects?page=1&page_size=1" | \
  grep -i x-total-count
# → X-Total-Count: <общее число проектов>
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` | Нет Basic Auth или неверные учётные данные | `-u user:pass`; для робот-аккаунта формат `robot$<project>+<name>` |
| `403 Forbidden` | Недостаточно прав | Робот-аккаунт имеет права только на свой проект; системные эндпоинты требуют System Admin |
| Пустой массив при большом числе записей | Пагинация | Добавьте `page`/`page_size`; сверяйтесь с `X-Total-Count` |
| `404` на эндпоинте | Эндпоинт удалён или переименован в версии | Проверьте Swagger UI вашей версии Harbor |
| `429`/замедление | Массовые запросы без пагинации | Увеличьте `page_size`, добавьте паузы; используйте `q`-фильтры |
| Cookie-авторизация мешает | Сессия Portal конфликтует с Basic Auth | Удалите cookies домена или используйте отдельный клиент (см. предупреждение в Swagger UI) |

## Граничные случаи

* **Секрет робот-аккаунта** возвращается только при создании (поле `secret` в ответе `POST /robots`) и при обновлении через `PATCH /robots/{id}/secret` — нигде не хранится; утерянный секрет обновляется только ротацией (`PATCH .../secret`).
* **`q`-фильтры** различаются по эндпоинтам — синтаксис конкретного фильтра смотрите в Swagger UI.
* **DELETE артефакта** возвращает `200` — удаление асинхронное; место освобождается после GC.
* **Аудит-лог API**: текущий эндпоинт — `GET /auditlog-exts` (с v2.13); эндпоинт `GET /audit-logs` помечен deprecated; типы событий — `GET /auditlog-exts/events`.
* **Запуск GC через API недоступен** — `GET /system/gc` возвращает только историю. Запуск — через UI или расписание (`POST/PUT/DELETE /system/gc/schedule`).
* **Квота и проект раздельны** — в модели `Project` нет поля `quota`; квоту 获取ают через `GET /quotas?reference=project&reference_id=<project_id>`.

## Лучшие практики

* **Робот-аккаунты вместо паролей администратора** для CI/CD — узкий scope (только нужные проекты), ограниченный `duration` (по умолчанию 30 дней), ротация секрета при смене ответственного.
* **Пагинация всегда**: `page_size` до 100, сверяйтесь с `X-Total-Count`. Без пагинации большие списки ведут к `429` и замедлению.
* **`with_*`-параметры по умолчанию выключены**: включайте `with_scan_overview` / `with_sbom_overview` / `with_label` только когда они нужны — лишние поля увеличивают ответ в десятки раз.
* **Квоты по умолчанию не ставятся** — задавайте их при создании проекта (поле `storage_limit` в `POST /projects` или отдельно через `/quotas`), чтобы не было неограниченного роста.
* **GC по расписанию + DRY RUN**: настройте `POST /system/gc/schedule` (cron), перед ручным запуском — DRY RUN через UI. GC не чаще 1 раза в минуту.
* **Аудит-лог выгружайте регулярно**, чем purge-окно: `GET /auditlog-exts` с фильтрами, экспорт в TSV/SIEM.
* **Безопасность**: Basic Auth передаёт учётные данные в открытом виде — используйте HTTPS, робот-аккаунты с минимальными правами, не коммитите секреты.

## Дополнительная информация

* Официальная документация: [View the Harbor REST API](https://goharbor.io/docs/2.15.0/working-with-projects/using-api-explorer/), спецификация [api/v2.0/swagger.yaml](https://github.com/goharbor/harbor/blob/main/api/v2.0/swagger.yaml).
* **Токенный flow Registry v2** (не путать с Harbor API) — [Registry HTTP API v2](../registry_api_v2.md).
* **Автоматизация через API** (ротация робот-аккаунтов, очистка артефактов) — [Supply Chain Security](../../../Security/Supply_Chain_Security/overview.md), [cleanup strategies](../../Docker_fs/cleanup_gc_strategies.md).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — компоненты.
* **[Работа с Harbor](./usage.md)** — робот-аккаунты, GC.
* **[Аутентификация](./authentication.md)** — пользователи и члены проектов через API.
* **[Эксплуатация](./operations.md)** — аудит-логи и метрики.
* **[Репликация](./replication.md)** — API executions.
