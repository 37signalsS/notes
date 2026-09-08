# CreateContainerConfigError: Диагностика

## Определения

**Диагностика CreateContainerConfigError** — систематический процесс выявления некорректно настроенных или отсутствующих зависимостей, которые блокируют формирование спецификации контейнера агентом `kubelet`. В отличие от прикладной отладки, этот процесс фокусируется на уровне управления (Control Plane) и взаимодействии узла с API-сервером.

Основной вызов диагностики заключается в том, что на этом этапе контейнер еще не создан в Container Runtime (CRI), поэтому стандартные инструменты (`kubectl logs`, `kubectl exec`) недоступны.

## Основные концепции

### Алгоритм диагностики (Workflow)

Процесс отладки должен следовать иерархии зависимостей: от API-объектов до прав доступа на узле. Этот процесс является итеративным — после каждого исправления необходимо перезапускать под и проверять результат.

1.  **Инспекция событий (Events):** Первичный поиск конкретного ресурса и причины отказа (NotFound, Forbidden). События — это единственный источник информации, пока контейнер не создан.
2.  **Валидация ссылок в PodSpec:** Проверка имен ConfigMap, Secret и PVC на наличие опечаток. Особое внимание — на Namespace, так как ресурсы должны находиться в том же пространстве имен.
3.  **Проверка доступности ресурса:** Подтверждение существования объекта в том же Namespace. Если ресурс существует, но в другом Namespace — это самая частая причина ошибки.
4.  **Целостность данных (Data Integrity):** Проверка наличия конкретных ключей в `data` ресурса, если используется `keyRef`. Ключи чувствительны к регистру и точке.
5.  **RBAC и ServiceAccount:** Проверка разрешений на чтение ресурсов от имени пода. Важно: `kubelet` использует системную идентификацию, но при чтении секретов для пода ограничивается правами ServiceAccount.
6.  **Уровень инфраструктуры (CSI/Provisioning):** Проверка статуса PVC и здоровья CSI-контроллеров, если ошибка связана с томами. Для эфемерных томов — проверка квот Namespace.
7.  **Проверка сетевой доступности API-сервера:** Если все ресурсы существуют и права корректны, но ошибка сохраняется — возможна проблема с сетевой связностью между kubelet и API-сервером.

### Ключевые команды и инструменты

| Инструмент | Команда / Метод | Ожидаемый результат |
| :--- | :--- | :--- |
| **Events** | `kubectl get events --field-selector involvedObject.name=<pod>` | Список ошибок в хронологическом порядке. |
| **JSONPath** | `kubectl get cm <name> -o jsonpath='{.data.key}'` | Быстрая проверка наличия ключа без вывода всего объекта. |
| **RBAC Audit** | `kubectl auth can-i get secret/<name> --as system:serviceaccount:<ns>:<sa>` | Подтверждение (`yes`) наличия прав доступа. |
| **Volume Check** | `kubectl describe pvc <pvc-name>` | Определение причин застревания тома в `Pending`. |
| **CSI Health** | `kubectl get pods -n kube-system -l app.kubernetes.io/name=<driver>` | Проверка здоровья драйверов хранилища. |
| **Kubelet Logs** | `journalctl -u kubelet -f --since "5 min ago"` | Мониторинг активности kubelet в реальном времени. |
| **API Server Audit** | `kubectl get --raw /api/v1/namespaces/<ns>/configmaps` | Проверка доступности API-сервера для конкретного Namespace. |

### Каталог типичных сообщений об ошибках

| Сообщение в Events | Причина | Категория | Решение |
| :--- | :--- | :--- | :--- |
| `configmap "x" not found` | ConfigMap не существует | Missing | Создайте ConfigMap или проверьте имя |
| `secret "x" not found` | Secret не существует | Missing | Создайте Secret или проверьте имя |
| `configmaps "x" not found: key "y" not found` | Ключ отсутствует в ConfigMap | Key Missing | Добавьте ключ в ConfigMap |
| `secret "x" not found: key "y" not found` | Ключ отсутствует в Secret | Key Missing | Добавьте ключ в Secret |
| `forbidden: user "x" cannot get resource "configmaps"` | Недостаточно прав | RBAC | Настройте Role/RoleBinding |
| `forbidden: user "x" cannot get resource "secrets"` | Недостаточно прав | RBAC | Настройте Role/RoleBinding |
| `projected volume error: configmap "x" not found` | Один из источников отсутствует | Volume | Проверьте все источники в projected |
| `hostPath type check failed` | Тип hostPath не совпадает | Volume | Проверьте существование пути |
| `failed to create emptyDir: quota exceeded` | Превышена квота | Quota | Увеличьте ResourceQuota |
| `pvc "x" not found` | PVC не существует | Missing | Создайте PVC |
| `pvc "x" is not bound` | PVC не привязан к PV | Provisioning | Проверьте StorageClass и PV |
| `serviceaccount "x" not found` | ServiceAccount не существует | Missing | Создайте ServiceAccount |
| `ConfigMap "x" is not a valid configmap` | Повреждены данные | Invalid | Пересоздайте ConfigMap |
| `Secret "x" is not a valid secret` | Повреждены данные | Invalid | Пересоздайте Secret |

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

### Сценарий 6: Диагностика проблем с Downward API

Downward API позволяет пробрасывать метаданные пода (имя, namespace, IP) внутрь контейнера. Ошибка возникает при обращении к полям, которые не могут быть разрешены на этапе старта.

**Типичные ошибки:**
- Обращение к `status.podIP` до назначения IP
- Использование несуществующих label/annotation
- Невалидный `fieldPath`

**Диагностика:**
```bash
# Проверка метаданных пода
kubectl get pod <pod-name> -o jsonpath='{.metadata.labels}' | jq

# Проверка событий на ошибки Downward API
kubectl describe pod <pod-name> | grep -A 5 "Events:"
# → Warning  Failed  ...  Error: fieldRef "status.podIP" is not supported
```

**Проверка допустимых полей (K8s 1.30+):**
```bash
# Список поддерживаемых полей для fieldRef
kubectl explain pod.spec.containers.env.valueFrom.fieldRef.fieldPath
# → DESCRIPTION: Path of the field to select in the specified API version.
# Valid values: metadata.name, metadata.namespace, metadata.uid,
# metadata.labels['<KEY>'], metadata.annotations['<KEY>'],
# spec.nodeName, spec.serviceAccountName, status.podIP, status.hostIP
```

**Решение:** Убедитесь, что `fieldPath` указывает на допустимое поле. Если под еще не получил IP, используйте `spec.nodeName` или добавьте `optional: true`.

### Сценарий 7: Диагностика ошибок Projected Volume

Projected Volume объединяет несколько источников (Secret, ConfigMap, Downward API, ServiceAccountToken). Сбой хотя бы одного источника блокирует запуск.

**Диагностика:**
```bash
# Проверка всех источников, указанных в манифесте
kubectl get secret <secret-name>,configmap <cm-name> -n <namespace>

# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 3 "Events:"
# → Warning  Failed  kubelet  Error: projected volume "vault-token": configmap "vault-config" not found
```

**Чеклист проверки Projected Volume:**
```bash
# 1. Проверка секретов
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data}' | jq 'keys'

# 2. Проверка ConfigMap
kubectl get configmap <cm-name> -n <namespace> -o jsonpath='{.data}' | jq 'keys'

# 3. Проверка ServiceAccountToken (если используется)
kubectl get sa <sa-name> -n <namespace> -o jsonpath='{.secrets}'

# 4. Проверка Downward API (метаданные пода)
kubectl get pod <pod-name> -o jsonpath='{.metadata.labels}'
```

**Решение:** Все источники в Projected Volume должны существовать. Для необязательных источников используйте `optional: true`.

### Сценарий 8: Диагностика Immutable ConfigMap/Secret

Если ConfigMap/Secret помечен как `immutable: true` и содержит некорректные данные, под не сможет запуститься до пересоздания ресурса.

**Диагностика:**
```bash
# Проверка иммутабельности ConfigMap
kubectl get configmap <cm-name> -o jsonpath='{.metadata.annotations}'
# → {"kubectl.kubernetes.io/last-applied-configuration":"..."}

# Или проверка через describe
kubectl describe configmap <cm-name> | grep -i immutable
# → Immutable: true

# Проверка иммутабельности Secret
kubectl get secret <secret-name> -o jsonpath='{.metadata.labels}'
# → {"immutable":"true"}  (если установлен через label)
```

**Решение:** Иммутабельные ресурсы нельзя редактировать. Создайте новый ConfigMap/Secret с правильными данными и обновите Pod/Deployment для использования нового ресурса.

### Сценарий 9: Диагностика проблем с Sidecar Containers (K8s 1.29+)

Нативные sidecar-контейнеры (init-контейнеры с `restartPolicy: Always`) запускаются перед основными контейнерами. Ошибка в конфигурации sidecar блокирует запуск всего пода.

**Диагностика:**
```bash
# Проверка статуса init-контейнеров
kubectl get pod <pod-name> -o jsonpath='{.status.initContainerStatuses}'
# → [{"name":"sidecar","state":{"waiting":{"reason":"CreateContainerConfigError","message":"..."}}]

# Проверка логов sidecar (если контейнер был создан ранее)
kubectl logs <pod-name> -c sidecar --previous
```

**Типичные ошибки:**
- Sidecar ссылается на ConfigMap/Secret, который не существует
- Sidecar использует ServiceAccount без необходимых прав
- Sidecar имеет некорректный `resourceRequirements`

**Решение:** Проверьте конфигурацию sidecar-контейнера отдельно от основных контейнеров. Убедитесь, что все зависимости sidecar доступны.

### Сценарий 10: Диагностика проблем с сетевой доступностью API-сервера

Если все ресурсы существуют и права корректны, но ошибка сохраняется — возможна проблема с сетевой связностью между kubelet и API-сервером.

**Диагностика:**
```bash
# Проверка доступности API-сервера из kubelet
kubectl get --raw /api/v1/namespaces/<namespace>/configmaps
# → Если ошибка — проблема с сетью или TLS

# Проверка сертификатов kubelet
ls -la /var/lib/kubelet/pki/
# → kubelet.crt, kubelet.key

# Проверка логов kubelet на ошибки сети
journalctl -u kubelet | grep -i "tls\|timeout\|connection refused"
```

**Типичные симптомы:**
- `context deadline exceeded` — таймаут соединения
- `connection refused` — API-сервер недоступен
- `x509: certificate signed by unknown authority` — проблемы с TLS

**Решение:** Проверьте сетевую связность, сертификаты и настройки TLS для kubelet.

## Дополнительная информация

### Место в процессе Troubleshooting

Диагностика `CreateContainerConfigError` — это граница между инфраструктурой и приложением. Она подтверждает, что «окружение готово», прежде чем управление будет передано процессу внутри контейнера.

**Дерево решений для диагностики:**

```
CreateContainerConfigError
├── Проверка Events (первый шаг)
│   ├── "not found" → Проверить существование ресурса
│   ├── "forbidden" → Проверить RBAC
│   ├── "key not found" → Проверить ключи в ресурсе
│   └── "not valid" → Пересоздать ресурс
├── Если Events нет подсказок
│   ├── Проверить Namespace mismatch
│   ├── Проверить иммутабельность
│   └── Проверить сетевую доступность API
└── Если ошибка сохраняется
    ├── Проверить логи kubelet
    ├── Проверить API-сервер
    └── Проверить сертификаты
```

*   [Жизненный цикл и состояния Pod](../../../Base/Pod/pod_lifecycle_and_state.md)
*   [Профилактика CreateContainerConfigError](./prevention.md)

### Расширенный скрипт диагностики

```bash
#!/bin/bash
# advanced-k8s-diagnostics.sh: Расширенная диагностика CreateContainerConfigError
POD=$1
NS=${2:-default}

echo "=== Расширенная диагностика $POD ==="

# 1. Проверка статуса пода
echo "[1. Статус пода]"
STATUS=$(kubectl get pod $POD -n $NS -o jsonpath='{.status.phase}')
echo "Phase: $STATUS"
WAITING=$(kubectl get pod $POD -n $NS -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}')
echo "Waiting reason: $WAITING"

# 2. Проверка ConfigMaps
echo -e "\n[2. ConfigMaps]"
for cm in $(kubectl get pod $POD -n $NS -o json | jq -r '
    .spec.containers[].env[].valueFrom.configMapKeyRef.name // empty,
    .spec.volumes[]?.configMap?.name // empty,
    .spec.volumes[]?.projected?.sources[]?.configMap?.name // empty
' | sort -u); do
    if ! kubectl get cm $cm -n $NS >/dev/null 2>&1; then
        echo "!! КРИТИЧНО: ConfigMap $cm не найден"
    else
        # Проверка ключей
        for key in $(kubectl get pod $POD -n $NS -o json | jq -r "
            .spec.containers[].env[] | select(.valueFrom.configMapKeyRef.name==\"$cm\") | .valueFrom.configMapKeyRef.key // empty
        "); do
            if ! kubectl get cm $cm -n $NS -o jsonpath="{.data.$key}" >/dev/null 2>&1; then
                echo "!! КРИТИЧНО: Ключ $key отсутствует в ConfigMap $cm"
            fi
        done
    fi
done

# 3. Проверка Secrets
echo -e "\n[3. Secrets]"
for sec in $(kubectl get pod $POD -n $NS -o json | jq -r '
    .spec.containers[].env[].valueFrom.secretKeyRef.name // empty,
    .spec.containers[].envFrom[].secretRef.name // empty,
    .spec.volumes[]?.secret?.secretName // empty,
    .spec.volumes[]?.projected?.sources[]?.secret?.name // empty
' | sort -u); do
    if ! kubectl get secret $sec -n $NS >/dev/null 2>&1; then
        echo "!! КРИТИЧНО: Secret $sec не найден"
    else
        # Проверка ключей
        for key in $(kubectl get pod $POD -n $NS -o json | jq -r "
            .spec.containers[].env[] | select(.valueFrom.secretKeyRef.name==\"$sec\") | .valueFrom.secretKeyRef.key // empty
        "); do
            if ! kubectl get secret $sec -n $NS -o jsonpath="{.data.$key}" >/dev/null 2>&1; then
                echo "!! КРИТИЧНО: Ключ $key отсутствует в Secret $sec"
            fi
        done
    fi
done

# 4. Проверка ServiceAccount
echo -e "\n[4. ServiceAccount]"
SA=$(kubectl get pod $POD -n $NS -o jsonpath='{.spec.serviceAccountName}' 2>/dev/null || echo "default")
if ! kubectl get sa $SA -n $NS >/dev/null 2>&1; then
    echo "!! КРИТИЧНО: ServiceAccount $SA не найден"
else
    # Проверка прав
    if ! kubectl auth can-i get secrets --as=system:serviceaccount:${NS}:${SA} -n $NS >/dev/null 2>&1; then
        echo "!! ВНИМАНИЕ: ServiceAccount $SA не имеет прав на чтение секретов"
    fi
fi

# 5. Проверка PVC
echo -e "\n[5. PVC]"
for pvc in $(kubectl get pod $POD -n $NS -o json | jq -r '.spec.volumes[].persistentVolumeClaim.claimName // empty'); do
    STATUS=$(kubectl get pvc $pvc -n $NS -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
    if [[ "$STATUS" != "Bound" ]]; then
        echo "!! ВНИМАНИЕ: PVC $pvc в статусе $STATUS"
        kubectl describe pvc $pvc -n $NS | grep -A 3 "Events:"
    fi
done

# 6. Проверка Downward API
echo -e "\n[6. Downward API]"
for field in $(kubectl get pod $POD -n $NS -o json | jq -r '
    .spec.containers[].env[]?.valueFrom?.fieldRef?.fieldPath // empty
'); do
    case $field in
        status.podIP|status.hostIP)
            IP=$(kubectl get pod $POD -n $NS -o jsonpath="{.status.podIP}" 2>/dev/null)
            if [[ -z "$IP" ]]; then
                echo "!! ВНИМАНИЕ: Поле $field еще не доступно"
            fi
            ;;
    esac
done

echo -e "\n=== Диагностика завершена ==="
```

### Связанные ресурсы

*   [Определения CreateContainerConfigError](./definitions.md)
*   [Проблемы с ConfigMap](./configmap_issues.md)
*   [Проблемы с Secret](./secret_issues.md)
*   [Проблемы с PVC](./pvc_issues.md)
*   [Проблемы с RBAC и ServiceAccount](./rbac_issues.md)
*   [Проблемы с томами](./volume_issues.md)
