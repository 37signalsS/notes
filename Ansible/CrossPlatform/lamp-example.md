# Ansible: Кроссплатформенный пример установки LAMP

## Определения

- **LAMP** — стек веб-приложений: Linux (ОС), Apache/Nginx (веб-сервер), MySQL/MariaDB (СУБД), PHP (язык программирования).
- **Кроссплатформенный плейбук** — плейбук Ansible, адаптирующийся к различным семействам ОС (Debian/RedHat) через условную логику и переменные.

> Базовые концепции кроссплатформенности описаны в [`concepts.md`](./concepts.md).

## Базовые концепции

### Структура проекта

**`ansible.cfg`** — централизованная конфигурация для единообразия:

```ini
[defaults]
inventory = inventory
roles_path = roles
host_key_checking = False
deprecation_warnings = False
```

**`inventory`** — инвентарь с группами серверов:

```ini
[ubuntu_servers]
server1 ansible_host=YOUR_UBUNTU_IP ansible_user=vagrant ansible_ssh_pass=vagrant

[centos_servers]
server2 ansible_host=YOUR_CENTOS_IP ansible_user=vagrant ansible_ssh_pass=vagrant
```

**Плейбук** — оркестрация ролей:

```yaml
---
- name: Установка LAMP на Ubuntu и CentOS
  hosts: ubuntu_servers, centos_servers
  become: true

  vars:
    php_version: "8.4"

  roles:
    - common
    - nginx
    - mysql
    - php
```

> **Примечание:** Переменные уровня плейбука (`php_version`) удобны для наглядности, но по стандартам должны находиться в `defaults/` роли.

### Принципы кроссплатформенности

1. **`ansible_os_family`** — базовая переменная для условной логики (`Debian` vs `RedHat`).
2. **`include_tasks`** — динамическое подключение OS-специфичных задач.
3. **Абстракция путей и имен** — вынос в `defaults/` или `vars/`.
4. **Нативные модули** — `apt`/`yum` предпочтительнее универсального `package` для специфичных задач.

## Практические сценарии

### Установка Nginx

**Ubuntu (Debian):** модуль [`ansible.builtin.apt`](../Modules/ansible_package_management_modules.md).

```yaml
# roles/nginx/tasks/ubuntu.yml
- name: Установка Nginx через apt
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: yes
```

**CentOS (Red Hat):** модуль [`ansible.builtin.yum`](../Modules/ansible_package_management_modules.md) + репозиторий EPEL:

```yaml
# roles/nginx/tasks/centos.yml
- name: Установка EPEL release
  ansible.builtin.yum:
    name: epel-release
    state: present

- name: Установка Nginx через yum
  ansible.builtin.yum:
    name: nginx
    state: present
```

> **Важно:** Модуль [`ansible.builtin.package`](../Modules/ansible_package_management_modules.md) универсален, но `apt`/`yum` дают больше контроля для специфичных задач (EPEL).

### Управление файлами и шаблонами Nginx

**Различия в путях:**

| ОС | Путь к document root |
| :--- | :--- |
| Ubuntu | `/var/www/html` |
| CentOS | `/usr/share/nginx/html` |

**Копирование файлов** — модуль [`ansible.builtin.copy`](../Modules/ansible_file_management_modules.md):

```yaml
# Пример для CentOS
- name: Копирование лендинга
  ansible.builtin.copy:
    src: files/html
    dest: /usr/share/nginx/html/
    owner: vagrant
    group: vagrant
    mode: '0755'
```

**Шаблоны конфигураций** — модуль [`ansible.builtin.template`](../Modules/ansible_file_management_modules.md) + Jinja2 (`.j2`):

```yaml
- name: Применение шаблона nginx.conf
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
```

> **Совет:** Суффикс `.j2` обязателен. Модуль `template` ищет шаблоны в `roles/<role>/templates/`.

### Установка MySQL/MariaDB

**Ubuntu (MySQL):**

```yaml
# roles/mysql/tasks/ubuntu.yml
- name: Установка MySQL и python3-pymysql
  ansible.builtin.apt:
    name:
      - mysql-server
      - python3-pymysql
    state: present

- name: Установка пароля root MySQL (через socket)
  community.mysql.mysql_user:
    login_unix_socket: /var/run/mysqld/mysqld.sock
    name: root
    host: localhost
    password: "{{ mysql_root_password }}"
    plugin: mysql_native_password
    state: present
```

> **Важно:** На Ubuntu первичное подключение через `login_unix_socket`.

**CentOS (MariaDB):**

```yaml
# roles/mysql/tasks/centos.yml
- name: Установка MariaDB и python3-pymysql
  ansible.builtin.yum:
    name:
      - mariadb-server
      - python3-pymysql
    state: present

- name: Запуск и включение MariaDB
  ansible.builtin.service:
    name: mariadb
    state: started
    enabled: yes

- name: Установка пароля root MariaDB
  community.mysql.mysql_user:
    name: root
    host: localhost
    password: "{{ mysql_root_password }}"
    plugin: mysql_native_password
    state: present
```

> **Примечание:** Требуется коллекция `community.mysql` (`ansible-galaxy collection install community.mysql`).

### Управление версиями PHP

**Ubuntu (PPA ondrej/php):**

```yaml
# roles/php/tasks/ubuntu.yml
- name: Проверка версии PHP
  ansible.builtin.fail:
    msg: "Неподдерживаемая версия PHP: {{ php_version }}"
  when: php_version not in ['8.2', '8.3', '8.4', '8.5']

- name: Добавление PPA репозитория
  ansible.builtin.apt_repository:
    repo: "ppa:ondrej/php"
    state: present

- name: Установка PHP и модулей
  ansible.builtin.apt:
    name:
      - "php{{ php_version }}-fpm"
      - "php{{ php_version }}-mysql"
    state: present
```

**CentOS (REMI):**

```yaml
# roles/php/tasks/centos.yml
- name: Установка REMI release
  ansible.builtin.yum:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_distribution_major_version }}.rpm"
    state: present

- name: Включение REMI PHP репозитория
  ansible.builtin.command:
    cmd: "yum-config-manager --enable remi-php{{ php_version | replace('.', '') }}"
  args:
    creates: /etc/yum.repos.d/remi-php.repo

- name: Установка PHP и модулей
  ansible.builtin.yum:
    name:
      - "php{{ php_version }}-php-fpm"
      - "php{{ php_version }}-php-mysqlnd"
    state: present
```

> **Примечание:** Фильтр `replace('.', '')` преобразует `8.4` → `84` для имени репозитория.

### Работа с Python-окружениями

**Управление интерпретатором:**

На CentOS 7 системный Python — версия 2. Для использования Python 3 укажите `ansible_python_interpreter`:

```yaml
- name: Deploy Python 3 app on CentOS
  hosts: centos_servers
  become: true
  vars:
    ansible_python_interpreter: /usr/bin/python3
  tasks:
    - name: Install Python 3
      ansible.builtin.yum:
        name: python3
        state: present
```

**Установка зависимостей с `pip` и `virtualenv`:**

Модуль [`ansible.builtin.pip`](../Modules/ansible_package_management_modules.md) изолирует зависимости в виртуальном окружении:

```yaml
- name: OS-specific dependencies
  ansible.builtin.yum:
    name: libselinux-python3
    state: present
  when: ansible_os_family == "RedHat"

- name: Python dependencies in virtualenv
  ansible.builtin.pip:
    requirements: "{{ app_path }}/requirements.txt"
    virtualenv: "{{ app_path }}/venv"
    virtualenv_command: /usr/bin/python3 -m venv
```

> **Совет:** `virtualenv_command` явно указывает команду создания venv, избегая проблем с версиями.

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — базовые принципы и паттерны
- [Модули управления пакетами](../Modules/ansible_package_management_modules.md) — `apt`, `yum`, `dnf`, `pip`
- [Модули управления файлами](../Modules/ansible_file_management_modules.md) — `copy`, `template`, `file`
- [Шаблонизация Jinja2](../ansible_jinja2_templating.md) — создание динамических конфигураций
- [Роли Ansible](../ansible_roles.md) — организация кроссплатформенного кода
