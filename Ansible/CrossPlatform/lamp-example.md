# Кроссплатформенный пример развертывания LAMP/LEMP

## Определения

- **LAMP/LEMP** — стеки программного обеспечения для веб-приложений:
  - **Linux** — операционная система.
  - **Apache** (LAMP) или **Nginx** (LEMP) — веб-сервер.
  - **MySQL** или **MariaDB** — реляционная СУБД.
  - **PHP** — язык программирования.
- **Кроссплатформенный плейбук** — сценарий Ansible, способный выполнять идентичные задачи на разных семействах ОС (Debian, RedHat) путем динамической адаптации под специфику дистрибутива.

## Базовые концепции

### Структура кроссплатформенной роли

Для эффективного управления различиями между ОС рекомендуется разделять задачи и переменные. Подробно этот паттерн описан в руководстве **[Кроссплатформенные концепции](./concepts.md)**.

**Пример организации роли `nginx`:**
```text
roles/nginx/
├── defaults/
│   └── main.yml         # Общие параметры (порты, лимиты)
├── vars/
│   ├── Debian.yml       # Пути и пакеты для Ubuntu/Debian
│   └── RedHat.yml       # Пути и пакеты для RHEL/Rocky/Alma
└── tasks/
    ├── main.yml         # Точка входа: include_vars + include_tasks
    ├── debian.yml       # Специфичные задачи для Debian
    └── redhat.yml       # Специфичные задачи для RedHat
```

### Динамическая загрузка конфигурации

Вместо жесткого кодирования путей в задачах, используйте паттерн `include_vars` в `tasks/main.yml`:

```yaml
- name: Загрузка переменных ОС
  ansible.builtin.include_vars: "{{ ansible_facts['os_family'] }}.yml"

- name: Выполнение задач ОС
  ansible.builtin.include_tasks: "{{ ansible_facts['os_family'] | lower }}.yml"
```

## Практические сценарии

### Сценарий 1: Установка веб-сервера (Nginx)

Различия заключаются в названиях пакетов и необходимости подключения EPEL для RHEL-систем.

#### Реализация для Debian (Ubuntu)
```yaml
# tasks/debian.yml
- name: Установка Nginx
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: yes
```

#### Реализация для RedHat (Rocky Linux, AlmaLinux)
```yaml
# tasks/redhat.yml
- name: Установка EPEL
  ansible.builtin.dnf:
    name: epel-release
    state: present

- name: Установка Nginx
  ansible.builtin.dnf:
    name: nginx
    state: present
```

### Сценарий 2: Настройка PHP через внешние репозитории

Для получения свежих версий PHP (8.3+) требуются репозитории Ondrej (Debian) или REMI (RedHat).

#### Подготовка в RedHat (использование DNF модулей)
```yaml
- name: Установка репозитория REMI
  ansible.builtin.dnf:
    name: "https://rpms.remirepo.net/enterprise/remi-release-{{ ansible_facts['distribution_major_version'] }}.rpm"
    state: present
    disable_gpg_check: no

- name: Сброс текущего модуля PHP
  ansible.builtin.dnf:
    name: "@php"
    state: absent

- name: Включение модуля PHP {{ php_version }} из REMI
  ansible.builtin.dnf:
    name: "@php:remi-{{ php_version }}"
    state: present
```

### Сценарий 3: Параметризация путей и пользователей

Разные ОС используют разные стандарты для путей к веб-контенту и пользователей сервисов. Эти данные должны храниться в `vars/`.

**Пример `vars/Debian.yml`:**
```yaml
web_root: "/var/www/html"
web_user: "www-data"
```

**Пример `vars/RedHat.yml`:**
```yaml
web_root: "/usr/share/nginx/html"
web_user: "nginx"
```

**Использование в задачах:**
```yaml
- name: Копирование контента сайта
  ansible.builtin.copy:
    src: index.html
    dest: "{{ web_root }}/index.html"
    owner: "{{ web_user }}"
    group: "{{ web_user }}"
```

### Сценарий 4: Настройка Python для MySQL

Модуль `community.mysql` требует наличия клиентской библиотеки Python на целевом хосте.

```yaml
- name: Установка Python-библиотеки для MySQL
  ansible.builtin.package:
    name: "{{ 'python3-pymysql' if ansible_facts['os_family'] == 'Debian' else 'python3-PyMySQL' }}"
    state: present
```

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — детали реализации паттернов адаптации.
- [Установка и настройка MySQL/MariaDB](../examples/mysql_setup.md) — профильное руководство по БД.
- [Модули управления пакетами](../Modules/ansible_package_management_modules.md) — подробнее об `apt`, `dnf` и `package`.
- [Роли: Стратегии проектирования](../Roles/strategies.md) — организация структуры ролей.
