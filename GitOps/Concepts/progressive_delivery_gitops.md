# Прогрессивная доставка в GitOps: Argo Rollouts и Flagger

**Актуально для:** Argo Rollouts v1.8.x, Flagger v1.44.x, Argo CD v3.5+, Flux v2.9.x, Gateway API v1.2+, Kubernetes 1.28–1.32+ (bare-metal / on-premise)

Прогрессивная доставка (canary, blue/green, A/B, traffic mirroring) — обязательный элемент production-зрелого GitOps в локальных (on-premise / bare-metal) кластерах: стандартный механизм `RollingUpdate` в Kubernetes переключает сетевой трафик на новую ревизию сразу по факту готовности проб (`ReadinessProbe`), задолго до того, как телеметрия и бизнес-метрики подтвердят стабильность релиза под реальной нагрузкой. Специализированные контроллеры прогрессивной доставки — **Argo Rollouts** и **Flagger** — дополняют декларативную GitOps-синхронизацию механизмом фазового управления трафиком и автоматического анализа метрик.

## Определения

- **Прогрессивная доставка (Progressive Delivery)**: Методология непрерывного развертывания, расширяющая Continuous Delivery контролем сетевого трафика. Включает поэтапное наращивание весов (Canary), параллельное мгновенное переключение (Blue/Green), сегментацию по атрибутам запроса (A/B) и теневое дублирование трафика (Traffic Mirroring).
- **Радиус поражения (Blast Radius)**: Доля пользовательского трафика, ресурсов кластера или бизнес-операций, подверженная сбою при дефекте в новой ревизии. Прогрессивная доставка удерживает начальный радиус поражения в пределах 1–10%.
- **Argo Rollouts**: Контроллер проекта Argo, заменяющий стандартный контроллер Deployment кастомным ресурсом `Rollout`. Напрямую управляет репликасетами (`ReplicaSet`), фазами паузы, шагами распределения трафика (`setWeight`) и ресурсами анализа.
- **AnalysisTemplate / AnalysisRun**: Пользовательские ресурсы (CRD) Argo Rollouts. `AnalysisTemplate` декларирует параметризованный шаблон проверки метрик (Prometheus PromQL, HTTP, Job). `AnalysisRun` представляет единичный запуск анализа; его провал переводит Rollout в статус деградации и запускает откат.
- **Flagger**: Контроллер прогрессивной доставки из экосистемы Flux (полноценно совместим с Argo CD). Работает как надстройка поверх стандартного Kubernetes `Deployment`, автоматически генерирует сервисы `<name>-primary` и `<name>-canary`, управляет объектами маршрутизации (HTTPRoute, Ingress, VirtualService) и проводит релиз по этапам.
- **MetricTemplate**: CRD Flagger, задающий шаблон запроса к провайдерам метрик (Prometheus). Включает встроенные провайдеры для расчета процента успешных ответов (`request-success-rate`) и задержки обработки (`request-duration`).
- **Окно наблюдения (Observation Window)**: Фиксированный интервал времени (шаг анализа), в течение которого собираются и анализируются метрики Canary перед принятием решения о переходе к следующему этапу.
- **Manual Gating (Ручной гейтинг)**: Механизм приостановки прогрессивного развертывания до получения явного подтверждения оператора или внешней системы комплаенса (через CLI-команду, паузу или webhook).
- **Traffic Shadowing / Mirroring (Зеркалирование трафика)**: Дублирование рабочего потока L7-запросов на новую ревизию без отправки ее ответов клиентам; позволяет оценить поведение сервиса под боевой нагрузкой без риска для пользователей.

## Архитектура и базовые концепции

### Сравнение моделей управления: Argo Rollouts vs Flagger

<a id="flagger-автономный-canary-для-deployment"></a>

| Аспект | Argo Rollouts | Flagger |
| :--- | :--- | :--- |
| **Модель ресурсов** | Замена: манифест описывает `kind: Rollout` (`argoproj.io/v1alpha1`) | Надстройка: остается штатный `kind: Deployment` (`apps/v1`), рядом создается `kind: Canary` (`flagger.app/v1beta1`) |
| **Управление подами** | Один ресурс `Rollout` управляет стабильным и канареечным ReplicaSet | Flagger клонирует Deployment в `<name>-primary`, а исходный Deployment использует как канарейку |
| **Генерация сетевых объектов** | Оператор объявляет Service в Git; Rollout меняет селекторы или веса в Ingress/HTTPRoute | Flagger сам динамически генерирует Service `<name>`, `<name>-primary`, `<name>-canary` и объекты Ingress/HTTPRoute |
| **Конфигурация шагов** | Внутри спецификации `spec.strategy.canary.steps` в манифесте приложения | В отдельном CRD `Canary` (`spec.analysis`) — стратегия отделена от спецификации приложения |
| **Анализ телеметрии** | Встроенные `AnalysisTemplate` (фоновые или пошаговые) с провайдером Prometheus | `spec.analysis.metrics` с ссылками на `MetricTemplate` и встроенные проверки |
| **Работа без Service Mesh/Ingress** | Доступна стратегия `blueGreen` на чистых Kubernetes Services | Доступен режим Blue/Green на чистом Kubernetes (`iterations` без traffic splitting) |
| **Рекомендуемый сценарий** | Команды сами владеют полным описанием выкатки в репозитории сервиса | Платформенная команда внедряет стандартизированный канареечный процесс без переписывания манифестов разработчиков |

### Архитектурный контракт с GitOps (Argo CD и Flux)

Ключевой контракт прогрессивной доставки: **Git фиксирует желаемое конечное состояние (Target State), а контроллер прогрессивной доставки управляет переходным процессом в рантайме кластера (State Transition Engine)**.

```text
  [ Git Repository ]
          │  (git commit: обновление тега образа billing-api:v2.0.0)
          ▼
┌────────────────────────────────────────┐
│      GitOps Controller                 │
│   (Argo CD Application / Flux Kustomize)│
└────────────────────────────────────────┘
          │  1. Синхронизирует Rollout или Deployment в кластер
          ▼
┌────────────────────────────────────────┐
│    Progressive Delivery Controller     │
│       (Argo Rollouts / Flagger)        │
└────────────────────────────────────────┘
          │  2. Фиксирует изменение PodTemplateSpec
          │  3. Разворачивает Canary-поды (0% трафика)
          │  4. Выполняет pre-rollout smoke tests / probes
          │  5. Поэтапно двигает веса: 10% → 25% → 50%
          │  6. Запрашивает Prometheus (AnalysisRun / MetricTemplate)
          │
          ├── [Метрики в норме (SLI OK)] ────► 100% трафика, Promotion, Healthy
          │
          └── [Метрики деградировали] ───────► Откат в кластере: 0% Canary, 100% Stable
                                               Статус Degraded / Failed
                                               Требуется: git revert в репозитории!
```

### Управление трафиком на On-Premise инфраструктуре

В отличие от облачных сред с управляемыми балансировщиками нагрузки, в on-premise кластерах маршрутизация трафика опирается на собственные сетевые компоненты:

1. **Ingress-NGINX**:
   - Реализуется через аннотации канарейки: `nginx.ingress.kubernetes.io/canary: "true"` и `nginx.ingress.kubernetes.io/canary-weight`.
   - Argo Rollouts управляет дополнительным Ingress-манифестом или мутирует аннотации основного.
   - Flagger генерирует парный Ingress (`<name>-canary`) и динамически меняет веса от 0 до 100.
2. **Kubernetes Gateway API (`gateway.networking.k8s.io/v1`)**:
   - Вендор-нейтральный стандарт для on-premise сред (поддерживается Envoy Gateway, Cilium, Traefik, Emissary).
   - Веса задаются декларативно в правилах `rules[].backendRefs[].weight` ресурса `HTTPRoute`.
   - Исключает зависимость от проприетарных аннотаций конкретного ingress-контроллера.
3. **Service Mesh (Istio / Linkerd)**:
   - Istio: управление весами через `VirtualService` и `DestinationRule` (подмножества `subsets: stable/canary`).
   - Linkerd: спецификация SMI `TrafficSplit` или прямое управление сервисами с endpoint-level балансировкой.
4. **Чистый Kubernetes (ClusterIP Services)**:
   - Без L7-манипуляций весами трафик распределяется дискретно при Blue/Green: контроллер переключает селектор основного `Service` с подов старой версии на поды новой версии после завершения приемочных тестов.

### Наблюдаемость, SRE Golden Signals и каналы обратной связи

Решение о продвижении релиза или немедленном откате принимается на основе SLI (Service Level Indicators):

- **Error Rate (Процент ошибок)**: Доля ответов с кодами `5xx` (или `4xx` при проверке клиентских API). Для Ingress-NGINX рассчитывается по метрике `nginx_ingress_controller_requests`.
- **Latency (Задержка ответов)**: 95-й и 99-й перцентили времени ответа (`request-duration`), измеряемые через `histogram_quantile`.
- **Saturation & Node Health (Ресурсы и стабильность)**: Отсутствие рестартов подов (`increase(kube_pod_container_status_restarts_total[5m]) == 0`) и исключение аварий OOMKilled во время анализа.
- **Webhooks**:
  - `pre-rollout`: Smoke-тесты и валидация схемы БД до подачи первого процента реального трафика.
  - `rollout`: Фоновые генераторы синтетической нагрузки (`load-tester`) для сервисов с низким естественным трафиком.
  - `confirm-rollout`: Точка ручной верификации (гейт для дежурного инженера или интеграции с Service Desk).
  - `post-rollout`: Финализация, очистка кэшей, отправка отчетов.

### Разрешение GitOps-конфликтов и предотвращение Drift

Поскольку контроллеры прогрессивной доставки динамически мутируют ресурсы во время выкатки, без специальной настройки GitOps-агенты входят в конфликт с рантаймом:

1. **Конфликт `spec.replicas` во Flagger**:
   - Flagger масштабирует исходный `Deployment` в ноль при завершении релиза, перенося поды в `<name>-primary`.
   - Если в Git зафиксировано `replicas: 3`, Argo CD или Flux попытаются вернуть поды обратно, спровоцировав бесконечный цикл реконсиляции.
   - **Решение**: Настройка `ignoreDifferences` в Argo CD на путь `/spec/replicas` исходного Deployment или использование HPA.
2. **Ложный статус Degraded во время пауз**:
   - Когда Rollout переходит в запланированную паузу (`pause: { duration: 10m }`), стандартный health-check Argo CD может интерпретировать отсутствие 100% готовности как сбой.
   - **Решение**: Регистрация кастомного Lua-скрипта оценки здоровья в `argocd-cm`.
3. **Рассинхронизация при откате**:
   - Автоматический откат контроллером локален для кластера: контроллер вернул 100% трафика на стабильную версию, но в Git по-прежнему закоммичен тег сбойного релиза.
   - Любая принудительная синхронизация (`Hard Refresh` / `Sync`) перезапустит дефектный релиз.
   - **Решение**: Немедленный `git revert` в Git-репозитории, автоматизируемый через вебхуки алертинга Flagger/Rollouts в CI-пайплайн.

---

## Практические сценарии

### Предварительные требования к инфраструктуре

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **Kubernetes** | Базовый кластер (bare-metal или on-premise гипервизоры) | v1.28–v1.32+ |
| **Argo Rollouts** | Контроллер прогрессивной доставки | v1.8.x (`kubectl-argo-rollouts` CLI) |
| **Flagger** | Контроллер канареечных релизов | v1.44.x (CRD `flagger.app/v1beta1`) |
| **L7-маршрутизация** | Ingress-NGINX (v1.10+) или Gateway API v1.2+ (Envoy Gateway) | Поддержка канареечных весов |
| **Мониторинг** | Prometheus Server v2.50+ / v3.x | Доступен по HTTP внутри кластера |
| **GitOps-агент** | Argo CD v3.5+ или Flux v2.9+ | Настроенный доступ к репозиторию |

---

### Сценарий 1: Canary через Argo Rollouts и Ingress-NGINX с доставкой Argo CD

Сценарий демонстрирует развертывание сервиса `billing-api` с управлением трафиком через Ingress-NGINX и анализом Golden Signals в Prometheus.

#### Шаг 1: Манифест Rollout приложения

В Git-репозитории манифест описывается как `Rollout`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: billing-api
  namespace: billing
spec:
  replicas: 10
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: billing-api
  strategy:
    canary:
      canaryService: billing-api-canary
      stableService: billing-api-stable
      trafficRouting:
        nginx:
          stableIngress: billing-api-ingress
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - analysis:
            templates:
              - templateName: billing-metrics-analysis
            args:
              - name: service-name
                value: billing-api-canary
        - setWeight: 30
        - pause: { duration: 5m }
        - analysis:
            templates:
              - templateName: billing-metrics-analysis
            args:
              - name: service-name
                value: billing-api-canary
        - setWeight: 60
        - pause: { duration: 5m }
  template:
    metadata:
      labels:
        app: billing-api
    spec:
      containers:
        - name: api
          image: harbor.internal/billing/api:v1.9.0
          ports:
            - name: http
              containerPort: 8080
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: 1000m
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
```

#### Шаг 2: Сетевые сервисы и Ingress

Для разделения стабильного и канареечного трафика требуются два Service и базовый Ingress:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: billing-api-stable
  namespace: billing
spec:
  ports:
    - name: http
      port: 80
      targetPort: 8080
  selector:
    app: billing-api
---
apiVersion: v1
kind: Service
metadata:
  name: billing-api-canary
  namespace: billing
spec:
  ports:
    - name: http
      port: 80
      targetPort: 8080
  selector:
    app: billing-api
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: billing-api-ingress
  namespace: billing
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
    - host: billing.internal
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: billing-api-stable
                port:
                  number: 80
```

#### Шаг 3: Шаблон анализа метрик (AnalysisTemplate)

Шаблон запрашивает Prometheus и валидирует процент успешных ответов (≥ 99%) и задержку P99 (≤ 500 мс) с защитой от деления на ноль:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: billing-metrics-analysis
  namespace: billing
spec:
  args:
    - name: service-name
  metrics:
    - name: success-rate
      interval: 1m
      count: 5
      successCondition: result[0] >= 0.99
      failureLimit: 1
      provider:
        prometheus:
          address: http://prometheus-k8s.monitoring.svc.cluster.local:9090
          query: |
            sum(rate(nginx_ingress_controller_requests{exported_service="{{ args.service-name }}",status!~"[5].*"}[2m]))
            /
            clamp_min(sum(rate(nginx_ingress_controller_requests{exported_service="{{ args.service-name }}"}[2m])), 0.001)
    - name: p99-latency
      interval: 1m
      count: 5
      successCondition: result[0] <= 0.500
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus-k8s.monitoring.svc.cluster.local:9090
          query: |
            histogram_quantile(0.99, sum(rate(nginx_ingress_controller_request_duration_seconds_bucket{exported_service="{{ args.service-name }}"}[2m])) by (le))
```

#### Шаг 4: Настройка Health Check в Argo CD

Для исключения ложной деградации приложения в Argo CD добавляется настройка в ConfigMap `argocd-cm`:

```yaml
# Дополнение в ConfigMap argocd-cm
data:
  resource.customizations.health.argoproj.io_Rollout: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.phase == "Healthy" then
        hs.status = "Healthy"
        hs.message = "Rollout is healthy"
        return hs
      end
      if obj.status.phase == "Paused" then
        hs.status = "Suspended"
        hs.message = "Rollout is paused (canary gating)"
        return hs
      end
      if obj.status.phase == "Progressing" then
        hs.status = "Progressing"
        hs.message = "Rollout is progressing"
        return hs
      end
      if obj.status.phase == "Degraded" then
        hs.status = "Degraded"
        hs.message = "Rollout is degraded"
        return hs
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for rollout status"
    return hs
```

#### Шаг 5: Валидация выкатки

```bash
# Мониторинг прогресса выкатки в реальном времени
kubectl argo rollouts get rollout billing-api -n billing --watch
# → Name:            billing-api
# → Status:          ॥ Paused
# → Strategy:        Canary
# →   Step:          1/5 (pause 5m)
# →   SetWeight:     10
# →   ActualWeight:  10

# Проверка созданного ингресса канарейки контроллером Rollouts
kubectl get ingress -n billing
# → billing-api-ingress          billing.internal   10.0.10.15   80
# → billing-api-billing-api-canary-ingress   billing.internal   10.0.10.15   80

# Инспекция активного анализа метрик
kubectl get analysisrun -n billing
# → NAME                                  FILLED   PHASE
# → billing-api-7b8f84478f-2-1            5/5      Successful
```

---

### Сценарий 2: Canary через Flagger поверх стандартного Deployment с Gateway API

Сценарий использует Kubernetes Gateway API (`HTTPRoute`), не требует изменения исходного манифеста `Deployment` и включает предварительный smoke-тест через webhook.

#### Шаг 1: Установка Flagger в on-premise кластер

```bash
helm repo add flagger https://flagger.app
helm repo update
helm upgrade -i flagger flagger/flagger \
  --namespace flagger-system \
  --create-namespace \
  --set meshProvider=gatewayapi:v1 \
  --set metricsServer=http://prometheus-k8s.monitoring.svc.cluster.local:9090
# → STATUS: deployed
# → REVISION: 1
```

#### Шаг 2: Манифест Flagger Canary

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: billing-api
  namespace: billing
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-api
  progressDeadlineSeconds: 600
  service:
    port: 8080
    targetPort: 8080
    hosts:
      - billing.internal
    gatewayRefs:
      - name: internal-gateway
        namespace: gateway-infra
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
        interval: 30s
    webhooks:
      - name: smoke-test
        type: pre-rollout
        url: http://flagger-loadtester.flagger-system/
        timeout: 30s
        metadata:
          type: bash
          cmd: "curl -sf http://billing-api-canary.billing:8080/healthz"
      - name: load-generator
        type: rollout
        url: http://flagger-loadtester.flagger-system/
        timeout: 5s
        metadata:
          type: cmd
          cmd: "hey -z 1m -q 20 -c 2 http://billing.internal/healthz"
```

#### Шаг 3: Настройка Argo CD Application (предотвращение конфликта реплик)

При работе Flagger манифест `Application` в Argo CD обязан содержать правило игнорирования:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-api
  namespace: argocd
spec:
  destination:
    server: https://kubernetes.default.svc
    namespace: billing
  source:
    repoURL: git@gitlab.internal:finance/billing.git
    targetRevision: main
    path: k8s/overlays/prod
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: billing-api
      jsonPointers:
        - /spec/replicas
```

#### Шаг 4: Наблюдение за релизом

```bash
# Просмотр статуса Canary
kubectl get canaries.flagger.app -n billing
# → NAME          STATUS        WEIGHT   LASTTRANSITIONTIME
# → billing-api   Progressing   20%      2026-10-13T16:45:10Z

# Проверка автоматически сгенерированных HTTPRoute с распределением весов
kubectl get httproute -n billing billing-api -o yaml | grep -A 8 backendRefs
# → backendRefs:
# → - group: ""
# →   kind: Service
# →   name: billing-api-primary
# →   port: 8080
# →   weight: 80
# → - group: ""
# →   kind: Service
# →   name: billing-api-canary
# →   port: 8080
# →   weight: 20
```

---

### Сценарий 3: Blue/Green развертывание без Service Mesh (чистый Kubernetes)

Для инфраструктур без L7-маршрутизаторов и Mesh прогрессивная доставка реализуется через мгновенное переключение `Service` на проверенный пул подов.

#### Вариант А: Argo Rollouts Blue/Green

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: internal-auth
  namespace: security
spec:
  replicas: 5
  strategy:
    blueGreen:
      activeService: internal-auth-active
      previewService: internal-auth-preview
      autoPromotionEnabled: false
      scaleDownDelaySeconds: 60
      prePromotionAnalysis:
        templates:
          - templateName: auth-smoke-analysis
  selector:
    matchLabels:
      app: internal-auth
  template:
    metadata:
      labels:
        app: internal-auth
    spec:
      containers:
        - name: auth
          image: harbor.internal/sec/auth:v2.4.0
          ports:
            - containerPort: 9000
```

В этой конфигурации:
1. Новая версия разворачивается и подключается к `internal-auth-preview`.
2. Запускается приемочный анализ `prePromotionAnalysis`.
3. Поскольку `autoPromotionEnabled: false`, Rollout ожидает подтверждения инженера.
4. После подтверждения селектор `internal-auth-active` мгновенно указывает на новую ревизию.
5. Старая версия подов продолжает работать 60 секунд (`scaleDownDelaySeconds`), обеспечивая дожим активных соединений, после чего масштабируется в ноль.

#### Вариант Б: Flagger Blue/Green на чистом Kubernetes

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: internal-auth
  namespace: security
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: internal-auth
  service:
    port: 9000
  analysis:
    interval: 1m
    threshold: 3
    iterations: 5
    mirror: false
    webhooks:
      - name: conformance-test
        type: rollout
        url: http://flagger-loadtester.flagger-system/
        timeout: 60s
        metadata:
          type: bash
          cmd: "curl -sf http://internal-auth-canary.security:9000/ready"
```

При отсутствии mesh-провайдера Flagger выполняет указанное число итераций (`iterations: 5`) conformance-тестов против канареечных подов. При успехе всех 5 проверок `internal-auth-primary` получает новый образ, а канареечный Deployment сворачивается.

---

### Сценарий 4: Ручной гейт подтверждения выпуска (Manual Gating)

В регламентированных контурах требуется пауза перед переводом основного потока пользователей на новую версию.

#### Вариант А: Бесконечная пауза в Argo Rollouts

В спецификации шагов `Rollout` последний шаг объявляется пустым объектом `{}`:

```yaml
      steps:
        - setWeight: 20
        - pause: { duration: 10m }
        - setWeight: 50
        - pause: {}  # Бесконечная пауза: требует явного подтверждения
```

Операторские команды:

```bash
# Проверка статуса Rollout (находится в ожидании подтверждения)
kubectl argo rollouts status billing-api -n billing
# → Rollout 'billing-api' is paused at step 4/4

# Ручное подтверждение и продолжение выкатки до 100%
kubectl argo rollouts promote billing-api -n billing
# → rollout 'billing-api' promoted

# Экстренное прерывание и немедленный откат
kubectl argo rollouts abort billing-api -n billing
# → rollout 'billing-api' aborted
```

#### Вариант Б: Webhook подтверждения во Flagger (`confirm-rollout`)

```yaml
    webhooks:
      - name: change-approval-gate
        type: confirm-rollout
        url: http://change-approval.internal/v1/verify
        timeout: 30s
```

Flagger перед переводом веса на следующий этап отправляет HTTP POST запрос. Пока сервис авторизации изменений не вернет код HTTP `200 OK`, выпуск удерживается на текущем шаге.

---

### Сценарий 5: A/B-тестирование по HTTP-заголовкам и Cookie

A/B-тестирование направляет на новую версию запросы конкретной группы пользователей (внутренние тестировщики, бета-пользователи, сотрудники компании).

#### Конфигурация Flagger с L7-матчингом

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: billing-api
  namespace: billing
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-api
  service:
    port: 8080
    match:
      - headers:
          x-canary-user:
            exact: internal-qa
      - headers:
          cookie:
            regex: ".*canary=true.*"
  analysis:
    interval: 1m
    iterations: 10
    threshold: 3
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99
```

Все входящие запросы с заголовком `X-Canary-User: internal-qa` или соответствующей cookie направляются на `billing-api-canary`. Обычные клиенты не затрагиваются.

#### Argo Rollouts Experiment (Изолированные эксперименты)

Для независимой валидации нескольких ревизий параллельно с основным Rollout используется ресурс `Experiment`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Experiment
metadata:
  name: billing-ab-experiment
  namespace: billing
spec:
  duration: 30m
  analyses:
    - templateName: billing-metrics-analysis
      args:
        - name: service-name
          value: billing-experiment-candidate
  templates:
    - name: candidate
      specRef: stable
      replicas: 2
      template:
        metadata:
          labels:
            app: billing-experiment
        spec:
          containers:
            - name: api
              image: harbor.internal/billing/api:v2.0.0-rc.2
```

---

### Сценарий 6: Traffic Mirroring (теневой трафик / Shadowing)

Зеркалирование копирует реальный входящий L7-трафик и отправляет его копию на канарейку. Ответы канарейки отбрасываются и не возвращаются клиенту.

```yaml
# Фрагмент Canary Flagger с зеркалированием
spec:
  analysis:
    interval: 1m
    iterations: 15
    threshold: 3
    mirror: true
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99.5
```

**Ограничения и правила SRE при Traffic Mirroring:**

1. **Идемпотентность и побочные эффекты (Side Effects)**:
   - При зеркалировании запросов с методами `POST`, `PUT`, `DELETE`, `PATCH` обе версии сервиса получают тело запроса.
   - Если сервис производит запись в базу данных, отправку сообщений в брокер (Kafka/RabbitMQ) или внешние API, произойдет **двойная запись или дублирование транзакций**.
   - **Правило**: Зеркалирование безопасно применять только к сервисам, работающим в режиме чтения (Read-Only), либо сервисам, в которых канареечный контур переключен на изолированную тестовую базу данных или теневой топик брокера.
2. **Двойная нагрузка на вспомогательную инфраструктуру**:
   - Канареечные поды создают дополнительную нагрузку на общие кэши (Redis/Memcached) и пулы соединений баз данных. Необходимо учитывать лимиты соединений СУБД.

---

### Сценарий 7: Совместимость с миграциями баз данных (Expand/Contract)

Прогрессивная доставка подразумевает, что в кластере **одновременно работают две версии кода**: стабильная (v1) и канареечная (v2). Сбой миграции БД ломает стабильную версию под 90% трафика.

**Паттерн двухфазной миграции (Expand/Contract):**

```text
Фаза 1: Расширение (Expand)
  1. Выполняется обратно-совместимая миграция БД (добавление нового nullable-поля).
  2. База данных поддерживает обе версии кода (v1 читает старое поле, v2 читает и пишет новое).
  
Фаза 2: Канареечный выпуск (Canary Rollout)
  1. Разворачивается версия кода v2 с шагами 10% → 50% → 100%.
  2. При сбое выполняется мгновенный откат: код v1 продолжает работать, так как схема БД не сломана.

Фаза 3: Сжатие (Contract)
  1. После успешного 100% промоушена v2 запускается отдельный Job очистки схемы БД (удаление старого столбца).
```

---

## Операции и команды управления

### Управление жизненным циклом через CLI `kubectl-argo-rollouts`

Плагин `kubectl-argo-rollouts` является основным оперативным инструментом администратора для ручного управления процессом прогрессивной доставки.

| Команда | Описание действия | Ожидаемый вывод / Реакция |
| :--- | :--- | :--- |
| `kubectl argo rollouts get rollout <name> -n <ns>` | Подробный статус Rollout, шаги, веса и репликасеты | Таблица ревизий, весов и прогресса анализа |
| `kubectl argo rollouts get rollout <name> -n <ns> --watch` | Непрерывный мониторинг перехода по шагам | Динамическое обновление вывода терминала |
| `kubectl argo rollouts promote <name> -n <ns>` | Ручное продвижение на следующий шаг паузы | `# → rollout '<name>' promoted` |
| `kubectl argo rollouts promote <name> -n <ns> --full` | Немедленный переход на 100% трафика (пропуск шагов) | `# → rollout '<name>' fully promoted` |
| `kubectl argo rollouts pause <name> -n <ns>` | Принудительная пауза текущего выполнения | `# → rollout '<name>' paused` |
| `kubectl argo rollouts resume <name> -n <ns>` | Возобновление ранее приостановленного развертывания | `# → rollout '<name>' resumed` |
| `kubectl argo rollouts abort <name> -n <ns>` | Экстренная отмена: возврат 100% трафика на stable | `# → rollout '<name>' aborted` |
| `kubectl argo rollouts retry <name> -n <ns>` | Повторный запуск после прерывания или сбоя | `# → rollout '<name>' retried` |
| `kubectl argo rollouts undo <name> -n <ns>` | Откат к предыдущей успешной ревизии | `# → rollout '<name>' undone (v2 → v1)` |
| `kubectl argo rollouts dashboard -n <ns> --port=3100` | Запуск локального графического веб-интерфейса | Открытие дашборда на `http://localhost:3100` |

### Эксплуатация и мониторинг Flagger через `kubectl`

```bash
# Получение списка всех активных канареек во всех неймспейсах
kubectl get canaries.flagger.app -A
# → NAMESPACE   NAME          STATUS        WEIGHT   LASTTRANSITIONTIME
# → billing     billing-api   Progressing   30%      2026-10-13T16:47:00Z

# Детальная инспекция событий Flagger (причины откатов и результаты вебхуков)
kubectl describe canary billing-api -n billing
# → Events:
# →   Type     Reason  Age                From     Message
# →   ----     ------  ----               ----     -------
# →   Normal   Synced  3m                 flagger  Advance billing-api canary weight 20
# →   Warning  Synced  2m                 flagger  Halt billing-api advancement: success rate 97.4% < 99%
# →   Warning  Synced  1m                 flagger  Rolling back billing-api failed checks threshold reached (5)

# Просмотр логов контроллера Flagger
kubectl logs -n flagger-system deployment/flagger -f --tail=100
```

### Экстренные действия SRE при инциденте

Если канареечная версия вызвала деградацию зависимых систем, не дожидаясь срабатывания порогов анализа метрик:

1. **Для Argo Rollouts:**
   ```bash
   # Мгновенная изоляция канарейки и возврат стабильной версии
   kubectl argo rollouts abort billing-api -n billing
   # Проверка, что канареечный вес обнулен
   kubectl argo rollouts get rollout billing-api -n billing
   ```
2. **Для Flagger:**
   ```bash
   # Блокировка выкатки через установку аннотации ручного гейта
   kubectl annotate canary billing-api -n billing flagger.app/manual-gate=halt --overwrite
   # И принудительный откат в stable:
   kubectl annotate canary billing-api -n billing flagger.app/manual-gate=rollback --overwrite
   ```
3. **Обязательное завершение инцидента в GitOps:**
   ```bash
   # Создание коммита отката в Git, чтобы GitOps-агент не вернул дефектный релиз
   git revert HEAD -m "revert(billing): rollback failed canary release"
   git push origin main
   ```

---

## Диагностика и устранение неполадок

### Сводная таблица типовых сбоев

| Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Argo CD показывает статус OutOfSync циклически** | Flagger изменяет `spec.replicas` или селекторы, а Argo CD пытается вернуть манифест из Git | Проверить `App Details → Diff` в интерфейсе Argo CD | Добавить `/spec/replicas` в `spec.ignoreDifferences` манифеста `Application` |
| **AnalysisTemplate падает с ошибкой пустого ряда или NaN** | Запрос к Prometheus возвращает пустой результат (нет трафика или неверные метки сервиса) | Выполнить PromQL запрос напрямую в Prometheus UI: `sum(rate(nginx_...))` | Использовать `clamp_min(..., 0.001)` или fallback: `(...) or vector(1)` для защиты от деления на ноль |
| **Вес трафика не меняется в Ingress-NGINX** | Отсутствует модуль канарейки в ingress-контроллере либо не совпадает `host` в stable и canary ingress | `kubectl describe ingress -n <ns>`: проверить наличие аннотации `nginx.ingress.kubernetes.io/canary: "true"` | Убедиться, что `host` и пути в основном Ingress и в Rollout `trafficRouting` идентичны |
| **Flagger не генерирует сетевые объекты (HTTPRoute/Service)** | В CRD `Canary` не указаны `service.hosts` или указан несуществующий `meshProvider` | `kubectl describe canary <name>`: проверить блок Events на ошибки валидации CRD | Проверить соответствие флага установки Flagger (`meshProvider=gatewayapi:v1`) фактической сетевой инфраструктуре |
| **Rollout зависает на шаге паузы как Degraded в Argo CD** | В Argo CD отсутствует кастомный Lua-скрипт оценки статуса ресурса `Rollout` | В Argo CD статус приложения `Degraded`, хотя поды работают корректно | Прописать Lua-скрипт оценки `argoproj.io_Rollout` в ConfigMap `argocd-cm` |
| **Дефектный релиз перезапускается после автоматического отката** | Контроллер прогрессивной доставки откатил версию в кластере, но в Git остался коммит с плохим тегом | Проверить статус Git-репозитория и историю синхронизации GitOps-агента | Выполнить `git revert` в целевой ветке репозитория и синхронизировать GitOps-агент |
| **Трафик не распределяется пропорционально весам (Keep-Alive)** | Клиенты или вышестоящие балансировщики удерживают долгоживущие TCP/HTTP Keep-Alive соединения | Метрики на бэкендах показывают перекос запросов вопреки весам Ingress | Настроить в Ingress-NGINX `keepalive_requests` (например, 100) и `keepalive_timeout` для принудительной перебалансировки |
| **PDB (PodDisruptionBudget) блокирует удаление старых реплик** | Задано жесткое значение `minAvailable: 100%` во время канареечного масштабирования | `kubectl get pdb -n <ns>`: `ALLOWED DISRUPTIONS: 0` | Снизить требования PDB до `maxUnavailable: 20%` или использовать динамический расчет |

### Пошаговые процедуры расследования инцидентов

#### Процедура 1: Анализ сбоя PromQL метрик в AnalysisRun

```bash
# 1. Поиск упавшего AnalysisRun
kubectl get analysisrun -n billing --sort-by=.metadata.creationTimestamp
# → billing-api-659f8c6b79-1-1   Failed   2026-10-13T16:48:12Z

# 2. Детальный просмотр причин провала метрик
kubectl describe analysisrun billing-api-659f8c6b79-1-1 -n billing
# → Status:
# →   Metric Results:
# →     Name:  success-rate
# →     Phase: Failed
# →     Failed: 2
# →     Measurements:
# →       Value: [0.962]   # Порог был >= 0.99!

# 3. Проверка доступности Prometheus из неймспейса приложения
kubectl run debug-curl --rm -it --image=curlimages/curl --restart=Never -n billing -- \
  curl -s "http://prometheus-k8s.monitoring.svc.cluster.local:9090/api/v1/query?query=up"
```

#### Процедура 2: Проверка генерации внутренних сервисов Flagger

```bash
# 1. Проверка наличия primary и canary сервисов
kubectl get svc -n billing -l app.kubernetes.io/name=billing-api
# → billing-api           ClusterIP   10.96.100.12   <none>   8080/TCP
# → billing-api-canary    ClusterIP   10.96.100.13   <none>   8080/TCP
# → billing-api-primary   ClusterIP   10.96.100.14   <none>   8080/TCP

# 2. Проверка соответствия селекторов подов
kubectl get ep -n billing billing-api-primary billing-api-canary
# → Должны содержать непустые списки IP-адресов соответствующих подов
```

---

## Рекомендации и Best Practices

1. **Размер окон наблюдения и шаг весов**:
   - Никогда не переключайте трафик крупными скачками (например, 0% → 50% → 100%).
   - Рекомендуемая производственная сетка для SRE: **5% (10 минут) → 20% (15 минут) → 50% (15 минут) → 100%**.
   - Начальный шаг 5% локализует возможный критический инцидент в узком радиусе поражения.
2. **Защита от статистических аномалий при низком RPS**:
   - При 1 запросе в секунду на канарейку (5% от 20 RPS) один случайный таймаут дает 100% ошибок, что вызовет ложный откат.
   - Используйте формулу с минимальным порогом объема: запрашивайте процент ошибок только при условии `sum(rate(requests[5m])) > 10`.
   - Включайте `initialDelay` (минимум 2–3 минуты) в `AnalysisTemplate` для защиты от ложных срабатываний во время JIT-компиляции и прогрева кэшей приложения.
3. **Взаимодействие с HPA (Horizontal Pod Autoscaler)**:
   - При использовании Argo Rollouts HPA должен указывать непосредственно на ресурс Rollout:
     ```yaml
     scaleTargetRef:
       apiVersion: argoproj.io/v1alpha1
       kind: Rollout
       name: billing-api
     ```
   - При использовании Flagger HPA указывает на исходный `Deployment`; Flagger автоматически клонирует HPA для `<name>-primary`.
4. **Контракт обратной совместимости API и очередей**:
   - Обе ревизии (v1 и v2) обязаны уметь читать одни и те же очереди сообщений (RabbitMQ / Kafka) и корректно десериализовать полезную нагрузку.
   - Изменение контракта API должно производиться через версионирование эндпоинтов (`/v1`, `/v2`), а не ломающие изменения в рамках одной схемы.
5. **Автоматизация отката в репозитории**:
   - Настройте алерт во Flagger/Alertmanager на событие `CanaryFailed`.
   - Подключите webhook к скрипту автоматического создания Pull Request / Merge Request с `git revert` для фиксации состояния в Git SSoT.

---

## Дополнительная информация

### Взаимодействие с механизмами GitOps

| Механизм | Архитектурное сочетание |
| :--- | :--- |
| **Sync Waves / dependsOn** | Контроллер прогрессивной доставки (Argo Rollouts или Flagger) и Prometheus Operator обязаны разворачиваться в инфраструктурных волнах с более низким индексом (например, wave `-1` или зависимый Kustomization), чем прикладные приложения |
| **Ignore Differences** | Поля, динамически мутируемые контроллерами доставки (веса маршрутизаторов, селекторы сервисов, число реплик исходного Deployment во Flagger), должны быть объявлены в правилах игнорирования GitOps-агента |
| **Progressive Sync (Fleet-level)** | Многоуровневая безопасность: Progressive Sync разворачивает приложение последовательно по кластерам (dev → stage → prod-eu → prod-us), а Argo Rollouts / Flagger управляют канарейкой трафика внутри каждого отдельного кластера |
| **Notifications** | События успешного завершения анализа или автоматического отката транслируются через контроллеры уведомлений в командные каналы и SIEM |
| **Audit Logs** | Каждый этап смены веса и результаты AnalysisRun фиксируются в событиях Kubernetes API и дополняют цепочку аудита GitOps (коммит → OCI-образ → результат анализа) |

### Связанные документы

- [Канареечное развертывание](../../CI-CD/Deployment_Strategies/canary_deployment.md) — фундаментальная теория разделения трафика, математические модели оценки и требования к L7-балансировщикам.
- [Обзор методологии GitOps](../GitOps_overview.md) — принципы декларативного согласования и место прогрессивной доставки в архитектуре.
- [Уведомления в GitOps](../gitops_notifications.md) — конфигурация оповещений об изменениях и авариях.
- [Feature Flags в GitOps](./feature_flags_gitops.md) — разделение понятий деплоя кода и выпуска функционала для пользователей.
- [DORA-метрики в GitOps](./dora_metrics_gitops.md) — оценка эффективности прогрессивной доставки через снижение CFR (Change Failure Rate) и MTTR (Mean Time to Restore).
- [Журналы аудита и трассируемость](./audit_logs.md) — сквозная трассируемость изменений от коммита до событий рантайма.
- [Игнорирование различий в Argo CD](../ArgoCD/synchronization/ignore_differences.md) — тонкая настройка `ignoreDifferences` для исключения конфликтов синхронизации.
- [Сравнение манифестов Argo CD и Flux](../argo_vs_flux_manifests.md) — особенности декларативного описания релизов в двух ведущих GitOps-инструментах.

---

## Вопросы для собеседования

### 1. Чем канареечное развертывание (Canary) принципиально отличается от A/B-тестирования?
**Canary Deployment** распределяет входящий трафик случайно по процентным весам (например, 10/90). Его цель чисто техническая — оценка стабильности и надежности (SRE Golden Signals: процент 5xx ошибок, латентность, потребление памяти). 
**A/B-тестирование** маршрутизирует трафик детерминированно на основе бизнес-атрибутов запроса (HTTP-заголовки, cookie, авторизованный ID пользователя, User-Agent). Его цель продуктовая — сравнение конверсии, поведения двух когорт пользователей или тестирование функционала на ограниченной группе бета-тестеров.

### 2. Почему после автоматического отката канарейки в кластере обязателен коммит `git revert`?
Контроллер прогрессивной доставки (Argo Rollouts или Flagger) производит откат исключительно на уровне рантайма кластера (переключает вес трафика на 0% и восстанавливает стабильный ReplicaSet). В Git-репозитории целевое состояние (Target State) остается неизменным и указывает на дефектный тег образа. Любой последующий запуск синхронизации GitOps-агента (`Sync`, перезапуск пода оператора, пуш соседнего изменения) приведет к повторному развертыванию сбойной версии. `git revert` возвращает единственный источник истины (Git) в соответствие с фактическим стабильным состоянием кластера.

### 3. Что произойдет при попытке выполнить UI Rollback в Argo CD для ресурса Rollout во время активной канарейки?
Argo CD попытается вернуть предыдущую ревизию ресурса `Rollout` через GitOps API, что вступит в конфликт с активным циклом реконсиляции контроллера Argo Rollouts (который управляет шагами `steps` и объектами `AnalysisRun`). Если включен `auto-sync` с `selfHeal`, Argo CD через короткое время перезапишет состояние кластера обратно манифестом из Git. Управлять откатом канарейки необходимо через CLI `kubectl argo rollouts undo/abort` либо через откат коммита в Git.

### 4. В каких ситуациях Flagger архитектурно предпочтительнее Argo Rollouts?
Flagger предпочтителен в платформенных командах, где разработчики используют стандартные манифесты Kubernetes `Deployment` и не должны переписывать их на сторонний CRD `Rollout`. Flagger подключается декларативно «сбоку» отдельным CRD `Canary`, берет на себя генерацию вспомогательных сервисов и маршрутов, а также предоставляет гибкую систему вебхуков (pre/post-rollout). Argo Rollouts выигрывает, когда команда полностью контролирует манифесты сервиса, хочет видеть шаги выкатки непосредственно в PR и использует встроенный Rollouts Dashboard / CLI.

### 5. Как прогрессивная доставка влияет на ключевые метрики DORA?
- **Change Failure Rate (CFR)**: Резко снижается, поскольку дефект локализуется на 5–10% трафика и автоматически купируется без возникновения полноценного инцидента и влияния на всех пользователей.
- **Mean Time to Restore (MTTR)**: Сокращается с десятков минут (время обнаружения человеком + ручной деплой) до секунд/минут автоматического отката по метрикам Prometheus.
- **Deployment Frequency (DF)**: Возрастает, так как автоматические защитные гейты снижают страх инженеров перед частыми релизами в production.

### 6. Как долгоживущие HTTP Keep-Alive соединения влияют на точность разделения трафика (Traffic Splitting)?
В протоколах HTTP/1.1 и gRPC (HTTP/2) клиенты и промежуточные балансировщики используют пул постоянных TCP-соединений (Keep-Alive). Если Ingress или L7-маршрутизатор распределяет трафик на уровне соединений, а не на уровне отдельных запросов, изменение веса не затронет уже открытые соединения. Новые поды канарейки будут получать 0% трафика от существующих клиентов. Для корректной работы L7-маршрутизаторы обязаны распределять вес per-request и ограничивать максимальное время жизни соединения (`keepalive_requests`, `keepalive_timeout`, `max_connection_age`).

### 7. Как правильно настраивать Horizontal Pod Autoscaler (HPA) при работе с Argo Rollouts и Flagger?
- В **Argo Rollouts** HPA настраивается непосредственно на `scaleTargetRef.kind: Rollout`. Контроллер Rollouts сам рассчитывает и пропорционально делит вычисленное число реплик между стабильным и канареечным ReplicaSet в зависимости от текущего шага веса трафика.
- Во **Flagger** HPA настраивается на исходный `Deployment`. При инициализации Flagger дублирует HPA для сгенерированного `Deployment` `<name>-primary`, обеспечивая независимое масштабирование стабильной версии под основной нагрузкой.
