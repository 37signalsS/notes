# Ansible: Установка и настройка PostgreSQL

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — использование плейбуков для управления жизненным циклом PostgreSQL: установка, настройка репликации, миграции схемы, обеспечение отказоустойчивости.

**SQL (Structured Query Language)** — язык структурированных запросов, используемый для взаимодействия с базой данных.

## Базовые концепции

### Подходы к управлению PostgreSQL

В экосистеме Ansible выделяют два основных подхода:

1. **Готовые роли из Ansible Galaxy** — использование проверенных сообществом решений для стандартизированных задач (например, `geerlingguy.postgresql`). Это значительно экономит время при развертывании типовых конфигураций.
2. **Модули коллекции `community.postgresql`** — применение специализированных модулей (`postgresql_db`, `postgresql_user`, `postgresql_query`) для гранулярного контроля. В сочетании с конструкциями `block`/`rescue` это обеспечивает атомарность сложных операций.

### Зависимости управляющего узла

Для работы с PostgreSQL необходимо подготовить окружение на контрольной машине:

```bash
# Роль для установки PostgreSQL
ansible-galaxy install geerlingguy.postgresql

# Коллекция модулей community.postgresql
ansible-galaxy collection install community.postgresql

# Python-библиотека для взаимодействия с PostgreSQL (psycopg2)
pip install psycopg2-binary
```

---

## Практические сценарии

### Сценарий 1: Настройка Master-Replica с использованием роли

Развертывание связки из основного узла (master) и реплики (replica) с использованием потоковой репликации.

**Теоретическая база:** Концептуальные основы и механизмы репликации подробно описаны в разделе **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)**.

#### Инвентарь `hosts.ini`

```ini
[postgres_master]
server_postgres_master ansible_host=192.168.51.2

[postgres_slave]
server_postgres_slave ansible_host=192.168.51.3

[postgres:children]
postgres_master
postgres_slave
```

#### Плейбук `postgres-playbook.yml`

```yaml
---
- name: Setup PostgreSQL Master
  hosts: postgres_master
  become: true
  vars:
    postgresql_replication_role: 'master'
    postgresql_replication_slots:
      - 'replica1_slot'
    postgresql_users:
      - name: repluser
        pass: 'your_strong_password' # Обязательно используйте Ansible Vault!
        replication: true
  roles:
    - geerlingguy.postgresql

- name: Setup PostgreSQL Replica
  hosts: postgres_slave
  become: true
  vars:
    postgresql_replication_role: 'replica'
    postgresql_master_host: '192.168.51.2'
    postgresql_replication_user:
      name: repluser
      pass: 'your_strong_password' # Обязательно используйте Ansible Vault!
  roles:
    - geerlingguy.postgresql
```

### Сценарий 2: Атомарная миграция схемы с откатом

Выполнение миграции базы данных (БД) с использованием SQL-скриптов и механизмов обработки ошибок в Ansible.

**Теоретическая база:** Стратегии и лучшие практики изменения структуры базы данных описаны в разделе **[Миграция схем баз данных](../../Databases/PostgreSQL/Concepts/schema_migrations.md)**.

#### Плейбук миграции

```yaml
---
- name: Manage PostgreSQL Database and Migrations
  hosts: postgres_master
  become: true
  vars:
    db_name: "namesdb"
    db_user: "your_user"

  pre_tasks:
    - name: Ensure database exists
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        state: present
      become_user: postgres

  tasks:
    - name: Run migrations within a block for error handling
      block:
        - name: Create employees table
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: |
              CREATE TABLE employees (
                  id serial NOT NULL PRIMARY KEY,
                  name text,
                  license_plate text
              );
              ALTER TABLE employees OWNER TO "{{ db_user }}";
              CREATE UNIQUE INDEX employees_id_uindex ON employees (id);
          become_user: postgres

        - name: Insert initial data
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: |
              INSERT INTO public.employees (name, license_plate) VALUES ('John B.', 'DB124GR');
              INSERT INTO public.employees (name, license_plate) VALUES ('Jill O.', 'VG645PH');
          become_user: postgres

      rescue:
        - name: Rollback changes on failure
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: "DROP TABLE IF EXISTS employees;"
          become_user: postgres
```

---

## Дополнительная информация

### Безопасность

Для защиты конфиденциальной информации (пароли, ключи доступа) всегда применяйте механизмы шифрования:
- **[Основы Ansible Vault](../Vault/basics.md)** — руководство по работе с зашифрованными переменными.

### Мониторинг и наблюдаемость

Для настройки комплексного мониторинга базы данных с использованием Prometheus и специализированных экспортеров обратитесь к руководству:
- **[Мониторинг PostgreSQL с Prometheus](./postgresql_prometheus_monitoring.md)**.

### Смежные документы

- **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)** — теоретические основы репликации.
- **[Миграция схем баз данных](../../Databases/PostgreSQL/Concepts/schema_migrations.md)** — стратегии управления изменениями в БД.
- **[Роли Ansible Galaxy](../Roles/galaxy.md)** — управление внешними зависимостями проекта.
