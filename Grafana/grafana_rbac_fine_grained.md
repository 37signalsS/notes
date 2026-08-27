# Grafana: Fine-grained RBAC — кастомные роли и права

Практическое руководство по управлению кастомными ролями (custom roles), назначению их командам/пользователям/сервисным аккаунтам и аудиту прав. Актуально для Grafana 12.x LTS и 13.x; API управления доступом доступен в OSS начиная с 11.x. Облачные и ИИ-функции не рассматриваются.

## Определения

- **RBAC (Role-Based Access Control)** — модель доступа, где права субъекта определяются набором назначенных ему ролей; итоговые права — объединение всех ролей пользователя и его команд.
- **Custom role (кастомная роль)** — создаваемая администратором роль из набора `action` + `scope`; хранится в БД Grafana, имеет уникальный `uid`.
- **Action** — операция над ресурсом, например `dashboards:create`, `datasources:query`, `alert.rules:write`. Суффиксы `:read`/`:write`/`:create`/`:delete`.
- **Scope (область)** — к чему применяется action: глобальный (`dashboards:*`), на ресурс по uid (`dashboards:uid:<uid>`), на папку с наследованием (`folders:uid:<uid>` → все вложенные дашборды).
- **Fixed role (фиксированная роль)** — предопределённая роль Grafana (`Viewer`, `Editor`, `Admin`, `Grafana Admin`, а также служебные типа `data source permissions reader`). Кастомные роли могут доопределять фиксированные через **builtin role assignments**.
- **Builtin role assignment** — привязка кастомной роли к базовой роли организации: все носители `Editor`, например, получают дополнительные permissions.
- **Zanzana** — движок проверки разрешений Grafana (на базе OpenFGA, с 11.x); единая точка ответа «может ли субъект выполнить action над scope».

## Базовые концепции

Трёхуровневая модель прав Grafana:

1. **Организационная роль** (`Viewer`/`Editor`/`Admin`) — базовый уровень доступа в конкретной организации.
2. **RBAC (actions/scopes)** — детальные операции: можно дать пользователю право создавать дашборды, но запретить удалять источники данных, независимо от организационной роли.
3. **Permissions на ресурсы** (папки, дашборды, источники) — явные ACL на конкретный объект (View/Edit/Admin), наследуются от папки к дашборду.

Ключевые принципы:

- Права **не вычитаются**: если хоть одна роль даёт `dashboards:delete`, субъект сможет удалять.
- **Наименьших прав**: типовой паттерн — сервисному аккаунту CI дают не `Admin`, а кастомную роль из 2–4 экшенов (`dashboards:read`, `dashboards:write`, `folders:read`) со scope на конкретную папку.
- Роли идемпотентно описываются кодом (Terraform) и версионируются в Git — это часть Monitoring as Code (см. связанные темы).
- Назначение ролей возможно четырём типам субъектов: user, team, service account, builtin role.

## Практические сценарии

### Предварительные требования

- Токен сервисного аккаунта или сессия с правами `Grafana Admin` (управление ролями — серверная операция).
- Версия Grafana 11.x+ для OSS-доступа к RBAC API; для UI-редактора ролей — лицензия Enterprise.
- Для Terraform — провайдер `grafana/grafana` с настроенным `url` и `auth`.

### Сценарий 1. Создание кастомной роли через API

Роль для команды поддержки: смотреть любые дашборды, но редактировать только внутри одной папки.

```bash
export GRAFANA="https://grafana.example.internal"
TOKEN="<sa-token>"

curl -sS -X POST "$GRAFANA/api/access-control/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "uid": "role-support-team",
    "name": "Support: read all, edit folder",
    "description": "Чтение дашбордов + запись в папке support",
    "permissions": [
      {"action": "dashboards:read", "scope": "dashboards:*"},
      {"action": "folders:read",    "scope": "folders:*"},
      {"action": "dashboards:create", "scope": "folders:uid:support-folder"},
      {"action": "dashboards:write",  "scope": "folders:uid:support-folder"},
      {"action": "datasources:explore", "scope": "datasources:*"}
    ]
  }'
# → {"message":"Role created","uid":"role-support-team", ...}
```

Проверка списка ролей:

```bash
curl -sS "$GRAFANA/api/access-control/roles" -H "Authorization: Bearer $TOKEN" | jq '.items[].name'
# → содержит "Support: read all, edit folder"
```

### Сценарий 2. Назначение роли команде, пользователю и SA

```bash
# Команде (teamId=5)
curl -sS -X POST "$GRAFANA/api/access-control/teams/5/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"roleUids": ["role-support-team"]}'
# → статус 200

# Пользователю (userId=42)
curl -sS -X POST "$GRAFANA/api/access-control/users/42/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"roleUids": ["role-support-team"]}'
# → статус 200
```

Проверка эффективных прав пользователя:

```bash
curl -sS "$GRAFANA/api/access-control/users/42/permissions" \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.action=="dashboards:write")'
# → [{"action":"dashboards:write","scope":"folders:uid:support-folder"}]
```

Финальная проверка «изнутри»: войти под тестовым пользователем команды, убедиться, что дашборды вне папки доступны только на чтение (кнопки редактирования отсутствуют).

### Сценарий 3. Донастройка базовых ролей (builtin role assignment)

Дать всем `Viewer` возможность использовать Explore по одному источнику:

```bash
curl -sS -X POST "$GRAFANA/api/access-control/builtin-roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "roleUid": "role-support-team",
    "builtinRole": "Viewer",
    "orgId": 1
  }'
# → {"message":"Builtin role assignment added"}
```

Проверка — обычный Viewer без назначения в команды видит пункт Explore.

### Сценарий 4. Управление ролями как кодом (Terraform)

```hcl
resource "grafana_role" "support_team" {
  name        = "Support: read all, edit folder"
  description = "Чтение дашбордов + запись в папке support"
  uid         = "role-support-team"

  permissions {
    action = "dashboards:read"
    scope  = "dashboards:*"
  }
  permissions {
    action = "dashboards:create"
    scope  = "folders:uid:${grafana_folder.support.id}"
  }
  permissions {
    action = "dashboards:write"
    scope  = "folders:uid:${grafana_folder.support.id}"
  }
}

resource "grafana_role_assignment" "support_assign" {
  role_uid = grafana_role.support_team.uid
  teams    = [grafana_team.support.id]

  builtin_role_assignment {
    builtin_role = "Viewer"
    org_id       = 1
  }
}
```

Проверка после `terraform apply`: повторить запросы сценариев 1–2 — состояние должно совпадать без drift; повторный `terraform plan` показывает `No changes`.

### Сценарий 5. Аудит: кто что может

Инвентаризация ролей и назначений перед чисткой:

```bash
# Все роли с permissions
curl -sS "$GRAFANA/api/access-control/roles" -H "Authorization: Bearer $TOKEN" \
  | jq '.items[] | {uid, name, actions: [.permissions[].action]}'

# Роли, назначенные командам
for t in $(curl -sS "$GRAFANA/api/teams/search?perpage=100" -H "Authorization: Bearer $TOKEN" | jq -r '.teams[].id'); do
  echo "team=$t:"; curl -sS "$GRAFANA/api/access-control/teams/$t/roles" -H "Authorization: Bearer $TOKEN" | jq -r '.items[]?.name';
done
```

Роли без назначений — кандидаты на удаление: `DELETE /api/access-control/roles/<uid>`.

## Дополнительная информация

### Рекомендации по эксплуатации

- Задавайте ролям стабильные `uid` — они используются в Terraform, скриптах и бэкапах.
- Одна роль = одна задача («деплой дашбордов», «дежурный читатель»); комбинируйте назначениями, а не плодите монструозные роли.
- Сервисным аккаунтам CI/CD — минимум экшенов и scope на папку, а не `*`.
- Проверяйте эффективные права через `/api/access-control/users/:id/permissions`, а не «по ощущениям» из UI.
- Изменения ролей фиксируйте в Git (Terraform), чтобы был diff и откат.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| `403 permission denied` при создании роли | Токен без прав управления доступом | Использовать токен SA/Grafana Admin с правом на access-control |
| Пользователь всё ещё видит чужие дашборды | Scope задан как `folders:uid:*` вместо списка папок / есть другая роль с широким scope | Проверить union всех ролей через permissions API, убрать лишние |
| Terraform пересоздаёт роль каждый план | Не задан стабильный `uid` | Указать `uid` явно в ресурсе |
| Роль назначена, но эффекта нет | Кэш сессии пользователя; перелогиниться | Попросить пользователя перезайти, проверить снова |
| После включения data source permissions источник пропал у всех | Поведение «по умолчанию запрещено» | Явно назначить права командам/SA на источник |

### Ограничения и особые случаи

- Редактор кастомных ролей в UI и Team Sync for RBAC — Enterprise; в OSS управление только через API/Terraform.
- Нельзя «вычесть» право из базовой организационной роли — только строить доступ заново кастомной ролью.
- `Grafana Admin` — серверная роль, она не даёт автоматически прав во всех организациях на уровне данных.
- Удаление роли, назначенной субъектам, требует предварительного снятия назначений.

### Очистка и откат изменений

```bash
# Снять роль с команды
curl -sS -X PUT "$GRAFANA/api/access-control/teams/5/roles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"roleUids": []}'
# Удалить роль
curl -sS -X DELETE "$GRAFANA/api/access-control/roles/role-support-team" \
  -H "Authorization: Bearer $TOKEN"
# → {"message":"Role removed"}
```

### Актуальность и статус

API `/api/access-control/*` стабилен с 10.x–11.x и актуален для 13.x; в OSS доступен с 11.x. Terraform-ресурсы `grafana_role`/`grafana_role_assignment` поддерживаются провайдером grafana/grafana.

### Связанные темы

- [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md)
- [Дашборды: папки и права](grafana-dashboards.md)
- [Monitoring as Code (MaC)](monitoring_as_code.md)
- [Источники данных: права доступа](grafana_datasources.md)
