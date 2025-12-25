# Настройка Angie в роли обратного HTTP-прокси

## 1. Определения и концепции

**Обратный прокси-сервер (Reverse Proxy)** — это сервер, который принимает запросы от клиентов, перенаправляет их на один или несколько бэкенд-серверов и возвращает ответ клиенту. С точки зрения клиента, он взаимодействует напрямую с прокси-сервером, не зная о внутренней архитектуре. Подробнее об отличиях от прямого прокси можно прочитать в заметке [Proxy Server](../../Networking/Concepts/proxy.md).

В [Angie](../Angie/angie_overview.md), как и в Nginx, эта функциональность реализуется модулем `ngx_http_proxy_module`.

**Основные задачи, решаемые обратным прокси:**

- **Балансировка нагрузки**: Распределение запросов между несколькими бэкенд-серверами. См. [Балансировка нагрузки HTTP(S) в Angie](./angie_http_load_balancing.md).
- **Терминация SSL/TLS**: Снятие нагрузки по шифрованию с бэкенд-серверов. См. [Настройка TLS в Angie](./angie_tls_setup.md).
- **Кэширование**: Хранение ответов от бэкендов для ускорения повторных запросов. См. [Серверное кэширование в Angie](./angie_caching.md).
- **Безопасность**: Сокрытие внутренней структуры сети и фильтрация запросов.

## 2. Базовая конфигурация

Минимальная конфигурация для проксирования всех запросов на один бэкенд выглядит следующим образом:

```nginx
# /etc/angie/conf.d/reverse_proxy.conf
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://localhost:9000;
    }
}
```
- `proxy_pass`: Ключевая директива, указывающая адрес бэкенд-сервера. В данном случае все запросы, приходящие на `location /`, будут перенаправлены на `http://localhost:9000`.

Для отладки работы прокси удобно использовать бэкенд, который в ответ возвращает все заголовки и параметры полученного им запроса, например, `ws-debugger` в [Docker](../../Docker/docker_overview.md).

## 3. Управление заголовками

При проксировании Angie изменяет некоторые параметры запроса. Чтобы бэкенд-сервер получал корректную информацию о клиенте, необходимо передавать ему оригинальные заголовки.

```nginx
location / {
    proxy_pass http://localhost:9000;
    
    # Передача IP-адреса клиента
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    # Передача оригинального хоста и протокола
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

- `proxy_set_header X-Real-IP $remote_addr;`: Передает реальный IP-адрес клиента в заголовке `X-Real-IP`.
- `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`: `$proxy_add_x_forwarded_for` — это специальная переменная, которая добавляет IP-адрес клиента (`$remote_addr`) к уже существующему заголовку `X-Forwarded-For`, что полезно при работе с цепочками прокси-серверов.
- `proxy_set_header Host $host;`: Передает оригинальный заголовок `Host` из запроса клиента. По умолчанию Angie подставил бы сюда имя апстрима (`localhost`).
- `proxy_set_header X-Forwarded-Proto $scheme;`: Передает оригинальный протокол (`http` или `https`).

## 4. Взаимодействие `location` и `proxy_pass` с URI

Правила обработки URI меняются в зависимости от того, есть ли в `proxy_pass` завершающий `/`.

- **`proxy_pass http://backend;` (без `/`)**: URI запроса передается "как есть". Запрос `/some/page` будет проксирован на `http://backend/some/page`.
- **`proxy_pass http://backend/;` (с `/`)**: Часть URI, совпадающая с `location`, отбрасывается.
    - `location /path/ { proxy_pass http://backend/; }`: Запрос `/path/some/page` будет проксирован на `http://backend/some/page`.

Подробное описание логики работы директивы `location` находится в отдельной заметке: [Директивы `location` в Angie](./angie_location_directives.md).

## 5. Продвинутые параметры проксирования

### 5.1. Keep-alive соединения с бэкендом

Для снижения задержек и нагрузки на CPU при проксировании на удаленные серверы рекомендуется использовать постоянные **[keep-alive соединения](../Nginx/Performance/nginx_performance_tuning.md#34-оптимизация-соединений-с-бэкендами-upstream)**.

```nginx
http {
    upstream backend_keepalive {
        server 127.0.0.1:9000;

        keepalive 32; # Количество keep-alive соединений в кэше для каждого worker-процесса
    }

    server {
        location / {
            proxy_pass http://backend_keepalive;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            # ... другие proxy_set_header
        }
    }
}
```
**Ключевые директивы:**
1.  `upstream { keepalive ...; }`: Включает кэш для keep-alive соединений в рамках `upstream` блока.
2.  `proxy_http_version 1.1;`: Переключает проксирование на протокол HTTP/1.1, который поддерживает keep-alive.
3.  `proxy_set_header Connection "";`: Сбрасывает заголовок `Connection`, чтобы Angie не передавал на бэкенд `Connection: close` от клиента.

### 5.2. Буферизация (`proxy_buffering`)

По умолчанию Angie буферизует ответы от бэкенда (`proxy_buffering on;`). Это означает, что он сначала полностью считывает ответ во временный буфер и только потом начинает отправлять его клиенту, что позволяет быстрее освободить бэкенд.

- `proxy_buffers 8 16k;`: Настраивает количество и размер буферов. Если ответ не помещается, он будет записан во временный файл на диске.
- `proxy_max_temp_file_size 0;`: Запрещает запись во временный файл при переполнении буферов.
- `proxy_buffering off;`: Полностью отключает буферизацию. Это может быть полезно для long-polling запросов или Server-Sent Events, но **ломает кэширование**.

### 5.3. Таймауты

- `proxy_connect_timeout 5s;`: Таймаут на установление соединения с бэкендом.
- `proxy_read_timeout 10s;`: Таймаут на чтение ответа от бэкенда.
- `proxy_send_timeout 10s;`: Таймаут на передачу запроса бэкенду.

По умолчанию таймауты установлены на 60 секунд. Их уменьшение позволяет быстрее обнаруживать проблемы с бэкендом.

### 5.4. Перехват ошибок (`proxy_intercept_errors`)

Эта директива позволяет перехватывать ошибки от бэкенда (коды 4xx и 5xx) и вместо них показывать кастомную страницу ошибки, настроенную через `error_page`.

```nginx
location / {
    proxy_pass http://backend;
    proxy_intercept_errors on;
    error_page 500 502 503 504 /50x.html;
}
location = /50x.html {
    root /usr/share/nginx/html;
    internal;
}
```

### 5.5. Проксирование на HTTPS-бэкенд

Если требуется шифрование между Angie и бэкендом, `proxy_pass` указывается с протоколом `https://`.

```nginx
location / {
    proxy_pass https://secure_backend;
    
    # Настройки TLS для проксирования
    proxy_ssl_server_name on;            # Передавать имя сервера (SNI) при TLS-подключении
    proxy_ssl_name "backend.example.com";# Указать конкретный домен для SNI
    proxy_ssl_verify on;                 # Включает проверку сертификата бэкенда (рекомендуется для production)
    proxy_ssl_trusted_certificate /etc/angie/certs/ca.crt; # Путь к доверенному CA для проверки
    proxy_ssl_session_reuse on;          # Возобновление TLS-сессий
}
```

## 6. Кэширование (`proxy_cache`)

Angie может кэшировать ответы от бэкендов, что значительно снижает нагрузку и ускоряет ответы.

```nginx
http {
    # 1. Определяем зону кэша
    proxy_cache_path /var/cache/angie/proxy_cache keys_zone=my_cache:10m inactive=60m;

    server {
        location / {
            # 2. Включаем кэширование для location
            proxy_cache my_cache;
            proxy_pass http://backend;

            # 3. Настраиваем время жизни кэша
            proxy_cache_valid 200 302 10m;
            proxy_cache_valid 404 1m;

            # 4. Повышение отказоустойчивости
            proxy_cache_use_stale error timeout updating http_500;
        }
    }
}
```
- `proxy_cache_path`: Создает зону кэша на диске.
- `proxy_cache`: Активирует кэширование, используя указанную зону.
- `proxy_cache_valid`: Определяет время жизни кэша для разных кодов ответа.
- `proxy_cache_use_stale`: Позволяет отдавать устаревший ответ из кэша, если бэкенд недоступен.

Более подробное описание всех директив и стратегий кэширования находится в заметке [**Серверное кэширование в Angie**](./angie_caching.md).
