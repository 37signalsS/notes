# Ansible: автоматизация установки и настройки MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — декларативное описание и воспроизводимое развертывание серверов баз данных на различных ОС (Debian, Ubuntu, RHEL, Rocky) с использованием модулей Ansible, что исключает ошибки ручного ввода.

**FQCN (Fully Qualified Collection Name)** — полное имя коллекции и модуля (например, `ansible.mysql.mysql_user`), являющееся стандартом Ansible 2.10+. Гарантирует вызов нужного модуля и предотвращает конфликты имен.

**Идемпотентность** — свойство задач Ansible сохранять целевое состояние системы при многократных запусках. Если база данных уже создана, повторный запуск модуля `mysql_db` не приведет к изменениям или ошибкам.

**.my.cnf** — файл конфигурации клиента (обычно в `/root/`), хранящий учетные данные (`user`, `password`). Используется модулями Ansible для локального подключения без передачи пароля в открытом виде через аргументы командной строки.

## Базовые концепции

### Зависимости и коллекции

С версии Ansible 2.10 модули для работы с базами данных вынесены в коллекцию `ansible.mysql` (ранее `community.mysql`). Для работы модулей требуется наличие специфических Python-библиотек на целевом хосте.

| Компонент | Где требуется | Назначение |
|---|---|---|
| `ansible.mysql` | Управляющий узел | Коллекция модулей для управления БД, пользователями и репликацией. |
| `PyMySQL` | Целевой хост | Основной Python-драйвер для взаимодействия модулей с MySQL/MariaDB. |
| `cryptography` | Целевой хост | Библиотека для поддержки плагина `caching_sha2_password` (MySQL 8.0+). |

Установка коллекции:
```bash
ansible-galaxy collection install ansible.mysql
```

### Аутентификация и современная безопасность

**Актуальность на 2026 год (Freshness Triggers):**
- **MySQL 8.4 LTS / 9.0:** Плагин `mysql_native_password` полностью удален в версии 9.0. Стандартом является `caching_sha2_password`.
- **MariaDB 12.3 LTS:** Поддерживает `caching_sha2_password` для совместимости. SSL/TLS рекомендуется включать по умолчанию для всех внешних соединений.
- **Debian/Ubuntu:** Для пользователя `root` по умолчанию применяется `auth_socket` (вход через sudo без пароля).

**Важные параметры модулей:**
- `login_unix_socket`: Обязателен для первичной настройки на Debian-системах, где root использует сокет.
- `check_implicit_admin`: Позволяет модулю войти без пароля, если обычный вход не удался (полезно при первом запуске после установки).
- `update_password: on_create`: Критически важно для плагина `caching_sha2_password`. Поскольку плагин генерирует разные хеши для одного пароля, этот параметр предотвращает ложные срабатывания `changed: true` при каждом запуске.

---

## Практические сценарии

### Сценарий 1: Полный цикл развертывания и закалки БД

Сценарий охватывает установку сервера, настройку безопасности и создание прикладной базы данных.

```yaml
---
- name: Развертывание и настройка MySQL/MariaDB
  hosts: db_servers
  become: true
  vars:
    # Используйте Ansible Vault для шифрования!
    mysql_root_password: "{{ vaulted_mysql_root_password }}"
    app_db_name: "production_app"
    app_db_user: "app_worker"
    app_db_password: "{{ vaulted_app_db_password }}"

  tasks:
    - name: Установка системных пакетов и зависимостей Python
      ansible.builtin.package:
        name:
          - "{{ 'mysql-server' if ansible_facts['os_family'] == 'Debian' else 'mariadb-server' }}"
          - python3-pymysql
          - python3-cryptography
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
        encoding: utf8mb4
        collation: utf8mb4_unicode_ci
        state: present

    - name: Создание пользователя приложения с правами доступа
      ansible.mysql.mysql_user:
        name: "{{ app_db_user }}"
        password: "{{ app_db_password }}"
        priv: "{{ app_db_name }}.*:ALL"
        state: present
        update_password: on_create
```

### Сценарий 2: Настройка SSL/TLS и ограничение доступа

В современных инфраструктурах (2026+) шифрование трафика является обязательным.

```yaml
- name: Настройка обязательного SSL для подключений
  ansible.builtin.blockinfile:
    path: /etc/mysql/mariadb.conf.d/50-server.cnf # Путь зависит от дистрибутива
    block: |
      [mysqld]
      ssl-ca=/etc/mysql/ssl/ca-cert.pem
      ssl-cert=/etc/mysql/ssl/server-cert.pem
      ssl-key=/etc/mysql/ssl/server-key.pem
      require_secure_transport=ON
  notify: Restart Database Service

- name: Требование SSL для пользователя приложения
  ansible.mysql.mysql_user:
    name: "{{ app_db_user }}"
    requires_ssl: yes
    state: present
```

### Сценарий 3: Управление сетевым доступом (Firewall)

```yaml
- name: Открытие порта 3306 через UFW (Ubuntu/Debian)
  community.general.ufw:
    rule: allow
    port: 3306
    proto: tcp
    from_ip: "{{ trusted_network_range }}"
  when: ansible_facts['os_family'] == 'Debian'

- name: Открытие порта 3306 через Firewalld (RHEL/Rocky)
  ansible.posix.firewalld:
    port: 3306/tcp
    permanent: yes
    state: enabled
    immediate: yes
  when: ansible_facts['os_family'] == 'RedHat'
```

---

## Дополнительная информация

### Использование Module Defaults

Для сокращения кода при большом количестве задач можно использовать `module_defaults`, чтобы не указывать параметры подключения (`login_user`, `login_password`, `login_unix_socket`) в каждой задаче:

```yaml
- name: Работа с БД
  hosts: all
  module_defaults:
    ansible.mysql.mysql_user:
      login_unix_socket: /var/run/mysqld/mysqld.sock
    ansible.mysql.mysql_db:
      login_unix_socket: /var/run/mysqld/mysqld.sock
  tasks:
    # Задачи выполняются с использованием сокета без явного указания
    - name: Создание базы данных
      ansible.mysql.mysql_db:
        name: staging_db
        state: present
```

### Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `Authentication plugin 'caching_sha2_password' is not supported` | Отсутствует `python3-cryptography` на целевом хосте. | Установите пакет `python3-cryptography`. |
| `Access denied for user 'root'@'localhost'` | Пароль уже изменен, а файл `.my.cnf` отсутствует или содержит неверные данные. | Проверьте наличие `/root/.my.cnf` или передайте `login_password` явно. |
| `ansible.mysql.mysql_user not found` | Коллекция не установлена на управляющем узле. | Выполните `ansible-galaxy collection install ansible.mysql`. |
| `Changed: true` на каждом прогоне | Использование `caching_sha2_password` без `update_password: on_create`. | Добавьте параметр `update_password: on_create` в модуль `mysql_user`. |

### Безопасность

Никогда не храните пароли в открытом виде. Используйте **[Ansible Vault](../Vault/basics.md)** для шифрования переменных:

```bash
ansible-vault encrypt_string 'StrongPassword2026!' --name 'mysql_root_password'
```

**Рекомендации:**
1. Не используйте `bind-address = 0.0.0.0` без настроенного Firewall.
2. Ограничивайте права пользователей (`priv`) только необходимыми таблицами и действиями.
3. Всегда используйте `FQCN` для надежности плейбуков.

## Смотрите также

- **[Ansible Vault: работа с секретами](../Vault/basics.md)**
- **[Развертывание LEMP-стека через Ansible](tutorial_lemp_stack.md)**
- **[MySQL: установка и базовая настройка (SSoT)](../../Databases/MySQL/installation.md)**
- **[MariaDB: установка и настройка (SSoT)](../../Databases/MariaDB/installation_and_setup.md)**
- **[Безопасная установка и закалка СУБД](../../Databases/installation_security.md)**
