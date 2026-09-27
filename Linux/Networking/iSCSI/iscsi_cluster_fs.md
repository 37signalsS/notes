# iSCSI: Кластерные файловые системы (GFS2, OCFS2)

Руководство по использованию кластерных файловых систем поверх iSCSI LUN для одновременного доступа данных с нескольких узлов.

## Определения

| Термин | Описание |
| :--- | :--- |
| **GFS2 (Global File System 2)** | Кластерная файловая система от Red Hat. Поддерживает одновременный доступ с нескольких узлов через DLM (Distributed Lock Manager). Используется в RHEL/Academy Hat. |
| **OCFS2 (Oracle Cluster File System 2)** | Кластерная файловая система от Oracle. Поддерживает параллельный I/O, используется для Oracle RAC и общих хранилищ. |
| **DLM (Distributed Lock Manager)** | Распределённый менеджер блокировок, обеспечивающий когерентность данных между узлами. Каждая ФС-операция блокирует соответствующие блоки на всех узлах. |
| **DLM Lock** | Блокировка на уровне блока ФС. Типы: Нет (NL), Частичный (PR), Разделяемый (CR), Эксклюзивный (EX). |
| **Clustered LVM (clvm)** | Расширение LVM для кластерных сред. Позволяет управлять VG/LV одновременно с нескольких узлов через dlm + clvmd. |
| **GULM (Global Unified Lock Manager)** | Устаревший менеджер блокировок для GFS (v1). Заменён DLM. |

## Зачем нужны кластерные ФС

### Проблема: обычная ФС на общем LUN

```text
┌──────────────┐              ┌──────────────┐
│    Node 01   │              │    Node 02   │
│  ext4 /dev/sda│             │  ext4 /dev/sda│
│  (read/write)│              │  (read/write)│
└──────┬───────┘              └──────┬───────┘
       │                              │
       └──────────────┬───────────────┘
                      │
              ┌───────▼───────┐
              │   iSCSI LUN   │
              │   (общий)     │
              └───────────────┘

Проблема: ext4 не координирует доступ!
Node01 пишет блок 100, Node02 перезаписывает блок 100 → ПОВРЕЖДЕНИЕ ДАННЫХ
```

### Решение: кластерная ФС + DLM

```text
┌──────────────┐              ┌──────────────┐
│    Node 01   │              │    Node 02   │
│  GFS2 /dev/sda│             │  GFS2 /dev/sda│
│  + DLM lock   │             │  + DLM lock   │
└──────┬───────┘              └──────┬───────┘
       │                              │
       │    DLM coordination          │
       ├──────────────────────────────┤
       │                              │
       └──────────────┬───────────────┘
                      │
              ┌───────▼───────┐
              │   iSCSI LUN   │
              │   (общий)     │
              └───────────────┘

Node01 запрашивает блокировку EX для блока 100
Node02 получает отказ (ожидание) → данные целостны
```

## Сравнение GFS2 и OCFS2

| Критерий | GFS2 | OCFS2 |
| :--- | :--- | :--- |
| **Разработчик** | Red Hat | Oracle |
| **Менеджер блокировок** | DLM (через pacemaker) | O2CB (встроенный) или DLM |
| **Журналирование** | Двухуровневое (per-node + shared) | Перinode |
| **Макс. размер ФС** | 8 ЭБ (64-бит) | 4 ПБ |
| **Макс. кол-во узлов** | ~256 (зависит от DLM) | ~256 |
| **Производительность** | Выше для metadata-heavy workload | Выше для parallel I/O |
| **Поддержка в RHEL** | Да (стандарт) | Да (через пакет) |
| **Поддержка в Ubuntu/Debian** | Да (пакет `gfs2-utils`) | Да (пакет `ocfs2-tools`) |
| **Применение** | General-purpose, SAP, HA-кластеры | Oracle RAC, базы данных |
| **Требование** | DLM (pacemaker) | O2CB кластер или DLM |

## Требования

1. **Общее блочное устройство:** iSCSI LUN, доступный со всех узлов
2. **SCSI-3 Persistent Reservations:** Обязательны для защиты от повреждения данных
3. **DLM или O2CB:** Менеджер блокировок должен быть запущен на всех узлах
4. **Синхронизация времени:** `chrony` или `ntp` (разница < 500 мс)
5. **Сеть:** Стабильная сеть между узлами (для DLM heartbeats)
6. **Пакеты:**
   - GFS2: `gfs2-utils`, `dlm`
   - OCFS2: `ocfs2-tools`, `ocfs2console`

## Практические сценарии

### Сценарий 1: Настройка GFS2 + DLM на двух узлах

#### Шаг 1: Установка пакетов (оба узла)

```bash
# RHEL/Rocky/Alma
sudo dnf install -y gfs2-utils dlm lvm2-cluster

# Debian/Ubuntu
sudo apt install -y gfs2-utils dlm lvm2-cluster
```

#### Шаг 2: Настройка DLM (оба узла)

```bash
# Включение DLM в автозагрузку
sudo systemctl enable --now dlm

# Проверка статуса
sudo systemctl status dlm
# → Active: active (running)
```

#### Шаг 3: Настройка кластера (один узел)

```bash
# Создание кластера (или использование существующего Pacemaker)
sudo pcs cluster setup my_cluster node1 node2
sudo pcs cluster start --all
sudo pcs cluster enable --all

# Настройка кворума (для 2 узлов: two_node)
sudo pcs property set no-quorum-policy=ignore
sudo pcs property set two_node=1
```

#### Шаг 4: Создание общего LVM (один узел)

```bash
# Создание кластерного VG (используя multipath-устройство)
sudo vgcreate --shared vg_cluster /dev/mapper/mpatha

# Создание LV
sudo lvcreate -L 100G -n lv_shared vg_cluster

# Форматирование GFS2
sudo mkfs.gfs2 -p lock_dlm -t my_cluster:shared_fs /dev/vg_cluster/lv_shared
# → This will destroy any data on /dev/vg_cluster/lv_shared.
# →Proceed? (y/n) y
# → Formatting: Downsize: Done.
# → Adding journals: Done.
# → Building resource groups: Done.
# → Creating quota data: Done.
# → Writing superblock and accounting information: Done.
```

**Параметры mkfs.gfs2:**
- `-p lock_dlm`: Протокол блокировок (DLM через pacemaker)
- `-t my_cluster:shared_fs`: Имя кластера:имя ФС (должно совпадать на всех узлах)
- `-j 2`: Количество журналов (по умолчанию = кол-во узлов)
- `-b 4K`: Размер блока (по умолчанию 4K)

#### Шаг 5: Монтирование (оба узла)

```bash
# На обоих узлах:
sudo mkdir -p /mnt/gfs2
sudo mount -o noatime /dev/vg_cluster/lv_shared /mnt/gfs2

# Проверка
df -h /mnt/gfs2
# → /dev/vg_cluster/lv_shared  100G  4.0K   96G   1% /mnt/gfs2

# Проверка кластерного монтирования
gfs2_tool df /mnt/gfs2
# → /dev/vg_cluster/lv_shared:
# →  SB lock proto = lock_dlm
# →  SB lock table = my_cluster:shared_fs
# →  Block size = 4096
# →  Journals = 2
```

#### Шаг 6: Автоматическое монтирование (/etc/fstab)

```bash
# На обоих узлах добавить в /etc/fstab:
/dev/vg_cluster/lv_shared  /mnt/gfs2  gfs2  defaults,noatime,_netdev  0  0
```

### Сценарий 2: Настройка OCFS2

#### Шаг 1: Установка

```bash
# RHEL/Rocky
sudo dnf install -y ocfs2-tools

# Debian/Ubuntu
sudo apt install -y ocfs2-tools
```

#### Шаг 2: Настройка O2CB кластера

```bash
# Создание кластера O2CB
sudo o2cb add-cluster mycluster

# Добавление узлов
sudo o2cb add-nodemap mycluster node1 1
sudo o2cb add-nodemap mycluster node2 2

# Запуск сервисов
sudo systemctl enable --now o2cb
sudo systemctl enable --now ocfs2

# Проверка статуса
sudo o2cb status
# → Cluster 'mycluster':
# →   Node 1 (node1): Online
# →   Node 2 (node2): Online
```

#### Шаг 3: Форматирование OCFS2

```bash
sudo mkfs.ocfs2 -b 4K -C 32K -N 4 -L myfs /dev/vg_cluster/lv_shared
```

**Параметры:**
- `-b 4K`: Размер блока
- `-C 32K`: Размер кластера (для parallel I/O)
- `-N 4`: Максимальное количество узлов
- `-L myfs`: Метка ФС

#### Шаг 4: Монтирование

```bash
sudo mkdir -p /mnt/ocfs2
sudo mount -t ocfs2 -o noatime,nodiratime /dev/vg_cluster/lv_shared /mnt/ocfs2

# /etc/fstab:
/dev/vg_cluster/lv_shared  /mnt/ocfs2  ocfs2  defaults,noatime,nodiratime,_netdev,cluster_stack=o2cb  0  0
```

### Сценарий 3: Кластерный LVM (clvm)

Для управления LVM с нескольких узлов одновременно:

```bash
# Включение кластерного LVM (оба узла)
sudo systemctl enable --now clvmd

# Проверка
sudo clvmd -s
# → clvmd Cluster LVM Daemon started

# Создание VG (выполнять ОДИН раз с любого узла)
sudo vgcreate --shared vg_cluster /dev/mapper/mpatha

# Создание LV (с любого узла)
sudo lvcreate -L 50G -n lv_data vg_cluster

# Просмотр с любого узла
sudo lvs
# → LV     VG       Attr       LSize   Pool Origin Data%
# → lv_data vg_cluster -wi-------  50.00g
```

### Сценарий 4: Добавление нового узла

```bash
# 1. Подключение нового узла к iSCSI LUN
sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP>
sudo iscsiadm -m node -T <IQN> -p <IP> --login

# 2. Настройка multipath
sudo multipath -r

# 3. Добавление узла в кластер Pacemaker
sudo pcs cluster auth new_node
sudo pcs cluster node add new_node

# 4. Добавление узла в DLM
# (выполняется автоматически через Pacemaker)

# 5. Монтирование GFS2
sudo mount -o noatime /dev/vg_cluster/lv_shared /mnt/gfs2

# 6. Проверка количества журналов (для GFS2)
# Если журналов недостаточно — добавить:
sudo gfs2_jadd -j 1 /dev/vg_cluster/lv_shared
```

### Сценарий 5: Мониторинг кластерной ФС

```bash
# Просмотр блокировок DLM
sudo dlm_tool lockdebug mycluster

# Просмотр статуса GFS2
sudo gfs2_tool sb /mnt/gfs21 sb
# → Locking Protocol: lock_dlm
# → Lock Table: my_cluster:shared_fs

# Просмотр журналов
sudo gfs2_jadd -l /dev/vg_cluster/lv_shared

# Мониторинг через Pacemaker
sudo pcs resource status
```

## Диагностика проблем

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `gfs2: error mounting: Resource temporarily unavailable` | DLM не запущен или кворум не собран | `sudo systemctl start dlm`, проверить `pcs status` |
| `mount: /mnt/gfs2: unknown filesystem type 'gfs2'` | Модуль gfs2 не загружен | `sudo modprobe gfs2` + `sudo update-initramfs -u` |
| `dlm: clustr.gridy shutdown` | Сетевая изоляция узла | Проверить сеть, порты 5404-5405 (UDP) |
| `GFS2: not a valid GFS2 device` | Неверная ФС или повреждённый суперблок | Восстановить из бэкапа или переформатировать |
| `ocfs2: Mount failed` | O2CB кластер не инициализирован | `sudo o2cb init-cluster mycluster` |
| ФС переключается в read-only | DLM потерял связь с узлом | Проверить сеть, увеличить DLM timeouts |
| Высокая latency при записи | Много блокировок DLM | Увеличить размер кластера ФС (`-C`), проверить сеть |

### Проверка DLM

```bash
# Статус DLM кластера
sudo dlm_tool status
# → Cluster: my_cluster
# →   Node: 1 (node1) - fe400a00  Member
# →   Node: 2 (node2) - fe400a01  Member

# Список активных блокировок
sudo dlm_tool lockdebug mycluster

# Логи DLM
sudo journalctl -u dlm -f
```

### Проверка GFS2

```bash
# Информация о суперблоке
sudo gfs2_tool sb /mnt/gfs2 sb

# Список journal'ов
sudo gfs2_jadd -l /dev/vg_cluster/lv_shared

# Проверка целостности (только при размонтированной ФС!)
sudo fsck.gfs2 -y /dev/vg_cluster/lv_shared
```

## Рекомендации для production

1. **SCSI-3 PR обязательны:** Без них риск повреждения данных при split-brain
2. **DLM через Pacemaker:** Не используйте автономный DLM без кластерного менеджера
3. **Мониторинг блокировок:** Настраивайте алерты на рост количества блокировок
4. **Размер journal:** Для metadata-heavy workload увеличивайте количество журналов
5. **Тестирование failover:** Регулярно проверяйте переключение узлов
6. **Backup:** Кластерные ФС не заменяют бэкап — используйте LVM-снапшоты

## См. также

- **[SCSI-3 Persistent Reservations](./iscsi_persistent_reservations.md)** — блокировки на уровне LUN
- **[iSCSI + Pacemaker HA](./iscsi_ha_pacemaker.md)** — автоматизация кластера
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость путей
- **[Сравнение iSCSI с NVMe-oF](./iscsi_concepts.md#сравнение-iscsi-с-альтернативами)** — когда выбирать другой протокол
