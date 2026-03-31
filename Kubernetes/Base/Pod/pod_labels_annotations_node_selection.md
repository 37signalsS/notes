# Метки, аннотации и выбор узлов в Kubernetes

## Определения

**Метки (Labels)** и **Аннотации (Annotations)** — механизмы организации метаданных объектов Kubernetes. Метки используются для идентификации и выборки объектов, аннотации — для хранения произвольной информации.

> **Примечание:** Подробное описание меток, аннотаций и рекомендуемых меток см. в [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

**Node Selection** — механизм влияния на размещение подов в кластере через привязку к определённым узлам.

**nodeSelector** — простейший способ привязки пода к узлам с определёнными метками. Под запустится только на узлах, имеющих все указанные метки.

**nodeName** — прямая привязка пода к конкретному узлу по имени. Планировщик игнорируется, под размещается на указанном узле.

---

## Базовые концепции

### Механизмы привязки к узлам

| Механизм | Описание | Гибкость | Рекомендация |
| :--- | :--- | :--- | :--- |
| `nodeSelector` | Привязка к узлам с определёнными метками | Средняя | Использовать для простых сценариев |
| `nodeName` | Прямая привязка к узлу по имени | Низкая | **Не рекомендуется** (снижает гибкость и отказоустойчивость) |
| [Node Affinity](../../Scheduling/affinity.md) | Продвинутая привязка с операторами и правилами | Высокая | Использовать для сложных сценариев |

### Сравнение nodeSelector и Node Affinity

| Характеристика | nodeSelector | Node Affinity |
| :--- | :--- | :--- |
| Синтаксис | Простой `key: value` | Расширенный с операторами (`In`, `NotIn`, `Exists`, `Gt`, `Lt`) |
| Логические операции | Только "И" (все метки должны совпадать) | "И", "ИЛИ", отрицания |
| Мягкие правила | Нет | Есть (`preferredDuringSchedulingIgnoredDuringExecution`) |
| Жёсткие правила | Да | Да (`requiredDuringSchedulingIgnoredDuringExecution`) |

### Рекомендации по использованию

**Метки узлов:**
- Создавайте осмысленные пользовательские метки (например, `special=ds-only`, `disktype=ssd`)
- Не привязывайтесь к стандартной метке `kubernetes.io/hostname` — имена узлов могут меняться

**Выбор механизма:**
- `nodeSelector` — для простых сценариев с точным совпадением меток
- `nodeAffinity` — для сложных правил с операторами и мягкими/жёсткими требованиями
- `nodeName` — только для отладки и специальных случаев

---

## Практические сценарии

### Пример 1: Использование nodeSelector для DaemonSet

**Сценарий:** Ограничить запуск `DaemonSet` только двумя из трёх узлов в кластере.

**Шаг 1: Добавление меток к узлам**

```bash
kubectl label nodes control-plane-1 special=ds-only
kubectl label nodes worker-2 special=ds-only
```

**Шаг 2: Проверка меток**

```bash
kubectl get nodes --show-labels
```

**Шаг 3: Добавление nodeSelector в манифест**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: restricted-daemonset
spec:
  selector:
    matchLabels:
      app: restricted-app
  template:
    metadata:
      labels:
        app: restricted-app
    spec:
      nodeSelector:
        special: ds-only
      containers:
      - name: app
        image: nginx
```

**Результат:** DaemonSet запустит поды только на узлах с меткой `special=ds-only`.

**Шаг 4: Удаление метки**

```bash
kubectl label nodes worker-2 special-
```

После удаления метки узел перестанет удовлетворять условию `nodeSelector`. DaemonSet автоматически удалит под с этого узла.

### Пример 2: nodeSelector для обычного пода

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-workload
  labels:
    app: ml-training
spec:
  nodeSelector:
    gpu-type: nvidia-v100
  containers:
  - name: trainer
    image: tensorflow/tensorflow:latest-gpu
    resources:
      limits:
        nvidia.com/gpu: 1
```

### Пример 3: Не рекомендуется — использование nodeName

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: debug-pod
spec:
  nodeName: worker-1  # Прямая привязка к узлу
  containers:
  - name: debug
    image: busybox
    command: ["sleep", "3600"]
```

**Проблемы такого подхода:**
- Планировщик не участвует в размещении
- Не работают `Taints/Tolerations`, `Affinity`
- При удалении узла под не будет автоматически перемещён
- Снижается отказоустойчивость

---

## Дополнительная информация

**Связанные темы:** [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md), [Node Affinity](../../Scheduling/affinity.md), [Taints and Tolerations](../../Scheduling/taints_and_tolerations.md), [Жизненный цикл пода](./pod_lifecycle_and_state.md).
