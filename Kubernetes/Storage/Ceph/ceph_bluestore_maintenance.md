# Обслуживание BlueStore

Руководство по эксплуатации, диагностике и обслуживанию хранилища BlueStore в OSD Ceph. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**, где BlueStore является стандартным бэкендом по умолчанию.

> **Границы документа:** общее управление OSD (добавление, замена, удаление) описано в [Операциях Ceph](./Administration/operations.md#2-управление-osd-классические-и-crimson); диагностика PG и recovery — в [Углубленной диагностике OSD/PG](./ceph_osd_troubleshooting.md); производительность — в [Бенчмаркинге](./ceph_benchmarks.md).

## Определения

**BlueStore** — бэкенд хранения данных OSD, работающий напрямую с блочным устройством, минуя файловую систему ОС. Хранит данные в raw-блоках, а метаданные — в RocksDB на том же устройстве или на выделенном DB/WAL.

**BlueFS** — легковесная файловая система поверх RocksDB, используемая BlueStore для организации метаданных (WAL, db-файлы RocksDB).

**DB/WAL устройства** — выделенные SSD/NVMe устройства для метаданных BlueStore (RocksDB + WAL). Позволяют размещать метаданные отдельно от данных, что критично для производительности на HDD-кластерах.

**WAL (Write Ahead Log)** — журнал предзаписи, обеспечивающий атомарность операций BlueStore. На HDD должен быть на отдельном SSD; на NVMe может быть на том же устройстве.

**RocksDB** — движок базы данных, используемый BlueStore для хранения метаданных объектов (дедупликация, индексы, атрибуты).

## Базовые концепции

### Архитектура BlueStore

```
┌─────────────────────────────────────────────────────────────┐
│  OSD Process (ceph-osd)                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Client    │  │   Journal   │  │   Metadata (RocksDB)│  │
│  │   I/O       │  │   (WAL)      │  │                     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │              │
│         ▼                ▼                     ▼              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              BlueStore Engine                         │    │
│  │  • Allocation (Bitmap + Freelist)                     │    │
│  │  • Compression (ZSTD, LZ4)                           │    │
│  │  • Checksums (XXH3, SHA256)                          │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                    │
│          ┌──────────────┼──────────────┐                     │
│          │              │              │                      │
│          ▼              ▼              ▼                       │
│    ┌───────────┐ ┌───────────┐ ┌───────────┐                  │
│    │  Data     │ │    WAL    │ │    DB     │                  │
│    │  (raw)    │ │  (SSD)    │ │  (SSD)    │                  │
│    └───────────┘ └───────────┘ └───────────┘                  │
│        HDD/NVMe       SSD/NVMe      SSD/NVMe                  │
└─────────────────────────────────────────────────────────────┘
```

### Типы конфигураций BlueStore

| Конфигурация | Data | WAL | DB | Сценарий |
|--------------|------|-----|----|----------|
| **All-in-one** | HDD | HDD (shared) | HDD (shared) | Тестовые среды, бюджетные кластеры |
| **Separated DB/WAL** | HDD | SSD | SSD | Production на HDD (метаданные отдельно) |
| **NVMe single** | NVMe | NVMe (shared) | NVMe (shared) | Высокопроизводительные кластеры |
| **Separated NVMe** | NVMe | NVMe (dedicated) | NVMe (dedicated) | Критичная производительность, большие PG |

### Сmeta-данные BlueStore

BlueStore хранит два типа метаданных:

1. **Внутренние метаданные (onode)** — индексы объектов, отображение object_id → блоки на диске. Хранятся в RocksDB.
2. **Внешние метаданные (xattr/omap)** — атрибуты объектов (ACL, временные метки, extended attributes). Также в RocksDB.

На HDD-кластерах RocksDB должен быть на SSD, иначе метаданные становятся узким местом.

## Практические сценарии

### 1. Проверка состояния BlueStore

#### 1.1 Просмотр информации об OSD

```bash
# Информация о бэкенде
ceph osd metadata <osd-id>
# → backend: Bluestore
# → osd_objectstore: bluestore

# ПроверкаBlueFS (файловая система метаданных)
ceph daemon osd.<id> bluestore fsck

# Статистика BlueStore
ceph daemon osd.<id> bluestore stats
# → {
#       "bluestore": {
#           "bytes": ...,
#           "bytes_used": ...,
#           "bytes_avail": ...,
#           "rocksdb": {
#               "bytes_used": ...
#           }
#       }
#   }
```

#### 1.2 Проверка здоровья дисков

```bash
# SMART-атрибуты
ssh <host> "smartctl -a /dev/sdb"

# Ошибки диска
ssh <host> "cat /sys/block/sdb/sdA/device/state"
ssh <host> "cat /proc/scsi/scsi"

# Логи OSD
journalctl -u ceph-osd@<id> --since "7 days ago"
```

### 2. BlueStore fsck и repair

#### 2.1 Проверка файловой системы BlueFS

```bash
# Остановить OSD
ceph orch daemon stop osd.<id>

# Проверка BlueFS
ceph-bluestore-tool fsck --path /var/lib/ceph/osd/<fsid>/osd.<id>

# Просмотр меток
ceph-bluestore-tool show-label --path /var/lib/ceph/osd/<fsid>/osd.<id>
```

#### 2.2 Восстановление из резервной копии

```bash
# Экспорт данных из старого OSD
ceph-objectstore-tool \
  --data-path /var/lib/ceph/osd/<fsid>/osd.<old-id> \
  --type bluestore \
  --op export \
  --out /tmp/osd-export.bin

# Импорт в новый OSD
ceph-objectstore-tool \
  --data-path /var/lib/ceph/osd/<fsid>/osd.<new-id> \
  --type bluestore \
  --op import \
  --in /tmp/osd-export.bin
```

### 3. Управление DB/WAL устройствами

#### 3.1 Конфигурация при создании OSD

```yaml
# spec.yaml для OSD с отдельными DB/WAL
service_type: osd
service_id: fast_osds
placement:
  label: osd_nvme
data_devices:
  rotational: false
db_devices:
  rotational: false
  size: "200G:"
wal_devices:
  rotational: false
  size: "50G:"
```

```bash
ceph orch apply -i spec.yaml
```

#### 3.2 Проверка использования DB/WAL

```bash
# Размер RocksDB
ceph daemon osd.<id> bluestore stats | jq '.bluestore.rocksdb'

# Квота на DB/WAL
ceph config get osd osd_bluestore_min_alloc_size
ceph config get osd bluestore_db_size
```

### 4. Сжатие и оптимизация

#### 4.1 Включение сжатия

```bash
# Глобально
ceph config set global bluestore_compression_mode passive

# Для конкретного пула
ceph osd pool set <pool-name> compression_algorithm zstd
ceph osd pool set <pool-name> compression_mode aggressive
```

#### 4.2 Настройка размера allocation unit

```bash
# Минимальный размер блока (4KB для small files, 64KB для big data)
ceph config set osd bluestore_min_alloc_size 4096
ceph config set osd bluestore_min_alloc_size_hdd 65536
```

### 5. Compact и обслуживание RocksDB

```bash
# Принудительная компактизация RocksDB
ceph daemon osd.<id> rocksdb compact

# Просмотр статистики RocksDB
ceph daemon osd.<id> rocksdb stats
```

### 6. Отказоустойчивость: замена диска с BlueStore

```bash
# 1. Остановить OSD
ceph orch daemon stop osd.<id>

# 2. Заменить физический диск
# (если используется DB/WAL на том же диске — нужно пересоздать и их)

# 3. Очистить заголовок Ceph
ceph-volume lvm zap /dev/sdX

# 4. Создать новый OSD
ceph orch daemon add osd <hostname>:/dev/sdX

# 5. Проверить
ceph osd tree
```

### 7. Мониторинг фрагментации

```bash
# Проверка фрагментации данных
ceph daemon osd.<id> bluestore allocator stats

# Если фрагментация высокая (>30%), запустите compact
ceph daemon osd.<id> rocksdb compact
```

## Лучшие практики

### Проектирование

- **HDD-кластеры:** отдельные SSD для DB/WAL (минимум 200GB на OSD).
- **NVMe-кластеры:** DB/WAL на том же NVMe допустим, но для максимальной производительности используйте отдельные.
- **Сжатие:** для cold data (архивы) используйте `zstd`; для hot data — `lz4` или отключите.
- **Размер блока:** `bluestore_min_alloc_size` 4KB для small files, 64KB для больших объектов (>1MB).

### Эксплуатация

- **Scrubbing:** планируйте deep scrub на часы минимальной нагрузки.
- **Диски:** мониторьте SMART-атрибуты, особенно `Reallocated_Sector_Ct` и `Current_Pending_Sector`.
- **Резервное копирование:** экспортируйте OSD перед деструктивными операциями.

### Ограничения

- BlueStore не поддерживает перемещение данных между устройствами без пересоздания OSD.
- Изменение конфигурации DB/WAL требует пересоздания OSD.
- `ceph-bluestore-tool` работает только с остановленным OSD.

## Дополнительная информация

### См. также

- [Операции Ceph](./Administration/operations.md) — управление OSD, замена дисков
- [Углубленная диагностика OSD/PG](./ceph_osd_troubleshooting.md) — recovery procedures, peering failures
- [Бенчмаркинг](./ceph_benchmarks.md) — тестирование производительности

### Официальные ресурсы

- [BlueStore Configuration](https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/) — параметры конфигурации
- [BlueStore Troubleshooting](https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-bluestore/) — официальное руководство
