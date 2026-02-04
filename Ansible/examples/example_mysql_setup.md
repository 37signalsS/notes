# Ansible: Кроссплатформенная установка и настройка MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — это процесс использования Ansible для развертывания, настройки и обеспечения безопасности сервера баз данных на различных операционных системах (например, Ubuntu и CentOS) без ручного вмешательства.

## Базовые концепции

### Зависимости

Для взаимодействия с MySQL/MariaDB модули Ansible требуют наличия определенных компонентов:

1. **Коллекция `community.mysql`**: Набор специализированных модулей Ansible для управления пользователями, базами данных, переменными и т.д. Устанавливается на управляющий узел (`control node`).
2. **Python-библиотека `PyMySQL`**: Требуется на управляющем узле для работы коллекции.
3. **Драйвер на целевом хосте**: На управляемых машинах должен быть установлен соответствующий Python-драйвер. Для Debian/Ubuntu это `python3-pymysql`, для CentOS/RHEL — `python3-PyMySQL`.

### Идемпотентность и аутентификация

Ключевая сложность при автоматизации — обеспечение **идемпотентности** (возможности многократного безопасного запуска плейбука). Основная проблема возникает при смене пароля `root`:

* **Debian/Ubuntu**: После установки пользователь `root` аутентифицируется через unix-сокет (`auth_socket`) без пароля. Для первоначальной настройки используется параметр `login_unix_socket`.
* **CentOS/RHEL**: После установки у `root` нет пароля, и можно подключиться локально.

После того как плейбук установит пароль и изменит плагин аутентификации на `mysql_native_password`, старый метод входа перестанет работать. Ansible должен уметь подключаться как при первом, так и при последующих запусках.

## Практические сценарии

### Предварительные требования на управляющем узле

```bash
# 1. Установить коллекцию Ansible
ansible-galaxy collection install community.mysql

# 2. Установить Python-библиотеку
pip install PyMySQL
```

### Кроссплатформенный плейбук

```yaml
---
- name: Install and Configure MySQL/MariaDB
  hosts: all
  become: yes
  vars:
    # ВАЖНО: Храните пароль в Ansible Vault!
    # ansible-vault encrypt_string 'YourSecretPassword' --name 'mysql_root_password'
    mysql_root_password: "YourSecretPassword"

  tasks:
    # --- Блок задач для Debian/Ubuntu ---
    - name: Debian | Install MySQL and dependencies
      ansible.builtin.apt:
        name:
          - mysql-server
          - python3-pymysql
        state: present
        update_cache: yes
      when: ansible_os_family == "Debian"

    # --- Блок задач для RedHat/CentOS ---
    - name: RedHat | Install MariaDB and dependencies
      ansible.builtin.yum:
        name:
          - mariadb-server
          - python3-PyMySQL
        state: present
      when: ansible_os_family == "RedHat"

    # --- Общие задачи ---
    - name: Ensure MySQL/MariaDB service is started and enabled
      ansible.builtin.service:
        name: "{{ 'mysql' if ansible_os_family == 'Debian' else 'mariadb' }}"
        state: started
        enabled: yes

    - name: Set root password and secure the installation
      block:
        - name: Set root password for the first time (Debian)
          community.mysql.mysql_user:
            login_unix_socket: /var/run/mysqld/mysqld.sock
            name: root
            host: localhost
            password: "{{ mysql_root_password }}"
            plugin: mysql_native_password
            state: present
          when: ansible_os_family == "Debian"

        - name: Set root password for the first time (RedHat)
          community.mysql.mysql_user:
            name: root
            host: localhost
            password: "{{ mysql_root_password }}"
            plugin: mysql_native_password
            state: present
          when: ansible_os_family == "RedHat"

        - name: Remove anonymous MySQL users
          community.mysql.mysql_user:
            login_user: root
            login_password: "{{ mysql_root_password }}"
            name: ''
            host_all: yes
            state: absent

        - name: Remove the MySQL test database
          community.mysql.mysql_db:
            login_user: root
            login_password: "{{ mysql_root_password }}"
            name: test
            state: absent
```

> **Примечание:** После первого успешного выполнения задачи по установке пароля, последующие задачи (`Remove anonymous...`, `Remove... test database`) используют `login_user` и `login_password` для аутентификации. Это обеспечивает идемпотентность при повторных запусках.

## Дополнительная информация

### Процесс отладки и типичные ошибки

1. **Ошибка: `couldn't resolve module/action 'community.mysql.mysql_user'`**
    * **Причина**: Коллекция `community.mysql` не установлена на управляющем узле.
    * **Решение**: `ansible-galaxy collection install community.mysql`.

2. **Ошибка: `Failed to import the required Python library (PyMySQL)`**
    * **Причина**: Отсутствует необходимый Python-драйвер на **целевом хосте**.
    * **Решение**: Добавить в плейбук установку пакета `python3-pymysql` (для Debian/Ubuntu) или `python3-PyMySQL` (для CentOS/RHEL), как показано в примере.

3. **Ошибка: `unable to connect to database...` при повторном запуске**
    * **Причина**: Нарушение идемпотентности. Плейбук изменил метод аутентификации `root` при первом запуске, и теперь не может подключиться старым способом.
    * **Решение**: Убедиться, что задачи, следующие за сменой пароля, используют новые учетные данные (`login_user`, `login_password`). В сложных сценариях могут потребоваться более продвинутые проверки с `register` и `when`.
