# Grafana: Enterprise SSO — SAML, JWT и расширенный LDAP

Практическое руководство по интеграции Grafana с корпоративными провайдерами аутентификации: SAML (Enterprise), JWT-заголовки для сервисных сценариев, продвинутый LDAP (team sync, multi-org). Базовый OAuth (GitHub/Keycloak) и первичная настройка LDAP — в [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md); теория протоколов — в `../Security/Concepts/`.

## Определения

- **SAML 2.0** — XML-протокол федеративной аутентификации: IdP подписывает assertion, Grafana (SP) проверяет его по метаданным/сертификату. В Grafana доступен с лицензией Enterprise.
- **JWT auth** — вход по подписанному токену в HTTP-заголовке или URL-параметре; Grafana проверяет подпись по JWKS-ключам IdP. Для машинных и reverse-proxy сценариях.
- **JWKS** — набор публичных ключей IdP (`/.well-known/jwks.json` или OpenID Connect certs endpoint), которым Grafana проверяет подпись JWT.
- **role_attribute_path** — JMESPath-выражение над claims/assertion, из которого Grafana вычисляет роль (`Viewer`/`Editor`/`Admin`).
- **Team Sync** — автоматическое членство в командах Grafana на основе групп IdP (LDAP/SAML/OAuth).
- **org_mapping** (SAML) — сопоставление групп IdP → организация Grafana + роль в ней.
- **skip_org_role_sync** — флаг «не менять локальную роль пользователя при каждом логине».

## Базовые концепции

Потоки входа:

1. **SAML (web SSO):** браузер → `/login/saml` → редирект на IdP → POST assertion на `/saml/acs` → Grafana проверяет подпись, аудиторию и время → вычисляет роль из `role_attribute_path`, организации из `org_mapping`, команды через Team Sync.
2. **JWT:** клиент/шлюз кладёт токен в заголовок (например `X-JWT-Assertion`) → Grafana достаёт публичный ключ из JWKS (кэшируется), проверяет подпись/exp/claims → создаёт пользователя при `auto_sign_up = true`.
3. **LDAP:** bind от имени введённого логина → поиск записи → `memberOf` сравнивается с `group_mappings`; при `active_sync_enabled` синхронизация повторяется периодически.

Ключевые правила эксплуатации:

- Роль из IdP пересчитывается **при каждом входе** (если не задан `skip_org_role_sync`): понизили группу в AD — роль упадёт после следующего логина.
- Часы! SAML-assertions живут минуты (`valid_for`), расхождение времени SP↔IdP ломает вход ошибкой «invalid assertion».
- Секреты (`sp_private_key`, `bind_password`, клиентские секреты) — через файлы или `${ENV_VAR}` в конфиге, не в Git.

## Практические сценарии

### Предварительные требования

- Доступ к `grafana.ini` и правам перезапуска сервиса.
- Для SAML: лицензия Enterprise, метаданные IdP (URL или XML), пара сертификат/ключ SP.
- Для Keycloak как IdP — см. `../Security/Tools/keycloak_overview.md` (создание realm, clients, mappers).

### Сценарий 1. SAML с Keycloak (Enterprise)

```ini
# grafana.ini
[auth.saml]
enabled = true
auto_sign_up = true

# Метаданные IdP (Keycloak realm)
idp_metadata_url = https://keycloak.example.com/realms/corp/protocol/saml/descriptor

# Ключи SP (Grafana как service provider)
certificate_path = /etc/grafana/keys/sp-cert.pem
private_key_path = /etc/grafana/keys/sp-key.pem

# Атрибуты assertion
assertion_attribute_login = username
assertion_attribute_email  = email
assertion_attribute_groups = groups

# Роль из групп IdP (JMESPath)
role_attribute_path = "contains(groups[*], 'grafana-admin') && 'Admin' || contains(groups[*], 'grafana-editors') && 'Editor' || 'Viewer'"

# Группы → организации (опционально)
# org_mapping = grafana-admins:1:Admin grafana-users:1:Viewer

# Группы → команды Grafana (Team Sync)
# team_ids_attribute = groups
```

В Keycloak: client типа SAML, Audience = `https://grafana.example.internal/saml/metadata`, mapper группы в атрибут `groups`.

Проверка:

```bash
curl -sS "$GRAFANA/saml/metadata" | head -5
# → <EntityDescriptor ...> — SP-метаданные доступны
curl -sS "$GRAFANA/saml/acs" -X GET
# → GET даёт страницу ошибки метода (нормально), POST принимает assertion от IdP
```

Полная проверка — входом тестового пользователя из каждой группы: роль в UI совпадает с ожидаемой (`GET /api/user` от его сессии).

### Сценарий 2. Вход по JWT (машинные пользователи / шлюз)

Случай: внутренний портал сам аутентифицирует пользователей и передаёт их в Grafana подписанным токеном.

```ini
[auth.jwt]
enabled = true
header_name = X-JWT-Assertion
jwk_set_url = http://keycloak:8080/realms/corp/protocol/openid-connect/certs
auto_sign_up = true
email_claim = sub
username_claim = preferred_username
name_claim = name
# Роль из claims
role_attribute_path = "contains(roles[*], 'grafana-admin') && 'Admin' || 'Viewer'"
expect_claims = {"iss": "https://keycloak.example.com/realms/corp"}
```

Проверка:

```bash
TOKEN_JWT=$(curl -sS "http://keycloak:8080/realms/corp/protocol/openid-connect/token" \
  -d "client_id=portal&grant_type=client_credentials" | jq -r .access_token)

curl -sS "$GRAFANA/api/user" -H "X-JWT-Assertion: $TOKEN_JWT"
# → JSON пользователя (auto_sign_up создал запись)
```

Если JWKS недоступен — в логах будет `failed to verify token`; проверьте сетевую доступность `jwk_set_url` из контура Grafana.

### Сценарий 3. Расширенный LDAP: Team Sync, multi-org, active sync

Дополняет базовый `ldap.toml` из [user management](grafana_user_management_and_authentication.md):

```toml
[[servers]]
host = "ad.example.com"
port = 636
use_ssl = true
# Периодическая ресинхронизация ролей/команд (минуты)
active_sync_enabled = true

[[servers.group_mappings]]
group_dn = "cn=grafana-admins,ou=groups,dc=example,dc=com"
org_role = "Admin"
org_id   = 1          # целевая организация (multi-org)

[servers.group_mappings.team_sync]
    [[servers.group_mappings.team_sync.teams]]
    name = "Platform Core"
    id   = 2           # teamId в Grafana

[[servers.group_mappings]]
group_dn = "cn=grafana-devops,ou=groups,dc=example,dc=com"
org_role = "Editor"
org_id   = 2
[servers.group_mappings.team_sync]
    [[servers.group_mappings.team_sync.teams]]
    name = "DevOps"
    id   = 7
```

Проверка:

```bash
# Маппинг конкретного пользователя без входа (Server Admin → LDAP → Test mapping в UI),
# либо трассировкой:
grep -n "filters" /etc/grafana/grafana.ini
# [log] filters = ldap:debug
journalctl -u grafana-server | grep -i ldap | tail
# → "LdapSyncJob completed", memberOf содержит ожидаемые DN
```

Членство в командах обновляется при входе и при periodic sync; ручное добавление таких пользователей в команды будет перезаписано.

### Сценарий 4. Отладка role_attribute_path (JMESPath)

Перед продом проверяйте выражение на реальном claim-дампе:

```bash
# Установить jmespath-cli (pip install jmespath-terminal) и прогнать:
echo '{"groups":["grafana-editors","devs"]}' | jp "contains(groups[*], 'grafana-admin') && 'Admin' || contains(groups[*], 'grafana-editors') && 'Editor' || 'Viewer'"
# → "Editor"
```

Если выражение не сработало в проде, временно включите дамп claims:

```ini
[auth.saml]
debug_mode = true     # писать assertion в лог (только временно!)
[log]
filters = saml:debug
```

## Дополнительная информация

### Рекомендации по эксплуатации

- Источник истины ролей — группы IdP; в Grafana роли вручную не правьте, иначе они затрутся следующим логином.
- `skip_org_role_sync = true` только там, где роли назначаются RBAC/Terraform (см. [Fine-grained RBAC](grafana_rbac_fine_grained.md)).
- Для SAML держите два набора ключей SP заранее (ротация без простоя): старый сертификат оставляйте вторым в цепочке проверки.
- JWKS у IdP кэшируется: после ротации ключей IdP перезапустите Grafana или дождитесь обновления кэша.
- Тестируйте вход тремя учётками: админ, редактор, обычный пользователь + пользователь без групп (ожидаемо Viewer или отказ).

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| `Invalid assertion` / NotOnOrAfter | Расхождение часов SP↔IdP | NTP на обоих узлах |
| Все входят как Viewer | `role_attribute_path` вернул null/false → дефолт Viewer | Прогнать JMESPath на дампе claims (сценарий 4) |
| SAML: `x509: certificate signed by unknown authority` | Самоподписанный/промежуточный сертификат IdP не доверен | Добавить CA в trust store контейнера Grafana |
| JWT: `failed to verify token` | Недоступен JWKS или неверный issuer | Проверить `jwk_set_url` из сети Grafana, сверить `expect_claims` |
| Пользователь «заморожен» со старой ролью | Задан `skip_org_role_sync` | Синхронизация отключена осознанно; менять роли через API/RBAC |
| Team Sync стирает ручное членство | Ожидаемое поведение | Управлять составом команд на стороне IdP |

### Ограничения и особые случаи

- `[auth.saml]` требует лицензию Enterprise; OAuth/OIDC и LDAP доступны в OSS.
- SAML — веб-only: для API/автоматизации всё равно нужны SA-токены или JWT.
- `debug_mode` пишет assertions (персональные данные!) в лог — включать точечно и ненадолго.
- Один провайдер каждого типа одновременно: второй SAML IdP потребует Enterprise-лицензии соответствующего уровня.

### Очистка и откат изменений

- Перед экспериментами сохраните `grafana.ini` и `ldap.toml`.
- Откат SSO: выключить секцию (`enabled = false`), рестарт; пользователи, созданные через SSO, остаются в БД — удалить через Server Admin, если не нужны.
- После отладки убрать `debug_mode` и `filters = *:debug`.

### Актуальность и статус

Конфигурации актуальны для 12.x LTS/13.x; секции `[auth.saml]`/`[auth.jwt]` меняются между мажорными версиями редко. `role_attribute_path` (JMESPath) стабилен с 7.x. Team Sync LDAP стабилен, `active_sync_enabled` поддерживается давно.

### Связанные темы

- [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md) — базовый OAuth/LDAP, SA, auth proxy
- [Fine-grained RBAC](grafana_rbac_fine_grained.md)
- [Безопасность и жёсткая настройка](grafana_security_hardening.md)
- `../Security/Concepts/jwt_overview.md`, `../Security/Concepts/oauth2_overview.md` — теория протоколов
- `../Security/Tools/keycloak_overview.md` — настройка Keycloak как IdP
