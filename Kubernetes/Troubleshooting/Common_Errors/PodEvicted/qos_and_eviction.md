# Выселение подов: Классы QoS и работа Менеджера выселения

## Определения

**Менеджер выселения (Eviction Manager)** — программный модуль в составе `kubelet`, который непрерывно (по умолчанию каждые 10 секунд) отслеживает использование системных ресурсов (RAM, Disk, PID) на узле и инициирует принудительное завершение подов при достижении критических порогов (`evictionHard` или `evictionSoft`). Метрики собираются через `cAdvisor` (встроен в `kubelet`).

**Класс QoS (Quality of Service)** — категория приоритетности пода, определяемая автоматически на основе его запросов (`requests`) и лимитов (`limits`). QoS напрямую влияет на значение `oom_score_adj` и очередность выселения при нехватке памяти. Класс присваивается **всему поду**, а не отдельным контейнерам.

**Рабочий набор памяти (Working set memory)** — объем памяти (RSS + активный кэш), используемый `kubelet` для оценки реального потребления. Включает в себя страницы, которые не могут быть немедленно сброшены ядром.
Подробнее: **[Выселение по памяти: Расчет доступной памяти](./memory_eviction.md#расчет-доступной-памяти-в-kubelet)**.

**oom_score_adj** — интерфейс ядра Linux (диапазон от -1000 до 1000), через который `kubelet` управляет вероятностью завершения процесса системным OOM Killer. Значение пересчитывается при каждом запуске контейнера на основе класса QoS пода.

**Приоритет пода (Pod Priority)** — числовой вес, задаваемый через `PriorityClass`. В современных версиях Kubernetes приоритет является первичным фактором ранжирования перед QoS **при вытеснении (preemption)**. При **выселении (eviction)** из-за нехватки ресурсов на узле приоритет QoS является основным критерием.

**Вытеснение (Preemption)** — механизм планировщика (`kube-scheduler`), при котором высокоприоритетный под вытесняет низкоприоритетный, чтобы освободить место. Работает на основе `PriorityClass`, а **не** QoS. Под `BestEffort` с высоким приоритетом **может** вытеснить под `Guaranteed` с низким приоритетом.

**ResourceQuota с QoS-сферами (scopes)** — позволяет ограничивать количество подов определенного класса QoS в namespace. Например, `scope: BestEffort` ограничивает количество BestEffort подов, чтобы предотвратить переуплотнение кластера некритичными задачами.

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Иерархия ранжирования кандидатов на выселение

При возникновении `MemoryPressure` или `DiskPressure` `kubelet` формирует очередь на выселение. В отличие от планировщика, `kubelet` при выселении учитывает не только приоритет, но и реальное потребление ресурсов относительно запросов.

Алгоритм ранжирования (в порядке убывания значимости):
1.  **Потребление сверх запросов:** Поды, чей фактический расход (`usage`) превышает их `requests`. Поды, не превышающие `requests`, выселяются в последнюю очередь.
2.  **Приоритет (Pod Priority):** Среди нарушителей лимитов первыми выселяются поды с наименьшим приоритетом.
3.  **Относительное превышение:** Степень превышения `requests` относительно емкости узла.

### Классы QoS и настройка oom_score_adj

Kubernetes транслирует бизнес-логику приоритетов QoS в ядро Linux через `oom_score_adj`. Это гарантирует, что системный OOM Killer будет убивать те же процессы, которые `kubelet` выбрал бы для выселения.

| Класс QoS | Описание ресурсов | `oom_score_adj` | Очередность выселения | Защита от OOMKilled |
|:---|:---|:---|:---|:---|
| **BestEffort** | нет `requests` и `limits` | `1000` | Первая | Нет (убиваются первыми) |
| **Burstable** | `requests` < `limits` | `2` — `999` | Вторая | Защита до уровня `requests` |
| **Guaranteed** | `requests` == `limits` | `-997` | Последняя | Максимальная защита |

**Формула расчета для Burstable:**
Для подов класса `Burstable` значение `oom_score_adj` вычисляется динамически на основе доли зарезервированной памяти:
`oom_score_adj = min(max(2, 1000 - (1000 * memory_requests) / memory_capacity), 999)`
*Чем больше `requests`, тем ниже `oom_score_adj` и тем выше шансы процесса выжить при системном OOM.*

> **Технический нюанс:** Системные процессы (`kubelet`, `containerd`, `docker`) имеют `oom_score_adj = -999`, что делает их практически неуязвимыми для OOM Killer. Это важно понимать: даже `Guaranteed` поды будут убиты раньше, чем `kubelet`.

### Определение класса QoS пода

Kubernetes определяет QoS на основе ресурсов **каждого контейнера** в поде:

```
Guaranteed:
  Для КАЖДОГО контейнера: requests.cpu == limits.cpu
  И для КАЖДОГО контейнера: requests.memory == limits.memory

BestEffort:
  Для КАЖДОГО контейнера: нет requests И нет limits

Burstable:
  Все остальные (один из контейнеров имеет requests != limits)
```

**Критическое правило для multi-container подов:**
QoS определяется по **"самому слабому звену"**. Если один контейнер в поде `Guaranteed`, а второй — `BestEffort`, весь под станет `Burstable`. Это важно учитывать при конфигурации sidecar'ов.

**Пример:**
```yaml
spec:
  containers:
  - name: app           # requests: 256Mi, limits: 512Mi → Burstable
  - name: sidecar       # requests: 64Mi, limits: 64Mi  → Guaranteed
# Результат: Burstable (min по контейнерам)
```

**Автоматическое назначение `requests` из `limits`:**
*   Если указан `limits.cpu`, но не указан `requests.cpu` → `requests.cpu = limits.cpu` (автоматически).
*   Если указан `limits.memory`, но не указан `requests.memory` → `requests.memory` **не** устанавливается (остается `0`, что ведет к `Burstable`).

> Это источник распространенной ошибки: разработчик указывает `limits: {memory: 512Mi}`, но забывает `requests`, и под оказывается в классе `Burstable` вместо `Guaranteed`.

### Ранжирование внутри классов

#### 1. Класс BestEffort
Поды этого класса не имеют резервации. `kubelet` сортирует их по абсолютному объему потребляемого рабочего набора памяти (`working set memory`). Выселяется тот, кто потребляет больше всего.

#### 2. Класс Burstable
Выбор происходит на основе того, насколько сильно под нагружает узел сверх того, что он обещал потреблять.
**Метрика:** `(Usage - Requests) / Capacity`.
Выселяется под, у которого это отношение максимально. Это защищает поды, которые потребляют меньше своих `requests`, даже если их приоритет ниже.

**Порядок внутри Burstable:**
1.  Поды, превышающие `requests` (нарушители лимитов).
2.  Поды, не превышающие `requests`, но потребляющие больше минимального.

#### 3. Класс Guaranteed
Выселяются крайне редко, обычно когда системные процессы требуют освобождения ресурсов, а других подов не осталось. Ранжирование идет по абсолютному потреблению (аналогично `BestEffort`).

### Алгоритм работы Менеджера выселения

1.  **Мониторинг:** `kubelet` собирает метрики через `cAdvisor` каждые 10 секунд.
2.  **Триггер:** Ресурсы падают ниже жесткого порога (`evictionHard`).
3.  **Сортировка:** Создается список кандидатов на основе Priority, QoS и формул превышения.
4.  **Сигналы завершения:**
    *   **Hard Eviction:** Поду отправляется `SIGKILL`. Поле `terminationGracePeriodSeconds` полностью игнорируется.
    *   **Soft Eviction:** Поду отправляется `SIGTERM`. Дается время `min(pod_grace, eviction_max_grace)`.
5.  **Верификация:** `kubelet` ожидает освобождения ресурсов и повторяет цикл, если давление сохраняется.

**Важные нюансы:**
*   Если ресурсы не освободились после `SIGTERM`, `kubelet` отправляет `SIGKILL` через время `evictionSoftGracePeriod`.
*   `kubelet` **не** может выселить под, защищенный `PodDisruptionBudget`, при **мягком** (soft) выселении. При **жестком** (hard) выселении PDB игнорируется.
*   После завершения пода `kubelet` ожидает освобождения ресурсов и, если ситуация не стабилизировалась, повторяет процесс с новым циклом ранжирования.

### Различия между Preemption и Kubelet Eviction

| Характеристика | Preemption (Вытеснение) | Eviction (Выселение) |
|:---|:---|:---|
| **Инициатор** | `kube-scheduler` | `kubelet` |
| **Причина** | Высокоприоритетный под не помещается | Нехватка ресурсов на узле |
| **Критерий** | Только `PriorityClass` | QoS + потребление |
| **PDB** | Учитывается (но может быть нарушен) | Soft: учитывается; Hard: игнорируется |
| **Сигнал** | `SIGTERM` (через `Deletion`) | `SIGTERM` (Soft) или `SIGKILL` (Hard) |
| **Порядок** | По приоритету (low → high) | BestEffort → Burstable → Guaranteed |

### ResourceQuota и QoS-сферы (scopes)

ResourceQuota может ограничивать количество подов по классу QoS:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: besteffort-quota
  namespace: dev
spec:
  hard:
    pods: "10"
  scopeSelector:
    matchExpressions:
    - scopeName: BestEffort
      operator: In
    - scopeName: NotBestEffort
      operator: DoesNotContain
```

**Поддерживаемые сферы (scopes):**
*   `BestEffort` — только BestEffort поды.
*   `NotBestEffort` — Burstable и Guaranteed.
*   `PriorityClass` — по значению приоритета.
*   `CrossNamespacePodAffinity` — по кросс-неймспейсной аффинити.

> Подробнее: **[Управление ресурсами: QoS](../../Scheduling/qos_limit_and_requests.md)**.

### In-Place Pod Resize и QoS (GA 1.35)

При изменении `requests`/`limits` запущенного пода QoS **не пересчитывается** автоматически:
*   Если под был создан как `Burstable`, он останется `Burstable`, даже если вы попытаетесь выровнять его `requests` и `limits` (что для нового пода дало бы `Guaranteed`).
*   Для получения нового QoS необходимо пересоздать под.

> Подробнее: **[In-Place Pod Resize](../../Autoscaling/in_place_pod_resize.md)**.

### CPU Manager Policy и QoS

Для получения **эксклюзивной привязки к физическим ядрам CPU** (CPU Pinning) под обязан:
1.  Принадлежать к классу `Guaranteed`.
2.  Запрашивать `requests.cpu` **целым числом** (например, `2`, `4`).
3.  В kubelet настроено `cpuManagerPolicy: static`.

> Подробнее: **[CPU Manager Policy](../../Scheduling/qos_limit_and_requests.md#static-cpu-manager-policy)**.

## Практические сценарии

### 1. Проверка QoS и oom_score_adj (SSH)

Чтобы подтвердить, что под классифицирован верно и защищен ядром:

```bash
# 1. Проверка класса через kubectl
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
# → Guaranteed

# 2. Проверка oom_score_adj процесса на узле
# Находим PID (например, через crictl inspect)
PID=$(crictl inspect <container-id> | jq -r .info.pid)
cat /proc/<PID>/oom_score_adj
# → -997 (Guaranteed) или 1000 (BestEffort)

# 3. Проверка через crictl
crictl inspect <container-id> | jq '.info.pid'
# Далее cat /proc/<PID>/oom_score_adj
```

### 2. Анализ очереди на выселение (Ranking)

В случае массового выселения можно увидеть логику `kubelet` в системном журнале:

```bash
# Логи о начале выделения ресурсов
journalctl -u kubelet | grep -E "eviction manager: (attempting|reclaim)"

# Логи о ранжировании подов
journalctl -u kubelet -g "eviction manager: ranking pods"

# Логи о конкретном выселении
journalctl -u kubelet | grep -E "eviction manager: (evicting|evicted)"
# → eviction manager: evicting pod <pod-name> (disk) due to node pressure
```

**Пример лога ранжирования:**
```
eviction manager: attempting to reclaim memory
eviction manager: node stats: available 52428800 capacity 33554432000
eviction manager: pod <besteffort-pod> is evicted because it exceeds its memory request
eviction manager: pod <burstable-pod> is evicted because it uses more memory than its request
eviction manager: no more evictions needed
```

### 3. Проверка class через kubectl с форматированием

```bash
# Все поды с указанием класса QoS
kubectl get pods -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,QOS:.status.qosClass,NODE:.spec.nodeName"

# Поды BestEffort (без requests и limits)
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.containers[] | (.resources.requests == null and .resources.limits == null)) | "\(.metadata.namespace)/\(.metadata.name)"'

# Поды, у которых requests != limits (Burstable)
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.containers[] | (.resources.requests.memory != .resources.limits.memory and .resources.requests.memory != null and .resources.limits.memory != null)) | "\(.metadata.namespace)/\(.metadata.name) req=\(.spec.containers[0].resources.requests.memory) lim=\(.spec.containers[0].resources.limits.memory)"'
```

### 4. Диагностика через DisruptionTarget (K8s 1.31+)

Если под был выселен, в его `status.conditions` появится условие `DisruptionTarget`. Оно позволяет точно отличить выселение из-за нехватки ресурсов на узле от других причин.

```bash
# Проверка условия DisruptionTarget
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → reason: EvictionByKubelet
# → message: Pod was evicted due to node pressure: MemoryPressure

# Проверка типа выселения
kubectl get pods -A -o json | jq -r '.items[] | select(.status.conditions[]? | select(.type=="DisruptionTarget")) | "\(.metadata.namespace)/\(.metadata.name): \(.status.reason) - \(.status.message)"'
```

### 5. Мониторинг и алерты

```promql
# Количество подов по классам QoS
count by (namespace, qos) (kube_pod_status_qos_class)

# Поды, приближающиеся к лимиту памяти
container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9

# Выселения за последние 24 часа
increase(kube_pod_status_reason{reason="Evicted"}[24h])

# MemoryPressure на узлах
kube_node_status_condition{condition="MemoryPressure", status="true"} == 1

# OOMKilled поды
increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[1h])

# Top подов по потреблению памяти (для поиска кандидатов на выселение)
topk(10, container_memory_working_set_bytes{container!=""})
```

**Алерты Prometheus:**
```yaml
# Предупреждение: BestEffort поды в production namespace
- alert: BestEffortPodsInProduction
  expr: count by (namespace) (kube_pod_status_qos_class{namespace="production", qos="BestEffort"}) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "BestEffort поды в production namespace: {{ $labels.namespace }}"

# Предупреждение: Mass eviction
- alert: MassEvictionDetected
  expr: increase(kube_pod_status_reason{reason="Evicted"}[1h]) > 5
  labels:
    severity: warning
  annotations:
    summary: "Массовое выселение: {{ $value }} подов за час"

# Критическое: Количество Guaranteed подов падает
- alert: GuaranteedPodsDecreasing
  expr: delta(kube_pod_status_qos_class{qos="Guaranteed"}[1h]) < -2
  labels:
    severity: critical
  annotations:
    summary: "Количество Guaranteed подов уменьшилось на {{ $value }}"
```

### 6. Проверка ResourcQuota и QoS scopes

```bash
# Проверка квот по QoS scopes
kubectl get resourcequota -n dev -o yaml

# Проверка, сколько BestEffort подов в namespace
kubectl get pods -n dev -o json | jq '[.items[] | select(.status.qosClass == "BestEffort")] | length'

# Проверка квоты на поды
kubectl describe resourcequota -n dev
# → Name: besteffort-quota
# → Resource                   Used  Hard
# → --------                   ----  ----
# → pods                       7     10
```

## Дополнительная информация

### Сводная таблица механизмов защиты

| Угроза | BestEffort | Burstable | Guaranteed |
|:---|:---|:---|:---|
| **Node-Pressure Eviction** | Выселяются первыми | Вторые (при превышении requests) | Последние |
| **OOMKilled** | `oom_score_adj: 1000` | `oom_score_adj: 2-999` | `oom_score_adj: -997` |
| **API Eviction (Drain)** | Соблюдение PDB | Соблюдение PDB | Соблюдение PDB |
| **Preemption** | Зависит от Priority | Зависит от Priority | Зависит от Priority |
| **CPU Throttling** | Да | Да | Нет (при static policy) |
| **Memory QoS (cgroup v2)** | Без резерва | `memory.high` throttle | `memory.min` гарантирован |

### Рекомендации по выживанию подов

1.  **Минимизация BestEffort:** В продуктивной среде всегда указывайте `requests`. Без них планировщик считает, что под не потребляет ресурсов, что ведет к переуплотнению (overcommit) узла.
2.  **Запросы на уровне среднего:** Устанавливайте `requests.memory` на уровне реального среднего потребления. Это обеспечит защиту пода от выселения в большинстве ситуаций.
3.  **Использование PriorityClass:** Для критических компонентов (Ingress, Monitoring) используйте высокие приоритеты, чтобы они выселялись в последнюю очередь даже внутри своих QoS-классов.
4.  **Soft Eviction для данных:** Настраивайте мягкое выселение с достаточным `evictionSoftGracePeriod` для приложений, которым нужно время на сброс кэшей или корректное завершение транзакций.
5.  **Guaranteed для latency-sensitive:** Используйте `requests == limits` для приложений, чувствительных к jitter и переключению контекста (БД, очереди сообщений, API).
6.  **Учет sidecar'ов:** Помните, что sidecar-контейнеры (Envoy, Fluent-bit) влияют на QoS пода. Если sidecar не имеет `limits`, под станет `Burstable`.
7.  **ResourceQuota с scopes:** Ограничивайте количество BestEffort подов в namespace через ResourceQuota, чтобы предотвратить "пожирание" ресурсов некритичными задачами.

### Типичные ошибки при настройке QoS

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| Указан `limits.memory`, но не `requests.memory` | Под становится `Burstable` вместо `Guaranteed` | Указывайте `requests` явно или используйте LimitRange |
| Sidecar без `limits` | Весь под становится `Burstable` | Добавьте `limits` для sidecar'ов |
| `requests` значительно ниже реального потребления | Под переуплотняет узел, другие поды выселяются | Устанавливайте `requests` на уровне среднего потребления |
| BestEffort в production | Первый кандидат на выселение при любом давлении | Всегда указывайте `requests` для production подов |
| Игнорирование QoS при выборе PriorityClass | `BestEffort` с высоким приоритетом вытесняет `Guaranteed` с низким | Учитывайте QoS при назначении PriorityClass |

### Смотрите также

* **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
* **[Выселение по памяти](./memory_eviction.md)** — расчет Working Set и метрики cgroups.
* **[Управление ресурсами: QoS](../../Scheduling/qos_limit_and_requests.md)** — полный обзор классов ресурсов и автоматическое назначение requests.
* **[Разбор ошибки OOMKilled](../oomkilled_pods.md)** — когда лимиты превышены.
* **[PriorityClass и вытеснение](../../Concepts/priorityclass.md)** — различия между Preemption и Eviction.
* **[CPU Manager Policy](../../Scheduling/qos_limit_and_requests.md#static-cpu-manager-policy)** — эксклюзивная привязка к ядрам CPU.
* **[In-Place Pod Resize](../../Autoscaling/in_place_pod_resize.md)** — изменение ресурсов без перезапуска.
* **[Descheduler](../../Operations/node_maintenance.md)** — автоматическое перераспределение подов при давлении.
