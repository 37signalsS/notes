# Multi-Factor Authentication в Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Login MFA** — вторая фактора аутентификации при входе в Vault. Доступна в **Vault Community** с версии 1.10: настраивается через `identity/mfa/method/...` и `identity/mfa/login-enforcement/...`, проверяется на этапе входа через auth method.

**Step-up MFA** — требование второго фактора для отдельных чувствительных путей, уже после выдачи токена. Доступна только в **Vault Enterprise**: методы создаются в `sys/mfa/method/...`, требование задаётся полем `mfa_methods` в ACL/Sentinel-политике.

**TOTP (Time-based One-time Password)** — одноразовый код по RFC 6238 (Google Authenticator, 1Password, Yubico Authenticator и др.). Поддерживается как Login MFA, так и Step-up MFA.

**Login enforcement** — запись `identity/mfa/login-enforcement/<name>`, связывающая MFA-методы с областью применения: accessors методов, типы методов, identity-группы или entity.

**MFA-метод** — запись конфигурации второго фактора. В Login MFA создаётся через `identity/mfa/method/<type>` и возвращает **UUID** (`method_id`); в Step-up — через `sys/mfa/method/<type>/<name>` с заданным именем.

**Single-phase / Two-phase login** — два способа передать MFA-код: сразу в заголовке `X-Vault-MFA` вместе с запросом на вход (single-phase) или вторым запросом к `sys/mfa/validate` после получения `mfa_requirement` (two-phase).

Типы MFA в Vault: **TOTP**, **Okta**, **Duo**, **PingID**.

## Основные концепции

### Матрица возможностей

| Возможность | Login MFA (Community) | Step-up MFA (Enterprise) |
| :--- | :--- | :--- |
| Endpoint метода | `POST /identity/mfa/method/<type>` | `POST /sys/mfa/method/<type>/<name>` |
| Идентификатор | UUID, возвращается при создании | Имя метода задаётся автором |
| Область | Вход (login) через auth method | Отдельные пути, проверка при каждом запросе |
| Требование | `identity/mfa/login-enforcement/<name>` | Поле `mfa_methods` в ACL/Sentinel-политике |
| Проверка | `POST /sys/mfa/validate` (two-phase) или `X-Vault-MFA` (single-phase) | `X-Vault-MFA: <method_name>:<passcode>` в запросе к пути |
| Self-enrollment | Только Enterprise (`enable_self_enrollment=true`) | Нет (регистрация через администратора) |

Важно: методы, поддерживаемые Step-up, используются и Login MFA, но через **разные endpoint-ы** — конфигурация одного метода не переносится на другой тип напрямую.

### Ограничения

* **Token auth method нельзя включить в Login MFA** — требование не применяется к `auth/token` входам.
* Login MFA по умолчанию **не защищает от перебора TOTP-кодов**: документация рекомендует per-client rate limits на login- и MFA-пути (`/sys/mfa/validate`), т.е. использовать [rate limit quotas](./quotas.md). Rate limiting MFA-путей включён по умолчанию с Vault 1.10.1.
* По умолчанию допускается 5 последовательных неудачных проверок TOTP (`max_validation_attempts`), затем требуется пауза/блокировка.
* Step-up MFA требует токен с identity-информацией — работают токены, полученные через auth methods, а не безликие `vault token create` без identity.
* `/sys/mfa` — restricted endpoint: вызывать только из root namespace; методы хранятся в root namespace и используются из любых namespace по имени.

### Two-phase flow (Login MFA)

1. Клиент шлёт обычный login-запрос.
2. Vault возвращает успешный auth-ответ, но **без рабочего токена** — вместо него `auth.mfa_requirement` с `mfa_request_id` и списком требуемых методов.
3. Клиент отправляет `POST /sys/mfa/validate` с `mfa_request_id` и `mfa_payload` (карта `method_id` → массив с кодом).
4. При успехе ответ идентичен успешному login: `auth.client_token` + accessor; при неудаче — 403.

### Single-phase flow

MFA-код передаётся сразу в заголовке `X-Vault-MFA`:

```
X-Vault-MFA: <method_id>:<passcode>          # или <method_name>:<passcode> (с 1.13)
```

Формат значения: `mfa_method_id[:passcode]`, часть после `:` необязательна для push-методов (Okta/Duo/PingID). Несколько методов — несколько заголовков. Для CLI: флаг `-mfa "id:code"` или переменная окружения `VAULT_MFA`. Непрагматичный интерактивный flow отключается флагом `-non-interactive` при `vault write sys/mfa/validate`.

## Практические сценарии

### Login MFA на TOTP: полный цикл

```bash
# 1. Создание TOTP-метода (возвращает method_id)
vault write identity/mfa/method/totp \
    generate=true \
    issuer=Vault \
    period=30 \
    key_size=30 \
    algorithm=SHA256 \
    digits=6
# → method_id: 1f36d4cf-52c9-475d-a5cd-49c573c54e55

# 2. Привязка к userpass: получаем accessor метода аутентификации
vault auth list -detailed
# → userpass/   auth_userpass_54b8e339

# 3. Enforcement: MFA обязателен для входа через userpass
vault write identity/mfa/login-enforcement/totp-required \
    mfa_method_ids="1f36d4cf-52c9-475d-a5cd-49c573c54e55" \
    auth_method_accessors="auth_userpass_54b8e339"

# 4. Регистрация секрета у пользователя: сам пользователь (под своим токеном)
#    или администратор для entity пользователя
vault write identity/mfa/method/totp/generate \
    method_id="1f36d4cf-52c9-475d-a5cd-49c573c54e55"
# → barcode, otpauth_url — отдать пользователю
```

Проверка two-phase входа через API:

```bash
# Фаза 1: логин → mfa_requirement вместо рабочего токена
curl --request POST --data '{"password":"..."}' \
    http://127.0.0.1:8200/v1/auth/userpass/login/alice | jq .auth.mfa_requirement

# Фаза 2: validate
curl --request POST \
    --data '{"mfa_request_id":"<id из фазы 1>",
             "mfa_payload":{"<method_id>":["695452"]}}' \
    http://127.0.0.1:8200/v1/sys/mfa/validate
# → auth.client_token + accessor (идентичен успешному login)
```

### Step-up MFA для чувствительного пути (Enterprise)

```bash
# 1. Метод с именем (не UUID)
vault write sys/mfa/method/totp/my_totp \
    issuer=Vault period=30 key_size=20 algorithm=SHA1 digits=6

# 2. Политика: MFA обязателен для чтения пути
vault policy write secrets-prod -<<EOF
path "secret/data/production/*" {
  capabilities = ["read", "list"]
  mfa_methods  = ["my_totp"]
}
EOF

# 3. Запрос с MFA-кодом
curl --header "X-Vault-Token: ..." --header "X-Vault-MFA: my_totp:695452" \
    http://127.0.0.1:8200/v1/secret/data/production/db
```

Все MFA-методы настраиваются в root namespace; в политике любого namespace они указываются по имени.

### Выбор способа

* Вход всех людей через корпоративный IdP с push/MFA на стороне IdP → MFA на стороне IdP; Vault Login MFA — второй контур для TOTP.
* Нужен MFA на конкретных путях (выгрузка, ротация, PKI-выпуск) → Step-up MFA (Enterprise).
* Демо/аудит на Community → Login MFA + `auth_method_accessors` для целевых методов.

## Устранение неполадок

| Симптом | Причина | Действия |
| :--- | :--- | :--- |
| Логин возвращает `mfa_requirement` вместо токена | Two-phase: не отправлен validate | `POST /sys/mfa/validate` с `mfa_request_id` или одиночный вход с `-mfa`/`X-Vault-MFA` |
| 403 на `/sys/mfa/validate` | Неверный/просроченный код, исчерпан `max_validation_attempts` | Сверьте время устройства (skew), дождитесь сброса счётчика |
| Enforcement не срабатывает | Не тот `auth_method_accessors`/`auth_method_types`, либо enforcement в другом namespace | `vault read identity/mfa/login-enforcement/<name>`, `vault auth list -detailed` |
| `X-Vault-MFA` игнорируется | Метод создан как Step-up (`sys/mfa/...`), а проверка — Login MFA (или наоборот) | Методы не взаимозаменяемы: создайте в нужном endpoint |
| Ошибка на `auth/token` входах | Token method не поддерживает Login MFA | Документированное ограничение; используйте другие auth methods |
| Перебор TOTP не блокируется | Per-client rate limit не настроен | Настройте rate limit quota на login- и `/sys/mfa/validate` пути |

## Лучшие практики

* Login MFA (Community) — для входа; Step-up MFA (Enterprise) — для чувствительных путей; при наличии Enterprise не смешивать два enforcement-механизма без нужды.
* Всегда накладывать rate limit quota на `auth/*/login/*` и `sys/mfa/validate` — документация прямо рекомендует это против перебора TOTP.
* `max_validation_attempts` держать в пределах 5 (по умолчанию); `skew=1` для терпимости к дрейфу часов.
* Push-методы (Okta/Duo/PingID) предпочтительнее TOTP там, где есть корпоративный IdP: перебор невозможен, управление устройствами централизовано.
* Enforcement привязывать к accessor конкретного auth method, а не к типу — иначе он зацепит и dev-монтирования.
* TOTP-secret хранится в identity entity: при увольнении отзывать токены и удалять entity/method, а не только членство в группах.

## Дополнительная информация

* [Rate limit и lease quotas](./quotas.md) — rate limiting на MFA- и login-путях
* [Аутентификация и авторизация](../authorization.md) — политики, Identity
* [OIDC SSO](./vault-auth-oidc-sso.md), [LDAP](./vault-auth-ldap.md) — методы входа, к которым применяется MFA
* [Control Groups](./control_groups.md) — многостороннее одобрение (Enterprise) как альтернатива второму фактору
* [Vault API Reference](./vault_api_reference.md) — curl-примеры
* Обзор generic TOTP-теории в базе: `Security/Concepts/mfa_totp.md`
