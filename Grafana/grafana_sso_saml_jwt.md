# Grafana: Enterprise SSO — SAML, JWT и расширенный LDAP

**Актуально для:** Grafana 13.x (12.x — LTS)

Практическое руководство по корпоративной аутентификации Grafana: SAML (Enterprise), вход по JWT для сервисных и embedding-сценариев, а также расширенные возможности LDAP — Team Sync и активная фоновая синхронизация. Базовый OAuth (GitHub/Keycloak), первичная настройка LDAP, сервисные аккаунты и RBAC — в [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md); теория протоколов — в `../Security/Concepts/jwt_overview.md` и `../Security/Concepts/oauth2_overview.md`.

## Определения

- **SAML 2.0** — XML-протокол федеративной аутентификации: IdP подписывает assertion, Grafana (SP) проверяет его по метаданным и сертификату. В Grafana доступен только с лицензией Enterprise.
- **SP (Service Provider)** — роль Grafana в SAML-обмене: генерирует AuthnRequest, принимает assertion на ACS, проверяет подпись.
- **JWT auth** — вход по подписанному токену в HTTP-заголовке (или URL-параметре при `url_login`). Grafana проверяет подпись по ключам IdP и сопоставляет claims с пользователем и ролью.
- **JWKS** — набор публичных ключей IdP (JSON Web Key Set), из которого Grafana берёт ключ для проверки подписи JWT.
- **`role_attribute_path`** — JMESPath-выражение над claims (JWT/OAuth), из которого Grafana вычисляет роль.
- **`assertion_attribute_role` + `role_values_*`** — механизм сопоставления ролей в SAML: имя SAML-атрибута с ролями IdP и списки значений, соответствующих ролям Grafana. Отдельного `role_attribute_path` у SAML нет.
- **`org_mapping`** — сопоставление значений атрибута организации IdP организациям Grafana в формате `Organization:OrgId:Role`.
- **`assertion_attribute_groups` / `groups_attribute_path`** — атрибут или JMESPath-выражение, из которого берутся группы IdP для Team Sync.
- **Team Sync** — автоматическая синхронизация членства в командах Grafana с группами IdP (LDAP/SAML/OAuth). Требует Enterprise.
- **`skip_org_role_sync`** — флаг «не пересчитывать локальную роль пользователя при каждом входе».

## Базовые концепции

### Точки входа (endpoints)

| Endpoint | Назначение |
| --- | --- |
| `/login/saml` | Инициализация веб-входа через SAML (SP-initiated); запускается из формы входа или через `auto_login` |
| `/saml/metadata` | SP-метаданные (Entity ID, ACS URL, публичный сертификат); используется как Entity ID / Audience в IdP |
| `/saml/acs` | Assertion Consumer Service: принимает SAMLResponse от IdP (binding HTTP-POST) |
| `/saml/slo` | Single Logout, если включён `single_logout = true` |
| `/login/<provider>` | Вход через OAuth-провайдера, например `/login/github` |

Grafana поддерживает SP-initiated (по умолчанию) и IdP-initiated вход. IdP-initiated (`allow_idp_initiated = true`) по умолчанию выключен из-за риска CSRF/MITM (см. «Ограничения»).

### Потоки входа

1. **SAML (web SSO):** браузер → `/login/saml` → редирект на IdP с AuthnRequest → пользователь аутентифицируется → IdP POST-ит SAMLResponse на `/saml/acs` → Grafana проверяет подпись (сертификат IdP из метаданных), audience (`entity_id`) и условия assertion (NotBefore/NotOnOrAfter, `max_issue_delay`) → маппит атрибуты в пользователя, роль (`assertion_attribute_role` + `role_values_*`), организации (`assertion_attribute_org` + `org_mapping`) и команды (`assertion_attribute_groups`).
2. **JWT:** шлюз или портал подписывает токен и кладёт его в заголовок (`header_name`) либо в URL-параметр `auth_token` (при `url_login = true`) → Grafana берёт публичный ключ и проверяет подпись, затем `exp`/`nbf`/`iat` и `expect_claims` → определяет пользователя по `username_claim`/`email_claim` и создаёт его при `auto_sign_up = true` → назначает роль через `role_attribute_path`.
3. **LDAP:** bind от имени введённого логина → поиск записи по `search_filter` → `memberOf` (или `group_search_filter`) сравнивается с `group_mappings`; при `active_sync_enabled` синхронизация повторяется по расписанию `sync_cron`.

### Расчёт ролей, организаций и команд

- **Роли (SAML):** значение `assertion_attribute_role` сверяется со списками `role_values_none/viewer/editor/admin/grafana_admin`. Если совпадения нет — назначается `auto_assign_org_role` (по умолчанию `Viewer`).
- **Роли (JWT):** `role_attribute_path` (JMESPath) применяется к claims; при `role_attribute_strict = true` вход без валидной роли запрещается (`auto_assign_org_role` не используется). `allow_assign_grafana_admin = true` разрешает выдать роль Grafana Admin.
- **Организации:** для SAML — `assertion_attribute_org` + `org_mapping`; для JWT — `org_attribute_path` + `org_mapping`. Для SAML вход можно ограничить списком `allowed_organizations`.
- **Команды:** Team Sync сопоставляет группы IdP с командами Grafana по внешнему идентификатору группы (GroupID). Для SAML он берётся из `assertion_attribute_groups`, для LDAP — это DN группы.
- **Роль пересчитывается при каждом входе**, если не задан `skip_org_role_sync`: понизили пользователя в AD — роль упадёт после следующего логина.

### Редакции: OSS и Enterprise

| Возможность | OSS | Enterprise |
| --- | --- | --- |
| LDAP + `group_mappings` (группа → роль org) | да | да |
| JWT-аутентификация | да | да |
| OAuth 2.0 / OIDC | да | да |
| SAML, Single Logout | нет | да |
| Team Sync (LDAP/SAML/OAuth) | нет | да |
| Активная фоновая синхронизация LDAP (enhanced LDAP) | нет | да |

## Практические сценарии

### Предварительные требования

- **Grafana 13.x** (12.x — LTS). SAML, Team Sync и активная LDAP-синхронизация требуют лицензии Enterprise.
- Доступ к `/etc/grafana/grafana.ini` (или переменным `GF_*`) и `/etc/grafana/ldap.toml`, права перезапуска службы.
- Корректный `root_url` в `[server]` — от него зависят ACS URL, Entity ID, cookie и редиректы.
- Синхронизация времени (NTP) между Grafana и IdP: расхождение часов ломает проверку assertion и валидацию `iat`/`nbf` в JWT.
- Для SAML: IdP-метаданные (URL или XML), пара SP-сертификат/ключ. Приватный ключ принимается только в формате **PKCS#8** (`-----BEGIN PRIVATE KEY-----`).
- Для Keycloak как IdP — см. `../Security/Tools/keycloak_overview.md` (realm, clients, mappers).

### Сценарий 1. SAML с Keycloak (Grafana Enterprise)

Минимальная конфигурация веб-входа. Grafana — SP, Keycloak — IdP.

```ini
# grafana.ini
[server]
root_url = https://grafana.example.internal

[auth.saml]
enabled = true
name = Keycloak
# SP-initiated по умолчанию; IdP-initiated оставляем выключенным
allow_idp_initiated = false
auto_login = false
# Создавать пользователя при первом входе (default true)
allow_sign_up = true

# Метаданные IdP (Keycloak realm). Альтернативы: idp_metadata_path, idp_metadata (base64)
idp_metadata_url = https://keycloak.example.com/realms/corp/protocol/saml/descriptor

# Ключи SP (приватный ключ — только PKCS#8)
certificate_path = /etc/grafana/keys/sp-cert.pem
private_key_path = /etc/grafana/keys/sp-key.pem
signature_algorithm = rsa-sha256

# Маппинг атрибутов assertion
assertion_attribute_name   = displayName
assertion_attribute_login  = username
assertion_attribute_email  = email
assertion_attribute_groups = groups
```

В Keycloak: создайте клиент типа SAML. В качестве Client ID / Entity ID укажите SP Entity ID (`https://grafana.example.internal/saml/metadata`), Valid Redirect URI / ACS URL — `https://grafana.example.internal/saml/acs`, и настройте mappers атрибутов `username`, `email`, `displayName`, `groups`.

Проверка SP-метаданных:

```bash
curl -sS https://grafana.example.internal/saml/metadata | head -n 5
# → <EntityDescriptor ...> — SP-метаданные доступны
```

Итоговая проверка — вход тестовым пользователем: роль в UI соответствует ожидаемой, а `GET /api/user` из его сессии показывает ту же роль.

### Сценарий 2. SAML: роли, организации и Team Sync

Продолжение сценария 1 — автоматическое назначение ролей и организаций из атрибутов IdP.

```ini
[auth.saml]
# ...
# Роль: assertion_attribute_role → role_values_*
assertion_attribute_role = role
role_values_none          = none
role_values_viewer        = external
role_values_editor        = editor, developer
role_values_admin         = admin, operator
role_values_grafana_admin = superadmin

# Организации: assertion_attribute_org → org_mapping (Organization:OrgId:Role)
assertion_attribute_org = Org
org_mapping = Engineering:2:Editor, Sales:3:Admin

# Ограничить вход членами организаций IdP (иначе вход разрешён всем аутентифицированным)
allowed_organizations = Engineering, Sales
```

Правила:

- Если значение из `assertion_attribute_role` не совпало ни с одним `role_values_*`, назначается `auto_assign_org_role` (по умолчанию `Viewer`).
- `org_mapping` хранится в БД как JSON; начиная с Grafana 11.5 можно указывать имя организации вместо ID. Синтаксис с пробелами или двоеточиями требует JSON-формы: `org_mapping = ["Org 1:2:Editor", "External\:Admin:ACME Corp:Admin"]`. Не используйте `org_mapping` для дробного разграничения — для этого есть Role/Team Sync.
- Ручные изменения роли и членства в Grafana затираются при следующем входе. Источник истины — IdP.

**Team Sync (Enterprise).** Grafana синхронизирует команды с группами IdP. В `[auth.saml]` задайте `assertion_attribute_groups = groups`, а затем в UI: **Administration → Users and access → Teams → \<team\> → External group sync → Add group**, где GroupID — значение группы из assertion.

> IdP должен передавать каждую группу отдельным элементом `<saml2:AttributeValue>`. Нельзя перечислять группы через запятую в одном значении — это ломает разбор. Team Sync не создаёт команды автоматически: команды в Grafana нужно завести заранее.

### Сценарий 3. Аутентификация по JWT

Случай: внутренний портал аутентифицирует пользователя сам и передаёт его в Grafana подписанным токеном (machine-to-machine или embedding).

```ini
[auth.jwt]
enabled = true
header_name = X-JWT-Assertion

# Идентификация пользователя. sub — обязательный claim; обычно используется как логин.
username_claim = preferred_username
email_claim    = email
# Если нужные claims вложены — используйте JMESPath:
# username_attribute_path = user.username
# email_attribute_path    = user.emails[0]

# Создавать пользователя при первом входе (default false)
auto_sign_up = true

# Проверка подписи по JWKS IdP
jwk_set_url = https://keycloak.example.com/realms/corp/protocol/openid-connect/certs
# Кэш ключей (default 60m); при 0s кэш отключён
cache_ttl = 60m

# Обязательные claims (по умолчанию валидируются только exp/nbf/iat)
expect_claims = {"iss": "https://keycloak.example.com/realms/corp"}

# Роль из claims (JMESPath)
role_attribute_path = "contains(roles[*], 'grafana-admin') && 'Admin' || 'Viewer'"
```

Альтернативные источники ключа (ровно один из вариантов): `jwk_set_file`, `jwk_set_value` (base64 JWKS), `key_file`/`key_value` (одиночный PEM-ключ, при наличии `kid` — вместе с `key_id`). Для самоподписанного JWKS-endpoint — `tls_client_ca`, для отказа от проверки CA — `tls_skip_verify_insecure` (не рекомендуется).

**URL-вход для embedding.** Если заголовок подставить нельзя, включите `url_login = true` — Grafana примет токен из query-параметра `auth_token`:

```
https://grafana.example.internal/d/<uid>/board?orgId=1&kiosk&auth_token=<JWT>
```

> `url_login` может привести к утечке токена в логи и сессионному захвату при отсутствии TLS. Для встраивания требуется `allow_embedding = true` в `[security]`.

Проверка:

```bash
TOKEN_JWT=$(curl -sS "https://keycloak.example.com/realms/corp/protocol/openid-connect/token" \
  -d "client_id=portal" -d "client_secret=$CLIENT_SECRET" -d "grant_type=client_credentials" | jq -r .access_token)

curl -sS -H "X-JWT-Assertion: $TOKEN_JWT" https://grafana.example.internal/api/user
# → JSON пользователя с назначенной ролью (auto_sign_up создал запись)
```

Если JWKS недоступен, в логах будет `failed to verify token`; проверьте сетевую доступность `jwk_set_url` из контура Grafana. Refresh-токены Grafana не поддерживает.

### Сценарий 4. Team Sync и активная синхронизация для LDAP

Базовый `ldap.toml` (host, bind, attributes) описан в [user management](grafana_user_management_and_authentication.md). Здесь — расширенные возможности. **Team Sync для LDAP настраивается не в `ldap.toml`, а на уровне `[auth.ldap]` и в UI/API.**

Активная фоновая синхронизация задаётся в `grafana.ini`:

```ini
[auth.ldap]
enabled = true
config_file = /etc/grafana/ldap.toml
allow_sign_up = true
# Фоновая синхронизация (Enterprise). true по умолчанию.
active_sync_enabled = true
# Расписание в cron-формате; по умолчанию — раз в сутки в 01:00
sync_cron = "0 1 * * *"
```

`ldap.toml` — сопоставление групп с организациями и ролями:

```toml
[[servers]]
host = "ad.example.com"
port = 636
use_ssl = true
bind_dn = "cn=grafana_bind,ou=users,dc=example,dc=com"
bind_password = "$__env{LDAP_BIND_PASSWORD}"
search_filter = "(sAMAccountName=%s)"
search_base_dns = ["dc=example,dc=com"]

[servers.attributes]
member_of = "memberOf"
email     = "mail"
username  = "sAMAccountName"

[[servers.group_mappings]]
group_dn = "cn=grafana-admins,ou=groups,dc=example,dc=com"
org_role = "Admin"
org_id   = 1
grafana_admin = true

[[servers.group_mappings]]
group_dn = "cn=grafana-devops,ou=groups,dc=example,dc=com"
org_role = "Editor"
org_id   = 2

# Перехват всех, кто не попал в предыдущие правила
[[servers.group_mappings]]
group_dn = "*"
org_role = "Viewer"
```

Правила сопоставления:

- Применяется **первое сверху** совпавшее правило; порядок блоков значим.
- `org_id` задаёт целевую организацию (по умолчанию 1); `grafana_admin = true` делает пользователя серверным администратором.
- При активной синхронизации `search_filter` и `servers.attributes.username` должны совпадать, иначе сессии пользователей будут сбрасываться после каждой синхронизации.

**Team Sync для LDAP** — синхронизация команд с LDAP-группами. GroupID — DN группы; включая wildcard, например `cn=*,ou=groups,dc=example,dc=com`. Настройка через UI (**Administration → Users and access → Teams → \<team\> → External group sync → Add group**), через API `POST /api/teams/:teamId/groups` или Terraform (`grafana_team_external_group`).

Проверка bind вне Grafana:

```bash
ldapsearch -H ldaps://ad.example.com:636 -D "cn=grafana_bind,ou=users,dc=example,dc=com" \
           -W -b "dc=example,dc=com" "(sAMAccountName=alice)" memberOf
# → запись пользователя и список memberOf (должен содержать group_dn из mappings)
```

Особенности активной синхронизации: синхронизируются только пользователи, входившие хотя бы раз; удалённые из LDAP аккаунты отключаются и разлогиниваются (остаются с меткой `disabled`); пользователям с изменёнными ролью/командами нужно обновить страницу. Single-bind конфигурация (bind по `bind_dn` с `%s`) с активной синхронизацией не поддерживается.

### Сценарий 5. Отладка и проверка маппингов

**Проверка JMESPath до прода** (актуально для JWT и OAuth):

```bash
# jmespath-terminal (pip install jmespath-terminal), команда jp
echo '{"roles":["grafana-editors","devs"]}' | jp "contains(roles[*], 'grafana-admin') && 'Admin' || contains(roles[*], 'grafana-editors') && 'Editor' || 'Viewer'"
# → "Editor"
```

**Диагностические логи** включаются фильтрами в `grafana.ini`:

```ini
[log]
# Выбрать нужный логгер:
# filters = saml.auth:debug
# filters = auth.jwt:debug
# filters = ldap:debug
```

> `saml.auth:debug` пишет полный SAML assertion (персональные данные) в лог — включайте точечно и ненадолго, после отладки убирайте фильтр.

## Дополнительная информация

### Рекомендации по эксплуатации

- Источник истины ролей и организаций — IdP. Не правьте роли в Grafana вручную: они затрутся следующим логином.
- `skip_org_role_sync = true` применяйте только там, где роли назначаются через RBAC/Terraform (см. [Fine-grained RBAC](grafana_rbac_fine_grained.md)).
- Держите два набора SP-ключей для ротации без простоя: заранее опубликуйте новый сертификат, затем переключите ключ.
- JWKS у IdP кэшируется (`cache_ttl`, по умолчанию 60 минут). После ротации ключей IdP либо дождитесь истечения кэша, либо перезапустите Grafana.
- Тестируйте вход минимум тремя учётками: админ, редактор, обычный пользователь, а также пользователь без групп (ожидаемо Viewer или отказ при `role_attribute_strict`).
- Секреты (`private_key`, `bind_password`, `client_secret`) передавайте через файлы или `${ENV_VAR}`/`$__env{...}`, не храните в Git.
- Не смешивайте несколько методов аутентификации для одних и тех же пользователей: ручные правки в БД затираются следующим синхронизированным входом.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| SAML: `Invalid assertion` / NotOnOrAfter | Расхождение часов SP↔IdP или истёк `max_issue_delay` | NTP на обоих узлах; при необходимости поднять `max_issue_delay` |
| SAML: `asn1: structure error: tags don't match` | Приватный ключ не в формате PKCS#8 | Переконвертировать ключ в PKCS#8 |
| SAML: бесконечный редирект после входа | `cookie_samesite = strict` | Выставить `cookie_samesite = lax` |
| SAML: `origin not allowed` | CSRF-проверка при входе через IdP/прокси | Задать `csrf_trusted_origins` (и при необходимости `csrf_additional_headers`) |
| SAML: `login session has expired` | Cookie выставлены не на домене `root_url` | Согласовать cookies прокси с `root_url`; `cookie_samesite = lax` |
| Все входят как Viewer | Значение `assertion_attribute_role` не совпало с `role_values_*` (SAML) или `role_attribute_path` вернул null (JWT) | Прогнать JMESPath на дампе claims / проверить атрибуты assertion |
| SAML: `x509: certificate signed by unknown authority` | Сертификат IdP не доверен или метаданные устарели | Обновить метаданные; добавить CA в trust store контейнера |
| JWT: `failed to verify token` | Недоступен JWKS, неверный issuer или `kid` не найден | Проверить `jwk_set_url` из сети Grafana, сверить `expect_claims` и `key_id` |
| Пользователь «заморожен» со старой ролью | Задан `skip_org_role_sync` | Синхронизация отключена осознанно; менять роли через RBAC/API |
| Team Sync убирает участников команды | Группа IdP изменилась — синхронные участники удаляются | Управлять составом групп на стороне IdP (вручную добавленные пользователи сохраняются) |
| LDAP: сессии сбрасываются после синхронизации | `search_filter` не совпадает с `servers.attributes.username` | Привести атрибут и фильтр к одному значению |

### Ограничения и особые случаи

- `[auth.saml]`, Team Sync и активная LDAP-синхронизация требуют лицензии Enterprise; JWT, OAuth/OIDC и базовый LDAP доступны в OSS.
- Grafana поддерживает один SAML IdP одновременно.
- SAML работает только для веб-входа; для API/автоматизации нужны сервисные аккаунты (SA-токены) или JWT.
- IdP-initiated вход (`allow_idp_initiated = true`) уязвим к login-CSRF и MITM: Grafana не может проверить, что поток инициировал пользователь. Оставляйте выключенным, если он не требуется явно.
- Один источник ключа JWT одновременно: нельзя задавать более одного из `key_file`, `key_value`, `jwk_set_file`, `jwk_set_value`, `jwk_set_url`.
- JWT не поддерживает refresh-токены; Grafana не обновляет их автоматически.
- `url_login` раскрывает токен в URL и логах — применим только по HTTPS и в доверенном контуре.
- Настройки SAML, заданные через UI или SSO Settings API, имеют приоритет над `grafana.ini` (порядок источников: API > env > файл > значения по умолчанию).

### Очистка и откат изменений

- Перед экспериментами сохраните `grafana.ini` и `ldap.toml`.
- Откат SSO: выставить `enabled = false` в нужной секции `[auth.*]` и перезапустить Grafana. Пользователи, созданные через SSO, остаются в БД — удаляйте их через Server Admin, если они не нужны.
- После отладки убрать фильтры `*=:debug` из `[log]`.
- Бэкапы БД (`grafana.db` для SQLite, `pg_dump` для PostgreSQL) содержат пользователей и токены — включайте их в регулярный бэкап.

### Актуальность и статус

- Актуальная линейка: **13.2.3** (текущая, сентябрь 2026), **12.x** — LTS.
- Секции `[auth.saml]` и `[auth.jwt]` стабильны между мажорными версиями; `role_values_*` / `assertion_attribute_role` и JMESPath `role_attribute_path` используются длительное время без изменений синтаксиса.
- Single Logout для SAML и активная LDAP-синхронизация относятся к Enterprise.

### Связанные темы

- [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md) — базовый OAuth/LDAP, SA, auth proxy, RBAC
- [Fine-grained RBAC](grafana_rbac_fine_grained.md)
- [Безопасность и жёсткая настройка](grafana_security_hardening.md)
- `../Security/Concepts/jwt_overview.md`, `../Security/Concepts/oauth2_overview.md` — теория протоколов
- `../Security/Tools/keycloak_overview.md` — настройка Keycloak как IdP
