# Nginx location: Примеры интеграции

## Определения

**Примеры интеграции** — практические конфигурации `location` для распространённых веб-приложений и технологий, демонстрирующие взаимодействие Nginx с бэкенд-сервисами (PHP-FPM, Node.js, Python-приложения и т.д.).

## Базовые концепции

### Взаимодействие с PHP-FPM через FastCGI

Для обработки PHP-скриптов Nginx использует FastCGI-протокол, взаимодействуя с PHP-FPM через TCP-сокет или Unix-сокет.

* Базовая настройка `location ~ \.php$` описана в [Основы и приоритеты location](./basics.md#сценарий-1-базовый-веб-сайт-с-php)
* Параметры `fastcgi_pass`, `SCRIPT_FILENAME` и `fastcgi_params` подробно рассмотрены в [Основы и приоритеты location](./basics.md#сценарий-1-базовый-веб-сайт-с-php)
* Директива `try_files` — в [Nginx: Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md#директива-try_files)
* Настройка TLS для HTTPS — в [TLS/SSL в Nginx: обзор](../Security/TLS_SSL/nginx_tls_ssl_overview.md) и [Конфигурация виртуальных хостов TLS](../Security/TLS_SSL/nginx_tls_virtual_host_config.md)

## Практические сценарии

### Сценарий 1: PHP-приложение

```nginx
location ~ \.php$ {
    root           /var/www/html;
    fastcgi_pass   unix:/var/run/php/php8.3-fpm.sock; # Путь к сокету PHP-FPM (актуально для PHP 8.3)
    fastcgi_index  index.php;
    include        fastcgi_params; # Включает стандартные параметры FastCGI
    fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

* Здесь используется регулярное выражение `~ \.php$` для сопоставления всех запросов, заканчивающихся на `.php`.
* `fastcgi_pass` указывает адрес FastCGI-сервера (часто Unix-сокет).
* `fastcgi_param SCRIPT_FILENAME` передаёт PHP-FPM полный путь к исполняемому скрипту.

### Сценарий 2: WordPress

Типичная конфигурация `location` для WordPress включает:

* Перенаправление HTTP на HTTPS. Подробная информация доступна в [TLS/SSL в Nginx: обзор](../Security/TLS_SSL/nginx_tls_ssl_overview.md).
* `location /` с `try_files` для обработки статики и перенаправления на `index.php` для динамического контента.
* `location ~ \.php$` для обработки PHP-скриптов через FastCGI.
* `location` для защиты конфиденциальных файлов (например, `.htaccess`, `wp-config.php`).
* Специальные `location` для статических ресурсов WordPress (например, `/wp-content/`).

```nginx
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/wordpress;
    index index.php index.html index.htm;

    # Защита конфиденциальных файлов, начинающихся с точки
    location ~ /\. {
        deny all; # запрещает доступ всем клиентам
    }
    location ~ /(wp-config\.php|wp-trackback\.php|xmlrpc\.php) {
        deny all;
    }

    # Обработка статических файлов и перенаправление на index.php
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # Обработка PHP-скриптов
    location ~ \.php$ {
        include snippets/fastcgi-php.conf; # Или полный набор fastcgi_params
        fastcgi_pass unix:/var/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Специальный location для статики wp-content
    location ~* \.(js|css|png|jpg|jpeg|gif|ico)$ {
        expires max;
        log_not_found off; # Не записывать ошибки «файл не найден»
    }
}
```

### Сценарий 3: Node.js-приложение (проксирование)

Для Node.js-приложений Nginx работает как обратный прокси, передавая запросы на порт, который слушает Node.js.

```nginx
location / {
    proxy_pass         http://127.0.0.1:3000; # Адрес Node.js-приложения
    proxy_http_version 1.1;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection 'upgrade';
    proxy_set_header   Host $host;
    proxy_cache_bypass $http_upgrade;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

* `proxy_pass` указывает адрес бэкенд-сервера.
* Заголовки `Upgrade` и `Connection` необходимы для поддержки WebSocket-соединений.
* `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto` передают информацию о клиенте бэкенду.

### Сценарий 4: Python-приложение (Gunicorn/uWSGI)

Для Python-приложений, работающих через Gunicorn или uWSGI, настройка аналогична PHP-FPM, но с использованием соответствующего протокола.

**Gunicorn (HTTP-проксирование):**

```nginx
location / {
    proxy_pass http://127.0.0.1:8000; # Адрес Gunicorn
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**uWSGI (протокол uwsgi):**

```nginx
location / {
    include uwsgi_params;
    uwsgi_pass unix:/var/run/uwsgi/app.sock; # Unix-сокет uWSGI
    uwsgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

## Дополнительная информация

### См. также

* [Основы и приоритеты location](./basics.md) — описание синтаксиса и порядка обработки `location`
* [Nginx: Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md) — директивы перезаписи URL и обработки файлов
* [Лучшие практики Nginx location](./best_practices.md) — рекомендации по безопасности и производительности
