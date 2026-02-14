# Продвинутые сценарии использования Vagrant

## Управление несколькими машинами (Multi-Machine)

`Vagrantfile` позволяет описывать и управлять целой группой взаимосвязанных машин из одного файла. Это идеально подходит для моделирования сложных окружений, таких как кластеры или многоуровневые приложения.

## Практические сценарии

### 1. Создание кластера из нескольких машин с Ansible

Этот `Vagrantfile` демонстрирует создание трех машин с использованием цикла. Для первой машины (`machine1`) применяется особый плейбук Ansible, а для остальных — общий. Это позволяет гибко настраивать роли в кластере.

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "jtarpley/ubuntu2404_base"
  config.vm.guest = :ubuntu # Явно указываем гостевую ОС

  # Задаем количество создаваемых машин
  N = 3
  (1..N).each do |machine_id|
    config.vm.define "machine#{machine_id}" do |machine|
      machine.vm.hostname = "machine#{machine_id}"
      machine.vm.box_check_update = false
      machine.vm.network "private_network", ip: "192.168.77.#{10+machine_id}"
      
      # Добавляем правило UFW для разрешения входящих подключений на порт 80
      machine.vm.provision "shell", inline: "sudo ufw allow 80/tcp"

      machine.vm.provider "libvirt" do |libvirt|
        libvirt.memory = 2048
        libvirt.cpus = 2
        libvirt.random_hostname = false

        libvirt.storage_pool_name = "default"
        libvirt.machine_virtual_size = 10
      end

      # Условное применение плейбуков Ansible
      if machine_id == 1
         # Для первой машины применяем особый плейбук
         machine.vm.provision :ansible do |ansible|
           ansible.inventory_path = "nginx-lab/ansible/inventory.ini"
           ansible.playbook = "nginx-lab/ansible/playbook_machine1.yml"
         end
      else
         machine.vm.provision :ansible do |ansible|
           ansible.inventory_path = "nginx-lab/ansible/inventory.ini"
           ansible.playbook = "nginx-lab/ansible/playbook.yml"
         end
      end
    end
  end
end
```
Команды `vagrant up`, `vagrant ssh` и другие теперь можно применять к конкретной машине, указывая ее имя:
```bash
vagrant up machine2
vagrant ssh machine1
vagrant destroy -f machine3
```

### 2. Интеграция с внешними сервисами: Tailscale

Этот пример использует плагин `vagrant-env` для безопасной передачи секретного ключа аутентификации `TAILSCALE_AUTHKEY` и автоматического подключения ВМ к вашей сети Tailscale. Триггер `before :destroy` гарантирует, что машина будет корректно отключена от сети перед удалением.

```ruby
# 1. Установите плагин: vagrant plugin install vagrant-env
# 2. Создайте файл .env и добавьте в него TAILSCALE_AUTHKEY=tskey-...
#    ВАЖНО: Добавьте .env в ваш .gitignore, чтобы случайно не опубликовать секреты.

Vagrant.configure("2") do |config|
  # Включить плагин для чтения .env файла
  config.env.enable

  config.vm.box = "ubuntu/jammy64"
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

### 3. Безопасное управление секретами с Ansible Vault

При использовании Ansible для провижининга часто возникает необходимость безопасно управлять секретами (паролями, ключами), не сохраняя их в открытом виде. Vagrant имеет встроенную поддержку Ansible Vault, что позволяет автоматизировать расшифровку секретов во время выполнения `vagrant up` или `vagrant provision`.

Для получения подробной информации о настройке и использовании см. практический сценарий в заметке [Ansible Vault: Интеграция с Vagrant](Ansible/Vault/basics.md).