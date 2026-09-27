# Middleware для безопасности и аутентификации

## Определения

**BasicAuth** — базовая HTTP-аутентификация по заголовку `Authorization` (Base64), пароли хранятся в виде хешей htpasswd (MD5/BCrypt/Argon2).

**ForwardAuth** — делегирование аутентификации внешнему сервису (Authelia, Authentik, Casdoor, OAuth2 Proxy): Traefik отправляет запрос на `/verify` и доверяет ответу.

**IPAllowList** — ограничение доступа по IP/CIDR.

**Headers** — модификация заголовков запроса/ответа, включая безопасные заголовки (CSP, CORS, HSTS).

**PassTLSClientCert** — передача клиентского сертификата (взаимной TLS-аутентификации) в бэкенд.

**DigestAuth** — дайджест-аутентификация (htdigest), устойчивее к перехвату, чем Basic (передает хеш, а не base64).

**Chain** — композиция middleware в одну цепочку.

## Базовые концепции

### Порядок фильтров имеет значение

Классическая схема защиты эндпоинта от атак — «дешевые» проверки первыми:

```
IPAllowList (отсев по IP, 403)
  → RateLimit (защита от brute-force, 429)
  → BasicAuth/ForwardAuth (проверка credentials, 401)
```

Нарушение порядка (например, BasicAuth до RateLimit) приводит к тому, что перебор паролей не лимитируется. Подробнеe — в [Kubernetes BasicAuth](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md) (там же: генерация хешей, работа с Secrets; здесь рассматривается конфигурация для File/Docker-провайдеров).

### Источник IP в IPAllowList и RateLimit

`IPAllowList` и RateLimit считают «источник» по `RemoteAddr` либо по `sourceCriterion.ipStrategy` из `X-Forwarded-For`. За балансировщиком обязательно настроить и `forwardedHeaders.trustedIPs` на entrypoint, и `depth` — иначе заблокируется/разрешится весь мир (см. [Доверенные заголовки](./traefik-forwarded-headers.md)).

### ForwardAuth: как работает

1. Traefik пересылает запрос на `address` (например, `https://auth.example.com/api/verify?rd=https://...`), передавая `X-Forwarded-Method/Proto/Host/Uri/For`.
2. Ответ `2xx` от auth-сервиса = доступ разрешен; остальные ответы проксируются клиенту как есть.
3. Заголовки из `authResponseHeaders` (например, `Remote-User`) прокидываются в бэкенд.

## Практические сценарии

### Сценарий 1: ForwardAuth на Authelia (File provider)

```yaml
http:
  middlewares:
    auth-ss:
      forwardAuth:
        address: "http://authelia:9091/api/verify?rd=https://auth.example.com"
        trustForwardHeader: true
        authResponseHeaders:
          - Remote-User
          - Remote-Groups
          - Remote-Email
    chain-protected:
      chain:
        middlewares:
          - default-headers
          - auth-ss

  routers:
    app:
      rule: "Host(`app.example.com`)"
      service: app-service
      entryPoints: [websecure]
      middlewares:
        - chain-protected
```

Примечание: `trustForwardHeader` — управляемый флаг (используйте осознанно); более надежно «доверие» конфигурируется через `forwardedHeaders.trustedIPs` на entrypoint.

### Сценарий 2: BasicAuth (File provider, BCrypt)

```yaml
http:
  middlewares:
    admin-auth:
      basicAuth:
        usersFile: /etc/traefik/auth/users.htpasswd
        removeHeader: true
```

Генерация хеша:

```bash
htpasswd -nbBC 10 admin "StrongPass!"
# → admin:$2y$10$...
```

### Сценарий 3: IPAllowList с неразглашением

```yaml
http:
  middlewares:
    office-only:
      ipAllowList:
        sourceRange:
          - "192.168.1.0/24"
          - "10.0.0.0/8"
        rejectStatusCode: 404   # скрываем факт существования ресурса
```

### Сценарий 4: Дайджест-аутентификация

```yaml
http:
  middlewares:
    dig-auth:
      digestAuth:
        usersFile: /etc/traefik/auth/users.htdigest
        realm: "example"
```

### Сценарий 5: Безопасные заголовки и CORS

```yaml
http:
  middlewares:
    secure-headers:
      headers:
        contentTypeNosniff: true
        frameDeny: true
        browserXssFilter: true
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        contentSecurityPolicy: "default-src 'self'; frame-ancestors 'none';"
        referrerPolicy: "strict-origin-when-cross-origin"
        permissionsPolicy: "geolocation=(), microphone=()"
    cors-api:
      headers:
        accessControlAllowOriginList:
          - "https://spa.example.com"
        accessControlAllowMethods:
          - GET
          - POST
          - OPTIONS
        accessControlAllowHeaders:
          - Content-Type
          - Authorization
        accessControlMaxAge: 100
        addVaryHeader: true
```

Важно (v3): `sslRedirect`, `sslTemporaryRedirect`, `featurePolicy` **удалены**; HTTP→HTTPS делайте через `redirections.entryPoint` или `redirectScheme`. OPTIONS-preflight при настроенных CORS-заголовках Traefik отвечает сам, без обращения к бэкенду.

### Сценарий 6: Передача клиентского сертификата (mTLS)

```yaml
http:
  middlewares:
    pass-cert:
      passTLSClientCert:
        info:
          subject:
            commonName: true
          serialNumber: true
```

Требуется настроенный `clientAuth` в TLS-options на роутере (см. [TLS Options](./traefik-tls-options.md)). Подсистема требует осторожности с размером заголовка — предпочитайте `info` вместо полного `pem`.

### Сценарий 7: Верификация вебхуков (HMAC/Signature)

Traefik не имеет встроенного middleware для проверки HMAC-подписи входящих вебхуков. Паттерн — **ForwardAuth** с внешним валидатором или **плагин**.

Паттерн A: ForwardAuth-микросервис

```yaml
services:
  webhook-validator:
    image: webhook-validator:latest
    environment:
      - HMAC_SECRET=${HMAC_SECRET}
      - EXPECTED_SIGNATURE_HEADER=X-Hub-Signature-256
    networks: [edge]

  traefik:
    # ...
    labels:
      - "traefik.http.routers.webhook.middlewares=webhook-auth@docker"
      - "traefik.http.middlewares.webhook-auth.forwardauth.address=http://webhook-validator:8080/validate"
      - "traefik.http.middlewares.webhook-auth.forwardauth.authResponseHeaders=X-Webhook-Valid"
```

Логика валидатора:
1. Считывает сырое тело запроса (не form-parsed).
2. Вычисляет HMAC-SHA256(secret, body).
3. Сравнивает с заголовком `X-Hub-Signature-256`.
4. Возвращает `200` (валид) или `401` (невалид).

Паттерн B: Community-плагин (Traefik Pilot / custom plugin)

```yaml
experimental:
  plugins:
    hmac-validator:
      modulename: github.com/org/traefik-hmac-plugin
      version: v0.1.0

http:
  middlewares:
    hmac-check:
      plugin:
        hmac-validator:
          secret: "${HMAC_SECRET}"
          header: "X-Hub-Signature-256"
          algorithm: "sha256"
```

Важно:
- **Сырое тело:** Traefik по умолчанию не дает middleware доступ к сырому телу до его парсинга. ForwardAuth-сервис должен принимать `Transfer-Encoding: chunked` и читать `req.Body` без ограничений.
- **Replay attacks:** добавляйте `X-Webhook-Timestamp` и отклоняйте запросы с временным смещением > 5 минут.
- **Content-Type:** для JSON-вебхуков валидируйте `Content-Type: application/json` до проверки подписи.

Паттерн C: GitHub/GitLab вебхуки (частный случай)

```yaml
http:
  middlewares:
    github-hmac:
      plugin:
        hmac-validator:
          secret: "${GITHUB_WEBHOOK_SECRET}"
          header: "X-Hub-Signature-256"
          algorithm: "sha256"
```

Для GitLab замените заголовок на `X-Gitlab-Token` (проще, но менее безопасно, чем HMAC).

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **401 на все запросы** | Неверный формат хеша/реестра (`users` vs `usersFile`) | Проверьте формат htpasswd и права файла |
| **RateLimit/IPAllowList блокируют всех** | `sourceCriterion` без `depth`, нет `trustedIPs` | Настройте entrypoint и `ipStrategy.depth` |
| **ForwardAuth никогда не пускает** | Auth-сервис отвечает не-2xx или недоступен из сети Traefik | Проверьте `address`, сетевую доступность, DNS |
| **CORS-preflight падает** | Не настроены `accessControlAllowMethods/Headers` | Укажите методы/заголовки; OPTIONS отвечает Traefik |
| **Заголовки безопасности не появляются** | Меiddleware не привязан к роутеру (или привязан к service, а не router) | Проверьте цепочку на роутере |

## Рекомендации

- Минимум для публичного администрирования: `IPAllowList → RateLimit → Auth` в одном `chain`.
- Пароли храните только в хешах; `usersFile` с правами чтения для процесса Traefik; в Docker — через secrets/файл, не в labels.
- ForwardAuth предпочтительнее, если уже есть SSO/LDAP/OIDC: лучше делегировать проверку, чем дублировать пароли.
- Держите `rejectStatusCode: 404` для внутренних админок при неразглашении.
- Проверяйте отсутствие утечки `Authorization` в бэкенд (BasicAuth `removeHeader: true`), если бэкенд не должен его видеть.

## Дополнительная информация

- [BasicAuth в Traefik + Kubernetes](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md) — генерация хешей, Secrets, CRD.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, InFlightReq, CircuitBreaker.
- [Обзор Traefik](./traefik_overview.md) — полная таблица middleware.
- [TLS Options и mTLS](./traefik-tls-options.md) — клиентские сертификаты.