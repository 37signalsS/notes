# Установка и настройка PostgreSQL с помощью Ansible

В этом руководстве рассматривается использование Ansible для автоматизации установки и настройки кластера PostgreSQL в конфигурации master-replica, а также для выполнения миграций базы данных.

## Пример: Master-Replica с использованием роли `geerlingguy.postgresql`

Этот плейбук демонстрирует, как развернуть PostgreSQL master и slave (replica), используя популярную роль из Ansible Galaxy.

### Файл инвентаря `hosts.ini`

```ini
[postgres_master]
server_postgres_master ansible_host=192.168.51.2

[postgres_slave]
server_postgres_slave ansible_host=192.168.51.3

[postgres:children]
postgres_master
postgres_slave
```

### Плейбук `postgres-playbook.yml`

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
        pass: 'your_strong_password'
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
      pass: 'your_strong_password'
  roles:
    - geerlingguy.postgresql
```

**Примечание:** Этот плейбук предполагает, что роль `geerlingguy.postgresql` уже установлена через `ansible-galaxy`.

---

## Упражнение: Миграция базы данных с откатом

Это практическое задание демонстрирует, как написать плейбук, который устанавливает PostgreSQL, создает базу данных и применяет SQL-миграции. Важным условием является наличие блока `rescue` для отката изменений в случае ошибки.

### Задача

1.  Использовать роль `geerlingguy.postgresql` для установки PostgreSQL 13.
2.  Создать новую базу данных с именем `namesdb`.
3.  Выполнить SQL-скрипт для создания таблицы и вставки данных.
4.  Если на любом этапе после создания таблицы происходит сбой, плейбук должен удалить созданную таблицу (`rescue` блок), чтобы восстановить исходное состояние.

### Плейбук для миграции

```yaml
---
- name: Install PostgreSQL and Run Migrations
  hosts: postgres_master # Целевой хост, где установлен PostgreSQL
  become: true
  vars:
    db_name: "namesdb"
    db_user: "your_user" # Замените на вашего пользователя

  roles:
    - geerlingguy.postgresql

  tasks:
    - name: "Ensure database '{{ db_name }}' exists"
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        state: present
      become_user: postgres

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
              INSERT INTO public.employees (name, license_plate) VALUES ('Phil K.', '6632266');
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

Этот плейбук использует `block` и `rescue` для обеспечения атомарности операции миграции. Если любая задача внутри `block` завершается неудачно, Ansible выполняет задачи из секции `rescue` для отката.
