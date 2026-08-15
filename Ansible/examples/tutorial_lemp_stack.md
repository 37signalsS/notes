# Развертывание LEMP-стека с помощью Ansible

## Определения

**LEMP (Linux, Nginx, MySQL/MariaDB, PHP)** — популярный и высокопроизводительный набор программного обеспечения с открытым исходным кодом для развертывания динамических веб-приложений.

**Компоненты стека:**
- **Linux** — операционная система, обеспечивающая базовые ресурсы и безопасность.
- **Nginx** (Engine-X) — веб-сервер, известный своей эффективностью при обработке большого количества одновременных соединений, часто используемый как реверс-прокси.
- **MySQL/MariaDB** — реляционные СУБД для надежного хранения и структурирования данных.
- **PHP** (Hypertext Preprocessor) — серверный язык сценариев, обрабатывающий логику приложения.

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

- `ansible.builtin.apt`: Установка системных пакетов и управление кэшем.
- `ansible.builtin.apt_repository`: Подключение сторонних PPA (например, для свежих версий PHP).
- `ansible.builtin.template`: Генерация конфигурационных файлов на основе Jinja2.
- `ansible.builtin.copy`: Доставка статического контента.
- `community.mysql.mysql_db` / `community.mysql.mysql_user`: Управление БД (требует `python3-pymysql` на хосте).
- `community.general.ufw`: Настройка межсетевого экрана.

---

## Практические сценарии

### Сценарий: Развертывание защищенного и актуального LEMP-стека

Современный подход включает использование актуальных репозиториев, настройку безопасности (Firewall, HTTP-заголовки) и автоматическую проверку связности компонентов.

#### Шаг 1: Подготовка переменных и Vault

Чувствительные данные (пароли) должны храниться в зашифрованном виде. Создайте файл `vars/vault.yml` с помощью **[Ansible Vault](../Vault/basics.md)**:

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

#### Шаг 8: Запуск и проверка

Выполнение плейбука с запросом пароля Vault:

```bash
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass
```

1.  **Настройка локальных хостов**: Добавьте `127.0.0.1 my-site.local` в файл `/etc/hosts`.
2.  **Проверка PHP**: Откройте `http://my-site.local` — должна отобразиться страница `phpinfo`.
3.  **Проверка базы данных**: Откройте `http://my-site.local/db_test.php` — ожидается сообщение об успешном соединении.

---

## Дополнительная информация

### Масштабирование и SSL (HTTPS)

- **Настройка HTTPS (Certbot)**: В современном веб-окружении SSL обязателен. Рекомендуется использовать роль `geerlingguy.certbot` или модуль `ansible.builtin.command` для вызова `certbot --nginx`.
- **Универсальность**: Данный пример ориентирован на Debian/Ubuntu. Для RHEL/CentOS необходимо использовать модули `ansible.builtin.yum/dnf` и учитывать различия в путях конфигураций Nginx. Подробнее: **[Кроссплатформенные плейбуки](../CrossPlatform/concepts.md)**.
- **Мониторинг**: Включите статус-страницу PHP-FPM для сбора метрик. Подробнее: **[Мониторинг PHP-FPM](../../WebServers/PHP/php-fpm-monitoring.md)**.
- **Рефакторинг**: Для крупных проектов выносите логику в отдельные **[роли Ansible](../ansible_roles.md)**.

## Смотрите также

- [Установка и настройка MySQL/MariaDB через Ansible](mysql_setup.md)
- [Кроссплатформенный пример развертывания LAMP](../CrossPlatform/lamp-example.md)
- [Шаблонизация Jinja2 в Ansible](../ansible_jinja_templating.md)
- [Обзор возможностей Nginx](../../WebServers/Nginx/Core/nginx_overview.md)
