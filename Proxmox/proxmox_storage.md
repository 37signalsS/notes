---
Надёжность: 10 (SSoT + Проектный контекст 2026)
Свежесть: Актуально на июль 2026
---

# Хранилища и Ceph в Proxmox

## Определения

**Storage (Хранилище)** в Proxmox Virtual Environment (PVE) — это абстрактный слой управления данными для подключения физических и сетевых накопителей. Используется для хранения дисков виртуальных машин (VM), контейнеров (LXC), образов ISO и резервных копий.

**Content Types (Типы контента)** — фильтры, определяющие назначение хранилища:
- **Disk images**: Диски VM (KVM).
- **ISO images**: Установочные образы ОС.
- **Container templates**: Шаблоны LXC.
- **Container**: Корневые ФС контейнеров.
- **VZDump backups**: Резервные копии (`vzdump` или PBS).
- **Snippets**: Скрипты (Cloud-Init, хуки).

## Основные концепции

### Типы локальных хранилищ

- **Directory**: Обычная папка (ext4/XFS). Универсальна, поддерживает все типы контента. Диски хранятся как файлы `.qcow2` или `.raw`.
- **LVM**: Блочные устройства. Быстрый доступ, но нет нативной поддержки снапшотов в PVE.
- **LVM-Thin**: Поддерживает Thin Provisioning и снапшоты. Идеально для локальных VM. Не поддерживает репликацию.
- **ZFS**: Рекомендуется для High Availability. Поддерживает компрессию и Storage Replication (репликация по расписанию через `zfs send/receive`).
- **BTRFS**: Поддерживается с PVE 7.x. Альтернатива ZFS для одиночных дисков, поддерживает снапшоты и компрессию.

### Сетевые и общие хранилища (Shared Storage)

Позволяют выполнять **Live Migration** без перемещения данных.
- **NFS**: Простая настройка, поддержка всех типов контента.
- **iSCSI**: Передача блочных данных. Требует LVM поверх для многопользовательского доступа.
- **Ceph (RBD/CephFS)**: Распределенное хранилище (см. ниже).
- **Proxmox Backup Server (PBS)**: Инкрементальные дедуплицированные бэкапы.

### Гиперконвергентный Ceph

**Ceph** объединяет локальные диски всех нод в единый отказоустойчивый пул. В PVE 8.x используются версии **Quincy** (17.2) или **Reef** (18.2).

- **MON (Monitors)**: Хранят карту состояния (нужно минимум 3 для кворума).
- **MGR (Managers)**: Мониторинг и метрики.
- **OSD (Object Storage Daemon)**: Управляет физическим диском. Репликация идет между OSD.
- **RBD (RADOS Block Device)**: Блочное хранилище для дисков VM.
- **CephFS**: Файловая система для ISO, шаблонов и бэкапов (требует MDS).

## Практические сценарии

### Управление через CLI (pvesm)

**Просмотр статуса:**
```bash
pvesm status
# → Name             Type     Status  Total (KB)   Used (KB)   Free (KB)   %
# → local            dir      active  102000000    5000000     97000000    4.90%
```

**Добавление NFS-хранилища:**
```bash
pvesm add nfs my-nfs --server 10.0.0.50 --export /mnt/pve --content images,iso
# → update storage: 'my-nfs'
```

**Импорт существующего диска в VM:**
```bash
qm importdisk 101 /tmp/image.qcow2 local-lvm
# → import: 100% done
# → Successfully imported disk as 'unused0'
```

### Настройка Ceph через CLI (pveceph)

**Статус кластера:**
```bash
pveceph status
# → health: HEALTH_OK
# → osds: 6 up, 6 in
```

**Создание OSD на новом диске:**
```bash
pveceph osd create /dev/nvme0n1
# → create OSD on /dev/nvme0n1 (bluestore)
```

## Диагностика и обслуживание

### Проблемы с производительностью (IO Delay)
Если в GUI наблюдается высокий "IO Delay":
1. Проверьте статус ZFS/Ceph: `zpool status` или `pveceph status`.
2. Проверьте нагрузку на диски: `iostat -x 1`.
3. Убедитесь, что LVM-Thin пул не заполнен на 100% (это блокирует запись всех VM).

### Очистка неиспользуемых дисков
```bash
pvesm free local-thin:vm-101-disk-0
# → successfully removed volume
```

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Кластеризация и HA в Proxmox](./proxmox_cluster.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)
- [Администрирование Ceph — Обзор](../Kubernetes/Storage/Ceph/Administration/index.md)
- [LVM Thin Provisioning](../../Linux/FileSystems/LVM/thin-provisioning.md)
