# Persistent Volumes для Prometheus (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **Основная тема:** настройка постоянного хранилища для Prometheus, Alertmanager и Grafana в kube-prometheus-stack.
> **Смежные темы:** [PV и PVC в Kubernetes](../../../../Kubernetes/Storage/pv_and_pvc.md) — определения, типы провижининга, reclaim-политики; [TSDB](../../../concepts/tsdb.md) — как Prometheus использует диск (retention, метрики); [Local Path Provisioner](../../../../Kubernetes/Storage/local-path-provisioner.md) — динамическое создание локальных PV.

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
| **Dynamic provisioning** | StorageClass автоматически создаёт PV при появлении PVC. | Production, облачные среды (AWS EBS, GCP PD), Longhorn, Ceph. |
| **Static provisioning** | Администратор создаёт PV вручную, указывая путь к диску. | Lab-стенды, Bare-metal без СХД, специфические локальные диски. |

> **Рекомендация:** Для production используйте dynamic provisioning (Longhorn, CSI-драйверы облаков). Ручной PV — только для тестов или узкоспециализированных задач.

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

### Сценарий 1: Dynamic provisioning (Longhorn / Cloud CSI)

**Задача:** Обеспечить отказоустойчивое хранилище с автоматическим созданием томов.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn # Или gp3 (AWS), standard (GCP)
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

### Сценарий 4: Настройка retention для управления объёмом

**Задача:** Гарантировать, что TSDB не переполнит диск.

```yaml
prometheus:
  prometheusSpec:
    retention: 15d
    retentionSize: 40GB # Оставляйте 10-20% запаса от размера PVC
```
Если размер данных превысит 40GB раньше чем через 15 дней, Prometheus начнёт удалять старые блоки.

## Дополнительная информация

### Диагностика проблем (Troubleshooting)

| Проблема | Причина | Решение |
|---|---|---|
| PVC в статусе `Pending` | StorageClass не найден или нет свободных PV. | `kubectl get sc`, проверьте квоты или наличие ручных PV. |
| Pod в `Pending` (FailedScheduling) | PV привязан к другой ноде (Affinity). | Проверьте `nodeAffinity` в PV или наличие taints на ноде. |
| Ошибка `Permission Denied` | Неверные права на директорию (для local storage). | Выполните `chown 65534:65534` или настройте `securityContext.fsGroup`. |
| Диск заполнен (Disk Full) | Не настроен `retentionSize`. | Настройте `retentionSize` < размера PVC. |

### Полезные команды

```bash
# Проверка статуса PVC
kubectl get pvc -n monitoring

# Просмотр событий привязки (если висит в Pending)
kubectl describe pvc <pvc-name> -n monitoring

# Проверка использования диска внутри пода
kubectl exec -it -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- df -h /prometheus
```

### Рекомендации (Best Practices)

1. **Режим привязки:** Для локальных дисков всегда используйте StorageClass с `volumeBindingMode: WaitForFirstConsumer`. Это гарантирует, что PV будет создан на той же ноде, где запланирован под.
2. **Запас места:** Всегда устанавливайте `retentionSize` на 10-15% меньше объёма PVC. Оставшееся место необходимо для WAL (Write Ahead Log) и процесса компакции (слияния блоков).
3. **Безопасность:** Используйте `fsGroup` в `securityContext` вместо ручного `chown` на нодах, если ваш CSI-драйвер это поддерживает.
4. **Тип диска:** Для Prometheus критична скорость записи. Используйте SSD/NVMe (gp3 в AWS, premium-ssd в Azure).

### Рекомендуемые размеры

| Нагрузка | Prometheus | Alertmanager | Grafana |
|---|---|---|---|
| Тестовая (Lab) | 10Gi | 1Gi | 2Gi |
| Средняя (Prod) | 100-200Gi | 5Gi | 10Gi |
| Высокая (Prod) | 500Gi+ | 10Gi | 20Gi |

### Связанные ресурсы

* [TSDB: устройство и оптимизация](../../../concepts/tsdb.md)
* [Longhorn — распределённое хранилище](../../../../Kubernetes/Storage/longhorn.md)
* [NFS Subdir External Provisioner](../../../../Kubernetes/Storage/nfs-subdir-external-provisioner.md)
* [Local Path Provisioner](../../../../Kubernetes/Storage/local-path-provisioner.md)
