# Descheduler: автоматическая дефрагментация и ребалансировка кластера

**Актуально для:** Kubernetes 1.28–1.32+ / Descheduler v0.31.x–v0.32.x (API `descheduler/v1alpha2`)

## Определения

**Descheduler** — специализированный контроллер Kubernetes, периодически анализирующий текущее распределение запущенных подов по узлам и инициирующий их «вежливое» выселение (eviction) для исправления субоптимального или несбалансированного размещения. В отличие от `kube-scheduler`, который принимает решение о размещении пода однократно в момент его создания, Descheduler работает с уже функционирующими подами.

**Eviction API** — встроенный механизм Kubernetes API (`policy/v1`, ресурс `pods/eviction`), предназначенный для безопасного завершения работы подов. В отличие от принудительного удаления (`kubectl delete pod`), вызов Eviction API гарантирует соблюдение бюджетов доступности (`PodDisruptionBudget`, PDB) и возвращает ошибку `429 Too Many Requests` (или статус `Cannot evict pod as it would violate the pod's disruption budget`), если выселение нарушит минимально допустимое количество готовых реплик.

**DeschedulerPolicy** — конфигурационный ресурс (спецификация `descheduler/v1alpha2`), определяющий профили, глобальные лимиты выселений и параметры подключаемых плагинов (фильтров, стратегий выселения и балансировки).

**Extension Points (точки расширения)** — архитектурные этапы жизненного цикла Descheduler:
- `filter` / `preEvictionFilter` — предварительная фильтрация подов, определяющая их принципиальную пригодность к выселению (плагин `DefaultEvictor`).
- `deschedule` — последовательный аудит подов по жестким критериям несоответствия (нарушение taints, affinity, устаревание, частые перезапуски).
- `balance` — групповой анализ топологии и нагрузки кластера с выселением подов для выравнивания плотности или освобождения узлов.

**Voluntary Disruption (добровольное прерывание)** — контролируемый процесс вывода пода из эксплуатации по инициативе администратора или контроллера (включая `kubectl drain` и Descheduler).

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|---|---|---|---|
| Kubernetes | 1.25 | 1.28–1.32+ | Поддержка стабильного Eviction API `policy/v1` |
| Descheduler | v0.29.0 | v0.31.x / v0.32.x | Спецификация конфигурации `descheduler/v1alpha2` |
| Metrics Server | 0.6.0+ | 0.7.0+ | Необходим только при балансировке по реальной утилизации узлов |
| PodDisruptionBudget | `policy/v1` | `policy/v1` | PDB защищает критичные рабочие нагрузки от одновременного выселения |

### Проверка готовности кластера

```bash
# 1. Проверка версии сервера Kubernetes
kubectl version -o json | jq -r '.serverVersion.gitVersion'
# → v1.31.2

# 2. Проверка доступности суб-ресурса Eviction API
kubectl api-resources --api-group=policy
# → NAME                      SHORTNAMES   APIVERSION   NAMESPACED   KIND
# → poddisruptionbudgets      pdb          policy/v1    true         PodDisruptionBudget

# 3. Проверка доступности Metrics Server (при использовании реальных метрик)
kubectl top nodes
# → NAME           CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → k8s-worker-01  1420m        35%    12400Mi         38%
# → k8s-worker-02  3200m        80%    26500Mi         82%
# → k8s-worker-03  410m         10%    4100Mi          12%

# 4. Анализ текущего перекоса количества подов по узлам
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.nodeName != null) | .spec.nodeName' | sort | uniq -c | sort -rn
# → 48 k8s-worker-02
# → 22 k8s-worker-01
# →  6 k8s-worker-03
```

---

## Архитектура и принцип работы

### Причины деградации планирования

Стандартный планировщик `kube-scheduler` оценивает состояние кластера исключительно в момент появления непроинициализированного пода в очереди. В процессе дальнейшей эксплуатации кластер неизбежно накапливает перекосы:
- **Дрейф нагрузки и емкости:** добавление новых рабочих узлов не приводит к автоматическому переезду подов со старых утилизированных узлов на новые.
- **Масштабирование рабочих нагрузок:** HPA увеличивает количество реплик во время пика; после спада нагрузки и масштабирования вниз оставшиеся поды могут оказаться скученными на ограниченном числе серверов.
- **Изменение инфраструктурного контекста:** на узлы добавляются или удаляются метки (`node labels`) и ограничения (`taints`), однако уже запущенные поды продолжают работать, даже если более не удовлетворяют новым правилам.
- **Нарушение топологических ограничений:** после аварийных перезагрузок нод правила `PodTopologySpreadConstraints` и `podAntiAffinity` (особенно с мягкими условиями `preferredDuringSchedulingIgnoredDuringExecution`) перестают гарантировать равномерность.

### Жизненный цикл выселения и перепланирования

Descheduler **никогда не переназначает и не создает поды самостоятельно**. Он делегирует полный цикл создания и планирования штатным компонентам Kubernetes:

```
[ Descheduler ]
      │
      ├─ 1. Сканирует ноды и запущенные поды (kube-apiserver)
      ├─ 2. Фильтрация кандидатов (DefaultEvictor: nodeFit, minPodAge, annotations)
      ├─ 3. Выбор целевых подов стратегиями (balance / deschedule)
      ├─ 4. Проверка ограничений (Circuit Breakers: maxNoOfPodsToEvictTotal)
      │
      ▼
[ POST /api/v1/namespaces/{ns}/pods/{name}/eviction ]
      │
      ├─ 5. kube-apiserver проверяет PDB (disruptionsAllowed > 0)
      │     ├─ PDB нарушен  ──► HTTP 429: выселение отклонено, под пропускается
      │     └─ PDB соблюден ──► Запуск штатного Terminating (graceful shutdown)
      ▼
[ Workload Controller (Deployment/ReplicaSet/StatefulSet) ]
      │
      ├─ 6. Фиксирует нехватку активной реплики
      └─ 7. Создает новый под со статусом Pending
      ▼
[ kube-scheduler ]
      │
      └─ 8. Размещает новый под на оптимальном узле (с учетом текущего состояния)
```

### Модель плагинов и профилей (Extension Points)

Конфигурация Descheduler базируется на плагинной архитектуре:

| Плагин | Extension Point | Тип действия | Описание |
|---|---|---|---|
| `DefaultEvictor` | `filter`, `preEvictionFilter` | Фильтр | Базовый фильтр допустимости выселения (защита системных подов, учет PDB, проверка `nodeFit`, аннотаций, времени жизни). |
| `RemoveDuplicates` | `balance` | Балансировка | Выселяет дубликаты реплик одного Deployment/RS/StatefulSet с одного узла, если их там более одной. |
| `LowNodeUtilization` | `balance` | Балансировка | Находит недозагруженные и перегруженные узлы по порогам ресурсов (CPU, Memory, Pods) и выселяет поды с перегруженных на свободные. |
| `HighNodeUtilization` | `balance` | Консолидация | Уплотняет поды на меньшем числе узлов, освобождая остальные (актуально для энергоэффективности bare-metal и подготовки к обслуживанию). |
| `RemovePodsViolatingTopologySpreadConstraint` | `balance` | Балансировка | Выравнивает распределение подов по зонам/стойкам при нарушении допустимого перекоса `maxSkew`. |
| `RemovePodsViolatingInterPodAntiAffinity` | `deschedule` | Аудит соответствия | Выселяет поды, нарушающие правила взаимного отталкивания (`podAntiAffinity`). |
| `RemovePodsViolatingNodeAffinity` | `deschedule` | Аудит соответствия | Выселяет поды, переставшие удовлетворять `nodeAffinity` (`requiredDuringSchedulingIgnoredDuringExecution`). |
| `RemovePodsViolatingNodeTaints` | `deschedule` | Аудит соответствия | Выселяет поды, не имеющие `tolerations` для taints, добавленных на узел после запуска подов. |
| `RemovePodsHavingTooManyRestarts` | `deschedule` | Санация | Выселяет поды с чрезмерным числом перезапусков контейнеров (CrashLoopBackOff). |
| `PodLifeTime` | `deschedule` | Санация | Выселяет поды, чей возраст превысил `maxPodLifeTimeSeconds`. |
| `RemoveFailedPods` | `deschedule` | Санация | Удаляет поды в фазе `Failed` с заданными причинами или кодами возврата. |

> [!IMPORTANT]
> В официальном реестре плагинов Descheduler **отсутствуют** отдельные плагины с названиями `RemoveLowPriorityNodes` или `RemovePodsViolatingPodDisruptionBudget`. Приоритеты подов обрабатываются плагином `DefaultEvictor` через параметр `priorityThreshold`, а бюджеты PDB валидируются API-сервером через вызовы Eviction API.

### Режимы выполнения: CronJob vs Deployment vs Job

| Параметр | CronJob (Периодический запуск) | Deployment (Daemon-режим) | Standalone Job (Разовый запуск) |
|---|---|---|---|
| **Принцип работы** | Запуск по расписанию cron, выполнение одного цикла аудита и завершение. | Постоянно запущенный демон с таймером `--descheduling-interval`. | Однократный запуск администратором вручную. |
| **Отказоустойчивость** | Обеспечивается контроллером CronJob. | Требует `--leader-elect=true` при `replicas > 1`. | Разовое выполнение, нет HA. |
| **Мониторинг метрик** | Метрики Prometheus живут только во время работы пода. | Постоянно доступный endpoint `/metrics` для Prometheus Operator. | Только сбор логов. |
| **Рекомендация SRE** | **Рекомендуется** для предсказуемых регламентных окон и постепенной дефрагментации. | **Рекомендуется** при динамичных нагрузках и необходимости непрерывного экспорта метрик. | Применяется после масштабного ввода новых стоек/нод или аварий. |

---

## Конфигурация и практические сценарии

### Глобальные параметры политики (`DeschedulerPolicy`)

Спецификация верхнего уровня `descheduler/v1alpha2` содержит предохранители (circuit breakers), ограничивающие объем выселений за один прогон:

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
# Ограничение узлов, попадающих под обработку
nodeSelector: "node-role.kubernetes.io/worker="
# Предохранители максимального количества выселений за один запуск:
maxNoOfPodsToEvictPerNode: 3          # Максимум с одного узла
maxNoOfPodsToEvictPerNamespace: 10    # Максимум из одного namespace
maxNoOfPodsToEvictTotal: 25           # Суммарно по всему кластеру
# Таймаут принудительного завершения подов при выселении
gracePeriodSeconds: 30
```

### Конфигурация фильтра `DefaultEvictor`

Плагин `DefaultEvictor` является обязательным барьером безопасности перед выселением любого пода:

```yaml
pluginConfig:
- name: "DefaultEvictor"
  args:
    # КРИТИЧЕСКИ ВАЖНО: проверять возможность планировщика разместить под на другом узле ПЕРЕД выселением
    nodeFit: true
    # Минимальный возраст пода перед выселением (защита от циклического перезапуска свежих подов)
    minPodAge: 5m
    # Игнорировать выселение, если в наборе контроллера осталось слишком мало реплик
    minReplicas: 2
    # Порог приоритета: поды с приоритетом >= указанного НЕ выселяются
    priorityThreshold:
      value: 1000000 # Либо имя: priorityThreshold: { name: "high-priority" }
    # Управление встроенными защитами подов (podProtections)
    podProtections:
      # Отключение дефолтных защит (разрешение выселения специфичных типов):
      defaultDisabled:
        - "PodsWithLocalStorage"  # Разрешить выселение подов с emptyDir/hostPath
      # Включение дополнительных защит:
      defaultEnabled:
        - "PodsWithoutPDB"        # Запретить выселение подов, у которых не объявлен PDB
```

---

### Сценарий 1: Ребалансировка нагрузки порогом использования узлов (`LowNodeUtilization`)

**Задача:** в кластере на bare-metal серверах поды распределены неравномерно. Некоторые узлы загружены по CPU/памяти более чем на 75%, тогда как вновь добавленные ноды простаивают (загрузка < 20%).

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
maxNoOfPodsToEvictTotal: 20
maxNoOfPodsToEvictPerNode: 4
profiles:
  - name: RebalanceLowUtilization
    pluginConfig:
      - name: "DefaultEvictor"
        args:
          nodeFit: true
          minPodAge: 10m
          minReplicas: 2
      - name: "LowNodeUtilization"
        args:
          # Пороги, ниже которых узел считается недозагруженным (приемник подов)
          thresholds:
            cpu: 25
            memory: 30
            pods: 20
          # Пороги, выше которых узел считается перегруженным (источник выселения)
          targetThresholds:
            cpu: 75
            memory: 80
            pods: 70
          # Ресурсные метрики: по умолчанию анализируются requests подов.
          # Для учета реальной утилизации требуется подключение Metrics Server:
          useDeviationThresholds: false
    plugins:
      balance:
        enabled:
          - "LowNodeUtilization"
```

> [!WARNING]
> Разница между `thresholds` и `targetThresholds` должна составлять не менее 20–30%. Если установить слишком узкий коридор (например, нижний 45%, верхний 55%), возникнет **флаппинг** — поды будут циклически мигрировать между узлами туда и обратно.

---

### Сценарий 2: Дефрагментация стоек и зон (`TopologySpreadConstraint` и `AntiAffinity`)

**Задача:** после аварии электропитания в одной из серверных стоек поды были перенесены планировщиком на оставшиеся стойки. После возврата стойки в строй поды не распределились автоматически, нарушая `maxSkew`.

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
profiles:
  - name: TopologyAndAffinityHealing
    pluginConfig:
      - name: "DefaultEvictor"
        args:
          nodeFit: true
          minPodAge: 5m
      - name: "RemovePodsViolatingTopologySpreadConstraint"
        args:
          includeSoftConstraints: true # Учитывать preferred правила ScheduleAnyway
      - name: "RemoveDuplicates"
        args:
          excludeOwnerKinds:
            - "StatefulSet" # Исключить StatefulSet из дедупликации
    plugins:
      deschedule:
        enabled:
          - "RemovePodsViolatingInterPodAntiAffinity"
          - "RemovePodsViolatingNodeAffinity"
          - "RemovePodsViolatingNodeTaints"
      balance:
        enabled:
          - "RemovePodsViolatingTopologySpreadConstraint"
          - "RemoveDuplicates"
```

---

### Сценарий 3: Санация кластера (очистка битых подов и зависших контейнеров)

**Задача:** периодическое удаление подов с циклическими падениями (`CrashLoopBackOff`, ошибки монтирования конфигураций), а также зависших подов со статусом `Failed`.

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
profiles:
  - name: ClusterSanitization
    pluginConfig:
      - name: "DefaultEvictor"
        args:
          nodeFit: false # Для удаления мусорных подов проверка nodeFit не требуется
      - name: "RemovePodsHavingTooManyRestarts"
        args:
          podRestartThreshold: 10
          includingInitContainers: true
      - name: "RemoveFailedPods"
        args:
          reasons:
            - "CrashLoopBackOff"
            - "ImagePullBackOff"
            - "CreateContainerConfigError"
          minPodLifetimeSeconds: 1800 # Под должен быть старше 30 минут
          excludeOwnerKinds:
            - "Job" # Завершенные Job не выселяются
    plugins:
      deschedule:
        enabled:
          - "RemovePodsHavingTooManyRestarts"
          - "RemoveFailedPods"
```

---

## Развертывание в кластере

### Способ 1: Установка через официальный Helm-чарт

```bash
# 1. Подключение репозитория
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm repo update

# 2. Создание файла переопределения параметров values.yaml
cat << 'EOF' > descheduler-values.yaml
kind: Deployment
replicas: 2
leaderElection:
  enabled: true

image:
  repository: registry.k8s.io/descheduler/descheduler
  tag: v0.32.0

cmdOptions:
  v: 3
  descheduling-interval: 10m
  dry-run: false

serviceMonitor:
  enabled: true
  insecureSkipVerify: true

deschedulerPolicy:
  apiVersion: "descheduler/v1alpha2"
  kind: "DeschedulerPolicy"
  maxNoOfPodsToEvictTotal: 30
  profiles:
    - name: DefaultProfile
      pluginConfig:
        - name: "DefaultEvictor"
          args:
            nodeFit: true
            minPodAge: 5m
            minReplicas: 2
        - name: "RemoveDuplicates"
        - name: "LowNodeUtilization"
          args:
            thresholds:
              cpu: 20
              memory: 20
              pods: 20
            targetThresholds:
              cpu: 70
              memory: 70
              pods: 60
      plugins:
        deschedule:
          enabled:
            - "RemovePodsViolatingNodeTaints"
            - "RemovePodsViolatingNodeAffinity"
        balance:
          enabled:
            - "RemoveDuplicates"
            - "LowNodeUtilization"
EOF

# 3. Установка релиза
helm upgrade --install descheduler descheduler/descheduler \
  --namespace kube-system \
  -f descheduler-values.yaml
# → Release "descheduler" has been upgraded. Happy Helming!

# 4. Проверка статуса подов
kubectl get pods -n kube-system -l app.kubernetes.io/name=descheduler
# → NAME                           READY   STATUS    RESTARTS   AGE
# → descheduler-7b89f5bc8c-k4m2p   1/1     Running   0          45s
# → descheduler-7b89f5bc8c-v8x1q   1/1     Running   0          45s
```

### Способ 2: Развертывание как CronJob манифестами Kubernetes

#### RBAC и права доступа (`descheduler-rbac.yaml`)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: descheduler-sa
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: descheduler-cluster-role
rules:
  - apiGroups: ["events.k8s.io", ""]
    resources: ["events"]
    verbs: ["create", "update"]
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get", "watch", "list"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "watch", "list"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "watch", "list"]
  - apiGroups: ["apps"]
    resources: ["daemonsets", "deployments", "replicasets", "statefulsets"]
    verbs: ["get", "watch", "list"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "watch", "list"]
  - apiGroups: ["scheduling.k8s.io"]
    resources: ["priorityclasses"]
    verbs: ["get", "watch", "list"]
  # Разрешение на вызов Eviction sub-resource для подов
  - apiGroups: [""]
    resources: ["pods/eviction"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: descheduler-cluster-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io/v1
  kind: ClusterRole
  name: descheduler-cluster-role
subjects:
  - kind: ServiceAccount
    name: descheduler-sa
    namespace: kube-system
```

#### Манифест CronJob (`descheduler-cronjob.yaml`)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: descheduler-policy-config
  namespace: kube-system
data:
  policy.yaml: |
    apiVersion: "descheduler/v1alpha2"
    kind: "DeschedulerPolicy"
    maxNoOfPodsToEvictTotal: 15
    profiles:
      - name: ScheduledRebalance
        pluginConfig:
          - name: "DefaultEvictor"
            args:
              nodeFit: true
              minPodAge: 5m
              minReplicas: 2
          - name: "RemoveDuplicates"
          - name: "LowNodeUtilization"
            args:
              thresholds:
                cpu: 20
                memory: 25
                pods: 20
              targetThresholds:
                cpu: 65
                memory: 70
                pods: 60
        plugins:
          balance:
            enabled:
              - "RemoveDuplicates"
              - "LowNodeUtilization"
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: descheduler-cronjob
  namespace: kube-system
spec:
  schedule: "*/30 * * * *"  # Запуск каждые 30 минут
  concurrencyPolicy: Forbid # Запретить параллельные запуски двух задач
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
            app.kubernetes.io/name: descheduler
        spec:
          serviceAccountName: descheduler-sa
          restartPolicy: Never
          containers:
            - name: descheduler
              image: registry.k8s.io/descheduler/descheduler:v0.32.0
              args:
                - --policy-config-file=/policy/policy.yaml
                - --v=3
              resources:
                requests:
                  cpu: 100m
                  memory: 128Mi
                limits:
                  cpu: 500m
                  memory: 512Mi
              volumeMounts:
                - name: policy-volume
                  mountPath: /policy
          volumes:
            - name: policy-volume
              configMap:
                name: descheduler-policy-config
```

---

## Операции, мониторинг и валидация

### Валидация в режиме симуляции (Dry-Run)

Перед применением новых агрессивных политик на production-кластере необходимо выполнить аудит в режиме симуляции:

```bash
# Ручной запуск Job с флагом --dry-run
kubectl run descheduler-dry-run \
  --namespace kube-system \
  --image=registry.k8s.io/descheduler/descheduler:v0.32.0 \
  --restart=Never \
  --overrides='{
    "spec": {
      "serviceAccountName": "descheduler-sa",
      "containers": [{
        "name": "descheduler",
        "image": "registry.k8s.io/descheduler/descheduler:v0.32.0",
        "args": ["--policy-config-file=/policy/policy.yaml", "--dry-run", "--v=3"],
        "volumeMounts": [{"name": "policy-vol", "mountPath": "/policy"}]
      }],
      "volumes": [{"name": "policy-vol", "configMap": {"name": "descheduler-policy-config"}}]
    }
  }'

# Просмотр логов аудита
kubectl logs -n kube-system descheduler-dry-run
# → I1012 18:40:02.120034 1 descheduler.go:182] "Executing in dry run mode, no pods will be evicted"
# → I1012 18:40:02.341102 1 lownodeutilization.go:195] "Node k8s-worker-02 is overutilized: cpu 78% > 70%"
# → I1012 18:40:02.345890 1 evictions.go:142] "Evicting pod (dry run)" pod="billing/payment-service-59695d7f7-r9m4l" reason="LowNodeUtilization"

# Удаление временного пода
kubectl delete pod descheduler-dry-run -n kube-system
# → pod "descheduler-dry-run" deleted
```

### Мониторинг метрик Prometheus

Descheduler в режиме Deployment отдает метрики в формате OpenMetrics/Prometheus через защищенный HTTPS-порт `10258`:

```bash
# Проверка доступности метрик через curl внутри пода
kubectl exec -n kube-system deploy/descheduler -- curl -k -s https://127.0.0.1:10258/metrics | grep "descheduler_"
# → # HELP descheduler_pods_evicted_total Total number of pods evicted by strategy
# → # TYPE descheduler_pods_evicted_total counter
# → descheduler_pods_evicted_total{namespace="billing",result="success",strategy="LowNodeUtilization"} 14
# → descheduler_pods_evicted_total{namespace="core",result="success",strategy="RemoveDuplicates"} 3
# → descheduler_pods_evicted_total{namespace="logging",result="failed",strategy="LowNodeUtilization"} 2
```

Ключевые метрики для настройки алертов SRE:
- `descheduler_pods_evicted_total` — счетчик выселений с лейблами `strategy`, `namespace`, `result` (`success` / `failed`).
- `descheduler_eviction_attempts_total` — общее число попыток инициации выселения.

### Управление выселением через аннотации подов

Инженеры эксплуатации и разработчики сервисов могут тонко регулировать поведение Descheduler на уровне конкретных подов с помощью аннотаций в `spec.template.metadata.annotations`:

```yaml
metadata:
  annotations:
    # 1. Запретить выселение пода любыми политиками Descheduler (жесткий запрет)
    descheduler.alpha.kubernetes.io/safe-to-evict: "false"

    # 2. Мягкая рекомендация избегать выселения пода, пока есть другие кандидаты
    descheduler.alpha.kubernetes.io/prefer-no-eviction: "true"
```

### Аудит событий в кластере

```bash
# Поиск событий выселения, инициированных Descheduler
kubectl get events -A --field-selector reason=Evicted -o wide
# → NAMESPACE   LAST SEEN   TYPE      REASON    OBJECT                          MESSAGE
# → billing     3m          Normal    Evicted   pod/payment-service-59695d7f7   Evicted by Descheduler: LowNodeUtilization

# Проверка статуса PDB и оставшихся разрешенных сбоев
kubectl get pdb -A
# → NAMESPACE   NAME          MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → billing     payment-pdb   2               N/A               1                     14d
```

### Удаление компонентов Descheduler

```bash
# Удаление при развертывании через Helm
helm uninstall descheduler -n kube-system
# → release "descheduler" uninstalled

# Удаление при развертывании через манифесты
kubectl delete cronjob descheduler-cronjob -n kube-system
kubectl delete configmap descheduler-policy-config -n kube-system
kubectl delete clusterrolebinding descheduler-cluster-binding
kubectl delete clusterrole descheduler-cluster-role
kubectl delete serviceaccount descheduler-sa -n kube-system
```

---

## Диагностика и устранение неполадок

| Проблема | Диагностика | Первопричина | Способ устранения |
|---|---|---|---|
| **Поды не выселяются при явном перекосе** | В логах: `0 pods evicted` или статус пропуска кандидатов. | Плагины не добавлены в секцию `enabled` соответствующей точки расширения (`balance` / `deschedule`), либо пороги загрузки не пересечены. | Проверить секцию `plugins.balance` и `plugins.deschedule` в политике. Убедиться, что имена плагинов написаны корректно. |
| **Ошибка API 429 Too Many Requests при выселении** | В логах Descheduler: `Cannot evict pod as it would violate the pod's disruption budget`. | PDB сервиса блокирует выселение: поле `ALLOWED DISRUPTIONS = 0` (реплики еще не готовы или их число минимально). | Штатное поведение. Если PDB завис из-за нездорового пода, настроить `unhealthyPodEvictionPolicy: AlwaysAllow` в спецификации PDB. |
| **Выселенные поды зависают в статусе Pending** | Поды выселяются, новые поды создаются контроллером, но не могут запуститься на других узлах. | Отключена опция `nodeFit: true` в плагине `DefaultEvictor`. Планировщик не может найти узел с достаточными ресурсами/подходящими taints. | Всегда включать `nodeFit: true` в `DefaultEvictor`. Настроить `minPodAge: 5m` для предотвращения каскадных сбоев. |
| **Флаппинг подов (постоянная миграция между нодами)** | Поды циклически выселяются каждые 15–30 минут между одними и теми же узлами. | Разница между `thresholds` и `targetThresholds` в `LowNodeUtilization` слишком мала (менее 15–20%). | Расширить зазор: например, нижний порог CPU установить в 25%, верхний — в 75%. Увеличить `minPodAge` до 15m. |
| **Descheduler падает с ошибкой доступа RBAC** | Ошибка в логах: `pods "xxx" is forbidden: User cannot create resource "pods/eviction"`. | У ServiceAccount отсутствуют права на `create` для суб-ресурса `pods/eviction` в API-группе `""`. | Добавить в `ClusterRole` правило для ресурса `pods/eviction` с глаголом `create`. |
| **Конфликтные гонки с HPA** | Descheduler выселяет поды, HPA в этот момент фиксирует рост метрик и начинает scale-up. | Периоды стабилизации HPA не согласованы с периодичностью запуска Descheduler. | Настроить в HPA `behavior.scaleDown.stabilizationWindowSeconds: 300` и запускать Descheduler не чаще 1 раза в 20–30 минут. |

---

## Лучшие практики для DevOps и SRE

1. **Всегда включайте предварительную симуляцию планирования (`nodeFit: true`)**:
   Без этого флага Descheduler выселяет под вслепую. Если свободных ресурсов в кластере нет или ограничения affinity препятствуют запуску, выселенный под застрянет в `Pending`, создавая искусственный инцидент доступности.

2. **Защищайте критичные сервисы и одиночные реплики**:
   - Устанавливайте `minReplicas: 2` (или выше) в `DefaultEvictor`, чтобы исключить выселение подов нереплицированных сервисов.
   - Используйте системные `PriorityClass` и ограничивайте порог выселения через `priorityThreshold`.
   - Для StatefulSet с локальными дисками используйте аннотацию `descheduler.alpha.kubernetes.io/safe-to-evict: "false"`.

3. **Соблюдайте безопасную дельту порогов утилизации**:
   При настройке `LowNodeUtilization` диапазон между недогруженным узлом (`thresholds`) и перегруженным (`targetThresholds`) должен быть не менее 25–30 процентных пунктов.

4. **Ограничивайте суммарную интенсивность выселений**:
   Всегда определяйте параметры `maxNoOfPodsToEvictTotal` и `maxNoOfPodsToEvictPerNode`. Выселение сотен подов одновременно создает всплеск нагрузки на etcd, kube-apiserver, сеть и registry образов.

5. **Координация с Horizontal Pod Autoscaler (HPA)**:
   При использовании метрик утилизации CPU/Memory для балансировки пороговые значения `targetThresholds` Descheduler должны быть согласованы с целевыми значениями HPA `averageUtilization` (порог Descheduler должен быть выше целевого порога HPA, чтобы не выселять поды, которые HPA планирует масштабировать).

6. **Тестирование через `--dry-run`**:
   Любая новая конфигурация политик должна работать в режиме `--dry-run` минимум сутки в staging-окружении для оценки журналов аудита перед включением боевого режима.

---

## Дополнительная информация

### Ограничения технологии

- Descheduler не производит планирование подов и не гарантирует, куда именно `kube-scheduler` разместит новую реплику.
- Descheduler не переносит состояние памяти (state) контейнеров; приложения должны корректно обрабатывать сигналы `SIGTERM` и штатный graceful shutdown.
- Выселение подов с локальными постоянными томами (`HostPath`, локальные PV) может привести к невозможности запуска на другом узле, если volume привязан к конкретному диску.

### См. также

- [Бюджет прерывания подов (PDB)](pod_disruption_budget.md) — защита сервисов от потери доступности при выселении
- [Управление размещением подов (Affinity, Anti-Affinity, TSC)](../Scheduling/affinity.md) — механизмы распределения, которые корректирует Descheduler
- [Планировщик Kubernetes (kube-scheduler)](../Concepts/kube_scheduler.md) — алгоритмы фильтрации и скоринга стандартного планировщика
- [Обслуживание узлов и drain](../Operations/node_maintenance.md) — плановый вывод узлов из эксплуатации через Eviction API
- [Cluster Autoscaler: детальный разбор](cluster_autoscaler_detailed.md) — взаимодействие Descheduler с автомасштабированием узлов
- [HPA: Продвинутые темы](HPA/hpa_advanced.md) — устранение взаимных конфликтов масштабирования и балансировки
