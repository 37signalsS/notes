# Развертывание и настройка PostgreSQL через Ansible

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — систематический процесс управления жизненным циклом СУБД (установка, конфигурация, репликация, миграции, бэкапы) с использованием декларативных плейбуков и специализированных модулей.

**community.postgresql** — основная коллекция Ansible, содержащая модули для управления всеми аспектами PostgreSQL (базы, пользователи, расширения, слоты репликации, параметры конфигурации).

**Идемпотентность** — свойство плейбука, гарантирующее, что повторные запуски не приведут к изменениям, если система уже находится в целевом состоянии. Для PostgreSQL это критично при создании баз данных, управлении привилегиями и выполнении DDL-запросов.

## Базовые концепции

### Подходы к управлению

В экосистеме Ansible выделяют два дополняющих друг друга метода:

1.  **Готовые роли (Ansible Galaxy)**: Использование проверенных сообществом ролей (например, `geerlingguy.postgresql` или `triumftech.postgresql`) для быстрой установки бинарных файлов, базовой настройки ОС, конфигурации `postgresql.conf` и `pg_hba.conf`.
2.  **Модули коллекции `community.postgresql`**: Прямое использование специализированных модулей (`postgresql_db`, `postgresql_user`, `postgresql_query`, `postgresql_ext`) для тонкой настройки логики БД, управления объектами и выполнения миграций.

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

---

## Дополнительная информация

### Безопасность и управление доступом

- **Управление секретами**: Для защиты конфиденциальных данных (пароли, TLS-ключи) всегда используйте шифрование. Подробнее: **[Основы Ansible Vault](../Vault/basics.md)**.
- **Аутентификация (`pg_hba.conf`)**: Для современных инсталляций рекомендуется использовать метод `scram-sha-256` вместо устаревшего `md5`. Убедитесь, что параметр `password_encryption` в `postgresql.conf` также установлен в `scram-sha-256`.
- **Минимизация привилегий**: Используйте `become_user: postgres` для задач управления БД, чтобы не выполнять команды от имени суперпользователя ОС (`root`) внутри СУБД.

### Мониторинг

Для настройки сбора метрик PostgreSQL в Prometheus используйте специализированный экспортер:
- **[Мониторинг PostgreSQL с помощью Prometheus и Ansible](./postgresql_prometheus_monitoring.md)**.
- Рекомендуется включение расширения `pg_stat_statements` для анализа производительности запросов.

## Смотрите также

- [Репликация в PostgreSQL: Теория](../../Databases/PostgreSQL/Concepts/replication.md)
- [Отказоустойчивый кластер PostgreSQL (Patroni)](../../Databases/PostgreSQL/Operations/high_availability_patroni.md)
- [Оптимизация PostgreSQL (Performance Tuning)](../../Databases/PostgreSQL/Operations/performance_tuning.md)
- [Работа с коллекциями в Ansible Galaxy](../Roles/galaxy.md)
