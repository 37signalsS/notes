# CreateContainerConfigError: Проблемы с PVC

## Определения

**PVC-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки к запуску контейнера, когда `kubelet` не может успешно обработать ссылки на `PersistentVolumeClaim` (PVC) в спецификации пода. 

В отличие от ошибок монтирования (которые обычно приводят к статусу `ContainerCreating`), `CreateContainerConfigError` в контексте PVC возникает, когда система не может даже начать процесс подготовки тома из-за логических или конфигурационных ошибок в API Kubernetes.

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Общие концепции хранилища (PV, PVC, StorageClass): [pv_and_pvc.md](../../../../Storage/pv_and_pvc.md).

## Основные концепции

### Механизм возникновения ошибки

1.  **Сборка спецификации (Pod Admission/Binding):** После назначения пода на узел, `kubelet` запрашивает из API-сервера полную информацию о всех ресурсах, указанных в `volumes`.
2.  **Разрешение ссылок (Volume Resolution):** `kubelet` пытается сопоставить `persistentVolumeClaim.claimName` из манифеста с реальным объектом в Namespace.
3.  **Остановка на этапе подготовки:** Если API-сервер возвращает `404 Not Found` или `403 Forbidden` для объекта PVC, `kubelet` не может сформировать структуру данных для Container Runtime (CRI).
4.  **Статус:** Процесс создания контейнера блокируется, поду присваивается статус `CreateContainerConfigError`.

### Типичные причины и сообщения об ошибках

| Сообщение в Events | Причина | Состояние ресурса |
|:---|:---|:---|
| `persistentvolumeclaim "x" not found` | PVC не существует или создана в другом Namespace | **Missing** |
| `forbidden: user ... cannot get resource "pvc"` | У ServiceAccount пода нет прав на чтение PVC | **Exists** (но недоступен) |
| `failed to provision volume` | Ошибка на стороне StorageClass или CSI-драйвера | **Pending** |
| `No matching volume found` | Нет PV, удовлетворяющего требованиям PVC (AccessMode, Size, SC) | **Pending** |
| `Multi-Attach error` | Том ReadWriteOnce уже примонтирован к другому узлу | **Bound** (ошибка монтирования) |
| `volume node affinity conflict` | Том находится в другой зоне доступности (AZ), чем узел пода | **Bound** |

### Причины застревания PVC в статусе Pending

1.  **Отсутствие подходящего PV (Static Provisioning):** Если используется статическое выделение, ни один PV не соответствует параметрам `storageClassName`, `accessModes` и `capacity` запроса PVC.
2.  **Ошибки динамического провижинера:** CSI-драйвер (например, AWS EBS, GCE PD, Longhorn) не может создать физический диск из-за лимитов облака, проблем с правами (IAM) или недоступности API.
3.  **Проблемы топологии (AZ mismatch):** В мультизональных кластерах `StorageClass` с `volumeBindingMode: Immediate` может создать диск в Зоне А, в то время как планировщик отправит под в Зону Б.
4.  **Resource Quotas:** В Namespace достигнут лимит на количество PVC или суммарный объем запрашиваемого хранилища.

## Практические сценарии

### Сценарий 1: PVC не найден (Namespace mismatch)

Одна из самых частых причин — манифест пода ссылается на PVC, который создан в другом Namespace или еще не применен.

**Диагностика:**
```bash
# Проверка наличия PVC в нужном namespace
kubectl get pvc -n <namespace>
# → No resources found in <namespace> namespace.
```

**Решение:** Убедитесь, что PVC создан в том же Namespace, что и Pod. В Kubernetes тома являются ресурсами уровня Namespace.

### Сценарий 2: Отсутствие прав доступа (RBAC)

Ситуация, когда `ServiceAccount` пода не имеет прав на получение информации о PVC. Это актуально при использовании кастомных политик безопасности.

**Диагностика:**
```bash
# Проверка прав ServiceAccount
kubectl auth can-i get pvc/<pvc-name> --as=system:serviceaccount:<namespace>:<sa-name>
# → no
```

**Решение:** Обновите `Role`/`ClusterRole` для ServiceAccount, добавив доступ к ресурсам `persistentvolumeclaims`.

### Сценарий 3: Ошибки динамического создания (CSI Driver)

Если PVC долго находится в статусе `Pending`, необходимо проверить события самого PVC.

**Диагностика:**
```bash
kubectl describe pvc <pvc-name>
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
```

**Решение:** Используйте `volumeBindingMode: WaitForFirstConsumer` в `StorageClass`. Это заставит Kubernetes подождать, пока под не будет назначен на узел, и только потом создавать диск в той же зоне.

### Сценарий 5: Несовместимость режимов доступа (AccessMode)

PVC запрашивает `ReadWriteMany` (RWX), но StorageClass поддерживает только `ReadWriteOnce` (RWO).

**Решение:** Используйте СХД с поддержкой RWX (NFS, CephFS) или измените режим доступа в PVC на RWO, если приложение поддерживает запуск только одной реплики.

### Сценарий 6: Использование ReadWriteOncePod (RWOP)

Новый режим доступа (GA v1.27), который ограничивает доступ к тому только ОДНИМ подом во всем кластере.

**Симптом:** Второй под не может запуститься и застревает в `CreateContainerConfigError`, так как `kubelet` видит нарушение политики доступа на этапе формирования конфига.

### Сценарий 7: Ошибки в Generic Ephemeral Volumes (K8s 1.23+)

Инлайн-PVC, жизненный цикл которых привязан к поду. Ошибка в `volumeClaimTemplate` (например, неверный `storageClassName`) блокирует под.

**Диагностика:**
```bash
kubectl get pvc # Ищите <pod-name>-<volume-name>
kubectl describe pvc <ephemeral-pvc-name>
```

### Сценарий 8: Превышение квот ресурсов

**Диагностика:**
```bash
kubectl describe resourcequota -n <namespace>
```

**Решение:** Удалите неиспользуемые тома или увеличьте квоты `requests.storage` и `persistentvolumeclaims`.

## Список проверок (Troubleshooting Checklist)

1.  **Namespace Integration:** PVC и Pod находятся в одном и том же пространстве имен.
2.  **Events Audit:** Выполнен `kubectl describe pvc <name>` и `kubectl describe pod <name>`.
3.  **RBAC Check:** ServiceAccount имеет права `get`, `list`, `watch` на `persistentvolumeclaims`.
4.  **StorageClass Validity:** Указано корректное имя `storageClassName`. Если не указано — проверьте `default` SC.
5.  **CSI Health:** Поды CSI-драйвера в `kube-system` запущены и не имеют `CrashLoopBackOff`.
6.  **Node Affinity:** Параметры `nodeAffinity` в PV позволяют запуск на целевых узлах.

## Дополнительная информация

### Связанные ресурсы

- [Обзор всех ошибок CreateContainerConfigError](../create_container_config_error.md)
- [Диагностика зависимостей пода](./diagnostics.md)
- [Проблемы с томами (не-PVC)](./volume_issues.md)
- [Подробно о PV/PVC](../../../../Storage/pv_and_pvc.md)
- [Настройка StorageClass](../../../../Storage/storageclass.md)
- [CSI Driver — архитектура](../../../../Storage/CSI/csi_overview.md)
