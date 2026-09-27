# Обзор Traefik

## Определения

**Traefik** — современный обратный прокси-сервер и балансировщик нагрузки с автоматическим обнаружением сервисов (service discovery) и динамической конфигурацией. Написан на Go, поставляется в виде одного бинарного файла или легковесного Docker-образа.

**Traefik Hub Runtime Platform** — коммерческая платформа, расширяющая функциональность Open Source Traefik Proxy (в рамках данной базы рассматривается только открытая версия). Включает Traefik Hub (cloud management) и Traefik Pilot (аналитика, alerting, centralized config для OSS). Для большинства production-сценариев OSS достаточно; Pilot/Hub рассматривайте, если нужна централизованная multi-cluster аналитика без самосборного стека Prometheus/Grafana/Loki.

**Ключевые отличия:**
- **Динамичность:** Traefik опрашивает API источников конфигурации (Docker, Kubernetes, Nomad, Consul, файловая система) и автоматически обновляет маршруты без перезагрузки процесса.
- **Единый бинарник:** Статическая линковка зависимостей, отсутствие внешних runtime-зависимостей.
- **Встроенная визуализация:** Веб-интерфейс (Dashboard) для мониторинга маршрутов, сервисов и статуса здоровья в реальном времени.

## Базовые концепции

### Архитектура компонентов

Архитектура Traefik v3 построена на цепочке обработки запроса:

`Entrypoint → Router (with Middlewares) → Service → Server (Backend)`

**Поток запроса:**
1. **Providers** — источники данных. Опрашивают API (Docker, Kubernetes, Nomad, Consul, файловая система) и поставляют динамическую конфигурацию.
2. **Entrypoints** — слушатели сети (порты). Определяют, какие протоколы (HTTP, HTTPS, TCP, UDP) и порты открыты для приема трафика.
3. **Routers** — логика анализа входящих запросов. Сопоставляют запрос (по `Host`, `Path`, `PathPrefix`, `Header`, `HeadersRegexp`, `Method`) с конкретным Service. К роутеру можно прикрепить Middleware.
4. **Middlewares** — компоненты трансформации запроса. Могут изменять заголовки, ограничивать скорость, проверять аутентификацию или перенаправлять трафик.
5. **Services** — абстракция над бэкендами. Определяют способ балансировки между физическими серверами (Round Robin, Power of Two Choices, Least Time) и параметры проверки здоровья (Health Checks).
6. **Servers** — отдельные экземпляры бэкенда (IP:Port).

**Примечание:** В конфигурации YAML/TOML секции именуются с префиксом `http:`, `tcp:` или `udp:`, в зависимости от протокола.

### Типы конфигурации

Traefik строго разделяет конфигурацию на два слоя.

#### 1. Статическая конфигурация

Определяет «фундамент» прокси. Загружается один раз при старте.
- **Параметры:** Entrypoints, Providers, Certificates Resolvers, логирование, метрики, трассировка, глобальные таймауты.
- **Источники:** Файл `traefik.yml` (или `.toml`, `.json`), переменные окружения, CLI-флаги.

*Пример (traefik.yml):*
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
    http:
      tls:
        certResolver: myresolver
        domains:
          - main: example.com
            sans:
              - "*.example.com"

providers:
  docker:
    exposedByDefault: false
    network: traefik_network
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  myresolver:
    acme:
      email: admin@example.com
      storage: acme.json
      httpChallenge:
        entryPoint: web

api:
  dashboard: true
  insecure: false
  ping: true

metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addServicesLabels: true

accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  bufferingSize: 100
  filters:
    statusCodes:
      - "400-599"
```

#### 2. Динамическая конфигурация

Определяет правила маршрутизации. Обновляется «на лету» без прерывания соединений.
- **Параметры:** Routers, Services, Middlewares, TLS-опции.
- **Источники:** Метки (labels) в Docker, CRD/IngressRoute в Kubernetes, отдельные файлы в `providers.file`, KV-хранилища (Consul, etcd, Redis, ZooKeeper — см. [Провайдеры KV-хранилищ](./traefik-providers-kv-stores.md)).

*Пример (YAML для провайдера file):*
```yaml
http:
  routers:
    my-app:
      rule: "Host(`app.example.com`) && PathPrefix(`/`)"
      service: app-service
      entryPoints:
        - websecure
      middlewares:
        - secure-headers
      tls:
        certResolver: myresolver

  middlewares:
    secure-headers:
      headers:
        stsSeconds: 31536000
        browserXssFilter: true
        contentTypeNosniff: true
        forceSTSHeader: true
        stsIncludeSubdomains: true
        stsPreload: true

  services:
    app-service:
      loadBalancer:
        healthCheck:
          path: /health
          interval: 10s
          timeout: 3s
        servers:
          - url: "http://192.168.1.10:8080"
```

### Тонкая настройка entrypoints

Помимо `address`, entrypoint настраивает таймауты соединений, ограничения и HTTP/3:

```yaml
entryPoints:
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: myresolver
      middlewares:
        - global-headers           # middleware применяется ко всем роутерам entrypoint
      maxHeaderBytes: 4096
    transport:
      respondingTimeouts:
        readTimeout: 30s
        writeTimeout: 30s
        idleTimeout: 180s
      lifeCycle:
        requestAcceptGraceTimeout: 2s
        graceTimeout: 10s
    proxyProtocol:
      trustedIPs: ["10.0.0.0/8"]   # PROXY protocol от доверенных LB
    forwardedHeaders:
      trustedIPs: ["10.0.0.0/8"]   # доверие X-Forwarded-* (см. трафик-заголовки)
    http3: {}                      # HTTP/3 (QUIC), требует открытого UDP-порта
```

- `http.middlewares` — middleware выполняется для **всех** роутеров этого entrypoint до router-level middleware.
- `transport.respondingTimeouts` — таймауты приёма/записи/простоя соединений.
- `transport.lifeCycle` — плавное завершение: `requestAcceptGraceTimeout` (добор входящих при shutdown) и `graceTimeout` (ожидание активных соединений при остановке).

Подробнее о forwarded-заголовках и PROXY protocol — [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md).

### SSL/TLS и автоматизация сертификатов (ACME)

Traefik имеет встроенную поддержку Let's Encrypt и ZeroSSL через протокол ACME. Поддерживаемые методы валидации:

| Метод | Описание | Основной кейс |
| :--- | :--- | :--- |
| **HTTP Challenge** | Проверка владения доменом через временный endpoint на порту 80. | Стандартный публичный веб-сайт. |
| **TLS Challenge** | Валидация через протокол ALPN на порту 443. | Использование только HTTPS. |
| **DNS Challenge** | Проверка через создание TXT-записи в DNS. | Wildcard-сертификаты (`*.example.com`) и внутренние сети. |

**Важные особенности ACME:**
- Сертификаты выпускаются на 90 дней. Traefik начинает продление за 30 дней до истечения срока.
- Файл `acme.json` должен иметь права `600`. Иначе Traefik проигнорирует файл.
- Для тестирования используйте staging-сервер Let's Encrypt: `https://acme-staging-v02.api.letsencrypt.org/directory`.
- Файл `acme.json` не может быть разделен между несколькими инстансами Traefik (конфликт записи). Для HA используйте DNS-01 challenge с внешним хранилищем или развертывание с `replicas: 1`.
- Ключевые параметры ACME:
  - `caServer` — адрес ACME-сервера (production/staging).
  - `certificatesDuration` — продолжительность сертификата в часах (по умолчанию 2160 = 90 дней).
  - `keyType` — тип ключа (`EC256`, `RSA2048`, `RSA4096`).
  - `preferredChain` — предпочтительная цепочка сертификатов (например, `ISRG Root X1`).
  - `disableCommonName` — отключение использования Common Name (требуется для совместимости с certain ACME-серверами).

*Пример DNS-01 challenge (wildcard-сертификат):*

```yaml
certificatesResolvers:
  dnsresolver:
    acme:
      email: admin@example.com
      storage: acme.json
      dnsChallenge:
        provider: cloudflare
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
      caServer: https://acme-staging-v02.api.letsencrypt.org/directory
```

DNS-01 подходит для внутренних сетей без публичного `:80`/`:443` и для wildcard-сертификатов; требует API-доступа провайдера DNS (в `providers.dns` нет шифрования секретов — храните их в переменных окружения/секретах).

### Промежуточное ПО (Middlewares)

Middlewares позволяют модифицировать запрос до того, как он попадет в сервис, или ответ после обработки.

**Категории Middlewares:**

| Категория | Middleware | Назначение |
| :--- | :--- | :--- |
| **Безопасность** | `BasicAuth` | Базовая аутентификация (username:hashed_password). |
| | `ForwardAuth` | Делегирование аутентификации внешнему сервису (например, Authelia, OAuth2 Proxy). |
| | `IPAllowList` | Белый список IP-адресов. |
| **Трансформация** | `AddPrefix` | Добавление префикса к пути запроса. |
| | `StripPrefix` / `StripPrefixRegex` | Удаление префикса из пути. |
| | `Headers` | Управление HTTP-заголовками (добавление, удаление, безопасные заголовки). |
| | `ReplacePath` / `ReplacePathRegex` | Замена пути запроса. |
| **Ограничение** | `RateLimit` | Ограничение количества запросов (защита от перегрузки). |
| | `CircuitBreaker` | Разрыв цепи при превышении порога ошибок бэкенда. |
| | `Retry` | Повторные попытки при ошибках. |
| | `Buffering` | Буферизация тела запроса/ответа. |
| **Ошибки** | `ErrorPage` | Перенаправление на кастомные страницы ошибок (503, 504). |
| | `Recovery` | Восстановление после паники (panic) в бэкенде. |
| **Сеть** | `Compress` | Сжатие ответа (gzip, brotli). |
| | `DigestAuth` | Аутентификация по дайджесту (MD5/SHA). |

**Middleware для безопасных заголовков (рекомендуемый минимум):**
```yaml
middlewares:
  secure-headers:
    headers:
      stsSeconds: 31536000
      browserXssFilter: true
      contentTypeNosniff: true
      forceSTSHeader: true
      stsIncludeSubdomains: true
      stsPreload: true
      customFrameOptionsValue: "DENY"
```

> Важно (v3): опции `sslRedirect`, `sslTemporaryRedirect`, `sslHost`, `sslForceHost`, `featurePolicy` из middleware `Headers` **удалены**. Редирект HTTP→HTTPS выполняется через `redirections.entryPoint` на entrypoint или middleware `redirectScheme`. Подробнее — [Правила и приоритет](./traefik-routers-and-rules.md) и [Middleware для безопасности](./traefik-middlewares-security.md).

#### Error Pages (production)

Для production используйте отдельный статический сервис ошибок вместо встроенного:

```yaml
http:
  services:
    error-pages:
      loadBalancer:
        servers:
        - url: http://static-errors:80
  middlewares:
    custom-errors:
      errors:
        status:
        - "500-599"
        service: error-pages
        query: "/{status}.html"
```

### Управление трафиком

#### Балансировка нагрузки

Traefik v3 поддерживает следующие алгоритмы балансировки между серверами (backend instances):

| Алгоритм | Описание | Кейс использования |
| :--- | :--- | :--- |
| **Wrr (Weighted Round Robin)** | Циклическое распределение с учетом весов. | Стандартный кейс, канареечные релизы. |
| **P2C (Power of Two Choices)** | Случайный выбор двух серверов, направление на тот, у которого меньше активных запросов. | Высокая нагрузка, снижение пиковых задержек. |
| **Least Time** | Направление на сервер с наименьшим временем ответа. | Оптимизация latency, гетерогенные бэкенды. |

#### Канареечные релизы (Canary Deployments)

Распределение трафика между разными версиями сервиса в процентном соотношении через Weighted Round Robin между **services**:

```yaml
services:
  canary-service:
    weighted:
      services:
        - name: app-v1@file
          weight: 90
        - name: app-v2@file
          weight: 10
```

#### Зеркалирование (Mirroring)

Дублирование входящего трафика на другой сервис (например, для тестирования новой версии на реальных данных без влияния на пользователя):

```yaml
services:
  production-service:
    mirroring:
      service: app-v1@file
      mirrors:
        - name: app-v2-test@file
          percent: 10
```

#### Failover

Автоматическое переключение на резервный сервис при недоступности основного:

```yaml
services:
  main-service:
    failover:
      service: backup-service@file
```

#### Многоуровневая маршрутизация (Multi-Layer Routing)

Иерархические отношения между роутерами, где родительские роутеры применяют общие middleware (например, аутентификация), а дочерние — принимают финальное решение о маршрутизации.

```yaml
http:
  routers:
    api-parent:
      rule: "Host(`api.example.com`) && PathPrefix(`/`)"
      middlewares:
        - auth-with-tier
      entryPoints:
        - websecure
      tls: {}
      # Нет service — это родительский роутер

    api-enterprise:
      rule: "HeaderRegexp(`X-Customer-Tier`, `(enterprise|business)`)"
      service: stable-backend
      parentRefs:
        - api-parent

    api-free:
      rule: "Header(`X-Customer-Tier`, `free`)"
      service: new-version
      parentRefs:
        - api-parent
```

**Поддерживаемые провайдеры для multi-layer routing:**
- File provider (YAML, TOML, JSON)
- KV stores (Consul, etcd, Redis, ZooKeeper)
- Kubernetes CRD (IngressRoute)

**Типы роутеров в иерархии:**
- **Root Router:** Прикреплен к entrypoint, может иметь `tls`, `observability`, `middlewares`. Не имеет `service`.
- **Intermediate Router:** Ссылается на родителя через `parentRefs`, может иметь дочерние роутеры. Не имеет `service`, `entryPoints`, `tls`.
- **Leaf Router:** Ссылается на родителя через `parentRefs`, должен иметь `service`. Не имеет `entryPoints`, `tls`, `observability`.

#### Service Middlewares

Применение middleware к сервису, а не к роутеру. Middleware выполняется для всего трафика, направленного к сервису, независимо от того, через какой роутер пришел запрос.

```yaml
services:
  whoami:
    middlewares:
      - service-headers
```

Приоритет выполнения: сначала router-level middlewares, затем service-level middlewares.

#### Sticky Sessions (Session Affinity)

Привязка сессии к конкретному серверу бэкенда через cookie:

```yaml
services:
  my-service:
    loadBalancer:
      sticky:
        cookie:
          name: sticky_cookie
          httpOnly: true
          secure: true
```

### Современные возможности и интеграции

#### Поддерживаемые протоколы

- **HTTP/1.1, HTTP/2** — настройка через entrypoint (`http2: true`).
- **HTTP/3 (QUIC)** — поддержка UDP-порта 443 с QUIC для ускорения в нестабильных сетях.
- **WebSocket** — прозрачная поддержка при наличии `Upgrade` заголовка.
- **TCP** — маршрутизация произвольного TCP-трафика (например, PostgreSQL, SSH, SMTP).
- **UDP** — маршрутизация UDP-трафика.

*Пример TCP-роутера:*
```yaml
tcp:
  routers:
    postgres-tcp:
      rule: "HostSNI(`db.example.com`)"
      service: postgres-service
      entryPoints:
        - postgres
      tls: {}

  services:
    postgres-service:
      loadBalancer:
        servers:
          - address: 10.0.0.10:5432
```

#### PROXY Protocol

Traefik поддерживает PROXY Protocol v1 и v2 на TCP-сервисах для передачи реального IP клиента от внешнего балансировщика:

```yaml
services:
  my-tcp-service:
    loadBalancer:
      proxyProtocol:
        version: 2
      servers:
        - address: 10.0.0.10:5432
```

#### Servers Transport и TLS между Traefik и бэкендом

Конфигурация защищенного соединения между Traefik и бэкендом:

```yaml
serversTransport:
  insecureSkipVerify: false
  rootCAs:
    - /etc/traefik/ca.crt
  maxIdleConnsPerHost: 200
  forwardingTimeouts:
    idleTimeout: 3m
    readTimeout: 1m
```

#### SPIFFE

Traefik поддерживает SPIFFE (Secure Production Identity Framework For Everyone) для mTLS между Traefik и бэкендами. Требует включения в статической конфигурации перед использованием.

SPIFFE-идентификация в Traefik строится на двух компонентах:

1. **SPIFFE ID** — идентификатор рабочей нагрузки в формате `spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>`. В Kubernetes это обычно ServiceAccount; в bare-metal — идентичность, выданная SPIRE agent.
2. **SVID (SPIFFE Verifiable Identity Document)** — X.509-сертификат, содержащий SPIFFE ID в поле SAN. Traefik использует SVID для взаимной аутентификации с бэкендом.

Паттерн интеграции:

- **Самый простой:** Traefik получает SVID от внешнего CA (Vault PKI/SPIRE) через volume-mounted secret. В статической конфигурации указывается `serversTransport.rootCAs` и `serversTransport.tls.clientCert`/`tls.clientKey`.
- **В Kubernetes:** cert-manager с SPIFFE-шаблоном или Vault Agent Injector монтирует сертификат в pod Traefik. Тогда `ServersTransport` CRD ссылается на Secret с SVID.
- **Проверка на бэкенде:** бэкенд должен иметь доверенный корневой CA (SPIRE trust bundle) и проверять `subjectAlternativeName` на совпадение SPIFFE ID.

Ограничения OSS:
- Traefik **не является** SPIFFE-совместимой рабочей нагрузкой сам — он только *проверяет* SVID бэкенда через `ServersTransport`.
- Автоматическая ротация SVID требует внешнего компонента (Vault Agent Injector, SPIRE agent с `workloadapi`).
- В Service Mesh (Istio/Linkerd) SPIFFE-идентичность управляется control plane; Traefik выступает как внешний ingress без sidecar.

Для практической настройки mTLS с клиентскими сертификатами см. [TLS-опции и mTLS](./traefik-tls-options.md).

#### Наблюдаемость (Observability)

- **Метрики:** Встроенный экспортер Prometheus (настраиваемый entrypoint, кастомные метки, buckets).
- **Трассировка:** В v3 — только интеграция с **OpenTelemetry (OTLP)** (Jaeger/Zipkin-провайдеры удалены).
- **Логи:** Форматы `common`, `json`, `logfmt`. Access log с фильтрацией по статус-кодам, буферизацией, полями для обфускации.

Подробнее — [Наблюдаемость Traefik](./traefik-observability.md).

### Безопасность и эксплуатация

1. **Защита Docker Socket:** При использовании провайдера Docker Traefik требует доступа к `/var/run/docker.sock`. Для безопасности рекомендуется использовать `docker-socket-proxy`, чтобы ограничить доступ Traefik только операциями чтения API (`CONTAINERS=1`, `SERVICES=1`, `TASKS=1`).
2. **Защита Dashboard:** По умолчанию дашборд открыт. Всегда защищайте его с помощью `BasicAuth` или `ForwardAuth` middleware и не выставляйте на публичные Entrypoints без TLS. Рекомендуется `api.insecure: false`.
3. **Логирование:** Используйте формат JSON для `accessLog` с фильтрацией по статус-кодам для облегчения интеграции с ELK/Loki.
4. **Ограничение ресурсов:** При развертывании в контейнере задавайте `limits` CPU и memory, особенно при использовании ACME с большим количеством сертификатов.

## Практические сценарии

Traefik адаптируется под разные уровни инфраструктуры. Детальные пошаговые инструкции находятся в соответствующих разделах:

- **Локальная разработка и VPS:** Использование Docker Compose для автоматизации SSL и маршрутизации.
  - См. [Traefik с Docker Compose](./traefik_with_docker_compose.md).
- **Кластеры Docker Swarm:** Работа в качестве динамического Edge Router.
  - См. [Docker Swarm Ingress с Traefik](../../Docker_swarm/swarm_ingress_traefik.md).
- **Kubernetes:**
  - В качестве Ingress-контроллера: [Обзор Ingress](../../Kubernetes/Networking/Ingress/overview.md).
  - Через современный [Traefik Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md).

### Требования к окружению

| Компонент | Минимальная версия / требование |
| :--- | :--- |
| **Traefik** | v3.1+ (актуальная стабильная: v3.4/v3.6) |
| **Docker** | 20.10+ (для Docker provider) |
| **Ядро Linux** | 4.19+ (для HTTP/3) |
| **Сертификаты** | `acme.json` — права `600`, владелец процесс Traefik |
| **Сеть** | Порты 80 (HTTP Challenge), 443 (HTTPS), 8080 (Dashboard, опционально) |

## Операции и команды

### Работа с бинарным файлом

```bash
# Запуск с статической конфигурацией через CLI-флаги
traefik \
  --entrypoints.web.address=:80 \
  --entrypoints.websecure.address=:443 \
  --providers.docker=true \
  --providers.docker.exposedbydefault=false \
  --certificatesresolvers.myresolver.acme.email=admin@example.com \
  --certificatesresolvers.myresolver.acme.storage=acme.json \
  --certificatesresolvers.myresolver.acme.httpchallenge.entrypoint=web \
  --api.dashboard=true \
  --log.level=INFO \
  --accesslog.format=json
# → Traefik запущен, порты 80/443 открыты, дашборд доступен на 8080
```

### Проверка работоспособности

```bash
# Health check (встроенный endpoint, требуется `api.ping: true`)
curl -s http://localhost:8080/ping
# → OK

# Проверка конфигурации через API
curl -s http://localhost:8080/api/http/routers | jq .
# → JSON со списком роутеров

# Проверка статуса сервисов
curl -s http://localhost:8080/api/http/services | jq .
# → JSON со списком сервисов и их бэкендов
```

### Работа с метриками

```bash
# Запрос метрик Prometheus
curl -s http://localhost:9100/metrics
# → # HELP traefik_service_requests_total ...
```

### Работа с логами

```bash
# Docker: просмотр логов Traefik
docker logs -f traefik

# Поиск ошибок ACME
docker logs traefik 2>&1 | grep -i acme

# Поиск ошибок маршрутизации
docker logs traefik 2>&1 | grep -i "rule"
```

## Устранение неисправностей

### Типовые ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **404 Not Found** | Неверный `Host` в метках/правилах или запрос пришел не на тот Entrypoint. | Проверьте Dashboard (`/api/http/routers`) и конфигурацию провайдера. |
| **502 Bad Gateway** | Приложение слушает `localhost` вместо `0.0.0.0`, неверный порт в `loadbalancer.server.port`, или бэкенд недоступен. | Убедитесь, что приложение доступно внутри сети Traefik. Проверьте health check. |
| **503 Service Unavailable** | Все бэкенды unhealthy или сервис пустой (`allowEmptyServices: false`). | Проверьте статус health check, логи бэкенда, таймауты. |
| **TLS Error (Internal)** | Ошибка выпуска сертификата (Rate limit Let's Encrypt, неправильные права на `acme.json`). | Проверьте логи ACME, права `chmod 600 acme.json`, используйте staging-сервер для тестов. |
| **TLS handshake error** | Сертификат недействителен или не соответствует домену. | Проверьте `certResolver` на роутере, убедитесь что домен указывает на Traefik. |
| **Dashboard не открывается** | Неправильные метки/правила для dashboard router или отсутствие middleware защиты. | Проверьте labels сервиса Traefik, убедитесь что dashboard доступен только через HTTPS. |
| **Bad Gateway (Socket)** | Traefik не может подключиться к `docker.sock`. | Проверьте права на файл сокета или настройки `socket-proxy`. |
| **High CPU / Memory** | Большое количество правил, отсутствие `watch: false` для File provider, или утечка в middleware. | Отключите `watch` для статических файлов, уменьшите количество меток, обновите версию. |

### Диагностические команды

```bash
# Проверка открытых портов Traefik
ss -tlnp | grep traefik

# Проверка доступности бэкенда изнутри сети Traefik
docker exec -it traefik curl -s http://app-backend:8080/health

# Проверка DNS-разрешения (если Traefik использует доменные имена)
docker exec -it traefik nslookup app-backend

# Просмотр логов ACME с детализацией
docker logs traefik 2>&1 | grep -A 5 -B 5 "acme"

# Проверка статуса health check через API
curl -s http://localhost:8080/api/http/services/app-service | jq '.loadBalancer.servers'
```

## Рекомендации

### Безопасность

- **Docker Socket:** Никогда не монтируйте `/var/run/docker.sock` напрямую в продакшене. Используйте `docker-socket-proxy` с минимальными правами (`CONTAINERS=1`, `SERVICES=1`, `TASKS=1`).
- **Dashboard:** Всегда защищайте дашборд middleware `BasicAuth` или `ForwardAuth`. Никогда не открывайте его на публичных entrypoints без TLS.
- **ACME:** Используйте staging-сервер Let's Encrypt для тестирования, чтобы не получить rate limit. Храните `acme.json` на персистентном томе.
- **Секреты:** Не храните хеши `BasicAuth` в открытом виде в Docker-лейблах. Используйте `docker secret` (Swarm) или внешний файл с правами `600`.
- **Сеть:** Ограничьте сетевой доступ к портам Traefik только необходимыми (80, 443). Порт 8080 (Dashboard) не должен быть доступен извне.

### Производительность

- **HTTP/2 и HTTP/3:** Включите HTTP/2 на entrypoint (`http2: true`). Для HTTP/3 откройте UDP-порт 443.
- **Keep-Alive:** Настройте `serversTransport.forwardingTimeouts` для долгоживущих соединений.
- **Connection limits:** Ограничьте глобальный пул соединений с бэкендами через `serversTransport.maxIdleConns` (общий лимит на все бэкенды) и `maxConnsPerHost` (лимит на один бэкенд). По умолчанию нет глобальных ограничений, что при высокой нагрузке может привести к exhaustion файловых дескрипторов.
- **Логирование:** Отключайте debug-логи в продакшене. Используйте буферизацию access log (`bufferingSize`) для снижения I/O.
- **Health Checks:** Настраивайте адекватные интервалы (`interval: 10s`) и таймауты (`timeout: 3s`). Слишком частые проверки создают нагрузку на бэкенды.
- **Развертывание:** Для HA развертываний используйте `mode: host` для портов Traefik (сохранение реального IP) и DNS-01 challenge для ACME.

### Эксплуатация

- **Версионирование:** Фиксируйте версию образа Traefik (например, `traefik:v3.4`), не используйте `latest` в продакшене.
- **Мониторинг:** Включите Prometheus metrics (`metrics.prometheus.enabled: true`) и настройте алерты на 5xx ошибки, latency p99, количество unhealthy бэкендов.
- **Обновления:** Traefik поддерживает graceful restart. Новые версии обрабатывают существующие соединения до их завершения.
- **Резервное копирование:** Регулярно резервируйте `acme.json` и статическую конфигурацию.

## Дополнительная информация

### Сравнение с альтернативами

| Характеристика | Traefik | Nginx Ingress | Envoy | HAProxy |
| :--- | :--- | :--- | :--- | :--- |
| **Сложность настройки** | Низкая (Auto) | Средняя | Высокая | Высокая |
| **Service Discovery** | Native | Через модулы/скрипты | Native (xDS) | Внешние скрипты |
| **SSL Automation** | Встроенная (ACME) | Внешняя | Внешняя | Внешняя |
| **Конфигурация** | Динамическая | Static/Reload | Динамическая (API/xDS) | Static/Runtime API |
| **Основной кейс** | Микросервисы, динамика | Static/High Perf | Service Mesh | Load Balancing, L4-L7 |

### См. также

- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — практическое руководство по развертыванию.
- [Правила и приоритет](./traefik-routers-and-rules.md) — матчеры, ruleSyntax, приоритеты, редиректы.
- [TLS Options и mTLS](./traefik-tls-options.md) — политики шифрования, клиентские сертификаты, passthrough.
- [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md) — forwardedHeaders, X-Forwarded-* за балансировщиком.
- [Протоколы и потоки данных](./traefik-protocols-advanced.md) — gRPC/h2c, HTTP/2-3, WebSocket, TCP/UDP.
- [Middleware для безопасности](./traefik-middlewares-security.md) — аутентификация, IP-фильтры, заголовки/CORS.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, CircuitBreaker, Retry, сжатие.
- [Наблюдаемость Traefik](./traefik-observability.md) — метрики, трейсинг, access log.
- [Провайдеры KV-хранилищ](./traefik-providers-kv-stores.md) — Consul, etcd, Redis, ZooKeeper.
- [Плагины](./traefik-plugins.md) — experimental plugins, каталог.
- [Миграция со v2 на v3](./traefik-migration-v2-to-v3.md) — breaking changes и чек-лист.
- [Docker Swarm Ingress с Traefik](../../Docker_swarm/swarm_ingress_traefik.md) — специфика развертывания в Swarm.
- [Обратный прокси (концепция)](../../Networking/Concepts/proxy.md) — теоретические основы работы прокси-серверов.
- [PROXY Protocol](../../Networking/Protocols/proxy_protocol.md) — передача реального IP клиента через балансировщик.
