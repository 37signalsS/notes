# Продвинутые сценарии использования Vagrant

## Определения

**Multi-Machine Vagrantfile** — конфигурация, описывающая группу взаимосвязанных виртуальных машин (ВМ) в рамках одного проекта. Позволяет моделировать сложные топологии: микросервисные архитектуры, кластеры баз данных и многоуровневые приложения (Frontend/Backend/DB).

**Triggers (триггеры)** — механизм выполнения произвольных действий (скриптов, команд) на хосте или внутри ВМ в ответ на события жизненного цикла Vagrant (до или после команд `up`, `halt`, `provision`, `destroy`).

**Динамическая конфигурация** — использование внешних источников данных (YAML/JSON файлы, переменные окружения) для управления параметрами ВМ без изменения основного кода `Vagrantfile`. Позволяет адаптировать окружение под нужды разных разработчиков или CI/CD-пайплайнов.

## Базовые концепции

### Продвинутая Multi-Machine архитектура

Vagrant позволяет не только описывать несколько машин, но и управлять их зависимостями, ролями и специфическими параметрами запуска.

**Ключевые параметры `config.vm.define`:**
- `primary: true` — помечает машину как основную. Она будет запускаться по умолчанию при выполнении `vagrant up` без указания имени.
- `autostart: false` — машина исключается из автоматического запуска при общей команде `up`. Требует явного вызова: `vagrant up <name>`.

**Пример оркестрации (Frontend + Backend + DB):**

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # База данных (запускается только вручную)
  config.vm.define "db", autostart: false do |db|
    db.vm.hostname = "db-node"
    db.vm.network "private_network", ip: "192.168.77.10"
  end

  # Веб-сервер (основной узел)
  config.vm.define "web", primary: true do |web|
    web.vm.hostname = "web-app"
    web.vm.network "private_network", ip: "192.168.77.11"
    # Ожидание готовности порта БД (пример простейшей зависимости)
    web.vm.provision "shell", inline: "until nc -z 192.168.77.10 5432; do sleep 1; done" 
  end
end
```

**Команды для управления мульти-машинами:**
```bash
vagrant up web              # Запустить конкретную ВМ
vagrant ssh db              # Подключиться к db (если она запущена)
vagrant status              # Статус всех машин в текущем проекте
vagrant halt web db         # Выключить выбранные машины
```

### Детальная настройка триггеров

Триггеры обеспечивают глубокую интеграцию Vagrant с хост-системой и внешними инструментами.

**Контексты и параметры выполнения:**
- `run_local`: Команда выполняется на хост-машине.
- `run_remote`: Команда выполняется внутри гостевой ОС (требует SSH).
- `run`: Псевдоним для выполнения (по умолчанию `local`).
- `abort: true`: Прерывает выполнение основной команды Vagrant, если триггер завершился с ошибкой.
- `on_error: :continue`: Продолжает работу, даже если триггер упал.

**Пример сложной автоматизации:**

```ruby
config.trigger.before :up do |trigger|
  trigger.name = "Pre-flight check"
  # Проверка наличия свободного места на хосте перед запуском
  trigger.run_local = { inline: "bash scripts/check_host_resources.sh", abort: true }
end

config.trigger.after :up do |trigger|
  trigger.name = "Post-up DNS automation"
  
  # Локальное действие: обновление /etc/hosts на хосте
  trigger.run_local = { 
    inline: "echo '192.168.77.11 web-app.local' | sudo tee -a /etc/hosts" 
  }
  
  # Удаленное действие: проверка статуса критического сервиса
  trigger.run_remote = { 
    inline: "systemctl is-active --quiet nginx || echo 'Warning: Nginx failed to start!'" 
  }
end
```

## Практические сценарии

### Сценарий 1: Генерация ВМ из внешнего YAML-конфига

Идеально для командной разработки, где параметры ресурсов выносятся в отдельный, понятный всем файл.

**Файл `servers.yml`:**
```yaml
- name: master
  ip: 192.168.10.10
  mem: 4096
  cpu: 2
- name: worker-1
  ip: 192.168.10.11
  mem: 2048
  cpu: 1
```

**Реализация в `Vagrantfile`:**
```ruby
require 'yaml'
servers = YAML.load_file('servers.yml') if File.exist?('servers.yml')

Vagrant.configure("2") do |config|
  servers.each do |server|
    config.vm.define server['name'] do |node|
      node.vm.box = "bento/ubuntu-24.04"
      node.vm.network "private_network", ip: server['ip']
      
      node.vm.provider "virtualbox" do |vb|
        vb.memory = server['mem']
        vb.cpus = server['cpu']
        vb.name = "cluster-#{server['name']}" # Уникальное имя в VirtualBox
      end
    end
  end
end
```

### Сценарий 2: Глобальные переменные окружения Vagrant

Управление поведением Vagrant через системные переменные без редактирования кода.

| Переменная | Описание |
| :--- | :--- |
| **`VAGRANT_CWD`** | Путь к директории, где искать `Vagrantfile`. |
| **`VAGRANT_DOTFILE_PATH`** | Путь к директории `.vagrant/` (полезно для изоляции веток/CI). |
| **`VAGRANT_HOME`** | Путь к глобальному кэшу образов и плагинов (`~/.vagrant.d`). |
| **`VAGRANT_LOG`** | Уровень логирования (`debug`, `info`, `warn`, `error`). |
| **`VAGRANT_DEFAULT_PROVIDER`** | Форсирует использование конкретного гипервизора. |
| **`VAGRANT_NO_PARALLEL`** | Отключает параллельный запуск машин (полезно при дефиците ресурсов). |

**Пример использования в терминале:**
```bash
VAGRANT_LOG=info VAGRANT_DEFAULT_PROVIDER=libvirt vagrant up
```

### Сценарий 3: Интеграция с Tailscale (Zero Trust VPN)

Автоматизация подключения ВМ к Mesh-сети для безопасного доступа без проброса портов.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  config.vm.provision "shell", inline: <<-SHELL
    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up --authkey=#{ENV['TAILSCALE_KEY']} --ssh --accept-routes
  SHELL

  config.trigger.before :destroy do |trigger|
    trigger.run_remote = { inline: "tailscale logout" }
  end
end
```

## Дополнительная информация

### Управление глобальным состоянием

Vagrant отслеживает все запущенные ВМ в системной базе данных. Команды для работы с «забытыми» ресурсами:

```bash
# Список всех ВМ, известных Vagrant в системе (со всех проектов)
vagrant global-status

# Очистка записей о машинах, которые были удалены вручную в гипервизоре
vagrant global-status --prune

# Управление машиной из любого места системы по её ID
vagrant ssh <id>
vagrant halt <id>
vagrant destroy <id> -f
```

### Лучшие практики

1.  **Изоляция метаданных:** При запуске нескольких копий проекта (например, разные фичи-ветки) используйте `VAGRANT_DOTFILE_PATH`, чтобы состояния `.vagrant/` не пересекались.
2.  **Безопасность триггеров:** Избегайте использования `sudo` в триггерах `run_local` без острой необходимости. Всегда проверяйте возвращаемые коды скриптов (`abort: true`).
3.  **Именование в гипервизоре:** В мульти-машинных конфигурациях всегда задавайте уникальные `vb.name` или `lv.name`, чтобы избежать коллизий имен при запуске нескольких кластеров на одном хосте.
4.  **Условная логика:** Используйте `if Vagrant.has_plugin?("...")` для настройки опций, зависящих от плагинов, чтобы файл оставался работоспособным у коллег без этих расширений.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — базовый синтаксис и структура.
- [Vagrant Networking: Сети кластера](./vagrant_networking.md) — настройка связи между узлами.
- [Vagrant Provisioning: Сложные сценарии](./vagrant_provisioning.md) — автоматизация настройки группы машин.
- [Vagrant Troubleshooting: Логирование](./vagrant_troubleshooting/basic_concepts.md) — детальная отладка через переменные окружения.
