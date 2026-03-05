# Конфигурационный файл Vagrantfile

## Определения

**Vagrantfile** — конфигурационный файл на Ruby, описывающий параметры виртуальных машин Vagrant. Единый источник истины для окружения.

> **Синтаксис:** Ruby DSL (Domain-Specific Language). Версия синтаксиса — `"2"` (актуальная).

## Базовые концепции

### Структура файла

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  # Конфигурация ВМ
end
```

**Параметры:**

- `config` — главный объект настройки
- Все параметры задаются внутри блока `Vagrant.configure("2")`

### Ключевые параметры конфигурации

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.box` | `"bento/ubuntu-24.04"` | Базовый образ (box) |
| `config.vm.box_version` | `"~> 202501.0"` | Версия образа |
| `config.vm.box_check_update` | `false` | Отключить проверку обновлений |
| `config.vm.hostname` | `"web-server"` | Имя хоста внутри ВМ |
| `config.vm.network` | `"forwarded_port", ...` | Настройка сети |
| `config.vm.provider` | `"libvirt"`, `"virtualbox"` | Провайдер виртуализации |
| `config.vm.provision` | `"shell"`, `"ansible"` | Provisioning |
| `config.vm.synced_folder` | `"./src", "/app"` | Общие папки |
| `config.ssh.username` | `"vagrant"` | Пользователь SSH |
| `config.ssh.private_key_path` | `"~/.ssh/id_rsa"` | SSH-ключ |

## Практические сценарии

### Сценарий 1: Базовая конфигурация

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.hostname = "dev-machine"
  
  # Выделение ресурсов
  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 2048
    libvirt.cpus = 2
  end
  
  # Проброс порта
  config.vm.network "forwarded_port", guest: 80, host: 8080
  
  # Provisioning
  config.vm.provision "shell", inline: "apt-get update && apt-get install -y nginx"
end
```

### Сценарий 2: Мульти-машинная конфигурация

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Веб-сервер
  config.vm.define "web" do |web|
    web.vm.hostname = "web-server"
    web.vm.network "private_network", ip: "192.168.77.10"
    web.vm.provision "shell", path: "scripts/web.sh"
  end
  
  # База данных
  config.vm.define "db" do |db|
    db.vm.hostname = "db-server"
    db.vm.network "private_network", ip: "192.168.77.11"
    db.vm.provision "shell", path: "scripts/db.sh"
  end
end
```

**Использование:**

```bash
vagrant up web        # Запустить web
vagrant up            # Запустить все
vagrant ssh db        # Подключиться к db
```

### Сценарий 3: Динамическая конфигурация через ENV

```ruby
Vagrant.configure("2") do |config|
  # Образ из переменной окружения или по умолчанию
  config.vm.box = ENV['VAGRANT_BOX'] || "bento/ubuntu-24.04"
  
  # Ресурсы из переменных
  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = ENV.fetch('VAGRANT_MEMORY', 2048).to_i
    libvirt.cpus = ENV.fetch('VAGRANT_CPUS', 2).to_i
  end
  
  # Включение provisioning только при необходимости
  if ENV['PROVISION'] == 'true'
    config.vm.provision "shell", path: "scripts/provision.sh"
  end
end
```

**Запуск:**

```bash
# С кастомными параметрами
VAGRANT_MEMORY=4096 VAGRANT_CPUS=4 vagrant up

# С provisioning
PROVISION=true vagrant up
```

### Сценарий 4: Полная конфигурация для разработки

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  # === Базовые настройки ===
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.hostname = "dev-environment"
  config.vm.box_check_update = false
  
  # === Сеть ===
  config.vm.network "forwarded_port", guest: 80, host: 8080
  config.vm.network "forwarded_port", guest: 443, host: 8443
  config.vm.network "forwarded_port", guest: 3000, host: 3000
  config.vm.network "private_network", ip: "192.168.77.10"
  
  # === Провайдер (Libvirt) ===
  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 4096
    libvirt.cpus = 4
    libvirt.nested = true
    libvirt.disk_bus = 'virtio'
    libvirt.nic_model_type = 'virtio'
    libvirt.storage_pool_name = "default"
    
    # Дополнительный диск
    libvirt.storage :file, size: "50G", type: "qcow2"
  end
  
  # === Общие папки ===
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.synced_folder "src/", "/app/src", type: "nfs"
  
  # === SSH ===
  config.ssh.insert_key = true
  config.ssh.timeout = 300
  
  # === Provisioning ===
  config.vm.provision "shell", path: "scripts/base.sh"
  config.vm.provision "shell", path: "scripts/docker.sh"
  config.vm.provision "ansible" do |ansible|
    ansible.playbook = "playbooks/site.yml"
    ansible.verbose = "-v"
  end
  
  # === Триггеры ===
  config.trigger.after :up do |trigger|
    trigger.name = "Ready notification"
    trigger.run_local = { inline: "echo 'VM is ready!'" }
  end
end
```

### Сценарий 5: Конфигурация для VirtualBox

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
  
  config.vm.provider "virtualbox" do |v|
    v.name = "my-vagrant-vm"
    v.memory = 2048
    v.cpus = 2
    v.gui = false
    v.vram = 128
    v.linked_clone = true
    
    # Проброс дополнительных портов
    v.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]
    v.customize ["modifyvm", :id, "--ioapic", "on"]
  end
  
  config.vm.synced_folder ".", "/vagrant",
    owner: "vagrant",
    group: "vagrant",
    mount_options: ["dmode=775,fmode=664"]
end
```

## Дополнительная информация

### Переменные и интерполяция

```ruby
# Использование переменных Ruby
app_name = "myapp"
config.vm.hostname = "#{app_name}-dev"

# Условия
if ENV['CI'] == 'true'
  config.vm.box_version = "~> 1.0"
end

# Циклы для создания нескольких машин
(1..3).each do |i|
  config.vm.define "node#{i}" do |node|
    node.vm.network "private_network", ip: "192.168.77.#{10 + i}"
  end
end
```

### Best Practices

1. **Комментируйте сложные секции:**

   ```ruby
   # === Сеть ===
   # Проброс портов для доступа к сервисам
   config.vm.network "forwarded_port", guest: 80, host: 8080
   ```

2. **Используйте `.gitignore`:**

   ```
   .vagrant/
   .env
   .vault_password
   *.log
   ```

3. **Версионируйте box'ы:**

   ```ruby
   config.vm.box = "bento/ubuntu-24.04"
   config.vm.box_version = "~> 202501.0"
   ```

4. **Разделяйте конфигурации:**
   - `Vagrantfile` — основная конфигурация
   - `scripts/` — shell-скрипты
   - `playbooks/` — Ansible плейбуки

### Валидация Vagrantfile

```bash
# Проверка синтаксиса
vagrant validate

# Проверка с выводом логов
VAGRANT_LOG=info vagrant up

# Просмотр финальной конфигурации
vagrant status
```

### См. также

- [Vagrant Basic Workflow](./vagrant_basic_workflow.md) — начало работы
- [Vagrant Networking](./vagrant_networking.md) — настройка сети
- [Vagrant Provisioning](./vagrant_provisioning.md) — автоматическая настройка
- [Vagrant Storage and Folders](./vagrant_storage_and_folders.md) — хранилище и папки
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — сложные сценарии
