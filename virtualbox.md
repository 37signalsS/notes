# VirtualBox в Arch Linux

## Определения

**VirtualBox** — гипервизор типа 2 (hosted) для рабочих станций. Разработан Oracle, распространяется под лицензией GPL v2 (base) и проприетарной (Extension Pack).

**Extension Pack** — проприетарное расширение с поддержкой USB 2.0/3.0, шифрования дисков, PXE, RDP. Лицензия: Personal Use Only.

---

## Основные концепции

### Архитектура VirtualBox

| Компонент | Описание |
| :--- | :--- |
| **vboxdrv** | Основной модуль ядра, требуется для всех ВМ |
| **vboxnetadp** | Host-only networking (виртуальные адаптеры) |
| **vboxnetflt** | Фильтр для host-only/bridged сети |
| **vboxpci** | Проброс PCI-устройств (требует группу `disk`) |

**Модули загружаются автоматически** через `systemd-modules-load.service`.

### Сетевые режимы

| Режим | Описание |
| :--- | :--- |
| **NAT** | ВМ за NAT хоста, доступ наружу есть, входящие — нет |
| **Bridged** | ВМ в той же сети, что хост (физический адаптер) |
| **Host-only** | Изолированная сеть между ВМ и хостом |
| **Internal** | Изолированная сеть между ВМ |

**Важно:** Для host-only сети требуется настройка `/etc/vbox/networks.conf`.

---

## Практические сценарии

### Установка VirtualBox

#### 1. Подготовка системы

```bash
# Обновление системы
sudo pacman -Syu

# Установка заголовков ядра (требуется для dkms)
sudo pacman -S --needed linux-headers

# Перезагрузка (после обновления ядра)
sudo reboot
```

#### 2. Установка пакетов

```bash
# Основные пакеты
sudo pacman -S virtualbox virtualbox-guest-iso
```

**Выбор модулей ядра** (зависит от ядра):

| Ядро | Пакет модулей |
| :--- | :--- |
| `linux` | `virtualbox-host-modules-arch` |
| `linux-lts` | `virtualbox-host-modules-lts` |
| `linux-zen`, `linux-custom` | `virtualbox-host-dkms` + заголовки |

```bash
# Для стандартного ядра (уже установлен с virtualbox)
sudo pacman -S virtualbox-host-modules-arch

# Для кастомных ядер (DKMS)
sudo pacman -S virtualbox-host-dkms
```

#### 3. Загрузка модулей

```bash
# Загрузка vboxdrv (обычно автоматически)
sudo modprobe vboxdrv

# Проверка
lsmod | grep vbox
```

#### 4. Настройка прав доступа

```bash
# Добавление пользователя в группу vboxusers (USB)
sudo usermod -aG vboxusers $USER

# Выход и повторный вход для применения
```

**Важно:** Требуется выход из системы для применения изменений группы.

---

### Установка Extension Pack

```bash
# Через AUR helper (рекомендуется)
yay -S virtualbox-ext-oracle

# Или вручную с сайта Oracle
# https://www.virtualbox.org/wiki/Downloads
```

**Проверка установки:**

```bash
VBoxManage list extpacks
```

---

### Настройка сети

#### Host-only сеть

**Файл `/etc/vbox/networks.conf`:**

```
* 10.0.0.0/8 192.168.0.0/16
* 2001:db8:1234::/48
```

**Создание адаптера:**

```bash
VBoxManage hostonlyif create
VBoxManage hostonlyif ipconfig vboxnet0 --ip 192.168.56.1 --netmask 255.255.255.0
```

---

### Работа с Wayland

**Проблемы:**

- Захват клавиатуры может не работать
- Интеграция мыши может быть нарушена

**Решения:**

1. **Whitelist для GNOME:**

```bash
gsettings set org.gnome.mutter.wayland xwayland-grab-access-rules "['VirtualBox Machine']"
```

1. **Принудительный X11:**

```bash
QT_QPA_PLATFORM=xcb VirtualBox
```

---

### Конфликт с KVM

**Проблема:** Модули KVM и VirtualBox не могут работать одновременно.

**Решение для Android Studio (эмулятор):**

```bash
# Выгрузить модули VirtualBox
sudo modprobe -r vboxnetflt vboxnetadp vboxdrv

# Загрузить KVM
sudo modprobe kvm-intel  # или kvm-amd
```

**Автоматизация:** Создать скрипт переключения или использовать `blacklist` в `/etc/modprobe.d/`.

---

### Настройка аудио (PipeWire)

```bash
# Явное указание драйвера
VBoxManage modifyvm "VM_name" --audio-driver pulse --audio-controller hda
```

---

### Проверка установки

```bash
# Модули ядра
lsmod | grep vbox

# Версия VirtualBox
VBoxManage --version

# Extension Pack
VBoxManage list extpacks

# Список ВМ
VBoxManage list vms

# Информация о хосте
VBoxManage list hostinfo
```

---

## Дополнительная информация

### Полезные команды VBoxManage

```bash
# Создание ВМ
VBoxManage createvm --name "VM_name" --register

# Настройка памяти
VBoxManage modifyvm "VM_name" --memory 4096

# Настройка сети (NAT)
VBoxManage modifyvm "VM_name" --nic1 nat

# Настройка сети (Bridged)
VBoxManage modifyvm "VM_name" --nic1 bridged --bridgeadapter1 eth0

# Проброс портов (NAT)
VBoxManage modifyvm "VM_name" --natpf1 "ssh,tcp,,2222,,22"

# Создание диска
VBoxManage createmedium disk --filename ~/VirtualBox\ VMs/disk.vdi --size 50000

# Подключение диска
VBoxManage storageattach "VM_name" --storagectl "SATA" --port 0 --device 0 --type hdd --medium ~/VirtualBox\ VMs/disk.vdi
```

### Vagrant + VirtualBox

Vagrant использует VirtualBox как провайдер по умолчанию:

```bash
vagrant up --provider=virtualbox
```

См. [Vagrant basic workflow](./Vagrant/vagrant_basic_workflow.md).

### Подпись модулей (кастомные ядра)

При `CONFIG_MODULE_SIG_FORCE`:

```bash
find "/lib/modules/$(uname -r)/" \
  '(' -name 'vboxdrv.ko*' -o -name 'vboxnetadp.ko*' -o -name 'vboxnetflt.ko*' ')' \
  -exec /lib/modules/$(uname -r)/build/scripts/sign-file \
    sha256 \
    /lib/modules/$(uname -r)/build/certs/signing_key.pem \
    /lib/modules/$(uname -r)/build/certs/signing_key.x509 {} \;
```

### Устранение проблем

| Проблема | Решение |
| :--- | :--- |
| **Модуль не загружается** | `sudo vboxreload` или перезагрузка |
| **Нет USB в ВМ** | Проверить группу `vboxusers`, установить Extension Pack |
| **Нет сети** | Проверить `/etc/vbox/networks.conf` для host-only |
| **Конфликт с KVM** | Выгрузить один из модулей |
| **Wayland проблемы** | Использовать X11 или whitelist |

### Альтернативы

| Решение | Тип | Преимущества |
| :--- | :--- | :--- |
| **KVM/QEMU** | Тип 1 | Производительность, интеграция с Linux |
| **VMware Workstation** | Тип 2 | 3D-графика, коммерческая поддержка |
| **GNOME Boxes** | Тип 1 (KVM) | Простота, интеграция с GNOME |

# force reindex test
