# Аутентификация через OpenID Connect (OIDC) в Angie

## Определения

**OpenID Connect (OIDC)** — протокол аутентификации поверх OAuth 2.0 (OpenID Connect Core 1.0), добавляющий к обмену токенами проверяемое «заявление о личности» пользователя: ID Token в формате JWT. Angie выступает в роли Relying Party (RP) — сервиса, который принимает авторизационные от IdP (Identity Provider), валидирует их и пропускает пользователя к приложению.

**IdP (Identity Provider)** — сервис, реализующий OIDC: выпускает ID/Access Token и публикует метаданные (Keycloak, Google, Yandex ID, Keycloak). Варианты развертывания см. в [Keycloak overview](../../Security/Tools/keycloak_overview.md).

**Discovery** — точка `/.well-known/openid-configuration`, из которой Angie/RP получает адреса `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint`. Автоматизация discovery описана в [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md).

**JWKS (JSON Web Key Set)** — документ с публичными ключами (`https://idp/.well-known/jwks.json`), которыми Angie проверяет подпись токенов. Каждый ключ идентифицируется `kid` (Key ID). Формат описан в RFC 7517.

**ID Token** — подписанный JWT (обычно `RS256`), содержащий claims `iss`, `sub`, `aud`, `exp`, `iat`, `email` и другие. Это доказательство аутентификации, которое валидирует Angie.

**Authorization Code Flow + PKCE** — основной сценарий для браузерных приложений: пользователь перенаправляется на IdP, после успешного входа IdP возвращает одноразовый `code`, который сервер обменивает на токены. PKCE (`code_challenge`) защищает обмен от перехвата.

**Access Token** — токен для обращения к ресурсам IdP/API (часто Opaque или JWT). Angie валидирует его, если API-шлюз построен на JWT.

## Базовые концепции

### Роли OIDC-потока в Angie

| Роль | Кто | Задача |
| :--- | :--- | :--- |
| **Relying Party (RP)** | Angie | Защищает ресурс, направляет на IdP, валидирует токены |
| **Identity Provider (IdP)** | Keycloak/Google | Аутентифицирует пользователя, выпускает токены |
| **Resource Server** | Backend-приложение | Принимает запрос с `Authorization: Bearer <token>` |

### Два подхода к интеграции

1. **Stateless-валидация (JWT как Access Token).** Angie сам проверяет подпись токена из заголовка и claims (`exp`, `aud`, `iss`) через директивы `auth_jwt_*`. Подходит для API-шлюзов и внутренних сервисов (machine-to-machine). Не требует обращений к IdP на каждый запрос.
2. **Полный браузерный flow (Authorization Code + PKCE).** Angie через `auth_request` + отдельный обработчик (njs или Lua) перенаправляет пользователя на IdP, обменивает `code` на токены, устанавливает сессию. Подходит для интерактивных веб-приложений.

Официальный гайд Angie по OIDC описывает подход №2 на базе Lua (`lua-resty-openidc`) в связке с `auth_request`; подход №1 реализуется модулем `ngx_http_auth_jwt_module` (пакет `angie-module-auth-jwt`), совместимым с модулем Nginx.

### Валидация токена

Angie проверяет (порядок некритичен, все проверки выполняются):

| Директива | Что проверяет |
| :--- | :--- |
| `auth_jwt` | Наличие токена и realm (текст в ответе `401`) |
| `auth_jwt_key_file` / `auth_jwt_key_request` | Подпись токена (по совпадению `kid` и `alg`) |
| `auth_jwt_require` | Произвольные claims (`exp`, `aud`, `iss`, `scope`) через переменные `$jwt_payload_*` |
| `auth_jwt_leeway` | Допуск на расхождение часов для `nbf`/`exp` |
| `auth_jwt_type` | Тип токена: `signed` (JWS), `encrypted` (JWE), `nested` |

Подробно про JWT и его структуру — в [JWT overview](../../Security/Concepts/jwt_overview.md).

## Практические сценарии

### Сценарий 1: Статический JWKS-файл (простейшая валидация)

Подходит, когда ключи IdP меняются редко (или вы поддерживаете ротацию вручную).

```nginx
load_module modules/ngx_http_auth_jwt_module.so;

http {
    server {
        location /api/ {
            auth_jwt "Private API";
            auth_jwt_key_file /etc/angie/keys/idp_public.jwk;
            # Проверка обязательных claims
            auth_jwt_require $jwt_payload_iss "https://idp.example.com";
            proxy_pass http://api_backend;
        }
    }
}
```

Получение публичного ключа IdP:

```bash
curl -s https://idp.example.com/realms/myrealm/protocol/openid-connect/certs \
  | jq . > /etc/angie/keys/idp_public.jwk
```

### Сценарий 2: Динамическая загрузка JWKS через подзапрос

Рекомендуемый способ для production: ключи берутся с `jwks_uri` IdP в момент запроса и кэшируются.

```nginx
load_module modules/ngx_http_auth_jwt_module.so;

http {
    proxy_cache_path /var/cache/angie/jwk levels=1 keys_zone=jwk:10m;

    server {
        location / {
            auth_jwt             "closed site";
            auth_jwt_key_request /_jwks_uri;   # ключи подгружаются подзапросом
            auth_jwt_key_cache   1h;           # кэш ключей в памяти

            proxy_pass http://backend;
        }

        location = /_jwks_uri {
            internal;
            proxy_method      GET;
            proxy_cache       jwk;
            proxy_cache_valid 200 12h;
            proxy_pass        https://idp.example.com/realms/myrealm/protocol/openid-connect/certs;
        }
    }
}
```

Здесь используется тот же механизм кэширования, что в [Proxy Cache в Nginx и Angie](../Nginx/Performance/Caching/proxy_caching.md). Без кэширования каждый запрос будет дёргать IdP — недопустимо при высоком RPS.

### Сценарий 3: Authorization Code + PKCE через auth_request

Полный браузерный сценарий: Angie перехватывает запрос к защищенному ресурсу, направляет неавторизованного пользователя на IdP, после `callback` сессия сохраняется в cookie.

```nginx
location /internal/ {
    auth_request /_oauth2;
    proxy_pass http://127.0.0.1/status/;
}

location /_oauth2 {
    internal;
    # Обработчик OIDC-потока (njs или Lua):
    # 1. нет сессии -> 302 на authorization_endpoint с code_challenge (PKCE)
    # 2. callback с code -> обмен token_endpoint, установка cookie сессии -> 204
    # 3. ошибка -> 401/403
    proxy_pass http://auth_handler;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
}

location /auth/callback {
    proxy_pass http://auth_handler/auth/callback;
}
location /auth/logout {
    proxy_pass http://auth_handler/auth/logout;
}
```

Роль обработчика может выполнять njs (см. [Скриптование на njs в Angie](./angie-njs.md)) или Lua (`lua-resty-openidc`). Вариант на Lua используется в официальном руководстве Angie по OIDC.

### Сценарий 4: Комбинация OIDC и mTLS/IP-фильтрации

Для внутренних административных панелей сочетайте OIDC с дополнительными проверками через `satisfy`:

```nginx
location /admin/ {
    satisfy all;
    allow 10.0.0.0/8;
    deny  all;

    auth_jwt "Admin";
    auth_jwt_key_request /_jwks_uri;
}
```

Общие принципы комбинирования методов доступа — в [Контроль доступа в Angie](./angie_access_control.md).

## Операции и команды

### Проверка discovery-документа IdP

```bash
curl -s https://idp.example.com/realms/myrealm/.well-known/openid-configuration | jq .
# Ожидаемые поля: authorization_endpoint, token_endpoint, jwks_uri, issuer
```

### Получение JWKS

```bash
curl -s https://idp.example.com/realms/myrealm/protocol/openid-connect/certs | jq .
# → { "keys": [ { "kty": "RSA", "kid": "…", "alg": "RS256", "n": "…", "e": "AQAB" } ] }
```

### Декодирование ID Token (отладка)

```bash
ID_TOKEN="eyJhbGciOi..."   # подставьте реальный токен
echo "$ID_TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
```

### Проверка, что Angie принимает токен

```bash
curl -i -H "Authorization: Bearer $ID_TOKEN" https://api.example.com/resource
# 200 — токен валиден; 401 — отсутствует/невалиден; 403 — claims не прошли
```

## Устранение неисправностей

### 401 Unauthorized при заведомо валидном токене

**Причина:** ключи для проверки устарели либо неверен `kid`/`alg` по сравнению с JWKS.
**Диагностика:**

```bash
# Сравнить kid в заголовке токена и в JWKS IdP
echo "$ID_TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null | python3 -m json.tool
curl -s https://idp.example.com/.../certs | jq -r '.keys[].kid'
```
**Решение:** обновить `auth_jwt_key_file` или включить динамическую ротацию через `auth_jwt_key_request` + кэш.

### 500 Internal Server Error при auth_jwt_key_request

**Причина:** не удалось загрузить или обработать ни один ключ (работа выполнена, но результат пуст).
**Диагностика:**
```bash
# Проверить достижимость и статус jwks_uri
curl -s -o /dev/null -w "%{http_code}\n" https://idp.example.com/.../certs
# Проверить кэш
grep -i "auth_jwt" /var/log/angie/error.log | tail -n 20
```
**Решение:** убедиться, что `jwks_uri` отдаёт корректный JSON и доступен из сети Angie; проверить `proxy_cache_valid`.

### Запрос с токеном уходит в default_server

**Причина:** запрос без корректного `Host` или токен используется на ресурсе вне защищённого `location`.
**Решение:** вернуть `444`/заглушку в `default_server`, см. [Конфигурация default_server в Nginx](../Nginx/Core/nginx_setup.md) и [Выбор виртуального сервера](../Nginx/Operations/nginx_troubleshooting.md).

### Периодические сбои после ротации ключей IdP

**Причина:** кэш ключей (`auth_jwt_key_cache`/proxy_cache) живёт дольше, чем период упреждения ротации IdP.
**Решение:** согласовать TTL кэша с политикой ротации IdP; при коротких окнах использовать меньший `auth_jwt_key_cache`.

## Лучшие практики

1. **Валидируйте все критические claims:** всегда требуйте `iss`, `aud` и `exp` через `auth_jwt_require`; не доверяйте `alg: none`.
2. **Используйте `RS256`/`ES256`** (асимметричные) вместо `HS256`, чтобы секрет не хранился на всех RP.
3. **Кэшируйте JWKS** и задавайте явный `auth_jwt_key_cache` — это снимает нагрузку с IdP.
4. **Проверяйте `kid` и ротацию:** держите TTL кэша ниже или равным периоду упреждения выпуска новых ключей.
5. **Для браузерных приложений применяйте PKCE**, никогда не прячьте `client_secret` в SPA-код.
6. **Храните `client_secret` только на сервере** (в env, Vault); в конфиг Angie передавайте через переменные (см. [Sops и секреты](../../Security/Tools/sops_overview.md)).
7. **Защищайте callback-endpoints** (`/auth/callback`, `/auth/logout`) от доступа извне лимитами `limit_req`.
8. **mTLS поверх OIDC** для критичных ресурсов — см. [mTLS в Angie](./angie_client_cert_auth.md).

## Дополнительная информация

- Пишите кастомную логику токенов/сессий на njs — [Скриптование njs в Angie](./angie-njs.md).
- Базовые директивы `auth_jwt_*`, `$jwt_payload_*` и `satisfy` — в [Контроль доступа в Angie](./angie_access_control.md).
- Общая теория OAuth 2.0 и OIDC — [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md).
- Структура JWT и алгоритмы подписи — [JWT overview](../../Security/Concepts/jwt_overview.md).
- Развертывание IdP — [Keycloak overview](../../Security/Tools/keycloak_overview.md) и [Keycloak LDAP federation](../../Security/Tools/keycloak_ldap_federation.md).
- Кэширование внутреннего подзапроса JWKS — [Proxy Cache в Nginx и Angie](../Nginx/Performance/Caching/proxy_caching.md).
- Официальная документация: [Auth JWT (внешние модули Angie)](https://en.angie.software/angie/docs/configuration/modules/external-modules/auth-jwt.md), [OIDC Authentication Setup](https://en.angie.software/angie/docs/configuration/oidc.md), [ngx_http_auth_jwt_module (nginx.org)](https://nginx.org/en/docs/http/ngx_http_auth_jwt_module.html).

## См. также

- [Контроль доступа в Angie](./angie_access_control.md)
- [Скриптование на njs в Angie](./angie-njs.md)
- [Настройка TLS в Angie](./angie_tls_setup.md) — обязательная база для защищённого OIDC
- [Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md)
- [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md)
- [JWT overview](../../Security/Concepts/jwt_overview.md)