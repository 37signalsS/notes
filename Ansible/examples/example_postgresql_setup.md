# Развертывание и настройка PostgreSQL через Ansible

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — систематический процесс управления жизненным циклом СУБД (установка, конфигурация, репликация, миграции, бэкапы) с использованием декларативных плейбуков и специализированных модулей.

**community.postgresql** — основная коллекция Ansible, содержащая модули для управления всеми аспектами PostgreSQL (базы, пользователи, расширения, слоты репликации, параметры конфигурации). Актуальная версия коллекции — **v4.2.0+** (2026 год), поддерживающая PostgreSQL 13–18.

**Идемпотентность** — свойство плейбука, гарантирующее, что повторные запуски не приведут к изменениям, если система уже находится в целевом состоянии. Для PostgreSQL это критично при создании баз данных, управлении привилегиями и выполнении DDL-запросов. Модули `postgresql_db`, `postgresql_user`, `postgresql_ext` поддерживают идемпотентность через параметр `state` (`present`/`absent`).

**Транзакционный DDL** — особенность PostgreSQL, позволяющая выполнять DDL-команды (`CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`) внутри транзакций. В сочетании с модулем `postgresql_query` это обеспечивает атомарность миграций: при ошибке все изменения откатываются.

## Базовые концепции

### Подходы к управлению

В экосистеме Ansible выделяют два дополняющих друг друга метода:

1.  **Готовые роли (Ansible Galaxy)**: Использование проверенных сообществом ролей (например, `geerlingguy.postgresql` или `triumftech.postgresql`) для быстрой установки бинарных файлов, базовой настройки ОС, конфигурации `postgresql.conf` и `pg_hba.conf`. Роль `geerlingguy.postgresql` поддерживает параметры репликации (`postgresql_replication_role`, `postgresql_replication_slots`) и управления пользователями (`postgresql_users`).
2.  **Модули коллекции `community.postgresql`**: Прямое использование специализированных модулей (`postgresql_db`, `postgresql_user`, `postgresql_query`, `postgresql_ext`) для тонкой настройки логики БД, управления объектами и выполнения миграций. Этот подход обеспечивает максимальный контроль, но требует ручной настройки серверных компонентов.

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
# → Результат: Installing 'community.postgresql' ...

pip install "psycopg[binary]" # Рекомендуется для новых версий
```

На целевых хостах драйвер устанавливается через пакетный менеджер ОС (`ansible.builtin.apt` или `ansible.builtin.yum`) перед вызовом модулей PostgreSQL.

**Важно:** Модули `postgresql_*` ищут драйвер в определенном порядке. Если на хосте установлены оба драйвера (`psycopg2` и `psycopg`), Ansible выберет `psycopg` (v3) как предпочтительный. Для явного указания используйте параметр `db_driver`.

### Ключевые параметры PostgreSQL

При автоматизации конфигурации через Ansible важно понимать основные параметры `postgresql.conf`, влияющие на безопасность и производительность:

| Параметр | Описание | Рекомендация |
|---|---|---|
| `listen_addresses` | IP-адреса для接受 подключений. | `'*'` для всех интерфейсов или конкретный IP для приватных сетей. |
| `port` | Порт PostgreSQL. | По умолчанию `5432`. Изменяйте только при конфликтах. |
| `max_connections` | Максимальное количество подключений. | Зависит от RAM: ~200-500 для средних серверов. Используйте PgBouncer для connection pooling. |
| `shared_buffers` | Размер общего буфера кэша. | 25% от оперативной памяти (например, 4GB для 16GB RAM). |
| `work_mem` | Память для сортировки и хэширования на операцию. | 4-16MB. Увеличение повышает производительность сложных запросов, но увеличивает потребление памяти. |
| `maintenance_work_mem` | Память для операций обслуживания (VACUUM, CREATE INDEX). | 512MB-1GB. Ускоряет индексацию и очистку. |
| `wal_level` | Уровень логирования WAL. | `replica` для репликации, `logical` для логической репликации. |
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

# SSL-подключения для внешних клиентов
hostssl all             all             0.0.0.0/0               scram-sha-256
```

---

## Предварительные требования

### Версии и совместимость

- **Ansible**: 2.12 или выше (рекомендуется 2.15+ для полной поддержки всех модулей коллекции).
- **PostgreSQL**: 13, 14, 15, 16, 17 или 18. Коллекция `community.postgresql` v4.2.0+ поддерживает все перечисленные версии.
- **Python на целевых хостах**: 3.7 или выше.
- **ОС**: Debian 11/12, Ubuntu 20.04/22.04/24.04, RHEL/CentOS 8/9, AlmaLinux 9.

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
├── group_vars/
│   └── all/
│       └── vault.yml          # Зашифрованные секреты
└── requirements.yml           # Зависимости (collections, roles)
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
    # Настройка pg_hba.conf для разрешения подключения реплики
    postgresql_hba_entries:
      - { type: local, database: all, user: postgres, auth_method: peer }
      - { type: host, database: all, user: all, address: '127.0.0.1/32', auth_method: scram-sha-256 }
      - { type: host, database: replication, user: repluser, address: '192.168.51.3/32', auth_method: scram-sha-256 }
    postgresql_users:
      - name: repluser
        password: "{{ vault_postgres_repl_password }}" # Пароль из Ansible Vault
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

**Лучшие практики:**
- Используйте `no_log: true` в задачах с секретами (пароли).
- Тестируйте плейбуки в staging-окружении перед продакшеном.
- Для критичных миграций добавьте `tags: ['migrate']` для избирательного выполнения.

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
# → -rw------- 1 postgres postgres 12345 ... prod_app_db_2026-08-26.sql.gz

# Проверка размера дампа
ansible postgres_master -m shell -a "du -sh /var/backups/postgres/{{ db_name }}_{{ ansible_date_time.date }}.sql.gz"
# → 15M /var/backups/postgres/prod_app_db_2026-08-26.sql.gz

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
- Храните бэкапы на удаленных носителях (S3, NFS, tape).
- Регулярно тестируйте восстановление из бэкапов.
- Для физических бэкапов (PITR) используйте **[pgBackRest](../../Databases/PostgreSQL/Concepts/backup_and_recovery.md)**.

---

## Дополнительная информация

### Безопасность и управление доступом

- **Управление секретами**: Для защиты конфиденциальных данных (пароли, TLS-ключи) всегда используйте шифрование. Подробнее: **[Основы Ansible Vault](../Vault/basics.md)**.
- **Аутентификация (`pg_hba.conf`)**: Для современных инсталляций рекомендуется использовать метод `scram-sha-256` вместо устаревшего `md5`. Убедитесь, что параметр `password_encryption` в `postgresql.conf` также установлен в `scram-sha-256`.
- **Минимизация привилегий**: Используйте `become_user: postgres` для задач управления БД, чтобы не выполнять команды от имени суперпользователя ОС (`root`) внутри СУБД.
- **SSL/TLS**: В production-средах обязательно использование SSL для подключений к PostgreSQL. Настройка параметров `ssl = on`, `ssl_cert_file`, `ssl_key_file` в `postgresql.conf` и `hostssl` в `pg_hba.conf`.

### Мониторинг

Для настройки сбора метрик PostgreSQL в Prometheus используйте специализированный экспортер:
- **[Мониторинг PostgreSQL с помощью Prometheus и Ansible](./postgresql_prometheus_monitoring.md)**.
- Рекомендуется включение расширения `pg_stat_statements` для анализа производительности запросов.

### Общие рекомендации

- **Тегирование**: Используйте `tags` для избирательного выполнения задач (например, `tags: ['backup', 'maintenance']`).
- **Check Mode**: Модули `postgresql_db`, `postgresql_user`, `postgresql_ext` поддерживают `check_mode`. Используйте `--check` для предварительной проверки изменений.
- **Diff Mode**: Модули не поддерживают `diff_mode`, но вы можете включить логирование изменений через `ansible.builtin.debug`.
- **Обработчики (Handlers)**: Для перезапуска PostgreSQL после изменения конфигурации используйте `notify` и `handlers`.
- **Connection Pooling**: Для высоконагруженных сред используйте **PgBouncer** или **Pgpool-II** для управления пулом подключений.
- **Логирование**: Настройте `log_destination = 'stderr'` и `logging_collector = on` для сохранения логов PostgreSQL.

### Обработка ошибок

Ansible предоставляет несколько механизмов обработки ошибок в плейбуках:

```yaml
- name: Пример обработки ошибок
  block:
    - name: Критическая задача
      community.postgresql.postgresql_query:
        db: "{{ db_name }}"
        query: "SELECT 1 FROM pg_stat_activity WHERE state = 'active';"
      register: result

  rescue:
    - name: Действия при ошибке
      ansible.builtin.debug:
        msg: "Ошибка: {{ result.msg }}"

  always:
    - name: Действия всегда (независимо от результата)
      ansible.builtin.debug:
        msg: "Задача завершена"
```

### Тестирование плейбуков

Перед запуском в production:

1. **Syntax Check**: `ansible-playbook playbook.yml --syntax-check`
2. **Check Mode**: `ansible-playbook playbook.yml --check --diff`
3. **Тестовый инвентарь**: Используйте отдельный inventory для staging.
4. **Verbose Mode**: `ansible-playbook playbook.yml -vvv` для детальной отладки.

---

## Смотрите также

- [Репликация в PostgreSQL: Теория](../../Databases/PostgreSQL/Concepts/replication.md)
- [Отказоустойчивый кластер PostgreSQL (Patroni)](../../Databases/PostgreSQL/Operations/high_availability_patroni.md)
- [Оптимизация PostgreSQL (Performance Tuning)](../../Databases/PostgreSQL/Operations/performance_tuning.md)
- [Работа с коллекциями в Ansible Galaxy](../Roles/galaxy.md)
