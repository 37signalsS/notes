# Развертывание LEMP-стека с помощью Ansible

## Определения

**LEMP (Linux, Nginx, MySQL/MariaDB, PHP)** — популярный и высокопроизводительный набор программного обеспечения с открытым исходным кодом для развертывания динамических веб-приложений.

**Компоненты стека:**
- **Linux** — операционная система, обеспечивающая базовые ресурсы и безопасность.
- **Nginx** (Engine-X) — веб-сервер, известный своей эффективностью при обработке большого количества одновременных соединений, часто используемый как реверс-прокси.
- **MySQL/MariaDB** — реляционные СУБД для надежного хранения и структурирования данных.
- **PHP** (Hypertext Preprocessor) — серверный язык сценариев, обрабатывающий логику приложения.

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 10.x | `ansible --version` |
| Python (управление) | 3.10+ | ≥ 3.12 | `python3 --version` |
| Python (целевые хосты) | 3.10+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` |
| PHP | 8.1+ | 8.3 | `php --version` |
| MariaDB/MySQL | 10.6+ | 10.11 / 8.0 | `mariadb --version` |
| Целевые ОС | Ubuntu 22.04+ / Debian 12+ | Ubuntu 24.04 | `lsb_release -a` |

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
# → Starting galaxy collection install process
# → Process install dependency map
# → Installing 'community.mysql' to ...
```

### Зависимости на целевых хостах

```bash
# Проверка зависимостей (однострочник)
ansible all -m shell -a "dpkg -l | grep -E 'python3-pymysql|python3-certbot|ufw'" --become

# Автоматическая установка зависимостей
ansible all -m apt -a "name=python3-pymysql,ufw state=present update_cache=yes" --become
```

### Сетевая доступность

- SSH-доступ к управляемым хостам (порт 22 по умолчанию).
- Параметр `become: true` для выполнения задач с привилегиями root.
- Доступ к интернету для загрузки пакетов и репозиториев.
- Порты 80 (HTTP) и 443 (HTTPS) открыты на целевых серверах.

### Переменные окружения

Перед запуском плейбука необходимо создать файл `vars/vault.yml` с чувствительными данными с помощью **[Ansible Vault](../Vault/basics.md)**:

```bash
ansible-vault create vars/vault.yml
# → Откроется редактор. Введите следующие переменные:
```

```yaml
db_name: "app_database"
db_user: "app_user"
db_password: "SecureAppPassword123"
php_version: "8.3"
domain_name: "my-site.local"
```

---

## Базовые концепции

### Структура управления и декларативность

| Элемент | Назначение |
|---|---|
| `hosts` | Целевые группы серверов из инвентаря (например, `web_servers`). |
| `become: true` | Выполнение задач с правами суперпользователя через `sudo`. |
| `tasks` | Декларативный список действий для приведения системы к LEMP-стеку. |
| `handlers` | Задачи (Restart/Reload), срабатывающие через `notify` только при изменении конфигурации. |
| `vars` | Параметры для настройки версий (PHP 8.3) и путей. |

### Ключевые модули

| Модуль | Назначение |
|---|---|
| `ansible.builtin.apt` | Установка системных пакетов и управление кэшем |
| `ansible.builtin.apt_repository` | Подключение сторонних PPA (например, для свежих версий PHP) |
| `ansible.builtin.template` | Генерация конфигурационных файлов на основе Jinja2 |
| `ansible.builtin.copy` | Доставка статического контента |
| `community.mysql.mysql_db` | Управление базами данных (требует `python3-pymysql` на хосте) |
| `community.mysql.mysql_user` | Управление пользователями БД |
| `community.general.ufw` | Настройка межсетевого экрана |
| `ansible.builtin.service` | Управление системными сервисами (systemd) |
| `ansible.builtin.file` | Управление файлами, директориями, симлинками |

### Порядок зависимостей между шагами

```
Шаг 1 (Vault) → Шаг 2 (Репозитории) → Шаг 3 (UFW)
                                       → Шаг 4 (Nginx)
                                       → Шаг 5 (MariaDB)
                                       → Шаг 6 (PHP-FPM + Nginx vhost)
                                       → Шаг 7 (Тестовое приложение)
                                       → Шаг 8 (Валидация)
```

**Важно:** каждый шаг зависит от предыдущего. Например, PHP-FPM (Шаг 6) не может работать без Nginx (Шаг 4), а модули MySQL (Шаг 5) требуют `python3-pymysql`.

---

## Практические сценарии

### Сценарий: Развертывание защищенного и актуального LEMP-стека

Современный подход включает использование актуальных репозиториев, настройку безопасности (Firewall, HTTP-заголовки) и автоматическую проверку связности компонентов.

#### Шаг 1: Подготовка переменных и Vault

Чувствительные данные (пароли) должны храниться в зашифрованном виде.

#### Шаг 2: Подготовка ОС и репозиториев (PHP PPA)

Для получения PHP 8.3+ на Ubuntu/Debian рекомендуется использовать репозиторий Ondřej Surý.

```yaml
---
- name: Развертывание защищенного LEMP-стека
  hosts: web_servers
  become: true
  vars_files:
    - vars/vault.yml

  tasks:
    - name: Установка базовых зависимостей
      ansible.builtin.apt:
        name: [software-properties-common, curl, ufw, logrotate]
        state: present
        update_cache: yes

    - name: Добавление репозитория PHP PPA
      ansible.builtin.apt_repository:
        repo: 'ppa:ondrej/php'
        state: present
```

**Валидация:**
```bash
# Проверка добавления PPA
ansible web_servers -m shell -a "grep -r ondrej /etc/apt/sources.list.d/" --become
# → /etc/apt/sources.list.d/ondrej-ubuntu-php-*.list: deb https://ppa.launchpadcontent.net/ondrej/php/ubuntu ...

# Проверка доступности пакетов PHP
ansible web_servers -m shell -a "apt-cache search php8.3-fpm" --become
# → php8.3-fpm - FastCGI Process Manager for PHP
```

#### Шаг 3: Настройка безопасности ОС (UFW)

Настроим firewall для разрешения только необходимых портов (SSH, HTTP, HTTPS).

```yaml
    - name: Настройка UFW (SSH, HTTP, HTTPS)
      community.general.ufw:
        rule: allow
        name: "{{ item }}"
      loop:
        - OpenSSH
        - 'Nginx Full'
      notify: Reload UFW

    - name: Включение UFW
      community.general.ufw:
        state: enabled
```

**Валидация:**
```bash
# Проверка статуса UFW
ansible web_servers -m shell -a "ufw status verbose" --become
# → Status: active
# → To                         Action      From
# --                         ------      ----
# 22/tcp                     ALLOW       Anywhere
# 80/tcp                     ALLOW       Anywhere
# 443/tcp                    ALLOW       Anywhere
```

#### Шаг 4: Установка и закалка Nginx

Удаляем дефолтные страницы и настраиваем директории.

```yaml
    - name: Установка Nginx
      ansible.builtin.apt:
        name: nginx
        state: present

    - name: Удаление стандартной директории веб-сервера
      ansible.builtin.file:
        path: /var/www/html
        state: absent

    - name: Создание корневой директории сайта
      ansible.builtin.file:
        path: "/var/www/{{ domain_name }}"
        state: directory
        owner: www-data
        group: www-data
        mode: '0755'
```

**Валидация:**
```bash
# Проверка статуса Nginx
ansible web_servers -m service -a "name=nginx state=started" --become
# → web_servers | SUCCESS => { "changed": false, "status": { "ActiveState": "active" } }

# Проверка наличия конфигурации
ansible web_servers -m shell -a "nginx -t" --become
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка удаления дефолтной директории
ansible web_servers -m shell -a "ls -la /var/www/" --become
# → drwxr-xr-x 3 www-data www-data 4096 ... html → отсутствует
```

#### Шаг 5: Развертывание базы данных MySQL/MariaDB

Для работы модулей на целевом сервере необходима библиотека `python3-pymysql`. Подробное руководство см. в **[Установка и настройка MySQL/MariaDB](mysql_setup.md)**.

```yaml
    - name: Установка MariaDB и Python-драйвера
      ansible.builtin.apt:
        name: 
          - mariadb-server
          - python3-pymysql
        state: present

    - name: Запуск и включение MariaDB
      ansible.builtin.service:
        name: mariadb
        state: started
        enabled: true

    - name: Создание базы данных приложения
      community.mysql.mysql_db:
        name: "{{ db_name }}"
        state: present
        login_unix_socket: /var/run/mysqld/mysqld.sock

    - name: Создание пользователя БД и выдача прав
      community.mysql.mysql_user:
        name: "{{ db_user }}"
        password: "{{ db_password }}"
        priv: "{{ db_name }}.*:ALL"
        state: present
        login_unix_socket: /var/run/mysqld/mysqld.sock
```

**Валидация:**
```bash
# Проверка статуса MariaDB
ansible web_servers -m service -a "name=mariadb state=started enabled=yes" --become

# Проверка создания базы данных
ansible web_servers -m shell -a "mariadb -e 'SHOW DATABASES;'" --become
# → +--------------------+
# → | Database           |
# → +--------------------+
# → | app_database       |
# → | information_schema |
# → | mysql              |
# → | performance_schema |
# → +--------------------+

# Проверка создания пользователя
ansible web_servers -m shell -a "mariadb -e \"SELECT user, host FROM mysql.user WHERE user='app_user';\"" --become
# → +----------+-----------+
# → | user     | host      |
# → +----------+-----------+
# → | app_user | localhost |
# → +----------+-----------+

# Проверка прав пользователя
ansible web_servers -m shell -a "mariadb -e \"SHOW GRANTS FOR 'app_user'@'localhost';\"" --become
# → GRANT USAGE ON *.* TO 'app_user'@'localhost'
# → GRANT ALL PRIVILEGES ON `app_database`.* TO 'app_user'@'localhost'
```

#### Шаг 6: Установка PHP и интеграция с Nginx

**Шаблон виртуального хоста `templates/nginx-php.conf.j2`:**
Включает базовые заголовки безопасности.

```jinja2
server {
    listen 80;
    server_name {{ domain_name }};
    root /var/www/{{ domain_name }};
    index index.php index.html;

    # Заголовки безопасности
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header X-XSS-Protection "1; mode=block";

    location / {
        try_files $uri $uri/ =404;
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php{{ php_version }}-fpm.sock;
    }

    location ~ /\.ht {
        deny all;
    }
}
```

**Задачи интеграции в плейбуке:**

```yaml
    - name: Установка PHP-FPM и расширений
      ansible.builtin.apt:
        name:
          - "php{{ php_version }}-fpm"
          - "php{{ php_version }}-mysql"
          - "php{{ php_version }}-gd"
        state: present

    - name: Настройка виртуального хоста Nginx
      ansible.builtin.template:
        src: templates/nginx-php.conf.j2
        dest: "/etc/nginx/sites-available/{{ domain_name }}.conf"
      notify: Reload Nginx

    - name: Активация конфигурации Nginx (симлинк)
      ansible.builtin.file:
        src: "/etc/nginx/sites-available/{{ domain_name }}.conf"
        dest: "/etc/nginx/sites-enabled/{{ domain_name }}.conf"
        state: link
      notify: Reload Nginx
```

**Валидация:**
```bash
# Проверка установки PHP-FPM
ansible web_servers -m shell -a "php8.3-fpm -v" --become
# → PHP 8.3.x (cli) (built: ...)

# Проверка работы PHP-FPM
ansible web_servers -m service -a "name=php8.3-fpm state=started" --become
# → web_servers | SUCCESS => { "changed": false }

# Проверка наличия сокета
ansible web_servers -m shell -a "ls -la /var/run/php/php8.3-fpm.sock" --become
# → srw-rw---- 1 www-data www-data 0 ... /var/run/php/php8.3-fpm.sock

# Проверка конфигурации Nginx
ansible web_servers -m shell -a "nginx -t" --become
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok

# Проверка симлинка
ansible web_servers -m shell -a "ls -la /etc/nginx/sites-enabled/" --become
# → lrwxrwxrwx 1 root root ... my-site.local.conf -> /etc/nginx/sites-available/my-site.local.conf
```

#### Шаг 7: Развертывание тестового приложения и верификация

Использование шаблонов предотвращает передачу паролей в открытом виде.

**Шаблон `templates/db_test.php.j2`:**

```jinja2
<?php
$mysqli = new mysqli("localhost", "{{ db_user }}", "{{ db_password }}", "{{ db_name }}");
if ($mysqli->connect_errno) {
  echo "Ошибка подключения: " . $mysqli->connect_error;
  exit();
}
echo "Соединение успешно. База: {{ db_name }}, Версия сервера: " . $mysqli->server_info;
$mysqli->close();
?>
```

**Задачи развертывания тестов:**

```yaml
    - name: Создание тестового файла phpinfo
      ansible.builtin.copy:
        content: "<?php phpinfo(); ?>"
        dest: "/var/www/{{ domain_name }}/index.php"
        owner: www-data
        mode: '0644'

    - name: Создание скрипта проверки БД из шаблона
      ansible.builtin.template:
        src: templates/db_test.php.j2
        dest: "/var/www/{{ domain_name }}/db_test.php"
        owner: www-data
        mode: '0644'

  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded

    - name: Restart PHP-FPM
      ansible.builtin.service:
        name: "php{{ php_version }}-fpm"
        state: restarted

    - name: Reload UFW
      community.general.ufw:
        state: reloaded
```

**Валидация:**
```bash
# Проверка наличия файлов
ansible web_servers -m shell -a "ls -la /var/www/my-site.local/" --become
# → -rw-r--r-- 1 www-data www-data ... db_test.php
# → -rw-r--r-- 1 www-data www-data ... index.php

# Проверка прав на файлы
ansible web_servers -m shell -a "stat -c '%U:%G %a' /var/www/my-site.local/*.php" --became
# → www-data:www-data 644
# → www-data:www-data 644
```

#### Шаг 8: Запуск и проверка

Выполнение плейбука с запросом пароля Vault:

```bash
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass
```

**Полная команда с отладкой:**
```bash
# Запуск с выводом отладки
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass -vvv

# Запуск только определенного шага (например, установка БД)
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass --tags "database"

# Dry Run (проверка без изменений)
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass --check --diff

# Запуск на конкретном хосте
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass --limit web1
```

**Проверка работоспособности стека:**

1.  **Настройка локальных хостов**: Добавьте `127.0.0.1 my-site.local` в файл `/etc/hosts`.
2.  **Проверка PHP**: Откройте `http://my-site.local` — должна отобразиться страница `phpinfo`.
3.  **Проверка базы данных**: Откройте `http://my-site.local/db_test.php` — ожидается сообщение об успешном соединении.

**Валидация через curl:**
```bash
# Проверка HTTP-ответа Nginx
ansible web_servers -m shell -a "curl -s -o /dev/null -w '%{http_code}' http://my-site.local/"
# → 200

# Проверка PHP-FPM через Nginx
ansible web_servers -m shell -a "curl -s http://my-site.local/ | grep 'PHP Version'"
# → <td class="e">PHP Version</td><td class="v">8.3.x</td>

# Проверка подключения к БД
ansible web_servers -m shell -a "curl -s http://my-site.local/db_test.php"
# → Соединение успешно. База: app_database, Версия сервера: 10.11.x-MariaDB

# Проверка обработчиков
ansible web_servers -m shell -a "systemctl status nginx --no-pager | head -5" --become
# → ● nginx.service - A high performance web server and a reverse proxy server
# →      Loaded: loaded (/lib/systemd/system/nginx.service; enabled; ...)
# →      Active: active (running) since ...
```

**Проверка идемпотентности:**
```bash
# Второй запуск должен показать 0 changed
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass 2>&1 | grep "changed"
# → localhost                  : ok=XX   changed=0    unreachable=0    failed=0
```

---

## Инвентарь и структура проекта

### Пример инвентаря (inventory.ini)

```ini
[web_servers]
web1 ansible_host=10.0.5.20 ansible_user=deploy
web2 ansible_host=10.0.5.21 ansible_user=deploy

[web_servers:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_become=true
ansible_become_method=sudo
```

### Структура директорий

```
lemp-project/
├── playbook.yml
├── hosts.ini
├── vars/
│   └── vault.yml          # Зашифрованные пароли
├── templates/
│   ├── nginx-php.conf.j2  # Шаблон виртуального хоста Nginx
│   └── db_test.php.j2     # Тестовый PHP-скрипт
└── README.md
```

### Чек-лист валидации после развертывания

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| UFW активен | `ufw status` | `Status: active` |
| Nginx запущен | `systemctl status nginx` | `active (running)` |
| Nginx конфигурация | `nginx -t` | `syntax is ok` |
| PHP-FPM запущен | `systemctl status php8.3-fpm` | `active (running)` |
| PHP-FPM сокет | `ls /var/run/php/php8.3-fpm.sock` | Файл существует |
| MariaDB запущена | `systemctl status mariadb` | `active (running)` |
| БД создана | `mariadb -e 'SHOW DATABASES;'` | `app_database` в списке |
| Пользователь БД | `mariadb -e "SELECT user FROM mysql.user;"` | `app_user` в списке |
| HTTP отвечает | `curl -s -o /dev/null -w '%{http_code}' http://localhost/` | `200` |
| PHP работает | `curl -s http://localhost/ \| grep PHP` | Строка с версией PHP |
| БД доступна | `curl -s http://localhost/db_test.php` | `Соединение успешно` |
| Идемпотентность | Второй запуск плейбука | `changed=0` |

---

## Устранение типичных неполадок

### Проблема: Ошибка `python3-pymysql not found`

**Симптом:** `Failed to import the required Python library (PyMySQL)`.

**Решение:**
```bash
# Установка на целевых хостах
ansible web_servers -m apt -a "name=python3-pymysql state=present" --become

# Проверка установки
ansible web_servers -m shell -a "python3 -c 'import pymysql; print(pymysql.__version__)'" --become
# → 1.0.2
```

### Проблема: PHP-FPM не подключается к Nginx

**Симптом:** 502 Bad Gateway при открытии страницы.

**Решение:**
```bash
# Проверка сокета
ansible web_servers -m shell -a "ls -la /var/run/php/php8.3-fpm.sock" --become

# Проверка прав доступа к сокету
ansible web_servers -m shell -a "sudo -u www-data ls -la /var/run/php/" --become

# Перезапуск PHP-FPM
ansible web_servers -m service -a "name=php8.3-fpm state=restarted" --become
```

### Проблема: MariaDB не запускается

**Симптом:** `Job for mariadb.service failed`.

**Решение:**
```bash
# Проверка логов
ansible web_servers -m shell -a "journalctl -u mariadb --no-pager -n 20" --become

# Проверка порта
ansible web_servers -m shell -a "ss -tlnp | grep 3306" --become

# Проверка конфигурации
ansible web_servers -m shell -a "mariadb-check --all-databases" --become
```

### Проблема: UFW блокирует соединения

**Симптом:** curl не может подключиться к серверу.

**Решение:**
```bash
# Проверка правил UFW
ansible web_servers -m shell -a "ufw status numbered" --become

# Добавление правила
ansible web_servers -m shell -a "ufw allow 80/tcp" --become
ansible web_servers -m shell -a "ufw reload" --become
```

### Проблема: PPA не добавляется

**Симпptom:** `Failed to add PPA` или `Unable to locate package php8.3-fpm`.

**Решение:**
```bash
# Обновление ключей GPG
ansible web_servers -m shell -a "apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 4F4EA0AAE5267A6C" --become

# Очистка кэша apt
ansible web_servers -m apt -a "update_cache=yes" --become

# Проверка доступности пакетов
ansible web_servers -m shell -a "apt-cache policy php8.3-fpm" --become
```

---

## Дополнительная информация

### Масштабирование и SSL (HTTPS)

- **Настройка HTTPS (Certbot)**: В современном веб-окружении SSL обязателен. Рекомендуется использовать роль `geerlingguy.certbot` или модуль `ansible.builtin.command` для вызова `certbot --nginx`.
- **Универсальность**: Данный пример ориентирован на Debian/Ubuntu. Для RHEL/CentOS необходимо использовать модули `ansible.builtin.yum/dnf` и учитывать различия в путях конфигураций Nginx. Подробнее: **[Кроссплатформенные плейбуки](../CrossPlatform/concepts.md)**.
- **Мониторинг**: Включите статус-страницу PHP-FPM для сбора метрик. Подробнее: **[Мониторинг PHP-FPM](../../WebServers/PHP/php-fpm-monitoring.md)**.
- **Рефакторинг**: Для крупных проектов выносите логику в отдельные **[роли Ansible](../ansible_roles.md)**.

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| PHP 8.1 на старых ОС | PPA недоступен | Используйте `apt-get install php-fpm` из официальных репозиториев |
| MySQL вместо MariaDB | Разные имена сервисов | Замените `mariadb` на `mysql` в `ansible.builtin.service` |
| SELinux на CentOS/RHEL | Блокирует соединения | Добавьте `setsebool -P httpd_can_network_connect 1` |
| Несколько сайтов | Конфликт виртуальных хостов | Используйте `server_name` для маршрутизации запросов |
| IPv6 | Nginx слушает только IPv4 | Добавьте `listen [::]:80;` в конфигурацию |

---

## Смотрите также

- [Установка и настройка MySQL/MariaDB через Ansible](mysql_setup.md)
- [Кроссплатформенный пример развертывания LAMP](../CrossPlatform/lamp-example.md)
- [Шаблонизация Jinja2 в Ansible](../ansible_jinja_templating.md)
- [Обзор возможностей Nginx](../../WebServers/Nginx/Core/nginx_overview.md)
