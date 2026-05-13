# Taints and Tolerations (Отравления и Терпимость): Управление размещением подов

## Definitions

* **Taints (отравления):** Механизм, применяемый к узлам Kubernetes, который «отталкивает» поды, не имеющие соответствующего `toleration`. Состоит из ключа (`key`), значения (`value`) и эффекта (`effect`).

    ```bash
    kubectl taint nodes <node-name> <key>=<value>:<effect>
    # Пример:
    kubectl taint nodes worker-1 dedicated=ml:NoSchedule
    ```

* **Tolerations (терпимость):** Свойство, задаваемое в спецификации пода (`pod.spec`), которое позволяет ему «терпеть» `taint` на узле и быть размещённым на нём.

### Эффекты Taint

* **`NoSchedule`:** Kubernetes не размещает на узле **новые** поды без `toleration`. Существующие поды продолжают работать.
* **`PreferNoSchedule`:** "Мягкая" версия `NoSchedule`. Kubernetes старается не размещать на узле новые поды без `toleration`, но сделает это при отсутствии альтернатив.
* **`NoExecute`:** Самый строгий эффект. Новые поды без `toleration` не размещаются, а существующие поды без `toleration` **вытесняются (evicted)**.

### Стандартные Taints узлов

Kubernetes автоматически применяет следующие `taints` к узлам в зависимости от их роли:

| Taint | Описание | Узлы |
|-------|----------|------|
| `node-role.kubernetes.io/control-plane:NoSchedule` | Запрет размещения на управляющих узлах | Control Plane (Kubernetes 1.20+) |
| `node-role.kubernetes.io/master:NoSchedule` | Устаревший taint для control-plane | Control Plane (до 1.24) |
| `node.kubernetes.io/not-ready:NoExecute` | Узел не готов (kubelet не отвечает) | Все узлы |
| `node.kubernetes.io/unreachable:NoExecute` | Узел недоступен в сети | Все узлы |
| `node.kubernetes.io/memory-pressure:NoSchedule` | Нехватка памяти на узле | Все узлы |
| `node.kubernetes.io/disk-pressure:NoSchedule` | Нехватка дискового пространства | Все узлы |
| `node.kubernetes.io/network-unavailable:NoSchedule` | Сеть узла недоступна | Все узлы |
| `node.kubernetes.io/pid-pressure:NoSchedule` | Исчерпание PID на узле | Все узлы |

> **Связанные механизмы:** Вытеснение подов также управляется через [QoS классы](./qos_limit_and_requests.md), которые определяют приоритет пода при нехватке ресурсов на узле.

## Basic Concepts

### Эффекты Taint и поведение подов

| Taint Effect     | Поведение для **новых** подов (без toleration) | Поведение для **существующих** подов (без toleration) |
|------------------|------------------------------------------------|-------------------------------------------------------|
| `NoSchedule`     | Не размещаются                                 | Продолжают работать                                   |
| `PreferNoSchedule` | Kubernetes старается не размещать             | Продолжают работать                                   |
| `NoExecute`      | Не размещаются                                 | Вытесняются (evicted)                             |

### Операторы Toleration

В `toleration` пода указывается оператор для сопоставления с `taint` узла:

* `operator: "Equal"`: `toleration` срабатывает, если `key`, `value` и `effect` точно совпадают с `taint`.
* `operator: "Exists"`: `toleration` срабатывает для любого `taint` с указанным `key` и `effect`, независимо от `value`.

> **Важно:** `toleration` не гарантирует, что под попадёт именно на ноду с соответствующим `taint` — он лишь снимает запрет на размещение. Для направления пода на конкретную ноду используйте `nodeSelector` или `nodeAffinity`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  # ... другие поля ...
  tolerations:
  - key: "key1"
    operator: "Equal"
    value: "value1"
    effect: "NoSchedule"
  - key: "key2"
    operator: "Exists"
    effect: "NoExecute"
```

#### Toleration для любого Taint

Если не указать `key` совсем — `toleration` сработает для любого `taint` на ноде (при совпадении `effect`):

```yaml
tolerations:
- operator: "Exists"
  effect: "NoSchedule"
```

### `tolerationSeconds` для `NoExecute`

Для `toleration` с эффектом `NoExecute` можно указать поле `tolerationSeconds`. Оно определяет, как долго под будет продолжать работать на узле после добавления `taint`, прежде чем его вытеснят. Это полезно для graceful shutdown при проблемах с узлом.

```yaml
tolerations:
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 300
```

Если `tolerationSeconds` не указано, под с соответствующим `toleration` останется на узле. Если `toleration` нет, под будет вытеснен немедленно.

### Стандартные `tolerationSeconds` в Kubernetes

Kubernetes автоматически добавляет следующие `tolerations` ко всем подам:

| Taint | Effect | `tolerationSeconds` |
|-------|--------|---------------------|
| `node.kubernetes.io/not-ready` | `NoExecute` | 300 |
| `node.kubernetes.io/unreachable` | `NoExecute` | 300 |
| `node.kubernetes.io/disk-pressure` | `NoSchedule` | — |
| `node.kubernetes.io/memory-pressure` | `NoSchedule` | — |
| `node.kubernetes.io/pid-pressure` | `NoSchedule` | — |

Это означает, что при потере связи с узлом поды будут вытеснены только через 5 минут, что позволяет избежать ложных срабатываний при временных проблемах с сетью.

### Taints/Tolerations vs. Affinity/Anti-Affinity

* **Направление действия**:
  * **Taints & Tolerations работают «от ноды»**: Нода «отталкивает» все поды, которые не имеют соответствующего `toleration`.
  * **Node Affinity работает «от пода»**: Под сам «тянется» к нодам с определёнными метками.
* **Применение**:
  * **Taints + Tolerations**: Используются для жёсткой изоляции узлов под специфические задачи (GPU, CI-воркеры, выделенные команды), чтобы на них не попадали «чужие» поды.
  * **Node Affinity**: Используется для направления подов на узлы с нужными характеристиками (тип диска, зона доступности, архитектура процессора).
* **Совместное использование**: В связке Taints удерживают лишние поды подальше, а Node Affinity гарантирует, что нужные поды попадут именно туда, где они должны работать. Подробнее в [Affinity и Anti-Affinity](./affinity.md).

## Practical Scenarios

### Ключевые варианты использования

* **Выделение узлов для специфических задач**: Например, узлы с GPU "отравляются" (`taint`), а поды, которым нужен GPU, получают `toleration`. Это гарантирует, что дорогостоящие ресурсы используются только по назначению.
* **Выделение узлов для определенных групп пользователей**: Разделение ресурсов между командами в многопользовательских кластерах.
* **Вытеснение подов при неисправности узла**: Kubernetes автоматически добавляет `taint` (например, `node.kubernetes.io/unreachable`) на недоступные узлы. Поды, не имеющие соответствующего `toleration` с `tolerationSeconds`, будут вытеснены, что позволяет планировщику перенести их на здоровые узлы.

### Сценарий: Разрешение запуска на Control Plane и управление Taints

В кластерах, развернутых с помощью RKE (Rancher Kubernetes Engine), узлы с ролями Control Plane и etcd по умолчанию получают `taints` для предотвращения размещения на них рабочих нагрузок. Например, `control-plane` узлы могут иметь `taint` `node-role.kubernetes.io/control-plane:NoSchedule`, а `etcd` узлы — `taint` `node-role.kubernetes.io/etcd:NoSchedule` или аналогичный.

Этот сценарий демонстрирует, как разрешить `DaemonSet` запускаться на `control-plane` узлах и как динамически управлять размещением с помощью `taints`.

**Шаг 1: Диагностика проблемы**

Вы развернули `DaemonSet` и заметили, что количество подов меньше, чем количество узлов в кластере.

```bash
# В кластере 3 узла, но запущено только 2 пода
$ kubectl get pods -o wide
NAME          READY   STATUS    RESTARTS   AGE   IP           NODE
test-ds-abc   1/1     Running   0          60s   10.42.1.5    worker-1
test-ds-def   1/1     Running   0          60s   10.42.2.8    worker-2
```

**Шаг 2: Проверка Taints на узлах**

С помощью `kubectl describe node` или специального вывода можно увидеть `taints`, примененные к узлам.

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

Вывод покажет, что на `control-plane` узле есть `taint`, который запрещает запуск обычных подов:
`node-role.kubernetes.io/control-plane:NoSchedule`

**Шаг 3: Добавление `toleration` в манифест**

Чтобы разрешить поду запускаться на `control-plane` узле, добавьте в его спецификацию (`spec.template.spec` для `DaemonSet`) соответствующий `toleration`.

```yaml
# daemonset-with-toleration.yaml
spec:
  template:
    spec:
      tolerations:
      - key: "node-role.kubernetes.io/control-plane"
        operator: "Exists" # "Exists" подходит для любого значения, т.к. value здесь не важно
        effect: "NoSchedule"
      containers:
      # ...
```

После применения этого манифеста `DaemonSet` запустит под и на `control-plane` узле.

**Шаг 4: Динамическое управление с помощью `taint`**

Вы можете "заразить" любой узел, чтобы временно или постоянно запретить на нем запуск подов.

```bash
# Добавляем taint с эффектом NoExecute к worker-2.
# Это приведет к вытеснению всех подов без соответствующего toleration.
kubectl taint nodes worker-2 test-taint:NoExecute
```

После выполнения этой команды под `DaemonSet` будет удален с узла `worker-2`.

**Шаг 5: Удаление `taint`**

Чтобы убрать `taint` и позволить `DaemonSet` снова запустить под, выполните команду с дефисом в конце.

```bash
kubectl taint nodes worker-2 test-taint:NoExecute-
```

`DaemonSet` обнаружит, что узел снова доступен для планирования, и автоматически создаст на нем недостающий под.

> **Осторожно с `NoExecute`**: Этот эффект вытесняет *все* поды без `toleration` с узла, что может затронуть другие приложения. Для более безопасного запрета планирования новых подов используйте `NoSchedule`.

### Отложенный запуск подов до готовности DaemonSet

Этот сценарий гарантирует, что системные компоненты (например, CNI-плагин или агент мониторинга), развернутые через [DaemonSet](../Base/daemonset.md), запустятся на узле раньше, чем поды приложений.

**Шаг 1: Применение Taint к узлам**
На новый узел применяется `taint` с эффектом `NoSchedule`, запрещая планировщику размещать на нем обычные поды.

```bash
kubectl taint nodes my-node my-daemonset.startup/not-ready:NoSchedule
```

**Шаг 2: Добавление Toleration в DaemonSet**
В манифест `DaemonSet` добавляется `toleration`, чтобы его поды могли запуститься на "отравленном" узле, игнорируя `taint`:

```yaml
# daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
# ...
spec:
  template:
    spec:
      tolerations:
      # Этот блок позволяет DaemonSet запуститься на "отравленном" узле
      - key: "my-daemonset.startup/not-ready"
        operator: "Exists" # Или "Equal" с value, если оно есть
        effect: "NoSchedule"
      containers:
      # ...
```

**Шаг 3: Автоматическое удаление Taint**
После успешного запуска пода `DaemonSet` на узле, внешний контроллер (часто встроенный в системные `DaemonSet`, например, CNI-плагин или оператор) должен удалить `taint` с узла. Это позволяет планировщику размещать на нем обычные поды. Для пользовательских `DaemonSet` может потребоваться разработка такого контроллера.

## Additional Information

Механизм `Taints` и `Tolerations` часто используется совместно с [Affinity и Anti-Affinity](./affinity.md) для построения сложных сценариев размещения подов, требующих как притяжения, так и отталкивания.
