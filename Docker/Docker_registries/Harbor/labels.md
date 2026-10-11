# Harbor: Управление лейблами артефактов

**Актуально для:** Harbor 2.15.x

## Определения

* **Label (лейбл)**: Метаданные артефакта в Harbor — имя, описание, цвет и область видимости (scope). Лейбл присваивается артефакту и используется для фильтрации, автоматизации и promotion-воркфлоу.
* **Scope (область видимости лейбла)**: Уровень, на котором существует лейбл. Два значения: `g` (global — создаётся системным администратором, доступен всем проектам) и `p` (project — создаётся администратором проекта, существует только внутри проекта).
* **Global label**: Лейбл с scope `g`. Управляется на уровне системы (Administration → Labels), одинаково доступен во всех проектах инстанса.
* **Project label**: Лейбл с scope `p`. Управляется внутри проекта (Projects → <project> → Labels), не виден в других проектах.
* **Label filter**: Фильтр артефактов по лейблам — в UI, в API (`q=labels=(id1,id2)`) и в правилах репликации.

## Предварительные требования

* **Роль**: для global-лейблов (scope `g`) — системный администратор; для project-лейблов (scope `p`) — администратор проекта или системный администратор.
* **Harbor 2.15.x** — текущая версия; API `api/v2.0` (тег `label`) и CLI `harbor label` доступны с 2.2+.
* **Доступ к инстансу**: HTTP/HTTPS (443), базовая аутентификация `admin:password` или токен робот-аккаунта для API/CLI.
* **Сканер (опционально)**: не требуется для работы с лейблами, но лейблы часто комбинируются с правилами сканирования и репликации (см. [replication.md](./replication.md), [sbom.md](./sbom.md)).

## Основные концепции

### Зачем лейблы в продакшене

| Сценарий | Как применяется |
| :--- | :--- |
| **Promotion образов** | Лейбл `env` на артефакте → правило репликации с фильтром по лейблу копирует его в Prod-реестр |
| **Фильтрация в UI** | Список артефактов фильтруется по типу, тегам и лейблам |
| **P2P preheat** | Событие `OnLabel` триггерит event-based политику прогрева при присвоении лейбла |
| **Retention** | Селекторы правил retention могут учитывать лейблы при выборе артефактов |
| **Автоматизация** | CI присваивает лейблы через API после прохождения тестов (например, `qa-passed`) |

### Лейбл vs аннотация OCI

Лейбл Harbor — сущность Harbor с UI, RBAC и API, хранится в БД Harbor. Аннотации (`annotations`) — часть манифеста OCI-артефакта, переносятся с артефактом при копировании между реестрами. Лейблы удобны для операционных воркфлоу (фильтры, триггеры), аннотации — для переносимых метаданных артефакта.

## Практические сценарии

### Сценарий 1: Создание лейбла в UI

**Global-лейбл (системный администратор):**

1. **Administration → Labels → +NEW LABEL**.
2. Поля: **Name** (например, `env`), **Description**, **Color** (цвет в UI), **Scope**: `g` (global).
3. **Save**.

**Project-лейбл (администратор проекта):**

1. **Projects → myproject → Labels → +NEW LABEL**.
2. Те же поля; **Scope**: `p` (project).
3. **Save**.

### Сценарий 2: Присвоение лейбла артефакту

1. Откройте артефакт: **Projects → myproject → репозиторий → артефакт**.
2. На панели артефакта — **Labels** → добавить существующий лейбл.
3. Лейбл отображается цветной меткой в списке артефактов.

Присвоение лейбла — событие `OnLabel`, которое триггерит event-based политики P2P preheat (см. [p2p_preheat.md](./p2p_preheat.md)).

### Сценарий 3: Управление лейблами через API

```bash
# Создание лейбла (scope g — global, p — project; для p обязателен project_id)
curl -sk -u "admin:$PASS" -X POST "https://harbor.corp.local/api/v2.0/labels" \
  -H "Content-Type: application/json" \
  -d '{"name":"env","description":"Environment","color":"#FF0000","scope":"g"}'
# → 201 Created, заголовок Location: .../labels/<id>

# Список лейблов (фильтры: name, scope, project_id)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/labels?scope=g" | jq '.[] | {id, name, scope}'

# Изменение лейбла
curl -sk -u "admin:$PASS" -X PUT "https://harbor.corp.local/api/v2.0/labels/<label_id>" \
  -H "Content-Type: application/json" \
  -d '{"name":"env","description":"Environment (updated)","color":"#00FF00","scope":"g"}'
# → 200 OK

# Присвоение лейбла артефакту (тело — объект Label с id или name)
curl -sk -u "admin:$PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts/sha256:abcd.../labels" \
  -H "Content-Type: application/json" \
  -d '{"name":"env"}'
# → 200 OK

# Снятие лейбла с артефакта
curl -sk -u "admin:$PASS" -X DELETE \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts/sha256:abcd.../labels/<label_id>"
# → 200 OK

# Удаление лейбла
curl -sk -u "admin:$PASS" -X DELETE "https://harbor.corp.local/api/v2.0/labels/<label_id>"
# → 200 OK
```

### Сценарий 4: Массовые операции (SRE/devops-контекст)

Лейблы особенно полезны в SRE-сценариях, где нужно выделить группу артефактов для массовой обработки: отката, сканирования, ретеншена или репликации.

```bash
# 1. Найти все артефакты с лейблом (по ID; with_label=true возвращает поля labels)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?q=labels=(42)&with_label=true&pageSize=100" | \
  jq '.[] | {digest, tags: [.tags[].name], labels: [.labels[].name]}'

# 2. Массовое сканирование артефактов с лейблом (фильтр по лейблу задаётся в UI:
#    Administration → Scan All → Filters → Label → выберите лейбл).
#    CLI: harbor scan all run запускает сканирование всего реестра без фильтров.
harbor scan all run
harbor scan all view schedule

# 3. Ретеншн по лейблу: в правилении retention (Administration → Retention → Rules) добавьте
#    селектор, включающий лейбл — артефакты без нужного лейбла исключаются из cleanup.
```

> **SRE-применение**: лейбл `rollback-candidate` на артефактах, известных как стабильные версии, позволяет быстро собрать список digest для отката (`harbor artifact view` + `docker pull @digest`) без поиска по тегам. Лейбл `deprecated` помечает устаревшие сборки для автоматического удаления при ретеншене.

### Сценарий 5: Управление лейблами через Harbor CLI

Официальный CLI (`goharbor/harbor-cli`) — альтернатива curl для скриптинга и CI/CD. Конфиг хранится в `$HOME/.config/harbor-cli/config.yaml`, пароль шифруется AES-256 (ключ — `HARBOR_ENCRYPTION_KEY`). Полный список команд — в [Harbor CLI Docs](https://goharbor.io/cli-docs/cli-docs).

```bash
# Установка
curl -sL https://github.com/goharbor/harbor-cli/releases/latest/download/harbor-cli-linux-amd64 -o harbor && chmod +x harbor

# Логин
harbor login harbor.corp.local -u "robot$production+ci-bot" --password-stdin <<< "$ROBOT_SECRET"

# Создание лейбла (по умолчанию scope g; -i/--project задаёт scope p)
harbor label create --name env --description "Environment" --color "#FF0000" --scope g
harbor label create --name qa --scope p --project 5

# Список лейблов
harbor label list

# Присвоение лейбла артефакту (аргумент — <project>/<repository>/<reference>)
harbor artifact label add myproject/my-app/sha256:abcd... env

# Снятие лейбла с артефакта
harbor artifact label delete myproject/my-app/sha256:abcd... env

# Список лейблов артефакта
harbor artifact label list myproject/my-app/sha256:abcd...
```

> `harbor artifact label add` принимает **имя лейбла** (не `name=value`). Формат `env=prod` — ошибка: лейбл с именем `env=prod` создастся, но не будет найден по имени `env`. Имена лейблов — произвольные строки без специального синтаксиса.

### Сценарий 6: Фильтрация артефактов по лейблам

```bash
# Артефакты с обоими лейблами (по ID; фильтр labels=(1,2) — AND)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?q=labels=(1,2)&with_tag=true" | \
  jq '.[] | {digest, tags: [.tags[].name]}'

# Другие q-фильтры для артефактов:
#   tags=*     — только тегированные
#   tags=nil   — только без тегов
#   tags=~v    — нечёткое совпадение тега "v"
#   tags=v     — точное совпадение тега
```

### Сценарий 7: Лейблы в правилах репликации

Лейбл — один из фильтров правила репликации (комбинируется с фильтрами по проекту, тегу и типу ресурса через AND):

1. **Administration → Replication → New Rule** (или правка существующего).
2. **Filters → Label**: выберите лейбл (например, `env`).
3. Артефакты с этим лейблом реплицируются по триггеру правила.

Типичный promotion-воркфлоу: CI помечает протестированный артефакт лейблом `env` через API → event-based правило реплицирует его в Prod-реестр. Подробнее — [replication.md, сценарий 4](./replication.md#сценарий-4-фильтры-правила).

## Валидация

```bash
# Лейбл создан
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/labels?name=env" | jq '.[0] | {name, scope}'
# → {"name":"env","scope":"g"}

# Лейбл присвоен артефакту
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?q=labels=(1)&with_tag=true" | jq 'length'
# → число артефактов с лейблом id=1
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `409 Conflict` при создании | Лейбл с таким именем и scope уже существует | Измените имя или обновите существующий (`PUT /labels/{id}`) |
| `400` при создании project-лейбла | Не указан `project_id` для scope `p` | Передайте `"project_id": <id>` в теле запроса |
| Лейбл не удаляется | На лейбл ссылаются артефакты или политики | Снимите лейбл с артефактов (`DELETE .../artifacts/{ref}/labels/{label_id}`), затем удалите |
| Фильтр `labels=(1,2)` возвращает пустой массив | Артефакты должны иметь **оба** лейбла (AND); ID — числовые | Проверьте ID через `GET /labels`; для одного лейбла — `labels=(1)` |
| Лейбл не виден в другом проекте | Project-лейбл (scope `p`) существует только в своём проекте | Используйте global-лейбл (scope `g`) для кросс-проектных сценариев |

## Граничные случаи

* **Лейблы не являются частью манифеста OCI** — они хранятся в БД Harbor и не переносятся при копировании артефакта в другой реестр (`skopeo copy`, репликация переносит артефакт; лейблы — Harbor-метаданные).
* **Цвет лейбла** — чисто визуальный атрибут UI, не влияет на логику фильтров.
* **Событие OnLabel** срабатывает при присвоении лейбла; снятие лейбла событием не является (учитывайте при event-based политиках P2P preheat).

## Лучшие практики

* **Используйте global-лейблы для кросс-проектных сценариев** (например, `env`, `team`), project-лейблы — только для специфичных проекту меток. Это минимизирует дублирование и упрощает фильтры репликации.
* **Называйте лейблы предсказуемо**: `env`, `status`, `owner`, `build`. Имена без `=value` — лейблы Harbor не поддерживают `key=value` синтаксис (это теги/аннотации).
* **Согласуйте словарь лейблов на уровне организации** — создайте набор global-лейблов до развертывания проектов, чтобы CI/CD скрипты могли полагаться на существующие ID.
* **Присваивайте лейблы в CI/CD после прохождения тестов** через API/CLI (`POST .../labels`) — это event-based триггер для репликации и P2P preheat.
* **Комбинируйте лейблы с `with_label=true`** в API-запросах только когда лейблы действительно нужны — лишние поля увеличивают ответ в десятки раз (см. [api.md](./api.md#сценарий-3-типовые-операции)).
* **Храните лейблы отдельно от OCI-артефакта**: лейблы не переносятся при копировании (`skopeo copy`) — при миграции между реестрами лейблы нужно воссоздавать вручную или через скрипт.
* **Для mass-операций используйте CLI**, не UI: `harbor artifact label add` поддерживает скриптинг, а для hundreds of artifacts API с пагинацией эффективнее ручного ввода.

## Откат изменений и очистка

* **Удаление лейбла**: лейбл можно удалить (`DELETE /labels/{id}` или `harbor label delete`), только если на него не ссылаются артефакты и политики. Сначала снимите лейбл со всех артефактов (`DELETE .../artifacts/{ref}/labels/{label_id}`).
* **Снятие лейбла с артефакта**: `harbor artifact label delete <project>/<repository>/<reference> <label name>` или `DELETE .../artifacts/{ref}/labels/{label_id}` — артефакт остаётся, лейбл пропадает из его метаданных.
* **Массовое снятие лейбла**: переберите артефакты через `GET .../artifacts?q=labels=(<id>)&with_label=true`, затем для каждого выполните `DELETE .../labels/{label_id}`. CLI не имеет пакетной команды снятия.
* **Очистка после инцидента**: если лейбл ошибочно присвоен массово — используйте фильтр `labels=(<id>)` для получения списка, затем снимайте по digest. Удаление артефактов не требуется (лейблы — метаданные, артефакт остаётся).
* **Восстановление после rename**: rename лейбла (`PUT /labels/{id}`) обновляет имя у всех артефактов, на которые он присвоен — откат не нужен, но проверьте, что скрипты CI/CD и фильтры репликации используют новое имя.
* **Резервное копирование**: лейблы хранятся в БД Harbor; при резервировании инстанса (например, через `harbor backup`) лейблы включаются в дамп автоматически.

## Дополнительная информация

* Официальная документация: [Managing Labels](https://goharbor.io/docs/2.15.0/working-with-projects/working-with-images/managing-labels/), спецификация API: `api/v2.0/swagger.yaml` (тег `label`).
* **Фильтры репликации по лейблам** — [replication.md, сценарий 4](./replication.md#сценарий-4-фильтры-правила).
* **Событие OnLabel для P2P preheat** — [p2p_preheat.md](./p2p_preheat.md).
* **Фильтры артефактов в API** — [api.md, сценарий 3](./api.md#сценарий-3-типовые-операции).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и компоненты.
* **[Работа с Harbor](./usage.md)** — артефакты, теги, жизненный цикл.
* **[Репликация](./replication.md)** — фильтры правил.
* **[Harbor REST API](./api.md)** — пагинация, q-фильтры.
* **[Вопросы на собеседованиях](./harbor_interview_qa.md)** — Q&A по Harbor.
