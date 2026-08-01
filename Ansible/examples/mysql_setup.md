# Ansible: Установка и настройка MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — воспроизводимое развертывание и настройка сервера баз данных на различных операционных системах (Debian/Ubuntu, CentOS/RHEL/Rocky) без ручного вмешательства.

**FQCN (Fully Qualified Collection Name)** — полное имя коллекции и модуля (например, `ansible.mysql.mysql_user`), которое гарантирует вызов конкретного модуля и является современным стандартом Ansible.

**Идемпотентность** — возможность многократного безопасного запуска сценария без изменения состояния системы, если оно уже соответствует целевому.

**.my.cnf** — файл конфигурации клиента MySQL, используемый для хранения учетных данных (`user`, `password`). В Ansible применяется для обеспечения идемпотентности, позволяя модулям подключаться локально без передачи пароля в параметрах каждой задачи.

## Базовые концепции

### Зависимости и коллекции

С версии Ansible 2.10 модули MySQL вынесены в отдельную коллекцию. Рекомендуется использовать FQCN `ansible.mysql` (ранее `community.mysql`).

| Компонент | Где требуется | Назначение |
|---|---|---|
| `ansible.mysql` | Управляющий узел | Коллекция модулей для управления базами данных |
| `PyMySQL` | Целевой хост | Python-библиотека (драйвер) для работы модулей |
| `cryptography` | Целевой хост | Библиотека для поддержки `caching_sha2_password` |

Установка коллекции:
```bash
ansible-galaxy collection install ansible.mysql  # → коллекция установлена
```

### Аутентификация и современная безопасность

**Freshness Triggers (Актуальность на 2026 г.):**
- **MySQL 8.4 LTS / 9.0:** Плагин `mysql_native_password` удален. Используется `caching_sha2_password`.
- **MariaDB 11.4 LTS:** Поддерживает `caching_sha2_password` для совместимости, SSL/TLS включен по умолчанию для всех соединений.
- **Debian/Ubuntu:** Для `root` по умолчанию используется `auth_socket` (вход через sudo без пароля).

**Важные параметры модулей:**
- `login_unix_socket`: Обязателен для первичной настройки на Debian-системах.
- `check_implicit_admin`: Позволяет модулю попытаться войти без пароля, если обычный вход не удался (полезно при первом запуске).
- `update_password: on_create`: Критически важно для `caching_sha2_password`, так как плагин генерирует разные хеши для одного пароля, что может приводить к ложным срабатываниям `changed: true`.

---

## Практические сценарии

### Сценарий: Полный цикл развертывания БД

Сценарий включает установку зависимостей, настройку безопасности `root` и создание прикладной базы данных.

```yaml
---
- name: Развертывание и настройка MySQL/MariaDB
  hosts: db_servers
  become: true
  vars:
    mysql_root_password: "SafeRootPassword123" # Используйте Ansible Vault!
    app_db_name: "production_app"
    app_db_user: "app_worker"
    app_db_password: "StrongAppPassword"

  tasks:
    - name: Установка системных пакетов и зависимостей Python
      ansible.builtin.package:
        name:
          - "{{ 'mysql-server' if ansible_facts['os_family'] == 'Debian' else 'mariadb-server' }}"
          - python3-pymysql
          - python3-cryptography # Необходимо для caching_sha2_password
        state: present
        update_cache: yes

    - name: Запуск и включение службы БД
      ansible.builtin.service:
        name: "{{ 'mysql' if ansible_facts['os_family'] == 'Debian' else 'mariadb' }}"
        state: started
        enabled: yes

    - name: Первичная настройка пароля root
      ansible.mysql.mysql_user:
        name: root
        password: "{{ mysql_root_password }}"
        login_unix_socket: "{{ '/var/run/mysqld/mysqld.sock' if ansible_facts['os_family'] == 'Debian' else omit }}"
        check_implicit_admin: yes
        state: present
        update_password: on_create

    - name: Создание .my.cnf для идемпотентности root
      ansible.builtin.copy:
        content: |
          [client]
          user=root
          password="{{ mysql_root_password }}"
        dest: /root/.my.cnf
        owner: root
        group: root
        mode: '0400'

    - name: Удаление небезопасных настроек по умолчанию
      ansible.mysql.mysql_user:
        name: ""
        host_all: yes
        state: absent
      loop: ["localhost", "{{ ansible_facts['hostname'] }}", "127.0.0.1", "::1"]

    - name: Создание прикладной базы данных
      ansible.mysql.mysql_db:
        name: "{{ app_db_name }}"
        state: present

    - name: Создание пользователя приложения с правами доступа
      ansible.mysql.mysql_user:
        name: "{{ app_db_user }}"
        password: "{{ app_db_password }}"
        priv: "{{ app_db_name }}.*:ALL"
        state: present
        update_password: on_create
```

---

## Дополнительная информация

### Использование Module Defaults

Для сокращения кода при большом количестве задач можно использовать `module_defaults`, чтобы не указывать параметры подключения в каждой задаче:

```yaml
- name: Работа с БД
  hosts: all
  module_defaults:
    ansible.mysql.mysql_user:
      login_unix_socket: /var/run/mysqld/mysqld.sock
    ansible.mysql.mysql_db:
      login_unix_socket: /var/run/mysqld/mysqld.sock
  tasks:
    # ... задачи без указания сокета ...
```

### Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `Authentication plugin 'caching_sha2_password' is not supported` | Отсутствует `python3-cryptography` | Установите пакет `python3-cryptography` на целевой хост. |
| `Access denied for user 'root'@'localhost'` | Пароль уже изменен, а `.my.cnf` отсутствует | Проверьте наличие `/root/.my.cnf` или передайте `login_password`. |
| `ansible.mysql.mysql_user not found` | Коллекция не установлена | Выполните `ansible-galaxy collection install ansible.mysql`. |

### Безопасность

Никогда не храните пароли в открытом виде. Используйте **[Ansible Vault](../Vault/basics.md)** для шифрования переменных:

```bash
ansible-vault encrypt_string 'StrongPassword' --name 'mysql_root_password'
```

## Смотрите также

- [Ansible Vault: Работа с секретами](../Vault/basics.md)
- [Развертывание LEMP-стека через Ansible](tutorial_lemp_stack.md)
- [MySQL: Установка и базовая настройка (SSoT)](../../Databases/MySQL/installation.md)
- [Безопасная установка и закалка СУБД](../../Databases/installation_security.md)
