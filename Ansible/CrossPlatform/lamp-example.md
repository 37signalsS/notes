# Кроссплатформенный пример установки LAMP/LEMP в Ansible

## Определения

- **LAMP/LEMP** — стеки программного обеспечения для веб-приложений.
  - **L**inux — Операционная Система (ОС).
  - **A**pache / **E**Nginx — веб-сервер.
  - **M**ySQL / MariaDB — Система Управления Базами Данных (СУБД).
  - **P**HP — язык программирования.
- **Кроссплатформенный плейбук** — сценарий Ansible, адаптирующийся к различным семействам ОС (Debian/RedHat) через условную логику и абстракцию переменных.

> Глубокое описание механизмов адаптации приведено в руководстве [Кроссплатформенные концепции](./concepts.md).

## Базовые концепции

### Структура кроссплатформенного проекта

Для обеспечения переносимости кода рекомендуется использовать следующую структуру:

**`ansible.cfg`** — настройка окружения для всех участников разработки:

```ini
[defaults]
inventory = inventory
roles_path = roles
host_key_checking = False
```

**Инвентарь (`inventory`)** — группировка хостов по назначению или ОС:

```ini
[web_servers]
srv-ubuntu ansible_host=192.168.1.10
srv-centos ansible_host=192.168.1.20
```

**Основной плейбук** — оркестрация ролей без привязки к конкретной ОС:

```yaml
---
- name: Развертывание стека LAMP/LEMP
  hosts: web_servers
  become: true
  vars:
    php_version: "8.4"
  roles:
    - common
    - nginx
    - mysql
    - php
```

### Ключевые методы адаптации

В данном примере используются:

1. **Динамическое включение задач**: модуль `include_tasks` с фильтром по `ansible_facts['os_family']`.
2. **Абстракция путей**: вынос специфичных для ОС путей в переменные (например, `web_root`).
3. **Нативные менеджеры пакетов**: использование `apt` для Debian и `yum`/`dnf` для RedHat в случаях, когда требуется тонкая настройка репозиториев.

## Практические сценарии

### Установка и настройка веб-сервера Nginx

Различия между ОС проявляются уже на этапе установки (необходимость EPEL репозитория для CentOS) и путей к контенту.

**Реализация для Debian/Ubuntu:**

```yaml
# roles/nginx/tasks/debian.yml
- name: Установка Nginx через apt
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: yes
```

**Реализация для RedHat/CentOS:**

```yaml
# roles/nginx/tasks/redhat.yml
- name: Установка EPEL release
  ansible.builtin.yum:
    name: epel-release
    state: present

- name: Установка Nginx через yum
  ansible.builtin.yum:
    name: nginx
    state: present
```

**Различия в путях к данным:**

| Семейство ОС | Путь по умолчанию (`web_root`) |
| :--- | :--- |
| **Debian** | `/var/www/html` |
| **RedHat** | `/usr/share/nginx/html` |

### Установка СУБД MySQL/MariaDB

Реализация идемпотентной и безопасной установки базы данных для различных семейств ОС вынесена в специализированное SSoT-руководство: **[Установка и настройка MySQL/MariaDB](../examples/mysql_setup.md)**.

### Управление версиями PHP через сторонние репозитории

Для установки актуальных версий PHP (например, 8.4) на стабильные дистрибутивы требуются внешние источники.

**Ubuntu (использование PPA ondrej/php):**

```yaml
# roles/php/tasks/debian.yml
- name: Добавление PPA репозитория PHP
  ansible.builtin.apt_repository:
    repo: "ppa:ondrej/php"
    state: present

- name: Установка PHP-FPM
  ansible.builtin.apt:
    name: "php{{ php_version }}-fpm"
    state: present
```

**CentOS (использование репозитория REMI):**

```yaml
# roles/php/tasks/redhat.yml
- name: Установка REMI release
  ansible.builtin.yum:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_facts['distribution_major_version'] }}.rpm"
    state: present

- name: Включение PHP репозитория REMI
  ansible.builtin.command:
    cmd: "yum-config-manager --enable remi-php{{ php_version | replace('.', '') }}"
  args:
    creates: /etc/yum.repos.d/remi-php.repo
```

### Работа с Python-зависимостями (pip и venv)

Кроссплатформенность в Python-проектах требует внимания к версии системного интерпретатора и изоляции окружений.

```yaml
- name: Установка системных зависимостей для MySQL
  ansible.builtin.package:
    name: "{{ 'python3-pymysql' if ansible_facts['os_family'] == 'Debian' else 'python3-mysql' }}"
    state: present

- name: Установка зависимостей в виртуальное окружение
  ansible.builtin.pip:
    requirements: "/var/www/app/requirements.txt"
    virtualenv: "/var/www/app/venv"
    virtualenv_command: /usr/bin/python3 -m venv
```

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — базовые паттерны и принципы.
- [Установка и настройка MySQL](../examples/mysql_setup.md) — детальный пример для баз данных.
- [Модули управления пакетами](../Modules/ansible_package_management_modules.md) — особенности `apt`, `yum`, `pip`.
- [Роли Ansible](../ansible_roles.md) — организация структуры кроссплатформенного проекта.
