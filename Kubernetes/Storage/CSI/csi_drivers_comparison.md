# Сравнение и эксплуатация CSI-драйверов

## Определения

**CSI Driver (Container Storage Interface Driver)** — программная реализация спецификации интерфейса хранения контейнеров для конкретной системы хранения данных. Каждый драйвер предоставляет уникальный набор возможностей (снапшоты, клонирование, расширение) в зависимости от поддерживаемой СХД (системы хранения данных).

**Provisioner** — компонент CSI-драйвера, отвечающий за динамическое создание и удаление томов в системе хранения.

**Attacher** — компонент, отвечающий за присоединение и отсоединение томов к узлам кластера.

> **Базовая информация:** [Обзор CSI](./csi_overview.md), [Продвинутые возможности CSI](./csi_advanced.md)

---

## Базовые концепции

### Сравнение возможностей драйверов

Выбор драйвера зависит от инфраструктуры кластера (облако или локальные серверы) и требований приложения к производительности и отказоустойчивости.

#### Облачные провайдеры

| Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Yandex Disk CSI** | Block | + | + | + | + | RWO, RWOP |
| **vSphere CSI** | Block | + | + | + | + | RWO, RWOP |
| **OpenStack Cinder CSI** | Block | + | + | + | + | RWO, RWOP |

#### Локальные (On-premise) решения

| Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Ceph RBD CSI** | Block | + | + | + | + | RWO, RWOP |
| **CephFS CSI** | File | + | + | + | + | RWX |
| **NFS Subdir** | File | - | - | - | - | RWX |
| **Local Path** | Local | - | - | - | - | RWO, RWOP |
| **Longhorn CSI** | Block | + | + | + | - | RWO, RWX |
| **Portworx CSI** | Block | + | + | + | + | RWO, RWX |

> **Примечание:** Возможности зависят от версии драйвера и конфигурации СХД. Для баз данных рекомендуются блочные устройства (Block), для общих файлов — файловые системы (File).

---

## Практические сценарии

### Диагностика и мониторинг

#### Проверка состояния драйверов

```bash
# Список установленных CSI-драйверов и их возможностей
kubectl get csidrivers.storage.k8s.io

# Проверка работоспособности подов драйвера (обычно в kube-system)
kubectl get pods -n kube-system -l app=csi-driver

# События, связанные с выделением ресурсов (provisioning)
kubectl get events -n kube-system --field-selector reason=Provisioning
```

#### Отладка проблем с томами

При возникновении проблем с монтированием томов следует проверять статус PVC (PersistentVolumeClaim) и PV (PersistentVolume):

```bash
# Просмотр описания PVC для поиска ошибок в событиях
kubectl describe pvc <pvc-name>

# Проверка состояния снапшотов
kubectl get volumesnapshot,volumesnapshotcontent

# Анализ логов конкретного контейнера в CSI-драйвере (например, attacher или provisioner)
kubectl logs -n kube-system -l app=csi-driver -c csi-provisioner
```

#### Типовые неисправности

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| PVC в статусе `Pending` | Нет подходящего PV или исчерпаны квоты | Проверить `StorageClass` и лимиты ресурсов |
| PV в статусе `Failed` | Ошибка аутентификации в СХД | Проверить Secrets (секреты) и права доступа |
| Тайм-аут монтирования | Проблемы сетевой связности с СХД | Проверить сетевые доступы и Firewall (межсетевой экран) |
| Snapshot не создаётся | Драйвер или версия СХД не поддерживают функцию | Сверить возможности в таблице выше |

### Драйвер Secrets Store CSI

Используется для монтирования секретов из внешних хранилищ (например, HashiCorp Vault) напрямую в файловую систему пода без создания объектов `Secret` в Kubernetes.

**Особенности эксплуатации:**

- **Архитектура:** Устанавливается как DaemonSet (на каждый узел). Использует CRD (Custom Resource Definition) `SecretProviderClass`.
- **Безопасность:** Секреты хранятся в памяти (`tmpfs`) и не попадают в `etcd`.
- **Ограничение:** Секреты доступны приложению только как файлы.

#### Пример настройки для Vault

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-db-credentials
spec:
  provider: vault
  parameters:
    vaultAddress: https://vault.example.com:8200
    vaultRole: app-role
    objects: |
      - objectName: "db-password"
        secretPath: "secret/data/myapp"
        secretKey: "password"
```

### Лучшие практики эксплуатации

1. **Режим привязки:** Используйте `WaitForFirstConsumer` в `StorageClass` для корректного планирования подов в многозонных кластерах (Topology Aware).
2. **Безопасность:** Ограничивайте использование `StorageClass` через RBAC (Role-Based Access Control).
3. **Производительность:** Мониторьте IOPS (Input/Output Operations Per Second) и задержки (latency) через метрики драйвера, если они доступны.
4. **Резервное копирование:** Регулярно тестируйте восстановление из снапшотов, так как наличие снапшота не гарантирует целостность данных без учета специфики приложения.

---

## Дополнительная информация

### Связанные темы

- [Обзор CSI](./csi_overview.md) — базовые понятия и архитектура.
- [Продвинутые возможности CSI](./csi_advanced.md) — детали работы снапшотов и топологии.
- [Хранение данных: PV и PVC](../pv_and_pvc.md) — основы управления дисками в Kubernetes.

### Ссылки

- [Kubernetes CSI Drivers](https://kubernetes-csi.github.io/docs/drivers.html) — официальный список поддерживаемых драйверов.
- [Secrets Store CSI Documentation](https://secrets-store-csi-driver.sigs.k8s.io/) — документация по драйверу секретов.
