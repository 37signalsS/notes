# Vagrant

Vagrant — это инструмент для создания и управления виртуализированными средами разработки.

## Установка (Debian/Ubuntu)

Процесс установки на современных системах Debian/Ubuntu включает добавление GPG-ключа и репозитория HashiCorp.

1.  **Установите необходимые пакеты:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y curl gpg
    ```

2.  **Добавьте GPG-ключ HashiCorp:**
    ```bash
    curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
    ```

3.  **Добавьте репозиторий HashiCorp:**
    ```bash
    echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
    ```

4.  **Установите Vagrant:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y vagrant
    ```

## Базовый рабочий процесс

1.  **Инициализация проекта**
    Создайте директорию для проекта и выполните в ней `vagrant init`. Эта команда создаст `Vagrantfile` — основной конфигурационный файл.

    ```bash
    # Инициализация с использованием box'а Ubuntu 22.04
    vagrant init ubuntu/jammy64
    ```
    Содержимое `Vagrantfile` будет минимальным:
    ```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
end
    ```

2.  **Запуск окружения**
    Команда `vagrant up` скачивает указанный box (если его нет в кэше), создает и запускает виртуальную машину.

    ```bash
    # Запуск с указанием провайдера (например, VirtualBox)
    vagrant up --provider=virtualbox
    ```

3.  **Подключение по SSH**
    Vagrant обеспечивает простой доступ к гостевой машине.

    ```bash
    # Посмотреть параметры для SSH-подключения
    vagrant ssh-config

    # Подключиться к машине
    vagrant ssh
    ```

4.  **Проверка статуса**
    Команда `vagrant status` показывает состояние всех управляемых машин.

    ```bash
    vagrant status
    ```

5.  **Перезагрузка и Provisioning**
    Для применения изменений в `Vagrantfile` или для повторного запуска скриптов настройки (provisioning) используются следующие команды:

    ```bash
    # Перезагрузить машину для применения изменений
    vagrant reload

    # Запустить provisioning на работающей машине
    vagrant provision

    # Перезагрузить и применить provisioning
    vagrant reload --provision
    ```

6.  **Удаление окружения**
    Команда `vagrant destroy` останавливает и удаляет виртуальную машину и все связанные с ней ресурсы.

    ```bash
    vagrant destroy
    ```

## Конфигурация (Vagrantfile)

### Сетевые настройки

```ruby
Vagrant.configure("2") do |config|
  # Приватная сеть с фиксированным IP
  config.vm.network :private_network, ip: "192.168.56.10"

  # Проброс портов: порт 80 гостевой машины будет доступен на порту 8080 хоста
  config.vm.network :forwarded_port, guest: 80, host: 8080
end
```

### Настройки виртуальной машины

```ruby
Vagrant.configure("2") do |config|
  # Имя хоста
  config.vm.hostname = "my-vm"

  # Отключить проверку обновлений box'а при старте
  config.vm.box_check_update = false

  # Настройки провайдера (VirtualBox)
  config.vm.provider "virtualbox" do |v|
    v.memory = 2048 # Память в МБ
    v.cpus = 2     # Количество CPU
  end
end
```

## Provisioning (Автоматическая настройка)

Provisioning позволяет автоматически устанавливать ПО и выполнять настройки при создании машины.

**Пример: установка Nginx с помощью shell-скрипта.**

1.  **Создайте скрипт `provision.sh`:**
    ```bash
    #!/bin/bash
    set -euo pipefail

    # Добавление репозитория Nginx
    apt-get update -y
    apt-get install -y curl gnupg
    curl -fsSL http://nginx.org/keys/nginx_signing.key | gpg --dearmor > /usr/share/keyrings/nginx-archive-keyring.gpg
    
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/ubuntu $(lsb_release -cs) nginx" \
        | tee /etc/apt/sources.list.d/nginx.list

    # Установка Nginx
    apt-get update -y
    apt-get install -y nginx
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

`Vagrantfile` позволяет описывать и управлять целой группой машин.

```ruby
# Общий скрипт для установки ПО
$provision_script = "apt-get update && apt-get install -y tree"

# Описание узлов в виде массива хэшей
nodes = [
    { hostname: 'node1', ip: '192.168.56.11', box: "ubuntu/jammy64" },
    { hostname: 'node2', ip: '192.168.56.12', box: "ubuntu/jammy64" }
]

Vagrant.configure("2") do |config|
    nodes.each do |node|
        config.vm.define node[:hostname] do |node_config|
            node_config.vm.box = node[:box]
            node_config.vm.hostname = node[:hostname]
            node_config.vm.network :private_network, ip: node[:ip]
            
            node_config.vm.provider :virtualbox do |vb|
                vb.memory = 1024
                vb.cpus = 1
            end
            
            node_config.vm.provision "shell", inline: $provision_script
        end
    end
end
```

### Работа через прокси-сервер

Если хост-машина находится за прокси, настройте переменные окружения:
```bash
export http_proxy="http://user:password@proxy.example.com:port/"
export https_proxy="http://user:password@proxy.example.com:port/"
export VAGRANT_HTTP_PROXY="${http_proxy}"
export VAGRANT_HTTPS_PROXY="${https_proxy}"
export VAGRANT_NO_PROXY="127.0.0.1,localhost"
```

### Интеграция с Tailscale

Этот пример использует плагин `vagrant-env` для безопасной передачи `TAILSCALE_AUTHKEY`.

```ruby
# 1. Установите плагин: vagrant plugin install vagrant-env
# 2. Создайте файл .env и добавьте в него TAILSCALE_AUTHKEY=tskey-...

Vagrant.configure("2") do |config|
  # Включить плагин для чтения .env файла
  config.env.enable

  config.vm.box = "ubuntu/jammy64"
  config.vm.hostname = "vagrant-tailscale-node"

  # Установка Tailscale
  config.vm.provision "tailscale-install", type: "shell" do |s|
    s.inline = "curl -fsSL https://tailscale.com/install.sh | sh"
  end

  # Подключение к сети Tailscale
  config.vm.provision "tailscale-up", type: "shell" do |s|
    # Используется ключ из .env файла
    s.inline = "tailscale up --ssh --operator=vagrant --authkey=#{ENV['TAILSCALE_AUTHKEY']}"
  end

  # При удалении машины выходить из сети Tailscale
  config.trigger.before :destroy do |trigger|
    trigger.name = "Tailscale Logout"
    trigger.run_remote = { inline: "tailscale logout" }
    trigger.on_error = :continue
  end
end
```

## Советы и решение проблем

### Сброс состояния проекта

Если `Vagrantfile` был изменен, но `vagrant status` не отражает изменений, или возникли другие проблемы с состоянием, можно удалить внутреннюю директорию Vagrant.

```bash
# Внимание: это действие удалит все снапшоты и метаданные,
# но не затронет саму виртуальную машину у провайдера.
rm -rf .vagrant
```
После этого `vagrant up` пересоздаст машину на основе актуального `Vagrantfile`.