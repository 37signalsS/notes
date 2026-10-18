# Proxmox Virtual Environment (PVE) — Обзор и базовые концепции

**Актуально для:** Proxmox VE 9.2 (ветка 9.x; Debian 13.5 «Trixie», ядро Linux 7.0, QEMU 11.0, LXC 7.0, ZFS 2.4; PVE 8.x — EOL 31.08.2026)

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом корпоративного уровня на базе Debian GNU/Linux. Объединяет гипервизор KVM/QEMU, системные контейнеры LXC, хранилища (LVM-Thin, ZFS, Ceph, NFS/iSCSI), SDN и единую модель управления (веб-интерфейс, REST API, CLI). Работает как одиночный узел (node) или как кластер с общей конфигурацией и HA. С PVE 9.2 официально поддерживаются также платформы arm64 (NVIDIA Grace / Vera), кроме x86-64.

**Node (Узел)** — физический или виртуальный сервер, на котором установлена PVE. Каждый узел имеет уникальное имя (hostname), задаваемое при установке.

**VMID (Virtual Machine ID)** — числовой идентификатор гостя (VM или LXC) в кластере: уникален в рамках всего кластера, диапазон 100–999999999. Используется во всех командах (`qm`, `pct`, `vzdump`, API).

**Hyper-Converged Infrastructure (HCI, Гиперконвергентная инфраструктура)** — архитектура, в которой вычисления, хранилище и сеть работают на одних и тех же узлах. В Proxmox реализуется связкой PVE + Ceph + SDN.

**QEMU (Quick EMUlator)** — эмулятор, обеспечивающий виртуализацию оборудования для гостевых ОС. В PVE работает в паре с KVM (в PVE 9.2 — QEMU 11.0).

**KVM (Kernel-based Virtual Machine)** — модуль ядра Linux, предоставляющий аппаратную виртуализацию. В PVE — основной гипервизор для ВМ с полной изоляцией.

**LXC (Linux Containers)** — системные контейнеры на уровне ядра хоста (namespaces, cgroups), без эмуляции оборудования. В PVE 9.2 — LXC 7.0. Легковеснее VM, но разделяют ядро хоста.

**Cloud-Init** — автоматизация первичной настройки гостевой ОС (пользователи, SSH-ключи, сеть, расширение диска) при первом запуске из шаблона.

**Template (Шаблон)** — образ VM или контейнера с предустановленной ОС и конфигурацией для многократного клонирования.

**pmxcfs (Proxmox Cluster File System)** — кластерная файловая система (FUSE поверх Corosync), синхронизирующая конфигурацию `/etc/pve/` между узлами в реальном времени. Для узла выглядит как обычная директория.

**vzdump** — встроенный инструмент резервного копирования VM и LXC (snapshot mode, сжатие zstd/lzo, шифрование, вывод на PBS или локальное хранилище).

**RBAC (Role-Based Access Control)** — ролевая модель доступа: права назначаются пользователям и группам на пулы, узлы, хранилища, отдельные гости.

**Subscription (Подписка)** — коммерческая лицензия Proxmox: даёт доступ к enterprise-репозиторию (рекомендуется для production) и поддержке. Без подписки используется no-subscription-репозиторий — конфигурация описана в [Обновлении систем](./proxmox_updates.md#настройка-репозиториев).

## Архитектура и взаимодействие компонентов

PVE — многоуровневая система:

- **Уровень ядра**: KVM (аппаратная виртуализация ВМ), Namespaces/Cgroups (изоляция LXC), сетевой стек Linux (мосты, VLAN, bonding, nftables).
- **Уровень управления**: `pvedaemon` — основной демон API (запуск/остановка гостей, задачи); `pveproxy` — HTTPS-прокси веб-интерфейса и REST API (порт 8006); `pvestatd` — сбор статистики узла; `pvescheduler` — периодические задания (бэкапы, репликация ZFS); `pve-ha-manager` (`pve-ha-crm` + `pve-ha-lrm`) — HA и failover; `pve-firewall` — межсетевой экран хоста и гостей; `spiceproxy` — SPICE-прокси для графических консолей; `qmeventd` — обработчик событий QEMU (guest agent, freeze); `watchdog-mux` — мультиплексор аппаратного/программного watchdog.
- **Кластерный уровень**: Corosync (обмен сообщениями, кворум; транспорт knet), `pve-cluster` (менеджер pmxcfs), `pvecm` — CLI кластера.
- **Хранилище**: LVM-Thin, ZFS, Ceph, NFS/CIFS/iSCSI и др. — конфигурация в `/etc/pve/storage.cfg` (см. [Хранилища](./proxmox_storage.md)).
- **Сеть**: Linux Bridge, OVS, SDN (VNet/Zones/IPAM/Fabrics) — см. [Сети](./proxmox_networking.md).

Взаимодействие: REST API (HTTPS :8006) → `pveproxy` → `pvedaemon`; CLI (`qm`, `pct`, `pvesh`, `pvenode`, `pvecm`, `pvesm`, `pveum`, `vzdump`, `pveam`) вызывает те же API-пути. Все изменения конфигурации пишутся в pmxcfs (`/etc/pve/`) и видны всем узлам кластера.

### Ключевые директории

| Путь | Назначение |
|---|---|
| `/etc/pve/` | pmxcfs: общая конфигурация кластера (видна как каталог) |
| `/etc/pve/qemu-server/<VMID>.conf` | конфигурация VM |
| `/etc/pve/lxc/<CTID>.conf` | конфигурация LXC |
| `/etc/pve/nodes/<node>/` | узловой контекст (`pve-ssl.pem`, локальные ресурсы) |
| `/etc/pve/local` | симлинк на `/etc/pve/nodes/<имя-этого-узла>` |
| `/etc/pve/storage.cfg` | реестр хранилищ |
| `/etc/pve/corosync.conf` | конфигурация Corosync |
| `/etc/pve/priv/` | приватные ключи (CA, SSH, кластерные секреты) |
| `/etc/pve/jobs.cfg` | периодические задания (vzdump и др., исполняет `pvescheduler`) |
| `/var/lib/vz/` | данные хранилища `local` по умолчанию (ISO, шаблоны, backup) |
| `/var/lib/qemu-server/` | дополнительные файлы VM (qcow2 и т.п. на directory-хранилищах) |
| `/var/lib/pve/` | служебные данные (например, subvol BTRFS `local-btrfs`) |

> `/etc/pve` — не обычный каталог: это FUSE-монтирование pmxcfs. Прямое редактирование «как файловой системы» без штатных инструментов (`pvesh`, `qm`, `pct`, `pvecm`, `pveum`) небезопасно; пароли и секреты не должны попадать в `/etc/pve` (только `/etc/pve/priv/`).

### Карта CLI-инструментов

| Инструмент | Назначение |
|---|---|
| `qm` | управление ВМ (create/set/start/stop/migrate/...) |
| `pct` | управление LXC-контейнерами |
| `pvesh` | прямой вызов REST API из CLI |
| `pvenode` | операции на узле (сертификаты, bulk-действия, задачи) |
| `pvecm` | кластер (create/add/status/updatecerts/nodes) |
| `pvesm` | хранилища (status/add/list) |
| `pveum` | пользователи, группы, роли, ACL, API-токены |
| `vzdump` | резервное копирование гостей |
| `pveam` | менеджер образов (шаблоны LXC, cloud-образы) |
| `ha-manager` | управление HA-ресурсами и состоянием CRM |

`qm list` и `pct list` работают только для **локального** узла; для обзора всего кластера — `pvesh get /cluster/resources`.

## Системные требования

Официальные минимумы (только evaluation, не production):

- **CPU**: 64-бит (x86-64 Intel/AMD или arm64); для x86 — поддержка VT-x/AMD-V (проверка: `egrep -c '(vmx|svm)' /proc/cpuinfo`).
- **RAM**: 1 ГБ + память под гостей.
- **Диск**: 8 ГБ+ (для удобства — 32 ГБ+).
- **NIC**: 1 сетевой интерфейс.

Рекомендации для production:

- **CPU**: современный x86-64 с VT-x/AMD-V; для PCI(e)-passthrough — IOMMU (VT-d / AMD-Vi), включённый в BIOS/UEFI.
- **RAM**: минимум 2 ГБ на ОС и сервисы PVE + выделенная память гостей; для ZFS и Ceph — примерно +1 ГБ на каждый ТиБ используемого хранилища.
- **Хранилище**: быстрое и избыточное; для ОС — hardware RAID с BBU или non-RAID + ZFS (SSD для ZIL/SLOG по необходимости). **ZFS и Ceph несовместимы с hardware RAID-контроллерами** в режиме HBA/RAID — для них нужны JBOD/HBA или диски, подключённые напрямую. SSD с PLP (защита от потери питания) предпочтительнее consumer-SSD.
- **Сеть**: избыточные (несколько) Gbit NIC; отдельные сети для управления, Ceph/репликации и гостевого трафика — см. [Сети](./proxmox_networking.md).
- **Out-of-band**: IPMI/iDRAC/iKVM на каждом узле (HA, обновления, аварийный доступ без pveproxy).

Для кластерных сценариев и HA требования дополняются правилами Corosync/кворума — см. [Кластер](./proxmox_cluster.md#требования-и-правила-создания-кластера).

## Установка и базовая настройка

### Инсталлятор

ISO-образ PVE содержит полный Debian + ядро с KVM/LXC + утилиты + веб-интерфейс. Типовой ход установки: лицензия → диск/ФС → часовой пояс (важен для логов и cron) → пароль root + email → сеть (IP, bridge `vmbr0`) → перезагрузка.

После установки — доступ к GUI: `https://<IP>:8006`, вход `root@pam`. Далее: проверить hostname, часовой пояс, сеть, firewall и **репозитории** (см. [Обновления](./proxmox_updates.md#настройка-репозиториев)) — без корректных репозиториев безопасные обновления невозможны.

### Варианты ФС и разбиения диска

По умолчанию инсталлятор создаёт **LVM-Thin** (тонкое выделение + мгновенные снимки) поверх ext4. Альтернативы в Advanced Options:

- **ZFS**: компрессия, снапшоты, storage replication; рекомендуется для HA без shared storage. В PVE 9.2 — ZFS 2.4.
- **ext4/XFS (Directory)**: классика; снапшоты VM — только через qcow2 или volume chains (PVE 9, tech preview).
- **BTRFS**: с PVE 7.x; в 9.x — **технологическое превью** (best-effort); RAID 5/6 — experimental и опасен.

Типовая схема LVM (ext4/XFS):

```text
/dev/sda
├── /dev/sda1  BIOS Boot (bios_grub) или EFI System Partition (UEFI)
├── /dev/sda2  pve-root   — корневая ФС
├── /dev/sda3  pve-swap   — подкачка
└── /dev/sda4  pve-data   — LVM-Thin пул для VM/LXC
```

Инсталлятор создаёт VG `pve` с LV `root`, `data`, `swap` (для ext4/XFS). Размеры — опции Advanced Options / параметры загрузки:

| Опция | Семантика (по умолчанию) |
|---|---|
| `hdsize` | общий объём диска под PVE (остальное можно отрезать под другой PV/VG) |
| `swapsize` | размер swap = объём RAM; min 4 ГБ, max 8 ГБ; не более `hdsize/8`; `0` — без swap |
| `maxroot` | макс. размер root: при месте > 48 ГиБ — `hdsize/4` (cap 96 ГиБ); при < 48 ГиБ — не менее `hdsize/2` |
| `maxvz` | макс. размер data-тома |
| `minfree` | свободное место в VG: при диске > 128 ГБ — 16 ГБ, иначе `hdsize/8` (для lvmthin снапшоты VG не критичны, но место пригодится для расширений) |

Фактический размер data: `datasize = hdsize - rootsize - swapsize - minfree` (не больше `maxvz`). Для LVM-Thin пул `data` создаётся только если `datasize > 4 ГБ`; `maxvz=0` — data-том не создаётся.

Для ZFS/BTRFS своя опция `hdsize` и параметры (ashift, compress и др.) — см. официальный Installer Guide; swap по умолчанию не создаётся (резервируется неразмеченное место или создаётся zvol/swapfile после установки).

Проверка после установки:

```bash
pvs && lvs
# → PV /dev/sda4   VG pve   lvm2 ...
# → LV pve-data   VG pve   ...  thin pool

pvesm status
pvecm status          # одиночный узел: корректно, кворум не нужен
```

## Основные концепции

### Виртуальные машины (KVM)

Полная аппаратная изоляция (KVM + QEMU 11.0). Подробнее: [KVM overview](../Linux/Virtualization/kvm/overview.md).

- **VirtIO**: паравиртуализированные драйверы дисков/сети; для Windows — ISO `virtio-win.iso` из репозитория PVE. Рекомендуемый тип машины — `q35` (не `i440fx`).
- **QEMU Guest Agent**: внутри гостя; нужен для корректного бэкапа (fs-freeze), graceful shutdown, сбора IP.
- **Windows 11/Server 2025**: TPM 2.0 + UEFI (OVMF); для 24H2+/Server 2025 в PVE 9.2 — загрузка UEFI-сертификатов 2023. Краткий чек-лист ниже; полный cloud/sysprep-процесс — [Шаблоны и Cloud-Init](./proxmox_vm_templates.md).

Базовые операции:

```bash
qm create 100 --name test-vm --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0
qm set 100 --scsi0 local-lvm:32,discard=on
qm start 100
qm status 100
# → status: running
qm terminal 100      # serial-консоль
qm stop 100          # жёсткая остановка (предпочтительнее для гостя — shutdown)
qm destroy 100
```

### Системные контейнеры (LXC)

Легковесная виртуализация на ядре хоста (LXC 7.0). Подробнее: [LXC](../Linux/Virtualization/lxc_overview.md), [LXC Advanced](./proxmox_lxc_advanced.md).

- **Unprivileged**: маппинг UID/GID (user namespaces) — по умолчанию в PVE 8.x/9.x; безопаснее privileged.
- **Nesting**: для Docker/вложенных LXC внутри контейнера.
- **Device passthrough**: GPU, USB.
- **Сеть**: полноценный IP в сети хоста (veth + bridge), в отличие от прикладных контейнеров Docker.

```bash
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
pct create 100 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname test-lxc --memory 1024 --cores 2 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1
pct start 100
pct status 100
# → status: running
pct enter 100
pct exec 100 -- systemctl status ssh
pct stop 100
pct destroy 100
```

### Шаблоны и клонирование

- **Full Clone**: полная независимая копия.
- **Linked Clone**: диск шаблона — read-only база; изменения — в новый слой. Экономит место, зависит от родителя.
- **LVM-Thin**: клоны копируют нужные блоки, поэтому удаление/изменение тома шаблона безопаснее, чем на «грубом» LVM (при наличии ссылок).
- **Шаблоны LXC**: `pveam` / встроенный репозиторий образов.
- **Шаблоны VM + Cloud-Init**: полное пошаговое руководство (Generic Template, импорт cloudimg, `qm template`, sysprep для Windows) — [Шаблоны ВМ и Cloud-Init](./proxmox_vm_templates.md). Краткий каркас:

```bash
qm create 9000 --name u-template --memory 2048 --net0 virtio,bridge=vmbr0 \
  --serial0 socket --vga serial0
qm disk import 9000 server-cloudimg-amd64.img local-lvm --format qcow2
qm set 9000 --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-9000-disk-0
qm set 9000 --ide2 local-lvm:cloudinit
qm set 9000 --boot order=scsi0
qm template 9000
```

### Программно-определяемые сети (SDN)

В PVE 9.x SDN встроен: VNet, Zones (Simple/VLAN/QinQ/VXLAN/EVPN), IPAM (встроенный, Netbox, phpIPAM), Fabrics (в PVE 9.2 — WireGuard, BGP, route maps/prefix lists). Подробнее: [Сетевые технологии](./proxmox_networking.md), [Обзор SDN](../Networking/Concepts/sdn/sdn_overview.md).

### Управление ресурсами и правами {#управление-ресурсами-и-правами}

- **Resource Pools**: логические группы VM/LXC/хранилищ для делегирования (например, команде разработки).
- **Tags**: цветовые метки для фильтрации.
- **RBAC**: роли (`PVEVMAdmin`, `PVEDatastoreUser`, …), назначение через ACL на пул/узел/корень (`/`).

```bash
pveum groupadd developers --comment "Development team"
pveum useradd john@pam --group developers --email john@example.com
pveum aclmod /pool/DevPool --user john@pam --role PVEDatastoreUser
pveum acllist /pool/DevPool
```

Для автоматизации предпочтительнее **API-токены** (`pveum user token add`) без интерактивного пароля — создание и права: [REST API](./proxmox_rest_api.md), [Ansible](./proxmox_ansible.md), [Security](./proxmox_security.md). Роли/ACL по умолчанию и hardening — в [Безопасности](./proxmox_security.md).

## Практические сценарии

### Начальная настройка узла (checklist)

После установки и выбора репозиториев ([updates](./proxmox_updates.md)):

```bash
# 1. Обновления (после настройки no-subscription/enterprise)
apt update && apt dist-upgrade -y

# 2. Время (критично для кворума, TLS, логов)
timedatectl status
# при необходимости: apt install chrony && systemctl enable --now chrony

# 3. Базовая проверка сервисов
systemctl status pve-cluster pvedaemon pveproxy pvestatd
pvecm status
pvesm status

# 4. Сеть: убедиться, что mgmt-доступ и bridge корректны
ip -br addr && ip route

# 5. Firewall хоста (штатный pve-firewall) — включать осознанно:
#    Datacenter → Firewall или CLI; правила — в proxmox_firewall_advanced.md
pve-firewall options
```

Не оставляйте production без мониторинга и OOB-доступа. Полезные глубинные статьи: [Security](./proxmox_security.md), [Monitoring](./proxmox_monitoring.md), [Firewall](./proxmox_firewall_advanced.md), [ACME/SSL](./proxmox_acme_ssl.md) (доверенные сертификаты для :8006).

### Быстрый старт: production-VM с guest agent

```bash
qm create 100 \
  --name production-app \
  --memory 4096 --cores 4 --cpu host \
  --net0 virtio,bridge=vmbr0,firewall=1 \
  --scsi0 local-lvm:64,discard=on,ssd=1 \
  --ide2 local-lvm:cloudinit \
  --boot order=scsi0 \
  --agent enabled=1 \
  --serial0 socket --vga serial0

# Импорт готового диска (опционально)
qm disk import 100 /path/to/image.qcow2 local-lvm --format qcow2
qm set 100 --scsi0 local-lvm:vm-100-disk-0

qm start 100
qm guest cmd 100 network-get-interfaces   # после установки qemu-guest-agent в госте
```

### Мониторинг состояния узла (SRE)

Ключевые сигналы и быстрая диагностика:

```bash
# Ресурсы хоста
htop
free -h
df -h / /var
pvesm status
lvs -o+seg_usage,pool_percent     # LVM-Thin: не держать pool близко к 100%

# Сервисы и кластер
systemctl status pveproxy pvedaemon pve-cluster pvestatd corosync
pvecm status
pvesm status

# Логи
journalctl -u pveproxy -u pvedaemon -n 100 --no-pager
journalctl -u corosync -u pve-cluster -n 50 --no-pager
```

Глубокий мониторинг (Prometheus, node_exporter, алерты кворума/сертификатов/пулов) — [Мониторинг](./proxmox_monitoring.md). Логирование и UPID задач — [Логирование](./proxmox_logging.md).

### Резервное копирование (кратко)

```bash
# Одиночная ВМ (snapshot mode, без остановки при поддержке хранилища)
vzdump 100 --mode snapshot --storage pbs --compress zstd

# Контейнер
vzdump 101 --mode snapshot --storage local

# Список бэкапов на хранилище
vzdump --list --storage pbs
```

Периодические задания настраиваются в Datacenter → Backup (конфиг — `/etc/pve/jobs.cfg`, `pvescheduler`), не «сервисом vzdump». Полные сценарии, PR/DR, retention — [Disaster Recovery](./proxmox_disaster_recovery.md), [PBS](./proxmox_backup_server.md), [Обновления (бэкапы перед upgrade)](./proxmox_updates.md).

### Миграция между узлами

```bash
# Cold (с остановкой)
qm migrate 100 node2 --online 0

# Live (без простоя; требуется shared storage или storage migration)
qm migrate 100 node2 --online 1
```

Ограничения (shared vs non-shared, LXC restart mode, кворум) — [Кластер](./proxmox_cluster.md).

### Установка Windows 11 (ключевые параметры)

Минимум: TPM 2.0, UEFI (OVMF) + Secure Boot, 4 ГБ RAM, 64 ГБ диска.

```bash
qm set 102 --bios ovmf \
  --efidisk0 local-lvm:0,pre-enrolled-keys=1 \
  --tpmstate0 local-lvm:0,version=v2.0
```

Драйверы VirtIO: второй CD с `virtio-win.iso` → `Load Driver` (`D:\amd64\win11`, `D:\NetKVM\win11\amd64`) → после установки — VirtIO Guest Tools + QEMU Guest Agent. Windows-шаблоны и cloudbase-init — [Шаблоны](./proxmox_vm_templates.md).

## Типичные проблемы и диагностика

### pveproxy недоступен

```bash
systemctl status pveproxy
journalctl -u pveproxy -n 50
ss -tlnp | grep 8006
# при необходимости:
systemctl restart pveproxy
```

Частые причины: не создан `/var/log/pveproxy/` (pveproxy падает без access.log), конфликт :8006, истёкший/битый сертификат ([ACME/SSL](./proxmox_acme_ssl.md)), firewall.

### Узел или кластер «не отвечает»

```bash
ping -c 3 node1.example.com
ssh root@node1.example.com          # SSH не зависит от pveproxy
pvecm status                        # кворум, состав нод
corosync-quorumtool -s              # альтернатива для скриптов
journalctl -u corosync -u pve-cluster -n 50
```

Потеря кворума, fencing, two-node + QDevice — [Кластер](./proxmox_cluster.md#кворум-и-голоса-quorum).

### Заполненное хранилище

```bash
pvesm status
df -h
lvs -o+seg_usage,pool_percent       # LVM-Thin
zpool list                           # ZFS
pveam cleanup                        # старые ISO
# удаление неиспользуемых backup — через GUI/CLI хранилища или prune-задачи PBS
```

Переполнение LVM-Thin/Ceph/тонкого qcow2 останавливает запись у всех гостей на этом хранилище — [Хранилища](./proxmox_storage.md#граничные-случаи-и-ограничения).

### Ceph (кратко)

```bash
ceph status
ceph osd tree
ceph pg stat
```

Развёртывание, мониторинг, troubleshooting — [Хранилища и Ceph](./proxmox_storage.md).

## Лучшие практики

- **Резервные копии**: регулярно **тестируйте восстановление**. Невосстановимая копия равна её отсутствию.
- **Имена узлов**: короткие, без пробелов; задаются при установке и практически не меняются.
- **Время**: chrony/systemd-timesyncd на всех узлах — иначе кворум, TLS и логи рассинхронизируются.
- **Ресурсы**: избегайте overcommit RAM в production; следите за thin-pool/Ceph.
- **Шаблоны**: стандартные шаблоны для каждого дистрибутива ускоряют deploy и снижают drift.
- **Изоляция сетей**: отдельные сети management / storage (Ceph, replication) / guests.
- **Out-of-band**: IPMI/iDRAC на каждом узле — GUI может быть недоступна во время обновления pveproxy.
- **Подписка и репозитории**: production — enterprise (при наличии подписки); иначе no-subscription с пониманием, что он less tested ([updates](./proxmox_updates.md)).
- **Окна обслуживания**: изменения кластера/ядра — через change management с бэкапами и rollback-планом.
- **Документация**: журнал изменений на уровне кластера (версии, узлы, инциденты).

## Граничные случаи

- **LVM-Thin / thin qcow2 / Ceph nearfull**: переполнение = остановка записи для всех гостей на пуле. Алерты на ≥80–85%.
- **2-узловой кластер**: без QDevice возможна потеря кворума при обновлении одного узла; используйте qdevice или свидетеля.
- **Смешанные мажорные версии**: live migration PVE 8 → 9 не поддерживается; только cold migration в процессе апгрейда ([updates](./proxmox_updates.md)).
- **DKMS-модули** (NVIDIA passthrough, специализированные HBA): перед обновлением ядра — `dkms status`; после — `dkms autoinstall` ([kernel](./proxmox_kernel_management.md)).
- **ZFS replication** во время upgrade: может зафиксировать mid-upgrade state — остановите scheduled replication на окно работ.
- **pmxcfs и права**: не «чините» `/etc/pve` напрямую в обход API; при квorum-lost запись в `/etc/pve` блокируется.
- **ACME ≠ cluster CA**: доверенный сертификат pveproxy не заменяет внутренний CA для кластерных вызовов ([ACME/SSL](./proxmox_acme_ssl.md)).
- **arm64**: PVE 9.2 arm64 — отдельная подписка на архитектуру; live migration только между узлами одной архитектуры.

## Дополнительная информация

### Связанные темы

- [Кластеризация и High Availability](./proxmox_cluster.md)
- [Хранилища и Ceph](./proxmox_storage.md)
- [Сетевые технологии и SDN](./proxmox_networking.md)
- [Шаблоны ВМ и Cloud-Init](./proxmox_vm_templates.md)
- [Обновление систем Proxmox](./proxmox_updates.md)
- [Безопасность и Hardening](./proxmox_security.md)
- [Мониторинг](./proxmox_monitoring.md)
- [Логирование](./proxmox_logging.md)
- [REST API](./proxmox_rest_api.md)
- [Автоматизация через Ansible](./proxmox_ansible.md)
- [Disaster Recovery и BCP](./proxmox_disaster_recovery.md)
- [Proxmox Backup Server](./proxmox_backup_server.md)
- [ACME и SSL-сертификаты](./proxmox_acme_ssl.md)
- [Производительность KVM/LXC](./proxmox_performance.md)
- [Планирование ресурсов](./proxmox_capacity_planning.md)
- [Kernel management](./proxmox_kernel_management.md)
- [PCI passthrough](./proxmox_pci_passthrough.md)
