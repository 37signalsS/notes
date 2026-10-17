# Middleware для безопасности и аутентификации

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6; с замечаниями по миграции с v2.x)

## Определения

**BasicAuth** — middleware базовой HTTP-аутентификации (RFC 7617). Клиент передает учетные данные в заголовке `Authorization: Basic <base64>`. Traefik сопоставляет их с хешами пользователей из файла формата `htpasswd` (поддерживаются алгоритмы MD5/apr1, BCrypt и Argon2id).

**DigestAuth** — middleware дайджест-аутентификации (RFC 7616 / RFC 2617). В отличие от BasicAuth, учетные данные не передаются в открытом виде (даже в Base64): клиент вычисляет MD5-хеш от комбинации логина, realm, пароля, nonce сервера и метода запроса. Сверяется с базой пользователей `htdigest`.

**ForwardAuth** — middleware делегирования аутентификации внешнему HTTP-сервису (Authelia, Authentik, Casdoor, OAuth2 Proxy). Для каждого входящего запроса Traefik выполняет фоновый субзапрос на указанный адрес (`address`). Доступ разрешается только при коде ответа `2xx`; любые иные ответы (401, 403, 302) транслируются клиенту.

**IPAllowList** — middleware фильтрации входящего трафика по белым спискам IP-адресов и подсетей (CIDR). В Traefik v3 пришло на смену устаревшему `ipWhiteList`. Поддерживает явное задание алгоритма поиска клиентского IP (`ipStrategy`) и переопределение кода ошибки (`rejectStatusCode`).

**Headers** — middleware модификации HTTP-заголовков запроса и ответа. Включает комплексный механизм безопасности: принудительный HSTS, политики встраивания фреймов (`X-Frame-Options` / CSP `frame-ancestors`), изоляцию типов контента (`X-Content-Type-Options`), реферера (`Referrer-Policy`), ограничение возможностей браузера (`Permissions-Policy`) и встроенный CORS-обработчик preflight-запросов (OPTIONS).

**PassTLSClientCert** — middleware извлечения информации о клиентском сертификате взаимной TLS-аутентификации (mTLS) и передачи её бэкенд-сервису в HTTP-заголовках (`X-Forwarded-Tls-Client-Cert` или `X-Forwarded-Tls-Client-Cert-Info`).

**Chain** — middleware агрегации, объединяющий несколько независимых middleware в именованную последовательную цепочку для переиспользования на нескольких роутерах.

**ipStrategy** — механизм определения реального клиентского IP-адреса из цепочки заголовка `X-Forwarded-For`. Регулируется параметрами глубины (`depth`) или списком исключаемых доверенных узлов (`excludedIPs`).

## Базовые концепции

### 1. Архитектура конвейера (Pipeline) и порядок middleware

В архитектуре Traefik каждый роутер пропускает входящий HTTP-запрос через упорядоченный конвейер middleware. Запрос проходит цепочку сверху вниз до бэкенда, а HTTP-ответ возвращается снизу вверх:

```
[Клиентский запрос]
         │
         ▼
[Входная точка: EntryPoint]
         │
         ▼
[Роутер: Router Rules]
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Middleware Chain (L7)                      │
│                                                             │
│ 1. IPAllowList ───────► (Не в CIDR? → 403/404, STOP)       │
│         │                                                   │
│ 2. RateLimit ─────────► (Превышен лимит? → 429, STOP)       │
│         │                                                   │
│ 3. Auth (Basic/Fwd) ──► (Не авторизован? → 401/302, STOP)   │
│         │                                                   │
│ 4. Headers (Sec/CORS) ─► Добавление/проверка заголовков    │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
[Бэкенд-сервис: Service / LoadBalancer]
         │
         ▼
[Клиентский ответ (с заголовками ответа Headers middleware)]
```

**Критическое правило безопасности:** проверки должны следовать от «вычислительно дешевых» к «дорогим»:
1. `IPAllowList` отсекает неавторизованные сетевые сегменты на раннем этапе без расхода CPU на парсинг криптографии или отправку сетевых пакетов.
2. `RateLimit` защищает контроллеры аутентификации от атак полного перебора (brute-force) и распределенного отказа в обслуживании (DDoS).
3. `BasicAuth` / `DigestAuth` / `ForwardAuth` выполняют проверку учетных данных (вычисление ресурсоемких хешей BCrypt/Argon2 либо сетевой субзапрос к внешнему IdP).
4. `Headers` добавляет защитные флаги и регулирует политику передачи контекста бэкендам.

Нарушение порядка (например, `BasicAuth` перед `RateLimit`) делает возможной атаку исчерпания CPU на сервер Traefik путем массовой отправки некорректных паролей BCrypt/Argon2.

### 2. Механизм работы ForwardAuth

`ForwardAuth` отделяет логику аутентификации от проксирования и бизнес-логики сервисов.

```
Клиент                 Traefik                    Auth Service (Authelia/OAuth2-Proxy)       Backend Service
  │                       │                                     │                                 │
  │── 1. GET /dashboard ─►│                                     │                                 │
  │                       │── 2. Субзапрос GET /verify ────────►│                                 │
  │                       │      (X-Forwarded-*, Cookie, Auth)  │                                 │
  │                       │                                     │                                 │
  │                       │◄── 3а. Ответ 200 OK ────────────────│                                 │
  │                       │        (Remote-User: admin)         │                                 │
  │                       │                                                                       │
  │                       │── 4. Запрос к бэкенду + Remote-User: admin ──────────────────────────►│
  │                       │◄── 5. Ответ 200 OK от бэкенда ────────────────────────────────────────│
  │◄── 6. Ответ клиенту ──│                                                                       │
  │                       │                                                                       │
  │                       │  (ИЛИ ЕСЛИ ОТВЕТ НЕ 2xx):                                             │
  │                       │◄── 3б. Ответ 401 Unauthorized / 302 Found (Redirect to IdP) ─────────│
  │◄── 4б. 302/401 ───────│   (Запрос к бэкенду НЕ отправляется)                                 │
```

**Протокол взаимодействия:**
1. Traefik пересылает во внешний сервис исходные метаданные через заголовки:
   - `X-Forwarded-Method`: метод HTTP (GET, POST и т.д.);
   - `X-Forwarded-Proto`: протокол (http или https);
   - `X-Forwarded-Host`: целевой хост запроса;
   - `X-Forwarded-Uri`: полный URI запроса с параметрами;
   - `X-Forwarded-For`: IP-адрес клиента.
2. Директива `authRequestHeaders` определяет, какие заголовки исходного клиента Traefik обязан скопировать в субзапрос (например, `Authorization`, `Cookie`, `X-Forwarded-Access-Token`).
3. При ответе внешнего сервиса со статусом `200..299`:
   - Traefik извлекает заголовки, перечисленные в `authResponseHeaders` (или подходящие под regex `authResponseHeadersRegex`), и инжектирует их в запрос, отправляемый на бэкенд.
   - Исходные заголовки клиента, совпадающие с именами из `authResponseHeaders`, принудительно перезаписываются значениями auth-сервиса, предотвращая инъекцию поддельного контекста пользователем.
4. При ответе со статусом, отличным от `2xx` (например, `401`, `403` или `302 Found` для перенаправления на веб-форму входа), Traefik прерывает обработку и отправляет клиенту полученный от auth-сервиса статус и заголовки (включая `Location` и `Set-Cookie`).

### 3. Определение реального IP в IPAllowList за балансировщиками

По умолчанию Traefik берет адрес непосредственного сетевого сокета `RemoteAddr`. Если перед Traefik расположен внешний L7-балансировщик нагрузки (HAProxy, Nginx, аппаратный ADC), значением `RemoteAddr` будет IP-адрес этого балансировщика.

Для корректной работы `IPAllowList` необходима комбинация двух настроек:
1. **На уровне EntryPoint (статическая конфигурация):** директива `forwardedHeaders.trustedIPs` объявляет CIDR вышестоящих прокси. Если входящий сокет не входит в этот список, заголовок `X-Forwarded-For` сбрасывается для предотвращения IP-спуфинга.
2. **На уровне Middleware (динамическая конфигурация):** секция `ipStrategy` определяет выбор IP из цепочки `X-Forwarded-For`:
   - `depth: N` — берет адрес с позиции $N$ с правого края цепочки. Если перед Traefik ровно один внешний доверенный прокси, используется `depth: 1`.
   - `excludedIPs: [...]` — Traefik просматривает заголовок справа налево, отбрасывая все адреса, входящие в указанные подсети, и выбирает первый адрес, не входящий в список исключений.

> **Отличие от матчера `ClientIP`:** Матчер роутера `ClientIP(...)` в Traefik v3 всегда проверяет исключительно физический адрес сокета TCP `RemoteAddr` и игнорирует L7-заголовки. Для фильтрации клиентов за L7-прокси необходимо применять именно middleware `IPAllowList` с настроенным `ipStrategy`.

### 4. mTLS и PassTLSClientCert

При включенной взаимной TLS-аутентификации (mTLS) Traefik валидирует сертификат клиента на этапе рукопожатия TLS, используя корневые сертификаты `caFiles` из настроек `tls.options`.

Middleware `passTLSClientCert` позволяет передать данные проверенного сертификата в бэкенд-сервис:
- **Режим PEM (`pem: true`):** Traefik передает полный сертификат в заголовке `X-Forwarded-Tls-Client-Cert` в формате URL-encoded PEM.
  *Риск:* сертификат формата X.509 в кодировке PEM занимает от 1.5 до 4 КБ. Это может приводить к ошибкам `431 Request Header Fields Too Large` или переполнению буферов бэкенд-серверов (Nginx `large_client_header_buffers`, Apache `LimitRequestFieldSize`).
- **Режим структурированных полей (`info: ...`):** Traefik передает в заголовке `X-Forwarded-Tls-Client-Cert-Info` только запрошенные атрибуты (Subject CN, SAN, SerialNumber, Issuer). Этот подход минимизирует размер заголовка и защищает от переполнения буфера.

### 5. Безопасные заголовки и CORS

Middleware `headers` в Traefik реализует защиту от типовых веб-уязвимостей:
- **HSTS (HTTP Strict Transport Security):** директивы `stsSeconds`, `stsIncludeSubdomains`, `stsPreload` сообщают браузеру о необходимости обращаться к домену исключительно по протоколу HTTPS.
- **X-Frame-Options и CSP frame-ancestors:** директива `frameDeny: true` отправляет `X-Frame-Options: DENY`, а `customFrameOptionsValue: "SAMEORIGIN"` позволяет открывать сайт во фреймах того же источника. В современных браузерах приоритет имеет директива `contentSecurityPolicy: "frame-ancestors 'self';"`.
- **MIME Sniffing:** `contentTypeNosniff: true` добавляет `X-Content-Type-Options: nosniff`.
- **CORS (Cross-Origin Resource Sharing):** при поступлении preflight-запроса `OPTIONS` Traefik самостоятельно формирует ответ `200/204` с заголовками `Access-Control-Allow-*`, не перегружая бэкенд вызовами preflight.

### 6. Изменения при переходе с Traefik v2 на v3

| Возможность | Синтаксис Traefik v2 | Синтаксис Traefik v3 | Примечания / Действие при миграции |
| :--- | :--- | :--- | :--- |
| **Белые списки IP** | `ipWhiteList` | `ipAllowList` | Поле `ipWhiteList` полностью удалено в v3 |
| **SSL-редирект** | `headers.sslRedirect: true` | Удалено из `headers` | Настраивается через `redirections.entryPoint` или middleware `redirectScheme` |
| **Временный SSL-редирект** | `headers.sslTemporaryRedirect` | Удалено | Удалено без прямой замены в `headers` |
| **Политика возможностей браузера** | `headers.featurePolicy` | `headers.permissionsPolicy` | Стандарт W3C Feature Policy заменен на Permissions Policy |
| **Хеширование паролей BasicAuth** | MD5, BCrypt | MD5, BCrypt, **Argon2id** | В Traefik v3 добавлена нативная поддержка `$argon2id$` |
| **Тело запроса в ForwardAuth** | Не поддерживалось | `forwardBody: true` | Позволяет пересылать тело входящего запроса auth-сервису |

## Практические сценарии

### Сценарий 1: Production BasicAuth с хешами Argon2/BCrypt и защитой от утечек (File Provider)

Конфигурация динамического файла `/etc/traefik/dynamic/auth-security.yml`. Заголовок `Authorization` удаляется перед проксированием в бэкенд (`removeHeader: true`), чтобы предотвратить компрометацию учетных данных Traefik внутренними сервисами.

```yaml
http:
  middlewares:
    # Защита от brute-force перебора паролей
    auth-rate-limit:
      rateLimit:
        average: 5
        period: 1m
        burst: 10
        sourceCriterion:
          ipStrategy:
            depth: 1

    # Базовая аутентификация по файлу htpasswd
    admin-basic-auth:
      basicAuth:
        realm: "Restricted Internal Zone"
        usersFile: /etc/traefik/auth/users.htpasswd
        removeHeader: true
        headerField: "X-Forwarded-User"

    # Объединенная защитная цепочка
    chain-admin-protected:
      chain:
        middlewares:
          - auth-rate-limit
          - admin-basic-auth

  routers:
    secured-service:
      rule: "Host(`service.example.local`)"
      entryPoints:
        - websecure
      service: internal-service
      middlewares:
        - chain-admin-protected
      tls: {}

  services:
    internal-service:
      loadBalancer:
        servers:
          - url: "http://10.10.20.15:8080"
```

### Сценарий 2: Комплексная интеграция ForwardAuth с Authelia / OAuth2-Proxy (Docker Compose)

Схема для боевого развертывания SSO на базе Docker Compose. Передаются учетные заголовки `Remote-User`, `Remote-Groups`, `Remote-Email`.

```yaml
services:
  traefik:
    image: traefik:v3.6
    restart: always
    command:
      - "--api.insecure=false"
      - "--api.dashboard=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.websecure.address=:443"
      # Доверяем внутреннему Docker bridge или внешнему прокси
      - "--entrypoints.websecure.forwardedheaders.trustedips=172.16.0.0/12,192.168.0.0/16"
    ports:
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./certs:/etc/traefik/certs:ro"
    networks:
      edge:
        ipv4_address: 172.28.0.2

  authelia:
    image: authelia/authelia:4.38
    restart: unless-stopped
    volumes:
      - "./authelia/config:/config"
    environment:
      - TZ=UTC
    networks:
      edge:
        ipv4_address: 172.28.0.10
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.auth.rule=Host(`auth.example.local`)"
      - "traefik.http.routers.auth.entrypoints=websecure"
      - "traefik.http.routers.auth.tls=true"
      - "traefik.http.services.auth.loadbalancer.server.port=9091"

  internal-app:
    image: containous/whoami:v1.5.0
    restart: unless-stopped
    networks:
      edge:
        ipv4_address: 172.28.0.20
    labels:
      - "traefik.enable=true"
      # Определение middleware ForwardAuth
      - "traefik.http.middlewares.sso-auth.forwardauth.address=http://172.28.0.10:9091/api/verify?rd=https://auth.example.local/"
      - "traefik.http.middlewares.sso-auth.forwardauth.trustforwardheader=true"
      - "traefik.http.middlewares.sso-auth.forwardauth.authresponseheaders=Remote-User,Remote-Groups,Remote-Name,Remote-Email"
      
      # Применение middleware к роутеру приложения
      - "traefik.http.routers.internal-app.rule=Host(`app.example.local`)"
      - "traefik.http.routers.internal-app.entrypoints=websecure"
      - "traefik.http.routers.internal-app.tls=true"
      - "traefik.http.routers.internal-app.middlewares=sso-auth"
      - "traefik.http.services.internal-app.loadbalancer.server.port=80"

networks:
  edge:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

### Сценарий 3: Защита админки через IPAllowList со скрытием ресурса (404 Not Found)

Ограничение доступа к закрытой инфраструктуре (Prometheus, Dashboard, phpMyAdmin). Если адрес не входит в доверенную офисную сеть или VPN, Traefik возвращает `404 Not Found` вместо стандартного `403 Forbidden`, маскируя само наличие маршрутизатора для сканеров периметра.

```yaml
http:
  middlewares:
    internal-ip-filter:
      ipAllowList:
        sourceRange:
          - "192.168.10.0/24"  # Офисный VPN
          - "10.50.0.0/16"     # Сегмент серверов управления
          - "127.0.0.1/32"
        # 404 скрывает ресурс от атакующего, создавая иллюзию отсутствия эндпоинта
        rejectStatusCode: 404
        ipStrategy:
          # Анализируем 1 промежуточный прокси (глубина 1)
          depth: 1

  routers:
    admin-dashboard:
      rule: "Host(`traefik-admin.corp.local`)"
      entryPoints:
        - websecure
      middlewares:
        - internal-ip-filter
      service: api@internal
      tls: {}
```

### Сценарий 4: DigestAuth для изолированных окружений без HTTPS-терминации

Применяется в изолированных технологических L2/L3-сетях (SCADA, IoT, legacy industrial LAN), где оконечные устройства не поддерживают TLS-сертификаты, но открытая передача паролей в Base64 недопустима.

```yaml
http:
  middlewares:
    scada-digest-auth:
      digestAuth:
        realm: "Industrial Controller Gate"
        usersFile: /etc/traefik/auth/users.htdigest
        removeHeader: true

  routers:
    telemetry-router:
      rule: "Host(`telemetry.plant.local`) && PathPrefix(`/metrics`)"
      entryPoints:
        - web
      middlewares:
        - scada-digest-auth
      service: telemetry-service

  services:
    telemetry-service:
      loadBalancer:
        servers:
          - url: "http://10.200.1.50:8000"
```

### Сценарий 5: Комплексные безопасные заголовки (Security Headers) и строгий CORS

Стандартный профиль hardening для веб-сервисов, соответствующий рекомендациям OWASP и требованиям стандартов ИБ.

```yaml
http:
  middlewares:
    hardening-headers:
      headers:
        # HSTS (2 года, все поддомены, готовность к preload списку браузеров)
        stsSeconds: 63072000
        stsIncludeSubdomains: true
        stsPreload: true
        forceSTSHeader: true

        # Защита от MIME-sniffing
        contentTypeNosniff: true

        # Защита от Clickjacking
        frameDeny: true
        customFrameOptionsValue: "DENY"

        # Content Security Policy (запрет небезопасных скриптов и встраивания во фреймы)
        contentSecurityPolicy: "default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';"

        # Контроль передачи заголовка Referer
        referrerPolicy: "strict-origin-when-cross-origin"

        # Отключение аппаратных API браузера на уровне периметра
        permissionsPolicy: "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

        # Защита от отраженного XSS (устаревающий заголовок, сохраняется для совместимости)
        browserXssFilter: true

    cors-strict:
      headers:
        accessControlAllowMethods:
          - GET
          - POST
          - PUT
          - DELETE
          - OPTIONS
        accessControlAllowHeaders:
          - Content-Type
          - Authorization
          - X-Requested-With
        accessControlAllowOriginList:
          - "https://portal.example.local"
        accessControlAllowCredentials: true
        accessControlMaxAge: 86400
        addVaryHeader: true
```

### Сценарий 6: Проброс клиентского сертификата mTLS (PassTLSClientCert) в бэкенд

Передача удостоверения клиента в backend-приложение при взаимной TLS-аутентификации. Вместо тяжелого PEM-блока передается компактный URL-encoded заголовок `X-Forwarded-Tls-Client-Cert-Info` с атрибутами `Subject.CommonName` и `SerialNumber`.

```yaml
# 1. Определение параметров TLS на уровне статической/динамической конфигурации
tls:
  options:
    mtls-strict:
      minVersion: VersionTLS13
      clientAuth:
        caFiles:
          - /etc/traefik/certs/corporate-pki-root-ca.crt
        clientAuthType: RequireAndVerifyClientCert

# 2. Динамическая маршрутизация и middleware
http:
  middlewares:
    extract-client-cert:
      passTLSClientCert:
        info:
          notAfter: true
          serialNumber: true
          subject:
            commonName: true
            organization: true
            organizationalUnit: true

  routers:
    b2b-gateway:
      rule: "Host(`b2b-api.example.local`)"
      entryPoints:
        - websecure
      tls:
        options: mtls-strict
      middlewares:
        - extract-client-cert
      service: b2b-service

  services:
    b2b-service:
      loadBalancer:
        servers:
          - url: "http://10.10.40.100:5000"
```

### Сценарий 7: Валидация подписи входящих вебхуков (HMAC) через ForwardAuth с `forwardBody`

В Traefik v3 появилась возможность передавать тело входящего запроса во внешний валидатор через директиву `forwardBody: true`. Это позволяет валидировать криптографические подписи (HMAC-SHA256) вебхуков от сторонних сервисов без развертывания сторонних плагинов.

```yaml
http:
  middlewares:
    webhook-hmac-auth:
      forwardAuth:
        address: "http://127.0.0.1:9095/validate-signature"
        trustForwardHeader: true
        authRequestHeaders:
          - "X-Hub-Signature-256"
          - "X-Webhook-Timestamp"
          - "Content-Type"
        # Включение пересылки тела запроса в Traefik v3
        forwardBody: true
        maxBodySize: 1048576  # 1 MB лимит на размер тела субзапроса

  routers:
    webhook-receiver:
      rule: "Host(`ci-hooks.example.local`) && Path(`/incoming`)"
      entryPoints:
        - websecure
      middlewares:
        - webhook-hmac-auth
      service: ci-processor
      tls: {}

  services:
    ci-processor:
      loadBalancer:
        servers:
          - url: "http://10.10.50.80:8080"
```

### Сценарий 8: Композиция модульных политик безопасности через Chain Middleware

Объединение разнородных политик безопасности в единый профиль для роутеров публичных и внутренних зон:

```yaml
http:
  middlewares:
    # Базовые атомарные фильтры
    filter-public-ip:
      ipAllowList:
        sourceRange:
          - "10.0.0.0/8"
          - "172.16.0.0/12"
          - "192.168.0.0/16"

    limit-requests:
      rateLimit:
        average: 20
        burst: 40

    sec-headers:
      headers:
        stsSeconds: 31536000
        contentTypeNosniff: true
        frameDeny: true

    auth-ldap:
      forwardAuth:
        address: "http://authentik.corp.local:9000/outpost.goauthentik.io/auth/traefik"
        trustForwardHeader: true
        authResponseHeaders:
          - "X-authentik-username"
          - "X-authentik-groups"

    # Именованная цепочка полного контура безопасности
    enterprise-security-chain:
      chain:
        middlewares:
          - filter-public-ip
          - limit-requests
          - auth-ldap
          - sec-headers

  routers:
    production-app:
      rule: "Host(`portal.corp.local`)"
      entryPoints: [websecure]
      middlewares:
        - enterprise-security-chain
      service: portal-service
      tls: {}

  services:
    portal-service:
      loadBalancer:
        servers:
          - url: "http://10.10.10.50:80"
```

## Операции и команды

### 1. Генерация и управление хешами учетных записей

Генерация хешей BCrypt (рекомендуется для Traefik v2/v3):

```bash
# Генерация учетной записи с алгоритмом BCrypt (-B) и фактором сложности 12 (-C 12)
htpasswd -nbB -C 12 devops_admin "SecureMasterP@ssw0rd!"
# → devops_admin:$2y$12$N7Q8ZcZfJ2tq1R...
```

Генерация хешей Argon2id (наиболее криптостойкий стандарт, поддерживаемый в Traefik v3):

```bash
# Генерация хеша Argon2id через Python-модуль argon2-cffi
python3 -c 'import sys; from argon2 import PasswordHasher; ph = PasswordHasher(); print(f"sysadmin:{ph.hash(sys.argv[1])}")' "UltraSecret2026!"
# → sysadmin:$argon2id$v=19$m=65536,t=3,p=4$qF3...$w8Z...
```

Создание базы учетных записей для DigestAuth:

```bash
# Создание нового файла htdigest с realm "Restricted Internal Zone"
htdigest -c /etc/traefik/auth/users.htdigest "Restricted Internal Zone" operator
# → Adding password for operator in realm Restricted Internal Zone.
# → New password: **********
# → Re-type new password: **********
```

Проверка прав доступа к файлу секретов (процесс Traefik должен иметь доступ только на чтение):

```bash
sudo chown -R traefik:traefik /etc/traefik/auth
sudo chmod 600 /etc/traefik/auth/users.htpasswd
ls -la /etc/traefik/auth/users.htpasswd
# → -rw------- 1 traefik traefik 118 Oct 17 12:00 /etc/traefik/auth/users.htpasswd
```

### 2. Валидация работы BasicAuth и очистки заголовков

Проверка отказа при отсутствии учетных данных (ожидается статус 401 и заголовок WWW-Authenticate):

```bash
curl -sv -o /dev/null https://service.example.local/ 2>&1 | grep -E "(< HTTP|< WWW-Authenticate)"
# → < HTTP/2 401
# → < www-authenticate: Basic realm="Restricted Internal Zone"
```

Проверка успешного входа по BasicAuth:

```bash
curl -sv -u devops_admin:"SecureMasterP@ssw0rd!" https://service.example.local/ 2>&1 | grep "< HTTP"
# → < HTTP/2 200
```

Проверка, что middleware удаляет заголовок `Authorization` перед передачей на бэкенд (`removeHeader: true`):

```bash
# Тестовый запрос на сервис эхо-заголовков (containous/whoami)
curl -s -u devops_admin:"SecureMasterP@ssw0rd!" https://service.example.local/ | grep -i "authorization"
# → (пустой вывод; заголовок Authorization успешно вырезан)
```

### 3. Тестирование и аудит ForwardAuth

Проверка неавторизованного запроса к защищенному маршруту (ожидается перенаправление 302 на страницу входа SSO):

```bash
curl -sI https://app.example.local/ | grep -E "(HTTP/|location)"
# → HTTP/2 302
# → location: https://auth.example.local/?rd=https%3A%2F%2Fapp.example.local%2F
```

Проверка валидированной сессии с передачей cookie аутентификации:

```bash
curl -sI -b "authelia_session=a8f9c1b2e3d4..." https://app.example.local/ | grep "HTTP/"
# → HTTP/2 200
```

### 4. Проверка фильтрации IPAllowList и защиты от спуфинга

Проверка отклонения неавторизованного IP-адреса:

```bash
curl -sv -o /dev/null https://traefik-admin.corp.local/ 2>&1 | grep "< HTTP"
# → < HTTP/2 404
```

Проверка симуляции клиентского адреса через `X-Forwarded-For` при наличии внешнего доверенного балансировщика:

```bash
# Отправка запроса с подделкой заголовка от узла, не входящего в trustedIPs
curl -sv -H "X-Forwarded-For: 192.168.10.50" https://traefik-admin.corp.local/ 2>&1 | grep "< HTTP"
# → < HTTP/2 404
```

### 5. Аудит безопасных заголовков и CORS Preflight

Проверка применения полного профиля безопасности HTTP:

```bash
curl -sI https://service.example.local/ | grep -E -i "(strict-transport|content-security|x-frame|x-content-type|referrer-policy|permissions-policy)"
# → strict-transport-security: max-age=63072000; includeSubDomains; preload
# → x-content-type-options: nosniff
# → x-frame-options: DENY
# → content-security-policy: default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';
# → referrer-policy: strict-origin-when-cross-origin
# → permissions-policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
```

Тестирование preflight-запроса CORS (OPTIONS):

```bash
curl -s -X OPTIONS https://service.example.local/api/data \
  -H "Origin: https://portal.example.local" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type,Authorization" -I | grep -E "HTTP/|access-control-"
# → HTTP/2 200
# → access-control-allow-origin: https://portal.example.local
# → access-control-allow-methods: GET,POST,PUT,DELETE,OPTIONS
# → access-control-allow-headers: Content-Type,Authorization,X-Requested-With
# → access-control-allow-credentials: true
# → access-control-max-age: 86400
```

### 6. Диагностика состояния middleware через Traefik API

Запрос текущего состояния динамических middleware через локальный административный эндпоинт:

```bash
curl -s http://127.0.0.1:8080/api/http/middlewares | jq '.[] | select(.status == "enabled") | {name: .name, type: .type, provider: .provider}'
# → {
# →   "name": "admin-basic-auth@file",
# →   "type": "basicauth",
# →   "provider": "file"
# → }
# → {
# →   "name": "internal-ip-filter@file",
# →   "type": "ipallowlist",
# →   "provider": "file"
# → }
```

Детальный осмотр конфигурации конкретного middleware:

```bash
curl -s http://127.0.0.1:8080/api/http/middlewares/admin-basic-auth@file | jq .
# → {
# →   "basicAuth": {
# →     "realm": "Restricted Internal Zone",
# →     "removeHeader": true,
# →     "headerField": "X-Forwarded-User"
# →   },
# →   "status": "enabled",
# →   "usedBy": [
# →     "chain-admin-protected@file"
# →   ]
# → }
```

## Устранение неисправностей

| Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **HTTP 401 на любые корректные логины/пароли** | Несовпадение формата хеша в `usersFile` либо права доступа процесса Traefik к файлу | `traefik log` содержит: `error reading users file` или `password does not match` | Проверить права `chmod 600`, убедиться, что файл доступен пользователю `traefik`, перегенерировать хеш через `htpasswd -B` |
| **IPAllowList возвращает 403/404 всем легитимным клиентам** | Traefik видит IP-адрес промежуточного балансировщика, а не клиента; отсутствует `forwardedHeaders.trustedIPs` | `curl -s http://traefik:8080/api/rawdata` или анализ `X-Forwarded-For` в access-log | Настроить на EntryPoint `forwardedHeaders.trustedIPs` с CIDR вышестоящего LB и добавить в middleware `ipStrategy.depth: 1` |
| **IP-спуфинг: клиент обходит IPAllowList поддельным заголовком** | Не настроен `trustedIPs` на EntryPoint, Traefik слепо доверяет внешнему `X-Forwarded-For` | `curl -H "X-Forwarded-For: 127.0.0.1"` разрешает доступ из публичной сети | Жестко ограничить `forwardedHeaders.trustedIPs` только фактическими адресами внутренних балансировщиков |
| **ForwardAuth: циклическая переадресация (Redirect Loop)** | Роутер самого auth-сервиса (Authelia) ошибочно обернут в middleware `ForwardAuth` | `curl -sIL https://app.example.local` показывает бесконечные 302-редиректы на один URL | Убедиться, что роутер домена аутентификации (`auth.example.local`) не содержит middleware `ForwardAuth` |
| **ForwardAuth возвращает 500 Internal Server Error** | Сетевая недоступность эндпоинта аутентификации, ошибка DNS или невалидный TLS-сертификат IdP | В логах Traefik: `error while forwarding auth request: dial tcp: lookup auth-service: no such host` | Проверить IP/DNS-резолвинг auth-сервиса, маршрутизацию между Docker-сетями, при HTTPS настроить секцию `forwardAuth.tls` |
| **Бэкенд не видит пользователя из ForwardAuth** | Заголовки ответа не добавлены в список `authResponseHeaders` | Логирование заголовков бэкенда показывает отсутствие `Remote-User` / `X-Auth-Request-User` | Добавить имя заголовка в массив `forwardAuth.authResponseHeaders` (например, `Remote-User`, `X-authentik-username`) |
| **CORS Preflight возвращает 404 или 403 на OPTIONS** | Запросы OPTIONS перехватываются роутером без CORS middleware или не настроены допустимые методы | `curl -X OPTIONS ... -I` возвращает 404/403 вместо 200/204 | Добавить `OPTIONS` в `accessControlAllowMethods` и убедиться, что middleware `headers` привязано к целевому роутеру |
| **PassTLSClientCert: ошибка HTTP 431 Request Header Fields Too Large** | Использование `pem: true` передает полный сертификат > 2-4 КБ, переполняя буфер бэкенда | В логах Nginx/Apache за Traefik: `431 Request Header Fields Too Large` или `client sent too long header` | Переключить middleware с `pem: true` на структурированный вывод `info` либо увеличить `large_client_header_buffers` на бэкенде |
| **Конфигурация отвергается в Traefik v3: `field not found`** | Использование устаревших директив v2: `ipWhiteList`, `sslRedirect`, `featurePolicy` | В логах: `field not found, node: ipWhiteList` | Заменить `ipWhiteList` на `ipAllowList`, перенести редирект HTTPS в EntryPoint, заменить `featurePolicy` на `permissionsPolicy` |

## Рекомендации

1. **Эшелонированная оборона (Defense in Depth):** Для закрытых административных интерфейсов (Traefik Dashboard, Vault UI, мониторинг) всегда объединяйте три рубежа защиты в цепочку (`chain`):
   $$\text{IPAllowList} \longrightarrow \text{RateLimit} \longrightarrow \text{BasicAuth / ForwardAuth}$$
2. **Гигиена учетных данных:**
   - Категорически избегайте хранения открытых паролей или устаревших хешей MD5 (`apr1`).
   - Используйте алгоритм **BCrypt** (`htpasswd -B -C 12`) как общепринятый стандарт или **Argon2id** для новых систем на базе Traefik v3.
   - Всегда активируйте `removeHeader: true` в `basicAuth` и `digestAuth`, если внутренний бэкенд не требует сквозного заголовка `Authorization`.
   - Файлы секретов (`usersFile`) должны монтироваться в режиме Read-Only с правами доступа `0600` или `0400`.
3. **Безопасная архитектура ForwardAuth:**
   - Не передавайте пароли через query-параметры.
   - Используйте `authRequestHeaders` для строгого ограничения заголовков, передаваемых во внешнюю систему.
   - Защищайте канал связи между Traefik и сервисом аутентификации (внутренняя изолированная сеть или взаимный mTLS через `forwardAuth.tls`).
4. **Контроль утечки метаданных периметра:**
   - Настраивайте `rejectStatusCode: 404` в `ipAllowList` для внутренних административных интерфейсов, чтобы предотвратить сканирование и идентификацию сетевых ресурсов.
   - Включайте `stsPreload` и `stsIncludeSubdomains` только после всесторонней проверки работоспособности всех поддоменов по протоколу HTTPS.
   - При использовании `passTLSClientCert` отдавайте предпочтение структурированному блоку `info` вместо громоздкого `pem`, чтобы избежать переполнения буферов заголовков L7-прокси.
5. **Мониторинг метрик безопасности:**
   - Отслеживайте всплески кодов `401 Unauthorized` (признак подбора паролей к BasicAuth), `403 Forbidden` / `404 Not Found` (срабатывание IPAllowList) и `429 Too Many Requests` (срабатывание RateLimit) через Prometheus-метрику `traefik_service_requests_total{code=~"401|403|429"}`.

## Дополнительная информация

- [Обзор архитектуры Traefik](./traefik_overview.md) — сводная таблица всех middleware и базовые принципы маршрутизации.
- [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md) — исчерпывающее руководство по `forwardedHeaders.trustedIPs`, PROXY protocol и предотвращению IP-спуфинга.
- [TLS Options и mTLS](./traefik-tls-options.md) — настройка шифров, протоколов TLS 1.3 и клиентских CA для взаимной аутентификации.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — параметры `RateLimit`, `InFlightReq` и `CircuitBreaker`.
- [Интеграция Traefik с OIDC и OAuth2 Proxy](./traefik-oidc-auth.md) — детальное развертывание SSO и PKCE через внешний прокси.
- [Hardening безопасности Traefik](./traefik-security-hardening.md) — рекомендации по защите от атак OWASP Top-10 и изоляции Docker Socket.
- [Traefik и CrowdSec WAF](./traefik-edge-security-waf.md) — интеграция межсетевого экрана уровня приложений (AppSec WAF) и блокировка атакующих IP.
- [BasicAuth в Traefik + Kubernetes](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md) — генерация хешей, работа с Kubernetes Secrets и IngressRoute CRD.