# Продвинутые сценарии использования Vagrant

## Определения

**Multi-Machine Vagrantfile** — конфигурация, описывающая группу взаимосвязанных виртуальных машин в рамках одного проекта. Позволяет моделировать сложные топологии: микросервисные архитектуры, кластеры баз данных и многоуровневые приложения (Frontend/Backend/DB).

**Triggers (триггеры)** — механизм выполнения произвольных действий (скриптов, команд) в ответ на события жизненного цикла Vagrant (до или после команд `up`, `halt`, `provision`, `destroy`).

**Динамическая конфигурация** — использование внешних источников данных (YAML-файлы, переменные окружения) для управления параметрами ВМ без изменения основного кода `Vagrantfile`.

## Базовые концепции

### Продвинутая Multi-Machine архитектура

Vagrant позволяет не только описывать несколько машин, но и управлять их зависимостями и ролями.

**Основные возможности:**
- `config.vm.define "name", primary: true` — помечает машину как основную (она будет запускаться по умолчанию при выполнении `vagrant up` без аргументов).
- `config.vm.define "name", autostart: false` — машина не будет запускаться автоматически при общей команде `up`.

**Пример оркестрации:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # База данных (вспомогательный узел)
  config.vm.define "db", autostart: false do |db|
    db.vm.hostname = "db-node"
    db.vm.network "private_network", ip: "192.168.77.10"
  end

  # Веб-сервер (основной узел)
  config.vm.define "web", primary: true do |web|
    web.vm.hostname = "web-app"
    web.vm.network "private_network", ip: "192.168.77.11"
    # Ожидание готовности БД через shell
    web.vm.provision "shell", inline: "sleep 10" 
  end
end
```

**Команды для конкретных машин:**

```bash
vagrant up web              # Запустить только web
vagrant ssh db              # Подключиться к db (если она запущена)
vagrant status              # Статус всех машин проекта
```

### Детальная настройка триггеров

Триггеры могут выполняться в разных контекстах, что критично для автоматизации.

**Контексты выполнения:**
- `run_local`: Команда выполняется на хост-машине.
- `run_remote`: Команда выполняется внутри гостевой ОС (требует активного SSH-соединения).
- `run`: Псевдоним для выполнения в зависимости от ситуации (по умолчанию `local`).

**Пример сложного триггера:**

```ruby
config.trigger.after :up do |trigger|
  trigger.name = "Post-up Automation"
  
  # Локальное действие: обновление файла /etc/hosts на хосте
  trigger.run_local = { 
    inline: "echo '192.168.77.11 web-app.local' | sudo tee -a /etc/hosts" 
  }
  
  # Удаленное действие: проверка статуса сервиса
  trigger.run_remote = { 
    inline: "systemctl is-active --quiet nginx || echo 'Warning: Nginx is not running!'" 
  }
end
```

## Практические сценарии

### Сценарий 1: Генерация ВМ из внешнего YAML-конфига

Лучшая практика для больших команд — вынос настроек ресурсов в отдельный файл, который не требует знаний Ruby для редактирования.

**Файл `servers.yml`:**
```yaml
- name: master
  ip: 192.168.10.10
  mem: 2048
  cpu: 2
- name: worker-1
  ip: 192.168.10.11
  mem: 1024
  cpu: 1
```

**Реализация в `Vagrantfile`:**
```ruby
require 'yaml'

servers = YAML.load_file('servers.yml')

Vagrant.configure("2") do |config|
  servers.each do |server|
    config.vm.define server['name'] do |node|
      node.vm.box = "bento/ubuntu-24.04"
      node.vm.network "private_network", ip: server['ip']
      
      node.vm.provider "libvirt" do |lv|
        lv.memory = server['mem']
        lv.cpus = server['cpu']
      end
    end
  end
end
```

### Сценарий 2: Глобальные переменные окружения Vagrant

Vagrant поддерживает ряд системных переменных, управляющих поведением самого приложения.

| Переменная | Описание |
| :--- | :--- |
| `VAGRANT_CWD` | Изменяет рабочую директорию (где искать `Vagrantfile`). |
| `VAGRANT_DOTFILE_PATH` | Изменяет путь к директории `.vagrant/` (полезно для CI/CD). |
| `VAGRANT_HOME` | Путь к глобальному кэшу образов и плагинов (`~/.vagrant.d`). |
| `VAGRANT_LOG` | Уровень логирования (`debug`, `info`, `warn`, `error`). |
| `VAGRANT_DEFAULT_PROVIDER` | Форсирует использование конкретного провайдера. |

**Пример использования в CLI:**
```bash
VAGRANT_LOG=info VAGRANT_DEFAULT_PROVIDER=libvirt vagrant up
```

### Сценарий 3: Интеграция с Tailscale (Zero Trust VPN)

Автоматическое подключение ВМ к приватной сети Tailscale для безопасного доступа.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  config.vm.provision "shell", inline: <<-SHELL
    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up --authkey=#{ENV['TAILSCALE_KEY']} --ssh
  SHELL

  config.trigger.before :destroy do |trigger|
    trigger.run_remote = { inline: "tailscale logout" }
  end
end
```

## Дополнительная информация

### Управление глобальным состоянием

При работе с множеством проектов полезно знать команды управления «забытыми» машинами:

```bash
# Список всех ВМ, известных Vagrant в системе
vagrant global-status

# Очистка записей о машинах, которые были удалены вручную
vagrant global-status --prune

# Подключение к машине из любого места системы (по ID из global-status)
vagrant ssh <id>
```

### Лучшие практики

1.  **Изоляция метаданных:** Если вы запускаете несколько копий одного проекта (например, для разных веток Git), используйте `VAGRANT_DOTFILE_PATH`, чтобы состояния `.vagrant/` не конфликтовали.
2.  **Безопасность триггеров:** Избегайте использования `sudo` в триггерах `run_local`, если это возможно. Если `sudo` необходимо, убедитесь, что команда не требует интерактивного ввода пароля.
3.  **Именование в мульти-машинах:** Всегда задавайте уникальные `vb.name` или `lv.management_network_name`, чтобы избежать коллизий на уровне гипервизора при запуске нескольких кластеров.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — базовый синтаксис и параметры.
- [Vagrant Networking: Кластерные сети](./vagrant_networking.md#сценарий-2-мульти-стек-сеть-ipv4-ipv6) — настройка связи между узлами.
- [Vagrant Provisioning: Сложные сценарии](./vagrant_provisioning.md#сценарий-4-совмещение-и-порядок-выполнения) — порядок настройки группы машин.
- [Vagrant Troubleshooting: Логирование](./vagrant_troubleshooting/basic_concepts.md) — детальная отладка через переменные окружения.