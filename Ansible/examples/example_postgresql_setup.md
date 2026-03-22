# Ansible: Примеры установки и настройки PostgreSQL

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — использование плейбуков для управления жизненным циклом PostgreSQL: установка, настройка репликации, миграции схемы, обеспечение отказоустойчивости.

## Базовые концепции

Подходы к управлению PostgreSQL в Ansible:

1. **Готовые роли из Ansible Galaxy** — для стандартизированных задач (например, `geerlingguy.postgresql`). Экономит время, предоставляет проверенные решения.
2. **Модули `community.postgresql`** — для гранулярного контроля и кастомных SQL-запросов (`postgresql_db`, `postgresql_user`, `postgresql_query`). В сочетании с `block`/`rescue` обеспечивают атомарность операций.

**Зависимости для управляющего узла:**

```bash
# Роль для установки PostgreSQL
ansible-galaxy install geerlingguy.postgresql

# Коллекция модулей community.postgresql
ansible-galaxy collection install community.postgresql

# Python-библиотека для работы с PostgreSQL
pip install psycopg2-binary
```

## Практические сценарии

### Сценарий 1: Настройка Master-Replica с использованием роли

Развертывание PostgreSQL master и replica с потоковой репликацией через роль `geerlingguy.postgresql`.

**Теоретическая база:** Концепции репликации описаны в **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)**.

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
        pass: 'your_strong_password' # Используйте Ansible Vault!
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
      pass: 'your_strong_password' # Используйте Ansible Vault!
  roles:
    - geerlingguy.postgresql
```

### Сценарий 2: Атомарная миграция схемы с откатом

Выполнение SQL-скрипта миграции с автоматическим откатом при ошибке через конструкцию `block`/`rescue`.

**Теоретическая база:** Стратегии миграции описаны в **[Миграция схем баз данных](../../Databases/PostgreSQL/Concepts/schema_migrations.md)**.

#### Плейбук миграции

```yaml
---
- name: Install PostgreSQL and Run Migrations
  hosts: postgres_master
  become: true
  vars:
    db_name: "namesdb"
    db_user: "your_user"

  pre_tasks:
    - name: "Ensure database '{{ db_name }}' exists"
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        state: present
      become_user: postgres

  tasks:
    - name: "Run migrations with rollback on failure"
      block:
        - name: "Create employees table"
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

        - name: "Insert data into employees table"
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: |
              INSERT INTO public.employees (name, license_plate) VALUES ('John B.', 'DB124GR');
              INSERT INTO public.employees (name, license_plate) VALUES ('Jill O.', 'VG645PH');
              -- Пример ошибочного запроса для теста rescue
              -- INSERT INTO non_existent_table VALUES (1);
          become_user: postgres

      rescue:
        - name: "Rollback: Drop employees table on failure"
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: "DROP TABLE IF EXISTS employees;"
          become_user: postgres
```

Конструкция `block`/`rescue` выполняет задачи из секции `rescue` при ошибке любой задачи в `block`.

## Дополнительная информация

### Безопасность

- Пароли и чувствительные данные храните в **Ansible Vault** ([Ansible Vault basics](../Vault/basics.md))
- Используйте переменные окружения или vault для передачи секретов

### Мониторинг

Пример развертывания мониторинга PostgreSQL с Prometheus и `postgres_exporter` описан в **[Мониторинг PostgreSQL с Prometheus](./postgresql_prometheus_monitoring.md)**.

### Смежные документы

- **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)** — теория репликации (SSoT)
- **[Миграция схем баз данных](../../Databases/PostgreSQL/Concepts/schema_migrations.md)** — стратегии миграций (SSoT)
- **[Роли Ansible Galaxy](../Roles/galaxy.md)** — управление зависимостями (SSoT)
