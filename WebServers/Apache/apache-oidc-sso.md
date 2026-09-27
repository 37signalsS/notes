# Apache: SSO через OIDC (mod_auth_openidc)

---

## Определения

**OIDC (OpenID Connect)** — протокол аутентификации поверх OAuth 2.0: клиент получает `id_token` (JWT) с информацией о пользователе и может запрашивать `access_token` для API. Ключевой поток для веб-приложений — **Authorization Code** с PKCE.

**mod_auth_openidc** — модуль Apache (производственный стандарт), который: перенаправляет пользователя на IdP (Identity Provider), принимает код, обменивает на токены, создаёт сессионную cookie Apache, раскладывает claims в переменные окружения (`OIDC_CLAIM_*`) и контролирует доступ через `Require`.

**IdP (Identity Provider)** — сервер, выпускающий и проверяющий токены (Keycloak, Okta, Dex, Azure AD...). Discovery-эндпоинт: `/.well-known/openid-configuration`.

**Client ID / Client Secret** — учётные данные реестра приложения (confidential client) на IdP.

**Claims** — атрибуты пользователя в `id_token`/userinfo (`sub`, `email`, `name`, `groups`, `roles`).

**mod_auth_mellon** — альтернативный модуль той же задачи (SAML + OIDC), часто в FreeIPA/Keycloak-средах.

---

## Основные концепции

### Поток Authorization Code с mod_auth_openidc

```
1. Client ──► URL /private/ → Apache: куки нет → redirect на IdP
2. Client ──► IdP login/code → redirect_uri на Apache
3. Apache обменивает код на id_token/access_token (client_secret)
4. Apache валидирует подпись IdP (jwks), создаёт OIDCCookie, кладёт в клиента
5. Следующие запросы: cookie → Require OIDC claim → доступ
```

### Основные директивы

| Директива | Назначение |
|---|---|
| `OIDCProviderMetadataURL` | Discovery-URL IdP |
| `OIDCClientID` / `OIDCClientSecret` | Креды клиента |
| `OIDCRedirectURI` | Callback (часто `https://host/callback_oidc`) |
| `OIDCCryptoPassphrase` | Ключ шифрования/подписи OIDCCookie |
| `OIDCScope "openid profile email groups"` | Запрашиваемые claims |
| `Require claim groups:*` | Авторизация по claim |
| `OIDCClaimPrefix "OIDC_"` | Префикс переменных окружения: `OIDC_CLAIM_email` |
| `OIDCCookieSameSite` / `OIDCCookieHttpOnly` | Параметры cookie |
| `OIDCSessionCookieName` | Имя куки (уникальное для vhost) |

### Авторизация через Require

```apacheconf
Require valid-user                          # любой аутентифицированный
Require claim groups:devops
Require claim email:~^.*@company\.com$
```

Контейнеры `RequireAll/RequireAny` позволяют комбинировать OIDC с IP-ограничениями.

---

## Практические сценарии

### 1. Защита каталога через Keycloak

Установка: `apt install libapache2-mod-auth-openidc` / `rpm`, либо сборка (см. [Сборка из исходников](./apache-install-from-source.md)).

```apacheconf
LoadModule auth_openidc_module modules/mod_auth_openidc.so

OIDCProviderMetadataURL https://sso.example.com/realms/company/.well-known/openid-configuration
OIDCClientID apache-prod
OIDCClientSecret change-me
OIDCRedirectURI https://app.example.com/callback_oidc
OIDCCryptoPassphrase a-long-random-passphrase
OIDCScope "openid profile email groups"
OIDCCookieSameSite Lax
OIDCCookieHttpOnly On

<VirtualHost *:443>
    ServerName app.example.com
    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/app.crt
    SSLCertificateKeyFile /etc/pki/tls/private/app.key

    # Callback не заворачиваем в Require
    <Location /callback_oidc>
        Require all granted
    </Location>

    # Защищённая зона
    <Location /private>
        AuthType openid-connect
        Require valid-user
        # Или по группе:  Require claim groups:devops
    </Location>
</VirtualHost>
```

### 2. Передача identity приложению

```apacheconf
<Location /private>
    AuthType openid-connect
    Require valid-user
</Location>

# Проксировать claims бэкенду заголовками
RequestHeader set X-User-Email "%{OIDC_CLAIM_email}e"
RequestHeader set X-User-Groups "%{OIDC_CLAIM_groups}e"
```

### 3. Опциональная аутентификация (auth и без auth)

`OIDCAuthNHeader` / `OIDCUnAuthAction` позволяют пускать «гостей»:

```apacheconf
<Location />
    OIDCUnAuthAction passive            # при отсутствии сессии — тихий поток
    AuthType openid-connect
    Require valid-user
</Location>
```

### 4. Одно приложение с двумя зонами (user/guest)

```apacheconf
<Location /public>
    Require all granted
</Location>

<Location /restricted>
    AuthType openid-connect
    Require claim groups:admins
</Location>
```

### 5. Проверка flow из командной строки

```bash
# Полный проход с сохранением куки (IdP должен позволить)
curl -L -c cookies.txt -b cookies.txt -o /dev/null -w "%{http_code}\n" https://app.example.com/private
# → 200 (с активной сессией IdP) или 302 (redirect на IdP при первом заходе)

# Проверка discovery
curl -s https://sso.example.com/realms/company/.well-known/openid-configuration \
  | python3 -m json.tool | head
```

---

## Операции и команды

| Команда/проверка | Назначение |
|---|---|
| `apache2ctl -M \| grep openidc` | Проверка модуля (`auth_openidc_module`) |
| `apache2ctl configtest` | Синтаксис |
| `curl -sI https://app/private` | Ожидаемый `302` на IdP при отсутствии сессии |
| `curl -s -c c.txt https://app/private` | Захват OIDCCookie |
| `grep -i openidc /var/log/httpd/error_log` | Ошибки токенов/коннекта к IdP |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `redirect_uri` не совпадает | Другой host в `OIDCRedirectURI`, чем фактический | Точно указать `https://host/callback_oidc`; добавить в реестр IdP |
| `401 invalid_client / unauthorized_client` | Неверный `OIDCClientSecret`; клиент не confidential | Проверить креды на IdP |
| Цикл redirect (302→302) | Сессионная кука не сохраняется (SameSite/Secure) или `OIDCCryptoPassphrase` меняется между процессами | Стабильный `OIDCCryptoPassphrase`; корректные cookie-флаги |
| `clock skew`-ошибка валидации токена | Расхождение часов с IdP | NTP-синхронизация (chrony/ntp) |
| Приложение не видит claims | Устаревшие переменные OIDC_CLAIM | Передать через headers; проверить scope в запросе |
| Callback недоступен (404) | `Require`-правило перекрывает `/callback_oidc` | Открыть `/callback_oidc` (`Require all granted`) |
| Проблемы за reverse-proxy | X-Forwarded-* подменяется | mod_remoteip + `OIDCXForwardedHeaders` |

---

## Лучшие практики

1. Завершать TLS на Apache перед OIDC; за reverse-proxy настраивать `mod_remoteip` и `OIDCXForwardedHeaders`.
2. `OIDCCryptoPassphrase` — стабильный секрет (в Vault/Ansible), не менять без грамотного rollout.
3. Открывать callback (`/callback_oidc`) отдельно от защищаемых зон.
4. Авторизацию по группам строить на claims с группами из IdP, не плодить локальные списки.
5. Кука: `HttpOnly`, `SameSite=Lax`, `Secure` (за HTTPS), уникальное имя на vhost.
6. Секреты хранить вне конфига (plaintext из конфига удалять; `OIDCClientSecret` можно задавать из файла).

---

## Дополнительная информация

### См. также

*   [OAuth 2.0 / OIDC: концепции](../../Security/Concepts/oauth2_overview.md) — гранты, токены, client types.
*   [Keycloak](../../Security/Tools/keycloak_overview.md) — настройка IdP, realm, клиентов.
*   [OIDC в Angie/Nginx](../../WebServers/Angie/angie-oidc.md) — аналогичная интеграция для Nginx-стека.