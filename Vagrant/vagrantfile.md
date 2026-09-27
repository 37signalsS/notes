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

| **Образ** | `config.vm.box` | Имя базового образа (например, `bento/ubuntu-24.04`). |
| | `config.vm.box_version` | Фиксация версии образа (`"~> 202501.0"`). |
| | `config.vm.box_url` | URL для загрузки образа, если его нет в Atlas/Cloud. |
| | `config.vm.box_check_update` | Проверка обновлений при каждом запуске (`true`/`false`). |
| | `config.vm.box_download_checksum` | Хэш для верификации целостности скачиваемого образа. |
| | `config.vm.box_download_checksum_type` | Алгоритм хэширования (`sha256`, `sha512`). |
| | `config.vm.ignore_box_vagrantfile` | Игнорировать Vagrantfile, встроенный в образ. |
| **ОС** | `config.vm.hostname` | Имя хоста внутри ВМ. |
| | `config.vm.guest` | Тип гостевой ОС (например, `:linux`, `:ubuntu`). |
| | `config.vm.boot_timeout` | Таймаут загрузки ВМ в секундах (по умолчанию `300`). Увеличивайте в CI. |
| | `config.vm.graceful_halt_timeout` | Таймаут корректной остановки ВМ в секундах (по умолчанию `60`). |
| **Сеть** | `config.vm.network` | Настройка портов (`forwarded_port`), частных (`private_network`) или публичных сетей. |
| **SSH** | `config.ssh.username` | Имя пользователя для подключения (по умолчанию `vagrant`). |
| | `config.ssh.private_key_path` | Путь к приватному ключу SSH. |
| | `config.ssh.forward_agent` | Проброс SSH-агента хоста в ВМ. |
| | `config.ssh.insert_key` | Вставлять уникальный SSH-ключ при первом запуске (`true`/`false`). |
| | `config.vm.communicator` | Тип коммуникатора: `ssh` (Linux/macOS) или `winrm` (Windows). |
| **Ресурсы** | `config.vm.provider` | Блок настроек гипервизора (память, CPU, специфические флаги). |
| **Файлы** | `config.vm.synced_folder` | Синхронизация директорий хоста и ВМ (детали в [Vagrant Storage](./vagrant_storage_and_folders.md)). |
| **Настройка**| `config.vm.provision` | Автоматизация установки ПО (Shell, Ansible, Docker). |
| | `run: "always"` | Параметр провижинера: выполнять при каждом `up` / `reload`. |
| **Мульти-машины** | `config.vm.primary` | Помечает ВМ как основную (запускается по умолчанию). |
| | `config.vm.autostart` | Если `false`, ВМ исключается из автоматического запуска (`vagrant up`). |
| | `config.trigger` | Триггеры жизненного цикла (`before`/`after` для `up`, `halt`, `provision`, `destroy`). |
| **Инфо** | `config.vm.post_up_message` | Сообщение, выводимое после успешного запуска. |

## Практические сценарии

### Сценарий 0: Работа с Windows и WinRM

Для гостевых ОС Windows используется коммуникатор `winrm` вместо `ssh`. Vagrant автоматически настраивает WinRM при указании соответствующего коммуникатора.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "gusztavvargadr/windows-server-2022"
  config.vm.communicator = "winrm"
  config.vm.username = "vagrant"
  config.vm.password = "vagrant"

  config.vm.provider "virtualbox" do |vb|
    vb.memory = 4096
    vb.cpus = 2
  end
end
```

**Важные нюансы:**
- WinRM требует предварительной настройки гостевой ОС (доверенные хосты, сертификаты).
- Плагин `vagrant-winrm` может потребоваться для специфичных сценариев.
- Атрибут `config.ssh.private_key_path` игнорируется при использовании WinRM.

### Ruby DSL: расширенные возможности

Vagrantfile — это полноценный Ruby-скрипт, что позволяет использовать всю мощь языка для динамической генерации конфигурации.

**Условная логика и обнаружение платформ:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  if Vagrant::Util::Platform.linux?
    config.vm.provider "libvirt" do |lv|
      lv.memory = 2048
    end
  elsif Vagrant::Util::Platform.darwin?
    config.vm.provider "virtualbox" do |vb|
      vb.memory = 2048
    end
  end
end
```

**Динамическая загрузка внешних файлов:**

```ruby
require 'yaml'

# Загрузка параметров из YAML (отделяет данные от кода)
if File.exist?("vagrant_config.yml")
  settings = YAML.load_file("vagrant_config.yml")
  config.vm.box = settings["box"] || "bento/ubuntu-24.04"
end
```

**Проверка зависимостей и плагинов:**

```ruby
required_plugins = %w(vagrant-vbguest vagrant-proxyconf)

missing_plugins = required_plugins.reject { |plugin| Vagrant.has_plugin?(plugin) }
unless missing_plugins.empty?
  abort "Missing plugins: #{missing_plugins.join(', ')}"
end
```

**Директивы Vagrant:**

```ruby
# Классический заголовок для редакторов
# -*- mode: ruby -*-
# vi: set ft=ruby :
```

### Верификация образов и безопасность

Для защиты от компрометации базовых образов ( Supply Chain Attack ) используйте контрольные суммы:

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.box_version = "202501.0"
  
  # Верификация SHA-256 при загрузке
  config.vm.box_download_checksum = "a1b2c3d4e5f6..."
  config.vm.box_download_checksum_type = "sha256"
end
```

**Проверка соответствия:**
```bash
# Получение контрольной суммы существующего box
vagrant box list --checksum bento/ubuntu-24.04
```

### Ограничения и крайние случаи

1. **Производительность парсинга:** Очень большие Vagrantfile (>500 строк с циклами) могут замедлять выполнение команд. Выносите данные в YAML/JSON.
2. **Одновременный запуск:** По умолчанию Vagrant запускает все ВМ параллельно. При дефиците RAM используйте `VAGRANT_NO_PARALLEL=true`.
3. **Совместимость Ruby:** Vagrant поставляется со встроенным Ruby. Используйте только стандартную библиотеку Ruby, чтобы обеспечить совместимость.
4. **Размер образа:** Избегайте хранения больших файлов в общих папках на хосте — это влияет на производительность `vboxsf`/`virtiofs`.

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

### Сценарий 5: Использование в CI/CD (неинтерактивный режим)

Для автоматизированных пайплайнов (Jenkins, GitLab CI, GitHub Actions) Vagrantfile должен работать без интерактивных запросов:

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.box_check_update = false  # Отключить проверку обновлений в CI

  # Увеличенные таймауты для медленных CI-агентов
  config.vm.boot_timeout = 600
  config.vm.graceful_halt_timeout = 120

  # Провайдер для headless-сред (Libvirt/KVM)
  config.vm.provider "libvirt" do |lv|
    lv.memory = 2048
    lv.cpus = 2
    lv.graphics_type = "none"        # Без GUI
    lv.video_type = "none"           # Без видеокарты
  end
end
```

**Запуск в CI:**
```bash
export VAGRANT_NO_TTY=1
export VAGRANT_DEFAULT_PROVIDER=libvirt
vagrant up --no-provision  # Сначала ВМ, потом провижининг отдельно
```

### Сценарий 6: Верификация целостности образа

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.box_version = "202501.0"
  config.vm.box_download_checksum = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  config.vm.box_download_checksum_type = "sha256"
end
```

**Проверка контрольной суммы существующего образа:**
```bash
vagrant box list --checksum bento/ubuntu-24.04
# → bento/ubuntu-24.04 (202501.0, virtualbox, sha256:e3b0c44298fc...)
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

# Постоянный файл лога для анализа
VAGRANT_LOG=debug VAGRANT_LOG_FILE=/tmp/vagrant_debug.log vagrant up
```

### Типичные ошибки Vagrantfile

**SyntaxError / NoMethodError:**
```bash
# Ошибка: undefined method 'vm' for nil:NilClass
# Причина: обращение к config.vm до Vagrant.configure("2")
```

**Решение:** Весь код, взаимодействующий с `config`, должен находиться внутри блока `Vagrant.configure("2") do |config| ... end`.

**Конфликт слияния конфигураций:**
```bash
# Симптом: настройка не применяется
# Диагностика: запустите с VAGRANT_LOG=debug и найдите строку "Applying"
```

**Решение:** Используйте `config.vm.define` с уникальными именами и проверяйте приоритеты (Project > User > Box).

**Медленный запуск из-за сложного Ruby:**
```bash
# Профилируйте выполнение Vagrantfile
time vagrant validate
```

**Решение:** Выносите данные в YAML/JSON. Избегайте тяжелых операций (HTTP-запросы) на этапе парсинга.

**State Desync (рассинхронизация):**
```bash
# Симптом: Vagrant "не видит" работающую ВМ
# Решение: vagrant global-status --prune && vagrant up
```

### Лучшие практики

1.  **Комментарии:** Используйте комментарии для логического разделения секций.
2.  **Безопасность:** Не храните секреты в `Vagrantfile`. Используйте переменные окружения или плагин `vagrant-env`.
3.  **Идемпотентность:** Скрипты провижининга должны быть готовы к повторному запуску.
4.  **Версионирование:** Фиксируйте версию box (`config.vm.box_version`) и версию Vagrant (`config.vagrant.require_version`).

### См. также

- [Vagrant Providers](./vagrant_providers.md) — детальная настройка гипервизоров и образов.
- [Vagrant Provisioning](./vagrant_provisioning.md) — автоматизация настройки гостевой ОС.
- [Vagrant Networking](./vagrant_networking.md) — проброс портов, приватные и публичные сети.
