# Сравнение и эксплуатация CSI-драйверов

Документ является основным источником (SSoT) для выбора, сравнения и первичной диагностики CSI-драйверов в Kubernetes.

## Определения

**CSI Driver (Container Storage Interface Driver)** — программная реализация спецификации интерфейса хранения контейнеров для конкретной системы хранения данных (СХД). Он выступает посредником между Kubernetes и API внешнего хранилища.

**Sidecar-контейнеры** — стандартные вспомогательные компоненты (external-provisioner, external-attacher и др.), которые обеспечивают интеграцию драйвера с объектами Kubernetes (PVC, PV, VolumeAttachment).

**Provisioner** — компонент драйвера, отвечающий за динамическое создание и удаление физических томов в СХД.

**Attacher** — компонент, отвечающий за логическую привязку (attach) тома к конкретному узлу кластера.

**Topology Awareness** — способность драйвера учитывать физическое расположение узлов (зоны, стойки) при планировании томов, обеспечивая локальность данных.

---

## Базовые концепции

### Сравнение возможностей популярных драйверов

Выбор драйвера зависит от типа инфраструктуры, требований к производительности и необходимости в дополнительных функциях (снапшоты, репликация).

#### Облачные и Enterprise решения

| СХД / Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **AWS EBS** (`ebs.csi.aws.com`) | Block | + | + | + | + | RWO, RWOP |
| **GCP PD** (`pd.csi.storage.gke.io`) | Block | + | + | + | + | RWO, RWOP |
| **Azure Disk** (`disk.csi.azure.com`) | Block | + | + | + | + | RWO, RWOP |
| **Yandex Disk** (`disk.csi.yandex.ru`) | Block | + | + | + | + | RWO, RWOP |
| **vSphere CSI** (`vsphere.csi.vmware.com`) | Block/File | + | + | + | + | RWO, RWX |
| **Portworx** (`pxd.portworx.com`) | Block | + | + | + | + | RWO, RWX |

#### Программно-определяемые (SDS) и Open Source

| СХД / Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Ceph RBD** (`rbd.csi.ceph.com`) | Block | + | + | + | + | RWO, RWOP |
| **CephFS** (`cephfs.csi.ceph.com`) | File | + | + | + | + | RWX, RWO |
| **Longhorn** (`driver.longhorn.io`) | Block | + | + | + | - | RWO, RWX |
| **Linstor** (`linstor.csi.linbit.com`) | Block | + | + | + | + | RWO, RWOP |
| **Mayastor** (`mayastor.openebs.io`) | Block | + | + | + | + | RWO |
| **Local Path** (`rancher.io/local-path`) | Local | - | - | - | + | RWO |
| **NFS** (`nfs.csi.k8s.io`) | File | - | - | - | - | RWX, RWO |
| **S3 CSI** (`csi-s3`, `geesefs`) | Object | - | - | - | - | RWO, RWX |
| **JuiceFS** (`juicefs.csi.k8s.io`) | File/S3 | + | + | + | + | RWX, RWO |

> **Примечание:** `RWOP` (ReadWriteOncePod) — эксклюзивный доступ только для одного пода на узле (доступно с Kubernetes 1.22+).

---

## Практические сценарии

### Выбор драйвера по критериям

1.  **Максимальная производительность (NVMe-oF):**
    *   Рекомендуется: **Mayastor (OpenEBS)** или **Linstor**. Идеально для высоконагруженных СУБД в bare-metal кластерах.
2.  **Отказоустойчивость и репликация (SDS):**
    *   Рекомендуется: **Ceph** (универсальность) или **Longhorn** (простота управления).
3.  **Общий доступ к файлам (Shared Storage):**
    *   Рекомендуется: **CephFS**, **NFS CSI** или **JuiceFS** (через S3).
4.  **Безопасное хранение секретов:**
    *   Используйте **Secrets Store CSI Driver**. Он монтирует данные из внешних хранилищ (Vault, AWS Secrets Manager) напрямую в `tmpfs` пода.

### Диагностика и эксплуатация

#### Инвентаризация CSI-ресурсов

```bash
# Список зарегистрированных драйверов и их возможностей
kubectl get csidrivers

# Информация о драйверах на узлах (топология, сокеты)
kubectl get csinodes

# Проверка статуса управляющих подов драйвера
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
```

#### Отладка жизненного цикла тома

Если PVC "завис" в статусе `Pending`, следуйте алгоритму:

1.  **Проверка PVC:** `kubectl describe pvc <name>`. Ищите события `FailedBinding` или ошибки провизионера.
2.  **Проверка StorageClass:** Убедитесь, что `provisioner` указан верно и драйвер запущен.
3.  **Логи контроллера:**
    ```bash
    kubectl logs -n kube-system -l app=csi-provisioner -c csi-provisioner
    ```
4.  **Проверка VolumeAttachment:** Для ошибок монтирования (Attach) проверьте объект привязки:
    ```bash
    kubectl get volumeattachment
    kubectl describe volumeattachment <id>
    ```

#### Типовые неисправности

| Симптом | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| `Pending` PVC (Topology) | Узлы в другой зоне или нет ресурсов | Проверить `WaitForFirstConsumer` в SC и доступные зоны в `csinodes`. |
| `MountVolume.SetUp failed` | Отсутствие бинарных файлов (iscsid, xfsprogs) | Установить зависимости на хосты (например, `apt install open-iscsi`). |
| `Permission Denied` | Неверные IAM-права или секреты | Проверить права ServiceAccount (IRSA для AWS) или `Secret` драйвера. |
| `Volume In Use` | Под не может отмонтировать диск | Проверить наличие финализаторов (`finalizers`) в объекте PV/PVC. |

### Лучшие практики эксплуатации

*   **Topology Awareness:** Всегда используйте `volumeBindingMode: WaitForFirstConsumer` для сетевых томов. Это гарантирует создание диска в той же зоне, где планировщик разместил под.
*   **Ресурсные лимиты:** Назначайте `PriorityClass: system-node-critical` для DaemonSet драйвера, чтобы предотвратить его вытеснение при нехватке памяти на узле.
*   **Мониторинг:** Настройте алерты на метрику `storage_operation_duration_seconds` для отслеживания задержек в операциях монтирования/создания.
*   **Безопасность:** Ограничивайте RBAC для драйвера только необходимыми пространствами имен или ресурсами.

---

## Дополнительная информация

### Связанные темы

- [Обзор CSI](./csi_overview.md) — детальная архитектура и жизненный цикл.
- [Продвинутые возможности CSI](./csi_advanced.md) — снапшоты, клонирование и расширение томов.
- [S3 CSI-драйверы](./s3-csi-drivers.md) — специфика работы с объектными хранилищами.
- [Persistent Volumes и PVC](../pv_and_pvc.md) — базовые объекты хранения.

### Ссылки

- [Kubernetes CSI Drivers List](https://kubernetes-csi.github.io/docs/drivers.html) — официальный реестр поддерживаемых драйверов.
- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/) — документация по интеграции внешних секретов.
- [CSI Spec GitHub](https://github.com/container-storage-interface/spec) — официальная спецификация интерфейса.
