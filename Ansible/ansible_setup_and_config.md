# Установка и настройка Ansible

## Определения

- **Контрольный узел (Control Node)**: Машина, на которой установлен Ansible и с которой запускаются команды и плейбуки. Требует наличия Python.
- **Управляемый узел (Managed Node)**: Целевой сервер или устройство, которым управляет Ansible. В большинстве случаев требует только наличие SSH-доступа и интерпретатора Python.
- **Инвентарь (Inventory)**: Файл (`.ini`, `YAML` и др.), который описывает управляемые узлы, их группы и переменные подключения. Является основой для целеуказания в Ansible.
- **Ad-hoc команда (Ad-hoc command)**: Быстрые однострочные команды. Подробное описание и примеры см. в [Введении в Ansible](./ansible_introduction.md#ad-hoc-команды).
- **`ansible.cfg`**: Основной конфигурационный файл Ansible, определяющий его поведение, пути к файлам, настройки подключения по умолчанию и другие параметры.
- **Плагин подключения (Connection Plugin)**: Компонент, отвечающий за способ подключения к управляемому узлу. Наиболее распространенные: `ssh` (по умолчанию), `local`, `docker`, `winrm`.

## Основные концепции

### Файл конфигурации (`ansible.cfg`)

Файл `ansible.cfg` позволяет централизованно управлять настройками самого Ansible, избавляя от необходимости каждый раз указывать одни и те же параметры в командной строке.

**Иерархия и приоритет**

Ansible ищет файл `ansible.cfg` в нескольких местах в строгом порядке. Будет использован **первый найденный** файл. Порядок приоритета (от высшего к низшему):

1. **Переменная окружения `ANSIBLE_CONFIG`**: Путь к файлу конфигурации задан явно.
2. **`ansible.cfg` в текущей директории**: Самый распространенный и рекомендуемый способ, так как он позволяет иметь индивидуальные настройки для каждого проекта.
3. **`~/.ansible.cfg`**: Скрытый файл конфигурации в домашней директории текущего пользователя.
4. **/etc/ansible/ansible.cfg**: Глобальный конфигурационный файл для всей системы.

### Файл инвентаризации (`inventory`)

Файл инвентаризации определяет хосты и группы хостов, которыми вы управляете.

#### Форматы инвентаря: INI и YAML

Ansible поддерживает два основных формата для файлов инвентаризации: INI (классический) и YAML.

**INI-формат**

Прост для чтения и плоских структур.

```ini
# inventory.ini
[webservers]
web1.example.com
web2.example.com ansible_port=2222

[dbservers]
db1.example.com

[servers:children]
webservers
dbservers
```

**YAML-формат**

Предпочтителен для сложных структур, так как позволяет определять вложенные группы и переменные более наглядно.

```yaml
# inventory.yml
all:
  children:
    webservers:
      hosts:
        web1.example.com:
        web2.example.com:
          ansible_port: 2222
    dbservers:
      hosts:
        db1.example.com:
    servers:
      children:
        webservers:
        dbservers:
```

#### Переменные инвентаря: `host_vars` и `group_vars`

Хотя переменные можно указывать прямо в файле инвентаря (inline-переменные), лучшей практикой является их вынесение в отдельные файлы. Ansible автоматически загружает переменные из файлов, расположенных в директориях `host_vars` и `group_vars`, которые должны находиться рядом с вашим файлом инвентаря или плейбуком.

**Структура каталогов:**

```
.
├── inventory.ini
├── playbook.yml
├── group_vars/
│   ├── all.yml          # Переменные для всех хостов
│   └── webservers.yml   # Переменные для группы [webservers]
└── host_vars/
    └── web1.example.com.yml # Переменные только для хоста web1.example.com
```

**Пример `group_vars/webservers.yml`:**

```yaml
---
ntp_server: ntp.example.com
http_port: 8080
```

Эти переменные будут автоматически применены ко всем хостам в группе `webservers`.

**Переменные подключения**

Параметры подключения (адрес, пользователь, ключ) также задаются как переменные, привязанные к хосту.

- `ansible_host`: IP-адрес или DNS-имя целевой машины.
- `ansible_user`: Имя пользователя для SSH-подключения.
- `ansible_ssh_private_key_file`: Путь к приватному SSH-ключу.

Пример в `host_vars/web1.example.com.yml`:

```yaml
---
ansible_host: 192.168.50.11
ansible_user: vagrant
ansible_ssh_private_key_file: ~/.vagrant.d/insecure_private_key
```

> **Внимание:** Хранение паролей в открытом виде (`ansible_ssh_pass`) **крайне небезопасно**. Для реальных проектов **всегда** используйте [Ansible Vault](./Vault/basics.md).

> Для поиска всех доступных переменных для плагина подключения (например, `ssh`), используйте команду: `ansible-doc -t connection ssh`.

### Типы подключений (Connection Plugins)

Плагин для хоста задается через переменную `ansible_connection`. Узнать, какие плагины доступны, можно командой `ansible-doc -t connection -l`.

- `ssh`: Стандартное подключение (по умолчанию).
- `local`: Для выполнения задач на самом контрольном узле.
- `docker`: Для подключения к Docker-контейнерам. В современных версиях требуется полное имя коллекции (FQCN), например `community.docker.docker`.
- `winrm`: Для подключения к машинам Windows.

## Практические сценарии

### 1. Установка и проверка подключения

#### Установка Ansible (рекомендуемый способ `pip`)

```bash
python3 -m venv ansible_env
source ansible_env/bin/activate
pip install ansible
```

#### Настройка `ansible.cfg` и `inventory`

**Пример `ansible.cfg`:**

```ini
[defaults]
inventory = ./inventory
remote_user = ansible_user
private_key_file = /path/to/your/private_key
host_key_checking = false
deprecation_warnings = False
roles_path = ./roles
```

**Пример `inventory`:**

```ini
[servers]
server1 ansible_host=192.168.51.4
```

#### Проверка подключения

Модуль `ping` — это основной способ проверить, что Ansible может подключиться к хосту и выполнить на нем Python-код.

```bash
ansible server1 -m ping
```

Если подключение успешно, хост вернет `pong`.

### 2. Подготовка тестовой среды с Vagrant

[Vagrant](../../Vagrant/vagrant_basic_workflow.md) — идеальный инструмент для быстрого развертывания локальной тестовой среды.

**Пример `Vagrantfile`:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.define "controlnode" do |controlnode|
    controlnode.vm.box = "ubuntu/focal64"
    controlnode.vm.network "private_network", ip: "192.168.50.4"
    controlnode.vm.provision "shell", inline: "apt-get update && apt-get install -y ansible"
  end

  config.vm.define "server" do |server|
    server.vm.box = "bento/centos-7.5"
    server.vm.network "private_network", ip: "192.168.51.4"
  end
end
```

## Дополнительная информация

- **Структура проекта**: Рекомендации по организации файлов и каталогов см. в документе [Структура проекта Ansible](./examples/example_project_layout.md).
- **Динамический инвентарь**: Для работы с облачными провайдерами и динамически изменяемой инфраструктурой см. [Dynamic inventory в Ansible](./Inventories/dynamic_inventory.md).
- **Безопасность**: Основные практики безопасности описаны в [ansible_security_best_practices.md](./ansible_security_best_practices.md).
- **Введение**: Для знакомства с основами и ad-hoc командами см. [Введение в Ansible](./ansible_introduction.md).
