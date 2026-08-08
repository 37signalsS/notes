# Pod Evicted: Диагностика и поиск первопричин

## Определения

**Диагностика выселения (Eviction Diagnostics)** — системный процесс выявления триггеров и условий, приведших к принудительному завершению пода компонентом `kubelet` или через Eviction API.

**Основные артефакты для анализа:**
*   **`status.reason: Evicted`**: Индикатор того, что под был выселен, а не просто упал или был удален.
*   **`status.message`**: Контекстное пояснение (например, `The node was low on resource: memory`).
*   **`status.conditions` (`DisruptionTarget`)**: Детальная причина выселения в современных версиях Kubernetes (1.31+).
*   **Node Pressure Conditions**: Флаги состояния узла (`MemoryPressure`, `DiskPressure`, `PIDPressure`).

Общие понятия и типы выселения описаны в файле **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Диагностическая матрица

Для эффективного траблшутинга необходимо сопоставлять данные из разных источников.

| Уровень | Инструмент | Искомая информация |
|:---|:---|:---|
| **API/Pod** | `kubectl describe pod` | Сообщения в `status.message`, события (Events). |
| **Node Status** | `kubectl describe node` | Состояния Pressure, Capacity vs Allocatable. |
| **Node Logs** | `journalctl -u kubelet` | Логи `eviction manager`, расчеты Working Set. |
| **Metrics** | `Prometheus/Grafana` | Тренды потребления ресурсов перед инцидентом. |
| **OS/Runtime** | `dmesg`, `crictl stats` | OOM Killer ядра, статус контейнеров в рантайме. |

### Алгоритм траблшутинга

1.  **Сбор первичных данных:** Идентификация всех выселенных подов и узлов, на которых они находились.
2.  **Классификация по `status.message`:** Разделение на выселения по памяти, диску, PID или через API (drain).
3.  **Анализ состояния узла (Pressure):** Если флаги Pressure установлены (`True`), значит узел стабильно перегружен. Если `False` — имел место кратковременный всплеск.
4.  **Проверка QoS и лимитов:** Определение класса QoS выселенного пода. В первую очередь выселяются `BestEffort` и `Burstable`, превысившие свои `requests`.
5.  **Корреляция с системными событиями:** Проверка `dmesg` на предмет OOM Killer (если выселение по памяти) или переполнения разделов ФС.
6.  **Верификация через метрики:** Анализ графиков потребления ресурсов за 15-30 минут до выселения.

## Практические сценарии

### 1. Первичный анализ через kubectl

```bash
# Получение списка выселенных подов с именами узлов и сообщениями
kubectl get pods -A --field-selector status.reason=Evicted -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,MESSAGE:.status.message"

# Проверка условия DisruptionTarget (для K8s 1.31+)
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
```

### 2. Анализ логов Kubelet на узле

Логи `kubelet` содержат детальную информацию о том, как `Eviction Manager` принимал решение.

```bash
# Поиск записей о начале выселения
journalctl -u kubelet -g "eviction manager: attempting to reclaim"

# Пример лога:
# eviction manager: attempting to reclaim memory
# eviction manager: unit of reclaim is nodes
# eviction manager: pod <pod_name> is evicted
```

### 3. Диагностика через Prometheus (PromQL)

Метрики позволяют увидеть картину в динамике, когда события уже стерты.

*   **Поиск узлов с MemoryPressure:**
    ```promql
    kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
    ```
*   **Топ подов, потребляющих больше запросов (Candidate for Eviction):**
    ```promql
    sum(container_memory_working_set_bytes) by (pod) - sum(kube_pod_container_resource_requests{resource="memory"}) by (pod) > 0
    ```
*   **Всплеск Disk Usage на nodefs:**
    ```promql
    node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.1
    ```

### 4. Анализ причин через события (Events)

События — это основной способ понять хронологию. Помните, что по умолчанию они хранятся всего 1 час.

```bash
# Фильтрация событий выселения по всему кластеру
kubectl get events -A --field-selector reason=Evicted --sort-by='.lastTimestamp'
```

**Паттерны в событиях:**
*   `The node was low on resource: memory`: Выселение по памяти.
*   `The node was low on resource: ephemeral-storage`: Переполнение `emptyDir` или логов.
*   `Evicted by Eviction API`: Результат `kubectl drain`.

### 5. Использование эфемерных контейнеров для отладки

Если узел в критическом состоянии, вы можете запустить отладочный контейнер с доступом к хостовой ФС.

```bash
kubectl debug node/<node-name> -it --image=busybox
# Внутри контейнера:
# chroot /host
# df -h  # Проверка дисков узла
# free -m # Проверка памяти узла
```

## Устранение последствий

### Массовая очистка выселенных подов

Выселенные поды остаются в API в статусе `Failed`. Их нужно периодически удалять, чтобы не нагружать `kube-apiserver` и не замусоривать выдачу `kubectl`.

```bash
# Удаление всех выселенных подов во всех пространствах имен
kubectl delete pods --field-selector status.reason=Evicted -A
```

**Автоматизация:** Kubernetes имеет встроенный параметр `terminated-pod-gc-threshold` (в `kube-controller-manager`), который определяет, сколько завершенных подов хранить до начала автоматической очистки.

## Дополнительная информация

### Диагностическая матрица ресурсов

| Ресурс | Что проверить на узле | Файл-руководство |
|:---|:---|:---|
| **Memory** | `WorkingSet`, `oom_score_adj` | **[Выселение по памяти](./memory_eviction.md)** |
| **Disk** | `/var/lib/kubelet`, `/var/lib/docker` | **[Выселение по диску](./disk_eviction.md)** |
| **PID** | `pids.current` в cgroups | **[Давление ресурсов](../NodeUnavailability/resource_pressure.md)** |
| **API** | `PodDisruptionBudget` | **[PDB и Taint Eviction](./pdb_and_taint_eviction.md)** |

### Смотрите также

- **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
- **[Профилактика выселения](./prevention.md)** — как не допустить повторения.
- **[QoS и выселение](./qos_and_eviction.md)** — влияние лимитов на выбор жертвы.
- **[Диагностика недоступности узла](../NodeUnavailability/diagnostics.md)** — если узел упал совсем.
