# Учебное пособие: Развертывание LEMP-стека (Nginx, MySQL, PHP) с Ansible

Это руководство является продолжением [учебного пособия по установке Nginx](ansible_first_playbook_tutorial.md). Здесь мы расширим наш плейбук для автоматической установки и настройки полного LEMP-стека, добавив MySQL и PHP.

**Цели:**
1.  Автоматизировать установку MySQL и PHP.
2.  Научиться настраивать Nginx для работы с PHP-FPM.
3.  Использовать шаблоны Ansible для создания динамических конфигурационных файлов.
4.  Развернуть простое PHP-приложение для проверки работы стека.

См. также:
*   [Пример: Кроссплатформенная установка LEMP](./ansible_lemp_cross_platform_example.md)
*   [Автоматизация установки MySQL с Ansible](mysql_setup_with_ansible.md)
*   [Кроссплатформенные плейбуки](cross_platform_playbooks.md)

---

## 1. Расширение плейбука

Мы продолжим работать с плейбуком, созданным в предыдущем руководстве. Теперь наша цель — добавить к нему задачи для установки и настройки базы данных и PHP.

Итоговая структура нашего плейбука будет выглядеть так:
1.  Установка Nginx.
2.  Установка MySQL и его базовая защита.
3.  Установка PHP-FPM и модуля для работы с MySQL.
4.  Создание и настройка нового виртуального хоста в Nginx для PHP-сайта.
5.  Развертывание тестового PHP-скрипта.

## 2. Задача: Установка и настройка MySQL

Вместо ручной установки `mysql-server` и запуска `mysql_secure_installation`, мы используем модули Ansible для идемпотентной настройки.

> **Примечание:** Для работы модулей `community.mysql.*` необходимо установить коллекцию `ansible-galaxy collection install community.mysql` и библиотеку `PyMySQL` (`pip install PyMySQL`) на управляющем узле, а также пакет `python3-pymysql` на целевом хосте, что мы и сделаем в плейбуке.

Добавим следующие задачи в наш плейбук:

```yaml
# ... (внутри секции tasks)

    - name: Install MySQL and dependencies
      ansible.builtin.apt:
        name:
          - mysql-server
          - python3-pymysql # Необходим для модулей Ansible
        state: present
        update_cache: yes

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

## 3. Задача: Установка PHP-FPM

Теперь установим PHP. Нам нужен сам обработчик `php-fpm` и модуль для связи с MySQL (`php-mysql`).

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

## 4. Настройка Nginx для PHP

При ручной настройке мы бы создали новый файл в `/etc/nginx/sites-available/`, а затем — символическую ссылку в `sites-enabled/`. В Ansible мы автоматизируем это с помощью шаблона.

### Создание шаблона Nginx

Создадим файл `templates/php-test.conf.j2` в нашем проекте:

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
*   Этот шаблон очень похож на то, что мы бы писали вручную.
*   `fastcgi_pass` — ключевая директива, которая "пробрасывает" запросы к `.php` файлам на обработку в PHP-FPM через его сокет.
*   Мы используем переменную `{{ php_version }}`, чтобы сделать путь к сокету динамическим (например, 7.4, 8.1 и т.д.). Ее можно определить в `vars` плейбука.

### Задача для создания конфигурации

Теперь добавим задачи в плейбук для использования этого шаблона.

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
      notify: Reload Nginx # Уведомляем обработчик
```
- Модуль `template` создает конфигурационный файл из нашего `.j2` шаблона.
- Модуль `file` с `state: link` создает символическую ссылку, как мы бы сделали это командой `ln -s`.
- `notify: Reload Nginx` отправляет уведомление обработчику, который перезагрузит Nginx для применения изменений. Не забудьте определить `handler`:

```yaml
# В конце плейбука, на том же уровне, что и 'tasks'
  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

## 5. Развертывание тестового PHP-приложения

На последнем шаге мы создадим директорию для сайта и скопируем туда два файла: `index.php` (с `phpinfo()`) и `db_test.php` для проверки соединения с MySQL.

```yaml
# ... (внутри секции tasks)

    - name: Create web root for PHP site
      ansible.builtin.file:
        path: /var/www/php-test
        state: directory
        owner: vagrant # или ваш пользователь
        group: vagrant # или ваша группа
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

## 6. Результат и проверка

После запуска полного плейбука у вас будет настроенный LEMP-стек. Для проверки:

1.  Добавьте `127.0.0.1 php-test.com` в ваш локальный файл `hosts` (как и при ручной настройке).
2.  Откройте в браузере `http://php-test.com` (убедитесь, что порт 80 проброшен на хост-машину). Вы должны увидеть страницу с информацией о PHP.
3.  Откройте `http://php-test.com/db_test.php`. Вы должны увидеть версию сервера MySQL.

Мы успешно автоматизировали весь процесс, который ранее выполнялся вручную, сделав его повторяемым, надежным и идемпотентным.
