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

## Конфигурация (Vagrantfile)

### Сетевые настройки

```ruby
Vagrant.configure("2") do |config|
  # Приватная сеть с фиксированным IP для доступа с хоста
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

  # Настройки провайдера (например, VirtualBox)
  config.vm.provider "virtualbox" do |v|
    v.memory = 2048 # Память в МБ
    v.cpus = 2     # Количество CPU
    v.name = "my-app-vm" # Имя в интерфейсе VirtualBox
  end
end
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
