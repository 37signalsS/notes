# Grafana: Fine-grained RBAC — кастомные роли

**Актуально для:** Grafana Enterprise (self-managed) 13.x; применимо к 12.x (LTS). Fine-grained RBAC — возможность **Grafana Enterprise и Grafana Cloud**; в Grafana OSS доступны только базовые организационные роли. Специфичные для Grafana Cloud детали здесь не рассматриваются.

## Определения

- **RBAC (Role-Based Access Control)** — модель доступа, где права субъекта определяются набором назначенных ему ролей; итоговые права — объединение (union) всех ролей пользователя и его команд.
- **Basic role (базовая/организационная роль)** — `Viewer`, `Editor`, `Admin`, а также `Grafana Admin` и `None` (нет прав). Единственный класс ролей, присутствующий в Grafana OSS.
- **Fixed role (фиксированная роль)** — предопределённая роль Grafana (например, `fixed:datasources:writer`); её нельзя изменить или удалить, можно только назначить. Доступна в Enterprise/Cloud.
- **Custom role (кастомная роль)** — роль, собираемая администратором из набора `action` + `scope`; хранится в БД Grafana, имеет `uid`, имя (по соглашению с префиксом `custom:`) и числовую `version`. Доступна в Enterprise/Cloud.
- **Action** — операция над ресурсом, например `dashboards:create`, `datasources:query`, `alert.rules:write`.
- **Scope (область)** — к чему применяется action: глобальная (`dashboards:*`) или на конкретный ресурс (`dashboards:uid:<uid>`). Scope папки (`folders:uid:<uid>`) наследуется вложенными дашбордами и подпапками. У части action scope не требуется (в таблице действий — `None`).
- **Builtin role assignment (назначение базовой роли)** — привязка фиксированной или кастомной роли к базовой роли: все носители базовой роли дополнительно получают её permissions.
- **`permissions:type:delegate`** — scope, позволяющий делегировать только собственные права (или их подмножество). Без него нельзя создать роль или назначение с правами шире своих.
- **Zanzana** — новый сервис авторизации Grafana Labs (обёртка над OpenFGA, модель Zanzibar); развивается как единая точка проверки доступа и применяется постепенно. Это внутренний компонент, а не элемент пользовательской настройки RBAC.

## Базовые концепции

Трёхуровневая модель прав Grafana:

1. **Организационная (базовая) роль** (`Viewer`/`Editor`/`Admin`) — базовый уровень доступа в конкретной организации; единственный уровень, доступный в OSS.
2. **Fine-grained RBAC (actions/scopes)** — детальные операции: можно дать пользователю право создавать дашборды, но запретить удалять источники данных, независимо от организационной роли. Требует Enterprise/Cloud.
3. **Permissions на ресурсы** (папки, дашборды, источники) — явные ACL на конкретный объект (View/Edit/Admin), наследуются от папки к дашборду.

Ключевые принципы:

- **Права не вычитаются**: если хоть одна роль даёт `dashboards:delete`, субъект сможет удалять. Исключение — переопределение permissions самой базовой роли.
- **Наименьшие права**: типовой паттерн — сервисному аккаунту CI дают не `Admin`, а кастомную роль из 2–4 экшенов (`dashboards:read`, `dashboards:write`, `folders:read`) со scope на конкретную папку.
- **Роли описываются кодом** (Terraform или provisioning) и версионируются в Git — см. [Monitoring as Code](monitoring_as_code.md).
- Назначение ролей возможно четырём типам субъектов: **user, team, service account, builtin role**.
- **Делегирование по умолчанию**: чтобы назначить роль, у назначающего должны быть те же права (scope `permissions:type:delegate`) — это защита от эскалации привилегий.

### Редции и лицензирование

| Возможность | OSS | Enterprise / Cloud |
| --- | --- | --- |
| Базовые роли (Viewer/Editor/Admin/Grafana Admin/None) | Есть | Есть |
| Фиксированные роли, кастомные роли | Нет | Есть |
| RBAC API (`/api/access-control/*`) | Нет | Есть |
| Файловый провиженинг RBAC (`provisioning/access-control/`) | Нет | Есть (только self-managed) |
| Terraform-провайдер `grafana_role`/`grafana_role_assignment` | Требует Enterprise-лицензии целевого инстанса | Есть |

## Практические сценарии

### Предварительные требования

- Лицензия **Grafana Enterprise** (или Grafana Cloud) на целевом инстансе — иначе RBAC API вернёт ошибку, а файлы `provisioning/access-control/` игнорируются.
- Токен сервисного аккаунта с ролью **Role writer** (`roles:write`, `roles:read`, `roles:delete`, `permissions:type:delegate`) — либо сессия `Grafana Admin` через basic-auth. Для правки **базовых** ролей сервисный аккаунт не подходит: нужен `Grafana Admin` с basic-auth.
- Для Terraform — провайдер `grafana/grafana` с настроенным `url` и `auth` (токен с достаточными правами).

### Сценарий 1. Проверка статуса RBAC

```bash
export GRAFANA="https://grafana.example.internal"
TOKEN="<sa-token>"

curl -sS "$GRAFANA/api/access-control/status" -H "Authorization: Bearer $TOKEN"
# → {"enabled":true}
```

Если в ответе `{"enabled":false}` или приходит `403` — на инстансе нет лицензии Enterprise.

### Сценарий 2. Создание кастомной роли через API

Роль для команды поддержки: смотреть любые дашборды, но редактировать только внутри одной папки.

```bash
curl -sS -X POST "$GRAFANA/api/access-control/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "uid": "custom_support_editor",
    "name": "custom:support_editor",
    "displayName": "Support: read all, edit folder",
    "description": "Чтение дашбордов + запись в папке support",
    "global": false,
    "permissions": [
      {"action": "dashboards:read",    "scope": "dashboards:*"},
      {"action": "folders:read",       "scope": "folders:*"},
      {"action": "dashboards:create",  "scope": "folders:uid:support-folder"},
      {"action": "dashboards:write",   "scope": "folders:uid:support-folder"},
      {"action": "datasources:query",  "scope": "datasources:*"}
    ]
  }'
# → 200 OK: полное определение роли (uid, name, permissions, version, global, ...)
```

Поле `name` обязательно и не должно начинаться с префикса фиксированной роли (`fixed:`) или базовой (`basic:`). `global: false` — роль видна только в организации запроса; `global: true` делает её глобальной. Ответ возвращает массив permissions с `created`/`updated`.

Проверка списка ролей (ответ — JSON-массив, не объект с `items`):

```bash
curl -sS "$GRAFANA/api/access-control/roles" -H "Authorization: Bearer $TOKEN" \
  | jq -r '.[] | select(.name | startswith("custom:")) | .name'
# → содержит "custom:support_editor"
```

### Сценарий 3. Назначение роли команде, пользователю и сервисному аккаунту

```bash
# Команде (teamId=5)
curl -sS -X POST "$GRAFANA/api/access-control/teams/5/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"roleUid": "custom_support_editor"}'
# → {"message":"Role added to the team."}

# Пользователю (userId=42)
curl -sS -X POST "$GRAFANA/api/access-control/users/42/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"roleUid": "custom_support_editor"}'
# → {"message":"Role added to the user."}

# Сервисному аккаунту (serviceAccountId=101) — тот же endpoint, id аккаунта
curl -sS -X POST "$GRAFANA/api/access-control/users/101/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"roleUid": "custom_support_editor"}'
# → {"message":"Role added to the user."}
```

Разница между одиночным и массовым назначением: `POST` использует поле `roleUid` (одна роль), `PUT` — `roleUids` (полный набор, лишние назначения снимаются).

Проверка эффективных прав пользователя:

```bash
curl -sS "$GRAFANA/api/access-control/users/42/permissions" \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.action=="dashboards:write")'
# → {"action":"dashboards:write","scope":"folders:uid:support-folder"}
```

Свои права проверяются без прав администратора: `GET /api/access-control/user/permissions?reloadcache=true`.

Финальная проверка «изнутри»: войти под тестовым пользователем команды, убедиться, что дашборды вне папки доступны только на чтение (кнопки редактирования отсутствуют).

### Сценарий 4. Изменение базовой роли (донастройка Viewer/Editor)

Задача: дать всем `Viewer` дополнительное право, например запрос к одному источнику. Базовые роли изменяемы: к ним можно скопировать permissions фиксированной/кастомной роли.

**Способ 1 — файловый провиженинг** (Enterprise, self-managed; см. [Провиженинг Grafana](grafana_provisioning.md)):

```yaml
# /etc/grafana/provisioning/access-control/roles.yaml
apiVersion: 2
roles:
  - name: 'basic:viewer'
    global: true
    version: 5
    from:
      - name: 'basic:viewer'
        global: true
    permissions:
      - action: 'datasources:query'
        scope: 'datasources:uid:prometheus-main'
```

`from` копирует permissions указанных ролей (базовых, фиксированных или кастомных); `version` нужно **увеличивать**, иначе изменение не применится. Затем перезагрузить provisioning (см. [grafana_provisioning.md](grafana_provisioning.md)).

**Через API** (работает и в Cloud): `GET /api/access-control/roles/basic_viewer`, добавить нужный permission, увеличить `version`, затем `PUT /api/access-control/roles/basic_viewer`.

> Важно: изменение базовой роли действует на **все организации** инстанса и **не распространяется** на другие базовые роли (`Viewer` не влияет на `Editor`). Если нужно изменить доступ только части пользователей — не трогайте базовую роль, назначьте им роль `None` и выдайте фиксированные/кастомные роли.

### Сценарий 5. Роли как код (Terraform)

```hcl
resource "grafana_role" "support_editor" {
  name        = "custom:support_editor"
  description = "Чтение дашбордов + запись в папке support"
  uid         = "custom_support_editor"

  permissions {
    action = "dashboards:read"
    scope  = "dashboards:*"
  }
  permissions {
    action = "dashboards:create"
    scope  = "folders:uid:${grafana_folder.support.uid}"
  }
  permissions {
    action = "dashboards:write"
    scope  = "folders:uid:${grafana_folder.support.uid}"
  }
}

resource "grafana_role_assignment" "support_assign" {
  role_uid         = grafana_role.support_editor.uid
  teams            = [grafana_team.support.id]
  service_accounts = [grafana_service_account.ci.id]
}
```

Проверка после `terraform apply`: повторить запросы сценариев 2–3 — состояние должно совпадать без drift; повторный `terraform plan` показывает `No changes`.

### Сценарий 6. Аудит: кто что может

Инвентаризация ролей и назначений перед чисткой:

```bash
# Все кастомные роли с actions
curl -sS "$GRAFANA/api/access-control/roles" -H "Authorization: Bearer $TOKEN" \
  | jq '.[] | select(.name | startswith("custom:")) | {uid, name, actions: [.permissions[].action]}'

# Роли, назначенные командам
for t in $(curl -sS "$GRAFANA/api/teams/search?perpage=100" -H "Authorization: Bearer $TOKEN" | jq -r '.teams[].id'); do
  echo "team=$t:"
  curl -sS "$GRAFANA/api/access-control/teams/$t/roles" -H "Authorization: Bearer $TOKEN" | jq -r '.[]?.name'
done
```

Роли без назначений — кандидаты на удаление: `DELETE /api/access-control/roles/<uid>`.

## Дополнительная информация

### Рекомендации по эксплуатации

- Задавайте ролям стабильные `uid` — они используются в Terraform, скриптах и назначениях.
- Одна роль = одна задача («деплой дашбордов», «дежурный читатель»); комбинируйте назначениями, а не плодите монструозные роли.
- Сервисным аккаунтам CI/CD — минимум экшенов и scope на папку, а не `*`.
- Не выдавайте `Admin` там, где достаточно кастомной роли из нескольких экшенов.
- Проверяйте эффективные права через `/api/access-control/users/:id/permissions`, а не «по ощущениям» из UI.
- Изменения ролей фиксируйте в Git (Terraform/provisioning), чтобы был diff и откат.
- Помните: кастомные роли **не получают новые permissions автоматически** при выходе новых фич — обновляйте их вручную (в отличие от изменённых базовых ролей).

### Провиженинг RBAC

Кастомные роли и их назначения описываются YAML-файлами в `provisioning/access-control/` и перечитываются в рантайме. Это доступно **только в Grafana Enterprise для self-managed** инстансов; в Grafana Cloud файловый провиженинг недоступен — используйте Terraform или HTTP API. Подробности — в [Провиженинг Grafana](grafana_provisioning.md).

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| `403` или `{"enabled":false}` на `/api/access-control/status` | Нет лицензии Enterprise/Cloud | Установить Enterprise-лицензию; в OSS RBAC недоступен |
| `403 permission denied` при создании роли | У токена нет `roles:write`/`permissions:type:delegate` | Использовать токен с ролью Role writer или basic-auth Grafana Admin |
| `400 Invalid scope` при создании роли | Scope несовместим с action (например, у `datasources:explore` scope `None`) | Сверить action/scope по таблице RBAC permissions |
| `400` «role with fixed prefix» | Имя роли начинается с `fixed:`/`basic:` | Использовать префикс `custom:` |
| `PUT` роли отклонён | Не увеличена `version` | Перечитать роль, увеличить `version`, повторить PUT |
| Пользователь всё ещё видит чужие дашборды | Scope задан как `folders:uid:*` либо другая роль даёт широкий scope | Проверить union ролей через permissions API, убрать лишние |
| Terraform пересоздаёт роль каждый план | Не задан стабильный `uid` | Указать `uid` явно в ресурсе |
| Назначение не вступило в силу | Кэш сессии/прав | `?reloadcache=true` или перелогинить пользователя |
| После включения data source permissions источник пропал у всех | Поведение «по умолчанию запрещено» | Явно назначить права командам/SA на источник |

### Ограничения и особые случаи

- **RBAC — только Enterprise/Cloud.** В Grafana OSS доступны исключительно базовые организационные роли; кастомные/фиксированные роли и RBAC API отсутствуют.
- Кастомные роли **не получают новые permissions автоматически** при выходе новых фич; изменённым базовым ролям новые permissions добавляются.
- Изменение базовой роли не распространяется на другие базовые роли и действует на весь инстанс (все организации).
- Нельзя «вычесть» право из роли — только переопределять набор permissions.
- Папка с именем `General`/`general` не управляется через RBAC.
- Одиночный `POST` назначения принимает одну роль (`roleUid`); массовая синхронизация набора — только `PUT` (`roleUids`).

### Очистка и откат

```bash
# Снять роль с команды
curl -sS -X DELETE "$GRAFANA/api/access-control/teams/5/roles/custom_support_editor" \
  -H "Authorization: Bearer $TOKEN"
# → {"message":"Role removed from team."}

# Снять роль с пользователя
curl -sS -X DELETE "$GRAFANA/api/access-control/users/42/roles/custom_support_editor" \
  -H "Authorization: Bearer $TOKEN"
# → {"message":"Role removed from user."}

# Удалить роль (force=true снимет и оставшиеся назначения)
curl -sS -X DELETE "$GRAFANA/api/access-control/roles/custom_support_editor?force=true&global=false" \
  -H "Authorization: Bearer $TOKEN"
# → 200 OK
```

Откат правки базовой роли: `POST /api/access-control/roles/hard-reset` с телом `{"BasicRoles": true}` (нужен scope `permissions:type:escalate` у `Grafana Admin`) либо опция `[rbac] reset_basic_roles = true` (сброс на каждом старте — включайте временно).

### Актуальность и статус

- RBAC API (`/api/access-control/*`) актуален для 13.x; в Grafana 13 маршруты `/api` постепенно вытесняются `/apis`, но legacy-маршруты продолжают работать.
- Terraform: `grafana_role` (Enterprise 8+), `grafana_role_assignment` (Enterprise 9.2+) в провайдере `grafana/grafana`.
- Провиженинг RBAC (`provisioning/access-control/`) — только Enterprise, self-managed.

### Связанные темы

- [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md)
- [Дашборды: папки и права](grafana-dashboards.md)
- [Провиженинг Grafana](grafana_provisioning.md)
- [Monitoring as Code (MaC)](monitoring_as_code.md)
- [Источники данных: права доступа](grafana_datasources.md)
