# Изменение ресурсов подов без перезапуска (In-Place Pod Resize)

**Актуально для:** Kubernetes 1.33+ (Beta) / 1.35+ (GA)

Механизм In-Place Pod Resize (KEP-1287) позволяет изменять запросы (`requests`) и лимиты (`limits`) вычислительных ресурсов (CPU, память) для работающих контейнеров без пересоздания подов и без перезапуска процессов PID 1. Это фундаментальный механизм вертикального масштабирования в Kubernetes, критически важный для обеспечения непрерывной доступности stateful-сервисов, распределенных баз данных, кэшей и нагрузок с длительным временем инициализации в on-premise и bare-metal инфраструктуре.

---

## Определения

* **In-Place Pod Resize (KEP-1287)** — встроенный механизм ядра Kubernetes, позволяющий модифицировать параметры CPU и памяти контейнера «на лету» через прямое обновление контроллеров `cgroups v2` на уровне Container Runtime Interface (CRI).
* **Подресурс `/resize` (Resize Subresource)** — специализированный REST API эндпоинт (`/api/v1/namespaces/{ns}/pods/{name}/resize`), через который разрешено изменять `spec.containers[].resources`, `spec.initContainers[].resources` (для сайдкаров) и `resizePolicy` работающего пода. Начиная с Kubernetes 1.33+ (Beta), прямое изменение ресурсов через основной эндпоинт пода запрещено валидатором API.
* **resizePolicy** — массив правил в спецификации контейнера (`spec.containers[].resizePolicy`), определяющий стратегию Kubelet при получении новых значений ресурсов: применить без прерывания (`NotRequired`) или принудительно перезапустить процесс контейнера (`RestartContainer`).
* **Четыре состояния ресурсов (Resource States)** — сквозная модель учета ресурсов в Kubelet:
  1. *Desired* — целевые ресурсы, запрошенные пользователем или контроллером (`spec.containers[].resources`).
  2. *Allocated* — ресурсы, допущенные Kubelet на узле к выделению (`status.containerStatuses[].allocatedResources`).
  3. *Actuated* — параметры, фактически переданные Kubelet в рантайм через CRI и сохраненные в локальном чекпоинте узла.
  4. *Actual* — текущие лимиты, вычитанные рантаймом напрямую из контроллеров cgroups (`status.containerStatuses[].resources`).
* **Pod Conditions ресайза** — стандартные условия статуса пода в Kubernetes 1.33+:
  - `PodResizePending` — запрос принят, но ресурсы еще не выделены узлом. Причины: `Deferred` (временная нехватка емкости узла) или `Infeasible` (невозможно удовлетворить в принципе).
  - `PodResizeInProgress` — Kubelet передал команду в CRI и ожидает применения cgroups. При ошибке рантайма выставляет причину `Error`.
* **status.resize (Legacy)** — поле статуса пода в Kubernetes 1.27–1.32 (Alpha), принимавшее значения `Proposed`, `InProgress`, `Infeasible`, `Deferred`. В ветке 1.33+ объявлено устаревшим в пользу Pod Conditions.
* **Cgroup v2** — объединенная иерархия контроллеров ядра Linux (`cpu.max`, `cpu.weight`, `memory.max`, `memory.min`), обеспечивающая атомарное и бесконфликтное изменение лимитов ресурсов без зависаний подсистемы управления памятью.

---

## Архитектура и принцип работы

### Сквозной жизненный цикл транзакции ресайза

Процесс изменения ресурсов без перезапуска строго упорядочен и проходит через несколько уровней абстракции кластера:

```
[Пользователь / VPA]
       │
       ▼ (PATCH /api/v1/namespaces/{ns}/pods/{name}/resize)
┌──────────────┐       1. Валидация: QoS неизменен, LimitRange, Quota
│  API-Server  │───────► Установка PodResizePending
└──────────────┘
       │
       ▼ (Node Watch)
┌──────────────┐       2. Проверка NodeAllocatable и свободной емкости
│   Kubelet    │───────► Если ресурсов нет: Deferred или Infeasible
└──────────────┘       3. Ресурсы есть: фиксация в allocatedResources
       │
       ▼ (Flow Control: двухфазный вызов CRI API)
┌──────────────┐       4. Увеличение: сначала Pod cgroup, затем Container
│  Containerd  │          Уменьшение: сначала Container, затем Pod cgroup
│   / CRI-O    │───────► Запись в cgroupfs (/sys/fs/cgroup/...)
└──────────────┘
       │
       ▼
┌──────────────┐       5. Kubelet читает cgroupfs, обновляет status.resources
│  Pod Status  │───────► Снятие условий PodResizePending и PodResizeInProgress
└──────────────┘
```

1. **Запрос к API:** Клиент отправляет PATCH-запрос к подресурсу `/resize` пода. API-сервер проверяет права RBAC, соответствие правилам `LimitRange` и валидирует, что запрос не нарушает неизменность класса обслуживания QoS.
2. **Kubelet Admission:** Kubelet получает обновление объекта через informer. Менеджер распределения ресурсов (`AllocationManager`) Kubelet проверяет доступную емкость узла (`NodeAllocatable` за вычетом уже выделенных `allocatedResources` всех остальных подов).
3. **Обработка нехватки емкости:**
   - Если увеличение `requests` превышает физическую емкость узла — выставляется условие `PodResizePending` с причиной `Infeasible`. Запрос бракуется навсегда.
   - Если емкость узла достаточна, но временно занята другими подами — выставляется `PodResizePending` с причиной `Deferred`. Kubelet регулярно перепроверяет возможность применения при освобождении ресурсов.
4. **Применение через CRI (Двухфазный Flow Control):**
   При наличии емкости Kubelet применяет изменения через Container Runtime Interface с соблюдением строгой очередности:
   - **При увеличении ресурсов (Scale-Up):** Kubelet сначала расширяет лимиты cgroup на уровне песочницы пода (`UpdatePodSandboxResources`), а затем увеличивает лимиты конкретного контейнера (`UpdateContainerResources`). Это предотвращает немедленный троттлинг или OOMKill контейнера родительской cgroup пода.
   - **При уменьшении ресурсов (Scale-Down):** Сначала зажимаются лимиты cgroup контейнера (`UpdateContainerResources`), и только после подтверждения рантайма ужимается родительская cgroup пода (`UpdatePodSandboxResources`).
5. **Финализация:** Kubelet считывает фактические значения из cgroups через вызов `ContainerStatus`, записывает их в `status.containerStatuses[].resources`, актуализирует `allocatedResources` и удаляет флаги `PodResizePending` / `PodResizeInProgress`.

### Приоритеты обработки запросов на узле

Если на узле одновременно конкурируют несколько запросов на изменение ресурсов, Kubelet выстраивает внутреннюю очередь согласно приоритетам:

1. **Операции без увеличения `requests`:** Запросы, в которых меняются только `limits` (любого знака) либо уменьшаются `requests`, применяются в первую очередь, так как они гарантированно не требуют дополнительной емкости узла.
2. **PriorityClass пода:** Среди запросов на увеличение `requests` первыми удовлетворяются поды с наивысшим числовым значением `priority`.
3. **Класс обслуживания QoS:** При равном PriorityClass приоритет отдается классу `Guaranteed` перед `Burstable`. Поды `BestEffort` не имеют requests и не участвуют в распределении гарантированной емкости.

### Неизменность класса обслуживания (QoS Class Immutability)

Класс QoS (`Guaranteed`, `Burstable`, `BestEffort`) рассчитывается API-сервером исключительно в момент создания пода на основе соотношения `requests` и `limits` всех его контейнеров.

* **Архитектурное правило:** Класс QoS пода **не может измениться** в течение его жизненного цикла.
* Если под был создан как `Burstable` (например, `requests.cpu: 500m`, `limits.cpu: 1000m`), попытка установить через `/resize` равные значения `requests.cpu: 1000m` и `limits.cpu: 1000m` **будет отклонена API-сервером** с ошибкой валидации, так как это означало бы смену класса на `Guaranteed`.
* Неизменность QoS защищает планировщик (`kube-scheduler`) и механизм вытеснения при дефиците памяти (`kubelet eviction manager`) от рассинхронизации приоритетов OOM-score.

### Механизм управления перезапуском (resizePolicy)

Спецификация контейнера позволяет гибко разграничить реакцию на изменение разных типов ресурсов:

```yaml
spec:
  containers:
  - name: backend
    resizePolicy:
      - resourceName: cpu
        restartPolicy: NotRequired       # Динамически через cgroup cpu.max / cpu.weight
      - resourceName: memory
        restartPolicy: RestartContainer  # Перезапуск PID 1 для пересчета Heap
```

| Политика | Поведение Kubelet | Рекомендуемая область применения |
| :--- | :--- | :--- |
| **`NotRequired`** *(по умолчанию)* | Обновление cgroupfs без остановки процессов контейнера. | CPU для любых языков; память для Go, Python, Node.js, C/Rust. |
| **`RestartContainer`** | Перезапуск конкретного контейнера с новыми параметрами без пересоздания пода и сетевого namespace. | Память для Java (JVM до 17), СУБД с жесткими статическими пулами буферов. |

**Правило старшинства политик:** Если в одном запросе одновременно обновляются CPU (`NotRequired`) и память (`RestartContainer`), Kubelet отдает безусловный приоритет политике `RestartContainer` — контейнер будет перезапущен.

### Взаимодействие с контроллерами верхнего уровня (Deployment, StatefulSet)

Критически важный аспект архитектуры для DevOps и SRE инженеров:

* Контроллеры `Deployment`, `StatefulSet` и `DaemonSet` отслеживают хэш шаблона спецификации пода (`pod-template-hash`).
* Прямое изменение `spec.template.spec.containers[].resources` в манифесте Deployment **не выполняет In-Place Resize**. Контроллер воспринимает это как изменение шаблона, создает новый `ReplicaSet` и запускает штатный Rolling Update с пересозданием всех подов.
* Выполнение In-Place Resize для рабочих нагрузок Deployment/StatefulSet без роллинга реализуется исключительно через **Vertical Pod Autoscaler (VPA)** в режиме `updateMode: InPlaceOrRecreate` или через внешние операторы, которые отправляют PATCH-запросы напрямую к объектам Pod через подресурс `/resize`.

### Ограничения технологии

| Категория | Поддерживается | Не поддерживается / Ограничено |
| :--- | :--- | :--- |
| **Ресурсы** | CPU (`requests`, `limits`), Память (`requests`, `limits`). | Ephemeral Storage (`requests/limits`), HugePages, Extended Resources (GPU, FPGA, SR-IOV). |
| **Менеджеры Kubelet** | Стандартные политики: `cpuManagerPolicy: none`, `memoryManagerPolicy: None`. | Статическая изоляция ядер `cpuManagerPolicy: static` (Guaranteed поды завершаются со статусом `Infeasible`). |
| **Контейнеры** | Обычные контейнеры приложений; Sidecar-контейнеры (initContainers с `restartPolicy: Always`). | Стандартные однократные Init-контейнеры; Ephemeral-контейнеры (`kubectl debug`). |
| **Типы подов** | Поды, управляемые планировщиком (ReplicaSet, StatefulSet, Job). | Статические поды Kubelet (`/etc/kubernetes/manifests`); поды с активным swap (`NodeSwap`). |

---

## Предварительные требования и настройка

### Совместимость компонентов платформы

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Kubernetes Control Plane** | 1.33+ (Beta) | 1.35+ (GA) | В 1.33+ включен по умолчанию. В 1.27–1.32 требовал feature gate `InPlacePodVerticalScaling`. |
| **Kubelet** | 1.33+ | 1.35+ | Должен соответствовать версии Control Plane. |
| **Container Runtime** | containerd 1.7.0+, CRI-O 1.27+ | containerd 2.0+, CRI-O 1.30+ | Поддержка gRPC CRI вызовов `UpdateContainerResources` и `UpdatePodSandboxResources`. |
| **Ядро Linux** | 5.15+ LTS | 6.1+ / 6.6+ LTS | Обязательна поддержка cgroup v2 unified hierarchy. На cgroup v1 ресайз памяти нестабилен. |

### Проверка готовности узлов и кластера

```bash
# 1. Проверка версии API-сервера и Kubelet
kubectl get nodes -o wide
# → NAME       STATUS   ROLES           AGE   VERSION   KERNEL-VERSION      CONTAINER-RUNTIME
# → k8s-node1  Ready    control-plane   30d   v1.35.0   6.1.0-28-amd64      containerd://2.0.2
# → k8s-node2  Ready    worker          30d   v1.35.0   6.1.0-28-amd64      containerd://2.0.2

# 2. Проверка активности cgroup v2 на рабочем узле (выполняется на хосте или через debug)
kubectl debug node/k8s-node2 -it --image=alpine -- cat /sys/fs/cgroup/cgroup.controllers
# → cpuset cpu io memory pids

# 3. Проверка параметров Kubelet Configuration на узле
kubectl debug node/k8s-node2 -it --image=alpine -- cat /var/lib/kubelet/config.yaml | grep -E "cpuManagerPolicy|memoryManagerPolicy"
# → cpuManagerPolicy: none
# → memoryManagerPolicy: None

# 4. Проверка поддержки подресурса resize через kubectl API discovery
kubectl api-resources --api-group="" | grep "pods/resize"
# → pods/resize                           v1             Pod           false        Pod
```

### Ограничения окружения пространства имен

1. **ResourceQuota:** При изменении ресурсов `requests` проверяются квотой немедленно. Если суммарные `requests` подов неймспейса превысят `hard.requests.cpu` или `hard.requests.memory`, API-сервер отклонит PATCH-запрос с кодом `403 Forbidden`.
2. **LimitRange:** Запрашиваемые новые значения обязаны находиться в диапазоне `[min, max]` и соответствовать `maxLimitRequestRatio`, заданным в неймспейсе.

---

## Практические сценарии

### Сценарий 1: Экстренное увеличение ресурсов пода через подресурс `/resize`

Применяется дежурным инженером SRE при риске исчерпания памяти (Out-Of-Memory) или резком росте CPU throttling на критичном поде без прерывания пользовательских сессий.

```bash
# 1. Проверка текущих Desired, Allocated и Actual ресурсов
kubectl get pod billing-core-0 -o jsonpath='{
  "Desired": .spec.containers[0].resources,
  "Allocated": .status.containerStatuses[0].allocatedResources,
  "Actual": .status.containerStatuses[0].resources
}'
# → {"Desired":{"limits":{"cpu":"1","memory":"1Gi"},"requests":{"cpu":"500m","memory":"512Mi"}},"Allocated":{"cpu":"500m","memory":"512Mi"},"Actual":{"cpu":"1","memory":"1Gi"}}

# 2. Применение патча через подресурс /resize
kubectl patch pod billing-core-0 --subresource=resize --type='merge' -p '{
  "spec": {
    "containers": [{
      "name": "billing-app",
      "resources": {
        "requests": {
          "cpu": "1",
          "memory": "1536Mi"
        },
        "limits": {
          "cpu": "2",
          "memory": "2Gi"
        }
      }
    }]
  }
}'
# → pod/billing-core-0 patched

# 3. Валидация успешности операции
kubectl get pod billing-core-0 -o jsonpath='{
  "Allocated": .status.containerStatuses[0].allocatedResources,
  "Conditions": .status.conditions[?(@.type=~"PodResize.*")]
}'
# → {"Allocated":{"cpu":"1","memory":"1536Mi"},"Conditions":[]}
```

**Прямой вызов через REST API (для bash-скриптов и CI/CD автоматизации):**

```bash
# Вызов подресурса через curl с сервисным токеном
APISERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
TOKEN=$(kubectl create token default --duration=10m)

curl -s -X PATCH "$APISERVER/api/v1/namespaces/default/pods/billing-core-0/resize" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/merge-patch+json" \
  -d '{
    "spec": {
      "containers": [{
        "name": "billing-app",
        "resources": {
          "requests": {"cpu": "1", "memory": "1536Mi"},
          "limits": {"cpu": "2", "memory": "2Gi"}
        }
      }]
    }
  }' | jq '.status.containerStatuses[0].allocatedResources'
# → {
# →   "cpu": "1",
# →   "memory": "1536Mi"
# → }
```

### Сценарий 2: Автомасштабирование через Vertical Pod Autoscaler (VPA)

Стандарт эксплуатации в production: VPA отслеживает профиль потребления и отправляет точечные PATCH-запросы к запущенным подам, переводя их на новые лимиты без перезапуска.

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: postgres-vpa
  namespace: database
spec:
  targetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: postgres-ha
  updatePolicy:
    updateMode: "InPlaceOrRecreate" # Пробует In-Place; при Infeasible выселяет под с соблюдением PDB
  resourcePolicy:
    containerPolicies:
      - containerName: postgres
        minAllowed:
          cpu: 500m
          memory: 1Gi
        maxAllowed:
          cpu: "8"
          memory: "16Gi"
        controlledResources: ["cpu", "memory"]
        controlledValues: RequestsAndLimits
```

**Диагностика работы VPA:**

```bash
# 1. Проверка рекомендаций Recommender
kubectl describe vpa postgres-vpa -n database
# → Recommendation:
# →   Target:
# →     Cpu:     1500m
# →     Memory:  3Gi

# 2. Проверка факта применения изменений VPA Updater без изменения возраста подов
kubectl get pods -n database -l app=postgres-ha -o custom-columns=NAME:.metadata.name,CPU_ALLOCATED:.status.containerStatuses[0].allocatedResources.cpu,MEM_ALLOCATED:.status.containerStatuses[0].allocatedResources.memory,AGE:.status.startTime
# → NAME            CPU_ALLOCATED   MEM_ALLOCATED   AGE
# → postgres-ha-0   1500m           3Gi             2026-09-01T10:00:00Z
# → postgres-ha-1   1500m           3Gi             2026-09-01T10:00:00Z
```

### Сценарий 3: Динамическое изменение ресурсов для нативных Sidecar-контейнеров

В Kubernetes 1.33+ In-Place Resize поддерживается для сайдкаров — init-контейнеров с директивой `restartPolicy: Always`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: payment-service-0
spec:
  initContainers:
  - name: envoy-proxy
    image: envoyproxy/envoy:v1.32.0
    restartPolicy: Always
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 256Mi
  containers:
  - name: payment-app
    image: payment-app:v2.4
    resources:
      requests:
        cpu: 500m
        memory: 1Gi
      limits:
        cpu: "1"
        memory: "2Gi"
```

```bash
# Увеличение лимитов CPU прокси-сайдкара под нагрузкой
kubectl patch pod payment-service-0 --subresource=resize --type='merge' -p '{
  "spec": {
    "initContainers": [{
      "name": "envoy-proxy",
      "resources": {
        "requests": {"cpu": "250m", "memory": "128Mi"},
        "limits": {"cpu": "1", "memory": "512Mi"}
      }
    }]
  }
}'
# → pod/payment-service-0 patched
```

### Сценарий 4: Безопасный откат ресурсов (Rollback)

При снижении нагрузки администратор или автоматизация возвращает базовые ресурсы:

```bash
# Откат параметров пода к базовым лимитам
kubectl patch pod billing-core-0 --subresource=resize --type='merge' -p '{
  "spec": {
    "containers": [{
      "name": "billing-app",
      "resources": {
        "requests": {"cpu": "500m", "memory": "512Mi"},
        "limits": {"cpu": "1", "memory": "1Gi"}
      }
    }]
  }
}'
# → pod/billing-core-0 patched

# Контроль отсутствия зависания в PodResizeInProgress (проверка, что память уменьшена)
kubectl get pod billing-core-0 -o jsonpath='{.status.containerStatuses[0].resources.limits.memory}'
# → 1Gi
```

---

## Операции и команды

### Сводная таблица команд администратора

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| **Изменить ресурсы** | `kubectl patch pod <pod> --subresource=resize -p '<JSON>'` | `pod/<pod> patched` |
| **Сравнить Desired vs Actual** | `kubectl get pod <pod> -o jsonpath='{"Spec":.spec.containers[0].resources,"Allocated":.status.containerStatuses[0].allocatedResources,"Actual":.status.containerStatuses[0].resources}'` | Вывод JSON с тремя объектами ресурсов |
| **Проверить условия ресайза** | `kubectl get pod <pod> -o jsonpath='{.status.conditions[?(@.type=~"PodResize.*")]}'` | Пусто (успех) или блок Conditions |
| **Найти поды со статусом Infeasible** | `kubectl get pods -A -o json \| jq '.items[] \| select(.status.conditions[]? \| select(.type=="PodResizePending" and .reason=="Infeasible")) \| {namespace: .metadata.namespace, name: .metadata.name, message: .status.conditions[].message}'` | Список подов, заблокированных нехваткой емкости |
| **Инспекция cgroupfs на хосте** | `cat /sys/fs/cgroup/kubepods.slice/.../cpu.max` | `<quota> <period>` (например, `200000 100000`) |
| **Инспекция через crictl** | `crictl inspect <container-id> \| jq .info.runtimeSpec.linux.resources` | Структура CPU и Memory в рантайме |

### Инспекция cgroups v2 на уровне хоста Linux

Системный администратор может проверить применение лимитов напрямую на узле без вызова API Kubernetes:

```bash
# 1. Получение Container ID и Pod UID
POD_UID=$(kubectl get pod billing-core-0 -o jsonpath='{.metadata.uid}')
CONTAINER_ID=$(kubectl get pod billing-core-0 -o jsonpath='{.status.containerStatuses[0].containerID}' | sed 's/containerd:\/\///')

# 2. Проверка cgroups v2 на узле хоста (путь для containerd в systemd slice)
CGROUP_PATH="/sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod${POD_UID//-/_}.slice/cri-containerd-${CONTAINER_ID}.scope"

# Чтение квоты CPU (cpu.max: <quota> <period>, где 200000 / 100000 = 2 ядра)
cat "$CGROUP_PATH/cpu.max"
# → 200000 100000

# Чтение веса CPU (cpu.weight, где 100 соответствуют запросу 1 ядро)
cat "$CGROUP_PATH/cpu.weight"
# → 100

# Чтение жесткого лимита памяти (memory.max в байтах, 2147483648 = 2Gi)
cat "$CGROUP_PATH/memory.max"
# → 2147483648

# Чтение гарантированной защиты памяти (memory.min / memory.low)
cat "$CGROUP_PATH/memory.low"
# → 1610612736
```

---

## Специфика рантаймов приложений

Изменение cgroupfs со стороны ядра Linux не означает, что прикладной процесс автоматически перенастроит внутренние пулы аллокаторов.

### Java (JVM)

* **Проблема:** JVM при старте определяет объем физической памяти через вызовы ядра и жестко инициализирует максимальный размер Heap (`-XX:MaxRAMPercentage` или `-Xmx`). При расширении лимита `memory.max` в cgroup процесс Java не увеличит размер Heap автоматически. При сужении cgroup ниже текущего размера Heap произойдет немедленный `OOMKilled` (Exit Code 137).
* **Поведение CPU:** Изменение CPU-квот поддерживается JVM прозрачно: потоки планировщика JVM (включая ForkJoinPool и Parallel GC) продолжают работать, а троттлинг устраняется ядром.
* **Рекомендация SRE:** Для Java-контейнеров выставлять:
  ```yaml
  resizePolicy:
    - resourceName: cpu
      restartPolicy: NotRequired
    - resourceName: memory
      restartPolicy: RestartContainer
  ```

### Go (Golang)

* **Механизм:** С версии Go 1.19 введена переменная окружения `GOMEMLIMIT`. Сборщик мусора (GC) Go ориентируется на это значение для агрессивной очистки памяти до достижения порога cgroup.
* **Решение:** Использовать библиотеку [automemlimit](https://github.com/KimMachineGun/automemlimit) или вызывать `runtime/debug.SetMemoryLimit`. Библиотека подписывается на изменения файла `/sys/fs/cgroup/memory.max` и обновляет внутренний лимит памяти рантайма Go без перезапуска процесса.
* **Рекомендация:** Для Go-приложений безопасна политика `NotRequired` для обоих ресурсов.

### Node.js (V8)

* **Механизм:** Движок V8 фиксирует лимит кучи при старте флагом `--max-old-space-size`.
* **Поведение:** Увеличение памяти в cgroup спасает контейнер от `OOMKilled` ядра Linux, но V8 может упасть с внутренней ошибкой `Fatal error: CALL_AND_RETRY_LAST Allocation failed - JavaScript heap out of memory`, если внутренний лимит остался прежним.
* **Рекомендация:** Для CPU использовать `NotRequired`. Для памяти — `RestartContainer` при необходимости смены `--max-old-space-size`.

### Python (CPython)

* **Механизм:** Стандартный CPython использует системные аллокаторы (`glibc malloc` / `ptmalloc` или `jemalloc`).
* **Поведение:** Python мгновенно видит добавленный объем оперативной памяти и задействует его при обработке объемных массивов (numpy, pandas, celery tasks).
* **Специфика освобождения:** Аллокатор `glibc` не всегда оперативно отдает освобожденную память ядру ОС из-за фрагментации страниц. При динамическом уменьшении лимитов памяти рекомендуется использовать `jemalloc` с включенным фоновым сбросом страниц (`MALLOC_CONF="background_thread:true,dirty_decay_ms:1000,muzzy_decay_ms:1000"`).

### .NET (Core 6+)

* **Механизм:** Рантайм .NET нативно поддерживает контейнерные cgroups.
* **Поведение:** Поддерживает флаги `DOTNET_GCHeapHardLimitPercent` и `DOTNET_GCConserveMemory`. При расширении cgroup GC подстраивается под новый потолок.
* **Рекомендация:** Политика `NotRequired` поддерживается для CPU и памяти.

### Базы данных и кэши (PostgreSQL, Redis)

* **PostgreSQL:** Параметр `shared_buffers` фиксируется при старте в оперативной памяти. Изменение `limits.memory` без перезапуска не увеличит размер кэша PostgreSQL, но увеличит доступный размер Page Cache ОС для быстрых чтений. Для масштабирования пулов требуется рестарт инстанса.
* **Redis:** Параметр `maxmemory` не синхронизируется с cgroup автоматически. Для задействования добавленной памяти требуется отправка команды `CONFIG SET maxmemory <bytes>` через `redis-cli` после ресайза пода.

---

## Диагностика и устранение неисправностей

### Матрица состояний и условий

| Условие / Статус | Причина | Что происходит под капотом | Действия инженера |
| :--- | :--- | :--- | :--- |
| **`PodResizePending`** | `Deferred` | На узле суммарно не хватает `NodeAllocatable` емкости для новых `requests`. | Ожидать завершения других подов или добавить рабочие узлы в кластер. |
| **`PodResizePending`** | `Infeasible` | Запрос превышает общую емкость узла, узел использует статический CPU Manager или включен Swap. | Проверить емкость узла и настройки Kubelet. Если используется VPA, он перезапустит под на большем узле. |
| **`PodResizeInProgress`** | `Error` | CRI рантайм (containerd) вернул ошибку при вызове `UpdateContainerResources`. | Изучить системный журнал containerd: `journalctl -u containerd -n 100`. |
| **`PodResizeInProgress`** | *(пусто)* | Идет штатный процесс применения настроек ядра Linux. | Ожидать завершения (обычно < 1 секунды). |

### Типовые проблемы и решения

#### 1. Ошибка API: `QoS class immutability violation`

* **Симптом:** При попытке применить `kubectl patch pod ... --subresource=resize` возвращается ошибка:
  `Error from server (Forbidden): pod updates may not change the pod QoS class`.
* **Причина:** Исходный под имел класс `Burstable` (requests != limits). Новые значения `requests` и `limits` установлены равными, что привело бы к пересчету класса в `Guaranteed`.
* **Решение:** Сохранять исходную пропорцию `requests < limits`, либо поддерживать ненулевую разницу. Для перевода пода в `Guaranteed` требуется пересоздание объекта.

#### 2. Зависание в `InProgress` при уменьшении лимита памяти

* **Симптом:** Лимит памяти уменьшен, но статус `PodResizeInProgress` не исчезает, либо процесс контейнера неожиданно завершается по `OOMKilled`.
* **Причина:** Активное потребление памяти (Resident Set Size + анонимные страницы) процесса превышает новый запрошенный лимит `memory.max`. Ядро Linux попыталось сбросить Page Cache, не смогло освободить требуемый объем и вызвало OOM Killer.
* **Диагностика:**
  ```bash
  # Проверка текущего RSS процесса перед уменьшением лимита
  kubectl top pod billing-core-0 --containers
  # → POD                NAME          CPU(cores)   MEMORY(bytes)
  # → billing-core-0     billing-app   150m         1400Mi
  ```
* **Решение:** Запрещено ужимать `limits.memory` ниже текущего потребления рабочего процесса. Сначала инициируйте сброс кэшей в приложении, и только затем уменьшайте лимит.

#### 3. Статус `Infeasible: cpuManagerPolicy static is active`

* **Симптом:** Под класса `Guaranteed` зависает с условием `PodResizePending` и причиной `Infeasible`. В логах Kubelet:
  `In-place resize is not yet supported for guaranteed pods alongside CPU manager static policy`.
* **Причина:** Узел настроен со статическим выделением изолированных процессорных ядер (`cpuManagerPolicy: static`). Механизм динамического изменения ресурсов не умеет перераспределять эксклюзивные pinned CPU cores без рестарта.
* **Решение:** Использовать In-Place Resize только на узлах с `cpuManagerPolicy: none`, либо использовать класс `Burstable`.

#### 4. Блокировка квотой пространства имен `ResourceQuota`

* **Симптом:** Запрос отклоняется: `exceeded quota: compute-resources, requested: requests.cpu=1, used: requests.cpu=15, limited: requests.cpu=15`.
* **Причина:** Увеличение `requests` выходит за границы квоты неймспейса.
* **Решение:** Расширить квоту `ResourceQuota` либо освободить квоту, снизив `requests` на некритичных dev-подах.

### Мониторинг и алертинг (Prometheus)

#### Ключевые метрики

```promql
# 1. Количество запросов на ресайз по результатам (счетчик Kubelet)
sum by (instance, result) (rate(kubelet_container_requested_resizes_total[5m]))

# 2. Количество подов, заблокированных из-за нехватки ресурсов узла (Infeasible)
sum(kubelet_pod_infeasible_resizes_total) by (instance)

# 3. Длительность транзакции ресайза в секундах (95-й перцентиль)
histogram_quantile(0.95, sum by (le) (rate(kubelet_pod_resize_duration_seconds_bucket[5m])))

# 4. Поды с активным условием PodResizePending (по причинам)
sum by (namespace, pod, reason) (kube_pod_status_condition{condition="PodResizePending", status="true"})

# 5. Рассинхронизация Desired и Allocated ресурсов дольше 5 минут
(kube_pod_container_resource_requests{resource="cpu"} - on(namespace, pod, container) kube_pod_container_resource_allocated{resource="cpu"}) != 0
```

#### Настройка правил алертинга (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: in-place-resize-alerts
  namespace: monitoring
spec:
  groups:
  - name: in-place-pod-resize
    rules:
    - alert: PodResizeStuckInProgress
      expr: kube_pod_status_condition{condition="PodResizeInProgress", status="true"} == 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} завис в процессе применения ресайза"
        description: "Контейнер находится в состоянии PodResizeInProgress более 5 минут. Проверьте логи containerd и доступность узла."

    - alert: PodResizeInfeasibleCapacity
      expr: kube_pod_status_condition{condition="PodResizePending", reason="Infeasible", status="true"} == 1
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Запрос на ресайз пода {{ $labels.namespace }}/{{ $labels.pod }} отклонен (Infeasible)"
        description: "Узел не может предоставить запрашиваемые ресурсы. Требуется вмешательство VPA для выселения или масштабирование емкости узлов."

    - alert: ResourceAllocationDrift
      expr: |
        (
          kube_pod_container_resource_requests{resource="memory"}
          - on(namespace, pod, container)
          kube_pod_container_resource_allocated{resource="memory"}
        ) > 0
      for: 15m
      labels:
        severity: critical
      annotations:
        summary: "Рассинхронизация желаемых и выделенных ресурсов для {{ $labels.pod }}"
        description: "Желаемый объем памяти в спецификации превышает фактически выделенный на узле более 15 минут."
```

---

## Лучшие практики

1. **Единая среда cgroup v2 на всех узлах:** Никогда не используйте In-Place Resize на гетерогенных кластерах со смешанными версиями cgroups. Память без сбоев масштабируется только в unified cgroup v2 (`/sys/fs/cgroup`).
2. **Безопасная политика масштабирования памяти:** Для приложений с виртуальными машинами (JVM, Erlang BEAM) всегда выставляйте `resizePolicy: RestartContainer` на ресурс `memory`. Использовать `NotRequired` для памяти допустимо только в рантаймах, динамически пересчитывающих аллокаторы по событиям cgroup (Go с `automemlimit`, .NET 6+).
3. **Разграничение ответственности с HPA:** Запрещено настраивать HPA и VPA/In-Place Resize на одни и те же ресурсные метрики (CPU/Memory). Стандартный паттерн: HPA масштабирует количество реплик по бизнес-метрикам (RPS, задержка очереди сообщений), а In-Place Resize регулирует вертикальные лимиты контейнеров.
4. **Контроль пределов `requests` в namespace:** Перед массовым внедрением In-Place Resize убедитесь, что лимиты `ResourceQuota` в неймспейсах имеют запас емкости для вертикального роста рабочих нагрузок.
5. **Запас емкости узлов (Node Headroom):** Для предотвращения массовых зависаний в статусе `Deferred` держите запас неаллоцированных ресурсов на рабочих узлах не менее 15–20% от `NodeAllocatable`.
6. **Тестирование Throttling при снижении CPU:** Уменьшение `limits.cpu` безопасно с точки зрения стабильности ОС, но может вызвать троттлинг потоков приложения. Проверяйте метрику `container_cpu_cfs_throttled_periods_total` в cAdvisor после применения новых лимитов.

---

## Дополнительная информация

### Внутренние руководства платформы

* [Vertical Pod Autoscaler (VPA)](./vpa_detailed.md) — контроллер автоматического управления ресурсами и генератор запросов In-Place Resize.
* [QoS классы и лимиты](../Scheduling/qos_limit_and_requests.md) — механизмы расчета классов обслуживания Guaranteed, Burstable и их влияние на вытеснение.
* [Горячий старт Java-приложений](../Scheduling/java-startup-cpu-boost.md) — паттерн динамического выделения CPU на этапе инициализации контейнера с последующим снятием через In-Place Resize.
* [Horizontal Pod Autoscaler (HPA)](./HPA/index.md) — базовые концепции и архитектура горизонтального масштабирования.
* [Диагностика OOMKilled](../Troubleshooting/Common_Errors/oomkilled_pods.md) — пошаговое расследование инцидентов принудительного завершения контейнеров по нехватке памяти.

### Внешние технические спецификации

* [KEP-1287: In-place Update of Pod Resources](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/1287-in-place-update-pod-resources) — официальный архитектурный дизайн и критерии стабилизации SIG-Node.
* [Control Group v2 Linux Kernel Documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html) — спецификация контроллеров управления памятью и процессором ядра Linux.
