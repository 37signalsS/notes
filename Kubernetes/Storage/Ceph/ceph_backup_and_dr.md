# Резервное копирование и Disaster Recovery в Ceph

Документ охватывает стратегии бэкапа данных и конфигурации Ceph, процедуры восстановления после аварий (Disaster Recovery). Является чек-листом для DevOps/SRE/sysadmin в продуктовых средах. Актуально для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

---

## Определения

**RPO (Recovery Point Objective)** — максимальный объём потерь данных, допустимый при аварии. Определяется частотой бэкапов или репликации.

**RTO (Recovery Time Objective)** — максимальное время восстановления сервиса после аварии.

**Бэкап конфигурации** — сохранение состояния кластера: `ceph.conf`, ключей (CephX), CRUSH-карты, сервисных спецификаций, конфигурационной базы данных (config db).

**Бэкап данных** — сохранение пользовательских данных: RBD-образов, объектов RGW, файлов CephFS.

**Disaster Recovery (DR)** — процедуры восстановления кластера после катастрофических сбоев: потеря кворума MON, потеря данных, повреждение store.

---

## Базовые концепции

### Два типа бэкапов

| Тип | Что хранится | Восстанавливает | Частота |
|-----|-------------|-----------------|---------|
| **Конфигурация** | ceph.conf, keyrings, crushmap, auth, specs | Контроль над кластером | Еженедельно + перед апгрейдом |
| **Данные** | RBD образы, CephFS файлы, RGW объекты | Пользовательские данные | По расписанию (daily/weekly) |

> **Критично:** бэкап конфигурации НЕ восстанавливает данные. Бэкап данных НЕ восстанавливает контроль над кластером. Нужны оба типа.

### Стратегия 3-2-1

```
3 копии данных
├── 1: Оригинал в Ceph-кластере (production)
├── 2: Локальный бэкап (другой сервер/сторадж)
└── 3: Off-site бэкап (другой ЦОД,对象ное хранилище)
```

---

## Практические сценарии

### 1. Бэкап конфигурации кластера

#### 1.1 Полный бэкап состояния

```bash
#!/bin/bash
# ceph-config-backup.sh
BACKUP_DIR="/backup/ceph/$(date +%F)"
mkdir -p "$BACKUP_DIR"

# 1. Конфигурация
ceph config dump -f json-pretty > "$BACKUP_DIR/ceph-config.json"

# 2. Ключи (CephX)
ceph auth export -o "$BACKUP_DIR/ceph-auth.export"

# 3. Статус кластера
ceph -s -f json-pretty > "$BACKUP_DIR/ceph-status.json"

# 4. CRUSH-карта
ceph osd getcrushmap -o "$BACKUP_DIR/ceph-crushmap.bin"

# 5. Мониторная карта
ceph mon dump -f json-pretty > "$BACKUP_DIR/ceph-monmap.json"

# 6. Сервисные спецификации (cephadm)
ceph orch ls --export -o "$BACKUP_DIR/ceph-specs.yaml"

# 7. Конфигурация пулов
ceph osd pool ls detail -f json-pretty > "$BACKUP_DIR/ceph-pools.json"

# 8. Проверка PG
ceph pg stat -f json-pretty > "$BACKUP_DIR/ceph-pgstat.json"

echo "Backup completed: $BACKUP_DIR"
ls -la "$BACKUP_DIR"
```

#### 1.2 Бэкап store монитора (per-MON)

```bash
#!/bin/bash
# ceph-mon-backup.sh
# Выполнять на каждом MON или через cephadm

MON_HOST="ceph-mon1"
BACKUP_DIR="/backup/ceph/mon/${MON_HOST}/$(date +%F)"
mkdir -p "$BACKUP_DIR"

# Остановить MON (через cephadm)
ceph orch daemon stop mon.${MON_HOST}

# Копирование store
rsync -aHP /var/lib/ceph/*/mon.${MON_HOST}/store.db "$BACKUP_DIR/"

# Запуск MON
ceph orch daemon start mon.${MON_HOST}

echo "MON store backup completed: $BACKUP_DIR"
```

#### 1.3 Автоматизация (cron)

```bash
# Еженедельный бэкап конфигурации (воскресенье, 02:00)
0 2 * * 0 /usr/local/bin/ceph-config-backup.sh >> /var/log/ceph-backup.log 2>&1

# Ежедневный бэкап store мониторов (пн-пт, 03:00)
0 3 * * 1-5 /usr/local/bin/ceph-mon-backup.sh >> /var/log/ceph-backup.log 2>&1
```

### 2. Бэкап данных

#### 2.1 RBD: инкрементальный бэкап

```bash
#!/bin/bash
# rbd-backup.sh
POOL="kube"
BACKUP_DIR="/backup/ceph/rbd"
DATE=$(date +%F)

# Создание снапшота
for img in $(rbd ls -p "$POOL"); do
  SNAP_NAME="backup-${DATE}"
  rbd snap create "${POOL}/${img}@${SNAP_NAME}"
  rbd snap protect "${POOL}/${img}@${SNAP_NAME}"

  # Инкрементальный экспорт (от предыдущего снапшота)
  PREV_SNAP=$(rbd snap ls "${POOL}/${img}" --format json | \
    python3 -c "import sys,json; snaps=[s for s in json.load(sys.stdin) if s['name'].startswith('backup-')]; print(snaps[-2]['name'] if len(snaps)>1 else '')")

  if [ -n "$PREV_SNAP" ]; then
    rbd export-diff "${POOL}/${img}@${PREV_SNAP}@${SNAP_NAME}" \
      "${BACKUP_DIR}/${img}-${PREV_SNAP}-${SNAP_NAME}.diff"
  else
    rbd export "${POOL}/${img}@${SNAP_NAME}" \
      "${BACKUP_DIR}/${img}-${SNAP_NAME}.img"
  fi

  echo "Backed up: ${img}"
done

# Удаление старых снапшотов (старше 30 дней)
for img in $(rbd ls -p "$POOL"); do
  for snap in $(rbd snap ls "${POOL}/${img}" --format json | \
    python3 -c "import sys,json; [print(s['name']) for s in json.load(sys.stdin) if s['name'].startswith('backup-') and s['name'] < 'backup-$(date -d-30days +%F)']"); do
    rbd snap unprotect "${POOL}/${img}@${snap}" 2>/dev/null || true
    rbd snap rm "${POOL}/${img}@${snap}"
  done
done
```

#### 2.2 CephFS: бэкап через rsync

```bash
#!/bin/bash
# cephfs-backup.sh
CEPHFS_MOUNT="/mnt/cephfs"
BACKUP_DIR="/backup/ceph/cephfs"
DATE=$(date +%F)

# Полный бэкап (rsync с инкрементальным режимом)
rsync -aHP --delete \
  --link-dest="${BACKUP_DIR}/latest" \
  "${CEPHFS_MOUNT}/" \
  "${BACKUP_DIR}/${DATE}/"

# Обновление symlink на последний бэкап
ln -snf "${BACKUP_DIR}/${DATE}" "${BACKUP_DIR}/latest"

echo "CephFS backup completed: ${BACKUP_DIR}/${DATE}"
```

#### 2.3 RGW: бэкап через S3 API

```bash
#!/bin/bash
# radosgw-backup.sh
# Синхронизация бакетов на второй RGW-эндпоинт (replication) или в object storage

SOURCE_ENDPOINT="http://rgw-primary:7480"
BACKUP_ENDPOINT="http://rgw-backup:7480"

# Список бакетов
BUCKETS=$(aws s3 ls --endpoint-url "$SOURCE_ENDPOINT" | awk '{print $3}')

for bucket in $BUCKETS; do
  aws s3 sync "s3://${bucket}" "s3://${bucket}" \
    --source-endpoint-url "$SOURCE_ENDPOINT" \
    --endpoint-url "$BACKUP_ENDPOINT"
  echo "Synced bucket: ${bucket}"
done
```

### 3. Восстановление конфигурации

#### 3.1 Восстановление из бэкапа

```bash
# Шаг 1: Восстановление ключей
ceph auth import -i /backup/ceph/$(date -d-7 +%F)/ceph-auth.export

# Шаг 2: Восстановление конфигурации
ceph config assimilate-conf -i /backup/ceph/$(date -d-7 +%F)/ceph-config.json

# Шаг 3: Восстановление CRUSH-карты
ceph osd setcrushmap -i /backup/ceph/$(date -d-7 +%F)/ceph-crushmap.bin

# Шаг 4: Проверка
ceph -s
ceph auth ls
ceph config dump
```

#### 3.2 Восстановление MON из бэкапа store

```bash
# Если MON store повреждён:

# 1. Остановить MON
ceph orch daemon stop mon.ceph-mon1

# 2. Восстановить store из бэкапа
RESTORE_DIR="/backup/ceph/mon/ceph-mon1/$(date -d-1 +%F)"
rsync -aHP "${RESTORE_DIR}/store.db/" /var/lib/ceph/*/mon.ceph-mon1/store.db/

# 3. Запустить MON
ceph orch daemon start mon.ceph-mon1

# 4. Проверить кворум
ceph mon stat
ceph quorum_status
```

### 4. Disaster Recovery: полная потеря кворума MON

#### 4.1 Чек-лист DR

- [ ] Определить количество выживших MON
- [ ] Проверить доступность OSD (`ceph osd tree`)
- [ ] Проверить наличие бэкапа конфигурации
- [ ] Оценить количество потерянных данных
- [ ] Принять решение: восстановление из бэкапа или из OSD

#### 4.2 Восстановление из бэкапа (Path A)

```bash
# Если есть бэкап store и выживший MON:

# 1. Восстановить store на выжившем MON
ceph mon getmap -o /tmp/monmap.bin

# 2. Пересоздать MON на новом хосте
ceph orch daemon add mon new-mon-host:10.0.0.15

# 3. Скопировать store на новый MON
# (выполнить на new-mon-host)
rsync -aHP /backup/ceph/mon/ceph-mon1/store.db/ /var/lib/ceph/*/mon.new-mon-host.store.db/

# 4. Запустить MON и проверить кворум
ceph mon stat
```

#### 4.3 Восстановление из OSD (Path B — нет бэкапа)

```bash
# КРИТИЧЕСКАЯ ПРОЦЕДУРА — только в случае полной потери MON store!

# 1. Остановить ВСЕ демоны кластера
cephadm cluster-stop --fsid <cluster-fsid>

# 2. С каждого OSD-хоста собрать osdmap
cephadm shell -- ceph-objectstore-tool \
  --data-path /var/lib/ceph/<fsid>/osd.<id> \
  --type bluestore \
  --op get-osdmap \
  --out /tmp/mon-store/osd.<id>.osdmap

# 3. Собрать все карты в один store
cephadm shell -- ceph-monstore-tool /tmp/mon-store rebuild \
  -- --keyring /etc/ceph/ceph.client.admin.keyring \
  --mon-ids mon.a mon.b mon.c

# 4. Развернуть store на первом MON
cephadm shell -- ceph-mon --mkfs -i <mon-id> \
  --monmap /tmp/mon-store/monmap \
  --osdmap /tmp/mon-store/osdmap

# 5. Запустить MON и кластер
cephadm cluster-start --fsid <cluster-fsid>

# 6. ПОСЛЕ ВОССТАНОВЛЕНИЯ: пересоздать:
#    - Ключи (ceph auth)
#    - Конфигурацию (ceph config)
#    - Сервисные спецификации (ceph orch apply)
#    - MDS, RGW и другие сервисы
```

> **Важно:** Восстановление из OSD — это сложная процедура, требующая минимум 2 инженеров и чек-лист. Потеря ключей и specs неизбежна — пересоздавайте из бэкапа.

### 5. Восстановление данных RBD

```bash
# Из полного бэкапа (rbd export)
rbd import /backup/ceph/rbd/my-image-backup.img kube/restored-image

# Из инкрементального бэкапа
# 1. Создать базовый образ (или восстановить из полного бэкапа)
rbd import /backup/ceph/rbd/my-image-backup.img kube/restored-image

# 2. Применить инкрементальные диффы
rbd import-diff /backup/ceph/rbd/my-image-backup-2025-08-01.diff kube/restored-image
rbd import-diff /backup/ceph/rbd/my-image-backup-2025-08-02.diff kube/restored-image

# 3. Проверка
rbd info kube/restored-image
rbd du kube/restored-image
```

### 6. Восстановление данных CephFS

```bash
# Из rsync-бэкапа
rsync -aHP /backup/ceph/cephfs/latest/ /mnt/cephfs-restored/

# Или монтирование бэкапа
mkdir /mnt/cephfs-backup
mount -t nfs backup-server:/backup/cephfs /mnt/cephfs-backup
rsync -aHP /mnt/cephfs-backup/ /mnt/cephfs-restored/
```

---

## Регламент

| Операция | Частота | Команда |
|----------|---------|---------|
| Бэкап конфигурации | Еженедельно | `ceph-config-backup.sh` |
| Бэкап store MON | Ежедневно | `ceph-mon-backup.sh` |
| Бэкап RBD | Ежедневно | `rbd-backup.sh` |
| Бэкап CephFS | Ежедневно | `rsync` |
| Тест восстановления | Ежеквартально | Восстановление на test-кластер |
| Ревью DR-плана | Раз в полгода | Ревью чек-листа |

---

## Дополнительная информация

### RPO/RTO для разных сценариев

| Сценарий | RPO | RTO | Стоимость |
|----------|-----|-----|-----------|
| Ежедневный бэкап | 24 часа | 1-4 часа | Низкая |
| Hourly backup | 1 час | 30-60 мин | Средняя |
| RBD mirroring (async) | 5-15 мин | 5-15 мин | Высокая |
| RBD mirroring (sync) | 0 | < 1 мин | Очень высокая |
| Replication 3x | 0 | < 1 мин | 3x存储 |

### Инструменты

| Инструмент | Назначение | Ссылка |
|-----------|-----------|--------|
| `rbd export/import` | Бэкап/восстановление RBD | Ceph docs |
| `rsync` | Бэкап CephFS/NFS | Linux standard |
| `velero` | Бэкап PV в Kubernetes | vmware-tanzu.github.io |
| `borgbackup` | Дедуплицирующий бэкап | borgbackup.org |
| `ceph-objectstore-tool` | Низкоуровневый доступ к OSD | Ceph docs |

### См. также

- [Операции Ceph](./Administration/operations.md) — резервное копирование конфигурации
- [Управление образами RBD](./ceph_rbd_usage/image_management.md) — экспорт/импорт образов
- [Практические сценарии CephFS](./cephfs_setup_and_usage/practical_scenarios.md) — бэкап субтомов
- [Администрирование Ceph](./Administration/index.md) — управление кластером
