# Кроссплатформенные плейбуки Ansible

В этом документе рассматриваются методы создания плейбуков Ansible, которые могут быть адаптированы для работы в различных операционных системах, таких как Ubuntu (Debian) и CentOS (Red Hat). Мы изучим использование условных конструкций, переменных и структуры ролей для достижения гибкости и идемпотентности.

См. также:
*   [Пример: Кроссплатформенная установка LEMP](./ansible_lemp_cross_platform_example.md)
*   [Обзор Ansible](ansible_overview.md)
*   [Ansible: Плейбуки](ansible_playbooks.md)
*   [Ansible: Роли](ansible_roles.md)

## 1. Общие настройки: `ansible.cfg` и `inventory`

Для кроссплатформенных плейбуков важна правильная настройка файлов конфигурации `ansible.cfg` и инвентаря.

### `ansible.cfg`
Рекомендуется использовать централизованный `ansible.cfg` в корне проекта для обеспечения единообразия. Пример базовой конфигурации:
```ini
[defaults]
inventory = inventory
roles_path = roles
host_key_checking = False
deprecation_warnings = False
```

### `inventory`
Файл инвентаря (`inventory`) определяет целевые хосты и группы. Для демонстрации кроссплатформенности удобно использовать группы хостов.
```ini
[ubuntu_servers]
server1 ansible_host=YOUR_UBUNTU_IP ansible_user=vagrant ansible_ssh_pass=vagrant

[centos_servers]
server2 ansible_host=YOUR_CENTOS_IP ansible_user=vagrant ansible_ssh_pass=vagrant
```
> **Примечание:** Хранение паролей в открытом виде небезопасно. Используйте [Ansible Vault](../ansible_vault.md) для хранения чувствительных данных.
> **Совет:** Используйте группы хостов в инвентаре для удобного управления разнородными системами, это более гибкий подход, чем перечисление отдельных серверов.

## 2. Структура плейбука и использование переменных

Плейбук для кроссплатформенного развертывания LAMP-стека может выглядеть следующим образом:

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
*   `name`: Задает имя для плейбука, которое будет отображаться в выводе Ansible. Это полезно для отслеживания выполнения задач.
*   `hosts`: Указывает группы хостов, на которых будет выполняться плейбук.
*   `become: true`: Выполнять все задачи с повышенными привилегиями (аналог `sudo`).
*   `vars`: Позволяет определить переменные на уровне плейбука, например, для динамического управления версиями компонентов.
> **Совет:** Размещение таких переменных, как `php_version`, непосредственно в секции `vars` плейбука, может быть полезно для быстрой настройки и наглядности, особенно если вы хотите, чтобы системный администратор сразу видел и мог изменить ключевые параметры при запуске плейбука. Хотя по строгим стандартам переменные, относящиеся к конкретной роли (например, PHP), должны находиться в этой роли, в системном администрировании допускается некоторая гибкость для повышения читаемости и удобства использования.

## 3. Гибкость с помощью ролей и `defaults`

Роли — это эффективный способ организации кода. Для кроссплатформенных решений особенно полезно использовать директорию `defaults` внутри роли.

### `defaults/main.yml`
Переменные, определенные в `defaults/main.yml`, имеют самый низкий приоритет среди всех источников переменных и могут быть переопределены на более высоких уровнях (плейбук, инвентарь, командная строка). Это делает их идеальными для задания значений по умолчанию, которые легко кастомизировать.
Пример `roles/nginx/defaults/main.yml`:
```yaml
nginx_http_port: 80
```
> **Примечание:** Если переменная определена в `defaults`, но не переопределена на более высоком уровне, будет использовано значение по умолчанию. Если переменной нет ни в `defaults`, ни где-либо еще, Ansible выдаст ошибку.

## 4. Адаптация задач с `include` и `when: ansible_os_family`

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

### Отличия в файлах задач (`ubuntu.yml` и `centos.yml`)

#### Установка Nginx
*   **Ubuntu (Debian):** Использует `ansible.builtin.apt` для установки пакета `nginx`.
    ```yaml
    # roles/nginx/tasks/ubuntu.yml
    - name: Установка Nginx через apt
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: yes
    ```
*   **CentOS (Red Hat):** Использует `ansible.builtin.yum` и предварительно устанавливает репозиторий EPEL для актуальных пакетов.
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
> **Важно:** Хотя существует универсальный модуль `ansible.builtin.package`, который абстрагирует различия между `apt` и `yum`, для специфических задач (например, установка EPEL) или когда требуется более тонкий контроль над пакетным менеджером, рекомендуется использовать специализированные модули (`apt`, `yum`). Это уменьшает "магию" и делает плейбуки более явными и предсказуемыми.

#### Управление файлами и конфигурацией Nginx
Пути к файлам Nginx могут отличаться:
*   **Ubuntu:** `/var/www/html`
*   **CentOS:** `/usr/share/nginx/html` (путь по умолчанию, который Ansible использует для Nginx в RedHat-подобных системах)

Пример копирования кастомной страницы:
```yaml
# Пример для Ubuntu (roles/nginx/tasks/ubuntu.yml)
- name: Копирование страницы лендинга в /var/www/html
  ansible.builtin.copy:
    src: files/html
    dest: /var/www/
    owner: vagrant
    group: vagrant
    mode: '0755'

# Пример для CentOS (roles/nginx/tasks/centos.yml)
- name: Копирование страницы лендинга в /usr/share/nginx/html
  ansible.builtin.copy:
    src: files/html
    dest: /usr/share/nginx/html/
    owner: vagrant
    group: vagrant
    mode: '0755'
```

#### Модуль `ansible.builtin.template`
Для создания динамических конфигурационных файлов используйте модуль `template` с шаблонами Jinja2 (`.j2`). Это позволяет внедрять переменные и логику в текстовые файлы перед их развертыванием на целевых хостах.
Пример использования:
```yaml
- name: Применение шаблона конфигурации Nginx
  ansible.builtin.template:
    src: nginx.conf.j2 # Шаблон в roles/nginx/templates/
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
```
> **Совет:** Используйте суффикс `.j2` для файлов шаблонов для наглядности, чтобы сразу было понятно, что это шаблон Jinja2. Модуль `template` автоматически ищет шаблоны в директории `templates` роли. Если вы просто скопируете файл с переменными с помощью `ansible.builtin.copy`, переменные не будут обработаны, и вы получите их в сыром виде.
> **Важно:** Директивы `include_tasks` сами по себе являются задачами, поэтому к ним также применимы условия `when` и другие параметры задач. Это позволяет строить гибкую и многоуровневую логику в плейбуках.

## 5. Особенности установки MySQL/MariaDB

Установка баз данных также имеет свои нюансы.

### MySQL на Ubuntu
```yaml
# roles/mysql/tasks/ubuntu.yml
- name: Установка MySQL и python3-pymysql
  ansible.builtin.apt:
    name:
      - mysql-server
      - python3-pymysql
    state: present
    update_cache: yes

- name: Установка пароля root MySQL (через socket)
  community.mysql.mysql_user:
    login_unix_socket: /var/run/mysqld/mysqld.sock
    name: root
    host: localhost
    password: "{{ mysql_root_password }}"
    plugin: mysql_native_password
    state: present
```
> **Важно:** Для первого подключения к свежеустановленному MySQL на Ubuntu используется `login_unix_socket`, так как `root` изначально аутентифицируется через сокет без пароля. Затем плагин меняется на `mysql_native_password` для возможности аутентификации по паролю.
> **Примечание:** Для использования модуля `community.mysql.mysql_user` необходимо убедиться, что коллекция `community.mysql` установлена в вашей среде Ansible. Это можно сделать с помощью `ansible-galaxy collection install community.mysql`.

### MariaDB на CentOS
На CentOS часто используется MariaDB вместо MySQL. Установка происходит через `yum`. Также важно вручную запустить службу после установки.
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
> **Примечание:** В CentOS с SELinux могут возникнуть проблемы с доступом к сокету, поэтому прямое подключение по паролю после запуска службы может быть более надежным. Убедитесь, что служба MariaDB запущена перед попыткой установить пароль.

## 6. Управление версиями PHP и репозиториями

Для PHP различия между ОС еще более выражены из-за необходимости использования сторонних репозиториев для актуальных версий.

### PHP на Ubuntu
*   Использование PPA (Private Package Archive) для установки нужной версии PHP.
*   Пример использования модуля `ansible.builtin.fail` для проверки поддерживаемой версии. Это позволяет прервать выполнение плейбука, если запрошенная версия PHP не входит в список поддерживаемых, предотвращая потенциальные ошибки.
```yaml
# roles/php/tasks/ubuntu.yml
- name: Проверка версии PHP
  ansible.builtin.fail:
    msg: "Неподдерживаемая версия PHP: {{ php_version }}. Поддерживаемые версии: 7.4, 8.0, 8.1, 8.2, 8.3"
  when: php_version not in ['7.4', '8.0', '8.1', '8.2', '8.3'] # Пример поддерживаемых версий

- name: Добавление PPA репозитория для PHP
  ansible.builtin.apt_repository:
    repo: "ppa:ondrej/php"
    state: present

- name: Установка PHP и модулей
  ansible.builtin.apt:
    name: "php{{ php_version }}-fpm, php{{ php_version }}-mysql"
    state: present
    update_cache: yes
```
> **Совет:** Желательно хранить шаблоны (`.j2`) для конфигурации PHP в отдельной директории `templates` внутри роли, аналогично другим ролям. Модуль `template` автоматически ищет файлы в этой директории.

### PHP на CentOS
*   Использование REMI-репозитория, который предоставляет актуальные версии PHP для Enterprise Linux.
*   Управление включением/выключением стандартных и REMI-репозиториев для установки конкретной версии. Это необходимо, чтобы избежать конфликтов и установить нужную версию PHP, так как CentOS по умолчанию может предлагать устаревшие версии.
*   Применение фильтров Jinja2 для обработки строковых переменных (например, `php_version | replace('.', '')`). Это позволяет адаптировать переменную `php_version` к формату, ожидаемому именем репозитория.
```yaml
# roles/php/tasks/centos.yml
- name: Установка REMI release для Enterprise Linux
  ansible.builtin.yum:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_distribution_major_version }}.rpm"
    state: present

- name: Отключение стандартного PHP-репозитория (пример для старых версий)
  ansible.builtin.command: "yum-config-manager --disable remi-php54"

- name: Включение REMI PHP {{ php_version }} репозитория
  ansible.builtin.command: "yum-config-manager --enable remi-php{{ php_version | replace('.', '') }}"
  # Использование фильтра replace для адаптации названия репозитория, убирая точки

- name: Установка PHP и модулей
  ansible.builtin.yum:
    name: "php{{ php_version }}-php-fpm, php{{ php_version }}-php-mysqlnd"
    state: present
```
> **Примечание:** В CentOS пути к PHP-сокетам и конфигурационным файлам могут отличаться от Ubuntu. Убедитесь, что шаблоны конфигурации адаптированы для соответствующей ОС.
> **Совет:** Избегайте слишком длинных цепочек фильтров Jinja2, так как это может ухудшить читаемость и отладку. Один-два фильтра, как в примере с `replace`, обычно допустимы.

## 7. Проверка существования файлов с `register` и `stat`

Для принятия решений в плейбуке на основе наличия файлов или директорий можно использовать связку `register` и модуля `stat`.

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
> **Совет:** Для доступа к элементам словаря в зарегистрированной переменной можно использовать точечную нотацию (`var.key`) или квадратные скобки (`var['key']`). Выбирайте один стиль и придерживайтесь его для консистентности на протяжении всего проекта, чтобы улучшить читаемость и избежать ошибок.
> **Важно:** Использование `register` и `stat` позволяет создавать более "идемпотентные" плейбуки, которые проверяют состояние системы перед выполнением действий, предотвращая ненужные изменения или ошибки.

## 8. Работа с Python-окружениями и системными различиями

При развертывании приложений, особенно на Python, возникают дополнительные кроссплатформенные нюансы, связанные с версиями интерпретатора и системными настройками.

### Управление интерпретатором Python

Некоторые системы (например, CentOS 7) поставляются с Python 2 по умолчанию, в то время как современные приложения требуют Python 3. Ansible, в свою очередь, для выполнения своих модулей использует системный Python (`/usr/bin/python`), который может быть симлинком на Python 2.

**Проблема:** Ваш плейбук, который устанавливает Python 3, может продолжать использовать Python 2 для выполнения последующих модулей, что приведет к ошибкам.

**Решение:** Использовать переменную `ansible_python_interpreter` для явного указания, какой интерпретатор должны использовать модули Ansible.

Это можно сделать на уровне плея:
```yaml
- name: Deploy Python 3 app on CentOS
  hosts: centos_servers
  become: true
  vars:
    # Указываем Ansible использовать Python 3 для всех последующих задач
    ansible_python_interpreter: /usr/bin/python3 

  tasks:
    - name: Install Python 3
      ansible.builtin.yum:
        name: python3
        state: present

    - name: Install pip for Python 3
      ansible.builtin.command: "python3 -m ensurepip --upgrade"
      
    # ... последующие задачи будут использовать python3
    - name: Install app dependencies using pip3
      ansible.builtin.pip:
        name: flask
        executable: pip3
```
Разделение на плеи, как в [примере с bootstrapping](../ansible_overview.md#установка-python-на-голые-хосты-bootstrapping), здесь также применимо: первый плей устанавливает Python 3, второй — использует его, указывая `ansible_python_interpreter`.

### Системно-зависимые параметры

Разные ОС используют разные соглашения для системных пользователей, групп и путей. Вместо жесткого кодирования этих значений их следует определять с помощью переменных и условных конструкций.

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

### Установка зависимостей Python с `pip` и `virtualenv`

Для изоляции зависимостей приложений на Python является стандартом использование виртуальных окружений. Модуль `ansible.builtin.pip` отлично с этим справляется.

*   `virtualenv`: Путь, где будет создано или использовано виртуальное окружение.
*   `requirements`: Путь к файлу `requirements.txt` для установки зависимостей.

При этом некоторые Python-библиотеки могут требовать системных зависимостей, специфичных для ОС.

**Пример:** Для работы с SELinux в CentOS Python-модулям может потребоваться `libselinux-python`.

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
*   `virtualenv_command`: Явно указывает команду для создания виртуального окружения, что помогает избежать проблем с версиями Python.

Такой подход позволяет создавать надежные и по-настоящему кроссплатформенные плейбуки для развертывания сложных приложений.


