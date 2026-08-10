# Управление хранилищем и общими папками в Vagrant

## Определения

**Общая папка (Synced Folder)** — программный механизм синхронизации директорий между хост-системой и гостевой операционной системой виртуальной машины (ВМ). Позволяет работать с исходным кодом проекта на хосте, выполняя и тестируя его в изолированном окружении.

**Виртуальный диск (Virtual Disk)** — логическое блочное устройство, используемое ВМ для хранения данных (ОС, базы данных, кэш). Может быть основным (root) или дополнительным (data).

**Точка монтирования (Mount Point)** — директория в файловой системе гостевой ОС, через которую осуществляется доступ к содержимому общей папки или виртуального диска.

## Базовые концепции

### Сравнение методов хранения

| Характеристика | Общие папки (Synced Folders) | Виртуальные диски (Disks) |
| :--- | :--- | :--- |
| **Назначение** | Исходный код, конфигурации | БД, логи, тяжелые бинарные данные |
| **Производительность**| Зависит от протокола (NFS/Virtiofs) | Максимальная (нативная ФС внутри ВМ) |
| **Синхронизация** | Двусторонняя (кроме rsync) | Отсутствует (только внутри ВМ) |
| **Доступность** | Хост и ВМ одновременно | Только ВМ |

### Типы общих папок

| Тип | Провайдер | Скорость | Особенности |
| :--- | :--- | :--- | :--- |
| **VirtualBox Shared**| VirtualBox | Средняя | Требует Guest Additions. Проблемы с правами доступа. |
| **NFS** | Linux / macOS | Высокая | Рекомендуется для больших проектов. Требует статический IP. |
| **Virtiofs** | Libvirt / QEMU | Экстремальная| Современный стандарт для KVM. Требует ядро 5.4+. |
| **rsync** | Любой | Высокая | Односторонняя (Host -> VM). Идеально для CI/CD. |
| **SMB** | Windows | Высокая | Стандарт для Windows-хостов (CIFS). |

## Практические сценарии

### Сценарий 1: Конфигурация общих папок с маппингом прав

Для корректной работы веб-серверов или баз данных внутри ВМ необходимо явно указывать владельца и права.

```ruby
Vagrant.configure("2") do |config|
  # Отключение стандартной синхронизации /vagrant (для безопасности)
  config.vm.synced_folder ".", "/vagrant", disabled: true
  
  # Монтирование с кастомными правами
  config.vm.synced_folder "src/", "/var/www/html",
    owner: "www-data",
    group: "www-data",
    mount_options: ["dmode=755,fmode=644"]
end
```

### Сценарий 2: Использование NFS для высокой производительности

NFS требует настройки `private_network` для связи гостя с хостом.

```ruby
Vagrant.configure("2") do |config|
  config.vm.network "private_network", ip: "192.168.56.10"
  
  config.vm.synced_folder ".", "/vagrant", 
    type: "nfs",
    nfs_version: 4,
    nfs_udp: false,
    mount_options: ["actimeo=1"] # Отключение кэширования атрибутов для мгновенного обновления
end
```

### Сценарий 3: Virtiofs (Libvirt / QEMU)

Обеспечивает производительность, близкую к локальному диску, за счет разделяемой памяти. Требует Vagrant 2.4+ и плагин `vagrant-libvirt`.

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "libvirt" do |lv|
    lv.memory = 2048
    lv.nic_model_type = "virtio"
  end

  config.vm.synced_folder ".", "/vagrant", 
    type: "virtiofs",
    virtiofs_direct_io: true # Ускорение I/O за счет обхода кэша гостя
end
```

### Сценарий 4: Управление дополнительными дисками (Vagrant Disk)

Механизм позволяет декларативно добавлять диски, которые сохраняются при `vagrant reload`.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Создание дополнительного диска для БД
  config.vm.disk :disk, 
    name: "database_storage", 
    size: "50GB",
    primary: false # Не является системным
end
```

**Операции через CLI:**
```bash
# Список всех дисков проекта и их путей в хост-системе
vagrant disk list

# Расширение диска (требует последующего resizefs внутри ВМ)
vagrant disk resize --name database_storage --size 100GB
```

### Сценарий 5: Ручная инициализация диска в Linux

Если провижинер не обрабатывает диски автоматически, выполните следующие шаги:

```bash
# 1. Определение устройства (обычно /dev/vdb в libvirt или /dev/sdb в VirtualBox)
vagrant ssh -c "lsblk"

# 2. Создание файловой системы XFS (рекомендуется для больших данных)
vagrant ssh -c "sudo mkfs.xfs /dev/vdb"

# 3. Настройка персистентного монтирования
vagrant ssh -c "sudo mkdir -p /data && \
  echo '/dev/vdb /data xfs defaults,nofail 0 2' | sudo tee -a /etc/fstab && \
  sudo mount -a"
```

## Дополнительная информация

### Тонкая настройка rsync

Метод `rsync` идеален для проектов с огромным количеством файлов (например, `node_modules`), так как не создает нагрузки на файловую систему в режиме ожидания.

```ruby
config.vm.synced_folder ".", "/app",
  type: "rsync",
  rsync__exclude: [".git/", "node_modules/", "*.log"],
  rsync__args: ["--verbose", "--archive", "--delete", "-z"],
  rsync__auto: true # Автоматический запуск vagrant rsync-auto
```

### Диагностика и типичные ошибки

1.  **Зависание NFS:** Проверьте, разрешены ли порты на хосте:
    ```bash
    # Для Linux (UFW)
    sudo ufw allow from 192.168.56.0/24 to any port nfs
    ```
2.  **Ошибка Guest Additions (VirtualBox):**
    ```bash
    vagrant plugin install vagrant-vbguest
    ```
3.  **Проверка монтирования:**
    ```bash
    vagrant ssh -c "findmnt -t nfs4,virtiofs,vboxsf"
    ```

### Лучшие практики

1.  **Изоляция данных:** Храните базы данных только на **виртуальных дисках**, а не в общих папках, чтобы избежать повреждения данных из-за особенностей сетевых протоколов (NFS/SMB).
2.  **Исключения:** Всегда настраивайте `rsync__exclude` для директорий с кэшем и логами.
3.  **Безопасность:** Используйте `mount_options: ["ro"]` (Read-Only) для папок с конфигурациями, которые ВМ не должна изменять.
4.  **Удаление ресурсов:** Помните, что `vagrant destroy` удаляет все диски, описанные в `Vagrantfile`, если не настроено иное через параметры провайдера.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — общая структура конфигурации.
- [Vagrant Providers: Libvirt и VirtualBox](./vagrant_providers.md) — специфические настройки хранилищ.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем с монтированием.
- [Монтирование дисков в Linux](../Linux/FileSystems/mounting/index.md) — подробнее о параметрах `fstab` и `mount`.
