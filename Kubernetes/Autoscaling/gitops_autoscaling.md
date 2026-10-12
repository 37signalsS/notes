# GitOps для Autoscaling: управление HPA, VPA, KEDA и узлами через Git

**Актуально для:** Kubernetes 1.28–1.32+, Argo CD 2.10–3.0+, Flux v2.3–v2.4+, KEDA 2.12–2.16+, Cluster API v1.7–v1.9+

## Определения

**GitOps** — парадигма управления инфраструктурой и приложениями, при которой декларативное состояние кластера хранится в системе контроля версий Git как единственный источник истины (Single Source of Truth, SSoT), а автоматизированные контроллеры (Argo CD, Flux) непрерывно синхронизируют фактическое состояние (live state) с целевым состоянием (desired state).

**ignoreDifferences** — декларативный механизм в Argo CD, предписывающий контроллеру приложений игнорировать расхождения между Git и live-состоянием для конкретных JSON-путей (`jsonPointers`), выражений (`jqPathExpressions`) или менеджеров полей (`managedFieldsManagers`).

**Server-Side Apply (SSA)** — встроенный механизм Kubernetes API (общедоступен с v1.22+), отслеживающий владельцев каждого поля манифеста через структуру `metadata.managedFields`. Позволяет нескольким независимым контроллерам бесконфликтно управлять разными полями одного объекта.

**RespectIgnoreDifferences** — параметр политики синхронизации Argo CD (`syncOptions`), указывающий контроллеру исключать игнорируемые поля не только при расчете diff (статус `Synced`), но и при непосредственной отправке patch-запроса в API-сервер во время синхронизации (`Sync`/`Self-Heal`).

**Reconciliation Loop Fight (гонка синхронизации)** — критическое состояние циклического конфликта между GitOps-агентом и контроллером автомасштабирования (HPA, KEDA, VPA, Cluster Autoscaler), при котором один компонент динамически мутирует поля объекта в кластере, а второй принудительно возвращает их к зафиксированному в Git значению.

**Drift Detection (детекция дрейфа)** — непрерывный процесс обнаружения различий между объявленным в Git состоянием и реальным состоянием ресурсов в etcd. В контексте autoscaling легитимные изменения (`.spec.replicas`, `resources.requests`) должны быть исключены из детекции дрейфа во избежание ложных тревог и внезапных откатов.

**GitOps Write-Back (обратная запись в Git)** — архитектурный паттерн автоматизации, при котором аналитические рекомендации (например, VPA Recommender или Right-Sizing инструменты) фиксируются в виде коммита или Pull Request в Git-репозиторий через CI-пайплайн, сохраняя непрерывность аудита и исключая мутации в обход Git.

---

## Архитектура и принципы работы

### Фундаментальный конфликт: Декларативный Git vs Динамический Runtime

В классическом GitOps манифест в Git является абсолютным авторитетом. Однако контроллеры автомасштабирования работают по реактивному принципу, меняя конфигурацию прямо в etcd:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 КОНФЛИКТ ВЛАДЕНИЯ ПОЛЕМ                                 │
│                                                                                        │
│   Git Repository (SSoT)                 Kubernetes API (etcd live state)               │
│   ┌───────────────────────┐             ┌──────────────────────────────────────────┐   │
│   │ Deployment:           │             │ Deployment:                              │   │
│   │   spec:               │             │   spec:                                  │   │
│   │     replicas: 2 ──────┼─────────┐   │     replicas: 10 ◄──────────┐            │   │
│   └───────────────────────┘         │   └───────────────────────────┼──────────────┘   │
│                                     ▼                               │                  │
│                          ┌────────────────────┐          ┌──────────────────────┐      │
│                          │  GitOps Controller │          │ Workload Autoscaler  │      │
│                          │  (Argo CD / Flux)  │          │ (HPA / KEDA / VPA)   │      │
│                          └────────────────────┘          └──────────────────────┘      │
│                                     │                               ▲                  │
│                                     │ Сброс реплик до 2 (SelfHeal) │ Рост нагрузки:    │
│                                     └──────────────────────────────┘ ScaleUp до 10     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Если взаимодействие не настроено:
1. При росте нагрузки HPA через подресурс `/scale` выставляет `spec.replicas: 10`.
2. GitOps-контроллер обнаруживает расхождение с Git (`replicas: 2`).
3. Механизм `selfHeal` (или очередная итерация сверки Flux) применяет патч, возвращая `spec.replicas: 2`.
4. Сервис испытывает деградацию (OOM, HTTP 502/504), HPA снова масштабирует поды вверх, порождая бесконечную нагрузку на API-сервер и флаппинг подов.

### Механизм владения полями (Server-Side Apply и managedFields)

Современные версии Argo CD (v2.10+) и Flux v2 используют Server-Side Apply. Kubernetes API сохраняет информацию о том, кто модифицировал каждое поле, в секции `metadata.managedFields`:

```yaml
metadata:
  managedFields:
    - manager: argocd-application-controller
      operation: Apply
      fieldsV1:
        f:spec:
          f:template:
            f:spec:
              f:containers: ...
    - manager: kube-controller-manager
      operation: Update
      subresource: scale
      fieldsV1:
        f:spec:
          f:replicas: {}
```

Когда контроллер GitOps использует SSA и в исходном манифесте Git **отсутствует** поле `spec.replicas`, GitOps-менеджер не заявляет права на владение этим полем. В результате `kube-controller-manager` (для HPA) или `keda-operator` становятся единственными владельцами поля, и конфликт исключается на уровне API-сервера.

### Стратегии разрешения конфликтов

| Стратегия | Реализация | Преимущества | Недостатки |
|:---|:---|:---|:---|
| **Omit Replicas (Рекомендуемая)** | Удаление поля `spec.replicas` из манифеста Deployment в Git | Нативная работа с SSA; отсутствие необходимости в сложных ignore-правилах; нулевой риск оверрайда | При первом деплое Deployment создается с 1 репликой по умолчанию (дефолт k8s) до реакции HPA |
| **Ignore Differences** | Явное указание игнорирования `/spec/replicas` в Argo CD / Flux | В Git можно зафиксировать базовое/минимальное количество реплик; прозрачно для legacy-манифестов | Требует обязательного включения `RespectIgnoreDifferences=true`; возможны ошибки при опечатках в jsonPointer |
| **Managed Fields Exclusion** | Игнорирование по менеджеру `kube-controller-manager` | Игнорируются любые мутации, выполненные системным HPA-контроллером, без привязки к путям | Не защищает от конфликтов, если поле мутируется нестандартным оператором или вебхуком |

---

## Практические сценарии и конфигурация

### Сценарий 1: Horizontal Pod Autoscaler (HPA) и Argo CD

#### Вариант А: Исключение поля replicas из Git (наиболее надежный подход)

В репозитории Git манифест Deployment не содержит строки `replicas:`:

```yaml
# apps/backend/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  namespace: production
spec:
  # Поле replicas НАМЕРЕННО отсутствует.
  selector:
    matchLabels:
      app: billing-service
  template:
    metadata:
      labels:
        app: billing-service
    spec:
      containers:
        - name: app
          image: internal-registry.corp/apps/billing:v2.14.0
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 2000m
              memory: 2Gi
---
# apps/backend/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: billing-service-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-service
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
```

#### Вариант Б: Конфигурация Application с ignoreDifferences и RespectIgnoreDifferences

Если поле `replicas` необходимо сохранить в Git (например, для отображения дефолта при первичном развертывании):

```yaml
# gitops/applications/billing-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-service
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@git.internal.corp:k8s/apps-inventory.git
    targetRevision: main
    path: apps/billing
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - RespectIgnoreDifferences=true  # КРИТИЧНО: не затирать игнорируемые поля при apply
      - ServerSideApply=true           # Использовать SSA для разделения managedFields
  ignoreDifferences:
    # 1. Игнорирование по пути JSON Pointer
    - group: apps
      kind: Deployment
      name: billing-service
      jsonPointers:
        - /spec/replicas
    # 2. Игнорирование по менеджеру полей HPA
    - group: apps
      kind: Deployment
      managedFieldsManagers:
        - kube-controller-manager
```

#### Вариант В: Глобальная настройка в ConfigMap argocd-cm

Чтобы не описывать исключения для каждого микросервиса индивидуально, системный администратор настраивает правила на уровне контроллера Argo CD:

```yaml
# platform/argocd/argocd-cm-patch.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Глобальное игнорирование реплик для всех Deployment, управляемых HPA
  resource.customizations.ignoreDifferences.apps_Deployment: |
    managedFieldsManagers:
      - kube-controller-manager
    jsonPointers:
      - /spec/replicas
  # Игнорирование для StatefulSet (если используется кастомный скейлер)
  resource.customizations.ignoreDifferences.apps_StatefulSet: |
    managedFieldsManagers:
      - kube-controller-manager
    jsonPointers:
      - /spec/replicas
```

---

### Сценарий 2: Horizontal Pod Autoscaler (HPA) и Flux v2

Flux v2 (контроллер `kustomize-controller`) применяет манифесты через Server-Side Apply по умолчанию.

#### Вариант А: Исключение replicas в Kustomize

В файлах `base/deployment.yaml` строка `replicas:` удаляется, а в `kustomization.yaml` не добавляются патчи с количеством реплик:

```yaml
# fleet/apps/order-api/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-api
spec:
  selector:
    matchLabels:
      app: order-api
  template:
    metadata:
      labels:
        app: order-api
    spec:
      containers:
        - name: api
          image: internal-registry.corp/apps/order-api:v1.8.2
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
```

#### Вариант Б: Настройка ignore-правил в Kustomization CRD

При включенной строгой проверке дрейфа (`spec.driftDetection.mode: enabled`):

```yaml
# fleet/clusters/prod-dc1/order-api-kustomization.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: order-api
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/order-api/overlays/production
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  # Тонкий контроль дрейфа SSA
  ignore:
    - paths:
        - /spec/replicas
```

#### Вариант В: HelmRelease в Flux v2

При развертывании через `helm-controller` стандартные чарты включают встроенный HPA:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: payment-gateway
  namespace: production
spec:
  interval: 15m
  chart:
    spec:
      chart: generic-service
      version: "3.5.x"
      sourceRef:
        kind: HelmRepository
        name: internal-charts
        namespace: flux-system
  values:
    # При включении HPA чарт автоматически не рендерит поле replicaCount в Deployment
    replicaCount: null
    autoscaling:
      enabled: true
      minReplicas: 4
      maxReplicas: 25
      targetCPUUtilizationPercentage: 75
```

---

### Сценарий 3: KEDA (Event-Driven Autoscaling) в GitOps

KEDA управляет ресурсами через собственный CRD `ScaledObject`. KEDA генерирует системный HPA под капотом и управляет подресурсом `/scale`.

#### Конфигурация ScaledObject и Deployment с защитой от гонок

```yaml
# apps/event-worker/worker.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kafka-consumer
  namespace: processing
  annotations:
    argocd.argoproj.io/sync-wave: "0" # Создается первым
spec:
  selector:
    matchLabels:
      app: kafka-consumer
  template:
    metadata:
      labels:
        app: kafka-consumer
    spec:
      containers:
        - name: consumer
          image: internal-registry.corp/workers/kafka-consumer:v4.1.0
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
---
# apps/event-worker/scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
  namespace: processing
  annotations:
    argocd.argoproj.io/sync-wave: "1" # Создается после Deployment
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: kafka-consumer
  pollingInterval: 15
  cooldownPeriod: 300
  minReplicaCount: 0  # Масштабирование в ноль при пустой очереди
  maxReplicaCount: 40
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-cluster-kafka-bootstrap.kafka.svc:9092
        consumerGroup: payment-processors
        topic: transaction-events
        lagThreshold: "50"
```

#### Исключение менеджеров полей KEDA в Argo CD

Поскольку KEDA при масштабировании в ноль и из нуля мутирует Deployment напрямую или через создаваемый HPA, необходимо расширить `ignoreDifferences`:

```yaml
# Дополнение в Application
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: kafka-consumer
      jsonPointers:
        - /spec/replicas
      managedFieldsManagers:
        - kube-controller-manager
        - keda-operator
        - keda-adapter
```

---

### Сценарий 4: Vertical Pod Autoscaler (VPA) в GitOps

Существует два архитектурных паттерна работы VPA в GitOps-средах:

#### Паттерн 1: Автономный VPA (In-Place Resize / Auto) с игнорированием ресурсов

Рекомендуется для изолированных сервисов, где допустима динамическая мутация ресурсов контейнеров.

```yaml
# apps/analytics/vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: analytics-worker-vpa
  namespace: processing
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: analytics-worker
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
      - containerName: "worker"
        minAllowed:
          cpu: 200m
          memory: 512Mi
        maxAllowed:
          cpu: 4000m
          memory: 8Gi
        controlledResources: ["cpu", "memory"]
```

Конфигурация Argo CD для игнорирования мутаций ресурсов в спецификации контейнеров:

```yaml
# В Application манифесте
spec:
  syncPolicy:
    syncOptions:
      - RespectIgnoreDifferences=true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: analytics-worker
      jqPathExpressions:
        - .spec.template.spec.containers[].resources.requests
        - .spec.template.spec.containers[].resources.limits
```

#### Паттерн 2: Recommender-Only + Git Write-Back (SRE Best Practice)

Для критических продакшен-систем мутация ресурсов в кластере в обход Git считается антипаттерном. VPA запускается в режиме `Off`, а CI/CD автоматизация транслирует рекомендации в Pull Request в Git:

```yaml
# apps/core-api/vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: core-api-vpa
  namespace: core
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: core-api
  updatePolicy:
    updateMode: "Off" # Исключительно аналитика и рекомендации
```

**Схема Git Write-Back пайплайна:**
1. VPA Recommender собирает метрики и формирует `.status.recommendation.containerRecommendations`.
2. CI-пайплайн (например, запускаемый раз в неделю по расписанию):
   - Считывает значение `target` из VPA.
   - Сравнивает с текущими значениями в Git-репозитории.
   - Если разница превышает порог (например, 20%), утилита (например, Kustomize/yq) обновляет значения `requests` в ветке и открывает Pull Request.
3. SRE-инженер или лид команды аппрувит PR, и Argo CD/Flux штатно применяет изменения без дрейфа.

---

### Сценарий 5: On-Premise Cluster Autoscaler и Cluster API (CAPI) через GitOps

В инфраструктуре на базе bare-metal (Metal3) или виртуализации (vSphere), управляемой через Cluster API (CAPI), рабочие узлы описываются ресурсом `MachineDeployment`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CAPI GITOPS АВТОМАСШТАБИРОВАНИЕ                  │
│                                                                        │
│   GitOps Repo                 Management Cluster                       │
│   ┌────────────────────┐      ┌───────────────────────────────────┐    │
│   │ MachineDeployment: │      │ MachineDeployment:                │    │
│   │   template: ...    │      │   spec.replicas: 12 ◄───────┐     │    │
│   │   (no replicas) ───┼─────►│   spec.template: ...        │     │    │
│   └────────────────────┘      └─────────────────────────────┼─────┘    │
│                                                             │          │
│                                                ┌────────────┴────────┐ │
│                                                │ Cluster Autoscaler  │ │
│                                                │ (CAPI expander)     │ │
│                                                └─────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

#### Манифест MachineDeployment для GitOps

```yaml
# infrastructure/clusters/mgmt/worker-pool.yaml
apiVersion: cluster.x-k8s.io/v1beta1
kind: MachineDeployment
metadata:
  name: prod-workers-dc1
  namespace: clusters
spec:
  clusterName: prod-dc1
  # replicas НЕ указывается либо управляется с ignoreDifferences
  selector:
    matchLabels:
      cluster.x-k8s.io/cluster-name: prod-dc1
  template:
    spec:
      clusterName: prod-dc1
      bootstrap:
        configRef:
          apiVersion: bootstrap.cluster.x-k8s.io/v1beta1
          kind: KubeadmConfigTemplate
          name: prod-workers-dc1-boot
      infrastructureRef:
        apiVersion: infrastructure.cluster.x-k8s.io/v1beta1
        kind: Metal3MachineTemplate
        name: prod-workers-dc1-hardware
```

#### Игнорирование реплик MachineDeployment в Argo CD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prod-cluster-nodes
  namespace: argocd
spec:
  syncPolicy:
    automated:
      prune: false
      selfHeal: true
    syncOptions:
      - RespectIgnoreDifferences=true
  ignoreDifferences:
    - group: cluster.x-k8s.io
      kind: MachineDeployment
      jsonPointers:
        - /spec/replicas
```

---

## Операции и команды

### 1. Проверка менеджеров полей (managedFields)

Диагностика фактического владельца поля `spec.replicas` в работающем Deployment:

```bash
kubectl get deployment billing-service -n production -o jsonpath='{range .metadata.managedFields[*]}{.manager}{"\t"}{.operation}{"\t"}{.fieldsV1.f:spec.f:replicas}{"\n"}{end}'
```
```
# → kube-controller-manager	Update	{}
# → argocd-application-controller	Apply	
```
*(Поле принадлежит `kube-controller-manager`, Argo CD им не владеет — конфигурация корректна).*

### 2. Проверка дрейфа и различий в Argo CD

Просмотр различий между Git и кластером с учетом SSA:

```bash
argocd app diff billing-service --server-side-diff
```
```
# → ===== apps/Deployment production/billing-service ======
# → (нет вывода, либо различия в /spec/replicas скрыты благодаря ignoreDifferences)
```

Синхронизация приложения с принудительным соблюдением правил игнорирования:

```bash
argocd app sync billing-service --respect-ignore-differences
```
```
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-12T22:15:00+03:00   apps  Deployment  production       billing-service    Synced  Healthy              deployment.apps/billing-service unchanged
```

### 3. Проверка дрейфа и реконсиляция во Flux v2

Проверка планируемых изменений без их применения:

```bash
flux diff kustomization order-api --path ./apps/order-api/overlays/production
```
```
# → ► inspecting diff for Kustomization order-api
# → ✔ no changes detected
```

Принудительная реконсиляция Kustomization из источника:

```bash
flux reconcile kustomization order-api --with-source
```
```
# → ► fetching at main:rev 8f4e2b1
# → ✔ reconciliation finished in 1.42s, next run in 5m0s
# → ✔ Applied revision: main@sha1:8f4e2b1
```

### 4. Инспекция статуса HPA и KEDA

Проверка состояния HPA и привязки к рабочей нагрузке:

```bash
kubectl get hpa -n production
```
```
# → NAME                  REFERENCE                    TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → billing-service-hpa   Deployment/billing-service   cpu: 64%/70%    3         30        8          42d
```

Проверка состояния ScaledObject в KEDA:

```bash
kubectl get scaledobject -n processing
```
```
# → NAME                    SCALETARGETKIND   SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION   READY   ACTIVE   FALLBACK   AGE
# → kafka-consumer-scaler   Deployment        kafka-consumer    0     40    kafka                       True    True     False      18d
```

---

## Диагностика и устранение неисправностей

### Матрица типовых инцидентов

| Проблема / Симптом | Первопричина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| **Сброс масштабирования при пике нагрузки** (HPA поднял 20 реплик, Argo CD через 2 мин сбросил до 2; всплеск 502/OOM) | Включен `selfHeal`, в манифесте Git зафиксировано `replicas: 2`, отсутствует `RespectIgnoreDifferences=true` | `kubectl get events -n <ns> --field-selector reason=ScalingReplicaSet`<br>`argocd app get <app>` | 1. Удалить `replicas` из Git-манифеста.<br>2. Добавить `RespectIgnoreDifferences=true` в `syncOptions`. |
| **Flapping реплик во Flux v2** (каждые `interval` поды скейлятся вниз и снова вверх) | В манифесте Kustomize жестко прописано `spec.replicas`, что заставляет SSA перехватывать владение | `flux logs --level=debug --kind=Kustomization`<br>Проверка `kubectl get deploy -o yaml \| grep -A 10 managedFields` | Удалить строку `replicas:` из исходного манифеста в Git; настроить `ignore` в `Kustomization`. |
| **Петля KEDA при minReplicaCount: 0** (KEDA гасит поды до 0, GitOps создает 1 под) | GitOps-контроллер считает отсутствие реплик за дрейф относительно дефолтного значения 1 | `kubectl describe scaledobject <name>`<br>`argocd app diff <app>` | Настроить `ignoreDifferences` для менеджера `keda-operator` и пути `/spec/replicas`. |
| **Вечный OutOfSync при включенном VPA** (приложение всегда в статусе OutOfSync) | VPA мутирует поля `requests`/`limits`, которые сверяются с исходными манифестами Git | `argocd app diff <app>` показывает расхождение в секции `resources` контейнеров | Использовать VPA в режиме `Off` (с Git Write-Back) либо настроить `jqPathExpressions` в `ignoreDifferences`. |
| **Cluster Autoscaler удаляет узлы On-Premise** (CA расширяет пул CAPI, GitOps уменьшает) | GitOps управляет `MachineDeployment` со статическим полем `spec.replicas` | `kubectl logs -n kube-system -l app=cluster-autoscaler`<br>`kubectl describe machinedeployment` | Добавить игнорирование `spec.replicas` для CRD `MachineDeployment`. |
| **Дедлок PDB при совместном rollout и scale-down** (поды зависают в Terminating) | HPA уменьшает нагрузку, одновременно GitOps выкатывает новый образ при `maxUnavailable: 0` | `kubectl get pdb -n <ns>`<br>`kubectl describe pdb <name>` (Allowed disruptions: 0) | Скорректировать PDB (`maxUnavailable: 25%` или `minAvailable` с запасом относительно `minReplicas`). |

---

### Детальный разбор: Сброс масштабирования в Argo CD под нагрузкой

**Контекст:** Нагрузочное тестирование или внезапный всплеск пользовательского трафика в рабочие часы. HPA успешно считывает загрузку CPU 85% и выполняет масштабирование с 3 до 18 подов. Спустя 2 минуты количество подов резко падает до 3, вызывая шквал ошибок `HTTP 502 Bad Gateway` и перезапуски из-за перегрузки CPU.

**Пошаговая диагностика:**

1. Изучите историю событий Deployment:
   ```bash
   kubectl get events -n production --sort-by='.metadata.creationTimestamp' | grep -E "(Scaled|Deployment)"
   ```
   ```
   # → 22:04:12 Normal  SuccessfulRescale  hpa/billing-service-hpa         New size: 18; reason: cpu resource utilization above target
   # → 22:06:15 Normal  ScalingReplicaSet  deployment/billing-service      Scaled down replica set billing-service-78f9c5d to 3 from 18
   ```
2. Проверьте события аудита контроллера Argo CD:
   ```bash
   kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=200 | grep "billing-service"
   ```
   ```
   # → time="2026-10-12T22:06:15Z" level=info msg="Applying resource apps/Deployment:production/billing-service with 3 replicas due to SelfHeal"
   ```
3. Проверьте настройки объекта `Application`:
   ```bash
   kubectl get application billing-service -n argocd -o jsonpath='{.spec.syncPolicy.syncOptions}'
   ```
   ```
   # → ["CreateNamespace=true","ServerSideApply=true"]
   ```
   *(Флаг `RespectIgnoreDifferences=true` отсутствует! Без него `ignoreDifferences` защищает только статус в интерфейсе, но при вызове `selfHeal` манифест Git накатывается поверх live-состояния).*

**Решение:**
1. Примените патч к объекту `Application`:
   ```bash
   kubectl patch application billing-service -n argocd --type=merge -p '{
     "spec": {
       "syncPolicy": {
         "syncOptions": [
           "ServerSideApply=true",
           "RespectIgnoreDifferences=true"
         ]
       }
     }
   }'
   ```
2. Удалите строку `replicas:` из файла `deployment.yaml` в Git-репозитории и выполните коммит.

---

## Лучшие практики

1. **Принцип разделения ответственности:** Git хранит **структуру и топологию** рабочей нагрузки (образы, переменные, правила монтирования, лимиты безопасности), а динамические контроллеры (HPA, KEDA, VPA, CA) управляют **масштабом и объемом ресурсов**.
2. **Всегда удаляйте `spec.replicas` из Git при наличии HPA/KEDA:** Это исключает необходимость в сложных костылях, предотвращает гонки между контроллерами и гарантирует чистоту Server-Side Apply.
3. **Обязательное использование `RespectIgnoreDifferences=true`:** Если правила `ignoreDifferences` используются в Argo CD, этот флаг должен присутствовать во всех манифестах `Application` или быть включенным глобально через `argocd-cm`.
4. **Синхронизация через Sync Waves:** При использовании KEDA всегда выставляйте `sync-wave` для `ScaledObject` выше, чем для целевого `Deployment`, чтобы избежать ошибок валидации контроллера при первом развертывании.
5. **Согласование HPA и PodDisruptionBudget:** Значение `minReplicas` в HPA должно быть строго больше, чем допустимый лимит вытеснения в PDB. Если `minReplicas: 1`, а PDB требует `minAvailable: 1`, Cluster Autoscaler или node drain никогда не смогут безопасно выселить этот под.
6. **Запрет на прямое мутирование кластера по расписанию:** Не используйте `CronJob` с `kubectl patch` внутри кластера для тюнинга ресурсов. Все автоматизированные корректировки на основе рекомендаций (VPA, Right-Sizing) должны идти через Git (Git Write-Back via Pull Requests).
7. **Алертинг на дрейф реплик и частоту синхронизаций:** Настройте Prometheus-алерты на метрики Argo CD и Flux для выявления скрытых петель:
   - `rate(argocd_app_sync_total{phase="Failed"}[5m]) > 0`
   - `rate(flux_kustomize_controller_reconcile_condition{type="Ready",status="False"}[5m]) > 0`
   - Аномально высокая частота `changes` для одного Deployment в kube-state-metrics (`rate(kube_deployment_status_replicas_updated[5m])`).

---

## Дополнительная информация

### См. также

- [Основы HPA](./HPA/index.md) — базовые принципы и настройка метрик Horizontal Pod Autoscaler
- [Продвинутые сценарии HPA](./HPA/hpa_advanced.md) — масштабирование по кастомным метрикам и тонкая настройка behavior
- [VPA: Глубокое погружение](./vpa_detailed.md) — режимы Recommender, Updater, Admission Controller и In-Place Pod Resize
- [KEDA: Концепции и архитектура](./keda/keda_concepts.md) — архитектура событийно-ориентированного масштабирования
- [KEDA: Практические сценарии](./keda/practical_scenarios.md) — настройка скейлеров Kafka, Redis и Prometheus
- [Pod Disruption Budget](./pod_disruption_budget.md) — защита доступности рабочих нагрузок при автомасштабировании
- [On-Premise Autoscaling](./on_premise_autoscaling.md) — особенности масштабирования узлов и подов в частных дата-центрах
- [Cluster Autoscaler](./cluster_autoscaler_detailed.md) — детальная архитектура контроллера масштабирования узлов
- [Argo CD: ignoreDifferences](../../GitOps/ArgoCD/synchronization/ignore_differences.md) — полный справочник по настройке игнорирования различий
- [Flux v2](../../GitOps/flux.md) — архитектура и тонкая настройка контроллеров Flux
- [Сравнение манифестов Argo CD и Flux](../../GitOps/argo_vs_flux_manifests.md) — сопоставление подходов к декларативному управлению

