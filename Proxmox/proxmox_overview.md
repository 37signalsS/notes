# Proxmox Virtual Environment (PVE) — Обзор и базовые концепции

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом корпоративного уровня на базе Debian GNU/Linux. Актуальная ветка — **9.x** (PVE 9.2 на базе Debian 13 «Trixie», ядро Linux 7.0). Объединяет в себе гипервизор KVM/QEMU, системные контейнеры LXC, программно-определяемые хранилища (Ceph) и сети (SDN) в едином веб-интерфейсе с REST API. Ветка PVE 8.x получает исправления безопасности до августа 2026.

**Hyper-Converged Infrastructure (HCI, Гиперконвергентная инфраструктура)** — архитектура, в которой вычислительные ресурсы, хранилище и сеть работают на одних и тех же узлах. В Proxmox это реализуется связкой PVE + Ceph + SDN.

**QEMU (Quick EMUlator)** — эмулятор, обеспечивающий виртуализацию оборудования для гостевых ОС. В PVE работает в паре с KVM для аппаратно-ускоренной виртуализации.

**KVM (Kernel-based Virtual Machine)** — модуль ядра Linux, предоставляющий аппаратную виртуализацию. В PVE используется как основной гипервизор для полной изоляции виртуальных машин.

**LXC (Linux Containers)** — технология контейнеризации на уровне ядра хоста, обеспечивающая легковесную изоляцию без эмуляции硬件. В PVE используется для системных контейнеров.

**Cloud-Init** — технология автоматизации первичной настройки гостевых ОС (создание пользователей, установка SSH-ключей, конфигурация сети, разбиение диска) при первом запуске из шаблона, без ручного вмешательства.

**Template (Шаблон)** — образ виртуальной машины или контейнера с предустановленной ОС и конфигурацией, предназначенный для многократного клонирования.

**pmxcfs** — кластерная файловая система Proxmox (Corosync-based), обеспечивающая синхронизацию конфигурации между узлами кластера в реальном времени. Хранит данные в `/etc/pve/` и видна как обычная директория.

**vzdump** — встроенный инструмент резервного копирования VM и LXC. Поддерживает снимки (snapshot mode), сжатие (zstd/lzo), шифрование и вывод в локальное хранилище или на PBS.

**RBAC (Role-Based Access Control)** — ролевая модель доступа, позволяющая назначать права на пулы, ноды, хранилища или отдельные VM/LXC пользователям и группам.

## Архитектура и взаимодействие компонентов

PVE представляет собой многоуровневую систему, где каждый компонент отвечает за отдельный аспект инфраструктуры:

- **Уровень ядра**: KVM предоставляет аппаратную виртуализацию,Namespaces/Cgroups обеспечивают изоляцию LXC, сетевой стек Linux обрабатывает мосты, VLAN и bonding.
- **Уровень управления**: `pvedaemon` координирует операции с ВМ/контейнерами, `pveproxy` обрабатывает HTTPS-доступ к веб-интерфейсу и API, `pve-ha-manager` управляет автоматическим перезапуском сервисов при сбоях.
- **Кластерный уровень**: Corosync обеспечивает передачу сообщений между узлами, `pmxcfs` синхронизирует конфигурацию, `pve-cluster` управляет состоянием кластера.
- **Хранилище**: LVM-Thin, ZFS, Ceph или сетевые хранилища предоставляют блочные и файловые ресурсы для дисков VM/rootdir LXC.
- **Сеть**: Linux Bridge и SDN обеспечивают L2/L3 connectivity для гостевых систем, как на одном узле, так и в кластере.

Взаимодействие происходит через REST API (порт 8006), CLI (`qm`, `pct`, `pvesh`) и веб-интерфейс. Все конфигурационные изменения записываются в `pmxcfs` и мгновенно распространяются на все узлы кластера.

## Основные концепции

### Установка и разбиение диска

При автоматической установке PVE 9.x используется LVM (Logical Volume Manager). По умолчанию создается пул **LVM-Thin**, который поддерживает динамическое (тонкое) выделение места и мгновенные снимки (snapshots). Типовая схема разделов:

```text
/dev/sda
├── /dev/sda1  BIOS Boot (bios_grub) или EFI System Partition (UEFI)
├── /dev/sda2  pve-root   — корневая ФС (ext4/XFS)
├── /dev/sda3  pve-swap   — раздел подкачки
└── /dev/sda4  pve-data   — LVM-Thin пул для дисков VM и LXC
```

Инсталлятор создает Volume Group `pve` с LV `root`, `data` и `swap` (при выборе ext4/XFS). Размеры задаются опциями `hdsize`, `swapsize`, `maxroot`, `maxvz` и `minfree` (Advanced Options) и вычисляются так:

- **swapsize** — по умолчанию равен объему установленной памяти, min 4 ГБ, max 8 ГБ; итоговое значение не может превышать `hdsize/8`. При значении 0 swap не создается.
- **maxroot** — максимальный размер root-тома: при доступном месте > 48 ГиБ по умолчанию `hdsize/4` (но не более 96 ГиБ); при < 48 ГиБ root-том занимает не менее `hdsize/2`.
- **minfree** — свободное место, оставляемое в VG `pve`: при диске > 128 ГБ по умолчанию 16 ГБ, иначе `hdsize/8`. Обычному LVM это место нужно для создания снапшотов (для lvmthin не требуется).
- **datasize** — фактический размер data-тома: `datasize = hdsize - rootsize - swapsize - minfree`, не больше `maxvz`. При LVM-Thin пул `data` создается только если `datasize > 4 ГБ`; при `maxvz = 0` data-том не создается вовсе.

Альтернативные варианты файловой системы (выбираются в Advanced Options инсталлятора):

- **ZFS**: рекомендуется для High Availability. Компрессия, снапшоты, Storage Replication. В PVE 9 поставляется ZFS 2.4.
- **ext4/XFS (Directory)**: классическая ФС без тонкого выделения; снапшоты только для qcow2.
- **BTRFS**: поддерживается с PVE 7.x, в PVE 9.x относится к технологическому превью.

Проверка схемы после установки:

```bash
pvs && lvs
# → PV /dev/sda4   VG pve   lvm2 ...
# → LV pve-data   VG pve   LSize ...
```

Пост-инсталляционный чеклист:

```bash
# 1. Проверка обновлений
apt update && apt list --upgradable

# 2. Проверка статуса кластерных сервисов
pvecluster status

# 3. Проверка хранилищ
pvesm status

# 4. Проверка сети
ip addr show && ip route show
```

Сравнение типов хранилищ — **[Хранилища Proxmox](./proxmox_storage.md#типы-локальных-хранилищ)**, механика тонкого выделения — **[LVM Thin Provisioning](../Linux/FileSystems/LVM/thin-provisioning.md)**.

### Виртуальные машины (KVM)

Обеспечивают полную аппаратную изоляцию за счет гипервизора KVM (Kernel-based Virtual Machine) и эмулятора QEMU (в PVE 9.2 — QEMU 11.0). Подробнее об архитектуре: **[KVM — Обзор и архитектура](../Linux/Virtualization/kvm/overview.md)**.

- **VirtIO**: Семейство паравиртуализированных драйверов для повышения производительности дисков и сети. В Windows-гостях подключаются через ISO-образ `virtio-win.iso`; рекомендуется использовать тип машины `q35` вместо устаревшего `i440fx`.
- **QEMU Guest Agent**: Сервис внутри ВМ для корректного бэкапа (fs-freeze), завершения работы и мониторинга IP-адресов.
- **Windows 11**: Требует обязательного включения TPM 2.0 и UEFI (OVMF). Для Windows 11 24H2+/Server 2025 в PVE 9.2 добавлена загрузка UEFI-сертификатов 2023 через GUI/API.

Базовые операции с ВМ через CLI:

```bash
# Создание ВМ (минимальные параметры)
qm create 100 --name test-vm --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0

# Добавление диска
qm set 100 --scsi0 local-lvm:32,discard=on

# Запуск
qm start 100

# Консоль (serial)
qm terminal 100

# Остановка
qm stop 100

# Удаление
qm destroy 100
```

### Системные контейнеры (LXC)

Легковесная виртуализация на базе ядра хоста (в PVE 9.2 — LXC 7.0). Подробнее об архитектуре и CLI: **[LXC — системные контейнеры](../Linux/Virtualization/lxc_overview.md)**.

- **Unprivileged Containers**: Используют маппинг UID/GID (User Namespaces) для безопасности. Включены по умолчанию в PVE 8.x/9.x.
- **Nesting**: Опция для запуска Docker или вложенных LXC внутри контейнера.
- **Device Passthrough**: Возможность проброса GPU или USB-устройств в контейнер.
- **Сеть**: В отличие от прикладных контейнеров Docker, LXC-контейнеры получают полноценный IP-адрес в сети хоста и ведут себя как отдельные серверы.

Базовые операции с контейнерами через CLI:

```bash
# Создание контейнера
pct create 100 local:vztmpl/debian-12-standard_12.0-1_amd64.tar.zst --hostname test-lxc --memory 1024 --net0 name=eth0,bridge=vmbr0,ip=dhcp

# Запуск
pct start 100

# Вход в контейнер
pct enter 100

# Выполнение команды без входа
pct exec 100 -- systemctl status ssh

# Остановка
pct stop 100

# Удаление
pct destroy 100
```

### Шаблоны (Templates) и клонирование

- **Full Clone (Полный клон)**: Полная копия виртуальной машины, полностью независимая от оригинала.
- **Linked Clone (Связанный клон)**: Использует диск шаблона как базу (только для чтения), записывая только изменения в новый слой. Экономит место, но создает зависимость от родительского шаблона.
- **LVM-Thin Exception**: При использовании LVM-Thin базовый том шаблона можно удалять или изменять, так как клоны используют свои блоки данных, пока на них есть ссылки.
- **Container Templates (vztmpl)**: Шаблоны LXC скачиваются из встроенного репозитория образов PVE (GUI или `pveam`).

### Программно-определяемые сети (SDN)

В PVE 9.x SDN — встроенный компонент, автоматизирующий настройку сетей на всех узлах кластера. Позволяет создавать:

- **VNet (Virtual Network)**: Виртуальные сети, изолированные друг от друга.
- **Zones (Зоны)**: Логические объединения VNets (Simple, VLAN, QinQ, VXLAN, EVPN).
- **IPAM**: Встроенное управление IP-адресами (внутренние диапазоны, Netbox, phpIPAM).
- **SDN Fabrics**: Автоматическая настройка сетей между нодами. В PVE 9.2 добавлены протоколы WireGuard и BGP, а также фильтрация BGP/EVPN (route maps, prefix lists).

Подробнее: **[Сетевые технологии Proxmox](./proxmox_networking.md)**.

### Управление ресурсами и правами

- **Resource Pools**: Логические группы ВМ, контейнеров и хранилищ для делегирования прав доступа (например, отделу разработки).
- **Tags**: Цветовые метки для быстрой фильтрации ресурсов в интерфейсе.
- **RBAC**: Ролевая модель доступа (Role-Based Access Control).

Базовые операции управления пользователями:

```bash
# Создание группы
pveum groupadd developers --comment "Development team"

# Создание пользователя
pveum useradd john@pam --group developers --email john@example.com

# Назначение роли на пул
pveum aclmod /pool/DevPool --user john@pam --role PVEDatastoreUser

# Проверка прав
pveum acllist /pool/DevPool
```

## Практические сценарии

### Начальная настройка узла

После установки PVE выполните базовую hardened-конфигурацию:

```bash
# 1. Отключение подписки (если нет лицензии)
sed -i 's/^deb \(.*\)enterprise/\deb \1no-subscription/' /etc/apt/sources.list

# 2. Настройка NTP
apt install chrony -y
systemctl enable --now chronyd

# 3. Настройка firewall
pve-firewall set options --enable 1

# 4. Создание резервного пользователя (не root)
pveum useradd admin2@pam --password $(openssl rand -base64 32)

# 5. Проверка обновлений
apt update && apt dist-upgrade -y
```

### Управление ВМ через CLI

Полный жизненный цикл виртуальной машины без GUI:

```bash
# Создание ВМ с диском
qm create 100 \
  --name production-app \
  --memory 4096 \
  --cores 4 \
  --cpu host \
  --net0 virtio,bridge=vmbr0,firewall=1 \
  --scsi0 local-lvm:64,discard=on,ssd=1 \
  --ide2 local-lvm:cloudinit \
  --boot c --bootdisk scsi0 \
  --agent 1 \
  --serial0 socket --vga serial0

# Импорт диска
qm disk import 100 /isos/debian-12.qcow2 local-lvm --format qcow2

# Привязка диска
qm set 100 --scsi0 local-lvm:vm-100-disk-0

# Запуск и проверка
qm start 100
qm status 100
# → status: running

# Мониторинг в реальном времени
qm monitor 100
```

### Управление LXC через CLI

Развертывание контейнера из шаблона:

```bash
# Скачивание шаблона
pveam download local debian-12-standard_12.0-1_amd64.tar.zst

# Создание контейнера
pct create 100 local:vztmpl/debian-12-standard_12.0-1_amd64.tar.zst \
  --hostname web-server \
  --memory 1024 \
  --cores 2 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --rootfs local-lvm:8 \
  --unprivileged 1

# Запуск
pct start 100

# Проверка статуса
pct status 100
# → status: running

# Выполнение команды внутри контейнера
pct exec 100 -- apt update
pct exec 100 -- apt install nginx -y
```

### Мониторинг состояния узла

Ключевые метрики для SRE/SysAdmin:

```bash
# Общая нагрузка
htop

# Использование памяти
free -h
# или
cat /proc/meminfo

# Использование дисков
df -h
pvesm status

# Температура процессора (если поддерживается)
sensors

# Статус кластерных сервисов
systemctl status pvedaemon pveproxy pve-cluster corosync

# Логи в реальном времени
journalctl -fu pveproxy
journalctl -fu pvedaemon

# Проверка работоспособности узла через API
curl -k -u root@pam:https://node1.example.com:8006/api2/json/nodes/node1/status
```

### Создание Cloud-Init шаблона

Для автоматизации развертывания рекомендуется использовать Cloud-Init шаблоны. Процесс включает создание базовой ВМ (Generic Template), импорт облачного образа дистрибутива, настройку Cloud-Init диска и конвертацию в шаблон.

Подробное пошаговое руководство (CLI и GUI): **[Шаблоны ВМ и Cloud-Init в Proxmox VE](./proxmox_vm_templates.md)**.

Краткий пример создания через CLI:
```bash
# 1. Создание заготовки
qm create 9000 --name u-template --memory 2048 --net0 virtio,bridge=vmbr0 --serial0 socket --vga serial0

# 2. Импорт диска и настройка Cloud-Init
qm disk import 9000 resolute-server-cloudimg-amd64.img local-lvm --format qcow2
qm set 9000 --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-9000-disk-0
qm set 9000 --ide2 local-lvm:cloudinit
qm set 9000 --boot c --bootdisk scsi0

# 3. Конвертация
qm template 9000
```

### Доступ по SSH для root в LXC

Если в шаблоне отключен вход по паролю для root:

1. Войти в контейнер с хоста:
   ```bash
   pct enter 101
   ```
2. Разрешить вход в `/etc/ssh/sshd_config`:
   ```bash
   sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
   systemctl restart ssh
   ```

### Установка Windows 11 (Ключевые параметры)

Минимальные требования: TPM 2.0, UEFI (OVMF) с Secure Boot, минимум 4 ГБ RAM и 64 ГБ диска.

1. **Создание ВМ**: Выбрать тип машины `q35`, BIOS `OVMF (UEFI)`, добавить `TPM Storage` и `EFI Storage`. Через CLI:
   ```bash
   qm set 102 --bios ovmf --efidisk0 local-lvm:0,pre-enrolled-keys=1 --tpmstate0 local-lvm:0,version=v2.0
   # → update VM 102: ...
   ```
2. **Драйверы**: Подключить второй виртуальный CD/DVD привод с ISO-образом `virtio-win.iso`.
3. **Этап установки**: При выборе диска нажать `Load Driver` и выбрать путь `D:\amd64\win11` (для диска) и `D:\NetKVM\win11\amd64` (для сетевой карты).
4. **Завершение**: После установки Windows запустить `VirtIO Guest Tools` из того же образа и установить QEMU Guest Agent.

*Примечание: Для Windows 11 24H2+ и Windows Server 2025 в PVE 9.2 загрузка UEFI-сертификатов 2023 доступна через GUI и API.*

### Резервное копирование через vzdump

Быстрое создание резервной копии ВМ или контейнера:

```bash
# Одиночная ВМ (snapshot mode — не требует остановки)
vzdump 100 --mode snapshot --storage pbs --compress zstd

# Все запущенные ВМ на узле
for vmid in $(qm list --active | awk 'NR>1 {print $1}'); do
  vzdump $vmid --mode snapshot --storage pbs
done

# Контейнер
vzdump 101 --mode snapshot --storage local

# Проверка резервной копии
vzdump --list --storage pbs
```

### Миграция ВМ между узлами

```bash
# Cold migration (с остановкой)
qm migrate 100 node2 --online 0

# Live migration (без простоев, требуется shared storage)
qm migrate 100 node2 --online 1
```

## Типичные проблемы и диагностика

### pveproxy недоступен

```bash
# Проверка статуса
systemctl status pveproxy

# Перезапуск
systemctl restart pveproxy

# Проверка порта
ss -tlnp | grep 8006
```

### Узел не отвечает

```bash
# Проверка доступности
ping node1.example.com

# Проверка SSH
ssh root@node1.example.com

# Проверка cluster quorum
pvecluster status

# Проверка Corosync
journalctl -u corosync -n 50
```

### Заполненное хранилище

```bash
# Проверка использования
pvesm status
df -h

# Очистка неиспользуемых образов ISO
pveam cleanup

# Удаление старых резервных копий
vzdump --cleanup 100
```

### Недоступность Ceph

```bash
# Проверка статуса кластера
ceph status

# Проверка OSD
ceph osd tree

# Проверка размера placement groups
ceph pg stat
```

## Лучшие практики

- **Резервное копирование**: тестируйте восстановление из резервных копий регулярно. Резервная копия, которую нельзя восстановить, равна отсутствию резервной копии.
- **Имена узлов**: используйте короткие осмысленные имена без пробелов (например, `pve1`, `node-storage`).
- **Сетевая синхронизация**: настройте NTP (chrony) на всех узлах для предотвращения рассинхронизации кворума и логов.
- **Ресурсы**: выделяйте ВМ и контейнерам только те ресурсы, которые им необходимы. Избегайте overcommit памяти для production-рабочих нагрузок.
- **Шаблоны**: поддерживайте стандартизированные шаблоны для каждого дистрибутива. Это ускоряет развертывание и снижает риск ошибок конфигурации.
- **Документация**: ведите журнал изменений на уровне кластера с указанием версий до/после, узлов и проблем.
- **Out-of-band доступ**: имейте для каждого узла IPMI/iDRAC/iKVM. Веб-интерфейс может стать недоступен при обновлении `pveproxy`.
- **Изоляция сетей**: выделяйте отдельные сети для управления, хранения данных (Ceph/replication) и гостевого трафика.

## Граничные случаи

- **Остановка узла при заполненном хранилище**: LVM-Thin переполнение приводит к остановке всех ВМ на узле. Мониторьте свободное место и настраивайте алерты.
- **Потеря кворума в 2-узловом кластере**: при обновлении последнего узла без witnesses кворум теряется. Используйте `qdevice` или обновляйте только при наличии witnesses.
- **Смешанные версии в кластере**: Live Migration между узлами разных мажорных версий (PVE 8 → PVE 9) не поддерживается. Используйте только холодную миграцию.
- **Обновление ядра с DKMS модулями**: перед обновлением ядра проверьте доступность модулей (NVIDIA GPU passthrough, специализированные HBA) для нового ядра:
  ```bash
  dkms status
  # После обновления пересоберите модули:
  dkms autoinstall
  ```
- **ZFS replication во время обновления**: репликация может зафиксировать состояние mid-upgrade. Остановите scheduled replication на время обновления узла.

## Дополнительная информация

### Связанные темы

- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Хранилища и Ceph в Proxmox](./proxmox_storage.md)
- [Шаблоны ВМ и Cloud-Init](./proxmox_vm_templates.md)
