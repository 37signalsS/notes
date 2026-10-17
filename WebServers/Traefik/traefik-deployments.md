# Развертывание Traefik: Blue/Green, Canary, Rolling Update

**Актуально для:** Traefik v3.3+ (с поддержкой v2.11+)

## Определения

**Blue/Green deployment (Сине-зеленое развертывание)** — стратегия развертывания с поддержанием двух идентичных сред (Blue — продуктивная версия, Green — новая версия). Переключение трафика между средами выполняется атомарно на уровне балансировщика без деградации сервиса.

**Canary deployment (Канареечный релиз)** — стратегия постепенного перенаправления части продуктивного трафика (например, 1% → 5% → 25% → 100%) на новую версию приложения для раннего выявления сбоев на основе мониторинга SLO/метрик.

**Weighted Round Robin (WRR)** — алгоритм взвешенной балансировки, распределяющий запросы между сервисами или наборами бэкендов пропорционально заданным числовым весам.

**Traffic Mirroring (Shadowing / Теневой трафик)** — дублирование входящего потока реальных запросов на изолированный сервис-кандидат без отправки ответов клиенту и без влияния на критический путь обработки.

**Rolling Update (Последовательное обновление)** — постепенная замена реплик старой версии приложения на новые с поддержанием заданного минимума доступных инстансов.

**TraefikService** — нативный Kubernetes Custom Resource Definition (CRD) в Traefik (`traefik.io/v1alpha1`), объединяющий несколько сервисов в единый виртуальный сервис с поддержкой Weighted Round Robin, Failover и Mirroring.

**Connection Draining (Graceful Drain)** — процедура вывода узла или пода из пула балансировки: прекращение приема новых соединений и ожидание завершения обработки уже принятых запросов до принудительной остановки процесса.

**Progressive Delivery (Прогрессивная поставка)** — методология контролируемого выпуска изменений, объединяющая канареечные релизы, автоматический анализ телеметрии и автоматический откат при нарушении пороговых значений.

## Архитектура и принципы работы

### Взвешенное распределение запросов (WRR) в Traefik

В Traefik балансировка реализуется на уровне компонента **Service**. Для реализации прогрессивной доставки Traefik формирует составные (composite) сервисы, где дочерними элементами выступают конечные сервисы версий:

```
                  ┌──────────────────────┐
                  │    HTTP Router       │ (Host, Path, Header)
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │ Traefik WRR Service  │ (app-canary)
                  └─────┬──────────┬─────┘
           Weight: 90   │          │   Weight: 10
     ┌──────────────────┘          └──────────────────┐
     ▼                                                ▼
┌───────────────────────┐                    ┌───────────────────────┐
│ Service: app-v1 (old) │                    │ Service: app-v2 (new) │
│ Replicas: 10.0.1.X    │                    │ Replicas: 10.0.2.X    │
└───────────────────────┘                    └───────────────────────┘
```

1. **Расчет долей:** Веса задаются целыми числами (`weight: 90` и `weight: 10`). Трафик делится как отношение веса сервиса к сумме весов всех сервисов в группе:
   $$\text{Ratio}_i = \frac{\text{Weight}_i}{\sum_{k=1}^N \text{Weight}_k}$$
2. **Нулевой вес:** Если сервису присваивается `weight: 0`, Traefik полностью исключает его из маршрутизации новых запросов, сохраняя определение сервиса в конфигурации (идеально для Blue/Green переключения).
3. **Взаимодействие со Sticky Sessions:** При включении механизма `sticky` сессионная cookie может назначаться как на уровне WRR-сервиса, так и на уровне конечных бэкендов. Если cookie зафиксирована на уровне WRR, клиент «привязывается» к определенной версии (v1 или v2) на весь срок жизни сессии, предотвращая скачки между версиями UI/API во время канареечного теста.

### Механика Traffic Mirroring (Теневое тестирование)

Traefik позволяет клонировать входящие запросы:

- Основной запрос передается в целевой сервис (`service`). Ответ этого сервиса возвращается клиенту.
- Копия запроса асинхронно отправляется в один или несколько теневых сервисов (`mirrors`). Ответы теневых сервисов считываются и отбрасываются Traefik, статус-коды и ошибки теневого бэкенда не влияют на пользователя.
- **Критический аспект SRE/Sysadmin:** Зеркалирование безопасно для идемпотентных запросов (`GET`, `HEAD`). Для мутирующих запросов (`POST`, `PUT`, `DELETE`) теневое зеркалирование без изоляции базы данных приведет к повторному списанию средств или дублированию записей. Решение — разделение роутеров по методам либо использование изолированного sandbox-бэкенда.

### Жизненный цикл подов и гонки при Rolling Update

Во время Rolling Update в Kubernetes возникает задержка между событиями контроллера и фактическим состоянием сети:

```
1. Kubelet получает команду удалить Pod.
   ├── A. Pod переходит в статус Terminating.
   ├── B. EndpointSlice Controller получает событие -> удаляет IP пода из EndpointSlice.
   └── C. Kubelet посылает SIGTERM процессу в контейнере.
2. Traefik Provider получает обновление EndpointSlice через API Watcher.
```

Если шаг **1.C** завершается быстрее, чем Traefik обрабатывает шаг **2**, Traefik направляет запросы на IP пода, который уже закрыл сокет или завершился. Клиенты получают ошибки **HTTP 502 Bad Gateway**.

Для достижения истинного Zero-Downtime требуются два механизма:
- **`lifecycle.preStop` hook** на стороне приложения: задержка остановки (`sleep 5`), позволяющая Traefik удалить IP пода из балансировки до отправки `SIGTERM`.
- **Middleware `Retry`** в Traefik: автоматический повтор запроса к следующему доступному серверу в случае сбоя сетевого подключения.

---

## Практические сценарии

### Сценарий 1: Blue/Green переключение через Dynamic File Provider

Базовый сценарий для Docker Compose или Bare-Metal сред без Kubernetes. Переключение выполняется атомарным изменением весов в dynamic-файле, который Traefik отслеживает без перезапуска.

```yaml
# /etc/traefik/dynamic/app-blue-green.yml
http:
  routers:
    app-prod:
      rule: Host(`app.example.com`)
      entryPoints:
        - websecure
      service: app-switch
      tls: {}

  services:
    app-switch:
      weighted:
        services:
          - name: app-blue
            weight: 100  # Активная среда Blue
          - name: app-green
            weight: 0    # Пассивная среда Green (прогрета и проверена)

    app-blue:
      loadBalancer:
        servers:
          - url: http://10.0.1.11:8080
          - url: http://10.0.1.12:8080
        healthCheck:
          path: /healthz
          interval: 5s
          timeout: 2s

    app-green:
      loadBalancer:
        servers:
          - url: http://10.0.2.21:8080
          - url: http://10.0.2.22:8080
        healthCheck:
          path: /healthz
          interval: 5s
          timeout: 2s
```

Атомарный переход на Green (Cutover):
```yaml
# Изменение в /etc/traefik/dynamic/app-blue-green.yml
    app-switch:
      weighted:
        services:
          - name: app-blue
            weight: 0    # Отключение Blue
          - name: app-green
            weight: 100  # Весь трафик идет на Green
```

### Сценарий 2: Canary через Kubernetes TraefikService CRD

Нативная реализация взвешенного канареечного релиза в Kubernetes с помощью CRD `traefik.io/v1alpha1`.

```yaml
# 1. Объединяющий взвешенный сервис TraefikService
apiVersion: traefik.io/v1alpha1
kind: TraefikService
metadata:
  name: payment-service-wrr
  namespace: prod
spec:
  weighted:
    services:
      - name: payment-stable
        port: 8080
        weight: 90
      - name: payment-canary
        port: 8080
        weight: 10
---
# 2. Основной маршрутизатор IngressRoute
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: payment-ingress
  namespace: prod
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`payment.example.com`)
      kind: Rule
      services:
        - name: payment-service-wrr
          kind: TraefikService
  tls:
    secretName: payment-tls-cert
```

Этапы канареечного продвижения:
1. `payment-canary: 5`, `payment-stable: 95` (проверка базовых метрик 15 минут).
2. `payment-canary: 25`, `payment-stable: 75` (нагрузочный тест реальным потоком).
3. `payment-canary: 100`, `payment-stable: 0` (релиз принят).
4. Обновление основного deployment `payment-stable` до новой версии и сброс веса canary на 0.

### Сценарий 3: Canary через Kubernetes Gateway API (HTTPRoute)

Стандартизированный подход Kubernetes Gateway API, поддерживаемый Traefik v3.x. Не требует специфичных CRD Traefik.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: billing-route
  namespace: prod
spec:
  parentRefs:
    - name: traefik-gateway
      namespace: traefik
  hostnames:
    - "billing.example.com"
  rules:
    - backendRefs:
        - name: billing-v1
          port: 8080
          weight: 85
        - name: billing-v2
          port: 8080
          weight: 15
```

### Сценарий 4: A/B тестирование и Canary по заголовкам/Cookie с явным Priority

Позволяет тестировать канареечную версию внутренним сотрудникам или пользователям с определенным токеном/cookie, не затрагивая общий поток.

> [!IMPORTANT]
> Traefik вычисляет приоритет роутеров по умолчанию на основе длины строкового выражения правила (`len(rule)`). Чтобы более короткое правило случайно не перехватило трафик или не возникло конфликтов, всегда явно указывайте директиву `priority`.

```yaml
http:
  routers:
    # 1. Маршрут для QA / разработчиков по специальному заголовку
    app-canary-header:
      rule: Host(`app.example.com`) && Header(`X-Canary-Access`, `internal-beta`)
      entryPoints: [websecure]
      service: app-v2
      priority: 100
      tls: {}

    # 2. Маршрут для группы бета-тестеров по Cookie
    app-canary-cookie:
      rule: Host(`app.example.com`) && HeadersRegexp(`Cookie`, `.*beta_tester=true.*`)
      entryPoints: [websecure]
      service: app-v2
      priority: 90
      tls: {}

    # 3. Базовый продуктивный маршрут для всех остальных пользователей
    app-stable:
      rule: Host(`app.example.com`)
      entryPoints: [websecure]
      service: app-v1
      priority: 10
      tls: {}

  services:
    app-v1:
      loadBalancer:
        servers:
          - url: http://app-v1:8080
    app-v2:
      loadBalancer:
        servers:
          - url: http://app-v2:8080
```

### Сценарий 5: Traffic Mirroring (Shadow Deployment) с фильтрацией мутаций

Безопасное теневое тестирование новой версии сервиса на 20% реального входящего трафика. Мутирующие методы изолируются и не отправляются в зеркало.

```yaml
http:
  routers:
    # Безопасное зеркалирование только для GET и HEAD
    app-shadow-reads:
      rule: Host(`api.example.com`) && Method(`GET`, `HEAD`)
      entryPoints: [websecure]
      service: shadow-service
      priority: 50
      tls: {}

    # Мутирующие запросы идут строго на production без зеркалирования
    app-direct-writes:
      rule: Host(`api.example.com`) && Method(`POST`, `PUT`, `DELETE`, `PATCH`)
      entryPoints: [websecure]
      service: app-production
      priority: 50
      tls: {}

  services:
    shadow-service:
      mirroring:
        service: app-production
        mirrors:
          - name: app-candidate
            percent: 20

    app-production:
      loadBalancer:
        servers:
          - url: http://app-prod-svc:8080

    app-candidate:
      loadBalancer:
        servers:
          - url: http://app-canary-svc:8080
```

### Сценарий 6: Zero-Downtime Rolling Update бэкендов в Kubernetes

Конфигурация инфраструктуры для исключения ошибок `502 Bad Gateway` во время ротации подов приложения.

1. **Конфигурация пода приложения (`Deployment`):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-app
  namespace: prod
spec:
  replicas: 4
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: app
          image: internal-registry.local/payment:v2.1.0
          lifecycle:
            preStop:
              exec:
                # Пауза перед SIGTERM для синхронизации EndpointSlice и Traefik
                command: ["/bin/sh", "-c", "sleep 5"]
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 3
            periodSeconds: 3
```

2. **Защитный Middleware `Retry` в Traefik:**

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: retry-on-disconnect
  namespace: prod
spec:
  retry:
    attempts: 3
    initialInterval: 100ms
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: payment-ingress
  namespace: prod
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`payment.example.com`)
      kind: Rule
      middlewares:
        - name: retry-on-disconnect
      services:
        - name: payment-app
          port: 8080
```

### Сценарий 7: Rolling Update инстансов самого Traefik

Обновление ingress-контроллера без сброса активных клиентских соединений.

```yaml
# PodDisruptionBudget: защита от одновременного сноса всех реплик
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik-pdb
  namespace: traefik
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
---
# Deployment Traefik (фрагмент)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: traefik
  namespace: traefik
spec:
  replicas: 3
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: traefik
          image: traefik:v3.3.4
          lifecycle:
            preStop:
              exec:
                # Внешний L4 LB (MetalLB/Keepalived) исключит ноду по /ping за 5-10 секунд
                command: ["/bin/sh", "-c", "sleep 10"]
          args:
            - "--ping=true"
            - "--ping.entrypoint=traefik"
            # Graceful shutdown:
            - "--entrypoints.websecure.transport.lifecycle.requestacceptgracetimeout=5s"
            - "--entrypoints.websecure.transport.lifecycle.gracetimeout=30s"
          readinessProbe:
            httpGet:
              path: /ping
              port: 9000
            periodSeconds: 2
            failureThreshold: 2
```

### Сценарий 8: Автоматизация Canary через Flagger и метрики Prometheus

Flagger автоматизирует управление объектами `TraefikService`, анализируя метрики из Prometheus.

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: payment-app
  namespace: prod
spec:
  provider: traefik
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-app
  progressDeadlineSeconds: 120
  service:
    port: 8080
    targetPort: 8080
  analysis:
    interval: 30s
    threshold: 3
    maxWeight: 50
    stepWeight: 10
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99
        interval: 30s
      - name: request-duration
        thresholdRange:
          max: 500
        interval: 30s
    webhooks:
      - name: load-test
        url: http://flagger-loadtester.prod/
        timeout: 5s
        metadata:
          type: cmd
          cmd: "hey -z 1m -q 20 -c 2 http://payment-app-canary.prod:8080/"
```

---

## Операции и команды

### 1. Тестирование распределения трафика Canary через curl

Запуск тестовой серии запросов для проверки фактического распределения весов (например, 90/10):

```bash
# Отправка 100 запросов и подсчет распределения по возвращаемому заголовку X-Version
for i in {1..100}; do
  curl -s -k -I https://app.example.com | grep -i "x-app-version"
done | sort | uniq -c
# → 90 X-App-Version: v1.0.0
# → 10 X-App-Version: v2.0.0
```

Проверка маршрута A/B тестирования по заголовку:

```bash
curl -s -k -H "X-Canary-Access: internal-beta" -I https://app.example.com | grep "HTTP/"
# → HTTP/2 200

curl -s -k -H "X-Canary-Access: internal-beta" https://app.example.com/api/version
# → {"version":"v2.0.0-rc1","status":"canary"}
```

### 2. Управление и инспекция TraefikService в Kubernetes

```bash
# Просмотр всех взвешенных сервисов Traefik в кластере
kubectl get traefikservices.traefik.io -n prod
# → NAME                  AGE
# → payment-service-wrr   5d

# Инспекция текущих весов сервиса
kubectl get traefikservice payment-service-wrr -n prod -o jsonpath='{.spec.weighted.services}' | jq .
# → [
# →   {
# →     "name": "payment-stable",
# →     "port": 8080,
# →     "weight": 90
# →   },
# →   {
# →     "name": "payment-canary",
# →     "port": 8080,
# →     "weight": 10
# →   }
# → ]

# Оперативное изменение веса (например, перевод canary на 25%)
kubectl patch traefikservice payment-service-wrr -n prod --type='json' -p='[
  {"op": "replace", "path": "/spec/weighted/services/0/weight", "value": 75},
  {"op": "replace", "path": "/spec/weighted/services/1/weight", "value": 25}
]'
# → traefikservice.traefik.io/payment-service-wrr patched
```

### 3. Инспекция состояния через Traefik API и Prometheus

```bash
# Проброс порта к API Traefik (порт 8080)
kubectl port-forward -n traefik deployment/traefik 9000:8080 &

# Проверка состояния WRR сервиса через REST API
curl -s http://localhost:9000/api/http/services/payment-service-wrr@kubernetescrd | jq '{status: .status, type: .type, weighted: .weighted}'
# → {
# →   "status": "enabled",
# →   "type": "weighted",
# →   "weighted": {
# →     "services": [
# →       {"name": "prod-payment-stable-8080@kubernetescrd", "weight": 75},
# →       {"name": "prod-payment-canary-8080@kubernetescrd", "weight": 25}
# →     ]
# →   }
# → }

# Сбор метрик распределения запросов по сервисам из Prometheus эндпоинта
curl -s http://localhost:9000/metrics | grep 'traefik_service_requests_total{service="prod-payment'
# → traefik_service_requests_total{code="200",method="GET",protocol="http",service="prod-payment-stable-8080@kubernetescrd"} 14205
# → traefik_service_requests_total{code="200",method="GET",protocol="http",service="prod-payment-canary-8080@kubernetescrd"} 4735
```

---

## Устранение неисправлений

| Симптом / Ошибка | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| **Ошибки `502 Bad Gateway` во время Rolling Update бэкендов** | Traefik пытается доставить запрос на под, получивший SIGTERM, до обновления EndpointSlice. | Добавьте в контейнер пода `lifecycle.preStop: exec: command: ["sleep", "5"]` и подключите Middleware `Retry` (`attempts: 3`) на IngressRoute. |
| **Канареечный трафик не балансируется (100% идет на одну версию)** | Включен `sticky` cookie на уровне балансировщика, и сессии клиентов залипают. | Проверьте директиву `sticky` в `loadBalancer`. Для честного тестирования снимите sticky-куку при нагрузочном тесте либо тестируйте новыми сессиями без кук (`curl -c /dev/null`). |
| **A/B роутер не перехватывает запросы по заголовку** | Автоматический `priority` роутера оказался ниже базового правила, либо конфликт в правиле `Host`. | Установите явный `priority: 100` для селективного роутера и `priority: 10` для дефолтного роутера в конфигурации. |
| **Зеркалирование трафика (Shadow) порождает дубликаты записей в БД** | Мутирующие HTTP-запросы (`POST`, `PUT`, `PATCH`) отправляются в зеркало без фильтрации методов. | Разделите роутеры: отправляйте в зеркало только `Method('GET', 'HEAD')`, либо направляйте теневой сервис в изолированную копию БД. |
| **TraefikService имеет статус `disabled` в API Dashboard** | Порт дочернего сервиса не совпадает с реальным Service port в K8s, либо сервис не найден. | Проверьте соответствие `spec.weighted.services[].port` реальному порту K8s Service (`kubectl describe svc <name>`). |
| **Трафик зависает при выкатке новой версии Traefik** | Внешний L4 балансировщик (MetalLB/Keepalived) медленно определяет отказ узла. | Настройте health-check внешнего балансировщика на эндпоинт `/ping` с `interval: 2s` и добавьте `preStop: sleep 10` в deployment Traefik. |

---

## Рекомендации и лучшие практики

1. **Минимальный порог канарейки:** Не устанавливайте начальный вес канарейки менее 5% на высоконагруженных системах или менее 10–20 запросов/сек, иначе статистические метрики задержки (p95/p99) и ошибок будут зашумлены и не позволят сделать объективный вывод о надежности.
2. **Обязательное использование preStop hook:** Всегда конфигурируйте `sleep 5` в `lifecycle.preStop` контейнеров за Traefik. Время остановки приложения гарантированно должно быть больше задержки распространения сетевых эндпоинтов в Kubernetes.
3. **Включение Retry Middleware:** Всегда подключайте middleware с типом `retry` (`attempts: 3`, `initialInterval: 100ms`) к продуктивным IngressRoute. Это полностью устраняет кратковременные всплески сетевых ошибок при смене топологии подов.
4. **Явные приоритеты роутеров (`priority`):** Никогда не полагайтесь на автоматический расчет приоритетов по длине строки при реализации A/B тестирования или канареечных исключений.
5. **Безопасность Mirroring:** При теневом деплое обязательно изолируйте сервис-зеркало от продуктивных внешних очередей, платёжных шлюзов и баз данных на запись.
6. **Автоматизация через Flagger / Argo Rollouts:** В production-окружениях избегайте ручной смены весов в YAML. Используйте операторы прогрессивной доставки, автоматически откатывающие релиз при выходе метрик за допустимые пределы SLO.

---

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — базовая архитектура, роутеры, сервисы и middleware.
- [Graceful Shutdown и Zero-Downtime Deploy в Traefik](./traefik-graceful-shutdown.md) — детальная настройка systemd, preStop, SIGTERM и жизненного цикла соединений Traefik.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — CircuitBreaker, RateLimit, Buffering и Retry.
- [Traefik в Kubernetes: CRD, RBAC, Helm, NetworkPolicy](./traefik-kubernetes.md) — полное руководство по CRD и интеграции в кластер.
- [Traefik — реализация Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md) — спецификация Gateway API, HTTPRoute и GAMMA.
- [Автоматический канареечный релиз в GitOps](./traefik-gitops.md) — интеграция Flagger и ArgoCD с Traefik.
- [Сине-зеленое развертывание (Blue-Green Deployment)](../../CI-CD/Deployment_Strategies/blue_green_deployment.md) — общесистемная теория и паттерны Cutover.
- [Канареечное развертывание (Canary Deployment)](../../CI-CD/Deployment_Strategies/canary_deployment.md) — мониторинг, Blast Radius и автоматический гейтинг.
