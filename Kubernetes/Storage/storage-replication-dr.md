# Репликация данных и Disaster Recovery в Kubernetes

## Определения

**Репликация данных (Data Replication)** — процесс создания и поддержания копий данных на нескольких узлах или в нескольких кластерах для обеспечения отказоустойчивости и доступности.

**Disaster Recovery (DR)** — комплекс процедур по восстановлению сервисов и данных после катастрофических сбоев (потеря узла, ЦОД, региона).

**RPO (Recovery Point Objective)** — максимальный объём потерь данных, допустимый при аварии. Определяется частотой репликации или бэкапов.

**RTO (Recovery Time Objective)** — максимальное время восстановления сервиса. Зависит от метода восстановления (автоматический failover vs ручное восстановление из бэкапа).

**RBD Mirroring** — механизм репликации образов Ceph RBD между двумя кластерами Ceph. Поддерживает синхронную и асинхронную репликацию.

**DR Volume (Longhorn)** — специальный тип тома Longhorn, который создаётся из бэкапа в целевом кластере и находится в режиме standby. Позволяет быстро переключить нагрузку при отказе основного кластера.

**DRBD (Distributed Replicated Block Device)** — программное решение для блочной репликации между узлами (описано в [Linux HA Stack](../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md)).

**Связанные темы:**
- [CSI — миграция между кластерами](./CSI/csi_cross_cluster_migration.md) — Velero + CSI Snapshots.
- [Longhorn — DR Volume](./longhorn.md) — DR-тома Longhorn.
- [Ceph — RBD Mirroring](./Ceph/ceph_rbd_usage/advanced_topics.md) — репликация Ceph.
- [Velero](../ToolsUtilities/velero-overview.md) — бэкап и восстановление.
- [Backup Strategies](../Operations/backup-strategies.md) — стратегии бэкапа.

---

## Теоретический блок

### Матрица подходов к репликации

| Подход | Уровень | RPO | RTO | Сложность | Стоимость |
|:---|:---|:---|:---|:---|:---|
| **Синхронная репликация (Ceph replica 3)** | СХД (block) | 0 | < 1 мин | Высокая | Высокая (x3 диски) |
| **Ceph RBD Mirroring** | СХД (block) | 0–секунды | 5–15 мин | Высокая | Средняя |
| **Longhorn DR Volume** | СХД (block) | Зависит от schedules | 15–30 мин | Средняя | Средняя |
| **DRBD (Pacemaker)** | ОС (block) | 0 (Protocol C) | < 1 мин | Высокая | Средняя |
| **Velero + CSI Snapshots** | K8s API | Часы | 30–60 мин | Средняя | Низкая |
| **Velero Data Mover** | K8s API + FS | Часы | 30–120 мин | Средняя | Низкая |
| **rsync поверх VPN** | Файловая | Зависит от cron | 10–30 мин | Низкая | Низкая |

### Матрица: Когда что использовать

| Сценарий | Рекомендация | Обоснование |
|:---|:---|:---|
| **HA внутри одного кластера** | Ceph RBD (replica 3) или Longhorn (replicas=3) | Автоматический failover, RPO=0 |
| **DR между ЦОД (разные здания)** | Ceph RBD Mirroring (async) или rsync | Достаточная пропускная способность, RPO > 0 |
| **DR между регионами** | Velero + CSI Snapshots в S3 | Медленная сеть, RPO = часы |
| **Критичные БД (RPO=0)** | Синхронная репликация на уровне БД + Ceph RBD | СХД-репликация + репликация БД |
| **Dev/Test DR** | Velero Scheduled Backups | Простота, низкая стоимость |

---

## Практический блок

### 1. Ceph RBD Mirroring (межкластерная репликация)

#### Архитектура

```
Кластер A (Primary)                    Кластер B (Secondary)
┌─────────────────┐                   ┌─────────────────┐
│  Pool: kube     │  ── async/sync ── │  Pool: kube     │
│  RBD: app-data  │                   │  RBD: app-data  │
│  MGR + rbd-mirror│                  │  MGR + rbd-mirror│
└─────────────────┘                   └─────────────────┘
```

#### Настройка (cephadm)

```bash
# 1. На обоих кластерах: создать pool и включить репликацию
ceph osd pool create kube 64 64
rbd pool init kube

# 2. На Primary кластере: включить mirroring для pool
rbd mirror pool enable kube pool

# 3. На Secondary кластере: включить mirroring для pool
rbd mirror pool enable kube pool

# 4. Создать bootstrap-токен на Primary
rbd mirror pool peer bootstrap create kube > /tmp/bootstrap.token

# 5. Импортировать токен на Secondary
rbd mirror pool peer bootstrap import kube /tmp/bootstrap.token

# 6. На Secondary: начать зеркалирование
rbd mirror image enable kube/app-data
```

#### Проверка статуса

```bash
# На Primary
rbd mirror pool status kube
# → peer1: site1 a]f234.., always_on

# На Secondary
rbd mirror pool status kube
# → images: 1 total, 1 replaying

# Детали по конкретному образу
rbd mirror image status kube/app-data
# → state: up+replaying, last_update: ...
```

#### Переключение при аварии (failover)

```bash
# На Secondary кластере: переключить образ в primary
rbd mirror image promote kube/app-data

# Проверить статус
rbd mirror image status kube/app-data
# → state: up+stopped (primary)

# Теперь поды в Secondary кластере могут писать в том
```

### 2. Longhorn DR Volume

#### Настройка backup target

```yaml
# На обоих кластерах: настроить общий S3-бакет
apiVersion: longhorn.io/v1beta2
kind: Setting
metadata:
  name: backup-target
spec:
  value: "s3://longhorn-backups@us-east-1/"
---
apiVersion: longhorn.io/v1beta2
kind: Setting
metadata:
  name: backup-target-credential-secret
spec:
  value: "backup-secret"
```

#### Создание бэкапа (Primary кластер)

```bash
# 1. Создать расписание бэкапов
kubectl apply -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: RecurringJob
metadata:
  name: dr-backup
  namespace: longhorn-system
spec:
  groups: ["dr-backup"]
  schedule: "*/30 * * * *"    # каждые 30 минут
  retain: 3
  concurrency: 1
  task: backup
EOF

# 2. Или создать одноразовый бэкап
kubectl apply -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Backup
metadata:
  name: app-backup-001
  namespace: longhorn-system
spec:
  volumeName: app-data
  snapshotName: manual-snap
EOF
```

#### Создание DR Volume (Secondary кластер)

```bash
# 1. Найти бэкап
kubectl get backups.longhorn.io -n longhorn-system
# → backup-xxxxx  app-data  10Gi  2026-09-01  ready

# 2. Создать DR Volume из бэкапа
kubectl apply -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Volume
metadata:
  name: app-data-dr
  namespace: longhorn-system
spec:
  fromBackup: backup-xxxxx
  numberOfReplicas: 3
  drVolume: true              # Включить DR-режим
EOF

# 3. Проверить статус
kubectl get volumes.longhorn.io app-data-dr -n longhorn-system
# → state: detached, standby: true

# 4. При необходимости: активировать DR Volume
kubectl patch volume app-data-dr -n longhorn-system --type merge \
  -p '{"spec":{"drVolume":false}}'
# Теперь том доступен для записи
```

### 3. Velero: межкластерная миграция/DR

#### Архитектура

```
Source Cluster:
  1. Velero backup → CSI snapshot → S3 (BSL)
  2. K8s resources → S3 (BSL)

Target Cluster:
  1. Velero restore из S3 (BSL)
  2. CSI snapshot → новый PVC
```

#### Установка Velero на обоих кластерах

```bash
# На обоих кластерах:
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.13.0 \
  --bucket velero-dr-backups \
  --secret-file ./credentials-velero \
  --backup-location-config region=us-east-1 \
  --use-node-agent
```

#### Настройка VolumeSnapshotClass

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ceph-rbd-snapclass
  labels:
    velero.io/csi-volumesnapshot-class: "true"  # Velero найдёт этот класс
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  csi.storage.k8s.io/snapshot-secret-name: ceph-secret
  csi.storage.k8s.io/snapshot-secret-namespace: default
```

#### Создание бэкапа (Source Cluster)

```bash
# Одноразовый бэкап
velero backup create prod-backup-001 \
  --include-namespaces production \
  --snapshot-volumes \
  --wait

# Проверка
velero backup describe prod-backup-001 --details
velero backup logs prod-backup-001 | grep -i error
```

#### Восстановление (Target Cluster)

```bash
# 1. Проверить доступность бэкапов
velero backup get

# 2. Восстановить в целевой namespace
velero restore create prod-restore-001 \
  --from-backup prod-backup-001 \
  --namespace-mappings production:production-restored \
  --wait

# 3. Проверить
velero restore describe prod-restore-001
kubectl get pvc -n production-restored
```

### 4. rsync поверх VPN (файловая репликация)

Для NFS/CephFS — простой вариант DR:

```bash
#!/bin/bash
# rsync-репликация NFS-данных

SOURCE_NFS="192.168.1.100:/exports/data"
TARGET_REMOTE="dr-backup-server:/backup/nfs-data"

# Синхронизация
rsync -avz --delete \
  -e "ssh -i /root/.ssh/dr-key" \
  ${SOURCE_NFS}/ \
  ${TARGET_REMOTE}/

# Результат
# → sent 1.2GB  received 500MB  25.3MB/s
```

---

## Дополнительная информация

### Чеклист DR-планирования

- [ ] Определены RPO/RTO для каждого сервиса
- [ ] Выбран метод репликации (синхронный/асинхронный)
- [ ] Настроены расписания репликации/бэкапов
- [ ] Тестовое восстановление выполнено и задокументировано
- [ ] Сетевая связность между кластерами проверена
- [ ] Документирована процедура failover/failback
- [ ] Мониторинг статуса репликации настроен (алерты на отставание)
- [ ] Регулярная верификация бэкапов (проверка восстановления)

### См. также

- [CSI — миграция между кластерами](./CSI/csi_cross_cluster_migration.md) — подробное руководство.
- [Velero — обзор](../ToolsUtilities/velero-overview.md) — архитектура и CRD.
- [Longhorn — DR Volume](./longhorn.md# Disaster Recovery) — DR-тома.
- [Ceph — RBD Mirroring](./Ceph/ceph_rbd_usage/advanced_topics.md) — настройка.
- [DRBD + Pacemaker](../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md) — HA на уровне ОС.
