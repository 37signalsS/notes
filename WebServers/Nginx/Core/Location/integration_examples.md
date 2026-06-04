# Nginx location: Примеры интеграции

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на июнь 2026)

## Определения

**Примеры интеграции** — это проверенные конфигурации блоков `location`, предназначенные для корректного взаимодействия Nginx с различными бэкенд-технологиями и приложениями.

**Бэкенд-сервис** — приложение или процесс (PHP-FPM, Node.js, Python), который выполняет динамическую обработку запросов, переданных от Nginx.

---

## Базовые концепции

### Механизмы проксирования

Nginx поддерживает несколько протоколов для передачи запросов бэкендам:

1. **FastCGI (Fast Common Gateway Interface):** используется преимущественно для PHP-приложений. Обеспечивает высокую производительность за счёт постоянных соединений с процессами обработки.
2. **HTTP (Hypertext Transfer Protocol):** стандартный способ проксирования для Node.js, Python (через Gunicorn), Go и других современных приложений.
3. **uWSGI (Universal Web Server Gateway Interface):** специализированный протокол для Python-приложений, обеспечивающий глубокую интеграцию с сервером uWSGI.

### Протоколы передачи данных

* **Unix Domain Sockets:** используются для взаимодействия процессов внутри одного сервера. Работают быстрее, чем сетевые сокеты, так как не задействуют сетевой стек TCP/IP (Transmission Control Protocol / Internet Protocol).
* **TCP (Transmission Control Protocol) Sockets:** применяются для взаимодействия с бэкендами на других серверах или при использовании контейнеризации (например, Docker).

---

## Практические сценарии

### Сценарий 1: PHP-приложение (PHP-FPM)

Классическая настройка для обработки динамического контента на языке PHP (Hypertext Preprocessor).

```nginx
location ~ \.php$ {
    root           /var/www/html;
    # Путь к сокету PHP-FPM (PHP FastCGI Process Manager)
    fastcgi_pass   unix:/var/run/php/php8.3-fpm.sock; 
    fastcgi_index  index.php;
    
    # Включает стандартные параметры FastCGI
    include        fastcgi_params; 
    
    # Передаёт полный путь к исполняемому скрипту
    fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

* Используется регулярное выражение `~ \.php$` для перехвата всех запросов к файлам с расширением `.php`.
* Подробный алгоритм приоритетов описан в [Основы и приоритеты location](./basics.md).

### Сценарий 2: WordPress

Конфигурация для самой популярной CMS (Content Management System — система управления контентом), включающая защиту и обработку статики.

```nginx
server {
    listen 80;
    server_name example.com;
    # Принудительный редирект на HTTPS (Hypertext Transfer Protocol Secure)
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/wordpress;
    index index.php index.html;

    # Защита скрытых файлов (начинаются с точки)
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Защита критических файлов WordPress
    location ~ /(wp-config\.php|wp-trackback\.php|xmlrpc\.php) {
        deny all;
    }

    # Единая точка входа для ЧПУ (человекопонятных URL)
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # Обработка PHP
    location ~ \.php$ {
        include fastcgi_params;
        fastcgi_pass unix:/var/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Оптимизация отдачи статики
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires max;
        log_not_found off;
    }
}
```

### Сценарий 3: Node.js-приложение (Проксирование HTTP)

Настройка Nginx в качестве обратного прокси (Reverse Proxy) для приложения на Node.js.

```nginx
location / {
    proxy_pass         http://127.0.0.1:3000; # Адрес и порт Node.js
    proxy_http_version 1.1;
    
    # Поддержка WebSocket-соединений
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection 'upgrade';
    
    # Передача информации о клиенте бэкенду
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    
    # Отключение кэширования для WebSocket
    proxy_cache_bypass $http_upgrade;
}
```

### Сценарий 4: Python-приложение (Gunicorn или uWSGI)

Интеграция с Python-приложениями через специализированные шлюзы.

**Gunicorn (протокол HTTP):**

```nginx
location / {
    proxy_pass http://127.0.0.1:8000; # Адрес Gunicorn (WSGI-сервер)
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
    # Путь к сокету uWSGI (Universal Web Server Gateway Interface)
    uwsgi_pass unix:/var/run/uwsgi/app.sock;
}
```

---

## Дополнительная информация

### См. также

* **[Основы и приоритеты location](./basics.md)** — алгоритм выбора и типы модификаторов.
* **[Nginx: Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md)** — подробнее о манипуляциях с URI.
* **[Лучшие практики Nginx location](./best_practices.md)** — рекомендации по безопасности и отладке.
* **[TLS/SSL в Nginx: обзор](../Security/TLS_SSL/nginx_tls_ssl_overview.md)** — настройка безопасных соединений.
* **[Конфигурация виртуальных хостов TLS](../Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — примеры SSL-конфигураций.
