# Конфигурационный файл Vagrantfile

## Определения

**Vagrantfile** — основной конфигурационный файл проекта на языке Ruby, описывающий желаемое состояние виртуальных машин (ВМ) и их окружения. Он является декларативным описанием инфраструктуры (Infrastructure as Code) и позволяет воспроизводить идентичные окружения на разных машинах разработчиков.

> **Синтаксис:** Ruby DSL (Domain-Specific Language). Актуальная и единственная поддерживаемая версия синтаксиса — `"2"`.

## Базовые концепции

### Порядок поиска Vagrantfile

При выполнении любой команды (`vagrant up`, `vagrant status` и др.) Vagrant ищет конфигурационные файлы в определённом порядке, объединяя их настройки:

1.  **Box Vagrantfile:** Поставляется вместе с образом (box). Содержит специфические для данного образа настройки (например, имя пользователя по умолчанию).
2.  **User Vagrantfile:** Расположен в домашней директории пользователя (`~/.vagrant.d/Vagrantfile`). Используется для глобальных настроек (например, прокси или плагинов для всех проектов).
3.  **Project Vagrantfile:** Находится в корневой директории проекта. Это основной файл, который хранится в системе контроля версий.

### Слияние конфигураций

Vagrant объединяет настройки из всех найденных файлов. При конфликте параметров действуют следующие правила:
-   **Переопределение:** Параметры из Project Vagrantfile имеют приоритет над User и Box Vagrantfile.
-   **Дополнение:** Некоторые параметры (например, проброс портов или сетевые интерфейсы) суммируются, создавая несколько правил.
-   **Специфичность:** Глобальные настройки внутри одного файла переопределяются настройками внутри блока `config.vm.define`.

### Структура файла

```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  # Проверка версии Vagrant
  config.vagrant.require_version ">= 2.4.0"

  # Глобальные настройки проекта
  config.vm.box = "bento/ubuntu-24.04"

  # Конфигурация конкретной ВМ
  config.vm.define "web" do |web|
    web.vm.hostname = "web-server"
    web.vm.network "forwarded_port", guest: 80, host: 8080
  end
end
```

**Основные элементы:**

-   `Vagrant.configure("2")` — инициализация блока конфигурации. Число "2" указывает на версию API Vagrant.
-   `config` — объект, через который задаются параметры, общие для всех машин в файле.
-   `do |config| ... end` — блок Ruby, внутри которого описывается логика.

### Конструкция config.vm.define

Метод `config.vm.define` используется для описания конкретной виртуальной машины (особенно важно в мульти-машинных конфигурациях).

**Пример:**
```ruby
config.vm.define "web", primary: true do |web|
  web.vm.hostname = "web-server"
end
```

**Разбор по частям:**

-   `config` — главный объект конфигурации Vagrant.
-   `vm` — раздел, отвечающий за параметры виртуальных машин.
-   `define` — метод, создающий логическое описание отдельной ВМ.
-   `"web"` — имя ВМ в контексте Vagrant (используется в командах: `vagrant up web`).
-   `primary: true` — помечает машину как основную (запускается по умолчанию при `vagrant up` без аргументов).
-   `do |web| ... end` — блок Ruby, внутри которого `web` ссылается на объект конфигурации этой конкретной ВМ. Параметры внутри блока переопределяют глобальные настройки `config`.

### Ключевые параметры конфигурации

| Группа | Параметр | Описание |
| :--- | :--- | :--- |
| **Образ** | `config.vm.box` | Имя базового образа (например, `bento/ubuntu-24.04`). |
| | `config.vm.box_version` | Фиксация версии образа (`"~> 202501.0"`). |
| | `config.vm.box_url` | URL для загрузки образа, если его нет в Atlas/Cloud. |
| | `config.vm.box_check_update` | Проверка обновлений при каждом запуске (`true`/`false`). |
| | `config.vm.ignore_box_vagrantfile` | Игнорировать Vagrantfile, встроенный в образ. |
| **ОС** | `config.vm.hostname` | Имя хоста внутри ВМ. |
| | `config.vm.guest` | Тип гостевой ОС (например, `:linux`, `:ubuntu`). |
| **Сеть** | `config.vm.network` | Настройка портов (`forwarded_port`), частных (`private_network`) или публичных сетей. |
| **SSH** | `config.ssh.username` | Имя пользователя для подключения (по умолчанию `vagrant`). |
| | `config.ssh.private_key_path` | Путь к приватному ключу SSH. |
| | `config.ssh.forward_agent` | Проброс SSH-агента хоста в ВМ. |
| **Ресурсы** | `config.vm.provider` | Блок настроек гипервизора (память, CPU, специфические флаги). |
| **Файлы** | `config.vm.synced_folder` | Синхронизация директорий хоста и ВМ. |
| **Настройка**| `config.vm.provision` | Автоматизация установки ПО (Shell, Ansible, Docker). |
| | `run: "always"` | Параметр провижинера: выполнять при каждом `up` / `reload`. |
| **Инфо** | `config.vm.post_up_message` | Сообщение, выводимое после успешного запуска. |

## Практические сценарии

### Сценарий 1: Проверка наличия плагинов и установка

Автоматическая проверка и уведомление об отсутствующих плагинах:

```ruby
required_plugins = %w(vagrant-proxyconf vagrant-vbguest)
missing_plugins = required_plugins.select { |plugin| !Vagrant.has_plugin?(plugin) }

unless missing_plugins.empty?
  puts "Missing plugins: #{missing_plugins.join(', ')}"
  puts "Install them with: vagrant plugin install #{missing_plugins.join(' ')}"
  exit 1
end

Vagrant.configure("2") do |config|
  config.proxy.http = "http://192.168.1.100:3128" if Vagrant.has_plugin?("vagrant-proxyconf")
  config.vm.box = "bento/ubuntu-24.04"
end
```

### Сценарий 2: Использование внешнего файла настроек (Vagrantfile.local)

Для локальных правок, которые не должны попадать в Git (например, изменение объема RAM под конкретную машину разработчика):

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Загрузка локальных настроек, если файл существует
  if File.exist?("Vagrantfile.local")
    load "Vagrantfile.local"
  end
end
```

### Сценарий 3: Динамическая генерация машин из цикла

Создание кластера из нескольких узлов с инкрементальными IP:

```ruby
Vagrant.configure("2") do |config|
  (1..3).each do |i|
    config.vm.define "node-#{i}" do |node|
      node.vm.box = "bento/ubuntu-24.04"
      node.vm.hostname = "node-#{i}"
      node.vm.network "private_network", ip: "192.168.56.#{10 + i}"
      
      node.vm.provider "virtualbox" do |vb|
        vb.memory = 1024
        vb.name = "cluster-node-#{i}"
      end
    end
  end
end
```

### Сценарий 4: Загрузка конфигурации из YAML

Лучшая практика для разделения кода (Ruby) и данных (YAML):

```ruby
require 'yaml'
servers = YAML.load_file('servers.yml') if File.exist?('servers.yml')

Vagrant.configure("2") do |config|
  servers.each do |server|
    config.vm.define server['name'] do |node|
      node.vm.box = server['box'] || "bento/ubuntu-24.04"
      node.vm.network "private_network", ip: server['ip']
    end
  end
end
```

## Дополнительная информация

### Использование переменных окружения

Для гибкого управления параметрами без редактирования файла:

```ruby
Vagrant.configure("2") do |config|
  # Использование переменной или значения по умолчанию
  ram = ENV['VAGRANT_RAM'] || "2048"
  
  config.vm.provider "virtualbox" do |vb|
    vb.memory = ram.to_i
  end
end
```

### Управление провижинингом

Можно контролировать, когда именно запускаются скрипты настройки:

```ruby
# Запускать при каждом vagrant up / vagrant reload
config.vm.provision "shell", inline: "uptime", run: "always"

# Запускать только по явному запросу (vagrant provision)
config.vm.provision "shell", inline: "apt-get update", run: "never"
```

### Триггеры (Triggers)

Позволяют выполнять команды на хосте или в ВМ при определенных событиях:

```ruby
config.trigger.after :up do |trigger|
  trigger.info = "ВМ запущена. Выполняю локальный скрипт..."
  trigger.run = { inline: "bash notify_host.sh" }
end
```

### Валидация и отладка

```bash
# Проверка синтаксиса Vagrantfile
vagrant validate

# Просмотр итоговой конфигурации всех ВМ в проекте
vagrant status

# Запуск с подробным логированием процесса разбора файла
VAGRANT_LOG=debug vagrant status
```

### Лучшие практики

1.  **Комментарии:** Используйте комментарии для логического разделения секций.
2.  **Безопасность:** Не храните секреты в `Vagrantfile`. Используйте переменные окружения или плагин `vagrant-env`.
3.  **Идемпотентность:** Скрипты провижининга должны быть готовы к повторному запуску.
4.  **Версионирование:** Фиксируйте версию box (`config.vm.box_version`) и версию Vagrant (`config.vagrant.require_version`).

### См. также

- [Vagrant Basic Workflow](./vagrant_basic_workflow.md) — основы работы и жизненный цикл ВМ.
- [Vagrant Providers](./vagrant_providers.md) — детальная настройка гипервизоров.
- [Vagrant Networking](./vagrant_networking.md) — проброс портов и настройка сетей.
- [Vagrant Provisioning](./vagrant_provisioning.md) — автоматизация настройки гостевой ОС.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — триггеры и мульти-машины.
