# Ansible: Подключения и Конфигурация

Этот документ описывает настройку тестовой среды с помощью Vagrant, управление SSH-ключами и конфигурационными файлами `ansible.cfg` для установления соединений с управляемыми узлами.

---

## 1. Настройка тестовой среды с Vagrant

Для безопасного тестирования плейбуков рекомендуется использовать виртуальные машины, управляемые Vagrant.

**Пример `Vagrantfile`:**
Этот файл описывает конфигурацию нескольких машин, включая `controlnode` и несколько серверов на Ubuntu и CentOS.

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

## 2. Проверка подключений

После настройки среды можно проверить доступность хостов с помощью `ansible`.

### Подключение к Docker-контейнеру
Ansible может управлять не только ВМ, но и Docker-контейнерами.

1.  **Запустите контейнер на `controlnode`:**
    ```bash
    vagrant ssh controlnode
    cd /ansible # Пример директории с docker-compose.yml
    sudo docker-compose up -d
    ```
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

## 3. Управление конфигурацией `ansible.cfg` и SSH

Понимание того, как Ansible находит и использует `ansible.cfg` и SSH-ключи, является ключом к успешной работе.

### Ошибка `Permission denied`
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

### Использование локального `ansible.cfg`
Ansible ищет файл `ansible.cfg` в нескольких местах, и файл в текущей директории (`./ansible.cfg`) имеет высокий приоритет. Это позволяет создавать проектно-специфичные конфигурации.

**Преимущества локального `ansible.cfg`:**
1.  **`inventory`**: Можно указать путь к файлу инвентаря, избавляясь от необходимости постоянно использовать ключ `-i`.
2.  **`private_key_file`**: Можно задать путь к приватному ключу по умолчанию для всех хостов.
3.  **`host_key_checking`**: Можно отключить проверку ключей хоста, что удобно для тестовых сред.

**Пример `ansible.cfg`:**
```ini
# ./ansible.cfg
[defaults]
inventory = ./hosts.ini
private_key_file = /home/vagrant/.ssh/vagrant_test
host_key_checking = false
```

С таким `ansible.cfg` в текущей директории:
*   Пути к ключам (`ansible_private_key_file`) можно убрать из `hosts.ini`.
*   Команду можно запускать без `-i hosts.ini`.

```bash
# Находясь в директории с ansible.cfg и hosts.ini
ansible centos -m ping
# SUCCESS
```
> **Важно!** Ansible может игнорировать `ansible.cfg`, если права на него слишком открытые (например, `777`). Убедитесь, что у файла адекватные права (например, `644` или `775` для директории).

Этот подход делает команды короче, а конфигурацию проекта — более чистой и переносимой.
