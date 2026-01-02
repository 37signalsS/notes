# Автоматизация установки и настройки MySQL с помощью Ansible

## Предварительные требования

1.  **Коллекция `community.mysql`:**
    ```bash
    ansible-galaxy collection install community.mysql
    ```
2.  **Python-библиотека для работы с MySQL:**
    ```bash
    pip install PyMySQL
    ```

На целевых хостах (где будет установлен MySQL) потребуется `python3-pymysql`. Плейбук автоматически установит его.

## Структура плейбука

1.  Установит пакеты `mysql-server` и `python3-pymysql`.
2.  Запустит и включит сервис `mysql`.
3.  Выполнит задачи безопасности, аналогичные `mysql_secure_installation`:
    *   Задаст пароль для `root`.
    *   Удалит анонимных пользователей.
    *   Удалит тестовую базу данных.
4.  Изменит метод аутентификации пользователя `root` на `mysql_native_password` для совместимости с большинством приложений.

### Полный плейбук

```yaml
---
- name: Install and configure MySQL Server
  hosts: all
  become: yes
  vars:
    # ВАЖНО: Храните пароль в Ansible Vault!
    # ansible-vault encrypt_string 'YourSecretPassword' --name 'mysql_root_password'
    mysql_root_password: "password" # Замените на пароль из Vault

  tasks:
    - name: Install MySQL packages and dependencies
      ansible.builtin.apt:
        name:
          - mysql-server
          - python3-pymysql # Необходим для модуля community.mysql.mysql_user
        state: present
        update_cache: yes
      tags:
        - mysql
        - mysql-install

    - name: Ensure MySQL service is started and enabled
      ansible.builtin.service:
        name: mysql
        state: started
        enabled: yes
      tags:
        - mysql
        - mysql-service

    - name: Set root password and secure installation
      block:
        # Эта задача изменяет пароль пользователя root и метод аутентификации.
        # login_unix_socket используется для первоначального подключения,
        # так как по умолчанию после установки у root нет пароля.
        - name: Change root user authentication to mysql_native_password
          community.mysql.mysql_user:
            login_unix_socket: /var/run/mysqld/mysqld.sock
            name: root
            host: localhost
            password: "{{ mysql_root_password }}"
            plugin: mysql_native_password
            state: present
          tags:
            - mysql
            - mysql-secure

        # Ansible подключается с использованием файла .my.cnf, который он создает
        # для последующих задач.
        - name: Remove anonymous MySQL users
          community.mysql.mysql_user:
            name: ''
            host_all: yes
            state: absent
          tags:
            - mysql
            - mysql-secure

        - name: Remove the MySQL test database
          community.mysql.mysql_db:
            name: test
            state: absent
          tags:
            - mysql
            - mysql-secure
      tags:
        - mysql-all
```

## Разбор ключевых задач

### Установка пакетов

```yaml
- name: Install MySQL packages and dependencies
  ansible.builtin.apt:
    name:
      - mysql-server
      - python3-pymysql
    state: present
    update_cache: yes
```
Эта задача устанавливает сам сервер MySQL и библиотеку `python3-pymysql`.

*   **`mysql-server`**: Основной пакет сервера баз данных.
*   **`python3-pymysql`**: Python-драйвер, необходимый модулям из коллекции `community.mysql` для взаимодействия с MySQL на целевом хосте. Без него вы столкнетесь с ошибкой `Failed to import the required Python library (PyMySQL).`

### Изменение аутентификации `root`

```yaml
- name: Change root user authentication to mysql_native_password
  community.mysql.mysql_user:
    login_unix_socket: /var/run/mysqld/mysqld.sock
    name: root
    host: localhost
    password: "{{ mysql_root_password }}"
    plugin: mysql_native_password
    state: present
```
Это ключевая и самая важная задача. Вручную это делается командой `ALTER USER`. Здесь мы делаем то же самое, но идемпотентно.

*   `login_unix_socket`: После свежей установки MySQL в Debian/Ubuntu пользователь `root` использует плагин `auth_socket` и может войти только через unix-сокет без пароля. Этот параметр указывает Ansible использовать именно этот метод для первого подключения, чтобы выполнить первоначальную настройку.
*   `plugin: mysql_native_password`: Эта директива переключает `root` на стандартную парольную аутентификацию, которая требуется большинству веб-приложений (PHP, Python и т.д.).
*   **Идемпотентность**: Проблема возникает при повторном запуске плейбука. После первого запуска метод аутентификации меняется, и подключение через сокет без пароля больше невозможно. Плейбук выше решает эту проблему, так как Ansible после успешного выполнения этой задачи "запоминает" пароль и использует его для последующих задач в рамках одного запуска. Для обеспечения идемпотентности между запусками можно было бы использовать `check_implicit_admin: yes`, который проверяет возможность входа без пароля перед выполнением действий, но использование `login_unix_socket` для начальной настройки является более явным подходом.

### Удаление анонимных пользователей и тестовой БД

```yaml
- name: Remove anonymous MySQL users
  community.mysql.mysql_user:
    name: ''
    host_all: yes
    state: absent

- name: Remove the MySQL test database
  community.mysql.mysql_db:
    name: test
    state: absent
```
Эти две задачи выполняют действия, которые предлагает интерактивный скрипт `mysql_secure_installation`.
*   **Контекст (Ubuntu vs. CentOS)**: В современных версиях MySQL на Ubuntu анонимные пользователи и тестовая база данных по умолчанию не создаются. Однако в других дистрибутивах, например, в CentOS, они могут присутствовать. Включение этих задач в плейбук делает его более универсальным и безопасным для различных окружений.

---

## Процесс отладки и типичные ошибки

### 1. Неизвестный модуль

*   **Проблема**: При первом запуске плейбука Ansible выдает ошибку, что не может найти модуль, например, `community.mysql.mysql_user`.
    ```
    ERROR! couldn't resolve module/action 'community.mysql.mysql_user'.
    ```
*   **Причина**: Модуль не является встроенным и поставляется в составе коллекции, которую нужно установить отдельно.
*   **Решение**: Установить коллекцию с помощью `ansible-galaxy`.
    ```bash
    ansible-galaxy collection install community.mysql
    ```

### 2. Отсутствие Python-драйвера

*   **Проблема**: Задача падает с ошибкой, сообщающей об отсутствии необходимой Python-библиотеки.
    ```
    "msg": "Failed to import the required Python library (PyMySQL) on ...'s Python /usr/bin/python3. Please install it with 'pip install PyMySQL'."
    ```
*   **Причина**: Модулю Ansible для работы с базой данных требуется соответствующий Python-драйвер на **целевом хосте**.
*   **Решение**: Добавить установку пакета `python3-pymysql` (для Debian/Ubuntu) в плейбук, как это сделано в примере выше.

### 3. Нарушение идемпотентности

*   **Проблема**: Плейбук успешно выполняется в первый раз, но падает при последующих запусках с ошибкой подключения к базе данных.
    ```
    "msg": "unable to connect to database, check login_user and login_password are correct"
    ```
*   **Причина**: Первая задача меняет метод аутентификации `root`, и при следующем запуске Ansible больше не может подключиться старым способом (через `login_unix_socket`).
*   **Решение**: Убедиться, что Ansible может аутентифицироваться как при первом, так и при последующих запусках. В данном плейбуке это решается тем, что после смены пароля Ansible автоматически подхватывает новые учетные данные для последующих задач. Для более сложных сценариев можно использовать переменные, условные проверки или специфичные параметры модуля, такие как `check_implicit_admin: yes`.
