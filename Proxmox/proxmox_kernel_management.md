# Управление ядром Linux в Proxmox VE

## Определения

**Kernel** -- ядро операционной системы, отвечающее за управление ресурсами, процессами, памятью, устройствами и безопасность. Proxmox VE использует модифицированное ядро Debian с патчами для виртуализации (KVM, LXC, ZFS, Ceph).

**DKMS (Dynamic Kernel Module Support)** -- фреймворк для автоматической пересборки модулей ядра при его обновлении. Позволяет устанавливать сторонние модули (ZFS, NVIDIA, WireGuard) без ручной компиляции.

**Live Patching** -- механизм обновления ядра без перезагрузки. Позволяет применять исправления безопасности к работающему ядру, минуя downtime.

**sysctl** -- интерфейс для чтения и изменения параметров ядра в runtime через `/proc/sys`. Позволяет настраивать сетевое поведение, управление памятью, безопасность и производительность.

**Secure Boot** -- стандарт безопасности UEFI, обеспечивающий проверку подписи загрузчика, ядра и модулей. Proxmox VE поддерживает Secure Boot с собственным ключом.

**initramfs (Initial RAM Filesystem)** -- временная файловая система, загружаемая ядром при старте для инициализации устройств и монтирования корневой ФС. Содержит модули ядра, необходимые для доступа к дискам.

**GRUB (Grand Unified Bootloader)** -- загрузчик операционной системы, отвечающий за выбор ядра и передачу параметров командной строки.

## Теоретический блок

### Структура ядер Proxmox

Proxmox VE использует несколько веток ядер:

| Ядро | Описание | Использование |
| :--- | :--- | :--- |
| **6.8 (Proxmox 8.x)** | Актуальная стабильная ветка | Production, рекомендуется |
| **6.2 (Proxmox 7.x)** | Устаревающая ветка | Legacy системы |
| **Backports** | Новые версии из Debian backports | Тестирование новых функций |

```bash
# Проверка текущего ядра
uname -r
# → 6.8.12-1-pve

# Просмотр доступных ядер
apt list --installed | grep pve-kernel

# Список всех установленных ядер
dpkg -l | grep pve-kernel
```

### Процесс обновления ядра

```
1. Скачивание нового ядра (apt upgrade)
2. Генерация initramfs (update-initramfs)
3. Обновление GRUB (update-grub)
4. Перезагрузка (reboot)
```

### DKMS в Proxmox

DKMS автоматически пересобирает модули при обновлении ядра:

```bash
# Просмотр установленных DKMS модулей
dkms status
# → zfs/2.2.4, 6.8.12-1-pve, x86_64: installed
# → nvidia/550.90.07, 6.8.12-1-pve, x86_64: installed

# Ручная пересборка модуля
dkms autoinstall -k 6.8.12-1-pve

# Удаление модуля
dkms remove nvidia/550.90.07 -k 6.8.12-1-pve
```

### Live Patching

Proxmox VE поддерживает live patching через ядро Linux (kpatch/livepatch):

| Механизм | Описание | Поддержка |
| :--- | :--- | :--- |
| **kpatch (Red Hat)** | Патчинг функций ядра | RHEL, CentOS |
| **livepatch (Canonical)** | Живое обновление Ubuntu | Ubuntu, Debian |
| **pve-kernel-livepatch** | Proxmox интеграция | Proxmox 8+ |

```bash
# Проверка доступных патчей
apt list | grep pve-kernel-livepatch

# Установка live patching
apt install pve-kernel-livepatch

# Включение
pve-livepatch enable

# Проверка статуса
pve-livepatch status
```

## Практические сценарии

### 1. Обновление ядра Proxmox

```bash
# Обновление всех пакетов (включая ядро)
apt update && apt full-upgrade

# Проверка нового ядра
dpkg -l | grep pve-kernel | tail -5

# Перезагрузка для применения нового ядра
reboot

# Проверка после перезагрузки
uname -r
```

### 2. Настройка sysctl для Proxmox

```bash
# Оптимизация сети для виртуализации
cat > /etc/sysctl.d/99-proxmox-networking.conf << 'EOF'
# Увеличение очереди соединений
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535

# Увеличение диапазона портов
net.ipv4.ip_local_port_range = 1024 65535

# Включение TCP Fast Open
net.ipv4.tcp_fastopen = 3

# Оптимизация памяти
net.ipv4.tcp_mem = 786432 1048576 26777216
net.ipv4.tcp_rmem = 4096 87380 33554432
net.ipv4.tcp_wmem = 4096 65536 33554432

# Conntrack
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144

# VM memory overcommit
vm.overcommit_memory = 0
vm.overcommit_ratio = 80
vm.swappiness = 10
EOF

sysctl -p /etc/sysctl.d/99-proxmox-networking.conf
```

### 3. Установка DKMS модуля (ZFS)

```bash
# ZFS уже включён в Proxmox ядро, но для сторонних модулей:
apt install dkms linux-headers-$(uname -r)

# Установка модуля (пример: WireGuard)
apt install wireguard-dkms

# Проверка
dkms status
# → wireguard/1.0.20210914, 6.8.12-1-pve, x86_64: installed
```

### 4. Настройка Secure Boot

```bash
# Проверка статуса Secure Boot
mokutil --sb-state
# → SecureBoot enabled или SecureBoot disabled

# Генерация ключа для подписи модулей
openssl req -new -x509 -newkey rsa:2048 -keyout MOK.priv -out MOK.der \
  -days 36500 -subj "/CN=My Module Signing Key/" -nodes

# Регистрация ключа
mokutil --import MOK.der
# → Требуется перезагрузка и подтверждение через MokManager

# Подпись модуля
kmodsign sha256 MOK.priv MOK.der module.ko
```

### 5. Откат ядра

```bash
# Просмотр доступных ядер в GRUB
grep menuentry /boot/grub/grub.cfg | cut -d "'" -f2

# Временный откат (при загрузке)
# В GRUB: Advanced options -> Выбрать предыдущее ядро

# Постоянный откат
grub-set-default "Advanced options for Proxmox VE GNU/Linux>Proxmox VE GNU/Linux, with Linux 6.8.11-1-pve"
update-grub
```

### 6. Диагностика проблем с ядром

```bash
# Просмотр логов ядра
dmesg | tail -50
journalctl -k -b -1  # логи предыдущей загрузки

# Проверка модулей
lsmod | grep -E "kvm|vfio|zfs"

# Загрузка/выгрузка модуля
modprobe kvm_intel
modprobe -r nouveau

# Проверка параметров ядра
cat /proc/cmdline

# Мониторинг использования памяти ядра
slabtop
cat /proc/slabinfo
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Модуль не загружается | Secure Boot блокирует неподписанный модуль | Подпишите модуль или отключите Secure Boot |
| DKMS ошибка при обновлении | Несовместимость с новым ядром | Проверьте версию DKMS модуля |
| Live patching не работает | Ядро не поддерживает livepatch | Используйте supported kernel version |
| sysctl не применяется | Синтаксическая ошибка | Проверьте: `sysctl -p <file> --system` |
| GRUB не видит новое ядро | Не выполнен update-grub | `update-grub && reboot` |
| Kernel panic | Повреждённый модуль или критическая ошибка в ядре | Загрузитесь с предыдущим ядром через GRUB; если откат невозможен — восстановите систему из резервной копии (PBS/ZFS snapshot) |

## Лучшие практики

1. **Регулярно обновляйте ядро**: Proxmox выпускает исправления безопасности и исправления ошибок.
2. **Тестируйте обновления**: На production узлах сначала обновите test-ноду. Свежие сборки ядра (например, 7.0.0.3) могут содержать критические ошибки, приводящие к kernel panic и невозможности загрузки.
3. **Сохраняйте предыдущее ядро**: Не удаляйте старые ядра сразу; дождитесь стабильности нового.
4. **Используйте sysctl.d**: Разделяйте конфигурацию по файлам для удобства управления.
5. **DKMS модули**: Устанавливайте `linux-headers` дляDKMS сборки.
6. **Live Patching**: Используйте для критических исправлений безопасности, не требующих простоя.
7. **Secure Boot**: Включайте для hardened конфигураций, но убедитесь, что все модули подписаны.
8. **Резервные копии**: Храните бэкапы (PBS или vzdump) на независимом хранилище. При kernel panic и невозможности загрузки единственным способом восстановления является переустановка узла и восстановление из резервных копий.

## Граничные случаи

- **Обновление ядра + Ceph/ZFS**: Обновляйте ядро и Ceph/ZFS одновременно для совместимости.
- **DKMS и Secure Boot**: Все DKMS модули должны быть подписаны ключом, зарегистрированным в MOK.
- **Live patching + перезагрузка**: Live patching не заменяет полное обновление; после накопления патчей требуется перезагрузка.
- **Нестандартные модули**: Модули, не входящие в основное ядро (NVIDIA, WireGuard), требуют DKMS и могут сломаться при обновлении.

## Дополнительная информация

### Связанные темы

- [Модули ядра Linux -- SSoT](../Linux/Core/kernel/kernel_modules.md)
- [sysctl -- SSoT](../Linux/Core/kernel/sysctl.md)
- [Live Patching -- SSoT](../Linux/Core/kernel/live_patching.md)
- [Обновление систем Proxmox](./proxmox_updates.md)
- [Безопасность и Hardening Proxmox VE](./proxmox_security.md)
