# Развертывание и настройка PostgreSQL через Ansible

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — систематический процесс управления жизненным циклом СУБД (установка, конфигурация, репликация, миграции, бэкапы, удаление) с использованием декларативных плейбуков и специализированных модулей коллекции `community.postgresql`.

**community.postgresql** — основная коллекция Ansible, содержащая модули для управления всеми аспектами PostgreSQL (базы, пользователи, расширения, слоты репликации, параметры конфигурации). Актуальная версия коллекции — **v4.2.0+** (2026 год), поддерживающая PostgreSQL 13–18.

**Идемпотентность** — свойство плейбука, гарантирующее, что повторные запуски не приведут к изменениям, если система уже находится в целевом состоянии. Для PostgreSQL это критично при создании баз данных, управлении привилегиями и выполнении DDL-запросов. Модули `postgresql_db`, `postgresql_user`, `postgresql_ext` поддерживают идемпотентность через параметр `state` (`present`/`absent`).

**Транзакционный DDL** — особенность PostgreSQL, позволяющая выполнять DDL-команды (`CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`) внутри транзакций. В сочетании с модулем `postgresql_query` и конструкцией `block`/`rescue` это обеспечивает атомарность миграций: при ошибке все изменения откатываются.

**Пул подключений (Connection Pooling)** — механизм поддержания кэша готовых соединений с PostgreSQL, снижающий накладные расходы на установку TCP/TLS-рукопожатия и аутентификацию. Для высоконагруженных сред рекомендуется **PgBouncer** или **Pgpool-II**.

**Восстановление до точки во времени (PITR)** — метод восстановления базы данных на произвольный момент в прошлом, основанный на комбинации базового резервного копирования и последовательных WAL-файлов.

## Базовые концепции

### Архитектура и принципы работы

Автоматизация PostgreSQL через Ansible строится на двух уровнях:

1. **Уровень операционной системы** — подготовка сервера: настройка ядра Linux (`sysctl`), лимитов ресурсов (`pam_limits`), установка пакетов PostgreSQL, создание пользователя `postgres`, настройка службы systemd.
2. **Уровень СУБД** — управление объектами базы данных через модули коллекции `community.postgresql`: создание БД, роли, расширения, выполнение миграций, настройка `postgresql.conf` и `pg_hba.conf`.

Для управления базовой установкой и конфигурацией файлов `postgresql.conf`/`pg_hba.conf` чаще всего используется проверенная роль сообщества **geerlingguy.postgresql** (Ansible Galaxy). Для тонкого управления объектами БД применяются специализированные модули коллекции.

**Ключевой принцип:** роль отвечает за установку и базовую конфигурацию ОС/СУБД, модули `community.postgresql` — за логику базы данных (миграции, пользователи, расширения).

### Подходы к управлению

В экосистеме Ansible выделяют два дополняющих друг друга метода:

1. **Готовые роли (Ansible Galaxy)**: Использование проверенных сообществом ролей (например, `geerlingguy.postgresql` или `triumftech.postgresql`) для быстрой установки бинарных файлов, базовой настройки ОС, конфигурации `postgresql.conf` и `pg_hba.conf`. Роль `geerlingguy.postgresql` поддерживает параметры репликации (`postgresql_replication_role`, `postgresql_replication_slots`) и управления пользователями (`postgresql_users`).
2. **Модули коллекции `community.postgresql`**: Прямое использование специализированных модулей (`postgresql_db`, `postgresql_user`, `postgresql_query`, `postgresql_ext`) для тонкой настройки логики БД, управления объектами и выполнения миграций. Этот подход обеспечивает максимальный контроль, но требует ручной настройки серверных компонентов.

**Выбор подхода:**
- Используйте **роли** для стандартных сценариев (установка, базовая репликация, мониторинг).
- Используйте **модули** для нестандартных конфигураций, сложных миграций или когда необходимо точечное управление объектами БД.

### Зависимости и инструментарий

Для работы модулей требуется Python-библиотека (драйвер) на целевом хосте. Современные версии коллекции поддерживают как классический `psycopg2`, так и новый `psycopg` (v3).

| Компонент | Где требуется | Назначение |
|---|---|---|
| `community.postgresql` | Управляющий узел | Коллекция модулей для управления PostgreSQL (установка через `ansible-galaxy`). |
| `psycopg2-binary` или `psycopg[binary]` | Управляющий узел | Python-драйвер для локальных задач (например, `postgresql_info`). |
| `python3-psycopg2` / `python3-psycopg` | Целевой хост | Системный пакет драйвера для выполнения модулей на сервере. |

**Установка зависимостей на контроллере:**

```bash
ansible-galaxy collection install community.postgresql
# → Starting galaxy collection install process
# → Process install dependency map

pip install "psycopg[binary]" # Рекомендуется для новых версий
```

На целевых хостах драйвер устанавливается через пакетный менеджер ОС (`ansible.builtin.apt` или `ansible.builtin.yum`) перед вызовом модулей PostgreSQL.

**Важно:** Модули `postgresql_*` ищут драйвер в определенном порядке. Если на хосте установлены оба драйвера (`psycopg2` и `psycopg`), Ansible выберет `psycopg` (v3) как предпочтительный. Для явного указания используйте параметр `db_driver`.

### Ключевые параметры PostgreSQL

При автоматизации конфигурации через Ansible важно понимать основные параметры `postgresql.conf`, влияющие на безопасность и производительность:

| Параметр | Описание | Рекомендация |
|---|---|---|
| `listen_addresses` | IP-адреса для принятия подключений. | `'*'` для всех интерфейсов или конкретный IP для приватных сетей. |
| `port` | Порт PostgreSQL. | По умолчанию `5432`. Изменяйте только при конфликтах. |
| `max_connections` | Максимальное количество подключений. | Зависит от RAM: ~200-500 для средних серверов. Используйте PgBouncer для connection pooling. |
| `shared_buffers` | Размер общего буфера кэша. | 25% от оперативной памяти (например, 4GB для 16GB RAM). |
| `work_mem` | Память для сортировки и хэширования на операцию. | 4-16MB. Увеличение повышает производительность сложных запросов, но увеличивает потребление памяти. |
| `maintenance_work_mem` | Память для операций обслуживания (VACUUM, CREATE INDEX). | 512MB-1GB. Ускоряет индексацию и очистку. |
| `wal_level` | Уровень логирования WAL. | `replica` для потоковой репликации, `logical` для логической репликации. |
| `max_wal_senders` | Максимальное количество процессов WAL-отправки. | Равно количеству реплик + запас (например, 10). |
| `password_encryption` | Метод шифрования паролей. | `scram-sha-256` (рекомендуется) или `md5` (устаревший). |

### Формат pg_hba.conf

Файл `pg_hba.conf` определяет правила доступа. Формат записи:

```
<тип>    <база>    <пользователь>    <адрес>    <метод аутентификации>
```

| Тип | Описание |
|---|---|
| `local` | Локальные подключения (Unix-сокеты). |
| `host` | TCP/IP подключения (включая SSL). |
| `hostssl` | Только SSL-подключения. |
| `hostnossl` | Только не-SSL подключения. |

| Метод | Описание |
|---|---|
| `trust` | Без проверки пароля (только для локальной отладки). |
| `md5` | Хэширование MD5 (устаревший, небезопасный). |
| `scram-sha-256` | Современный метод аутентификации (рекомендуется). |
| `cert` | Аутентификация по SSL-сертификату. |
| `reject` | Отклонение подключения. |

**Пример productions-ready `pg_hba.conf`:**

```conf
# Локальные подключения postgres (peer auth)
local   all             postgres                                peer

# Все подключения через localhost (scram-sha-256)
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256

# Репликация только с доверенных IP
host    replication     replicator      192.168.51.0/24         scram-sha-256

# Внешние клиенты (ограничьте CIDR в production!)
hostssl all             all             10.0.0.0/8              scram-sha-256
```

> **Важно:** В production-средах никогда не используйте `0.0.0.0/0` для `hostssl` без дополнительных средств контроля доступа (VPN, firewall, certificates). Ограничьте доступ доверенными подсетями.

---

## Предварительные требования

### Версии и совместимость

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 2.20 | `ansible --version` |
| Python (управление) | 3.10+ | ≥ 3.12 | `python3 --version` |
| Python (целевые хосты) | 3.10+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` |
| ansible-lint | 26.x+ | ≥ 26.8.0 | `ansible-lint --version` |
| community.postgresql | 4.2.0+ | 4.2.0+ | `ansible-galaxy collection list community.postgresql` |
| PostgreSQL | 13–18 | 16–18 | `psql --version` на целевом хосте |
| Целевые ОС | Debian 11+ / Ubuntu 20.04+ / RHEL 8+ | Ubuntu 24.04 / RHEL 9 | `lsb_release -a` или `cat /etc/os-release` |

### Сетевые требования

- Порт **5432** (или настроенный) должен быть открыт между управляющим узлом и целевыми серверами.
- Для репликации: порт 5432 должен быть открыт между Master и Replica.
- При использовании SSL: убедитесь, что сертификаты доступны на всех узлах.

### Права доступа

- Управляющий пользователь должен иметь права `sudo` на целевых хостах.
- Для операций управления БД используйте `become_user: postgres` (не `root`).
- Пароли и секреты храните в **[Ansible Vault](../Vault/basics.md)**.

### Структура проекта

Рекомендуемая структура для проекта PostgreSQL:

```text
ansible-postgresql/
├── ansible.cfg
├── requirements.yml           # Зависимости (collections, roles)
├── inventory/
│   ├── production/
│   │   ├── hosts.yml
│   │   └── group_vars/
│   │       ├── all.yml
│   │       └── postgres.yml
│   └── staging/
├── playbooks/
│   ├── setup_replication.yml
│   ├── migrate_db.yml
│   └── backup.yml
├── roles/
│   └── postgresql/
└── group_vars/
    └── all/
        └── vault.yml          # Зашифрованные секреты
```

---

## Практические сценарии

### Сценарий 1: Подготовка ОС и тюнинг производительности (Performance Tuning)

Для высоконагруженных инстансов PostgreSQL требуется настройка параметров ядра Linux и лимитов ресурсов.

```yaml
- name: Тюнинг системы для PostgreSQL
  hosts: postgres
  become: true
  tasks:
    - name: Настройка параметров ядра (sysctl)
      ansible.posix.sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        state: present
        sysctl_file: /etc/sysctl.d/99-postgresql.conf
      loop:
        - { key: 'vm.swappiness', value: '10' }
        - { key: 'vm.overcommit_memory', value: '2' }
        - { key: 'kernel.sched_migration_cost_ns', value: '5000000' }

    - name: Настройка лимитов ресурсов (limits.conf)
      community.general.pam_limits:
        domain: postgres
        limit_type: "{{ item.type }}"
        limit_item: "{{ item.item }}"
        value: "{{ item.value }}"
      loop:
        - { type: 'soft', item: 'nofile', value: '65536' }
        - { type: 'hard', item: 'nofile', value: '65536' }
```

**Валидация:**

```bash
# Проверка примененных параметров sysctl
ansible postgres -m shell -a "sysctl vm.swappiness vm.overcommit_memory"
# → vm.swappiness = 10
# → vm.overcommit_memory = 2

# Проверка лимитов ресурсов
ansible postgres -m shell -a "ulimit -n"
# → 65536
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `Permission denied` для `pam_limits` | Нет модуля `pam_limits.so` | Установить `libpam-modules` (Debian/Ubuntu) или `pam` (RHEL). |
| Лимиты не применяются после перезапуска | `limits.conf` не подключен | Убедитесь, что `/etc/pam.d/postgresql` содержит `session required pam_limits.so`. |

### Сценарий 2: Настройка репликации Master-Replica

Развертывание связки из основного узла (Master) и реплики (Replica) с использованием потоковой репликации и современных методов аутентификации.

**Теоретическая база:** Концептуальные основы и механизмы описаны в разделе **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)**. Подробные шаги ручной настройки: **[Настройка потоковой репликации](../../Databases/PostgreSQL/Operations/replication_setup.md)**.

#### Инвентарь `hosts.ini`

```ini
[postgres_master]
pg-master ansible_host=192.168.51.2

[postgres_replica]
pg-replica-01 ansible_host=192.168.51.3

[postgres:children]
postgres_master
postgres_replica
```

#### Плейбук `setup_replication.yml`

```yaml
---
- name: Настройка PostgreSQL Master
  hosts: postgres_master
  become: true
  vars:
    postgresql_replication_role: 'master'
    postgresql_replication_slots: ['replica_slot_01']
    postgresql_password_encryption: 'scram-sha-256'
    postgresql_hba_entries:
      - { type: local, database: all, user: postgres, auth_method: peer }
      - { type: host, database: all, user: all, address: '127.0.0.1/32', auth_method: scram-sha-256 }
      - { type: host, database: replication, user: repluser, address: '192.168.51.3/32', auth_method: scram-sha-256 }
    postgresql_users:
      - name: repluser
        password: "{{ vault_postgres_repl_password }}"
        replication: true
  roles:
    - geerlingguy.postgresql

- name: Настройка PostgreSQL Replica
  hosts: postgres_replica
  become: true
  vars:
    postgresql_replication_role: 'replica'
    postgresql_master_host: "{{ groups['postgres_master'][0] }}"
    postgresql_replication_user:
      name: repluser
      password: "{{ vault_postgres_repl_password }}"
  roles:
    - geerlingguy.postgresql
```

**Валидация:**

```bash
# Проверка статуса репликации на Master
ansible postgres_master -m shell -a "sudo -u postgres psql -c \"SELECT client_addr, state, sent_lsn, write_lsn FROM pg_stat_replication;\""
# → client_addr  | state     | sent_lsn    | write_lsn
# → 192.168.51.3 | streaming | 0/1000000   | 0/1000000

# Проверка состояния реплики
ansible postgres_replica -m shell -a "sudo -u postgres psql -c \"SELECT pg_is_in_recovery() AS is_replica;\""
# → is_replica
# → t

# Проверка задержки репликации
ansible postgres_replica -m shell -a "sudo -u postgres psql -c \"SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;\""
# → replication_lag
# → 00:00:00.000000
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `FATAL: could not connect to replicator` | Неверный пароль или IP в `pg_hba.conf` | Проверьте `pg_hba.conf` на Master и строку подключения. |
| `WAL sender process` завершается | `max_wal_senders` слишком низкий | Увеличьте `max_wal_senders` в `postgresql.conf`. |
| Реплика не запускается | Нет файла `standby.signal` | Убедитесь, что `pg_basebackup` выполнен с флагом `-R`. |
| `replication slot` забит WAL | Реплика долго не работала | Очистите слот или увеличьте `wal_keep_size`. |

**Безопасность:** Пароль репликации (`vault_postgres_repl_password`) должен быть зашифрован через **[Ansible Vault](../Vault/basics.md)**. Никогда не храните его в открытом виде.

### Сценарий 3: Создание БД и атомарная миграция схемы с откатом

Полный цикл: от создания базы данных и пользователя до безопасного выполнения изменений структуры (миграции) с использованием механизмов обработки ошибок (`block`/`rescue`).

#### Плейбук миграции `migrate_db.yml`

```yaml
---
- name: Управление базой данных и миграциями
  hosts: postgres_master
  become: true
  vars:
    db_name: "prod_app_db"
    db_user: "app_user"

  tasks:
    - name: Установка Python драйвера (Debian/Ubuntu)
      ansible.builtin.apt:
        name: python3-psycopg2 # Или python3-psycopg для новых систем
        state: present

    - name: Создание базы данных
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        state: present
      become_user: postgres

    - name: Управление расширениями (Extensions)
      community.postgresql.postgresql_ext:
        name: pg_stat_statements
        db: "{{ db_name }}"
        state: present
      become_user: postgres

    - name: Создание пользователя приложения
      community.postgresql.postgresql_user:
        name: "{{ db_user }}"
        password: "{{ vault_app_db_password }}"
        priv: "{{ db_name }}/ALL"
        state: present
      become_user: postgres

    - name: Выполнение миграции в блоке для обработки ошибок
      block:
        - name: Создание таблицы сотрудников
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: |
              CREATE TABLE IF NOT EXISTS employees (
                  id SERIAL PRIMARY KEY,
                  full_name TEXT NOT NULL,
                  position TEXT
              );
              ALTER TABLE employees OWNER TO "{{ db_user }}";
          become_user: postgres

        - name: Добавление начальных данных
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: |
              INSERT INTO employees (full_name, position) VALUES ('Иван Иванов', 'DevOps');
              INSERT INTO employees (full_name, position) VALUES ('Петр Петров', 'SRE');
          become_user: postgres

      rescue:
        - name: Откат изменений при сбое
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: "DROP TABLE IF EXISTS employees;"
          become_user: postgres
          # Примечание: PostgreSQL поддерживает транзакционный DDL.
          # Все команды внутри одного postgresql_query выполняются в единой транзакции.
```

**Валидация:**

```bash
# Проверка существования базы данных
ansible postgres_master -m community.postgresql.postgresql_db -a "name={{ db_name }} state=present" -e "ansible_become_user=postgres"

# Проверка наличия таблицы
ansible postgres_master -m shell -a "sudo -u postgres psql -d {{ db_name }} -c \"\\dt employees\""
# → List of relations
# → Schema | Name      | Type  | Owner
# → -------|-----------|-------|--------
# → public | employees | table | app_user

# Проверка расширения
ansible postgres_master -m shell -a "sudo -u postgres psql -d {{ db_name }} -c \"SELECT extname FROM pg_extension WHERE extname='pg_stat_statements';\""
# → extname
# → ----------------
# → pg_stat_statements

# Проверка прав пользователя
ansible postgres_master -m shell -a "sudo -u postgres psql -d {{ db_name }} -c \"SELECT rolname FROM pg_roles WHERE rolname='{{ db_user }}';\""
# → rolname
# → ----------
# → app_user
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `ERROR: permission denied for table` | Пользователь не имеет прав на таблицу | Проверьте `priv` в `postgresql_user` или выполните `GRANT`. |
| `ERROR: role "app_user" already exists` | Пользователь уже создан | Используйте `state: present` для идемпотентности. |
| `ERROR: extension "pg_stat_statements" already exists` | Расширение уже установлено | Модуль `postgresql_ext` с `state: present` является идемпотентным. |
| Миграция не откатывается | DDL-команды в разных `postgresql_query` | Оберните все команды в один блок `block` для транзакционного DDL. |

### Сценарий 4: Автоматизация резервного копирования (Logical Backup)

Настройка регулярного создания дампов базы данных с помощью Ansible.

```yaml
- name: Настройка резервного копирования
  hosts: postgres_master
  become: true
  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: /var/backups/postgres
        state: directory
        owner: postgres
        mode: '0700'

    - name: Создание дампа базы данных
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        state: dump
        target: "/var/backups/postgres/{{ db_name }}_{{ ansible_date_time.date }}.sql.gz"
      become_user: postgres
```

**Валидация:**

```bash
# Проверка создания директории
ansible postgres_master -m shell -a "ls -la /var/backups/postgres/"
# → drwx------ 2 postgres postgres 4096 ...
# → -rw------- 1 postgres postgres 12345 ... prod_app_db_2026-09-23.sql.gz

# Проверка размера дампа
ansible postgres_master -m shell -a "du -sh /var/backups/postgres/{{ db_name }}_{{ ansible_date_time.date }}.sql.gz"
# → 15M /var/backups/postgres/prod_app_db_2026-09-23.sql.gz

# Проверка содержимого дампа (первые строки)
ansible postgres_master -m shell -a "zcat /var/backups/postgres/{{ db_name }}_{{ ansible_date_time.date }}.sql.gz | head -5"
# → PostgreSQL database cluster dump
# → ...
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `pg_dump: error: connection to server failed` | Неверные учетные данные или PostgreSQL не запущен | Проверьте доступ `postgres` пользователя и статус сервиса. |
| `Permission denied` для директории | Неверные права на `/var/backups/postgres` | Убедитесь, что `owner: postgres` и `mode: '0700'`. |
| Дамп создается, но файл пустой | База данных пуста или нет прав на чтение | Проверьте права пользователя `postgres` на чтение всех таблиц. |

**Рекомендации по резервному копированию:**
- Используйте **cron** для регулярного запуска плейбука (например, ежедневно в 02:00).
- Храните бэкапы на удаленных носителях (NFS, tape, локальный NAS).
- Регулярно тестируйте восстановление из бэкапов.
- Для физических бэкапов (PITR) используйте **[pgBackRest](../../Databases/PostgreSQL/Concepts/backup_and_recovery.md)**.

---

## Операции и команды

### Основные команды управления проектом

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml --syntax-check` | Проверка синтаксиса YAML | `ansible-playbook playbooks/site.yml --syntax-check` |
| `ansible-playbook playbook.yml --check --diff` | Dry-run с показом изменений | `ansible-playbook playbooks/site.yml --check --diff` |
| `ansible-playbook playbook.yml --list-tasks` | Просмотр задач без выполнения | `ansible-playbook playbooks/site.yml --list-tasks` |
| `ansible-playbook playbook.yml --list-tags` | Просмотр тегов | `ansible-playbook playbooks/site.yml --list-tags` |
| `ansible-playbook playbook.yml --list-hosts` | Просмотр хостов | `ansible-playbook playbooks/site.yml --list-hosts` |
| `ansible-playbook playbook.yml --step` | Пошаговое выполнение | `ansible-playbook playbooks/site.yml --step` |
| `ansible-playbook playbook.yml --start-at-task` | Запуск с конкретной задачи | `ansible-playbook playbooks/site.yml --start-at-task="Deploy"` |
| `ansible-inventory --graph` | Визуализация инвентаря | `ansible-inventory -i environments/prod/hosts.yml --graph` |
| `ansible-inventory --host` | Переменные хоста | `ansible-inventory -i environments/prod/hosts.yml --host web1` |
| `ansible <host> -m setup` | Сбор фактов | `ansible web1 -m setup -a "filter=ansible_distribution"` |
| `ansible <host> -m debug` | Просмотр переменной | `ansible web1 -m debug -a "var=my_var"` |
| `ansible <host> -m ping` | Проверка доступности | `ansible all -m ping` |

### Команды для работы с секретами

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-vault create <file>` | Создание зашифрованного файла | `ansible-vault create group_vars/all/vault.yml` |
| `ansible-vault edit <file>` | Редактирование зашифрованного файла | `ansible-vault edit group_vars/all/vault.yml` |
| `ansible-vault encrypt <file>` | Зашифровывает существующий файл | `ansible-vault encrypt group_vars/prod/vault.yml` |
| `ansible-vault decrypt <file>` | Расшифровывает файл | `ansible-vault decrypt group_vars/prod/vault.yml --ask-vault-pass` |
| `ansible-vault view <file>` | Просмотр содержимого без записи | `ansible-vault view group_vars/prod/vault.yml --vault-password-file .vault_pass` |
| `ansible-vault encrypt_string` | Шифрование отдельной строки | `ansible-vault encrypt_string 'secret' --name 'db_password'` |

### Команды специфичные для PostgreSQL

| Команда | Назначение | Пример |
|---|---|---|
| `ansible <host> -m shell -a "sudo -u postgres psql -c \"...\""` | Выполнение произвольного SQL | `ansible pg-master -m shell -a "sudo -u postgres psql -c '\\l'"` |
| `ansible <host> -m shell -a "sudo -u postgres psql -c \"SELECT ...\""` | Проверка статуса репликации | `ansible pg-master -m shell -a "sudo -u postgres psql -c \"SELECT * FROM pg_stat_replication;\""` |
| `ansible <host> -m shell -a "sudo -u postgres psql -c \"SELECT pg_is_in_recovery();\""` | Проверка: является ли хост репликой | `ansible pg-replica -m shell -a "sudo -u postgres psql -c \"SELECT pg_is_in_recovery();\""` |
| `ansible <host> -m shell -a "sudo -u postgres psql -c \"\\dt\""` | Список таблиц в БД | `ansible pg-master -m shell -a "sudo -u postgres psql -d {{ db_name }} -c \"\\dt\""` |
| `ansible <host> -m community.postgresql.postgresql_db` | Проверка/управление БД через модуль | `ansible pg-master -m community.postgresql.postgresql_db -a "name={{ db_name }} state=present"` |

### Валидация качества кода

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml --syntax-check` | Проверка синтаксиса YAML | `ansible-playbook playbooks/site.yml --syntax-check` |
| `ansible-lint playbooks/` | Проверка качества кода | `ansible-lint playbooks/` |
| `yamllint .` | Проверка синтаксиса YAML | `yamllint .` |

---

## Устранение типичных неполадок

### Проблема: Роль не найдена при вызову

**Симптом:** `ERROR! the role 'geerlingguy.postgresql' was not found`.

**Решение:**
```bash
# Проверка установленных ролей
ansible-galaxy role list

# Установка роли
ansible-galaxy role install geerlingguy.postgresql

# Проверка структуры роли
ls -la roles/geerlingguy.postgresql/
# → defaults/ handlers/ tasks/ templates/ meta/ files/
```

### Проблема: Драйвер Python не найден

**Симптом:** `ERROR! No module named 'psycopg2'`.

**Решение:**
```bash
# Установка драйвера на целевой хост (Debian/Ubuntu)
ansible postgres -m ansible.builtin.apt -a "name=python3-psycopg2 state=present" --become

# Установка драйвера на целевой хост (RHEL)
ansible postgres -m ansible.builtin.yum -a "name=python3-psycopg2 state=present" --become

# Установка драйвера на контроллер
pip install "psycopg[binary]"
```

### Проблема: PostgreSQL не подключается по сети

**Симптом:** `UNREACHABLE!` или `FATAL: no pg_hba.conf entry`.

**Решение:**
```bash
# Проверка доступности порта
ansible postgres_master -m ansible.builtin.wait_for -a "host={{ ansible_host }} port=5432 timeout=5"

# Проверка статуса сервиса
ansible postgres_master -m ansible.builtin.systemd -a "name=postgresql state=started enabled=yes" --become

# Проверка параметра listen_addresses
ansible postgres_master -m shell -a "sudo -u postgres psql -c 'SHOW listen_addresses;'"
# → listen_addresses
# → 0.0.0.0

# Проверка pg_hba.conf
ansible postgres_master -m shell -a "sudo -u postgres psql -c 'SELECT * FROM pg_hba_file_rules;'"
```

### Проблема: Репликация не стартует

**Симптом:** `FATAL: could not connect to replicator` или `could not receive data from WAL stream`.

**Решение:**
```bash
# Проверка pg_hba.conf на Master
ansible postgres_master -m shell -a "sudo -u postgres psql -c 'SELECT type, database, user_name, address, netmask, auth_method FROM pg_hba_file_rules;'"

# Проверка статуса репликации
ansible postgres_master -m shell -a "sudo -u postgres psql -c 'SELECT * FROM pg_stat_replication;'"

# Проверка размера WAL
ansible postgres_master -m shell -a "sudo -u postgres psql -c 'SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), '00000001/00000000')) AS wal_size;'"
```

### Проблема: Vault не расшифровывает переменные

**Симптом:** `ERROR! A Vault password is required` или `Decryption failed`.

**Решение:**
```bash
# Проверка зашифрованного файла
ansible-vault view group_vars/all/vault.yml --ask-vault-pass

# Проверка Vault ID в заголовке
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Запуск с правильным Vault ID
ansible-playbook site.yml --vault-id prod@.vault_pass
```

### Проблема: Задачи выполняются дважды (нарушение идемпотентности)

**Симптом:** Повторные запуски показывают `changed` там, где ожидается `ok`.

**Решение:**
```bash
# Проверка идемпотентности
ansible-playbook playbooks/site.yml --check --diff

# Второй запуск должен показать changed=0
ansible-playbook playbooks/site.yml 2>&1 | grep "changed="
# → localhost                  : ok=XX   changed=0    unreachable=0    failed=0
```

### Проблема: Обработчик не выполняется

**Симптом:** `notify: Restart PostgreSQL` не срабатывает при изменении конфигурации.

**Решение:**
```bash
# Проверка, что notify привязан к задаче
# В плейбуке:
# - name: Копирование конфигурации
#   ansible.builtin.template:
#     src: postgresql.conf.j2
#     dest: /etc/postgresql/16/main/postgresql.conf
#   notify: Restart PostgreSQL   # ← Должно быть на одном уровне с задачей

# Проверка обработчиков
ansible-playbook playbooks/site.yml --list-handlers

# Принудительный запуск обработчиков
ansible-playbook playbooks/site.yml --handlers-first
```

---

## Рекомендации

### Best Practices

1. **Храните секреты в Vault**: Никогда не коммитьте пароли в открытом виде. Используйте `ansible-vault` с защищенным хранилищем паролей.
2. **Используйте FQCN**: Всегда указывайте полные имена модулей (`community.postgresql.postgresql_db` вместо `postgresql_db`) для совместимости между версиями Ansible и коллекций.
3. **Настраивайте `no_log: true`** для задач с секретами. Это предотвращает утечку данных в логи CI/CD.
4. **Проверяйте идемпотентность**: Второй запуск плейбука не должен вносить изменения (`changed=0`). Это подтверждает корректность декларативного подхода.
5. **Используйте `block/rescue/always`** вместо `ignore_errors: true` для осмысленной обработки ошибок.
6. **Документируйте переменные** в `README.md` проекта или в `defaults/main.yml` роли с комментариями.
7. **Выносите логику в роли**: Для повторного использования настройка сервисов должна быть оформлена как роль. Подробнее: **[Структура роли Ansible](../Roles/structure.md)**.
8. **Настраивайте `ansible.cfg`** с разумными таймаутами и `ControlPersist` для ускорения повторных подключений.
9. **Используйте `--check --diff`** перед первым запуском в production. Это позволяет увидеть точные изменения без риска.
10. **Валидируйте конфигурацию**: Всегда проверяйте синтаксис YAML и плейбуков через `ansible-playbook --syntax-check` и `ansible-lint`.

### Безопасность

- **Управление секретами**: Для защиты конфиденциальных данных (пароли, TLS-ключи) всегда используйте шифрование. Подробнее: **[Основы Ansible Vault](../Vault/basics.md)**.
- **Аутентификация (`pg_hba.conf`)**: Для современных инсталляций рекомендуется использовать метод `scram-sha-256` вместо устаревшего `md5`. Убедитесь, что параметр `password_encryption` в `postgresql.conf` также установлен в `scram-sha-256`.
- **Минимизация привилегий**: Используйте `become_user: postgres` для задач управления БД, чтобы не выполнять команды от имени суперпользователя ОС (`root`) внутри СУБД.
- **SSL/TLS**: В production-средах обязательно использование SSL для подключений к PostgreSQL. Настройка параметров `ssl = on`, `ssl_cert_file`, `ssl_key_file` в `postgresql.conf` и `hostssl` в `pg_hba.conf`.
- **Логирование**: Настройте `log_destination = 'stderr'` и `logging_collector = on` для сохранения логов PostgreSQL.

### Производительность и стабильность

- **Connection Pooling**: Для высоконагруженных сред используйте **PgBouncer** или **Pgpool-II** для управления пулом подключений.
- **Тюнинг ядра**: Настройте `vm.swappiness = 10` и `vm.overcommit_memory = 2` через `ansible.posix.sysctl`.
- **Лимиты ресурсов**: Установите `nofile` не менее 65536 для пользователя `postgres` через `community.general.pam_limits`.
- **Мониторинг**: Включите расширение `pg_stat_statements` для анализа производительности запросов.
- **Check Mode**: Модули `postgresql_db`, `postgresql_user`, `postgresql_ext` поддерживают `check_mode`. Используйте `--check` для предварительной проверки изменений.

---

## Дополнительная информация

### Смотрите также

- [Репликация в PostgreSQL: Теория](../../Databases/PostgreSQL/Concepts/replication.md)
- [Отказоустойчивый кластер PostgreSQL (Patroni)](../../Databases/PostgreSQL/Operations/high_availability_patroni.md)
- [Оптимизация PostgreSQL (Performance Tuning)](../../Databases/PostgreSQL/Operations/performance_tuning.md)

### Именование и организации

- **Плейбуки:** Используйте префиксы `01_`, `02_` в `playbooks/` для визуализации порядка развертывания.
- **Переменные:** Всегда используйте префиксы ролей (например, `postgresql_port`), чтобы избежать конфликтов при слиянии переменных из разных источников.
- **Тегирование:** Используйте `tags` для избирательного выполнения задач (например, `tags: ['backup', 'maintenance']`).

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Несколько `ansible.cfg` | Конфликт настроек | Ansible использует ближайший `ansible.cfg` к плейбуку; не создавайте дубли. |
| Windows-контрольный узел | Некоторые модули не работают | Используйте WSL2 или Linux-контрольный узел. |
| Параллельный запуск | Файловые конфликты | Используйте `serial` в плейбуке или `forks` в `ansible.cfg`. |
| Vault и CI/CD | Пароль Vault недоступен | Передавайте через `ANSIBLE_VAULT_PASSWORD_FILE` env var. |
| Большие инвентари | Медленная загрузка | Используйте динамический инвентарь или `yaml` вместо `ini` формата. |
