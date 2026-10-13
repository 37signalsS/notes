# Вертикальное авто-масштабирование подов (Vertical Pod Autoscaler — VPA)

**Актуально для:** Kubernetes 1.33+ (Beta In-Place Resize) / 1.35+ (GA) / Vertical Pod Autoscaler 1.2+ / 1.3+ (autoscaling.k8s.io/v1)

---

## Определения

* **Vertical Pod Autoscaler (VPA)** — контроллер Kubernetes (`autoscaling.k8s.io/v1`), выполняющий автоматический подбор и корректировку вычислительных ресурсов (`requests` и `limits` CPU и оперативной памяти) контейнеров на основе непрерывного анализа истории их фактического потребления. В отличие от HPA, изменяющего количество реплик, VPA оптимизирует размер единичного пода.
* **In-Place Pod Resize (KEP-1287)** — встроенный механизм ядра Kubernetes, позволяющий модифицировать `requests` и `limits` работающего контейнера на лету через обновление контроллеров `cgroups v2` без пересоздания пода и без перезапуска процесса PID 1.
* **VPA Recommender** — компонент VPA, опрашивающий источник метрик (Metrics Server или Prometheus), агрегирующий временные ряды в логарифмические гистограммы с экспоненциальным затуханием весов и рассчитывающий оптимальные границы ресурсов.
* **VPA Updater** — фоновый контроллер, отслеживающий соответствие фактических ресурсов запущенных подов вычисленным рекомендациям. При выходе за границы допустимого диапазона инициирует обновление через подресурс `/resize` (In-Place) или через Eviction API с учетом Pod Disruption Budget (PDB).
* **VPA Admission Controller** — мутирующий вебхук (`MutatingWebhookConfiguration`), перехватывающий запросы создания подов (`CREATE`) и подставляющий актуальные рекомендованные значения ресурсов в манифест до планирования пода на узел.
* **VerticalPodAutoscalerCheckpoint** — вспомогательный CRD (`autoscaling.k8s.io/v1`), в котором Recommender периодически сохраняет агрегированные гистограммы потребления подов в etcd, предотвращая потерю накопленной аналитики при перезапуске контроллера.
* **Target** — целевое рекомендованное значение ресурса, рассчитанное Recommender (95-й перцентиль для CPU, 99-й перцентиль для RAM плюс буфер безопасности).
* **LowerBound / UpperBound** — нижняя и верхняя границы допустимого диапазона ресурсов. Если текущие `requests` пода находятся между `lowerBound` и `upperBound`, Updater считает конфигурацию корректной и не предпринимает действий.
* **uncappedTarget** — расчетное целевое значение ресурсов без наложения ограничений `minAllowed`/`maxAllowed`. Позволяет SRE выявлять скрытый дефицит ресурсов, искусственно сдерживаемый политикой.
* **controlledValues** — директива политики масштабирования, определяющая целевые поля контейнера: `RequestsAndLimits` (пропорциональное масштабирование обоих параметров) или `RequestsOnly` (изменение только запросов с сохранением фиксированных лимитов).
* **OOM Bump** — алгоритмическая реакция Recommender на событие аварийного завершения контейнера по нехватке памяти (`OOMKilled`), мгновенно повышающая рекомендацию памяти с мультипликатором без ожидания накопления статистики.
* **Decay Half-Life** — период полураспада весов измерений в гистограмме Recommender (по умолчанию 24 часа), определяющий скорость устаревания исторических данных в пользу недавних всплесков нагрузки.

---

## Архитектура и принцип работы

### Компоненты системы

Пакет VPA состоит из трех слабосвязанных независимых микросервисов, развертываемых внутри кластера (как правило, в пространстве имен `kube-system`):

| Компонент | Роль в кластере | Порт метрик / Health | Основные флаги запуска |
| :--- | :--- | :--- | :--- |
| **`vpa-recommender`** | Опрос метрик, расчет перцентилей, генерация рекомендаций, запись чекпоинтов в etcd. | `:8942` (`/metrics`, `/healthz`) | `--recommender-interval=1m`<br>`--metric-storage=metrics-server`<br>`--cpu-histogram-decay-half-life=24h`<br>`--storage=checkpoint` |
| **`vpa-updater`** | Мониторинг отклонений ресурсов подов, вызов In-Place Resize или эвикция с учетом PDB. | `:8943` (`/metrics`, `/healthz`) | `--updater-interval=1m`<br>`--min-replicas=2`<br>`--eviction-tolerance=0.5`<br>`--eviction-rate-limit=-1` |
| **`vpa-admission-controller`** | Мутирующий вебхук перехвата `Pod/CREATE`, подстановка `requests`/`limits`. | `:8944` (`/metrics`, `/healthz`) | `--webhook-port=8000`<br>`--tls-cert-file=/etc/tls-certs/tls.crt`<br>`--register-webhook=true` |

### Сквозной поток данных (Data Flow)

```
[Ядро Linux / cgroups v2]
         │
         ▼ (Чтение cAdvisor внутри Kubelet: 10250)
[Metrics Server] (или долгосрочный Prometheus)
         │
         ▼ (HTTP polling каждые 60с)
┌─────────────────────────────────────────────────────────────┐
│                      vpa-recommender                        │
│ 1. Сбор временных рядов CPU/RAM                             │
│ 2. Экспоненциальное затухание весов (half-life = 24h)       │
│ 3. Расчет: 95% CPU, 99% RAM + 15% буфер                     │
│ 4. Запись чекпоинтов (CRD VerticalPodAutoscalerCheckpoint)  │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
     (Обновление CRD)                      (Обновление CRD)
   .status.recommendation                .status.recommendation
            │                                     │
            ▼                                     ▼
┌───────────────────────────────┐   ┌────────────────────────────────┐
│          vpa-updater          │   │    vpa-admission-controller    │
│ 1. Периодический цикл (1m)    │   │ 1. Перехват события Pod CREATE │
│ 2. Сверка ресурсов пода       │   │ 2. Проверка селектора VPA      │
│ 3. Если вне [Lower, Upper]:   │   │ 3. Мутация requests/limits     │
│    - K8s 1.33+: PATCH /resize │   └───────────────┬────────────────┘
│    - Fallback: Eviction (PDB) │                   │
└───────────────┬───────────────┘                   │
                │                                   │
                ▼                                   ▼
        [API-Server /resize]              [Kubelet Pod Schedule]
                │                                   │
                ▼                                   ▼
       [Kubelet Node Cgroup]               [Запуск контейнера]
```

### Механизм чекпоинтов (VerticalPodAutoscalerCheckpoint)

Для исключения проблемы «холодного старта» при перезапуске `vpa-recommender` данные не теряются. Recommender формирует объекты `VerticalPodAutoscalerCheckpoint` для каждого контейнера в пространстве имен целевого сервиса:

```bash
# Просмотр созданных чекпоинтов VPA
kubectl get verticalpodautoscalercheckpoints -n default
# → NAME                      AGE
# → api-vpa-app               3d
```

Структура чекпоинта содержит состояние гистограмм, временные границы и суммарное количество обработанных сэмплов:

```bash
kubectl get verticalpodautoscalercheckpoint api-vpa-app -n default -o yaml
```
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscalerCheckpoint
metadata:
  name: api-vpa-app
  namespace: default
spec:
  containerName: app
  vpaObjectName: api-vpa
status:
  firstSampleStart: "2026-03-01T08:00:00Z"
  lastSampleStart: "2026-03-04T12:00:00Z"
  totalSamplesCount: 4320
  version: "v1"
```

### Математический алгоритм и формулы расчета

1. **Гистограммы с логарифмическими корзинами (Buckets):**
   * Recommender разбивает диапазон потребления на логарифмически возрастающие интервалы.
   * Для CPU базовый шаг составляет `10m` с коэффициентом роста `1.05`.
   * Для памяти шаг составляет `10Mi` с мультипликатором роста `1.05`.
2. **Экспоненциальное сглаживание (Exponential Weight Decay):**
   * Вес измерения $w(t)$ затухает со временем по закону:
     $$w(t) = w_0 \cdot 2^{-\frac{\Delta t}{T_{decay}}}$$
     где $T_{decay}$ задается флагом `--cpu-histogram-decay-half-life` (по умолчанию 24 часа). Сэмпл, полученный сутки назад, имеет вдвое меньший вес, чем текущий.
3. **Расчет перцентилей и запаса безопасности:**
   * **CPU:** вычисляется 95-й перцентиль взвешенного распределения и умножается на буфер безопасности $1.15$ (коэффициент запаса 15%).
   * **RAM:** вычисляется 99-й перцентиль пиковых значений (Working Set Size) за скользящее окно (по умолчанию 8 дней) плюс запас безопасности $1.15$.
4. **Реакция на OOMKilled:**
   * При получении события ядра `OOMKilled` Recommender не ожидает накопления истории.
   * Новая рекомендация рассчитывается мгновенно:
     $$\text{Target}_{\text{RAM}} = \max(\text{RAM}_{\text{observed}}, \text{Limit}_{\text{RAM}}) \times 1.20$$
     Минимальный прирост составляет не менее `400Mi` для быстрого вывода сервиса из аварийного состояния.

### Смысл расчетных полей статуса

```
[0] ────────── [lowerBound] ────────── [target] ────────── [upperBound] ────────── [maxAllowed]
      Зона              Зона стабильной            Зона
   недогруза               работы               перегруза
 (Downscale)            (Бездействует)          (Upscale)
```

* **`lowerBound`**: порог, ниже которого под считается критически переразмеренным (Overprovisioned). Если текущий `request` пода выше `upperBound` или ниже `lowerBound`, Updater инициирует изменение.
* **`target`**: расчетный оптимум ресурсов, передаваемый в `spec.containers[].resources`.
* **`upperBound`**: порог, превышение которого свидетельствует о нехватке ресурсов (Underprovisioned).
* **`uncappedTarget`**: целевое значение без учета ограничений `minAllowed`/`maxAllowed`. Если `uncappedTarget > maxAllowed`, сервис уперся в искусственную границу, заданную инженером, и требует пересмотра квот.

### Режимы работы (`updateMode`)

| Режим | Поведение контроллера | Риск простоя | Сценарий применения |
| :--- | :--- | :--- | :--- |
| **`Off`** | Только расчет и публикация рекомендаций в CRD. Модификация подов не выполняется. | Нулевой | Аудит ресурсов, capacity planning, Git Write-Back, критические базы данных. |
| **`Initial`** | Мутация `requests`/`limits` через вебхук только в момент создания нового пода. Работающие поды не перезапускаются. | Нулевой для live | Постепенное внедрение, приложения с длительным прогревом кэшей. |
| **`Recreate`** | Принудительное выселение пода через Eviction API для применения новых ресурсов при старте. | Умеренный (зависит от PDB) | Кластеры без поддержки In-Place Resize, пакетные задачи. |
| **`InPlaceOrRecreate`** | **Основной стандарт Kubernetes 1.33+/1.35+**. Приоритетная модификация cgroups на лету через `/resize`. Если ресурсов на узле нет — выселение по PDB. | Минимальный | Микросервисы, HTTP API, распределенные базы данных. |
| **`InPlace`** | Строго модификация cgroups без перезапуска. Если узел переполнен (`Infeasible`), обновление откладывается до появления емкости. | Нулевой | Stateful-приложения (PostgreSQL, Redis, ClickHouse), где эвикция недопустима. |

### Директивы управления ресурсами

* **`controlledValues`**:
  * `RequestsAndLimits`: VPA модифицирует и `requests`, и `limits`, сохраняя исходное соотношение (burstable ratio) между ними.
  * `RequestsOnly`: VPA управляет исключительно `requests`, оставляя `limits` фиксированными (или отсутствующими для устранения троттлинга CPU).
* **`controlledResources`**:
  * Массив `["cpu", "memory"]`. Позволяет ограничить воздействие VPA только одним ресурсом (например, поручить VPA только оперативную память, а CPU масштабировать горизонтально через HPA).

---

## Установка и практические сценарии

### Предварительные требования к инфраструктуре кластера

Для надежного функционирования VPA на Bare Metal и виртуализированных узлах (On-Premise) требуются следующие настройки хостов и рантаймов:

1. **Cgroups v2:** обязателен объединенный контроллер (`cgroup2fs`). Проверка на узле:
   ```bash
   stat -fc %T /sys/fs/cgroup/
   # → cgroup2fs
   ```
2. **Containerd:** в `/etc/containerd/config.toml` включен системный драйвер cgroups:
   ```toml
   [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
     SystemdCgroup = true
   ```
3. **Kubelet:** корректный расчет доступной емкости узла (`NodeAllocatable`):
   ```bash
   # Проверка резервов kubelet
   kubectl get node node1.corp.local -o jsonpath='{.status.allocatable.memory}'
   # → 65780120Ki
   ```
4. **Metrics Server:** сервис установлен и стабильно отдает метрики:
   ```bash
   kubectl top nodes
   # → NAME                CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
   # → node1.corp.local    420m         5%     8192Mi          12%
   ```

### Установка VPA в On-Premise кластере

#### Вариант А: Установка через манифесты и генерация TLS для Admission Controller

Admission Controller требует валидного TLS-сертификата, доверенного API-сервером Kubernetes.

```bash
# 1. Клонирование официального репозитория autoscaler
git clone https://github.com/kubernetes/autoscaler.git
cd autoscaler/vertical-pod-autoscaler

# 2. Запуск скрипта генерации сертификатов и регистрации вебхука
./hack/vpa-up.sh
# → customresourcedefinition.apiextensions.k8s.io/verticalpodautoscalers.autoscaling.k8s.io created
# → customresourcedefinition.apiextensions.k8s.io/verticalpodautoscalercheckpoints.autoscaling.k8s.io created
# → deployment.apps/vpa-recommender created
# → deployment.apps/vpa-updater created
# → deployment.apps/vpa-admission-controller created
# → mutatingwebhookconfiguration.admissionregistration.k8s.io/vpa-webhook-config created
```

#### Вариант Б: Интеграция с cert-manager для промышленного выпуска сертификатов

В production-средах рекомендуется делегировать выпуск и ротацию сертификата вебхука оператору `cert-manager`:

```yaml
# vpa-webhook-cert.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: vpa-webhook-tls
  namespace: kube-system
spec:
  secretName: vpa-webhook-tls-secret
  duration: 8760h # 1 год
  renewBefore: 720h # 30 дней
  issuerRef:
    name: cluster-internal-ca
    kind: ClusterIssuer
  commonName: vpa-webhook.kube-system.svc
  dnsNames:
    - vpa-webhook
    - vpa-webhook.kube-system
    - vpa-webhook.kube-system.svc
    - vpa-webhook.kube-system.svc.cluster.local
---
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: vpa-webhook-config
  annotations:
    cert-manager.io/inject-ca-from: kube-system/vpa-webhook-tls
webhooks:
  - name: vpa.k8s.io
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
    clientConfig:
      service:
        name: vpa-webhook
        namespace: kube-system
        port: 443
    admissionReviewVersions: ["v1"]
    sideEffects: None
    failurePolicy: Ignore # КРИТИЧНО: Ignore предотвращает блокировку создания подов при сбое вебхука
```

---

### Сценарий 1: Аудит и Right-sizing в режиме Off (Capacity Planning)

Базовый сценарий для профилирования продакшен-нагрузок перед выделением фиксированных ресурсов или настройкой квот.

```yaml
# vpa-audit.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: billing-api-vpa
  namespace: finance
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-api
  updatePolicy:
    updateMode: "Off"
  resourcePolicy:
    containerPolicies:
      - containerName: "billing-service"
        controlledValues: RequestsAndLimits
```

Применение манифеста и инспекция сформированных рекомендаций:

```bash
kubectl apply -f vpa-audit.yaml
# → verticalpodautoscaler.autoscaling.k8s.io/billing-api-vpa created

# Проверка статуса через 24 часа сбора метрик
kubectl get vpa billing-api-vpa -n finance -o yaml
```
```yaml
status:
  conditions:
  - lastTransitionTime: "2026-03-04T10:00:00Z"
    status: "True"
    type: RecommendationProvided
  recommendation:
    containerRecommendations:
    - containerName: billing-service
      lowerBound:
        cpu: 180m
        memory: 380Mi
      target:
        cpu: 350m
        memory: 512Mi
      uncappedTarget:
        cpu: 350m
        memory: 512Mi
      upperBound:
        cpu: 850m
        memory: 1200Mi
```

---

### Сценарий 2: Production StatefulSet (PostgreSQL) с In-Place Resize и PDB

Масштабирование оперативной памяти и ядер СУБД без разрыва соединений клиентов и перезапуска реплик.

```yaml
# postgres-vpa.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-pdb
  namespace: databases
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: postgres
---
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: postgres-vpa
  namespace: databases
spec:
  targetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: postgres
  updatePolicy:
    updateMode: "InPlace" # Строго без рестарта контейнеров
  resourcePolicy:
    containerPolicies:
      - containerName: "postgresql"
        minAllowed:
          cpu: "1"
          memory: 4Gi
        maxAllowed:
          cpu: "8"
          memory: 32Gi
        controlledValues: RequestsAndLimits
```

Проверка применения ресурсов на лету:

```bash
# Проверка текущих ресурсов контейнера в Pod
kubectl get pod postgres-0 -n databases -o jsonpath='{.status.containerStatuses[0].resources}'
# → {"limits":{"cpu":"4","memory":"16Gi"},"requests":{"cpu":"4","memory":"16Gi"}}
```

---

### Сценарий 3: Гибридное автоскейлирование — совместная работа VPA и HPA

Совместное использование HPA и VPA по одним и тем же метрикам (CPU/Memory) запрещено, так как приводит к конфликту регуляторов. Допустимая промышленная схема: HPA управляет количеством реплик по бизнес-метрике (RPS), а VPA управляет исключительно оперативной памятью контейнеров.

```yaml
# vpa-hpa-hybrid.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: edge-gateway-vpa
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: edge-gateway
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "gateway"
        controlledResources: ["memory"] # VPA управляет ТОЛЬКО памятью
        minAllowed:
          memory: 256Mi
        maxAllowed:
          memory: 2Gi
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: edge-gateway-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: edge-gateway
  minReplicas: 3
  maxReplicas: 25
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "350"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
```

---

### Сценарий 4: Тонкая настройка resourcePolicy для подов с сайдкарами

Изоляция служебных контейнеров (логирование, proxy) от изменений VPA.

```yaml
# sidecar-workload-vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: orders-service-vpa
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: orders-service
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        minAllowed:
          cpu: 200m
          memory: 512Mi
        maxAllowed:
          cpu: "4"
          memory: 8Gi
        controlledValues: RequestsAndLimits
      - containerName: "vector-agent"
        mode: "Off" # Сайдкар исключен из автоскейлинга
      - containerName: "envoy-proxy"
        mode: "Off" # Фиксированные ресурсы сети
```

---

### Сценарий 5: VPA с долгосрочным хранилищем метрик в Prometheus

Metrics Server хранит данные только в RAM за последние минуты. Для точного расчета недельных сезонных циклов Recommender переключается на чтение метрик из кластерного Prometheus.

Конфигурация Deployment `vpa-recommender`:

```yaml
# vpa-recommender-prometheus.yaml (фрагмент spec.template.spec)
containers:
  - name: recommender
    image: registry.k8s.io/autoscaling/vpa-recommender:1.3.0
    args:
      - --recommender-interval=1m
      - --metric-storage=prometheus
      - --prometheus-address=http://prometheus-k8s.monitoring.svc.cluster.local:9090
      - --prometheus-cadvisor-job-name=cadvisor
      - --history-length=14d # Анализ двухнедельного окна потребления
      - --cpu-histogram-decay-half-life=48h
      - --storage=checkpoint
```

Проверка подключения Recommender к Prometheus:

```bash
kubectl logs -n kube-system deployment/vpa-recommender | grep -i prometheus
# → I0304 10:15:20.123 recommender.go:88] Initializing Prometheus client with address: http://prometheus-k8s.monitoring.svc.cluster.local:9090
# → I0304 10:15:21.450 prometheus.go:142] Successfully fetched 1250 cAdvisor metric samples
```

---

### Сценарий 6: Оптимизация профилей сред выполнения (Java JVM, Go, Node.js)

При динамическом ресайзе памяти через VPA рантаймы приложений должны своевременно реагировать на изменение лимитов контейнера:

1. **Java (OpenJDK 17+/21+):**
   * Запрещено указывать жесткие флаги `-Xmx` / `-Xms`.
   * Использовать процентные ограничения от cgroup:
     ```bash
     JAVA_OPTS="-XX:MaxRAMPercentage=75.0 -XX:MinRAMPercentage=50.0 -XX:+UseG1GC"
     ```
2. **Go (Golang 1.19+):**
   * Задавать мягкий лимит кучи через переменную окружения `GOMEMLIMIT`:
     ```yaml
     env:
       - name: GOMEMLIMIT
         valueFrom:
           resourceFieldRef:
             resource: limits.memory
             divisor: "1Mi"
     ```
   * Либо в скрипте запуска резервировать 10% под стек и системные аллокации: `export GOMEMLIMIT=90%`.
3. **Node.js (V8):**
   * V8 не подхватывает изменение лимитов на лету без перезапуска. Для Node.js в `spec.containers[].resizePolicy` указывается:
     ```yaml
     resizePolicy:
       - resourceName: cpu
         restartPolicy: NotRequired
       - resourceName: memory
         restartPolicy: RestartContainer # Безопасный рестарт для пересчета heap size
     ```

---

### Сценарий 7: Интеграция с GitOps (ArgoCD / Flux) без конфликтов дрейфа

Когда VPA мутирует `requests`/`limits` в кластере, GitOps-контроллеры фиксируют расхождение с Git-репозиторием и откатывают изменения (State Churn).

#### Решение 1: ArgoCD ignoreDifferences с RespectIgnoreDifferences

```yaml
# application-argocd.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  namespace: argocd
spec:
  syncPolicy:
    syncOptions:
      - RespectIgnoreDifferences=true # КРИТИЧНО: не затирать live-значения при sync
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: payment-service
      jqPathExpressions:
        - .spec.template.spec.containers[].resources.requests
        - .spec.template.spec.containers[].resources.limits
```

#### Решение 2: Паттерн Git Write-Back (SRE Best Practice)

Для критических инфраструктур VPA эксплуатируется в режиме `updateMode: "Off"`. Специализированный CronJob или CI-скрипт еженедельно считывает `.status.recommendation.containerRecommendations.target` и создает Pull Request с обновленными ресурсами в Git-репозиторий проекта.

---

### Сценарий 8: Стратегия поэтапного внедрения (Rollout) VPA в кластере

```bash
# Этап 1: Создание объекта в режиме Off для сбора аналитики
kubectl apply -f - <<EOF
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: core-api-vpa
  namespace: default
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: core-api
  updatePolicy:
    updateMode: "Off"
EOF
# → verticalpodautoscaler.autoscaling.k8s.io/core-api-vpa created

# Этап 2: Анализ рекомендаций через 7 суток (недельный цикл)
kubectl describe vpa core-api-vpa -n default
# → Target: CPU: 420m, Memory: 1200Mi

# Этап 3: Переключение на Initial mode (проверка на вновь создаваемых подах)
kubectl patch vpa core-api-vpa -n default --type='merge' -p '{"spec":{"updatePolicy":{"updateMode":"Initial"}}}'
# → verticalpodautoscaler.autoscaling.k8s.io/core-api-vpa patched

# Этап 4: Активация промышленного режима InPlaceOrRecreate
kubectl patch vpa core-api-vpa -n default --type='merge' -p '{"spec":{"updatePolicy":{"updateMode":"InPlaceOrRecreate"}}}'
# → verticalpodautoscaler.autoscaling.k8s.io/core-api-vpa patched
```

---

## Операции и команды

### Администрирование и аудит VPA через kubectl

```bash
# Список всех объектов VPA во всех пространствах имен
kubectl get vpa -A
# → NAMESPACE    NAME               MODE                CPU    MEM      PROVIDED   AGE
# → default      core-api-vpa       InPlaceOrRecreate   420m   1200Mi   True       8d
# → finance      billing-api-vpa    Off                 350m   512Mi    True       2d

# Детальная инспекция статуса рекомендаций и условий
kubectl describe vpa core-api-vpa
# → Reference:          Deployment/core-api
# → Target:             CPU: 420m, Memory: 1200Mi
# → Lower Bound:        CPU: 200m, Memory: 600Mi
# → Upper Bound:        CPU: 1200m, Memory: 3200Mi
# → Uncapped Target:    CPU: 420m, Memory: 1200Mi

# Просмотр событий изменения ресурсов и эвикции
kubectl get events -n default --field-selector involvedObject.kind=VerticalPodAutoscaler
# → 5m   Normal   CalculationDone   verticalpodautoscaler/core-api-vpa   Recommendation generated successfully

# Инспекция реальных cgroup-лимитов на узле через kubelet pod status
kubectl get pod core-api-7b89f8d9b-w9z4x -o jsonpath='{.status.containerStatuses[0].allocatedResources}'
# → {"cpu":"420m","memory":"1200Mi"}

# Проверка Pod Conditions ресайза в Kubernetes 1.33+
kubectl get pod core-api-7b89f8d9b-w9z4x -o jsonpath='{.status.conditions[?(@.type=="PodResizePending")]}'
# → (пусто при завершенном ресайзе)
```

---

## Мониторинг и алертинг

### Встроенные метрики компонентов VPA

Каждый компонент VPA экспортирует метрики в формате Prometheus на выделенных портах:

| Компонент | Метрика Prometheus | Тип | Назначение |
| :--- | :--- | :--- | :--- |
| `recommender` | `vpa_recommender_recommendation_latency_seconds` | Histogram | Задержка цикла вычисления рекомендаций. |
| `recommender` | `vpa_recommender_aggregate_container_states_count` | Gauge | Количество агрегированных состояний контейнеров в памяти. |
| `updater` | `vpa_updater_evicted_pods_total` | Counter | Количество подов, выселенных апдейтером. |
| `updater` | `vpa_updater_eviction_attempts_total` | Counter | Общее количество попыток эвикции (включая заблокированные PDB). |
| `admission` | `vpa_admission_controller_admission_latency_seconds` | Histogram | Задержка мутирующего вебхука при создании подов. |
| `admission` | `vpa_admission_controller_mutated_pods_total` | Counter | Количество подов, модифицированных вебхуком. |

### Правила алертинга Prometheus / Alertmanager

```yaml
# vpa-alerting-rules.yaml
groups:
  - name: vpa_sre_alerts
    rules:
      - alert: VPARecommenderDown
        expr: up{job="vpa-recommender"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "VPA Recommender недоступен"
          description: "Экземпляр vpa-recommender на узле {{ $labels.instance }} не отвечает более 5 минут."

      - alert: VPAAdmissionWebhookHighLatency
        expr: histogram_quantile(0.99, rate(vpa_admission_controller_admission_latency_seconds_bucket[5m])) > 0.5
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка VPA Admission Webhook"
          description: "P99 задержки вебхука превышает 500мс, что замедляет запуск подов в кластере."

      - alert: VPAEvictionBlockedByPDB
        expr: rate(vpa_updater_eviction_attempts_total{result="eviction_blocked_by_pdb"}[10m]) > 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Эвикции VPA заблокированы политикой PDB"
          description: "Updater не может применить рекомендации для {{ $labels.target_ref }} из-за ограничений PodDisruptionBudget."

      - alert: VPAUncappedTargetExceedsMaxAllowed
        expr: kube_customresource_verticalpodautoscaler_status_recommendation_containerrecommendations_uncappedtarget{resource="memory"} > kube_customresource_verticalpodautoscaler_spec_resourcepolicy_containerpolicies_maxallowed{resource="memory"}
        for: 30m
        labels:
          severity: info
        annotations:
          summary: "Рекомендация VPA уперлась в лимит maxAllowed"
          description: "Нагрузка {{ $labels.verticalpodautoscaler }} требует больше памяти, чем разрешено политикой maxAllowed."
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Сводная матрица типовых неисправностей

| Симптом / Ошибка | Первопричина | Метод проверки | Действие по устранению |
| :--- | :--- | :--- | :--- |
| **VPA не формирует рекомендации** (секция `status.recommendation` пуста). | 1. Metrics Server не работает.<br>2. У контейнеров в Pod spec отсутствуют `requests`.<br>3. Контейнер работает меньше 5 минут. | `kubectl top pods -n <ns>`<br>`kubectl logs -n kube-system deploy/vpa-recommender` | 1. Восстановить Metrics Server.<br>2. Задать базовые `requests` в Deployment.<br>3. Дождаться накопления минимальной выборки метрик. |
| **Поды не обновляются при активном VPA**. | 1. `updateMode` установлен в `Off` или `Initial`.<br>2. Текущие ресурсы внутри диапазона `[lowerBound, upperBound]`.<br>3. PDB запрещает эвикцию. | `kubectl get vpa <name> -o yaml`<br>`kubectl get pdb -n <ns>` | 1. Переключить в `InPlaceOrRecreate`.<br>2. Скорректировать PDB (`maxUnavailable: 1`). |
| **Сбой создания подов: `failed calling webhook "vpa.k8s.io"`**. | Истек или не валиден TLS-сертификат вебхука; `vpa-admission-controller` недоступен. | `kubectl get events`<br>`curl -k -v https://vpa-webhook.kube-system:443` | 1. Обновить сертификат через cert-manager / `./hack/vpa-up.sh`.<br>2. Временно выставить `failurePolicy: Ignore` в MutatingWebhookConfiguration. |
| **Статус ресайза `Infeasible`**. | На узле не хватает свободного `NodeAllocatable` CPU/RAM для удовлетворения запроса In-Place. | `kubectl describe pod <name> \| grep -A5 Conditions` | 1. Перевести под в `InPlaceOrRecreate` (сработает эвикция на более свободный узел).<br>2. Оптимизировать плотность размещения через [Descheduler](./descheduler.md). |
| **Бесконечный рестарт подов (Thrashing / Eviction Churn)**. | 1. Конфликт VPA и HPA по одинаковым метрикам.<br>2. Всплесковая нагрузка при узком интервале `[lower, upper]`. | `kubectl get events --field-selector reason=EvictedByVPA`<br>`kubectl get hpa` | 1. Разделить метрики VPA и HPA.<br>2. Зафиксировать `minAllowed` на уровне пиковых значений.<br>3. Увеличить `--eviction-tolerance` до `0.7` в Updater. |
| **GitOps петля (ArgoCD / Flux вечный `OutOfSync`)**. | GitOps-агент перезаписывает мутированные поля ресурсов манифестом из Git. | `argocd app diff <app>` | Настроить `ignoreDifferences` с `RespectIgnoreDifferences=true` в ArgoCD. |
| **Java-приложение падает по OOMKilled после масштабирования**. | В JVM жестко задан `-Xmx`, приложение не видит добавленной оперативной памяти. | `kubectl logs <pod> \| grep -i maxheapsize` | Заменить `-Xmx` на процентные директивы `-XX:MaxRAMPercentage=75.0`. |

### Диагностические команды SRE

```bash
# 1. Проверка работоспособности Admission Webhook
kubectl get mutatingwebhookconfigurations vpa-webhook-config -o yaml
# → Проверить корректность caBundle и failurePolicy

# 2. Поиск событий выселения подов контроллером VPA
kubectl get events -A --field-selector reason=EvictedByVPA --sort-by='.lastTimestamp'
# → default   3m   EvictedByVPA   pod/core-api-7b89f8d9b-w9z4x   Pod was evicted by VPA Updater to apply recommendations

# 3. Инспекция логов Recommender на предмет ошибок расчета
kubectl logs -n kube-system -l app=vpa-recommender --tail=100
# → I0304 10:20:00.001 recommender.go:210] Cluster architecture: 4 nodes, 85 monitored containers

# 4. Проверка состояния In-Place Resize на уровне Kubelet
kubectl get pod postgres-0 -n databases -o jsonpath='{.status.conditions[?(@.type=="PodResizePending")].reason}'
# → Infeasible (если на узле нет свободной памяти)
```

---

## Рекомендации и лучшие практики (Best Practices)

1. **Всегда задавать защитные границы (Guardrails):**
   * Никогда не развертывать VPA в продакшене без блока `resourcePolicy`.
   * Обязательно указывать `minAllowed` (защита от деградации сервиса при отсутствии трафика) и `maxAllowed` (защита от исчерпания бюджета емкости кластера).
2. **Обязательная настройка Pod Disruption Budget:**
   * Для всех сервисов под управлением `updateMode: Recreate` или `InPlaceOrRecreate` должен быть объявлен PDB с `maxUnavailable: 1` или `minAvailable: N-1`. Это гарантирует сохранение доступности при эвикциях.
3. **Разграничение сфер влияния VPA и HPA:**
   * Категорически запрещено одновременное автоматическое управление по CPU/Memory.
   * Оптимальный шаблон: **HPA по внешним метрикам (RPS, Queue Length)** + **VPA в режиме `controlledResources: ["memory"]`** или **VPA в режиме `Off`**.
4. **Конфигурация failurePolicy для Webhook:**
   * В манифесте `MutatingWebhookConfiguration` для `vpa-webhook-config` устанавливайте `failurePolicy: Ignore`. Это гарантирует, что временный сбой пода вебхука не заблокирует развертывание релизов и запуск новых подов в кластере.
5. **Использование Prometheus для долгосрочного профилирования:**
   * Для сезонных нагрузок с циклом «неделя / месяц» переключайте `vpa-recommender` на чтение метрик из Prometheus (`--metric-storage=prometheus`). Это устраняет искажения, вызванные кратковременными всплесками.
6. **Настройка рантаймов (JVM / Go):**
   * Всегда используйте динамические переменные (`-XX:MaxRAMPercentage`, `GOMEMLIMIT`) для сред с динамическим размером памяти.
7. **Изоляция ServiceAccount и RBAC:**
   * Компоненты VPA должны запускаться под строго изолированными ServiceAccount с минимальными правами доступа (принцип наименьших привилегий).

---

## Дополнительная информация

### Взаимодействие со смежными компонентами кластера

* **[In-Place Pod Resize](./in_place_pod_resize.md):** базовый механизм ядра K8s, через который VPA в режиме `InPlaceOrRecreate` модифицирует cgroups контейнеров без прерывания соединений.
* **[Pod Disruption Budget](./pod_disruption_budget.md):** механизм контроля доступности, предотвращающий одновременный перезапуск реплик апдейтером VPA.
* **[Descheduler](./descheduler.md):** дополняет VPA в On-Premise среде. Если VPA увеличил ресурсы подов, вызвав неравномерную утилизацию узлов, Descheduler безопасно перебалансирует нагрузку между серверами.
* **[QoS классы и управление ресурсами](../Scheduling/qos_limit_and_requests.md):** VPA изменяет `requests` и `limits`, что напрямую влияет на класс обслуживания пода (Guaranteed, Burstable) и его `oom_score_adj` на уровне ядра Linux.
* **ResourceQuota и LimitRange:** рекомендации VPA не могут превышать лимиты пространства имен. Если VPA Admission Controller пытается подставить ресурсы, превышающие квоту пространства имен, API-сервер отклонит создание пода.
* **[GitOps для автоскейлинга](./gitops_autoscaling.md):** регламент синхронизации ресурсов между Git-репозиториями (ArgoCD/Flux) и динамическими мутациями VPA.

### Ограничения технологии

* **Короткоживущие задачи (Jobs / CronJobs):** VPA не эффективен для кратковременных задач, так как Recommender не успевает собрать статистически значимую выборку метрик.
* **Дисковые ресурсы:** VPA управляет исключительно CPU и оперативной памятью. Управление `ephemeral-storage` и постоянными томами (Persistent Volumes) не поддерживается.
* **Extended Resources (Расширенные ресурсы):** VPA не поддерживает автоматическое масштабирование HugePages, аппаратных сопроцессоров и иных пользовательских ресурсов узла (`spec.containers[].resources.limits`).

### Ссылки

* [In-Place Pod Resize](./in_place_pod_resize.md) — детальный архитектурный разбор механизма изменения ресурсов без перезапуска.
* [Обзор автоскейлинга в Kubernetes](./overview_concepts.md) — классификация и иерархия горизонтального, вертикального и инфраструктурного масштабирования.
* [Pod Disruption Budget](./pod_disruption_budget.md) — обеспечение непрерывной доступности при плановых выселениях подов.
* [Автомасштабирование StatefulSet](./statefulset_autoscaling.md) — специфика вертикального масштабирования баз данных и очередей сообщений.
* [Масштабирование в On-Premise инфраструктуре](./on_premise_autoscaling.md) — специфика автоскейлинга на физических серверах и локальной виртуализации.
* [Metrics Server](../MonitoringLogging/metrics-server.md) — установка, конфигурация и диагностика источника метрик.
* [Goldilocks](../ToolsUtilities/goldilocks.md) — визуализация и практическое применение рекомендаций VPA.
* [Устранение неполадок HPA](../Troubleshooting/Common_Errors/hpa_troubleshooting.md) — разрешение конфликтов регуляторов масштабирования.
* [Кластерный планировщик Descheduler](./descheduler.md) — вторичная балансировка и дефрагментация ресурсов узлов.
* [QoS классы и лимиты](../Scheduling/qos_limit_and_requests.md) — глубокое погружение в requests, limits и планирование подов.
