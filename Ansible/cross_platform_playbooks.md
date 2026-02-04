# Кроссплатформенные плейбуки Ansible

## Определения

- **Кроссплатформенный плейбук (Cross-Platform Playbook)**: Плейбук, спроектированный для успешного выполнения на различных операционных системах (например, Debian- и RedHat-семейств) путем адаптации задач к целевому окружению.
- **Факты Ansible (`ansible_facts`)**: Набор переменных, которые Ansible автоматически собирает с управляемого узла. Эти факты содержат системную информацию, такую как сетевые интерфейсы, версия ОС и семейство ОС.
- **`ansible_os_family`**: Ключевой факт Ansible, который группирует операционные системы по семействам (например, `Debian` для Ubuntu/Debian, `RedHat` для CentOS/RHEL/Fedora). Это основная переменная, используемая для построения условной логики в кроссплатформенных плейбуках.

### Ключевые принципы кроссплатформенности

- **Используйте `ansible_os_family`**: Это основа для построения условной логики.
- **Разделяйте задачи**: Выносите OS-специфичные задачи в отдельные файлы и подключайте их через `include_tasks`.
- **Абстрагируйтесь через переменные**: Не кодируйте жестко пути, имена пакетов, служб, пользователей. Определяйте их в `vars/` или `defaults/` с использованием условных выражений.
- **Предпочитайте нативные модули**: `apt`/`yum` дают больше контроля, чем универсальный `package`.
- **Автоматизируйте тестирование**: Используйте Molecule для проверки идемпотентности и корректной работы на всех поддерживаемых дистрибутивах.

## Основные концепции

### Адаптация задач с `include_tasks` и `when: ansible_os_family`

Ключевым элементом кроссплатформенности является использование директивы `ansible.builtin.include_tasks` в сочетании с условной конструкцией `when`, которая опирается на магическую переменную `ansible_os_family`. Директива `include_tasks` по сути берет задачи из указанного файла и "встраивает" их в текущий плейбук, позволяя динамически выбирать набор задач в зависимости от условий.

Пример `roles/nginx/tasks/main.yml`:

```yaml
---
- name: Включение задач для Debian-подобных систем
  ansible.builtin.include_tasks: ubuntu.yml
  when: ansible_os_family == "Debian"

- name: Включение задач для RedHat-подобных систем
  ansible.builtin.include_tasks: centos.yml
  when: ansible_os_family == "RedHat"
```

Это позволяет разделить логику для разных операционных систем в отдельные файлы задач.

> **Важно:** Директивы `include_tasks` сами по себе являются задачами, поэтому к ним также применимы условия `when` и другие параметры задач. Это позволяет строить гибкую и многоуровневую логику в плейбуках.

### Гибкость с помощью ролей и `defaults`

Роли — это эффективный способ организации кода. Для кроссплатформенных решений особенно полезно использовать директорию `defaults` внутри роли.

#### `defaults/main.yml`

Переменные, определенные в `defaults/main.yml`, имеют самый низкий приоритет среди всех источников переменных и могут быть переопределены на более высоких уровнях (плейбук, инвентарь, командная строка). Это делает их идеальными для задания значений по умолчанию, которые легко кастомизировать.
Пример `roles/nginx/defaults/main.yml`:

```yaml
nginx_http_port: 80
```

> **Примечание:** Если переменная определена в `defaults`, но не переопределена на более высоком уровне, будет использовано значение по умолчанию. Если переменной нет ни в `defaults`, ни где-либо еще, Ansible выдаст ошибку.

### Проверка состояния с `register` и `stat`

Для принятия решений в плейбуке на основе наличия файлов или директорий можно использовать связку `register` и модуля `stat`. Это позволяет создавать более "идемпотентные" плейбуки, которые проверяют состояние системы перед выполнением действий.

Пример проверки существования директории Nginx:

```yaml
- name: Проверка существования директории Nginx html
  ansible.builtin.stat:
    path: /usr/share/nginx/html # Путь для CentOS
  register: nginx_html_dir_stat

- name: Копирование файлов только если директория существует
  ansible.builtin.copy:
    src: files/html
    dest: /usr/share/nginx/html/
    owner: vagrant
    group: vagrant
    mode: '0755'
  when: nginx_html_dir_stat.stat.exists # Использование зарегистрированной переменной
```

> **Совет:** Для доступа к элементам словаря в зарегистрированной переменной можно использовать точечную нотацию (`var.key`) или квадратные скобки (`var['key']`). Выбирайте один стиль и придерживайтесь его для консистентности на протяжении всего проекта.

### Работа с системно-зависимыми параметрами

Разные ОС используют разные соглашения для системных пользователей, групп и путей. Вместо жесткого кодирования этих значений их следует определять с помощью условных конструкций.

**Пример:** Веб-сервер Nginx работает от пользователя и группы `www-data` в Debian/Ubuntu, но от `nginx` в RedHat/CentOS. При создании `systemd`-юнита для Gunicorn, который должен взаимодействовать с Nginx через сокет, важно указать правильную группу.

```yaml
# Фрагмент шаблона systemd-юнита (gunicorn.service.j2)
[Service]
User=vagrant
Group={{ nginx_user_group }}
# ...

# Фрагмент плейбука
- name: Create Gunicorn service unit
  ansible.builtin.template:
    src: gunicorn.service.j2
    dest: /etc/systemd/system/myapp.service
  vars:
    # Определяем переменную в зависимости от семейства ОС
    nginx_user_group: "{{ 'nginx' if ansible_os_family == 'RedHat' else 'www-data' }}"
```

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

- **Ubuntu (Debian):** Использует [модуль `ansible.builtin.apt`](ansible_common_modules.md#ansiblebuiltinapt).
- **CentOS (Red Hat):** Использует [модуль `ansible.builtin.yum`](ansible_common_modules.md#ansiblebuiltyum) и предварительно устанавливает репозиторий EPEL.

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

> **Важно:** Хотя существует универсальный [модуль `ansible.builtin.package`](ansible_common_modules.md#ansiblebuiltinpackage), для специфических задач (например, установка EPEL) рекомендуется использовать модули `apt` и `yum` для большей предсказуемости.

### Управление файлами и шаблонами Nginx

**Различия в путях:**

- **Ubuntu:** `/var/www/html`
- **CentOS:** `/usr/share/nginx/html`

**Копирование файлов с [модулем `ansible.builtin.copy`](ansible_common_modules.md#ansiblebuiltincopy):**

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

**Создание конфигураций с [модулем `ansible.builtin.template`](ansible_common_modules.md#ansiblebuiltintemplate):**
Модуль `template` использует [шаблоны Jinja2](ansible_jinja2_templating.md) (`.j2`) для создания динамических файлов.

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
