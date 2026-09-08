# Pod Evicted: Определения и концепции

## Определения

**`Evicted` (Выселен)** — терминальное состояние пода (фаза `Failed`), означающее, что Kubernetes принудительно прекратил его выполнение на узле. Выселение не является ошибкой самого приложения, а представляет собой защитный механизм кластера или результат административных действий.

**Менеджер выселения (Eviction Manager)** — программный модуль в составе `kubelet`, отвечающий за поддержание стабильности узла. Он непрерывно (каждые 10 секунд по умолчанию) собирает метрики потребления ресурсов через `cAdvisor` и сравнивает их с порогами. При достижении критических значений `Eviction Manager` формирует очередь кандидатов на выселение на основе класса QoS, приоритета пода и степени превышения ресурсов.

**Порог выселения (Eviction Threshold)** — конфигурационный параметр `kubelet`, определяющий лимит ресурсов, при достижении которого узел считается перегруженным.
*   **Ресурсы:** `memory.available`, `nodefs.available`, `nodefs.inodesFree`, `imagefs.available`, `imagefs.inodesFree`, `pid.available`.
*   **Типы порогов:** Hard (немедленное выселение по SIGKILL) и Soft (выселение после grace period по SIGTERM).
*   **Настройка:** Задаются в `KubeletConfiguration` (`/var/lib/kubelet/config.yaml`) или через CLI-флаги `--eviction-hard` и `--eviction-soft`.

**Eviction API** — часть Kubernetes API (`policy/v1`), позволяющая приложениям и контроллерам запрашивать "вежливое" выселение подов. Этот API является основой для работы команды `kubectl drain` и контроллеров автоматизации (например, `Descheduler`). В отличие от прямого `kubectl delete`, `Eviction API` учитывает `PodDisruptionBudget` и может быть отклонен API-сервером.

**cAdvisor** — встроенный агент в `kubelet`, который собирает метрики потребления ресурсов (CPU, память, файловая система, сеть) для всех контейнеров на узле. Данные `cAdvisor` используются `Eviction Manager` для принятия решений о выселении.

**Ресурсы (Incompressible vs Compressible)** — типы ресурсов, определяющие реакцию системы на дефицит:
*   **Несжимаемые (Incompressible):** Память (RAM), дисковое пространство, PID. Дефицит приводит к выселению подов.
*   **Сжимаемые (Compressible):** CPU. Дефицит приводит к Throttling (замедлению), но не к выселению.

## Основные концепции

### Классификация механизмов выселения

Процесс выселения может инициироваться на разных уровнях кластера:

| Тип | Инициатор | Триггер | Учет PDB | Grace Period |
|:---|:---|:---|:---|:---|
| **Node-Pressure** | `kubelet` | Критическая нехватка ресурсов (RAM, Disk, PID) | **Нет** | Зависит от типа (Hard/Soft) |
| **API-Initiated** | Пользователь / скрипт | Запрос через API (`kubectl drain`) | **Да** | `terminationGracePeriodSeconds` |
| **Taint-Based** | `Control Plane` | Сбой узла (Taint `NoExecute`) | **Нет** | `tolerationSeconds` |
| **Preemption** | `Scheduler` | Необходимость запустить приоритетный под | Старается | Обычно до 30s |

### Жесткое (Hard) и Мягкое (Soft) выселение

Режимы работы `Eviction Manager` при нехватке ресурсов:

1.  **Hard Eviction (`eviction-hard`)**:
    *   **Приоритет:** Стабильность узла важнее данных приложения.
    *   **Действие:** Поду отправляется сигнал `SIGKILL`.
    *   **Таймаут:** `terminationGracePeriodSeconds` полностью игнорируется.
    *   **По умолчанию:** `memory.available<100Mi`, `nodefs.available<10%`.
2.  **Soft Eviction (`eviction-soft`)**:
    *   **Приоритет:** Корректное завершение работы приложения.
    *   **Действие:** Поду отправляется сигнал `SIGTERM`.
    *   **Таймаут:** Соблюдается время `eviction-soft-grace-period`. Если порог превышен дольше этого времени, под удаляется.
    *   **Преимущество:** Позволяет игнорировать кратковременные всплески нагрузки.

**Важно:** Если `evictionHard` и `evictionSoft` наложены на один и тот же ресурс (например, `memory.available`), жесткий порог имеет приоритет и `soft` игнорируется для этого ресурса.

### Состояния узла (Node Conditions)

При достижении порогов `kubelet` помечает узел соответствующим состоянием, что запрещает планировщику (`kube-scheduler`) назначать на него новые поды (кроме критических).

*   **`MemoryPressure`**: Доступная память узла (Capacity - WorkingSet) ниже порога.
    *   **Причина:** Критическая нехватка оперативной памяти.
    *   **Последствие:** На узел накладывается taint `node.kubernetes.io/memory-pressure:NoSchedule`.
    *   **Действие:** Новые поды не планируются, пока ситуация не стабилизируется.
*   **`DiskPressure`**: Свободное место или `inodes` на основной ФС или ФС образов ниже порога.
    *   **Причина:** Переполнение дискового пространства или исчерпание inodes.
    *   **Последствие:** На узел накладывается taint `node.kubernetes.io/disk-pressure:NoSchedule`.
    *   **Действие:** `kubelet` запускает Garbage Collection (очистку образов и контейнеров) перед выселением.
*   **`PIDPressure`**: Исчерпан лимит идентификаторов процессов в ОС (защита от fork-бомб).
    *   **Причина:** Критическое количество процессов в системе.
    *   **Последствие:** На узел накладывается taint `node.kubernetes.io/pid-pressure:NoSchedule`.
    *   **Действие:** Выселение подов с наименьшим приоритетом.

**Связь Conditions и Taints:** При переходе узла в состояние Pressure (True) автоматически накладывается соответствующий taint, что блокирует планирование новых подов. Это создает "барьер" для предотвращения further resource exhaustion.

> Подробнее о диагностике этих состояний: **[Диагностика выселения подов](./diagnostics.md)**.

### DisruptionTarget и диагностические условия (K8s 1.31+)

Для упрощения отладки в Kubernetes 1.31 (GA) введено условие `DisruptionTarget`, которое записывается в `status.conditions` пода. Оно позволяет точно определить, *почему* под был выселен.

**Примеры причин (`reason`):**
*   `EvictionByEvictionAPI`: Выселен через `kubectl drain` или Descheduler (учитывает PDB).
*   `DeletionByTaintManager`: Удален из-за Taint `NoExecute` (узел упал).
*   `PreemptionByKubeScheduler`: Вытеснен более важным подом.
*   `EvictionByKubelet`: Выселен из-за давления ресурсов на узле (MemoryPressure, DiskPressure).

**Как использовать для диагностики:**
```bash
# Проверка условия DisruptionTarget (K8s 1.31+)
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → reason: EvictionByKubelet
```

### Связь Eviction Manager и cAdvisor

`Eviction Manager` работает в тесной интеграции с `cAdvisor`:

1. **Сбор данных:** `cAdvisor` собирает метрики потребления ресурсов каждые 10 секунд.
2. **Анализ:** `Eviction Manager` сравнивает метрики с порогами выселения.
3. **Принятие решений:** При достижении порогов формируется очередь кандидатов.
4. **Выполнение:** Кандидаты выстраиваются по приоритету и удаляются.

**Как проверить метрики cAdvisor:**
```bash
# Через API kubelet (требуется аутентификация)
curl -sk https://<node-ip>:10250/stats/summary | jq '.pods[].containers[].memory'

# Через Prometheus (если настроен)
container_memory_working_set_bytes{pod="<pod-name>"}
```

### Eviction vs Preemption: ключевые различия

| Характеристика | Eviction (Выселение) | Preemption (Вытеснение) |
|:---|:---|:---|
| **Инициатор** | `kubelet` (Node-Pressure) или `kubectl drain` | `kube-scheduler` |
| **Причина** | Нехватка ресурсов на узле | Необходимость разместить приоритетный под |
| **Учет PDB** | Зависит от типа (API - да, Node-Pressure - нет) | Да (старается) |
| **Очередность** | По QoS и потреблению ресурсов | По PriorityClass |
| **Восстановление** | Автоматическое (ReplicaSet/Deployment) | Нет (под вытеснен навсегда) |

## Практические сценарии

### 1. Идентификация причины через статус пода

Если под находится в статусе `Evicted`, первым делом нужно проверить сообщение в `status.message`.

```bash
kubectl get pod <pod-name> -o jsonpath='{.status.reason}: {.status.message}'
# → Evicted: The node was low on resource: memory. Container app was using 1500Mi, which is over its request of 1Gi.
```

**Разбор сообщения:**
*   `The node was low on resource: memory` — причина на уровне узла (`MemoryPressure`).
*   `Container app was using 1500Mi` — фактическое потребление в момент выселения.
*   `over its request of 1Gi` — сравнение с запросом. Это критически важно, так как при `MemoryPressure` в первую очередь выселяются те, кто превысил свои `requests`.

### 2. Отличие Eviction от OOMKilled

Часто эти два состояния путают, так как оба связаны с памятью.

| Характеристика | Eviction (`MemoryPressure`) | OOMKilled (`OOM`) |
|:---|:---|:---|
| **Кто убивает** | `kubelet` | Ядро Linux (OOM Killer) |
| **Логика** | Предиктивная (запас ~100-500Mi) | Реактивная (память кончилась в ноль) |
| **Гранулярность** | Весь под целиком | Конкретный контейнер |
| **Сигнал** | SIGTERM/SIGKILL | SIGKILL (мгновенно) |
| **Статус** | `Reason: Evicted` | `Reason: OOMKilled` |

### 3. Выселение при плановом обслуживании (API)

При выполнении `kubectl drain` используется Eviction API. В этом случае под не переходит в статус `Failed` (Reason: `Evicted`), а просто удаляется и пересоздается контроллером (например, Deployment) на другом узле. Если в этот момент под "завис", следует проверять наличие `PodDisruptionBudget`.

**Порядок действий при `kubectl drain`:**
1. Проверка PDB для всех подов на узле.
2. Отправка Eviction API для каждого пода (с учетом PDB).
3. Ожидание завершения подов (grace period).
4. Удаление узла из планирования (Cordon).

### 4. Проверка всех состояний узла одновременно

Для быстрой оценки состояния кластера:

```bash
# Проверка всех Pressure conditions на всех узлах
kubectl get nodes -o custom-columns="\
NAME:.metadata.name,\
MEMORY_PRESSURE:.status.conditions[?(@.type=='MemoryPressure')].status,\
DISK_PRESSURE:.status.conditions[?(@.type=='DiskPressure')].status,\
PID_PRESSURE:.status.conditions[?(@.type=='PIDPressure')].status,\
READY:.status.conditions[?(@.type=='Ready')].status"

# Результат:
# node-1   False   False   False   True
# node-2   True    False   False   True  ← MemoryPressure!
```

**Интерпретация:**
*   `False` — Pressure не активен, узел стабилен.
*   `True` — Pressure активен, узел перегружен.
*   `Unknown` — Узел недоступен, возможно сбой.

### 5. Автоматическая очистка выселенных подов

Выселенные поды остаются в API в статусе `Failed`. Это полезно для диагностики, но замусоривает вывод.

```bash
# Удаление всех выселенных подов во всех пространствах имен
kubectl delete pods --field-selector status.reason=Evicted -A

# Проверка количества выселенных подов
kubectl get pods -A --field-selector status.reason=Evicted --no-headers | wc -l
# → 15
```

**Автоматизация через CronJob:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-evicted-pods
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"  # Каждые 6 часов
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: evicted-pod-cleanup
          containers:
          - name: cleanup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl delete pods -A --field-selector status.reason=Evicted
          restartPolicy: OnFailure
```

### 6. Анализ хронологии выселения через события

События (Events) показывают хронологию всех действий в кластере:

```bash
# Получение событий выселения за последние 24 часа
kubectl get events -A --field-selector reason=Evicted --sort-by='.lastTimestamp' | tail -20

# Детальный просмотр конкретного события
kubectl describe event <event-name> -n <namespace>
```

**Паттерны в событиях:**
*   `The node was low on resource: memory` — выселение по памяти.
*   `The node was low on resource: ephemeral-storage` — переполнение `emptyDir` или логов.
*   `Evicted by Eviction API` — результат `kubectl drain`.
*   `Preempted by scheduler` — вытеснение более приоритетным подом.

### 7. Использование эфемерных контейнеров для отладки

Если узел в критическом состоянии и SSH недоступен:

```bash
# Запуск отладочного контейнера с доступом к хостовой ФС
kubectl debug node/<node-name> -it --image=busybox

# Внутри контейнера:
chroot /host
df -h  # Проверка дисков узла
free -m  # Проверка памяти узла
ps aux | wc -l  # Количество процессов
```

### 8. Проверка PDB перед обслуживанием

Перед `kubectl drain` убедитесь, что PDB не блокирует выселение:

```bash
# Просмотр всех PDB в кластере
kubectl get pdb -A

# Детали конкретного PDB
kubectl describe pdb <pdb-name> -n <namespace>

# Проверка, сколько подов можно выселить
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionsAllowed}'
# → 1
```

## Дополнительная информация

### Сводная таблица сигналов и таймаутов

| Сценарий | Сигнал | Учет Grace Period | Восстановление |
|:---|:---|:---|:---|
| `Hard Eviction` | `SIGKILL` | Игнорируется (0s) | Автоматическое (ReplicaSet) |
| `Soft Eviction` | `SIGTERM` | Да (`eviction-soft-grace-period`) | Автоматическое (ReplicaSet) |
| `API Eviction` | `SIGTERM` | Да (`terminationGracePeriodSeconds`) | Автоматическое (ReplicaSet) |
| `Preemption` | `SIGTERM` | Да (обычно до 30s) | Нет (под вытеснен) |
| `Taint-Based` | `SIGTERM` | Да (`tolerationSeconds`) | Автоматическое (если есть controller) |

### Рекомендации по классификации

*   Если под пропал "молча" и пересоздался — скорее всего, это **API Eviction** (drain) или **Preemption**.
*   Если под остался в списке `kubectl get pods` со статусом `Evicted` — это **Node-Pressure Eviction** (нехватка ресурсов).
*   Если под в `Terminating` на узле `NotReady` — это **Taint-based Eviction**.
*   Если под в `OOMKilled` — это **Resource Limit Exceeded** (приложение превысило лимит памяти).

### Типичные ошибки при диагностике

| Ошибка | Последствия | Решение |
|:---|:---|:---|
| Путаница Eviction и OOMKilled | Неправильный выбор стратегии исправления | Проверяйте `status.reason` и `status.message` |
| Игнорирование PDB при drain | `kubectl drain` зависает на часы | Проверяйте PDB перед обслуживанием |
| Отсутствие мониторинга Pressure | Проблемы обнаруживаются только после вылета сервисов | Настройте алерты в Prometheus |
| Неправильные requests/limits | Частые выселения или недоресурсирование | Используйте VPA для автоматической настройки |

### Смотрите также

- **[Диагностика выселения](./diagnostics.md)** — практические шаги по анализу.
- **[Профилактика выселения](./prevention.md)** — как настроить кластер, чтобы избежать выселений.
- **[QoS и выселение](./qos_and_eviction.md)** — как классы ресурсов влияют на очередность удаления.
