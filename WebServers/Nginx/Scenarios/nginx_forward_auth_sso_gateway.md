# Nginx: шлюз централизованной аутентификации (Forward Auth / SSO через auth_request и OAuth2-Proxy)

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), OAuth2-Proxy 7.7.x / 7.8.x, Keycloak 24+ / 26+, Authelia 4.38+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по настройке пограничного шлюза сквозной корпоративной аутентификации (SSO / Forward Auth) на базе модуля `ngx_http_auth_request_module`:
- [Core/Location/internal_routing.md](../Core/Location/internal_routing.md) — описывает базовую концепцию внутренних подзапросов (`internal`, `subrequest`), но содержит лишь краткий 30-строчный абстрактный пример.
- [Scenarios/nginx_as_reverse_proxy_for_grafana.md](./nginx_as_reverse_proxy_for_grafana.md) — рассматривает внутренний механизм Grafana Auth Proxy (доверие заголовкам), не охватывая внешний цикл OIDC-аутентификации.
- [Security/nginx_security_guide.md](../Security/nginx_security_guide.md) — перечисляет директиву `auth_request` в сводной таблице мер харденинга без практической реализации инфраструктурного контура.

---

## 1. Определения

- **Forward Auth (Внешняя аутентификация на шлюзе)** — архитектурный паттерн безопасности, при котором обратный прокси-сервер (Nginx) перед передачей входящего запроса целевому приложению делегирует проверку прав внешнему сервису авторизации через синхронный внутренний HTTP-подзапрос (Subrequest).
- **Модуль `ngx_http_auth_request_module`** — встроенный модуль Nginx (включается директивой сборки `--with-http_auth_request_module`), реализующий проверку прав клиента на основе кода ответа вспомогательного URI (`auth_request /uri;`). Если подзапрос возвращает статус `2xx`, доступ разрешается; если `401` или `403` — запрос блокируется или перенаправляется на форму аутентификации.
- **OAuth2-Proxy** — специализированный обратный прокси-демон с открытым исходным кодом, выступающий связующим звеном между веб-сервером и корпоративными провайдерами идентификации (Identity Provider: Keycloak, Okta, GitLab, Google, Microsoft Entra ID). Реализует протоколы OAuth2 и OpenID Connect (OIDC), хранит пользовательские сессии в зашифрованных Cookie или Redis и проверяет валидность токенов.
- **Директива `auth_request_set`** — директива Nginx, позволяющая сохранить значение заголовка ответа из сервиса аутентификации (переменные `$upstream_http_*`) в локальную переменную Nginx для ее последующей передачи бэкенду через `proxy_set_header`.
- **Identity Provider (IdP)** — централизованный сервис управления учетными записями пользователей, группами и доступом (Keycloak, Authentik, FreeIPA), выпускающий криптографически подписанные токены (ID Token, Access Token).
- **Subrequest (Подзапрос)** — внутренний HTTP-запрос, генерируемый ядром Nginx в фазе доступа (`NGX_HTTP_ACCESS_PHASE`). Подзапрос не уходит в сеть клиенту, а обрабатывается внутри Nginx и направляется в указанный `location` без передачи тела клиентского POST/PUT-запроса (`proxy_pass_request_body off;`).
- **Single Sign-On (SSO / Сквозной вход)** — технология, позволяющая пользователю единожды пройти аутентификацию в централизованном IdP и получить доступ ко всем внутренним инфраструктурным сервисам (Prometheus, Kibana, RabbitMQ UI, внутренние дашборды) без повторного ввода логина и пароля.

---

## 2. Архитектура и принципы работы

### 2.1 Жизненный цикл запроса при Forward Auth

```text
Клиент              Nginx (Gateway)               OAuth2-Proxy                 Keycloak (IdP)
  │                        │                            │                            │
  │─── 1. GET /dashboard ─►│                            │                            │
  │                        │── 2. auth_request /auth ──►│                            │
  │                        │   (Проверка Cookie)        │                            │
  │                        │                            │                            │
  │                        │◄── 3. 401 Unauthorized ────│                            │
  │                        │                            │                            │
  │◄── 4. 302 Redirect ────│ (error_page 401 = @signin) │                            │
  │   (На Keycloak Login)  │                            │                            │
  │                        │                            │                            │
  │─── 5. Переход в браузер на страницу ввода пароля ───────────────────────────────►│
  │◄── 6. Успешный вход: редирект с Authorization Code ──────────────────────────────│
  │                        │                            │                            │
  │─── 7. GET /oauth2/callback?code=XYZ ───────────────►│                            │
  │                        │                            │── 8. Обмен кода на JWT ───►│
  │                        │                            │◄── ID Token / Access Token─│
  │◄── 9. Set-Cookie: _oauth2_proxy=EncryptedSession ───│                            │
  │                        │                            │                            │
  │─── 10. GET /dashboard ─►│                            │                            │
  │   (С Cookie сессии)    │── 11. auth_request /auth ─►│                            │
  │                        │                            │                            │
  │                        │◄── 12. 202 Accepted ───────│                            │
  │                        │    + Заголовки:            │                            │
  │                        │      X-Auth-Request-User   │                            │
  │                        │      X-Auth-Request-Email  │                            │
  │                        │                            │                            │
  │                        │── 13. proxy_pass (с X-User, X-Email) ──► [ Backend App ]│
  │◄── 14. 200 OK ─────────│◄── 200 OK ─────────────────────────────── [          ] │
```

### 2.2 Ключевые фазы обработки подзапроса в Nginx

1. **Фаза авторизации (`NGX_HTTP_ACCESS_PHASE`):**  
   Директива `auth_request /oauth2/auth;` перехватывает управление до того, как Nginx начнет проксировать данные в целевой бэкенд.
2. **Очистка служебных заголовков и тела:**  
   Подзапрос к auth-сервису обязан содержать только заголовки (включая Cookie). Передача клиентского тела запроса (payload) в подзапрос запрещается директивами `proxy_pass_request_body off;` и `proxy_set_header Content-Length "";`. В противном случае клиентский POST-запрос на 10 МБ вызовет зависание auth-прокси.
3. **Обработка статусов ответа:**  
   * **`200 OK` / `202 Accepted`:** Доступ разрешен. Nginx сохраняет необходимые заголовки авторизации через `auth_request_set` и продолжает стандартный конвейер проксирования.
   * **`401 Unauthorized`:** Пользователь не авторизован (нет Cookie или истекла сессия). Директива `error_page 401 = @oauth2_signin;` перехватывает ошибку и перенаправляет браузер на маршрут аутентификации.
   * **`403 Forbidden`:** Пользователь аутентифицирован, но не состоит в требуемой роли/группе IdP. Nginx отдает клиенту страницу запрета доступа 403.

---

## 3. Практические сценарии

### Сценарий 1: Защита внутренних дашбордов (Prometheus, Admin Panel) через OAuth2-Proxy и Keycloak

**Контекст:** В локальной сети работают сервисы без встроенной аутентификации (Prometheus на `127.0.0.1:9090` и внутренняя панель управления на `127.0.0.1:8000`). Требуется закрыть доступ к ним через корпоративный Keycloak (OIDC).

#### 1. Конфигурация Nginx (`/etc/nginx/conf.d/sso_gateway.conf`)

```nginx
# Пул процессов OAuth2-Proxy
upstream oauth2_proxy_backend {
    server 127.0.0.1:4180;
    keepalive 16;
}

# Пул защищаемого сервиса (Prometheus)
upstream prometheus_backend {
    server 127.0.0.1:9090;
    keepalive 16;
}

server {
    listen 80;
    server_name monitoring.internal.company.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name monitoring.internal.company.com;

    # SSL сертификаты
    ssl_certificate /etc/ssl/certs/internal_wildcard.crt;
    ssl_certificate_key /etc/ssl/private/internal_wildcard.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Точка входа для авторизационного сервиса OAuth2-Proxy
    location /oauth2/ {
        proxy_pass http://oauth2_proxy_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Внутренний эндпоинт проверки прав (Subrequest)
    location = /oauth2/auth {
        internal;
        proxy_pass http://oauth2_proxy_backend;
        proxy_http_version 1.1;

        # Запрет передачи тела запроса в auth-сервис
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";

        # Передача заголовков оригинального запроса
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Uri $request_uri;
    }

    # Именованный location для обработки 401 и редиректа на IdP
    location @oauth2_signin {
        # Редирект пользователя на вход с сохранением исходного URL возврата (rd)
        return 302 /oauth2/start?rd=$scheme://$host$request_uri;
    }

    # Публичный эндпоинт проверки здоровья (Bypass аутентификации)
    location = /healthz {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }

    # Защищенный основной сервис (Prometheus)
    location / {
        # Активация Forward Auth проверки
        auth_request /oauth2/auth;

        # Перехват 401 Unauthorized для старта OAuth2 flow
        error_page 401 = @oauth2_signin;

        # Извлечение данных пользователя из заголовков ответа OAuth2-Proxy
        auth_request_set $auth_user $upstream_http_x_auth_request_user;
        auth_request_set $auth_email $upstream_http_x_auth_request_email;
        auth_request_set $auth_groups $upstream_http_x_auth_request_groups;

        # Проброс контекста пользователя в защищаемое приложение
        proxy_set_header X-Forwarded-User $auth_user;
        proxy_set_header X-Forwarded-Email $auth_email;
        proxy_set_header X-Forwarded-Groups $auth_groups;

        # Проброс Cookie авторизации обратно клиенту (если сессия была обновлена)
        auth_request_set $auth_cookie $upstream_http_set_cookie;
        add_header Set-Cookie $auth_cookie;

        # Проксирование в защищаемый сервис
        proxy_pass http://prometheus_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### 2. Конфигурация сервиса OAuth2-Proxy (`/etc/oauth2-proxy/oauth2-proxy.cfg`)

```ini
http_address = "127.0.0.1:4180"
reverse_proxy = true

# Настройки OIDC-провайдера (Keycloak)
provider = "keycloak-oidc"
client_id = "nginx-sso-gateway"
client_secret = "SecretKeyGeneratedInKeycloak2026"
oidc_issuer_url = "https://sso.company.com/realms/production"

# Ограничение по домену электронной почты и группам
email_domains = [ "company.com" ]
allowed_groups = [ "devops", "sre", "platform-admins" ]

# Настройки безопасности Cookie сессии
cookie_name = "_infra_sso_session"
cookie_secret = "RandomBase64EncodedKey32BytesLength=="
cookie_secure = true
cookie_httponly = true
cookie_samesite = "lax"
cookie_expire = "12h"
cookie_refresh = "1h"

# Заголовки, возвращаемые в Nginx для проброса в бэкенд
set_xauthrequest = true
pass_user_headers = true
pass_authorization_header = false
```

#### 3. Systemd-юнит для OAuth2-Proxy (`/etc/systemd/system/oauth2-proxy.service`)

```ini
[Unit]
Description=OAuth2 Proxy Forward Authentication Engine
After=network.target

[Service]
Type=simple
User=oauth2-proxy
Group=oauth2-proxy
ExecStart=/usr/local/bin/oauth2-proxy --config=/etc/oauth2-proxy/oauth2-proxy.cfg
Restart=always
RestartSec=5s
LimitNOFILE=65536

# Харденинг изоляции
ProtectSystem=strict
ProtectHome=true
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

---

### Сценарий 2: Аутентификация API через внутренний сервис верификации токенов (Bearer JWT)

**Контекст:** Внешние клиенты и микросервисы вызывают шлюз API с заголовком `Authorization: Bearer <JWT>`. Nginx проверяет валидность токена и права доступа через внутренний легковесный auth-сервис на `127.0.0.1:8081`.

```nginx
server {
    listen 443 ssl http2;
    server_name api.company.com;

    # SSL конфигурация ...

    # Внутренний обработчик валидации JWT
    location = /internal/api-auth {
        internal;
        proxy_pass http://127.0.0.1:8081/v1/validate;
        proxy_http_version 1.1;

        # Проброс заголовка авторизации в валидатор
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Original-URI $request_uri;
        proxy_set_header X-Original-Method $request_method;

        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
    }

    # Защищенный API бэкенд
    location /v1/ {
        auth_request /internal/api-auth;

        # В случае невалидного токена возвращаем JSON вместо HTML редиректа
        error_page 401 = @api_unauthorized;
        error_page 403 = @api_forbidden;

        # Передача извлеченного из токена Subject ID и Tenant ID
        auth_request_set $client_sub $upstream_http_x_token_sub;
        auth_request_set $client_tenant $upstream_http_x_token_tenant;

        proxy_set_header X-Consumer-ID $client_sub;
        proxy_set_header X-Tenant-ID $client_tenant;

        proxy_pass http://api_upstream_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location @api_unauthorized {
        default_type application/json;
        return 401 '{"error": "unauthorized", "message": "Missing or expired Bearer token"}\n';
    }

    location @api_forbidden {
        default_type application/json;
        return 403 '{"error": "forbidden", "message": "Insufficient scopes for requested endpoint"}\n';
    }
}
```

---

## 4. Операции и команды

### 4.1 Управление сервисами и валидация конфигурации

```bash
# Проверка синтаксиса Nginx
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезапуск OAuth2-Proxy и перезагрузка Nginx
sudo systemctl restart oauth2-proxy
sudo systemctl reload nginx

# Проверка статуса сервиса авторизации
sudo systemctl status oauth2-proxy --no-pager
# → Active: active (running) since Sat 2026-10-17 21:30:00 MSK; 1h ago
```

### 4.2 Тестирование цепочки авторизации через `curl`

```bash
# 1. Запрос неавторизованного клиента: должен вернуться 302 редирект на логин
curl -i -s https://monitoring.internal.company.com/
# → HTTP/2 302
# → location: /oauth2/start?rd=https://monitoring.internal.company.com/

# 2. Прямой опрос внутреннего /oauth2/auth без cookie: статус 401
curl -i -s -H "Host: monitoring.internal.company.com" http://127.0.0.1:4180/oauth2/auth
# → HTTP/1.1 401 Unauthorized

# 3. Запрос с валидной сессионной Cookie: статус 200 и возврат контента
curl -i -s -b "_infra_sso_session=VALID_ENCRYPTED_COOKIE_VALUE" \
     https://monitoring.internal.company.com/graph
# → HTTP/2 200
# → content-type: text/html; charset=utf-8
```

---

## 5. Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Бесконечный циклический редирект (302 Redirect Loop)** | 1. URL редиректа `/oauth2/start` попадает под общий блок `location /`, требующий `auth_request`.<br>2. Cookie сессии установлена для другого домена (`cookie_domain`). | `curl -Iv https://site/` показывает бесконечные 302 на самого себя. | 1. Вынести `location /oauth2/` в отдельный блок **без** директивы `auth_request`.<br>2. Проверить совпадение `cookie_domain` и домена хоста. |
| **Зависание POST/PUT запросов с телом (`client request timed out`)** | В подзапрос `auth_request` передается тело клиентского запроса, которое сервис авторизации не вычитывает. | В `error.log`: `"client request body is being read..."` или таймауты 504 при POST-запросах. | В блоке `location = /oauth2/auth` жестко прописать:<br>`proxy_pass_request_body off;`<br>`proxy_set_header Content-Length "";`. |
| **Переменные пользователя пустые на бэкенде (`X-Forwarded-User: -`)** | Значение `$upstream_http_*` перезаписывается или теряется, если `auth_request_set` вызван не в том же блоке `location`. | В логах бэкенда заголовок `X-Forwarded-User` приходит пустым. | Директивы `auth_request_set $var $upstream_http_*;` должны находиться непосредственно в блоке `location /`, где определен `auth_request`. |
| **Ошибка `500 Internal Server Error` при вызове подзапроса** | Сервис OAuth2-Proxy упал, перегружен или слушает не тот сокет/порт. | В `error.log`: `"connect() failed (111: Connection refused) while connecting to upstream, request: "GET /oauth2/auth""`. | Проверить состояние демона: `systemctl status oauth2-proxy` и прослушивание сокетов: `ss -tulpn \| grep 4180`. |
| **`400 Bad Request` от IdP при попытке входа** | Некорректно настроен Redirect URI (Redirect Callback) в панели Keycloak / Okta. | В логах браузера ошибка `invalid_redirect_uri`. | В настройках клиента Keycloak добавить в Valid Redirect URIs:<br>`https://monitoring.internal.company.com/oauth2/callback`. |

---

## 6. Рекомендации и лучшие практики

1. **Используйте флаг `internal` для эндпоинта подзапроса:**  
   Блок `location = /oauth2/auth` должен быть строго закрыт директивой `internal;`. Внешний клиент не должен иметь возможности напрямую вызвать подзапрос в обход конвейера.
2. **Всегда отключайте передачу тела запроса в подзапросах:**  
   Обязательно выставляйте `proxy_pass_request_body off;` и сбрасывайте `Content-Length`. Auth-сервису для принятия решения требуются только заголовки (Cookie, Authorization, Client IP).
3. **Защищайте Cookie сессии (Security Flags):**  
   Для сессионных cookie OAuth2-Proxy всегда активируйте флаги `cookie_secure = true` (только по HTTPS), `cookie_httponly = true` (защита от кражи через XSS в JS) и `cookie_samesite = "lax"` (защита от CSRF-атак).
4. **Организуйте Bypass для Health Checks и Webhooks:**  
   Системные проверки жизнеспособности (`/healthz`, `/livez`) и внешние вебхуки (например, входящие алерты Alertmanager или хуки CI/CD) не поддерживают интерактивный вход. Выносите их в выделенные `location` с префиксом `^~` без `auth_request`.
5. **Ротируйте `cookie_secret` в автоматизированных пайплайнах:**  
   Используйте 32-байтный псевдослучайный ключ (`openssl rand -base64 32`). При наличии нескольких инстансов Nginx / OAuth2-Proxy они обязаны использовать один и тот же секрет для бесшовной балансировки сессий.

---

## 7. Дополнительная информация

- [Nginx: внутренний роутинг и подзапросы](../Core/Location/internal_routing.md) — низкоуровневые механизмы директив `internal` и `subrequest`.
- [Nginx: обратный прокси для Grafana](./nginx_as_reverse_proxy_for_grafana.md) — настройка Grafana Auth Proxy.
- [Руководство по безопасности Nginx](../Security/nginx_security_guide.md) — системный харденинг веб-сервера.
