# Установка и настройка Ansible

## 1. Подготовка тестовой среды с Vagrant

Прежде чем устанавливать Ansible и писать плейбуки, крайне полезно настроить локальную тестовую среду. Это позволяет безопасно экспериментировать, не затрагивая рабочие серверы. [Vagrant](../../Vagrant/vagrant_overview.md) — идеальный инструмент для этой цели.

Ниже приведен пример `Vagrantfile`, который создает несколько виртуальных машин, включая `controlnode` и несколько серверов на Ubuntu и CentOS.

```ruby
# Vagrantfile
Vagrant.configure("2") do |config|
  # ... (определения машин)

  # Пример определения controlnode
  config.vm.define "controlnode" do |controlnode|
    controlnode.vm.box = "ubuntu/focal64"
    controlnode.vm.network "private_network", ip: "192.168.50.4"
    
    # Копирование приватного ключа на controlnode
    controlnode.vm.provision "file", source: "files/vagrant_test", destination: "/home/vagrant/.ssh/"
    
    # Установка Ansible и другого ПО
    controlnode.vm.provision "shell", inline: <<-SHELL
      apt-get update && apt-get install -y ansible docker-ce sshpass
      chmod 600 /home/vagrant/.ssh/vagrant_test
    SHELL
  end

  # Пример определения управляемого сервера
  config.vm.define "server_centos" do |server_centos|
    server_centos.vm.box = "bento/centos-7.5"
    server_centos.vm.network "private_network", ip: "192.168.51.4"
  end

  # Раздача публичного ключа на все машины
  config.vm.provision "file", source: "files/vagrant_test.pub", destination: "/home/vagrant/.ssh/authorized_keys"
end
```
*В данном примере `authorized_keys` используется для простоты. В реальности публичный ключ добавляется к существующему файлу.*

### Процесс настройки:
1.  **Создайте папку `files`** и сгенерируйте в ней пару SSH-ключей.
    ```bash
    mkdir files
    ssh-keygen -f files/vagrant_test 
    ```
    *На Windows, если `ssh-keygen` отсутствует, его можно получить, установив Git for Windows.*
2.  **Запустите виртуальные машины:**
    ```bash
    vagrant up
    ```
    Vagrant создаст машины, установит Ansible на `controlnode`, скопирует приватный ключ на `controlnode` и публичный ключ на все остальные машины.


## 2. Установка Ansible

Ansible написан на Python и требует его наличия на **контрольном узле**. Современные версии Ansible требуют Python 3.

Если вы не используете Vagrant-провижининг, как показано выше, вы можете установить Ansible вручную.

### Debian/Ubuntu
В стандартных репозиториях Ubuntu может быть устаревшая версия Ansible. Для установки актуальной версии рекомендуется использовать официальный PPA (Personal Package Archive).

```bash
sudo apt update
sudo apt install -y software-properties-common
# Добавляем репозиторий от команды Ansible
sudo add-apt-repository --yes --update ppa:ansible/ansible
# Устанавливаем Ansible
sudo apt install -y ansible
```

### CentOS/RHEL
```bash
sudo yum install -y epel-release
sudo yum install -y ansible
```

### С помощью `pip` (универсальный способ)
Этот способ позволяет установить последнюю версию Ansible в изолированное окружение.
```bash
python3 -m venv ansible_env
source ansible_env/bin/activate
pip install ansible
```

### Проверка установки и версии

После установки проверьте, что все работает, командой `ansible --version`.

```
ansible 2.9.6
  config file = /etc/ansible/ansible.cfg
  configured module search path = ['/home/vagrant/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /usr/lib/python3/dist-packages/ansible
  executable location = /usr/bin/ansible
  python version = 3.8.10 (default, Nov 26 2021, 20:14:08) [GCC 9.3.0]
```
Вывод показывает версию Ansible, путь к конфигурационному файлу и версию Python, которую он использует.

**О версиях Ansible:**
Существует два типа пакетов:
*   `ansible-core`: Минимальный пакет, содержащий ядро Ansible и базовые модули. Версии нумеруются как `2.11`, `2.12`, и т.д.
*   `ansible`: Пакет "community edition", который включает `ansible-core` и большой набор готовых коллекций и модулей от сообщества. Его версии нумеруются иначе (`4.x.x`, `5.x.x`). Например, `ansible 5.x` может содержать `ansible-core 2.12`.

Для обучения мы используем пакет `ansible`, так как он включает все необходимое "из коробки".

---

## 3. Конфигурация и подключения

### Файл конфигурации (`ansible.cfg`)

Файл `ansible.cfg` позволяет централизованно управлять настройками самого Ansible, избавляя от необходимости каждый раз указывать одни и те же параметры в командной строке. "Дзен Ansible" заключается в том, чтобы выносить общие для всех проектов настройки в этот файл.

**Иерархия и приоритет**

Ansible ищет файл `ansible.cfg` в нескольких местах в строгом порядке. Будет использован **первый найденный** файл. Порядок приоритета (от высшего к низшему):
1.  **Переменная окружения `ANSIBLE_CONFIG`**: Путь к файлу конфигурации задан явно. Это самый приоритетный способ.
2.  **`ansible.cfg` в текущей директории**: Наличие `ansible.cfg` в корневой папке вашего проекта — самый распространенный и рекомендуемый способ, так как он позволяет иметь индивидуальные настройки для каждого проекта.
3.  **`~/.ansible.cfg`**: Скрытый файл конфигурации в домашней директории текущего пользователя.
4.  **/etc/ansible/ansible.cfg**: Глобальный конфигурационный файл для всей системы с самым низким приоритетом.

**Пример `ansible.cfg` для проекта:**
```ini
# ./ansible.cfg
[defaults]
# Указываем путь к файлу инвентаря.
inventory = ./hosts.ini
# Задаем путь к приватному ключу по умолчанию.
private_key_file = /home/vagrant/.ssh/vagrant_test
# Отключаем проверку ключей хоста (удобно для тестовых сред).
host_key_checking = false
# Подавляет предупреждения о том, что Ansible управляет данным хостом впервые.
deprecation_warnings = False

[ssh_connection]
# Дополнительные аргументы для SSH, могут быть полезны.
# ssh_args = -o ControlMaster=auto -o ControlPersist=60s
```
> **Важно!** Ansible может игнорировать `ansible.cfg`, если права на него слишком открытые (например, `777`). Убедитесь, что у файла адекватные права (например, `644` или `775` для директории).

### Файл инвентаризации (`inventory`)

Файл инвентаризации (inventory) — это основа Ansible, определяющая хосты и группы хостов, которыми вы управляете. Хотя можно перечислять просто IP-адреса, **рекомендуется** использовать псевдонимы (aliases) для каждого хоста. Это делает плейбуки и вывод команд гораздо более читаемыми.

**Способы определения параметров подключения**

Параметры подключения (адрес, пользователь, пароль, ключ, тип подключения) задаются как переменные, привязанные к хосту.

```ini
# inventory.ini

[servers]
# Имя хоста, которое вы будете использовать в плейбуках
server1 ansible_host=192.168.50.11 ansible_user=vagrant ansible_ssh_pass=vagrant

[servers:vars]
# Эти переменные будут применены ко всем хостам в группе [servers]
# ansible_user=vagrant
# ansible_ssh_pass=vagrant
```
- `server1`: Псевдоним хоста.
- `ansible_host`: IP-адрес или DNS-имя целевой машины.
- `ansible_user`: Имя пользователя для SSH-подключения.
- `ansible_ssh_pass`: Пароль для SSH-подключения.

> **Внимание:** Хранение паролей в открытом виде в файле инвентаризации **крайне небезопасно**. Этот метод следует использовать только в изолированных учебных средах. Для реальных проектов **всегда** используйте [Ansible Vault](../ansible_vault.md).

**Использование SSH-ключей (Самый безопасный способ)**

```ini
[servers]
prod_server ansible_host=195.2.73.85 ansible_user=root ansible_port=2414 ansible_ssh_private_key_file=~/.ssh/prod_id_rsa
```

> **Как найти нужную переменную?**
> Имена переменных, таких как `ansible_ssh_private_key_file`, не всегда очевидны. Их можно найти во встроенной документации для соответствующего плагина подключения. Например, чтобы увидеть все параметры для SSH-подключения, используйте команду: `ansible-doc -t connection ssh`.


### Практический пример: Решение проблем с SSH-подключением

Если при попытке пинга вы получаете ошибку `Permission denied (publickey,password)`, это означает, что Ansible не смог найти подходящий SSH-ключ.

```bash
ansible centos -m ping -i hosts.ini
# UNREACHABLE! => {"msg": "Failed to connect to the host via ssh: ... Permission denied ..."}
```
**Решение 1: Указание ключа в инвентаре**
Вы можете явно указать путь к приватному ключу для каждого хоста или группы.

```ini
# hosts.ini
[centos]
192.168.51.3 ansible_private_key_file=/home/vagrant/.ssh/vagrant_test
192.168.51.5 ansible_private_key_file=/home/vagrant/.ssh/vagrant_test
```
Теперь команда `ansible centos -m ping -i hosts.ini` будет успешной.

**Решение 2: Использование `ansible.cfg`**
С помощью `ansible.cfg` в корне проекта можно централизованно задать путь к инвентарю и ключу, что избавляет от необходимости постоянно использовать ключи `-i` и `ansible_private_key_file`.

```ini
# ./ansible.cfg
[defaults]
inventory = ./hosts.ini
private_key_file = /home/vagrant/.ssh/vagrant_test
host_key_checking = false
```
С таким файлом команда становится намного проще: `ansible centos -m ping`.

### Типы подключений (Connection Plugins)

Хотя по умолчанию Ansible использует SSH, его архитектура является модульной. За способ подключения к управляемому узлу отвечают **плагины подключения (connection plugins)**.

Узнать, какие плагины доступны в вашей системе, можно с помощью команды `ansible-doc`:
```bash
ansible-doc -t connection -l
```
Вы увидите список, включающий:
- `ssh`: Стандартное подключение (по умолчанию).
- `local`: Для выполнения задач на самом контрольном узле.
- `docker`: Для подключения к Docker-контейнерам напрямую через Docker API.
- `kubernetes.core.kubectl`: Для выполнения команд через `kubectl exec`.
- `winrm`: Для подключения к машинам Windows.

Плагин для хоста задается через переменную `ansible_connection`.

**Пример: Проверка подключения к Docker-контейнеру**
Ansible может управлять не только ВМ, но и Docker-контейнерами.
1.  **Запустите контейнер на `controlnode`**
2.  **Проверьте пинг**, используя инвентарь, где для контейнера указан `ansible_connection=docker`.
    *`hosts.ini` для примера:*
    ```ini
    [local]
    pythonlocal ansible_connection=docker ansible_host=ansible_test_1 ansible_python_interpreter=/usr/bin/python3
    
    [remote_servers]
    remote ansible_host=192.168.51.2
    ```
    *Команда:*
    ```bash
    # Запускаем от sudo для доступа к Docker-сервису
    sudo ansible all -m ping -i hosts.ini
    ```
    Вы должны увидеть `SUCCESS` и `pong` для всех хостов.

> **Важно: FQCN для плагинов**
> В Ansible 2.9 и старше можно было использовать короткие имена, например `docker`. В современных версиях (2.10+ и community-сборках 3+) требуется указывать полное имя коллекции (FQCN): `community.docker.docker`. Если короткое имя не работает, `ansible-doc` подскажет правильное полное имя.


### Пример 1: Проверка подключения с `ping`

Модуль `ping` — это основной способ проверить, что Ansible может подключиться к хосту, выполнить на нем Python-код и получить ответ.

```bash
ansible ws01,ws02,ws03 -m ping -i inventory.ini -u bond --ask-pass
```
-   `ws01,ws02,ws03`: Выполнить команду на указанных хостах.
-   `-i inventory.ini`: Указать файл инвентаря.
-   `-u bond`: Указать пользователя для SSH-подключения.
-   `--ask-pass`: Запросить пароль для SSH.

Если подключение успешно, каждый хост вернет `pong`.

### Пример 2: Выполнение произвольных команд с `command`, `shell`

*   `command`: для простых команд без конвейеров (`|`), перенаправлений (`>`) или переменных окружения. Это модуль по умолчанию: если вы не указываете модуль через `-m`, Ansible попытается выполнить вашу строку как `command`.
*   `shell`: для выполнения сложных скриптов и команд в полноценной оболочке узла. Позволяет использовать пайпы, перенаправления и т.д.

```bash
# Выполнить команду 'date' на localhost (используется модуль command по умолчанию)
ansible localhost -a "date"

# Посмотреть содержимое корневого каталога с помощью shell
ansible all -i inventory.ini -m shell -a "ls -la /"
```
> **Внимание:** Используйте `shell` и `command` с осторожностью. Они часто нарушают **идемпотентность**, так как выполняют команды императивно, а не декларативно. Каждый запуск будет помечен как `changed`, и Ansible не сможет проверить, нужно ли действие на самом деле. Это "грязные хаки", которых стоит избегать в пользу специализированных модулей, если это возможно. Их основное применение — задачи, для которых нет модуля, или первоначальная установка Python.

### Пример 3: Сбор информации о системе (Факты)

Модуль `setup` собирает обширную информацию (факты) об управляемом хосте. Эти факты автоматически собираются при первом соединении с сервером в плейбуке и могут быть использованы как переменные.

```bash
ansible localhost -m setup
```
**Результат:**

Ansible выведет большой объем JSON-данных, содержащих информацию о системе, такую как IP-адреса, операционная система, версии, ядро, жесткие диски и т.д.

### Модуль `raw` для первоначальной настройки

Модуль `raw` выполняет команду через SSH "как есть", без использования Python-обертки. Ему не нужен Python на целевом хосте, что делает его ключевым инструментом для первоначальной установки Python на "голые" серверы.

```bash
# Пример установки Python на "голый" Debian/Ubuntu
ansible new_server -m raw -a "apt-get update && apt-get install -y python3"
```