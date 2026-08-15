# Кроссплатформенный пример развертывания LAMP/LEMP

## Определения

- **LAMP/LEMP** — классические стеки программного обеспечения для веб-серверов:
  - **Linux** — базовая операционная система (ядро инфраструктуры).
  - **Apache** (LAMP) или **Nginx** (LEMP) — веб-сервер, обрабатывающий HTTP-запросы.
  - **MySQL** или **MariaDB** — реляционная система управления базами данных (СУБД).
  - **PHP** — серверный язык программирования для генерации динамического контента.
- **Кроссплатформенный плейбук (Cross-Platform Playbook)** — сценарий Ansible, способный выполнять идентичные задачи на разных семействах ОС (Debian, RedHat, Alpine) путем динамической адаптации под специфику дистрибутива.
- **FQCN (Fully Qualified Collection Name)** — стандарт именования модулей (например, `ansible.builtin.package`), обеспечивающий бесконфликтную работу в разных средах и версиях Ansible.

## Основные концепции

### Структура кроссплатформенной роли

Для эффективного управления различиями между дистрибутивами Linux рекомендуется разделять задачи и переменные. Это позволяет сохранить файл задач (`tasks/main.yml`) чистым, вынося всю специфику в `vars/`.

**Рекомендуемая структура каталогов:**
```text
roles/webserver/
├── meta/
│   └── argument_specs.yml # Валидация входных данных (PHP версия, стек)
├── defaults/
│   └── main.yml           # Общие безопасные параметры (порты, лимиты)
├── vars/
│   ├── Debian.yml         # Специфика Ubuntu/Debian (пути, пакеты)
│   ├── RedHat.yml         # Специфика RHEL/Rocky/Alma (SELinux, пути)
│   └── default.yml        # Резервные значения
└── tasks/
    ├── main.yml           # Точка входа: include_vars + include_tasks
    ├── setup-debian.yml   # Репозитории Ondrej, PPA
    ├── setup-redhat.yml   # Репозитории REMI, EPEL
    ├── configure.yml      # Универсальные шаблоны Nginx/PHP
    └── firewall.yml       # Адаптация под ufw (Debian) или firewalld (RHEL)
```

### Абстракция через факты ОС

Использование словаря `ansible_facts` является обязательным для кроссплатформенности:
- `ansible_facts['os_family']` — для выбора пакетного менеджера (APT vs DNF) и структуры задач.
- `ansible_facts['distribution_major_version']` — для выбора версии сторонних репозиториев (например, REMI для RHEL 8 vs 9).
- `ansible_facts['distribution_release']` — для формирования путей в APT репозиториях (например, `jammy` для Ubuntu 22.04).

## Практические сценарии

### Сценарий 1: Установка веб-сервера (Абстракция пакетов)

Имена пакетов и сервисов часто различаются между семействами Linux.

**Пример `vars/RedHat.yml`:**
```yaml
web_package: "nginx" # Или "httpd" для Apache
web_service: "nginx" # Или "httpd"
web_user: "nginx"
```

**Пример `vars/Debian.yml`:**
```yaml
web_package: "nginx" # Или "apache2" для Apache
web_service: "nginx" # Или "apache2"
web_user: "www-data"
```

**Универсальная задача установки:**
```yaml
- name: Установка веб-сервера
  ansible.builtin.package:
    name: "{{ web_package }}"
    state: present
```

### Сценарий 2: Настройка PHP-FPM (Различия в сокетах и правах)

PHP-FPM требует внимания к пользователю процесса и путям к сокетам, которые жестко заданы в конфигурации пула.

| Параметр | Debian/Ubuntu | RHEL/Rocky (Remi) |
| :--- | :--- | :--- |
| **Пользователь процесса** | `www-data` | `nginx` (или `apache`) |
| **Путь к сокету** | `/run/php/php{{ php_version }}-fpm.sock` | `/run/php-fpm/www.sock` (или TCP) |
| **Имя сервиса** | `php{{ php_version }}-fpm` | `php-fpm` |

**Пример настройки сокета в шаблоне `nginx.conf.j2`:**
```nginx
location ~ \.php$ {
    include fastcgi_params;
    fastcgi_pass unix:{{ php_fpm_socket }};
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

### Сценарий 3: Настройка безопасности (SELinux и Firewall)

На RedHat-системах (RHEL, Rocky, Alma) SELinux по умолчанию блокирует сетевые соединения веб-сервера.

```yaml
# tasks/setup-redhat.yml
- name: Разрешить веб-серверу сетевые соединения в SELinux
  ansible.posix.seboolean:
    name: "{{ item }}"
    state: yes
    persistent: yes
  loop:
    - httpd_can_network_connect
    - httpd_can_network_connect_db
  when: ansible_facts['os_family'] == 'RedHat'

- name: Открытие портов в Firewalld
  ansible.posix.firewalld:
    service: "{{ item }}"
    permanent: yes
    state: enabled
    immediate: yes
  loop: [http, https]
  when: ansible_facts['os_family'] == 'RedHat'
```

### Сценарий 4: Подключение актуальных репозиториев PHP

Стандартные репозитории часто содержат устаревшие версии PHP. Кроссплатформенный подход требует подключения внешних источников.

**Для RedHat (REMI):**
```yaml
- name: Установка REMI репозитория
  ansible.builtin.dnf:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_facts['distribution_major_version'] }}.rpm"
    state: present
    disable_gpg_check: no

- name: Включение модуля PHP {{ php_version }} (DNF Stream)
  ansible.builtin.dnf:
    name: "@php:remi-{{ php_version }}"
    state: present
```

**Для Debian (Ondřej Surý PPA):**
```yaml
- name: Добавление PHP PPA
  ansible.builtin.apt_repository:
    repo: 'ppa:ondrej/php'
    state: present
    update_cache: yes
```

### Сценарий 5: Подготовка Python для работы с БД

Модули `community.mysql` требуют наличия клиентских библиотек Python на целевом хосте.

```yaml
- name: Установка Python-коннектора для MySQL/MariaDB
  ansible.builtin.package:
    name: "{{ mysql_python_package }}"
    state: present
  vars:
    mysql_python_package: "{{ 'python3-pymysql' if ansible_facts['os_family'] == 'Debian' else 'python3-PyMySQL' }}"
```

### Сценарий 6: Работа с Python-зависимостями (Pip и Venv) {#работа-с-python-зависимостями-pip-и-venv}

В современных дистрибутивах (Ubuntu 24.04+, RHEL 9+) прямая установка пакетов через `pip` в системный интерпретатор запрещена (стандарт PEP 668).

```yaml
- name: Установка системных пакетов для работы с venv
  ansible.builtin.package:
    name:
      - python3
      - "{{ 'python3-venv' if ansible_facts['os_family'] == 'Debian' else 'python3-pip' }}"
    state: present

- name: Создание виртуального окружения и установка зависимостей
  ansible.builtin.pip:
    requirements: "/var/www/app/requirements.txt"
    virtualenv: "/var/www/app/venv"
    virtualenv_command: "python3 -m venv"
```

### Сценарий 7: Абстракция путей виртуальных хостов и SSL

Debian-подобные системы используют механизм `sites-available` / `sites-enabled`, в то время как RHEL использует одну директорию `conf.d`.

**Переменные `vars/Debian.yml`:**
```yaml
nginx_conf_path: "/etc/nginx/sites-available"
nginx_enabled_path: "/etc/nginx/sites-enabled"
ssl_cert_path: "/etc/ssl/certs"
```

**Переменные `vars/RedHat.yml`:**
```yaml
nginx_conf_path: "/etc/nginx/conf.d"
nginx_enabled_path: "" # Не используется
ssl_cert_path: "/etc/pki/tls/certs"
```

**Задача активации конфига:**
```yaml
- name: Активация виртуального хоста (симлинк для Debian)
  ansible.builtin.file:
    src: "{{ nginx_conf_path }}/{{ domain_name }}.conf"
    dest: "{{ nginx_enabled_path }}/{{ domain_name }}.conf"
    state: link
  when: ansible_facts['os_family'] == 'Debian'
  notify: Reload Nginx
```

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — фундаментальные паттерны и работа с `ansible_facts`.
- [Развертывание LEMP (Walkthrough)](../examples/tutorial_lemp_stack.md) — пошаговое руководство для Ubuntu.
- [Установка и настройка MySQL/MariaDB](../examples/mysql_setup.md) — детальное руководство по базам данных.
- [Тестирование ролей с Molecule](../ansible_testing_with_molecule.md) — проверка кроссплатформенности в CI (Docker/Vagrant).
- [Переменные в Ansible](../PlaybookStructure/variables.md) — иерархия, приоритеты и использование `hostvars`.
