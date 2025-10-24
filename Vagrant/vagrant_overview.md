# Vagrant

Vagrant — это инструмент с открытым исходным кодом для создания и управления виртуализированными средами разработки. Он позволяет легко воссоздавать окружения, описанные в конфигурационном файле `Vagrantfile`.

## Установка (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y curl gpg apt-transport-https
```

### Добавьте GPG-ключ HashiCorp
Этот ключ проверяет подлинность пакетов.
```bash
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
```

### Добавьте репозиторий HashiCorp
```bash
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
```

### Установите Vagrant
```bash
sudo apt-get update
sudo apt-get install -y vagrant=2.4.9
```

## Базовый рабочий процесс

### Инициализация проекта
Создайте директорию проекта и выполните `vagrant init`, чтобы сгенерировать `Vagrantfile`.

```bash
# Инициализация с использованием образа (box) Ubuntu 22.04
vagrant init ubuntu/jammy64
```
Будет создан минимальный `Vagrantfile`:
```ruby
# Vagrantfile
Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
  config.vm.box_version = "20240912.0.0"
end
```

### Запуск окружения
Команда `vagrant up` скачивает box (если его нет в кэше), создает и запускает виртуальную машину.

```bash
# Запуск с указанием провайдера (например, VirtualBox)
vagrant up --provider=virtualbox
```

### Подключение по SSH
Vagrant автоматически настраивает SSH-доступ.

```bash
# Посмотреть параметры для SSH-подключения
vagrant ssh-config

# Подключиться к машине
vagrant ssh
```

### Проверка статуса
Команда `vagrant status` показывает состояние управляемых машин.

```bash
vagrant status
```

### Перезагрузка и Provisioning
Для применения изменений в `Vagrantfile` или повторного запуска скриптов настройки (provisioning) используются команды:

```bash
# Перезагрузить машину для применения изменений
vagrant reload

# Запустить provisioning на работающей машине
vagrant provision

# Перезагрузить и применить provisioning
vagrant reload --provision
```

### Удаление окружения
Команда `vagrant destroy` останавливает и удаляет виртуальную машину и все связанные с ней ресурсы.

```bash
vagrant destroy -f # -f для подтверждения без запроса
```

---

## Детальная конфигурация Vagrantfile (Cheat Sheet)

Vagrant позволяет гибко настраивать виртуальную машину через `Vagrantfile`, включая память, CPU, сеть, диски, общие папки и многое другое. Ниже представлен разбор ключевых и продвинутых параметров с акцентом на `libvirt`/QEMU, но многие из них универсальны.

### Настройки VM и Гипервизора

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.box` | `"ubuntu2404_base"` | Базовый образ (box) |
| `config.vm.hostname` | `"suricata-diplom"` | Имя хоста внутри VM |
| `config.vm.provider` | `"libvirt"` | Провайдер (VirtualBox, libvirt, VMware) |
| `libvirt.memory` | `2048` | RAM в МБ |
| `libvirt.cpus` | `2` | Количество CPU |
| `libvirt.disk_bus` | `'virtio'` | Тип дискового контроллера (лучшая производительность) |
| `libvirt.nic_model_type` | `'virtio'` | Модель сетевой карты (лучшая производительность) |
| `libvirt.graphics_type` | `'vnc'` | Графический интерфейс (vnc, spice) |
| `libvirt.arch` | `'x86_64'` | Архитектура CPU |
| `libvirt.os_type` | `'linux'` | Тип OS (linux, windows) |

### Сеть

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.network "forwarded_port"` | `guest: 80, host: 8080` | Проброс портов с хоста в гостевую ОС(порт 80 гостевой машины будет доступен на порту 8080 хоста) |
| `config.vm.network "private_network"` | `ip: "192.168.50.4"` | Host-only сеть с фиксированным IP (доступна только с хоста) |
| `config.vm.network "public_network"` | — | Bridged-сеть (VM видна в локальной сети) |

### Общие папки (Synced Folders)

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.synced_folder` | `"./data", "/vagrant_data", type: "rsync"` | Синхронизация папок хост ↔ VM |
| `disabled: true` | `config.vm.synced_folder ".", "/vagrant", disabled: true` | Отключает стандартную общую папку `/vagrant` |
| `type: "nfs"` | `type: "nfs"` | Использовать NFS для быстрого доступа (рекомендуется для Linux) |

### Provisioning (Автоматическая настройка)

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.provision "shell"` | `inline: "apt-get update"` | Bash-скрипт для установки ПО |
| `config.vm.provision "ansible"` | `playbook: "site.yml"` | Ansible playbook |
| `config.vm.provision "puppet"` | `manifest: "default.pp"` | Puppet-манифесты |
| `config.vm.provision "docker"` | `run: "nginx"` | Запуск Docker-контейнеров внутри VM |

### Хранилище и диски (libvirt)

| Параметр | Пример | Описание |
| --- | --- | --- |
| `libvirt.storage :file, size: '20G'` | — | Дополнительный диск на 20GB |
| `libvirt.disk_bus` | `'virtio'` | Тип контроллера диска |
| `libvirt.storage_pool_name` | `"default"` | Пул хранения для дисков VM |

### Пользователь и SSH-доступ

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.ssh.username` | `"vagrant"` | Имя пользователя для SSH |
| `config.ssh.private_key_path` | `"~/.vagrant.d/insecure_private_key"` | Путь к приватному ключу SSH |
| `config.vm.network "forwarded_port"` | `guest: 22, host: 2222` | Проброс SSH-порта на другой порт хоста |

### Прочие параметры

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.box_check_update` | `false` | Отключить проверку обновлений box'а при старте |
| `config.vm.boot_timeout` | `600` | Время ожидания загрузки VM в секундах |
| `libvirt.cloud_init` | `true` | Использовать cloud-init для настройки VM |
| `libvirt.nested` | `true` | Разрешить вложенную виртуализацию (KVM внутри KVM) |

---

### Шаблон Vagrantfile для VirtualBox

```ruby
Vagrant.configure("2") do |config|
  # Имя хоста
  config.vm.hostname = "my-vm"

  # Отключить проверку обновлений box'а при старте
  config.vm.box_check_update = false

  # Настройки провайдера (например, VirtualBox)
  config.vm.provider "virtualbox" do |v|
    v.memory = 2048 # Память в МБ
    v.cpus = 2     # Количество CPU
    v.name = "my-app-vm" # Имя в интерфейсе VirtualBox
  end
end
```

## Провайдеры и образы (Boxes)

### Поиск образов (Boxes)

Найти нужный образ Vagrant можно на официальном портале: **[HashiCorp Vagrant Cloud](https://portal.cloud.hashicorp.com/vagrant/discover)**.

Портал позволяет фильтровать образы по поддержке определенного провайдера виртуализации, например, `libvirt`, `virtualbox`, `hyperv` и др.

### Настройка провайдера

Вы можете указать, какой провайдер использовать, и настроить его параметры прямо в `Vagrantfile`.

**Пример настройки libvirt-провайдера:**
```ruby
Vagrant.configure("2") do |config|
  # ... другие настройки ...

  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 2048
    libvirt.cpus = 2
    # Использование virtio для лучшей производительности дисков и сети
    libvirt.disk_bus = 'virtio'
    libvirt.nic_model_type = 'virtio'
  end

  # 3. Сеть (приватная сеть с фиксированным IP)
  config.vm.network "private_network", ip: "192.168.50.4"
  
  # 4. Отключение общей папки, для включения этой функции необходимо изменить true на false, после перезапуска вм с этой настройкой папка хоста в которой находиться запускаемый Vagranfile станет общей, а файлы с синхронизированной папки хоста будут в режиме реального времени появляться в вм(сихронизация работает в обе стороны) без необходимости с перезагрузки
  config.vm.synced_folder ".", "/vagrant", disabled: true

  # 5. Автоматическая установка ПО (provisioning)
  config.vm.provision "shell", inline: <<-SHELL
    apt-get update
    apt-get install -y suricata
  SHELL
end
```

### Смена провайдера

Чтобы сменить провайдера для существующего проекта (например, с VirtualBox на libvirt), необходимо **удалить директорию `.vagrant`** в каталоге с `Vagrantfile`. После этого команда `vagrant up` будет использовать нового провайдера, указанного в конфигурации.

```bash
# Удалить метаданные текущего провайдера
rm -rf .vagrant

# Запустить окружение с новым провайдером
vagrant up --provider=libvirt
```

## Provisioning

Provisioning позволяет автоматически устанавливать ПО и выполнять настройки при создании машины.

### Пример: установка Nginx с помощью shell-скрипта

1.  **Создайте скрипт `provision.sh`:**
    ```bash
    #!/bin/bash
    set -euo pipefail # Останавливать скрипт при ошибках

    # Обновление пакетов
    apt-get update -y

    # Установка Nginx
    apt-get install -y nginx

    # Запуск и добавление в автозагрузку
    systemctl enable nginx
    systemctl start nginx
    ```

2.  **Подключите скрипт в `Vagrantfile`:**
    ```ruby
    Vagrant.configure("2") do |config|
      config.vm.provision :shell, path: "provision.sh"
    end
    ```
    При следующем `vagrant up` или `vagrant provision` скрипт будет выполнен.

## Продвинутые сценарии

### Управление несколькими машинами

`Vagrantfile` позволяет описывать и управлять группой машин из одного файла.

```ruby
# Описание узлов в виде массива хэшей
nodes = [
    { hostname: 'node1', ip: '192.168.56.11', box: "ubuntu/jammy64", version: "20240912.0.0" },
    { hostname: 'node2', ip: '192.168.56.12', box: "ubuntu/jammy64", version: "20240912.0.0" }
]

Vagrant.configure("2") do |config|
    nodes.each do |node|
        config.vm.define node[:hostname] do |node_config|
            node_config.vm.box = node[:box]
            node_config.vm.box_version = node[:version]
            node_config.vm.hostname = node[:hostname]
            node_config.vm.network :private_network, ip: node[:ip]
            
            node_config.vm.provider :virtualbox do |vb|
                vb.memory = 1024
                vb.cpus = 1
            end
            
            # Пример inline-скрипта
            node_config.vm.provision "shell", inline: "apt-get update && apt-get install -y tree"
        end
    end
end
```

### Интеграция с Tailscale

Этот пример использует плагин `vagrant-env` для безопасной передачи `TAILSCALE_AUTHKEY`.

```ruby
# 1. Установите плагин: vagrant plugin install vagrant-env
# 2. Создайте файл .env и добавьте в него TAILSCALE_AUTHKEY=tskey-...
#    ВАЖНО: Добавьте .env в ваш .gitignore, чтобы случайно не закомитить секреты.

Vagrant.configure("2") do |config|
  # Включить плагин для чтения .env файла
  config.env.enable

  config.vm.box = "ubuntu/jammy64"
  config.vm.box_version = "20240912.0.0"
  config.vm.hostname = "vagrant-tailscale-node"

  # Шаг 1: Установка Tailscale
  config.vm.provision "tailscale-install", type: "shell", inline: "curl -fsSL https://tailscale.com/install.sh | sh"

  # Шаг 2: Подключение к сети Tailscale с использованием ключа из .env
  config.vm.provision "tailscale-up", type: "shell" do |s|
    s.inline = "tailscale up --ssh --operator=vagrant --authkey=#{ENV['TAILSCALE_AUTHKEY']}"
  end

  # Триггер: перед удалением машины выйти из сети Tailscale
  config.trigger.before :destroy do |trigger|
    trigger.name = "Tailscale Logout"
    trigger.run_remote = { inline: "tailscale logout" }
    trigger.on_error = :continue # Продолжить даже если команда завершилась с ошибкой
  end
end
```

### Libvirt с несколькими дисками и автоматическим монтированием

1.  **Создание VM:** На базе образа `Ubuntu 24.04`.
2.  **Конфигурация ресурсов:** 2 CPU и 2048 МБ RAM.
3.  **Управление дисками:**
    *   Определяет размер основного диска (`20G`).
    *   Создает второй, дополнительный диск (`10G`).
4.  **Автоматизация:** С помощью `shell provisioner` выполняет автоматическое создание раздела, форматирование в `ext4` и монтирование второго диска в директорию `/data`.

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  # Образ Ubuntu 24.04
  config.vm.box = "jtarpley/ubuntu2404_base"
  config.vm.hostname = "suricata-diplom"

  # Настройки провайдера libvirt
config.vm.provider "libvirt" do |libvirt|
  libvirt.memory = 6048
  libvirt.cpus = 4
  libvirt.storage :file, size: "30G", type: "qcow2", bus: "virtio"
  libvirt.nic_model_type = "virtio"
  config.vm.synced_folder ".", "/vagrant", disabled: true
end

  # Приватная сеть для удобного доступа
  config.vm.network "private_network", ip: "192.168.56.10"

  # Автоматическое создание и монтирование второго диска
  config.vm.provision "shell", inline: <<-SHELL
    set -eux

    # Проверяем наличие второго диска
    if lsblk | grep -q vdb; then
      # Если диск не размечен — создаём раздел и файловую систему
      if ! blkid /dev/vdb1 >/dev/null 2>&1; then
        echo "Создаю раздел на /dev/vdb..."
        echo ",,L" | sfdisk /dev/vdb
        mkfs.ext4 /dev/vdb1
        mkdir -p /data
        echo '/dev/vdb1 /data ext4 defaults 0 0' >> /etc/fstab
        mount -a
      else
        echo "Раздел уже существует, просто монтирую..."
        mkdir -p /data
        mount -a
      fi
    else
      echo "Второй диск не найден!"
    fi
  SHELL
end
```

## Советы и решение проблем

- **Приостановка и возобновление:**
  - `vagrant suspend`: Сохраняет текущее состояние ВМ на диск и останавливает ее (быстро).
  - `vagrant resume`: Восстанавливает ВМ из сохраненного состояния.

- **Работа через прокси:**
  Если хост-машина находится за прокси, настройте переменные окружения:
  ```bash
  export http_proxy="http://user:pass@proxy.example.com:port/"
  export https_proxy="http://user:pass@proxy.example.com:port/"
  export VAGRANT_HTTP_PROXY="${http_proxy}"
  export VAGRANT_HTTPS_PROXY="${https_proxy}"
  ```

- **Сброс состояния проекта:**
  Если `vagrant status` показывает неверный статус или возникли проблемы с состоянием, можно удалить внутреннюю директорию Vagrant.
  ```bash
  # Внимание: это действие удалит метаданные Vagrant (снапшоты, ID машины),
  # но не затронет саму виртуальную машину у провайдера.
  rm -rf .vagrant
  ```
  После этого `vagrant up` пересоздаст машину на основе актуального `Vagrantfile`.

- **Остановка и именование ВМ:**

  - `vagrant halt`: Корректно завершает работу гостевой операционной системы и останавливает ВМ.
  
  - **Именование ВМ:** Не используйте нижнее подчеркивание (`_`) в именах виртуальных машин. Это может привести к ошибкам при старте. Вместо этого используйте дефис (`-`).
