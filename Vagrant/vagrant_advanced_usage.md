# Продвинутые сценарии использования Vagrant

## Определения

**Multi-Machine Vagrantfile** — конфигурация, описывающая группу взаимосвязанных виртуальных машин (ВМ) в рамках одного проекта. Позволяет моделировать сложные топологии: микросервисные архитектуры, кластеры баз данных и многоуровневые приложения (Frontend/Backend/DB).

**Triggers (триггеры)** — механизм выполнения произвольных действий (скриптов, команд) на хосте или внутри ВМ в ответ на события жизненного цикла Vagrant (до или после команд `up`, `halt`, `provision`, `destroy`).

**Динамическая конфигурация** — использование внешних источников данных (YAML/JSON файлы, переменные окружения) для управления параметрами ВМ без изменения основного кода `Vagrantfile`. Позволяет адаптировать окружение под нужды разных разработчиков или CI/CD-пайплайнов.

**Health Check (проверка работоспособности)** — автоматическая валидация доступности сервиса после запуска ВМ. В контексте Vagrant реализуется через shell-провижинеры или триггеры, ожидающие открытия порта или завершения инициализации службы.

**Pre-flight проверка** — набор валидаций, выполняемых на хосте перед запуском ВМ (свободное место, доступность ресурсов, корректность параметров). Реализуется через `trigger.before :up` с `abort: true`.

**Communicator (коммуникатор)** — программный мост, через который Vagrant отправляет команды внутрь ВМ. Основные типы: `ssh` (Linux/macOS) и `winrm` (Windows). От коммуникатора зависит этап провижининга и монтирования общих папок.

**Suspend/Resume** — механизм сохранения полного состояния ВМ (ОЗУ, CPU, устройства) в файл на диске гипервизора. В отличие от `halt` (штатное завершение работы гостевой ОС), `suspend` замораживает ВМ и позволяет мгновенно возобновить работу без загрузки. Состояние переживает перезагрузку хоста.

## Базовые концепции

### Продвинутая Multi-Machine архитектура

Vagrant позволяет не только описывать несколько машин, но и управлять их зависимостями, ролями и специфическими параметрами запуска.

**Ключевые параметры `config.vm.define`:**
- `primary: true` — помечает машину как основную. Она будет запускаться по умолчанию при выполнении `vagrant up` без указания имени.
- `autostart: false` — машина исключается из автоматического запуска при общей команде `up`. Требует явного вызова: `vagrant up <name>`.

**Порядок запуска и зависимость:**
По умолчанию Vagrant запускает все ВМ параллельно. Для сложных топологий (БД → кэш → бекенд → фронтенд) необходимо использовать явный порядок или проверки готовности.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # База данных (запускается только вручную или первой)
  config.vm.define "db", primary: false do |db|
    db.vm.hostname = "db-node"
    db.vm.network "private_network", ip: "192.168.77.10"
    db.vm.provision "shell", inline: <<-SHELL
      systemctl enable --now postgresql
      sudo -u postgres psql -c "SELECT 1;" || exit 1
    SHELL
  end

  # Кэш (зависит от БД)
  config.vm.define "cache", autostart: false do |cache|
    cache.vm.hostname = "cache-node"
    cache.vm.network "private_network", ip: "192.168.77.12"
    cache.vm.provision "shell", inline: <<-SHELL
      until nc -z 192.168.77.10 5432; do sleep 1; done
      systemctl enable --now redis-server
    SHELL
  end

  # Веб-сервер (основной узел, зависит от обоих)
  config.vm.define "web", primary: true do |web|
    web.vm.hostname = "web-app"
    web.vm.network "private_network", ip: "192.168.77.11"
    web.vm.provision "shell", inline: <<-SHELL
      until nc -z 192.168.77.10 5432; do sleep 1; done
      until nc -z 192.168.77.12 6379; do sleep 1; done
      systemctl enable --now nginx
    SHELL
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

**События, на которые можно вешать триггеры:**
- `:up` — перед/после запуска ВМ
- `:halt` — перед/после выключения
- `:destroy` — перед/после удаления
- `:provision` — перед/после провижининга
- `:reload` — перед/после перезагрузки

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

config.trigger.after :destroy do |trigger|
  trigger.name = "Cleanup"
  # Очистка временных файлов на хосте
  trigger.run_local = { inline: "rm -f /tmp/vagrant-*" }
end
```

### Динамическая конфигурация и генерация окружения

Vagrantfile — это полноценный Ruby-скрипт, что позволяет использовать всю мощь языка для динамической генерации конфигурации.

**Источники данных:**
- YAML/JSON файлы — человекочитаемые описания инстансов.
- Переменные окружения — для CI/CD и секретов.
- ERB-шаблоны — для сложной логики генерации.
- Логика на Ruby — циклы, условия, вычисления.

**Пример чтения из YAML:**

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
        vb.name = "cluster-#{server['name']}"
      end
    end
  end
end
```

**Пример условной логики по платформе хоста:**

```ruby
Vagrant.configure("2") do |config|
  if Vagrant::Util::Platform.linux?
    config.vm.provider "libvirt" do |lv|
      lv.memory = 2048
      lv.cpus = 2
      lv.nested = true
    end
  elsif Vagrant::Util::Platform.darwin?
    config.vm.provider "virtualbox" do |vb|
      vb.memory = 2048
      vb.cpus = 2
      vb.linked_clone = true
    end
  else
    config.vm.provider "hyperv" do |h|
      h.memory = 2048
      h.cpus = 2
    end
  end
end
```

### Коммуникаторы: SSH и WinRM тонкая настройка

**SSH (Linux/macOS/BSD):**
Vagrant по умолчанию использует SSH с сгенерированным ключом. Для продвинутых сценариев:

```ruby
Vagrant.configure("2") do |config|
  config.ssh.username = "vagrant"
  config.ssh.private_key_path = ["~/.vagrant.d/insecure_private_key", "~/.ssh/id_ed25519"]
  config.ssh.forward_agent = true
  config.ssh.forward_x11 = false
  config.ssh.shell = "bash -l"
  config.ssh.keep_alive = true
  config.ssh.connect_timeout = 30
  config.ssh.insert_key = true
end
```

**WinRM (Windows):**
Для гостевых ОС Windows используется коммуникатор `winrm` вместо `ssh`. Vagrant автоматически настраивает WinRM при указании соответствующего коммуникатора.

```ruby
Vagrant.configure("2") do |config|
  config.vm.communicator = "winrm"
  config.vm.username = "vagrant"
  config.vm.password = "vagrant"
  config.winrm.transport = :ssl
  config.winrm.ssl_peer_verification = false
end
```

> **Примечание:** Плагин `vagrant-winrm` может потребоваться для специфичных сценариев.

### SSH: известные хосты и доступ через bastion

При автоматизации (CI) и доступе через jump-host возникают типовые вопросы host key verification. Vagrant сам не требует ручного подтверждения хоста, но при вызове системного `ssh` с `-F <(vagrant ssh-config)` валидацию нужно настраивать осознанно.

```bash
# CI: сервер одноразовый, подтверждать fingerprint автоматически
ssh -F <(vagrant ssh-config) \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=/dev/null \
  default

# Изолированный known_hosts для vagrant-окружений (не разрастает ~/.ssh/known_hosts)
export SSH_KNOWN_HOSTS="$HOME/.ssh/known_hosts.vagrant"
ssh -F <(vagrant ssh-config) -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" default
```

Правила безопасности:

- `StrictHostKeyChecking=no` и `UserKnownHostsFile=/dev/null` допустимы **только** в эфемерных CI-машинах; для постоянных ВМ используйте `accept-new` либо заранее внесённые fingerprint'ы.
- **SSH-агент форвардится только через первую «прыжковую» машину**: `config.ssh.forward_agent = true` работает до первого бастиона, дальше по цепочке агент не передаётся. Для многосегментного доступа поднимайте локальные туннели (Сценарий 12), а не цепочки агента.
- Внешний доступ к ВМ в приватной сети — через **bastion/jump-host**: `vagrant ssh-config` даёт параметры цели, а реальное подключение идёт через промежуточный узел, на котором уже есть агент или ключ.

### Управление ресурсами и лимитами

При работе с мульти-машинными окружениями важно контролировать распределение ресурсов хоста.

**Рекомендации по ресурсам:**
- Фиксируйте `memory` и `cpus` для каждой ВМ, чтобы избежать превышения лимитов хоста.
- Используйте `VAGRANT_NO_PARALLEL=true` при дефиците RAM, чтобы запускать машины последовательно.
- Для Libvirt включите `nested = true` и `cpu_mode = "host-passthrough"` для вложенной виртуализации.
- Для VirtualBox используйте `linked_clone = true` для экономии дискового пространства.

**Пример ограничения ресурсов:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "libvirt" do |lv|
    lv.memory = 2048
    lv.cpus = 2
    lv.nested = true
    lv.cpu_mode = "host-passthrough"
    lv.storage_pool_name = "default"
  end
end
```

**Глубокая настройка производительности (Libvirt): NUMA, memory backing, balloon**

`vagrant-libvirt` пробрасывает в домен QEMU топологию NUMA, политики памяти и параметры balloon. Настройка узлов/libvirt на стороне хоста (резервирование hugepages в GRUB, отключение THP, `numastat`, `numactl`) — вне Vagrant, см. [Performance Tuning KVM](../Linux/Virtualization/kvm/performance_tuning_2026.md).

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "libvirt" do |lv|
    lv.cpus  = 4
    lv.memory = 4096

    # Топология NUMA для гостя: распределение vCPU и памяти по узлам (память в MB)
    lv.numa_nodes = [
      { cpus: "0-1", memory: "2048" },
      { cpus: "2-3", memory: "2048" },
    ]

    # Memory backing (memoryBacking в domain XML)
    lv.memorybacking :source, :type => "memfd"   # общая таблица страниц
    lv.memorybacking :access, :mode => "shared"   # MMAP-разделяемая память (в официальных примерах для virtiofs)
    lv.memorybacking :nosharepages                # запрет совместного использования страниц KSM
    # lv.memorybacking :hugepages                 # использовать hugepages (см. примечание)
    # lv.memorybacking :locked                    # запрет swap (mlock)

    # Balloon: по умолчанию libvirt вешает virtio-balloon — для стабильности отключить
    lv.memballoon_enabled = false

    # Управление CPU
    lv.cpu_affinity = "0-3"   # пиннинг vCPU на физические ядра
  end
end
```

Примечания:

- Полный элемент `<hugepages>` с per-node страницами в `vagrant-libvirt` реализован не полностью — для точного контроля hugepages правьте домен через `virsh edit` либо настройте память на уровне хоста (см. [Performance Tuning KVM](../Linux/Virtualization/kvm/performance_tuning_2026.md)).
- При использовании `numa_nodes` сумма `memory` по узлам и число vCPU должны совпадать с `lv.memory` и `lv.cpus`.
- `memorybacking :access :shared` фигурирует в официальных примерах vagrant-libvirt для `virtiofs` на свежих libvirt/QEMU.

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
        vb.name = "cluster-#{server['name']}"
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
| **`VAGRANT_NO_TTY`** | Отключает интерактивный режим (обязательно для CI/CD). |
| **`VAGRANT_BOX_UPDATE_CHECK`** | Отключает проверку обновлений box (ускоряет CI). |

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

### Сценарий 4: Последовательный запуск с явными зависимостями

Для топологий, где порядок запуска критичен (БД → бекенд → фронтенд), используйте явный sequential запуск с health-check ожиданиями.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  config.vm.define "db" do |db|
    db.vm.hostname = "db-node"
    db.vm.network "private_network", ip: "192.168.77.10"
    db.vm.provision "shell", inline: <<-SHELL
      systemctl enable --now postgresql
      sudo -u postgres psql -c "SELECT 1;" || exit 1
    SHELL
  end

  config.vm.define "app" do |app|
    app.vm.hostname = "app-node"
    app.vm.network "private_network", ip: "192.168.77.11"
    app.vm.provision "shell", inline: <<-SHELL
      until nc -z 192.168.77.10 5432; do sleep 2; done
      systemctl enable --now myapp
    SHELL
  end

  config.vm.define "web", primary: true do |web|
    web.vm.hostname = "web-node"
    web.vm.network "private_network", ip: "192.168.77.12"
    web.vm.provision "shell", inline: <<-SHELL
      until nc -z 192.168.77.11 8080; do sleep 2; done
      systemctl enable --now nginx
    SHELL
  end
end
```

**Запуск:**
```bash
# Запустить все в порядке зависимостей (db → app → web)
vagrant up db
vagrant up app
vagrant up web

# Или запустить только основную машину (web), если db и app уже запущены
vagrant up
```

### Сценарий 5: Pre-flight проверки ресурсов через триггеры

Автоматическая проверка свободного места на хосте перед запуском ВМ, предотвращающая частичный сбой.

```ruby
config.trigger.before :up do |trigger|
  trigger.name = "Pre-flight: disk space"
  trigger.run_local = {
    inline: <<-BASH
      threshold=90
      usage=$(df -hT ~/.vagrant.d | awk 'NR==2 {print $5}' | tr -d '%')
      if [ "$usage" -ge "$threshold" ]; then
        echo "ERROR: Disk usage ${usage}% exceeds ${threshold}%"
        exit 1
      fi
    BASH
  }
  trigger.abort = true
end

config.trigger.before :up do |trigger|
  trigger.name = "Pre-flight: RAM availability"
  trigger.run_local = {
    inline: "free -m | awk 'NR==2 {exit ($7+0 < 2048)}' || (echo 'ERROR: Less than 2GB RAM free' && exit 1)"
  }
  trigger.abort = true
end
```

### Сценарий 6: Динамическая генерация кластера из JSON

Для крупных кластеров используйте JSON с полными конфигурациями, включая провижининг и сети.

**Файл `cluster.json`:**
```json
{
  "nodes": [
    {
      "name": "k8s-master",
      "ip": "192.168.100.10",
      "mem": 4096,
      "cpu": 4,
      "roles": ["master", "etcd"]
    },
    {
      "name": "k8s-worker-1",
      "ip": "192.168.100.11",
      "mem": 2048,
      "cpu": 2,
      "roles": ["worker"]
    },
    {
      "name": "k8s-worker-2",
      "ip": "192.168.100.12",
      "mem": 2048,
      "cpu": 2,
      "roles": ["worker"]
    }
  ]
}
```

**Реализация в `Vagrantfile`:**
```ruby
require 'json'
cluster = JSON.parse(File.read('cluster.json')) if File.exist?('cluster.json')

Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  cluster['nodes'].each do |node|
    config.vm.define node['name'] do |n|
      n.vm.hostname = node['name']
      n.vm.network "private_network", ip: node['ip']
      
      n.vm.provider "libvirt" do |lv|
        lv.memory = node['mem']
        lv.cpus = node['cpu']
        lv.nested = true if node['roles'].include?('worker')
      end
      
      n.vm.provision "shell", inline: <<-SHELL
        echo "Roles: #{node['roles'].join(', ')}"
        hostnamectl set-hostname #{node['name']}
      SHELL
    end
  end
end
```

### Сценарий 7: Smoke-тесты после запуска через триггеры

Проверка доступности HTTP-сервисов и критических портов после `vagrant up`.

```ruby
config.trigger.after :up do |trigger|
  trigger.name = "Smoke test: web health"
  trigger.run_remote = {
    inline: <<-SHELL
      timeout 60 bash -c 'until curl -sf http://localhost:3000/health; do sleep 2; done'
      echo "Health check passed"
    SHELL
  }
  trigger.abort = true
end

config.trigger.after :up do |trigger|
  trigger.name = "Smoke test: database connectivity"
  trigger.run_remote = {
    inline: "pg_isready -h 127.0.0.1 -p 5432 || (echo 'DB not ready' && exit 1)"
  }
  trigger.abort = true
end
```

### Сценарий 8: Гостевой firewall и SSH hardening

Автоматическая настройка безопасности внутри гостевой ОС при развертывании.

```ruby
config.vm.provision "shell", inline: <<-SHELL
  # Отключение парольной аутентификации SSH
  sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
  sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
  
  # Ограничение попыток входа
  echo "MaxAuthTries 2" >> /etc/ssh/sshd_config
  
  # Перезапуск sshd
  systemctl restart sshd
  
  # Включение файрвола (разрешить только SSH и HTTP)
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
SHELL
```

### Сценарий 9: Интеграция с локальными скриптами и tooling

Вызов локальных инструментов (Ansible, Terraform, PowerShell) через триггеры до/after основных операций Vagrant.

```ruby
config.trigger.before :up do |trigger|
  trigger.name = "Local: Ansible syntax check"
  trigger.run_local = {
    inline: "ansible-playbook --syntax-check playbooks/site.yml"
  }
  trigger.abort = true
end

config.trigger.after :up do |trigger|
  trigger.name = "Local: Update /etc/hosts"
  trigger.run_local = {
    inline: "./scripts/update-hosts.sh"
  }
end

config.trigger.after :destroy do |trigger|
  trigger.name = "Local: Cleanup artifacts"
  trigger.run_local = {
    inline: "rm -f /tmp/vagrant-*.log"
  }
end
```

### Сценарий 10: Suspend/Resume для быстрого контекста

Сохраняйте полное состояние ВМ на диске гипервизора для мгновенного возврата к работе (без загрузки ОС).

```bash
# Приостановить ВМ (состояние ОЗУ/CPU записывается в файл состояния на диск)
vagrant suspend

# Вернуться к работе (мгновенно, не требует полной загрузки)
vagrant resume

# Штатное выключение: гостевая ОС корректно завершает работу
vagrant halt

# Проверка статуса
vagrant status
# → current state: saved (suspended)
```

**Важно:** При `suspend` время гостевой ОС останавливается. После `resume` возможен clock drift — настройте NTP внутри гостя.

### Сценарий 11: Управление состоянием multi-machine: backup и restore

Создание переносимых архивов для мульти-машинных окружений.

```bash
# 1. Остановка всех ВМ
vagrant halt

# 2. Упаковка каждой ВМ
for vm in web app db; do
  vagrant package --output ${vm}-backup.box --vagrantfile Vagrantfile.${vm}
done

# 3. Экспорт метаданных
cp -r .vagrant ./vagrant-metadata-backup
vagrant global-status --prune > global-status-backup.txt
vagrant plugin list > plugins-backup.txt
```

**Восстановление:**
```bash
# Добавление образов
vagrant box add web-restore ./web-backup.box --name web-restore
vagrant box add app-restore ./app-backup.box --name app-restore
vagrant box add db-restore ./db-backup.box --name db-restore

# Запуск
vagrant up
```

### Сценарий 12: SSH-туннели и работа с внешним SSH-клиентом

Проброс портов на уровне SSH («нативный туннель») отличается от `forwarded_port` гипервизора: работает через `vagrant ssh` и годится для доступа к сервисам в приватной сети либо для подключения внешнего клиента (VS Code, rsync, дебаггер).

```bash
# Прямой туннель: хост:8080 → ВМ:localhost:80
vagrant ssh -- -L 8080:localhost:80 -N

# Обратный туннель: гость:2222 → хост:localhost:22 (для доступа гостя наружу)
vagrant ssh -- -R 2222:localhost:22

# Сочетание туннелей и внешних опций SSH: остальные ключи идут после "--"
vagrant ssh web -- -L 5432:db:5432 -o ServerAliveInterval=15
```

**Подключение системным `ssh` (для IDE/rsync):** Vagrant генерирует готовый SSH-конфиг:

```bash
vagrant ssh-config
# → Host default
#   HostName 127.0.0.1
#   Port 2222
#   User vagrant
#   IdentityFile .../private_key

# Использование сгенерированного конфига
ssh -F <(vagrant ssh-config) default
# для конкретной машины: ssh -F <(vagrant ssh-config web) web
```

**Jump-хост внутри multi-machine:** доступ к приватным узлам через промежуточную ВМ:

```bash
# web → доступ к бд: реальный прыжок через узел web
vagrant ssh web -- -L 15432:db:5432 -N
# затем локально: psql -h localhost -p 15432
```

**Требования:** включите проброс агента (`config.ssh.forward_agent = true`) в `Vagrantfile`, чтобы в гостях работали агентные ключи SSH (пример — в разделе «Коммуникаторы»).

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

### Логирование и отладка multi-machine

При работе с несколькими ВМ используйте изолированные логи и метаданные:

```bash
# Изоляция состояний для параллельных джобов (CI/CD)
export VAGRANT_DOTFILE_PATH=/tmp/vagrant-${CI_JOB_ID}
mkdir -p $VAGRANT_DOTFILE_PATH

# Debug-лог конкретной ВМ
VAGRANT_LOG=debug vagrant up web 2>&1 | tee web-debug.log

# Проверка статуса всех машин
vagrant status

# Проверка SSH-конфигурации конкретной ВМ
vagrant ssh-config web
```

### Безопасность

1. **SSH-ключи:** Vagrant по умолчанию использует insecure_private_key. После первого запуска он генерирует уникальный ключ в `.vagrant/machines/<name>/<provider>/private_key`. Для production-образов замените его на собственный ключ через `config.ssh.private_key_path`.
2. **Секреты:** Не храните пароли в `Vagrantfile`. Используйте переменные окружения или плагин `vagrant-env`.
3. **Гостевой firewall:** После развертывания включите `ufw`/`nftables` внутри гостевой ОС, разрешив только необходимые порты.
4. **Изоляция метаданных:** При запуске нескольких копий проекта используйте `VAGRANT_DOTFILE_PATH`, чтобы состояния `.vagrant/` не пересекались.

### Производительность

1. **Параллельный запуск:** По умолчанию Vagrant запускает все ВМ параллельно. При дефиците RAM используйте `VAGRANT_NO_PARALLEL=true`.
2. **Linked clones (VirtualBox):** Используйте `vb.linked_clone = true` для экономии диска и ускорения создания ВМ.
3. **Virtiofs (Libvirt):** Для высокой производительности общих папок используйте `type: "virtiofs"` вместо NFS.
4. **Boot timeout:** В CI/CD и на медленных хостах увеличьте `config.vm.boot_timeout` до 600–1200 секунд.
5. **Rsync для CI:** В пайплайнах используйте `type: "rsync"` вместо NFS — не требует DHCP/NFS-сервер и работает быстрее в изолированных сетях.

### Типичные ошибки multi-machine окружений

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `vagrant up` запускает только часть ВМ | Параллельный запуск, дефицит RAM | `VAGRANT_NO_PARALLEL=true vagrant up` |
| `Machine not found` в multi-machine | State Desync одной из ВМ | `vagrant global-status --prune && vagrant up` |
| ВМ не видят друг друга по имени | Отсутствует DNS или hostmanager | Установите `vagrant-hostmanager` или используйте статические IP |
| Зависание на boot timeout | Недостаток RAM, медленный диск | Увеличьте `config.vm.boot_timeout`, проверьте `free -m` на хосте |
| Конфликт портов между ВМ | Одинаковые `host` порты в forwarded_port | Укажите уникальные `host` порты или `auto_correct: true` |

### Лучшие практики

1.  **Изоляция метаданных:** При запуске нескольких копий проекта (например, разные фичи-ветки) используйте `VAGRANT_DOTFILE_PATH`, чтобы состояния `.vagrant/` не пересекались.
2.  **Безопасность триггеров:** Избегайте использования `sudo` в триггерах `run_local` без острой необходимости. Всегда проверяйте возвращаемые коды скриптов (`abort: true`).
3.  **Именование в гипервизоре:** В мульти-машинных конфигурациях всегда задавайте уникальные `vb.name` или `lv.name`, чтобы избежать коллизий имен при запуске нескольких кластеров на одном хосте.
4.  **Условная логика:** Используйте `if Vagrant.has_plugin?("...")` для настройки опций, зависящих от плагинов, чтобы файл оставался работоспособным у коллег без этих расширений.
5.  **Версионирование:** Фиксируйте версию box (`config.vm.box_version`) и версию Vagrant (`config.vagrant.require_version`).
6.  **Идемпотентность:** Провижинеры и триггеры должны быть идемпотентными — повторный запуск не должен ломать окружение.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — базовый синтаксис и структура.
- [Vagrant Provisioning: Сложные сценарии](./vagrant_provisioning.md) — автоматизация настройки группы машин.
- [Vagrant Networking: Сети кластера](./vagrant_networking.md) — настройка связи между узлами.
- [Vagrant Providers: Libvirt и VirtualBox](./vagrant_providers.md) — специфические настройки хранилищ.
- [Vagrant Troubleshooting: Практические сценарии](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем с multi-machine, SSH и сетями.
- [Vagrant Troubleshooting: Дополнительная информация](./vagrant_troubleshooting/additional_info.md) — профилактика, snapshots, air-gapped среды.
- [Vagrant Storage и общие папки](./vagrant_storage_and_folders.md) — virtiofs, NFS, управление дисками.
- [Packer и Пайплайн box](./vagrant_packer_boxes.md) — сборка собственных `.box` и публикация в Vagrant Cloud.
- [Плагины и команды](./vagrant_plugins_and_commands.md) — hostmanager, scp, sshfs и рабочие команды.
- [Vagrant и альтернативы](./vagrant_vs_alternatives.md) — место Vagrant среди Docker/Terraform/Minikube.
