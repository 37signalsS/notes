# Обзор Traefik

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6)

## Определения

**Traefik** — современный обратный прокси-сервер (reverse proxy) и балансировщик нагрузки с открытым исходным кодом, ориентированный на микросервисную архитектуру и динамическую инфраструктуру. Написан на языке Go, поставляется в виде одного статического бинарного файла или минималистичного контейнера. В автономных и локальных инфраструктурах (on-premise, bare-metal, private cloud) функционирует полностью независимо, без привязки к внешним SaaS-платформам.

**Статическая конфигурация (Static Configuration)** — параметры инициализации ядра Traefik, задаваемые при старте процесса. Определяет сетевые слушатели (Entrypoints), активные провайдеры (Providers), параметры ACME-резолверов, глобальные таймауты, форматы логов и экспортеры метрик. Не может быть изменена во время работы без перезапуска процесса.

**Динамическая конфигурация (Dynamic Configuration)** — правила маршрутизации входящего трафика (Routers, Middlewares, Services, TLS Options). Загружается и непрерывно обновляется провайдерами «на лету» без прерывания активных сетевых соединений и без перезагрузки процесса Traefik.

**Провайдеры (Providers)** — программные модули обнаружения инфраструктуры. Опрашивают API целевых платформ (Docker engine, Kubernetes API, HashiCorp Nomad, Consul, локальная файловая система) и автоматически транслируют обнаруженные сервисы в динамическую конфигурацию Traefik.

**Точки входа (Entrypoints)** — сетевые слушатели Traefik (порты TCP/UDP), принимающие входящие пакеты из внешней сети. На уровне Entrypoint настраиваются таймауты L4/L7, буферы, поддержка HTTP/3 (QUIC), PROXY Protocol и цепочки глобальных middleware.

**Роутеры (Routers)** — логические правила сопоставления входящих запросов. Анализируют атрибуты пакета (домен, путь, HTTP-метод, заголовки, SNI) и направляют подходящий трафик в соответствующий сервис.

**Промежуточные обработчики (Middlewares)** — цепочки модификаторов запроса и ответа. Выполняются до передачи запроса бэкенду (аутентификация, ограничение частоты запросов, добавление/удаление заголовков, перенаправление) или перед возвратом ответа клиенту (сжатие, кастомные страницы ошибок).

**Сервисы (Services)** — абстракция над целевыми серверами (бэкендами). Отвечают за алгоритм распределения нагрузки между физическими или контейнерными экземплярами, проверку их доступности (Health Check) и фиксацию сессий (Sticky Sessions).

**ServersTransport** — низкоуровневая конфигурация сетевого взаимодействия между Traefik и вышестоящими бэкендами. Управляет пулом постоянных соединений (HTTP Keep-Alive), таймаутами проксирования, проверкой TLS-сертификатов бэкендов и взаимной аутентификацией (mTLS / SPIFFE).

## Базовые концепции

### Архитектура и жизненный цикл запроса

Обработка каждого входящего сетевого пакета в Traefik v3 следует строгой конвейерной архитектуре:

```
[Входящий клиентский запрос]
              │
              ▼
    ┌───────────────────┐
    │    Entrypoint     │  (L4/L7 слушатель: :80, :443, :8080)
    └─────────┬─────────┘
              │ (Глобальные Middlewares точки входа)
              ▼
    ┌───────────────────┐
    │      Router       │  (Анализ правил: Host, Path, Headers, SNI)
    └─────────┬─────────┘
              │ (Middlewares роутера: Auth, RateLimit, Headers)
              ▼
    ┌───────────────────┐
    │      Service      │  (Балансировка: Round Robin, Weighted, Failover)
    └─────────┬─────────┘
              │ (Middlewares сервиса)
              ▼
    ┌───────────────────┐
    │  ServersTransport │  (TLS к бэкенду, Connection Pool, Timeouts)
    └─────────┬─────────┘
              │
              ▼
     [Серверы бэкенда]     (Физические хосты, Docker-контейнеры, Pods)
```

**Принцип работы конвейера:**
1. **Entrypoint** принимает TCP/UDP-соединение, декодирует протокол (HTTP/1.1, HTTP/2, HTTP/3, TLS passthrough) и применяет глобальные ограничения (например, `maxRequestBodyBytes`).
2. **Router** проверяет дерево правил (`rule`) для отбора целевого маршрута. Если несколько роутеров соответствуют запросу, выбирается роутер с наивысшим приоритетом (по умолчанию определяется длиной правила).
3. **Middlewares** последовательно трансформируют запрос. Если middleware безопасности (например, `BasicAuth` или `IPAllowList`) отклоняет запрос, цепочка прерывается, и Traefik сразу возвращает клиенту соответствующий код ответа (`401`, `403`).
4. **Service** распределяет валидный запрос между доступными серверами пула с учетом состояния проверок здоровья (Health Check) и весов.
5. **ServersTransport** отправляет запрос на целевой IP-адрес и порт бэкенда через переиспользуемое TCP-соединение из пула.

### Двухуровневая модель конфигурации

Traefik строго изолирует неизменяемые системные настройки от правил маршрутизации приложений.

#### 1. Статическая конфигурация

Определяет базовые параметры сетевого демона. Загружается исключительно при старте бинарного файла через конфигурационный файл (`traefik.yml`), переменные окружения (`TRAEFIK_*`) или CLI-флаги.

*Пример production-конфигурации (`/etc/traefik/traefik.yml`):*
```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

# Сетевые слушатели
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt
  metrics:
    address: ":8082"
  traefik:
    address: ":8080"

# Источники динамической конфигурации
providers:
  docker:
    endpoint: "tcp://127.0.0.1:2375" # Доступ через защищенный docker-socket-proxy
    exposedByDefault: false
    network: traefik_network
    watch: true
  file:
    directory: /etc/traefik/dynamic
    watch: true

# Автоматизация выпуска SSL/TLS (ACME)
certificatesResolvers:
  letsencrypt:
    acme:
      email: noc@example.internal
      storage: /etc/traefik/acme.json
      httpChallenge:
        entryPoint: web

# Внутренний API и веб-дашборд
api:
  dashboard: true
  insecure: false

# Эндпоинт проверки жизнеспособности демона
ping:
  entryPoint: traefik

# Экспорт метрик для Prometheus
metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addServicesLabels: true
    addRoutersLabels: true

# Системный журнал событий
log:
  level: INFO
  format: json

# Журнал доступа входящих запросов
accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  bufferingSize: 100
  filters:
    statusCodes:
      - "400-599"
```

#### 2. Динамическая конфигурация

Управляет маршрутами приложений. Поставляется провайдерами в реальном времени.

*Пример конфигурации файлового провайдера (`/etc/traefik/dynamic/routes.yml`):*
```yaml
http:
  routers:
    # Защищенный доступ к веб-интерфейсу Traefik Dashboard
    traefik-dashboard:
      rule: "Host(`traefik.example.internal`)"
      entryPoints:
        - traefik
      service: api@internal
      middlewares:
        - internal-auth

    # Маршрутизация производственного сервиса
    api-service:
      rule: "Host(`api.example.com`) && PathPrefix(`/v1`)"
      entryPoints:
        - websecure
      service: api-backend
      middlewares:
        - secure-headers
        - api-ratelimit
      tls:
        certResolver: letsencrypt

  middlewares:
    internal-auth:
      basicAuth:
        users:
          # Пароль сгенерирован через htpasswd -nB admin
          - "admin:$2y$05$59074Ndfw8QdGg0YpZqU..cZg26N7P00mJkYQkW2vX14Oa6K.2Wl6"

    secure-headers:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        forceSTSHeader: true
        contentTypeNosniff: true
        browserXssFilter: true
        customFrameOptionsValue: "DENY"

    api-ratelimit:
      rateLimit:
        average: 100
        burst: 50
        period: 1m

  services:
    api-backend:
      loadBalancer:
        healthCheck:
          path: /healthz
          interval: 10s
          timeout: 3s
        servers:
          - url: "http://192.168.10.11:8080"
          - url: "http://192.168.10.12:8080"
```

### Тонкая настройка Entrypoints

Entrypoint управляет жизненным циклом входящего TCP/UDP соединения, обработкой заголовков проксирования и параметрами мягкого завершения:

```yaml
entryPoints:
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt
      middlewares:
        - global-security-headers
      maxHeaderBytes: 8192
    transport:
      respondingTimeouts:
        readTimeout: 30s
        writeTimeout: 30s
        idleTimeout: 180s
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 15s
    proxyProtocol:
      trustedIPs:
        - "192.168.1.0/24"
        - "10.0.0.1"
    forwardedHeaders:
      trustedIPs:
        - "192.168.1.0/24"
    http3: {}
```

- `http.middlewares` — список middleware, принудительно выполняемых для **всех** роутеров, подключенных к этой точке входа, до выполнения роутер-специфичных правил.
- `transport.respondingTimeouts` — защита от атак типа Slowloris и утечек файловых дескрипторов (таймауты чтения заголовков, записи ответов и удержания keep-alive соединений).
- `transport.lifeCycle` — обеспечение плавного завершения работы (Graceful Shutdown) при получении сигналов `SIGTERM`/`SIGINT`. `requestAcceptGraceTimeout` позволяет добрать соединения из очереди сокета, а `graceTimeout` удерживает процесс до завершения обработки текущих запросов.
- `proxyProtocol.trustedIPs` — разбор бинарного заголовка PROXY Protocol v1/v2 только от доверенных вышестоящих аппаратных балансировщиков (HAProxy, Keepalived LVS).
- `forwardedHeaders.trustedIPs` — парсинг заголовков `X-Forwarded-*` и `X-Real-IP`. Недоверенные источники сбрасываются во избежание спуфинга IP-адресов. Подробнее — [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md).
- `http3: {}` — активация протокола HTTP/3 поверх UDP на том же порту.

### Правила маршрутизации (Routers & Rules)

В Traefik v3 синтаксис правил основан на строгих матчерах Go-типов. Значения аргументов всегда обрамляются в обратные кавычки (backticks):

| Матчер | Описание | Пример |
| :--- | :--- | :--- |
| `Host(...)` | Точное совпадение доменного имени или wildcard | `Host(`api.example.com`, `*.example.com`)` |
| `HostRegexp(...)` | Сопоставление домена по регулярному выражению | `HostRegexp(`^([a-z0-9-]+)\.app\.internal$`)` |
| `Path(...)` | Строгое соответствие пути URL | `Path(`/api/v1/health`)` |
| `PathPrefix(...)` | Префикс пути URL (в v3 без regexp) | `PathPrefix(`/static`, `/media`)` |
| `PathRegexp(...)` | Соответствие пути по регулярному выражению | `PathRegexp(`^/articles/[0-9]+$`)` |
| `Method(...)` | HTTP-метод запроса | `Method(`GET`, `POST`)` |
| `Header(...)` | Наличие точного ключа и значения заголовка | `Header(`X-Environment`, `production`)` |
| `HeaderRegexp(...)` | Соответствие значения заголовка по regexp | `HeaderRegexp(`User-Agent`, `(?i)curl.*`)` |
| `ClientIP(...)` | Фильтрация по IP или CIDR клиента | `ClientIP(`10.0.0.0/8`, `192.168.1.50`)` |

Матчеры объединяются логическими операторами:
- `&&` — логическое И;
- `||` — логическое ИЛИ;
- `!` — логическое отрицание;
- `(...)` — группировка условий.

**Приоритет правил:**
Если входящий запрос подходит под условия нескольких роутеров одновременно, Traefik разрешает коллизию через поле `priority`:
1. Если `priority` задан явно — побеждает роутер с максимальным числовым значением.
2. Если `priority` не задан (по умолчанию 0) — Traefik автоматически рассчитывает приоритет как **длину строки правила в символах**. Более длинные и специфичные правила получают преимущество над короткими.

Подробнее о матчерах и синтаксисе — [Правила и приоритет](./traefik-routers-and-rules.md).

### Балансировка нагрузки и типы сервисов

В архитектуре Traefik сервис отвечает за непосредственную доставку запроса в целевые бэкенды. Поддерживаются следующие режимы и структуры:

#### 1. Балансировка между серверами (LoadBalancer)

Распределяет запросы между физическими или контейнерными адресами бэкенда (`servers`) с использованием алгоритма **Round Robin**.

```yaml
services:
  web-service:
    loadBalancer:
      # Проверка состояния доступности серверов
      healthCheck:
        path: /ping
        interval: 10s
        timeout: 2s
        scheme: http
        hostname: example.internal
        port: 8080
      # Фиксация клиентской сессии (Session Affinity)
      sticky:
        cookie:
          name: srv_id
          secure: true
          httpOnly: true
          sameSite: lax
          maxAge: 86400
      servers:
        - url: "http://10.10.1.11:8080"
        - url: "http://10.10.1.12:8080"
```

- **HealthCheck (активный):** Периодически выполняет HTTP-запрос к каждому серверу из списка. Если сервер не отвечает или возвращает статус вне диапазона `200-399`, Traefik временно исключает его из пула маршрутизации до восстановления.
- **Sticky Sessions:** Устанавливает криптографически подписанную HTTP-cookie клиенту при первом обращении, направляя последующие запросы того же клиента на тот же бэкенд.

#### 2. Взвешенное распределение (Weighted Round Robin — WRR)

Позволяет распределять трафик в заданных процентных пропорциях между несколькими вложенными сервисами. Применяется для канареечных развертываний (Canary Deployments) и сине-зеленых релизов (Blue-Green):

```yaml
services:
  app-canary:
    weighted:
      services:
        - name: app-v1@file
          weight: 90
        - name: app-v2@file
          weight: 10
```

#### 3. Highest Random Weight (HRW)

Режим детерминированной балансировки на основе хеширования Rendezvous (HRW). Позволяет направлять запросы с одинаковыми входными характеристиками (заголовки, IP) на один и тот же нижележащий сервис без необходимости хранения общего состояния сессий.

```yaml
services:
  hrw-service:
    highestRandomWeight:
      services:
        - name: app-shard-1@file
          weight: 1
        - name: app-shard-2@file
          weight: 1
```

#### 4. Зеркалирование трафика (Mirroring)

Клонирует входящий поток запросов на теневой тестовый сервис без блокировки основного ответа клиенту:

```yaml
services:
  production-with-shadow:
    mirroring:
      service: app-production@file
      mirrors:
        - name: app-shadow-audit@file
          percent: 20
```

#### 5. Аварийное переключение (Failover)

Перенаправляет входящие запросы на резервный сервис (например, статический сайт-заглушку или резервный ЦОД) только в случае, если все серверы основного сервиса признаны неработоспособными проверкой `healthCheck`:

```yaml
services:
  resilient-service:
    failover:
      service: primary-app@file
      fallback: maintenance-app@file
```

#### 6. Сервисные Middleware и иерархическая маршрутизация

Traefik v3 поддерживает назначение middleware непосредственно на уровне сервиса (`services.<name>.middlewares`). Такой middleware применяется ко всему входящему в сервис трафику независимо от того, через какой роутер пришел запрос.
Также поддерживается многоуровневая маршрутизация (Multi-Layer Routing) через директиву `parentRefs`, где родительский роутер выполняет общую аутентификацию на порту, а дочерние роутеры разбирают пути и бизнес-заголовки.

### Промежуточные обработчики (Middlewares)

Middlewares группируются по функциональным задачам:

| Категория | Middleware | Назначение в production |
| :--- | :--- | :--- |
| **Безопасность** | `BasicAuth` | HTTP Basic аутентификация по htpasswd-хешам |
| | `ForwardAuth` | Делегирование проверки токена внешнему IdP (Authelia, Keycloak, OAuth2-Proxy) |
| | `IPAllowList` | Фильтрация клиентских IP-адресов по белым спискам CIDR |
| | `Headers` | Установка HSTS, X-Frame-Options, CSP, CORS |
| **Трафик** | `RateLimit` | Ограничение RPS/RPM с алгоритмом Token Bucket (локально или через Redis) |
| | `CircuitBreaker` | Превентивный разрыв цепи при всплеске ошибок бэкенда |
| | `Retry` | Автоматический повтор запроса при сетевых сбоях бэкенда |
| | `Buffering` | Ограничение размера и буферизация тела запроса/ответа на диск |
| **Трансформация** | `StripPrefix` / `StripPrefixRegex` | Удаление префикса пути перед отправкой в бэкенд |
| | `AddPrefix` | Добавление префикса к пути бэкенда |
| | `ReplacePath` / `ReplacePathRegex` | Модификация URI запроса по регулярным выражениям |
| **Служебные** | `Compress` | Потоковое сжатие ответов алгоритмами Gzip и Brotli |
| | `ErrorPage` | Перехват 5xx/4xx ошибок и отдача страниц из статического сервиса |

Подробнее о настройке безопасности — [Middleware для безопасности](./traefik-middlewares-security.md), об управлении нагрузкой — [Middleware для управления трафиком](./traefik-middlewares-traffic.md).

### SSL/TLS и автоматизация сертификатов (ACME)

В Traefik встроен клиент протокола ACME (RFC 8555), автоматизирующий получение и обновление бесплатных сертификатов Let's Encrypt и ZeroSSL.

**Поддерживаемые типы проверок:**
- **HTTP-01 (`httpChallenge`):** Traefik перехватывает запросы по пути `/.well-known/acme-challenge/*` на порту 80. Требует прямого доступа из интернета к порту 80.
- **TLS-ALPN-01 (`tlsChallenge`):** Валидация через протокол согласования уровня приложений на порту 443. Удобно для хостов, где порт 80 полностью закрыт фаерволом.
- **DNS-01 (`dnsChallenge`):** Проверка через создание временных TXT-записей в DNS-зоне через API провайдера DNS. Единственный метод для получения wildcard-сертификатов (`*.example.com`) и обслуживания закрытых внутренних периметров без публичных IP.

**Критические эксплуатационные правила ACME:**
1. **Права на файл хранилища:** Файл `acme.json` должен строго иметь права `0600` (`chmod 600 acme.json`) и принадлежать пользователю процесса Traefik. При любых других правах Traefik аварийно прекратит работу с сертификатами.
2. **Ограничение масштабирования OSS:** В открытой версии Traefik файл `acme.json` **не может** быть разделен между несколькими репликами Traefik (отсутствует распределенная блокировка файлового дескриптора). Для кластеров высокой доступности (HA) используется либо DNS-01 через cert-manager в Kubernetes, либо выделенный инстанс генерации, либо внешнее распределение сертификатов через файловый провайдер.
3. **Лимиты Let's Encrypt:** Для отладки и тестирования конфигурации всегда используйте staging-сервер:
   `caServer: https://acme-staging-v02.api.letsencrypt.org/directory`

### ServersTransport: взаимодействие с бэкендами и mTLS

Секция `serversTransport` настраивает исходящие соединения от Traefik к бэкендам:

```yaml
http:
  serversTransports:
    secure-backend-transport:
      insecureSkipVerify: false
      rootCAs:
        - /etc/traefik/certs/internal-ca.crt
      certificates:
        - certFile: /etc/traefik/certs/traefik-client.crt
          keyFile: /etc/traefik/certs/traefik-client.key
      maxIdleConnsPerHost: 200
      forwardingTimeouts:
        dialTimeout: 3s
        responseHeaderTimeout: 10s
        idleConnTimeout: 90s
```

- `rootCAs` — доверенный корневой сертификат корпоративного удостоверяющего центра (Internal CA / Vault PKI) для валидации самоподписанных сертификатов бэкендов.
- `certificates` — клиентский сертификат Traefik для взаимной аутентификации (mTLS).
- `spiffe` — Traefik v3 поддерживает нативную валидацию рабочих нагрузок SPIFFE/SPIRE через проверку SVID (SPIFFE Verifiable Identity Document) бэкенда.
- `maxIdleConnsPerHost` — размер пула простаивающих keep-alive соединений. Предотвращает исчерпание сокетов при высокой частоте запросов к бэкендам. Подробнее — [Пул соединений (Connection Pooling)](./traefik-connection-pooling.md).

### Поддерживаемые сетевые протоколы

Traefik маршрутизирует трафик на уровнях L4 и L7 модели OSI:
- **HTTP/1.1 и HTTP/2:** Поддерживаются нативно, включая прозрачную передачу gRPC поверх HTTP/2 и протокол h2c (нешифрованный HTTP/2 к бэкендам).
- **HTTP/3 (QUIC):** Работает поверх протокола UDP. Обеспечивает мгновенный handshake и устраняет блокировку очереди (head-of-line blocking) на нестабильных каналах связи.
- **WebSocket:** Поддерживается «из коробки» без специальных директив; Traefik автоматически обрабатывает заголовок `Connection: Upgrade`.
- **TCP (L4):** Маршрутизация на основе `HostSNI(...)` при включенном TLS или маршрутизация сырого TCP-потока на выделенном порту (`HostSNI(`*`)`). Применяется для баз данных (PostgreSQL, Redis), SSH-шлюзов и почтовых серверов.
- **UDP (L4):** Маршрутизация датаграмм DNS, Syslog и игровых серверов.

### Наблюдаемость (Observability)

- **Метрики Prometheus:** Встроенный экспортер на выделенном entrypoint (по умолчанию отдает метрики в стандартном формате OpenMetrics/Prometheus). Содержит счетчики запросов (`traefik_entrypoint_requests_total`), гистограммы задержек (`traefik_entrypoint_request_duration_seconds`) и статус открытых соединений.
- **Трассировка OpenTelemetry (OTLP):** В Traefik v3 интеграция с распределенной трассировкой унифицирована через протокол OTLP (gRPC или HTTP). Легаси-провайдеры Jaeger и Zipkin полностью удалены.
- **Журналирование:** Поддержка форматов `json` и `common`. В access-логах поддерживается маскирование конфиденциальных заголовков (Authorization, Cookie) и фильтрация статус-кодов.

Подробнее — [Наблюдаемость Traefik](./traefik-observability.md).

## Практические сценарии

### Требования к окружению

| Компонент | Минимальная версия / Требование | Назначение |
| :--- | :--- | :--- |
| **ОС** | Linux с ядром 4.19+ (рекомендуется 5.15+) | Поддержка сокетов UDP для HTTP/3, epoll |
| **Бинарный файл** | Traefik v3.x (amd64 / arm64) | Статический исполняемый файл без runtime-зависимостей |
| **Docker Engine** | 20.10+ (при использовании контейнеров) | Совместимость с Docker API v1.41+ |
| **Сетевые порты** | 80/tcp, 443/tcp, 443/udp | Стандартные порты входящего веб-трафика и HTTP/3 |
| **Служебные порты** | 8080/tcp (Dashboard), 8082/tcp (Metrics) | Изолированные порты мониторинга и управления |
| **Права файловой системы** | `chmod 600 /etc/traefik/acme.json` | Обязательное условие для работы ACME Let's Encrypt |

---

### Сценарий 1: Развертывание Traefik на Linux (Bare-Metal / systemd)

Развертывание Traefik в виде системного демона без оверхеда контейнеризации.

#### 1. Создание системного пользователя и структуры каталогов

```bash
# Создание выделенного системного пользователя без оболочки входа
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/traefik -M traefik

# Создание каталогов конфигурации, состояния и логов
sudo mkdir -p /etc/traefik/dynamic /var/lib/traefik /var/log/traefik

# Инициализация файла для хранения сертификатов ACME
sudo touch /var/lib/traefik/acme.json
sudo chmod 600 /var/lib/traefik/acme.json

# Назначение владельца
sudo chown -R traefik:traefik /etc/traefik /var/lib/traefik /var/log/traefik
```

#### 2. Загрузка бинарного файла и назначение сетевых привилегий Linux

```bash
TRAEFIK_VER="v3.6.0"
curl -sSL "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VER}/traefik_${TRAEFIK_VER}_linux_amd64.tar.gz" -o /tmp/traefik.tar.gz
sudo tar -xzf /tmp/traefik.tar.gz -C /usr/local/bin/ traefik
sudo chmod 755 /usr/local/bin/traefik
rm -f /tmp/traefik.tar.gz

# Разрешение бинарнику открывать привилегированные порты (80, 443) от непривилегированного пользователя
sudo setcap 'cap_net_bind_service=+ep' /usr/local/bin/traefik
```

#### 3. Создание статической конфигурации (`/etc/traefik/traefik.yml`)

```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: ":443"
  metrics:
    address: "127.0.0.1:8082"
  traefik:
    address: "127.0.0.1:8080"

providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.internal
      storage: /var/lib/traefik/acme.json
      httpChallenge:
        entryPoint: web

api:
  dashboard: true
  insecure: false

ping:
  entryPoint: traefik

metrics:
  prometheus:
    entryPoint: metrics

log:
  level: INFO
  format: json

accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  bufferingSize: 50
```

#### 4. Создание unit-файла systemd (`/etc/systemd/system/traefik.service`)

```ini
[Unit]
Description=Traefik Edge Router & Reverse Proxy
Documentation=https://doc.traefik.io/traefik/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=traefik
Group=traefik
ExecStartPre=/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml
Restart=always
RestartSec=3s

# Ограничения безопасности процесса
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/traefik /var/log/traefik
PrivateTmp=true
LimitNOFILE=65536

# Параметры завершения
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=20s

[Install]
WantedBy=multi-user.target
```

#### 5. Запуск и валидация службы

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now traefik
sudo systemctl status traefik --no-pager
# → Active: active (running) since ...
```

Подробное руководство по bare-metal развертыванию — [Traefik на bare-metal/VM](./traefik-bare-metal.md).

---

### Сценарий 2: Безопасное развертывание с Docker Compose и `docker-socket-proxy`

**Проблема безопасности:** Прямое монтирование сокета `/var/run/docker.sock` в публично доступный контейнер предоставляет root-эквивалентные привилегии на хосте. При компрометации прокси злоумышленник получает полный контроль над хостом.
**Решение:** Разделение контуров через `docker-socket-proxy`, открывающий только read-only API операций обнаружения контейнеров.

#### Файл `compose.yaml`:

```yaml
services:
  # Защитный шлюз к Docker API
  socket-proxy:
    image: tecnativa/docker-socket-proxy:0.1.1
    container_name: traefik-socket-proxy
    restart: unless-stopped
    mem_limit: 128m
    cpus: 0.2
    environment:
      - CONTAINERS=1
      - SERVICES=1
      - TASKS=1
      - NETWORKS=1
      - POST=0
      - DELETE=0
      - PUT=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - socket_net

  # Основной шлюз Traefik
  traefik:
    image: traefik:v3.6.0
    container_name: traefik-edge
    restart: unless-stopped
    depends_on:
      - socket-proxy
    security_opt:
      - no-new-privileges:true
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp" # HTTP/3 QUIC
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
      - ./dynamic:/etc/traefik/dynamic:ro
      - traefik_acme:/etc/traefik/acme
      - traefik_logs:/var/log/traefik
    networks:
      - socket_net
      - public_edge
    labels:
      - "traefik.enable=true"
      # Настройка роутера для собственного Dashboard
      - "traefik.http.routers.dashboard.rule=Host(`traefik.local.internal`)"
      - "traefik.http.routers.dashboard.entrypoints=websecure"
      - "traefik.http.routers.dashboard.service=api@internal"
      - "traefik.http.routers.dashboard.middlewares=admin-auth"
      # BasicAuth middleware: admin / secretPassHashed
      - "traefik.http.middlewares.admin-auth.basicauth.users=admin:$$2y$$05$$59074Ndfw8QdGg0YpZqU..cZg26N7P00mJkYQkW2vX14Oa6K.2Wl6"

  # Пример целевого приложения
  whoami:
    image: traefik/whoami:v1.10.1
    container_name: demo-whoami
    restart: unless-stopped
    networks:
      - public_edge
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.whoami.rule=Host(`whoami.local.internal`)"
      - "traefik.http.routers.whoami.entrypoints=websecure"
      - "traefik.http.services.whoami.loadbalancer.server.port=80"

networks:
  socket_net:
    internal: true # Изолированная сеть без доступа в интернет
  public_edge:
    name: traefik_network

volumes:
  traefik_acme:
  traefik_logs:
```

Подробнее о работе с метками контейнеров — [Traefik с Docker Compose](./traefik_with_docker_compose.md).

---

### Сценарий 3: Kubernetes On-Premise (IngressRoute и Gateway API)

В инфраструктурах на базе самостоятельных кластеров Kubernetes (bare-metal k8s, Talos, kubeadm, RKE2) Traefik развертывается как Edge Ingress-контроллер через Helm-чарт:

1. **Режим IngressRoute (Traefik CRD):** Собственные декларативные манифесты `traefik.io/v1alpha1` (`IngressRoute`, `Middleware`, `ServersTransport`), дающие полный доступ ко всем возможностям Traefik без ограничений стандартных аннотаций Ingress.
2. **Режим Kubernetes Gateway API:** Современная стандартная спецификация маршрутизации (`GatewayClass`, `Gateway`, `HTTPRoute`, `TCPRoute`), обеспечивающая переносимость манифестов.

Подробные руководства:
- [Traefik в Kubernetes](./traefik-kubernetes.md)
- [Traefik Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md)
- [Автоматизация TLS через cert-manager](./traefik-cert-manager-ingressroute-tls.md)

## Операции и команды

### Управление и валидация конфигурации через CLI

```bash
# Проверка версии и параметров компиляции бинарника
traefik version
# → Version:      v3.6.0
# → Codename:     mouclade
# → Go version:   go1.24.x
# → OS/Arch:      linux/amd64

# Синтаксическая валидация статического файла конфигурации перед перезапуском
traefik config validate --configfile=/etc/traefik/traefik.yml
# → Configuration is valid

# Тестовый прогон конфигурации в Docker-контейнере
docker run --rm -v $(pwd)/traefik.yml:/etc/traefik/traefik.yml:ro traefik:v3.6.0 config validate
# → Configuration is valid

# Встроенная CLI-проверка работоспособности демона через сокет/порт
traefik healthcheck --ping
# → OK
```

### Диагностика состояния через встроенный HTTP API

```bash
# Быстрая проверка жизнеспособности (liveness probe)
curl -s -f http://127.0.0.1:8080/ping
# → OK

# Получение сырого дампа активной конфигурации всех провайдеров
curl -s http://127.0.0.1:8080/api/rawdata | jq '.http.routers | keys'
# → [ "dashboard@docker", "whoami@docker" ]

# Вывод списка роутеров с правилами и целевыми сервисами
curl -s http://127.0.0.1:8080/api/http/routers | jq '.[] | {name: .name, rule: .rule, service: .service, status: .status}'
# → {
# →   "name": "whoami@docker",
# →   "rule": "Host(`whoami.local.internal`)",
# →   "service": "whoami",
# →   "status": "enabled"
# → }

# Детальный статус доступности бэкенд-серверов в сервисе
curl -s http://127.0.0.1:8080/api/http/services/whoami@docker | jq '.serverStatus'
# → {
# →   "http://172.20.0.3:80": "UP"
# → }
```

### Сбор и анализ метрик

```bash
# Получение метрик Prometheus на служебном порту
curl -s http://127.0.0.1:8082/metrics | grep traefik_entrypoint_requests_total | head -n 5
# → # HELP traefik_entrypoint_requests_total How many HTTP requests processed on an entrypoint, partitioned by status code, protocol, and method.
# → # TYPE traefik_entrypoint_requests_total counter
# → traefik_entrypoint_requests_total{code="200",entrypoint="websecure",method="GET",protocol="http"} 4521
# → traefik_entrypoint_requests_total{code="404",entrypoint="websecure",method="GET",protocol="http"} 12
```

### Системное администрирование и логи

```bash
# Просмотр системного статуса службы в systemd
sudo systemctl status traefik --no-pager
# → ● traefik.service - Traefik Edge Router & Reverse Proxy
# →      Loaded: loaded (/etc/systemd/system/traefik.service; enabled)
# →      Active: active (running) since Thu 2026-10-16 10:15:20 MSK; 3h ago

# Потоковый просмотр системных логов демона
sudo journalctl -u traefik -f -o cat
# → {"level":"info","msg":"Configuration loaded from file: /etc/traefik/traefik.yml","time":"2026-10-16T10:15:20Z"}

# Анализ access-лога: подсчет кодов ответа 5xx
grep -E '"StatusCode":5[0-9]{2}' /var/log/traefik/access.log | jq -r '.RequestPath' | sort | uniq -c
# → 14 /api/v1/checkout
```

## Устранение неисправностей

### Матрица типовых инцидентов SRE / Sysadmin

| Симптом / Ошибка | Первопричина | Метод локализации и устранение |
| :--- | :--- | :--- |
| **404 Not Found** | 1. Запрос не совпал ни с одним правилом `rule`.<br>2. Неверно указан `entryPoints` у роутера.<br>3. У роутера отсутствует целевой `service`. | Проверьте `curl http://127.0.0.1:8080/api/http/routers`. Убедитесь, что заголовок `Host` в запросе точно соответствует правилу. Проверьте приоритет роутера. |
| **502 Bad Gateway** | 1. Приложение в контейнере слушает `127.0.0.1` вместо `0.0.0.0`.<br>2. Неверно указан порт в `loadbalancer.server.port`.<br>3. Traefik и контейнер находятся в разных Docker-сетях. | Проверьте сетевую связность: `docker exec -it traefik-edge nc -zv <ip-бэкенда> <порт>`. Проверьте, что приложение слушает интерфейс `0.0.0.0`. |
| **503 Service Unavailable** | 1. Все бэкенды сервиса провалили проверку `healthCheck`.<br>2. Сервис пустой, а опция `allowEmptyServices` выключена. | Проверьте состояние серверов: `/api/http/services/<name>`. Проверьте эндпоинт проверки здоровья бэкенда напрямую через `curl`. Увеличьте `timeout` проверки. |
| **413 Payload Too Large** | Размер тела запроса превысил лимит, установленный на точке входа. | Настройте параметр точки входа: `entryPoints.<name>.http.maxRequestBodyBytes: 104857600` (100MB) или настройте middleware `Buffering`. |
| **ACME: Ошибка выпуска сертификата** | 1. Права на `acme.json` отличны от `0600`.<br>2. Порт 80 недоступен извне для HTTP-01.<br>3. Достигнут rate limit Let's Encrypt. | Проверьте права: `ls -l acme.json`. Убедитесь, что порт 80 открыт в фаерволе хоста. Временно переключите `caServer` на staging Let's Encrypt для изоляции ошибки. |
| **401 Unauthorized на Dashboard** | Неправильный формат хеша в `basicAuth` или отсутствие экранирования знака `$` в Compose. | В файлах `compose.yaml` знак `$` в хешах bcrypt необходимо удваивать (`$$2y$$...`), иначе Compose подставляет пустую переменную окружения. |
| **High CPU / Goroutine Leak** | 1. Файловый провайдер отслеживает (`watch: true`) директорию с тысячами файлов.<br>2. Шторм событий Docker сокета при циклическом рестарте других контейнеров. | Ограничьте `providers.file.directory` только каталогом с YAML-конфигами. Исключите из директории логи и временные файлы. |

### Диагностические команды

```bash
# 1. Проверка открытых слушающих портов процесса
ss -tulpn | grep traefik
# → tcp   LISTEN 0      4096         0.0.0.0:80        0.0.0.0:*    users:(("traefik",pid=1420,fd=7))
# → tcp   LISTEN 0      4096         0.0.0.0:443       0.0.0.0:*    users:(("traefik",pid=1420,fd=8))
# → udp   UNCONN 0      0            0.0.0.0:443       0.0.0.0:*    users:(("traefik",pid=1420,fd=9))

# 2. Тестирование ответа роутера с принудительной передачей заголовка Host
curl -Iv -k --resolve app.example.com:443:127.0.0.1 https://app.example.com/healthz
# → HTTP/2 200
# → server: traefik

# 3. Проверка прав файла ключей ACME
stat -c "%a %U:%G" /var/lib/traefik/acme.json
# → 600 traefik:traefik

# 4. Поиск критических ошибок сертификации в журналах
journalctl -u traefik --no-pager | grep -iE 'error.*acme|certificate' | tail -n 5
# → {"level":"error","msg":"Unable to obtain ACME certificate for domains...","time":"2026-10-16T11:00:00Z"}
```

## Рекомендации

### Безопасность

- **Защита Docker Socket:** Категорически запрещается монтировать сокет `/var/run/docker.sock` напрямую в публичный контейнер Traefik в продакшене. Всегда используйте изолированный прокси-шлюз (например, `docker-socket-proxy`) с минимальным набором прав (`CONTAINERS=1`, `SERVICES=1`, `TASKS=1`, запись `POST/PUT/DELETE=0`).
- **Защита Dashboard и API:** Никогда не устанавливайте параметр `api.insecure: true` на общедоступных серверах. Публикуйте Dashboard исключительно через явный роутер на защищенном entrypoint с обязательной аутентификацией (`BasicAuth` с надежным алгоритмом bcrypt или `ForwardAuth` с интеграцией в корпоративный SSO/IdP).
- **Минимизация привилегий ОС:** На bare-metal серверах запускайте Traefik от непривилегированного системного пользователя (`traefik`), делегируя право прослушивания портов 80 и 443 через Linux capability `CAP_NET_BIND_SERVICE`.
- **Защита файловой системы:** Права на файл `acme.json` должны быть жестко зафиксированы как `0600`. Конфигурационные файлы должны быть доступны процессу только на чтение (`read-only`).
- **Безопасные заголовки:** Для всех публичных L7-сервисов включайте middleware `Headers` с принудительным `HSTS` (`stsSeconds: 31536000`), защитой от MIME-спуфинга (`contentTypeNosniff: true`) и блокировкой Clickjacking (`customFrameOptionsValue: "DENY"`).

### Производительность и надежность (SRE)

- **Пул постоянных соединений (Keep-Alive):** Для высоконагруженных систем обязательно настраивайте `serversTransport.maxIdleConnsPerHost` (по умолчанию 2, рекомендуется от 100 до 500 для предотвращения исчерпания эфемерных портов хоста под нагрузкой).
- **Плавное завершение (Graceful Shutdown):** Задавайте параметры `transport.lifeCycle.requestAcceptGraceTimeout` и `graceTimeout` на основных Entrypoint. Это гарантирует, что при перезапуске процесса или накатке обновлений Traefik корректно дождется завершения обработки текущих пользовательских сессий без сброса TCP-соединений (`RST`).
- **Защита бэкендов от перегрузки:** Комбинируйте middleware `RateLimit` (ограничение частоты запросов от подозрительных IP) и `CircuitBreaker` (мгновенный разрыв соединений при деградации бэкенда, защищающий базу данных от каскадного отказа).
- **Буферизация Access Log:** На серверах с высоким RPS включайте буферизацию журналов доступа (`accessLog.bufferingSize: 100-500`). Прямая синхронная запись каждой строки в файл на диске создает избыточную нагрузку на подсистему ввода-вывода (I/O wait).

### Эксплуатация и сопровождение

- **Фиксация версий:** Никогда не используйте тег `:latest` в производственных средах. Фиксируйте точную минорную или патч-версию (например, `traefik:v3.6.0`), чтобы исключить внезапные сбои при breaking changes.
- **Предварительная валидация:** Включайте вызов команды `traefik config validate` в шаг `ExecStartPre` в unit-файлах systemd или в пайплайны CI/CD перед развертыванием новой статической конфигурации.
- **Резервное копирование:** Настройте регулярный бэкап файла `acme.json` и статических файлов конфигурации. Потеря `acme.json` при наличии сотен доменов может привести к блокировке выпуска сертификатов по суточным лимитам Let's Encrypt.
- **Мониторинг метрик:** Настройте Prometheus-алерты на ключевые метрики:
  - `rate(traefik_entrypoint_requests_total{code=~"5.."}[5m]) > 0` — появление серверных ошибок шлюза;
  - `traefik_service_server_up == 0` — полный отказ бэкенд-серверов в сервисе;
  - Время ответа `histogram_quantile(0.99, sum(rate(traefik_entrypoint_request_duration_seconds_bucket[5m])) by (le))`.

## Дополнительная информация

### Сравнение с альтернативными обратными прокси

| Критерий | Traefik v3 | Nginx (OSS) | HAProxy | Envoy |
| :--- | :--- | :--- | :--- | :--- |
| **Модель обнаружения сервисов** | Встроенная динамическая (Docker, K8s, Nomad, Consul) | Статическая (перезагрузка конфигурации/Lua) | Runtime API / DNS resolution | Динамическая через gRPC (xDS API) |
| **Автоматизация SSL (ACME)** | Встроенная «из коробки» (Let's Encrypt, ZeroSSL) | Через внешние утилиты (Certbot, lego) | Через внешние скрипты / acme.sh | Внешняя (через Cert-Manager/xDS) |
| **Горячая перезагрузка роутов** | Мгновенная в памяти, без прерывания соединений | `nginx -s reload` (пересоздание worker-процессов) | `haproxy reload` (передача сокетов) | Мгновенная динамическая без перезапуска |
| **Язык и поставка** | Go, единый статический бинарный файл | C, модульная сборка | C, монолитный бинарник | C++, монолитный бинарник |
| **Основная ниша** | Динамические микросервисы, Docker, K8s Edge | Высокопроизводительная статика, High-Load L7 | Экстремальный L4/L7 балансировщик, низкая задержка | Service Mesh, сложный межсервисный трафик |

### См. также

- [Traefik на bare-metal/VM](./traefik-bare-metal.md) — развертывание бинарного файла, systemd и ротация логов.
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — развертывание в Docker, иерархия меток и сетевая изоляция.
- [Правила и приоритет](./traefik-routers-and-rules.md) — детальный справочник матчеров, ruleSyntax и расчет приоритетов.
- [TLS Options и mTLS](./traefik-tls-options.md) — политики шифрования, клиентские сертификаты и SNI Passthrough.
- [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md) — настройка forwardedHeaders и PROXY Protocol за балансировщиками.
- [Протоколы и потоки данных](./traefik-protocols-advanced.md) — специфика gRPC/h2c, HTTP/3, WebSocket, TCP и UDP.
- [Middleware для безопасности](./traefik-middlewares-security.md) — ForwardAuth, BasicAuth, IPAllowList и заголовки безопасности.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, CircuitBreaker, Retry, Buffering и сжатие.
- [Пул соединений (Connection Pooling)](./traefik-connection-pooling.md) — тонкая настройка `serversTransport`, таймаутов и пулов сокетов.
- [Проверки здоровья (Health Checks)](./traefik-health-checks.md) — активные и пассивные проверки бэкендов.
- [Плавное завершение (Graceful Shutdown)](./traefik-graceful-shutdown.md) — настройка `transport.lifeCycle` для исключения потери соединений.
- [Отказоустойчивость Traefik (HA)](./traefik-high-availability.md) — отказоустойчивые топологии с Keepalived и внешними хранилищами.
- [Наблюдаемость Traefik](./traefik-observability.md) — метрики Prometheus, OTLP-трейсинг и структурированные логи.
- [Провайдеры конфигурации](./traefik-providers-advanced.md) — File provider, Nomad, Consul Catalog.
- [Провайдеры KV-хранилищ](./traefik-providers-kv-stores.md) — интеграция с Consul, etcd, Redis, ZooKeeper.
- [Плагины](./traefik-plugins.md) — локальные плагины Yaegi и расширение функциональности.
- [Миграция с v2 на v3](./traefik-migration-v2-to-v3.md) — отличия v3, breaking changes и переход на новый синтаксис.
- [Docker Swarm Ingress с Traefik](../../Docker_swarm/swarm_ingress_traefik.md) — особенности маршрутизации в кластерах Swarm.
- [Traefik в Kubernetes](./traefik-kubernetes.md) — IngressRoute CRD, Middleware и балансировка в K8s.
- [Traefik Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md) — реализация спецификации Gateway API.
- [Обратный прокси (концепция)](../../Networking/Concepts/proxy.md) — архитектурные принципы работы обратных прокси-серверов.
- [PROXY Protocol](../../Networking/Protocols/proxy_protocol.md) — передача исходного клиентского IP через промежуточные балансировщики.
