# Ansible: Установка и настройка MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — воспроизводимое развертывание и настройка сервера баз данных на различных операционных системах (ОС — Операционная Система) (Debian/Ubuntu, CentOS/RHEL/Rocky) без ручного вмешательства.

**Идемпотентность** — возможность многократного безопасного запуска плейбука без изменения состояния системы, если оно уже соответствует целевому. Основная сложность при автоматизации MySQL — смена метода аутентификации `root` с `auth_socket` на парольный.

**community.mysql** — основная коллекция Ansible для управления MySQL/MariaDB, включающая модули для работы с пользователями, базами данных и репликацией.

## Базовые концепции

### Зависимости

| Компонент | Где требуется | Назначение |
|---|---|---|
| `community.mysql` | Управляющий узел | Коллекция модулей для управления MySQL |
| `PyMySQL` | Управляющий узел | Python-библиотека для работы коллекции |
| `python3-pymysql` | Целевой хост (Debian/Ubuntu) | Драйвер на управляемой машине |
| `python3-PyMySQL` | Целевой хост (RHEL/CentOS/Rocky) | Драйвер на управляемой машине |

Установка на управляющем узле:

```bash
ansible-galaxy collection install community.mysql  # → коллекция установлена
pip install PyMySQL  # → библиотека установлена
```

### Аутентификация и идемпотентность

| ОС | Метод по умолчанию | Современный стандарт |
|---|---|---|
| Debian/Ubuntu | `auth_socket` (через сокет) | `caching_sha2_password` (MySQL 8.0+) |
| RHEL/Rocky | Без пароля (через сокет) | `mysql_native_password` (MariaDB) |

**Важные изменения (Freshness):**
- **MySQL 8.4+:** плагин `mysql_native_password` помечен как устаревший (deprecated).
- **MySQL 9.0+:** плагин `mysql_native_password` полностью удален.
- **Рекомендация:** используйте `caching_sha2_password` для MySQL 8.0+ и `mysql_native_password` для MariaDB.

**Ключевой принцип:** для обеспечения идемпотентности рекомендуется создавать файл `.my.cnf` для пользователя `root` на целевом хосте. Это позволяет модулям подключаться без явной передачи пароля в каждой задаче.

### Кроссплатформенные переменные

```yaml
# Имя службы
service_name: "{{ 'mysql' if ansible_facts['os_family'] == 'Debian' else 'mariadb' }}"

# Пакеты и плагины в зависимости от ОС
mysql_config:
  Debian:
    packages: ["mysql-server", "python3-pymysql"]
    plugin: "caching_sha2_password"
  RedHat:
    packages: ["mariadb-server", "python3-PyMySQL"]
    plugin: "mysql_native_password"
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
    config: "{{ mysql_config[ansible_facts['os_family']] }}"

  tasks:
    - name: Install database server and dependencies
      ansible.builtin.package:
        name: "{{ config.packages }}"
        state: present
      register: db_install

    - name: Ensure service is started and enabled
      ansible.builtin.service:
        name: "{{ service_name }}"
        state: started
        enabled: yes

    - name: Configure root password (initial setup)
      block:
        - name: Set root password
          community.mysql.mysql_user:
            login_unix_socket: "{{ '/var/run/mysqld/mysqld.sock' if ansible_facts['os_family'] == 'Debian' else omit }}"
            name: root
            host: localhost
            password: "{{ mysql_root_password }}"
            plugin: "{{ config.plugin }}"
            state: present
          register: root_pwd_setup
      rescue:
        - name: Password already set or socket unavailable
          ansible.builtin.debug:
            msg: "Initial root setup skipped, possibly already configured."

    - name: Create .my.cnf for root idempotency
      ansible.builtin.copy:
        content: |
          [client]
          user=root
          password={{ mysql_root_password }}
        dest: /root/.my.cnf
        owner: root
        group: root
        mode: '0400'

    - name: Secure installation | Remove anonymous users
      community.mysql.mysql_user:
        name: ''
        host_all: yes
        state: absent

    - name: Secure installation | Remove test database
      community.mysql.mysql_db:
        name: test
        state: absent
```

---

## Дополнительная информация

### Типичные ошибки и решения

**Ошибка: `couldn't resolve module/action 'community.mysql.mysql_user'`**
- **Причина:** Коллекция `community.mysql` не установлена на управляющем узле.
- **Решение:** `ansible-galaxy collection install community.mysql` # → коллекция установлена

**Ошибка: `Failed to import the required Python library (PyMySQL)`**
- **Причина:** Отсутствует Python-драйвер на целевом хосте.
- **Решение:** Убедитесь, что пакет `python3-pymysql` (Debian) или `python3-PyMySQL` (RedHat) установлен до вызова модулей MySQL.

**Ошибка: `unable to connect to database` при повторном запуске**
- **Причина:** Плейбук изменил метод аутентификации, но пытается подключиться старым способом.
- **Решение:** Используйте метод с созданием файла `/root/.my.cnf`, как показано в сценарии выше, для обеспечения полной идемпотентности.

### Безопасность

Пароль `root` и другие чувствительные данные необходимо хранить в [Ansible Vault (защищенное хранилище)](../Vault/basics.md):

```bash
ansible-vault encrypt_string 'YourSecretPassword' --name 'mysql_root_password' # → зашифрованная строка сгенерирована
```

## Смотрите также

- [Ansible Vault: Базовая настройка](../Vault/basics.md)
- [Развертывание LEMP-стека через Ansible](tutorial_lemp_stack.md)
- [MySQL: Установка и базовая настройка (SSoT)](../../Databases/MySQL/installation.md)
