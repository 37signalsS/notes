# Аутентификация в Traefik: OIDC/OAuth2 Proxy, Authelia, ForwardAuth

## Определения

**OIDC (OpenID Connect)** — слой аутентификации поверх OAuth2: выдает ID-токен (JWT) с утверждениями о пользователе; теоретическая база — в [OAuth2/OIDC overview](../../Security/Concepts/oauth2_overview.md). Здесь даем прикладную сторону для Traefik.

**ForwardAuth middleware** — middlewer, перенаправляющий каждый HTTP-запрос на внешний эндпоинт аутентификации; если тот вернет `2xx` — пропускает запрос к бэкенду, если `401/403` — отвечает клиенту.

**OAuth2 Proxy** — внешний компонент: обрабатывает редиректы к IdP (Authorization Code + PKCE), валидирует токены, сохраняет сессию в cookie, отдает `X-Auth-Request-*` заголовки. Никакого «Proxy в Nginx» — для Traefik это просто адрес ForwardAuth.

**Authelia** — self-hosted SSO/2FA (TOTP, WebAuthn), встраивается в Traefik так же через ForwardAuth.

**JWT/JWKS** — формат токена (JSON Web Token) и набор ключей для проверки подписи; в приложении, получающем `X-Auth-Request-User`, JWT уже не нужен — о проверке заботится OAuth2 Proxy.

## Базовые концепции

### Почему «нет переключателя aбукти» в Traefik

Traefik **не выполняет** OIDC-диалог с IdP сам: он проксирует решение аутентификации внешнему сервису. Причины:

- OAuth2-флоу — редиректы, state/CSRF, PKCE, refresh — слишком интерактивен для middleware;
- хранение сессий и проверка токенов — работа сервиса вроде OAuth2 Proxy;
- в Traefik остаются только **решения**: пускать/запретить по `X-Auth-Request-*`.

### Поток с OAuth2 Proxy (ForwardAuth)

```
 клиент ──GET /app──▶ Traefik (router + forwardAuth middleware)
     │                       │ не аутентифицирован
     │ 302 ────────────────▶  │  ──X-Auth-Request-Redirect + URL──▶ OAuth2 Proxy
     │                       │        │ (session? cookie? refresh?)
     │                       │ 302 ─▶ IdP (Keycloak/Vault, etc.)
 Код авторизации + PKCE     │  ◀──────── 302, код
     │                       │   OAuth2 Proxy → OIDC token endpoint
     │                       │   проверка JWT (JWKS) + кука сессии
     │                       │        │
     │  X-Auth-Request-User / E-Mail (2xx) queue
     │                       │
     │ ──headers бэкенду──▶ app (получает X-Auth-Request-User и др.)
```

Что делает ForwardAuth-соmпоnent:

- при отсутствии сессии редиректит клиента на OAuth2 Proxy с параметрами (через `X-Auth-Request-Redirect`);
- при успешной аутентификации — **удаляет** служебные заголовки аутентификации клиента и подставляет удостоверяющие (`X-Auth-Request-*`), которые бэкенд считает доверительными;
- для защиты API/SPA нередко используется базовый (JSON) флоу — ForwardAuth уже и API, И фронт за одной маршрутной точкой.

## Практические сценарии

### Сценарий 1: Защита приложения через OAuth2 Proxy (Docker Compose)

```yaml
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.7
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
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.auth.rule=Host(`app.example.com`) && PathPrefix(`/oauth2/`)"
      - "traefik.http.routers.auth.service=oauth2-proxy"

      # Маршрут приложения через forwardAuth
      - "traefik.http.routers.app.rule=Host(`app.example.com`)"
      - "traefik.http.routers.app.service=app-backend"
      - "traefik.http.routers.app.middlewares=authentication@docker"
      - "traefik.http.middlewares.authentication.forwardauth.address=http://oauth2-proxy:4180/oauth2/auth"
      - "traefik.http.middlewares.authentication.forwardauth.authResponseHeaders=X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Access-Token"

  app:
    image: httpd:2.4-alpine
    networks:
      - default
    labels:
      - "traefik.enable=true"
      - "traefik.http.services.app-backend.loadbalancer.server.port=80"
```

Проверка (`Authorization` в консоль), что заголовки доходят до приложения — лог access-log `X-Auth-Request-User`:

```bash
docker logs oauth2-proxy | rg -i 'auth|no cookie'
docker logs traefik | rg -i 'forward|auth'
# Полный доступ по адресу: залогиниться в IdP и проверить заголовок на бэкенде
```

### Сценарий 2: Authelia (self-hosted SSO) — та же схема

- Вместо OAuth2 Proxy — контейнер `authelia/authelia`.
- В Traefik: forwardAuth с `tls.insecureSkipVerify: false` (по HTTPS) и `authResponseHeaders` — `Remote-User, Remote-Name, Remote-Groups`.
- Authelia берёт на себя и 2FA (TOTP/WebAuthn), политики доступа по группам, session storage.
- Роуты для `/verify*` AuthFLow помечаются в том же приложении, что и фронт.

### Сценарий 3: API/SPA с Bearer токеном (вместо full-page redirect)

Для API-клиентов, которым не нужен cookie-флоу:

- introspect: OAuth2 Proxy с `--skip-auth-preflight=true` для `/docs`, прямые API-маршруты — с forwardAuth в режиме `query`? Нет: для API используйте `forwardauth.address` без редиректа — Traefik ForwardAuth вернет `403` напрямую, если OAuth2 Proxy скажет «нет cookie».

Наиболее практичный вариант для API у OAuth2 Proxy:

```yaml
    oauth2-proxy:
      command:
        - --set-xauthrequest=true
        - --email-domain=example.com
        # не редиректить на IdP для API — отдавать 401/403 напрямую
        - --skip-jwt-bearer-tokens=true   # проверка Bearer JWT без cookie
```

В приложении после этого можно считывать `X-Auth-Request-Access-Token`.

### Сценарий 4: Logout и завершение сессии

OAuth2 Proxy и Authelia поддерживают logout-endpoint, который Traefik проксирует как обычный маршрут.

#### OAuth2 Proxy logout

```yaml
services:
  traefik:
    labels:
      # Logout-роут
      - "traefik.http.routers.logout.rule=PathPrefix(`/oauth2/signout`)"
      - "traefik.http.routers.logout.entrypoints=websecure"
      - "traefik.http.routers.logout.service=oauth2-proxy"
      - "traefik.http.routers.logout.tls.certresolver=le"
```

При запросе `/oauth2/signout` OAuth2 Proxy:
1. Удаляет сессионную cookie.
2. Редиректит на IdP (`/protocol/openid-connect/logout`) для SLO (если настроено).
3. После logout перенаправляет обратно на `--redirect-url` (обычно `/`).

Проверка:

```bash
curl -I https://app.example.com/oauth2/signout
# → 302 Found → Location: https://idp.example.com/.../logout
```

#### Автоматический logout по таймауту

```yaml
oauth2-proxy:
  command:
    - --cookie-refresh=1h           # обновление cookie
    - --cookie-expire=24h           # абсолютный срок жизни
    - --session-store-type=redis    # хранение сессий в Redis (для multi-replica)
```

Redis-хранилище сессий обязательно при нескольких репликах OAuth2 Proxy (иначе сессия записывается в память конкретного инстанса и теряется при переключении).

#### Clear-Site-Data

Для принудительной очистки клиентских данных:

```yaml
http:
  middlewares:
    logout-headers:
      headers:
        clearSiteData:
          - "cache"
          - "cookies"
          - "storage"
```

Применять к `/oauth2/signout`.

#### Примечание по JWT

JWT — stateless: отзыв токена **невозможен** без blacklist/CRL. Для немедленного завершения сессии:
- Используйте короткий `access_token` TTL (5–15 минут).
- Храните `refresh_token` в Redis с TTL; при logout — удаляйте пару.
- Для API: проверяйте `jti` (JWT ID) в Redis blacklist на каждый запрос через ForwardAuth.

## Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Циклический редирект на /oauth2/** | OAuth2 Proxy не видит cookie-secret (`--cookie-secure` на http) | Включить `--cookie-secure=false` в dev или перейти на HTTPS |
| **`X-Auth-Request-*` не доходят до приложения** | ForwardAuth `authResponseHeaders` не перечислены | Привести список заголовков (см. Compose выше) |
| **ForwardAuth вернул 500/502** | OAuth2 Proxy недоступен/не готов | Проверить сеть контейнеров, порт 4180, логи oauth2-proxy |
| **OIDC-флоу падает «invalid redirect_uri»** | `redirect-url` не совпадает с зарегистрированным в IdP | В IdP зарегистрировать точный `https://app.example.com/oauth2/callback` |
| **JWT не проходит проверку** | IdP публикует RSA JWKS, а OAuth2 Proxy получает конфигурацию с ip-key | Проверить `--oidc-issuer-url` и доступность `.well-known/openid-configuration` |
| **После входа падает state mismatch** | Два инстанса OAuth2 Proxy / лишний прокси | Один экземпляр на домен; общий `cookie-secret` и фикс host |

## Рекомендации

- ForwardAuth — стратегия «все наружу через единый эдг»: ставить OAuth2 Proxy/Authelia **в один docker network** с Traefik (никаких внешних портов).
- Всегда `--cookie-secure=true`, `--set-xauthrequest=true` и генерируемый `cookie-secret` (общая в Helm/K8s — из секрета, одинаковый на всех репликах!).
- Не примешивайте клиентские `Authorization`; Traefik отдаёт доверенные заголовки только после успешного ForwardAuth.
- Для множества приложений пользы: одна точка аутентификации (OAuth2 Proxy) на несколько Traefik-роутов, а не N переключений.
- Если бэкенд сильно зависит от заголовков аутентификации — смотрите [Приложения-заголовки (middlewares-security)](./traefik-middlewares-security.md) и [Forwarded headers (параметры подлинности IP)](./traefik-forwarded-headers.md).

## Дополнительная информация

- [OAuth2/OIDC (Security)](../../Security/Concepts/oauth2_overview.md) — теория потоков, PKCE, ID-токены.
- [Traefik Middlewares: безопасность](./traefik-middlewares-security.md) — forwardAuth, basicauth, headers.
- [Traefik Plugins](./traefik-plugins.md) — если решений OAuth2 Proxy недостаточно и нужны community-плагины JWT.
- [Traefik Forwarded Headers](./traefik-forwarded-headers.md) — корректная передача реального IP за прокси (важно для forwardAuth и вебхук-check).