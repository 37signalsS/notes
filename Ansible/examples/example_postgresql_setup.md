# Развертывание и настройка PostgreSQL через Ansible

## Определения

**Автоматизация PostgreSQL с помощью Ansible** — процесс управления жизненным циклом базы данных (установка, конфигурация, репликация, миграции) с использованием декларативных плейбуков и специализированных модулей.

**community.postgresql** — основная коллекция Ansible, содержащая модули для управления всеми аспектами PostgreSQL (базы, пользователи, расширения, слоты репликации).

**Идемпотентность** — свойство плейбука, гарантирующее, что повторные запуски не приведут к изменениям, если система уже находится в целевом состоянии. Для PostgreSQL это критично при создании баз данных и управлении привилегиями.

## Базовые концепции

### Подходы к управлению

В экосистеме Ansible выделяют два основных метода:

1.  **Готовые роли (Ansible Galaxy)**: Использование проверенных сообществом ролей (например, `geerlingguy.postgresql`) для быстрой установки и базовой настройки ОС и сервера.
2.  **Модули коллекции `community.postgresql`**: Прямое использование модулей (`postgresql_db`, `postgresql_user`, `postgresql_query`) для тонкой настройки логики БД, особенно в рамках CI/CD пайплайнов.

### Зависимости и инструментарий

Для работы модулей требуется Python-библиотека для взаимодействия с PostgreSQL (`psycopg2`).

| Компонент | Где требуется | Назначение |
|---|---|---|
| `community.postgresql` | Управляющий узел | Коллекция модулей для управления PostgreSQL. |
| `psycopg2-binary` | Управляющий узел | Python-драйвер для локальных задач (например, `delegate_to: localhost`). |
| `python3-psycopg2` | Целевой хост | Системный пакет драйвера для выполнения модулей на сервере. |

Установка зависимостей:

```bash
ansible-galaxy collection install community.postgresql # → коллекция установлена
pip install psycopg2-binary # → драйвер на контроллере установлен
```

На целевых хостах рекомендуется устанавливать драйвер через пакетный менеджер ОС (например, `apt install python3-psycopg2`) перед вызовом модулей PostgreSQL.

---

## Практические сценарии

### Сценарий 1: Настройка репликации Master-Replica

Развертывание связки из основного узла (Master) и реплики (Replica) с использованием потоковой репликации.

**Теоретическая база:** Концептуальные основы и механизмы описаны в разделе **[Репликация в PostgreSQL](../../Databases/PostgreSQL/Concepts/replication.md)**.

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
    postgresql_users:
      - name: repluser
        password: "{{ vault_postgres_repl_password }}" # Из Ansible Vault
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

### Сценарий 2: Атомарная миграция схемы с откатом

Выполнение изменений структуры базы данных (БД) с использованием SQL-скриптов и механизмов обработки ошибок (`block`/`rescue`).

**Теоретическая база:** Стратегии управления структурой описаны в разделе **[Миграция схем баз данных](../../Databases/PostgreSQL/Concepts/schema_migrations.md)**.

#### Плейбук миграции

```yaml
---
- name: Управление базой данных и миграциями
  hosts: postgres_master
  become: true
  vars:
    db_name: "prod_app_db"
    db_user: "app_user"

  tasks:
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
          # Все команды внутри одного postgresql_query выполняются в транзакции.
```

---

## Дополнительная информация

### Безопасность

Для защиты конфиденциальных данных (пароли, TLS-ключи) всегда используйте шифрование:
- **[Основы Ansible Vault](../Vault/basics.md)** — руководство по работе с секретами.

### Мониторинг

Для настройки сбора метрик PostgreSQL в Prometheus используйте специализированный экспортер:
- **[Мониторинг PostgreSQL](./postgresql_prometheus_monitoring.md)**.

## Смотрите также

- [Репликация в PostgreSQL: Теория](../../Databases/PostgreSQL/Concepts/replication.md)
- [Установка и настройка MySQL через Ansible](mysql_setup.md)
- [Работа с коллекциями в Ansible Galaxy](../Roles/galaxy.md)
