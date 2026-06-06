# Taints и Tolerations (Отравления и Терпимость): Управление размещением подов

## Определения

* **Taints (отравления)**: Механизм, применяемый к узлам Kubernetes, который «отталкивает» поды, не имеющие соответствующего `toleration`. Состоит из ключа (`key`), значения (`value`) и эффекта (`effect`).

    ```bash
    kubectl taint nodes <node-name> <key>=<value>:<effect>
    # Пример:
    kubectl taint nodes worker-1 dedicated=ml:NoSchedule
    ```

* **Tolerations (терпимость)**: Свойство, задаваемое в спецификации пода (`pod.spec`), которое позволяет ему «терпеть» `taint` на узле и быть размещённым на нём.

### Эффекты Taint

* **`NoSchedule`**: Kubernetes не размещает на узле **новые** поды без `toleration`. Существующие поды продолжают работать.
* **`PreferNoSchedule`**: «Мягкая» версия `NoSchedule`. Kubernetes старается не размещать на узле новые поды без `toleration`, но сделает это при отсутствии альтернатив.
* **`NoExecute`**: Самый строгий эффект. Новые поды без `toleration` не размещаются, а существующие поды без `toleration` **вытесняются (evicted)**.

---

## Основные концепции

### Эффекты Taint и поведение подов

| Taint Effect | Поведение для **новых** подов (без toleration) | Поведение для **существующих** подов (без toleration) |
| :--- | :--- | :--- |
| `NoSchedule` | Не размещаются | Продолжают работать |
| `PreferNoSchedule` | Kubernetes старается не размещать | Продолжают работать |
| `NoExecute` | Не размещаются | Вытесняются (evicted) |

### Операторы Toleration

В `toleration` пода указывается оператор для сопоставления с `taint` узла:

* `operator: "Equal"`: `toleration` срабатывает, если `key`, `value` и `effect` точно совпадают с `taint`.
* `operator: "Exists"`: `toleration` срабатывает для любого `taint` с указанным `key` и `effect`, независимо от `value`.

> **Важно**: `toleration` не гарантирует, что под попадёт именно на ноду с соответствующим `taint` — он лишь снимает запрет на размещение. Для направления пода на конкретную ноду используйте `nodeSelector` или `nodeAffinity`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  tolerations:
  - key: "key1"
    operator: "Equal"
    value: "value1"
    effect: "NoSchedule"
  - key: "key2"
    operator: "Exists"
    effect: "NoExecute"
```

### Стандартные Taints узлов

Kubernetes автоматически применяет следующие `taints` к узлам:

| Taint | Описание | Условие (Condition) |
| :--- | :--- | :--- |
| `node.kubernetes.io/not-ready:NoExecute` | Узел не готов | `Ready=False` |
| `node.kubernetes.io/unreachable:NoExecute` | Узел недоступен | `Ready=Unknown` |
| `node.kubernetes.io/memory-pressure:NoSchedule` | Нехватка памяти | `MemoryPressure=True` |
| `node.kubernetes.io/disk-pressure:NoSchedule` | Нехватка диска | `DiskPressure=True` |
| `node.kubernetes.io/pid-pressure:NoSchedule` | Исчерпание PID | `PIDPressure=True` |
| `node.kubernetes.io/network-unavailable:NoSchedule` | Сеть недоступна | `NetworkUnavailable=True` |
| `node-role.kubernetes.io/control-plane:NoSchedule` | Узел управления | Роль Control Plane |

### Процесс выселения (Eviction Timeline)

При потере связи с узлом процесс выселения подов проходит следующие этапы:

1. **Обнаружение**: `node-controller` ждёт время, указанное в `--node-monitor-grace-period` (по умолчанию 40с).
2. **Маркировка**: Состояние узла меняется на `Unknown`, добавляется taint `unreachable:NoExecute`.
3. **Ожидание**: Поды без специфических `tolerations` начинают выселяться по истечении `tolerationSeconds` (по умолчанию 300с для стандартных taints).
4. **Удаление**: Поды удаляются из API и планируются на другие узлы.

### Параметры Node Controller

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--node-monitor-grace-period` | 40s | Время до присвоения статуса `Unknown` |
| `--pod-eviction-timeout` | 5m | Интервал между попытками выселения (не время до начала) |

### Сравнение с Affinity

* **Taints и Tolerations работают «от ноды»**: Нода «отталкивает» поды. Используется для изоляции ресурсов (GPU, выделенные узлы).
* **Node Affinity работает «от пода»**: Под «тянется» к нодам. Используется для выбора узлов по характеристикам (тип диска, зона).
* **Совместное использование**: Taints удерживают лишние поды, а Node Affinity гарантирует попадание нужных подов на правильные узлы. Подробнее в [Affinity и Anti-Affinity](./affinity.md).

---

## Практические сценарии

### Сценарий 1: Выделение узлов под специфические задачи (GPU)

Узлы с дорогостоящим оборудованием "отравляются", чтобы на них не попадали обычные поды.

```bash
kubectl taint nodes gpu-node-1 hardware=gpu:NoSchedule
```

Поды приложения, требующие GPU, должны иметь соответствующую терпимость:

```yaml
tolerations:
- key: "hardware"
  operator: "Equal"
  value: "gpu"
  effect: "NoSchedule"
```

### Сценарий 2: Разрешение запуска на Control Plane

По умолчанию узлы управления имеют taint, запрещающий запуск рабочих подов. Чтобы запустить на них, например, агент мониторинга через `DaemonSet`:

```yaml
tolerations:
- key: "node-role.kubernetes.io/control-plane"
  operator: "Exists"
  effect: "NoSchedule"
```

### Сценарий 3: Управление временем выселения (Graceful Eviction)

Если под должен оставаться на недоступном узле дольше стандартных 5 минут (например, при кратковременных сбоях сети):

```yaml
tolerations:
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 600 # 10 минут
```

### Сценарий 4: Динамическое управление размещением

Использование `taint` для временного вывода узла из планирования без его полной остановки:

```bash
# Добавление временного запрета
kubectl taint nodes worker-1 maintenance=true:NoSchedule

# Удаление запрета (дефис в конце)
kubectl taint nodes worker-1 maintenance=true:NoSchedule-
```

---

## Дополнительная информация

* **DaemonSet**: По умолчанию игнорирует `NoSchedule` для `node.kubernetes.io/unschedulable`.
* **QoS классы**: Влияют на приоритет вытеснения при нехватке ресурсов. Подробнее в [QoS, Requests и Limits](./qos_limit_and_requests.md).
* **Диагностика**:
    ```bash
    # Проверка taints на узле
    kubectl describe node <node-name> | grep Taints
    
    # Проверка tolerations пода
    kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
    ```
