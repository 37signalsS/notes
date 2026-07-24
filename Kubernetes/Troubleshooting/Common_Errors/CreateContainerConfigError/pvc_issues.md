# CreateContainerConfigError: Проблемы с PVC

## Определения

**PVC-related CreateContainerConfigError** — состояние пода, при котором он не может запустить контейнер из-за проблем с `PersistentVolumeClaim` (PVC). Хотя чаще проблемы с томами приводят к статусу `ContainerCreating` (ошибки монтирования), в некоторых конфигурациях и версиях Kubernetes некорректная ссылка на PVC или его отсутствие может блокировать генерацию конфигурации контейнера.

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Общие концепции хранилища (PV, PVC, StorageClass): [pv_and_pvc.md](../../../../Storage/pv_and_pvc.md).

## Основные концепции

### Типичные причины и сообщения об ошибках

| Сообщение в Events | Причина | Состояние ресурса |
|-----------|---------|-------------------|
| `persistentvolumeclaim "x" not found` | PVC с указанным именем не существует в данном Namespace | **Missing** |
| `failed to provision volume` | Ошибка на стороне StorageClass или CSI-драйвера | **Pending** |
| `No matching volume found` | Нет PV, удовлетворяющего требованиям PVC (AccessMode, Size, SC) | **Pending** |
| `Multi-Attach error` | Том ReadWriteOnce уже примонтирован к другому узлу | **Bound** (но ошибка монтирования) |
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

### Сценарий 2: Ошибки динамического создания (CSI Driver)

Если PVC долго находится в статусе `Pending`, необходимо проверить события самого PVC.

**Диагностика:**
```bash
kubectl describe pvc <pvc-name>
```

**Ожидаемый вывод при ошибке прав:**
```text
Events:
  Type     Reason              Age                From                         Message
  ----     ------              ----               ----                         -------
  Warning  VpcIdNotSpecified   2m (x5 over 10m)   ebs.csi.aws.com              Failed to create volume: VpcId not specified
  Warning  ProvisioningFailed  1m (x10 over 15m)  persistentvolume-controller  Failed to provision volume with StorageClass "ebs-sc": IAM permission denied
```

**Решение:** Проверьте логи CSI-контроллера (обычно в `kube-system`) и наличие необходимых IAM-ролей/секретов.

### Сценарий 3: Конфликт топологии (Topology / Multi-AZ)

Проблема возникает, когда PV привязан к конкретной зоне (например, `us-east-1a`), а под пытается запуститься на узле в `us-east-1b`.

**Диагностика:**
```bash
kubectl get nodes -L topology.kubernetes.io/zone
kubectl describe pv <pv-name> | grep nodeAffinity
```

**Решение:** Используйте `volumeBindingMode: WaitForFirstConsumer` в вашем `StorageClass`. Это заставит Kubernetes подождать, пока под не будет назначен на узел, и только потом создавать диск в той же зоне.

### Сценарий 4: Несовместимость режимов доступа (AccessMode)

PVC запрашивает `ReadWriteMany` (RWX), но StorageClass поддерживает только `ReadWriteOnce` (RWO).

**Диагностика:**
```bash
kubectl get storageclass <sc-name> -o yaml
# Проверьте параметры и возможности провижинера
```

**Решение:**
- Если нужны общие данные для многих подов, используйте СХД с поддержкой RWX (NFS, CephFS, Azure Files).
- Для блочных устройств (EBS, GCP PD) используйте только RWO.

### Сценарий 5: Превышение квот ресурсов

**Диагностика:**
```bash
kubectl describe resourcequota -n <namespace>
```

**Ожидаемый вывод:**
```text
Resource Quotas
 Name:            storage-quota
 Resource         Used  Hard
 --------         ---   ---
 requests.storage 90Gi  100Gi
 persistentvolumeclaims 10  10
```

**Решение:** Удалите неиспользуемые тома или запросите увеличение квоты у администратора кластера.

## Список проверок (Troubleshooting Checklist)

1.  **Namespace:** PVC и Pod находятся в одном и том же пространстве имен.
2.  **Events:** Выполнен `kubectl describe pvc <name>` для поиска сообщений от провижинера.
3.  **StorageClass:** Указано корректное имя `storageClassName`. Если не указано — проверьте наличие `default` StorageClass.
4.  **CSI Health:** Проверьте, что поды CSI-драйвера в `kube-system` запущены и не имеют ошибок.
5.  **Selector/Labels:** Если используется статическое выделение, убедитесь, что метки на PV и селектор в PVC совпадают.

## Дополнительная информация

### Связанные ресурсы

- [Обзор всех ошибок CreateContainerConfigError](../create_container_config_error.md)
- [Диагностика зависимостей пода](./diagnostics.md)
- [Подробно о PV/PVC](../../../../Storage/pv_and_pvc.md)
- [Настройка StorageClass](../../../../Storage/storageclass.md)
- [CSI Driver — архитектура](../../../../Storage/CSI/csi_overview.md)
