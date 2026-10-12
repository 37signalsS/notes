# Kueue: очереди и квоты для batch/AI-нагрузок

**Актуально для:** Kueue 0.19.x (API `kueue.x-k8s.io/v1beta2`)

## Определения

* **Kueue** — набор API и контроллер для очередей заданий (job queueing) в Kubernetes (проект kubernetes-sigs, CNCF). Это менеджер на уровне заданий: он решает, **когда** задание допускается к запуску (создаются поды) и **когда** оно останавливается (активные поды удаляются). Kueue работает как admission-контроллер **перед** планировщиком и не заменяет `kube-scheduler`.
* **ResourceFlavor** — кластерный объект, описывающий «вкус» ресурсов: профиль оборудования (например, ноды с GPU A100, ноды с GPU T4, spot-инстансы). Маппинг flavor на группу нод задаётся через метки нод (`nodeLabels`) или аннотации.
* **ClusterQueue** — кластерный объект, определяющий пул квот (CPU, memory, GPU, pods) для одного или нескольких `ResourceFlavor`. Единица разделения ресурсов между командами.
* **LocalQueue** — объект в namespace, «ручка» для пользователей: указывает на `ClusterQueue`. Пользователи не отправляют задания напрямую в `ClusterQueue`, а в `LocalQueue` своего namespace.
* **Workload** — объект, который Kueue создаёт из поддерживаемого API (Job, JobSet, RayJob, Kubeflow Trainer, LeaderWorkerSet, Pod и др.). Именно `Workload` проходит admission.
* **Admission** — процесс допуска `Workload` к запуску. Пока квота недоступна, задание удерживается в приостановленном состоянии (у Job — `suspend: true`), поды не создаются.
* **Cohort** — группа `ClusterQueue`, между которыми разрешено динамическое заимствование свободной квоты.
* **Gang scheduling** — паттерн «все или ничего»: задание запускается только когда одновременно доступны ресурсы под **все** его поды. Kueue реализует его через удержание задания в suspended-состоянии до момента admission.

---

## Основные концепции

### Как работает Kueue

```
Пользователь создаёт Job/JobSet с меткой kueue.x-k8s.io/queue-name: <local-queue>
        │
        ▼
Kueue (admission controller)
        │
        ├── Создаёт объект Workload, удерживает задание в suspend
        │
        ├── Проверяет квоту в LocalQueue → ClusterQueue → ResourceFlavor
        │    ├── Квота есть → admission: снимает suspend, поды создаются и планируются kube-scheduler
        │    └── Квоты нет → Workload ждёт в очереди (FIFO с учётом приоритета)
        │
        └── Задание завершено → квота освобождается, следующий Workload из очереди допускается
```

Ключевое отличие от «голого» Kubernetes: без Kueue поды создаются сразу и висят в `Pending`, flood-ом нагружая API-сервер и планировщик; с Kueue задания стоят в очереди **до** создания подов, а квоты контролируются явно.

### Квоты: nominalQuota, borrowingLimit, lendingLimit

В `ClusterQueue` для каждого ресурса flavor задаются:

* **`nominalQuota`** — гарантированный объём ресурса, доступный ClusterQueue в любой момент.
* **`borrowingLimit`** — максимум, который ClusterQueue может **заимствовать** из неиспользуемой nominalQuota других ClusterQueue того же cohort.
* **`lendingLimit`** — максимум, который ClusterQueue **одалживает** другим очередям cohort, когда сам не использует свою nominalQuota.

Fair sharing: если у ClusterQueue команды-B есть pending-нагрузка, а команда-A полностью использует свою nominalQuota, Kueue допустит нагрузку команды-B **раньше** новых заданий команды-A — гарантированная квота команды-B защищена.

### Выбор flavor и «дешёвые ресурсы первыми»

Kueue перебирает flavor в порядке их перечисления в `spec.resourceGroups[*].flavors` и выбирает **первый** flavor, в котором хватает свободной квоты (без заимствования и вытеснения). Это даёт простой механизм оптимизации в пользу недорогих ресурсов: перечислите сначала дешёвые flavor (например, spot-ноды или старые GPU), а дорогие — последними.

### Приоритеты и вытеснение

* **WorkloadPriorityClass** — кластерный объект Kueue, задающий приоритет `Workload` (аналог `PriorityClass` для подов, но на уровне заданий).
* При нехватке квоты высокоприоритетный `Workload` может **вытеснить** (preempt) уже запущенные низкоприоритетные задания в том же ClusterQueue/cohort (вытеснение включается конфигурацией ClusterQueue).

### Что поддерживается из коробки

* **Gang scheduling** для JobSet и других групповых API (задание не начинается, пока не влезет целиком).
* **Partial admission и dynamic reclaim** — запуск задания с уменьшённым параллелизмом на основе доступной квоты и освобождение квоты по мере завершения подов.
* **Topology-Aware Scheduling (TAS)** — размещение с учётом физической топологии (для распределённого обучения LLM).
* **MultiKueue** — диспетчеризация заданий между несколькими кластерами.
* **Mixing training and inference** — одновременное управление batch-заданиями и serving-нагрузкой (Deployments/StatefulSets).

---

## Предварительные требования

| Компонент | Требование |
|-----------|------------|
| Kubernetes | 1.29+ (официально поддерживается и тестируется на 1.34+) |
| Kueue | 0.19.x, API `kueue.x-k8s.io/v1beta2` |
| kubectl | настроен для целевого кластера |
| Интеграция с JobSet | установлен JobSet operator (см. [Job и CronJob](../Base/job.md)) |

---

## Практические сценарии

### Установка

```bash
# Установка последней release-версии
kubectl apply --server-side -f \
  https://github.com/kubernetes-sigs/kueue/releases/download/v0.19.6/manifests.yaml

# Ожидание готовности контроллера
kubectl wait deploy/kueue-controller-manager -n kueue-system \
  --for=condition=available --timeout=5m
# → deployment.apps/kueue-controller-manager condition met

# Или через Helm
helm install kueue oci://registry.k8s.io/kueue/charts/kueue \
  --version 0.19.6 --namespace kueue-system --create-namespace \
  --wait --timeout 300s
```

### Минимальная конфигурация: ResourceFlavor + ClusterQueue + LocalQueue

```yaml
# 1. Flavor: описывает тип оборудования (например, ноды с A100)
apiVersion: kueue.x-k8s.io/v1beta2
kind: ResourceFlavor
metadata:
  name: gpu-a100
spec:
  nodeLabels:
    accelerator: nvidia-a100   # ноды с такой меткой относятся к этому flavor
---
# 2. ClusterQueue: пул квот для flavor
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: ml-cluster-queue
spec:
  namespaceSelector: {}        # {} — все namespace; либо matchLabels для ограничения
  resourceGroups:
  - coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
    flavors:
    - name: gpu-a100
      resources:
      - name: "cpu"
        nominalQuota: 100
      - name: "memory"
        nominalQuota: 500Gi
      - name: "nvidia.com/gpu"
        nominalQuota: 8        # всего 8 GPU A100 в пуле
---
# 3. LocalQueue: очередь внутри namespace команды
apiVersion: kueue.x-k8s.io/v1beta2
kind: LocalQueue
metadata:
  namespace: team-ml
  name: team-ml-queue
spec:
  clusterQueue: ml-cluster-queue
```

### Запуск Job в очереди

Единственное изменение в манифесте задания — метка `kueue.x-k8s.io/queue-name`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: inference-job
  namespace: team-ml
  labels:
    kueue.x-k8s.io/queue-name: team-ml-queue   # ← маршрутизация в LocalQueue
spec:
  parallelism: 4
  completions: 4
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: inference
        image: my-registry/inference:latest
        resources:
          limits:
            nvidia.com/gpu: 1
```

Пока квота занята, Job остаётся с `SUSPEND`-флагом, поды не создаются:

```bash
kubectl get jobs -n team-ml
# → NAME            COMPLETIONS   DURATION   AGE
# → inference-job   0/4           5s         1m   # задание в очереди

kubectl get workloads -n team-ml
# → NAME                     QUEUE         RESERVED IN     ADMITTED   FINISHED
# → job-inference-job-xxxx   team-ml-queue ml-cluster-queue False      False
```

### JobSet + Kueue: gang scheduling для распределённого обучения

Kueue — штатный способ координировать запуск JobSet «все вместе или никого»: JobSet удерживается в suspend, пока ClusterQueue не сможет admits все реплики одновременно.

```yaml
apiVersion: jobset.x-k8s.io/v1alpha2
kind: JobSet
metadata:
  name: llm-training
  namespace: team-ml
  labels:
    kueue.x-k8s.io/queue-name: team-ml-queue
spec:
  replicatedJobs:
  - name: worker
    replicas: 4
    template:
      spec:
        parallelism: 1
        completions: 1
        template:
          spec:
            restartPolicy: Never
            containers:
            - name: trainer
              image: my-registry/trainer:latest
              resources:
                limits:
                  nvidia.com/gpu: 2   # 4 реплики × 2 GPU = 8 GPU целиком
```

Дополнительно можно передать управление Job внешнему контролеру через поле `managedBy` (GA в Job API v1.35): встроенный контроллер Job игнорирует такой Job, а Kueue управляет квотами и очередями.

### Разделение GPU между командами (несколько flavor)

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ResourceFlavor
metadata:
  name: gpu-t4
spec:
  nodeLabels:
    accelerator: nvidia-t4
---
apiVersion: kueue.x-k8s.io/v1beta2
kind: ResourceFlavor
metadata:
  name: gpu-a100
spec:
  nodeLabels:
    accelerator: nvidia-a100
---
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: shared-gpu-queue
spec:
  namespaceSelector: {}
  resourceGroups:
  - coveredResources: ["nvidia.com/gpu"]
    flavors:
    - name: gpu-t4          # дешёвый flavor первым — приоритет использования
      resources:
      - name: "nvidia.com/gpu"
        nominalQuota: 4
    - name: gpu-a100        # дорогой flavor — когда T4 не хватает
      resources:
      - name: "nvidia.com/gpu"
        nominalQuota: 8
```

Kueue сначала попробует разместить задание на T4, и только при нехватке квоты T4 — на A100. Порядок flavor = порядок предпочтения.

---

## Проверка работы (валидация)

```bash
# Состояние ClusterQueue: глубина очереди и допущенные задания
kubectl get clusterqueue ml-cluster-queue -o wide
# → NAME              COHORT   STRATEGY         PENDING WORKLOADS   ADMITTED WORKLOADS
# → ml-cluster-queue           BestEffortFIFO   2                   3

# LocalQueue в namespace
kubectl get localqueue -n team-ml
# → NAME          CLUSTERQUEUE       PENDING WORKLOADS   ADMITTED WORKLOADS
# → team-ml-queue ml-cluster-queue   1                   2

# Workload: admitted/finished-флаги
kubectl get workloads -n team-ml

# События admission-решений
kubectl describe workload <workload-name> -n team-ml

# Логи контроллера
kubectl logs -n kueue-system -l control-plane=controller-manager --tail=50
```

---

## Траблшутинг

| Симптом | Причина | Решение |
|---------|---------|---------|
| Workload вечно `ADMITTED=False` | Квота ClusterQueue исчерпана другими заданиями | `kubectl get clusterqueue` — проверить `PENDING/ADMITTED WORKLOADS`; увеличить `nominalQuota` или настроить cohort/borrowing |
| Задание не попадает в очередь | Нет метки `kueue.x-k8s.io/queue-name` или LocalQueue не существует в namespace задания | Проверить метку и `kubectl get localqueue -n <ns>`; LocalQueue namespace-scoped — он должен быть в том же namespace, что и задание |
| Flavor не подходит | Метки нод не совпадают с `spec.nodeLabels` flavor | `kubectl get nodes --show-labels` и сверить с `ResourceFlavor` |
| Preemption не срабатывает | Вытеснение не включено в конфигурации ClusterQueue или приоритеты равны | Настроить `preemption` в ClusterQueue и `WorkloadPriorityClass` |
| Job не suspend-ится | Поле `managedBy` установлено, но контроллер Kueue не управляет этим типом | Убедиться, что API задания поддерживается Kueue (Job, JobSet, RayJob, Kubeflow, Pod и др.) |

---

## Лучшие практики

* **Один LocalQueue на namespace команды**, все LocalQueue одной команды — на один или несколько ClusterQueue (общая квота с заимствованием или жёсткое разделение).
* **Размер квоты = реальной ёмкости**: пустая (неограниченная) квота превращает Kueue в «прозрачный» проход — очередь не работает.
* **Порядок flavor = экономия**: дешёвые/старые ресурсы первыми, дорогие последними.
* **Cohort для burst-нагрузки**: объединяйте ClusterQueue команд в cohort с `borrowingLimit`, чтобы простаивающая квота одной команды использовалась другой.
* **Gang scheduling через JobSet + Kueue** вместо самописных решений — комбинация значительно проще полноценного кастомного планировщика.
* **Регулярно пересматривайте квоты**: паттерны использования нагрузок меняются, квоты должны отражать текущую реальность.

---

## Дополнительная информация

### Ограничения

* Kueue — не планировщик: он решает **когда** задание запускается, но **куда** поды размещает `kube-scheduler` (или другой планировщик, например Volcano/KAI Scheduler).
* Вытеснение (preemption) по умолчанию выключено — включается явно в конфигурации ClusterQueue.
* API `v1beta1` deprecated; в новых установках используйте `kueue.x-k8s.io/v1beta2`.

### См. также

* [Job и CronJob (JobSet)](../Base/job.md) — групповые задания, интегрируемые с Kueue
* [Kube-scheduler](../Concepts/kube_scheduler.md) — стандартный планировщик, который размещает допущенные поды
* [Volcano для batch-нагрузок](../Autoscaling/on_premise_autoscaling.md#volcano-для-batch-нагрузок) — альтернативный подход (свой планировщик + очереди)
* [Apache YuniKorn](./yunikorn.md) — иерархические очереди и квоты
* [KAI Scheduler](./kai_scheduler.md) — topology-aware GPU-планирование
* [Обзор решений для планирования](./scheduling_solutions_overview.md) — матрица выбора
* [Официальная документация Kueue](https://kueue.sigs.k8s.io/)
