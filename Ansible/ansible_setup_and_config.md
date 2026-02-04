# Установка и настройка Ansible

## Определения

- **Контрольный узел (Control Node)**: Машина, на которой установлен Ansible и с которой запускаются команды и плейбуки. Требует наличия Python.
- **Управляемый узел (Managed Node)**: Целевой сервер или устройство, которым управляет Ansible. В большинстве случаев требует только наличие SSH-доступа и интерпретатора Python.
- **Инвентарь (Inventory)**: Файл (`.ini`, `YAML` и др.), который описывает управляемые узлы, их группы и переменные подключения. Является основой для целеуказания в Ansible.
- **Ad-hoc команда (Ad-hoc command)**: Быстрые однострочные команды. Подробное описание и примеры см. в [Введении в Ansible](ansible_introduction.md#ad-hoc-команды).
- **`ansible.cfg`**: Основной конфигурационный файл Ansible, определяющий его поведение, пути к файлам, настройки подключения по умолчанию и другие параметры.
- **Плагин подключения (Connection Plugin)**: Компонент, отвечающий за способ подключения к управляемому узлу. Наиболее распространенные: `ssh` (по умолчанию), `local`, `docker`, `winrm`.

## Основные концепции

### Файл конфигурации (`ansible.cfg`)

Файл `ansible.cfg` позволяет централизованно управлять настройками самого Ansible, избавляя от необходимости каждый раз указывать одни и те же параметры в командной строке. "Дзен Ansible" заключается в том, чтобы выносить общие для всех проектов настройки в этот файл.

**Иерархия и приоритет**

Ansible ищет файл `ansible.cfg` в нескольких местах в строгом порядке. Будет использован **первый найденный** файл. Порядок приоритета (от высшего к низшему):

1. **Переменная окружения `ANSIBLE_CONFIG`**: Путь к файлу конфигурации задан явно. Это самый приоритетный способ.
2. **`ansible.cfg` в текущей директории**: Наличие `ansible.cfg` в корневой папке вашего проекта — самый распространенный и рекомендуемый способ, так как он позволяет иметь индивидуальные настройки для каждого проекта.
3. **`~/.ansible.cfg`**: Скрытый файл конфигурации в домашней директории текущего пользователя.
4. **/etc/ansible/ansible.cfg**: Глобальный конфигурационный файл для всей системы с самым низким приоритетом.

> **Важно!** Ansible может игнорировать `ansible.cfg`, если права на него слишком открытые (например, `777`). Убедитесь, что у файла адекватные права (например, `644` или `775` для директории).

### Файл инвентаризации (`inventory`)

Файл инвентаризации — это основа Ansible, определяющая хосты и группы хостов, которыми вы управляете. Хотя можно перечислять просто IP-адреса, **рекомендуется** использовать псевдонимы (aliases) для каждого хоста. Это делает плейбуки и вывод команд гораздо более читаемыми.

**Способы определения параметров подключения**

Параметры подключения (адрес, пользователь, пароль, ключ, тип подключения) задаются как переменные, привязанные к хосту.

```ini
# inventory.ini

[servers]
# Имя хоста, которое вы будете использовать в плейбуках
server1 ansible_host=192.168.50.11 ansible_user=vagrant

[servers:vars]
# Эти переменные будут применены ко всем хостам в группе [servers]
ansible_ssh_pass=vagrant
```

- `server1`: Псевдоним хоста.
- `ansible_host`: IP-адрес или DNS-имя целевой машины.
- `ansible_user`: Имя пользователя для SSH-подключения.
- `ansible_ssh_pass`: Пароль для SSH-подключения.
- `ansible_ssh_private_key_file`: Путь к приватному SSH-ключу.

> **Внимание:** Хранение паролей в открытом виде в файле инвентаризации **крайне небезопасно**. Этот метод следует использовать только в изолированных учебных средах. Для реальных проектов **всегда** используйте [Ansible Vault](ansible_vault.md).

> **Как найти нужную переменную?**
> Имена переменных, таких как `ansible_ssh_private_key_file`, не всегда очевидны. Их можно найти во встроенной документации для соответствующего плагина подключения. Например, чтобы увидеть все параметры для SSH-подключения, используйте команду: `ansible-doc -t connection ssh`.

### Типы подключений (Connection Plugins)

Хотя по умолчанию Ansible использует SSH, его архитектура является модульной. За способ подключения к управляемому узлу отвечают **плагины подключения**.

Плагин для хоста задается через переменную `ansible_connection`. Узнать, какие плагины доступны, можно командой `ansible-doc -t connection -l`.

- `ssh`: Стандартное подключение (по умолчанию).
- `local`: Для выполнения задач на самом контрольном узле.
- `docker`: Для подключения к Docker-контейнерам напрямую через Docker API.
- `kubernetes.core.kubectl`: Для выполнения команд через `kubectl exec`.
- `winrm`: Для подключения к машинам Windows.

> **Важно: FQCN для плагинов**
> В Ansible 2.9 и старше можно было использовать короткие имена, например `docker`. В современных версиях (2.10+ и community-сборках 3+) требуется указывать полное имя коллекции (FQCN): `community.docker.docker`. Если короткое имя не работает, `ansible-doc` подскажет правильное полное имя.

### Версии Ansible

Существует два типа пакетов:

- `ansible-core`: Минимальный пакет, содержащий ядро Ansible и базовые модули. Версии нумеруются как `2.11`, `2.12`, и т.д.
- `ansible`: Пакет "community edition", который включает `ansible-core` и большой набор готовых коллекций и модулей от сообщества. Его версии нумеруются иначе (`4.x.x`, `5.x.x`). Например, `ansible 5.x` может содержать `ansible-core 2.12`.

## Практические сценарии

### 1. Установка и проверка подключения

#### Установка Ansible

**Debian/Ubuntu (через PPA):**

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository --yes --update ppa:ansible/ansible
sudo apt install -y ansible
```

**CentOS/RHEL:**

```bash
sudo yum install -y epel-release
sudo yum install -y ansible
```

**С помощью `pip` (универсальный способ):**

```bash
python3 -m venv ansible_env
source ansible_env/bin/activate
pip install ansible
```

#### Настройка `ansible.cfg` и `inventory`

**Пример `ansible.cfg`:**

```ini
# ./ansible.cfg
[defaults]
# Указываем путь к файлу инвентаря.
inventory = ./hosts.ini
# Задаем пользователя по умолчанию для всех хостов.
# Подробнее о его создании см. в [ansible_security_best_practices.md](ansible_security_best_practices.md).
remote_user = ansible_user 
# Задаем путь к приватному ключу по умолчанию.
private_key_file = /path/to/your/private_key
# Отключаем проверку ключей хоста (удобно для тестовых сред).
host_key_checking = false
# Подавляет предупреждения о будущих изменениях.
deprecation_warnings = False
```

**Пример `hosts.ini` (инвентарь):**

```ini
[servers]
server1 ansible_host=192.168.51.4
```

#### Проверка подключения

Команда `ansible --version` покажет версию Ansible и путь к используемому `ansible.cfg`.

Модуль `ping` — это основной способ проверить, что Ansible может подключиться к хосту, выполнить на нем Python-код и получить ответ.

```bash
ansible server1 -m ping
```

Если подключение успешно, хост вернет `pong`.

### 2. Выполнение ad-hoc команд

После успешной настройки можно выполнять первые команды. Подробный разбор ad-hoc команд и примеры их использования (`ping`, `command`, `shell`, `setup`) вынесены в документ [Введение в Ansible](ansible_introduction.md#ad-hoc-команды).

Ниже приведен пример использования модуля `raw` для первоначальной настройки системы, где еще не установлен Python.

```bash
# Пример установки Python на "голый" Debian/Ubuntu
ansible new_server -m raw -a "apt-get update && apt-get install -y python3"
```

### 3. Подготовка тестовой среды с Vagrant (Альтернативный путь)

[Vagrant](../../Vagrant/vagrant_overview.md) — идеальный инструмент для быстрого развертывания локальной тестовой среды, включающей и контрольный, и управляемые узлы.

**Пример `Vagrantfile`:**

```ruby
# Vagrantfile
Vagrant.configure("2") do |config|
  # Определение controlnode
  config.vm.define "controlnode" do |controlnode|
    controlnode.vm.box = "ubuntu/focal64"
    controlnode.vm.network "private_network", ip: "192.168.50.4"
    
    # Копирование приватного ключа
    controlnode.vm.provision "file", source: "files/vagrant_test", destination: "/home/vagrant/.ssh/"
    
    # Установка Ansible
    controlnode.vm.provision "shell", inline: <<-SHELL
      apt-get update && apt-get install -y ansible
      chmod 600 /home/vagrant/.ssh/vagrant_test
    SHELL
  end

  # Определение управляемого сервера
  config.vm.define "server_centos" do |server_centos|
    server_centos.vm.box = "bento/centos-7.5"
    server_centos.vm.network "private_network", ip: "192.168.51.4"
  end

  # Раздача публичного ключа на все машины
  config.vm.provision "file", source: "files/vagrant_test.pub", destination: "/home/vagrant/.ssh/authorized_keys"
end
```

**Процесс настройки:**

1. Создайте папку `files` и сгенерируйте в ней пару SSH-ключей: `ssh-keygen -f files/vagrant_test`.
2. Запустите виртуальные машины: `vagrant up`.

### 4. Решение проблем с SSH-подключением

Если при попытке пинга вы получаете ошибку `Permission denied (publickey,password)`, это означает, что Ansible не смог найти подходящий SSH-ключ.

**Решение 1: Указание ключа в инвентаре**

```ini
# hosts.ini
[centos]
192.168.51.3 ansible_ssh_private_key_file=/path/to/your/private_key
```

**Решение 2: Использование `ansible.cfg`**

Задайте `private_key_file` в секции `[defaults]` вашего `ansible.cfg`, как показано в примере выше. Это централизует конфигурацию и упрощает команды. С таким файлом достаточно выполнить `ansible <hostname> -m ping`.
