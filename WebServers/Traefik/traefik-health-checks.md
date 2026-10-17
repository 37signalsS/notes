# Health Checks в Traefik: активные проверки, gRPC, Failover, Circuit Breaker

**Актуально для:** Traefik v3.x (с замечаниями по обратной совместимости с Traefik v2.x)

## Определения

**Active health check (активная проверка жизнеспособности)** — периодический опрос бэкенд-серверов со стороны Traefik (фоновые HTTP-запросы или gRPC-вызовы к протоколу `grpc.health.v1`). При обнаружении сбоя Traefik исключает конкретный сервер из пула балансировки до восстановления его работоспособности.

**Passive health check (пассивная проверка)** — обнаружение сбоев на основе анализа реального пользовательского трафика (ошибки соединения, таймауты, коды 5xx). В Traefik OSS встроенный пассивный health check на уровне пула серверов отсутствует, но реализуется через middleware `circuitBreaker` (размыкание цепи при превышении порога ошибок) и `retry`.

**Failure threshold и Success threshold** — количество последовательных ошибок для признания сервера неработоспособным (unhealthy) и количество успешных ответов для возврата в пул (healthy). В базовом алгоритме активного health check Traefik переключение статуса происходит немедленно (1 сбой = `DOWN`, 1 успех = `UP`), а сглаживание переходных процессов достигается настройкой интервалов, таймаутов либо внешним оркестратором.

**Health check port override (`port`)** — директива, позволяющая направлять запросы проверки здоровья на специализированный порт управления или метрик (management port), отличный от порта обработки бизнес-трафика.

**gRPC Health Checking Protocol (`mode: grpc`)** — стандартный протокол проверки жизнеспособности gRPC-сервисов (`grpc.health.v1.Health/Check`), при котором опрос выполняется нативным gRPC-клиентом без промежуточной HTTP-эмуляции.

**Failover Service** — тип сервиса в динамической конфигурации Traefik, автоматически перенаправляющий входящий трафик с основного сервиса (`service`) на резервный (`fallback`), если все серверы основного пула признаны неработоспособными проверкой `healthCheck`.

**Traefik Ping Endpoint (`/ping`, `traefik healthcheck`)** — внутренний механизм самодиагностики экземпляра Traefik, предоставляющий HTTP-эндпоинт `/ping` и CLI-команду `traefik healthcheck --ping` для оркестраторов (Docker `HEALTHCHECK`, systemd, Keepalived).

**Flapping (флаппинг серверов)** — циклическое переключение статуса бэкенда (`UP` ↔ `DOWN`), возникающее при слишком жестких таймаутах, высокой нагрузке на приложение или пограничных состояниях сети, приводящее к сбросу сессий и всплескам ошибок.

## Базовые концепции и архитектура

### Принцип работы ServiceHealthChecker

Внутри архитектуры Traefik за мониторинг бэкендов отвечает компонент `ServiceHealthChecker`. Для каждого сервиса, у которого определена секция `healthCheck`, создается независимый цикл проверки на базе Go-таймера (`time.Ticker`):

```mermaid
flowchart TD
    subgraph Traefik Proxy
        Ticker["time.Ticker (интервал interval)"] --> Probe["executeHealthCheck()"]
        Probe -->|mode: http| HTTPCheck["HTTP GET/HEAD на target + path"]
        Probe -->|mode: grpc| GRPCCheck["gRPC Check на grpc.health.v1"]
        HTTPCheck --> Eval{Код ответа валиден?}
        GRPCCheck --> EvalGRPC{Статус SERVING?}
        Eval -- Да --> SetUP["balancer.SetStatus(server, UP)"]
        Eval -- Нет / Таймаут --> SetDOWN["balancer.SetStatus(server, DOWN)"]
        EvalGRPC -- Да --> SetUP
        EvalGRPC -- Нет / Таймаут --> SetDOWN
        SetUP --> Metrics["traefik_service_server_up = 1"]
        SetDOWN --> Metrics0["traefik_service_server_up = 0"]
        SetUP --> RuntimeState["runtime.ServiceInfo: UP"]
        SetDOWN --> RuntimeState2["runtime.ServiceInfo: DOWN"]
    end
    subgraph Backend Servers
        HTTPCheck -.-> Srv1["Бэкенд 1 (/healthz)"]
        HTTPCheck -.-> Srv2["Бэкенд 2 (/healthz)"]
    end
```

1. **Изолированный опрос:** Traefik отправляет запросы непосредственно на IP-адрес/URL каждого сконфигурированного сервера в пуле `servers`.
2. **Мгновенная реакция:** Если запрос завершается сетевой ошибкой, превышением таймаута (`timeout`) или невалидным кодом ответа, сервер немедленно переводится в состояние `DOWN`. Балансировщик прекращает передавать на него новые входящие запросы.
3. **Восстановление:** Как только очередной периодический опрос возвращает успешный ответ, сервер сразу возвращается в состояние `UP`.
4. **Отказ всех серверов:** Если все серверы пула переходят в `DOWN`, Traefik возвращает клиенту код `503 Service Unavailable`, либо передает управление сервису `failover`, если он настроен.

### Поддерживаемые протоколы и архитектурные ограничения

Traefik разделяет динамическую маршрутизацию на уровне протоколов (HTTP, TCP, UDP):

| Протокол сервиса | Поддержка активного `healthCheck` | Механизм реализации в Traefik OSS |
| :--- | :--- | :--- |
| **HTTP / HTTPS** | Полная нативная поддержка | HTTP-запрос (GET, HEAD и др.), проверка статус-кодов |
| **gRPC (h2c / https)** | Полная нативная поддержка | `mode: grpc` через стандарт `grpc.health.v1.Health/Check` |
| **TCP (L4)** | **Отсутствует** на уровне `TCPServersLoadBalancer` | Нативный активный healthcheck для TCP отсутствует. Решается внешними проверками (Consul, Keepalived, Docker) либо вспомогательным HTTP-эндпоинтом приложения |
| **UDP (L4)** | **Отсутствует** | Протокол без установления соединения. Проверки не поддерживаются |

> [!IMPORTANT]
> В секциях `tcp.services.<name>.loadBalancer` и `udp.services.<name>.loadBalancer` директива `healthCheck` не поддерживается схемой Traefik. Попытка указать параметры вида `send`/`expect` в TCP-сервисе игнорируется парсером конфигурации. Для отказоустойчивости TCP-сервисов (PostgreSQL, Redis, RabbitMQ) мониторинг состояния возлагается на оркестратор контейнеров, Keepalived/VRRP либо внешний агент сервисного каталога.

### Параметры конфигурации HTTP Health Check

Все параметры задаются внутри секции `healthCheck` балансировщика сервиса:

| Параметр | Тип | Значение по умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `path` | string | `""` | Обязательный путь эндпоинта проверки (например, `/healthz` или `/api/v1/health`) |
| `interval` | duration | `30s` | Интервал между проверками (рекомендуется `5s`–`10s` для продакшена) |
| `timeout` | duration | `5s` | Таймаут ожидания ответа (должен быть строго меньше `interval`) |
| `method` | string | `"GET"` | HTTP-метод запроса проверки (например, `GET`, `HEAD`) |
| `status` | int | `0` | Ожидаемый точный код HTTP-ответа (например, `200`). Если задан `0`, успешными считаются любые коды в диапазоне `200–399` |
| `port` | int | `0` (порт сервера) | Переопределение порта для проверки (удобно для отдельного management/admin порта) |
| `scheme` | string | scheme сервера | Схема запроса (`http` или `https`) |
| `mode` | string | `"http"` | Режим проверки: `"http"` (стандартный HTTP) или `"grpc"` (gRPC Health Check v1) |
| `hostname` | string | `""` | Значение заголовка `Host`, передаваемое в запросе проверки (для virtual hosts) |
| `followRedirects`| bool | `true` | Следовать ли HTTP-редиректам (3xx) |
| `headers` | map | `{}` | Кастомные заголовки запроса (`X-Health-Check`, токены авторизации) |

### Взаимодействие с Kubernetes Probes (On-Premise / Bare-Metal)

В инфраструктуре под управлением Kubernetes (kubeadm, k3s, RKE2):
- **Kubelet `readinessProbe`** управляет включением pod в объект `Endpoints` / `EndpointSlice`. При падении readiness-пробы Kubelet исключает pod из списка эндпоинтов.
- **Traefik `healthCheck`** выполняет прямые сетевые проверки pod-ов из памяти самого процесса Traefik.

```mermaid
sequenceDiagram
    participant Pod as Backend Pod
    participant Kubelet as Kubelet Probe
    participant K8sAPI as K8s API (EndpointSlice)
    participant Traefik as Traefik Pod

    Pod->>Pod: Внутренний сбой / перегрузка
    par Задержка API K8s (5-15 сек)
        Kubelet->>Pod: GET /health (Readiness)
        Pod-->>Kubelet: 500 Internal Error
        Kubelet->>K8sAPI: Удалить Pod из EndpointSlice
        K8sAPI->>Traefik: Watch Event: Update Endpoints
    and Быстрая реакция Traefik (2-3 сек)
        Traefik->>Pod: GET /health (Traefik HealthCheck)
        Pod-->>Traefik: 500 Internal Error
        Note over Traefik: Сервер немедленно исключен из пула балансировки
    end
```

**Преимущество связки:** Обновление `EndpointSlice` через K8s API и его доставка в Traefik через Watch-информер занимают от 2 до 10 секунд. Активный health check внутри Traefik реагирует за время `interval + timeout` (~2–3 секунды) и защищает пользователей от ошибок во время задержек control plane.

**Ограничение масштабирования (Fan-Out):** При наличии $N$ реплик Traefik и $M$ pod-ов сервиса суммарная нагрузка на health check составляет:
$$\text{RPS}_{\text{health}} = \frac{N \times M}{\text{interval}}$$
Для кластера с 10 репликами Traefik и 20 pod-ами бэкенда при `interval: 2s` бэкенд будет получать 100 проверочных запросов в секунду. Рекомендуется балансировать `interval` в диапазоне `5s–10s`.

## Практические сценарии и конфигурация

### Сценарий 1: Базовый HTTP Health Check (File Provider, YAML)

Базовая настройка пула серверов с проверкой эндпоинта `/healthz`:

```yaml
# /etc/traefik/dynamic/services.yml
http:
  routers:
    web-app-router:
      rule: "Host(`app.internal.example.com`)"
      service: web-app-service
      entryPoints:
        - web

  services:
    web-app-service:
      loadBalancer:
        healthCheck:
          path: /healthz
          interval: 5s
          timeout: 2s
          followRedirects: true
        servers:
          - url: "http://10.0.1.11:8080"
          - url: "http://10.0.1.12:8080"
          - url: "http://10.0.1.13:8080"
```

### Сценарий 2: Продвинутый HTTP Health Check (Port Override, Method, Headers)

Конфигурация для бэкенда, где бизнес-трафик идет на порт `8080`, а проверка здоровья изолирована на порту администрирования `8081`, требует HTTP-метода `HEAD`, кода `200` и авторизационного токена:

```yaml
# /etc/traefik/dynamic/secure-service.yml
http:
  services:
    payment-service:
      loadBalancer:
        healthCheck:
          path: /manage/health
          port: 8081
          method: HEAD
          status: 200
          interval: 10s
          timeout: 2s
          hostname: "payment.internal.local"
          headers:
            X-Health-Check: "traefik-probe"
            Authorization: "Bearer secret-probe-token-string"
        servers:
          - url: "http://10.0.2.21:8080"
          - url: "http://10.0.2.22:8080"
```

### Сценарий 3: Docker Compose стек с Health Check метками

Развертывание Traefik и масштабируемого сервиса приложения на одном хосте. Настройка проверок осуществляется декларативно через labels:

```yaml
# compose.yml
services:
  traefik:
    image: traefik:v3.3
    container_name: traefik
    restart: unless-stopped
    command:
      - "--api.dashboard=true"
      - "--api.insecure=false"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--ping=true"
      - "--ping.entrypoint=traefik"
    ports:
      - "80:80"
      - "127.0.0.1:8080:8080" # Traefik API/Dashboard & Ping
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
    healthcheck:
      test: ["CMD", "traefik", "healthcheck", "--ping"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s

  app:
    image: hashicorp/http-echo:latest
    restart: unless-stopped
    command: ["-text=healthy-backend-response", "-listen=:5678"]
    deploy:
      replicas: 2
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`demo.local`)"
      - "traefik.http.routers.app.entrypoints=web"
      - "traefik.http.services.app.loadbalancer.server.port=5678"
      # Параметры активного health check Traefik:
      - "traefik.http.services.app.loadbalancer.healthcheck.path=/"
      - "traefik.http.services.app.loadbalancer.healthcheck.interval=5s"
      - "traefik.http.services.app.loadbalancer.healthcheck.timeout=2s"
      - "traefik.http.services.app.loadbalancer.healthcheck.status=200"
```

### Сценарий 4: gRPC Health Check (`mode: grpc`)

Проверка gRPC микросервисов по протоколу `grpc.health.v1.Health/Check`. Сервер должен возвращать статус `SERVING`:

```yaml
# /etc/traefik/dynamic/grpc-service.yml
http:
  routers:
    grpc-router:
      rule: "Host(`rpc.example.internal`)"
      service: grpc-service
      entryPoints:
        - web

  services:
    grpc-service:
      loadBalancer:
        healthCheck:
          mode: grpc
          interval: 5s
          timeout: 2s
        servers:
          - url: "h2c://10.0.3.11:50051"
          - url: "h2c://10.0.3.12:50051"
```

> [!NOTE]
> Для gRPC с шифрованием TLS укажите схему `https://` в URL сервера (`https://10.0.3.11:50051`) либо директиву `scheme: https` в секции `healthCheck`.

### Сценарий 5: Failover Service (Автоматическое резервирование)

Если весь основной пул серверов вышел из строя, Traefik автоматически переключает трафик на резервный сервис (например, статический сайт-заглушку или резервный ЦОД):

```yaml
# /etc/traefik/dynamic/failover.yml
http:
  routers:
    core-api-router:
      rule: "Host(`api.example.com`)"
      service: core-api-failover
      entryPoints:
        - web

  services:
    core-api-failover:
      failover:
        service: core-api-primary
        fallback: core-api-fallback
        healthCheck: {}

    core-api-primary:
      loadBalancer:
        healthCheck:
          path: /health
          interval: 3s
          timeout: 1s
        servers:
          - url: "http://10.0.1.10:8080"
          - url: "http://10.0.1.11:8080"

    core-api-fallback:
      loadBalancer:
        servers:
          - url: "http://10.0.99.10:8080" # Сервер страницы технического обслуживания
```

### Сценарий 6: Проверка жизнеспособности самого Traefik (Самодиагностика `/ping`)

Включение внутреннего эндпоинта в статическом файле `traefik.yml`:

```yaml
# /etc/traefik/traefik.yml
entryPoints:
  web:
    address: ":80"
  traefik:
    address: ":8080"

ping:
  entryPoint: "traefik"
  terminatingStatusCode: 503

api:
  dashboard: true
```

Проверка состояния процесса Traefik из systemd (`/etc/systemd/system/traefik.service.d/override.conf`):

```ini
[Service]
ExecStartPost=/usr/bin/traefik healthcheck --ping
```

### Сценарий 7: Kubernetes IngressRoute с Health Check (CRD `traefik.io/v1alpha1`)

Конфигурация для bare-metal кластера Kubernetes с использованием Traefik CRD:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: order-service-route
  namespace: production
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`orders.internal`)
      kind: Rule
      services:
        - name: order-service
          port: 8080
          healthCheck:
            path: /healthz
            interval: "5s"
            timeout: "2s"
            followRedirects: true
```

### Сценарий 8: Пассивный Health Check через комбинацию Circuit Breaker и Retry

Поскольку Traefik OSS не исключает серверы на основе ошибок реального трафика в `loadBalancer`, отказоустойчивость выстраивается цепочкой middleware:

```yaml
# /etc/traefik/dynamic/resilience.yml
http:
  routers:
    resilient-router:
      rule: "Host(`catalog.internal`)"
      service: catalog-service
      entryPoints:
        - web
      middlewares:
        - retry-on-failure
        - service-circuit-breaker

  middlewares:
    # Повторная попытка на соседний сервер пула при сетевом сбое:
    retry-on-failure:
      retry:
        attempts: 3
        initialInterval: 100ms

    # Размыкание цепи при высоком проценте 5xx ошибок:
    service-circuit-breaker:
      circuitBreaker:
        expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.25 || NetworkErrorRatio() > 0.10"
        checkPeriod: 5s
        fallbackDuration: 15s
        recoveryDuration: 10s
        responseCode: 503

  services:
    catalog-service:
      loadBalancer:
        healthCheck:
          path: /health
          interval: 5s
          timeout: 2s
        servers:
          - url: "http://10.0.1.31:8080"
          - url: "http://10.0.1.32:8080"
```

## Операции и команды

### Мониторинг статуса серверов через Traefik API

Traefik предоставляет API для инспекции состояния конфигурации в рантайме:

```bash
# Получение статуса всех серверов сервиса (UP / DOWN)
curl -s http://127.0.0.1:8080/api/http/services/web-app-service@file | jq '.serverStatus'
# → {
# →   "http://10.0.1.11:8080": "UP",
# →   "http://10.0.1.12:8080": "DOWN",
# →   "http://10.0.1.13:8080": "UP"
# → }

# Фильтрация только отключенных (DOWN) бэкендов
curl -s http://127.0.0.1:8080/api/http/services/web-app-service@file | jq '.serverStatus | to_entries[] | select(.value == "DOWN")'
# → {
# →   "key": "http://10.0.1.12:8080",
# →   "value": "DOWN"
# → }
```

### Сбор и аудит метрик Prometheus

Traefik экспортирует gauge-метрику `traefik_service_server_up` для каждого сервера:

```bash
# Запрос метрик состояния серверов
curl -s http://127.0.0.1:8080/metrics | grep "traefik_service_server_up"
# → # HELP traefik_service_server_up Traefik service server status (1 for UP, 0 for DOWN).
# → # TYPE traefik_service_server_up gauge
# → traefik_service_server_up{service="web-app-service@file",url="http://10.0.1.11:8080"} 1
# → traefik_service_server_up{service="web-app-service@file",url="http://10.0.1.12:8080"} 0
# → traefik_service_server_up{service="web-app-service@file",url="http://10.0.1.13:8080"} 1
```

### Проверка работоспособности Traefik CLI

```bash
# Вызов встроенной утилиты проверки Traefik
traefik healthcheck --ping
# → OK
# → echo $? вернет 0

# Прямой HTTP запрос к эндпоинту пинга
curl -i http://127.0.0.1:8080/ping
# → HTTP/1.1 200 OK
# → Content-Type: text/plain; charset=utf-8
# → Date: Sat, 17 Oct 2026 13:00:00 GMT
# → Content-Length: 2
# → 
# → OK
```

### Ручная валидация эндпоинтов бэкендов

```bash
# Ручная симуляция запроса Traefik к HTTP бэкенду
curl -s -o /dev/null -w "%{http_code} time_total=%{time_total}s\n" http://10.0.1.11:8080/healthz
# → 200 time_total=0.003s

# Проверка стандартного gRPC health check через grpcurl
grpcurl -plaintext 10.0.3.11:50051 grpc.health.v1.Health/Check
# → {
# →   "status": "SERVING"
# → }
```

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Все серверы помечены как DOWN (HTTP 503)** | Некорректный `path`, бэкенд возвращает код $\ge 400$, либо срабатывает сетевой таймаут | `curl -i http://<backend_ip>:<port><path>` с хоста Traefik | Исправьте путь эндпоинта или параметр `status`. Проверьте сетевую связность и firewall (iptables/nftables) |
| **Флаппинг (сервер циклически переходит UP/DOWN)** | Слишком агрессивный `timeout` ($\le 1s$) при высокой нагрузке на бэкенд | Логи Traefik: `Health check failed: context deadline exceeded` | Увеличьте `timeout` (до 2s–3s) и `interval` (до 5s–10s). Убедитесь, что health check эндпоинт не выполняет тяжелых операций |
| **gRPC health check завершается ошибкой** | Бэкенд не реализует интерфейс `grpc.health.v1.Health` | Ошибка в логах Traefik: `gRPC server does not implement the health protocol: code = Unimplemented` | Реализуйте стандартный обработчик `grpc.health.v1` в приложении либо переключитесь на HTTP health check по вспомогательному порту |
| **Health check возвращает ошибку на 3xx редирект** | По умолчанию редирект разрешен, но бэкенд перенаправляет на внешний HTTPS хост или путь, где возвращается 404/403 | `curl -IL http://<backend_ip>:<port><path>` | Укажите конечный эндпоинт в `path` без промежуточных редиректов. Если требуется запретить переход по редиректам, установите `followRedirects: false` |
| **Health check запросы забивают access-лог** | Высокая частота опроса при множестве бэкендов | Быстрый рост файла `/var/log/traefik/access.log` записями с кодом 200 на эндпоинт `/health` | Настройте фильтр в статической конфигурации `accessLog.filters.statusCodes` (например, логировать только ошибки `400-599`) |
| **Большой всплеск RPS на бэкенд при масштабировании Traefik** | Fan-out эффект: каждая реплика Traefik независимо опрашивает каждый бэкенд | Анализ метрик RPS бэкенда на `/healthz` | Увеличьте `interval` до 10s–15s либо используйте `readinessProbe` оркестратора вместо плотного Traefik health check |
| **HealthCheck в TCP-сервисе игнорируется** | Директива `healthCheck` указана в секции `tcp.services` | Traefik запускается, но бэкенды никогда не исключаются при падении порта | Активный `healthCheck` поддерживается только для HTTP/gRPC. Для TCP используйте внешние средства (Consul, Keepalived, Docker healthcheck) |

## Рекомендации и Best Practices

1. **Изолируйте логику проверок жизнеспособности:**
   - Эндпоинт `/healthz` (или `/live`) должен быть максимально легковесным (проверка работы рантайма процесса в памяти).
   - Не выполняйте тяжелые SQL-запросы к базе данных или внешним API внутри ежесекундного health check. Сбой внешней базы данных не должен приводить к одновременному падению всех экземпляров веб-серверов в статус `DOWN`.
2. **Соблюдайте пропорции таймингов:**
   - Таймаут должен составлять не более половины интервала: $\text{timeout} \le \frac{\text{interval}}{2}$.
   - Рекомендуемый стандарт для критичных сервисов: `interval: 5s`, `timeout: 2s`.
   - Для фоновых или низконагруженных сервисов: `interval: 15s`, `timeout: 3s`.
3. **Используйте выделенный порт управления (`port`):**
   - Если приложение поддерживает разделение сетевых интерфейсов, выносите метрики и проверку здоровья на внутренний порт (например, `8081` или `9090`), закрытый от внешнего периметра, и настраивайте директиву `port: 8081` в Traefik `healthCheck`.
4. **Настройте алертинг в Prometheus (Alertmanager):**
   - Создайте правило на полную недоступность сервиса:
     ```yaml
     - alert: TraefikServiceAllBackendsDown
       expr: count by (service) (traefik_service_server_up == 1) == 0
       for: 15s
       labels:
         severity: critical
       annotations:
         summary: "Все бэкенды сервиса {{ $labels.service }} недоступны"
     ```
   - Создайте предупреждающее правило на деградацию пула:
     ```yaml
     - alert: TraefikServiceDegraded
       expr: sum by (service) (traefik_service_server_up == 0) / count by (service) (traefik_service_server_up) > 0.5
       for: 1m
       labels:
         severity: warning
       annotations:
         summary: "Более 50% серверов сервиса {{ $labels.service }} в статусе DOWN"
     ```
5. **Предотвращайте эффект лавины (Thundering Herd) через Failover Service:**
   - Всегда определяйте резервный статический бэкенд через сервис типа `failover`, чтобы при аварии всего основного пула клиенты получали информативную страницу состояния (Maintenance mode), а не тайм-аут или аварийный ответ балансировщика.
6. **Комбинируйте активный Health Check с Circuit Breaker и Retry:**
   - Активный health check исключает уже отказавший сервер из пула, а связка `retry` + `circuitBreaker` перехватывает единичные сбои "на лету" до завершения интервала следующего опроса.

## Дополнительная информация

- [Архитектурный обзор Traefik](./traefik_overview.md) — базовые сущности: Routers, Middlewares, Services, балансировка нагрузки
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — развертывание, декларативные labels, встроенный ping
- [Circuit Breaker и Retry в Traefik](./traefik-circuit-breaker-retry.md) — настройка пассивных проверок, выражений для ошибок и latency
- [Traefik в Kubernetes](./traefik-kubernetes.md) — probes, EndpointSlice, IngressRoute и отказоустойчивость
- [Мониторинг и наблюдаемость Traefik](./traefik-observability.md) — экспорт метрик Prometheus, конфигурация access log и трассировки
- [Traefik на Bare-Metal](./traefik-bare-metal.md) — высокодоступные схемы с Keepalived, systemd и локальными провайдерами
- [Расширенные протоколы Traefik](./traefik-protocols-advanced.md) — маршрутизация gRPC, TCP и UDP
