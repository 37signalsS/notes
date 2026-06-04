# Конфигурационный файл Vagrantfile

## Определения

**Vagrantfile** — конфигурационный файл на языке Ruby, описывающий параметры виртуальных машин и их окружения. Служит единым источником истины для настройки инфраструктуры проекта.

> **Синтаксис:** Ruby DSL (Domain-Specific Language). Актуальная версия синтаксиса — `"2"`.

## Базовые концепции

### Структура файла

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  # Глобальные настройки проекта
  config.vm.box = "bento/ubuntu-24.04"

  # Конфигурация конкретной ВМ
  config.vm.define "web" do |web|
    web.vm.hostname = "web-server"
  end
end
```

**Основные элементы:**

- `Vagrant.configure("2")` — инициализация блока конфигурации.
- `config` — объект, через который задаются глобальные параметры.
- `do |config| ... end` — блок Ruby, внутри которого описывается логика.

### Ключевые параметры конфигурации

| Параметр | Пример | Описание |
| :--- | :--- | :--- |
| `config.vm.box` | `"bento/ubuntu-24.04"` | Базовый образ (box) |
| `config.vm.box_version` | `"~> 202501.0"` | Версия образа |
| `config.vm.box_check_update` | `false` | Проверка обновлений box при запуске |
| `config.vm.hostname` | `"web-server"` | Имя хоста внутри виртуальной машины |
| `config.vm.network` | `"forwarded_port", ...` | Настройка сетевых интерфейсов |
| `config.vm.provider` | `"libvirt"`, `"virtualbox"` | Настройки гипервизора |
| `config.vm.provision` | `"shell"`, `"ansible"` | Автоматизация настройки ОС |
| `config.vm.synced_folder` | `"./src", "/app"` | Синхронизация папок хост-гость |
| `config.ssh.username` | `"vagrant"` | Имя пользователя для SSH-подключения |

## Практические сценарии

### Сценарий 1: Базовая конфигурация

Минимально необходимый набор параметров для запуска одной машины:

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.hostname = "dev-machine"
  
  # Настройка ресурсов (провайдер Libvirt)
  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 2048
    libvirt.cpus = 2
  end
  
  # Проброс порта для веб-приложения
  config.vm.network "forwarded_port", guest: 80, host: 8080
  
  # Базовая настройка через Shell-скрипт
  config.vm.provision "shell", inline: "apt-get update && apt-get install -y nginx"
end
```

### Сценарий 2: Комплексная конфигурация для разработки

Пример файла, объединяющего сеть, провайдеры, общие папки и расширенный provisioning:

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
  config.vm.network "forwarded_port", guest: 3000, host: 3000
  config.vm.network "private_network", ip: "192.168.77.10"
  
  # === Настройки провайдера (Libvirt) ===
  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 4096
    libvirt.cpus = 4
    libvirt.nested = true
    libvirt.storage_pool_name = "default"
  end
  
  # === Общие папки ===
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.synced_folder "src/", "/app/src", type: "nfs"
  
  # === Provisioning (Shell + Ansible) ===
  config.vm.provision "shell", path: "scripts/bootstrap.sh"
  config.vm.provision "ansible" do |ansible|
    ansible.playbook = "playbooks/site.yml"
  end
  
  # === Триггеры ===
  config.trigger.after :up do |trigger|
    trigger.run_local = { inline: "echo 'VM is ready!'" }
  end
end
```

### Другие сценарии

Для реализации специфических задач используйте соответствующие разделы:

- **Мульти-машинные конфигурации:** Описание нескольких ВМ в одном файле — [Vagrant Advanced Usage](./vagrant_advanced_usage.md#multi-machine-архитектура).
- **Динамическая конфигурация:** Использование переменных окружения (`ENV`) — [Vagrant Advanced Usage](./vagrant_advanced_usage.md#динамическая-конфигурация-через-env).
- **Настройка VirtualBox:** Специфические параметры для провайдера VirtualBox — [Vagrant Providers](./vagrant_providers.md#сценарий-1-настройка-параметров-провайдера).

## Дополнительная информация

### Переменные и циклы в Vagrantfile

Поскольку Vagrantfile — это Ruby-код, в нем можно использовать стандартные конструкции языка:

```ruby
# Использование переменных
app_name = "myapp"
config.vm.hostname = "#{app_name}-dev"

# Условия (например, для CI-окружения)
if ENV['CI'] == 'true'
  config.vm.box_check_update = true
end

# Циклы для создания кластера машин
(1..3).each do |i|
  config.vm.define "node-#{i}" do |node|
    node.vm.network "private_network", ip: "192.168.77.#{10 + i}"
  end
end
```

### Лучшие практики

1. **Комментарии:** Разделяйте логические секции (`Network`, `Providers`, `Provision`) комментариями для удобства чтения.
2. **Безопасность:** Не храните пароли и токены в `Vagrantfile`. Используйте переменные окружения или зашифрованные файлы (например, Ansible Vault).
3. **Версионирование:** Всегда указывайте версию box (`config.vm.box_version`), чтобы избежать внезапных изменений в базовой ОС при обновлении образа у разработчиков.
4. **.gitignore:** Добавляйте директорию `.vagrant/` и файлы с секретами (`.env`) в исключения Git.

### Валидация Vagrantfile

```bash
# Проверка синтаксиса файла
vagrant validate

# Просмотр итоговой конфигурации всех машин
vagrant status
```

Подробные уровни логирования при отладке конфигурации описаны в [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md).

### См. также

- [Vagrant Basic Workflow](./vagrant_basic_workflow.md) — основы работы.
- [Vagrant Providers](./vagrant_providers.md) — управление образами и провайдерами.
- [Vagrant Networking](./vagrant_networking.md) — детальная настройка сетей.
- [Vagrant Provisioning](./vagrant_provisioning.md) — автоматизация настройки.
- [Vagrant Storage and Folders](./vagrant_storage_and_folders.md) — работа с дисками и папками.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — сложные сценарии и триггеры.
