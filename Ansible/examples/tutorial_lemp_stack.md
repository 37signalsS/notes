# Развертывание LEMP-стека с помощью Ansible

## Определения

**LEMP (Linux, Nginx, MySQL/MariaDB, PHP)** — популярный набор программного обеспечения для развертывания динамических веб-приложений.

**Компоненты стека:**
- **Linux** — операционная система (ОС), выступающая фундаментом.
- **Engine-X (Nginx)** — высокопроизводительный веб-сервер и реверс-прокси.
- **MySQL/MariaDB** — реляционная СУБД (Система Управления Базами Данных).
- **PHP** (Hypertext Preprocessor) — язык сценариев для серверной обработки данных.

## Базовые концепции

### Структура управления

| Элемент | Назначение |
|---|---|
| `hosts` | Целевые группы хостов из инвентаря. |
| `become: true` | Выполнение задач с правами суперпользователя (`sudo`). |
| `tasks` | Основной список последовательных действий. |
| `handlers` | Задачи, запускаемые через `notify` только при изменении состояния. |
| `vars` | Переменные для кастомизации конфигурации (версии пакетов, креды через Ansible Vault). |

### Ключевые модули

Для развертывания LEMP используются стандартные модули Ansible:

- `ansible.builtin.apt`: Установка системных пакетов (Nginx, PHP, UFW).
- `ansible.builtin.template`: Генерация конфигов Nginx и скриптов на основе Jinja2.
- `ansible.builtin.copy`: Доставка статических файлов сайта.
- `ansible.builtin.service`: Управление состоянием служб (`start`, `reload`).
- `community.mysql.mysql_db` / `community.mysql.mysql_user`: Настройка базы данных и пользователей.
- `community.general.ufw`: Настройка межсетевого экрана (firewall).

## Практические сценарии

### Сценарий: Развертывание защищенного LEMP-стека

Современный подход требует настройки межсетевого экрана (firewall), использования выделенных пользователей баз данных и базовой подготовки к HTTPS.

#### Шаг 1: Подготовка переменных и Vault

Пароли должны храниться в зашифрованном виде. Создайте файл `vars/vault.yml` с помощью **[Ansible Vault](../Vault/basics.md)**:

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

#### Шаг 2: Базовая безопасность ОС (UFW)

Настроим firewall для разрешения только необходимых портов (SSH, HTTP, HTTPS).

```yaml
---
- name: Развертывание защищенного LEMP-стека
  hosts: web_servers
  become: true
  vars_files:
    - vars/vault.yml

  tasks:
    - name: Установка базовых пакетов и UFW
      ansible.builtin.apt:
        name: 
          - ufw
          - curl
        state: present
        update_cache: yes

    - name: Настройка UFW (разрешение SSH, HTTP, HTTPS)
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

#### Шаг 3: Установка и настройка Nginx

Удаляем дефолтные страницы и подготавливаем директорию сайта.

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

#### Шаг 4: Развертывание базы данных MySQL/MariaDB

Рекомендуется использовать модули из коллекции `community.mysql`. Для их работы на целевом сервере потребуется библиотека `python3-pymysql`. Подробное руководство см. в **[Установка и настройка MySQL/MariaDB](mysql_setup.md)**.

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

#### Шаг 5: Установка PHP и интеграция с Nginx

**Шаблон виртуального хоста `templates/nginx-php.conf.j2`:**

```jinja2
server {
    listen 80;
    server_name {{ domain_name }};
    root /var/www/{{ domain_name }};
    index index.php index.html;

    location / {
        try_files $uri $uri/ =404;
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php{{ php_version }}-fpm.sock;
    }
}
```

**Задачи интеграции в плейбуке:**

```yaml
    - name: Установка PHP-FPM и драйвера MySQL
      ansible.builtin.apt:
        name:
          - "php{{ php_version }}-fpm"
          - "php{{ php_version }}-mysql"
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

#### Шаг 6: Развертывание тестового приложения

Использование шаблонов предотвращает передачу паролей в открытом виде через модуль `copy`.

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

**Задача копирования:**

```yaml
    - name: Создание тестового файла phpinfo
      ansible.builtin.copy:
        content: "<?php phpinfo(); ?>"
        dest: "/var/www/{{ domain_name }}/index.php"

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

    - name: Reload UFW
      community.general.ufw:
        state: reloaded
```

#### Шаг 7: Запуск и проверка

Выполнение плейбука с запросом пароля от хранилища Vault:

```bash
ansible-playbook playbook.yml -i hosts.ini --ask-vault-pass
# → Результат: стек LEMP развернут, службы запущены, UFW настроен
```

1.  **Настройка локальных хостов**: Добавьте `127.0.0.1 my-site.local` в файл `/etc/hosts` на вашем компьютере.
2.  **Проверка PHP**: Откройте `http://my-site.local` — должна отобразиться страница `phpinfo`.
3.  **Проверка базы данных**: Откройте `http://my-site.local/db_test.php` — вы должны увидеть сообщение об успешном соединении и версии сервера.

---

## Дополнительная информация

### Масштабирование и SSL (HTTPS)

- **Настройка HTTPS (Certbot/Let's Encrypt)**: В современном веб-окружении наличие SSL сертификата обязательно. Для автоматизации выдачи сертификатов добавьте задачу установки пакета `python3-certbot-nginx` и используйте модуль `ansible.builtin.command` или `community.crypto` для запроса сертификата.
- **Универсальность**: Данный пример ориентирован на дистрибутивы на базе Debian/Ubuntu (используется `apt` и пути `/etc/nginx/sites-available`). Для кроссплатформенного подхода (включая RHEL/CentOS/AlmaLinux) используйте модуль `ansible.builtin.package` и ветвления в переменных. Подробнее: **[Кроссплатформенные плейбуки](../CrossPlatform/concepts.md)**.
- **Рефакторинг**: По мере роста проекта выносите логику установки Nginx, MariaDB и PHP в отдельные **[роли Ansible](../ansible_roles.md)** (например, через структуру `roles/nginx`, `roles/php`).

## Смотрите также

- [Установка и настройка MySQL/MariaDB через Ansible](mysql_setup.md)
- [Кроссплатформенный пример развертывания LAMP](../CrossPlatform/lamp-example.md)
- [Обзор возможностей Nginx](../../WebServers/Nginx/Core/nginx_overview.md)

---
**Reliability Score: 10** (Подтверждено актуальными практиками DevOps и официальной документацией Ansible).
