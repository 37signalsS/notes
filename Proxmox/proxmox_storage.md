# Хранилища и Ceph в Proxmox

## Определения

**Storage (Хранилище)** в Proxmox Virtual Environment (PVE) — это абстрактный слой управления данными для подключения физических и сетевых накопителей. Используется для хранения дисков виртуальных машин (VM), контейнеров (LXC), образов ISO и резервных копий. Все хранилища описываются в общем конфигурационном файле `/etc/pve/storage.cfg`, который автоматически синхронизируется между узлами кластера через кластерную файловую систему pmxcfs.

**Content Types (Типы контента)** — фильтры, определяющие назначение хранилища (для одного хранилища можно указать несколько типов):
- **images**: Диски VM (KVM/QEMU).
- **rootdir**: Корневые файловые системы контейнеров (LXC).
- **iso**: Установочные образы ОС.
- **vztmpl**: Шаблоны LXC.
- **backup**: Резервные копии (`vzdump` или PBS).
- **snippets**: Скрипты (Cloud-Init, хуки виртуальных машин).
- **import**: OVA-образы и файлы дисков, которые можно импортировать в PVE (добавлен в PVE 8.3).

**Shared Storage (Общее хранилище)** — хранилище, доступное всем узлам кластера одновременно (NFS, SMB/CIFS, iSCSI, Ceph). Флаг `shared` в конфигурации **не делает** локальное хранилище общим — он лишь помечает уже совместно используемое хранилище, чтобы PVE корректно включил его в кластерные операции (Live Migration без копирования данных).

**Volume ID (VOLID)** — уникальный идентификатор тома в формате `<STORAGE_ID>:<путь/имя>`, например `local:230/example-image.raw`, `local:iso/debian-netinst.iso` или `local-lvm:vm-101-disk-0`. Используется во всех командах работы с томами.

**Thin Provisioning (Тонкое выделение)** — режим, при котором на хранилище записываются только реально используемые гостем блоки, а не весь виртуальный размер диска. Поддерживается qcow2 и всеми типами хранилищ с поддержкой снапшотов. Опасность: при переполнении хранилища все гости, использующие его тома, получают ошибки I/O.

## Основные концепции

### Типы локальных хранилищ

- **Directory**: Обычная папка (ext4/XFS). Универсальна, поддерживает все типы контента. Диски хранятся как файлы `.qcow2` или `.raw`. Снапшоты возможны только для qcow2 (внутренние или как цепочка томов).
- **LVM**: Блочные устройства. Быстрый доступ без накладных расходов на формат файла. До PVE 8.x не поддерживал снапшоты в PVE; **с PVE 9 снапшоты VM на LVM доступны через цепочку томов** (`snapshot-as-volume-chain`) — снимки данных создаются в отдельных томах и наслаиваются без блокировки работы VM.
- **LVM-Thin**: Тонкое выделение и снапшоты на уровне пула. Идеально для локальных VM. Не поддерживает Storage Replication. Подробнее о механиках — **[LVM Thin Provisioning](../Linux/FileSystems/LVM/thin-provisioning.md)**.
- **ZFS**: Рекомендуется для High Availability. Поддерживает компрессию, снапшоты и Storage Replication (репликация по расписанию через `zfs send/receive`). В PVE 9 поставляется ZFS 2.4, **с PVE 9.0 доступно расширение RAIDZ-массивов** без пересоздания пула. ZFS-тома (zvol) для VM хранятся в пуле как блочные устройства.
- **BTRFS**: Поддерживается с PVE 7.x. Альтернатива ZFS для одиночных дисков, поддерживает снапшоты и компрессию. В PVE 9.x относится к **технологическому превью** (best-effort поддержка со стороны Proxmox).

### Сетевые и общие хранилища (Shared Storage)

Позволяют выполнять **Live Migration** без перемещения данных.

- **NFS**: Простая настройка, поддержка всех типов контента. Рекомендуется использовать NFS v4.1 и выше. Снапшоты на NFS выполняются средствами qcow2 и крайне медленны на больших дисках — на сетевых хранилищах их лучше создавать при выключенной VM. Монтируется автоматически через mount-опции (`--options`).
- **SMB/CIFS**: Общие файловые ресурсы Windows/TrueNAS/Samba. Поддерживает все типы контента и снапшоты qcow2. SMB1 не поддерживается по соображениям безопасности (по умолчанию SMB3).
- **iSCSI**: Передача блочных данных. В PVE два плагина: `iscsi` (через ядро, krbd/kernel) и `iscsidirect` (через libiscsi). Для многопользовательского доступа и разбиения LUN на виртуальные диски поверх iSCSI требуется LVM. Для отказоустойчивости рекомендуется multipath.
- **FC/SAS**: Fibre Channel и SAS-хранилища обслуживаются хостом напрямую, без специального плагина PVE; поверх LUN используется LVM.
- **ZFS over iSCSI**: Тип `zfs` — блочное общее хранилище, предоставляемое по iSCSI, со снапшотами на уровне ZFS.
- **Ceph (RBD/CephFS)**: Распределенное программно-определяемое хранилище (см. ниже).
- **Proxmox Backup Server (PBS)**: Инкрементальные дедуплицированные бэкапы с шифрованием (см. **[Proxmox Backup Server](./proxmox_backup_server.md)**).

### Сводная таблица типов хранилищ (PVE 9.x)

| Тип | Плагин | Уровень | Shared | Снапшоты | Статус |
|---|---|---|---|---|---|
| ZFS (локальный) | zfspool | файл/блок | нет | да | stable |
| Directory | dir | файл | нет | да (qcow2) | stable |
| BTRFS | btrfs | файл | нет | да | tech preview |
| NFS | nfs | файл | да | да (qcow2) | stable |
| CIFS | cifs | файл | да | да (qcow2) | stable |
| Proxmox Backup | pbs | файл/блок | да | n/a | stable |
| CephFS | cephfs | файл | да | да | stable |
| LVM | lvm | блок | нет | да (PVE 9+) | stable |
| LVM-thin | lvmthin | блок | нет | да | stable |
| iSCSI (kernel/libiscsi) | iscsi, iscsidirect | блок | да | да (через LVM) | stable |
| FC/SAS | native | блок | да | да (через LVM) | stable |
| Ceph/RBD | rbd | блок | да | да | stable |
| ZFS over iSCSI | zfs | блок | да | да | stable |

> **Примечание по поддержке версий**: GlusterFS удален из поддерживаемых типов, а плагин Linstor (технологическое превью в PVE 8.2/8.3) исключен в PVE 9. Для отказоустойчивых распределенных файловых хранилищ используйте CephFS.

### Общие параметры хранилищ

Пример стандартной конфигурации (`/etc/pve/storage.cfg`) после установки:

```ini
dir: local
        path /var/lib/vz
        content iso,vztmpl,backup

lvmthin: local-lvm
        thinpool data
        vgname pve
        content rootdir,images

zfspool: local-zfs
        pool rpool/data
        sparse
        content images,rootdir
```

Ключевые общие параметры:

- **nodes**: список узлов кластера, на которых хранилище доступно (ограничение доступа).
- **content**: набор типов контента (images/rootdir/iso/vztmpl/backup/snippets/import).
- **shared**: флаг общего хранилища (см. определение выше).
- **disable**: полностью отключает хранилище.
- **prune-backups**: политика хранения резервных копий (`keep-last`, `keep-daily`, `keep-weekly`, `keep-monthly`, `keep-yearly`, `keep-hourly`).
- **format**: формат образов по умолчанию (raw/qcow2/vmdk) для файловых хранилищ.
- **preallocation**: режим предварительного выделения (off/metadata/falloc/full); для сетевых хранилищ с большими qcow2 рекомендуется `off` во избежание таймаутов.

> Не рекомендуется использовать один и тот же пул хранилища одновременно в разных кластерах PVE: операции с томами требуют эксклюзивной блокировки, которая работает только внутри одного кластера.

### Гиперконвергентный Ceph

**Ceph** объединяет локальные диски всех нод в единый отказоустойчивый пул. В PVE Ceph устанавливается и управляется непосредственно на гипервизорах (через GUI или CLI `pveceph`), превращая кластер в гиперконвергентную систему.

**Версии Ceph в PVE:**
- **PVE 9.0** (авг 2025) поставляется с **Ceph Squid (19.2.3)**.
- **PVE 9.2** (май 2026): для **новых** установок по умолчанию предлагается **Ceph Tentacle (20.2.1)**; существующие кластеры остаются на своей версии — новые ноды выравниваются под версию, уже запущенную в кластере.
- **Ресурсы жизненного цикла**: поддержка Ceph Squid заканчивается ориентировочно **19 сентября 2026**; Ceph Reef (18.x) архивирован и больше не сопровождается. PVE 8.x (ветка до EOL — август 2026) использует Quincy/Reef.
- **Порядок обновления гиперконвергентного кластера**: сначала Ceph на Squid → затем переход PVE 8→9 → затем Ceph на Tentacle (после PVE 9.1). Специфика обновления кластера с Ceph — **[Обновление систем Proxmox](./proxmox_updates.md)**.

> **Внимание**: следите за сроками поддержки версий Ceph в используемом PVE. Продление жизни кластера за пределами EOL версии Ceph небезопасно — обновление Ceph практически никогда не умещается в одно окно обслуживания.

**Компоненты:**
- **MON (Monitors)**: Хранят карту состояния кластера (Cluster Map). Минимум 3 для кворума; больше 3 обычно не нужно.
- **MGR (Managers)**: Мониторинг, метрики, telemetry, PG-автоскейлинг. Один активный, остальные standby.
- **OSD (Object Storage Daemon)**: Управляет физическим диском (один OSD на диск). Репликация и распределение данных идут между OSD. Начиная с Ceph Luminous OSD использует хранилище **BlueStore** (по умолчанию), для которого можно выделять отдельные устройства DB/WAL.
- **MDS (Metadata Server)**: Требуется для CephFS. Активный + standby; можно несколько активных (multi-MDS) при высокой нагрузке на клиенты.
- **RBD (RADOS Block Device)**: Блочное хранилище для дисков VM.
- **CephFS**: Файловая система для ISO, шаблонов и бэкапов (требует MDS), POSIX-совместимая и распределенная между MDS.

**Архитектура данных:**
- **Pools (пулы)** — логические группы объектов. Пулу назначаются число реплик (size, по умолчанию 3), минимальное число реплик (min_size, по умолчанию 2) и число Placement Groups (PG). Не устанавливайте min_size=1: при деградации реплик это ведет к потере данных.
- **PG (Placement Groups)** — группы объектов, единица распределения и восстановления. По умолчанию PVE создает 128 PG на пул. Рекомендуется включать **PG Autoscaler** (`ceph mgr module enable pg_autoscaler`, режимы `warn`/`on`/`off`).
- **CRUSH** — алгоритм распределения объектов по OSD без центрального индекса. Пул можно ограничить классом дисков (hdd/ssd/nvme) через правила CRUSH и device classes.
- **Erasure Coding (EC)** — альтернатива репликации: данные разбиваются на k фрагментов + m контрольных; допускает потерю m OSD. Больше полезного места, ниже производительность. Для RBD обязателен отдельный реплицированный metadata-пул.

**Рекомендации по железу и сети (для гиперконвергентного кластера):**
- Минимум 3 одинаковых сервера; минимум 12 OSD (по 4 на ноду), равномерно распределенных.
- **Сеть**: выделенная полоса не менее 10 Гбит/с только для Ceph. Для высокопроизводительных конфигураций — три отдельных сети: внутренняя кластерная (25+ Гбит/с), публичная (10+ Гбит/с) и для latency-чувствительного corosync (1 Гбит/с). Трафик ребалансировки может «съедать» полосу и ломать кворум кластера при общих сетях.
- **Память**: OSD требует по умолчанию 4 ГиБ, рекомендовано 8 ГиБ на OSD. Оставляйте запас на recovery/backfill.
- **CPU**: минимум 1 ядро на каждый сервис Ceph; NVMe-OSD может утилизировать 4–6 потоков CPU.
- **Диски**: избегайте RAID-контроллеров — используйте HBA (host bus adapter), Ceph сам управляет избыточностью. В малых кластерах предпочтительны SSD для быстрого восстановления.
- **Firewall**: при включенном межсетевом экране откройте порты Ceph (проще всего — макрос firewall).

**FastEC (Ceph Tentacle)**: новый путь I/O для EC-пулов (`allow_ec_optimizations`), добавляющий частичные чтения/записи и существенно улучшающий мелкий случайный I/O. Требует tentacle-релиз OSD, профиль EC `reed_sol_van` и stripe unit кратный 4 КБ. Переключатель односторонний — включив, откатить без пересоздания пула нельзя.

## Практические сценарии

### Управление хранилищами через CLI (pvesm)

**Просмотр статуса:**
```bash
pvesm status
# → Name             Type     Status  Total   Used   Available   %
# → local            dir      active  102000000 5000000 97000000  4.90%
# → local-lvm        lvmthin  active  ...
```

**Список содержимого хранилища:**
```bash
pvesm list local
pvesm list local --content iso
```

**Добавление NFS-хранилища:**
```bash
pvesm add nfs my-nfs --server 10.0.0.50 --export /mnt/pve --content images,iso
# → update storage: 'my-nfs'
```

**Добавление SMB/CIFS-хранилища:**
```bash
pvesm add cifs my-smb --server 10.0.0.60 --share /backup --content backup,iso \
  --username backup --password 'secret' --smbversion 3.0
```

**Подключение Proxmox Backup Server:**
```bash
pvesm add pbs backup-storage --server 10.0.0.70 --datastore main \
  --username backup@pbs --password 'secret' --fingerprint AA:BB:...
```

**Изменение и удаление конфигурации хранилища:**
```bash
pvesm set my-nfs --content backup,iso
pvesm remove my-nfs
```

**Сканирование доступных ресурсов:**
```bash
pvesm scan nfs 10.0.0.50
pvesm scan cifs 10.0.0.60 --username admin
pvesm scan iscsi 10.0.0.80
pvesm scan pbs 10.0.0.70 backup@pbs --password 'secret'
```

**Работа с томами:**
```bash
pvesm alloc local-lvm 101 vm-101-disk-1 32G
pvesm free local-thin:vm-101-disk-0
# → successfully removed volume
pvesm path local:iso/debian-netinst.iso
# → /var/lib/vz/template/iso/debian-netinst.iso
```

**Управление хранением бэкапов (prune):**
```bash
pvesm prune-backups backup-store --vmid 101 --keep-last 7 --keep-weekly 4
```

**Импорт существующего диска в VM:**
```bash
qm importdisk 101 /tmp/image.qcow2 local-lvm
# → import: 100% done
# → Successfully imported disk as 'unused0'
```

### Развертывание и настройка Ceph через CLI (pveceph)

**Установка пакетов Ceph** (на каждой ноде; настраивает apt-репозиторий `ceph.sources`):
```bash
pveceph install
```

**Начальная конфигурация** (один раз на одной ноде; создает `/etc/pve/ceph.conf`, симлинк `/etc/ceph/ceph.conf`):
```bash
pveceph init --network 10.10.10.0/24
```

**Мониторы и менеджеры:**
```bash
pveceph mon create
pveceph mgr create
# Минимум 3 MON для кворума; MGR рекомендуется устанавливать на MON-нодах
```

**Статус кластера:**
```bash
pveceph status
# → health: HEALTH_OK
# → osds: 6 up, 6 in
```

**Создание OSD** (по одному на диск; по умолчанию BlueStore):
```bash
pveceph osd create /dev/nvme0n1
# → create OSD on /dev/nvme0n1 (bluestore)
```

**OSD с отдельными устройствами DB/WAL** (для производительности NVMe-кластеров):
```bash
pveceph osd create /dev/sda -db_dev /dev/nvme0n1 -wal_dev /dev/nvme0n1 \
  -db_size 20G -wal_size 2G
```

**Подготовка бывшего в использовании диска** (полное уничтожение данных!):
```bash
ceph-volume lvm zap /dev/sdX --destroy
```

**Безопасное удаление OSD:**
```bash
ceph osd out <id>                          # исключить из распределения данных
ceph osd ok-to-stop <id>                   # проверить, что остановка безопасна
pveceph stop --service osd.<id>
pveceph osd destroy <id> --cleanup         # очистка partition table для переиспользования
```

**Создание пула** (по умолчанию: 128 PG, size=3, min_size=2):
```bash
pveceph pool create <pool-name> --add_storages
# → создаст пул и автоматически зарегистрирует его как RBD-хранилище в PVE
```

**Erasure Coded пул** (k=2, m=1 → size=3, min_size=2; создаются пулы `<name>-data` и `<name>-metadata`):
```bash
pveceph pool create <pool-name> --erasure-coding k=2,m=1
```

**Добавление существующего EC-пула как хранилища:**
```bash
pvesm add rbd ec-storage --pool <replicated-pool> --data-pool <ec-pool>
```

**Удаление пула:**
```bash
pveceph pool destroy <name>
```

**Правило CRUSH по классу дисков (nvme/ssd/hdd):**
```bash
ceph osd crush rule create-replicated nvme-rule default host nvme
ceph osd pool set <pool-name> crush_rule nvme-rule
```

**Метаданные и CephFS:**
```bash
pveceph mds create
pveceph fs create --pg_num 128 --add-storage
# → cephfs (data: cephfs_data / 128 PG; metadata: cephfs_metadata / 32 PG)
```

**Конфигурация через MON DB** (прецеденция выше локального ceph.conf):
```bash
ceph config set osd osd_memory_target 8G
ceph config dump
ceph config get mon osd_pool_default_erasure_code_profile
```

**PG Autoscaler:**
```bash
ceph mgr module enable pg_autoscaler
ceph osd pool set <pool-name> pg_autoscale_mode warn|on|off
```

### Подключение внешнего Ceph-кластера

Для Ceph-кластера, не управляемого локальным PVE, при добавлении RBD-хранилища укажите адреса мониторов и keyring:

```bash
pvesm add rbd external-ceph --monhost 10.0.0.1,10.0.0.2,10.0.0.3 \
  --pool <pool-name> --keyring /etc/pve/priv/ceph/external-ceph.keyring
```

Keyring для внешнего кластера размещается в `/etc/pve/priv/ceph/<storage_id>.keyring` (для гиперконвергентного кластера это делается автоматически).

## Диагностика и обслуживание

### Проблемы с производительностью (IO Delay)

Высокий "IO Delay" в GUI указывает на ожидание узлом дисковых операций.
1. Проверьте статус ZFS/Ceph: `zpool status` или `pveceph status` (ищите `HEALTH_*`).
2. Проверьте нагрузку на диски: `iostat -x 1`.
3. Убедитесь, что LVM-Thin пул не заполнен на 100% (это блокирует запись всех VM).
4. Для Ceph: `ceph osd df tree` — проверьте перекос загрузки между OSD и уровень заполнения относительно `nearfull_ratio` (по умолчанию 85%).

### Переполнение хранилища

- Тонкое выделение (qcow2, LVM-Thin, Ceph RBD) позволяет создавать диски больше физического объема — при исчерпании места **все гости** на этом хранилище получают ошибки I/O, что может привести к повреждению файловых систем.
- При заполнении Ceph-пулов до `nearfull`/`full` блокируется запись в кластер в целом. Контролируйте заполнение и оставляйте запас для восстановления (recovery/backfill).

### Мониторинг состояния Ceph

```bash
ceph -s                       # общий статус и health
ceph versions                 # версии демонов
ceph osd df tree              # заполнение и распределение OSD
ceph osd tree                 # топология и классы дисков
ceph config dump              # конфигурация в MON DB
```

Совместно с общесистемными метриками (`ceph-exporter`, Prometheus) — см. **[Администрирование Ceph — Обзор](../Kubernetes/Storage/Ceph/Administration/index.md)**.

### Восстановление после сбоя диска

1. Выполните `ceph osd out <id>` — данные начнут перераспределяться на здоровые OSD.
2. Дождитесь завершения ребалансировки (в малых кластерах это может занять длительное время — риск повторного отказа диска в период восстановления).
3. Замените диск, при необходимости затрите его `ceph-volume lvm zap /dev/sdX --destroy` и создайте новый OSD `pveceph osd create /dev/sdX`.

## Дополнительная информация

### Связанные темы

- [Proxmox VE — Обзор и базовые концепции](./proxmox_overview.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)
