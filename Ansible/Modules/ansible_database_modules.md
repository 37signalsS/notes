# Ansible: Модули управления базами данных и сервисами

## Определения

**Модули управления базами данных** — группа декларативных инструментов Ansible из специализированных коллекций (`community.general`, `community.postgresql`, `ansible.mysql`, `community.mongodb`), предназначенных для автоматизации развертывания, конфигурации и администрирования СУБД в production-средах.

**Модули управления кэширующими сервисами** — инструменты для автоматизации развертывания и конфигурации Redis, Memcached и аналогичных систем, используемых как кэши, брокеры сообщений или хранилища сессий.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `namespace.collection.module` (например, `community.postgresql.postgresql_db`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения.

**Идемпотентность** — свойство модуля, гарантирующее, что повторные запуски не приведут к изменениям, если система уже находится в целевом состоянии. Для модулей управления БД это критично при создании баз данных, управлении привилегиями и выполнении DDL-запросов.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ |
| **community.postgresql** | 4.0+ | 5.0+ |
| **ansible.mysql** | 5.0+ | 5.2+ |
| **community.mongodb** | 1.7+ | 1.8+ |
| **community.general** | 13.0+ | Актуальная |
| **Python** (target) | 3.9+ | 3.12+ |
| **sudo** (target) | 1.8+ | Актуальная LTS |

**Установка коллекций:**
```bash
ansible-galaxy collection install community.postgresql
ansible-galaxy collection install ansible.mysql
ansible-galaxy collection install community.mongodb
ansible-galaxy collection install community.general
```

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible-doc -l community.postgresql | head -10
# → community.postgresql.postgresql_db
# → community.postgresql.postgresql_user
# → community.postgresql.postgresql_ext

ansible-doc -l ansible.mysql | head -10
# → ansible.mysql.mysql_db
# → ansible.mysql.mysql_user
# → ansible.mysql.mysql_replication

ansible-doc -l community.mongodb | head -10
# → community.mongodb.mongodb_user
# → community.mongodb.mongodb_replicaset
# → community.mongodb.mongodb_shard

ansible-doc -l community.general | grep redis
# → community.general.redis
# → community.general.redis_info
```

## Архитектура и принципы работы

Модули управления базами данных operate на уровне целевых хостов и требуют установленных Python-драйверов и клиентских утилит СУБД. Их работа делится на несколько уровней:

### 1. Уровень операционной системы

Перед использованием модулей управления БД необходимо:
- Установить серверные пакеты СУБД (`postgresql16`, `postgresql16-server`, `mysql-server`, `mongodb-org`, `redis-server`)
- Установить Python-драйверы (`python3-psycopg2` или `python3-psycopg3`, `python3-pymysql`, `python3-pymongo`, `python3-redis`)
- Настроить `pg_hba.conf` / `my.cnf` / `mongod.conf` для аутентификации
- Создать системного пользователя БД (`postgres`, `mysql`)

### 2. Уровень СУБД

На этом уровне работают модули коллекций:
- Создание/удаление БД, пользователей, ролей
- Управление расширениями, схемами, табличными пространствами
- Выполнение SQL-запросов для миграций
- Настройка репликации и шардирования

### 3. Уровень прикладного доступа

Модули управления кэширующими сервисами (Redis) operate на уровне:
- Управления экземпляром Redis (запуск, остановка, конфигурация)
- Сбора метрик и аудита конфигурации
- Настройки persistence и репликации Redis

### Взаимодействие с handlers

При изменении конфигурации СУБД часто требуется перезапуск сервиса. Используйте `notify` + `handler` для атомарного применения изменений:

```yaml
- name: "Настройка PostgreSQL"
  community.postgresql.postgresql_alter_system:
    name: max_connections
    value: "200"
  notify: "Reload PostgreSQL"
```

## Основные концепции

### Модули управления PostgreSQL

1. **`community.postgresql.postgresql_db`**: Управление базами данных. Создание, удаление, переименование. Поддерживает `name`, `owner`, `encoding`, `lc_collate`, `state`.
2. **`community.postgresql.postgresql_user`**: Управление пользователями. Создание, удаление, изменение прав, `role_attr_flags` (SUPERUSER, LOGIN, CREATEDB), `groups`, `expires`.
3. **`community.postgresql.postgresql_ext`**: Управление расширениями (`pg_stat_statements`, `pgcrypto`, `uuid-ossp`).
4. **`community.postgresql.postgresql_query`**: Выполнение SQL-запросов для миграций и проверок.
5. **`community.postgresql.postgresql_slot`**: Управление слотами репликации (physical/logical). Поддерживает `slot_type`, `output_plugin`, `state`.
6. **`community.postgresql.postgresql_info`**: Сбор информации о конфигурации и состоянии PostgreSQL. Возвращает `config`, `tablespaces`, `roles`, `replication`. Полезен для аудита.
7. **`community.postgresql.postgresql_privs`**: Управление привилегиями на объектах БД (GRANT/REVOKE). Поддерживает `type` (table, schema, database), `objs`, `privs`, `roles`.
8. **`community.postgresql.postgresql_pg_hba`**: Управление правилами `pg_hba.conf`. Добавление, удаление, модификация правил аутентификации.

### Модули управления MySQL/MariaDB

1. **`ansible.mysql.mysql_db`**: Управление базами данных. Создание, удаление, импорт SQL-дампа. Поддерживает `name`, `state`, `collation`, `encoding`.
2. **`ansible.mysql.mysql_user`**: Управление пользователями. Создание, удаление, изменение прав. Поддерживает `name`, `password`, `host`, `priv`, `requires_ssl`, `update_password`.
3. **`ansible.mysql.mysql_replication`**: Управление репликацией. Настройка primary-replica, `gtid_mode`.
4. **`ansible.mysql.mysql_query`**: Выполнение SQL-запросов для миграций и проверок.

### Модули управления MongoDB

1. **`community.mongodb.mongodb_user`**: Управление пользователями. Создание, удаление, изменение ролей.
2. **`community.mongodb.mongodb_replicaset`**: Управление Replica Set. Инициализация, добавление/удаление членов.
3. **`community.mongodb.mongodb_shard`**: Управление шардированием. Добавление шардов, настройка балансировщика.
4. **`community.mongodb.mongodb_shell`**: Выполнение команд через MongoDB shell. Поддерживает `eval`, `file`, `idempotent`, `stringify`.
5. **`community.mongodb.mongodb_index`**: Управление индексами. Создание, удаление, настройка unique/sparse/partial/TTL индексов.

### Модули управления Redis

1. **`community.general.redis`**: Управление экземпляром Redis. Запуск, остановка, перезагрузка, изменение конфигурации. Поддерживает `state` (started/stopped/restarted), `config` (словарь параметров), `service`, `daemonize`.
2. **`community.general.redis_info`**: Сбор информации о конфигурации и состоянии Redis. Возвращает `config`, `stats`, `persistence`, `replication`. Полезен для аудита и мониторинга.

### Ключевые параметры

**`community.postgresql.postgresql_db`:**
- `name`: Имя базы данных.
- `owner`: Владелец БД (роль PostgreSQL).
- `encoding`: Кодировка (например, `UTF-8`).
- `lc_collate`: Сортировка (например, `en_US.UTF-8`).
- `state`: `present` (создать) или `absent` (удалить).

**`community.postgresql.postgresql_user`:**
- `name`: Имя пользователя/роли.
- `password`: Хеш пароля (рекомендуется хранить в Vault).
- `role_attr_flags`: Атрибуты роли (`LOGIN`, `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`).
- `groups`: Группы, в которые добавлять роль.
- `expires`: Дата истечения пароля.

**`ansible.mysql.mysql_db`:**
- `name`: Имя базы данных.
- `state`: `present` или `absent`.
- `collation`: Сравнение (например, `utf8mb4_unicode_ci`).
- `encoding`: Кодировка (например, `utf8mb4`).

**`ansible.mysql.mysql_user`:**
- `name`: Имя пользователя.
- `password`: Пароль (хранить в Vault).
- `host`: Хост, с которого разрешен вход (`localhost`, `%`).
- `priv`: Привилегии в формате `db.table:priv1,priv2`.
- `requires_ssl`: Требовать SSL-соединение.
- `update_password`: `always` (обновлять всегда) или `on_create` (только при создании).

**`community.general.redis`:**
- `state`: Целевое состояние (`started`, `stopped`, `restarted`).
- `config`: Словарь параметров конфигурации Redis.
- `service`: Имя systemd-сервиса (по умолчанию `redis` или `redis-server`).
- `daemonize`: Фоновый режим (для не-systemd сред).

## Практические сценарии

### Сценарий 1: Развертывание PostgreSQL с полным циклом

```yaml
- name: "Установка PostgreSQL"
  ansible.builtin.package:
    name:
      - postgresql16
      - postgresql16-server
    state: present
  become: yes

- name: "Инициализация БД"
  ansible.builtin.command: postgresql-16-setup initdb
  become: yes
  become_user: postgres

- name: "Создание БД production"
  community.postgresql.postgresql_db:
    name: production_db
    owner: app_user
    encoding: UTF-8
    lc_collate: en_US.UTF-8
  become: yes
  become_user: postgres

- name: "Создание пользователя БД"
  community.postgresql.postgresql_user:
    name: app_user
    password: "{{ vault_db_password }}"
    role_attr_flags: LOGIN,CREATEDB
    expires: "2025-12-31"
  become: yes
  become_user: postgres

- name: "Установка расширений"
  community.postgresql.postgresql_ext:
    name: pg_stat_statements
    db: production_db
  become: yes
  become_user: postgres

- name: "Аудит конфигурации"
  community.postgresql.postgresql_info:
    data: config
  register: pg_info

- name: "Проверка параметров"
  ansible.builtin.assert:
    that:
      - pg_info.config.max_connections | int >= 100
    fail_msg: "max_connections слишком низкий"
    success_msg: "Конфигурация PostgreSQL корректна"
```

### Сценарий 2: Развертывание Redis с конфигурацией и валидацией

```yaml
- name: "Установка Redis"
  ansible.builtin.package:
    name: redis-server
    state: present
  become: yes

- name: "Настройка Redis"
  community.general.redis:
    state: started
    service: redis-server
    config:
      maxmemory: "2g"
      maxmemory_policy: "allkeys-lru"
      save: "900 1"
      appendonly: "yes"
      requirepass: "{{ vault_redis_password }}"
  register: redis_config

- name: "Проверка конфигурации Redis"
  community.general.redis_info:
    data: config
  register: redis_info

- name: "Аудит параметров Redis"
  ansible.builtin.assert:
    that:
      - redis_info.config.maxmemory == "2g"
      - redis_info.config.maxmemory_policy == "allkeys-lru"
      - redis_info.config.appendonly == "yes"
    fail_msg: "Конфигурация Redis не соответствует требуемой"
    success_msg: "Конфигурация Redis корректна"
```

### Сценарий 3: Настройка репликации MySQL

```yaml
- name: "Настройка MySQL master"
  ansible.mysql.mysql_replication:
    mode: getprimary
    login_user: root
    login_password: "{{ vault_mysql_root_password }}"
  register: primary_info

- name: "Настройка MySQL replica"
  ansible.mysql.mysql_replication:
    mode: changeprimary
    primary_host: "{{ primary_info.primary_host }}"
    primary_user: repl_user
    primary_password: "{{ vault_repl_password }}"
    primary_log_file: "{{ primary_info.File }}"
    primary_log_pos: "{{ primary_info.Position }}"
  become: yes
```

### Сценарий 4: Развертывание MongoDB Replica Set

```yaml
- name: "Установка MongoDB"
  ansible.builtin.package:
    name: mongodb-org
    state: present
  become: yes

- name: "Инициализация Replica Set"
  community.mongodb.mongodb_replicaset:
    login_user: admin
    login_password: "{{ vault_mongodb_admin_password }}"
    replica_set_name: rs0
    members:
      - host: "{{ inventory_hostname }}:27017"
    state: present
  become: yes
```

### Сценарий 5: Управление пользователями и индексами MongoDB

```yaml
- name: "Создание пользователя MongoDB"
  community.mongodb.mongodb_user:
    login_user: admin
    login_password: "{{ vault_mongodb_admin_password }}"
    database: admin
    name: app_user
    password: "{{ vault_mongodb_app_password }}"
    roles:
      - db: production_db
        role: readWrite
    state: present

- name: "Создание уникального индекса"
  community.mongodb.mongodb_index:
    login_user: admin
    login_password: "{{ vault_mongodb_admin_password }}"
    database: production_db
    collection: users
    indexes:
      - keys:
          email: 1
        options:
          unique: true
          name: idx_email
    state: present
```

### Сценарий 6: Выполнение миграций через postgresql_query

```yaml
- name: "Выполнение миграции"
  community.postgresql.postgresql_query:
    login_user: app_user
    login_password: "{{ vault_db_password }}"
    db: production_db
    query: "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"
  register: migration_result
  failed_when: migration_result.failed and 'already exists' not in migration_result.msg

- name: "Проверка целостности"
  community.postgresql.postgresql_query:
    login_user: app_user
    login_password: "{{ vault_db_password }}"
    db: production_db
    query: "SELECT COUNT(*) FROM users WHERE created_at IS NULL;"
  register: null_check

- name: "Откат при ошибке"
  community.postgresql.postgresql_query:
    login_user: app_user
    login_password: "{{ vault_db_password }}"
    db: production_db
    query: "ALTER TABLE users DROP COLUMN IF EXISTS created_at;"
  when: null_check.rowcount[0][0] > 0
```

### Сценарий 7: Настройка правил pg_hba.conf

```yaml
- name: "Разрешить доступ для приложения"
  community.postgresql.postgresql_pg_hba:
    dest: /var/lib/pgsql/data/pg_hba.conf
    contype: host
    users: app_user
    source: "10.0.0.0/24"
    databases: production_db
    method: md5
    create: true
  become: yes
  become_user: postgres
  notify: "Reload PostgreSQL"

- name: "Разрешить репликацию"
  community.postgresql.postgresql_pg_hba:
    dest: /var/lib/pgsql/data/pg_hba.conf
    contype: host
    users: repl_user
    source: "10.0.1.0/24"
    databases: replication
    method: md5
  become: yes
  become_user: postgres
  notify: "Reload PostgreSQL"
```

## Операции и команды

### Базы данных

| Операция | Команда |
| :--- | :--- |
| Создание БД PostgreSQL | `community.postgresql.postgresql_db` с `name`, `owner` |
| Создание пользователя | `community.postgresql.postgresql_user` с `name`, `password`, `role_attr_flags` |
| Установка расширения | `community.postgresql.postgresql_ext` с `name`, `db` |
| SQL-запрос | `community.postgresql.postgresql_query` с `query`, `db` |
| Слот репликации | `community.postgresql.postgresql_slot` с `slot_name`, `slot_type` |
| Управление привилегиями | `community.postgresql.postgresql_privs` с `type`, `privs`, `roles` |
| Правила pg_hba | `community.postgresql.postgresql_pg_hba` с `contype`, `users`, `databases` |
| Создание БД MySQL | `ansible.mysql.mysql_db` с `name`, `state` |
| Создание пользователя MySQL | `ansible.mysql.mysql_user` с `name`, `password`, `priv` |
| Настройка репликации MySQL | `ansible.mysql.mysql_replication` с `mode`, `primary_host` |
| SQL-запрос MySQL | `ansible.mysql.mysql_query` с `query`, `db` |
| Создание пользователя MongoDB | `community.mongodb.mongodb_user` с `name`, `database`, `roles` |
| Инициализация Replica Set | `community.mongodb.mongodb_replicaset` с `replica_set_name`, `members` |
| Управление шардированием | `community.mongodb.mongodb_shard` с `shard`, `replica_set` |
| Выполнение команд MongoDB | `community.mongodb.mongodb_shell` с `eval`, `login_user` |
| Управление индексами | `community.mongodb.mongodb_index` с `database`, `indexes` |

### Кэши и сервисы

| Операция | Команда |
| :--- | :--- |
| Управление Redis | `community.general.redis` с `state`, `config` |
| Аудит Redis | `community.general.redis_info` с `data` |

### Диагностические команды

```bash
# Проверка статуса PostgreSQL
systemctl status postgresql
# → ● postgresql.service - PostgreSQL database server

# Проверка пользователей
sudo -u postgres psql -c "\du"
# → List of roles
# → Role name | Attributes | Member of
# → app_user  | Superuser  | {}

# Проверка репликации
sudo -u postgres psql -c "SHOW replica_status;"
# → Replica_IO_Running: Yes
# → Replica_SQL_Running: Yes

# Проверка правил pg_hba
sudo -u postgres psql -c "SELECT * FROM pg_hba_file_rules;"
# → type | database | user_name | address | netmask | auth_method

# Проверка Redis
redis-cli ping
# → PONG

redis-cli INFO server
# → redis_version:7.2.3
# → os:Linux 5.15.0-78-generic x86_64

# Проверка MongoDB
mongosh --eval "db.adminCommand('listDatabases')"
# → { databases: [...], ok: 1 }

# Проверка индексов
mongosh --eval "db.users.getIndexes()"
# → [ { key: { _id: 1 }, name: "_id_" }, { key: { email: 1 }, name: "idx_email", unique: true } ]
```

## Типичные ошибки и диагностика

### Ошибки PostgreSQL

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: role "app_user" does not exist` | Пользователь не создан | Создайте пользователя перед выдачей прав |
| `psycopg2.errors.DuplicateDatabase` | БД уже существует | Используйте `state: present` (идемпотентно) |
| `caching_sha2_password is not supported` | Отсутствует python3-cryptography | Установите пакет на целевой хост |
| `Peer authentication failed for user postgres` | Неправильный `become_user` | Используйте `become_user: postgres` с `become: yes` |
| `SSL error: decryption failed or bad record mac` | Несовпадение SSL-настройки клиента и сервера | Проверьте `sslmode` и сертификаты в `pg_hba.conf` |

### Ошибки MySQL/MariaDB

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Access denied for user` | Неверные учетные данные | Проверьте пароль, хост, права пользователя |
| `Unknown MySQL server host` | Хост недоступен | Проверьте DNS или `/etc/hosts` |
| `Can't connect to local MySQL server` | Служба не запущена | `systemctl start mysql` |
| `Table doesn't exist` | БД не инициализирована | Выполните `mysql_db` с `state: import` или миграции |

### Ошибки MongoDB

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- |
| `Authentication failed` | Неверные учетные данные или несуществующий пользователь | Проверьте `login_user`, `login_password`, `login_database: admin` |
| `not master and slaveOk=false` | Запрос к secondary без разрешения | Укажите `read_preference: secondary` или запрашивайте у primary |
| `Server selection timeout` | MongoDB не запущен или недоступен | `systemctl status mongod`, проверьте порт 27017 |

### Ошибки Redis

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- |
| `Could not connect to Redis` | Служба не запущена или блокировка firewall | `systemctl status redis-server`, проверьте порт 6379 |
| `WRONGPASS invalid username-password pair` | Неверный пароль или отсутствие `requirepass` | Проверьте конфигурацию Redis и пароль в Vault |
| `MISCONF Redis is configured to save RDB snapshots` | Диск заполнен | Освободите место или отключите persistence |

## Рекомендации

1. **Идемпотентность**: Всегда используйте `state: present` для создания ресурсов. Повторный запуск плейбука не должен вызывать ошибок. Модули `postgresql_db`, `mysql_db`, `mongodb_user` поддерживают идемпотентность через `state`.

2. **Хранение секретов**: Пароли и учетные данные БД храните в Ansible Vault. Используйте `no_log: true` для задач с секретами. Никогда не передавайте пароли в открытом виде в переменных плейбука.

3. **Привилегированный доступ**: Все модули управления БД требуют `become: yes` и `become_user: postgres` (для PostgreSQL) или `become_user: mysql` (для MySQL). Настройте `sudoers` для безпарольного переключения.

4. **Python-драйверы**: Убедитесь, что на целевом хосте установлены необходимые пакеты:
   - PostgreSQL: `python3-psycopg2` или `python3-psycopg3`
   - MySQL: `python3-pymysql` или `python3-mysqlclient`
   - MongoDB: `python3-pymongo`
   - Redis: `python3-redis`

5. **Репликация**: Для production используйте специализированные модули:
   - PostgreSQL: `community.postgresql.postgresql_slot` + `pg_basebackup` + `postgresql.conf`
   - MySQL: `ansible.mysql.mysql_replication`
   - MongoDB: `community.mongodb.mongodb_replicaset`

6. **Валидация**: Используйте `ansible.builtin.assert` после создания БД/пользователей для проверки корректности конфигурации. Для аудита используйте `community.postgresql.postgresql_info` и `community.general.redis_info`.

7. **Миграции**: Выполняйте DDL-миграции через `postgresql_query` / `mysql_query` внутри `block`/`rescue` для атомарности. PostgreSQL поддерживает транзакционный DDL — при ошибке все изменения откатываются.

8. **Бэкапы**: Автоматизируйте резервное копирование через `community.general.borg` или `community.general.restic` с cron-заданиями. Для PostgreSQL используйте `pg_dump` / `pg_basebackup`.

9. **Безопасность**:
   - Включайте SSL/TLS для подключений к БД (`requires_ssl: yes` для MySQL, `sslmode: require` для PostgreSQL)
   - Ограничивайте доступ к портам БД (5432, 3306, 27017, 6379) через `firewalld`/`ufw`
   - Включайте аудит PostgreSQL (`log_statement = 'all'`)

## Дополнительная информация

- **[Ansible PostgreSQL Collection](https://docs.ansible.com/ansible/latest/collections/community/postgresql/)** — документация модулей `community.postgresql`.
- **[Ansible MySQL Collection](https://docs.ansible.com/ansible/latest/collections/ansible/mysql/)** — документация модулей `ansible.mysql`.
- **[Ansible MongoDB Collection](https://docs.ansible.com/ansible/latest/collections/community/mongodb/)** — документация модулей `community.mongodb`.
