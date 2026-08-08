# CreateContainerConfigError: Диагностика

## Определения

**Диагностика CreateContainerConfigError** — систематический процесс выявления некорректно настроенных или отсутствующих зависимостей, которые блокируют формирование спецификации контейнера агентом `kubelet`. В отличие от прикладной отладки, этот процесс фокусируется на уровне управления (Control Plane) и взаимодействии узла с API-сервером.

Основной вызов диагностики заключается в том, что на этом этапе контейнер еще не создан в Container Runtime (CRI), поэтому стандартные инструменты (`kubectl logs`, `kubectl exec`) недоступны.

## Основные концепции

### Алгоритм диагностики (Workflow)

Процесс отладки должен следовать иерархии зависимостей: от API-объектов до прав доступа на узле.

1.  **Инспекция событий (Events):** Первичный поиск конкретного ресурса и причины отказа (NotFound, Forbidden).
2.  **Валидация ссылок в PodSpec:** Проверка имен ConfigMap, Secret и PVC на наличие опечаток.
3.  **Проверка доступности ресурса:** Подтверждение существования объекта в том же Namespace.
4.  **Целостность данных (Data Integrity):** Проверка наличия конкретных ключей в `data` ресурса, если используется `keyRef`.
5.  **RBAC и ServiceAccount:** Проверка разрешений на чтение ресурсов от имени пода.
6.  **Уровень инфраструктуры (CSI/Provisioning):** Проверка статуса PVC и здоровья CSI-контроллеров, если ошибка связана с томами.

### Ключевые команды и инструменты

| Инструмент | Команда / Метод | Ожидаемый результат |
| :--- | :--- | :--- |
| **Events** | `kubectl get events --field-selector involvedObject.name=<pod>` | Список ошибок в хронологическом порядке. |
| **JSONPath** | `kubectl get cm <name> -o jsonpath='{.data.key}'` | Быстрая проверка наличия ключа без вывода всего объекта. |
| **RBAC Audit** | `kubectl auth can-i get secret/<name> --as system:serviceaccount:<ns>:<sa>` | Подтверждение (`yes`) наличия прав доступа. |
| **Volume Check** | `kubectl describe pvc <pvc-name>` | Определение причин застревания тома в `Pending`. |
| **CSI Health** | `kubectl get pods -n kube-system -l app.kubernetes.io/name=<driver>` | Проверка здоровья драйверов хранилища. |

## Практические сценарии

### Сценарий 1: Быстрый поиск причины через Events и фильтрацию

Самый эффективный способ — извлечь конкретное сообщение об ошибке, скрыв лишнюю информацию.

```bash
# Получение причины ожидания контейнера
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].state.waiting.message}'

# Пример вывода:
# → configmap "app-settings" not found
```

### Сценарий 2: Глубокая проверка ключей в ConfigMap/Secret

Часто ресурс существует, но в нем отсутствует ключ, указанный в `env` или `envFrom`.

```bash
# Проверка всех ключей в Secret
kubectl get secret <name> -o jsonpath='{.data}' | jq 'keys'

# Проверка, на какой ключ ссылается манифест пода
kubectl get pod <pod-name> -o json | jq '.spec.containers[].env[] | select(.valueFrom.configMapKeyRef) | .valueFrom.configMapKeyRef.key'
```

### Сценарий 3: Диагностика проблем с PersistentVolumeClaim (PVC)

Если ошибка связана с PVC, необходимо проверить не только сам объект, но и `StorageClass`.

```bash
# Проверка статуса и ошибок привязки
kubectl describe pvc <pvc-name>

# Типичная ошибка топологии (Multi-AZ):
# → Warning  FailedScheduling  ...  1 node(s) had volume node affinity conflict.

# Проверка StorageClass на наличие WaitForFirstConsumer (рекомендуется для облаков)
kubectl get sc <sc-name> -o jsonpath='{.volumeBindingMode}'
```

Подробнее: [Проблемы с PVC](./pvc_issues.md).

### Сценарий 4: Проверка прав доступа через ServiceAccount (Impersonation)

Если `kubectl get secret` работает у вас, это не значит, что он работает у пода.

```bash
# 1. Получаем SA пода
SA=$(kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}')

# 2. Проверяем возможность чтения конкретного секрета
kubectl auth can-i get secret/<secret-name> --as=system:serviceaccount:<namespace>:$SA
# → no  <-- Если 'no', нужно обновить RoleBinding/Role.
```

### Сценарий 5: Автоматизированный скрипт диагностики зависимостей

```bash
#!/bin/bash
# check-k8s-deps.sh: Проверка всех внешних зависимостей пода
POD=$1
NS=${2:-default}

echo "--- Диагностика зависимостей для $POD ---"

# Проверка ConfigMaps в env
echo "[ConfigMaps]"
for cm in $(kubectl get pod $POD -n $NS -o json | jq -r '.spec.containers[].env[].valueFrom.configMapKeyRef.name // empty'); do
    kubectl get cm $cm -n $NS >/dev/null 2>&1 || echo "!! КРИТИЧНО: ConfigMap $cm не найден"
done

# Проверка Secrets в volumes
echo "[Secrets (Volumes)]"
for sec in $(kubectl get pod $POD -n $NS -o json | jq -r '.spec.volumes[].secret.secretName // empty'); do
    kubectl get secret $sec -n $NS >/dev/null 2>&1 || echo "!! КРИТИЧНО: Secret $sec не найден"
done

# Проверка PVC
echo "[PVC]"
for pvc in $(kubectl get pod $POD -n $NS -o json | jq -r '.spec.volumes[].persistentVolumeClaim.claimName // empty'); do
    STATUS=$(kubectl get pvc $pvc -n $NS -o jsonpath='{.status.phase}')
    [[ "$STATUS" != "Bound" ]] && echo "!! ВНИМАНИЕ: PVC $pvc в статусе $STATUS"
done
```

## Дополнительная информация

### Место в процессе Troubleshooting

Диагностика `CreateContainerConfigError` — это граница между инфраструктурой и приложением. Она подтверждает, что «окружение готово», прежде чем управление будет передано процессу внутри контейнера.

*   [Жизненный цикл и состояния Pod](../../../Base/Pod/pod_lifecycle_and_state.md)
*   [Профилактика CreateContainerConfigError](./prevention.md)

### Связанные ресурсы

*   [Определения CreateContainerConfigError](./definitions.md)
*   [Проблемы с ConfigMap](./configmap_issues.md)
*   [Проблемы с Secret](./secret_issues.md)
*   [Проблемы с PVC](./pvc_issues.md)
*   [Проблемы с RBAC и ServiceAccount](./rbac_issues.md)
*   [Проблемы с томами](./volume_issues.md)
