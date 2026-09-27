# Persistent Volumes для Prometheus (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **Основная тема:** настройка постоянного хранилища для Prometheus, Alertmanager и Grafana в kube-prometheus-stack.
> **Смежные темы:** [TSDB](../../../../concepts/tsdb.md) — как Prometheus использует диск (retention, метрики).

## Определения

**PersistentVolume (PV)** — ресурс Kubernetes, представляющий физическое хранилище (диск, NFS, Longhorn volume). Создаётся администратором вручную (static provisioning) или автоматически провижинером (dynamic provisioning).

**PersistentVolumeClaim (PVC)** — запрос приложения на хранение определённого объёма с заданными характеристиками (`accessMode`, `storageClassName`). kube-prometheus-stack создаёт PVC автоматически на основе `storageSpec.volumeClaimTemplate`.

**StorageClass** — шаблон для динамического создания PV. Определяет провижинер (Longhorn, NFS, local-path), параметры репликации и режим привязки (`Immediate` или `WaitForFirstConsumer`).

**`storageSpec`** — поле в CRD Prometheus/Alertmanager (kube-prometheus-stack), определяющее конфигурацию постоянного хранилища. Поддерживает `volumeClaimTemplate` для динамического создания PVC.

## Основные концепции

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

Prometheus развёртывается как `StatefulSet`. Каждый под имеет собственный PVC, который сохраняет привязку к конкретному экземпляру (например, `prometheus-0`). При удалении пода данные сохраняются в PV и монтируются обратно при перезапуске.

### Два подхода к созданию PV

| Подход | Описание | Когда использовать |
|---|---|---|
| **Dynamic provisioning** | StorageClass автоматически создаёт PV при появлении PVC. | Production, Longhorn, Ceph, NFS Subdir External Provisioner. |
| **Static provisioning** | Администратор создаёт PV вручную, указывая путь к диску. | Lab-стенды, Bare-metal без СХД, специфические локальные диски. |
| **Local Path Provisioner** | Динамическое создание локальных PV на узлах через helperPod и hostPath. | Одноузловые стенды,边缘节点, временные окружения. |

> **Рекомендация:** Для production используйте dynamic provisioning с отказоустойчивыми CSI-драйверами (Longhorn, Ceph, NFS Subdir). Ручной PV и Local Path Provisioner — только для тестов или узкоспециализированных задач.

### Политика удержания PVC (Retention Policy)

Начиная с Kubernetes 1.27 (GA в 1.32), StatefulSet поддерживает управление жизненным циклом PVC при удалении или масштабировании.

| Параметр | Описание | Значение по умолчанию |
|---|---|---|
| `whenDeleted` | Что делать с PVC при удалении StatefulSet. | `Retain` (сохранить) |
| `whenScaled` | Что делать с PVC при уменьшении количества реплик. | `Retain` (сохранить) |

Настройка в `values.yaml`:
```yaml
prometheus:
  prometheusSpec:
    persistentVolumeClaimRetentionPolicy:
      whenDeleted: Retain
      whenScaled: Delete
```

## Практические сценарии

### Сценарий 1: Dynamic provisioning (Longhorn / NFS Subdir)

**Задача:** Обеспечить отказоустойчивое хранилище с автоматическим созданием томов.

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

### Сценарий 2: Использование локальных дисков (static provisioning)

**Задача:** Максимальная производительность на локальных NVMe дисках без динамического провижинера.

**Шаг 1: Подготовка директории на ноде**
```bash
sudo mkdir -p /mnt/prometheus-data
sudo chown 65534:65534 /mnt/prometheus-data # UID пользователя prometheus
```

**Шаг 2: Создание PV**
```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: prometheus-local-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /mnt/prometheus-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - node-01
```

**Шаг 3: Настройка `values.yaml`**
```yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-storage
          resources:
            requests:
              storage: 100Gi
```

### Сценарий 3: Онлайн-расширение PVC

**Задача:** Увеличить размер диска Prometheus без остановки системы.

1. Убедитесь, что StorageClass поддерживает расширение (`allowVolumeExpansion: true`).
2. Измените размер в `values.yaml` (например, с 50Gi до 100Gi).
3. Примените изменения через `helm upgrade`.
4. Оператор обновит PVC. Большинство современных CSI-драйверов (EBS, Longhorn) расширят файловую систему на лету.

> **Важно:** Уменьшение размера PVC невозможно в большинстве СХД.

### Сценарий 5: Local Path Provisioner (динамические локальные тома)

**Задача:** Использовать Local Path Provisioner для динамического создания локальных PV без ручного управления нодами.

**Шаг 1: Установка Local Path Provisioner**
```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml
```

**Шаг 2: Проверка StorageClass**
```bash
kubectl get storageclass local-path
# → NAME                 PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE
# → local-path (default)   rancher.io/local-path         Delete          WaitForFirstConsumer
```

**Шаг 3: Настройка values.yaml**
```yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 5Gi
```

> **Важно:** Local Path Provisioner создаёт PV на ноде, где запущен под. При удалении пода PVC удаляется ( reclaimPolicy: Delete). Для production используйте с `persistentVolumeClaimRetentionPolicy: Retain`.

### Сценарий 6: Мониторинг заполнения PVC

**Задача:** Получать алерты до того, как диск Prometheus заполнится.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: storage-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: storage.rules
      rules:
        - alert: PersistentVolumeUsageHigh
          expr: |
            (
              kubelet_volume_stats_used_bytes{persistentvolumeclaim!=""} / kubelet_volume_stats_capacity_bytes{persistentvolumeclaim!=""}
            ) > 0.85
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "PVC заполнен более чем на 85%"
            description: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} заполнен на {{ $value | humanizePercentage }}."
        - alert: PersistentVolumeAlmostFull
          expr: |
            (
              kubelet_volume_stats_used_bytes{persistentvolumeclaim!=""} / kubelet_volume_stats_capacity_bytes{persistentvolumeclaim!=""}
            ) > 0.95
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "PVC заполнен более чем на 95%"
            description: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} заполнен на {{ $value | humanizePercentage }}. Требуется немедленное вмешательство."
        - alert: PrometheusTSDBRetentionSizeApproaching
          expr: |
            prometheus_tsdb_storage_retention_size_bytes / prometheus_tsdb_storage_retention_size_limit_bytes > 0.9
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Prometheus TSDB приближается к лимиту retentionSize"
            description: "Использовано {{ $value | humanizePercentage }} от лимита retentionSize."
```

**Валидация:**
```bash
kubectl apply -f storage-alerts.yaml
kubectl get prometheusrule -n monitoring storage-alerts
```

### Сценарий 7: Снапшоты и резервное копирование

**Задача:** Создавать снапшоты PVC для защиты от потери данных.

#### Способ 1: VolumeSnapshot (CSI-драйвер)

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: prometheus-snapshot
  namespace: monitoring
spec:
  volumeSnapshotClassName: longhorn-snapshot
  source:
    persistentVolumeClaimName: prometheus-kube-prometheus-stack-prometheus-0
```

**Создание снапшота:**
```bash
kubectl apply -f snapshot.yaml
kubectl get volumesnapshot -n monitoring
# → NAME               STATUS   READY_TO_USE   SOURCE_PVC                                    SIZE
# → prometheus-snapshot  Created  true          prometheus-kube-prometheus-stack-prometheus-0  50Gi
```

#### Способ 2: Резервное копирование через Velero (без CSI)

```bash
velero backup create prometheus-backup \
  --include-namespaces monitoring \
  --include-resources pvc,secret,configmap,servicemonitor,prometheusrule \
  --wait
```

> **Важно:** Снапшоты не заменяют `retentionSize`. Они защищают от сбоев СХД и ошибок оператора, но не от логического удаления данных.

### Сценарий 8: Онлайн-расширение для Alertmanager

**Задача:** Увеличить размер диска Alertmanager без остановки системы.

1. Убедитесь, что StorageClass поддерживает расширение (`allowVolumeExpansion: true`).
2. Измените размер в `values.yaml`:
```yaml
alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 10Gi
```
3. Примените изменения через `helm upgrade`.
4. Проверьте расширение:
```bash
kubectl get pvc -n monitoring -l app.kubernetes.io/name=alertmanager
kubectl exec -it -n monitoring alertmanager-kube-prometheus-stack-alertmanager-0 -- df -h /alertmanager
```

> **Важно:** Уменьшение размера PVC невозможно в большинстве СХД. Планируйте запас с запасом.

## Дополнительная информация

### Диагностика проблем (Troubleshooting)

| Проблема | Причина | Решение |
|---|---|---|
| PVC в статусе `Pending` | StorageClass не найден или нет свободных PV. | `kubectl get sc`, проверьте квоты или наличие ручных PV. |
| Pod в `Pending` (FailedScheduling) | PV привязан к другой ноде (Affinity). | Проверьте `nodeAffinity` в PV или наличие taints на ноде. |
| Ошибка `Permission Denied` | Неверные права на директорию (для local storage). | Выполните `chown 65534:65534` или настройте `securityContext.fsGroup`. |
| Диск заполнен (Disk Full) | Не настроен `retentionSize`. | Настройте `retentionSize` < размера PVC. |
| WAL повреждён после сбоя | Диск не синхронизирован (например, ext4 без barriers). | Включите `walCompression: true` и используйте XFS/ext4 с `barrier=1`. |
| PVC не удаляется после удаления StatefulSet | `persistentVolumeClaimRetentionPolicy` не настроен. | Установите `whenDeleted: Delete` или удалите PVC вручную. |

### Безопасность хранения

```yaml
prometheus:
  prometheusSpec:
    securityContext:
      fsGroup: 65534
      runAsUser: 65534
      runAsNonRoot: true
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi
```

| Параметр | Описание |
|---|---|
| `fsGroup: 65534` | Привязывает том к группе `nobody` (UID/GID Prometheus в официальном образе). |
| `runAsUser: 65534` | Запускает процесс Prometheus от непривилегированного пользователя. |
| `runAsNonRoot: true` | Блокирует запуск от root. |
| `readOnlyRootFilesystem: true` | Запрещает запись в корневой контейнер (требует tmpfs для /tmp). |

### Ресурсы StatefulSet

```yaml
prometheus:
  prometheusSpec:
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: 2000m
        memory: 8Gi
```

**Рекомендации по ресурсам для Prometheus (SSD/NVMe):**

| Компонент | CPU request | Memory request | Memory limit | Метрика для мониторинга |
|---|---|---|---|---|
| Prometheus Server | 500m | 2Gi | 8Gi | `container_memory_working_set_bytes`, `rate(container_cpu_cfs_throttled_seconds_total)` |
| Alertmanager | 100m | 256Mi | 1Gi | `container_memory_working_set_bytes` |
| Grafana | 100m | 128Mi | 512Mi | `container_memory_working_set_bytes` |

> **Важно:** Для больших нагрузок (>500k active series) увеличивайте memory limit до 16Gi. Используйте `native-histograms` для снижения потребления памяти.

### Очистка окружения

```bash
# 1. Удаление Helm-релиза
helm uninstall monitoring -n monitoring

# 2. Удаление Persistent Volume Claims (если данные не нужны)
kubectl delete pvc -n monitoring -l app.kubernetes.io/instance=monitoring

# 3. Удаление ручных PV (если создавали вручную)
kubectl delete pv prometheus-local-pv

# 4. Удаление StorageClass (опционально)
kubectl delete storageclass longhorn
```

> **Важно:** Удаление PVC приводит к безвозвратной потере данных TSDB. Для временного отключения используйте `helm uninstall` с `persistentVolumeClaimRetentionPolicy: Retain`.

### Пограничные случаи (Edge Cases)

| Сценарий | Проблема | Решение |
|---|---|---|
| **Однокластерный режим (single-node)** | Local Path Provisioner создаёт PV на единственной ноде. | Используйте Longhorn с `replicaCount: 1` для отказоустойчивости на одном узле. |
| **Диск readonly (ext4 ошибка)** | Файловая система переведена в readonly после сбоя I/O. | Проверьте `dmesg | grep -i ext4`, замените диск, восстановите из снапшота. |
| **PVC > 1Ti** | Некоторые CSI-драйверы не поддерживают большие тома. | Проверьте лимиты StorageClass (`maxVolumeSize`). |
| **hostPath + StatefulSet** | `hostPath` не поддерживается в StatefulSet через PVC. | Используйте Local Persistent Volume с `nodeAffinity`. |
| **etcd v2 store** | Старые версии Kubernetes используют v2 store, где PV привязка работает иначе. | Обновите кластер до v1.27+ для поддержки `persistentVolumeClaimRetentionPolicy`. |
| **WAL corruption** | При неожиданном отключении питания WAL может быть повреждён. | Prometheus автоматически восстанавливает WAL при перезапуске. Если восстановление не удаётся — удалите старый WAL (`/prometheus/wal`) и начните с пустого TSDB. |

### Полезные команды

```bash
# Проверка статуса PVC
kubectl get pvc -n monitoring

# Просмотр событий привязки (если висит в Pending)
kubectl describe pvc <pvc-name> -n monitoring

# Проверка использования диска внутри пода
kubectl exec -it -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- df -h /prometheus

# Проверка StorageClass и allowVolumeExpansion
kubectl get sc <storage-class-name> -o yaml | grep allowVolumeExpansion

# Мониторинг метрик WAL и compaction
kubectl exec -it -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- wget -qO- http://localhost:9090/metrics | grep -E 'prometheus_tsdb_|wal_'
```

### Рекомендации (Best Practices)

1. **Режим привязки:** Для локальных дисков всегда используйте StorageClass с `volumeBindingMode: WaitForFirstConsumer`. Это гарантирует, что PV будет создан на той же ноде, где запланирован под.
2. **Запас места:** Всегда устанавливайте `retentionSize` на 10-15% меньше объёма PVC. Оставшееся место необходимо для WAL (Write Ahead Log) и процесса компакции (слияния блоков).
3. **Безопасность:** Используйте `fsGroup` в `securityContext` вместо ручного `chown` на нодах, если ваш CSI-драйвер это поддерживает.
4. **Тип диска:** Для Prometheus критична скорость записи. Используйте SSD/NVMe. Избегайте HDD для production-сред с высокой нагрузкой.
5. **Резервное копирование:** Регулярно создавайте снапшоты PVC (если StorageClass поддерживает VolumeSnapshot) или резервные копии через Velero.
6. **Мониторинг:** Настройте алерты на заполнение PVC (см. Сценарий 6) и отслеживайте метрики TSDB (`prometheus_tsdb_storage_retention_size_bytes`).
7. **Retention:** Используйте `retentionSize` вместо `retention` (время) при использовании быстрых SSD. Это защищает от переполнения диска.

### Рекомендуемые размеры

| Нагрузка | Prometheus | Alertmanager | Grafana |
|---|---|---|---|
| Тестовая (Lab) | 10Gi | 1Gi | 2Gi |
| Средняя (Prod) | 100-200Gi | 5Gi | 10Gi |
| Высокая (Prod) | 500Gi+ | 10Gi | 20Gi |

### Связанные ресурсы

* [TSDB: устройство и оптимизация](../../../../concepts/tsdb.md)
