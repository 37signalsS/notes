# Кроссплатформенный пример развертывания LAMP/LEMP

## Определения

- **LAMP/LEMP** — стеки программного обеспечения для веб-приложений:
  - **Linux** — базовая операционная система.
  - **Apache** (LAMP) или **Nginx** (LEMP) — веб-сервер.
  - **MySQL** или **MariaDB** — реляционная СУБД.
  - **PHP** — язык серверного программирования.
- **Кроссплатформенный плейбук (Cross-Platform Playbook)** — сценарий Ansible, способный выполнять идентичные задачи на разных семействах ОС (Debian, RedHat) путем динамической адаптации под специфику дистрибутива.

## Базовые концепции

### Структура кроссплатформенной роли

Для эффективного управления различиями между ОС рекомендуется разделять задачи и переменные. Подробно этот паттерн описан в руководстве **[Кроссплатформенные концепции](./concepts.md)**.

**Пример организации кроссплатформенной роли:**
```text
roles/webserver/
├── defaults/
│   └── main.yml         # Общие параметры (порты, php_version)
├── vars/
│   ├── Debian.yml       # Пакеты и пути для Ubuntu/Debian
│   └── RedHat.yml       # Пакеты и пути для RHEL/Rocky/Alma
└── tasks/
    ├── main.yml         # Точка входа: include_vars + include_tasks
    ├── setup-debian.yml # Установка репозиториев и пакетов Debian
    ├── setup-redhat.yml # Установка репозиториев и пакетов RedHat
    ├── configure.yml    # Общие задачи конфигурации
    └── firewall.yml     # Настройка ufw/firewalld
```

### Абстракция через факты ОС

Ключевым инструментом является использование `ansible_facts`.
- `ansible_facts['os_family']` — для выбора пакетного менеджера и структуры задач.
- `ansible_facts['distribution_major_version']` — для выбора версии сторонних репозиториев (REMI, Ondrej).

## Практические сценарии

### Сценарий 1: Установка веб-сервера (Nginx или Apache)

Имена пакетов и сервисов часто различаются между семействами.

**Пример `vars/RedHat.yml`:**
```yaml
web_package: "nginx" # Или "httpd" для Apache
web_service: "nginx" # Или "httpd"
```

**Пример `vars/Debian.yml`:**
```yaml
web_package: "nginx" # Или "apache2" для Apache
web_service: "nginx" # Или "apache2"
```

**Задача установки:**
```yaml
- name: Установка веб-сервера
  ansible.builtin.package:
    name: "{{ web_package }}"
    state: present
```

### Сценарий 2: Настройка PHP-FPM

В кроссплатформенных сценариях PHP-FPM требует внимания к пользователю процесса и пути к сокету.

| Параметр | Debian/Ubuntu | RHEL/Rocky (Remi) |
| :--- | :--- | :--- |
| **Пользователь** | `www-data` | `nginx` (или `apache`) |
| **Путь к сокету** | `/run/php/php{{ v }}-fpm.sock` | `/run/php-fpm/www.sock` (или TCP) |

**Пример настройки сокета в шаблоне `nginx.conf.j2`:**
```nginx
location ~ \.php$ {
    include fastcgi_params;
    fastcgi_pass unix:{{ php_fpm_socket }};
}
```

### Сценарий 3: Настройка безопасности (SELinux и Firewall)

На RedHat-системах SELinux часто блокирует соединения Nginx с PHP-FPM или внешними базами данных.

```yaml
# tasks/setup-redhat.yml
- name: Разрешить Nginx сетевые соединения в SELinux
  ansible.posix.seboolean:
    name: httpd_can_network_connect
    state: yes
    persistent: yes
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

### Сценарий 4: Подключение свежих репозиториев PHP

Для Ubuntu рекомендуется PPA Ondrej, для RHEL — репозиторий REMI.

**Для RedHat (использование REMI):**
```yaml
- name: Установка REMI репозитория
  ansible.builtin.dnf:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_facts['distribution_major_version'] }}.rpm"
    state: present

- name: Включение модуля PHP {{ php_version }}
  ansible.builtin.dnf:
    name: "@php:remi-{{ php_version }}"
    state: present
```

### Сценарий 5: Подготовка Python для MySQL/MariaDB

Для работы модулей `community.mysql` требуются клиентские библиотеки.

```yaml
- name: Установка Python-коннектора для БД
  ansible.builtin.package:
    name: "{{ mysql_python_package }}"
    state: present
  vars:
    mysql_python_package: "{{ 'python3-pymysql' if ansible_facts['os_family'] == 'Debian' else 'python3-PyMySQL' }}"
```

### Сценарий 6: Работа с Python-зависимостями (Pip и Venv) {#работа-с-python-зависимостями-pip-и-venv}

В современных дистрибутивах (Ubuntu 24.04+, RHEL 9+) прямая установка пакетов через `pip` в системный интерпретатор ограничена (PEP 668). Рекомендуется использовать виртуальные окружения.

```yaml
- name: Установка системных пакетов для Python
  ansible.builtin.package:
    name:
      - python3
      - "{{ 'python3-venv' if ansible_facts['os_family'] == 'Debian' else 'python3-pip' }}"
    state: present

- name: Создание venv и установка зависимостей
  ansible.builtin.pip:
    requirements: "/var/www/app/requirements.txt"
    virtualenv: "/var/www/app/venv"
    virtualenv_command: "python3 -m venv"
```

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — детали реализации паттернов адаптации.
- [Установка и настройка MySQL/MariaDB](../examples/mysql_setup.md) — профильное руководство по БД.
- [Модули управления пакетами](../Modules/ansible_package_management_modules.md) — подробнее об `apt`, `dnf` и `package`.
- [Роли: Стратегии проектирования](../Roles/strategies.md) — организация структуры ролей.
