# Управление хранилищем и общими папками в Vagrant

## Определения

1. **Общая папка (Synced Folder)** — механизм синхронизации директории хоста с директорией ВМ в реальном времени. Основной способ работы с кодом проекта.

2. **Виртуальный диск (Virtual Disk)** — блочное устройство внутри ВМ для размещения файловой системы. Vagrant управляет основным и дополнительными дисками.

## Базовые концепции

### Два подхода к работе с файлами

| Подход | Описание | Сценарий |
| --- | --- | --- |
| **Общие папки** | Синхронизация хост ↔ ВМ | Редактирование кода, конфигураций |
| **Виртуальные диски** | Данные только внутри ВМ | Базы данных, логи, кэш |

**По умолчанию:** Vagrant синхронизирует папку проекта (где `Vagrantfile`) в `/vagrant` внутри ВМ.

### Типы общих папок

| Тип | Производительность | Зависимости | Платформа |
| --- | --- | --- | --- |
| **Default (VirtualBox)** | Средняя | Guest Additions | VirtualBox |
| **Default (VMware)** | Средняя | VMware Tools | VMware |
| **NFS** | Высокая | nfs-kernel-server | Linux/macOS |
| **rsync** | Односторонняя | rsync | Кроссплатформенный |
| **SMB** | Высокая | Встроен в Windows | Windows/macOS |

## Практические сценарии

### Сценарий 1: Настройка общих папок

**Отключение стандартной папки:**

```ruby
Vagrant.configure("2") do |config|
  # Отключить /vagrant
  config.vm.synced_folder ".", "/vagrant", disabled: true
end
```

**Добавление новой папки:**

```ruby
Vagrant.configure("2") do |config|
  # Базовая синхронизация
  config.vm.synced_folder "src/", "/srv/website"
  
  # С указанием владельца
  config.vm.synced_folder "src/", "/srv/website",
    owner: "www-data",
    group: "www-data",
    mount_options: ["dmode=775,fmode=664"]
end
```

**NFS для производительности (Linux/macOS):**

```ruby
config.vm.synced_folder "src/", "/srv/website", type: "nfs"

# С дополнительными опциями
config.vm.synced_folder "src/", "/srv/website",
  type: "nfs",
  nfs_udp: false,
  mount_options: ["rw,vers=3,tcp,actimeo=1"]
```

**Установка NFS на хосте (Ubuntu/Debian):**

```bash
sudo apt-get install -y nfs-kernel-server
```

**rsync для односторонней синхронизации:**

```ruby
config.vm.synced_folder "src/", "/srv/website",
  type: "rsync",
  rsync__exclude: [".git/", "node_modules/", ".vagrant/"],
  rsync__args: ["--verbose", "--archive", "--delete", "-z"]
```

**Ручная синхронизация rsync:**

```bash
vagrant rsync
vagrant rsync-auto  # Автоматическая синхронизация при изменениях
```

### Сценарий 2: Управление дисками (Libvirt)

**Увеличение основного диска:**

```ruby
config.vm.provider "libvirt" do |libvirt|
  # Увеличить корневой диск до 15GB (если текущий меньше)
  libvirt.machine_virtual_size = 15
end
```

> `machine_virtual_size` только увеличивает диск, но не уменьшает.

**Добавление дополнительного диска:**

```ruby
config.vm.provider "libvirt" do |libvirt|
  libvirt.storage_pool_name = "default"
  
  libvirt.storage :file,
    size: "30G",
    type: "qcow2",      # Формат диска
    bus: "virtio",      # Контроллер для производительности
    name: "data-disk.qcow2",
    cache: "none"       # Режим кэширования
end
```

**Несколько дополнительных дисков:**

```ruby
config.vm.provider "libvirt" do |libvirt|
  # Основной дополнительный диск
  libvirt.storage :file, size: "50G", type: "qcow2"
  
  # Диск для данных
  libvirt.storage :file, size: "100G", type: "qcow2"
  
  # Быстрый диск для кэша
  libvirt.storage :file, size: "10G", type: "raw"
end
```

**Форматирование и монтирование диска внутри ВМ:**

```bash
# После запуска ВМ
sudo fdisk -l                    # Найти новый диск (например, /dev/vdb)
sudo mkfs.ext4 /dev/vdb          # Форматировать
sudo mkdir /data                 # Создать точку монтирования
sudo mount /dev/vdb /data        # Смонтировать

# Для автоматического монтирования добавить в /etc/fstab
echo "/dev/vdb /data ext4 defaults 0 0" | sudo tee -a /etc/fstab
```

### Сценарий 3: Временные файлы и исключения

**Исключение директорий из синхронизации:**

```ruby
config.vm.synced_folder ".", "/vagrant",
  rsync__exclude: [
    ".git/",
    "node_modules/",
    "vendor/",
    "*.log",
    ".vagrant/"
  ]
```

**Отключение синхронизации для больших директорий:**

```ruby
# Отключить для директории с бинарниками
config.vm.synced_folder "binaries/", "/tmp/binaries", disabled: true
```

### Сценарий 4: Настройка для VirtualBox

**Включение поддержки общих папок:**

```ruby
config.vm.provider "virtualbox" do |v|
  v.name = "my-vm"
  v.memory = 2048
  
  # Включение поддержки общих папок
  v.customize ["setextradata", :id, "VBoxInternal2/SharedFolders/EnableSymlinks", "1"]
end
```

**Настройка размера видеопамяти для GUI:**

```ruby
config.vm.provider "virtualbox" do |v|
  v.gui = true
  v.vram = 128
end
```

## Дополнительная информация

### Проблемы и решения

| Проблема | Решение |
| --- | --- |
| Медленная синхронизация | Использовать `type: "nfs"` или `type: "rsync"` |
| Ошибки прав доступа | Указать `owner` и `group` явно |
| NFS не работает | Проверить firewall, установить `nfs-kernel-server` |
| Disk full | Увеличить `machine_virtual_size` или добавить диск |

### Лучшие практики

1. **Исключайте лишнее:** Добавляйте в `rsync__exclude` директории `node_modules/`, `.git/`, `vendor/`.

2. **Используйте NFS для разработки:** На Linux/macOS NFS даёт лучшую производительность для больших проектов.

3. **Разделяйте данные и код:** Код — в общих папках, данные (БД, логи) — на виртуальных дисках.

4. **Монтируйте диски правильно:** Используйте `virtio` контроллер для лучшей производительности в Libvirt.

### Диагностика

```bash
# Проверить смонтированные файловые системы
vagrant ssh -c "df -h"

# Проверить доступные диски
vagrant ssh -c "lsblk"

# Проверить общие папки
vagrant ssh -c "mount | grep vagrant"
```

Решение проблем с синхронизацией описано в [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md), полный синтаксис конфигурации — в [Vagrantfile Reference](./vagrantfile.md).
