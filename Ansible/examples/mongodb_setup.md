# Ansible: автоматизация развертывания и обслуживания MongoDB Replica Set

## Определения

**MongoDB Replica Set** — отказоустойчивый кластер из нескольких узлов `mongod`, обеспечивающий автоматическое переключение при сбоях (failover) и высокую доступность данных. Теоретические основы кворума, Oplog и Write Concern описаны в разделе **[Репликация в MongoDB](../../Databases/MongoDB/mongodb-replication.md)**.

**community.mongodb** — специализированная коллекция Ansible (FQCN), предоставляющая модули для управления конфигурацией, пользователями, репликацией и обслуживанием MongoDB. Текущая стабильная версия коллекции — 1.7.x.

**mongosh (MongoDB Shell)** — современная интерактивная оболочка на базе Node.js, пришедшая на смену устаревшей `mongo`. В 2026 году является обязательной для выполнения административных скриптов через Ansible. Текущая версия — 2.8.x.

**keyFile** — секретный файл, используемый для взаимной аутентификации узлов внутри реплика-сета. Без него включение RBAC в кластере невозможно.

**RBAC (Role-Based Access Control)** — система управления доступом на основе ролей (например, `root`, `readWrite`), критически важная для защиты данных в распределенных системах. Подробнее — в разделе **[Безопасность MongoDB](../../Databases/MongoDB/mongodb-security.md)**.

**WiredTiger** — движок хранения MongoDB по умолчанию, обеспечивающий Document-level Concurrency, Snapshot Isolation и сжатие данных.

**THP (Transparent Huge Pages)** — механизм ядра Linux, который должен быть отключен для MongoDB, так как вызывает непредсказуемые задержки.

## Базовые концепции

### Зависимости и инструментарий

Автоматизация MongoDB 8.0+ требует актуальных версий Python-драйверов и инструментов на целевых хостах.

| Компонент | Требование | Назначение |
|---|---|---|
| `community.mongodb` | Управляющий узел | Коллекция модулей для управления всеми аспектами БД. |
| `pymongo` | Целевой хост | Python-библиотека для взаимодействия Ansible с протоколом MongoDB. Рекомендуется 4.9+ для полной совместимости с MongoDB 8.0. |
| `mongosh` | Целевой хост | CLI-инструмент для выполнения команд и проверки состояния кластера. Версия 2.x. |
| `dnspython` | Целевой хост | Зависимость `pymongo` для разрешения SRV-записей (рекомендуется >= 2.6.1). |

Установка коллекции на управляющем узле:
```bash
ansible-galaxy collection install community.mongodb
# → Installing 'community.mongodb' to ...
```

### Предварительные требования (Prerequisites)

Перед запуском плейбуков необходимо убедиться в выполнении следующих условий на **управляющем узле** и **целевых хостах**:

**Управляющий узел (Control Node):**

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible | 2.16+ (рекомендуется >= 2.21) | `ansible --version` |
| Python | 3.10+ | `python3 --version` |
| `community.mongodb` | 1.7.x | `ansible-galaxy collection list community.mongodb` |

**Целевые хосты (Managed Nodes):**

| Компонент | Требование | Назначение |
|---|---|---|
| Python 3 | 3.9+ | Модули Ansible работают через Python на целевом хосте |
| `pymongo` | 4.9+ | Python-драйвер для MongoDB (полная совместимость с MongoDB 8.0) |
| MongoDB Server | 8.0+ | Целевая версия СУБД |
| `mongosh` | 2.x | Современная оболочка для административных скриптов |
| Права `sudo` | Настроен `NOPASSWD` | Выполнение задач с `become: true` |
| SSH-доступ | Настроен и протестирован | Удаленное управление через Ansible |
| Файловая система | XFS (рекомендуется) | WiredTiger работает эффективнее с XFS |

**Аппаратные ограничения:**

| Требование | Минимум | Рекомендуется |
|---|---|---|
| CPU | 2 ядра (с поддержкой AVX) | 4+ ядер |
| RAM | 4 ГБ | 16+ ГБ (для Buffer Pool) |
| Диск | 20 ГБ SSD | 100+ ГБ NVMe SSD |

> **Важно:** Начиная с версии 5.0+, MongoDB требует процессор с поддержкой набора инструкций **AVX**. Проверка: `grep -q avx /proc/cpuinfo && echo "AVX supported" || echo "AVX NOT supported"`

**Проверка зависимостей на целевом хосте (однострочник):**
```bash
# Debian/Ubuntu
python3 -c "import pymongo; print(f'pymongo {pymongo.version}')" 2>/dev/null || echo "pymongo NOT installed"

# RHEL/Rocky
python3 -c "import pymongo; print(f'pymongo {pymongo.version}')" 2>/dev/null || echo "pymongo NOT installed"

# Проверка mongosh
mongosh --version 2>/dev/null || echo "mongosh NOT installed"
```

### Архитектура и роли узлов

1. **Primary:** Единственный узел, принимающий операции записи.
2. **Secondary:** Узлы, копирующие данные с Primary. Могут участвовать в выборах нового лидера.
3. **Arbiter:** Узел, который участвует только в голосовании и не хранит данные (используется для достижения нечетного количества голосующих узлов).

### Принципы безопасности и идемпотентности

- **Этапность**: При первой установке сначала настраивается `keyFile` и базовая конфигурация, затем инициализируется Replica Set, и только после создания пользователя `admin` включается авторизация (`security.authorization: enabled`).
- **Тюнинг системы**: Для работы MongoDB 8.0+ через Ansible необходимо обеспечить отключение **Transparent Huge Pages (THP)** (с персистентным сохранением через systemd) и установку лимитов `ulimit` (не менее 64000).
- **Секреты**: Содержимое `keyFile` и пароли пользователей должны храниться исключительно в **[Ansible Vault](../Vault/basics.md)**.

## Практические сценарии

### Сценарий 1: Полный цикл развертывания кластера MongoDB 8.0

Плейбук включает настройку репозиториев, установку, системную оптимизацию и инициализацию репликации для Debian/Ubuntu и RHEL/Rocky.

#### Play 1: Подготовка узлов

```yaml
---
- name: Подготовка узлов MongoDB
  hosts: mongo_nodes
  become: true
  vars:
    mongodb_version: "8.0"
    mongodb_replset_name: "rs0"
    vault_mongodb_keyfile: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      61626364656667686970...

  tasks:
    - name: Загрузка GPG-ключа MongoDB (Debian/Ubuntu)
      ansible.builtin.get_url:
        url: "https://www.mongodb.org/static/pgp/server-{{ mongodb_version }}.asc"
        dest: /usr/share/keyrings/mongodb-server.asc
        mode: "0644"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Добавление официального репозитория (Debian/Ubuntu)
      ansible.builtin.apt_repository:
        repo: "deb [signed-by=/usr/share/keyrings/mongodb-server.asc] https://repo.mongodb.org/apt/ubuntu {{ ansible_facts['distribution_release'] }}/mongodb-org/{{ mongodb_version }} multiverse"
        state: present
      when: ansible_facts['os_family'] == 'Debian'

    - name: Импорт GPG-ключа MongoDB (RHEL/Rocky)
      ansible.builtin.rpm_key:
        state: present
        key: https://www.mongodb.org/static/pgp/server-{{ mongodb_version }}.asc
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Добавление официального репозитория (RHEL/Rocky)
      ansible.builtin.copy:
        content: |
          [mongodb-org-{{ mongodb_version }}]
          name=MongoDB Repository
          baseurl=https://repo.mongodb.org/yum/redhat/$releasever/mongodb-org/{{ mongodb_version }}/x86_64/
          gpgcheck=1
          enabled=1
          gpgkey=https://www.mongodb.org/static/pgp/server-{{ mongodb_version }}.asc
        dest: /etc/yum.repos.d/mongodb-org-{{ mongodb_version }}.repo
        mode: '0644'
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Установка пакетов MongoDB и Python-драйверов (Debian/Ubuntu)
      ansible.builtin.package:
        name:
          - mongodb-org
          - python3-pymongo
        state: present
        update_cache: yes
      when: ansible_facts['os_family'] == 'Debian'

    - name: Установка пакетов MongoDB и Python-драйверов (RHEL/Rocky)
      ansible.builtin.package:
        name:
          - mongodb-org
          - python3-pymongo
        state: present
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Отключение Transparent Huge Pages (THP)
      ansible.builtin.shell: |
        echo never > /sys/kernel/mm/transparent_hugepage/enabled
        echo never > /sys/kernel/mm/transparent_hugepage/defrag
      changed_when: false

    - name: Персистентное отключение THP через systemd
      ansible.builtin.copy:
        content: |
          [Unit]
          Description=Disable Transparent Huge Pages (THP)
          DefaultDependencies=no
          After=sysinit.target local-fs.target
          Before=mongod.service

          [Service]
          Type=oneshot
          ExecStart=/bin/sh -c 'echo never | tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null'
          ExecStart=/bin/sh -c 'echo never | tee /sys/kernel/mm/transparent_hugepage/defrag > /dev/null'

          [Install]
          WantedBy=multi-user.target
        dest: /etc/systemd/system/disable-thp.service
        mode: '0644'
      notify: Reload Systemd

    - name: Включение службы отключения THP
      ansible.builtin.service:
        name: disable-thp
        state: started
        enabled: yes

    - name: Настройка лимитов ulimit для MongoDB
      ansible.builtin.copy:
        content: |
          mongodb soft nofile 64000
          mongodb hard nofile 64000
          mongodb soft nproc 64000
          mongodb hard nproc 64000
        dest: /etc/security/limits.d/99-mongodb.conf
        mode: '0644'

    - name: Деплой keyFile для кластера
      ansible.builtin.copy:
        content: "{{ vault_mongodb_keyfile }}"
        dest: /var/lib/mongodb/keyfile
        owner: mongodb
        group: mongodb
        mode: '0400'
      no_log: true

    - name: Деплой шаблона mongod.conf
      ansible.builtin.template:
        src: templates/mongod.conf.j2
        dest: /etc/mongod.conf
        owner: root
        group: root
        mode: '0644'
      notify: Restart Mongodb

  handlers:
    - name: Reload Systemd
      ansible.builtin.systemd:
        daemon_reload: yes

    - name: Restart Mongodb
      ansible.builtin.service:
        name: mongod
        state: restarted
```

#### Play 2: Инициализация Replica Set и настройка RBAC

```yaml
- name: Инициализация Replica Set
  hosts: mongo_primary
  become: true
  vars:
    mongodb_replset_name: "rs0"
    vault_mongodb_admin_pass: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      ...

  tasks:
    - name: Ожидание запуска службы
      ansible.builtin.wait_for:
        port: 27017
        timeout: 60

    - name: Инициализация репликации (Replica Set)
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: "{{ mongodb_replset_name }}"
        members: "{{ groups['mongo_nodes'] }}"
      run_once: true

    - name: Создание администратора кластера
      community.mongodb.mongodb_user:
        database: admin
        name: admin
        password: "{{ vault_mongodb_admin_pass }}"
        roles:
          - { db: "admin", role: "root" }
        state: present
      run_once: true
      no_log: true

    - name: Включение авторизации в конфигурации
      ansible.builtin.lineinfile:
        path: /etc/mongod.conf
        insertafter: '^#?security:'
        line: |
          security:
            authorization: enabled
      notify: Restart Mongodb After Auth

  handlers:
    - name: Restart Mongodb After Auth
      ansible.builtin.service:
        name: mongod
        state: restarted
```

> **Примечание по порядку задач:** Авторизация (`security.authorization: enabled`) включается **только после** создания пользователя `admin`. Если включить её ранее, модуль `community.mongodb.mongodb_user` не сможет подключиться для создания пользователя, так как MongoDB откажет в доступе без аутентификации.

**Пример шаблона `templates/mongod.conf.j2`:**
```yaml
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true

systemLog:
  destination: file
  logAppend: true
  path: /var/log/mongodb/mongod.log

net:
  port: 27017
  bindIp: {{ ansible_default_ipv4.address }},127.0.0.1

security:
  keyFile: /var/lib/mongodb/keyfile

replication:
  replSetName: "{{ mongodb_replset_name }}"
```

### Сценарий 2: Настройка TLS/SSL для защиты трафика

Обязательный шаг для обеспечения безопасности в 2026 году. TLS 1.3 обеспечивает минимальные задержки при рукопожатии.

```yaml
- name: Настройка TLS для MongoDB
  hosts: mongo_nodes
  become: true
  vars:
    mongodb_tls_cert_src: "certs/{{ inventory_hostname }}.pem"
    mongodb_tls_ca_src: "certs/ca.pem"

  tasks:
    - name: Деплой сертификата сервера
      ansible.builtin.copy:
        src: "{{ mongodb_tls_cert_src }}"
        dest: /etc/ssl/mongodb.pem
        mode: '0400'
        owner: mongodb
        group: mongodb

    - name: Деплой CA-сертификата
      ansible.builtin.copy:
        src: "{{ mongodb_tls_ca_src }}"
        dest: /etc/ssl/ca.pem
        mode: '0444'
        owner: root
        group: root

    - name: Включение TLS в конфигурации
      ansible.builtin.blockinfile:
        path: /etc/mongod.conf
        marker: "# {mark} TLS CONFIGURATION BLOCK"
        block: |
          net:
            ssl:
              mode: requireSSL
              PEMKeyFile: /etc/ssl/mongodb.pem
              CAFile: /etc/ssl/ca.pem
              allowConnectionsWithoutCertificates: false
      notify: Restart Mongodb

  handlers:
    - name: Restart Mongodb
      ansible.builtin.service:
        name: mongod
        state: restarted
```

**Валидация TLS:**

```bash
# Проверка включения TLS на сервере
mongosh --eval "db.adminCommand({getParameter: 1, sslArePeersVerified: 1})"
# → { "sslArePeersVerified" : true }

# Проверка конфигурации TLS
mongosh --eval "db.adminCommand({getParameter: 1, sslMode: 1})"
# → { "sslMode" : "requireSSL" }

# Тест подключения с TLS (с клиента)
mongosh --tls --tlsCertificateKeyFile /etc/ssl/client.pem --tlsCAFile /etc/ssl/ca.pem --host mongodb://mongo1:27017
# → Подключение успешно
```

### Сценарий 3: Автоматизация резервного копирования

Регулярные бэкапы через `mongodump` с ротацией и хранением в локальном хранилище или сетевом NAS.

```yaml
- name: Автоматизация резервного копирования MongoDB
  hosts: mongo_nodes
  become: true
  vars:
    backup_dir: /opt/mongodb_backups
    retention_days: 7
    vault_mongodb_backup_user: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      ...
    vault_mongodb_backup_pass: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      ...

  tasks:
    - name: Установка пакета mongodb-database-tools
      ansible.builtin.package:
        name:
          - mongodb-database-tools
        state: present

    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        owner: mongodb
        group: mongodb
        mode: '0750'

    - name: Создание пользователя для бэкапов
      community.mongodb.mongodb_user:
        database: admin
        name: backup_user
        password: "{{ vault_mongodb_backup_pass }}"
        roles:
          - { db: "admin", role: "backup" }
          - { db: "admin", role: "readAnyDatabase" }
        state: present
      no_log: true

    - name: Деплой скрипта бэкапа
      ansible.builtin.template:
        src: templates/mongodb_backup.sh.j2
        dest: /usr/local/bin/mongodb_backup.sh
        owner: root
        group: root
        mode: '0750'
      notify: Reload Systemd Timers

    - name: Включение systemd-таймера для ежедневного бэкапа
      ansible.builtin.template:
        src: templates/mongodb_backup.timer.j2
        dest: /etc/systemd/system/mongodb-backup.timer
        owner: root
        group: root
        mode: '0644'
      notify: Reload Systemd Timers

    - name: Включение systemd-сервиса бэкапа
      ansible.builtin.template:
        src: templates/mongodb_backup.service.j2
        dest: /etc/systemd/system/mongodb-backup.service
        owner: root
        group: root
        mode: '0644'
      notify: Reload Systemd Timers

    - name: Запуск и включение таймера бэкапа
      ansible.builtin.service:
        name: mongodb-backup.timer
        state: started
        enabled: yes

  handlers:
    - name: Reload Systemd Timers
      ansible.builtin.systemd:
        daemon_reload: yes
```

**Пример шаблона `templates/mongodb_backup.sh.j2`:**
```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="{{ backup_dir }}"
RETENTION_DAYS="{{ retention_days }}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="{{ backup_dir }}/mongodb_backup_${DATE}.archive"

/usr/bin/mongodump \
  --uri="mongodb://{{ vault_mongodb_backup_user }}:{{ vault_mongodb_backup_pass }}@localhost:27017/admin?replicaSet={{ mongodb_replset_name }}" \
  --archive="$BACKUP_FILE" \
  --gzip

# Ротация старых бэкапов
find "$BACKUP_DIR" -name "mongodb_backup_*.archive" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $BACKUP_FILE"
```

### Сценарий 4: Настройка брандмауэра (Firewall)

```yaml
- name: Настройка Firewall для MongoDB
  hosts: mongo_nodes
  become: true

  tasks:
    - name: Разрешение порта 27017 в UFW (Debian/Ubuntu)
      community.general.ufw:
        rule: allow
        port: 27017
        proto: tcp
        from_ip: "{{ item }}"
      loop: "{{ groups['mongo_nodes'] }}"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Открытие порта в Firewalld (RHEL/Rocky)
      ansible.posix.firewalld:
        port: 27017/tcp
        permanent: yes
        state: enabled
        immediate: yes
      when: ansible_facts['os_family'] == 'RedHat'
```

**Валидация сетевых правил:**

```bash
# Проверка UFW (Debian/Ubuntu)
sudo ufw status | grep 27017
# → 27017/tcp    ALLOW    10.0.5.20
# → 27017/tcp    ALLOW    10.0.5.21

# Проверка Firewalld (RHEL/Rocky)
sudo firewall-cmd --list-ports
# → 27017/tcp

# Тест подключения с удаленного хоста
mongosh --host mongo1 --port 27017 --eval "db.runCommand({ping: 1})"
# → { "ok" : 1 }
```

### Структура проекта и инвентарь

**Пример инвентаря (`inventory.ini`):**
```ini
[mongo_nodes]
mongo1 ansible_host=10.0.5.20 ansible_user=deploy
mongo2 ansible_host=10.0.5.21 ansible_user=deploy
mongo3 ansible_host=10.0.5.22 ansible_user=deploy

[mongo_primary]
mongo1 ansible_host=10.0.5.20 ansible_user=deploy

[mongo_nodes:vars]
ansible_become=true
ansible_become_method=sudo
```

**Структура файлов проекта:**
```
mongodb-automation/
├── inventory.ini
├── playbook.yml
├── vars/
│   ├── vault.yml          # Зашифрованные пароли и keyFile
│   └── default.yml        # Обычные переменные
├── handlers/
│   └── main.yml           # Handlers (Restart Mongodb, Reload Systemd)
├── templates/
│   ├── mongod.conf.j2     # Шаблон конфигурации MongoDB
│   ├── mongodb_backup.sh.j2
│   ├── mongodb_backup.service.j2
│   └── mongodb_backup.timer.j2
└── files/
    └── certs/
        ├── ca.pem
        └── mongo1.pem
```

**Создание зашифрованных переменных:**
```bash
# Создание файла Vault
ansible-vault create vars/vault.yml
# → Содержимое:
#   vault_mongodb_keyfile: "MIIB... (содержимое keyFile)"
#   vault_mongodb_admin_pass: "StrongAdmin2026!"
#   vault_mongodb_backup_user: "backup_user"
#   vault_mongodb_backup_pass: "BackupPass2026!"

# Шифрование отдельной строки (для вставки в YAML)
ansible-vault encrypt_string 'SuperSecretKeyFileContent' --name 'vault_mongodb_keyfile'
```

### Чек-лист валидации после развертывания

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Служба запущена | `systemctl status mongod` | `active (running)` |
| Порт слушается | `ss -tlnp \| grep 27017` | Процесс `mongod` на `0.0.0.0:27017` |
| Replica Set инициализирован | `mongosh --eval "rs.status().ok"` | `1` |
| Количество узлов | `mongosh --eval "rs.status().members.length"` | `3` (или заданное число) |
| Primary определен | `mongosh --eval "rs.status().members.find(m=>m.stateStr=='PRIMARY').name"` | Имя основного узла |
| Авторизация включена | `mongosh -u admin -p --authenticationDatabase admin --eval "1"` | Подключение успешно |
| keyFile корректен | `stat -c %a /var/lib/mongodb/keyfile` | `400` |
| THP отключен | `cat /sys/kernel/mm/transparent_hugepage/enabled` | `[never]` |
| TLS активен (если настроен) | `mongosh --eval "db.adminCommand({getParameter:1,sslMode:1})"` | `requireSSL` |
| Резервное копирование работает | `systemctl status mongodb-backup.timer` | `active (waiting)` |

## Операции и команды

### Команды запуска плейбуков

```bash
# Полный запуск (с запросом пароля Vault)
ansible-playbook -i inventory.ini playbook.yml --ask-vault-pass

# Запуск с конкретными переменными
ansible-playbook -i inventory.ini playbook.yml \
  -e @vars/default.yml \
  --ask-vault-pass

# Проверка без выполнения (dry-run)
ansible-playbook -i inventory.ini playbook.yml --check --diff --ask-vault-pass

# Запуск только подготовки (Play 1)
ansible-playbook -i inventory.ini playbook.yml --limit "mongo_nodes" --ask-vault-pass

# Запуск только инициализации (Play 2)
ansible-playbook -i inventory.ini playbook.yml --limit "mongo_primary" --ask-vault-pass

# Ограничение по конкретному хосту
ansible-playbook -i inventory.ini playbook.yml --limit "mongo1" --ask-vault-pass
```

### Основные параметры модулей

| Модуль | Параметр | Значение | Назначение |
|---|---|---|---|
| `community.mongodb.mongodb_replicaset` | `replica_set` | Имя RS (например, `rs0`) | Идентификатор реплика-сета |
| `community.mongodb.mongodb_replicaset` | `members` | Список хостов | Узлы кластера |
| `community.mongodb.mongodb_replicaset` | `login_host` | `localhost` | Хост для подключения |
| `community.mongodb.mongodb_user` | `database` | `admin` | БД для создания пользователя |
| `community.mongodb.mongodb_user` | `name` | Имя пользователя | Логин |
| `community.mongodb.mongodb_user` | `password` | Пароль из Vault | Пароль пользователя |
| `community.mongodb.mongodb_user` | `roles` | Список ролей | Назначенные роли |

### mongosh: основные команды

```bash
# Проверка статуса Replica Set
mongosh --eval "rs.status().ok"
# → 1

# Проверка участников кластера
mongosh --eval "rs.status().members.forEach(function(m) { print(m.name + ' - ' + m.stateStr) })"
# → mongo1:27017 - PRIMARY
# → mongo2:27017 - SECONDARY
# → mongo3:27017 - SECONDARY

# Проверка включения авторизации
mongosh --eval "db.getAdminCmd({getParameter: 1, authenticationMechanisms: 1})"
# → { "authenticationMechanisms" : [ "SCRAM-SHA-256" ] }

# Проверка создания пользователя admin
mongosh -u admin -p --authenticationDatabase admin --eval "db.getUser('admin')"
# → { "user" : "admin", "roles" : [ { "role" : "root", "db" : "admin" } ] }

# Проверка статуса бэкапа
systemctl status mongodb-backup.timer
# → Active: active (waiting) since ...
```

## Устранение неисправностей

### Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `keyFile precision too open` | Права на файл превышают `0400`. | Убедитесь, что `mode: '0400'` и владелец `mongodb`. |
| `mongosh not found` | Используется устаревшая версия MongoDB. | Обновите MongoDB до 8.0+. Shell `mongo` удален. |
| `Replica set is not yet initialized` | Попытка создать пользователя до `rs.initiate()`. | Соблюдайте порядок задач в сценарии 1. |
| `Authentication failed` | Несовпадение `keyFile` на разных узлах. | Используйте одну переменную из Vault для всех узлов. |
| `No such file or directory: /var/lib/mongodb/keyfile` | MongoDB не может прочитать keyFile (права или путь). | Проверьте `ls -la /var/lib/mongodb/keyfile` и владельца. |
| `pymongo.errors.OperationFailure: not authorized` | Авторизация включена до создания пользователя `admin`. | Включайте `security.authorization` только после Play 2. |
| `Reconfiguration rejected: version number error` | Параллельная инициализация на нескольких узлах. | Используйте `run_once: true` и `limit: mongo_primary`. |
| `Timed out waiting for port 27017` | Служба mongod не запустилась после деплоя конфигурации. | Проверьте `journalctl -u mongod -n 50` на наличие ошибок. |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Невалидный или просроченный сертификат TLS. | Проверьте срок действия: `openssl x509 -in cert.pem -noout -dates`. |
| `Connection refused` | Firewall блокирует порт 27017. | Проверьте `ufw status` или `firewall-cmd --list-all`. |
| `Illegal instruction (core dumped)` | CPU не поддерживает AVX. | Перейдите на старое оборудование или используйте MongoDB < 5.0 (не рекомендуется). |
| `WiredTiger error (13)` | Проблемы с правами на `/var/lib/mongodb`. | `sudo chown -R mongodb:mongodb /var/lib/mongodb`. |

## Рекомендации

### Безопасность и лучшие практики

- **Write Concern**: Для критических данных используйте `w: majority` и `j: true`.
- **Ansible Vault**: Никогда не оставляйте `vault_mongodb_keyfile` в открытом виде. Используйте `ansible-vault encrypt_string` для шифрования.
- **Принцип минимальных привилегий**: Приложениям выдавайте роль `readWrite` только в рабочей БД, не в `admin`.
- **Резервное копирование**: Настройте автоматические бэкапы через `mongodump` с ротацией и проверяйте целостность восстановления.
- **no_log**: Добавляйте `no_log: true` ко всем задачам, передающим пароли или keyFile — это предотвращает утечку секретов в логах Ansible.
- **Логирование**: Настройте `systemLog.destination: file` и ротацию логов для аудита действий.
- **Мониторинг**: Разверните `mongodb_exporter` для Prometheus и настройте алерты наReplica Lag, Oplog Window и доступность Primary.

## Дополнительная информация

### Использование Module Defaults

Для сокращения кода при большом количестве задач можно использовать `module_defaults`, чтобы не указывать параметры подключения в каждой задаче:

```yaml
- name: Работа с MongoDB
  hosts: all
  module_defaults:
    group/community.mongodb:
      login_host: localhost
      login_user: admin
      login_password: "{{ vault_mongodb_admin_pass }}"
  tasks:
    - name: Создание пользователя приложения
      community.mongodb.mongodb_user:
        database: app_db
        name: app_user
        password: "{{ vault_mongodb_app_pass }}"
        roles:
          - { db: "app_db", role: "readWrite" }
        state: present
```

### Масштабирование и обслуживание

При добавлении новых узлов в инвентарь модуль `mongodb_replicaset` автоматически обнаруживает новые IP-адреса и выполняет `rs.reconfig()`. Если узел является Арбитром, укажите параметр `arbiterOnly: true` в определении участника.

Для последовательного развертывания (избегая параллельных конфликтов) используйте `serial: 1`:
```yaml
- name: Подготовка узлов MongoDB
  hosts: mongo_nodes
  serial: 1
  become: true
  tasks:
    # ...
```

### Краевые случаи (Edge Cases)

**1. Первый запуск с существующими данными:**
Если MongoDB уже был установлен и содержит данные, `community.mongodb.mongodb_replicaset` может завершиться ошибкой, так как Replica Set уже инициализирован. Перед запуском плейбука проверьте: `mongosh --eval "rs.status()"`. Если RS уже существует, используйте `force: yes` с осторожностью.

**2. Нечетное количество голосующих узлов:**
Для обеспечения кворума требуется нечетное число голосующих узлов (3, 5, 7). Использование 2 узлов без арбитра приведет к невозможности выборов при сбое сети. Добавьте Arbiter или третий узел.

**3. Переключение Primary при настройке TLS:**
Если Primary-узел переключился во время деплоя TLS-сертификатов, Play 2 (инициализация) может подключиться к другому узлу. Убедитесь, что `mongo_primary` в инвентаре всегда указывает на текущий Primary.

**4. Идемпотентность `mongodb_replicaset`:**
Повторный запуск модуля `mongodb_replicaset` с теми же параметрами не вызывает ошибок — модуль проверяет текущее состояние перед `rs.reconfig()`. Однако при изменении состава `members` (добавлении/удалении узлов) конфигурация будет обновлена.

**5. Отличия MongoDB Community vs Enterprise:**
Сценарии в этом файле относятся к Community Edition. Enterprise добавляет LDAP/Kerberos, auditing и native TLS — эти функции требуют дополнительных параметров модулей.

**6. Восстановление после сбоя кластера:**
Если все узлы Replica Set недоступны одновременно, после восстановления необходимо вручную инициировать `rs.initiate({force: true})` на узле с наиболее актуальными данными. Ansible-плейбук не обрабатывает этот edge case автоматически.

### Кроссплатформенные замечания

- Название пакета на RHEL/Rocky — `mongodb-org`. Репозиторий настраивается через `/etc/yum.repos.d/`.
- Путь к конфигурационному файлу (`mongod.conf`) одинаков на Debian/Ubuntu и RHEL/Rocky (`/etc/mongod.conf`).
- На RHEL/Rocky пакет Python-библиотеки называется `python3-pymongo`.
- На RHEL/Rocky настройте контексты SELinux для `/var/lib/mongodb` и `/var/run/mysqld/` (если используется).
- На RHEL/Rocky для установки `mongosh` используйте пакет `mongodb-mongosh-shared-openssl3` для OpenSSL 3 или `mongodb-mongosh-shared-openssl11` для OpenSSL 1.1.

## Смотрите также

- **[Обзор MongoDB](../../Databases/MongoDB/mongodb.md)**
- **[Репликация в MongoDB](../../Databases/MongoDB/mongodb-replication.md)**
- **[Безопасность MongoDB](../../Databases/MongoDB/mongodb-security.md)**
