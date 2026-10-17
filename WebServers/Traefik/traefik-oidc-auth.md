# Аутентификация в Traefik: OIDC/OAuth2 Proxy, Authelia, ForwardAuth

**Актуально для:** Traefik v3.x (протестировано на v3.3–v3.7; OAuth2 Proxy v7.8.x–v7.15.x, Authelia v4.38.x–v4.39.x)

## Определения

**OIDC (OpenID Connect)** — протокол идентификации и аутентификации, построенный поверх спецификации OAuth 2.0 (RFC 6749). Позволяет клиенту верифицировать личность пользователя на основе аутентификации, выполненной сервером авторизации (IdP), и получать базовую информацию о профиле в виде подписанного JSON Web Token (ID Token). Теоретическая база протокола описана в [OAuth2/OIDC overview](../../Security/Concepts/oauth2_overview.md).

**ForwardAuth** — встроенный middleware Traefik, делегирующий авторизацию каждого входящего HTTP-запроса внешнему сервису аутентификации. Traefik выполняет внутренний HTTP-подзапрос (subrequest) на заданный адрес: при коде `2xx` запрос перенаправляется целевому бэкенду с добавлением доверенных заголовков, а при любых других статусах (`401`, `403`, `302`) ответ auth-сервиса напрямую возвращается клиенту.

**OAuth2 Proxy** — автономный обратный прокси-сервер и демон аутентификации, реализующий диалог с OIDC/OAuth2-провайдерами (Authorization Code Flow с PKCE, валидация ID/Access токенов, управление сессиями в зашифрованных cookie или Redis). В связке с Traefik выступает в роли обработчика ForwardAuth на эндпоинте `/oauth2/auth` и терминатора OAuth-коллбэков на `/oauth2/callback`.

**Authelia** — self-hosted система аутентификации и управления доступом (SSO) с поддержкой двухфакторной аутентификации (2FA: TOTP, FIDO2 WebAuthn, Duo), централизованных списков контроля доступа (ACL) и интеграции с локальными каталогами учетных записей (LDAP, Active Directory, локальный YAML-файл). Интегрируется с Traefik через эндпоинт `/api/verify`.

**IdP (Identity Provider)** — централизованный сервер идентификации (Keycloak, Dex, Authentik, FreeIPA), выпускающий криптографические токены и хранящий учетные записи пользователей.

**PKCE (Proof Key for Code Exchange, RFC 7636)** — расширение протокола OAuth 2.0, предотвращающее перехват кода авторизации через использование динамического секрета (`code_verifier` и `code_challenge`). Обязательно в современной архитектуре аутентификации.

**JWT (JSON Web Token) / JWKS (JSON Web Key Set)** — стандартизированный формат компактных подписанных токенов (RFC 7519) и набор открытых криптографических ключей сервера IdP (RFC 7517), публикуемый по адресу `/.well-known/jwks.json` для автономной проверки подписи токенов без постоянных сетевых запросов к IdP.

---

## Базовые концепции и архитектура

### Почему в Traefik отсутствует встроенный OIDC-клиент

Traefik проектировался как высокопроизводительный динамический L7-маршрутизатор и обратный прокси-сервер. В архитектуре Traefik намеренно не реализуется встроенный диалог OpenID Connect (OIDC Client):

1. **Сложность жизненного цикла сессий:** OIDC Authorization Code Flow требует обработки множественных HTTP-перенаправлений, генерации и валидации криптографических параметров `state`, `nonce`, PKCE `code_verifier`, обработки refresh-токенов и шифрования cookie сессий.
2. **Разделение ответственности:** L7-прокси отвечает за быструю маршрутизацию сетевых пакетов, TLS-терминацию и балансировку. Хранение сессий пользователей (в памяти или внешнем Redis), управление 2FA и интеграция с LDAP/IdP выносятся в специализированные демоны аутентификации (OAuth2 Proxy, Authelia, Authentik).
3. **Единая точка принятия решений:** Traefik делегирует проверку прав через минималистичный интерфейс `ForwardAuth`: внешний сервис отвечает только «разрешить с заголовками» (код `2xx`) или «запретить/перенаправить» (код `401`/`403`/`302`).

### Поток обработки запросов с OAuth2 Proxy (ForwardAuth)

```
[Клиент]                 [Traefik v3]               [OAuth2 Proxy]                 [IdP (Keycloak/Dex)]            [Бэкенд App]
   │                          │                           │                                │                             │
   │─── 1. GET /app ─────────▶│                           │                                │                             │
   │                          │─── 2. GET /oauth2/auth ──▶│ (проверка Cookie сессии)       │                             │
   │                          │                           │                                │                             │
   │                          │◀── 3. 401 Unauthorized ───│ (нет cookie)                   │                             │
   │◀── 4. 302 Found ─────────│                           │                                │                             │
   │   (Location: /oauth2/start)                          │                                │                             │
   │                          │                           │                                │                             │
   │─── 5. GET /oauth2/start ─▶──────────────────────────▶│                                │                             │
   │                          │                           │─── 6. 302 к IdP (с PKCE) ─────▶│                             │
   │◀── 7. Редирект на IdP ───┴───────────────────────────│                                │                             │
   │                          │                           │                                │                             │
   │─── 8. Аутентификация ────────────────────────────────────────────────────────────────▶│                             │
   │◀── 9. Редирект с Code ───────────────────────────────────────────────────────────────│                             │
   │                          │                           │                                │                             │
   │─── 10. GET /oauth2/callback?code=... ───────────────▶│                                │                             │
   │                          │                           │─── 11. Обмен Code на токены ──▶│                             │
   │                          │                           │◀── 12. ID Token + Access Token─│                             │
   │                          │                           │ (генерация зашифрованной cookie)                             │
   │◀── 13. 302 /app + Set-Cookie ────────────────────────│                                │                             │
   │                          │                           │                                │                             │
   │─── 14. GET /app + Cookie▶│                           │                                │                             │
   │                          │─── 15. GET /oauth2/auth──▶│                                │                             │
   │                          │    (с Cookie клиента)     │ (проверка сессии: OK)          │                             │
   │                          │◀── 16. 202/200 OK ────────│                                │                             │
   │                          │    + X-Auth-Request-User  │                                │                             │
   │                          │    + X-Auth-Request-Email │                                │                             │
   │                          │                           │                                │                             │
   │                          │─── 17. GET /app (с внедренными заголовками) ────────────────────────────────────────────▶│
   │                          │        X-Auth-Request-User: alice                                                        │
   │                          │        X-Auth-Request-Email: alice@example.local                                         │
   │◀── 18. 200 OK (данные приложения) ──────────────────────────────────────────────────────────────────────────────────│
```

### Алгоритм работы и безопасность заголовков (Header Spoofing Prevention)

При обработке входящего соединения механизм ForwardAuth выполняет следующие действия:

1. **Формирование подзапроса:** Traefik копирует заголовки входящего запроса клиента (включая `Cookie`, `Authorization` и, при включенном `trustForwardHeader: true`, заголовки `X-Forwarded-*`) и передает их по HTTP на внутренний адрес демона аутентификации.
2. **Обработка ответа от auth-сервиса:**
   - **Статус `2xx` (обычно 200 или 202):** доступ разрешен. Traefik считывает из ответа auth-сервиса заголовки, перечисленные в директиве `authResponseHeaders` (например, `X-Auth-Request-User`, `X-Auth-Request-Email`, `Remote-User`), и внедряет их в исходный запрос перед отправкой на бэкенд.
   - **Статус `302/307`:** перенаправление. Traefik возвращает клиенту заголовок `Location` для старта OIDC-флоу в браузере.
   - **Статус `401/403`:** отказ в доступе. Клиент получает ошибку напрямую.
3. **Защита от спуфинга заголовков (Header Injection):**
   Если вредоносный клиент самостоятельно передает заголовок `X-Auth-Request-User: admin` напрямую в открытый Traefik, существует риск компрометации бэкенда.
   - Traefik перезаписывает заголовки, перечисленные в `authResponseHeaders`, значениями, полученными из ответа ForwardAuth-сервера.
   - **Критическое правило SRE:** Всегда удаляйте входящие заголовки `X-Auth-Request-*` и `Remote-*` на уровне входного роутера или EntryPoint с помощью middleware `Headers` (`customRequestHeaders`), чтобы неавторизованные запросы или эндпоинты, не защищенные middleware, никогда не пропускали поддельные данные от клиента.

---

## Практические сценарии

### Требования к окружению (Prerequisites)

- Хост под управлением Linux (Ubuntu 22.04/24.04 LTS, Debian 12 или Rocky Linux 9).
- Установленный Docker Engine v26+ и Docker Compose v2.24+ (либо Kubernetes v1.28+ на bare-metal инфраструктуре).
- Развернутый локальный или корпоративный IdP (Keycloak, Dex, Authentik или FreeIPA с OIDC). В примерах используется Realm `company` на `https://idp.example.local`.
- Настроенные DNS-записи в локальной сети (`/etc/hosts` для стенда):
  - `traefik.example.local` — входная точка Traefik;
  - `app.example.local` — защищаемое веб-приложение;
  - `auth.example.local` — интерфейс SSO/Authelia;
  - `idp.example.local` — корпоративный сервер Keycloak.
- Сгенерированный криптографический секрет для шифрования сессионных cookie (32 байта base64):
  ```bash
  openssl rand -base64 32 | tr -- '+/' '-_'
  # → 4A7kFqW8pM3vT9yX2zL1rE6bN0sV8uQ3cI5wP7xZ2mE=
  ```

---

### Сценарий 1: Защита веб-сервиса через OAuth2 Proxy в Docker Compose

Полный стек production-уровня: Traefik v3 с TLS-терминацией, OAuth2 Proxy в режиме OIDC и тестовый бэкенд (`whoami`). Все компоненты изолированы во внутренней Docker-сети `edge-net`.

#### Шаг 1: Конфигурационный файл docker-compose.yml

```yaml
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.15.1
    restart: unless-stopped
    command:
      - --provider=oidc
      - --oidc-issuer-url=https://idp.example.com/realms/myrealm
      - --client-id=${OAUTH_CLIENT_ID}
      - --client-secret=${OAUTH_CLIENT_SECRET}
      - --redirect-url=https://app.example.com/oauth2/callback
      - --cookie-secret=${COOKIE_SECRET}
      - --cookie-secure=true
      - --set-xauthrequest=true                 # отдавать X-Auth-Request-* в forwardAuth
      - --set-authorization-header=true         # Authorization: Bearer <access_token>
      - --email-domain=example.com
      - --whitelist-domain=.example.com
    networks: [edge]

  traefik:
    image: traefik:v3.7
    container_name: traefik
    restart: unless-stopped
    command:
      - "--global.checknewversion=false"
      - "--global.sendanonymoususage=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--entrypoints.websecure.address=:443"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.network=edge-net"
      - "--providers.file.directory=/etc/traefik/dynamic"
      - "--providers.file.watch=true"
      - "--accesslog=true"
      - "--accesslog.fields.names.StartUTC=drop"
      - "--log.level=INFO"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./certs:/etc/traefik/certs:ro"
      - "./dynamic:/etc/traefik/dynamic:ro"
    networks:
      - edge-net

  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.8.1
    container_name: oauth2-proxy
    restart: unless-stopped
    environment:
      OAUTH2_PROXY_PROVIDER: "oidc"
      OAUTH2_PROXY_OIDC_ISSUER_URL: "https://idp.example.local/realms/company"
      OAUTH2_PROXY_CLIENT_ID: "traefik-proxy-client"
      OAUTH2_PROXY_CLIENT_SECRET: "SecretClientToken123456"
      OAUTH2_PROXY_COOKIE_SECRET: "4A7kFqW8pM3vT9yX2zL1rE6bN0sV8uQ3cI5wP7xZ2mE="
      OAUTH2_PROXY_COOKIE_DOMAINS: ".example.local"
      OAUTH2_PROXY_COOKIE_SECURE: "true"
      OAUTH2_PROXY_COOKIE_HTTPONLY: "true"
      OAUTH2_PROXY_COOKIE_SAMESITE: "lax"
      OAUTH2_PROXY_EMAIL_DOMAINS: "*"
      OAUTH2_PROXY_SET_XAUTHREQUEST: "true"
      OAUTH2_PROXY_SET_AUTHORIZATION_HEADER: "true"
      OAUTH2_PROXY_PASS_ACCESS_TOKEN: "true"
      OAUTH2_PROXY_UPSTREAMS: "static://202"
      OAUTH2_PROXY_HTTP_ADDRESS: "0.0.0.0:4180"
      OAUTH2_PROXY_REVERSE_PROXY: "true"
      OAUTH2_PROXY_WHITELIST_DOMAINS: ".example.local"
      OAUTH2_PROXY_REDIRECT_URL: "https://app.example.local/oauth2/callback"
    labels:
      - "traefik.enable=true"
      # Роутер для обработки коллбэков и старта OIDC
      - "traefik.http.routers.oauth2.rule=Host(`app.example.local`) && PathPrefix(`/oauth2/`)"
      - "traefik.http.routers.oauth2.entrypoints=websecure"
      - "traefik.http.routers.oauth2.tls=true"
      - "traefik.http.routers.oauth2.service=oauth2-service"
      - "traefik.http.services.oauth2-service.loadbalancer.server.port=4180"

      # Определение middleware ForwardAuth
      - "traefik.http.middlewares.oauth2-forwardauth.forwardauth.address=http://oauth2-proxy:4180/oauth2/auth"
      - "traefik.http.middlewares.oauth2-forwardauth.forwardauth.trustForwardHeader=true"
      - "traefik.http.middlewares.oauth2-forwardauth.forwardauth.authResponseHeaders=X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Preferred-Username,X-Auth-Request-Access-Token,Authorization"
    networks:
      - edge-net

  app:
    image: traefik/whoami:v1.10.1
    container_name: app-protected
    restart: unless-stopped
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`app.example.local`)"
      - "traefik.http.routers.app.entrypoints=websecure"
      - "traefik.http.routers.app.tls=true"
      - "traefik.http.routers.app.middlewares=oauth2-forwardauth@docker"
      - "traefik.http.routers.app.service=app-service"
      - "traefik.http.services.app-service.loadbalancer.server.port=80"
    networks:
      - edge-net

networks:
  edge-net:
    driver: bridge
```

#### Шаг 2: Проверка и диагностика работы

1. Проверка состояния запущенных контейнеров:
```bash
docker compose ps
# → NAME            IMAGE                                     COMMAND                  SERVICE        CREATED         STATUS         PORTS
# → app-protected   traefik/whoami:v1.10.1                    "/whoami"                app            2 minutes ago   Up 2 minutes   80/tcp
# → oauth2-proxy    quay.io/oauth2-proxy/oauth2-proxy:v7.8.1  "/bin/oauth2-proxy"      oauth2-proxy   2 minutes ago   Up 2 minutes   4180/tcp
# → traefik         traefik:v3.7                              "/entrypoint.sh --gl…"   traefik        2 minutes ago   Up 2 minutes   0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```

2. Выполнение запроса неаутентифицированным клиентом (ожидается статус 401 Unauthorized от subrequest, преобразуемый в redirect на OAuth2-флоу):
```bash
curl -k -i -s https://app.example.local/ | head -n 12
# → HTTP/2 401 
# → date: Sat, 17 Oct 2026 14:15:30 GMT
# → content-length: 13
# → content-type: text/plain; charset=utf-8
# → 
# → Unauthorized
```

3. Проверка прямого ответа эндпоинта `/oauth2/auth` внутри сети:
```bash
docker compose exec traefik wget -q -S -O - http://oauth2-proxy:4180/oauth2/auth
# → HTTP/1.1 401 Unauthorized
# → Date: Sat, 17 Oct 2026 14:16:02 GMT
# → Content-Length: 13
# → Content-Type: text/plain; charset=utf-8
```

4. Проверка проброса заголовков после авторизации (в логах `whoami`):
```bash
docker logs app-protected | grep -E "X-Auth-Request|Authorization"
# → X-Auth-Request-User: admin@example.local
# → X-Auth-Request-Email: admin@example.local
# → X-Auth-Request-Preferred-Username: admin
# → Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

### Сценарий 2: Интеграция с Authelia (Self-Hosted SSO/2FA)

Authelia предоставляет централизованный портал авторизации с поддержкой двухфакторной аутентификации (TOTP, WebAuthn) и гибких списков контроля доступа (ACL).

#### Конфигурация Docker Compose для Authelia + Traefik v3

```yaml
services:
  authelia:
    image: authelia/authelia:v4.38.19
    container_name: authelia
    restart: unless-stopped
    volumes:
      - ./authelia/config:/config
    environment:
      AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET_FILE: /config/jwt_secret
      AUTHELIA_SESSION_SECRET_FILE: /config/session_secret
      AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE: /config/storage_key
    labels:
      - "traefik.enable=true"
      # Роутер портала входа Authelia
      - "traefik.http.routers.authelia.rule=Host(`auth.example.local`)"
      - "traefik.http.routers.authelia.entrypoints=websecure"
      - "traefik.http.routers.authelia.tls=true"
      - "traefik.http.routers.authelia.service=authelia-service"
      - "traefik.http.services.authelia-service.loadbalancer.server.port=9091"

      # Middleware ForwardAuth для других сервисов
      - "traefik.http.middlewares.authelia-auth.forwardauth.address=http://authelia:9091/api/verify?rd=https://auth.example.local/"
      - "traefik.http.middlewares.authelia-auth.forwardauth.trustForwardHeader=true"
      - "traefik.http.middlewares.authelia-auth.forwardauth.authResponseHeaders=Remote-User,Remote-Groups,Remote-Name,Remote-Email"
    networks:
      - edge-net
```

#### Фрагмент configuration.yml для Authelia

```yaml
server:
  host: 0.0.0.0
  port: 9091

session:
  name: authelia_session
  same_site: 'lax'
  expiration: '1h'
  inactivity: '15m'
  remember_me_duration: '1M'
  domain: 'example.local'

access_control:
  default_policy: 'deny'
  rules:
    - domain: 'app.example.local'
      policy: 'two_factor'
      subject:
        - 'group:devops'
        - 'group:sre'
    - domain: 'status.example.local'
      policy: 'one_factor'

authentication_backend:
  file:
    path: /config/users_database.yml
    password:
      algorithm: argon2id
```

#### Проверка редиректа на портал Authelia

```bash
curl -k -I https://app.example.local/
# → HTTP/2 302 
# → location: https://auth.example.local/?rd=https%3A%2F%2Fapp.example.local%2F
# → server: Traefik
# → date: Sat, 17 Oct 2026 14:20:10 GMT
```

---

### Сценарий 3: Развертывание в Kubernetes (Bare-Metal / IngressRoute CRD)

Для bare-metal/on-premise инсталляций Kubernetes интеграция с ForwardAuth описывается через кастомные ресурсы Traefik (`Middleware` и `IngressRoute` версии `traefik.io/v1alpha1`).

#### Определение Secret, Middleware и IngressRoute

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oauth2-proxy-secret
  namespace: auth
type: Opaque
stringData:
  cookie-secret: "4A7kFqW8pM3vT9yX2zL1rE6bN0sV8uQ3cI5wP7xZ2mE="
  client-secret: "SecretClientToken123456"
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: oidc-forward-auth
  namespace: auth
spec:
  forwardAuth:
    address: http://oauth2-proxy.auth.svc.cluster.local:4180/oauth2/auth
    trustForwardHeader: true
    authResponseHeaders:
      - X-Auth-Request-User
      - X-Auth-Request-Email
      - X-Auth-Request-Preferred-Username
      - X-Auth-Request-Access-Token
      - Authorization
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: oauth2-proxy-routes
  namespace: auth
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`dashboard.internal.local`) && PathPrefix(`/oauth2/`)
      kind: Rule
      services:
        - name: oauth2-proxy
          port: 4180
  tls:
    secretName: internal-wildcard-tls
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: protected-dashboard
  namespace: monitoring
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`dashboard.internal.local`)
      kind: Rule
      middlewares:
        - name: oidc-forward-auth
          namespace: auth
      services:
        - name: monitoring-dashboard
          port: 8080
  tls:
    secretName: internal-wildcard-tls
```

#### Проверка CRD в кластере:

```bash
kubectl get ingressroute,middleware -A
# → NAMESPACE    NAME                                                AGE
# → auth         ingressroute.traefik.io/oauth2-proxy-routes         10m
# → monitoring   ingressroute.traefik.io/protected-dashboard         10m
# → auth         middleware.traefik.io/oidc-forward-auth             10m

kubectl describe middleware oidc-forward-auth -n auth
# → Name:         oidc-forward-auth
# → Namespace:    auth
# → Spec:
# →   Forward Auth:
# →     Address:               http://oauth2-proxy.auth.svc.cluster.local:4180/oauth2/auth
# →     Auth Response Headers: X-Auth-Request-User, X-Auth-Request-Email...
# →     Trust Forward Header:  true
```

---

### Сценарий 4: Защита API и SPA (Bearer Token без перенаправления)

При защите REST API или SPA браузерный редирект (код 302 с HTML-страницей IdP) приводит к ошибкам CORS и невозможности обработки запроса API-клиентами.

1. **Режим проверки Bearer токенов:**
   OAuth2 Proxy настраивается флагом `--skip-jwt-bearer-tokens=true` и `--extra-jwt-issuers`:
   ```yaml
   command:
     - --skip-jwt-bearer-tokens=true
     - --extra-jwt-issuers=https://idp.example.local/realms/company=traefik-proxy-client
     - --oidc-issuer-url=https://idp.example.local/realms/company
   ```
2. **Поведение ForwardAuth:**
   - Если запрос содержит `Authorization: Bearer <jwt>`, OAuth2 Proxy автономно проверяет криптографическую подпись через JWKS сервера Keycloak.
   - Если токен валиден: эндпоинт `/oauth2/auth` возвращает `202 Accepted`, извлекает claims (sub, email, roles) и передает их в заголовках.
   - Если токен отсутствует или просрочен: возвращается прямой код `401 Unauthorized` (вместо перенаправления на HTML-форму логина).

Проверка API-запроса с токеном:

```bash
curl -k -i -H "Authorization: Bearer eyJhbGciOiJSUzI1..." https://app.example.local/api/v1/metrics
# → HTTP/2 200 
# → content-type: application/json
# → {"status":"ok","authenticated_user":"service-account-prometheus"}
```

---

### Сценарий 5: Завершение сессии и Single Log-Out (SLO)

Корректное завершение сессии требует согласованного удаления локальной cookie в браузере, сессии в Redis и завершения сеанса на сервере IdP.

#### Маршрут Signout в Traefik

```yaml
labels:
  - "traefik.http.routers.signout.rule=Host(`app.example.local`) && PathPrefix(`/oauth2/signout`)"
  - "traefik.http.routers.signout.entrypoints=websecure"
  - "traefik.http.routers.signout.service=oauth2-service"
  - "traefik.http.routers.signout.middlewares=clear-site-data@docker"

  # Middleware принудительной очистки хранилища браузера
  - "traefik.http.middlewares.clear-site-data.headers.customResponseHeaders.Clear-Site-Data=\"cache\", \"cookies\", \"storage\""
```

При переходе на `https://app.example.local/oauth2/signout`:
1. OAuth2 Proxy выставляет заголовок `Set-Cookie` с истекшим сроком жизни (`Max-Age=0`).
2. Очищаются сессионные данные в Redis.
3. Middleware `clear-site-data` принуждает браузер стереть локальный кэш и хранилища `localStorage`/`sessionStorage`.
4. Клиент перенаправляется на эндпоинт IdP:
   `https://idp.example.local/realms/company/protocol/openid-connect/logout?post_logout_redirect_uri=https://app.example.local/`

---

## Диагностика и эксплуатация

### Таблица ключевых команд проверки и отладки

| Задача | Команда | Ожидаемый результат (`# →`) |
| :--- | :--- | :--- |
| **Генерация Cookie Secret** | `openssl rand -base64 32 \| tr -- '+/' '-_'` | 32-байтовая строка в base64 url-safe |
| **Проверка доступности IdP Discovery** | `curl -s https://idp.example.local/realms/company/.well-known/openid-configuration \| jq -r .issuer` | `# → https://idp.example.local/realms/company` |
| **Проверка JWKS ключей IdP** | `curl -s https://idp.example.local/realms/company/protocol/openid-connect/certs \| jq '.keys[0].kid'` | `# → "rX8...k2Q"` (наличие актуального Key ID) |
| **Тест ForwardAuth подзапроса** | `curl -i -H "Host: app.example.local" http://127.0.0.1:4180/oauth2/auth` | `# → HTTP/1.1 401 Unauthorized` |
| **Тест сессионной Cookie** | `curl -k -i -b "_oauth2_proxy=COOKIE_VAL" https://app.example.local/` | `# → HTTP/2 200 OK` + данные бэкенда |
| **Просмотр логов аутентификации** | `docker logs --tail 50 oauth2-proxy \| grep -E "auth\|session"` | Записи о валидации токена или истечении срока сессии |
| **Проверка счетчиков Traefik в Prometheus** | `curl -s http://traefik:8080/metrics \| grep "traefik_service_requests_total"` | Метрики с кодами 200, 302, 401 |

---

## Устранение неисправностей

| Симптом | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| **Бесконечный циклический редирект (Redirect Loop / ERR_TOO_MANY_REDIRECTS)** | Роутер самого обработчика аутентификации (`/oauth2/` или домен Authelia) ошибочно обернут в middleware `forwardauth` | `curl -sIL https://app.example.local/` показывает последовательность повторяющихся 302-редиректов на `/oauth2/start` | Исключить префикс `/oauth2/` из правил middleware `forwardauth`; убедиться, что роутер коллбэка имеет наивысший приоритет |
| **ForwardAuth возвращает код 500 / 502 Bad Gateway** | Демон аутентификации упал, перегружен или недоступен по DNS/сети контейнеров | В логах Traefik: `error while forwarding auth request: dial tcp: lookup oauth2-proxy: no such host` | Проверить нахождение Traefik и auth-демона в общей Docker-сети (`edge-net`); проверить `docker ps` и логи `oauth2-proxy` |
| **Заголовки `X-Auth-Request-*` отсутствуют на бэкенде** | Заголовки не указаны в параметре `authResponseHeaders` middleware Traefik | В логах бэкенда (whoami/httpd) отсутствуют заголовки пользователя | Добавить полный список заголовков через запятую в `traefik.http.middlewares.<name>.forwardauth.authResponseHeaders` |
| **Ошибка IdP: `invalid redirect_uri`** | URL коллбэка в запросе к IdP не совпадает со списком Valid Redirect URIs в настройках клиента IdP | Анализ URL в адресной строке браузера при переходе на IdP: параметр `redirect_uri=...` | Проверить схему (http vs https), порт и точный путь (например, `https://app.example.local/oauth2/callback`) в настройках клиента IdP |
| **Ошибка при входе: `state mismatch` / `CSRF Failed`** | Работает несколько реплик OAuth2 Proxy без общего Redis-хранилища сессий либо разные `cookie-secret` | В логах oauth2-proxy: `CSRF token mismatch` или `Invalid state parameter` | Подключить Redis для хранения сессий (`--session-store-type=redis`); синхронизировать значение `cookie-secret` на всех подах/репликах |
| **Токен не проходит проверку (Invalid Token / Signature verification failed)** | Рассинхронизация времени NTP на серверах либо недоступность JWKS эндпоинта IdP | В логах: `token has expired` или `crypto/rsa: verification error` | Проверить синхронизацию службы `chrony`/`systemd-timesyncd` на хостах; проверить доступность эндпоинта `certs` с хоста auth-демона |
| **Cookie сбрасывается сразу после входа на HTTP-стенде** | Включен флаг `--cookie-secure=true` при тестировании через незащищенное HTTP-соединение | Браузер игнорирует заголовок `Set-Cookie` с директивой `Secure` на `http://` | На тестовом стенде без TLS временно выставить `cookie-secure: false`; в production всегда использовать HTTPS |

---

## Рекомендации и SRE-практики

1. **Сетевая изоляция и Zero Trust:**
   Никогда не публикуйте порты сервисов аутентификации (`4180` у OAuth2 Proxy, `9091` у Authelia) на внешних сетевых интерфейсах хоста (`0.0.0.0`). Общение между Traefik и ForwardAuth-демоном должно происходить исключительно внутри изолированных программных сетей (Docker bridge network без проброса портов наружу либо Kubernetes ClusterIP).
2. **Отказоустойчивость и масштабирование (HA):**
   При запуске более чем одной реплики Traefik или OAuth2 Proxy:
   - Хранение сессий пользователей обязательно переводится в Redis Cluster или Redis Sentinel (`--session-store-type=redis --redis-connection-url=redis://...`).
   - Значения `cookie-secret` и `client-secret` должны передаваться через защищенные Secret-файлы или хранилища секретов (HashiCorp Vault, Kubernetes Secrets).
3. **Оценка задержки (Latency Overhead):**
   Middleware `ForwardAuth` выполняет блокирующий HTTP-подзапрос на **каждый** входящий запрос к защищенному маршруту.
   - SRE обязаны отслеживать накладные расходы на аутентификацию по метрике `traefik_service_request_duration_seconds`.
   - Включайте keep-alive соединения между Traefik и сервисом авторизации, чтобы исключить задержки на повторное рукопожатие TCP.
4. **Предотвращение спуфинга заголовков:**
   На всех внешних точках входа (EntryPoints) настройте сброс пользовательских заголовков аутентификации:
   ```yaml
   http:
     middlewares:
       sanitize-headers:
         headers:
           customRequestHeaders:
             X-Auth-Request-User: ""
             X-Auth-Request-Email: ""
             X-Auth-Request-Preferred-Username: ""
             Remote-User: ""
   ```
5. **Безопасность Cookie:**
   В боевом окружении флаги cookie должны быть строго зафиксированы: `Secure=true`, `HttpOnly=true`, `SameSite=Lax`. Не используйте `SameSite=None`, если приложения работают в рамках единого доменного пространства.

---

## Дополнительная информация

- [Middlewares безопасности Traefik](./traefik-middlewares-security.md) — детальный разбор BasicAuth, IPAllowList, Headers и цепочек Chain.
- [Интеграция Traefik с Kubernetes](./traefik-kubernetes.md) — развертывание Traefik в bare-metal кластерах с использованием CRD IngressRoute.
- [Параметры подлинности IP и Forwarded Headers](./traefik-forwarded-headers.md) — безопасная передача реального клиентского IP за обратным прокси.
- [Теория и протоколы OAuth2/OIDC](../../Security/Concepts/oauth2_overview.md) — спецификации RFC 6749, RFC 7636 (PKCE), типы токенов и вектор атак.
- [Архитектура JWT токенов](../../Security/Concepts/jwt_overview.md) — структура заголовков, полезной нагрузки и проверка цифровых подписей.
- [SSO и OIDC в Angie WebServer](../Angie/angie-oidc.md) — альтернативная реализация аутентификации через модуль `auth_request` в Angie.