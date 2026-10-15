# Apache: SSO через OIDC (mod_auth_openidc)

**Актуально для:** Apache httpd 2.4.x, mod_auth_openidc 2.4.x

---

## Определения

**OIDC (OpenID Connect)** — открытый протокол федеративной аутентификации, построенный в виде надстройки над фреймворком авторизации OAuth 2.0 ([RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)). OIDC вводит стандартизированный токен идентичности (**ID Token** в формате JWT — JSON Web Token) и эндпоинт информации о пользователе (**UserInfo**), позволяя клиентам верифицировать личность субъекта без доступа к его паролю.

**mod_auth_openidc** — модуль веб-сервера Apache HTTP Server (производственный стандарт для On-Premise инфраструктуры), выступающий в роли **Relying Party (RP)** и/или **OAuth 2.0 Resource Server**. Модуль перехватывает неавторизованные запросы, перенаправляет браузер на IdP, обрабатывает обратный вызов (Authorization Code), валидирует криптографические подписи токенов, формирует сессию, пробрасывает атрибуты пользователя в переменные окружения и осуществляет гранулярный контроль доступа директивами `Require`.

**Relying Party (RP)** — приложение или обратный прокси (в данном случае Apache), полагающийся на Identity Provider для проверки подлинности пользователя.

**OpenID Provider (OP) / Identity Provider (IdP)** — централизованный сервер управления идентификацией и доступом, выпускающий и удостоверяющий токены. В корпоративной On-Premise инфраструктуре типовыми IdP выступают [Keycloak](../../Security/Tools/keycloak_overview.md), FreeIPA (Ipsilon), Dex, Authelia или Authentik. Стандартизированный discovery-документ провайдера публикуется по пути `/.well-known/openid-configuration`.

**Claims (Утверждения)** — пары ключ-значение в полезной нагрузке (payload) токена или ответе UserInfo, описывающие атрибуты субъекта (`sub`, `preferred_username`, `email`, `groups`, `roles`).

**PKCE (Proof Key for Code Exchange, RFC 7636)** — расширение протокола Authorization Code, использующее динамически генерируемый криптографический верификатор (`code_verifier`) и его хэш (`code_challenge`) для предотвращения перехвата кода авторизации.

**JWKS (JSON Web Key Set, RFC 7517)** — набор открытых криптографических ключей, публикуемый IdP по эндпоинту `jwks_uri`, используемый `mod_auth_openidc` для верификации цифровых подписей токенов (алгоритмы RS256, ES256).

**mod_auth_mellon** — альтернативный модуль Apache для федеративной аутентификации, изначально ориентированный на протокол SAML 2.0. При развертывании чистого OIDC в современной инфраструктуре стандартом де-факто является `mod_auth_openidc`.

---

## Основные концепции и архитектура

### Роли компонентов и модель доверия

При интеграции Apache с корпоративным SSO веб-сервер обычно развертывается как **Security Gateway / Ingress Reverse Proxy** перед внутренними веб-приложениями, сервисами мониторинга или API.

```
┌─────────────┐        1. GET /private/          ┌──────────────────────────────────────┐
│             ├─────────────────────────────────►│ Apache HTTPD (mod_auth_openidc)      │
│             │◄─────────────────────────────────┤   - Проверка сессионной cookie       │
│             │  2. 302 Redirect to IdP          │   - Отсутствует: генерация PKCE/state│
│             │     (?client_id&challenge&state) └──────────────────────────────────────┘
│             │
│ User-Agent  │        3. AuthN / MFA Form
│  (Браузер)  ├─────────────────────────────────►┌──────────────────────────────────────┐
│             │◄─────────────────────────────────┤ On-Premise IdP (Keycloak / Dex)      │
│             │  4. 302 Redirect to Callback     │   - Аутентификация по LDAP/Kerberos  │
│             │     (/callback_oidc?code&state)  │   - Выпуск Authorization Code        │
│             │                                  └──────────────────▲───────────────────┘
│             │        5. GET /callback_oidc?code                   │
│             ├─────────────────────────────────►┌──────────────────┴───────────────────┐
│             │                                  │ Apache HTTPD (Relying Party)         │
│             │                                  │  6. Back-Channel POST /token (mTLS) ──┘
│             │                                  │  7. Валидация ID Token через JWKS    │
│             │                                  │  8. Запись сессии (Cookie / Redis)   │
│             │◄─────────────────────────────────┤  9. 302 Redirect to /private/        │
│             │  Set-Cookie: oidc_session=...    └──────────────────┬───────────────────┘
│             │                                                     │
│             │        10. GET /private/ (с Cookie)                 │ 11. Reverse Proxy
│             ├─────────────────────────────────────────────────────┤     (с чистыми заголовками)
│             │                                                     ▼
│             │                                  ┌──────────────────────────────────────┐
│             │◄─────────────────────────────────┤ Backend App (Internal Service)       │
│             │        12. 200 OK (Контент)      │   - Доверяет X-Remote-User           │
└─────────────┘                                  └──────────────────────────────────────┘
```

### Поток Authorization Code с PKCE: пошаговый цикл

1. **Запрос к защищенному ресурсу:** Пользователь отправляет `GET https://app.example.com/private/`.
2. **Проверка контекста:** `mod_auth_openidc` проверяет наличие сессионной cookie. Если валидная сессия не найдена, модуль сохраняет исходный целевой URL в зашифрованном состоянии `state`, генерирует `code_verifier` и `code_challenge` (S256), после чего формирует HTTP-ответ `302 Found` с перенаправлением на `authorization_endpoint` IdP.
3. **Аутентификация на IdP:** Пользователь переходит на страницу входа IdP, проходит проверку учетных данных (например, пароль + TOTP в Keycloak с бэкендом в OpenLDAP/FreeIPA).
4. **Возврат кода:** IdP перенаправляет браузер на предварительно зарегистрированный `OIDCRedirectURI` (например, `https://app.example.com/callback_oidc`) с параметрами `code` и `state`.
5. **Валидация состояния и обмен:** Apache перехватывает обращение к `OIDCRedirectURI` (данный URL виртуален и не требует наличия физического файла на диске), сверяет `state`, извлекает `code_verifier` и по прямому серверному каналу (Back-Channel HTTP POST) обращается к `token_endpoint` IdP, передавая `client_id`, `client_secret`, `code` и `code_verifier`.
6. **Криптографическая верификация:** IdP возвращает `id_token` (JWT) и `access_token`. Apache загружает открытые ключи с `jwks_uri` (с кэшированием), проверяет цифровую подпись токена, срок действия (`exp`, `nbf`), соответствие издателя (`iss`), получателя (`aud`) и nonce.
7. **Формирование сессии:** Apache создает локальную сессию, шифрует ее ключом `OIDCCryptoPassphrase` (или сохраняет в Redis) и выставляет клиенту защищенную cookie (`HttpOnly`, `SameSite`, `Secure`).
8. **Авторизация и проксирование:** Браузер переходит на исходный URL `/private/` с сессионной cookie. Apache расшифровывает сессию, применяет правила директив `Require claim`, устанавливает переменные окружения (`REMOTE_USER`, `OIDC_CLAIM_*`) и безопасно проксирует запрос к целевому сервису.

### Модели хранения сессий: Cookie vs Server-Side Cache (Redis)

| Критерий | Client-Side Cookie (по умолчанию) | Server-Side Cache (`OIDCCacheType redis`) |
|---|---|---|
| **Архитектура** | Полный контекст сессии и токены шифруются и хранятся в браузере клиента. | В браузере хранится только компактный случайный идентификатор сессии; данные лежат в Redis. |
| **Ограничение по размеру** | Жесткий лимит браузеров на размер заголовков и cookies (~4 КБ). Токены с десятками групп разбиваются на chunks (`mod_auth_openidc_session_chunks`). | Отсутствует. Поддерживаются токены любого размера без риска ошибки `400 Bad Request: Request Header Or Cookie Too Large`. |
| **Кластеризация Apache** | Работает без общего хранилища при едином `OIDCCryptoPassphrase` на всех узлах. | Идеально для горизонтального масштабирования: любой узел кластера имеет мгновенный доступ к сессии. |
| **Мгновенный отзыв (Revocation)** | Затруднен до истечения TTL или требует ведения локальных черных списков. | Мгновенный отзыв сессии удалением ключа в Redis (Single Logout). |

### Справочник ключевых директив mod_auth_openidc

| Директива | Контекст | Назначение |
|---|---|---|
| `OIDCProviderMetadataURL` | Server, VirtualHost | URL эндпоинта OpenID Discovery (`/.well-known/openid-configuration`). |
| `OIDCClientID` | Server, VirtualHost | Идентификатор доверенного клиента (Confidential Client), зарегистрированного на IdP. |
| `OIDCClientSecret` | Server, VirtualHost | Секретный ключ клиента для серверного обмена токенов. |
| `OIDCRedirectURI` | Server, VirtualHost | Абсолютный vanity-URL точки обратного вызова (должен совпадать с Valid Redirect URI в IdP). |
| `OIDCCryptoPassphrase` | Server, VirtualHost | Мастер-пароль для шифрования cookies сессий и параметров state (AES-GCM). Поддерживает ротацию. |
| `OIDCScope` | Server, VirtualHost | Перечень запрашиваемых областей доступа (например, `"openid profile email groups"`). |
| `OIDCRemoteUserClaim` | Server, VirtualHost | Имя claim для заполнения переменной `REMOTE_USER` (по умолчанию `sub`; обычно `preferred_username`). |
| `OIDCPassClaimsAs` | Directory, Location | Способ передачи claims: `environment` (по умолчанию), `headers`, `both`, `none`. |
| `OIDCClaimPrefix` | Server, VirtualHost | Префикс экспортируемых переменных окружения (по умолчанию `OIDC_CLAIM_`). |
| `OIDCSessionInactivityTimeout` | Server, VirtualHost | Таймаут неактивности сессии в секундах (по умолчанию 300). При простое сессия сбрасывается. |
| `OIDCSessionMaxDuration` | Server, VirtualHost | Максимальное абсолютное время жизни сессии в секундах (например, 28800 = 8 часов). |
| `OIDCCookieSameSite` | Server, VirtualHost | Атрибут безопасности cookie: `Lax` (рекомендуется), `Strict`, `None`. |
| `OIDCCookieHTTPOnly` | Server, VirtualHost | Запрет доступа к cookie из клиентского JavaScript (`On` / `Off`). |
| `OIDCCacheType` | Server, VirtualHost | Движок кэширования сессий: `client-cookie`, `redis`, `memcache`, `file`. |
| `OIDCCacheRedis` | Server, VirtualHost | Адрес сервера Redis в формате `host[:port]` или список серверов через запятую. |
| `OIDCCacheRedisPassword` | Server, VirtualHost | Пароль аутентификации в Redis (AUTH). |
| `OIDCLogoutPath` | Server, VirtualHost | Виртуальный URL, переход на который инициирует локальный и федеративный выход. |
| `OIDCDefaultLoggedOutURL` | Server, VirtualHost | URL перенаправления пользователя после завершения сессии выхода. |
| `OIDCCACertificatePath` | Server, VirtualHost | Путь к директории с доверенными CA-сертификатами для проверки TLS-сертификата IdP. |

---

## Практические сценарии и конфигурация

### Сценарий 1: Production-ready Reverse Proxy с аутентификацией через On-Premise Keycloak

Типовая задача системного администратора: защитить внутренний сервис (например, Grafana, Promhat, внутренний портал), завершить TLS на Apache, аутентифицировать пользователя через корпоративный Keycloak и пробросить идентификатор учетной записи и email в защищенных заголовках.

#### 1. Установка пакетов

На Debian / Ubuntu:
```bash
apt-get update && apt-get install -y apache2 libapache2-mod-auth-openidc
# → Чтение списков пакетов… Готово
# → Настройка libapache2-mod-auth-openidc (2.4.x) …

a2enmod auth_openidc proxy proxy_http ssl headers remoteip
# → Enabling module auth_openidc.
# → Enabling module proxy.
# → Enabling module proxy_http.
# → Enabling module ssl.
# → Enabling module headers.
# → Enabling module remoteip.
```

На RHEL / AlmaLinux / Rocky Linux:
```bash
dnf install -y epel-release
dnf install -y httpd mod_auth_openidc mod_ssl
# → Installed: mod_auth_openidc-2.4.x... Complete!
```

#### 2. Защищенный файл секретов

В соответствии с правилами харденинга секреты (`OIDCClientSecret`, `OIDCCryptoPassphrase`) не должны храниться в открытом виде в основном репозитории конфигурации. Создадим изолированный файл `/etc/apache2/conf-available/oidc-secrets.conf` (или `/etc/httpd/conf.d/oidc-secrets.conf` для RHEL):

```bash
install -m 0600 /dev/null /etc/apache2/conf-available/oidc-secrets.conf
```

Содержимое файла секретов:
```apacheconf
# /etc/apache2/conf-available/oidc-secrets.conf
# Доступ только для root / веб-сервера (chmod 0600)
OIDCClientSecret "k8s-sso-production-secret-XYZ-7788"
OIDCCryptoPassphrase "Passphrase-4-Encryption-Very-Long-Random-String-99"
```

#### 3. Конфигурация VirtualHost

```apacheconf
<VirtualHost *:443>
    ServerName app.corp.internal
    ServerAdmin admin@corp.internal

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/app.corp.internal.crt
    SSLCertificateKeyFile /etc/ssl/private/app.corp.internal.key
    SSLProtocol -all +TLSv1.2 +TLSv1.3
    SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384

    # 1. Подключение секретов
    Include /etc/apache2/conf-available/oidc-secrets.conf

    # 2. Настройки IdP (Keycloak On-Premise Realm)
    OIDCProviderMetadataURL https://sso.corp.internal/realms/production/.well-known/openid-configuration
    OIDCClientID apache-app-portal
    OIDCRedirectURI https://app.corp.internal/oauth2/callback
    OIDCScope "openid profile email groups"
    
    # 3. Сопоставление пользователей и сессии
    OIDCRemoteUserClaim preferred_username
    OIDCSessionInactivityTimeout 1800
    OIDCSessionMaxDuration 28800
    OIDCSessionCookieName oidc_session_app

    # 4. Флаги безопасности cookies
    OIDCCookieSameSite Lax
    OIDCCookieHTTPOnly On
    
    # 5. Обработка размера заголовков (для корпоративных JWT с множеством групп)
    LimitRequestFieldSize 16384

    # 6. Точка обратного вызова (не должна перекрываться Require valid-user)
    <Location /oauth2/callback>
        AuthType None
        Require all granted
    </Location>

    # 7. Санитизация входящих заголовков от клиента (защита от спуфинга!)
    RequestHeader unset X-Remote-User
    RequestHeader unset X-User-Email
    RequestHeader unset X-User-Groups

    # 8. Защищенный бэкенд
    <Location />
        AuthType openid-connect
        Require valid-user

        # Безопасная инъекция claims бэкенду
        RequestHeader set X-Remote-User "%{REMOTE_USER}s"
        RequestHeader set X-User-Email "%{OIDC_CLAIM_email}e"
        RequestHeader set X-User-Groups "%{OIDC_CLAIM_groups}e"

        ProxyPass http://127.0.0.1:8080/
        ProxyPassReverse http://127.0.0.1:8080/
    </Location>

    ErrorLog ${APACHE_LOG_DIR}/app_oidc_error.log
    CustomLog ${APACHE_LOG_DIR}/app_oidc_access.log combined
</VirtualHost>
```

---

### Сценарий 2: Централизованное хранилище сессий в Redis (Кластеризация без Sticky Sessions)

При горизонтальном масштабировании Apache за балансировщиком нагрузки (HAProxy, Keepalived) сессии по умолчанию хранятся в cookie. Однако если полезная нагрузка JWT превышает допустимый размер или требуется централизованный мгновенный отзыв сессий, применяется `redis`.

```apacheconf
# Глобальная конфигурация сессионного кэша через Redis
OIDCCacheType redis
OIDCCacheRedis "redis-node-01.corp.internal:6379,redis-node-02.corp.internal:6379"
OIDCCacheRedisPassword "RedisAuthSecretTokenStrong123"
OIDCCacheRedisDatabase 2

# Время хранения сессионных записей в секундах
OIDCSessionInactivityTimeout 3600
OIDCSessionMaxDuration 43200
```

> [!IMPORTANT]
> Для работы `OIDCCacheType redis` модуль `mod_auth_openidc` должен быть собран с поддержкой библиотеки `hiredis` (в стандартных пакетах Debian 12 и RHEL 9 поддержка включена по умолчанию).

---

### Сценарий 3: Гранулярный RBAC и исключение публичных URL

В корпоративных приложениях часто требуется:
- Открыть доступ без авторизации к метрикам (`/metrics`) и проверкам живости (`/healthz`).
- Ограничить доступ к административной панели (`/admin`) только участникам группы `corp-devops`.
- Ограничить корпоративные учетные записи по доменной маске email.

```apacheconf
# 1. Публичные эндпоинты (Healthchecks, Prometheus Scrape, Webhooks)
<LocationMatch "^/(healthz|metrics|api/public|webhook)">
    AuthType None
    Require all granted
</LocationMatch>

# 2. Основная рабочая зона — все сотрудники компании
<Location /portal>
    AuthType openid-connect
    <RequireAll>
        Require valid-user
        Require claim email:~^.*@corp\.internal$
    </RequireAll>
</Location>

# 3. Административная панель — только участники группы devops с intranet-подсети
<Location /portal/admin>
    AuthType openid-connect
    <RequireAll>
        # Ограничение по сетевому периметру
        Require ip 10.100.0.0/16 192.168.1.0/24
        # Ограничение по роли/группе из Keycloak
        Require claim groups:corp-devops
    </RequireAll>
</Location>
```

---

### Сценарий 4: Настройка RP-Initiated Single Sign-Out (Logout)

При выходе из системы недостаточно просто удалить локальную cookie Apache — необходимо также инвалидировать сессию в Keycloak, чтобы предотвратить повторный прозрачный вход без ввода пароля.

```apacheconf
# Путь, перехватываемый Apache для инициации выхода
OIDCLogoutPath /oauth2/logout

# URL перенаправления после завершения выхода на IdP
# Передает эндпоинт выхода Keycloak с обратным возвратом на главную страницу
OIDCDefaultLoggedOutURL "https://sso.corp.internal/realms/production/protocol/openid-connect/logout?post_logout_redirect_uri=https%3A%2F%2Fapp.corp.internal%2Flogged-out"

<Location /logged-out>
    AuthType None
    Require all granted
</Location>
```

При переходе пользователя по ссылке `https://app.corp.internal/oauth2/logout`:
1. Apache уничтожает локальную сессионную cookie (или удаляет ключ из Redis).
2. Выполняет 302 Redirect на эндпоинт выхода Keycloak.
3. Keycloak завершает SSO-сессию пользователя и возвращает браузер на страницу `/logged-out`.

---

### Сценарий 5: Работа Apache за внешним L4/L7 балансировщиком (Reverse Proxy / TLS Offloading)

Если перед Apache размещен балансировщик (например, HAProxy, Nginx или Envoy), выполняющий терминацию TLS, Apache получает незашифрованный HTTP-запрос на внутренний порт (например, 8080). Без специальной настройки `mod_auth_openidc` сгенерирует некорректный `redirect_uri` со схемой `http://` вместо `https://`, что приведет к ошибке `invalid_redirect_uri` на IdP.

```apacheconf
# Включение поддержки проксированных заголовков
LoadModule remoteip_module modules/mod_remoteip.so

# 1. Извлечение реального IP клиента
RemoteIPHeader X-Forwarded-For
RemoteIPInternalProxy 10.0.0.0/8 172.16.0.0/12

# 2. Доверие заголовкам X-Forwarded-Proto и X-Forwarded-Port от балансировщика
OIDCXForwardedHeaders On

# 3. Принудительное задание канонического внешнего имени и порта
ServerName https://app.corp.internal:443
UseCanonicalName On

# 4. Редирект URI всегда строго фиксирован во внешнем виде
OIDCRedirectURI https://app.corp.internal/oauth2/callback
```

---

## Операции и обслуживание

### Проверка синтаксиса и активных модулей

Проверка компиляции и синтаксиса перед перезагрузкой сервиса:
```bash
apache2ctl configtest
# → Syntax OK
```
*(Для систем RHEL: `httpd -t`)*

Проверка загрузки модуля `auth_openidc_module`:
```bash
apache2ctl -M | grep -i openidc
# → auth_openidc_module (shared)
```

### Диагностика сетевой доступности и токенов через CLI

Проверка доступности OpenID Discovery документа IdP с сервера Apache:
```bash
curl -sk https://sso.corp.internal/realms/production/.well-known/openid-configuration | python3 -m json.tool | head -n 12
# → {
# →     "issuer": "https://sso.corp.internal/realms/production",
# →     "authorization_endpoint": "https://sso.corp.internal/realms/production/protocol/openid-connect/auth",
# →     "token_endpoint": "https://sso.corp.internal/realms/production/protocol/openid-connect/token",
# →     "token_introspection_endpoint": "https://sso.corp.internal/realms/production/protocol/openid-connect/token/introspect",
# →     "userinfo_endpoint": "https://sso.corp.internal/realms/production/protocol/openid-connect/userinfo",
# →     "end_session_endpoint": "https://sso.corp.internal/realms/production/protocol/openid-connect/logout",
# →     "jwks_uri": "https://sso.corp.internal/realms/production/protocol/openid-connect/certs",
# →     "grant_types_supported": [
# →         "authorization_code",
# →         "implicit",
# →         "refresh_token",
# →         "client_credentials"
# →     ]
# → }
```

Проверка первичного редиректа на IdP при отсутствии сессионной cookie:
```bash
curl -s -o /dev/null -w "%{http_code} -> Location: %{redirect_url}\n" https://app.corp.internal/private
# → 302 -> Location: https://sso.corp.internal/realms/production/protocol/openid-connect/auth?response_type=code&client_id=apache-app-portal&redirect_uri=https%3A%2F%2Fapp.corp.internal%2Foauth2%2Fcallback&scope=openid+profile+email+groups&state=...
```

Инспекция ключей сессий в Redis (при `OIDCCacheType redis`):
```bash
redis-cli -n 2 -a "RedisAuthSecretTokenStrong123" --scan --pattern "mod_auth_openidc:session:*"
# → mod_auth_openidc:session:9d7e35b7-7f81-49b2-8419-f0270a41d4c2
# → mod_auth_openidc:session:1b3c99a4-2e55-46aa-9a71-42cb910fba83

redis-cli -n 2 -a "RedisAuthSecretTokenStrong123" ttl "mod_auth_openidc:session:9d7e35b7-7f81-49b2-8419-f0270a41d4c2"
# → (integer) 1785
```

### Настройка детального логирования для отладки

Для расследования ошибок аутентификации без перевода всего сервера в режим `debug`:
```apacheconf
# Установка уровня debug исключительно для модуля mod_auth_openidc
LogLevel warn auth_openidc:debug
```

Просмотр журнала модуля в реальном времени:
```bash
journalctl -u apache2 -f | grep -E "oidc|openidc"
# → [auth_openidc:debug] [pid 14205] src/mod_auth_openidc.c(3210): oidc_handle_redirect_authorization: valid state and code returned
# → [auth_openidc:debug] [pid 14205] src/proto.c(910): oidc_proto_resolve_userinfo: successfully resolved user claims: preferred_username=ivanov
```

### Бесшовная ротация криптографического ключа

Директива `OIDCCryptoPassphrase` принимает несколько аргументов. Первый ключ используется для шифрования новых cookies, а последующие — для расшифровки существующих сессий, что позволяет менять ключ без единовременного разлогина всех пользователей:

```apacheconf
# 1. Новая кодовая фраза идет первой, старая сохраняется вторым аргументом
OIDCCryptoPassphrase "New-Super-Strong-Passphrase-2026" "Old-Passphrase-2025"

# 2. Через 24 часа (после истечения OIDCSessionMaxDuration) старый ключ удаляется
# OIDCCryptoPassphrase "New-Super-Strong-Passphrase-2026"
```

---

## Типичные ошибки и диагностика

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
|---|---|---|---|
| **Циклический редирект (HTTP 302 Loop)** | 1. Cookie блокируется браузером из-за `SameSite=Strict` при кросс-доменном редиректе с IdP.<br>2. Apache работает за HTTP-прокси без согласования схемы `https`.<br>3. Рассинхронизация `OIDCCryptoPassphrase` между нодами кластера. | Проверить заголовки в DevTools: возвращается ли `Set-Cookie` в ответе `/callback` и передается ли она в следующем запросе к целевому URL. | 1. Задать `OIDCCookieSameSite Lax`.<br>2. Установить `OIDCXForwardedHeaders On` и настроить `mod_remoteip`.<br>3. Унифицировать секреты на всех нодах или перенести сессии в Redis. |
| **Error: state mismatch / nonce mismatch** | 1. Истек таймаут ожидания ввода учетных данных пользователем на IdP (`OIDCStateTimeout`).<br>2. Пользователь открыл несколько вкладок авторизации параллельно.<br>3. Рассинхронизация времени (NTP drift). | В логах: `[auth_openidc:error] ... oidc_authorization_response_matches_state: state mismatch`. | 1. Увеличить таймаут: `OIDCStateTimeout 600`.<br>2. Синхронизировать серверные часы через `chronyd` на Apache и IdP. |
| **HTTP 400 Bad Request: Request Header Or Cookie Too Large** | Токен пользователя содержит десятки корпоративных групп из LDAP/AD. Размер заголовков `Cookie` превышает дефолтный лимит Apache (`LimitRequestFieldSize 8190`). | Браузер возвращает ошибку 400 при запросах. В логах: `request failed: error reading the headers`. | 1. Добавить `LimitRequestFieldSize 16384` в VirtualHost.<br>2. Перевести сессии в Redis: `OIDCCacheType redis`.<br>3. В Keycloak настроить Client Scope Mapper, отфильтровав только необходимые группы. |
| **invalid_redirect_uri (ошибка на стороне IdP)** | URL в `OIDCRedirectURI` не совпадает побитово со списком **Valid Redirect URIs** в настройках клиента IdP (разница в порту, схеме http/https или регистре). | IdP выводит страницу с ошибкой: `Invalid parameter: redirect_uri`. | Скопировать значение директивы `OIDCRedirectURI` из конфига Apache и вставить в конфигурацию Client на стороне IdP. |
| **SSL certificate problem: unable to get local issuer certificate** | Сервер Apache не доверяет внутреннему корневому CA, выпустившему сертификат для IdP (On-Premise PKI). | В логах: `oidc_util_http_call: curl_easy_perform() failed on ... (60): SSL certificate problem`. | 1. Добавить корпоративный CA в доверенные системы (`update-ca-certificates`).<br>2. Либо явно указать `OIDCCACertificatePath /etc/ssl/certs` в Apache. |
| **HTTP 403 Forbidden при валидном токене** | 1. Ошибка в директиве `Require claim` (например, несоответствие регистра `corp-devops` vs `Corp-DevOps`).<br>2. Поле `groups` возвращается в виде массива JSON, а разделитель claims настроен некорректно. | Проверить фактическое тело ID-токена в `LogLevel auth_openidc:debug`. | 1. Использовать регулярное выражение: `Require claim groups:~(?i)^devops$`.<br>2. Задать разделитель claims при сериализации: `OIDCClaimDelimiter ","`. |
| **HTTP 404 Not Found на `/oauth2/callback`** | Внешний `ProxyPass` или `RewriteRule` перехватывает путь обратного вызова до того, как управление передается `mod_auth_openidc`. | Запрос к `/oauth2/callback` уходит на бэкенд и бэкенд отвечает 404. | Задать исключение проксирования перед общими правилами: `ProxyPass /oauth2/callback !`. |

---

## Лучшие практики (DevOps / SRE / Security)

### 1. Безопасность криптографии и сессионных Cookies

- **Флаг Secure:** Всегда запускать OIDC исключительно поверх HTTPS. Модуль автоматически устанавливает атрибут `Secure`, если соединение зашифровано.
- **Атрибут SameSite:** Значение `Lax` является оптимальным компромиссом между безопасностью (защита от CSRF) и корректной работой редиректа при входе (переход с внешнего домена IdP методом GET с сохранением сессионной cookie).
- **Изоляция сессионных cookies:** При размещении нескольких VirtualHost на одном Apache-инстансе обязательно задавайте уникальные `OIDCSessionCookieName` для каждого виртуального хоста, чтобы избежать взаимной перезаписи сессий:
  ```apacheconf
  OIDCSessionCookieName oidc_sess_monitoring
  ```

### 2. Защита бэкендов от спуфинга идентичности (Header Sanitization)

Если бэкенд-приложение полагается на HTTP-заголовки от обратного прокси (`X-Remote-User`, `X-User-Email`), существует риск, что злоумышленник отправит эти заголовки напрямую с клиента.

**Обязательное правило:** Всегда выполняйте сброс (unset) доверенных заголовков перед их повторной установкой через `mod_headers`:
```apacheconf
RequestHeader unset X-Remote-User
RequestHeader unset X-User-Email
RequestHeader unset X-User-Groups

RequestHeader set X-Remote-User "%{REMOTE_USER}s"
RequestHeader set X-User-Email "%{OIDC_CLAIM_email}e"
```

### 3. Хранение секретов вне основного дерева конфигурации

- Никогда не коммитьте `OIDCClientSecret` и `OIDCCryptoPassphrase` в публичные или общие репозитории Git.
- Выносите секреты в отдельный файл (например, `/etc/apache2/oidc-secrets.conf`), права на который ограничены `0600 root:root` (или `0640 root:www-data`).
- В шаблонах CI/CD (Ansible, Puppet) генерируйте файл секретов через Ansible Vault.

### 4. Согласование жизненного цикла сессий (Session Lifecycle Sync)

Таймауты сессии на Apache должны быть согласованы с таймаутами SSO-сессии на IdP (Keycloak SSO Session Idle / Max):
- Если `OIDCSessionInactivityTimeout` в Apache больше, чем `SSO Session Idle` в Keycloak, пользователь попытается обновить токен и получит ошибку инвалидации на IdP.
- Рекомендуемая схема:
  - `OIDCSessionInactivityTimeout` на Apache = 30 минут (`1800` сек).
  - `OIDCSessionMaxDuration` на Apache = 8 часов (`28800` сек).
  - Keycloak `SSO Session Idle` = 30 минут, `SSO Session Max` = 8–10 часов.

### 5. Сетевая надежность и кэширование ключей JWKS

`mod_auth_openidc` кэширует открытые ключи IdP локально в памяти. Для предотвращения сбоев при кратковременной недоступности IdP и оптимизации времени ответа:
- Контролируйте интервал обновления открытых ключей:
  ```apacheconf
  OIDCJWKSRefreshInterval 3600
  ```
- Обеспечьте низкую задержку (RTT < 5 мс) между серверами Apache и кластером Keycloak внутри корпоративной сети.

---

## Дополнительная информация

### См. также

* [Обзор Apache HTTP Server](./apache_overview.md) — базовая архитектура, модели MPM, конфигурация виртуальных хостов.
* [Аутентификация и авторизация в Apache](./apache_authentication.md) — локальная аутентификация `htpasswd`, интеграция с LDAP (`mod_authnz_ldap`) и базовые механизмы `Require`.
* [Харденинг Apache](./apache_hardening.md) — защищенная конфигурация TLS, заголовки безопасности, минимизация раскрытия информации.
* [Продвинутый Reverse Proxy в Apache](./apache-reverse-proxy-advanced.md) — детальная настройка балансировки, перезапись cookies и передача заголовков.
* [Сборка Apache из исходников](./apache-install-from-source.md) — компиляция сторонних модулей через `apxs`.
* [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md) — фундаментальные стандарты RFC, типы грантов, токены и модель безопасности.
* [Keycloak: Архитектура и администрирование](../../Security/Tools/keycloak_overview.md) — настройка On-Premise Identity Provider, Realms, Clients и Client Scopes.
* [Keycloak: Федерация пользователей через LDAP](../../Security/Tools/keycloak_ldap_federation.md) — интеграция IdP с корпоративным каталогом пользователей.
* [OIDC в Angie](../../WebServers/Angie/angie-oidc.md) — сопоставление подходов к реализации OIDC в экосистеме Nginx/Angie.