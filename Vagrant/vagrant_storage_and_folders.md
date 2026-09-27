# Управление хранилищем и общими папками в Vagrant

## Определения

**Общая папка (Synced Folder)** — программный механизм синхронизации директорий между хост-системой и гостевой операционной системой виртуальной машины (ВМ). Позволяет работать с исходным кодом проекта на хосте, выполняя и тестируя его в изолированном окружении.

**Виртуальный диск (Virtual Disk)** — логическое блочное устройство, используемое ВМ для хранения данных (ОС, базы данных, кэш). Может быть основным (root) или дополнительным (data).

**Точка монтирования (Mount Point)** — директория в файловой системе гостевой ОС, через которую осуществляется доступ к содержимому общей папки или виртуального диска.

**Guest Additions (Гостевые дополнения)** — набор драйверов и сервисов, поставляемый гипервизором (VirtualBox Guest Additions, QEMU Guest Agent). Обеспечивают точное время, буфер обмена, общие папки `vboxsf`, динамическое изменение разрешения экрана. Drift версий Guest Additions между хостом и гостем — частая причина падения производительности общих папок и некорректного определения размера диска.

**Propagation (Propagation Mode)** — политика распространения событий монтирования между пространствами имён mount namespace. Режимы: `private` (по умолчанию, события не распространяются), `shared` (события распространяются), `slave` (принимает события только от родителя). Критичен для Docker-in-Vagrant и сложных оркестраций.

**vagrant-disk plugin** — официальный плагин для декларативного управления дисками (`config.vm.disk`). Позволяет создавать, переименовывать и расширять виртуальные диски без ручного обращения к CLI провайдера. Сохраняет диски при `vagrant reload`, но не при `vagrant destroy` (если не настроено иное).

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

### Справочник параметров `config.vm.synced_folder`

| Параметр | Тип | Назначение | Пример |
| :--- | :--- | :--- | :--- |
| `type` | String | Протокол синхронизации | `"nfs"`, `"virtiofs"`, `"rsync"`, `"smb"`, `"virtualbox"` |
| `disabled` | Boolean | Отключить стандартную папку `/vagrant` | `disabled: true` |
| `owner` | String/numeric | Владелец точки монтирования внутри ВМ | `owner: "www-data"` |
| `group` | String/numeric | Группа точки монтирования | `group: "www-data"` |
| `mount_options` | Array | Опции монтирования Linux (аналоги `mount -o`) | `mount_options: ["dmode=755,fmode=644"]` |
| `create` | Boolean | Создать целевую директорию, если её нет | `create: true` |
| `rsync__exclude` | Array | Исключения для rsync | `rsync__exclude: [".git/", "node_modules/"]` |
| `rsync__args` | Array | Дополнительные флаги rsync | `rsync__args: ["--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r"]` |
| `rsync__auto` | Boolean | Запустить `vagrant rsync-auto` фоном | `rsync__auto: true` |
| `nfs_version` | Numeric | Версия NFS | `nfs_version: 4` |
| `nfs_udp` | Boolean | Использовать UDP для NFS | `nfs_udp: false` |
| `smb_username` | String | Имя пользователя для SMB/CIFS | `smb_username: "vagrant"` |
| `smb_password` | String | Пароль для SMB/CIFS | `smb_password: "secret"` |
| `id` | String | Явный идентификатор монтирования | `id: "app-sync"` |

### Справочник параметров `config.vm.disk`

| Параметр | Тип | Назначение | Пример |
| :--- | :--- | :--- | :--- |
| `name` | String | Уникальный идентификатор диска | `name: "database_storage"` |
| `size` | String | Размер диска | `size: "50GB"` |
| `primary` | Boolean | Является ли диск системным | `primary: false` |
| `type` | String | Тип диска (`disk` или `dvd`) | `type: "disk"` |

### Провайдер-специфичные особенности

**VirtualBox:**
- Общие папки: протокол `vboxsf` (Guest Additions). Требует плагин `vagrant-vbguest` для автоматического обновления гостевых дополнений при несовпадении версий хоста и гостя.
- Диски: формат `vmdk`. Дополнительные диски создаются как `vdi`/`vmdk` и подключаются через `VBoxManage storageattach`. Удаление диска при `destroy` управляется параметром провайдера.

**Libvirt/QEMU:**
- Общие папки: протокол `virtiofs` (рекомендуется, требует ядро ≥5.4 в гостевой ОС и Vagrant 2.4+). Альтернатива — `9p` (legacy). NFS работает через `private_network`.
- Диски: формат `qcow2` (поддерживает сжатие, snapshots, thin provisioning). Пулы хранилища управляются через `virsh pool-*`. Дополнительные диски `config.vm.disk` создаются в пуле по умолчанию.

**QEMU (Apple Silicon / `vagrant-qemu`):**
- Общие папки: `virtiofs` через `-virtfs` в CLI QEMU. Требует корректной настройки `virtiofsd` на хосте.
- Диски: формат `qcow2` или `img`. Размер задаётся через `lv.disk_size`.

**VMware:**
- Общие папки: `vmhgfs` (VMware HGFS). Требует плагин `vagrant-vmware-desktop` и установленных open-vm-tools внутри гостевой ОС.
- Диски: формат `vmdk`. Поддерживает динамическое расширение.

**Hyper-V:**
- Общие папки: нет нативного高性能 протокола общих папок. Используется SMB или развёртывание через `vagrant rsync`.
- Диски: формат `vhd`/`vhdx`. Динамическое расширение поддерживается нативно.

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

### Сценарий 6: Настройка NFS-экспорта на хосте Linux

NFS требует, чтобы хост-машина выступала в роли сервера экспорта. При использовании `config.vm.synced_folder` с `type: "nfs"` Vagrant автоматически добавляет запись в `/etc/exports` (требует `sudo`). Для статических конфигураций или air-gapped окружений настройте экспорт вручную.

```bash
# 1. Создание директории для общего доступа
sudo mkdir -p /srv/vagrant-nfs/project
sudo chown -R $(id -u):$(id -g) /srv/vagrant-nfs/project

# 2. Добавление в /etc/exports (подставьте IP гостевой ВМ)
echo "/srv/vagrant-nfs/project 192.168.56.10(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports

# 3. Экспорт и перезагрузка демона
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server

# 4. Проверка экспорта
sudo exportfs -v
# → /srv/vagrant-nfs/project 192.168.56.10(rw,wdelay,root_squash,no_subtree_check)
```

```ruby
# Vagrantfile
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.network "private_network", ip: "192.168.56.10"
  
  config.vm.synced_folder "/srv/vagrant-nfs/project", "/vagrant",
    type: "nfs",
    nfs_version: 4,
    nfs_udp: false,
    mount_options: ["actimeo=1", "rw", "vers=4.2"]
end
```

### Сценарий 7: rsync для CI/CD и односторонней синхронизации

`rsync` идеален для пайплайнов, где исходный код копируется с хоста (runner) в ВМ, но не требуется обратная синхронизация. Исключение кэша и логов критично для скорости.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  config.vm.synced_folder ".", "/app",
    type: "rsync",
    rsync__exclude: [".git/", "node_modules/", "vendor/", "*.log", ".vagrant/"],
    rsync__args: ["--verbose", "--archive", "--delete", "-z", "--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r"],
    rsync__auto: false # В CI включать только при явном vagrant rsync
end
```

```bash
# В CI/CD этапе (GitLab CI / GitHub Actions)
# 1. Синхронизация
vagrant rsync

# 2. Запуск провижининга
vagrant provision

# 3. Валидация
vagrant ssh -c "ls -la /app"
```

### Сценарий 8: Полное управление жизненным циклом дисков

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Системный диск расширяется автоматически при создании ВМ
  # (зависит от box; для bento/ubuntu-24.04 поддерживается auto-resize)
  
  # Дополнительный диск для данных
  config.vm.disk :disk,
    name: "database_storage",
    size: "50GB",
    primary: false
end
```

**Расширение диска через плагин vagrant-disk (preferred):**

```bash
# 1. Список дисков
vagrant disk list
# → database_storage  /Users/mac/notes/.vagrant/machines/default/libvirt/disk_database_storage.vdi  (50 GB)

# 2. Расширение
vagrant disk resize --name database_storage --size 100GB

# 3. Перезагрузка ВМ
vagrant reload
```

**Расширение диска через CLI провайдера (fallback):**

```bash
# Libvirt/QEMU
qemu-img resize /var/lib/libvirt/images/<vm_name>.qcow2 +50G

# VirtualBox
VBoxManage modifyhd /path/to/disk.vdi --resize 102400
```

**Расширение раздела внутри гостевой ОС:**

```bash
# Для GPT-разделов (cloud-image, Ubuntu 22.04+)
vagrant ssh -c "sudo growpart /dev/vda 1"
vagrant ssh -c "sudo resize2fs /dev/vda1"

# Для XFS (увеличение без growpart)
vagrant ssh -c "sudo xfs_growfs -d /data"

# Для LVM
vagrant ssh -c "sudo pvresize /dev/vdb"
vagrant ssh -c "sudo lvextend -l +100%FREE /dev/mapper/vg0-data"
vagrant ssh -c "sudo resize2fs /dev/mapper/vg0-data"
```

**Верификация:**

```bash
vagrant ssh -c "lsblk"
vagrant ssh -c "df -h /data"
```

### Сценарий 9: Восстановление данных из неработающей ВМ

Если ВМ не загружается, но диск сохранён на хосте, данные можно извлечь напрямую без запуска гостевой ОС.

```bash
# 1. Определение расположения диска
# Libvirt
sudo find /var/lib/libvirt/images -name "*.qcow2" | grep <vm_name>
# VirtualBox
VBoxManage list hdds | grep -B2 "<vm_name>"

# 2. Монтирование диска на хосте (read-only)
sudo apt-get install -y libguestfs-tools
sudo guestmount -a /var/lib/libvirt/images/<vm_name>.qcow2 -i --ro /mnt/vm-recovery

# 3. Копирование данных
sudo cp -r /mnt/vm-recovery/home/vagrant/project ./recovered/

# 4. Размонтирование
sudo guestunmount /mnt/vm-recovery
```

```bash
# Альтернатива: подключение диска как второго к рабочей ВМ
# Libvirt: Attach disk to another running VM
virsh attach-disk <running_vm> /var/lib/libvirt/images/<vm_name>.qcow2 vdb --type disk --mode readonly
```

### Сценарий 10: Диагностика проблем с монтированием

Пошаговая процедура при ошибке `Mounting shared folders failed`.

```bash
# 1. Проверка типа монтирования внутри ВМ
vagrant ssh -c "findmnt -t nfs4,virtiofs,vboxsf,9p,smbfs"
# → /vagrant  /Users/mac/project  virtiofs  rw,relatime...

# 2. Проверка логов гипервизора
# Libvirt
sudo journalctl -u libvirtd -n 100 | grep -i -E "error|fail|virtiofs"
# VirtualBox
VBoxManage list runningvms
VBoxManage showvminfo <vm_name> | grep -i "shared folder"

# 3. Проверка доступности NFS с хоста (если используется NFS)
sudo rpcinfo -p 192.168.56.10 | grep nfs

# 4. Проверка прав на директории хоста
ls -la /srv/vagrant-nfs/project
namei -l /srv/vagrant-nfs/project
```

**Типичные ошибки:**

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Mounting shared folders failed` | Несовпадение версий Guest Additions | `vagrant plugin install vagrant-vbguest && vagrant reload` |
| `Stale file handle` | NFS-сервер недоступен, hard-mount | `vagrant halt && vagrant up` или переключение на `virtiofs`/`rsync` |
| `Permission denied` | Неправильные права на хост-директории | `sudo chown -R $(id -u):$(id -g) /path/to/host/dir` |
| `mount: wrong fs type` | Отсутствует модуль ядра (virtiofs) | Проверьте `uname -r >= 5.4` и модуль `virtiofs` в гостевой ОС |
| `mount.nfs: access denied` | NFS-экспорт не настроен или firewall блокирует | `sudo exportfs -v`, проверьте порты 2049/tcp |

### Сценарий 11: Персистентность данных при `vagrant destroy`

По умолчанию `vagrant destroy` удаляет ВМ и **все** связанные диски, описанные в `Vagrantfile` через `config.vm.disk`. Для сохранения данных на хосте переименуйте диск или используйте внешний пул.

```bash
# 1. Список дисков перед destroy
vagrant disk list

# 2. Ручное переименование (чтобы vagrant-disk plugin не нашёл диск по имени)
mv /var/lib/libvirt/images/vagrant_default_database_storage.qcow2 \
   /var/lib/libvirt/images/saved_database_storage.qcow2

# 3. destroy ВМ
vagrant destroy -f

# 4. Возврат исходного имени
mv /var/lib/libvirt/images/saved_database_storage.qcow2 \
   /var/lib/libvirt/images/vagrant_default_database_storage.qcow2

# 5. Пересоздание ВМ — диск останется
vagrant up
```

**Важно:** Общие папки (synced folders) **не** сохраняются при `destroy` независимо от протокола, так как это механизм монтирования, а не физическое хранилище. Для персистентных данных используйте виртуальные диски или внешние NAS/SAN (согласно scope — без облачных технологий).

### Сценарий 12: Отключение стандартной папки `/vagrant` и безопасная конфигурация

Стандартная папка `/vagrant` монтируется автоматически и может создавать проблемы с правами или безопасностью. Отключите её и замените на явные правила.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Отключение стандартной папки /vagrant
  config.vm.synced_folder ".", "/vagrant", disabled: true
  
  # Только исходный код (read-only для гостя)
  config.vm.synced_folder "src/", "/opt/app/src",
    type: "virtiofs",
    mount_options: ["ro"]
  
  # Артефакты сборки (read-write, owner = текущий пользователь хоста)
  config.vm.synced_folder "build/", "/opt/app/build",
    type: "nfs",
    mount_options: ["rw", "no_root_squash"]
  
  # Конфигурации (только для чтения, owner = root)
  config.vm.synced_folder "config/", "/etc/myapp/conf",
    owner: "root",
    group: "root",
    mount_options: ["ro", "dmode=755,fmode=644"]
end
```

```bash
# Верификация
vagrant up
vagrant ssh -c "ls -la /vagrant"
# → ls: cannot access '/vagrant': No such file or directory
vagrant ssh -c "ls -la /opt/app/src"
vagrant ssh -c "mount | grep -E 'virtiofs|nfs'"
```

## Дополнительная информация

### Guest Additions drift и автоматическое обновление

Drift версий гостевых дополнений — частая причина падения производительности общих папок и некорректного определения размера диска в VirtualBox.

```bash
# 1. Проверка версии Guest Additions в гостевой ОС
vagrant ssh -c "cat /opt/VBoxGuestAdditions-*/version"

# 2. Проверка версии хоста
VBoxManage --version

# 3. Автоматическое исправление через vagrant-vbguest
vagrant plugin install vagrant-vbguest
vagrant up # Плагин автоматически проверит и обновит Guest Additions
```

Для Libvirt/QEMU используется `qemu-guest-agent`, который устанавливается внутри гостевой ОС:

```bash
# Ubuntu/Debian внутри ВМ
sudo apt-get install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
```

### Персистентность данных и влияние `vagrant destroy`

| Хранилище | Сохраняется при `vagrant destroy` | Примечание |
| :--- | :--- | :--- |
| Общие папки (любой тип) | Нет | Это механизм монтирования, а не физическое хранилище |
| `config.vm.disk` (Libvirt) | Нет (по умолчанию) | Диск удаляется вместе с доменом Libvirt |
| `config.vm.disk` с внешним пулом | Да | Если диск создан в пуле, не управляемом Vagrant |
| Внешний NAS/SAN | Да | Подключение через iSCSI/NFS напрямую к гостю (вне Vagrant) |

### Диагностика и типичные ошибки

1.  **Зависание NFS:** Проверьте, разрешены ли порты на хосте:
    ```bash
    # Для Linux (UFW)
    sudo ufw allow from 192.168.56.0/24 to any port nfs
    # Для firewalld
    sudo firewall-cmd --add-service=nfs --permanent
    sudo firewall-cmd --reload
    ```
2.  **Ошибка Guest Additions (VirtualBox):**
    ```bash
    vagrant plugin install vagrant-vbguest
    ```
3.  **Проверка монтирования:**
    ```bash
    vagrant ssh -c "findmnt -t nfs4,virtiofs,vboxsf,9p,smbfs"
    ```
4.  **Проверка места на диске хоста:**
    ```bash
    df -hT ~/.vagrant.d /var/lib/libvirt/images
    ```
5.  **Очистка сиротских дисков Libvirt:**
    ```bash
    virsh --connect qemu:///system pool-list --all
    virsh --connect qemu:///system vol-list default
    virsh --connect qemu:///system vol-delete --pool default <volume_name>.qcow2
    ```
6.  **Очистка сиротских дисков VirtualBox:**
    ```bash
    VBoxManage list hdds
    VBoxManage closemedium disk <uuid> --delete
    ```

### Лучшие практики

1.  **Изоляция данных:** Храните базы данных только на **виртуальных дисках**, а не в общих папках, чтобы избежать повреждения данных из-за особенностей сетевых протоколов (NFS/SMB).
2.  **Исключения:** Всегда настраивайте `rsync__exclude` для директорий с кэшем и логами.
3.  **Безопасность:** Используйте `mount_options: ["ro"]` (Read-Only) для папок с конфигурациями, которые ВМ не должна изменять. Отключайте стандартную папку `/vagrant` через `disabled: true` и создавайте явные правила синхронизации.
4.  **Удаление ресурсов:** Помните, что `vagrant destroy` удаляет все диски, описанные в `Vagrantfile`, если не настроено иное через параметры провайдера. Для сохранения критичных данных используйте внешние пулы хранилища.
5.  **Гостевые дополнения:** Для VirtualBox всегда используйте `vagrant-vbguest` в продакшн-окружениях. Для Libvirt убедитесь, что `qemu-guest-agent` установлен и активен.
6.  **Производительность:** Вместо NFS используйте `virtiofs` для однохостовых сценариев на Libvirt/KVM (требует ядро 5.4+ в гостевой ОС). Для Windows-хостов используйте SMB 3.0+ с шифрованием.
7.  **Кэширование rsync:** В CI/CD окружениях используйте `rsync` вместо постоянных общих папок, чтобы снизить нагрузку на файловую систему хоста во время простоя.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — общая структура конфигурации.
- [Vagrant Providers: Libvirt и VirtualBox](./vagrant_providers.md) — специфические настройки хранилищ.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем с монтированием.
