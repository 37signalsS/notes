# Ansible: Установка и настройка MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — воспроизводимое развертывание и настройка сервера баз данных на различных ОС (Debian/Ubuntu, CentOS/RHEL) без ручного вмешательства.

**Идемпотентность** — возможность многократного безопасного запуска плейбука. Основная сложность при автоматизации MySQL — смена метода аутентификации `root` с `auth_socket` на парольный.

## Базовые концепции

### Зависимости

| Компонент | Где требуется | Назначение |
|---|---|---|
| `community.mysql` | Управляющий узел | Коллекция модулей для управления MySQL |
| `PyMySQL` | Управляющий узел | Python-библиотека для работы коллекции |
| `python3-pymysql` | Целевой хост (Debian/Ubuntu) | Драйвер на управляемой машине |
| `python3-PyMySQL` | Целевой хост (CentOS/RHEL) | Драйвер на управляемой машине |

Установка на управляющем узле:

```bash
ansible-galaxy collection install community.mysql
pip install PyMySQL
```

### Аутентификация и идемпотентность

| ОС | Метод по умолчанию | После настройки |
|---|---|---|
| Debian/Ubuntu | `auth_socket` (без пароля, через сокет) | `mysql_native_password` с паролем |
| CentOS/RHEL | Без пароля (локальное подключение) | `mysql_native_password` с паролем |

**Ключевой принцип:** после установки пароля все последующие задачи должны использовать `login_user` и `login_password` для аутентификации.

### Кроссплатформенные переменные

```yaml
# Имя службы
service_name: "{{ 'mysql' if ansible_os_family == 'Debian' else 'mariadb' }}"

# Пакеты для Debian
debian_packages:
  - mysql-server
  - python3-pymysql

# Пакеты для RedHat
redhat_packages:
  - mariadb-server
  - python3-PyMySQL
```

---

## Практические сценарии

### Сценарий: Кроссплатформенная установка MySQL/MariaDB

```yaml
---
- name: Install and Configure MySQL/MariaDB
  hosts: all
  become: true
  vars:
    mysql_root_password: "YourSecretPassword"  # Хранить в Ansible Vault!

  tasks:
    # --- Debian/Ubuntu ---
    - name: Debian | Install MySQL and dependencies
      ansible.builtin.apt:
        name:
          - mysql-server
          - python3-pymysql
        state: present
        update_cache: yes
      when: ansible_os_family == "Debian"

    # --- RedHat/CentOS ---
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

    - name: Set root password and secure installation
      block:
        - name: Set root password (Debian)
          community.mysql.mysql_user:
            login_unix_socket: /var/run/mysqld/mysqld.sock
            name: root
            host: localhost
            password: "{{ mysql_root_password }}"
            plugin: mysql_native_password
            state: present
          when: ansible_os_family == "Debian"

        - name: Set root password (RedHat)
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

        - name: Remove test database
          community.mysql.mysql_db:
            login_user: root
            login_password: "{{ mysql_root_password }}"
            name: test
            state: absent
```

---

## Дополнительная информация

### Типичные ошибки и решения

**Ошибка: `couldn't resolve module/action 'community.mysql.mysql_user'`**

- **Причина:** Коллекция `community.mysql` не установлена на управляющем узле
- **Решение:** `ansible-galaxy collection install community.mysql`

**Ошибка: `Failed to import the required Python library (PyMySQL)`**

- **Причина:** Отсутствует Python-драйвер на целевом хосте
- **Решение:** Добавить установку `python3-pymysql` (Debian) или `python3-PyMySQL` (RedHat) в плейбук

**Ошибка: `unable to connect to database` при повторном запуске**

- **Причина:** Нарушение идемпотентности — плейбук изменил метод аутентификации, но следующие задачи используют старый способ
- **Решение:** Задачи после смены пароля должны использовать `login_user` и `login_password`

### Безопасность

Пароль `root` необходимо хранить в [Ansible Vault](../Vault/basics.md):

```bash
ansible-vault encrypt_string 'YourSecretPassword' --name 'mysql_root_password'
```

### Кроссплатформенные роли

Примеры использования MySQL в составе LAMP/LEMP-стеков — в [CrossPlatform/concepts.md](../CrossPlatform/concepts.md) и [tutorial_lemp_stack.md](tutorial_lemp_stack.md).
