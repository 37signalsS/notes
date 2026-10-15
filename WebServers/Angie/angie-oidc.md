# Аутентификация через OpenID Connect (OIDC) в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x; ngx_http_auth_jwt_module, ngx_http_auth_request_module, ngx_http_js_module

## Определения

**OpenID Connect (OIDC)** — протокол идентификации и аутентификации прикладного уровня, надстроенный над спецификацией авторизации OAuth 2.0 (RFC 6749, OpenID Connect Core 1.0). Добавляет к потоку делегирования прав стандартизированный токен идентификации (**ID Token**) в криптографическом формате JSON Web Token (JWT) и стандартизированный эндпоинт метаданных Discovery.

**Relying Party (RP)** — приложение или промежуточный шлюз (в данном контексте — веб-сервер Angie), который полагается на сторонний Identity Provider для подтверждения подлинности пользователя и валидации входящих запросов.

**Identity Provider (IdP)** — централизованный сервис управления идентификацией и доступом (IAM), выпускающий криптографически подписанные токены аутентификации (ID Token) и авторизации (Access Token). В онпремис-инфраструктуре в качестве IdP выступают Keycloak, Authentik, Dex, FreeIPA или собственный сервис на базе OpenLDAP/OIDC. Развертывание и архитектура Keycloak описаны в [Keycloak](../../Security/Tools/keycloak_overview.md).

**OpenID Provider Metadata (Discovery)** — стандартизированный эндпоинт `/.well-known/openid-configuration`, возвращающий конфигурационный JSON-документ с сетевыми адресами ключевых служб IdP: `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint`, `end_session_endpoint`, а также списком поддерживаемых алгоритмов подписи (`id_token_signing_alg_values_supported`). Теория протокола представлена в [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md).

**JSON Web Key Set (JWKS)** — документ в формате JSON (RFC 7517), публикуемый IdP по адресу `jwks_uri` (например, `https://idp.example.internal/realms/production/protocol/openid-connect/certs`). Содержит массив открытых криптографических ключей, с помощью которых Angie проверяет валидность цифровой подписи токенов. Ключи индексируются по идентификатору `kid` (Key ID) и содержат параметры алгоритма (`kty`, `alg`, `use`, `n`, `e` для RSA или `crv`, `x`, `y` для EC).

**ID Token** — криптографически подписанный токен в формате JWS (обычно алгоритмы `RS256` или `ES256`), подтверждающий факт успешной аутентификации субъекта (`sub`), содержащий временные границы действия (`iat`, `exp`, `nbf`), издателя (`iss`), целевую аудиторию (`aud`) и профильные атрибуты (claims: `email`, `preferred_username`, `groups`, `roles`). Подробный разбор полей приведен в [JWT](../../Security/Concepts/jwt_overview.md).

**Authorization Code Flow с расширением PKCE** — защищенный протокол взаимодействия для клиентских приложений и веб-интерфейсов (RFC 7636). Исключает перехват авторизационного кода путем генерации разового криптографического верификатора (`code_verifier`) и проверочного хэша (`code_challenge`), исключая необходимость передачи долгоживущих секретов в браузер.

**ngx_http_auth_jwt_module** — динамический модуль Angie (поставляется в пакетах `angie-module-auth-jwt` и `angie-pro-module-auth-jwt`), выполняющий локальную валидацию входящих JSON Web Tokens на фазе контроля доступа (`NGX_HTTP_ACCESS_PHASE`) по статическим файлам ключей или динамически подгружаемым JWKS-наборам без обращения к IdP на каждый HTTP-запрос.

**ngx_http_auth_request_module** — базовый модуль ядра Angie, реализующий делегирование авторизации входящего запроса во внутренний HTTP-подзапрос (subrequest) к локальному скрипту njs или внешнему демону-посреднику (например, `oauth2-proxy`).

## Базовые концепции и архитектура

### Роли и участники взаимодействия

В архитектуре корпоративного периметра Angie реализует две фундаментальные модели интеграции с OIDC-провайдерами:

| Роль в схеме | Компонент системы | Назначение и функции |
| :--- | :--- | :--- |
| **User-Agent / Client** | Браузер, curl, мобильный клиент | Запрашивает защищенный ресурс, передает заголовок `Authorization: Bearer <JWT>` либо сессионные Cookie |
| **Relying Party (RP) / API Gateway** | Angie | Терминирует трафик, валидирует токены, проверяет claims, маршрутизирует запрос или перенаправляет на IdP |
| **Identity Provider (IdP)** | Keycloak / Authentik | Аутентифицирует пользователей, обрабатывает вход по паролю/2FA/Kerberos, выпускает и подписывает токены |
| **Auth Handler / Sidecar** | `oauth2-proxy` / скрипт njs | Обрабатывает браузерный redirect flow, взаимодействует с `token_endpoint`, устанавливает шифрованные cookie |
| **Resource Server (Upstream)** | Бэкенд-приложение / API | Получает проверенный запрос с заголовками идентификации (`X-User`, `X-Roles`), извлеченными Angie |

### Два архитектурных подхода к интеграции

```
[Подход 1: Stateless API Gateway (ngx_http_auth_jwt_module)]
Клиент ──► [ Angie (auth_jwt) ] ──(валидация подписи по локальному JWKS)──► [ Бэкенд API ]
               │
          (периодический subrequest за JWKS)
               ▼
        [ Identity Provider ]

[Подход 2: Браузерный Web SSO (auth_request + oauth2-proxy)]
Браузер ──► [ Angie ] ──(auth_request)──► [ oauth2-proxy ] ──(проверка сессии)
               │                                │
               │ (302 Redirect при 401)         ▼
               └───────────────────────► [ Identity Provider (Keycloak) ]
```

1. **Stateless-валидация JWT (L7 API Gateway):**
   Применяется для взаимодействия Machine-to-Machine (M2M), мобильных клиентов и микросервисных API.
   * Клиент передает токен в заголовке `Authorization: Bearer <token>`.
   * Модуль `ngx_http_auth_jwt_module` декодирует заголовок и полезную нагрузку токена, проверяет совпадение идентификатора ключа `kid` и алгоритма `alg`, сверяет криптографическую подпись с публичным ключом из кэша JWKS, проверяет срок жизни (`exp`) и обязательные утверждения (`auth_jwt_require`).
   * Сетевой трафик к IdP на каждый клиентский запрос отсутствует; задержка обработки минимальна (доли миллисекунды).
2. **Stateful Web SSO с поддержкой браузерного входа (Authorization Code Flow + PKCE):**
   Применяется для веб-приложений, панелей мониторинга и внутренних интерфейсов (Grafana, Kibana, внутренние порталы).
   * Неаутентифицированный пользователь обращается к веб-серверу без сессии.
   * Angie через директиву `auth_request` опрашивает обработчик (`oauth2-proxy` или njs).
   * Обработчик возвращает статус `401 Unauthorized`. Angie перехватывает его директивой `error_page 401` и возвращает браузеру редирект `302 Found` на `authorization_endpoint` IdP.
   * После ввода учетных данных IdP перенаправляет пользователя на URI обратного вызова (`/oauth2/callback`) с одноразовым кодом авторизации.
   * Обработчик обменивает код на токены через бэк-канал (`token_endpoint`), проверяет ID Token, шифрует его и сохраняет в безопасной `HttpOnly` Cookie.
   * Последующие запросы валидируются мгновенно по расшифрованной сессионной Cookie.

### Внутренний механизм модуля ngx_http_auth_jwt_module

Модуль исполняется на фазе `NGX_HTTP_ACCESS_PHASE` (до передачи запроса генераторам контента или в upstream):

```
1. Извлечение токена: заголовок Authorization: Bearer либо переменная token=$arg_token
2. Декодирование структуры JOSE: Header, Payload, Signature
3. Проверка типа токена: директива auth_jwt_type (по умолчанию signed)
4. Поиск ключа: по атрибуту kid в Header внутри auth_jwt_key_file или кэша auth_jwt_key_request
5. Проверка алгоритма: соответствие заявленному (RS256, ES256 и др.); запрет 'none'
6. Криптографическая верификация подписи через библиотеку OpenSSL
7. Проверка временных меток:
   - exp (срок истечения) > ($time_iso8601 - auth_jwt_leeway)
   - nbf (not before) <= ($time_iso8601 + auth_jwt_leeway)
8. Проверка утверждений auth_jwt_require:
   - логика И (AND) между отдельными директивами
   - логика ИЛИ (OR) между аргументами одной директивы
9. Экспорт переменных в контекст запроса ($jwt_header_*, $jwt_payload_*)
```

Директивы модуля:

| Директива | Контекст | Назначение |
| :--- | :--- | :--- |
| `auth_jwt <realm> [token=$var]` / `off` | `http`, `server`, `location` | Включает валидацию JWT с указанием realm для заголовка `WWW-Authenticate` |
| `auth_jwt_key_file <path>` | `http`, `server`, `location` | Задает путь к локальному файлу с ключами в формате JSON Web Key Set |
| `auth_jwt_key_request <uri>` | `http`, `server`, `location` | Указывает внутренний URI подзапроса для динамической загрузки JWKS с IdP |
| `auth_jwt_key_cache <time>` | `http`, `server`, `location` | Задает время кэширования публичных ключей JWKS в оперативной памяти процесса |
| `auth_jwt_leeway <time>` | `http`, `server`, `location` | Задает допустимую погрешность рассинхронизации системных часов (по умолчанию `0s`) |
| `auth_jwt_require <$var> <val...>` | `http`, `server`, `location` | Требует совпадения значения переменной хотя бы с одним из указанных значений |
| `auth_jwt_type signed\|encrypted\|nested` | `http`, `server`, `location` | Определяет ожидаемый криптографический тип токена (по умолчанию `signed` — JWS) |

Доступные переменные ядра Angie:
* `$jwt_header_<name>` — значение поля заголовка токена (например, `$jwt_header_alg`, `$jwt_header_kid`, `$jwt_header_typ`).
* `$jwt_payload_<name>` (синоним `$jwt_claim_<name>`) — значение поля полезной нагрузки (например, `$jwt_payload_iss`, `$jwt_payload_sub`, `$jwt_payload_aud`, `$jwt_payload_email`, `$jwt_payload_preferred_username`).

## Практические сценарии

### Требования и окружение (Prerequisites)

Перед настройкой интеграции убедитесь, что хост удовлетворяет инфраструктурным требованиям:
* **Операционная система:** Linux (Debian 11/12, Ubuntu 22.04/24.04, AlmaLinux 8/9, Rocky Linux 8/9, РЕД ОС, Astra Linux 1.7/1.8).
* **Сетевая связанность:** Открытые сетевые маршруты от сервера Angie до эндпоинтов IdP по портам TCP 443/8443; отсутствие блокировок внутренних DNS-имен.
* **Синхронизация времени:** На всех серверах Angie и узлах IdP обязательно запущен сервис точного времени `chronyd` или `systemd-timesyncd`. Рассинхронизация свыше 1–2 секунд приводит к ложным отказам валидации `exp`/`nbf`.
* **Установленные пакеты:** Установлен Angie версии 1.12.x и динамический модуль JWT:

Для систем Debian/Ubuntu:
```bash
apt-get update && apt-get install -y angie angie-module-auth-jwt jq curl
```

Для систем RHEL/AlmaLinux/Rocky:
```bash
dnf install -y angie angie-module-auth-jwt jq curl
```

Подключение динамического модуля выполняется в главном конфигурационном файле `/etc/angie/angie.conf` на верхнем уровне (вне блоков `http`/`events`):

```nginx
# /etc/angie/angie.conf
load_module modules/ngx_http_auth_jwt_module.so;

user angie;
worker_processes auto;
pid /run/angie.pid;
error_log /var/log/angie/error.log warn;

events {
    worker_connections 4096;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;
    include /etc/angie/http.d/*.conf;
}
```

### Сценарий 1: Высокопроизводительный API Gateway с динамическим кэшированием JWKS

Сценарий обеспечивает защиту REST/gRPC API. Angie динамически получает открытые ключи с `jwks_uri` Keycloak, кэширует их на диске через `proxy_cache` и в оперативной памяти через `auth_jwt_key_cache`, проверяет валидность токена, сверяет утверждения `iss` и `aud`, после чего передает идентификатор пользователя в upstream через HTTP-заголовки.

```nginx
# /etc/angie/http.d/api_gateway_oidc.conf

# Зона кэширования ответов JWKS от IdP (1 МБ keys_zone вмещает ~8000 ключей)
proxy_cache_path /var/cache/angie/jwks levels=1:2 keys_zone=jwks_cache:2m 
                 max_size=20m inactive=24h use_temp_path=off;

upstream backend_api {
    zone backend_api 64k;
    server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

upstream idp_backend {
    zone idp_backend 64k;
    server idp.example.internal:443;
    keepalive 16;
}

server {
    listen 443 ssl reuseport;
    server_name api.example.internal;

    ssl_certificate     /etc/angie/ssl/api.example.internal.crt;
    ssl_certificate_key /etc/angie/ssl/api.example.internal.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Допуск 30 секунд на дрейф часов между генератором токена и шлюзом
    auth_jwt_leeway 30s;

    location /api/v1/ {
        # Включаем валидацию JWT Bearer токена
        auth_jwt "Protected Corporate API";

        # Загрузка JWKS через внутренний подзапрос с кэшированием в RAM на 2 часа
        auth_jwt_key_request /_jwks_fetch;
        auth_jwt_key_cache   2h;

        # Проверка обязательных утверждений (Claims)
        auth_jwt_require $jwt_payload_iss "https://idp.example.internal/realms/production";
        auth_jwt_require $jwt_payload_aud "corporate-api-client" "gateway-service";

        # Передача верифицированных данных аутентификации в бэкенд
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Auth-User-Id $jwt_payload_sub;
        proxy_set_header X-Auth-Username $jwt_payload_preferred_username;
        proxy_set_header X-Auth-Email $jwt_payload_email;

        proxy_pass http://backend_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    # Внутренний эндпоинт для выгрузки ключей JWKS от IdP
    location = /_jwks_fetch {
        internal;

        proxy_pass https://idp_backend/realms/production/protocol/openid-connect/certs;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host idp.example.internal;

        # Кэширование ключей на диске для отказоустойчивости при недоступности IdP
        proxy_cache jwks_cache;
        proxy_cache_valid 200 12h;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;

        # Ограничение размера буфера и таймауты подзапроса
        proxy_buffer_size 16k;
        proxy_buffers 4 32k;
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;

        # Проверка TLS сертификата Identity Provider
        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_ssl_server_name on;
        proxy_ssl_name idp.example.internal;
    }
}
```

### Сценарий 2: Полноценный Web SSO (Authorization Code + PKCE) через auth_request и oauth2-proxy

Классический SRE-паттерн для защиты интерфейсов без встроенной поддержки OIDC (например, Grafana, внутренний Prometheus UI, Alertmanager, админ-панели). Все взаимодействие по протоколу OIDC делегируется локальному легковесному демону `oauth2-proxy`, работающему через UNIX-сокет или локальный порт, а Angie осуществляет контроль доступа по механизму `auth_request`.

```
[Пользователь] 
      │ 1. GET /dashboard/
      ▼
   [Angie] ──────── 2. auth_request /oauth2/auth ────────► [oauth2-proxy]
      │                                                           │
      │ ◄────────── 3. 401 Unauthorized (нет cookie) ─────────────┘
      │
      │ 4. 302 Found (Redirect to /oauth2/start?rd=/dashboard/)
      ▼
   [Браузер] ────── 5. Редирект на Keycloak (Authorization Endpoint) ──► [Keycloak]
      │                                                                      │
      │ ◄────── 6. Ввод логина/пароля, 302 Callback с code=XYZ ──────────────┘
      ▼
   [Angie] ──────── 7. Передача /oauth2/callback на 127.0.0.1:4180 ─────► [oauth2-proxy]
                                                                             │ 8. Обмен code на токены
                                                                             ▼
                                                                        [Keycloak]
      │ ◄────── 9. Установка шифрованной cookie _oauth2_proxy ───────────────┘
      ▼
   [Браузер] ────── 10. Повторный GET /dashboard/ с Cookie ─────────────► [Angie]
      │                                                                      │
      │                                                    auth_request 202  │
      ▼                                                                      ▼
  [Upstream] ◄───── 11. proxy_pass с заголовком X-Auth-Request-User ─────────┘
```

#### Шаг 1: Конфигурация сервиса oauth2-proxy в Linux

Создайте конфигурационный файл `/etc/oauth2-proxy/oauth2-proxy.cfg`:

```ini
# /etc/oauth2-proxy/oauth2-proxy.cfg
http_address = "127.0.0.1:4180"
reverse_proxy = true

# Провайдер OIDC (Keycloak)
provider = "keycloak-oidc"
provider_display_name = "Corporate Keycloak"
oidc_issuer_url = "https://idp.example.internal/realms/production"

# Учетные данные клиента OIDC (Client Type: Confidential)
client_id = "angie-web-sso"
client_secret = "CHANGE_ME_TO_REAL_CLIENT_SECRET"

# Секрет шифрования cookie (32 байта base64: openssl rand -base64 32)
cookie_secret = "k6GgSgV3F8lqLwS9sK8YnN1wX7vQ4zR2pM5tE8uI1oA="
cookie_name = "_angie_oidc_session"
cookie_secure = true
cookie_httponly = true
cookie_samesite = "lax"
cookie_expire = "8h"
cookie_refresh = "1h"

# Настройки пересылки заголовков
pass_user_headers = true
pass_access_token = false
set_xauthrequest = true
set_authorization_header = true

# Разрешенные домены перенаправления и email
email_domains = ["*"]
whitelist_domains = [".example.internal"]
redirect_url = "https://dashboard.example.internal/oauth2/callback"

# Корневые сертификаты доверия
ssl_insecure_skip_verify = false
```

Создайте systemd-юнит `/etc/systemd/system/oauth2-proxy.service`:

```ini
[Unit]
Description=OAuth2 Proxy Daemon for Angie SSO
After=network.target

[Service]
Type=simple
User=angie
Group=angie
ExecStart=/usr/local/bin/oauth2-proxy --config=/etc/oauth2-proxy/oauth2-proxy.cfg
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Активация и запуск сервиса:
```bash
systemctl daemon-reload
systemctl enable --now oauth2-proxy
systemctl status oauth2-proxy --no-pager
# → Active: active (running) since ...
```

#### Шаг 2: Конфигурация виртуального хоста в Angie

```nginx
# /etc/angie/http.d/dashboard_sso.conf

upstream oauth2_proxy_backend {
    zone oauth2_proxy 64k;
    server 127.0.0.1:4180;
    keepalive 16;
}

upstream dashboard_backend {
    zone dashboard_backend 64k;
    server 127.0.0.1:3000;
    keepalive 16;
}

server {
    listen 443 ssl;
    server_name dashboard.example.internal;

    ssl_certificate     /etc/angie/ssl/dashboard.crt;
    ssl_certificate_key /etc/angie/ssl/dashboard.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # Увеличенный буфер заголовков для передачи крупных OIDC-cookie
    large_client_header_buffers 4 16k;

    # Точка входа для авторизации через auth_request
    location /oauth2/ {
        proxy_pass       http://oauth2_proxy_backend;
        proxy_set_header Host                    $host;
        proxy_set_header X-Real-IP               $remote_addr;
        proxy_set_header X-Scheme                $scheme;
        proxy_set_header X-Auth-Request-Redirect $request_uri;
        proxy_connect_timeout 3s;
        proxy_read_timeout    10s;
    }

    # Внутренний подзапрос проверки сессии
    location = /oauth2/auth {
        internal;
        proxy_pass       http://oauth2_proxy_backend;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        proxy_set_header Host           $host;
        proxy_set_header X-Real-IP      $remote_addr;
        proxy_set_header X-Scheme       $scheme;
    }

    # Защищенный рабочий контент
    location / {
        auth_request /oauth2/auth;

        # При отсутствии сессии перенаправляем пользователя на авторизацию в IdP
        error_page 401 = /oauth2/start?rd=$escaped_request_uri;

        # Перехват заголовков ответа oauth2-proxy и передача в бэкенд
        auth_request_set $user   $upstream_http_x_auth_request_user;
        auth_request_set $email  $upstream_http_x_auth_request_email;
        auth_request_set $groups $upstream_http_x_auth_request_groups;

        proxy_set_header X-WebAuth-User   $user;
        proxy_set_header X-WebAuth-Email  $email;
        proxy_set_header X-WebAuth-Groups $groups;

        proxy_pass http://dashboard_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Сценарий 3: Легковесная валидация и маршрутизация токенов на njs

В окружениях, где установка сторонних бинарных демонов нежелательна, Angie позволяет использовать встроенный JavaScript-интерпретатор njs (пакет `angie-module-njs`). njs производит разбор структуры JWT, декодирует Base64URL без внешних библиотек и проверяет специфические бизнес-атрибуты перед пропуском трафика. Подробные принципы работы njs описаны в [Скриптование на njs в Angie](./angie-njs.md).

```nginx
# /etc/angie/http.d/njs_jwt_filter.conf
js_import oidc from /etc/angie/njs/oidc_filter.js;

# Динамическое извлечение роли из JWT через njs
js_set $jwt_user_role oidc.extractRole;

server {
    listen 443 ssl;
    server_name portal.example.internal;

    ssl_certificate     /etc/angie/ssl/portal.crt;
    ssl_certificate_key /etc/angie/ssl/portal.key;

    location /admin/ {
        # Криптографическую валидацию подписи выполняет нативный C-модуль
        auth_jwt "Admin Area";
        auth_jwt_key_file /etc/angie/keys/idp_public.jwk;

        # Проверка бизнес-роли через njs
        if ($jwt_user_role != "superadmin") {
            return 403 "Forbidden: Insufficient privileges";
        }

        proxy_pass http://127.0.0.1:9000;
    }
}
```

Файл скрипта `/etc/angie/njs/oidc_filter.js`:

```javascript
// /etc/angie/njs/oidc_filter.js
function extractRole(r) {
    var authHeader = r.headersIn['Authorization'];
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
        return "";
    }
    try {
        var token = authHeader.substring(7);
        var parts = token.split('.');
        if (parts.length !== 3) {
            return "";
        }
        // Декодирование Payload (вторая секция JWT)
        var payloadJson = Buffer.from(parts[1], 'base64url').toString('utf8');
        var claims = JSON.parse(payloadJson);

        // Извлечение ролей из структуры Keycloak realm_access.roles
        if (claims.realm_access && Array.isArray(claims.realm_access.roles)) {
            if (claims.realm_access.roles.includes('superadmin')) {
                return "superadmin";
            }
            return claims.realm_access.roles[0] || "user";
        }
        return claims.role || "unknown";
    } catch (e) {
        r.error("njs JWT parsing error: " + e.message);
        return "";
    }
}

export default { extractRole };
```

### Сценарий 4: Гранулярный контроль доступа (RBAC) и проверка утверждений Keycloak

Сценарий демонстрирует разграничение доступа к различным эндпоинтам одного API-сервиса на основе утверждений токена: область видимости (`scope`), издатель (`iss`) и принадлежность клиента.

```nginx
# /etc/angie/http.d/rbac_api.conf
server {
    listen 443 ssl;
    server_name secure-api.example.internal;

    ssl_certificate     /etc/angie/ssl/api.crt;
    ssl_certificate_key /etc/angie/ssl/api.key;

    # Базовая валидация для всего виртуального хоста
    auth_jwt "Corporate Gateway";
    auth_jwt_key_request /_jwks_cache_uri;
    auth_jwt_leeway 30s;
    auth_jwt_require $jwt_payload_iss "https://idp.example.internal/realms/production";

    # Публичные методы API — достаточно любого валидного токена с аудиторией
    location /api/v1/public/ {
        auth_jwt_require $jwt_payload_aud "mobile-client" "web-spa";
        proxy_pass http://127.0.0.1:8080;
    }

    # Служебные методы — требуют специфического scope 'metrics:read'
    location /api/v1/metrics/ {
        auth_jwt_require $jwt_payload_scope "metrics:read" "system:admin";
        proxy_pass http://127.0.0.1:8081;
    }

    # Эндпоинты управления — требуют строгой учетной записи оператора
    location /api/v1/manage/ {
        auth_jwt_require $jwt_payload_azp "devops-bastion-client";
        proxy_pass http://127.0.0.1:8082;
    }

    location = /_jwks_cache_uri {
        internal;
        proxy_pass https://idp.example.internal/realms/production/protocol/openid-connect/certs;
        proxy_cache jwks_cache;
        proxy_cache_valid 200 6h;
    }
}
```

### Сценарий 5: Эшелонированная защита (OIDC + IP Allowlist + mTLS + Rate Limiting)

Для защиты критических сервисов (например, админ-панелей балансировщиков, API управления базами данных) аутентификация по токену комбинируется с сетевыми ограничениями и взаимной аутентификацией по сертификатам клиента (mTLS). Детали настройки сертификатов приведены в [Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md), а сетевые директивы — в [Контроль доступа в Angie](./angie_access_control.md).

```nginx
# /etc/angie/http.d/defense_in_depth.conf

# Лимитирование запросов к эндпоинтам аутентификации (защита от перегрузки IdP)
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=10r/s;

server {
    listen 443 ssl;
    server_name admin.example.internal;

    ssl_certificate        /etc/angie/ssl/admin.crt;
    ssl_certificate_key    /etc/angie/ssl/admin.key;

    # mTLS валидация сертификатов клиентов
    ssl_client_certificate /etc/angie/ssl/corporate_ca.crt;
    ssl_verify_client      optional; # optional позволяет настроить логику через satisfy

    location /admin/ {
        limit_req zone=auth_limit burst=20 nodelay;

        # satisfy all: клиент ОБЯЗАН удовлетворять сетевому фильтру IP,
        # иметь валидный TLS-сертификат И предоставить валидный OIDC токен
        satisfy all;

        # 1. Сетевой фильтр (L3/L4)
        allow 192.168.10.0/24;
        allow 10.50.0.0/16;
        deny  all;

        # 2. Проверка mTLS (L7)
        if ($ssl_client_verify != "SUCCESS") {
            return 403 "Forbidden: Valid corporate TLS certificate required";
        }

        # 3. OIDC JWT валидация (L7)
        auth_jwt "Critical Admin Console";
        auth_jwt_key_request /_jwks_uri;
        auth_jwt_require $jwt_payload_iss "https://idp.example.internal/realms/production";
        auth_jwt_require $jwt_payload_client_role "admin";

        proxy_pass http://127.0.0.1:9090;
    }

    location = /_jwks_uri {
        internal;
        proxy_pass https://idp.example.internal/realms/production/protocol/openid-connect/certs;
        proxy_cache jwks_cache;
        proxy_cache_valid 200 12h;
    }
}
```

## Операции и команды

### 1. Проверка discovery-документа IdP

Проверка сетевой доступности и структуры метаданных Identity Provider:

```bash
curl -s -k https://idp.example.internal/realms/production/.well-known/openid-configuration | jq '{issuer, authorization_endpoint, token_endpoint, jwks_uri, id_token_signing_alg_values_supported}'
```
Ожидаемый результат:
```json
# → {
# →   "issuer": "https://idp.example.internal/realms/production",
# →   "authorization_endpoint": "https://idp.example.internal/realms/production/protocol/openid-connect/auth",
# →   "token_endpoint": "https://idp.example.internal/realms/production/protocol/openid-connect/token",
# →   "jwks_uri": "https://idp.example.internal/realms/production/protocol/openid-connect/certs",
# →   "id_token_signing_alg_values_supported": [
# →     "RS256",
# →     "ES256"
# →   ]
# → }
```

### 2. Получение и аудит JWKS-ключей

Выгрузка набора публичных ключей IdP и проверка идентификатора ключа (`kid`):

```bash
curl -s https://idp.example.internal/realms/production/protocol/openid-connect/certs | jq '.keys[] | {kid, kty, alg, use}'
```
Ожидаемый результат:
```json
# → {
# →   "kid": "k-2026-prod-01",
# →   "kty": "RSA",
# →   "alg": "RS256",
# →   "use": "sig"
# → }
```

Сохранение ключей в локальный статический файл (для Сценария со статическим JWKS):

```bash
curl -s https://idp.example.internal/realms/production/protocol/openid-connect/certs | jq . > /etc/angie/keys/idp_public.jwk
test -s /etc/angie/keys/idp_public.jwk && echo "JWKS file successfully written"
# → JWKS file successfully written
```

### 3. Получение тестового токена через Resource Owner Password Credentials / Client Credentials

Получение сервисного Access/ID токена через curl для проведения тестирования:

```bash
TOKEN_RESPONSE=$(curl -s -X POST https://idp.example.internal/realms/production/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=corporate-api-client" \
  -d "client_secret=CHANGE_ME_TO_REAL_SECRET")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r .access_token)
echo "Token length: ${#ACCESS_TOKEN}"
# → Token length: 852
```

### 4. Локальный декодинг и инспекция JWT (без отправки в сторонние сервисы)

Инспекция заголовка (Header) и полезной нагрузки (Payload) средствами Linux CLI:

```bash
# Декодирование JOSE Header
echo "$ACCESS_TOKEN" | cut -d. -f1 | tr '_-' '/+' | base64 -d 2>/dev/null | jq .
```
Ожидаемый результат:
```json
# → {
# →   "alg": "RS256",
# →   "typ": "JWT",
# →   "kid": "k-2026-prod-01"
# → }
```

```bash
# Декодирование Claims Payload
echo "$ACCESS_TOKEN" | cut -d. -f2 | tr '_-' '/+' | base64 -d 2>/dev/null | jq '{iss, sub, aud, exp, preferred_username}'
```
Ожидаемый результат:
```json
# → {
# →   "iss": "https://idp.example.internal/realms/production",
# →   "sub": "b83f3e82-12a4-4f9e-9d21-419bcf882194",
# →   "aud": "corporate-api-client",
# →   "exp": 1776182400,
# →   "preferred_username": "service-worker"
# → }
```

### 5. Тестирование валидации токена через шлюз Angie

**Запрос без токена (ожидается 401 Unauthorized с указанием Realm):**
```bash
curl -i -s https://api.example.internal/api/v1/resource | head -n 5
```
Ожидаемый результат:
```http
# → HTTP/1.1 401 Unauthorized
# → Server: Angie/1.12.0
# → Date: Wed, 14 Oct 2026 16:45:00 GMT
# → Content-Type: text/html
# → WWW-Authenticate: Bearer realm="Protected Corporate API"
```

**Запрос с валидным Bearer токеном:**
```bash
curl -i -s -H "Authorization: Bearer $ACCESS_TOKEN" https://api.example.internal/api/v1/resource | head -n 4
```
Ожидаемый результат:
```http
# → HTTP/1.1 200 OK
# → Server: Angie/1.12.0
# → Content-Type: application/json
# → X-Auth-User-Id: b83f3e82-12a4-4f9e-9d21-419bcf882194
```

**Запрос с модифицированным/невалидным токеном (проверка защиты от подделки подписи):**
```bash
TAMPERED_TOKEN="${ACCESS_TOKEN%?}X"
curl -i -s -H "Authorization: Bearer $TAMPERED_TOKEN" https://api.example.internal/api/v1/resource | head -n 5
```
Ожидаемый результат:
```http
# → HTTP/1.1 401 Unauthorized
# → Server: Angie/1.12.0
# → WWW-Authenticate: Bearer realm="Protected Corporate API", error="invalid_token"
```

### 6. Валидация конфигурации и горячая перезагрузка Angie

Перед применением любых изменений в OIDC-конфигурациях обязательна синтаксическая проверка:

```bash
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

systemctl reload angie
systemctl status angie --no-pager | grep "Active:"
# → Active: active (running) since ...
```

## Устранение неисправностей

### Сводная таблица типичных инцидентов

| Симптом / Ошибка | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **401 Unauthorized** (при валидном токене) | Рассинхронизация часов хоста; устаревший JWKS кэш; расхождение `kid` | `grep "auth_jwt" /var/log/angie/error.log` | Увеличить `auth_jwt_leeway 30s;`; проверить работу `chrony`; очистить кэш JWKS |
| **403 Forbidden** | Токен валиден, но не совпало условие директивы `auth_jwt_require` | Проверить значения claims через декодер Base64; логи уровня `info` | Сверить `$jwt_payload_*` с фактическим содержимым токена; скорректировать конфиг |
| **500 Internal Server Error** на `auth_jwt_key_request` | Ошибка DNS, таймаут подзапроса к IdP, сбой TLS-хэндшейка при обращении к JWKS | `curl -vk https://idp.../certs`; проверить `error.log` на наличие `SSL alert` | Добавить `proxy_ssl_trusted_certificate`; проверить DNS `resolver`; настроить `proxy_cache_use_stale` |
| **502 Bad Gateway** на `auth_request` | Процесс `oauth2-proxy` остановлен либо заблокирован порт 4180 | `systemctl status oauth2-proxy`; `ss -tlpn \| grep 4180` | Запустить службу `oauth2-proxy`; проверить права доступа к UNIX-сокету |
| **Циклический редирект (302 Loop)** | Сессионная Cookie не сохраняется в браузере (нет флага `Secure`, расхождение доменов) | Браузерная панель Network; `curl -v -c cookies.txt` | Убедиться в работе поверх HTTPS; настроить `cookie_domain`; передавать `X-Forwarded-Proto $scheme` |
| **400 Bad Request / Header Too Large** | Размер ID Token или заголовка `Cookie` превышает лимиты буфера Nginx/Angie | `grep "client sent too large header" /var/log/angie/error.log` | Увеличить `large_client_header_buffers 4 16k;` и `proxy_buffer_size 16k;` |

### Разбор конкретных неполадок

#### 1. Ошибка 401 Unauthorized: token is expired / not yet valid

**Симптом:** Пользователь или сервис получает `401 Unauthorized`, хотя токен только что сгенерирован. В `error.log` фиксируется сообщение:
`auth_jwt: token is expired` либо `auth_jwt: token is not yet valid`.

**Диагностика:**
```bash
# Проверка текущего системного времени и рассинхронизации
chronyc tracking
# → Reference ID    : C0A80101 (ntp.example.internal)
# → Stratum         : 2
# → System time     : 0.000012450 seconds slow of NTP time

# Сравнение времени exp токена с текущим UNIX timestamp
EXP_TIME=$(echo "$ACCESS_TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq -r .exp)
CURRENT_TIME=$(date +%s)
echo "Current: $CURRENT_TIME, Exp: $EXP_TIME, Diff: $((EXP_TIME - CURRENT_TIME))s"
# → Current: 1776182390, Exp: 1776182400, Diff: 10s
```

**Решение:**
1. Если разница составляет единицы секунд, настройте допустимый допуск в блоке `server` или `location`:
   ```nginx
   auth_jwt_leeway 30s;
   ```
2. Синхронизируйте время на шлюзе и нодах IdP: `systemctl restart chronyd`.

#### 2. Ошибка 500 при загрузке JWKS через auth_jwt_key_request

**Симптом:** При первом запросе или после истечения `auth_jwt_key_cache` шлюз возвращает `500 Internal Server Error`. В `error.log`:
`auth_jwt: failed to load keys from subrequest "/_jwks_fetch"`.

**Диагностика:**
```bash
# 1. Проверка доступности jwks_uri с самого хоста Angie
curl -s -o /dev/null -w "HTTP: %{http_code}, Time: %{time_total}s\n" https://idp.example.internal/realms/production/protocol/openid-connect/certs
# → HTTP: 200, Time: 0.045s

# 2. Поиск детализированных ошибок в логе Angie
grep -E "auth_jwt|_jwks" /var/log/angie/error.log | tail -n 10
```

**Решение:**
1. Если в подзапросе используется доменное имя, а upstream не объявлен статически, добавьте системный резолвер в `http` контекст:
   ```nginx
   resolver 127.0.0.53 192.168.1.1 valid=30s ipv6=off;
   resolver_timeout 3s;
   ```
2. Убедитесь, что для подзапроса настроена проверка SSL-сертификата IdP или доверенный CA:
   ```nginx
   proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
   proxy_ssl_verify on;
   ```
3. Проверьте размер буфера: ключи JWKS часто превышают стандартный размер буфера `4k`. Установите `proxy_buffer_size 16k;`.

#### 3. Периодические сбои 401 после плановой ротации ключей в Keycloak

**Симптом:** IdP выпустил новые ключи подписи; токены новых сессий содержат новый `kid`, но Angie отвечает `401 Unauthorized` в течение 1–2 часов.

**Причина:** Значение директивы `auth_jwt_key_cache` или `proxy_cache_valid` задает время удержания старого JWKS-документа, не содержащего новый ключ.

**Решение:**
1. Согласуйте время жизни кэша ключей с регламентом ротации IdP. В Keycloak новые ключи переводятся в статус активных с упреждением:
   ```nginx
   auth_jwt_key_cache 1h;
   ```
2. Экстренная инвалидация кэша JWKS на диске:
   ```bash
   rm -rf /var/cache/angie/jwks/*
   systemctl reload angie
   ```

## Лучшие практики

### 1. Криптографическая устойчивость и валидация

* **Запрет слабых алгоритмов:** Никогда не используйте симметричный алгоритм `HS256` для межсервисной аутентификации публичных клиентов, так как утечка общего секрета позволяет подделывать токены. Используйте только асимметричные пары: `RS256` (минимум RSA 2048 бит) либо `ES256` (кривая NIST P-256).
* **Контроль claims:** Всегда валидируйте издателя (`iss`), целевую аудиторию (`aud`) и срок действия токена (`exp`). Для сервисных аккаунтов дополнительно ограничивайте субъекта (`sub`) или клиентский идентификатор (`azp`).
* **Защита от алгоритмической подмены (`alg: none`):** Модуль `ngx_http_auth_jwt_module` по умолчанию отклоняет токены без подписи (`alg: none`). Не отключайте строгий парсинг типов.

### 2. Отказоустойчивость и SRE-параметры шлюза

* **Автономность при сбоях IdP:** Используйте директиву `proxy_cache_use_stale` в подзапросе JWKS:
  ```nginx
  proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
  ```
  Это позволит Angie продолжать валидировать запросы по уже закэшированным открытым ключам даже в том случае, если Identity Provider временно недоступен или перезагружается.
* **Keepalive соединения к IdP:** Для ускорения обработки внутренних подзапросов настройте пул постоянных TCP-соединений (`keepalive 16;`) в блоке `upstream` к IdP.
* **Лимитирование подзапросов:** Используйте `proxy_cache_lock on;`, чтобы при истечении срока кэша только один рабочий процесс Angie отправлял запрос к IdP за обновлением JWKS, предотвращая эффект «лавины запросов» (Thundering Herd).

### 3. Безопасность сессионных Cookie и заголовков

* **Защитные флаги Cookie:** При использовании браузерного SSO через `oauth2-proxy` cookie обязана иметь атрибуты:
  * `HttpOnly` — предотвращает чтение токена клиентскими XSS-скриптами.
  * `Secure` — передача cookie разрешена строго по HTTPS.
  * `SameSite=Lax` (или `Strict`) — защита от атак межсайтовой подделки запросов (CSRF).
* **Маскирование чувствительных данных в логах:** JWT-токены содержат персональные данные и цифровые подписи. Запрещается выводить полный заголовок `Authorization` в стандартный `access.log`.

Рекомендуемый безопасный формат логирования в `/etc/angie/angie.conf`:
```nginx
log_format oidc_combined '$remote_addr - $jwt_payload_sub [$time_local] '
                         '"$request" $status $body_bytes_sent '
                         '"$http_referer" "$http_user_agent" '
                         'jwt_iss="$jwt_payload_iss" jwt_kid="$jwt_header_kid" '
                         'rt=$request_time uct="$upstream_connect_time" uht="$upstream_header_time"';
```

### 4. Регламент аварийного отката (Rollback / Emergency Bypass)

В случае масштабного инфраструктурного сбоя IdP (потеря базы данных IAM, компрометация корневых сертификатов) администратор должен иметь возможность изолировать авторизацию без деградации сетевой инфраструктуры.

**Временное отключение проверки JWT для изоляции инцидента:**
```nginx
# Замена auth_jwt на временный доступ доверенным IP-сетям
location /api/v1/ {
    # auth_jwt off;
    allow 192.168.1.0/24;
    deny all;
    proxy_pass http://backend_api;
}
```
После правки конфигурации выполните `angie -t && systemctl reload angie`.

## Дополнительная информация

* Архитектурные принципы и сопутствующие модули безопасности:
  * [Контроль доступа в Angie](./angie_access_control.md) — базовые модули контроля доступа, директива `satisfy`, IP-фильтрация.
  * [Скриптование на njs в Angie](./angie-njs.md) — расширенная обработка заголовков, парсинг полезной нагрузки токенов.
  * [Настройка TLS в Angie](./angie_tls_setup.md) — криптографическая безопасность транспортного уровня HTTPS.
  * [Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md) — второй эшелон аутентификации по сертификатам.
  * [Логирование в Angie](./angie_logging.md) — настройка безопасных форматов журналов доступа и трассировки.
  * [Обратный прокси в Angie](./angie_reverse_proxy.md) — тюнинг буферов и заголовков проксирования.
  * [Серверное кэширование (Proxy Cache) в Nginx и Angie](../Nginx/Performance/Caching/proxy_caching.md) — организация дискового кэша для статических и динамических подзапросов.
* Концепции и сопутствующие инструменты безопасности:
  * [Keycloak](../../Security/Tools/keycloak_overview.md) — развертывание, конфигурирование Realms и OIDC-клиентов.
  * [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md) — спецификации потоков Authorization Code, PKCE, Client Credentials.
  * [JWT](../../Security/Concepts/jwt_overview.md) — структура токенов, JOSE-стандарты, алгоритмы подписи.
  * [SOPS и управление секретами](../../Security/Tools/sops_overview.md) — безопасное хранение клиентских секретов `client_secret` и `cookie_secret`.
* Официальная документация:
  * [Документация модуля ngx_http_auth_jwt_module (Angie)](https://en.angie.software/angie/docs/configuration/modules/external-modules/auth-jwt.md)
  * [Спецификация OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
  * [OAuth 2.0 Threat Model and Security Considerations (RFC 6819)](https://datatracker.ietf.org/doc/html/rfc6819)

## См. также

- [Контроль доступа в Angie](./angie_access_control.md)
- [Скриптование на njs в Angie](./angie-njs.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
- [Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md)
- [Логирование в Angie](./angie_logging.md)
- [Обратный прокси в Angie](./angie_reverse_proxy.md)
- [Keycloak](../../Security/Tools/keycloak_overview.md)
- [OAuth 2.0 и OpenID Connect](../../Security/Concepts/oauth2_overview.md)
- [JWT](../../Security/Concepts/jwt_overview.md)