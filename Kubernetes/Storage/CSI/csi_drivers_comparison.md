# CSI-драйверы: сравнение и эксплуатация

## Определения

**CSI Driver** — реализация спецификации Container Storage Interface для конкретной системы хранения. Каждый драйвер предоставляет уникальный набор возможностей в зависимости от поддерживаемой СХД.

> **Базовая информация:** [Container Storage Interface (CSI)](./csi_overview.md), [Продвинутые возможности CSI](./csi_advanced.md)

---

## Сравнение CSI-драйверов

### Облачные провайдеры

> **Примечание:** Для локального аринта используйте on-premise решения (Ceph, NFS, Longhorn).

| Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Yandex Disk CSI** | Block | ✅ | ✅ | ✅ | ✅ | RWO, RWOP |
| **vSphere CSI** | Block | ✅ | ✅ | ✅ | ✅ | RWO, RWOP |
| **OpenStack Cinder CSI** | Block | ✅ | ✅ | ✅ | ✅ | RWO, RWOP |

### On-premise решения

| Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Ceph RBD CSI** | Block | ✅ | ✅ | ✅ | ✅ | RWO, RWOP |
| **CephFS CSI** | File | ✅ | ✅ | ✅ | ✅ | RWX |
| **NFS Subdir** | File | ❌ | ❌ | ❌ | ❌ | RWX |
| **Local Path** | Local | ❌ | ❌ | ❌ | ❌ | RWO, RWOP |
| **Longhorn CSI** | Block | ✅ | ✅ | ✅ | ❌ | RWO, RWX |
| **Portworx CSI** | Block | ✅ | ✅ | ✅ | ✅ | RWO, RWX |

> **Примечание:** Возможности зависят от версии драйвера и конфигурации СХД.

---

## Диагностика и мониторинг CSI

### Проверка статуса CSI-драйвера

```bash
# Проверка установленных CSI-драйверов
kubectl get csidrivers.storage.k8s.io

# Проверка подов CSI-драйвера
kubectl get pods -n kube-system -l app=csi-driver

# Просмотр событий CSI
kubectl get events -n kube-system --field-selector reason=Provisioning

# Детальная информация о драйвере (пример для Ceph RBD)
kubectl describe csidriver rbd.csi.ceph.com
```

### Диагностика проблем с томами

```bash
# Статус PVC и PV
kubectl get pvc,pv

# Детальная информация о PVC
kubectl describe pvc my-app-pvc

# Проверка VolumeSnapshots
kubectl get volumesnapshot,volumesnapshotcontent,volumesnapshotclass

# Логи CSI-драйвера
kubectl logs -n kube-system -l app=csi-driver --all-containers=true
```

### Распространённые проблемы

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| PVC в статусе `Pending` | Нет подходящего PV, quota превышен | Проверить `StorageClass`, лимиты ресурсов |
| PV в статусе `Failed` | Ошибка аутентификации в СХД | Проверить secrets, права доступа |
| Под не запускается | Том не монтируется | Проверить логи CSI Node Plugin, совместимость FS |
| Snapshot не создаётся | Драйвер не поддерживает `CREATE_DELETE_SNAPSHOT` | Проверить возможности драйвера |
| Timeout при монтировании | Сетевые проблемы, недоступность СХД | Проверить сеть, доступность СХД, firewall |

---

## Лучшие практики

### Выбор StorageClass

- Используйте `WaitForFirstConsumer` для stateful-приложений в многозонных кластерах
- Устанавливайте `reclaimPolicy: Retain` для production-данных
- Включайте `allowVolumeExpansion: true` для гибкости
- Для баз данных используйте блочные хранилища (RWO)
- Для общих данных — файловые хранилища (RWX)

### Безопасность

- Ограничивайте доступ к `StorageClass` через RBAC
- Используйте отдельные secrets для provisioner и node plugin
- Шифруйте данные на уровне СХД (encryption at rest)
- Регулярно тестируйте восстановление из snapshots

### Мониторинг

- Отслеживайте использование дискового пространства (алерты на 80%, 90%)
- Мониторьте latency и IOPS томов
- Настройте алерты на ошибки provisioning
- Собирайте метрики CSI-драйвера (если поддерживает)

### Бэкапы

- Используйте VolumeSnapshots для быстрых локальных бэкапов
- Не полагайтесь только на snapshots — экспортируйте данные во внешнее хранилище
- Тестируйте восстановление регулярно
- Автоматизируйте создание snapshots через CronJob или внешние инструменты

---

## Практические сценарии

### Secrets Store CSI Driver

**Назначение:** Монтирование секретов из внешних хранилищ (HashiCorp Vault, Yandex Lockbox) напрямую в файловую систему пода.

**Архитектура:**
- **CSI Driver:** Устанавливается как DaemonSet на каждом узле
- **CSI Provider:** Плагин для конкретного хранилища (Vault Provider, Yandex Lockbox Provider)
- **SecretProviderClass:** CRD, описывающий какие секреты и откуда монтировать

**Преимущества:**
- Секреты не хранятся в etcd даже в зашифрованном виде
- Автоматическая ротация секретов без перезапуска подов
- Нативная интеграция через стандартный CSI-интерфейс

**Недостатки:**
- Секреты доступны только как файлы (не как environment variables напрямую)
- Требует установки CSI-компонентов на каждый узел кластера

#### Пример интеграции с HashiCorp Vault

```yaml
# SecretProviderClass для Vault
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-db-credentials
spec:
  provider: vault
  parameters:
    vaultAddress: https://vault.example.com:8200
    vaultRole: my-app-role
    vaultKVMountName: secret
    objects: |
      - objectName: "db-username"
        secretPath: "data/myapp"
        secretKey: "username"
      - objectName: "db-password"
        secretPath: "data/myapp"
        secretKey: "password"

---
# Pod с монтированием секретов
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
    - name: app
      image: my-app:latest
      volumeMounts:
        - name: secrets-store
          mountPath: /mnt/secrets
          readOnly: true
      env:
        - name: DB_USERNAME
          valueFrom:
            secretKeyRef:
              name: my-app-secrets
              key: db-username
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: my-app-secrets
              key: db-password
  volumes:
    - name: secrets-store
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: "vault-db-credentials"
```

> **Подробно:** [External Secret Managers](../Base/secrets/external_managers.md), [Интеграция Vault с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)

---

## Связанные темы

- **Базовая информация:** [Container Storage Interface (CSI)](./csi_overview.md)
- **Продвинутые возможности:** [CSI Advanced Features](./csi_advanced.md)
- **PV и PVC:** [Хранение данных: PV, PVC и StorageClass](../pv_and_pvc.md)
- **Ceph CSI:** [Ceph Overview](../Ceph/ceph_overview.md)

## Официальные источники

- [Container Storage Interface (CSI) Specification](https://github.com/container-storage-interface/spec)
- [Kubernetes CSI Documentation](https://kubernetes.io/docs/concepts/storage/volumes/#csi)
- [CSI Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
- [CSI Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/)
- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/)
