# Кроссплатформенные плейбуки Ansible: Пример установки LAMP

## Практические сценарии

### Подготовка и базовая структура

**`ansible.cfg`**
Рекомендуется использовать централизованный `ansible.cfg` в корне проекта для обеспечения единообразия.

```ini
[defaults]
inventory = inventory
roles_path = roles
host_key_checking = False
deprecation_warnings = False
```

**`inventory`**

```ini
[ubuntu_servers]
server1 ansible_host=YOUR_UBUNTU_IP ansible_user=vagrant ansible_ssh_pass=vagrant

[centos_servers]
server2 ansible_host=YOUR_CENTOS_IP ansible_user=vagrant ansible_ssh_pass=vagrant
```

**Пример структуры плейбука:**

```yaml
---
- name: Установка LAMP на Ubuntu и CentOS
  hosts: ubuntu_servers, centos_servers
  become: true

  vars:
    php_version: "7.4" # Динамическое управление версией PHP

  roles:
    - common
    - nginx
    - mysql
    - php
```

> **Совет:** Размещение таких переменных, как `php_version`, в секции `vars` плейбука может быть полезно для наглядности, хотя по строгим стандартам они должны находиться в соответствующей роли.

### Установка Nginx

- **Ubuntu (Debian):** Использует [модуль `ansible.builtin.apt`](../Modules/ansible_modules_overview.md#ansiblebuiltinapt).
- **CentOS (Red Hat):** Использует [модуль `ansible.builtin.yum`](../Modules/ansible_modules_overview.md#ansiblebuiltyum) и предварительно устанавливает репозиторий EPEL.

**`roles/nginx/tasks/ubuntu.yml`**

```yaml
- name: Установка Nginx через apt
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: yes
```

**`roles/nginx/tasks/centos.yml`**

```yaml
- name: Установка EPEL release
  ansible.builtin.yum:
    name: epel-release
    state: present

- name: Установка Nginx через yum
  ansible.builtin.yum:
    name: nginx
    state: present
```

> **Важно:** Хотя существует универсальный [модуль `ansible.builtin.package`](../Modules/ansible_modules_overview.md#ansiblebuiltinpackage), для специфических задач (например, установка EPEL) рекомендуется использовать модули `apt` и `yum` для большей предсказуемости.

### Управление файлами и шаблонами Nginx

**Различия в путях:**

- **Ubuntu:** `/var/www/html`
- **CentOS:** `/usr/share/nginx/html`

**Копирование файлов с [модулем `ansible.builtin.copy`](../Modules/ansible_modules_overview.md#ansiblebuiltincopy):**

```yaml
# Пример для CentOS
- name: Копирование страницы лендинга в /usr/share/nginx/html
  ansible.builtin.copy:
    src: files/html
    dest: /usr/share/nginx/html/
    owner: vagrant
    group: vagrant
    mode: '0755'
```

**Создание конфигураций с [модулем `ansible.builtin.template`](../Modules/ansible_modules_overview.md#ansiblebuiltintemplate):**
Модуль `template` использует [шаблоны Jinja2](../ansible_jinja2_templating.md) (`.j2`) для создания динамических файлов.

```yaml
- name: Применение шаблона конфигурации Nginx
  ansible.builtin.template:
    src: nginx.conf.j2 # Шаблон в roles/nginx/templates/
    dest: /etc/nginx/nginx.conf
```

> **Совет:** Используйте суффикс `.j2` для файлов шаблонов. Модуль `template` автоматически ищет их в директории `templates` роли.

### Установка MySQL/MariaDB

**MySQL на Ubuntu:**

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

> **Важно:** На Ubuntu для первого подключения к MySQL используется `login_unix_socket`.

**MariaDB на CentOS:**

```yaml
# roles/mysql/tasks/centos.yml
- name: Установка MariaDB и python3-pymysql
  ansible.builtin.yum:
    name:
      - mariadb-server
      - python3-pymysql
    state: present

- name: Запуск и включение службы MariaDB
  ansible.builtin.service:
    name: mariadb
    state: started
    enabled: yes

- name: Установка пароля root MariaDB (после запуска службы)
  community.mysql.mysql_user:
    name: root
    host: localhost
    password: "{{ mysql_root_password }}"
    plugin: mysql_native_password
    state: present
```

> **Примечание:** Для модулей `community.mysql.*` требуется коллекция `community.mysql`.

### Управление версиями PHP и репозиториями

**PHP на Ubuntu:**
Используется PPA (`ppa:ondrej/php`) для установки нужной версии.

```yaml
# roles/php/tasks/ubuntu.yml
- name: Проверка версии PHP
  ansible.builtin.fail:
    msg: "Неподдерживаемая версия PHP: {{ php_version }}."
  when: php_version not in ['7.4', '8.0', '8.1', '8.2', '8.3']

- name: Добавление PPA репозитория для PHP
  ansible.builtin.apt_repository:
    repo: "ppa:ondrej/php"
    state: present

- name: Установка PHP и модулей
  ansible.builtin.apt:
    name: "php{{ php_version }}-fpm, php{{ php_version }}-mysql"
    state: present
```

**PHP на CentOS:**
Используется репозиторий REMI.

```yaml
# roles/php/tasks/centos.yml
- name: Установка REMI release для Enterprise Linux
  ansible.builtin.yum:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_distribution_major_version }}.rpm"
    state: present

- name: Включение REMI PHP {{ php_version }} репозитория
  ansible.builtin.command: "yum-config-manager --enable remi-php{{ php_version | replace('.', '') }}"
  # Фильтр replace используется для адаптации имени репозитория (7.4 -> 74)

- name: Установка PHP и модулей
  ansible.builtin.yum:
    name: "php{{ php_version }}-php-fpm, php{{ php_version }}-php-mysqlnd"
    state: present
```

### Работа с Python-окружениями

**Управление интерпретатором Python**
На системах вроде CentOS 7 системным Python может быть Python 2. Чтобы модули Ansible использовали Python 3, укажите его явно через `ansible_python_interpreter`.

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
    # ...
```

**Установка зависимостей с `pip` и `virtualenv`**
Модуль `ansible.builtin.pip` позволяет изолировать зависимости в виртуальном окружении.

```yaml
# Пример задачи для установки зависимостей Python-приложения
- name: Install OS-specific dependencies for Python app
  ansible.builtin.yum:
    name: libselinux-python3 # Пример для CentOS
    state: present
  when: ansible_os_family == "RedHat"

- name: Install Python dependencies into a virtual environment
  ansible.builtin.pip:
    requirements: "{{ app_path }}/requirements.txt"
    virtualenv: "{{ app_path }}/venv"
    virtualenv_command: /usr/bin/python3 -m venv
```

Параметр `virtualenv_command` явно указывает команду для создания виртуального окружения, что помогает избежать проблем с версиями.
