# Progressive Delivery для Deployment

**Актуально для:** Kubernetes 1.28–1.32+, Argo Rollouts v1.8.x, Flagger v1.44.x, Prometheus 2.50+ / 3.x, Gateway API v1.2+, Ingress-NGINX v1.10+ (On-Premise / Bare-Metal)

Интеграция прогрессивной доставки с Kubernetes Deployment в локальных кластерах: архитектура контроллеров, бесшовный переход со стандартного `apps/v1 Deployment` на Argo Rollouts (orphan handover), сосуществование с HPA и PDB, емкостное планирование (capacity surge), автоматический метрический гейтинг через Prometheus и операционный траблшутинг для DevOps, SRE и системных администраторов.

## Предварительные требования (Prerequisites)

- **Рабочий кластер Kubernetes:** версии 1.28–1.32+ (на базе `kubeadm`, RKE2, K3s на bare-metal или локальных гипервизорах KVM/VMware).
- **Контроллер прогрессивной доставки:**
  - Установленный оператор **Argo Rollouts** (CRD `rollouts.argoproj.io`, `analysistemplates.argoproj.io`) либо **Flagger** (CRD `canaries.flagger.app`, `metrictemplates.flagger.app`).
  - Установленный плагин командной строки `kubectl-argo-rollouts` для инженеров эксплуатации.
- **Сетевая инфраструктура маршрутизации трафика (L7):**
  - **Ingress-NGINX** (поддержка канареечных аннотаций `nginx.ingress.kubernetes.io/canary*`).
  - **Gateway API** (контроллер с поддержкой весов `HTTPRoute.spec.rules.backendRefs.weight`, например Envoy Gateway, Cilium Gateway или Istio в on-prem).
- **Стек мониторинга и телеметрии:**
  - Локальный **Prometheus** (версии 2.50+ или 3.x) с настроенным сбором метрик приложений (`http_requests_total`, `http_request_duration_seconds_bucket`) и сетевых шлюзов.
- **Базовые знания:**
  - Понимание архитектуры [Deployment](./index.md), ротации реплик [Lifecycle Management](./lifecycle_management.md) и механики [Probes](../probes.md).

---

## 1. Определения

- **Progressive Delivery (Прогрессивная доставка)** — методология контролируемого выпуска обновлений, расширяющая Continuous Delivery автоматическим управлением долями сетевого трафика, инкрементальным увеличением нагрузки на новую версию (Canary / Blue-Green) и автоматическим прерыванием выкатки на основе анализа телеметрии (SLI/SLO).
- **Argo Rollouts** — специализированный Kubernetes-контроллер проекта Argo, заменяющий стандартный контроллер Deployment кастомным ресурсом `Rollout` (`argoproj.io/v1alpha1`). Напрямую управляет объектами `ReplicaSet`, шагами весов сетевого трафика и проверками метрик.
- **Flagger** — контроллер прогрессивной доставки экосистемы CNCF, функционирующий как надстройка над стандартным `apps/v1 Deployment`. Автоматически генерирует сервисы `<name>-primary` и `<name>-canary`, управляет маршрутизацией и выполняет канареечный анализ через CRD `Canary` (`flagger.app/v1beta1`).
- **AnalysisTemplate / AnalysisRun** — декларативные ресурсы Argo Rollouts. `AnalysisTemplate` задает параметризованный шаблон сбора метрик (Prometheus PromQL, Webhook, Job), а `AnalysisRun` представляет экземпляр выполнения проверки на конкретном шаге выкатки.
- **MetricTemplate** — декларативный ресурс Flagger, описывающий шаблон PromQL-запроса к Prometheus с пороговыми значениями (`thresholdRange`).
- **Traffic Routing Provider** — сетевой компонент кластера (Ingress-NGINX, Gateway API HTTPRoute, Service Mesh), через API которого контроллер прогрессивной доставки динамически меняет процент трафика, направляемого на канареечные поды.
- **Canary Service и Stable Service** — два раздельных сетевых сервиса Kubernetes (`core/v1 Service`), селекторы которых контроллер модифицирует меткой хэша шаблона (`rollouts-pod-template-hash`), разделяя стабильную и тестируемую версии нагрузки.
- **Capacity Surge & Headroom** — дополнительный объем вычислительных ресурсов (CPU, RAM, лимиты `ResourceQuota`), требуемый кластеру во время параллельной работы старой и новой версий приложения.
- **Orphan Handover (Перехват без простоя)** — метод миграции с `apps/v1 Deployment` на `Rollout` путем удаления старого объекта с флагом `--cascade=orphan`, при котором существующие ReplicaSet и поды не удаляются, а бесшовно усыновляются новым контроллером.
- **Manual Gating (Ручной гейтинг)** — остановка процесса выкатки на фиксированном проценте трафика (шаг `pause` без указания длительности), требующая подтверждения инженером дежурной смены перед продолжением продвижения релиза.

---

## 2. Базовые концепции и архитектура

### Deployment vs Rollout vs Flagger

В архитектуре Kubernetes стандартный `apps/v1 Deployment` не обладает механизмами L7-маршрутизации трафика и метрического гейтинга. Решение задачи прогрессивной доставки реализуется двумя альтернативными подходами: полной заменой контроллера (Argo Rollouts) либо надстройкой над существующим ресурсом (Flagger).

| Аспект | Kubernetes Deployment (`apps/v1`) | Argo Rollouts (`argoproj.io/v1alpha1`) | Flagger (`flagger.app/v1beta1`) |
| :--- | :--- | :--- | :--- |
| **Управляющий ресурс** | `kind: Deployment` | `kind: Rollout` | `kind: Deployment` + `kind: Canary` |
| **Управление ReplicaSet** | Напрямую управляет старым и новым RS через `deployment-controller` | Напрямую управляет canary и stable RS через `rollout-controller` | Клонирует Deployment в `<name>-primary`; исходный становится канарейкой |
| **Управление трафиком** | Случайное L4 распределение через Service пропорционально числу подов | Прямое динамическое управление весами в Ingress-NGINX / Gateway API | Прямое динамическое управление весами в Ingress / HTTPRoute / Mesh |
| **Анализ состояния** | Только пробы контейнеров (`liveness`, `readiness`, `startup`) | Метрические запросы PromQL, Webhook, Job (`AnalysisTemplate`) | Метрические запросы PromQL, Webhook (`MetricTemplate`) |
| **Реакция на деградацию** | Остановка выкатки по таймауту `progressDeadlineSeconds` | Мгновенный автоматический откат (`abort`) по метрикам SLI/SLO | Мгновенный автоматический откат (`rollback`) по порогам метрик |
| **Совместимость с HPA** | Нативная поддержка масштабирования | Поддерживается (целевой ресурс: `kind: Rollout`) | Поддерживается (целевой ресурс: `<name>-primary`) |
| **Влияние на манифесты** | Базовый стандарт ядра Kubernetes | Требует переписывания манифестов с `Deployment` на `Rollout` | Сохраняет манифесты `Deployment` разработчиков без изменений |

### Архитектура контроллера Argo Rollouts

Argo Rollouts заменяет собой стандартный `deployment-controller` из состава `kube-controller-manager`. Он перехватывает управление `ReplicaSet` и интегрируется с сетевыми шлюзами кластера:

```text
               kube-apiserver
                     │
                     ▼
             rollouts-controller
                     │
         ┌───────────┴────────────────────────┐
         │ (Управление подами)                │ (Управление трафиком L7)
         ▼                                    ▼
┌──────────────────┐               ┌─────────────────────────────────┐
│ Stable ReplicaSet│ (90% трафика) │ Ingress-NGINX / Gateway API     │
│ Canary ReplicaSet│ (10% трафика) │ HTTPRoute (backendRef weights)  │
└──────────────────┘               └─────────────────────────────────┘
         │                                    ▲
         ▼                                    │
┌──────────────────┐               ┌─────────────────────────────────┐
│ AnalysisRun      │──────────────►│ Prometheus (PromQL query)       │
│ (Метрический суд)│  (Провал:     │ Rate 5xx < 1%, Latency p95 OK   │
└──────────────────┘   Abort/Undo) └─────────────────────────────────┘
```

1. **Контроль реплик:** Контроллер вычисляет количество подов для Stable и Canary наборов. При наличии Service Mesh или Ingress с разделением трафика число подов канарейки может быть минимальным (например, 1 под при 10% трафика), так как трафик регулируется сетевым провайдером, а не соотношением количества реплик.
2. **Маршрутизация L7:** Контроллер модифицирует целевой ресурс:
   - В **Ingress-NGINX**: создает временный теневой Ingress с аннотациями `nginx.ingress.kubernetes.io/canary: "true"` и `nginx.ingress.kubernetes.io/canary-weight: "10"`.
   - В **Gateway API**: обновляет веса `weight` в `rules.backendRefs` внутри ресурса `HTTPRoute`.
3. **Метрический гейтинг:** На каждом шаге контроллер генерирует `AnalysisRun`, опрашивающий локальный Prometheus. Если результат PromQL не удовлетворяет условию `successCondition`, контроллер инициирует процедуру `abort`.

### Архитектура Flagger поверх Deployment

Flagger сохраняет оригинальный `Deployment` как источник правды о желаемой спецификации, но модифицирует топологию выполнения:

```text
 [Разработчик / CI/CD] ──► Применяет Deployment "my-app" (образ: v2)
                                 │
                                 ▼
                          flagger-controller
                                 │
     ┌───────────────────────────┴───────────────────────────┐
     ▼                                                       ▼
Deployment "my-app" (Canary, v2)              Deployment "my-app-primary" (v1)
Service: "my-app-canary"                      Service: "my-app-primary"
     │                                                       │
     └───────────────────────────┬───────────────────────────┘
                                 ▼
                     Service "my-app" (Apex)
           (Маршрутизация трафика: Ingress / Gateway API)
```

1. При первом запуске Flagger создает из `my-app` постоянный Deployment `my-app-primary` с текущим стабильным образом.
2. Исходный Deployment `my-app` масштабируется в 0 реплик.
3. Когда CI/CD обновляет образ в `my-app`, Flagger масштабирует `my-app` до 1+ реплик, помечает его как канарейку и начинает постепенный перенос трафика с `my-app-primary` на `my-app`.
4. В случае успешного завершения всех этапов анализа образ в `my-app-primary` обновляется до v2, а канареечный `my-app` снова масштабируется в 0.

### Емкостное планирование (Capacity Surge & Headroom)

Критический аспект SRE и системного администрирования на локальной bare-metal инфраструктуре: **прогрессивная доставка требует резерва ресурсов нод**.

- **Canary с L7-роутингом:** При разделении трафика через Ingress/Gateway API для приложения с 10 репликами канарейка может запускаться всего на 1–2 дополнительных подах (всплеск 10–20% по CPU/RAM).
- **Blue-Green развертывание:** Требует запуска **100% дублирующей емкости**. Если сервис занимает 64 vCPU и 128 GiB RAM, в кластере должно быть свободно минимум 64 vCPU и 128 GiB RAM.
- **Ограничения `ResourceQuota`:** Если неймспейс ограничен жесткой квотой:
  $$\text{Requests}_{\text{Total}} = \text{Requests}_{\text{Stable}} + \text{Requests}_{\text{Canary}} \le \text{Quota}$$
  При превышении квоты поды канарейки переходят в статус `FailedCreate` с ошибкой `exceeded quota`, а процесс выкатки блокируется.

### Взаимодействие с HPA (HorizontalPodAutoscaler)

При интеграции с HPA необходимо исключить конфликт контуров управления:

1. **Для Argo Rollouts:** Ресурс HPA должен нацеливаться строго на `kind: Rollout`:
   ```yaml
   spec:
     scaleTargetRef:
       apiVersion: argoproj.io/v1alpha1
       kind: Rollout
       name: my-app
   ```
   Argo Rollouts автоматически пересчитывает распределение реплик между Stable и Canary в соответствии с общим целевым количеством реплик, вычисленным HPA.
2. **Динамическое масштабирование Rollout:** Если в процессе выкатки HPA увеличивает нагрузку с 10 до 20 реплик при шаге канарейки 20%, Rollout выделит 4 поды под канарейку и 16 под стабильную версию.
3. **Для Flagger:** HPA должен быть нацелен на генерируемый ресурс `my-app-primary`, а не на исходный `my-app`, иначе HPA и Flagger будут непрерывно перезаписывать количество реплик друг друга.

### Взаимодействие с PDB (PodDisruptionBudget)

Неправильно настроенный PDB может заблокировать прогрессивную доставку или вызвать технологический дедлок:

- Если для сервиса из 3 реплик задан `minAvailable: 3` (или `maxUnavailable: 0`), контроллер не сможет остановить ни один старый под при продвижении канарейки или при дренировании узла инженером.
- **Правило SRE:** Всегда используйте процентные значения либо оставляйте запас минимум в 1 реплику:
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: my-app-pdb
  spec:
    maxUnavailable: 25%
    selector:
      matchLabels:
        app: my-app
  ```

---

## 3. Практические сценарии и конфигурация

### Сценарий 1: Бесшовная миграция с Deployment на Argo Rollout (Zero-Downtime Adoption)

Чтобы мигрировать боевой сервис с `apps/v1 Deployment` на `Rollout` без перезапуска подов и без технологического простоя, применяется паттерн открепления (orphan handover):

#### Шаг 1: Инспекция существующего Deployment
```bash
# Проверяем метки селектора текущего Deployment
kubectl get deployment my-app -n production -o jsonpath='{.spec.selector.matchLabels}'
# → {"app":"my-app"}

# Проверяем текущие поды и ReplicaSet
kubectl get replicaset -n production -l app=my-app
# → NAME                DESIRED   CURRENT   READY   AGE
# → my-app-7d6b9f4b9c   4         4         4       14d
```

#### Шаг 2: Удаление объекта Deployment с сохранением ReplicaSet и подов
```bash
# Флаг --cascade=orphan оставляет ReplicaSet и поды в кластере
kubectl delete deployment my-app -n production --cascade=orphan
# → deployment.apps "my-app" deleted

# Убеждаемся, что поды продолжают работать и обслуживать трафик
kubectl get pods -n production -l app=my-app
# → NAME                      READY   STATUS    RESTARTS   AGE
# → my-app-7d6b9f4b9c-2w9jl   1/1     Running   0          14d
# → my-app-7d6b9f4b9c-7xkz4   1/1     Running   0          14d
# → my-app-7d6b9f4b9c-k8v2m   1/1     Running   0          14d
# → my-app-7d6b9f4b9c-p9nbt   1/1     Running   0          14d
```

#### Шаг 3: Применение манифеста Rollout с Ingress-NGINX
Манифест `my-app-rollout.yaml` объявляет `Rollout`, два сервиса и базовый Ingress:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
  namespace: production
spec:
  replicas: 4
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: my-app
  strategy:
    canary:
      canaryService: my-app-canary
      stableService: my-app-stable
      trafficRouting:
        nginx:
          stableIngress: my-app-ingress
      steps:
      - setWeight: 10
      - pause: {duration: 5m}
      - analysis:
          templates:
          - templateName: http-error-rate-and-latency
          args:
          - name: service-name
            value: my-app-canary
      - setWeight: 25
      - pause: {duration: 10m}
      - setWeight: 50
      - pause: {duration: 10m}
      - setWeight: 100
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: my-app
        image: registry.local/production/my-app:v1.10.0
        ports:
        - name: http
          containerPort: 8080
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
        readinessProbe:
          httpGet:
            path: /healthz
            port: http
          initialDelaySeconds: 5
          periodSeconds: 5
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]
---
apiVersion: v1
kind: Service
metadata:
  name: my-app-stable
  namespace: production
spec:
  ports:
  - name: http
    port: 80
    targetPort: http
  selector:
    app: my-app
---
apiVersion: v1
kind: Service
metadata:
  name: my-app-canary
  namespace: production
spec:
  ports:
  - name: http
    port: 80
    targetPort: http
  selector:
    app: my-app
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: production
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: my-app.internal.domain
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app-stable
            port:
              number: 80
```

```bash
# Применяем манифест Rollout
kubectl apply -f my-app-rollout.yaml
# → rollout.argoproj.io/my-app created
# → service/my-app-stable configured
# → service/my-app-canary created
# → ingress.networking.k8s.io/my-app-ingress configured

# Проверяем, что Rollout усыновил существующий ReplicaSet без рестарта подов
kubectl argo rollouts status rollout my-app -n production
# → Rollout 'my-app' is healthy
```

### Сценарий 2: Production AnalysisTemplate на базе Prometheus

Шаблон анализа метрик выполняет автоматический аудит стабильности релиза по золотым сигналам SRE (ошибки HTTP 5xx и перцентили задержки p95).

Включает защиту от:
1. **Деления на ноль:** использование `clamp_min(..., 0.001)` или fallback `or vector(0)` при слабом трафике.
2. **Холодного старта (Cold Start / JIT):** директива `initialDelay` дает подам время на прогрев кэшей перед включением метрического гейта.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: http-error-rate-and-latency
  namespace: production
spec:
  args:
  - name: service-name
  metrics:
  - name: success-rate
    interval: 1m
    count: 5
    failureLimit: 2
    initialDelay: 2m
    successCondition: result[0] >= 0.99
    provider:
      prometheus:
        address: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        query: |
          (
            sum(rate(nginx_ingress_controller_requests{exported_service="{{args.service-name}}", status!~"5.."}[1m]))
            /
            clamp_min(sum(rate(nginx_ingress_controller_requests{exported_service="{{args.service-name}}"}[1m])), 0.001)
          ) or vector(1)
  - name: p95-latency
    interval: 1m
    count: 5
    failureLimit: 2
    initialDelay: 2m
    successCondition: result[0] <= 0.400
    provider:
      prometheus:
        address: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        query: |
          (
            histogram_quantile(0.95, sum(rate(nginx_ingress_controller_request_duration_seconds_bucket{exported_service="{{args.service-name}}"}[1m])) by (le))
          ) or vector(0.050)
```

### Сценарий 3: Gateway API канареечная маршрутизация

В кластерах с поддержкой Gateway API (v1.2+) Argo Rollouts модифицирует вес бекендов внутри ресурса `HTTPRoute`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: api-gateway-app
  namespace: production
spec:
  replicas: 4
  selector:
    matchLabels:
      app: api-gateway-app
  strategy:
    canary:
      canaryService: api-gateway-app-canary
      stableService: api-gateway-app-stable
      trafficRouting:
        gatewayAPI:
          httpRouteName: api-gateway-app-route
      steps:
      - setWeight: 20
      - pause: {duration: 10m}
      - setWeight: 50
      - pause: {duration: 10m}
      - setWeight: 100
  template:
    metadata:
      labels:
        app: api-gateway-app
    spec:
      containers:
      - name: app
        image: registry.local/production/api-gateway-app:v2.0.0
        ports:
        - name: http
          containerPort: 8080
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-gateway-app-route
  namespace: production
spec:
  parentRefs:
  - name: internal-gateway
    namespace: envoy-gateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api/v1
    backendRefs:
    - name: api-gateway-app-stable
      port: 8080
      weight: 100
    - name: api-gateway-app-canary
      port: 8080
      weight: 0
```

### Сценарий 4: Flagger для стандартных Deployment с нагрузочным тестированием

Для команд, эксплуатирующих нативные `apps/v1 Deployment`, Flagger обеспечивает прогрессивную доставку без изменения манифестов приложения:

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: backend-service
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend-service
  progressDeadlineSeconds: 600
  autoscalerRef:
    apiVersion: autoscaling/v2
    kind: HorizontalPodAutoscaler
    name: backend-service
  service:
    port: 8080
    targetPort: http
    gateways:
    - internal-gateway.envoy-gateway-system
    hosts:
    - backend.internal.domain
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
    - name: request-success-rate
      thresholdRange:
        min: 99
      interval: 1m
    - name: request-duration
      thresholdRange:
        max: 500
      interval: 1m
    webhooks:
    - name: smoke-test
      type: pre-rollout
      url: http://flagger-loadtester.testing.svc.cluster.local/
      timeout: 15s
      metadata:
        type: bash
        cmd: "curl -s -f http://backend-service-canary.production:8080/healthz"
    - name: load-test
      type: rollout
      url: http://flagger-loadtester.testing.svc.cluster.local/
      timeout: 5s
      metadata:
        type: cmd
        cmd: "hey -z 1m -q 20 -c 4 http://backend-service-canary.production:8080/api/v1/ping"
```

### Сценарий 5: Blue-Green стратегия на чистых Kubernetes Services

Паттерн мгновенного переключения нагрузки без Ingress и Mesh (на уровне изменения селекторов двух `Service`):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: payment-processor
  namespace: production
spec:
  replicas: 4
  selector:
    matchLabels:
      app: payment-processor
  strategy:
    blueGreen:
      activeService: payment-processor-active
      previewService: payment-processor-preview
      autoPromotionEnabled: false
      scaleDownDelaySeconds: 300
      prePromotionAnalysis:
        templates:
        - templateName: smoke-test-check
      postPromotionAnalysis:
        templates:
        - templateName: http-error-rate-and-latency
  template:
    metadata:
      labels:
        app: payment-processor
    spec:
      containers:
      - name: payment-processor
        image: registry.local/production/payment-processor:v3.2.1
        ports:
        - name: http
          containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: payment-processor-active
  namespace: production
spec:
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    app: payment-processor
---
apiVersion: v1
kind: Service
metadata:
  name: payment-processor-preview
  namespace: production
spec:
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    app: payment-processor
```

---

## 4. Операции и команды

### Управление Argo Rollouts (`kubectl-argo-rollouts`)

| Команда | Назначение | Параметры / Опции |
| :--- | :--- | :--- |
| `kubectl argo rollouts get rollout <name>` | Визуализация текущего графа ревизий, весов и подов | `--watch`, `--no-color`, `-n <ns>` |
| `kubectl argo rollouts status rollout <name>` | Ожидание завершения или стабилизации раскатки | `--timeout 5m`, `-n <ns>` |
| `kubectl argo rollouts pause <name>` | Немедленная ручная приостановка раскатки | `-n <ns>` |
| `kubectl argo rollouts resume <name>` | Возобновление раскатки после ручной паузы | `-n <ns>` |
| `kubectl argo rollouts promote <name>` | Принудительный пропуск текущей паузы или шага анализа | `--full` (мгновенно до 100%), `-n <ns>` |
| `kubectl argo rollouts abort <name>` | Экстренное прерывание выкатки и возврат трафика на Stable | `-n <ns>` |
| `kubectl argo rollouts retry <name>` | Сброс статуса Aborted и повторная попытка раскатки | `-n <ns>` |
| `kubectl argo rollouts undo <name>` | Откат к конкретной исторической ревизии | `--to-revision=<N>`, `-n <ns>` |
| `kubectl argo rollouts dashboard` | Запуск локального графического веб-интерфейса управления | `-p 3100`, `--port <port>` |

#### Примеры вызова команд с ожидаемым выводом

```bash
# 1. Просмотр текущего прогресса канареечной раскатки в реальном времени
kubectl argo rollouts get rollout my-app -n production
# → NAME                                  KIND        STATUS        AGE  INFO
# → ⟳ my-app                              Rollout     paused        4m   4/4 replicas, 1 paused
# → ├──# revision:2
# → │  └──⧉ my-app-5649b85c88             ReplicaSet  healthy       4m   canary (10%)
# → │     └──□ my-app-5649b85c88-m9f2q    Pod         running       4m   ready:1/1
# → └──# revision:1
# →    └──⧉ my-app-7d6b9f4b9c             ReplicaSet  healthy       14d  stable
# →       ├──□ my-app-7d6b9f4b9c-2w9jl    Pod         running       14d  ready:1/1
# →       ├──□ my-app-7d6b9f4b9c-7xkz4    Pod         running       14d  ready:1/1
# →       └──□ my-app-7d6b9f4b9c-k8v2m    Pod         running       14d  ready:1/1

# 2. Ручное продвижение выкатки (пропуск паузы)
kubectl argo rollouts promote my-app -n production
# → rollout 'my-app' promoted

# 3. Экстренное прерывание выкатки при обнаружении дефекта
kubectl argo rollouts abort my-app -n production
# → rollout 'my-app' aborted

# 4. Проверка статуса прерванного Rollout
kubectl argo rollouts get rollout my-app -n production
# → NAME                                  KIND        STATUS   AGE  INFO
# → ⟳ my-app                              Rollout     degraded 6m   4/4 replicas, abort
# → ├──# revision:2
# → │  └──⧉ my-app-5649b85c88             ReplicaSet  healthy  6m   canary (0%)
# → └──# revision:1
# →    └──⧉ my-app-7d6b9f4b9c             ReplicaSet  healthy  14d  stable (100%)

# 5. Повторный перезапуск раскатки после фиксации конфигурации
kubectl argo rollouts retry my-app -n production
# → rollout 'my-app' retried
```

### Управление Flagger через стандартный `kubectl`

```bash
# Просмотр статуса канареек во всех пространствах имен
kubectl get canaries.flagger.app -A
# → NAMESPACE    NAME              STATUS        WEIGHT   LASTTRANSITION
# → production   backend-service   Progressing   20       2026-10-13T17:10:00Z
# → production   auth-service      Succeeded     0        2026-10-12T14:22:00Z

# Детальная диагностика шагов Flagger и логов анализа
kubectl describe canary backend-service -n production
# → Events:
# →   Type     Reason  Age                From     Message
# →   ----     ------  ----               ----     -------
# →   Normal   Synced  3m                 flagger  New revision detected! Scaling up backend-service.production
# →   Normal   Synced  2m                 flagger  Starting canary analysis for backend-service.production
# →   Normal   Synced  1m                 flagger  Advance backend-service.production canary weight 10
# →   Normal   Synced  10s                flagger  Advance backend-service.production canary weight 20
```

---

## 5. Диагностика и устранение неполадок

### Матрица типичных сбоев и решений

| Симптом | Корневая причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Поды непрерывно создаются и удаляются в цикле (флаппинг)** | Коллизия контроллеров: одновременно запущены `Deployment` и `Rollout` с одинаковыми `matchLabels`. | `kubectl get deploy,rollout -n <ns>` | Удалить старый `Deployment` с флагом `--cascade=orphan`. |
| **Канареечные поды зависают в статусе `Pending`** | 1. Превышена квота `ResourceQuota` неймспейса.<br>2. Недостаточно свободной емкости на рабочих узлах кластера. | `kubectl describe pod <canary-pod>`: ошибка `FailedScheduling` или `exceeded quota`. | 1. Увеличить лимиты в `ResourceQuota`.<br>2. Настроить Cluster Autoscaler или снизить `replicas` / `maxSurge`. |
| **Дедлок выкатки: старые поды не завершаются** | PDB с жестким `minAvailable` блокирует вывод реплик из эксплуатации. | `kubectl get pdb -n <ns>`: `ALLOWED DISRUPTIONS: 0`. | Задать в PDB `maxUnavailable: 25%` или снизить `minAvailable`. |
| **Ложный откат (False Positive Abort) в начале шага** | Холодный старт: всплеск задержки из-за компиляции JIT / прогрева кэшей. | Проверить запуск `AnalysisRun`: падение на 1-й минуте. | Добавить в `AnalysisTemplate` директиву `initialDelay: 2m-3m`. |
| **`AnalysisRun` падает с ошибкой `NaN` или `empty result`** | 1. Нет входящего трафика на канарейку.<br>2. PromQL делит на 0.<br>3. Недоступен Prometheus. | `kubectl describe analysisrun <name> -n <ns>` | Использовать в PromQL безопасное деление: `clamp_min(..., 0.001) or vector(1)`. |
| **Вес трафика в Ingress-NGINX игнорируется клиентами** | Включена липкость сессий (Sticky Sessions / Session Affinity), перебивающая канарейку. | `kubectl get ingress <name> -o yaml \| grep affinity` | Настроить `nginx.ingress.kubernetes.io/canary-by-header` для тестового трафика или отключить affinity для канарейки. |
| **HPA конфликтует с Rollout или выставляет неверные реплики** | HPA нацелен на удаленный `apps/v1 Deployment` вместо `Rollout`. | `kubectl get hpa <name> -o yaml \| grep -A 3 scaleTargetRef` | Изменить в HPA `scaleTargetRef.apiVersion` на `argoproj.io/v1alpha1` и `kind` на `Rollout`. |

### Сценарии восстановления (Runbooks)

#### Сценарий 1: Аварийная ручная фиксация при отказе сетевой маршрутизации
Если Ingress-контроллер не может применить аннотации канарейки, а трафик пользователей деградирует:
```bash
# 1. Немедленно прерываем Rollout, возвращая 100% трафика на стабильный Service
kubectl argo rollouts abort my-app -n production

# 2. Принудительно устанавливаем 100% стабильного веса в основном Ingress
kubectl annotate ingress my-app-ingress -n production --overwrite \
  nginx.ingress.kubernetes.io/canary-weight="0"

# 3. Удаляем теневой канареечный Ingress, если он завис
kubectl delete ingress my-app-my-app-canary -n production --ignore-not-found
```

#### Сценарий 2: Диагностика падения AnalysisRun
```bash
# 1. Находим имя активного или упавшего AnalysisRun
kubectl get analysisrun -n production -l rollouts-pod-template-hash
# → NAME                               STATUS   AGE
# → my-app-5649b85c88-2-quick-check-1  Failed   2m

# 2. Получаем точные значения метрик и причину сбоя
kubectl describe analysisrun my-app-5649b85c88-2-quick-check-1 -n production
# → Status:
# →   Metric Results:
# →     Name: success-rate
# →       Status: Failed
# →       Failed: 3
# →       Measurements:
# →         Value: [0.942]
# →         Message: Condition 'result[0] >= 0.99' evaluated false
```

---

## 6. Лучшие практики

### 1. Емкостной буфер на узлах кластера (Cluster Headroom Calculation)
- **Расчет запаса по памяти и CPU:** При проектировании bare-metal кластера минимальный запас емкости на нодах для канареечных выкаток рассчитывается по формуле:
  $$\text{Capacity}_{\text{Headroom}} \ge \sum \left( \text{Requests}_{\text{Pod}} \times \max(\text{CanaryReplicas}) \right) + \text{Node}_{\text{FailoverReserve}}$$
- Для Blue-Green развертываний запас свободных вычислительных ресурсов в кластере должен составлять не менее **100% от пикового потребления** сервиса.

### 2. Защита от холодного старта и прогрев (Warm-up & JIT Window)
- Всегда задавайте `initialDelay` (минимум 2–3 минуты) в метриках `AnalysisTemplate`. Первые запросы к новому поду в рантаймах с JIT (Java, .NET, Node.js) вызывают всплески процессорного времени и задержки из-за компиляции байткода и наполнения кэшей.
- Используйте хуки `preStop` (например, `sleep 10-15`) в контейнерах пода для обеспечения безаварийного завершения активных сетевых соединений при выводе старых реплик из пула.

### 3. Интеграция с GitOps (Argo CD / Flux)
- **Исключение конфликтов селекторов:** Контроллер Argo Rollouts динамически модифицирует `spec.selector` управляемых сервисов. В манифесте Argo CD `Application` необходимо обязательно объявить игнорирование различий (`ignoreDifferences`):
  ```yaml
  spec:
    ignoreDifferences:
    - group: ""
      kind: Service
      name: my-app-stable
      jsonPointers:
      - /spec/selector
    - group: ""
      kind: Service
      name: my-app-canary
      jsonPointers:
      - /spec/selector
  ```
- **Фиксация Target State в Git:** Репозиторий Git фиксирует целевой образ (например, `image: v2.0.0`). Вся механика перехода — временное состояние рантайма, управляемое Rollouts или Flagger.

### 4. Принцип минимального шага и окна стабилизации (Bake Time)
- Не переключайте веса с шагом более 20–25% за один этап.
- Рекомендуемая прогрессия для боевых сред: `5% (10m) → 20% (15m) → 50% (15m) → 100%`.
- Шаг с весом 5% позволяет изолировать критические дефекты (падения подов, несовместимость схемы БД, утечки памяти) на минимальном радиусе поражения (Blast Radius).

### 5. Метрическая изоляция и безопасный PromQL
- Никогда не используйте неэкранированное деление в запросах к Prometheus.
- Включайте фильтрацию метрик по селекторам конкретного сервиса или хэша репликасета (`pod_template_hash`), чтобы исключить попадание телеметрии стабильных подов в метрики канарейки.

---

## 7. Дополнительная информация

### Внутренние документы раздела Deployment

- [Deployment в Kubernetes](./index.md) — обзорная концепция, контроллеры и базовые механизмы `apps/v1 Deployment`.
- [Манифест и спецификация Deployment](./deployment_manifest.md) — полный справочник полей, QoS-классы и параметры надежности.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — математика ротации реплик, стратегия `RollingUpdate` и прерывание выкаток.
- [Мониторинг и Observability Deployment](./deployment_monitoring_observability.md) — метрики kube-state-metrics, cAdvisor и золотые сигналы SRE.
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — паттерны аварийного отката, сравнение `Rollout Undo` и GitOps Rollback.
- [Deployment с Service Mesh](./deployment_with_servicemesh.md) — интеграция с Istio и Linkerd для L7-управления трафиком.
- [Deployment с GitOps](./deployment_with_gitops.md) — декларативное развертывание через Argo CD и Flux.
- [Диагностика и устранение неполадок Deployment](./troubleshooting.md) — каталог аварийных ситуаций и SRE Runbooks.
- [Чек-лист готовности Deployment к Production](./production_checklist.md) — критерии надежности и безопасности для боевых сред.

### Связанные разделы базы знаний

- [Прогрессивная доставка в GitOps](../../../GitOps/Concepts/progressive_delivery_gitops.md) — детальный гайд по оркестрации выкаток через GitOps-пайплайны.
- [Канареечный деплой: мониторинг и автоматический гейтинг](../../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md) — математические модели оценки SLI/SLO и настройка судейских гейтов.
- [Сравнение стратегий развертывания](../../../CI-CD/Deployment_Strategies/comparison.md) — сравнительный анализ Rolling, Blue-Green, Canary, A/B и Shadow развертываний.
