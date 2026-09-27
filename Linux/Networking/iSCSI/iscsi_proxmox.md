# iSCSI + Proxmox VE: Интеграция сетевого хранилища

Руководство по настройке и использованию iSCSI в Proxmox VE: подключение LUN, создание Storage, интеграция с виртуальными машинами и контейнерами.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Proxmox VE (PVE)** | Открытая серверная платформа для виртуализации на базе KVM/QEMU и LXC. Поддерживает various storage backends, включая iSCSI. |
| **Storage Plugin** | Модуль PVE для работы с конкретным типом хранилища. Для iSCSI доступны: `iscsi`, `iscsidirect`, `zfs over iSCSI`. |
| **Datastore** | Логическое хранилище в PVE, определяемое типом, подключением и параметрами. Видно как `/dev/pve/datastore`. |
| **LVM over iSCSI** | Настройка, при которой iSCSI LUN используется как Physical Volume (PV) для LVM-группы в PVE. |
| **ZFS over iSCSI** | Настройка, при которой ZFS-пул создаётся на удалённом массиве и экспортируется через iSCSI. |
| **thin pool** | LVM thin provisioning pool для динамического выделения дискового пространства. |
| **Replication** | Механизм синхронизации данных между узлами PVE через ZFS send/receive. |

## Варианты интеграции iSCSI с PVE

| Storage Plugin | Описание | Применение | Ограничения |
| :--- | :--- | :--- | :--- |
| **iscsi** | Базовый iSCSI, LUN как блочное устройство | Raw LUN для VM, shared storage | Без snap/backup на уровне PVE |
| **iscsidirect** | iSCSI без промежуточного LVM | Прямой доступ к LUN | Ограничения на количество VM |
| **LVM over iSCSI** | iSCSI LUN → PV → VG → LV | Полная интеграция с LVM | Требует LVM конфигурации |
| **LVM thin over iSCSI** | iSCSI LUN → thin pool | Thin provisioning, снапшоты | Требует LVM thin |
| **ZFS over iSCSI** | ZFS на массиве → iSCSI | ZFS features, снапшоты, replication | Требует ZFS на array |

### Когда использовать каждый вариант

| Сценарий | Рекомендуемый plugin | Почему |
| :--- | :--- | :--- |
| **Raw LUN для важной БД** | `iscsi` | Прямой доступ, нет overhead |
| **Общее хранилище для VM** | `LVM over iSCSI` | Снапшоты, тонкое provisionирование |
| **Быстрые снапшоты** | `LVM thin over iSCSI` | Thin provisioning, мгновенные снапшоты |
| **ZFS features на SAN** | `ZFS over iSCSI` | Checksums, compression, dedup |
| **Бэкап/Replication** | `ZFS over iSCSI` | Native replication в PVE |

## Практические сценарии

### Сценарий 1: LVM over iSCSI (рекомендуется)

#### Шаг 1: Подключение iSCSI на хосте PVE

```bash
# Установка open-iscsi
sudo apt install open-iscsi -y

# Включение и запуск iscsid
sudo systemctl enable --now iscsid

# Discovery таргетов
sudo iscsiadm -m discovery -t sendtargets -p 192.168.1.200

# Login ко всем таргетам
sudo iscsiadm -m node --loginall=all

# Проверка подключённых LUN
sudo iscsiadm -m session -P 3
ls /dev/sd*

# Настройка автозапуска
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.startup -v automatic
```

#### Шаг 2: Настройка Multipath (рекомендуется)

```bash
# Установка
sudo apt install multipath-tools -y

# Конфигурация /etc/multipath.conf
cat > /etc/multipath.conf << 'EOF'
defaults {
    polling_interval    30
    path_grouping_policy  multibus
    uid_attribute       ID_SERIAL
    path_selector       "round-robin 0"
    failback            immediate
    no_path_retry       5
    user_friendly_names yes
}

blacklist {
    devnode "^(ram|raw|loop|fd|md|dm-|sr|scd|st)[0-9]*"
    devnode "^(sd[a-b][0-9]*)"
}
EOF

# Запуск multipathd
sudo systemctl enable --now multipathd

# Проверка
sudo multipath -ll
```

#### Шаг 3: Создание LVM на iSCSI LUN

```bash
# Определение устройства (multipath или прямое)
lsblk
# → mpatha   8:0    0   100G  0  dm-0

# Создание PV
sudo pvcreate /dev/mapper/mpatha

# Создание VG
sudo vgcreate vg_pve_iscsi /dev/mapper/mpatha

# Создание thin pool (рекомендуется)
sudo lvcreate -L 10G -T vg_pve_iscsi/thin_pool
sudo lvcreate -V 90G -T vg_pve_iscsi/thin_pool -n data

# Проверка
sudo lvs
# → data     vg_pve_iscsi  twi-aotz--  90.00g
# → thin_pool vg_pve_iscsi twi-aotz-- 100.00g
```

#### Шаг 4: Добавление Storage в PVE

Через Web UI:
```
Datacenter → Storage → Add → LVM
  - Name: iscsi-lvm
  - Storage type: LVM
  - VG name: vg_pve_iscsi
  - Base storage: (none)
  - Content: Images, RootDir
```

Или через CLI:

```bash
pvesm add lvm iscsi-lvm \
  --vgname vg_pve_iscsi \
  --content images,rootdir
```

#### Шаг 5: Использование

```bash
# Создание VM на iSCSI storage
qm create 100 \
  --name "web-server" \
  --memory 4096 \
  --cores 2 \
  --scsihw virtio-scsi-single \
  --scsi0 iscsi-lvm:100 \
  --net0 virtio,bridge=vmbr0

# Создание диска для контейнера
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname container1 \
  --memory 2048 \
  --rootfs iscsi-lvm:8

# Резервное копирование
vzdump 100 --storage local
```

### Сценарий 2: iSCSI Direct (прямой доступ)

```bash
# Добавление iSCSI storage без LVM
pvesm add iscsi iscsi-direct \
  --portal 192.168.1.200 \
  --target iqn.2026-07.com.example:storage.target01

# Просмотр доступных LUN
pvesm status

# Использование (прямой LUN)
qm set 100 --scsi0 iscsi-direct:0
```

### Сценарий 3: ZFS over iSCSI

Требует ZFS-массив на стороне storage-сервера:

```bash
# На storage-сервере (TrueNAS, Proxmox как storage):
# 1. Создание ZFS-пула
zpool create tank mirror /dev/sda /dev/sdb

# 2. Создание ZFS volume для iSCSI
zfs create -V 100G tank/iscsi-lun

# 3. Экспорт через iSCSI target (LIO)

# На Proxmox хосте:
# 4. Подключение iSCSI LUN
sudo iscsiadm -m discovery -t sendtargets -p 192.168.1.200
sudo iscsiadm -m node --loginall=all

# 5. Создание ZFS pool поверх iSCSI
sudo zpool create zfs-iscsi mirror /dev/sdX /dev/sdY

# 6. Добавление в PVE
pvesm add zfspool iscsi-zfs \
  --pool zfs-iscsi \
  --content images,rootdir \
  --sparse true
```

### Сценарий 4: Настройка CHAP-аутентификации

```bash
# На хосте PVE: настройка CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.username -v pve-user
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.password -v secret123

# Добавление в PVE (с CHAP)
pvesm add iscsi iscsi-secure \
  --portal 192.168.1.200 \
  --target iqn.2026-07.com.example:storage.target01 \
  --username pve-user \
  --password secret123
```

### Сценарий 5: Миграция VM на iSCSI

```bash
# Копирование VM на iSCSI storage
qm disk move 100 0 iscsi-lvm

# Или через Web UI:
# VM → Hardware → Hard Disk → Move → iscsi-lvm

# Проверка
qm config 100
# → scsi0: iscsi-lvm:vm-100-disk-0,size=32G
```

## Диагностика проблем

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Storage не отображается в PVE | iSCSI не подключён или LVM не создан | `pvesm status`, `sudo iscsiadm -m session`, `sudo lvs` |
| `no such logical volume` | LV не существует или имя изменилось | `sudo lvs`, `pvesm status` |
| VM не запускается на iSCSI | Недостаточно space или permissions | Проверить `df -h`, права на `/dev/pve/*` |
| Медленная работа VM | Нет multipath, нет Jumbo Frames | `multipath -ll`, `ip link show eth1` (MTU=9000) |
| Снапшоты не работают | Используется `iscsi` plugin вместо LVM thin | Переключиться на `LVM thin over iSCSI` |
| `connection refused` на portal | Target недоступен или ACL не настроен | `nc -zv <IP> 3260`, проверить ACL на target |
| Высокая latency | Проблемы с сетью или multipath | `ping -M do -s 8972 <IP>`, `iostat -xmt 5 /dev/sdX` |

## Мониторинг iSCSI в PVE

```bash
# Статус storage
pvesm status

# Просмотр LVM
sudo lvs
sudo pvs
sudo vgs

# Логи PVE
journalctl -u pvedaemon -f
journalctl -u pve-cluster -f

# Просмотр iSCSI сессий
sudo iscsiadm -m session -P 3

# Проверка multipath
sudo multipath -ll
```

## Рекомендации

1. **Используйте Multipath:** Обязательно для production (2+ сетевых пути)
2. **Jumbo Frames:** Включите MTU 9000 на всей iSCSI-линии
3. **LVM thin:** Для гибкого управления пространством и снапшотами
4. **CHAP:** Включите аутентификацию для защиты данных
5. **Мониторинг:** Настройте алерты на loss of path, I/O errors
6. **Бэкап:** Используйте `vzdump` с appropriate storage backend
7. **Тестирование failover:** Регулярно проверяйте поведение при потере пути

## См. также

- **[Proxmox: Storage](../../Proxmox/proxmox_storage.md)** — общая информация о storage в PVE
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — серверная часть
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость путей
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подключение к iSCSI
- **[SCSI-3 Persistent Reservations](./iscsi_persistent_reservations.md)** — для кластерных VM
