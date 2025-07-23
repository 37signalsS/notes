# Vagrant

## Установка

1.  Добавьте GPG-ключ HashiCorp:
    ```sh
    curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
    ```

2.  Добавьте официальный репозиторий HashiCorp:
    ```sh
    sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
    ```

3.  Установите Vagrant:
    ```sh
    sudo apt-get update && sudo apt-get install vagrant
    ```

## Основные команды

Создайте директорию для вашего проекта и в ней поддиректории для каждой виртуальной машины.

1.  **Инициализация**
    В директории проекта выполните инициализацию. Vagrant создаст конфигурационный файл `Vagrantfile`.
    ```sh
    vagrant init generic/ubuntu2010
    ```
    Будет создан `Vagrantfile` с базовой конфигурацией:
    ```ruby
    Vagrant.configure("2") do |config|
      config.vm.box = "generic/ubuntu2010"
    end
    ```

2.  **Запуск виртуальной машины**
    ```sh
    vagrant up --provider=virtualbox
    ```

3.  **Статус**
    Посмотреть список и статус виртуальных машин:
    ```sh
    vagrant status
    ```

4.  **Подключение по SSH**
    Узнать параметры для SSH-подключения:
    ```sh
    vagrant ssh-config
    ```
    Подключиться к машине:
    ```sh
    vagrant ssh
    ```

5.  **Удаление виртуальной машины**
    ```sh
    vagrant destroy
    ```

6.  **Перезагрузка и Provisioning**
    Перезагрузить машину (например, после изменения `Vagrantfile`):
    ```sh
    vagrant reload
    ```
    Запустить provisioning на уже запущенной машине:
    ```sh
    vagrant provision
    ```
    Перезагрузить и применить provisioning:
    ```sh
    vagrant reload --provision
    ```

## Конфигурация (`Vagrantfile`)

### Имя хоста
```ruby
config.vm.hostname = "my-vm"
```

### Сеть
Настройка приватной сети с указанием IP-адреса:
```ruby
config.vm.network :private_network, ip: "192.168.56.10"
```

### Проброс портов
Сделать сайт на гостевой машине доступным с хоста:
```ruby
config.vm.network :forwarded_port, guest: 80, host: 8080
```

### Параметры провайдера
Настройка характеристик виртуальной машины (память, CPU):
```ruby
config.vm.provider "virtualbox" do |v|
    v.memory = 2048
    v.cpus = 2
end
```

### Отключение проверки обновлений
Отключить проверку обновлений box'а при старте:
```ruby
config.vm.box_check_update = false
```

### Сброс конфигурации
Если после изменения конфига в статусе ничего не поменялось, можно удалить внутреннее состояние Vagrant для проекта:
```sh
rm -rf .vagrant
```

## Provisioning (Настройка ПО)

Vagrant может автоматически устанавливать и настраивать ПО на виртуальных машинах.

**Пример: установка Nginx с помощью shell-скрипта.**

1.  Создайте скрипт `bootstrap.sh`:
    ```sh
    #!/bin/sh
    
    echo 'deb https://nginx.org/packages/ubuntu/ focal nginx' > /etc/apt/sources.list.d/nginx.list
    echo 'deb-src https://nginx.org/packages/ubuntu/ focal nginx' >> /etc/apt/sources.list.d/nginx.list
    apt-key adv --keyserver keyserver.ubuntu.com --recv-keys ABF5BD827BD9BF62
    apt-get update -y
    apt-get install nginx -y
    systemctl enable nginx
    systemctl start nginx
    ```

2.  Добавьте в `Vagrantfile` указание на скрипт:
    ```ruby
    config.vm.provision :shell, path: "bootstrap.sh"
    ```

3.  Запустите машину. Nginx будет установлен автоматически.
    ```sh
    vagrant up
    ```

## Продвинутые конфигурации

### Конфигурация для нескольких машин

```ruby
# Скрипт для установки ПО, который будет выполняться на каждой машине
$script = <<-SCRIPT
    # Тут пишем, что необходимо установить и т.д.
    # Например:
    # apt-get update
    # apt-get install -y tree
SCRIPT

# Описание узлов
nodes = [
    { hostname: 'ubuntu1', ip: '10.245.1.222', memory: 1024, cpu: 1, boxname: "ubuntu/xenial64" },
    { hostname: 'ubuntu2', ip: '10.245.1.223', memory: 1024, cpu: 1, boxname: "ubuntu/xenial64" }
]

Vagrant.configure("2") do |config|
    config.vm.box_check_update = false

    nodes.each do |node|
        config.vm.define node[:hostname] do |nodeconfig|
            nodeconfig.vm.box = node[:boxname]
            nodeconfig.vm.hostname = node[:hostname]
            nodeconfig.vm.network :private_network, ip: node[:ip]
            
            nodeconfig.vm.provider :virtualbox do |vb|
                vb.memory = node[:memory]
                vb.cpus = node[:cpu]
            end
            
            nodeconfig.vm.provision "shell", inline: $script
        end
    end
end
```

### Использование прокси-сервера

Для работы Vagrant через прокси, установите переменные окружения:
```sh
export http_proxy="http://user:password@ip_proxy:port/"
export https_proxy="http://user:password@ip_proxy:port/"
export VAGRANT_HTTP_PROXY="${http_proxy}"
export VAGRANT_HTTPS_PROXY="${https_proxy}"
export VAGRANT_NO_PROXY="127.0.0.1"
```

### Интеграция с Tailscale

```ruby
Vagrant.configure("2") do |config|
  # Убедитесь, что плагин vagrant-env установлен: vagrant plugin install vagrant-env
  config.env.enable

  config.vm.box = ENV['VM_BOX']
  config.vm.hostname = ENV['VM_HOSTNAME']    
  config.vm.provider ENV['VM_ENGINE'] do |v| 
    v.name = ENV['VM_HOSTNAME']
    v.memory = ENV['VM_MEMORY']
    v.cpus = ENV['VM_CPUS']
  end

  config.vm.provision "tailscale-install", type: "shell" do |s|
    s.inline = "curl -fsSL https://tailscale.com/install.sh | sh"
  end

  config.vm.provision "tailscale-up", type: "shell" do |s|
    # Убедитесь, что TAILSCALE_AUTHKEY задан в вашем окружении
    s.inline = "tailscale up --ssh --operator=vagrant --authkey #{ENV['TAILSCALE_AUTHKEY']}"
  end

  # При удалении машины выходить из сети Tailscale
  config.trigger.before :destroy do |trigger|
    trigger.run_remote = {inline: "tailscale logout"}
    trigger.on_error = :continue
  end
end
```
