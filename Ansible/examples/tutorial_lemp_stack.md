# Развертывание LEMP-стека с помощью Ansible

## Определения

**LEMP (Linux, Nginx, MySQL, PHP)** — популярный набора программного обеспечения для развертывания динамических веб-приложений.

**Компоненты стека:**
- **Linux** — операционная система (ОС — Операционная Система), выступающая фундаментом.
- **Engine-X (Nginx)** — высокопроизводительный веб-сервер и реверс-прокси.
- **MySQL/MariaDB** — реляционная **СУБД (Система Управления Базами Данных)**.
- **PHP** (Hypertext Preprocessor) — язык сценариев для серверной обработки данных.

## Базовые концепции

### Структура управления

| Элемент | Назначение |
|---|---|
| `hosts` | Целевые группы хостов из инвентаря. |
| `become: true` | Выполнение задач с правами суперпользователя (`sudo`). |
| `tasks` | Основной список последовательных действий. |
| `handlers` | Задачи, запускаемые через `notify` только при изменении состояния. |
| `vars` | Переменные для кастомизации конфигурации (например, версии пакетов). |

### Ключевые модули

Для развертывания LEMP используются стандартные модули Ansible:

- `ansible.builtin.apt`: Установка пакетов (Nginx, PHP).
- `ansible.builtin.template`: Генерация конфигов Nginx на основе Jinja2.
- `ansible.builtin.copy`: Доставка статических файлов сайта.
- `ansible.builtin.service`: Управление состоянием служб (start, reload).
- `community.mysql.*`: Настройка базы данных и пользователей.

## Практические сценарии

### Сценарий: Развертывание LEMP-стека с нуля

#### Шаг 1: Установка и настройка Nginx

1.  **Установка**: Используем `apt` для инсталляции. Параметр `update_cache: yes` гарантирует актуальность списка пакетов.
2.  **Очистка**: Удаляем стандартную страницу приветствия Nginx.
3.  **Доставка контента**: Копируем файлы лендинга.

```yaml
---
- name: Развертывание LEMP-стека
  hosts: web_servers
  become: true
  vars:
    php_version: "8.3"

  tasks:
    - name: Установка Nginx
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: yes

    - name: Удаление стандартной директории веб-сервера
      ansible.builtin.file:
        path: /var/www/html
        state: absent

    - name: Копирование статических файлов сайта
      ansible.builtin.copy:
        src: files/landing/
        dest: /var/www/my-site/
        owner: www-data
        group: www-data
        mode: '0755'
```

#### Шаг 2: Установка и настройка MySQL

Подробный разбор кроссплатформенной и идемпотентной установки базы данных вынесен в основное руководство: **[Установка и настройка MySQL/MariaDB](mysql_setup.md)**.

В реальном проекте вы можете вынести эти задачи в отдельную роль или файл и подключить их через `include_tasks` / `import_role`. В рамках данного туториала предполагается, что база данных настраивается с учетом рекомендаций из указанной статьи.

#### Шаг 3: Установка PHP и интеграция с Nginx

1.  **Инсталляция**: Устанавливаем `php-fpm` и драйвер для MySQL.
2.  **Шаблонизация**: Создаем виртуальный хост Nginx. Путь к сокету зависит от версии PHP: `/var/run/php/php{{ php_version }}-fpm.sock`.

**Шаблон `templates/nginx-php.conf.j2`:**

```j2
server {
    listen 80;
    server_name my-site.local;
    root /var/www/my-site;
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

**Задачи в плейбуке:**

```yaml
    - name: Установка PHP-FPM и модулей
      ansible.builtin.apt:
        name:
          - "php{{ php_version }}-fpm"
          - "php{{ php_version }}-mysql"
        state: present

    - name: Настройка виртуального хоста Nginx
      ansible.builtin.template:
        src: templates/nginx-php.conf.j2
        dest: /etc/nginx/sites-available/my-site.conf
      notify: Reload Nginx

    - name: Активация конфигурации (симлинк)
      ansible.builtin.file:
        src: /etc/nginx/sites-available/my-site.conf
        dest: /etc/nginx/sites-enabled/my-site.conf
        state: link
      notify: Reload Nginx

  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

#### Шаг 4: Развертывание тестового приложения

```yaml
    - name: Создание корневой директории сайта
      ansible.builtin.file:
        path: /var/www/my-site
        state: directory
        owner: www-data
        group: www-data
        mode: '0755'

    - name: Создание тестового файла phpinfo
      ansible.builtin.copy:
        content: "<?php phpinfo(); ?>"
        dest: /var/www/my-site/index.php

    - name: Тест подключения к базе данных
      ansible.builtin.copy:
        content: |
          <?php
          $mysqli = new mysqli("localhost", "root", "{{ mysql_root_password }}");
          if ($mysqli->connect_errno) {
            echo "Ошибка подключения: " . $mysqli->connect_error;
            exit();
          }
          echo "Соединение успешно. Версия сервера: " . $mysqli->server_info;
          $mysqli->close();
          ?>
        dest: /var/www/my-site/db_test.php
```

#### Шаг 5: Запуск и проверка

1.  **Запуск**: `ansible-playbook playbook.yml -i hosts.ini` # → стек LEMP развернут
2.  **Настройка хостов**: Добавьте `127.0.0.1 my-site.local` в локальный файл `/etc/hosts`.
3.  **Проверка PHP**: Откройте `http://my-site.local` — вы увидите страницу `phpinfo`.
4.  **Проверка БД**: Откройте `http://my-site.local/db_test.php` — должна отобразиться версия MySQL.

---

## Дополнительная информация

### Безопасность и масштабирование

- **Секреты**: Для защиты паролей (например, `mysql_root_password`) всегда используйте **[Ansible Vault](../Vault/basics.md)**.
- **Универсальность**: Данный пример ориентирован на Ubuntu/Debian. Для поддержки RHEL/CentOS используйте модуль `package` и кроссплатформенные переменные. См. **[Кроссплатформенные плейбуки](../CrossPlatform/concepts.md)**.
- **Структурирование**: Для крупных проектов переносите логику в **[роли Ansible](../ansible_roles.md)**.

## Смотрите также

- [Установка и настройка MySQL через Ansible](mysql_setup.md)
- [Пример развертывания LAMP](../CrossPlatform/lamp-example.md)
- [Обзор возможностей Nginx](../../WebServers/Nginx/Core/nginx_overview.md)
