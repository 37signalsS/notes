# Виртуальные Машины (VM) и Vagrant

Виртуальная машина (ВМ) — это эмулированная компьютерная система, которая работает внутри другой операционной системы (хост-системы). Она предоставляет собой "гостевую" операционную систему, изолированную от основной. Это позволяет запускать несколько операционных систем на одном физическом оборудовании, обеспечивает изоляцию, безопасность и эффективное использование ресурсов. Хостеры и сервис-провайдеры активно используют ВМ благодаря этим преимуществам.

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
Команда `vagrant up` скачивает box (если его нет в кэше), создает и запускает виртуальную машину. При этом Vagrant отображает процесс выполнения в консоли.

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
Команда `vagrant status` показывает состояние управляемых машин, проверяя наличие виртуальной машины для текущего `Vagrantfile`. Статус может быть 'Running', 'PowerOff', 'Aborted' и т.д.

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

---

## Детальная конфигурация Vagrantfile (Cheat Sheet)

Vagrant позволяет гибко настраивать виртуальную машину через `Vagrantfile`, включая память, CPU, сеть, диски, общие папки и многое другое. Ниже представлен разбор ключевых и продвинутых параметров с акцентом на `libvirt`/QEMU, но многие из них универсальны.

### Настройки VM и Гипервизора

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.box` | `"ubuntu2404_base"` | Определяет базовый образ (box) виртуальной системы, которая будет установлена. Vagrant автоматически скачает его при запуске, если образа нет в кэше. Значение по умолчанию "base" обычно требует замены на конкретный образ (например, "ubuntu/jammy64"). Вы можете найти доступные образы на [HashiCorp Vagrant Cloud](https://portal.cloud.hashicorp.com/vagrant/discover). |
| `config.vm.hostname` | `"suricata-diplom"` | Имя хоста внутри VM |
| `config.vm.provider` | `"libvirt"` | Провайдер (VirtualBox, libvirt, VMware) |
| `libvirt.memory` | `2048` | RAM в МБ |
| `libvirt.cpus` | `2` | Количество CPU |
| `libvirt.disk_bus` | `'virtio'` | Тип дискового контроллера (лучшая производительность) |
| `libvirt.nic_model_type` | `'virtio'` | Модель сетевой карты (лучшая производительность) |
| `libvirt.graphics_type` | `'vnc'` | Графический интерфейс (vnc, spice) |
| `libvirt.arch` | `'x86_64'` | Архитектура CPU |
| `libvirt.os_type` | `'linux'` | Тип OS (linux, windows) |

### Сеть

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.network "forwarded_port"` | `guest: 80, host: 8080` | Проброс портов с хоста в гостевую ОС. Порты в системе являются адресами для приложений. `guest` – это номер порта в гостевой ВМ, `host` – номер порта на вашей хост-машине. Таким образом, запросы, приходящие на порт `host` вашей машины, будут перенаправлены на порт `guest` виртуальной машины. (Например, порт 80 гостевой машины будет доступен на порту 8080 хоста). |
| `config.vm.network "private_network"` | `ip: "192.168.50.4"` | Host-only сеть с фиксированным IP (доступна только с хоста) |
| `config.vm.network "public_network"` | — | Bridged-сеть (VM видна в локальной сети) |

### Общие папки (Synced Folders)

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.synced_folder` | `"./data", "/vagrant_data", type: "rsync"` | Синхронизация папок хост ↔ VM. По умолчанию, директория с `Vagrantfile` монтируется в `/vagrant` внутри гостевой ОС. |
| `disabled: true` | `config.vm.synced_folder ".", "/vagrant", disabled: true` | Отключает стандартную общую папку `/vagrant` |
| `type: "nfs"` | `type: "nfs"` | Использовать NFS для быстрого доступа (рекомендуется для Linux) |

### Provisioning (Автоматическая настройка)

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.provision "shell"` | `inline: "apt-get update"` | Bash-скрипт для установки ПО |
| `config.vm.provision "ansible"` | `playbook: "site.yml"` | Ansible playbook |
| `config.vm.provision "puppet"` | `manifest: "default.pp"` | Puppet-манифесты |
| `config.vm.provision "docker"` | `run: "nginx"` | Запуск Docker-контейнеров внутри VM |

### Хранилище и диски (libvirt)

| Параметр | Пример | Описание |
| --- | --- | --- |
| `libvirt.storage_pool_name` | `"default"` | Указывает пул хранения libvirt, в котором будут создаваться диски ВМ. Убедитесь, что этот пул существует и активен на вашем хосте. |
| `libvirt.volume_size` | `"10G"` | Определяет размер основного (корневого) диска виртуальной машины. Этого может быть достаточно для базовой системы и небольших приложений, но для баз данных или приложений с большим количеством данных этого может не хватить. |
| `libvirt.volume_name` | `"machine#{machine_id}-root.qcow2"` | Задает имя основного диска ВМ. Используйте динамическую генерацию имен (например, с `#{machine_id}`) для предотвращения конфликтов. |
| `libvirt.storage :file, size: '20G'` | — | Добавляет **дополнительный** диск размером 20GB к виртуальной машине. Этот параметр не управляет размером основного диска гостевой ОС. |
| `libvirt.disk_bus` | `'virtio'` | Тип контроллера диска (для основных и дополнительных дисков). |

**Примечание:** Для корректной работы с дисками в Libvirt, необходимо убедиться, что указанный `libvirt.storage_pool_name` существует и активен на хост-системе. Имена дисков формируются стандартным образом, учитывающим имя проекта и определение машины в Vagrantfile.

### Пользователь и SSH-доступ

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.ssh.username` | `"vagrant"` | Имя пользователя для SSH |
| `config.ssh.private_key_path` | `"~/.vagrant.d/insecure_private_key"` | Путь к приватному ключу SSH |
| `config.vm.network "forwarded_port"` | `guest: 22, host: 2222` | Проброс SSH-порта на другой порт хоста. Vagrant автоматически пробрасывает порт 22 гостевой машины для SSH-доступа. |

### Прочие параметры

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.box_check_update` | `false` | Отключить проверку обновлений box'а при старте |
| `config.vm.boot_timeout` | `600` | Время ожидания загрузки VM в секундах |
| `libvirt.cloud_init` | `true` | Использовать cloud-init для настройки VM |
| `libvirt.nested` | `true` | Разрешить вложенную виртуализацию (KVM внутри KVM) |

---


## Провайдеры и образы (Boxes)

### Поиск образов (Boxes)

Найти нужный образ Vagrant можно на официальном портале: **[HashiCorp Vagrant Cloud](https://portal.cloud.hashicorp.com/vagrant/discover)**.

Портал позволяет фильтровать образы по поддержке определенного провайдера виртуализации, например, `libvirt`, `virtualbox`, `hyperv` и др.

### Настройка провайдера

Вы можете указать, какой провайдер использовать, и настроить его параметры прямо в `Vagrantfile`.

**Пример настройки libvirt-провайдера:**
```ruby
Vagrant.configure("2") do |config|
  # ... другие настройки ...

  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 2048
    libvirt.cpus = 2
    # Использование virtio для лучшей производительности дисков и сети
    libvirt.disk_bus = 'virtio'
    libvirt.nic_model_type = 'virtio'
  end

  # 3. Сеть (приватная сеть с фиксированным IP)
  config.vm.network "private_network", ip: "192.168.50.4"
  
  # 4. Отключение общей папки, для включения этой функции необходимо изменить true на false, после перезапуска вм с этой настройкой папка хоста в которой находиться запускаемый Vagranfile станет общей, а файлы с синхронизированной папки хоста будут в режиме реального времени появляться в вм(сихронизация работает в обе стороны) без необходимости с перезагрузки. Общая пака будет называться /vagrant в вм.
  config.vm.synced_folder ".", "/vagrant", disabled: true

  # 5. Автоматическая установка ПО (provisioning)
  config.vm.provision "shell", inline: <<-SHELL
    apt-get update
    apt-get install -y suricata
  SHELL
end
```

**Примечание:** Для использования `libvirt` в качестве провайдера необходимо установить плагин `vagrant-libvirt`. Если плагин отсутствует, Vagrant не сможет найти провайдера и выдаст ошибку.

```bash
# Установка плагина vagrant-libvirt
vagrant plugin install vagrant-libvirt
```

### Смена провайдера

Чтобы сменить провайдера для существующего проекта (например, с VirtualBox на libvirt), необходимо **удалить директорию `.vagrant`** в каталоге с `Vagrantfile`. После этого команда `vagrant up` будет использовать нового провайдера, указанного в конфигурации.

```bash
# Удалить метаданные текущего провайдера
rm -rf .vagrant

# Запустить окружение с новым провайдером
vagrant up --provider=libvirt
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

### Управление несколькими машинами (Libvirt и Ansible)

`Vagrantfile` позволяет описывать и управлять группой машин из одного файла, используя циклы для динамической конфигурации. Этот пример демонстрирует создание нескольких машин с Libvirt, настройку сети, дисков и условное применение различных плейбуков Ansible.

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

      # Конфигурация провайдера Libvirt
      machine.vm.provider "libvirt" do |libvirt|
        libvirt.memory = 2144
        libvirt.cpus = 2
        libvirt.nic_model_type = "virtio"
        libvirt.random_hostname = false

        libvirt.storage_pool_name = "default"
        libvirt.volume_size = "10G"
        libvirt.volume_name = "machine#{machine_id}-root.qcow2"
      end

      # Условное применение плейбуков Ansible
      if machine_id == 1
         # Для первой машины применяем особый плейбук
         machine.vm.provision :ansible do |ansible|
           ansible.playbook = "nginx-lab/ansible/playbook_machine1.yml"
           ansible.limit = "machine1" 
         end
      else
         # Для остальных машин применяем стандартный плейбук
         machine.vm.provision :ansible do |ansible|
           ansible.playbook = "nginx-lab/ansible/playbook.yml"
           ansible.limit = "machine#{machine_id}" 
         end
      end
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

### Libvirt с выделенным именем диска


```ruby
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.define "diplom" do |node|
    node.vm.box = "jtarpley/ubuntu2404_base"
    node.vm.hostname = "suricata-diplom"
    node.vm.box_check_update = false

    node.vm.provider "libvirt" do |libvirt|
      libvirt.memory = 6144
      libvirt.cpus = 4
      libvirt.nic_model_type = "virtio"
      libvirt.random_hostname = false

      libvirt.storage_pool_name = "default"

      libvirt.storage :file,
        size: "30G",
        type: "qcow2",
        bus: "virtio",
        name: "suricata_diplom.qcow2",
        allow_duplicate: true
    end

    node.vm.synced_folder ".", "/vagrant", disabled: false
    node.vm.provision "shell", path: "provision.sh"
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

- **Проблема: Рассинхронизация состояния диска (Libvirt)**

  **Симптом:** При запуске `vagrant up` возникает ошибка, связанная с уже существующим диском (например, `suricata_diplom.qcow2`), хотя физически этого файла нет в директории (`/var/lib/libvirt/images/`) и в пуле хранения `libvirt`.

  **Причина:** Такое несоответствие возникает, если Vagrant или `fog-libvirt` сохранили запись о диске в своем внутреннем состоянии (в каталоге `.vagrant` проекта или в кэше `libvirt`), но сам диск был удален вручную или в результате сбоя.

  **Решение:** Необходимо принудительно очистить состояние Vagrant и `libvirt` для данной ВМ.

  1.  **Уничтожить все ВМ, управляемые Vagrant в проекте:**
      Эта команда удалит виртуальные машины и связанные с ними записи в `libvirt`.
      ```bash
      vagrant destroy -f
      ```

  2.  **Удалить локальное состояние Vagrant:**
      Эта команда очистит кэш и метаданные проекта, включая ссылки на несуществующие диски.
      ```bash
      rm -rf .vagrant
      ```

  3.  **Повторить запуск:**

- **Именование ВМ в Libvirt:**
  Имя домена виртуальной машины в Libvirt формируется из имени каталога проекта (где лежит `Vagrantfile`) и имени, заданного в `config.vm.define`. Например, для проекта "dev" и машин "machine1", "machine2", "machine3" полные имена доменов и дисков будут `dev_machine1`, `dev_machine2` и `dev_machine3`. Это стандартное поведение Vagrant, и имя домена напрямую влияет на имя диска. Даже после `vagrant destroy -f` и `vagrant up` имена дисков останутся прежними.

- **Остановка и именование ВМ:**

  - `vagrant halt`: Корректно завершает работу гостевой операционной системы и останавливает ВМ.
  
  - **Именование ВМ:** Не используйте нижнее подчеркивание (`_`) в именах виртуальных машин. Это может привести к ошибкам при старте. Вместо этого используйте дефис (`-`).
