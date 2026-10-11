# GitHub Enterprise Admin: Управление предприятием, политики и SCIM

**Актуально для:** GitHub Enterprise Cloud + Enterprise Server, октябрь 2026 (Enterprise Managed Users, SCIM auto-provisioning, IP allowlists, audit log streaming, custom repository properties); для GitHub Enterprise Server — 3.14+

GitHub Enterprise — платформа для крупных организаций с расширенными функциями администрирования: централизованное управление доступом (SCIM), SSO (SAML/OIDC), IP allowlists, политики действий, audit log, Enterprise Managed Users (EMU) и кастомные свойства репозиториев. Это уровень выше Organization — один Enterprise может включать десятки организаций.

## Определения

- **Enterprise**: Контейнер для организаций на github.com (Enterprise Cloud) или автономный сервер (Enterprise Server). Все организации в Enterprise наследуют enterprise-level политики.
- **Enterprise Managed Users (EMU)**: Специальные аккаунты, управляемые Enterprise через SCIM/SSO. EMU не могут выходить за пределы Enterprise и не имеют публичных профилей.
- **SCIM provisioning**: Автоматическое создание/обновление/удаление пользователей и Teams в GitHub через протокол SCIM (обычно из IdP: Okta, Azure AD, Google Workspace).
- **SSO (SAML/OIDC)**: Единый вход через внешний Identity Provider. Обязателен для EMU.
- **IP Allowlist**: Список разрешённых IP-диапазонов для доступа к Enterprise.
- **Audit Log**: Журнал всех действий в Enterprise (создание репозитория, изменение настроек, доступ к коду). Может streamиться в SIEM (Splunk, Datadog).
- **Custom Repository Properties (preview)**: Кастомные метаданные репозитория (team ownership, compliance level), используемые для политик и отчётности.
- **Repository Network**: Enterprise-level view всех репозиториев (включая forks) для audit.

## Архитектура и модель доступа

### Иерархия доступа

```text
Enterprise Owner (Enterprise Admins)
    ↓
Policies (наследуются org-ами)
    ↓
Organizations (org-level admins)
    ↓
Teams и Users (репозитории, права)
    ↓
Repository → Branch → Commit
```

- **Enterprise Owner**: полный доступ к Enterprise настройкам, политикам, org, billing.
- **Organization Owner**: управляет org-level настройками, teams, репозиториями в пределах политик Enterprise.
- **Teams**: группы пользователей с общими правами. Могут быть вложенными (nested teams).

### SCIM provisioning flow

```text
IdP (Okta/Azure AD)
    │
    1. SCIM API call: POST /scim/v2/Users или /scim/v2/Groups
    │   (создание/обновление пользователя или team)
    │
    2. GitHub Enterprise создаёт/обновляет EMU
    │   → автоматическое добавление в org
    │   → назначение ролей через attribute mapping
    │
    3. SSO (SAML/OIDC) для аутентификации
    │   → EMU аутентифицируется через IdP
    │
GitHub Enterprise
```

## Практические сценарии

### Сценарий 1: Настройка SCIM provisioning через Azure AD

**Предварительные требования**: GitHub Enterprise Cloud с подпиской; Azure AD Premium; Enterprise Owner доступ.

```bash
# 1. Включить SCIM в GitHub Enterprise (UI)
# Settings → Enterprise → Authentication → SAML SSO → Enable SCIM
# → Скопировать SCIM endpoint и токен

# 2. Список SCIM-пользователей
gh api /enterprises/{enterprise}/scim/v2/Users --jq '.Resources[].userName'

# 3. Создать SCIM-группу (Team)
gh api -X POST /enterprises/{enterprise}/scim/v2/Groups \
  -f schemas='["urn:ietf:params:scim:schemas:core:2.0:Group"]' \
  -f displayName="dev-team" \
  -f members='[{"value": "12345", "$ref": "urn:ietf:params:scim:schemas:core:2.0:User:12345"}]'
```

**Azure AD конфигурация**:
```
Identifier (Entity ID): urn:github:enterprises/my-enterprise
Reply URL: https://github.com/enterprises/my-enterprise/sso
SCIM endpoint: https://p85i5b3.ourcompany.com/scim/v2/enterprises/my-enterprise
Token: <copied-from-github-scim-settings>
```

- **Валидация**: в GitHub UI → Enterprise → Users появляются EMU-пользователи; `gh api /enterprises/{enterprise}/scim/v2/Users --jq '.Resources | length'` показывает количество.

### Сценарий 2: SSO через SAML (Okta пример)

```bash
# 1. Сгенерировать токен для SAML (через UI или API)
gh api /enterprises/{enterprise} --jq '.saml_configuration.id'

# 2. Настройки Okta:
# Single sign-on URL: https://github.com/enterprises/my-enterprise/sso
# Audience URI (Entity ID): urn:github:enterprises/my-enterprise
# Name ID format: Persistent
# Attribute statements:
#   - Name: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailAddress
#   - Name: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name

# 3. Проверить SSO через API
gh api /user/memberships/enterprises/my-enterprise --jq '.state'
```

### Сценарий 3: IP Allowlist для Enterprise

```bash
# 1. Получить текущие IP allowlist-entries
gh api /enterprises/{enterprise}/ip_allow_lists --jq '.[] | {ip: .ip, name: .name}'

# 2. Добавить IP range
gh api -X POST /enterprises/{enterprise}/ip_allow_lists \
  -f ip="192.168.1.0/24" \
  -f name="office-network"

# 3. Включить IP allowlist для org в Enterprise
gh api -X PUT /orgs/{org}/allowlist/agents \
  -f allowlist_id={allowlist_id}
```

### Сценарий 4: Audit Log Streaming в SIEM

```bash
# 1. Включить audit log streaming (через UI или API)
# Settings → Enterprise → Audit log → Stream to SIEM

# 2. Просмотр audit log через API
gh api /enterprises/{enterprise}/audit-log \
  --jq '.[] | select(.action == "org.add_member") | {actor: .user, target: .user_login, created: .created_at}' \
  -f include=organization_change -f order=desc -f per_page=100

# 3. Фильтр по типу события
gh api "/enterprises/{enterprise}/audit-log?phrase=action:repo.create&order=desc&per_page=50" \
  --jq '.[] | {repo: .repo, actor: .user, created: .created_at}'
```

### Сценарий 5: Custom Repository Properties

```bash
# 1. Создать custom property
gh api -X POST /enterprises/{enterprise}/properties \
  -f name="team-owner" \
  -f type="string" \
  -f description="Team responsible for the repository"

# 2. Назначить property репозиторию
gh api -X PUT /repos/{owner}/{repo}/properties \
  -f 'properties=[{"property_name": "team-owner", "value": "platform"}]'

# 3. Фильтр репозиториев по свойству
gh api /search/repositories \
  -f q="org:{org} property:team-owner=platform" \
  --jq '.items[].full_name'
```

## Команды и API-операции

### Enterprise API

| Операция | Endpoint |
|---|---|
| Информация об Enterprise | `GET /enterprises/{enterprise}` |
| Список org в Enterprise | `GET /enterprises/{enterprise}/organizations` |
| Audit log | `GET /enterprises/{enterprise}/audit-log` |
| SCIM Users | `GET/POST /enterprises/{enterprise}/scim/v2/Users` |
| SCIM Groups | `GET/POST /enterprises/{enterprise}/scim/v2/Groups` |
| IP allowlist | `GET/POST /enterprises/{enterprise}/ip_allow_lists` |
| Custom properties | `POST /enterprises/{enterprise}/properties` |
| SAML SSO config | `GET/PUT /enterprises/{enterprise}/saml-sso` |

### CLI

```bash
# Информация об enterprise
gh api /enterprises/{enterprise}

# Список org
gh api /enterprises/{enterprise}/organizations --jq '.[] | .login'

# Audit log: все созданные репозитории за 24h
gh api "/enterprises/{enterprise}/audit-log?phrase=action:repo.create&order=desc&per_page=100"

# SCIM users
gh api /enterprises/{enterprise}/scim/v2/Users --jq '.Resources[].userName'
```

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| SCIM provisioning не работает | SCIM endpoint/токен неверные; IdP misconfiguration | Проверить токен в Settings → Enterprise → SCIM; `gh api /enterprises/.../scim/v2/Users` |
| SSO не работает | Name ID mismatch; атрибуты не mapятся | Проверить attribute mapping в IdP; `Name ID format: Persistent` |
| IP allowlist блокирует | VPN/user IP не в allowlist | Добавить IP range; использовать `bypass` для админов |
| Audit log пустой | Filter слишком строгий | Убрать `phrase`; widen date range |
| Custom property не применяется | Property не создан в Enterprise или репо в другой org | Создать property на enterprise level; проверить org принадлежность |
| EMU не появляется | SCIM не создал, либо SSO не завершён | Проверить SCIM logs в IdP; forced SAML SSO login через UI |

## Лучшие практики

1. **SCIM + SSO как mandatory**: для Enterprise с EMU требуйте SSO; SCIM синхронизирует membership автоматически.
2. **Least privilege для SCIM**: IdP должен отправлять только `active`, `userName`, `displayName`, `emails`, `groups` — минимум для provisioning.
3. **IP allowlist для production org**: включайте на уровне org, а не enterprise (иначе ломаете dev/sandbox).
4. **Audit log streaming**: stream в SIEM (Splunk/Datadog) для compliance; используйте `phrase` filtering для targeted alerts.
5. **Custom properties для governance**: добавляйте `team-owner`, `data-classification`, `compliance-level` к репозиториям для отчётности.
6. **Enterprise policies для Actions**: на enterprise level задавайте `default_workflow_permissions`, `action can be used` политики.
7. **Repository network audit**: ежеквартально проверяйте `Repository network` в UI на наличие security-рисков.
8. **Billing на enterprise level**: используйте unified billing для всех org в Enterprise.

## Дополнительная информация

- **[GitHub API](./github_api.md)** — общий REST/GraphQL API с rate limits и pagination.
- **[Rulesets](./rulesets.md)** — политики защиты веток/Tags на enterprise/org/repo уровнях.
- **[Сетевая безопасность](./network-security.md)** — аудит трафика и Harden-Runner для Actions.
- **[GitHub Apps](./github_apps.md)** — аутентификация App для автоматизации в Enterprise.
- **Официальная документация**: [Enterprise Administration](https://docs.github.com/en/enterprise-cloud@latest/admin), [SCIM](https://docs.github.com/en/enterprise-cloud@latest/admin/user-management/using-scim-to-manage-user-and-group-access), [Audit log](https://docs.github.com/en/enterprise-cloud@latest/admin/monitoring-activity/reviewing-audit-logs-for-your-enterprise).
