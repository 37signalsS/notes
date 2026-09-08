# CreateContainerConfigError: Проблемы с PVC

## Определения

**PVC-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки к запуску контейнера, когда `kubelet` не может успешно обработать ссылки на `PersistentVolumeClaim` (PVC) в спецификации пода. Когда `kubelet` обнаруживает, что PVC не существует, недоступен или находится в состоянии, не позволяющем монтировать том, процесс формирования `ContainerConfig` для Container Runtime (CRI) прерывается, и поду назначается статус `CreateContainerConfigError`.

В отличие от ошибок монтирования (которые обычно приводят к статусу `ContainerCreating`), `CreateContainerConfigError` в контексте PVC возникает, когда система не может даже начать процесс подготовки тома из-за логических или конфигурационных ошибок в API Kubernetes.

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Общие концепции хранилища (PV, PVC, StorageClass): [pv_and_pvc.md](../../../../Storage/pv_and_pvc.md).

## Основные концепции

### Механизм возникновения ошибки в kubelet SyncPod Loop

Ошибка возникает в рабочем цикле `kubelet` (Pod Worker) до вызова CRI-метода `CreateContainer`. Понимание этого цикла критично для быстрой диагностики, так как события и статусы меняются на каждой итерации.

#### Полный workflow kubelet при работе с PVC

1.  **SyncPod Loop:** `kubelet` обнаруживает новый под, назначенный на узел (через `PodWorker`). Запускает итерацию `SyncPod`.
2.  **Volume Admission:** Проверка и начальная подготовка томов. `kubelet` читает секцию `volumes` из PodSpec.
3.  **Volume Manager Stage:** `kubelet` (через `volumeManager`) пытается сопоставить `persistentVolumeClaim.claimName` из манифеста с реальным объектом PVC в Namespace. Этот шаг выполняется через API-сервер.
4.  **PVC Resolution (Критическая фаза):**
    -   `kubelet` запрашивает через API-сервер информацию о PVC: статус (`Bound`, `Pending`, `Lost`), связанный PV, `storageClassName`, `accessModes`.
    -   Если PVC находится в статусе `Pending` (например, из-за `WaitForFirstConsumer`), `kubelet` не может перейти к монтированию.
    -   Если PVC не существует или недоступен (404/403), процесс блокируется.
5.  **CRI Config Generation:** `kubelet` пытается собрать `ContainerConfig` для передачи в рантайм (containerd/CRI-O). Эта конфигурация включает пути монтирования томов.
6.  **Блокировка:** Если на шаге 3 или 4 происходит сбой — PVC не найден, недоступен по RBAC, или находится в статусе, не позволяющем монтирование — `kubelet` выставляет статус `CreateContainerConfigError` и прекращает попытку создания контейнера. Под будет периодически переоцениваться (exponential backoff).

#### Важное различие: CreateContainerConfigError vs PodPending

| Аспект | CreateContainerConfigError (PVC) | PodPending (PVC) |
| :--- | :--- | :--- |
| **Этап блокировки** | После назначения на узел, на этапе `kubelet` preparation | На этапе планирования (scheduler) |
| **Статус пода** | `CreateContainerConfigError` в `containerStatuses` | Фаза `Pending` |
| **Триггер** | `kubelet` не может разрешить PVC в API | Планировщик не может назначить под на узел |
| **Возможная причина PVC** | PVC не существует, недоступен (RBAC), в статусе `Lost` | PVC в `Pending` (нет PV, топология), `WaitForFirstConsumer` deadlock |

### Типичные причины и сообщения об ошибках

| Сообщение в Events | Причина | Состояние ресурса |
|:---|:---|:---|
| `persistentvolumeclaim "x" not found` | PVC не существует или создана в другом Namespace | **Missing** |
| `forbidden: user ... cannot get resource "pvc"` | У ServiceAccount пода нет прав на чтение PVC | **Exists** (но недоступен) |
| `failed to provision volume` | Ошибка на стороне StorageClass или CSI-драйвера | **Pending** |
| `No matching volume found` | Нет PV, удовлетворяющего требованиям PVC (AccessMode, Size, SC) | **Pending** |
| `Multi-Attach error` | Том ReadWriteOnce уже примонтирован к другому узлу | **Bound** (ошибка монтирования) |
| `volume node affinity conflict` | Том находится в другой зоне доступности (AZ), чем узел пода | **Bound** |
| `persistentvolumeclaim "x" is in Pending state` | PVC не привязан к PV (обычно с `WaitForFirstConsumer`) | **Pending** |
| `persistentvolumeclaim "x" is in Lost state` | PV, связанный с PVC, удален или недоступен | **Lost** |
| `volume is being attached` / `nodeStage` timeout | CSI-драйвер не может примонтировать том на узле | **Bound** (но Stage ошибка) |
| `storageClass "x" not found` | StorageClass, указанный в PVC, не существует | **Pending** |

### Причины застревания PVC в статусе Pending

1.  **Отсутствие подходящего PV (Static Provisioning):** Если используется статическое выделение, ни один PV не соответствует параметрам `storageClassName`, `accessModes` и `capacity` запроса PVC.
2.  **Ошибки динамического провижинера:** CSI-драйвер (например, AWS EBS, GCE PD, Longhorn) не может создать физический диск из-за лимитов облака, проблем с правами (IAM) или недоступности API.
3.  **Проблемы топологии (AZ mismatch):** В мультизональных кластерах `StorageClass` с `volumeBindingMode: Immediate` может создать диск в Зоне А, в то время как планировщик отправит под в Зону Б.
4.  **Resource Quotas:** В Namespace достигнут лимит на количество PVC или суммарный объем запрашиваемого хранилища.
5.  **WaitForFirstConsumer Deadlock:** Pod не может быть запланирован из-за других ограничений (resource, affinity, taints), а PVC не привязывается, потому что ждет назначения Pod на узел. Это создает взаимоблокировку.

### Механизм работы Volume Attachment (Attach/Detach)

Для понимания ошибок монтирования важно знать, как том проходит путь от PVC к поду:

1.  **Provisioning:** `external-provisioner` (sidecar CSI) создает физический том и объект PV.
2.  **Attaching:** Планировщик назначает под на узел → `external-attacher` вызывает `ControllerPublishVolume` (привязка тома к узлу в СХД).
3.  **Staging (NodeStageVolume):** `kubelet` форматирует и монтирует том в глобальный путь (`/var/lib/kubelet/plugins/.../globalmount`).
4.  **Publishing (NodePublishVolume):** `kubelet` монтирует том из глобального пути в приватную директорию пода.

Если ошибка возникает на этапе 2 (Attach) — под получает `FailedAttachVolume` и остается в `ContainerCreating`, а не `CreateContainerConfigError`. Ошибка `CreateContainerConfigError` в контексте PVC возникает, когда `kubelet` не может даже начать этот процесс (steps 1–2 не завершены успешно).

Подробнее о механизмах CSI: [Обзор CSI](../../../../Storage/CSI/csi_overview.md).

## Практические сценарии

### Сценарий 1: PVC не найден (Namespace mismatch)

Одна из самых частых причин — манифест пода ссылается на PVC, который создан в другом Namespace или еще не применен.

**Диагностика:**
```bash
# Проверка наличия PVC в нужном namespace
kubectl get pvc -n <namespace>
# → No resources found in <namespace> namespace.

# Проверка всех PVC в кластере
kubectl get pvc --all-namespaces | grep "my-pvc"

# Проверка на опечатки в имени PVC в манифесте пода
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}'
```

**Решение:** Убедитесь, что PVC создан в том же Namespace, что и Pod. В Kubernetes тома являются ресурсами уровня Namespace.

### Сценарий 2: Отсутствие прав доступа (RBAC)

Ситуация, когда `ServiceAccount` пода не имеет прав на чтение PVC. Это актуально при использовании кастомных политик безопасности.

**Диагностика:**
```bash
# Проверка прав ServiceAccount
kubectl auth can-i get pvc/<pvc-name> --as=system:serviceaccount:<namespace>:<sa-name>
# → no

# Проверка текущего ServiceAccount пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Проверка Role/ClusterRole для ServiceAccount
kubectl get rolebinding,clusterrolebinding -A | grep <sa-name>
```

**Решение:** Обновите `Role`/`ClusterRole` для ServiceAccount, добавив доступ к ресурсам `persistentvolumeclaims`.
```bash
kubectl create role pvc-reader --verb=get,list,watch --resource=persistentvolumeclaims -n <namespace>
kubectl create rolebinding pvc-reader-binding --role=pvc-reader --serviceaccount=<namespace>:<sa-name> -n <namespace>
```

### Сценарий 3: Ошибки динамического создания (CSI Driver)

Если PVC долго находится в статусе `Pending`, необходимо проверить события самого PVC.

**Диагностика:**
```bash
kubectl describe pvc <pvc-name>

# Проверка сообщений об ошибках провижинирования
kubectl get events -n <namespace> --field-selector involvedObject.name=<pvc-name> --sort-by='.lastTimestamp'

# Проверка логов CSI-контроллера
kubectl logs -n kube-system -l app.kubernetes.io/name=<csi-driver-name> --since=1h
```

**Пример ошибки прав (IAM):**
```text
Events:
  Warning  ProvisioningFailed  1m  persistentvolume-controller  Failed to provision volume with StorageClass "ebs-sc": IAM permission denied
```

**Решение:** Проверьте логи CSI-контроллера в `kube-system` и наличие необходимых IAM-ролей/секретов у узлов или контроллера.

### Сценарий 4: Конфликт топологии (Topology / Multi-AZ)

Проблема возникает, когда PV привязан к конкретной зоне (например, `us-east-1a`), а под пытается запуститься на узле в `us-east-1b`.

**Диагностика:**
```bash
kubectl get nodes -L topology.kubernetes.io/zone
kubectl describe pv <pv-name> | grep nodeAffinity
kubectl get pvc <pvc-name> -o jsonpath='{.spec.storageClassName}'
kubectl get sc <sc-name> -o jsonpath='{.volumeBindingMode}'
```

**Решение:** Используйте `volumeBindingMode: WaitForFirstConsumer` в `StorageClass`. Это заставит Kubernetes подождать, пока под не будет назначен на узел, и только потом создавать диск в той же зоне.

### Сценарий 5: Несовместимость режимов доступа (AccessMode)

PVC запрашивает `ReadWriteMany` (RWX), но StorageClass поддерживает только `ReadWriteOnce` (RWO).

**Диагностика:**
```bash
# Проверка запрашиваемого режима доступа
kubectl get pvc <pvc-name> -o jsonpath='{.spec.accessModes}'

# Проверка поддерживаемых режимов StorageClass (через CSI-driver capabilities)
kubectl get csidriver -o json | jq -r '.items[].metadata.name'
kubectl describe csidriver <driver-name>
```

**Решение:** Используйте СХД с поддержкой RWX (NFS, CephFS) или измените режим доступа в PVC на RWO, если приложение поддерживает запуск только одной реплики.

### Сценарий 6: Использование ReadWriteOncePod (RWOP)

Новый режим доступа (GA v1.27), который ограничивает доступ к тому только ОДНИМ подом во всем кластере.

**Симптом:** Второй под не может запуститься и застревает в `CreateContainerConfigError`, так как `kubelet` видит нарушение политики доступа на этапе формирования конфига.

**Диагностика:**
```bash
# Проверка режима доступа в PVC
kubectl get pvc <pvc-name> -o jsonpath='{.spec.accessModes}'

# Проверка фазы PVC
kubectl get pvc <pvc-name> -o jsonpath='{.status.phase}'

# Проверка, кто использует том
kubectl get pods -A -o json | jq -r --arg pvc "<pvc-name>" '.items[] | .spec.volumes[]? | select(.persistentVolumeClaim.claimName == $pvc) | "\(.metadata.namespace)/\(.metadata.name)"'
```

### Сценарий 7: Ошибки в Generic Ephemeral Volumes (K8s 1.23+)

Инлайн-PVC, жизненный цикл которых привязан к поду. Ошибка в `volumeClaimTemplate` (например, неверный `storageClassName`) блокирует под.

**Диагностика:**
```bash
kubectl get pvc # Ищите <pod-name>-<volume-name>
kubectl describe pvc <ephemeral-pvc-name>

# Проверка статуса PVC эпхемерного тома
kubectl get pvc <ephemeral-pvc-name> -o jsonpath='{.status.phase} {.status.message}'
```

### Сценарий 8: Превышение квот ресурсов

**Диагностика:**
```bash
kubectl describe resourcequota -n <namespace>
kubectl get resourcequota -n <namespace> -o json | jq '.items[] | select(.metadata.name=="compute-quota") | .status'
```

**Решение:** Удалите неиспользуемые тома или увеличьте квоты `requests.storage` и `persistentvolumeclaims`.

### Сценарий 9: PVC в статусе Lost

Когда PV, связанный с PVC, удален из СХД или стал недоступным (но PVC имеет `reclaimPolicy: Retain`), PVC переходит в статус `Lost`. Это блокирует `kubelet` на этапе разрешения тома.

**Диагностика:**
```bash
kubectl get pvc <pvc-name> -o jsonpath='{.status.phase}'
# → Lost

kubectl get pv | grep <pv-name>
# → может быть пустым (PV удален)

kubectl describe pvc <pvc-name>
# → события будут показывать проблемы с доступом к томам
```

**Решение:**
```bash
# Вариант A: Восстановить PV вручную (если физический диск существует)
kubectl patch pv <pv-name> -p '{"spec":{"claimRef":{"name":"<pvc-name>","namespace":"<namespace>","uid":"<pvc-uid>"}}}'

# Вариант B: Удалить PVC и создать новый (потеря данных)
kubectl delete pvc <pvc-name>
kubectl apply -f new-pvc.yaml
```

### Сценарий 10: Статическое PV с неверным storageClassName

PVC указывает `storageClassName: ""` (пустая строка), что означает использование PV без StorageClass. Если PV имеет другой `storageClassName`, привязка не произойдет.

**Диагностика:**
```bash
# Проверка storageClassName в PVC
kubectl get pvc <pvc-name> -o jsonpath='{.spec.storageClassName}'

# Проверка storageClassName в PV
kubectl get pv <pv-name> -o jsonpath='{.spec.storageClassName}'

# Поиск непривязанных PV без StorageClass
kubectl get pv | grep -E 'Available|Released' | grep None
```

**Решение:**
```bash
# Установить пустой storageClassName в PVC для связывания с PV без класса
kubectl patch pvc <pvc-name> -p '{"spec":{"storageClassName": null}}'

# Или изменить storageClassName на PV
kubectl patch pv <pv-name> -p '{"spec":{"storageClassName": "manual"}}'
```

### Сценарий 11: WaitForFirstConsumer Deadlock

PVC не привязывается, потому что Pod не может быть запланирован, а PVC ждет назначения Pod на узел.

**Диагностика:**
```bash
# Проверка статуса PVC
kubectl get pvc <pvc-name> -o jsonpath='{.status.phase}'
# → Pending

# Проверка событий PVC
kubectl describe pvc <pvc-name>
# → события покажут, что provisioner ждет назначения пода на узел

# Проверка, почему под не планируется
kubectl describe pod <pod-name> | grep -A10 "Events:"
# → FailedScheduling: 0/5 nodes are available: 1 pod(s) had volume node affinity conflict

# Проверка ограничений пода
kubectl get pod <pod-name> -o json | jq '{nodeSelector, affinity, tolerations, volumes}'
```

**Решение:**
```bash
# Исправьте ограничения планирования пода (resource, affinity, taints)
# Или временно измените volumeBindingMode на Immediate (рискованно)
# Или создайте статический PV в нужной зоне
```

### Сценарий 12: Automated Dependency Checker (SRE Script)

Скрипт для проверки всех PVC-зависимостей пода перед релизом:

```bash
#!/bin/bash
# check-pvc-deps.sh: Проверка PVC-зависимостей пода
POD=$1
NS=${2:-default}

echo "--- PVC Dependency Check для $POD ---"

# 1. Проверка наличия PVC
echo "[PVC Existence]"
for pvc in $(kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}'); do
    if kubectl get pvc $pvc -n $NS >/dev/null 2>&1; then
        STATUS=$(kubectl get pvc $pvc -n $NS -o jsonpath='{.status.phase}')
        echo "✓ PVC $pvc найден (status: $STATUS)"
        if [[ "$STATUS" != "Bound" ]]; then
            echo "  ⚠ WARNING: PVC не в статусе Bound!"
        fi
    else
        echo "✗ CRITICAL: PVC $pvc не найден в namespace $NS"
    fi
done

# 2. Проверка StorageClass
echo "[StorageClass]"
for sc in $(kubectl get pod $POD -n $NS -o json | jq -r '.spec.volumes[]?.persistentVolumeClaim.claimName // empty' | while read pvc; do
    kubectl get pvc $pvc -n $NS -o jsonpath='{.spec.storageClassName}' 2>/dev/null
done); do
    if kubectl get sc $sc >/dev/null 2>&1; then
        echo "✓ StorageClass $sc существует"
        kubectl get sc $sc -o jsonpath='{.volumeBindingMode}' | xargs -I{} echo "  bindingMode: {}"
    else
        echo "✗ CRITICAL: StorageClass $sc не найден"
    fi
done

# 3. Проверка PVC в namespace cluster-wide (cross-namespace reference detection)
echo "[Cross-namespace Check]"
kubectl get pods -A -o json | jq -r --arg pod "$POD" --arg ns "$NS" \
    '.items[] | select(.metadata.name == $pod and .metadata.namespace == $ns) | 
     .spec.volumes[]?.persistentVolumeClaim.claimName // empty' | while read pvc; do
    # PVC должен быть в том же namespace
    if ! kubectl get pvc $pvc -n $NS >/dev/null 2>&1; then
        FOUND_NS=$(kubectl get pvc $pvc --all-namespaces -o jsonpath='{.items[].metadata.namespace}' 2>/dev/null)
        if [[ -n "$FOUND_NS" ]]; then
            echo "✗ CRITICAL: PVC $pvc найден в namespace $FOUND_NS, а под в $NS"
        fi
    fi
done

# 4. Проверка ResourceQuota
echo "[ResourceQuota]"
QUOTA=$(kubectl get resourcequota -n $NS -o json 2>/dev/null | jq -r '.items[0].status.used.storage || "unlimited"')
echo "  Used PVC storage quota: $QUOTA"
```

## Граничные случаи (Edge Cases)

| Ситуация | Почему возникает CreateContainerConfigError | Как предотвратить |
| :--- | :--- | :--- |
| **PVC с пустым storageClassName** | PVC не может связаться с ни одним PV, если нет default StorageClass | Убедитесь, что storageClassName указан явно или существует default SC |
| **PV с другим storageClassName** | PVC и PV не связываются из-за несовпадения классов хранилища | Используйте `storageClassName: ""` в обоих объектах для статического привязывания |
| **CSI Driver не зарегистрирован на узле** | `kubelet` не может найти unix socket драйвера в `/var/lib/kubelet/plugins/<driver>/` на узле | Проверьте `kubectl describe csinode <node>` и статус DaemonSet CSI Node Plugin |
| **VolumeAttachment застрел в Creating** | CSI Controller не отвечает или сеть между контроллером и `external-attacher` оборвана | Проверьте логи `external-attacher` и сетевые политики в namespace CSI |
| **PVC слишком большой для PV** | PV меньше запрошенного объема в PVC | Убедитесь, что `resources.requests.storage` PVC <= `spec.capacity.storage` PV |
| **RWOP конфликт** | Второй под пытается использовать том с `ReadWriteOncePod` | Используйте другой PVC или дождитесь завершения первого пода |
| **Deleted PVC с Retain** | PVC удалён, но PV в статусе `Released` с `reclaimPolicy: Retain` — новая PVC не может привязаться | Вручную удалите `claimRef` из PV перед созданием нового PVC |

## Очистка и откат (Cleanup & Rollback)

### Допрос ссылок перед удалением PVC

Перед удалением PVC убедитесь, что на него нет ссылок в работающих подах:

```bash
# Поиск подов, использующих конкретный PVC
PVC_NAME="<pvc-name>"
NAMESPACE="<namespace>"
kubectl get pods -n $NAMESPACE -o json | jq -r --arg pvc "$PVC_NAME" \
    '.items[] | select(.spec.volumes != null) | .spec.volumes[]? | 
     select(.persistentVolumeClaim.claimName == $pvc) | 
     "\(.metadata.name)"'

# Проверка статуса PVC перед удалением
kubectl get pvc $PVC_NAME -n $NAMESPACE -o jsonpath='{.status.phase}'

# Проверка, что поды использующе этот PVC не запущены
kubectl get pods -n $NAMESPACE -o json | jq -r --arg pvc "$PVC_NAME" \
    '[.items[] | select(.spec.volumes != null) | .spec.volumes[]? | 
      select(.persistentVolumeClaim.claimName == $pvc) | .metadata.name] | 
      length' 
```

### Безопасное удаление PVC

```bash
# 1. Остановите поды, использующие PVC (если применимо)
kubectl rollout pause deployment/<name>

# 2. Проверьте, что никто не использует PVC
REFCOUNT=$(kubectl get pods -n $NAMESPACE -o json | jq --arg name "$PVC_NAME" \
    '[.items[] | .spec.volumes[]? | 
      select(.persistentVolumeClaim.claimName == $name)] | length')
[[ "$REFCOUNT" -gt 0 ]] && echo "WARNING: PVC used by $REFCOUNT pods" && exit 1

# 3. Удалите PVC
kubectl delete pvc $PVC_NAME -n $NAMESPACE

# 4. Если reclaimPolicy: Retain — PV перейдет в Released. Удалите его вручную:
kubectl delete pv <pv-name>
# (Данные на физическом диске сохранятся)

# 5. Возобновите deployment
kubectl rollout resume deployment/<name>
```

### Восстановление PVC после удаления

```bash
# Если PVC был удален, а PV остался в Released (retainPolicy: Retain):
kubectl patch pv <pv-name> -p '{"spec":{"claimRef": null}}'
kubectl patch pv <pv-name> -p '{"spec":{"claimRef":{"name":"<pvc-name>","namespace":"<namespace>","uid":"<new-pvc-uid>"}}}'

# Или создайте новый PVC с volumeName для статического привязывания:
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: recovered-pvc
  namespace: <namespace>
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ""
  volumeName: <pv-name>
  resources:
    requests:
      storage: 50Gi
EOF
```

### Откат изменений StorageClass

```bash
# 1. Просмотр истории изменений
kubectl rollout history deployment/<name>

# 2. Откат на конкретную ревизию
kubectl rollout undo deployment/<name> --to-revision=<n>

# 3. Если StorageClass был изменен — создайте новый с нужными параметрами
# и обновите PVC для использования нового класса (только для новых томов)
kubectl apply -f original-storageclass.yaml
```

## Мониторинг и алертинг (Prometheus)

Настройка алертов для раннего обнаружения проблем с PVC:

```yaml
# PrometheusRule для мониторинга PVC
groups:
- name: kubernetes.pvc.alerts
  rules:
  - alert: PVCNotBound
    expr: kube_persistentvolumeclaim_resource_requests_storage_bytes > 0 and on(persistentvolumeclaim,namespace) kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} в статусе Pending более 10 минут"
      description: "PVC не может быть привязан к PV. Проверьте StorageClass и provisioner."

  - alert: PVCapacityLow
    expr: kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes < 0.1
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "На томе {{ $labels.persistentvolumeclaim }} мало свободного места (< 10%)"
      description: "PVC требует расширения или очистки данных."
```

### Автоматизированная проверка здоровья CSI

```bash
#!/bin/bash
# csi-health-check.sh: Проверка здоровья CSI-драйверов

echo "=== CSI Health Check ==="

# 1. Проверка CSIDriver объектов
kubectl get csidriver -o json | jq -r '.items[].metadata.name' | while read driver; do
    echo "Checking driver: $driver"
    kubectl get csidriver $driver -o jsonpath='{.spec.attachRequired} {.spec.volumeLifecycleModes}'
done

# 2. Проверка controller plugin pods
kubectl get pods -n kube-system -l app=csi-controller -o json | jq -r '.items[] | select(.status.phase != "Running") | "ALERT: \(.metadata.name) не в Running"'

# 3. Проверка node plugin pods
kubectl get pods -n kube-system -l app=csi-node -o json | jq -r '.items[] | select(.status.phase != "Running") | "ALERT: \(.metadata.name) не в Running"'

# 4. Проверка CSINode объектов (регистрация на узлах)
kubectl get csinode -o json | jq -r '.items[] | select(.status = null or (.status.drivers | length == 0)) | "ALERT: \(.metadata.name) нет зарегистрованных драйверов"'

# 5. Проверка VolumeAttacheментов в состоянии ошибки
kubectl get volumeattachment -o json | jq -r '.items[] | select(.status.attached == false) | "WARNING: \(.metadata.name) не прикреплен"'
```

## Список проверок (Checklist)

1.  **Namespace Integration:** PVC и Pod находятся в одном и том же пространстве имен.
2.  **Events Audit:** Выполнен `kubectl describe pvc <name>` и `kubectl describe pod <name>`.
3.  **RBAC Check:** ServiceAccount имеет права `get`, `list`, `watch` на `persistentvolumeclaims`.
4.  **StorageClass Validity:** Указано корректное имя `storageClassName`. Если не указано — проверьте `default` SC.
5.  **CSI Health:** Поды CSI-драйвера в `kube-system` запущены и не имеют `CrashLoopBackOff`.
6.  **Node Affinity:** Параметры `nodeAffinity` в PV позволяют запуск на целевых узлах.
7.  **PVC Status:** PVC находится в статусе `Bound`, а не `Pending` или `Lost`.
8.  **StorageClass Provisioner:** CSI-драйвер запущен и healthy.
9.  **Resource Quota:** Квоты на хранилище не превышены в Namespace.
10. **Volume Binding Mode:** `WaitForFirstConsumer` используется для мультизональных кластеров.
11. **Access Modes:** Режимы доступа в PVC совместимы с StorageClass и CSI-драйвером.
12. **Volume Attachment:** `VolumeAttachment` в статусе `Attached` для используемого PVC.
13. **Reclaim Policy:** `reclaimPolicy: Retain` для production данных.
14. **Capacity:** Размер PVC не превышает размер PV.

## Дополнительная информация

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Определения CreateContainerConfigError](./definitions.md)
- [Проблемы с томами (не-PVC)](./volume_issues.md)
- [Общее диагностика проблем с PVC](./diagnostics.md#сценарий-3-диагностика-проблем-с-persistentvolumeclaim-pvc)
- [Подробно о PV/PVC](../../../../Storage/pv_and_pvc.md)
- [Настройка StorageClass](../../../../Storage/storageclass.md)
- [CSI Driver — архитектура](../../../../Storage/CSI/csi_overview.md)
- [Расширенные сценарии PV/PVC](../../../../Storage/pv_pvc_advanced.md)
- [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md)