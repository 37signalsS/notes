# Управление ресурсами в Kubernetes: Requests, Limits, Quotas и QoS

## Предварительные требования

### Требования к кластеру
* **Kubernetes:** версия 1.26+ (для стабильной работы QoS и ResourceQuota), 1.33+ для In-Place Pod Resize (Beta)
* **Kubelet:** настроенные флаги `--kube-reserved` и `--system-reserved` для корректного расчета `Node Allocatable`
* **Container Runtime:** containerd 1.7+ или CRI-O 1.26+ (для поддержки cgroups v2 и In-Place Resize)

### Инструменты
* **kubectl:** версия 1.26+
* **Metrics Server:** установлен для работы `kubectl top` и HPA
* **Prometheus + kube-state-metrics:** для мониторинга потребления ресурсов и алертинга

### Проверка готовности
```bash
# Проверка версии Kubernetes
kubectl version --short
# Client: v1.31.0
# Server: v1.31.0

# Проверка наличия Metrics Server
kubectl top nodes
# NAME   CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# node1  250m         12%    2048Mi          51%

# Проверка Node Allocatable
kubectl get node <node-name> -o jsonpath='{.status.allocatable}'
# {"cpu":"3800m","memory":"15Gi","pods":"110"}

# Проверка текущих ResourceQuota в Namespace
kubectl describe quota -n <namespace>

# Проверка LimitRange в Namespace
kubectl describe limitrange -n <namespace>
```

### Начальное состояние
* Кластер запущен и доступен через `kubectl`
* Имеется как минимум один рабочий узел (worker node)
* Пользователь имеет права на создание Pod, ResourceQuota, LimitRange в целевом Namespace

---

## Определения

* **`requests` (Запросы):** Минимальный гарантированный уровень ресурсов (CPU и памяти), который Kubernetes выделяет контейнеру. 
  * **Планирование:** Планировщик (`kube-scheduler`) использует это значение как основной критерий при поиске узла. Он суммирует `requests` уже запущенных подов на ноде и сравнивает с общим объемом ресурсов ноды, чтобы понять, «влезет» ли новый под.
  * **Приоритет исполнения:** Помимо планирования, `requests` определяют приоритет подов в процессе работы (аналог значения `nice` в Linux) — поды с более высокими запросами могут получать приоритет при распределении циклов CPU.
  * **`requests.cpu`:** Минимальная вычислительная мощность. Выражается в ядрах или милли-ядрах.
  * **`requests.memory`:** Минимальный объём оперативной памяти.

* **`limits` (Лимиты):** Максимальная верхняя граница ресурсов, которую контейнеру разрешено потреблять.
  * **`limits.cpu` (Мягкое ограничение):** Жёсткий потолок использования CPU. При попытке превышения лимита процесс подвергается **[throttling (дросселированию)](../Troubleshooting/Common_Errors/cpu_throttling.md)** — искусственному ограничению циклов процессора планировщиком CFS (Completely Fair Scheduler). Это приводит к незаметному снижению производительности (рост Latency, таймауты), но не к падению приложения. 
    * *Примечание:* Если в Kubelet отключен флаг `--cpu-cfs-quota=false` (обычно используется для высоконагруженных вычислительных кластеров), лимиты CPU игнорировались ядром, однако современная практика Kubernetes требует использования CFS-квот для изоляции. В свежих версиях ядра проблема избыточного троттлинга CFS была в значительной степени решена.
  * **`limits.memory` (Жесткое ограничение):** Жёсткий потолок памяти. Если процесс запрашивает память сверх лимита, ядро ОС или kubelet принудительно завершают его с ошибкой **[OOMKilled](../Troubleshooting/Common_Errors/oomkilled_pods.md)** (код 137). В отличие от ЦП, это немедленное прекращение работы.

* **QoS (Quality of Service — Качество Обслуживания):** Класс приоритетности, который Kubernetes автоматически присваивает поду на основе конфигурации его ресурсов. Этот класс определяет, насколько "защищен" под при нехватке ресурсов на узле и в какой очередности он будет выселен (**eviction**).

* **Node Allocatable (Доступные ресурсы узла):** Реальный объем ресурсов, доступный для планирования пользовательских нагрузок.
  * Формула: `Allocatable = Capacity - (Kube-reserved + System-reserved + Hard-Eviction-Threshold)`.
  * Планировщик оперирует именно значением `Allocatable`, а не полной мощностью железа.

### Типы ресурсов

1. **CPU (`cpu`):** Вычислительная мощность. Измеряется в "milliCPU" (`1000m` = 1 vCPU/Core).
   * Ресурс является **сжимаемым** (compressible): при нехватке приложение просто работает медленнее.
2. **Память (`memory`):** Оперативная память. Измеряется в байтах или с суффиксами (`Mi`, `Gi`).
   * Ресурс является **несжимаемым** (non-compressible): при нехватке процесс убивается.
3. **Эфемерное хранилище (`ephemeral-storage`):** Место на локальном диске узла для нужд пода.
   * Включает: слои контейнера (writable layer), логи приложения, тома типа `emptyDir`.
   * **`requests.ephemeral-storage`:** Гарантированное место.
   * **`limits.ephemeral-storage`:** При превышении лимита под будет немедленно выселен с узла (**Evicted**).
4. **HugePages (`hugepages-<size>`):** Резервирование памяти большими страницами (например, `hugepages-2Mi`, `hugepages-1Gi`).
   * Требует предварительной настройки на уровне ОС узла и включенного Feature Gate в Kubernetes.
   * HugePages являются несжимаемыми ресурсами.
5. **Расширенные ресурсы (Extended Resources):** Пользовательские ресурсы, не встроенные в ядро K8s (GPU, FPGA, специальные сетевые адаптеры).
   * Формат: `domain/resource-name` (например, `nvidia.com/gpu: 1`).
   * **GPU (Graphics Processing Unit):** Требуют установки драйверов и специализированного плагина (например, **NVIDIA Device Plugin**).
   * **Дробное выделение (Fractional GPU):** По умолчанию ресурсы GPU запрашиваются только целыми числами. Для эффективного использования в задачах GenAI и LLM применяются технологии разделения:
    * **NVIDIA MIG (Multi-Instance GPU):** Аппаратное разделение одного физического GPU на несколько полностью изолированных инстансов (до 7 шт.). Обеспечивает гарантированную производительность и изоляцию памяти. Рекомендуется для критических нагрузок GenAI. См. [Шеринг GPU](./gpu_sharing.md).
    * **NVIDIA MPS (Multi-Process Service):** Программный слой, позволяющий нескольким процессам (контейнерам) одновременно использовать один GPU. Обеспечивает высокую плотность размещения мелких моделей (инференс), но с меньшей изоляцией, чем MIG. См. [Шеринг GPU](./gpu_sharing.md).
    * **Time-slicing:** Разделение GPU по времени. Позволяет нескольким подам использовать GPU по очереди, что подходит для некритичных задач разработки. См. [Шеринг GPU](./gpu_sharing.md).
    * **HAMi:** Open source GPU-виртуализация (CNCF Incubating): time-slicing + изоляция видеопамяти (`nvidia.com/gpumem`) и ядер (`nvidia.com/gpucores`). См. [Шеринг GPU](./gpu_sharing.md).
   * **Особое правило:** Для расширенных ресурсов `requests` должны быть всегда **равны** `limits`.


### Единицы измерения

* **CPU:** `1000m` = `1` vCPU/Core. `500m` — половина ядра. `0.1` эквивалентно `100m`.
* **Память и диск:** Используются двоичные (Ki, Mi, Gi, Ti) или десятичные (K, M, G, T) префиксы.
  * Рекомендуется использовать двоичные (`Mi`, `Gi`), так как они соответствуют реальному выделению памяти в ОС.
  * `1Mi` (mebibyte) = 1,048,576 байт. `1M` (megabyte) = 1,000,000 байт.

---

## Основные концепции

### Классы качества обслуживания (QoS)

Kubernetes вычисляет QoS-класс на основе `requests` и `limits` всех контейнеров в поде:

#### 1. `Guaranteed` (Гарантированный)
* **Условия:**
  1. Для каждого контейнера в поде (включая init-контейнеры) заданы `requests` и `limits` для CPU и памяти.
  2. Значения `requests` строго равны `limits` для каждого ресурса.
* **Приоритет:** **Высший**. Эти поды выселяются только в крайнем случае, когда на узле не осталось подов других классов, а системным компонентам не хватает ресурсов.

#### 2. `Burstable` (Эластичный)
* **Условия:**
  1. Под не соответствует критериям `Guaranteed`.
  2. Хотя бы у одного контейнера указан `requests` для CPU или памяти.
* **Поведение:** Поды могут использовать ресурсы вплоть до `limits`, если они доступны на узле. Если под потребляет больше своих `requests` и узел находится под давлением, этот под становится кандидатом на выселение.

#### 3. `BestEffort` (Максимальное усилие)
* **Условия:** Ни у одного контейнера в поде не указаны ни `requests`, ни `limits`.
* **Приоритет:** **Низший**. Поды получают ресурсы по остаточному принципу. Это "первые кандидаты на вылет" при любой нехватке ресурсов.

#### Сводная таблица QoS

| QoS Класс      | Условие (CPU & RAM)                         | Очередность выселения    | Типичный сценарий                                    |
|----------------|---------------------------------------------|--------------------------|------------------------------------------------------|
| **`Guaranteed`** | `requests` == `limits`                     | Последний (самый защищенный) | СУБД, Production API, StatefulSet                     |
| **`Burstable`**  | `requests` < `limits` или только `requests` | Средний                  | Микросервисы, Web-серверы                            |
| **`BestEffort`** | Нет ни `requests`, ни `limits`              | Первый (наименее защищенный) | Тестовые окружения, некритичные Batch-задачи         |

### Расчет ресурсов для специальных типов контейнеров

#### Инициализирующие контейнеры (Init Containers)
Поскольку init-контейнеры выполняются последовательно до старта основных контейнеров, планировщик учитывает их ресурсы следующим образом:
* `EffectiveRequest = max(max(init_containers_requests), sum(app_containers_requests))`
* `EffectiveLimit = max(max(init_containers_limits), sum(app_containers_limits))`

#### Нативные сайдкары (Native Sidecars, GA 1.29+)
Контейнеры в `initContainers` с полем `restartPolicy: Always` продолжают работать в течение всего жизненного цикла пода. Их ресурсы суммируются с основными контейнерами:
* `EffectiveRequest = sum(app_containers_requests) + sum(sidecar_containers_requests)`

### Менеджер выселения (Eviction Manager), QoS и oom_score_adj

При возникновении `Node Pressure` (нехватка ресурсов на узле), `kubelet` активирует механизм выселения подов. Решение принимается на основе QoS и реального потребления:

1. **Ранжирование по классу:** Сначала выбираются все поды `BestEffort`, затем `Burstable`.
2. **Ранжирование внутри Burstable:** Среди `Burstable` первыми выселяются те, у которых **текущее потребление превышает их `requests`** в наибольшей степени.
3. **Защита Guaranteed:** Поды класса `Guaranteed` выселяются только если все `BestEffort` и "нарушители" `Burstable` уже удалены.

**Связь с OOM Killer в ядре Linux (`oom_score_adj`):**
Kubernetes транслирует бизнес-логику приоритетов QoS напрямую в ядро Linux через параметр `oom_score_adj` (диапазон от -1000 до 1000). Это определяет, кого ядро Linux убьет первым при системной нехватке памяти:
* **`Guaranteed`**: `-997` (максимально защищен от OOM-убийцы, не может быть убит ядром, пока есть другие процессы).
* **`BestEffort`**: `1000` (первый кандидат на убийство).
* **`Burstable`**: Динамическое значение от `2` до `999` (рассчитывается по формуле `min(max(2, 1000 - (1000 * memoryRequest) / memoryCapacity), 999)`). Чем больше памяти запрошено относительно объема узла, тем ниже (безопаснее) score.
* *Примечание:* Компоненты Kubelet и Docker/containerd имеют `oom_score_adj = -999`, что защищает их даже от процессов `Guaranteed`.

Подробные алгоритмы описаны в руководстве: **[Выселение подов: Классы QoS и работа Менеджера выселения](../Troubleshooting/Common_Errors/PodEvicted/qos_and_eviction.md)**.

### Static CPU Manager Policy

Этот механизм позволяет подам с QoS `Guaranteed` получить **эксклюзивную привязку к физическим ядрам CPU** (CPU Pinning).
* **Требования:**
  1. Класс пода — `Guaranteed`.
  2. `requests.cpu` — целое число (например, `2`, `4`).
  3. В kubelet настроено `cpuManagerPolicy: static`.
* **Результат:** Ядро процессора полностью выделяется под контейнер. Другие поды не могут использовать это ядро. Это критично для приложений, чувствительных к переключению контекста и кэш-промахам.

### Memory QoS через cgroups v2

Современный механизм управления памятью, который заменяет грубый OOMKill на более гибкие инструменты:
* **`memory.min` (соответствует `requests.memory`):** Жесткое резервирование. Эту память ОС никогда не заберет у контейнера для кэша или других нужд.
* **`memory.high` (соответствует `limits.memory`):** "Мягкий" лимит. При достижении этого порога ядро начинает замедлять (throttle) процесс, давая ему шанс освободить память самостоятельно, прежде чем сработает OOM Killer.

### Dynamic Resource Allocation (DRA)

Механизм (Beta в 1.30+), приходящий на смену Device Plugins. Позволяет описывать сложные требования к ресурсам (например, "мне нужно 2 GPU с поддержкой NVLink и 100 ГБ памяти на них") через `ResourceClaim` и `ResourceClass`. Обеспечивает более глубокую интеграцию со специфическим железом. Подробнее: [Device Manager](./device_manager.md).

### In-Place Pod Resize (GA 1.35)

Функция, позволяющая менять `requests` и `limits` запущенного пода без его перезапуска.
* **Как работает:** Вы редактируете Deployment/Pod, kubelet видит изменения и пытается применить их через cgroups на лету.
* **Resize Policy:** Можно указать, допустим ли перезапуск контейнера для применения новых лимитов (`RestartContainer`) или изменения должны быть применены без простоя (`NoRestart`).
* **Статус:** Если на узле нет места для увеличения `requests`, под останется в статусе `Proposed`, пока ресурсы не освободятся.

Подробнее: **[In-Place Pod Resize](../Autoscaling/in_place_pod_resize.md)**.

### Изменение ресурсов в Job (v1.36 Beta)

Для приостановленных Job (`suspend: true`) теперь можно менять шаблон ресурсов пода. Это полезно для пакетных систем (Batch Scheduling), которые могут уменьшить аппетиты задачи, чтобы она "влезла" в текущие свободные ресурсы кластера.

### Preemption (Вытеснение) и QoS

**Preemption** — это механизм планировщика, когда высокоприоритетный под вытесняет низкоприоритетный, чтобы занять его место.
* **Важно:** Preemption работает на основе `PriorityClass`, а не QoS.
* Под `BestEffort` с высоким `priorityClassName` **может** вытеснить под `Guaranteed` с низким приоритетом.
* QoS влияет на выселение при нехватке ресурсов (kubelet), а `PriorityClass` — на вытеснение при планировании (scheduler).

### Topology Manager и NUMA-выравнивание

Для высокопроизводительных задач (High-Performance Computing, Telco) недостаточно просто выделить ресурсы; критически важно **физическое расположение** этих ресурсов на материнской плате.

*   **Проблема (NUMA):** В многопроцессорных системах память и PCI-устройства (включая GPU и быстрые сетевые карты) привязаны к конкретным CPU сокетам (NUMA-узлам). Если под получает CPU из `NUMA Node 0`, а GPU — из `NUMA Node 1`, пересылка данных через шину QPI/UPI вызовет серьезную деградацию производительности (Latency penalty).
*   **Решение (Topology Manager):** Встроенный компонент kubelet, который координирует работу CPU Manager, Memory Manager и Device Manager для выдачи ресурсов строго из одного NUMA-узла.
*   **Политики Topology Manager:**
    *   `none` (по умолчанию): Kubelet не пытается выравнивать ресурсы.
    *   `best-effort`: Kubelet попытается выровнять ресурсы (CPU, GPU, SR-IOV), но под все равно запустится, даже если идеальное выравнивание невозможно.
    *   `restricted`: Под запустится, только если ресурсы можно выровнять, иначе получит ошибку `TopologyAffinityError`.
    *   `single-numa-node`: Самая строгая политика. Все запрошенные ресурсы (целые CPU, память, GPU) должны быть гарантированно выделены ровно из **одного** NUMA-узла.
*   **Требования:** Для работы Topology Manager под обязан принадлежать к классу **`Guaranteed`** (requests == limits) и запрашивать ресурсы (CPU/устройства) целыми числами.

> Подробный разбор Topology Manager, его политик, практических сценариев и диагностики см. в [Topology Manager](./topology_manager.md).

### Автоматическое назначение и наследование ресурсов

* **CPU:** Если указан `limits.cpu`, но не указан `requests.cpu`, Kubernetes автоматически установит `requests.cpu = limits.cpu`.
* **Память:** Если указан `limits.memory`, но не указан `requests.memory`, `requests.memory` **не** устанавливается автоматически (остается 0, что ведет к QoS `Burstable`).
* **Multi-container поды:** QoS определяется по "самому слабому звену". Если один контейнер `Guaranteed`, а второй — `BestEffort`, весь под станет `Burstable`.

---

## Практические сценарии

### Сценарий 1: Настройка Guaranteed QoS для Production-сервиса

**Задача:** Развернуть критически важный сервис (например, базу данных или API) с максимальной защитой от выселения и предсказуемой производительностью.

**Решение:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: production-api
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: production-api
  template:
    metadata:
      labels:
        app: production-api
    spec:
      containers:
      - name: api
        image: my-api:v2.1.0
        resources:
          requests:
            cpu: "1000m"      # 1 vCPU гарантировано
            memory: "2Gi"     # 2 ГБ гарантировано
          limits:
            cpu: "1000m"      # Равно requests → Guaranteed QoS
            memory: "2Gi"     # Равно requests → Guaranteed QoS
        ports:
        - containerPort: 8080
```

**Валидация:**
```bash
# Применение манифеста
kubectl apply -f production-api.yaml
# deployment.apps/production-api created

# Проверка QoS-класса
kubectl get pod -l app=production-api -o jsonpath='{.items[0].status.qosClass}'
# → Guaranteed

# Проверка выделенных ресурсов
kubectl get pod -l app=production-api -o custom-columns=\
NAME:.metadata.name,QOS:.status.qosClass,CPU_REQ:.spec.containers[].resources.requests.cpu,MEM_REQ:.spec.containers[].resources.requests.memory
# NAME                QOS          CPU_REQ   MEM_REQ
# production-api-xxx  Guaranteed   1000m     2Gi

# Проверка работоспособности
kubectl get pods -l app=production-api
# NAME                              READY   STATUS    RESTARTS   AGE
# production-api-6b7d8f9c4-xxxxx    1/1     Running   0          30s
```

**Cleanup:**
```bash
kubectl delete deployment production-api -n production
# → deployment.apps "production-api" deleted
```

**Edge Cases:**
* Если узлы не имеют достаточно ресурсов для `requests` — поды останутся в `Pending`. Проверьте `kubectl describe pod <name>` для уточнения причины.
* При использовании init-контейнеров убедитесь, что они также имеют `requests == limits`, иначе QoS всего пода будет `Burstable`.
* Если контейнер использует сайдкары (Istio, Vault Agent), их ресурсы суммируются — учитывайте это при расчете.

---

### Сценарий 2: Изоляция команд через ResourceQuota и LimitRange

**Задача:** Ограничить ресурсы для команды разработки в отдельном Namespace, чтобы предотвратить "шумного соседа" и обеспечить справедливое распределение.

**Решение:**
```yaml
# 1. Создание Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: team-alpha
  labels:
    team: alpha
    environment: development
---
# 2. LimitRange — значения по умолчанию и ограничения
apiVersion: v1
kind: LimitRange
metadata:
  name: default-resources
  namespace: team-alpha
spec:
  limits:
  - default:                          # Лимиты по умолчанию
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:                   # Requests по умолчанию
      cpu: "100m"
      memory: "128Mi"
    max:                              # Максимальные значения
      cpu: "4"
      memory: "8Gi"
    min:                              # Минимальные значения
      cpu: "50m"
      memory: "64Mi"
    type: Container
---
# 3. ResourceQuota — суммарные ограничения
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: team-alpha
spec:
  hard:
    requests.cpu: "20"                # Суммарные requests для CPU
    requests.memory: "40Gi"           # Суммарные requests для памяти
    limits.cpu: "40"                  # Суммарные limits для CPU
    limits.memory: "80Gi"             # Суммарные limits для памяти
    pods: "100"                       # Максимальное количество подов
    persistentvolumeclaims: "20"      # Максимальное количество PVC
    services: "20"                    # Максимальное количество сервисов
```

**Валидация:**
```bash
# Применение конфигурации
kubectl apply -f team-alpha-quota.yaml
# namespace/team-alpha created
# limitrange/default-resources created
# resourcequota/team-quota created

# Проверка квоты
kubectl describe quota team-quota -n team-alpha
# Name:                    team-quota
# Namespace:               team-alpha
# Resource                 Used   Hard
# --------                 ---    ---
# limits.cpu               0      40
# limits.memory            0      80Gi
# pods                     0      100
# requests.cpu             0      20
# requests.memory          0      40Gi
# persistentvolumeclaims   0      20
# services                 0      20

# Проверка LimitRange
kubectl describe limitrange default-resources -n team-alpha
# Type        Resource  Min   Max  Default Request  Default Limit  Max Limit/Request Ratio
# ----        --------  ---   ---  ---------------  -------------  -----------------------
# Container   cpu       50m   4    100m             500m           -
# Container   memory    64Mi  8Gi  128Mi            512Mi          -

# Тест: создание пода без указания ресурсов (получит значения по умолчанию)
kubectl run test-pod --image=nginx --namespace=team-alpha
kubectl get pod test-pod -n team-alpha -o jsonpath='{.spec.containers[].resources}'
# {"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"128Mi"}}

# Тест: попытка превысить квоту
kubectl run big-pod --image=nginx --namespace=team-alpha -- \
  --requests=cpu=25,memory=50Gi
# Error from server (Forbidden): pods "big-pod" is forbidden:
# exceeded quota: team-quota, requested: requests.cpu=25,
# used: requests.cpu=100m, limited: requests.cpu=20
```

**Cleanup:**
```bash
kubectl delete namespace team-alpha
# → namespace "team-alpha" deleted
```

**Edge Cases:**
* Если в Namespace установлена ResourceQuota на `requests.cpu`, каждый под должен иметь явные `requests.cpu` — иначе создание будет отклонено.
* LimitRange применяется только к новым подам, созданным после его установки.
* При использовании с HPA убедитесь, что квота позволяет максимальное количество реплик.

---

### Сценарий 3: Диагностика и устранение CPU Throttling

**Задача:** Приложение демонстрирует высокую задержку (Latency) при низкой утилизации CPU на графике.

**Диагностика:**
```bash
# Шаг 1: Проверка метрик троттлинга в Prometheus
# Запрос PromQL:
# rate(container_cpu_cfs_throttled_seconds_total[5m]) > 0

# Шаг 2: Проверка текущего потребления через kubectl top
kubectl top pod -l app=my-app --sort-by=cpu
# NAME          CPU(cores)   MEMORY(bytes)
# my-app-xxxxx  950m         1024Mi

# Шаг 3: Проверка лимитов пода
kubectl get pod my-app-xxxxx -o jsonpath='{.spec.containers[].resources.limits.cpu}'
# → 1000m

# Шаг 4: Проверка через cgroup (на узле)
# Подключиться к узлу и выполнить:
cat /sys/fs/cgroup/cpu/kubepods/pod<pod-id>/cpu.stat
# nr_periods 1000
# nr_throttled 500    ← 50% периодов троттлились
# throttled_time 50000000000  ← 50 секунд суммарно
```

**Решение:**
```yaml
# Вариант A: Увеличение лимита CPU (если есть запас на узле)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
      - name: app
        resources:
          requests:
            cpu: "500m"
          limits:
            cpu: "2000m"      # Увеличен лимит
---
# Вариант B: Отмена лимита CPU (bursting pattern)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
      - name: app
        resources:
          requests:
            cpu: "500m"
          # limits не указаны — под может использовать свободные ресурсы узла
```

**Валидация:**
```bash
# Применение исправления
kubectl apply -f my-app-fixed.yaml

# Проверка снижения троттлинга (через 5 минут)
# PromQL: rate(container_cpu_cfs_throttled_seconds_total[5m])
# Ожидаемое значение: 0 или близко к 0

# Проверка Latency приложения
# PromQL: histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
# Ожидаемое значение: снижение p99 latency
```

**Cleanup:**
```bash
# Откат к предыдущей версии при необходимости
kubectl rollout undo deployment my-app
```

**Edge Cases:**
* Многопоточные приложения (Java, Go) могут троттлиться даже при низком среднем потреблении — из-за неравномерного распределения нагрузки по периодам CFS.
* При использовании `--cpu-cfs-quota=false` в Kubelet лимиты CPU игнорируются — приложение может потреблять неограниченно, рискуя создать "шумного соседа".
* Исторический баг CFS в ядрах < 5.4 вызывал избыточный троттлинг — обновите ядро узлов.

---

### Сценарий 4: Диагностика и устранение OOMKilled

**Задача:** Под постоянно перезапускается с ошибкой `OOMKilled` (код 137).

**Диагностика:**
```bash
# Шаг 1: Проверка статуса пода
kubectl get pod my-app-xxxxx
# NAME          READY   STATUS      RESTARTS   AGE
# my-app-xxxxx  0/1     OOMKilled   5          10m

# Шаг 2: Проверка предыдущего завершения
kubectl get pod my-app-xxxxx -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# {"containerID":"docker://xxx","exitCode":137,"finishedAt":"...",
#  "reason":"OOMKilled","startedAt":"..."}

# Шаг 3: Проверка лимитов памяти
kubectl get pod my-app-xxxxx -o jsonpath='{.spec.containers[].resources}'
# {"limits":{"cpu":"1000m","memory":"512Mi"},"requests":{"cpu":"500m","memory":"256Mi"}}

# Шаг 4: Проверка реального потребления
kubectl top pod my-app-xxxxx
# NAME          CPU(cores)   MEMORY(bytes)
# my-app-xxxxx  200m         510Mi    ← Близко к лимиту 512Mi

# Шаг 5: Проверка событий узла
kubectl get events --field-selector reason=OOMKilling --sort-by='.lastTimestamp'
```

**Решение:**
```yaml
# Вариант A: Увеличение лимита памяти (если приложение легитимно требует больше)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
      - name: app
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"    # Увеличен request
          limits:
            cpu: "1000m"
            memory: "1Gi"      # Увеличен limit
---
# Вариант B: Использование Guaranteed QoS для защиты
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
      - name: app
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"      # requests == limits → Guaranteed
          limits:
            cpu: "500m"
            memory: "1Gi"
```

**Валидация:**
```bash
# Применение исправления
kubectl apply -f my-app-fixed.yaml

# Мониторинг перезапусков (через 10-15 минут)
kubectl get pod -l app=my-app -w
# NAME                       READY   STATUS    RESTARTS   AGE
# my-app-6b7d8f9c4-xxxxx     1/1     Running   0          5m    ← RESTARTS не растет

# Проверка потребления памяти
kubectl top pod -l app=my-app
# NAME                       CPU(cores)   MEMORY(bytes)
# my-app-6b7d8f9c4-xxxxx     200m         400Mi    ← Ниже лимита
```

**Cleanup:**
```bash
# Откат к предыдущей версии при необходимости
kubectl rollout undo deployment my-app
```

**Edge Cases:**
* "Тихий OOM" (cgroups v2): ядро убивает дочерний процесс, а не PID 1 — контейнер не перезапускается, но работает некорректно. Проверяйте логи приложения.
* Утечка памяти в sidecar-контейнере (Istio, Fluent Bit) может вызывать OOMKilled всего пода — устанавливайте лимиты для всех контейнеров.
* Java-приложения: Heap может расти сверх `limits.memory` из-за нативной памяти (метаданные классы, стеки потоков) — оставляйте запас 20-30%.

---

### Сценарий 5: Использование VPA для подбора оптимальных requests/limits

**Задача:** Автоматически определить оптимальные значения `requests` и `limits` для приложения на основе истории потребления.

**Решение:**
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Off"    # Режим рекомендаций без автоматического применения
  resourcePolicy:
    containerPolicies:
    - containerName: '*'
      minAllowed:
        cpu: "100m"
        memory: "128Mi"
      maxAllowed:
        cpu: "4000m"
        memory: "8Gi"
```

**Валидация:**
```bash
# Установка VPA (через kubectl apply -f vpa.yaml или helm)
kubectl apply -f vpa.yaml

# Проверка рекомендаций (через несколько часов сбора данных)
kubectl describe vpa my-app-vpa
# Recommendation:
#    Container Recommendations:
#      Container Name:  api
#      Lower Bound:
#        Cpu:     250m
#        Memory:  262144000
#      Target:
#        Cpu:     500m        ← Рекомендуемый request
#        Memory:  512Mi       ← Рекомендуемый request
#      Uncapped Target:
#        Cpu:     500m
#        Memory:  512Mi
#      Upper Bound:
#        Cpu:     1000m
#        Memory:  1Gi

# Применение рекомендаций вручную
kubectl patch deployment my-app --patch \
  '{"spec":{"template":{"spec":{"containers":[{"name":"api","resources":{"requests":{"cpu":"500m","memory":"512Mi"},"limits":{"cpu":"2000m","memory":"1Gi"}}}]}}}}'
```

**Cleanup:**
```bash
kubectl delete vpa my-app-vpa
# → verticalpodautoscaler.autoscaling.k8s.io "my-app-vpa" deleted
```

**Edge Cases:**
* VPA в режиме `Auto` может вызывать частые перезапуски подов — используйте `Off` или `Initial` для Production.
* VPA не работает корректно с HPA на одних и тех же метриках — используйте разные метрики или только один автоскейлер.
* При использовании In-Place Pod Resize (1.31+) VPA может применять изменения без перезапуска.

---

### Сценарии на собеседованиях: Бесконечное количество подов

Этот гипотетический вопрос проверяет знание механизмов управления ресурсами, планирования и лимитов кластера.

**Неправильный ответ:** «Kubernetes упадет» или «Это технически невозможно». Эти ответы упускают возможность показать знание внутренних механизмов.

**Правильный подход:**
1.  **Физические ограничения:** Признайте, что создание бесконечного количества подов невозможно из-за физических ограничений ресурсов кластера (CPU, память) и доступности узлов. Каждый под потребляет часть этих ресурсов для работы.
2.  **Механизмы предотвращения истощения:**
    *   **Resource Quotas:** На практике Kubernetes предотвращает истощение ресурсов с помощью квот. На уровне Namespace `ResourceQuota` жестко ограничивает максимальное количество подов и суммарный объем ресурсов.
    *   **Limit Ranges:** Задают лимиты по умолчанию и ограничения на минимальные/максимальные значения, предотвращая запуск подов с некорректными аппетитами.
3.  **Поведение планировщика:** Если запрос на создание пода превышает доступные ресурсы, `kube-scheduler` не сможет разместить его на узле. Под перейдет в состояние **`Pending` (Ожидание)**. Планировщик будет постоянно пытаться их выделить, но будет ограничен имеющимися ресурсами.
4.  **Автомасштабирование и его пределы:**
    *   **HPA (Horizontal Pod Autoscaler):** Масштабирует поды на основе метрик, но только до заданного в манифесте `maxReplicas`.
    *   **Cluster Autoscaler:** Может добавлять новые узлы в кластер при наличии `Pending` подов, но его возможности ограничены лимитами облачной инфраструктуры или физического оборудования.
5.  **Влияние на производительность и стабильность:**
    *   Постоянные попытки планирования огромного числа подов создают нагрузку на API-сервер и etcd.
    *   В реальном сценарии исчерпание ресурсов узлов может привести к деградации производительности кластера и массовым выселениям (Evictions) менее приоритетных подов.

**Резюме:** Попытка создания бесконечных подов будет предотвращена встроенными механизмами ограничений Kubernetes, а лишние запросы останутся незапланированными в состоянии ожидания.

### Проверка текущего состояния ресурсов

```bash
# Узнать QoS-класс пода
kubectl get pod <name> -o jsonpath='{.status.qosClass}'

# Просмотр реально выделенных ресурсов (учитывая In-Place Resize)
kubectl get pod <name> -o jsonpath='{.status.containerStatuses[0].allocatedResources}'

# Вывод подов, потребляющих больше своих запросов (кандидаты на выселение)
kubectl top pods -A --sort-by=memory
```

### Пример Guaranteed пода с GPU и HugePages

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: heavy-ml-workload
spec:
  containers:
  - name: trainer
    image: training-app:latest
    resources:
      requests:
        cpu: "4"           # Целое число для Static CPU Policy
        memory: "16Gi"
        nvidia.com/gpu: 1  # Расширенный ресурс (req == limit автоматически)
        hugepages-2Mi: "1Gi"
      limits:
        cpu: "4"
        memory: "16Gi"
        nvidia.com/gpu: 1
        hugepages-2Mi: "1Gi"
```

### Использование LimitRange для контроля QoS

`LimitRange` позволяет автоматически превращать все поды в `Burstable` или `Guaranteed`, если разработчики забыли указать ресурсы.

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: mem-limit-range
spec:
  limits:
  - default:
      memory: "512Mi"  # Автоматический лимит
    defaultRequest:
      memory: "256Mi"  # Автоматический запрос
    type: Container
```

### ResourceQuota: Ограничение суммарных лимитов

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-resources
spec:
  hard:
    requests.cpu: "10"
    requests.memory: "20Gi"
    limits.cpu: "20"
    limits.memory: "40Gi"
```

---

## Дополнительная информация

### Диагностика и мониторинг

#### Проверка текущего состояния ресурсов

```bash
# Узнать QoS-класс пода
kubectl get pod <name> -o jsonpath='{.status.qosClass}'
# → Guaranteed

# Просмотр реально выделенных ресурсов (учитывая In-Place Resize)
kubectl get pod <name> -o jsonpath='{.status.containerStatuses[0].allocatedResources}'
# {"cpu":"500m","memory":"512Mi"}

# Вывод подов, потребляющих больше своих запросов (кандидаты на выселение)
kubectl top pods -A --sort-by=memory
# NAMESPACE     NAME          CPU(cores)   MEMORY(bytes)
# production    my-app-xxxxx  800m         1024Mi

# Проверка распределения подов по узлам
kubectl top nodes
# NAME   CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# node1  3500m        87%    12Gi            75%

# Проверка использования ResourceQuota
kubectl describe quota -n <namespace>
```

#### Мониторинг в Prometheus

**Ключевые метрики:**
```promql
# Потребление CPU контейнерами
rate(container_cpu_usage_seconds_total[5m])

# CPU Throttling — количество периодов дросселирования
rate(container_cpu_cfs_throttled_periods_total[5m])

# Потребление памяти (Working Set)
container_memory_working_set_bytes

# Доступные ресурсы узла для планирования
kube_node_status_allocatable{resource="cpu"}

# Использование ResourceQuota
kube_resourcequota{type="used", resource="cpu"}
kube_resourcequota{type="hard", resource="cpu"}
```

**Алерты:**
```yaml
# Алерт на CPU Throttling
- alert: CPUThrottling
  expr: rate(container_cpu_cfs_throttled_periods_total[5m]) > 0.5
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Контейнер {{ $labels.container }} троттлируется"

# Алерт на приближение к OOM
# Основан на сравнении Working Set с лимитом
# Требует настройки через kube-state-metrics и recording rules
```

---

### Troubleshooting

#### Проблема: Поды зависли в Pending из-за нехватки ресурсов

**Диагностика:**
```bash
# Шаг 1: Проверка событий пода
kubectl describe pod <pod-name> | grep -A 10 "Events:"
# Warning  FailedScheduling  0/5 nodes are available:
# 5 Insufficient cpu/memory

# Шаг 2: Проверка Allocatable на узлах
kubectl get nodes -o custom-columns=\
NAME:.metadata.name,ALLOC_CPU:.status.allocatable.cpu,ALLOC_MEM:.status.allocatable.memory

# Шаг 3: Проверка текущего потребления
kubectl top nodes
```

**Решения:**
1. Уменьшите `requests` пода, если они завышены.
2. Добавьте узлы в кластер или используйте Cluster Autoscaler.
3. Освободите ресурсы — удалите неиспользуемые поды или увеличьте квоты.

#### Проблема: CPU Throttling при низкой утилизации

**Диагностика:**
```bash
# Проверка метрик троттлинга
# PromQL: rate(container_cpu_cfs_throttled_seconds_total[5m]) > 0

# Проверка через cgroup на узле
cat /sys/fs/cgroup/cpu/kubepods/pod<pod-id>/cpu.stat
# nr_throttled: 100    ← Проблема
```

**Решения:**
1. Увеличьте `limits.cpu` или полностью уберите лимит (bursting pattern).
2. Проверьте количество потоков приложения — многопоточные приложения требуют пропорционально больше лимита.
3. Обновите ядро узлов до версии 5.4+ (исправляет баг CFS).

#### Проблема: OOMKilled при стабильной нагрузке

**Диагностика:**
```bash
# Проверка истории перезапусков
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# {"reason":"OOMKilled","exitCode":137,...}

# Проверка лимита vs потребление
kubectl top pod <pod-name>
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[].resources.limits.memory}'
```

**Решения:**
1. Увеличьте `limits.memory` с запасом 20-30% для Java-приложений (нативная память).
2. Проверьте sidecar-контейнеры — они могут потреблять память сверх ожидаемого.
3. Используйте VPA для определения реальных потребностей.

#### Проблема: ResourceQuota блокирует создание подов

**Диагностика:**
```bash
# Проверка использования квоты
kubectl describe quota -n <namespace>
# Resource    Used   Hard
# requests.cpu  19    20    ← Почти исчерпана

# Проверка событий
kubectl get events --field-selector reason=FailedCreate
# exceeded quota: team-quota, requested: requests.cpu=500m
```

**Решения:**
1. Увеличьте квоту: `kubectl edit quota <name> -n <namespace>`.
2. Уменьшите `requests` существующих подов.
3. Удалите неиспользуемые ресурсы.

---

### Стратегии и лучшие практики

1. **Burstable — стандарт индустрии.** Устанавливайте `requests` на уровне реального среднего потребления, а `limits` — с запасом под пики. Это позволяет Kubernetes переподписывать (overcommit) ресурсы узла, экономя деньги.

2. **CPU Requests без Limits (Bursting).** Современная лучшая практика для многих рабочих нагрузок — устанавливать `requests.cpu`, но оставлять `limits.cpu` пустым. Это позволяет приложению кратковременно использовать свободные ресурсы узла и избегать троттлинга при резких скачках нагрузки.
   - *Исключение:* Для критически важных приложений (Latency-sensitive) лучше устанавливать `requests` и `limits` равными (QoS Guaranteed) для максимально предсказуемой производительности.

3. **Guaranteed — для "тяжелых" сервисов.** Используйте для БД, Java-приложений с большим Heap, и Latency-sensitive API. Это дает предсказуемость и защиту от "шумных соседей".

4. **Никогда не оставляйте память без лимитов.** CPU throttling замедляет сервис, но OOMKill из-за отсутствия лимитов памяти может положить весь узел, если процесс начнет бесконтрольно расти.

5. **Requests и HPA.** `HorizontalPodAutoscaler` рассчитывает загрузку в процентах от `requests`. Если вы установите `requests` слишком низко, HPA будет постоянно создавать новые реплики, даже если реальной нагрузки нет.

6. **VPA для подбора значений.** Используйте `VerticalPodAutoscaler` в режиме `Recommendation`, чтобы узнать реальные аппетиты вашего приложения в течение недели, и затем скорректируйте манифесты.

7. **In-Place Resize для минимизации простоев.** При обновлении лимитов в Production используйте возможности Kubernetes 1.35+, чтобы избежать рестарта контейнеров и сброса кэшей.

8. **Мониторинг и алертинг.** Настройте алерты на:
   * CPU Throttling > 0 в течение 10 минут
   * Memory Usage > 80% от limit
   * ResourceQuota Usage > 80% от hard
   * Количество OOMKilled подов > 0

9. **Документирование ресурсов.** Ведите реестр используемых `requests`/`limits` для каждого сервиса. Это помогает при планировании capacity и расследовании инцидентов.

10. **Тестирование нагрузкой.** Проводите нагрузочное тестирование перед установкой лимитов в Production. Используйте инструменты (k6, Locust) для определения реальных потребностей.

---

### Поведение при нехватке ресурсов (Сводка)

* **CPU Limit exceeded:** Throttling (замедление, процесс заставляют ждать).
* **Memory Limit exceeded:** OOMKill контейнера (немедленный рестарт).
* **Ephemeral Storage Limit exceeded:** Pod Eviction (удаление и пересоздание на другом узле).
* **Node Pressure:** Kubelet выселяет поды по цепочке `BestEffort` -> `Burstable (over req)` -> `Burstable (under req)` -> `Guaranteed`.

---

### См. также

* [Диагностика OOMKilled](../Troubleshooting/Common_Errors/oomkilled_pods.md) — пошаговое руководство по решению проблем с памятью.
* [CPU Throttling](../Troubleshooting/Common_Errors/cpu_throttling.md) — детальный разбор механизма CFS и диагностики троттлинга.
* [OOM Killer в контейнерах](../../Linux/Core/processes/oom_killer_containers.md) — глубокое погружение в механизмы ядра Linux.
* [Pod Evicted](../../Kubernetes/Troubleshooting/Common_Errors/PodEvicted/definitions.md) — типы и причины выселения подов.
* [PriorityClass](../Concepts/priorityclass.md) — управление приоритетами планирования.
* [Affinity и Anti-Affinity](./affinity.md) — правила размещения подов для высокой доступности.
* [In-Place Pod Resize](../Autoscaling/in_place_pod_resize.md) — изменение ресурсов без перезапуска.
* [Горячий старт Java-приложений](./java-startup-cpu-boost.md) — динамические CPU-лимиты на время старта (Kyverno + In-Place Resize).
* [HPA](../Autoscaling/HPA/index.md) — горизонтальное автомасштабирование подов.
