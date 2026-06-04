# Управление хранилищем и общими папками в Vagrant

## Определения

**Общая папка (Synced Folder)** — программный механизм синхронизации директорий между хост-системой и гостевой операционной системой виртуальной машины (ВМ). Позволяет работать с исходным кодом проекта на хосте, выполняя его в изолированном окружении.

**Виртуальный диск (Virtual Disk)** — логическое блочное устройство, представленное в виде файла-образа или раздела, используемое ВМ для хранения данных (ОС, базы данных, логи).

**Точка монтирования (Mount Point)** — директория в файловой системе гостевой ОС, через которую осуществляется доступ к содержимому общей папки или виртуального диска.

## Базовые концепции

### Подходы к хранению данных

| Подход | Описание | Основные сценарии |
| :--- | :--- | :--- |
| **Общие папки** | Синхронизация файлов хост ↔ ВМ | Редактирование кода, конфигурационные файлы |
| **Виртуальные диски** | Изолированное хранилище внутри ВМ | Базы данных, кэш, постоянные данные ОС |

По умолчанию Vagrant синхронизирует корневую директорию проекта (где расположен `Vagrantfile`) в путь `/vagrant` внутри виртуальной машины.

### Типы общих папок

| Тип | Производительность | Платформа | Особенности |
| :--- | :--- | :--- | :--- |
| **Default (VirtualBox)** | Средняя | VirtualBox | Требует Guest Additions |
| **Default (VMware)** | Средняя | VMware | Требует VMware Tools |
| **NFS** | Высокая | Linux / macOS | Быстрый доступ для больших проектов |
| **rsync** | Высокая | Кроссплатформенный | Односторонняя синхронизация (хост → ВМ) |
| **SMB** | Высокая | Windows / macOS | Встроено в ОС Windows |

## Практические сценарии

### Сценарий 1: Настройка общих папок

**Базовая конфигурация и управление доступом:**

```ruby
Vagrant.configure("2") do |config|
  # Отключение стандартной синхронизации /vagrant
  config.vm.synced_folder ".", "/vagrant", disabled: true
  
  # Добавление новой папки с указанием прав доступа
  config.vm.synced_folder "src/", "/var/www/project",
    owner: "www-data",
    group: "www-data",
    mount_options: ["dmode=775,fmode=664"]
end
```

**Использование NFS для высокой производительности (Linux/macOS):**

```ruby
Vagrant.configure("2") do |config|
  config.vm.synced_folder "src/", "/app", type: "nfs"
  
  # Опциональная настройка параметров монтирования
  config.vm.synced_folder "data/", "/mnt/data",
    type: "nfs",
    nfs_udp: false,
    mount_options: ["rw", "vers=3", "tcp", "actimeo=1"]
end
```

**Настройка rsync для исключения лишних файлов:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.synced_folder ".", "/vagrant",
    type: "rsync",
    rsync__exclude: [".git/", "node_modules/", "*.log"],
    rsync__args: ["--verbose", "--archive", "--delete", "-z"]
end
```

### Сценарий 2: Управление дисками (провайдер Libvirt)

**Изменение размера основного диска:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "libvirt" do |libvirt|
    # Увеличение корневого раздела до 20GB
    libvirt.machine_virtual_size = 20
  end
end
```

**Добавление дополнительных дисков:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "libvirt" do |libvirt|
    libvirt.storage_pool_name = "default"
    
    # Создание дополнительного диска для данных
    libvirt.storage :file,
      size: "40G",
      type: "qcow2",
      bus: "virtio",
      name: "extra-storage.qcow2"
  end
end
```

### Сценарий 3: Настройка для VirtualBox

**Включение поддержки символических ссылок:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "virtualbox" do |v|
    v.customize ["setextradata", :id, "VBoxInternal2/SharedFolders/EnableSymlinks", "1"]
  end
end
```

### Сценарий 4: Подготовка диска внутри ВМ

После добавления нового виртуального диска его необходимо инициализировать в гостевой ОС:

```bash
# Поиск нового устройства (например, /dev/vdb)
vagrant ssh -c "lsblk"

# Форматирование и монтирование (пример для ext4)
vagrant ssh -c "sudo mkfs.ext4 /dev/vdb && sudo mkdir -p /data && sudo mount /dev/vdb /data"

# Добавление в /etc/fstab для автозагрузки
echo "/dev/vdb /data ext4 defaults 0 0" | sudo tee -a /etc/fstab
```

## Дополнительная информация

### Диагностика состояния

| Команда | Описание |
| :--- | :--- |
| `df -h` | Проверка использования дискового пространства и точек монтирования |
| `lsblk` | Просмотр списка блочных устройств |
| `mount | grep vagrant` | Проверка активных общих папок |
| `vagrant rsync-auto` | Запуск автоматической синхронизации rsync при изменениях |

### Лучшие практики

1. **Разделение контента:** Храните исходный код в общих папках, а "тяжелые" данные (БД, артефакты) — на виртуальных дисках.
2. **Исключение метаданных:** Всегда добавляйте `.git/`, `.vagrant/` и директории зависимостей (`node_modules/`, `vendor/`) в исключения rsync.
3. **Производительность:** Для разработки на Linux/macOS отдавайте предпочтение NFS перед стандартными методами VirtualBox.
4. **Безопасность:** Явно указывайте `owner` и `group` для общих папок, чтобы избежать проблем с правами доступа к веб-приложениям.

### Решение типичных проблем

- **Низкая скорость записи:** Переключитесь на NFS или rsync.
- **Ошибки монтирования:** Проверьте наличие Guest Additions (для VirtualBox) или установленный пакет `nfs-kernel-server` на хосте (для NFS).
- **Диск не увеличивается:** Убедитесь, что `machine_virtual_size` больше текущего размера диска; уменьшение диска через этот параметр невозможно.

Подробные сценарии устранения ошибок доступны в разделе [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md).

### См. также

- [Vagrantfile Reference](./vagrantfile.md) — справочник параметров конфигурации
- [Продвинутое использование Vagrant](./vagrant_advanced_usage.md) — триггеры и мульти-машинные окружения
- [rsync в Linux](../Linux/SystemAdministration/rsync.md) — детальное описание работы утилиты rsync
