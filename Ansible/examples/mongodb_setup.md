# Ansible: автоматизация развертывания MongoDB Replica Set

## Определения

**MongoDB Replica Set** — отказоустойчивый кластер, состоящий из нескольких узлов `mongod`, который обеспечивает автоматическое переключение при сбоях (failover) и высокую доступность данных. Теоретические основы механизмов кворума, Oplog и Write Concern описаны в разделе **[Репликация в MongoDB](../../Databases/MongoDB/mongodb-replication.md)**.

**community.mongodb** — специализированная коллекция Ansible (FQCN), предоставляющая модули для управления конфигурацией, пользователями и репликацией MongoDB. Начиная с версии 8.0+, является основным инструментом автоматизации.

**mongosh (MongoDB Shell)** — современная интерактивная оболочка на базе Node.js, пришедшая на смену устаревшей `mongo`. В 2026 году является обязательной для выполнения административных скриптов через Ansible.

**keyFile** — секретный файл, используемый для взаимной аутентификации узлов внутри реплика-сета. Без него включение RBAC в кластере невозможно.

**RBAC (Role-Based Access Control)** — система управления доступом на основе ролей (например, `root`, `readWrite`), критически важная для защиты данных в распределенных системах. Подробнее — в разделе **[Безопасность MongoDB](../../Databases/MongoDB/mongodb-security.md)**.

## Базовые концепции

### Зависимости и инструментарий

Автоматизация MongoDB 8.0+ требует актуальных версий Python-драйверов на целевых хостах.

| Компонент | Требование | Назначение |
|---|---|---|
| `community.mongodb` | Управляющий узел | Коллекция модулей для управления всеми аспектами БД. |
| `pymongo` | Целевой хост | Python-библиотека для взаимодействия Ansible с протоколом MongoDB. |
| `mongosh` | Целевой хост | CLI-инструмент для выполнения команд и проверки состояния кластера. |

Установка коллекции:
```bash
ansible-galaxy collection install community.mongodb
```

### Предварительные требования (Prerequisites)

Перед запуском плейбуков необходимо убедиться в выполнении следующих условий на **управляющем узле** и **целевых хостах**:

**Управляющий узел (Control Node):**

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible | 2.15+ (рекомендуется ≥ 10.x для поддержки `community.mongodb`) | `ansible --version` |
| Python | 3.10+ | `python3 --version` |
| `community.mongodb` | Последняя версия | `ansible-galaxy collection list community.mongodb` |

**Целевые хосты (Managed Nodes):**

| Компонент | Требование | Назначение |
|---|---|---|
| Python 3 | 3.8+ | Модули Ansible работают через Python на целевом хосте |
| `pymongo` | 4.0+ | Python-драйвер для MongoDB (обязателен для модулей `community.mongodb`) |
| MongoDB Server | 7.0+ (рекомендуется 8.0+) | Целевая версия СУБД |
| `mongosh` | 2.0+ | Современная оболочка для административных скриптов |
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

# Проверка mongosh
mongosh --version 2>/dev/null || echo "mongosh NOT installed"
```

### Архитектура и роли узлов

1.  **Primary:** Единственный узел, принимающий операции записи.
2.  **Secondary:** Узлы, копирующие данные с Primary. Могут участвовать в выборах нового лидера.
3.  **Arbiter:** Узел, который участвует только в голосовании и не хранит данные (используется для достижения нечетного количества голосующих узлов).

### Принципы безопасности и идемпотентности

- **Этапность**: При первой установке сначала настраивается `keyFile` и базовая конфигурация, затем инициализируется Replica Set, и только после создания пользователя `admin` включается авторизация (`security.authorization: enabled`).
- **Тюнинг системы**: Для работы MongoDB 8.0+ через Ansible необходимо обеспечить отключение **Transparent Huge Pages (THP)** (с персистентным сохранением через systemd) и установку лимитов `ulimit` (не менее 64000).
- **Секреты**: Содержимое `keyFile` и пароли пользователей должны храниться исключительно в **[Ansible Vault](../Vault/basics.md)**.

---

## Практические сценарии

### Сценарий 1: Полный цикл развертывания кластера MongoDB 8.0

Плейбук включает настройку репозиториев, установку, системную оптимизацию и инициализацию репликации.

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
    - name: Импорт GPG-ключа MongoDB
      ansible.builtin.apt_key:
        url: "https://www.mongodb.org/static/pgp/server-{{ mongodb_version }}.asc"
        state: present
        keyring: /usr/share/keyrings/mongodb-server.gpg

    - name: Добавление официального репозитория
      ansible.builtin.apt_repository:
        repo: "deb [signed-by=/usr/share/keyrings/mongodb-server.gpg] https://repo.mongodb.org/apt/ubuntu {{ ansible_facts['distribution_release'] }}/mongodb-org/{{ mongodb_version }} multiverse"
        state: present

    - name: Установка пакетов MongoDB и Python-драйверов
      ansible.builtin.package:
        name:
          - mongodb-org
          - python3-pymongo
        state: present
        update_cache: yes

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

**Валидация (ожидаемый результат):**

После выполнения плейбука проверьте корректность развертывания:

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

# Проверка отключения THP
cat /sys/kernel/mm/transparent_hugepage/enabled
# → [always] madvise never  (never выделен квадратными скобками)

# Проверка лимитов ulimit
sudo -u mongodb bash -c "ulimit -n"
# → 64000

# Идемпотентность: повторный запуск не должен показать changes
ansible-playbook playbook.yml --diff
# → В идеале: 0 changed
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

### Сценарий 3: Настройка брандмауэра (Firewall)

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

---

## Запуск и структура проекта

### Пример инвентаря (inventory)

**Файл `inventory.ini`:**
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
└── templates/
    └── mongod.conf.j2     # Шаблон конфигурации MongoDB
```

**Создание зашифрованных переменных:**
```bash
# Создание файла Vault
ansible-vault create vars/vault.yml
# → Содержимое:
#   vault_mongodb_keyfile: "MIIB... (содержимое keyFile)"
#   vault_mongodb_admin_pass: "StrongAdmin2026!"

# Шифрование отдельной строки (для вставки в YAML)
ansible-vault encrypt_string 'SuperSecretKeyFileContent' --name 'vault_mongodb_keyfile'
```

### Команды запуска

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

---

## Дополнительная информация

### Использование Module Defaults

Для сокращения кода при большом количестве задач можно использовать `module_defaults`, чтобы не указывать параметры подключения в каждой задаче:

```yaml
- name: Работа с MongoDB
  hosts: all
  module_defaults:
    community.mongodb.mongodb_user:
      login_host: localhost
      login_user: admin
      login_password: "{{ vault_mongodb_admin_pass }}"
    community.mongodb.mongodb_replicaset:
      login_host: localhost
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
Сценарии в этом файле适用于 Community Edition. Enterprise добавляет LDAP/Kerberos, auditing и nativet TLS — эти функции требуют дополнительных параметров модулей.

**6. Восстановление после сбоя кластера:**
Если все узлы Replica Set недоступны одновременно, после восстановления необходимо вручную инициировать `rs.initiate({force: true})` на узле с наиболее актуальными данными. Ansible-плейбук не обрабатывает этот edge case автоматически.

### Безопасность и лучшие практики

- **Write Concern**: Для критических данных используйте `w: majority` и `j: true`.
- **Ansible Vault**: Никогда не оставляйте `vault_mongodb_keyfile` в открытом виде. Используйте `ansible-vault encrypt_string` для шифрования.
- **Принцип минимальных привилегий**: Приложениям выдавайте роль `readWrite` только в рабочей БД, не в `admin`.
- **Резервное копирование**: Рекомендуется настройка `mongodb_exporter` для Prometheus и регулярный `mongodump`.
- **no_log**: Добавляйте `no_log: true` ко всем задачам, передающим пароли или keyFile — это предотвращает утечку секретов в логах Ansible.
- **Логирование**: Настройте `systemLog.destination: file` и ротацию логов для аудита действий.

## Смотрите также

- **[Обзор MongoDB](../../Databases/MongoDB/mongodb.md)**
- **[Репликация в MongoDB](../../Databases/MongoDB/mongodb-replication.md)**
- **[Безопасность MongoDB](../../Databases/MongoDB/mongodb-security.md)**
