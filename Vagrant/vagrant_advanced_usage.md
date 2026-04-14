# Продвинутые сценарии использования Vagrant

## Определения

**Multi-Machine Vagrantfile** — конфигурация, описывающая несколько взаимосвязанных ВМ в одном файле. Позволяет моделировать сложные окружения: кластеры, микросервисы, многоуровневые приложения.

**Triggers (триггеры)** — механизм автоматического выполнения действий до/после команд Vagrant (`up`, `destroy`, `provision` и др.). Используются для бэкапов, уведомлений, проверок.

**Динамическая конфигурация** — использование переменных окружения (`ENV`) для гибкой настройки параметров ВМ без изменения Vagrantfile.

## Базовые концепции

### Multi-Machine архитектура

Каждая машина определяется через `config.vm.define` и имеет индивидуальную конфигурацию. Подробный синтаксис: [Vagrantfile Reference](./vagrantfile.md#сценарий-2-мульти-машинная-конфигурация).

**Команды для конкретных машин:**

```bash
vagrant up web              # Запустить только web
vagrant ssh db              # Подключиться к db
vagrant provision web       # Применить provisioning к web
vagrant destroy -f db       # Удалить только db
vagrant status              # Статус всех машин
```

### Триггеры

Триггеры выполняются локально (`run_local`) или удалённо (`run_remote`) на ВМ. Пример конфигурации: [Vagrantfile Reference](./vagrantfile.md#сценарий-4-полная-конфигурация-для-разработки).

**Ключевые возможности:**

- `config.trigger.before :command` — действие ДО команды
- `config.trigger.after :command` — действие ПОСЛЕ команды
- `trigger.on_error = :continue` — продолжить при ошибке
- `trigger.run_local` / `trigger.run_remote` — контекст выполнения

### Динамическая конфигурация через ENV

Использование `ENV.fetch` для параметров с значениями по умолчанию:

```ruby
libvirt.memory = ENV.fetch('VAGRANT_MEMORY', 2048).to_i
libvirt.cpus = ENV.fetch('VAGRANT_CPUS', 2).to_i
```

Подробности: [Vagrantfile Reference](./vagrantfile.md#сценарий-3-динамическая-конфигурация-через-env).

### Плагины для работы с переменными окружения

**vagrant-env** — плагин для загрузки `.env` файлов:

```bash
vagrant plugin install vagrant-env
```

Файл `.env` (добавить в `.gitignore!`):

```bash
VAGRANT_MEMORY=4096
VAGRANT_CPUS=4
TAILSCALE_AUTHKEY=tskey-...
```

## Практические сценарии

### Сценарий 1: Создание кластера с циклом и Ansible

Развертывание кластера из N машин с различными ролями через цикл:

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "jtarpley/ubuntu2404_base"
  config.vm.guest = :ubuntu

  N = 3
  (1..N).each do |machine_id|
    config.vm.define "machine#{machine_id}" do |machine|
      machine.vm.hostname = "machine#{machine_id}"
      machine.vm.box_check_update = false
      machine.vm.network "private_network", ip: "192.168.77.#{10+machine_id}"

      # Правило UFW для разрешения входящих подключений на порт 80
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

**Использование:**

```bash
vagrant up                    # Запуск всего кластера
vagrant up machine2           # Запуск отдельного узла
vagrant provision machine1    # Перепровижининг конкретного узла
vagrant destroy -f machine3   # Удаление узла
```

> **Примечание:** Сети для multi-machine описаны в [Vagrant Networking](./vagrant_networking.md#сценарий-2-изолированная-сеть-для-кластера).

### Сценарий 2: Интеграция с Tailscale

Автоматическое подключение ВМ к приватной сети Tailscale:

```ruby
Vagrant.configure("2") do |config|
  config.env.enable

  config.vm.box = "bento/ubuntu-24.04"
  config.vm.hostname = "tailscale-node"

  # Установка Tailscale
  config.vm.provision "install", type: "shell", inline: <<-SHELL
    curl -fsSL https://tailscale.com/install.sh | sh
  SHELL

  # Подключение к сети
  config.vm.provision "connect", type: "shell" do |s|
    s.inline = "tailscale up --ssh --operator=vagrant --authkey=#{ENV['TAILSCALE_AUTHKEY']}"
    s.privileged = true
  end

  # Очистка при уничтожении
  config.trigger.before :destroy do |trigger|
    trigger.name = "Tailscale Logout"
    trigger.run_remote = { inline: "tailscale logout" }
    trigger.on_error = :continue
  end
end
```

**Преимущества:**

- Безопасный доступ к ВМ из любой точки мира
- Не требуется пробрасывать порты на роутере
- Шифрование всего трафика

Подробнее о Tailscale: [VPN/Tailscale](../Vpn/tailscale.md)

### Сценарий 3: Ansible Vault для секретов

Интеграция с Ansible Vault для безопасного хранения секретов:

```ruby
config.vm.provision :ansible do |ansible|
  ansible.playbook = "playbook.yml"
  ansible.vault_password_file = ".vault_password"
end
```

Файл `.vault_password` должен быть в `.gitignore`.

**Подробности:** [Ansible Vault Examples](../Ansible/Vault/examples.md)

### Сценарий 4: Триггеры для автоматизации бэкапов и проверок

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Проверка перед запуском
  config.trigger.before :up do |trigger|
    trigger.name = "Pre-up check"
    trigger.run_local = { inline: "echo 'Starting VM...'" }
  end

  # Бэкап перед уничтожением
  config.trigger.before :destroy do |trigger|
    trigger.name = "Backup data"
    trigger.run_remote = {
      inline: "tar -czf /tmp/data-backup.tar.gz /var/data 2>/dev/null || true"
    }
    trigger.on_error = :continue
  end

  # Уведомление после запуска
  config.trigger.after :up do |trigger|
    trigger.name = "Post-up notification"
    trigger.run_local = { inline: "echo 'VM is ready!'" }
  end
end
```

## Дополнительная информация

### Лучшие практики

1. **Именование машин:** Используйте дефисы вместо подчёркиваний (`web-server`, не `web_server`) — это предотвращает конфликты в Libvirt.

2. **Секреты:** Никогда не храните секреты в `Vagrantfile`. Используйте:
   - `vagrant-env` для переменных окружения
   - Ansible Vault для зашифрованных переменных ([Ansible Vault Best Practices](../Ansible/Vault/best_practices.md))
   - Файл `.env` в `.gitignore`

3. **Идемпотентность provisioning:** Скрипты должны выполняться многократно без побочных эффектов:

   ```bash
   # Плохо
   echo "line" >> /etc/config

   # Хорошо
   grep -q "line" /etc/config || echo "line" >> /etc/config
   ```

   Подробнее: [Vagrant Provisioning](./vagrant_provisioning.md#лучшие-практики)

4. **Версионирование box'ов:** Фиксируйте версии для воспроизводимости:

   ```ruby
   config.vm.box = "bento/ubuntu-24.04"
   config.vm.box_version = "~> 202501.0"
   ```

5. **Ресурсы:** Выделяйте разумное количество ресурсов. Для большинства задач достаточно 1-2 CPU и 1-2GB RAM.

### См. также

- [Vagrant Provisioning](./vagrant_provisioning.md) — детальная настройка provisioning
- [Vagrantfile Reference](./vagrantfile.md) — полный синтаксис конфигурации
- [Vagrant Networking](./vagrant_networking.md) — конфигурация сетей
- [Vagrant Storage and Folders](./vagrant_storage_and_folders.md) — synced folders, управление дисками
- [Vagrant Providers](./vagrant_providers.md) — настройка провайдеров (Libvirt, VirtualBox)
