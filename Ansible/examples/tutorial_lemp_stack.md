# Учебное пособие: Развертывание LEMP-стека с нуля с помощью Ansible

В этом руководстве мы пошагово создадим Ansible Playbook для полной автоматизации установки и настройки стека LEMP (Linux, Nginx, MySQL, PHP) на удаленном хосте. Мы пройдем весь путь от создания первого плейбука до рабочего веб-сервера с PHP-приложением, подключенным к базе данных.


См. также:
*   [Обзор Ansible](../ansible_overview.md)
*   [Плейбуки Ansible](../ansible_playbooks.md)
*   [Пример: Кроссплатформенная установка LEMP](example_lemp_cross_platform.md)

---

## Часть 1: Основы и настройка Nginx

Создадим наш первый плейбук `playbook.yml`:

```yaml
---
- name: Configure Web Server
  hosts: all
  become: true
```
- `name`: Описание того, что делает этот плей.
- `hosts: all`: Указывает, что плей будет применяться ко всем хостам из инвентаря.
- `become: true`: Говорит Ansible выполнять все задачи с повышенными привилегиями (через `sudo`).

Запустим его командой `ansible-playbook`:
```bash
ansible-playbook playbook.yml -i inventory.ini
```
Результатом будет выполнение задачи по умолчанию — **`Gathering Facts`**, в ходе которой Ansible собирает информацию о целевой системе.

### 3. Добавление задач для Nginx

Задачи описываются в секции `tasks` и выполняются последовательно.

**Итоговый плейбук для установки Nginx:**
```yaml
---
# playbook.yml
- name: Configure Nginx Web Server
  hosts: all
  become: true

  tasks:
    - name: Install nginx via apt
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: yes

    - name: Remove default html directory
      ansible.builtin.file:
        path: /var/www/html
        state: absent

    - name: Copy our landing page content
      ansible.builtin.copy:
        src: files/html # Директория с вашим сайтом
        dest: /var/www/
        owner: vagrant
        group: vagrant
        mode: '0755'
```

**Разбор задач:**

1.  **`Install nginx via apt`**: Устанавливает Nginx. Параметр `state: present` обеспечивает **идемпотентность**: пакет будет установлен, только если его еще нет в системе. При повторном запуске эта задача не вызовет изменений.
2.  **`Remove default html directory`**: Удаляет стандартную директорию Nginx, чтобы подготовить место для нашего сайта. `state: absent` гарантирует, что директория будет отсутствовать.
3.  **`Copy our landing page content`**: Копирует содержимое нашего сайта из локальной папки `files/html` на удаленный сервер.

После выполнения этого плейбука у вас будет установлен Nginx с кастомной стартовой страницей.

---

## Часть 2: Добавление MySQL и PHP

Теперь расширим наш плейбук, добавив остальные компоненты стека.

### 4. Установка и настройка MySQL

Вместо ручной установки `mysql-server` и запуска `mysql_secure_installation`, мы используем модули Ansible для идемпотентной настройки.

> **Примечание:** Для работы модулей `community.mysql.*` необходимо установить коллекцию `ansible-galaxy collection install community.mysql` и библиотеку `PyMySQL` (`pip install PyMySQL`) на управляющем узле, а также пакет `python3-pymysql` на целевом хосте, что мы и сделаем в плейбуке.

**Добавьте эти задачи в ваш плейбук:**
```yaml
# ... (внутри секции tasks)
    - name: Install MySQL and dependencies
      ansible.builtin.apt:
        name:
          - mysql-server
          - python3-pymysql # Необходим для модулей Ansible
        state: present

    - name: Set root password and secure MySQL
      community.mysql.mysql_user:
        login_unix_socket: /var/run/mysqld/mysqld.sock
        name: root
        host: localhost
        password: "{{ mysql_root_password }}" # Используйте Vault!
        plugin: mysql_native_password
        state: present

    - name: Remove anonymous MySQL users
      community.mysql.mysql_user:
        name: ''
        host_all: yes
        state: absent

    - name: Remove the MySQL test database
      community.mysql.mysql_db:
        name: test
        state: absent
```
- Мы используем `login_unix_socket` для первоначальной настройки пароля root, так как в Ubuntu после установки `root` не имеет пароля и аутентифицируется через сокет.
- Затем мы удаляем анонимных пользователей и тестовую базу данных.
- **Безопасность:** Пароль `mysql_root_password` **необходимо** хранить в зашифрованном виде с помощью [Ansible Vault](ansible_vault.md).

### 5. Установка PHP-FPM

Установим обработчик `php-fpm` и модуль для связи с MySQL.

**Добавьте эту задачу:**
```yaml
# ... (внутри секции tasks)
    - name: Install PHP-FPM and PHP-MySQL
      ansible.builtin.apt:
        name:
          - php-fpm
          - php-mysql
        state: present
```
Эта задача автоматизирует ручную установку `apt install php-fpm php-mysql`. После ее выполнения в системе будет запущен сервис `php-fpm`, который создаст сокет для взаимодействия (обычно в `/var/run/php/`).

### 6. Настройка Nginx для PHP

При ручной настройке мы бы создали новый файл в `/etc/nginx/sites-available/`, а затем — символическую ссылку в `sites-enabled/`. В Ansible мы автоматизируем это с помощью шаблона.

**Создайте файл `templates/php-test.conf.j2`:**
```j2
server {
    listen 80;
    server_name php-test.com;
    root /var/www/php-test;

    index index.php;

    location / {
        try_files $uri $uri/ =404;
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        # Указываем путь к сокету PHP-FPM
        fastcgi_pass unix:/var/run/php/php{{ php_version }}-fpm.sock;
    }
}
```
- `fastcgi_pass` "пробрасывает" запросы к `.php` файлам на обработку в PHP-FPM.
- Мы используем переменную `{{ php_version }}`, чтобы сделать путь к сокету динамическим.

**Добавьте задачи для создания конфигурации:**
```yaml
# ... (внутри секции tasks)
    - name: Create Nginx config for PHP site from template
      ansible.builtin.template:
        src: templates/php-test.conf.j2
        dest: /etc/nginx/sites-available/php-test.conf
      notify: Reload Nginx # Уведомляем обработчик

    - name: Create symlink for the new site config
      ansible.builtin.file:
        src: /etc/nginx/sites-available/php-test.conf
        dest: /etc/nginx/sites-enabled/php-test.conf
        state: link
      notify: Reload Nginx
```
- Модуль `template` создает конфигурационный файл из нашего `.j2` шаблона.
- Модуль `file` с `state: link` создает символическую ссылку, как мы бы сделали это командой `ln -s`.
- `notify: Reload Nginx` отправляет уведомление обработчику, который перезагрузит Nginx для применения изменений. Не забудьте определить `handler`:

**Добавьте обработчик в конец плейбука:**
```yaml
# В конце плейбука, на том же уровне, что и 'tasks'
  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

### 7. Развертывание тестового PHP-приложения

Создадим директорию для сайта и скопируем туда два файла: `index.php` (с `phpinfo()`) и `db_test.php` для проверки соединения с MySQL.

**Добавьте эти задачи:**
```yaml
# ... (внутри секции tasks)
    - name: Create web root for PHP site
      ansible.builtin.file:
        path: /var/www/php-test
        state: directory
        owner: vagrant
        group: vagrant
        mode: '0755'

    - name: Deploy phpinfo page
      ansible.builtin.copy:
        content: "<?php phpinfo(); ?>"
        dest: /var/www/php-test/index.php

    - name: Deploy MySQL test page
      ansible.builtin.copy:
        content: |
          <?php
          $mysqli = new mysqli("localhost", "root", "{{ mysql_root_password }}");
          if ($mysqli->connect_errno) {
            echo "Failed to connect to MySQL: " . $mysqli->connect_error;
            exit();
          }
          echo "MySQL Server Version: " . $mysqli->server_info;
          $mysqli->close();
          ?>
        dest: /var/www/php-test/db_test.php
```
- Мы автоматизируем создание директории (`mkdir`) и смену владельца (`chown`) с помощью модуля `file`.
- Модуль `copy` с параметром `content` позволяет нам создавать небольшие файлы прямо из плейбука.

### 8. Результат и проверка

После запуска полного плейбука у вас будет настроенный LEMP-стек. Для проверки:
1.  Добавьте `127.0.0.1 php-test.com` в ваш локальный файл `hosts`.
2.  Откройте в браузере `http://php-test.com`. Вы должны увидеть страницу с информацией о PHP.
3.  Откройте `http://php-test.com/db_test.php`. Вы должны увидеть версию сервера MySQL.