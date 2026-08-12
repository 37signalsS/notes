# Proxmox Virtual Environment (PVE) — Обзор и базовые концепции

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом корпоративного уровня на базе Debian GNU/Linux. Актуальная ветка — **9.x** (PVE 9.2 на базе Debian 13 «Trixie», ядро Linux 7.0). Объединяет в себе гипервизор KVM/QEMU, системные контейнеры LXC, программно-определяемые хранилища (Ceph) и сети (SDN) в едином веб-интерфейсе с REST API. Ветка PVE 8.x получает исправления безопасности до августа 2026.

**Hyper-Converged Infrastructure (HCI, Гиперконвергентная инфраструктура)** — архитектура, в которой вычислительные ресурсы, хранилище и сеть работают на одних и тех же узлах. В Proxmox это реализуется связкой PVE + Ceph + SDN.

**Cloud-Init** — технология автоматизации первичной настройки гостевых ОС (создание пользователей, установка SSH-ключей, конфигурация сети, разбиение диска) при первом запуске из шаблона, без ручного вмешательства.

**Template (Шаблон)** — образ виртуальной машины или контейнера с предустановленной ОС и конфигурацией, предназначенный для многократного клонирования.

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

Сравнение типов хранилищ — **[Хранилища Proxmox](./proxmox_storage.md#типы-локальных-хранилищ)**, механика тонкого выделения — **[LVM Thin Provisioning](../Linux/FileSystems/LVM/thin-provisioning.md)**.

### Виртуальные машины (KVM)

Обеспечивают полную аппаратную изоляцию за счет гипервизора KVM (Kernel-based Virtual Machine) и эмулятора QEMU (в PVE 9.2 — QEMU 11.0). Подробнее об архитектуре: **[KVM — Обзор и архитектура](../Linux/Virtualization/kvm/overview.md)**.

- **VirtIO**: Семейство паравиртуализированных драйверов для повышения производительности дисков и сети. В Windows-гостях подключаются через ISO-образ `virtio-win.iso`; рекомендуется использовать тип машины `q35` вместо устаревшего `i440fx`.
- **QEMU Guest Agent**: Сервис внутри ВМ для корректного бэкапа (fs-freeze), завершения работы и мониторинга IP-адресов.
- **Windows 11**: Требует обязательного включения TPM 2.0 и UEFI (OVMF). Для Windows 11 24H2+/Server 2025 в PVE 9.2 добавлена загрузка UEFI-сертификатов 2023 через GUI/API.

### Системные контейнеры (LXC)

Легковесная виртуализация на базе ядра хоста (в PVE 9.2 — LXC 7.0). Подробнее об архитектуре и CLI: **[LXC — системные контейнеры](../Linux/Virtualization/lxc_overview.md)**.

- **Unprivileged Containers**: Используют маппинг UID/GID (User Namespaces) для безопасности. Включены по умолчанию в PVE 8.x/9.x.
- **Nesting**: Опция для запуска Docker или вложенных LXC внутри контейнера.
- **Device Passthrough**: Возможность проброса GPU или USB-устройств в контейнер.
- **Сеть**: В отличие от прикладных контейнеров Docker, LXC-контейнеры получают полноценный IP-адрес в сети хоста и ведут себя как отдельные серверы.

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

## Практические сценарии

### Создание Cloud-Init шаблона через CLI

Cloud-Init позволяет автоматизировать настройку ВМ (пользователи, SSH-ключи, сеть) при первом запуске. Для шаблонов рекомендуется использовать официальные cloud-ready образы (например, Ubuntu Cloud Images). Актуальный LTS — Ubuntu 26.04 «Resolute Raccoon».

```bash
# 1. Загрузка образа и создание ВМ
wget https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-amd64.img
qm create 9000 --name u-template --memory 2048 --net0 virtio,bridge=vmbr0
# → VM 9000 created

# 2. Импорт диска
qm importdisk 9000 resolute-server-cloudimg-amd64.img local-lvm
# → successfully imported disk as 'unused0'

# 3. Настройка параметров и Cloud-Init
qm set 9000 --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-9000-disk-0
qm set 9000 --ide2 local-lvm:cloudinit
qm set 9000 --boot c --bootdisk scsi0
qm set 9000 --serial0 socket --vga serial0
# → update VM 9000: ...

# 4. Конвертация в шаблон
qm template 9000
# → VM 9000 converted to template
```

После клонирования из шаблона укажите в GUI Cloud-Init данные пользователя, SSH-ключ и сеть — они применятся при первом старте клона.

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

## Дополнительная информация

### Связанные темы

- [LXC (Linux Containers) — системные контейнеры](../Linux/Virtualization/lxc_overview.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Хранилища и Ceph в Proxmox](./proxmox_storage.md)
- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)
- [Обновление систем Proxmox](./proxmox_updates.md)
