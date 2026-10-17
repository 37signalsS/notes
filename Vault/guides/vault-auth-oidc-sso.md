# OIDC аутентификация в Vault (SSO)

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**OIDC (OpenID Connect)** — протокол поверх OAuth 2.0, дающий приложению проверенную идентичность пользователя (ID token) и его атрибуты (claims). В Vault используется как метод аутентификации людей через корпоративный IdP (Keycloak, Okta, Entra ID, Google Workspace).

**OIDC auth method** — монтируется на `auth/oidc`, строит авторизационный URL на IdP, принимает callback с кодом, обменивает его на токены и выдаёт Vault-токен с политиками роли.

**JWT (JSON Web Token)** — подписанный токен с claims. В Vault два разных применения: `oidc` — для людей через browser flow; `jwt` — для машин, когда доверенный сервис присылает свой JWT напрямую (CI/CD, GitHub Actions) — паттерн описан в [Основных концепциях](../concepts.md).

**Redirect URI** — URL, на который IdP возвращает пользователя с кодом авторизации. Должен точно совпадать с зарегистрированным в клиенте IdP; vault_url + `oidc_callback` = `<vault_addr>/v1/auth/oidc/oidc/callback`.

**Claims** — поля ID token (`sub`, `email`, `groups`, `preferred_username`). Через `claims_role` (or `bound_claims` в роли) и `user_claim` Vault превращает их в имя пользователя, а через `groups_claim` → Identity → политики — в права доступа.

**OIDC roles** — записи `auth/oidc/roles/<name>`: привязывают allowlisted атрибуты (`bound_subject`, `bound_email`, `bound_claims`, `allowed_redirect_uris`, `user_claim`, `groups_claim`) к выдаваемым политикам.

## Основные концепции

### Поток входа

1. Пользователь открывает Vault UI/CLI: `vault login -method=oidc`.
2. Vault редиректит на `authorization_endpoint` IdP с `client_id`, `scope=openid profile email groups`, `state`, `nonce`.
3. Пользователь проходит вход на IdP; IdP редиректит обратно на Vault callback с `code`.
4. Vault обменивает `code` на `id_token`/`access_token` (client secret или PKCE), проверяет подпись, `iss`, `aud`, `nonce`.
5. По `user_claim` определяется пользователь, по `groups_claim` — членство в группах → Identity entities/groups → политики → выдаётся Vault-токен.

### Два уровня привязки: config и role

В `auth/oidc/config` — параметры доверия к IdP:

```bash
vault write auth/oidc/config \
    oidc_discovery_url="https://keycloak.corp.example.com/realms/corp" \
    oidc_client_id="vault" \
    oidc_client_secret='<client-secret>' \
    default_role="default"
```

В роли — условия на конкретного пользователя/приложение:

```bash
vault write auth/oidc/roles/engineer \
    user_claim="email" \
    groups_claim="groups" \
    bound_redirect_uris="https://vault.corp.example.com/v1/auth/oidc/oidc/callback" \
    oidc_scopes="profile,email,groups" \
    policies="engineer" \
    ttl="1h"
```

Отдельные параметры в духе `bound_issuer`/`bound_audiences` относятся к **роле** (для machine-to-machine JWT роли — `auth/jwt/roles/<name>`), а не к конфигурации метода.

### Привязка групп к политикам через Identity

`groups_claim` не даёт политик напрямую. Цепочка:

1. Роль кладёт groups из claims в Identity entity пользователя.
2. Identity group имеет `policies` (или маппится через `identity/groups/<name>`).
3. Vault-токен получает политики = политики роли + политики групп.

Альтернативный источник групп — не Identity, а сама роль: через `bound_claims` (например `"groups": ["platform"]`) можно жёстко привязать политики к принадлежности к группе; для динамического маппинга произвольного набора групп в политики используется Identity (см. ниже).

### Сравнение OIDC и JWT для входа

| | `oidc` | `jwt` |
| :--- | :--- | :--- |
| Кто входит | Человек через browser | Сервис с собственным JWT |
| Нужен client secret / PKCE | Да | Нет |
| `jwks_uri` | Обнаруживается через discovery | Задаётся явно или через discovery |
| Основной bind | `bound_subject`, `bound_claims` по id token | `bound_claims`, `bound_audiences` по сервисному JWT |
| Где в базе | тема ниже | [Основные концепции](../concepts.md) — CI/CD паттерн |

## Практические сценарии

### Keycloak: регистрация клиента

1. Realm → Clients → Create client: Client ID `vault`, Protocol `openid-connect`.
2. Valid Redirect URIs: `https://vault.corp.example.com/v1/auth/oidc/oidc/callback`.
3. Client authentication ON, Service accounts OFF; взять Client Secret.
4. Mappers на группу: добавить в client scope групповой mapper (`Group Membership`, `groups`, `full path` — как требует `groups_claim`).

### Включение метода и роли

```bash
vault auth enable oidc

vault write auth/oidc/config \
    oidc_discovery_url="https://keycloak.corp.example.com/realms/corp" \
    oidc_client_id="vault" \
    oidc_client_secret='<client-secret>' \
    default_role="default"

vault write auth/oidc/roles/default \
    user_claim="email" \
    groups_claim="groups" \
    bound_redirect_uris="https://vault.corp.example.com/v1/auth/oidc/oidc/callback" \
    oidc_scopes="profile,email,groups" \
    policies="readonly" \
    ttl="8h"

vault login -method=oidc
# → Opening the browser... (ввод на странице IdP, затем Authentication successful)
```

### Политики для групп из Identity

```bash
# После первого входа entity пользователя виден в Identity
vault read identity/entity/name/alice@corp.example.com

vault write identity/group/name/platform \
    policies="deploy" \
    member_entity_ids="<entity-id>"
```

### Проверка claims

```bash
vault token lookup
# → token_policies, meta (entity), ttl — проверяем, что политики пришли из ожидаемых групп
```

## Устранение неполадок

| Симптом | Причина | Действия |
| :--- | :--- | :--- |
| `redirect URI mismatch` / ошибка на стороне IdP | `allowed_redirect_uris` в роли не совпадает с URI в клиенте IdP (включая схему, порт, точный путь) | Сверьте строки побайтно |
| Вход проходит, политики пустые | Нет групп в claims или `groups_claim` не совпадает с именем клейма | Проверьте mapper групп на IdP, `groups_claim` в роли |
| `oidc: claim is not a string` при `user_claim` | Заявленный claim имеет не строковый тип (например, массив) | Смените `user_claim` на строковый (`email`, `preferred_username`) |
| `token expired`/неверная подпись | В discovery-документе другой issuer; склонированный realm с чужим secret | Сверьте `oidc_discovery_url` и secret |
| Callback 404 | Метод смонтирован не на `oidc`/не тот `vault_addr` за балансировщиком | `vault read auth/oidc/config`, проверьте `X-Vault-Namespace` и путь за LB |
| CLI не открывает браузер | Headless-сервер | Используйте UI по ссылке, которую печатает CLI, или `vault login -method=oidc` на рабочей машине |

## Лучшие практики

* Только HTTPS callback; `allowed_redirect_uris` — точный список, без wildcard.
* `oidc_scopes` — минимально необходимый список через запятую (scope `openid` добавляется Vault автоматически; `groups` запрашивать только где нужен).
* Роль по умолчанию (`default_role`) — read-only политики; привилегированные роли — явный allowlist `bound_*`.
* Токены: `ttl=8h` и меньше для людей; после блокировки пользователя на IdP действующие Vault-токены нужно отзывать отдельно (`vault token revoke -accessor`).
* Client secret хранить как секрет (не в HCL/git); для public-клиентов используйте PKCE-режим через параметры конфига.
* Разделять realms/клиенты по средам — dev/stage/prod не должны делить redirect URI.

## Дополнительная информация

* [Основные концепции](../concepts.md) — таблица auth-методов и JWT для CI/CD
* [Аутентификация и авторизация](../authorization.md) — политики и Identity
* [LDAP аутентификация](./vault-auth-ldap.md) — альтернативный вход для людей из корпоративного каталога
* [MFA](./vault-mfa.md) — второй фактор поверх OIDC
* [Vault API Reference](./vault_api_reference.md) — curl-примеры API
