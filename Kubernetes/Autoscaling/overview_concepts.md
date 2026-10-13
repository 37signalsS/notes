# Автоматическое масштабирование в Kubernetes: Архитектурный обзор и концепции

**Актуально для:** Kubernetes 1.30–1.35 (API autoscaling/v2, In-Place Pod Resize GA, Cluster API)

## Определения

**Автоматическое масштабирование (Autoscaling)** — встроенный и расширяемый комплекс механизмов Kubernetes для динамической адаптации вычислительных мощностей кластера (как на уровне рабочих нагрузок, так и на уровне инфраструктурных узлов) к профилю текущей нагрузки в реальном времени.

**Горизонтальное масштабирование (Horizontal Scaling)** — изменение количества активных экземпляров (реплик подов или узлов кластера).
*   **Scale-out (Масштабирование вовне):** Добавление новых реплик подов или физических/виртуальных серверов при возрастании входящего трафика или длины очереди задач.
*   **Scale-in (Масштабирование внутрь):** Контролируемое сокращение числа реплик или узлов при спаде нагрузки для устранения простоя оборудования.

**Вертикальное масштабирование (Vertical Scaling)** — изменение вычислительных ресурсов (CPU, Memory), выделенных конкретным контейнерам или серверам.
*   **Scale-up (Масштабирование вверх):** Увеличение лимитов и запросов ресурсов контейнера. Включает классический метод с перезапуском пода (Recreate) и изменение параметров cgroups на лету (**In-Place Pod Resize**).
*   **Scale-down (Масштабирование вниз):** Снижение выделенных лимитов и запросов ресурсов контейнера при снижении потребления.

**Horizontal Pod Autoscaler (HPA)** — встроенный контроллер Kubernetes (`autoscaling/v2`), регулирующий число реплик в объектах `Deployment`, `StatefulSet` или `ReplicaSet` на основе данных об утилизации ресурсов (CPU, RAM) либо кастомных метрик приложения.

**Vertical Pod Autoscaler (VPA)** — внешний оператор Kubernetes (`autoscaling.k8s.io`), анализирующий фактическое потребление ресурсов контейнерами и автоматически корректирующий значения `requests` и `limits` CPU и оперативной памяти.

**KEDA (Kubernetes Event-driven Autoscaling)** — событийно-ориентированный оператор автомасштабирования, расширяющий HPA поддержкой десятков внешних систем очередей, баз данных и брокеров сообщений (Kafka, RabbitMQ, PostgreSQL, Redis, Prometheus), а также обеспечивающий масштабирование нагрузки до нуля (**Scale-to-Zero**).

**Cluster Autoscaler (CA)** — системный контроллер, управляющий размером пула рабочих узлов (Worker Nodes). Принимает решение о добавлении узлов исключительно при наличии подов в состоянии `Pending`, не помещающихся на текущие серверы из-за дефицита `requests`, и удаляет недогруженные узлы с соблюдением политик безопасности.

**Cluster API (CAPI)** — декларативный фреймворк Kubernetes для управления жизненным циклом кластеров и узлов через CRD (`Machine`, `MachineSet`, `MachineDeployment`). В локальных средах (On-Premise) взаимодействует с Bare-Metal через Metal3 (CAPM3) либо с платформами виртуализации через CAPV (VMware vSphere), CAPK (KubeVirt) или CAPO (OpenStack).

**In-Place Pod Resize** — возможность Kubernetes (GA в версии 1.35), позволяющая изменять `resources.requests` и `resources.limits` CPU и памяти контейнера непосредственно в cgroups ядра Linux без перезапуска пода и переподключения сетевого сокета.

**Headroom (Overprovisioning Buffer)** — архитектурный паттерн поддержания «тёплого» запаса вычислительных мощностей в кластере с помощью спящих подов с отрицательным приоритетом (`PriorityClass`). Гарантирует мгновенное размещение всплесков нагрузки без ожидания длительной загрузки физических серверов.

**Pod Disruption Budget (PDB)** — ресурс политики доступности (`policy/v1`), определяющий минимально допустимое количество готовых реплик приложения во время добровольного выселения подов (при сжатии пула узлов или обслуживании серверов).

**Дребезг масштабирования (Flapping / Thrashing)** — негативный эффект быстрого циклического переключения между scale-up и scale-down из-за кратковременных всплесков нагрузки или некорректно настроенных окон стабилизации.

---

## Архитектура и базовые концепции

### Иерархия уровней масштабирования

Автомасштабирование в Kubernetes разделено на два независимых, но тесно взаимодействующих уровня: уровень приложений (**Workload Layer**) и уровень инфраструктуры (**Infrastructure Layer**).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                              │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                    Workload Layer (Поды)                       │   │
│   │                                                                │   │
│   │   ┌───────────────┐   ┌───────────────┐   ┌────────────────┐   │   │
│   │   │  HPA (v2)     │   │     KEDA      │   │   VPA (Auto/   │   │   │
│   │   │  (CPU / RAM / │   │ (Events, Msg  │   │    In-Place)   │   │   │
│   │   │   Custom)     │   │   Queues)     │   │  (Requests /   │   │   │
│   │   │               │   │               │   │    Limits)     │   │   │
│   │   └───────┬───────┘   └───────┬───────┘   └────────┬───────┘   │   │
│   │           │                   │                    │           │   │
│   │           ▼                   ▼                    ▼           │   │
│   │     Scale-Out / In (Replicas)            In-Place / Recreate   │   │
│   │                                                                │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
│                                   │                                    │
│                     Нехватка requests (Pending)                        │
│                                   │                                    │
│                                   ▼                                    │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                 Infrastructure Layer (Узлы)                    │   │
│   │                                                                │   │
│   │                  ┌───────────────────────────┐                 │   │
│   │                  │    Cluster Autoscaler     │                 │   │
│   │                  │  (Pending Pods Trigger)   │                 │   │
│   │                  └─────────────┬─────────────┘                 │   │
│   │                                │                               │   │
│   │                                ▼                               │   │
│   │                  ┌───────────────────────────┐                 │   │
│   │                  │    Cluster API (CAPI)     │                 │   │
│   │                  │  (MachineDeployment CRUD) │                 │   │
│   │                  └──────┬─────────────┬──────┘                 │   │
│   │                         │             │                        │   │
│   │                         ▼             ▼                        │   │
│   │                 Bare-Metal (Metal3)  Virtualization (vSphere)  │   │
│   │                 PXE / BMC / Ironic   VM Template Clone         │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

| Уровень | Объект | Компонент | Тип масштабирования | Ключевой механизм |
|---|---|---|---|---|
| **Приложение** | Поды (Replicas) | [HPA](HPA/index.md) | Горизонтальное | Модификация `spec.replicas` в Deployment/StatefulSet по метрикам |
| **Приложение** | Поды (Replicas) | [KEDA](./keda/keda_concepts.md) | Горизонтальное | Scale-to-Zero, опрос очередей (Kafka, RabbitMQ, DB) через External Metrics |
| **Приложение** | Ресурсы (CPU/RAM) | [VPA](vpa_detailed.md) | Вертикальное | Анализ истории и обновление `requests`/`limits` (In-Place или Recreate) |
| **Приложение** | Ресурсы контейнера | [In-Place Resize](in_place_pod_resize.md) | Вертикальное | Мутация cgroups ядра через Kubelet/containerd без рестарта |
| **Инфраструктура** | Узлы (Nodes) | [Cluster Autoscaler](cluster_autoscaler_detailed.md) | Горизонтальное | Обнаружение `Pending` подов и масштабирование MachineDeployments |
| **Инфраструктура** | Физические узлы | [On-Premise CAPI / Metal3](on_premise_autoscaling.md) | Горизонтальное | Выделение серверов через IPMI/Redfish, Ironic и сетевую загрузку PXE |

---

### Архитектура и принципы работы компонентов

#### 1. Horizontal Pod Autoscaler (HPA)

HPA функционирует как управляющий контур (Control Loop) внутри `kube-controller-manager`. По умолчанию период синхронизации `--horizontal-pod-autoscaler-sync-period` составляет 15 секунд.

*   **Алгоритм расчёта:**
    $$\text{desiredReplicas} = \left\lceil \text{currentReplicas} \times \left( \frac{\text{currentMetricValue}}{\text{targetMetricValue}} \right) \right\rceil$$
*   **Зона нечувствительности (Tolerance):** По умолчанию составляет 10% (флаг контроллера `--horizontal-pod-autoscaler-tolerance=0.1`). Если отношение текущей метрики к целевой находится в диапазоне $[0.9; 1.1]$, масштабирование не выполняется, что защищает от мелких колебаний.
*   **Секция `behavior` (autoscaling/v2):** Позволяет асимметрично управлять скоростью наращивания и сжатия:
    *   `scaleUp`: Как правило, агрессивный (`stabilizationWindowSeconds: 0`), с возможностью утроения подов в минуту для защиты SLA.
    *   `scaleDown`: Плавный, с окном стабилизации (`stabilizationWindowSeconds: 300`) и ограничением темпа (например, не более 2 подов в 2 минуты), предотвращающий преждевременное удаление реплик.
*   **Источники метрик:**
    *   *Resource Metrics API:* `metrics-server` (CPU и Resident Memory контейнеров).
    *   *Custom Metrics API:* `prometheus-adapter` (RPS сервиса, задержка ответов HTTP).
    *   *External Metrics API:* `keda-metrics-apiserver` (размер очереди брокера сообщений).
*   **Подробнее:** [HPA: Архитектура и концепции](HPA/hpa_concepts.md), [HPA: Расширенная настройка](HPA/hpa_advanced.md).

#### 2. Vertical Pod Autoscaler (VPA)

VPA решает задачу оптимального подбора вычислительных ресурсов (`requests` и `limits`), устраняя ручное гадание и риски CPU Throttling / OOMKilled. Архитектура VPA включает три независимых компонента:

1.  **VPA Recommender:** Опрашивает Metrics Server и агрегирует историю потребления. Рассчитывает 95-й перцентиль по CPU и 99-й перцентиль по памяти за скользящее 8-дневное окно.
2.  **VPA Admission Controller:** Мутирующий вебхук (`MutatingWebhookConfiguration`). Перехватывает создание пода и подставляет актуальные рекомендованные значения `requests`/`limits`.
3.  **VPA Updater:** Отслеживает запущенные поды. Если текущие ресурсы расходятся с рекомендациями, инициирует обновление.
*   **Режимы работы (Update Modes):**
    *   `Off`: Только расчет рекомендаций (`Target`, `LowerBound`, `UpperBound`). Безопасный режим для аудита и SRE-профилирования.
    *   `Initial`: Применение рекомендованных значений только в момент создания нового пода.
    *   `Recreate`: Выселение работающих подов (Eviction) для перезапуска с новыми ресурсами (вызывает деградацию при отсутствии избыточности).
    *   `InPlaceOrRecreate`: Приоритетное обновление cgroups на лету через Kubelet без рестарта контейнера. Если нода переполнена, под пересоздается.
*   **OOM-Driven Scaling:** VPA моментально фиксирует событие `OOMKilled` и экстренно поднимает рекомендованный лимит памяти с запасом, не дожидаясь суточной аналитики.
*   **Подробнее:** [VPA: Подробный разбор](vpa_detailed.md).

#### 3. In-Place Pod Resize

Механизм прямого обновления ресурсов контейнера (GA в Kubernetes 1.35). До появления этой технологии любое изменение `requests` или `limits` требовало пересоздания пода, что сопровождалось сбросом TCP-соединений, прогревом JVM-кэшей и падением доступности.

*   **Как это работает:**
    1. Пользователь или VPA выполняет `PATCH` спецификации пода в API Server (`spec.containers[*].resources`).
    2. API Server валидирует запрос и обновляет `status.containerStatuses[*].allocatedResources`.
    3. Kubelet на узле сравнивает `allocatedResources` с текущим состоянием cgroups.
    4. Kubelet вызывает через CRI интерфейс `UpdateContainerResources` у containerd/CRI-O.
    5. Container runtime напрямую изменяет параметры cgroup v2 (`cpu.max`, `memory.max`, `cpu.weight`) без сигнала остановки процессу.
*   **Политика `resizePolicy`:** В манифесте пода настраивается раздельно для `cpu` и `memory`:
    *   `RestartNotRequired` — изменение лимита выполняется на лету.
    *   `RestartContainer` — требуется перезапуск контейнера (например, если рантайм языка не умеет динамически адаптировать heap-память).
*   **Подробнее:** [In-Place Pod Resize: Глубокое погружение](in_place_pod_resize.md).

#### 4. KEDA (Событийное масштабирование)

KEDA внедряет событийно-ориентированную модель в Kubernetes, устраняя ограничения встроенного HPA:

*   **Scale-to-Zero:** Когда очередь сообщений пуста, KEDA сворачивает Deployment до 0 реплик, полностью освобождая ресурсы узлов. При появлении хотя бы одного сообщения в брокере контроллер мгновенно активирует под (`0 -> 1`), передавая дальнейшее управление алгоритмам HPA.
*   **Архитектура:**
    *   `keda-operator`: Контроллер, управляющий жизненным циклом CRD `ScaledObject` и создающий дочерний объект `HorizontalPodAutoscaler`.
    *   `keda-metrics-apiserver`: Реализация интерфейса Kubernetes External Metrics API, транслирующая метрики из брокеров сообщений непосредственно в HPA.
*   **Локальные скалеры (On-Premise):** Работает с Kafka, RabbitMQ, NATS, Redis, PostgreSQL, MySQL, Elasticsearch, Prometheus без привязки к внешним сервисам.
*   **Подробнее:** [KEDA: Основные концепции](./keda/keda_concepts.md), [KEDA: Практические сценарии](./keda/practical_scenarios.md).

#### 5. Cluster Autoscaler в локальной инфраструктуре (On-Premise)

В частных ЦОД Cluster Autoscaler опирается на **Cluster API (CAPI)**:

*   **Триггер масштабирования вверх (Scale-Up):** Наличие подов со статусом `Pending` и причиной `FailedScheduling` (недостаточно CPU/RAM requests на узлах). CA симулирует размещение подов на гипотетических узлах доступных групп `MachineDeployment`. При успешной симуляции CA увеличивает реплики `MachineDeployment`.
*   **Триггер сжатия (Scale-Down):** Узел помечается как `unneeded`, если суммарные `requests` размещенных на нем подов ниже порога (по умолчанию 50% от емкости узла) на протяжении времени `--scale-down-unneeded-time=10m`. Перед удалением сервер переводится в `cordon` и `drain` с обязательным учетом бюджетов PDB.
*   **Специфика частного ЦОД:**
    *   В виртуализированной среде (vSphere, KVM, Proxmox) новый узел создается за 1–3 минуты.
    *   На физическом железе (Bare-Metal через Metal3/Ironic) ввод сервера в строй занимает от 8 до 20 минут (аппаратный POST, инициализация BMC/IPMI, сетевая загрузка PXE, прожиг дискового образа).
*   **Подробнее:** [Cluster Autoscaler: Архитектура и алгоритмы](cluster_autoscaler_detailed.md), [Autoscaling в On-Premise](on_premise_autoscaling.md).

---

### Сквозная цепочка автомасштабирования (End-to-End Lifecycle)

В промышленном кластере компоненты масштабирования образуют согласованную цепочку реакции на всплеск нагрузки:

```
[1. Рост нагрузки] ──► RPS возрастает или растет лаг очереди в Kafka / RabbitMQ
        │
        ▼
[2. Детекция]      ──► Metrics Server / KEDA фиксирует превышение целевого порога
        │
        ▼
[3. Вычисление]    ──► HPA рассчитывает desiredReplicas и патчит Deployment
        │
        ▼
[4. Планирование]  ──► kube-scheduler пытается разместить новые поды
        │
        ├──► Ресурсы есть в наличии ──► Pod Running ──► Трафик распределен
        │
        └──► Ресурсов на узлах нет
                 │
                 ▼
[5. Дефицит]       ──► Поды переходят в состояние Pending (FailedScheduling)
        │
        ▼
[6. Scale-Up нод]  ──► Cluster Autoscaler фиксирует Pending поды и вызывает CAPI
        │
        ▼
[7. Провижининг]   ──► Metal3 / vSphere вводит новый узел в строй (PXE / VM Clone)
        │
        ▼
[8. Размещение]    ──► kubelet регистрирует узел, Scheduler размещает Pending поды
        │
        ▼
[9. Оптимизация]   ──► VPA анализирует профиль нагрузки и корректирует cgroups (In-Place)
        │
        ▼
[10. Спад нагрузки] ──► HPA/KEDA сокращает реплики; CA дренирует и удаляет лишние узлы
```

#### Временные задержки (Autoscaling Latency Breakdown)

SRE-инженеры должны учитывать, что реактивное масштабирование не является мгновенным. Совокупный лаг состоит из нескольких фаз:

1.  **Интервал сбора метрик (Metrics Scraping Lag):** 10–30 секунд (сбор cAdvisor узла $\to$ агрегация в Metrics Server / Prometheus).
2.  **Интервал расчета контроллера (HPA Sync Period):** 15 секунд (ожидание тика управляющего контура `kube-controller-manager`).
3.  **Инициализация пода (Pod Startup Latency):** 15–90 секунд (скачивание образа контейнера, выполнение `initContainers`, прогрев приложения, проверка `readinessProbe`).
4.  **Задержка ввода узла (Node Provisioning Latency):**
    *   При наличии Headroom: **0 секунд** (поды размещаются мгновенно).
    *   Виртуальные машины (vSphere/KubeVirt): **1–3 минуты**.
    *   Физические серверы (Bare-Metal Metal3/PXE): **8–20 минут**.

> [!IMPORTANT]
> При резких всплесках трафика (Spike) реактивный HPA + CA не успевает ввести узлы в строй до деградации SLA. Решением для частных дата-центров является архитектурный буфер **Headroom** (предварительное резервирование емкости).

---

### Матрица архитектурных конфликтов и ограничений

| Конфликт / Проблема | Причина возникновения | Решение для DevOps / SRE |
|---|---|---|
| **HPA + VPA по одной метрике (CPU/RAM)** | Оба контроллера одновременно пытаются компенсировать нагрузку: HPA добавляет реплики, VPA увеличивает размер подов. Возникает «гонка масштабирования» и раздувание ресурсов. | **Строгое разделение:** HPA масштабирует по CPU или RPS; VPA работает в режиме `Off` (рекомендации) либо масштабирует память через In-Place Resize. |
| **GitOps (ArgoCD / Flux) vs HPA** | В Git зафиксировано `replicas: 3`. HPA увеличивает число до `10`. Механизм `selfHeal` в GitOps считает это дрейфом и принудительно возвращает `3`. | 1. Удалить строку `replicas` из манифеста в Git.<br>2. В манифесте ArgoCD `Application` настроить [`ignoreDifferences`](../../GitOps/ArgoCD/synchronization/ignore_differences.md) для `/spec/replicas` с параметром `RespectIgnoreDifferences=true`. |
| **PDB блокирует сжатие узлов (Scale-Down)** | Слишком строгий бюджет (например, `minAvailable: 100%` или `maxUnavailable: 0`) запрещает выселение подов. CA не может очистить и выключить узел. | Использовать относительные проценты (`maxUnavailable: 20%`) либо оставлять числовой зазор, достаточный для миграции минимум одного пода. |
| **Локальное хранилище (emptyDir / HostPath)** | Поды используют локальные диски узла без аннотации разрешения выселения. CA считает узел неизвлекаемым. | Добавить поду аннотацию `"cluster-autoscaler.kubernetes.io/safe-to-evict": "true"`. |
| **Долгий cold start физических узлов** | Bare-metal узлы загружаются через PXE 10+ минут, поды простаивают в `Pending`. | Развернуть **Headroom** (спящие поды с низким приоритетом), освобождающие место мгновенно при вытеснении. |

---

## Практические сценарии

### Предварительные требования

Перед развертыванием сценариев убедитесь, что в кластере функционируют базовые компоненты:

1.  **Kubernetes 1.30+** с включенными cgroups v2 на рабочих узлах.
2.  **Metrics Server:** развернут и доступен через агрегированный API.
3.  **Инструменты:** настроены утилиты командной строки `kubectl`, `curl`, `jq`.

```bash
# 1. Проверка версии ядра и cgroups v2 на узлах кластера
kubectl get nodes -o wide
# → NAME     STATUS   ROLES    AGE   VERSION   INTERNAL-IP   OS-IMAGE             KERNEL-VERSION
# → node-1   Ready    worker   45d   v1.32.2   10.10.10.11   Ubuntu 24.04.1 LTS   6.8.0-40-generic
# → node-2   Ready    worker   45d   v1.32.2   10.10.10.12   Ubuntu 24.04.1 LTS   6.8.0-40-generic

# 2. Проверка доступности API метрик
kubectl top nodes
# → NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node-1   420m         10%    4120Mi          26%
# → node-2   380m         9%     3850Mi          24%

# 3. Проверка доступности группы API autoscaling/v2
kubectl api-resources --api-group=autoscaling
# → NAME                      SHORTNAMES   APIVERSION       NAMESPACED   KIND
# → horizontalpodautoscalers  hpa          autoscaling/v2   true         HorizontalPodAutoscaler
```

---

### Сценарий 1: Отказоустойчивый HPA для веб-микросервиса с защитой от флаттеринга и PDB

**Контекст:** Производственный веб-сервис в локальном кластере. Требуется настроить мгновенный scale-up при росте нагрузки, плавное удержание реплик при спаде (защита от дребезга) и гарантию доступности при дренаже серверов.

#### Шаг 1. Создание манифеста Deployment

```yaml
# webapp-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: production
  labels:
    app.kubernetes.io/name: webapp
spec:
  # Поле replicas намеренно не указывается для совместимости с HPA и GitOps
  selector:
    matchLabels:
      app.kubernetes.io/name: webapp
  template:
    metadata:
      labels:
        app.kubernetes.io/name: webapp
    spec:
      containers:
      - name: webapp
        image: nginx:1.27-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "500m"
            memory: "256Mi"
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]
```

#### Шаг 2. Создание манифеста HPA с расширенным поведением (behavior)

```yaml
# webapp-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: webapp-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp
  minReplicas: 3
  maxReplicas: 15
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 65
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      selectPolicy: Max
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 4
        periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      selectPolicy: Min
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
      - type: Pods
        value: 2
        periodSeconds: 60
```

#### Шаг 3. Создание манифеста PodDisruptionBudget (PDB)

```yaml
# webapp-pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: webapp-pdb
  namespace: production
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: webapp
```

#### Шаг 4. Применение и валидация

```bash
# Применение манифестов
kubectl apply -f webapp-deployment.yaml
# → deployment.apps/webapp created
kubectl apply -f webapp-hpa.yaml
# → horizontalpodautoscaler.autoscaling/webapp-hpa created
kubectl apply -f webapp-pdb.yaml
# → poddisruptionbudget.policy/webapp-pdb created

# Проверка исходного состояния HPA
kubectl get hpa webapp-hpa -n production
# → NAME         REFERENCE           TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → webapp-hpa   Deployment/webapp   cpu: 1%/65%     3         15        3          45s

# Запуск генератора нагрузки внутри кластера
kubectl run load-generator -n production --rm -i --tty --image=busybox:1.36 --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://webapp.production.svc.cluster.local > /dev/null; done"

# Наблюдение за реакцией HPA в соседнем терминале
kubectl get hpa webapp-hpa -n production -w
# → webapp-hpa   Deployment/webapp   cpu: 85%/65%    3         15        3          2m
# → webapp-hpa   Deployment/webapp   cpu: 85%/65%    3         15        6          2m15s
# → webapp-hpa   Deployment/webapp   cpu: 64%/65%    3         15        8          2m30s
```

---

### Сценарий 2: Гибридное масштабирование VPA (In-Place по памяти) + HPA (RPS по кастомным метрикам)

**Контекст:** Сервис обработки запросов с базой данных в On-Premise. Нельзя масштабировать реплики по CPU из-за особенностей многопоточного профиля, но требуется автоподбор лимитов памяти на лету без падений по OOMKilled, а реплики масштабировать по числу входящих HTTP-запросов (RPS).

#### Шаг 1. Настройка VPA в режиме InPlaceOrRecreate для контроля памяти

```yaml
# service-vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api-service-vpa
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-service
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
    - containerName: api-service
      controlledResources: ["memory"]
      minAllowed:
        memory: "256Mi"
      maxAllowed:
        memory: "4Gi"
      controlledValues: "RequestsAndLimits"
```

#### Шаг 2. Настройка HPA по метрике RPS из Prometheus

```yaml
# service-hpa-rps.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-service-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-service
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "200m"
```

#### Шаг 3. Валидация работы связки

```bash
kubectl apply -f service-vpa.yaml
# → verticalpodautoscaler.autoscaling.k8s.io/api-service-vpa created
kubectl apply -f service-hpa-rps.yaml
# → horizontalpodautoscaler.autoscaling/api-service-hpa created

# Проверка расчетных рекомендаций VPA
kubectl describe vpa api-service-vpa -n production
# → Recommendation:
# →   Container Recommendations:
# →     Container Name:  api-service
# →     Lower Bound:
# →       Memory:  256Mi
# →     Target:
# →       Memory:  512Mi
# →     Uncapped Target:
# →       Memory:  512Mi
# →     Upper Bound:
# →       Memory:  1024Mi

# Проверка, что VPA обновил cgroup памяти без рестарта пода (In-Place Resize)
kubectl get pod -n production -l app=api-service -o jsonpath='{range .items[*]}{.metadata.name}{"\tRestarts: "}{.status.containerStatuses[0].restartCount}{"\tAllocated Mem: "}{.status.containerStatuses[0].allocatedResources.memory}{"\n"}{end}'
# → api-service-7f9b8c6-a1b2c   Restarts: 0   Allocated Mem: 512Mi
# → api-service-7f9b8c6-d3e4f   Restarts: 0   Allocated Mem: 512Mi
```

---

### Сценарий 3: KEDA Scale-to-Zero для воркеров обработки локальной очереди RabbitMQ

**Контекст:** Асинхронные фоновые обработчики задач. Ночью задачи отсутствуют, поды должны сворачиваться в `0`, высвобождая память кластера. При поступлении сообщений в RabbitMQ воркеры должны мгновенно подниматься.

#### Шаг 1. Манифест воркера

```yaml
# rabbitmq-worker.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: queue-worker
  namespace: processing
spec:
  replicas: 0
  selector:
    matchLabels:
      app: queue-worker
  template:
    metadata:
      labels:
        app: queue-worker
    spec:
      containers:
      - name: worker
        image: alpine:3.20
        command: ["/bin/sh", "-c", "sleep 3600"]
        resources:
          requests:
            cpu: "200m"
            memory: "128Mi"
```

#### Шаг 2. Манифест KEDA TriggerAuthentication и ScaledObject

```yaml
# keda-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: rabbitmq-auth
  namespace: processing
spec:
  secretTargetRef:
  - parameter: host
    name: rabbitmq-credentials
    key: amqp-uri
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-queue-scaler
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: queue-worker
  pollingInterval: 10
  cooldownPeriod: 60
  minReplicaCount: 0
  maxReplicaCount: 20
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 120
  triggers:
  - type: rabbitmq
    metadata:
      protocol: amqp
      queueName: task-pipeline
      mode: QueueLength
      value: "50"
      activationValue: "1"
    authenticationRef:
      name: rabbitmq-auth
```

#### Шаг 3. Валидация Scale-to-Zero

```bash
kubectl apply -f rabbitmq-worker.yaml
# → deployment.apps/queue-worker created
kubectl apply -f keda-scaledobject.yaml
# → triggerauthentication.keda.sh/rabbitmq-auth created
# → scaledobject.keda.sh/rabbitmq-queue-scaler created

# Проверка начального состояния: 0 реплик
kubectl get deployment queue-worker -n processing
# → NAME           READY   UP-TO-DATE   AVAILABLE   AGE
# → queue-worker   0/0     0            0           30s

# Проверка статуса KEDA
kubectl get scaledobject rabbitmq-queue-scaler -n processing
# → NAME                    SCALETARGETKIND      SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION   READY   ACTIVE   AGE
# → rabbitmq-queue-scaler   apps/v1.Deployment   queue-worker      0     20    rabbitmq   rabbitmq-auth    True    False    1m

# После отправки 250 сообщений в очередь RabbitMQ:
kubectl get deployment queue-worker -n processing
# → NAME           READY   UP-TO-DATE   AVAILABLE   AGE
# → queue-worker   5/5     5            5           2m
```

---

### Сценарий 4: Создание буфера мощностей (Headroom / Overprovisioning) для Cluster Autoscaler

**Контекст:** В On-Premise дата-центре физические узлы (Bare-Metal) через Metal3 загружаются по PXE около 12 минут. Если кластер заполнится до 100%, новые поды сервисов будут висеть в `Pending` 12 минут. Решение: развернуть низкоприоритетные «поды-заглушки», резервирующие емкость двух серверов.

#### Шаг 1. Создание PriorityClass с отрицательным приоритетом

```yaml
# headroom-priority.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning-headroom
value: -1
globalDefault: false
description: "Низкий приоритет для буферных подов резервирования емкости кластера."
```

#### Шаг 2. Развертывание Deployment резерва

```yaml
# headroom-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-headroom
  namespace: kube-system
spec:
  replicas: 4
  selector:
    matchLabels:
      app: cluster-headroom
  template:
    metadata:
      labels:
        app: cluster-headroom
    spec:
      priorityClassName: overprovisioning-headroom
      terminationGracePeriodSeconds: 0
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.10
        resources:
          requests:
            cpu: "2"
            memory: "8Gi"
          limits:
            cpu: "2"
            memory: "8Gi"
```

#### Шаг 3. Валидация мгновенного вытеснения

```bash
kubectl apply -f headroom-priority.yaml
# → priorityclass.scheduling.k8s.io/overprovisioning-headroom created
kubectl apply -f headroom-deployment.yaml
# → deployment.apps/cluster-headroom created

# Проверка запуска буферных подов
kubectl get pods -n kube-system -l app=cluster-headroom -o wide
# → NAME                                READY   STATUS    NODE     NOMINATED NODE
# → cluster-headroom-6f778d9b4-8xk21   1/1     Running   node-1   <none>
# → cluster-headroom-6f778d9b4-c9m04   1/1     Running   node-2   <none>

# Развертывание боевого приложения с дефицитом ресурсов
kubectl create deployment heavy-app -n production --image=nginx:alpine --replicas=2
kubectl set resources deployment heavy-app -n production --requests=cpu=2,memory=8Gi

# Боевые поды мгновенно вытесняют cluster-headroom:
kubectl get pods -n production -l app=heavy-app
# → NAME                         READY   STATUS    AGE   NODE
# → heavy-app-5d8f6d89f7-p7x4k   1/1     Running   3s    node-1
# → heavy-app-5d8f6d89f7-v9z12   1/1     Running   3s    node-2

# Буферные поды переходят в Pending и в фоновом режиме будят Cluster Autoscaler:
kubectl get pods -n kube-system -l app=cluster-headroom
# → cluster-headroom-6f778d9b4-8xk21   0/1     Pending   10s   <none>
```

---

### Сценарий 5: Защита критичного StatefulSet (PostgreSQL) при сжатии пула узлов

**Контекст:** База данных PostgreSQL развернута в кластере. Cluster Autoscaler при оптимизации пула рабочих узлов не должен выселять поды СУБД и удалять узел, на котором запущен primary-инстанс.

```yaml
# postgres-protection.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: database
spec:
  serviceName: postgresql
  replicas: 3
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
      annotations:
        # Запрет Cluster Autoscaler выселять данный под
        cluster-autoscaler.kubernetes.io/safe-to-evict: "false"
    spec:
      containers:
      - name: postgresql
        image: postgres:16-alpine
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgresql-pdb
  namespace: database
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: postgresql
```

```bash
# Применение конфигурации
kubectl apply -f postgres-protection.yaml
# → statefulset.apps/postgresql created
# → poddisruptionbudget.policy/postgresql-pdb created

# Блокировка выключения физического узла, на котором работает мастер БД
NODE_NAME=$(kubectl get pod postgresql-0 -n database -o jsonpath='{.spec.nodeName}')
kubectl annotate node "$NODE_NAME" cluster-autoscaler.kubernetes.io/scale-down-disabled="true"
# → node/node-1 annotated

# Проверка наличия аннотации на узле
kubectl get node "$NODE_NAME" -o jsonpath='{.metadata.annotations.cluster-autoscaler\.kubernetes\.io/scale-down-disabled}'
# → true
```

---

### Сценарий 6: Мониторинг и алерты Prometheus для контуров автомасштабирования

**Контекст:** Развертывание правил мониторинга для обнаружения сбоев HPA, зависших подов в `Pending` и деградации контроллеров масштабирования.

```yaml
# autoscaling-prometheus-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
  - name: kubernetes-autoscaling.rules
    rules:
    - alert: HPAScaleCapabilityExhausted
      expr: kube_hpa_status_current_replicas == kube_hpa_spec_max_replicas and kube_hpa_status_condition{condition="ScalingLimited",status="true"} == 1
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "HPA уперся в максимальный лимит реплик"
        description: "HPA {{ $labels.horizontalpodautoscaler }} в неймспейсе {{ $labels.namespace }} удерживает максимум реплик ({{ $value }}). Резерв масштабирования исчерпан."

    - alert: PodsStuckInPending
      expr: sum by (namespace) (kube_pod_status_phase{phase="Pending"}) > 0
      for: 10m
      labels:
        severity: critical
      annotations:
        summary: "Поды застряли в статусе Pending более 10 минут"
        description: "В неймспейсе {{ $labels.namespace }} обнаружены поды в состоянии Pending. Проверьте емкость узлов кластера, квоты ResourceQuota и работу Cluster Autoscaler."

    - alert: ClusterAutoscalerScaleUpFailed
      expr: rate(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Сбой масштабирования узлов кластера (Cluster Autoscaler)"
        description: "Cluster Autoscaler не может ввести новые рабочие узлы в строй. Проверьте состояние MachineDeployment в Cluster API, связь с Metal3/vSphere и пул физических адресов."

    - alert: VPARecommenderDown
      expr: absent(up{job="vpa-recommender"} == 1)
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "VPA Recommender недоступен"
        description: "Компонент VPA Recommender не отвечает. Рекомендации по оптимизации ресурсов не рассчитываются."
```

```bash
kubectl apply -f autoscaling-prometheus-rules.yaml
# → prometheusrule.monitoring.coreos.com/autoscaling-alerts created
```

---

## Операции и команды

Справочник базовых команд для инженеров DevOps и SRE по управлению и диагностике компонентов автомасштабирования:

| Операция | Команда | Назначение |
|---|---|---|
| **Инспекция HPA** | `kubectl get hpa -A` | Общий просмотр всех объектов HPA, целевых значений и текущих реплик |
| **Детализация HPA** | `kubectl describe hpa <name> -n <ns>` | Просмотр событий масштабирования, условий (AbleToScale, ScalingLimited) и истории метрик |
| **Инспекция VPA** | `kubectl get vpa -A` | Просмотр объектов VPA, режима работы (UpdateMode) и статуса поддержки |
| **Рекомендации VPA** | `kubectl describe vpa <name> -n <ns>` | Детальный вывод рекомендаций (Target, LowerBound, UpperBound) по контейнерам |
| **Инспекция KEDA** | `kubectl get scaledobjects.keda.sh -A` | Просмотр статуса готовности (Ready) и активности (Active) очередей |
| **Потребление узлов** | `kubectl top nodes --sort-by=cpu` | Анализ фактической нагрузки узлов для выявления дисбаланса |
| **Потребление подов** | `kubectl top pods -A --sort-by=memory` | Поиск подов с высоким потреблением оперативной памяти |
| **Ручной оверрайд** | `kubectl scale deployment <name> --replicas=5` | Временное принудительное изменение числа реплик |
| **Запрет дренажа ноды** | `kubectl annotate node <node> cluster-autoscaler.kubernetes.io/scale-down-disabled="true"` | Защита конкретного сервера от удаления контроллером Cluster Autoscaler |
| **Снятие защиты ноды** | `kubectl annotate node <node> cluster-autoscaler.kubernetes.io/scale-down-disabled-` | Разрешение Cluster Autoscaler анализировать и удалять узел |
| **Эвенты планировщика** | `kubectl get events -A --field-selector reason=FailedScheduling` | Просмотр причин невозможности размещения подов |
| **Логи Cluster Autoscaler** | `kubectl logs -n kube-system -l app=cluster-autoscaler --tail=100 -f` | Мониторинг решений о scale-up и scale-down в реальном времени |

### Примеры выполнения диагностических команд

```bash
# 1. Диагностика состояния HPA с подробным статусом
kubectl describe hpa webapp-hpa -n production
# → Name:                                                  webapp-hpa
# → Namespace:                                             production
# → Reference:                                             Deployment/webapp
# → Metrics:                                               ( current / target )
# →   resource cpu on pods  (as a percentage of request):  42% (42m) / 65%
# → Min replicas:                                          3
# → Max replicas:                                          15
# → Deployment pods:                                       3 current / 3 desired
# → Conditions:
# →   Type            Status  Reason               Message
# →   ----            ------  ------               -------
# →   AbleToScale     True    ReadyForNewScale     recommended size matches current size
# →   ScalingActive   True    ValidMetricFound     the HPA was able to successfully calculate a replica count
# →   ScalingLimited  False   DesiredWithinRange   the desired count is within the acceptable range

# 2. Просмотр структуры MachineDeployments в Cluster API (On-Premise)
kubectl get machinedeployments -A
# → NAMESPACE   NAME           CLUSTER      REPLICAS   READY   UPDATED   UNAVAILABLE   PHASE       AGE
# → default     worker-baremetal-pool   k8s-prod     8          8       8         0             Running     30d
```

---

## Диагностика и устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
|---|---|---|---|
| **HPA отображает `<unknown>` в столбце TARGETS** | 1. В контейнерах подов не объявлены `resources.requests`.<br>2. Сбой `metrics-server` или отказ APIService `v1beta1.metrics.k8s.io`. | `kubectl describe hpa <name>`<br>`kubectl get apiservice v1beta1.metrics.k8s.io`<br>`kubectl logs -n kube-system -l k8s-app=metrics-server` | 1. Добавить блок `resources.requests.cpu` в спецификацию контейнеров.<br>2. Проверить работу `metrics-server`, TLS-сертификаты и флаг `--kubelet-insecure-tls` (при необходимости). |
| **Поды зависают в состоянии `Pending`, узлы не добавляются** | 1. В On-Premise пуле Cluster API закончились свободные физические серверы/слоты VM.<br>2. Сбой сетевого взаимодействия с BMC/IPMI контроллерами.<br>3. Превышены лимиты `ResourceQuota` в namespace. | `kubectl describe pod <pending-pod>` (секция Events)<br>`kubectl get machines.cluster.x-k8s.io`<br>`kubectl describe resourcequota -n <ns>` | 1. Проверить логи Cluster Autoscaler и статус `MachineDeployment`.<br>2. Проверить доступность IPMI/Redfish в Metal3.<br>3. Скорректировать квоты неймспейса. |
| **Флаттеринг (Flapping / Thrashing): постоянные скачки числа реплик** | Слишком короткое окно стабилизации на уменьшение (`stabilizationWindowSeconds`) при волнообразном характере трафика. | Анализ графиков Prometheus:<br>`kube_deployment_status_replicas`<br>`rate(http_requests_total[1m])` | В блоке `behavior.scaleDown` установить `stabilizationWindowSeconds: 300` или `600`, ограничить шаг уменьшения через `policies` (`value: 1-2 pods`). |
| **VPA перезапускает поды во время пиковой нагрузки** | Установлен режим `updateMode: "Auto"` или `updateMode: "Recreate"`, а среда не поддерживает In-Place Resize. | `kubectl describe vpa <name>`<br>`kubectl get events --field-selector reason=EvictedByVPA` | 1. Перевести VPA в режим `updateMode: "InPlaceOrRecreate"`.<br>2. Убедиться, что Kubernetes $\ge 1.30$, Kubelet и containerd поддерживают In-Place Resize.<br>3. Настроить жесткий PDB для сервиса. |
| **Cluster Autoscaler не может сжать узел (Scale-Down Blocked)** | 1. На узле запущен под без PDB или с нарушенным PDB.<br>2. На узле запущен под с локальным хранилищем (`emptyDir`) без аннотации `safe-to-evict`.<br>3. На узле работает non-DaemonSet под из неймспейса `kube-system`. | `kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml`<br>Логи CA с фильтром по имени ноды | 1. Настроить адекватный PDB для приложений.<br>2. Добавить поду аннотацию `"cluster-autoscaler.kubernetes.io/safe-to-evict": "true"`. |
| **Бесконечный цикл конфликта GitOps (ArgoCD) и HPA** | В Git зафиксировано статическое значение `replicas`, а ArgoCD включен в режим автоматической синхронизации (`selfHeal`). | `argocd app diff <app-name>`<br>`kubectl get deployment <name> -o yaml \| grep replicas` | 1. Удалить строку `replicas` из манифеста в Git-репозитории.<br>2. В манифесте `Application` добавить секцию `ignoreDifferences` для `/spec/replicas` и указать `syncOptions: [RespectIgnoreDifferences=true]`. |

---

## Лучшие практики

### 1. Строгая дисциплина спецификации ресурсов (Resource Hygiene)
*   **Requests обязательны для 100% контейнеров:** И алгоритм HPA, и планировщик `kube-scheduler`, и симулятор Cluster Autoscaler принимают решения строго на основе `requests`. Поды без `requests` не масштабируются по процентам и создают риск перегрузки серверов (Noisy Neighbor).
*   **Корректный выбор целевой утилизации HPA:** Не устанавливайте целевой порог CPU на уровне 90–95%. Рекомендуемое значение для SRE — **60–70%**. Запас в 30–40% необходим для компенсации всплесков трафика во время холодного старта новых подов (пока работают JIT, инициализация пулов БД и прогрев кэшей).

### 2. Принцип асимметричного масштабирования (Behavior Tuning)
*   **Быстрый подъем (Aggressive Scale-Up):** Настраивайте `scaleUp.stabilizationWindowSeconds: 0`. Всплеск нагрузки должен гаситься добавлением подов без искусственных задержек.
*   **Консервативный спуск (Conservative Scale-Down):** Настраивайте `scaleDown.stabilizationWindowSeconds` не менее 300 секунд (для очередей и пакетных задач — 600 секунд). Ограничивайте максимальный темп сжатия (не более 10–20% реплик за шаг), чтобы избежать каскадных аварий при кратковременных просадках метрик.

### 3. Обязательное использование PodDisruptionBudget (PDB)
*   Для любого сервиса, масштабируемого через HPA или работающего в динамическом кластере, **обязателен PDB**.
*   VPA Updater и Cluster Autoscaler жестко соблюдают PDB через Eviction API. Настройка `minAvailable` или `maxUnavailable` защищает приложение от полной недоступности при сжатии кластера или плановом дренаже серверов.

### 4. Headroom-буфер для локальных дата-центров (On-Premise)
*   Поскольку добавление физических серверов по сети (PXE/Metal3) занимает 8–20 минут, эксплуатация On-Premise кластеров без буфера мощностей приводит к длительным простоям подов в `Pending`.
*   Используйте шаблон Headroom на базе низкоприоритетных `pause`-подов (`PriorityClass: -1`). Они мгновенно уступают место критичным сервисам при всплеске, а их вытеснение запускает фоновый ввод новых узлов.

### 5. Бесшовное завершение работы (Graceful Shutdown)
*   При горизонтальном масштабировании вниз поды регулярно уничтожаются.
*   Всегда конфигурируйте `terminationGracePeriodSeconds` (обычно 30–60с) и хук `preStop: exec: command: ["/bin/sh", "-c", "sleep 10"]`. Это дает время Ingress-контроллерам и балансировщикам (MetalLB/Cilium) исключить удаляемый под из пула эндпоинтов до того, как приложение закроет сокет.

### 6. Разделение зон ответственности HPA и VPA
*   Никогда не направляйте HPA и VPA на одну и ту же метрику (например, CPU).
*   Рекомендуемая модель совместной работы:
    *   HPA управляет количеством реплик по нагрузке (CPU или RPS).
    *   VPA работает в режиме `Off` для непрерывного формирования рекомендаций по `requests/limits`, либо в режиме `InPlaceOrRecreate` управляет исключительно оперативной памятью (исключая OOMKilled).

---

## Дополнительная информация

### Матрица совместимости механизмов автомасштабирования

| Компонент / Сценарий | HPA | VPA | KEDA | Cluster Autoscaler |
|---|---|---|---|---|
| **HPA** | — | Конфликт по CPU/RAM; допустим VPA по памяти или VPA Off | Полная синергия (KEDA управляет HPA) | Синергия (Pending поды от HPA будят CA) |
| **VPA** | См. выше | — | Синергия при разделении метрик | Синергия (VPA снижает overprovisioning) |
| **KEDA** | Управляет HPA | Синергия при разделении метрик | — | Синергия через вытеснение и Pending поды |
| **In-Place Resize** | Не зависит | Нативная поддержка (InPlaceOrRecreate) | Не зависит | Снижает потребность в добавлении узлов |
| **Cluster Autoscaler** | Синергия | Синергия | Синергия | — |

### Связанные документы базы знаний

*   [HPA: Архитектура и алгоритмы](HPA/hpa_concepts.md) — математический аппарат, циклы опроса и внутренняя логика.
*   [HPA: Расширенная настройка и behavior](HPA/hpa_advanced.md) — тонкая настройка политик масштабирования и стабилизации.
*   [VPA: Подробный архитектурный разбор](vpa_detailed.md) — компоненты Recommender, Updater, Admission Controller и алгоритмы рекомендаций.
*   [In-Place Pod Resize](in_place_pod_resize.md) — динамическая модификация cgroups без перезапуска контейнеров в Kubernetes 1.35+.
*   [KEDA: Концепции и архитектура](./keda/keda_concepts.md) — событийное масштабирование и Scale-to-Zero.
*   [Cluster Autoscaler: Архитектура и алгоритмы](cluster_autoscaler_detailed.md) — планировщик, симуляции, алгоритмы expander и scale-down.
*   [Autoscaling в On-Premise и Bare-Metal](on_premise_autoscaling.md) — специфика интеграции с Cluster API, Metal3, Ironic, vSphere и Headroom.
*   [Pod Disruption Budget (PDB)](pod_disruption_budget.md) — обеспечение непрерывности работы при выселении подов.
*   [Descheduler](descheduler.md) — дефрагментация и балансировка подов по узлам кластера.
*   [HPA, PriorityClass и Preemption](hpa_priority_preemption.md) — приоритеты и вытеснение при конкуренции за ресурсы.
*   [Масштабирование StatefulSet](statefulset_autoscaling.md) — управление репликами баз данных и очередей.
*   [GitOps и автомасштабирование](gitops_autoscaling.md) — разрешение конфликтов с ArgoCD и Flux.
*   [Алертинг и мониторинг автомасштабирования](alerting_monitoring.md) — метрики, дашборды и PrometheusRule.
*   [Управление размещением подов (Affinity/Anti-Affinity)](../Scheduling/affinity.md) — влияние топологии на масштабирование.
*   [Metrics Server и мониторинг](../MonitoringLogging/metrics-server.md) — инфраструктура сбора базовых метрик кластера.
