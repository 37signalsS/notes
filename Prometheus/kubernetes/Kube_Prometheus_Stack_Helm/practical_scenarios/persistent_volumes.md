# Persistent Volumes for Prometheus (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** настройка постоянного хранилища для Prometheus, Alertmanager и Grafana в kube-prometheus-stack.  
> **Смежные темы:** [PV и PVC в Kubernetes](../../../../Kubernetes/Storage/pv_and_pvc.md) — определения, типы провижининга, reclaim-политики; [TSDB](../../../concepts/tsdb.md) — как Prometheus использует диск (retention, метрики); [Local Path Provisioner](../../../../Kubernetes/Storage/local-path-provisioner.md) — динамическое создание локальных PV.

## Definitions

**PersistentVolume (PV)** — ресурс Kubernetes, представляющий физическое хранилище (диск, NFS, Longhorn volume). Создаётся администратором вручную (static provisioning) или автоматически провижинером (dynamic provisioning).

**PersistentVolumeClaim (PVC)** — запрос приложения на хранение определённого объёма с заданными характеристиками (`accessMode`, `storageClassName`). kube-prometheus-stack создаёт PVC автоматически на основе `storageSpec.volumeClaimTemplate`.

**StorageClass** — шаблон для динамического создания PV. Определяет провижинер (Longhorn, NFS, local-path), параметры репликации и режим привязки (`Immediate` или `WaitForFirstConsumer`).

**`storageSpec`** — поле в CRD Prometheus/Alertmanager (kube-prometheus-stack), определяющее конфигурацию постоянного хранилища. Поддерживает `volumeClaimTemplate` для динамического создания PVC.

## Basic Concepts

### Зачем Prometheus нужно постоянное хранилище

```
Prometheus Server (StatefulSet)
    │
    └── TSDB (Time Series Database)
            ├── Хранит метрики на диске (/prometheus)
            ├── WAL (Write-Ahead Log) для восстановления
            ├── Блоки данных (2-часовые chunks)
            └── Retention: по времени (15d) и размеру (50GiB)
                    └── Без PV данные теряются при перезапуске пода
```

Prometheus — StatefulSet; каждый pod имеет собственный PVC. При удалении/пересоздании pod данные сохраняются, если PVC имеет reclaim-политику `Retain` или StorageClass поддерживает перебиндинг.

### Два подхода к созданию PV

| Подход | Когда | Механизм |
|---|---|---|
| **Dynamic provisioning** | StorageClass поддерживает (Longhorn, NFS, local-path) | kube-prometheus-stack создаёт PVC → StorageClass создаёт PV автоматически |
| **Static provisioning (ручной PV)** | Нет провижинера, `local-storage`, NFS без subdir-provisioner | Администратор создаёт PV вручную → PVC привязывается к существующему PV |

> **Рекомендация:** Для production используйте dynamic provisioning (Longhorn, Ceph). Ручной PV — для lab/dev-сред или специфических СХД.

### Связь storageSpec и PVC в kube-prometheus-stack

```yaml
# values.yaml — kube-prometheus-stack генерирует PVC автоматически
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn     # StorageClass для dynamic provisioning
          accessModes: ["ReadWriteOnce"] # RWO — только один pod монтирует том
          resources:
            requests:
              storage: 50Gi             # Запрашиваемый объём
```

kube-prometheus-stack преобразует это в PVC с именем `prometheus-kube-prometheus-stack-prometheus-db-data-prometheus-kube-prometheus-stack-prometheus-0`.

## Practical Scenarios

### Сценарий 1: Dynamic provisioning (Longhorn) — рекомендуемый

**Задача:** Автоматическое создание PV с репликацией для production.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 5Gi

grafana:
  persistence:
    enabled: true
    storageClassName: longhorn
    size: 10Gi
```

**Применение:**

```bash
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f values.yaml

# Проверка PVC
kubectl get pvc -n monitoring

# Проверка PV (создан автоматически)
kubectl get pv
```

> **Подробнее:** [Longhorn — установка и настройка](../../../../Kubernetes/Storage/longhorn.md) — распределённое блочное хранилище для Kubernetes, онлайн и оффлайн установка.

### Сценарий 2: Ручной PV для local-storage (static provisioning)

**Задача:** Использовать локальный диск на ноде когда динамический провижинер отсутствует.

**Шаг 1: Подготовка директории на ноде**

```bash
# На целевой ноде (node-1)
sudo mkdir -p /mnt/local-pv-1
sudo chown 65534:65534 /mnt/local-pv-1  # nobody:nogroup
```

**Шаг 2: Создание PV**

```yaml
# pv-prometheus.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv-prometheus-1
spec:
  capacity:
    storage: 50Gi
  accessModes:
    - ReadWriteOnce
  storageClassName: local-storage
  local:
    path: /mnt/local-pv-1
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - node-1
```

```bash
kubectl apply -f pv-prometheus.yaml
```

**Шаг 3: Привязка через storageSpec**

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-storage  # Должен совпадать с PV
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi
```

> **Важно:** `storageClassName` в PVC должен совпадать с `storageClassName` в PV. Иначе привязка не произойдёт.

### Сценарий 3: Dynamic provisioning через Local Path Provisioner

**Задача:** Быстрое развёртывание в dev/test без сложной СХД.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path    # Rancher Local Path Provisioner
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 20Gi
```

> **Ограничения:** Данные привязаны к узлу. При пересоздании StatefulSet на другой ноде — данные теряются. Только для dev/test.  
> **Подробнее:** [Local Path Provisioner](../../../../Kubernetes/Storage/local-path-provisioner.md).

### Сценарий 4: Настройка retention для управления объёмом данных

**Задача:** Ограничить размер TSDB чтобы не переполнить PVC.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    # Retention по времени (по умолчанию 10d)
    retention: 15d
    # Retention по размеру (дополнительное ограничение)
    retentionSize: 45GB  # Оставить запас 5Gi на 50Gi PVC
```

> **Рекомендация:** `retentionSize` должен быть на 10-15% меньше размера PVC для запаса на WAL и компакцию.  
> **Подробнее:** [TSDB retention flags](../../../concepts/tsdb.md).

### Сценарий 5: NFS для хранения (через nfs-subdir-external-provisioner)

**Задача:** Использовать сетевое хранилище для данных Prometheus.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: nfs-client
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi
```

> **Важно для Rancher:** При использовании Rancher Monitoring с NFS и `volumeClaimTemplate` могут возникнуть проблемы из-за особенностей NFS locking. Проверяйте совместимость.  
> **Подробнее:** [NFS Subdir External Provisioner](../../../../Kubernetes/Storage/nfs-subdir-external-provisioner.md).

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| PVC в статусе `Pending` | Нет PV с matching `storageClassName` | Создать PV вручную или проверить StorageClass |
| PVC в статусе `Pending` | StorageClass не существует | `kubectl get storageclass`; создать или указать существующий |
| Pod в `Pending` — `FailedScheduling` | PV привязан к другой ноде (local-storage) | Проверить `nodeAffinity` PV; переместить pod или создать PV на нужной ноде |
| TSDB disk full | `retentionSize` > размер PVC | Уменьшить retention или увеличить PVC |
| Данные потерялись после рестарта | PVC удалён (режим удаления StatefulSet) | Проверить `persistentVolumeClaimRetentionPolicy` StatefulSet |
| `Mismatched storageClassName` | PVC и PV имеют разные `storageClassName` | Привести к одному значению |

### Диагностика

```bash
# Проверка PVC и их статуса
kubectl get pvc -n monitoring

# Детали PVC (Events покажут причину привязки)
kubectl describe pvc <pvc-name> -n monitoring

# Проверка PV
kubectl get pv
kubectl describe pv <pv-name>

# Проверка StorageClass
kubectl get storageclass

# Проверка использования диска TSDB (из Prometheus UI)
# http://localhost:9090/api/v1/status/tsdb

# Проверка retention-настроек
kubectl get prometheus -n monitoring -o yaml | grep -A 5 retention
```

### Best Practices

1. **Production = dynamic provisioning с репликацией** — Longhorn или Ceph. Ручной PV — только для dev/test.
2. **RWO для Prometheus** — StatefulSet требует ReadWriteOnce; ReadWriteMany не поддерживается.
3. **`retentionSize` < размер PVC** — оставляйте 10-15% запаса на WAL и компакцию.
4. **`volumeBindingMode: WaitForFirstConsumer` для локальных PV** — гарантирует привязку к правильной ноде.
5. **Мониторьте диск TSDB** — метрика `prometheus_tsdb_storage_blocks_bytes` + алерт на 85% заполнения.
6. **Отдельный PVC для Alertmanager** — данные alertmanager не такие объёмные, но тоже требуют persistence.
7. **Не используйте HostPath** — небезопасно и неудобно; Local Path Provisioner — минимальная альтернатива.

### Рекомендуемые размеры PVC

| Компонент | Dev/Test | Production (малый) | Production (средний) |
|---|---|---|---|
| **Prometheus** | 10-20Gi | 50Gi | 200-500Gi |
| **Alertmanager** | 1Gi | 5Gi | 10Gi |
| **Grafana** | 1Gi | 5Gi | 10Gi |
| **Thanos Sidecar** | — | Зависит от external storage | 50Gi (локальный буфер) |

> **Примечание:** Размер Prometheus PVC зависит от ingestion rate и retention. Рассчитывайте по формуле: `Байт/с × retention_seconds × 1.15 (запас)`.

### Связанные ресурсы

| Ресурс | Описание |
|---|---|
| [PV и PVC в Kubernetes](../../../../Kubernetes/Storage/pv_and_pvc.md) — определения, static vs dynamic provisioning, reclaim policies |
| [TSDB](../../../concepts/tsdb.md) — как Prometheus использует диск, retention flags, метрики |
| [Local Path Provisioner](../../../../Kubernetes/Storage/local-path-provisioner.md) — динамическое создание локальных PV |
| [NFS Subdir External Provisioner](../../../../Kubernetes/Storage/nfs-subdir-external-provisioner.md) — NFS для Kubernetes |
| [Offline Air-gapped Installation](./offline_airgapped_installation.md) — настройка storageSpec в закрытом контуре |
