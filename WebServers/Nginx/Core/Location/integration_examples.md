# Nginx location: примеры интеграции

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на август 2026)

## Определения

**Примеры интеграции** — это проверенные конфигурации блоков `location`, предназначенные для корректного взаимодействия Nginx с различными бэкенд-технологиями и приложениями.

**Бэкенд-сервис** — приложение или процесс (PHP-FPM, Node.js, Python, Go), который выполняет динамическую обработку запросов, переданных от Nginx.

**FastCGI (Fast Common Gateway Interface)** — протокол для взаимодействия веб-сервера с исполняемыми программами (преимущественно PHP).

**uWSGI (Universal Web Server Gateway Interface)** — высокопроизводительный протокол и сервер приложений для Python.

**SCGI (Simple Common Gateway Interface)** — упрощенный протокол, аналогичный FastCGI, используемый в некоторых специализированных приложениях.

**gRPC (Google Remote Procedure Call)** — современный высокопроизводительный протокол на базе HTTP/2 и Protocol Buffers.

---

## Базовые концепции

### Механизмы проксирования

Nginx поддерживает несколько протоколов для передачи запросов бэкендам:

1. **FastCGI:** используется для PHP. Требует передачи параметров окружения через `fastcgi_param`.
2. **HTTP:** универсальный способ для Node.js, Python, Go, Java. Использует `proxy_pass`.
3. **uWSGI:** нативный протокол для Python-стека.
4. **gRPC:** требует HTTP/2 на стороне клиента и бэкенда. Использует `grpc_pass`.
5. **SCGI:** используется в таких приложениях, как rTorrent или некоторые C++ бэкенды.

### Выбор типа сокета

* **Unix Domain Sockets (`unix:/path/to/socket`):** Оптимально для локальных бэкендов на том же сервере. Минимальные задержки, отсутствие накладных расходов на сетевой стек.
* **TCP Sockets (`127.0.0.1:port` или `ip:port`):** Необходимы для распределенных систем и Docker-контейнеров без общих томов.

---

## Практические сценарии

### Сценарий 1: PHP-приложение (PHP-FPM 8.3+)

Конфигурация для современных PHP-приложений (Laravel, Symfony).

```nginx
location ~ \.php$ {
    root           /var/www/html/public;
    # Сокет PHP-FPM (версия 8.3+)
    fastcgi_pass   unix:/var/run/php/php8.3-fpm.sock; 
    fastcgi_index  index.php;
    
    include        fastcgi_params; 
    
    # Критически важный параметр для работы скриптов
    fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
    
    # Защита от передачи пустых путей в PHP
    fastcgi_split_path_info ^(.+\.php)(/.+)$;
}
```

### Сценарий 2: WordPress (Защищенная конфигурация)

Включает оптимизацию статики и блокировку уязвимых путей.

```nginx
server {
    listen 443 ssl;
    http2 on; # Для Nginx 1.25.1+
    server_name example.com;
    root /var/www/wordpress;
    index index.php;

    # Блокировка скрытых файлов и .git
    location ~ /\.(?!well-known) {
        deny all;
    }

    # Единая точка входа
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # Обработка PHP через сокет
    location ~ \.php$ {
        include fastcgi_params;
        fastcgi_pass unix:/var/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Кэширование статики на стороне клиента
    location ~* \.(webp|avif|jxl|css|js|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 365d;
        add_header Cache-Control "public, no-transform";
        log_not_found off;
    }
}
```

### Сценарий 3: Node.js и WebSocket

Использование Nginx как терминатора SSL и балансировщика для Node.js.

```nginx
location / {
    proxy_pass         http://127.0.0.1:3000;
    proxy_http_version 1.1;
    
    # Проброс заголовков для Upgrade (WebSocket)
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    
    # Стандартный блок заголовков проксирования
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    
    # Таймауты для долгоживущих соединений
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}
```

### Сценарий 4: Python (Gunicorn / uWSGI)

**Gunicorn (HTTP):**

```nginx
location / {
    proxy_pass http://unix:/tmp/gunicorn.sock; # Проксирование через сокет
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

**uWSGI (Native uwsgi):**

```nginx
location /app/ {
    include uwsgi_params;
    uwsgi_pass unix:/var/run/uwsgi/app.sock;
    uwsgi_modifier1 30; # Специфично для некоторых Python-конфигураций
}
```

### Сценарий 5: gRPC Интеграция

Требует установленного модуля `ngx_http_grpc_module` (входит в стандартную сборку).

```nginx
location /api.v1.OrderService/ {
    grpc_pass grpc://127.0.0.1:50051;
    
    # Для защищенного gRPC
    # grpc_pass grpcs://backend_grpc;
    
    error_page 502 = /error502grpc;
}
```

---

## Продвинутые настройки проксирования

### Буферизация и таймауты

Для стабильной работы под нагрузкой необходимо настраивать буферы:

```nginx
location / {
    proxy_pass http://backend;

    # Буферизация ответа от бэкенда (on по умолчанию)
    proxy_buffers 8 16k;
    proxy_buffer_size 32k;
    proxy_busy_buffers_size 64k;

    # Таймауты (default 60s)
    proxy_connect_timeout 5s;  # Время на установку соединения
    proxy_send_timeout 60s;    # Время на передачу запроса бэкенду
    proxy_read_timeout 60s;    # Время на ожидание ответа от бэкенда
}
```

### Использование SCGI

Пример для приложений, использующих протокол SCGI (например, rTorrent).

```nginx
location /RPC2 {
    include scgi_params;
    scgi_pass 127.0.0.1:5000;
}
```

---

## Дополнительная информация

### Валидация конфигурации

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
nginx -s reload
# → graceful reload executed
```

### См. также

* **[Основы и приоритеты location](./basics.md)** — детальный разбор алгоритма выбора.
* **[Rewrite правила и try_files](../nginx_rewrite_rules_and_try_files.md)** — управление URI.
* **[Лучшие практики Nginx location](./best_practices.md)** — безопасность и оптимизация.
* **[Балансировка нагрузки L7](../Proxy/Load_Balancing/practical_configuration.md)** — настройка `upstream` групп.
