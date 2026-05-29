# Учебное пособие: Развертывание LEMP-стека с помощью Ansible

## Определения

**LEMP-стек** — набор программного обеспечения для развертывания веб-приложений. Акроним расшифровывается как:

* **L**inux — операционная система.
* **E**ngine-X (Nginx) — веб-сервер.
* **M**ySQL/MariaDB — система управления базами данных (СУБД).
* **P**HP — язык программирования для обработки динамического контента.

## Базовые концепции

### Структура плейбука

* `name`: Описание плейбука.
* `hosts`: Целевые хосты или группы из инвентаря.
* `become: true`: Указание выполнять задачи с повышенными привилегиями (`sudo`).
* `tasks`: Список задач, которые выполняются последовательно.
* `handlers`: Специальные задачи, которые запускаются только по уведомлению от других задач (например, для перезапуска сервиса после изменения конфигурации).

### Ключевые модули

* `ansible.builtin.apt`: Управление пакетами в Debian-подобных системах.
* `ansible.builtin.file`: Управление файлами, директориями и символическими ссылками.
* `ansible.builtin.copy`: Копирование файлов с управляющего узла на целевые хосты.
* `ansible.builtin.template`: Создание файлов на основе шаблонов Jinja2.
* `ansible.builtin.service`: Управление системными службами.
* `community.mysql.mysql_user`: Управление пользователями MySQL.
* `community.mysql.mysql_db`: Управление базами данных MySQL.

## Практические сценарии

### Сценарий: Развертывание LEMP-стека с нуля

#### Шаг 1: Установка и настройка Nginx

1. **Установка Nginx**: Используем модуль `apt` для установки пакета. Параметр `state: present` обеспечивает идемпотентность.
2. **Подготовка веб-директории**: Удаляем стандартную директорию `/var/www/html`.
3. **Развертывание сайта**: Копируем файлы простого HTML-сайта из локальной папки `files/html` на сервер.

```yaml
---
- name: Configure LEMP Stack
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

#### Шаг 2: Установка и настройка MySQL

Подробный разбор кроссплатформенной и идемпотентной установки базы данных вынесен в основное руководство: **[Установка и настройка MySQL/MariaDB](mysql_setup.md)**.

В реальном проекте вы можете вынести эти задачи в отдельную роль или файл и подключить их через `include_tasks` / `import_role`. В рамках данного туториала предполагается, что база данных настраивается с учетом рекомендаций из указанной статьи.

#### Шаг 3: Установка PHP и интеграция с Nginx

1. **Установка PHP**: Устанавливаем `php-fpm` (менеджер процессов FastCGI) и `php-mysql` для связи с MySQL.
2. **Шаблонизация конфигурации Nginx**: Создаем конфигурационный файл для PHP-сайта из шаблона `php-test.conf.j2`. Это позволяет использовать переменные (например, `{{ php_version }}`) для динамической генерации конфигурации.
3. **Активация сайта и обработчики**: Создаем символическую ссылку для активации сайта и используем `notify`, чтобы уведомить `handler` о необходимости перезагрузки Nginx.

**Шаблон `templates/php-test.conf.j2`:**

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
        fastcgi_pass unix:/var/run/php/php{{ php_version }}-fpm.sock;
    }
}
```

**Задачи и обработчик в плейбуке:**

```yaml
# ... (продолжение секции tasks)
    - name: Install PHP-FPM and PHP-MySQL
      ansible.builtin.apt:
        name:
          - php-fpm
          - php-mysql
        state: present

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

# ... (в конце плейбука, на одном уровне с 'tasks')
  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

#### Шаг 4: Развертывание тестового PHP-приложения

Создаем директорию для сайта и два PHP-файла для проверки: один с `phpinfo()` и второй для теста соединения с MySQL.

```yaml
# ... (продолжение секции tasks)
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

#### Шаг 5: Запуск и проверка

1. Запустите плейбук: `ansible-playbook playbook.yml -i inventory.ini`
2. Добавьте `127.0.0.1 php-test.com` в ваш локальный файл `hosts` (если вы запускаете на локальной VM).
3. Откройте в браузере `http://php-test.com` для просмотра информации о PHP.
4. Откройте `http://php-test.com/db_test.php` для проверки соединения с MySQL.

## Дополнительная информация

* **Безопасность**: Для хранения чувствительных данных, таких как пароль от базы данных, всегда используйте **[Ansible Vault](../Vault/basics.md)**.
* **Кроссплатформенность**: Этот плейбук ориентирован на Debian/Ubuntu. Для создания универсальных плейбуков, работающих на разных ОС (например, CentOS), ознакомьтесь с примером **[кроссплатформенной установки LAMP](../CrossPlatform/lamp-example.md)** и документом о **[кроссплатформенных плейбуках](../CrossPlatform/concepts.md)**.
* **Роли**: Для более сложных и переиспользуемых конфигураций рекомендуется структурировать плейбуки с помощью **[ролей Ansible](../ansible_roles.md)**.
