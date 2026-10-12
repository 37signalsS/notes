# Каскадное масштабирование микросервисов (Cascading Scaling)

**Актуально для:** Kubernetes 1.28–1.35 (HPA autoscaling/v2, Ingress-NGINX 1.10+, Istio 1.22+)

## Определения

**Каскадное масштабирование (Cascading Scaling)** — процесс, при котором горизонтальное автомасштабирование одного сервиса (upstream) инициирует пропорциональный или лавинообразный рост нагрузки на зависимые компоненты (downstream), вызывая цепную реакцию масштабирования по всему графу вызовов.

**Узкое место (Bottleneck)** — компонент распределенной системы, чья предельная пропускная способность ограничивает общую производительность инфраструктуры. При каскадном масштабировании узким местом выступает компонент, который не поддерживает горизонтальное масштабирование (например, реляционная СУБД, хранилище на базе ReadWriteOnce PV) либо масштабируется медленнее входящего потока запросов.

**Задержка сквозного масштабирования (Trickle-down Scaling Lag)** — совокупное время между моментом всплеска трафика на upstream-сервисе и моментом, когда downstream-сервис вводит в эксплуатацию достаточный объем вычислительных ресурсов. Складывается из: интервала опроса HPA контроллером, времени планирования подов планировщиком (kube-scheduler), задержки загрузки образов контейнеров, инициализации рантайма и прохождения `readinessProbe`.

**Запас емкости (Capacity Headroom)** — превентивно зарезервированный пул вычислительных ресурсов (CPU, Memory, IOPS, сетевые сокеты), предназначенный для поглощения пиковых всплесков нагрузки в интервале реакции автомасштабирования без деградации времени отклика.

**Спираль смерти / Лавинообразный отказ (Death Spiral / Cascading Failure)** — аварийный режим, при котором перегрузка downstream-сервиса приводит к задержкам ответов и тайм-аутам на upstream, вызывая повторные попытки запросов (retries), рост очередей, ложное срабатывание HPA upstream-уровня и окончательный отказ всей системы.

**Обратная связь по нагрузке (Backpressure)** — механизм сигнализации о насыщении downstream-компонента, при котором upstream принудительно замедляет генерацию запросов, помещает их во временный буфер либо сбрасывает с управляемым статусом ошибки (HTTP 429 / 503).

**Сброс нагрузки (Load Shedding)** — техника защиты сервиса от деградации, при которой при достижении пороговых задержек или исчерпании пула потоков низкоприоритетные запросы отбрасываются до их обработки приложением.

**Автоматический выключатель (Circuit Breaker)** — паттерн отказоустойчивости, отслеживающий ошибки и задержки downstream-сервиса и превентивно разрывающий сетевые вызовы при превышении лимита отказов для предотвращения истощения ресурсов клиента.

---

## Предварительные требования

Перед проектированием и внедрением многоуровневого автомасштабирования в кластере Kubernetes необходимо обеспечить соблюдение базовых инфраструктурных требований:

1. **Метрики кластера (Metrics Server):**
   Развернут и работоспособен `metrics-server` для предоставления базовых метрик ресурсов:
   ```bash
   kubectl get apiservice v1beta1.metrics.k8s.io
   # → NAME                     SERVICE                      AVAILABLE   AGE
   # → v1beta1.metrics.k8s.io   kube-system/metrics-server   True        42d
   ```

2. **Custom / External Metrics Adapter:**
   Для масштабирования по L7-метрикам (RPS, latency, глубина очередей) развернут Prometheus Adapter или KEDA:
   ```bash
   kubectl get apiservice v1beta1.custom.metrics.k8s.io
   # → NAME                            SERVICE                                      AVAILABLE   AGE
   # → v1beta1.custom.metrics.k8s.io   monitoring/prometheus-adapter                True        42d
   ```

3. **Корректные декларации ресурсов:**
   У всех контейнеров каждого участвующего сервиса в обязательном порядке определены `resources.requests` и `resources.limits`. Отсутствие `requests` переводит HPA в состояние `<unknown>`.

4. **Инфраструктурная изоляция:**
   Наличие сетевого контроллера Ingress (Ingress-NGINX) и/или Service Mesh (Istio / Envoy) для реализации Rate Limiting и Circuit Breaking на сетевых границах.

5. **Пул соединений к базам данных:**
   Наличие проксирующего слоя соединений (PgBouncer, ProxySQL) перед реляционными СУБД для предотвращения исчерпания серверных дескрипторов соединений при резком масштабировании подов.

---

## Архитектура и принципы работы

### Архитектура многоуровневой цепочки вызовов

```
                         ┌────────────────────────┐
                         │ Ingress-NGINX (Daemon) │
                         │ Rate Limit, Conn Limit │
                         └───────────┬────────────┘
                                     │
                         ┌───────────▼────────────┐
                         │     Frontend (HPA)     │
                         │   Target: RPS / CPU    │
                         └───────────┬────────────┘
                                     │
               ┌─────────────────────┼─────────────────────┐
               │                     │                     │
     ┌─────────▼───────────┐ ┌───────▼───────────┐ ┌───────▼───────────┐
     │   API Gateway (HPA) │ │  Auth Service(HPA)│ │ Rate Limiter (HPA)│
     │ Target: Concurrency │ │    Target: CPU    │ │  Target: QPS/Mem  │
     └─────────┬───────────┘ └───────────────────┘ └───────────────────┘
               │
     ┌─────────▼───────────┐
     │  Backend Tier (HPA) │
     │   Target: CPU / QPS │
     └─────────┬───────────┘
               │
     ┌─────────▼───────────┐
     │ Connection Pooler   │
     │ (PgBouncer / Proxy) │
     └─────────┬───────────┘
               │
     ┌─────────▼───────────┐
     │  Database / Storage │
     │ (StatefulSet / Bare)│
     └─────────────────────┘
```

### Типы каскадных явлений

#### 1. Прямой каскад (Direct Cascade)

Upstream-сервис (Frontend) получает резкий всплеск внешнего трафика. HPA увеличивает количество реплик Frontend с 3 до 30. Каждая новая реплика начинает генерировать сетевые запросы к downstream-сервису (Backend).
- **Следствие:** Downstream получает суммарный поток, кратно превышающий его базовую пропускную способность.
- **Риск:** Если downstream масштабируется медленнее (Trickle-down Lag) или упирается в `maxReplicas`, его очереди переполняются, CPU утилизируется на 100%, а запросы от Frontend получают статус HTTP 504 Gateway Timeout.

#### 2. Обратный каскад и спираль смерти (Reverse Cascade & Death Spiral)

Downstream-сервис (например, база данных или сервис генерации отчетов) начинает испытывать высокую задержку ответов (high latency p99).
- **Механизм развития:**
  1. Потоки Frontend блокируются в ожидании ответов от Backend.
  2. Из-за блокировки пулов потоков растет потребление CPU и памяти на подах Frontend, а также скапливается очередь входящих HTTP-запросов.
  3. HPA Frontend считывает возросшую утилизацию CPU и инициирует добавление новых подов Frontend.
  4. Новые поды Frontend посылают дополнительные параллельные запросы к уже перегруженному Backend.
  5. Backend окончательно теряет способность отвечать, поды начинают падать по OOMKilled или проваливать `readinessProbe`.
  6. Нагрузка перераспределяется на оставшиеся поды, вызывая мгновенный каскадный отказ всей системы.

#### 3. Параллельный каскад и истощение ресурсов узлов (Parallel Cascade & Node Starvation)

Всплеск комплексной бизнес-операции вызывает синхронное срабатывание HPA у десятков разнородных сервисов в одном пространстве имен или кластере.
- **Следствие:** Все сервисы одновременно запрашивают планирование сотен новых подов.
- **Риск в bare-metal / on-prem инфраструктуре:** Физическая емкость рабочих узлов (Compute Nodes) конечна. Наступает насыщение по CPU, RAM, емкости таблицы Conntrack ядра Linux (`nf_conntrack_max`) или исчерпание лимитов сетевых адресов CNI. Системные демоны (CoreDNS, Ingress Controller, CNI-плагины) начинают испытывать троттлинг CPU, что приводит к деградации резолвинга DNS и сбоям маршрутизации трафика во всем кластере.

### Факторы задержки масштабирования (Trickle-down Scaling Lag)

Общее время реакции зависимого сервиса на каскадный всплеск вычисляется по формуле:

$$T_{total\_lag} = T_{hpa\_sync} + T_{metric\_scrape} + T_{scheduler} + T_{image\_pull} + T_{app\_init} + T_{readiness}$$

1. **$T_{hpa\_sync}$ (Интервал контроллера):** По умолчанию `--horizontal-pod-autoscaler-sync-period` равен 15 секундам.
2. **$T_{metric\_scrape}$ (Интервал сбора метрик):** Задержка обновления метрик в Prometheus / Metrics Server (обычно 15–30 секунд).
3. **$T_{scheduler}$ (Планирование):** Время на поиск подходящего узла планировщиком `kube-scheduler` (при дефиците ресурсов — задержка preemption).
4. **$T_{image\_pull}$ (Загрузка образа):** Время скачивания контейнерного слоя из локального реестра (0 секунд при `imagePullPolicy: IfNotPresent` и наличии слоя на узле, либо 10–60 секунд при скачивании по сети).
5. **$T_{app\_init}$ (Запуск приложения):** Прогрев JVM, компиляция байткода, инициализация пулов БД и подгрузка локальных структур (от 5 до 120 секунд).
6. **$T_{readiness}$ (Готовность пода):** Интервал между запуском и успешным прохождением `readinessProbe` (`initialDelaySeconds` + `periodSeconds` $\times$ `successThreshold`).

**Вывод:** До тех пор, пока не истечет $T_{total\_lag}$, вся возросшая нагрузка от масштабированного upstream ложится исключительно на исходное количество подов downstream.

### Математическая модель согласования емкости

Для предотвращения каскадного насыщения емкость каждого нижележащего уровня должна перекрывать максимальную расчетную нагрузку вышележащего уровня:

$$\text{Capacity}(Tier_{N+1}) \ge \text{Capacity}(Tier_{N}) \times \text{Fanout Factor}$$

Пусть:
- $M_{up}$ — `maxReplicas` для upstream-сервиса (Frontend).
- $R_{pod}$ — максимальный объем исходящих RPS, генерируемый одним подом upstream при пиковой загрузке.
- $T_{target}$ — целевой расчетный RPS на один под downstream-сервиса (Backend).
- $C_{db}$ — максимальная пропускная способность базы данных (RPS / транзакций в секунду).
- $K_{query}$ — среднее число запросов в БД на один входящий вызов Backend.

Тогда минимально допустимый параметр `maxReplicas` для downstream рассчитывается как:

$$M_{down\_required} = \left\lceil \frac{M_{up} \times R_{pod}}{T_{target}} \right\rceil$$

Предельное ограничение на масштабирование бэкенда диктуется базой данных:

$$M_{down\_limit} = \left\lfloor \frac{C_{db}}{T_{target} \times K_{query}} \right\rfloor$$

Если расчетное $M_{down\_required} > M_{down\_limit}$, включение масштабирования upstream без установки жестких лимитов гарантированно приведет к каскадному падению базы данных.

### Сравнительный анализ стратегий защиты

| Стратегия | Уровень изоляции | Механизм действия | Преимущества | Ограничения и компромиссы |
|:---|:---|:---|:---|:---|
| **Independent HPA с behavior** | Kubernetes Workload | Независимые целевые метрики и асимметричные политики скорости | Простота внедрения, нативный механизм | Не защищает от резких секундных всплесков из-за Trickle-down Lag |
| **Ingress Rate Limiting** | L7 Network Edge | Отсечение избыточных запросов на сетевом периметре | Защищает всю внутреннюю цепочку от перегрузки | Запросы пользователей отбрасываются с кодом 429 |
| **Circuit Breaking (Envoy/Istio)** | L7 Service Mesh | Разрыв соединений при росте задержек или 5xx-кодов | Предотвращает лавинообразные отказы и зацикливание тайм-аутов | Требует наличия Service Mesh и логики обработки fallback в клиенте |
| **Connection Pooling (PgBouncer)** | Data Layer | Ограничение максимального числа физических сессий к СУБД | Защищает память и процессор базы данных от шторма подключений | Очередь запросов в пулере может вызывать рост latency |
| **Asynchronous Queue (AMQP/Kafka)** | Architectural Layer | Буферизация задач между уровнями через брокер сообщений | Полное устранение прямой связанности по пропускной способности | Не применимо для синхронных интерактивных HTTP/gRPC API |

---

## Практические сценарии и конфигурация

### Паттерн 1: Согласованная настройка HPA с политиками behavior

Для предотвращения лавинообразного роста и дребезга реплик (flapping) upstream настраивается с более консервативным темпом расширения, а downstream получает превентивный агрессивный scale-up и увеличенное окно стабилизации при scale-down.

```yaml
# hpa-frontend.yaml — Upstream сервис
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend
  minReplicas: 5
  maxReplicas: 25
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      selectPolicy: Max
      policies:
        - type: Percent
          value: 50
          periodSeconds: 30
        - type: Pods
          value: 4
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      selectPolicy: Min
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
---
# hpa-backend.yaml — Downstream сервис
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  minReplicas: 10
  maxReplicas: 40
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      selectPolicy: Max
      policies:
        # Агрессивное масштабирование для опережения входящего потока от Frontend
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 8
          periodSeconds: 15
    scaleDown:
      # Защита от преждевременного свертывания при волновой нагрузке
      stabilizationWindowSeconds: 600
      selectPolicy: Min
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
```

### Паттерн 2: L7 Rate Limiting и защита периметра через Ingress-NGINX

Ограничение интенсивности входящих запросов на уровне Ingress защищает всю нижележащую цепочку от перегрузки при исчерпании лимитов масштабирования.

```yaml
# ingress-protection.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  namespace: production
  annotations:
    kubernetes.io/ingress.class: "nginx"
    # Ограничение среднего числа запросов в секунду с одного IP
    nginx.ingress.kubernetes.io/limit-rps: "150"
    # Всплеск (burst) запросов без немедленного сброса
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "3"
    # Лимит параллельных TCP-соединений с одного IP-адреса
    nginx.ingress.kubernetes.io/limit-connections: "30"
    # Кастомный код ответа при превышении лимита
    nginx.ingress.kubernetes.io/configuration-snippet: |
      limit_req_status 429;
    # Настройка тайм-аутов для защиты внутренних воркеров от зависания
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "5"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "15"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "15"
spec:
  rules:
    - host: api.internal.infra
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend
                port:
                  number: 80
```

### Паттерн 3: Circuit Breaking и Outlier Detection через Istio DestinationRule

Service Mesh перехватывает сетевой трафик между подами и предотвращает перегрузку downstream при сбоях или исчерпании пула соединений.

```yaml
# destination-rule-backend.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: backend-circuit-breaker
  namespace: production
spec:
  host: backend.production.svc.cluster.local
  trafficPolicy:
    connectionPool:
      tcp:
        # Предельное количество одновременных TCP-соединений
        maxConnections: 500
      http:
        # Предельное число ожидающих (pending) HTTP/1.1 запросов
        http1MaxPendingRequests: 100
        # Максимальное число активных параллельных HTTP/2 запросов
        http2MaxRequests: 2000
        # Максимальное число запросов на соединение перед закрытием
        maxRequestsPerConnection: 100
        # Максимальное число повторных попыток
        maxRetries: 2
    outlierDetection:
      # Изоляция пода при 3 подряд ошибках 5xx
      consecutive5xxErrors: 3
      # Интервал проверки состояния
      interval: 10s
      # Базовое время исключения пода из пула балансировки
      baseEjectionTime: 30s
      # Максимальный процент подов, которые могут быть одновременно исключены
      maxEjectionPercent: 50
```

### Паттерн 4: Защита базы данных через PgBouncer перед StatefulSet

При масштабировании сервиса Backend до 40 подов прямое подключение каждого пода (с пулом по 20 соединений на под) создаст 800 сессий к PostgreSQL, что приведет к деградации производительности СУБД из-за конкуренции за процессорное время и память. Установка пулера соединений изолирует состояние.

```yaml
# pgbouncer-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pgbouncer
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pgbouncer
  template:
    metadata:
      labels:
        app: pgbouncer
    spec:
      containers:
        - name: pgbouncer
          image: edoburu/pgbouncer:1.23.0
          ports:
            - containerPort: 5432
          env:
            - name: DB_HOST
              value: "postgresql-primary.production.svc.cluster.local"
            - name: DB_PORT
              value: "5432"
            - name: DB_USER
              value: "app_user"
            - name: POOL_MODE
              value: "transaction"
            - name: MAX_CLIENT_CONN
              value: "2000"
            - name: DEFAULT_POOL_SIZE
              value: "50"
            - name: RESERVE_POOL_SIZE
              value: "10"
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1000m"
              memory: "512Mi"
```

### Паттерн 5: Метрики и алертинг каскадного масштабирования в Prometheus

Правила Prometheus Alertmanager для заблаговременного обнаружения признаков каскадной перегрузки и исчерпания запаса емкости.

```yaml
# prometheus-rules-cascading.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cascading-scaling-alerts
  namespace: monitoring
spec:
  groups:
    - name: cascading_autoscaling.rules
      rules:
        # Алерт: HPA уперся в лимит maxReplicas
        - alert: DownstreamAutoscalingSaturated
          expr: |
            kube_horizontalpodautoscaler_status_condition{
              condition="ScalingLimited", status="true"
            } == 1
            and
            (
              kube_horizontalpodautoscaler_status_current_replicas
              / kube_horizontalpodautoscaler_spec_max_replicas
            ) >= 1.0
          for: 3m
          labels:
            severity: critical
            tier: autoscaling
          annotations:
            summary: "Downstream HPA исчерпал предельные реплики: {{ $labels.horizontalpodautoscaler }}"
            description: "Автомасштабирование уперлось в maxReplicas в течение 3 минут. Риск каскадного отказа вышележащих сервисов."

        # Алерт: Рассинхронизация масштабирования upstream и downstream
        - alert: CascadingScalingLagDetected
          expr: |
            (
              rate(http_requests_total{job="frontend"}[2m]) > 1000
            )
            and
            (
              histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job="backend"}[2m])) > 1.5
            )
          for: 2m
          labels:
            severity: warning
            tier: performance
          annotations:
            summary: "Обнаружено отставание масштабирования Backend от Frontend"
            description: "Всплеск входящего трафика на Frontend сопровождается ростом p99 latency на Backend выше 1.5s."

        # Алерт: Исчерпание пула соединений к базе данных
        - alert: DatabaseConnectionPoolNearExhaustion
          expr: |
            pgbouncer_pools_cl_waiting > 10
            or
            (pgbouncer_pools_sv_active / pgbouncer_pools_sv_login) > 0.9
          for: 1m
          labels:
            severity: critical
            tier: database
          annotations:
            summary: "Пул соединений PgBouncer переполнен"
            description: "Клиенты находятся в очереди ожидания свободных сессий к БД из-за масштабирования бэкенда."
```

---

## Операции и валидация цепочки

### Предварительная валидация готовности инфраструктуры

Перед активацией HPA на взаимосвязанных компонентах production-контура необходимо проверить согласованность квот, PDB и текущую емкость.

```bash
# 1. Проверка наличия и лимитов HPA по всей цепочке сервисов
kubectl get hpa -n production -o wide
# → NAME           REFERENCE             TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → backend-hpa    Deployment/backend    cpu: 45%/60%    10        40        10         14d
# → frontend-hpa   Deployment/frontend   cpu: 32%/70%    5         25        5          14d

# 2. Проверка ResourceQuota в целевом namespace на запас по CPU и памяти
kubectl get resourcequota -n production
# → NAME            AGE   REQUESTS                                    LIMITS
# → compute-quota   30d   requests.cpu: 18/64, requests.memory: 32Gi/128Gi   limits.cpu: 40/128, limits.memory: 64Gi/256Gi

# 3. Проверка PodDisruptionBudget (PDB) для предотвращения одновременного сброса реплик
kubectl get pdb -n production
# → NAME           MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → backend-pdb    7               N/A               3                     14d
# → frontend-pdb   3               N/A               2                     14d

# 4. Проверка состояния эндпоинтов downstream
kubectl get endpointslices -l kubernetes.io/service-name=backend -n production
# → NAME                  ADDRESSTYPE   PORTS   ENDPOINTS                            AGE
# → backend-7x4fg         IPv4          8080    10.244.1.12,10.244.2.15 + 8 more...   14d
```

### Сквозное нагрузочное тестирование

Для проверки устойчивости к каскадным эффектам выполняется генерация ступенчатой нагрузки с фиксацией реакции HPA и контролем задержек.

```bash
# Запуск генератора нагрузки Fortio с фиксированной версией образа
kubectl run fortio-load-test --rm -i --tty \
  --image=fortio/fortio:1.68.0 -- \
  load -c 30 -qps 1500 -t 120s -timeout 5s \
  http://frontend.production.svc.cluster.local/api/v1/checkout
# → Fortio 1.68.0 running at 1500 queries per second, 30->30 procs, for 120s:
# → IP addresses: 10.244.3.45:80
# → Starting at 1500 qps with 30 workers, 120s
# → All 180000 calls done in 120.012s, avg qps 1499.8
# → Sockets used: 30 (for perfect keepalive)
# → Code 200 : 179850 (99.9 %)
# → Code 429 : 150 (0.1 %)
# → Response OK : 179850
# → Response Duration Percentiles:
# →   p50 : 0.0082s
# →   p75 : 0.0145s
# →   p90 : 0.0240s
# →   p99 : 0.0890s
# →   p99.9 : 0.4500s

# Мониторинг динамики масштабирования в параллельном терминале
kubectl get hpa -n production --watch
# → NAME           REFERENCE             TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → frontend-hpa   Deployment/frontend   cpu: 85%/70%    5         25        12         14d
# → backend-hpa    Deployment/backend    cpu: 78%/60%    10        40        24         14d
# → frontend-hpa   Deployment/frontend   cpu: 68%/70%    5         25        18         14d
# → backend-hpa    Deployment/backend    cpu: 58%/60%    10        40        32         14d
```

---

## Диагностика и устранение неполадок

### Матрица типовых проблем каскадного масштабирования

| Симптом | Первопричина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| Upstream возвращает HTTP 504 Gateway Timeout, поды Frontend масштабируются до `maxReplicas` | Downstream уперся в свой `maxReplicas`, образовалась очередь запросов | `kubectl describe hpa backend-hpa`, проверить condition `ScalingLimited` | Увеличить `maxReplicas` downstream (при запасе БД) либо настроить Rate Limiting на Ingress |
| Поды downstream циклически падают по OOMKilled после масштабирования upstream | Недостаточный `resources.requests.memory` при резком росте параллельных коннектов | `kubectl get pods -l app=backend -o jsonpath='{.items[*].status.containerStatuses[*].lastState.terminated.reason}'` | Пересмотреть профиль памяти, ограничить `maxConnections` в Circuit Breaker |
| "Спираль смерти": новые поды долго стартуют и получают трафик до прогрева кэша | Некорректно настроенная `readinessProbe` или длительная инициализация пулов | `kubectl describe pod <pod-name>`, просмотр событий `Probe failed` | Добавить `startupProbe`, увеличить `initialDelaySeconds` и настроить прогрев приложения |
| База данных падает с ошибкой `FATAL: remaining connection slots are reserved` | Суммарное число коннектов от всех реплик backend превысило `max_connections` | В PostgreSQL: `SELECT count(*) FROM pg_stat_activity;` | Внедрить PgBouncer в режиме transaction pooling; ограничить размер пула в коде приложения |
| Ошибки резолвинга DNS (`i/o timeout`) при масштабировании | Всплеск DNS-запросов от десятков новых подов перегрузил поды CoreDNS | `kubectl logs -n kube-system -l k8s-app=kube-dns` | Развернуть NodeLocal DNSCache в кластере; настроить масштабирование CoreDNS через `cluster-proportional-autoscaler` |
| Дребезг (Flapping) реплик upstream и downstream каждые несколько минут | Слишком короткое окно `stabilizationWindowSeconds` на scaleDown | `kubectl get hpa -w`, сравнение графиков реплик в Grafana | Увеличить `behavior.scaleDown.stabilizationWindowSeconds` до 300–600 секунд |

### Сценарии устранения неисправностей

#### Сценарий 1: Downstream застрял в состоянии ScalingLimited (maxReplicas)

**Диагностика:**
```bash
# 1. Проверка статуса условий HPA
kubectl get hpa backend-hpa -n production -o yaml | grep -A 10 "conditions:"
# → conditions:
# → - lastTransitionTime: "2026-10-12T15:30:00Z"
# →   message: the desired replica count is more than the maximum replica count
# →   reason: TooManyReplicas
# →   status: "True"
# →   type: ScalingLimited

# 2. Проверка задержки обработки запросов на downstream
kubectl top pods -l app=backend -n production --sort-by=cpu
# → NAME                       CPU(cores)   MEMORY(bytes)
# → backend-6f5d8c7b8-1a2b3    980m         1420Mi
# → backend-6f5d8c7b8-4c5d6    995m         1390Mi
```

**Решение:**
1. Если хранилище и ресурсы узлов позволяют, оперативно увеличьте `maxReplicas` в манифесте HPA:
   ```bash
   kubectl patch hpa backend-hpa -n production --type='json' -p='[{"op": "replace", "path": "/spec/maxReplicas", "value": 60}]'
   # → horizontalpodautoscaler.autoscaling/backend-hpa patched
   ```
2. Если увеличение невозможно из-за ограничений БД, активируйте сброс нагрузки (Rate Limiting) на Ingress, чтобы остановить лавину запросов.

#### Сценарий 2: Спираль смерти из-за сбоя Readiness Probe при нагрузке

**Диагностика:**
При резком поступлении трафика на только что стартовавший под его CPU загружается на 100%, приложение перестает своевременно отвечать на HTTP-проверку готовности, kubelet исключает под из EndpointSlice, и весь трафик возвращается на старые поды.

```bash
# Проверка событий сбоя проверок готовности
kubectl get events -n production --field-selector reason=Unhealthy --sort-by='.metadata.creationTimestamp'
# → 2m   Warning   Unhealthy   pod/backend-849c6d-9z8y7   Readiness probe failed: HTTP probe failed with statuscode: 503
```

**Решение:**
Разделите `startupProbe` и `readinessProbe` в манифесте Deployment. `startupProbe` должна давать достаточное время на прогрев приложения, а `readinessProbe` — иметь увеличенный `failureThreshold` и отдельный облегченный эндпоинт (например, `/healthz/ready`, не делающий тяжелых запросов в базу данных).

```yaml
# Фрагмент манифеста deployment-backend.yaml
startupProbe:
  httpGet:
    path: /healthz/startup
    port: 8080
  failureThreshold: 30
  periodSeconds: 5
readinessProbe:
  httpGet:
    path: /healthz/ready
    port: 8080
  initialDelaySeconds: 2
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 3
```

---

## Рекомендации и лучшие практики

### Принципы проектирования устойчивых систем

1. **Принцип превентивного запаса (Headroom Planning):**
   Устанавливайте значение `minReplicas` на downstream-сервисах с расчетом на мгновенное поглощение 2-кратного базового всплеска нагрузки без ожидания запуска новых подов. Внутренние компоненты должны быть готовы принять нагрузку до того, как HPA зафиксирует рост метрик.

2. **Асимметричное поведение масштабирования (Asymmetric Behavior):**
   - **Scale Up:** Должен быть быстрым (окно стабилизации 0 секунд, агрессивный процент добавления реплик: 50–100%).
   - **Scale Down:** Должен быть крайне консервативным (окно стабилизации 300–600 секунд, медленное снижение: не более 10–20% в минуту). Это защищает систему от волновых колебаний трафика.

3. **Соблюдение топологической емкости кластера:**
   Суммарное значение `maxReplicas * requests.cpu` всех сервисов кластера не должно превышать физическую емкость доступных рабочих узлов (Allocatable CPU/RAM). В противном случае поды окажутся в статусе `Pending`, вызывая сбои в обслуживании трафика.

4. **Изоляция критических инфраструктурных сервисов:**
   Для CoreDNS, Ingress-NGINX и сервисов мониторинга обязательно настраивайте `PriorityClass: system-cluster-critical` или выделенные `nodeSelector` / `tolerations`, чтобы каскадно масштабируемые бизнес-приложения не вытесняли системные демоны.

5. **Обязательное использование PodDisruptionBudget (PDB):**
   Каждый сервис в цепочке обязан иметь манифест PDB с параметром `minAvailable` или `maxUnavailable`, предотвращающий выселение слишком большого числа подов при плановом обслуживании узлов.

### Чек-лист готовности к production

- [ ] Все взаимосвязанные сервисы имеют независимые HPA с API `autoscaling/v2`.
- [ ] Рассчитано математическое соотношение `maxReplicas` между уровнями: downstream гарантированно выдерживает пиковый трафик от upstream.
- [ ] На downstream-сервисах порог срабатывания HPA установлен ниже (например, 60% CPU), чем на upstream (70–75% CPU), для компенсации Trickle-down Lag.
- [ ] В `behavior.scaleDown` настроены окна стабилизации не менее 300 секунд для предотвращения flapping.
- [ ] На Ingress-контроллере активны аннотации `limit-rps` и `limit-connections`.
- [ ] Для межсервисного взаимодействия настроен Circuit Breaker (Istio DestinationRule или аналогичный механизм).
- [ ] Перед базой данных установлен пул соединений (PgBouncer) с ограничением максимального числа сессий.
- [ ] В манифестах подов настроены `startupProbe` и `readinessProbe` с реалистичными тайм-аутами.
- [ ] Настроены алерты Prometheus на условия `ScalingLimited` и исчерпание пулов соединений.
- [ ] Проведено нагрузочное тестирование с эмуляцией резкого ступенчатого всплеска трафика.

### Вопросы и ответы для собеседования (SRE / System Design)

**Вопрос:** Как предотвратить падение базы данных при резком масштабировании бэкенд-сервисов в Kubernetes?
**Ответ:** Защита выстраивается на четырех рубежах:
1. **Расчет емкости (Capacity Cap):** Жесткое ограничение `maxReplicas` в HPA бэкенда исходя из предельного числа параллельных запросов к БД.
2. **Пулинг соединений:** Внедрение промежуточного слоя (например, PgBouncer в режиме транзакций) между подами бэкенда и СУБД для мультиплексирования тысяч клиентских соединений в фиксированное число серверных потоков.
3. **Circuit Breaking:** Настройка лимитов `maxConnections` и `http1MaxPendingRequests` в Service Mesh (Istio/Envoy) для автоматического сброса избыточных вызовов с ошибкой до того, как они достигнут БД.
4. **Асинхронная изоляция:** Перенос тяжелых операций записи в очереди сообщений (Kafka, RabbitMQ) с регулируемой скоростью вычитки воркерами.

**Вопрос:** В чем опасность масштабирования подов по памяти (Memory Utilization) в микросервисной цепочке?
**Ответ:** Память в Kubernetes измеряется через `working_set_bytes`, куда входит как резидентная память (RSS), так и страничный кэш файловой системы. Многие виртуальные машины (Java, Go) не отдают выделенную память операционной системе сразу после сборки мусора (GC). В результате метрика утилизации памяти не снижается даже после спада нагрузки, HPA застревает на `maxReplicas` и не может масштабироваться вниз, сохраняя избыточное давление на инфраструктуру. Для автомасштабирования рекомендуется использовать CPU или RPS, а память применять только как защитный ограничитель.

---

## Дополнительная информация

### Антипаттерны каскадного масштабирования

| Антипаттерн | Механизм деградации | Корректное архитектурное решение |
|:---|:---|:---|
| **Синхронное масштабирование без буферов** | Upstream и downstream синхронно наращивают поды, передавая пики нагрузки без сглаживания прямо в базу данных | Использование Ingress Rate Limiting на входе и очередей сообщений для тяжелых асинхронных задач |
| **Одинаковые пороги утилизации CPU** | Upstream и downstream имеют таргет 70% CPU. Из-за задержки старта downstream отстает и перегружается | Downstream должен иметь более низкий таргет (50–60%) и агрессивный scaleUp для опережения upstream |
| **Единый HPA для нескольких Deployment** | Попытка связать один HPA с несколькими сущностями приводит к коллизиям в API-сервере | Строгое соответствие: один объект HPA управляет ровно одним целевым `scaleTargetRef` |
| **Агрессивный scaleDown без стабилизации** | При кратковременном спаде трафика поды сворачиваются, а следующий пик застает систему врасплох | Установка `scaleDown.stabilizationWindowSeconds` от 300 до 600 секунд |
| **Отсутствие лимитов на пулы соединений** | Каждый новый под открывает собственный пул на 50 соединений к БД, вызывая отказ СУБД | Использование централизованного connection pooler и ограничение пулов внутри приложения |

### См. также

- **[HPA: Главная](./index.md)** — архитектура, подресурсы масштабирования и основы HPA
- **[HPA: Основные концепции](./hpa_concepts.md)** — алгоритм расчета желаемого числа реплик и контрольный цикл
- **[HPA: Практические сценарии](./hpa_scenarios.md)** — конфигурации манифестов для различных типов нагрузок
- **[HPA: Продвинутые темы](./hpa_advanced.md)** — тонкая настройка `behavior`, метрики памяти и отладка условий
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — обеспечение доступности сервисов при изменении топологии
- **[Autoscaling в On-Premise / Bare-Metal средах](../on_premise_autoscaling.md)** — специфика автомасштабирования без облачных провайдеров
- **[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — горизонтальное масштабирование узлов инфраструктуры
