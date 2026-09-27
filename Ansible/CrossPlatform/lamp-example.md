# Кроссплатформенный пример развертывания LAMP/LEMP

## Определения

- **LAMP/LEMP** — классические стеки программного обеспечения для веб-серверов:
  - **Linux** — базовая операционная система (ядро инфраструктуры).
  - **Apache** (LAMP) или **Nginx** (LEMP) — веб-сервер, обрабатывающий HTTP-запросы.
  - **MySQL** или **MariaDB** — реляционная система управления базами данных (СУБД).
  - **PHP** — серверный язык программирования для генерации динамического контента; в связке с Nginx используется через PHP-FPM (FastCGI Process Manager).
- **Кроссплатформенный плейбук (Cross-Platform Playbook)** — сценарий Ansible, способный выполнять идентичные задачи на разных семействах ОС (Debian, RedHat, Alpine) путем динамической адаптации под специфику дистрибутива.
- **FQCN (Fully Qualified Collection Name)** — стандарт именования модулей (например, `ansible.builtin.package`), обеспечивающий бесконфликтную работу в разных средах и версиях Ansible.
- **Идемпотентность** — свойство задач Ansible сохранять целевое состояние системы при многократных запусках; повторный запуск роли не должен давать `changed` по перечню задач, если конфигурация уже соответствует желаемому состоянию.
- **Control Node** — узел, на котором установлен ansible-core и запускаются `ansible-playbook`/`ansible`. Управляемые узлы (Managed Nodes) не требуют установки Ansible.
- **Become** — механизм выполнения задач от другого пользователя (обычно root/Administrator): `sudo`/`su` на POSIX-системах.

## Архитектура и принципы работы

### Жизненный цикл LAMP/LEMP-стека

LAMP/LEMP-стек работает как цепочка обработки HTTP-запросов:

1. Клиент отправляет HTTP-запрос на веб-сервер (порт 80/443).
2. **Nginx** обслуживает статические файлы напрямую (изображения, CSS, JS).
3. Для PHP-скриптов Nginx передает запрос PHP-FPM через Unix-сокет или TCP.
4. **PHP-FPM** обрабатывает скрипт, при необходимости обращается к **MySQL/MariaDB**.
5. Результат возвращается обратно через цепочку PHP-FPM → Nginx → Клиент.

### Зависимости между компонентами

Каждый компонент зависит от предыдущего:
- Базовые пакеты и репозитории должны быть подключены до установки конкретных версий.
- Файрвол настраивается до запуска веб-сервисов, чтобы не открывать лишние порты на промежуточных этапах.
- Nginx развертывается до PHP-FPM, потому что конфигурация виртуального хоста зависит от путей и существования директорий.
- PHP-FPM интегрируется с Nginx через симлинки или директории конфигурации, поэтому Nginx должен быть уже установлен.
- Модули `ansible.mysql` требуют наличия Python-коннектора на целевом хосте.

### Идентификация операционной системы

Ansible использует агентскую (agentless) модель: модуль `ansible.builtin.setup` подключается к узлу по SSH, выполняет на нем Python и возвращает словарь фактов. Для кроссплатформенности критически важно использование синтаксиса `ansible_facts['os_family']` вместо устаревшего плоского формата.

Ключевые факты для LAMP/LEMP-роли:
- `ansible_facts['os_family']` — для выбора пакетного менеджера (APT vs DNF) и структуры задач.
- `ansible_facts['distribution_major_version']` — для выбора версии сторонних репозиториев (например, REMI для RHEL 8 vs 9).
- `ansible_facts['distribution_release']` — для формирования путей в APT репозиториях (например, `jammy` для Ubuntu 22.04).
- `ansible_facts['pkg_mgr']` — обнаруженный пакетный менеджер (`apt`, `dnf`, `apk`).
- `ansible_facts['service_mgr']` — процесс инициализации (`systemd`, `openrc`, `launchd`).

Детальнее о фактах и стратегиях кроссплатформенности — в [Кроссплатформенные концепции](./concepts.md).

## Предварительные требования

### Версии и компоненты

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.19+ | 2.21+ (стабильная на май 2026) | `ansible --version` |
| **Python (Control Node)** | 3.11+ | 3.12–3.14 | `python3 --version` |
| **Python (Managed Nodes, POSIX)** | 3.9+ | 3.11+ | `ansible all -m setup -a "filter=ansible_python_version"` |
| **Целевые ОС** | Ubuntu 22.04+, Debian 12+, RHEL/Rocky/Alma 8+ | Ubuntu 24.04 LTS, Debian 13 | `lsb_release -a` |

> **Важно:** CentOS 7 достиг EOL и не поддерживается современными ansible-core (отсутствует совместимый Python 3.9+). Для унаследованных систем используйте ansible-core 2.14 с Python 2.7 или 3.6, либо мигрируйте на Rocky/Alma Linux.

### Необходимые коллекции

```yaml
# requirements.yml
collections:
  - name: ansible.posix          # firewalld, seboolean, sysctl, mount
  - name: ansible.mysql          # mysql_db, mysql_user, mysql_replication
  - name: community.general      # ufw, homebrew, apparmor, pacman
```

Установка коллекций:
```bash
ansible-galaxy collection install -r requirements.yml
# → Starting galaxy collection install process
# → Process install dependency map
```

### Сетевая доступность и аутентификация

- SSH-доступ к управляемым хостам (порт 22 по умолчанию).
- Параметр `become: true` для выполнения задач с привилегиями root.
- Доступ к интернету для загрузки пакетов и репозиториев.
- Порты 80 (HTTP) и 443 (HTTPS) открыты на целевых серверах или разрешены файрволом.

### Переменные окружения

Перед запуском плейбука создайте файл `vars/vault.yml` с чувствительными данными:

```bash
ansible-vault create vars/vault.yml
# → Откроется редактор. Введите переменные:
```

```yaml
# Файл vars/vault.yml (хранится в зашифрованном виде)
db_name: "app_database"
db_user: "app_user"
db_password: "{{ vault_db_password }}"
php_version: "8.3"
domain_name: "my-site.local"
```

> **Безопасность:** Никогда не храните пароли в открытом виде в плейбуках или inventory. Используйте Ansible Vault. В примерах ниже переменные с префиксом `vault_` обозначают значения, хранящиеся в зашифрованном файле.

## Структура кроссплатформенной роли

Для эффективного управления различиями между дистрибутивами Linux рекомендуется разделять задачи и переменные. Это позволяет сохранить файл задач (`tasks/main.yml`) чистым, вынося всю специфику в `vars/`.

**Рекомендуемая структура каталогов:**
```text
roles/webserver/
├── meta/
│   └── argument_specs.yml     # Валидация входных данных (PHP версия, стек)
├── defaults/
│   └── main.yml               # Общие безопасные параметры (порты, лимиты)
├── vars/
│   ├── Debian.yml             # Специфика Ubuntu/Debian (пути, пакеты)
│   ├── RedHat.yml             # Специфика RHEL/Rocky/Alma (SELinux, пути)
│   └── default.yml            # Резервные значения
└── tasks/
    ├── main.yml               # Точка входа: include_vars + include_tasks
    ├── setup-debian.yml       # Репозитории Ondřej Surý, PPA
    ├── setup-redhat.yml       # Репозитории REMI, EPEL
    ├── configure.yml          # Универсальные шаблоны Nginx/PHP
    └── firewall.yml           # Адаптация под ufw (Debian) или firewalld (RHEL)
```

### Абстракция через факты ОС

Использование словаря `ansible_facts` является обязательным для кроссплатформенности:
- `ansible_facts['os_family']` — для выбора пакетного менеджера (APT vs DNF) и структуры задач.
- `ansible_facts['distribution_major_version']` — для выбора версии сторонних репозиториев.
- `ansible_facts['distribution_release']` — для формирования путей в APT репозиториях.

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

Модули `ansible.mysql` требуют наличия клиентских библиотек Python на целевом хосте.

```yaml
- name: Установка Python-коннектора для MySQL/MariaDB
  ansible.builtin.package:
    name: "{{ mysql_python_package }}"
    state: present
  vars:
    mysql_python_package: "{{ 'python3-pymysql' if ansible_facts['os_family'] == 'Debian' else 'python3-PyMySQL' }}"
```

### Сценарий 6: Работа с Python-зависимостями (Pip и Venv)

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

### Сценарий 8: Bootstrap узлов без Python

Python на целевом узле не всегда предустановлен (минимальные контейнеры, старые дистрибутивы). Без Python не работает ни факт-сбор, ни модули — только `ansible.builtin.raw` и `ansible.builtin.script`, которые выполняют команды через shell. Bootstrap выполняется в отдельном плейбуке с `gather_facts: false`:

```yaml
# bootstrap_play.yml
- name: Установка Python перед основным запуском
  hosts: all
  gather_facts: false          # фактов нет — Python еще не установлен
  become: true
  tasks:
    - name: Debian/Ubuntu
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      when: "'debian' in group_names"
    - name: RHEL-семейство
      ansible.builtin.raw: dnf install -y python3
      when: "'rhel' in group_names"
    - name: Alpine
      ansible.builtin.raw: apk add python3
      when: "'alpine' in group_names"

- name: Основной плейбук
  hosts: all
  tasks:
    - name: Теперь доступен полный набор фактов и модулей
      ansible.builtin.package:
        name: htop
        state: present
```

После bootstrap сбор фактов идет штатно. Для узлов с нестандартным интерпретатором явно задайте путь:

```ini
# inventory.ini — группа [rhel8:vars]
[rhel8:vars]
ansible_python_interpreter=/usr/bin/python3
```

```ini
# ansible.cfg — тихое автообнаружение вместо предупреждающего auto
[defaults]
interpreter_python=auto_silent
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
# → ok=1 changed=0 без применения изменений
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
# → Active: active (running)

# Проверка статуса PHP-FPM
ansible web_servers -m shell -a "systemctl status php-fpm --no-pager" -b
# → Active: active (running)

# Проверка доступности веб-сервера
curl -I http://your-domain.local
# → HTTP/1.1 200 OK
```

### Проверка базы данных

```bash
# Проверка подключения к MySQL/MariaDB (с использованием .my.cnf)
ansible web_servers -m shell -a "mysql -e 'SELECT 1;'" -b
# → 1
```

> **Примечание:** Избегайте передачи паролей через аргументы командной строки (они попадают в историю shell и логи). Используйте файл `/root/.my.cnf` или Ansible Vault. В production-средах добавляйте `no_log: true` к задачам, работающим с паролями.

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible-playbook --syntax-check site.yml` | Проверка синтаксиса | `playbook: site.yml` |
| `ansible-playbook site.yml --check --diff --limit web_servers` | Сухой прогон с диффами | `ok`/`changed` без применения изменений |
| `ansible-playbook site.yml --list-tasks` | Список задач до выполнения | Список задач без выполнения |
| `ansible-inventory --graph --vars` | Граф групп и переменных инвентаря | Дерево групп и переменных хостов |
| `ansible web_servers -m ansible.builtin.setup -a "filter=ansible_os_family*"` | Просмотр фактов семейства ОС | `"ansible_facts": { "os_family": "Debian" }` |
| `ansible all -m ansible.builtin.setup -a "gather_subset=!all,min,distribution"` | Быстрый сбор фактов дистрибутива | Перечень хостов с фактами |
| `ansible web_servers -m shell -a "nginx -t" -b` | Проверка конфигурации Nginx | `syntax is ok`, `test is successful` |
| `ansible web_servers -m shell -a "php -v" -b` | Проверка версии PHP | `PHP 8.3.x (cli)` |
| `ansible web_servers -m shell -a "mysql -V" -b` | Проверка версии MySQL/MariaDB | `Ver 15.1 Distrib 10.11.x-MariaDB` |
| `ansible-doc ansible.posix.firewalld` | Справка по модулю firewalld | Документация по параметрам модуля |
| `ansible-lint .` | Статический анализ плейбуков/ролей | Отчет о нарушениях правил |
| `ansible-galaxy collection install -r requirements.yml` | Установка коллекций по манифесту | Список установленных коллекций |

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
4. Для MySQL 8.0+ убедитесь, что пользователь создан с правильным плагином аутентификации (`caching_sha2_password` или `mysql_native_password` для совместимости).

### Проблема: SELinux блокирует соединения

**Симптом**: `Permission denied` при попытке подключения к БД или внешним ресурсам

**Решение**:
```bash
# Проверка статуса SELinux
ansible web_servers -m shell -a "getenforce" -b
# → Enforcing

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
4. Проверьте конфигурацию Nginx: `nginx -t`

### Проблема: Сертификат SSL не работает

**Симптом**: Браузер показывает предупреждение о небезопасном соединении

**Решение**:
1. Проверьте пути к сертификатам в переменных.
2. Убедитесь, что права доступа корректны: `chmod 644 /etc/ssl/certs/*.pem`
3. Проверьте конфигурацию Nginx для SSL.

### Проблема: Факты не собираются

**Симптом**: `module 'setup'` не найден или факты пустые

**Решение**:
1. Убедитесь, что Python установлен на целевом хосте.
2. Проверьте переменную `ansible_python_interpreter` в inventory.
3. Для минимальных контейнеров выполните bootstrap (Сценарий 8).

## Рекомендации и лучшие практики

### Безопасность

1. **Используйте Ansible Vault** для хранения паролей и секретов. Добавляйте `no_log: true` к задачам, работающим с паролями.
2. **Минимизируйте права доступа**: сервисы должны работать от минимально необходимых пользователей.
3. **Настройте файрвол**: откройте только необходимые порты (22, 80, 443).
4. **Регулярно обновляйте системы**: используйте `ansible.builtin.package` с `state: latest` для критических обновлений.
5. **Используйте `validate` параметр**: для шаблонов Nginx добавляйте `validate: "nginx -t -c %s"`, чтобы откатить изменения при ошибке синтаксиса.

### Производительность

1. **Оптимизируйте сбор фактов**: используйте `gather_subset` для сбора только необходимых данных.
2. **Кэшируйте пакеты**: для Debian/Ubuntu используйте `apt_cache_valid_time`.
3. **Используйте handlers** для перезапуска сервисов только при изменении конфигурации.
4. **Ограничивайте сбор фактов** на больших парках: `gather_subset: ['!all', '!min', 'distribution', 'os_family']`.

### Сопровождение

1. **Версионируйте роли**: используйте `meta/argument_specs.yml` для документирования входных параметров.
2. **Тестируйте изменения**: используйте Molecule для тестирования на разных платформах.
3. **Документируйте переменные**: создайте README.md для каждой роли.
4. **Используйте `changed_when`** для модулей `command`/`shell`, чтобы сохранить идемпотентность.

### Деплой и откат

1. **Check Mode перед деплоем**: всегда запускайте `ansible-playbook site.yml --check --diff --limit web_servers` перед применением на продакшен.
2. **Validate параметр**: для шаблонов Nginx добавляйте `validate: "nginx -t -c %s"`, чтобы откатить изменения при ошибке синтаксиса.
3. **Canary deployment**: начинайте с `serial: 1` на одном хосте, проверяйте health-check, затем расширяйте на весь парк.
4. **Rollback через tags**: используйте `tags: [rollback]` для задач отката, которые не должны выполняться при обычном деплое.
5. **Health-check после деплоя**: интегрируйте `ansible.builtin.uri` с `until`/`retries`/`delay` для автоматической проверки работоспособности.
6. **Configuration snapshot**: создавайте бэкап конфигов перед изменением через `command: cp` или `synchronize`.

## Граничные случаи и ограничения

### Поддержка операционных систем

- **Ubuntu 22.04+**: Полная поддержка.
- **Debian 12+**: Полная поддержка.
- **RHEL/Rocky/Alma 8+**: Полная поддержка с учетом SELinux.
- **CentOS 7**: Ограниченная поддержка (устаревшие пакеты, EOL). Требует ansible-core 2.14 или ниже.
- **Alpine Linux**: Требует дополнительной настройки (отсутствуют некоторые пакеты, OpenRC вместо systemd).

### Версии PHP

- **PHP 7.4**: EOL, не рекомендуется для использования.
- **PHP 8.0**: EOL 2025-11-26.
- **PHP 8.1**: Поддерживается до 2025-11-26.
- **PHP 8.2+**: Рекомендуемая версия для новых проектов, доступна в дополнительных репозиториях.

### Ограничения кроссплатформенности

1. **Windows**: Данный плейбук не поддерживает Windows (требуется отдельная реализация).
2. **macOS**: Возможна адаптация через Homebrew, но требует значительных изменений.
3. **Контейнеры**: Для Docker-окружений рекомендуется использовать официальные образы.

## Дополнительная информация

- [Кроссплатформенные концепции](./concepts.md) — фундаментальные паттерны и работа с `ansible_facts`, матрица платформ, типичные проблемы кроссплатформенности.
- [Кроссплатформенное выполнение](./ansible_cross_platform_execution_flow.md) — `strategy`, `serial`, `throttle`, `check_mode`, `async`, `tags`, `--limit` в mixed-парках.
- [Кроссплатформенный инвентарь и факты](./ansible_cross_platform_inventory_and_facts.md) — динамический инвентарь, constructed plugin, host patterns, fact caching.
- [Кроссплатформенные соединения](./ansible_cross_platform_connection.md) — SSH-тюнинг, WinRM, bastion, connection plugins.
- [Кроссплатформенная конфигурация системы](./ansible_cross_platform_system_config.md) — `sysctl`, NTP/timezone, systemd timers, логи, файловые системы.
- [Кроссплатформенный откат и drift detection](./ansible_cross_platform_rollback_testing_drift.md) — rollback стратегии, canary, drift detection в CI/CD, Molecule.
- [Установка и настройка MySQL/MariaDB](../examples/mysql_setup.md) — детальное руководство по базам данных, репликации, SSL/TLS.
- [Переменные в Ansible](../PlaybookStructure/variables.md) — иерархия, приоритеты и использование `ansible_facts`.
