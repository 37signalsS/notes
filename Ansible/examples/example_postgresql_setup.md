# Ansible: Примеры установки и настройки PostgreSQL

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — это процесс использования плейбуков для управления полным жизненным циклом экземпляров PostgreSQL, включая установку, настройку репликации, выполнение миграций схемы базы данных и обеспечение отказоустойчивости.

## Базовые концепции

В экосистеме Ansible для управления PostgreSQL используются два основных подхода, которые можно комбинировать:

1.  **Использование готовых ролей из Ansible Galaxy**: Для сложных, стандартизированных задач, таких как настройка потоковой репликации, рекомендуется использовать проверенные сообществом роли (например, `geerlingguy.postgresql`). Это экономит время и обеспечивает доступ к большому набору функций "из коробки".

2.  **Использование встроенных модулей `community.postgresql`**: Для гранулярного контроля и выполнения кастомных SQL-запросов (например, при миграции схемы) используются специализированные модули, такие как `postgresql_db`, `postgresql_user`, `postgresql_query`. В сочетании с конструкциями `block`/`rescue` они позволяют создавать надежные и атомарные операции.

## Практические сценарии

### Сценарий 1: Настройка Master-Replica с использованием роли

Этот пример демонстрирует, как развернуть PostgreSQL master и slave (replica), используя популярную роль `geerlingguy.postgresql`.

*   **Теоретическая база:** Подробное описание концепций потоковой репликации доступно в документе **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)**.

#### Файл инвентаря `hosts.ini`
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
        pass: 'your_strong_password' # Используйте Vault!
        replication: true
  roles:
    - geerlingguy.postgresql

- name: Setup PostgreSQL Replica
  hosts: postgres_slave
  become: true
  vars:
    postgresql_replication_role: 'replica'
    postgresql_master_host: '192.168.51.2' # IP мастера
    postgresql_replication_user:
      name: repluser
      pass: 'your_strong_password' # Используйте Vault!
  roles:
    - geerlingguy.postgresql
```

### Сценарий 2: Атомарная миграция схемы с откатом

Этот пример показывает, как выполнить SQL-скрипт для создания и наполнения таблицы, обеспечив автоматический откат в случае сбоя.

*   **Теоретическая база:** Подходы к изменению структуры БД описаны в документе **[Миграция схем баз данных](../../Databases/PostgreSQL/Concepts/schema_migrations.md)**.

#### Плейбук для миграции
```yaml
---
- name: Install PostgreSQL and Run Migrations
  hosts: postgres_master # Целевой хост, где установлен PostgreSQL
  become: true
  vars:
    db_name: "namesdb"
    db_user: "your_user" # Замените на вашего пользователя

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
Конструкция `block`/`rescue` гарантирует, что если любая задача внутри `block` завершится неудачно, Ansible выполнит задачи из секции `rescue` для отката изменений.

## Дополнительная информация

### Предварительные требования

Для работы приведенных примеров необходимо установить зависимости на **управляющем узле** (где запускается `ansible-playbook`):

1.  **Роль `geerlingguy.postgresql`**:
    ```bash
    ansible-galaxy install geerlingguy.postgresql
    ```
2.  **Коллекция `community.postgresql`**:
    ```bash
    ansible-galaxy collection install community.postgresql
    ```
3.  **Python-библиотека `psycopg2`**:
    ```bash
    pip install psycopg2-binary
    ```