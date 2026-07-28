---
Надёжность: 10 (SSoT + Проектный контекст 2026)
Свежесть: Актуально на июль 2026
---

# Proxmox Virtual Environment (PVE) — Обзор и базовые концепции

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом корпоративного уровня на базе Debian GNU/Linux. Объединяет в себе гипервизор KVM, контейнеры LXC, программно-определяемые хранилища (Ceph) и сети (SDN) в едином веб-интерфейсе.

**Hyper-Converged Infrastructure (HCI, Гиперконвергентная инфраструктура)** — архитектура, в которой вычислительные ресурсы, хранилище и сеть работают на одних и тех же узлах. В Proxmox это реализуется связкой PVE + Ceph + SDN.

## Основные концепции

### Установка и разбиение диска

При автоматической установке используется LVM (Logical Volume Manager). По умолчанию создается пул **LVM-Thin**, который поддерживает динамическое выделение места и мгновенные снимки (snapshots).

Подробная схема: **[Логика разбиения диска при установке](./proxmox_storage.md#логика-разбиения-диска-при-установке)**.

### Виртуальные машины (KVM)

Обеспечивают полную аппаратную изоляцию.
- **VirtIO**: Семейство паравиртуализированных драйверов для повышения производительности дисков и сети.
- **QEMU Guest Agent**: Сервис внутри ВМ для корректного бэкапа (fs-freeze), завершения работы и мониторинга IP-адресов.
- **Windows 11**: Требует обязательного включения TPM 2.0 и UEFI (OVMF).

### Системные контейнеры (LXC)

Легковесная виртуализация на базе ядра хоста.
- **Unprivileged Containers**: Используют маппинг UID/GID для безопасности. Включены по умолчанию в PVE 8.x.
- **Nesting**: Опция для запуска Docker или вложенных LXC внутри контейнера.
- **Device Passthrough**: Возможность проброса GPU или USB-устройств в контейнер.

### Программно-определяемые сети (SDN)

В PVE 8.1+ SDN стала основным компонентом. Позволяет создавать:
- **VNet**: Виртуальные сети, изолированные друг от друга.
- **Zones**: Логические объединения VNets (Simple, VLAN, QinQ, VXLAN, EVPN).
- **IPAM**: Встроенное управление IP-адресами.

### Управление ресурсами и правами

- **Resource Pools**: Логические группы ВМ, контейнеров и хранилищ для делегирования прав доступа (например, отделу разработки).
- **Tags**: Цветовые метки для быстрой фильтрации ресурсов в интерфейсе.
- **RBAC**: Ролевая модель доступа (Role-Based Access Control).

## Практические сценарии

### Создание Cloud-Init шаблона через CLI

Cloud-Init позволяет автоматизировать настройку ВМ (пользователи, SSH-ключи, сеть) при первом запуске.

```bash
# 1. Загрузка образа и создание ВМ
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
qm create 9000 --name u-template --memory 2048 --net0 virtio,bridge=vmbr0
# → VM 9000 created

# 2. Импорт диска
qm importdisk 9000 jammy-server-cloudimg-amd64.img local-lvm
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

При создании ВМ через CLI или GUI:
```bash
qm set 102 --bios ovmf --efidisk0 local-lvm:0,pre-enrolled-keys=1 --tpmstate0 local-lvm:0,version=v2.0
# → update VM 102: ...
```
*Примечание: Не забудьте подключить ISO с VirtIO-драйверами.*

## Дополнительная информация

### Связанные темы

- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Хранилища и Ceph в Proxmox](./proxmox_storage.md)
- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)
- [Обновление систем Proxmox](./proxmox_updates.md)
