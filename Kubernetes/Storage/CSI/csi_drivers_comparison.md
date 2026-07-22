# Сравнение и эксплуатация CSI-драйверов

## Определения

**CSI Driver (Container Storage Interface Driver)** — программная реализация спецификации интерфейса хранения контейнеров для конкретной системы хранения данных (СХД). Он выступает посредником между Kubernetes и API внешнего хранилища.

**Sidecar-контейнеры** — стандартные вспомогательные компоненты (external-provisioner, external-attacher и др.), которые обеспечивают интеграцию драйвера с объектами Kubernetes (PVC, PV, VolumeAttachment).

**Provisioner** — компонент драйвера, отвечающий за динамическое создание и удаление физических томов в СХД.

**Attacher** — компонент, отвечающий за логическую привязку (attach) тома к конкретному узлу кластера.

> **Базовая информация:** [Обзор CSI](./csi_overview.md), [Продвинутые возможности CSI](./csi_advanced.md).

---

## Базовые концепции

### Сравнение возможностей популярных драйверов

Выбор драйвера зависит от типа инфраструктуры и функциональных требований (безопасность, производительность, возможность создания снимков).

#### Облачные провайдеры (Managed CSI)

| СХД / Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **AWS EBS** (`ebs.csi.aws.com`) | Block | + | + | + | + | RWO, RWOP |
| **GCP PD** (`pd.csi.storage.gke.io`) | Block | + | + | + | + | RWO, RWOP |
| **Azure Disk** (`disk.csi.azure.com`) | Block | + | + | + | + | RWO, RWOP |
| **Yandex Disk** (`disk.csi.yandex.ru`) | Block | + | + | + | + | RWO, RWOP |

#### Локальные и Open Source решения

| СХД / Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Ceph RBD** (`rbd.csi.ceph.com`) | Block | + | + | + | + | RWO, RWOP |
| **CephFS** (`cephfs.csi.ceph.com`) | File | + | + | + | + | RWX, RWO |
| **Longhorn** (`driver.longhorn.io`) | Block | + | + | + | - | RWO, RWX |
| **Portworx** (`pxd.portworx.com`) | Block | + | + | + | + | RWO, RWX |
| **Local Path** (`rancher.io/local-path`) | Local | - | - | - | + | RWO |
| **NFS** (`nfs.csi.k8s.io`) | File | - | - | - | - | RWX, RWO |
| **S3 CSI** (`csi-s3`) | Object | - | - | - | - | RWO, RWX |

> **Примечание:** `RWOP` (ReadWriteOncePod) — эксклюзивный доступ только для одного пода на узле (доступно с Kubernetes 1.22+).

---

## Практические сценарии

### Выбор драйвера для объектного хранилища (S3)

Для монтирования S3-бакетов в поды как файловых систем используются специализированные CSI-драйверы:
- **ctrox/csi-s3**: Универсальный драйвер с поддержкой Goofys, s3fs и rclone.
- **yandex-cloud/k8s-csi-s3**: Оптимизированный форк с использованием GeeseFS.

Подробное сравнение и инструкции по установке: **[S3 CSI-драйверы](./s3-csi-drivers.md)**.

### Диагностика и эксплуатация

#### Инвентаризация CSI-ресурсов

```bash
# Список зарегистрированных драйверов и их возможностей (Attach, PodInfo)
kubectl get csidrivers

# Информация о драйверах, зарегистрированных на конкретных узлах
kubectl get csinodes

# Проверка статуса подов драйвера (обычно в kube-system или отдельном namespace)
kubectl get pods -A -l app.kubernetes.io/instance=<driver-name>
```

#### Отладка жизненного цикла тома

Если PVC "завис" в статусе `Pending`, проверьте цепочку событий:

1.  **Provisioning (Создание):**
    ```bash
    kubectl describe pvc <pvc-name>
    # Ищите ошибки: "failed to provision volume", "permission denied"
    ```
2.  **Attaching (Привязка к ноде):**
    ```bash
    kubectl get volumeattachment
    kubectl describe volumeattachment <attachment-id>
    # Ошибки часто связаны с лимитами дисков на одну ВМ или зонами доступности.
    ```
3.  **Логи контроллера (Sidecars):**
    ```bash
    # Логи компонента, отвечающего за создание томов
    kubectl logs -n <namespace> -l app=<driver-controller> -c csi-provisioner
    ```

#### Типовые неисправности

| Симптом | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| `Pending` PVC (FailedScheduling) | Несовпадение зон (Topology) | Проверить `nodeSelector` пода и зоны в `StorageClass`. |
| `MountVolume.SetUp failed` | Отсутствие утилит (nfs-common, ceph-common) | Установить необходимые пакеты на все рабочие узлы. |
| `VolumeExpansion` завис | ФС не поддерживает resize онлайн | Перезагрузить под для выполнения resize офлайн. |
| `AttachVolume.Attach` timeout | Лимит дисков на облачную ВМ | Использовать ВМ большего размера или увеличить объем существующих дисков. |

### Драйвер Secrets Store CSI

Используется для безопасного монтирования секретов из внешних хранилищ (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager) напрямую в файловую систему пода.

**Ключевые особенности:**
- **Без объектов Secret:** Данные монтируются как `tmpfs` (память), не сохраняясь в `etcd`.
- **Sync as Secret:** Возможность зеркалирования данных в обычные Kubernetes Secrets (если приложению это необходимо).
- **Rotation:** Поддержка автоматического обновления секретов в поде при их изменении во внешнем источнике.

#### Пример объекта SecretProviderClass (Vault)
```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-db-creds
spec:
  provider: vault
  parameters:
    vaultAddress: "https://vault:8200"
    roleName: "app-role"
    objects: |
      - objectName: "db-password"
        secretPath: "secret/data/db"
        secretKey: "password"
```

---

## Лучшие практики эксплуатации

1.  **Topology Awareness:** Всегда используйте `volumeBindingMode: WaitForFirstConsumer` для облачных дисков и локальных томов. Это гарантирует, что том будет создан в той же зоне, где планировщик разместил под.
2.  **Ресурсные лимиты:** Ограничивайте ресурсы (CPU/Memory) для подов CSI-драйвера, чтобы они не влияли на работу приложений, но имели достаточный приоритет (`PriorityClass`).
3.  **Мониторинг:** Настройте алерты на ошибки в `VolumeAttachment` и события `FailedMount`. Используйте метрики из `csi-provisioner` для отслеживания времени создания томов.
4.  **Безопасность:** Используйте `CSIDriver` объект для включения `podInfoOnMount`, если драйверу необходимы данные о поде (например, для аудита или специфичных прав доступа).

---

## Дополнительная информация

### Связанные темы

- [Обзор CSI](./csi_overview.md) — архитектура и компоненты.
- [Продвинутые возможности CSI](./csi_advanced.md) — детали работы снапшотов и топологии.
- [Хранение данных: PV и PVC](../pv_and_pvc.md) — основы управления дисками.

### Ссылки

- [Kubernetes CSI Drivers List](https://kubernetes-csi.github.io/docs/drivers.html) — официальный реестр драйверов.
- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/) — документация по драйверу секретов.
