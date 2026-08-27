# Кроссплатформенный пример развертывания LAMP/LEMP

## Определения

- **LAMP/LEMP** — классические стеки программного обеспечения для веб-серверов:
  - **Linux** — базовая операционная система (ядро инфраструктуры).
  - **Apache** (LAMP) или **Nginx** (LEMP) — веб-сервер, обрабатывающий HTTP-запросы.
  - **MySQL** или **MariaDB** — реляционная система управления базами данных (СУБД).
  - **PHP** — серверный язык программирования для генерации динамического контента.
- **Кроссплатформенный плейбук (Cross-Platform Playbook)** — сценарий Ansible, способный выполнять идентичные задачи на разных семействах ОС (Debian, RedHat, Alpine) путем динамической адаптации под специфику дистрибутива.
- **FQCN (Fully Qualified Collection Name)** — стандарт именования модулей (например, `ansible.builtin.package`), обеспечивающий бесконфликтную работу в разных средах и версиях Ansible.

## Предварительные требования

Для успешного развертывания LAMP/LEMP-стека с помощью Ansible необходимо выполнение следующих условий:

### Версии и компоненты

- **Ansible Core**: версия 2.10 или выше (рекомендуется 2.14+).
- **Python на узлах управления**: Python 3.8 или выше.
- **Python на управляемых хостах**: Минимум Python 2.7 или Python 3.6+ (рекомендуется Python 3.8+ для современных модулей).
- **Целевые ОС**: Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+, CentOS 7+ (с ограничениями).

### Необходимые коллекции

```bash
# Основные коллекции
ansible.builtin
ansible.posix

# Для работы с MySQL/MariaDB
community.mysql

# Для настройки файрвола
community.general
```

Установка необходимых коллекций:
```bash
ansible-galaxy collection install community.mysql community.general ansible.posix
```

### Сетевая доступность и аутентификация

- SSH-доступ к управляемым хостам (порт 22 по умолчанию).
- Параметр `become: true` для выполнения задач с привилегиями root.
- Доступ к интернету для загрузки пакетов и репозиториев.

### Переменные окружения

Перед запуском плейбука необходимо создать файл `vars/vault.yml` с чувствительными данными:

```bash
ansible-vault create vars/vault.yml
```

Пример содержимого `vars/vault.yml`:
```yaml
db_name: "app_database"
db_user: "app_user"
db_password: "SecurePassword123"
php_version: "8.3"
domain_name: "my-site.local"
```

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

## Валидация и проверка

### Проверка синтаксиса плейбука

Перед запуском всегда проверяйте синтаксис:

```bash
ansible-playbook --syntax-check site.yml
# → В случае успеха: "playbook: site.yml"
```

### Проверка на сухом ходу

Визуализация изменений без их применения:

```bash
ansible-playbook --check --diff site.yml --limit web_servers
```

### Проверка идемпотентности

Двойной запуск плейбука должен показать `changed=0` на втором проходе:

```bash
ansible-playbook site.yml --limit web_servers
# Первый запуск: changed=N (где N > 0)
ansible-playbook site.yml --limit web_servers
# Второй запуск: changed=0 (идемпотентность)
```

### Проверка работоспособности сервисов

```bash
# Проверка статуса Nginx
ansible web_servers -m shell -a "systemctl status nginx --no-pager" -b

# Проверка статуса PHP-FPM
ansible web_servers -m shell -a "systemctl status php-fpm --no-pager" -b

# Проверка доступности веб-сервера
curl -I http://your-domain.local
# → Ожидаемый результат: HTTP/1.1 200 OK
```

### Проверка базы данных

```bash
# Проверка подключения к MySQL/MariaDB
ansible web_servers -m shell -a "mysql -u {{ db_user }} -p{{ db_password }} -e 'SELECT 1;'" -b
```

## Устранение типичных неполадок

### Проблема: Ошибка установки пакетов

**Симптом**: `E: Unable to locate package` или `No package available`

**Решение**:
1. Проверьте подключение к интернету.
2. Убедитесь, что репозитории добавлены корректно.
3. Для Debian/Ubuntu: `ansible web_servers -m shell -a "apt update" -b`
4. Для RHEL/Rocky: `ansible web_servers -m shell -a "dnf makecache" -b`

### Проблема: Ошибка подключения к MySQL

**Симптом**: `Access denied for user` или `Can't connect to MySQL server`

**Решение**:
1. Проверьте правильность переменных в `vars/vault.yml`.
2. Убедитесь, что Python-коннектор установлен: `python3-pymysql` (Debian) или `python3-PyMySQL` (RHEL).
3. Проверьте, запущен ли сервис MySQL/MariaDB.

### Проблема: SELinux блокирует соединения

**Симптом**: `Permission denied` при попытке подключения к БД или внешним ресурсам

**Решение**:
```bash
# Проверка статуса SELinux
ansible web_servers -m shell -a "getenforce" -b

# Установка булевых переменных SELinux
ansible web_servers -m shell -a "setsebool -P httpd_can_network_connect 1" -b
ansible web_servers -m shell -a "setsebool -P httpd_can_network_connect_db 1" -b
```

### Проблема: PHP-FPM не работает

**Симптом**: Ошибки в логах Nginx при обработке .php файлов

**Решение**:
1. Проверьте статус PHP-FPM: `systemctl status php-fpm`
2. Убедитесь, что сокет существует: `ls -la /run/php/`
3. Проверьте права доступа к сокету.

### Проблема: Сертификат SSL не работает

**Симптом**: Браузер показывает предупреждение о небезопасном соединении

**Решение**:
1. Проверьте пути к сертификатам в переменных.
2. Убедитесь, что права доступа корректны: `chmod 644 /etc/ssl/certs/*.pem`
3. Проверьте конфигурацию Nginx для SSL.

## Рекомендации и лучшие практики

### Безопасность

1. **Используйте Ansible Vault** для хранения паролей и секретов.
2. **Минимизируйте права доступа**: сервисы должны работать от минимально необходимых пользователей.
3. **Настройте файрвол**: откройте только необходимые порты (22, 80, 443).
4. **Регулярно обновляйте системы**: используйте `ansible.builtin.package` с `state: latest` для критических обновлений.

### Производительность

1. **Оптимизируйте сбор фактов**: используйте `gather_subset` для сбора только необходимых данных.
2. **Кэшируйте пакеты**: для Debian/Ubuntu используйте `apt_cache_valid_time`.
3. **Используйте handlers** для перезапуска сервисов только при изменении конфигурации.

### Сопровождение

1. **Версионируйте роли**: используйте `meta/argument_specs.yml` для документирования входных параметров.
2. **Тестируйте изменения**: используйте Molecule для тестирования на разных платформах.
3. **Документируйте переменные**: создайте README.md для каждой роли.

## Граничные случаи и ограничения

### Поддержка операционных систем

- **Ubuntu 20.04+**: Полная поддержка.
- **Debian 11+**: Полная поддержка.
- **RHEL/Rocky/Alma 8+**: Полная поддержка с учетом SELinux.
- **CentOS 7**: Ограниченная поддержка (устаревшие пакеты, EOL).
- **Alpine Linux**: Требует дополнительной настройки (отсутствуют некоторые пакеты).

### Версии PHP

- **PHP 7.4**: EOL, не рекомендуется для использования.
- **PHP 8.0**: Поддерживается до 2025-11-26.
- **PHP 8.1**: Рекомендуемая версия для новых проектов.
- **PHP 8.2+**: Доступна в дополнительных репозиториях.

### Ограничения кроссплатформенности

1. **Windows**: Данный плейбук не поддерживает Windows (требуется отдельная реализация).
2. **macOS**: Возможна адаптация через Homebrew, но требует значительных изменений.
3. **Контейнеры**: Для Docker-окружений рекомендуется использовать официальные образы.

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — фундаментальные паттерны и работа с `ansible_facts`.
- [Развертывание LEMP (Walkthrough)](../examples/tutorial_lemp_stack.md) — пошаговое руководство для Ubuntu.
- [Установка и настройка MySQL/MariaDB](../examples/mysql_setup.md) — детальное руководство по базам данных.
- [Тестирование ролей с Molecule](../ansible_testing_with_molecule.md) — проверка кроссплатформенности в CI (Docker/Vagrant).
- [Переменные в Ansible](../PlaybookStructure/variables.md) — иерархия, приоритеты и использование `hostvars`.
