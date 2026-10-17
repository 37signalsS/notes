# LDAP аутентификация в Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**LDAP auth method** — метод аутентификации в Vault, при котором Vault выступает как LDAP-клиент: он выполняет поиск учётной записи пользователя в каталоге (OpenLDAP, Active Directory и совместимые) и проверяет пароль через bind-операцию.

**Bind DN (Distinguished Name)** — DN учётной записи, которой Vault ищет пользователя в каталоге. В привилегированном режиме (`binddn` + `bindpass`) используется «служебный» bind user с правами на поиск; в анонимном режиме — анонимный bind (не подходит для продакшена).

**UserDN / UserAttr** — откуда берётся DN пользователя для проверки пароля: `userattr` определяет атрибут, по которому строится DN (или значение используется напрямую при `userattr=dn`), `userdn` — база поиска пользователей.

**UserFilter / GroupFilter** — фильтры поиска в формате Go template: `{{.Username}}`, `{{.UserDN}}`, `{{.UserAttr}}`, `{{.Query}}`, `{{.UPN}}`. Именно так пишутся параметры `userfilter` и `groupfilter` — с одним словом, без подчёркивания.

**UPN (User Principal Name)** — атрибут формата `user@domain` в Active Directory. Режим `upndomain` строит UPN как `{{.Username}}@<upndomain>` и ищет пользователя напрямую по UPN, минуя обычную иерархию DN.

**GroupResolver** — механизм, которым Vault разрешает членство пользователя в группах: `ldap` (запросы к каталогу), `noop` (группы берутся из атрибута пользователя), `token` (из claims токена). Членство групп маппится на политики через `auth/ldap/groups/<name>`.

## Основные концепции

### Схема входа

1. Пользователь вызывает `vault login -method=ldap username=<user>` (или API `POST /auth/ldap/login/<username>`).
2. Vault находит DN пользователя по `userdn`/`userattr` (или `upndomain`) и `userfilter`.
3. Vault выполняет bind от имени пользователя с указанным паролем.
4. При успехе Vault разрешает группы пользователя (`groupattr`, `groupfilter`) и выдаёт токен с политиками, назначенными роли (`auth/ldap/roles/<name>`), группам (`auth/ldap/groups/<name>`) и пользователю (`auth/ldap/users/<name>`).

### Назначение политик: три источника

Политики токена складываются из трёх мест:

```bash
vault write auth/ldap/roles/deployers policies="deployers,readonly"
vault write auth/ldap/groups/platform-admins policies="admins"
vault write auth/ldap/users/alice policies="break-glass"
```

Параметр политики здесь — `policies` (множественное число, значения через запятую): он задаётся в записи роли/группы/пользователя, а не в `auth/ldap/config`.

### Разрешение групп и синхронизация состояния

* Группы разрешаются при каждом входе. Изменения членства в каталоге действуют на **новые** токены: существующие токены не пересчитываются — после изменения групп их нужно отзывать вручную (`vault token revoke`).
* При `groupauthstrategy=userattr` группы берутся из атрибута пользователя (`groupattr`, например `memberOf`) без отдельных запросов к каталогу.
* Групповой DN групп маппится на политики по короткому имени (RDN) либо по полному DN — см. `groupdn` в роли.

### User lockout

Начиная с Vault 1.13 для методов аутентификации включён **user lockout по умолчанию**: после 5 неудачных попыток учётная запись блокируется на 15 минут, счётчик сбрасывается через 15 минут. Параметры настраиваются на mount:

```bash
vault auth tune -path=ldap \
    user_lockout="true" \
    lockout_threshold="5" \
    lockout_duration="15m" \
    lockout_counter_reset_duration="15m"
```

Lockout защищает каталог от перебора паролей, но требует учёта при штатных ошибках: неудачные попытки старых CI-джоб могут заблокировать сервисный аккаунт. Подробнее о скоупе и исключениях — в [quotas](./quotas.md).

### Ротация bind-пользователя

Пароль bind user хранится в Vault. Ротация выполняется без остановки:

```bash
vault write -f auth/ldap/config/rotate-root
```

Vault генерирует новый пароль, обновляет его в LDAP, затем в своей конфигурации. Выполнять ротацию должен оператор с правами `update` на `auth/ldap/config/rotate-root`; исходный пароль bind user, известный Vault, считается скомпрометированным после ручных смен.

## Практические сценарии

### OpenLDAP: аутентифицированный поиск

```bash
# Включение метода (кастомный путь — опционально; по умолчанию auth/ldap)
vault auth enable ldap

vault write auth/ldap/config \
    url="ldaps://ldap.corp.example.com:636" \
    userdn="ou=users,dc=corp,dc=example,dc=com" \
    userattr="uid" \
    groupdn="ou=groups,dc=corp,dc=example,dc=com" \
    groupattr="memberOf" \
    binddn="cn=vault-bind,ou=service,dc=corp,dc=example,dc=com" \
    bindpass='<bind-password>' \
    tls_skip_verify="false" \
    starttls="true" \
    insecure_tls="false"

vault write auth/ldap/roles/platform policies="default,policy-app"
vault write auth/ldap/groups/developers policies="policy-app"

vault login -method=ldap username=alice
# → Authentication (method: ldap) successful
```

В продакшене `insecure_tls` и `tls_skip_verify` остаются `false`; для внутреннего CA добавьте `certificate=@/etc/vault.d/ca.pem` вместо отключения проверки.

### Active Directory: режим UPN и вложенные группы

```bash
vault write auth/ldap/config \
    url="ldaps://ad.corp.example.com:636" \
    userdn="dc=corp,dc=example,dc=com" \
    userattr="userPrincipalName" \
    upndomain="corp.example.com" \
    groupdn="dc=corp,dc=example,dc=com" \
    groupattr="memberOf" \
    groupfilter="(&(objectClass=group)(member:1.2.840.113556.1.4.1941:={{.UserDN}}))" \
    userfilter="(&(objectClass=user)(userPrincipalName={{.UPN}}))" \
    binddn="CORP\\vault-bind" \
    bindpass='<bind-password>' \
    resolve_group_memberships="true"
```

* `upndomain` — поиск по `alice@corp.example.com` вместо обхода иерархии DN.
* `groupfilter` с OID `1.2.840.113556.1.4.1941` (LDAP_MATCHING_RULE_IN_CHAIN) — разрешение **вложенных** групп AD.
* `resolve_group_memberships=true` — вложенные группы разворачиваются в полный список членства.

### Проверка соответствия пользователя и политик

```bash
vault login -method=ldap username=alice
vault token lookup          # → policies: [...], policies должны содержать назначенные роли/группы
vault read auth/ldap/roles/platform
vault read auth/ldap/groups/developers
```

### Диагностика конфигурации

```bash
# Текущая конфигурация (bindpass возвращается маскированным)
vault read auth/ldap/config

# Контрольный вход тестовым пользователем
vault login -method=ldap username=ci-bot
```

Ошибки поиска (`user not found in ...`) отделяются от ошибок bind (`invalid credentials`) по тексту ответа: первая — проблема `userdn`/`userattr`/`userfilter`, вторая — пароль или bind DN.

## Устранение неполадок

| Симптом | Причина | Действия |
| :--- | :--- | :--- |
| `user not found in <base DN>` | Неверный `userdn`/`userattr`/`userfilter` | Проверьте базу поиска и атрибут; для AD проверьте `upndomain` |
| `invalid credentials` при верном пароле | Bind DN некорректен или нет прав на чтение пользователя | Проверьте `binddn`/`bindpass`, права bind user на базу поиска |
| Пользователь входит, но политики не те | Нет записи в `auth/ldap/groups/<name>` либо `groupattr` не возвращает членства | `vault read auth/ldap/groups/<name>`, проверьте `groupfilter`/`resolve_group_memberships` |
| Изменение групп не действует на открытый токен | Существующие токены не пересчитываются | Отзовите токены: `vault token revoke -accessor <accessor>` |
| Блокировка после серии попыток | User lockout включён по умолчанию (threshold 5) | Дождитесь `lockout_duration` или снимите lockout через `auth tune` осознанно |
| `tls: bad certificate` | Самоподписанный CA каталога | Добавьте сертификат CA в `certificate=`, не отключайте `insecure_tls` |
| `permission denied` на `rotate-root` | Нет capability `update` на `auth/ldap/config/rotate-root` | Добавьте capability в политику оператора |

## Лучшие практики

* Bind user — минимально необходимые права (чтение баз пользователей/групп), отдельная учётная запись, ротация через `rotate-root` по расписанию.
* Только LDAPS/StartTLS, `insecure_tls=false`, явный `certificate` для корпоративного CA.
* Группы — основной источник политик; индивидуальные `auth/ldap/users/<name>` только для исключений (break-glass).
* После изменения групп/политик в каталоге отзывайте активные токены затронутых пользователей.
* User lockout оставляйте включённым; исключения (сервисные аккаунты с автоматическими попытками) решайте корректировкой `lockout_threshold`, а не полным отключением.
* `groupfilter` по умолчанию (`(objectClass=group)`) не разрешает вложенные группы AD — в AD-окружениях всегда проверяйте сценарий вложенных групп.

## Дополнительная информация

* [Основные концепции Vault](../concepts.md) — общая таблица методов аутентификации
* [Аутентификация и авторизация](../authorization.md) — политики и capability
* [AppRole](./vault_auth_approle.md) — M2M-альтернатива для машин
* [Rate limit и lease quotas](./quotas.md) — блокировки, лимиты запросов, аудит отказов
* [Vault API Reference](./vault_api_reference.md) — curl-примеры LDAP auth API
* LDAP fundamentals в базе: `LDAP/ldap_fundamentals.md`
