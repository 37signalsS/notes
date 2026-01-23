# Taints and Tolerations (Отравления и Терпимость)

## Определения

*   **Taints (отравления) и Tolerations (терпимость)**: Механизм в Kubernetes, который позволяет ограничивать размещение подов на определенных узлах. Узел с `taint` "отталкивает" поды, у которых нет соответствующего `toleration`.
*   **Taint**: Метка, применяемая к узлу и состоящая из ключа (`key`), значения (`value`) и эффекта (`effect`).
    ```bash
    kubectl taint nodes <node-name> <key>=<value>:<effect>
    ```
*   **Toleration**: Свойство в спецификации пода (`pod.spec`), которое позволяет ему "терпеть" `taint` на узле и быть размещенным на нем.
*   **Эффект `NoSchedule`**: Kubernetes не размещает на узле новые поды без `toleration`. Существующие поды продолжают работать.
*   **Эффект `PreferNoSchedule`**: "Мягкая" версия `NoSchedule`. Kubernetes старается не размещать на узле новые поды без `toleration`, но сделает это при отсутствии альтернатив.
*   **Эффект `NoExecute`**: Самый строгий эффект. Новые поды без `toleration` не размещаются, а существующие — вытесняются (evicted).

## Основные концепции

### Эффекты Taint

| Taint Effect     | Поведение для **новых** подов (без toleration) | Поведение для **существующих** подов (без toleration) |
|------------------|------------------------------------------------|-------------------------------------------------------|
| `NoSchedule`     | Не размещаются                                 | **Продолжают работать**                               |
| `PreferNoSchedule` | Kubernetes старается не размещать             | Продолжают работать                                   |
| `NoExecute`      | Не размещаются                                 | **Вытесняются (evicted)**                             |

### Операторы Toleration

В `toleration` пода указывается оператор для сопоставления с `taint` узла.

*   `operator: "Equal"`: `toleration` срабатывает, если `key`, `value` и `effect` точно совпадают с `taint`.
*   `operator: "Exists"`: `toleration` срабатывает для любого `taint` с указанным `key` и `effect`, независимо от `value`.

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

## Практические сценарии

### Ключевые варианты использования

*   **Выделение узлов для специфических задач**: Например, узлы с GPU "отравляются" (`taint`), а поды, которым нужен GPU, получают `toleration`.
*   **Выделение узлов для определенных групп пользователей**: Разделение ресурсов между командами.
*   **Вытеснение подов при неисправности узла**: Kubernetes автоматически добавляет `taint` (например, `node.kubernetes.io/unreachable`) на недоступные узлы, что приводит к вытеснению подов (с эффектом `NoExecute`).

### Отложенный запуск подов до готовности DaemonSet

Сценарий гарантирует, что системные компоненты (например, CNI-плагин), развернутые через [DaemonSet](../Base/daemonset.md), запустятся на узле раньше, чем поды приложений.

**Шаг 1: Применение Taint к узлам**
На новый узел применяется `taint` с эффектом `NoSchedule`, запрещая планировщику размещать на нем обычные поды.
```bash
kubectl taint nodes my-node my-daemonset.startup/not-ready:NoSchedule
```

**Шаг 2: Добавление Toleration в DaemonSet**
В манифест `DaemonSet` добавляется `toleration`, чтобы его поды могли запуститься на "отравленном" узле.
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
        operator: "Exists"
        effect: "NoSchedule"
      containers:
      # ...
```

**Шаг 3: Автоматическое удаление Taint**
После успешного запуска пода `DaemonSet` на узле, внешний контроллер (часто встроенный в системные `DaemonSet`, например, CNI) должен удалить `taint` с узла. Это позволяет планировщику размещать на нем обычные поды. Для пользовательских `DaemonSet` может потребоваться разработка такого контроллера.

## Дополнительная информация

Механизм `Taints` и `Tolerations` часто используется совместно с [Affinity и Anti-Affinity](./affinity.md) для построения сложных сценариев размещения подов.