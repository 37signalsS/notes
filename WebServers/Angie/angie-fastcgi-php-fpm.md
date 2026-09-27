# FastCGI и PHP-FPM в Angie

## Определения

*   **FastCGI** — бинарный протокол взаимодействия веб-сервера с внешними приложениями (application server). В отличие от классического CGI, процесс приложения живёт постоянно и обрабатывает множество запросов, поэтому накладные расходы на запуск процесса отсутствуют. Angie передаёт параметры запроса (метод, URI, заголовки) и получает ответ в бинарном формате.
*   **PHP-FPM (FastCGI Process Manager)** — демон, реализующий FastCGI для PHP. Работает постоянно, содержат пул воркеров (`pm.max_children`), которые исполняют PHP-скрипты.
*   **Unix-сокет / TCP-сокет** — два способа соединения Angie с FPM. Unix-сокет быстрее (без TCP-стека) и безопаснее по правам, но работает только в пределах хоста; TCP позволяет вынести FPM на другую машину.
*   **`SCRIPT_FILENAME`** — FastCGI-параметр, указывающий FPM путь к PHP-файлу, который нужно исполнить. Самая частая причина 502/404 при неверной настройке.

## Базовые концепции

### Как Angie взаимодействует с PHP-FPM

1. Angie получает HTTP-запрос, например `GET /index.php?a=1`.
2. В контексте `location ~ \.php$` Angie формирует FastCGI-запрос на сокет FPM (`fastcgi_pass`): метод, URI, `QUERY_STRING`, заголовки, `SCRIPT_FILENAME`.
3. FPM резолвит `SCRIPT_FILENAME` в файл на диске, исполняет его и возвращает ответ (бинарный пакет FastCGI).
4. Angie передаёт ответ клиенту и, при необходимости, участвует в логировании, кэшировании и метриках.

Протокол FastCGI поддерживают также другие прикладные серверы:
*   **uWSGI** (`uwsgi_pass`) — Python (Django, Flask), а также Ruby/PHP в конфигурации uWSGI.
*   **SCGI** (`scgi_pass`) — более простой текстовый протокол, используется редко.

Полный общий разбор интеграционных протоколов (proxy/fastcgi/uwsgi/scgi) для семейства Nginx см. в [примеры интеграции location (Nginx)](../Nginx/Core/Location/integration_examples.md).

### Параметры FastCGI

Переменные окружения передаются директивами `fastcgi_param`. Для PHP критичны:

*   `SCRIPT_FILENAME` — путь к исполняемому файлу на диске FPM.
*   `PATH_INFO` — часть URI после пути к скрипту (для фреймворков, использующих PATH-style роутинг).
*   `QUERY_STRING` — параметры запроса.
*   `REQUEST_METHOD`, `REQUEST_URI`, `SERVER_NAME`, `SERVER_PORT` — метаданные запроса.
*   `HTTPS` — должен быть `on` для корректной генерации ссылок и cookies (`secure`) за TLS-терминацией.

Канонический набор параметров подключают файлом `fastcgi_params` (в некоторых сборках `fastcgi.conf`), после чего добавляют/переопределяют нужные параметры.

### Исполнение только PHP-файлов

Ключевое правило безопасности: `fastcgi_pass` должен применяться только к `location`, совпадающему с регулярным выражением (`.php$`), и обработка должна идти через `try_files $uri =404;` или проверку `fastcgi_split_path_info`. Если отдавать PHP-буфер через `fastcgi_pass` в префиксном `location`, можно получить RCE: запрос `/uploads/shell.jpg/xxx.php` исполнит содержимое jpg как PHP.

## Практические сценарии

### Сценарий 1: PHP-FPM за Unix-сокетом (Laravel/Symfony)

```nginx
server {
    listen 443 ssl http2;
    server_name app.example.com;

    root /var/www/app/public;
    index index.php;

    location / {
        # Прохождение запросов к front-controller приложения
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        try_files $uri =404;
        fastcgi_pass unix:/run/php/php8.4-fpm.sock;
        fastcgi_index index.php;

        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param HTTPS on;
    }
}
```

Сокет по умолчанию для Debian/Ubuntu — `/run/php/php<version>-fpm.sock`, для RHEL-подобных — `/run/php-fpm/www.sock`. Пользователь процесса PHP-FPM (`www-data` на Debian) должен иметь права на запись в каталог сокета.

### Сценарий 2: FastCGI по TCP (FPM на другом хосте)

```nginx
upstream php_fpm_servers {
    zone php_fpm_servers 64k;
    server 10.0.0.11:9000 weight=2;
    server 10.0.0.12:9000 weight=1;
    keepalive 16;
}

location ~ \.php$ {
    try_files $uri =404;
    fastcgi_pass php_fpm_servers;
    fastcgi_keep_conn on;   # переиспользование keepalive-соединений к FPM
    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

Внимание: `SCRIPT_FILENAME` должен быть путём **на хосте FPM**, а не на хосте Angie. При общем NFS/клонированном коде пути совпадают, в ином случае используйте `alias` или отдельный конфиг.

### Сценарий 3: PATH_INFO и защита от исполнения не-PHP содержимого

```nginx
location ~ ^/index\.php(/|$) {
    try_files $uri =404;

    fastcgi_split_path_info ^(.+\.php)(/.*)$;
    fastcgi_pass unix:/run/php/php8.4-fpm.sock;

    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    fastcgi_param PATH_INFO $fastcgi_path_info;
}
```

`fastcgi_split_path_info` разбивает URI на скрипт и `PATH_INFO`, что требуется многими фреймворками. Регулярное выражение `^/index\.php(/|$)` гарантирует, что в обработку попадает только реальный front-controller — запросы вида `/uploads/x.jpg` не будут исполнены как PHP.

### Сценарий 4: Кэширование FastCGI-ответов

```nginx
fastcgi_cache_path /var/cache/angie/fcgi levels=1:2 keys_zone=fcgi:64m inactive=1h max_size=1g;

location ~ \.php$ {
    try_files $uri =404;
    fastcgi_pass unix:/run/php/php8.4-fpm.sock;
    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;

    # Зона, ключ и время жизни
    fastcgi_cache fcgi;
    fastcgi_cache_key "$request_method|$uri|$query_string";
    fastcgi_cache_valid 200 301 302 1h;

    # Не кэшировать залогиненных пользователей и POST
    fastcgi_cache_bypass $http_cookie;
    fastcgi_no_cache $http_cookie;

    # Инструкция бэкенду не кэшировать самому (X-Accel-Expires)
    fastcgi_cache_use_stale error timeout updating http_500 http_502 http_503;
}
```

Кэширование динамических PHP-страниц оправдано для публичных страниц (главная, каталог, статьи) при высокой посещаемости. Для страниц с персональными данными всегда отключайте кэш по cookie.

### Сценарий 5: Статусная страница и health-check PHP-FPM

```nginx
location = /fpm_status {
    access_log off;
    # Разрешаем только мониторингу
    allow 127.0.0.1;
    allow 10.0.0.0/8;
    deny all;

    # Статус FPM должен быть включен в /etc/php/*/fpm/pool.d/*.conf:
    # pm.status_path = /fpm_status
    fastcgi_pass unix:/run/php/php8.4-fpm.sock;
    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

Вывод страницы: `pool, process manager, start time, accepted conn, listen queue, max active processes, max children reached`. Метрики `pm.max_children_reached` и `listen queue` — главные сигналы нехватки пула. Подробнее см. [Мониторинг PHP-FPM](../PHP/php-fpm-monitoring.md).

## Операции и команды

```bash
# Проверка конфигурации Angie
angie -t
# → nginx: the configuration file /etc/angie/angie.conf syntax is ok

# Проверка, что сокет создан и принадлежит правильной группе
ls -la /run/php/php8.4-fpm.sock
# → srw-rw---- 1 www-data www-data ... /run/php/php8.4-fpm.sock

# Проверка пула FPM (статус)
curl http://127.0.0.1/fpm_status?full
# → pool: www  ...  accepted conn: 15234  listen queue: 0  max children reached: 1

# Перезапуск PHP-FPM (Debian/Ubuntu)
sudo systemctl restart php8.4-fpm

# Стресс-тест сокета через cgi-fcgi (перед вводом в эксплуатацию)
echo -e "GET /index.php HTTP/1.0\r\n\r\n" | cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock

# Проверка зоны fastcgi_cache
angie -s reload   # применение конфигурации
curl http://127.0.0.1/status/http/cache_zones/   # через API, при включенном status
```

## Устранение неисправностей

### 502 Bad Gateway от FastCGI

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `connect() to unix:/run/php/... failed (13: Permission denied)` | Права на каталог сокета | Добавить пользователя Angie в группу `www-data`; проверить `chmod 775 /run/php` |
| `connect() to ... failed (111: Connection refused)` | FPM не запущен или слушает другой адрес | `systemctl status php8.4-fpm`; проверить `listen =` в пуле |
| `no such file or directory` в `SCRIPT_FILENAME` | Путь не совпадает с корнем FPM | Проверить `root`/`$document_root` и путь на хосте FPM |
| `Primary script unknown` (404) | `try_files $uri =404` отсутствует; путь маппится неверно | Добавить `try_files $uri =404;` и проверить `fastcgi_split_path_info` |
| `upstream sent too big header` | Большие заголовки приложения | Увеличить `fastcgi_buffer_size` и `fastcgi_buffers` |

### 504 Gateway Timeout

FPM не успевает ответить в пределах `fastcgi_read_timeout` (по умолчанию 60s). Для долгих операций (экспорт, тяжёлые отчёты) увеличьте таймаут или переведите операцию в фоновую задачу:

```nginx
location ~ \.php$ {
    fastcgi_read_timeout 300s;
    fastcgi_send_timeout 300s;
    fastcgi_connect_timeout 10s;
    ...
}
```

### Высокая нагрузка на CPU и отказоустойчивость

Демонстрируются на странице `/fpm_status`: `max children reached` — пул исчерпан, увеличить `pm.max_children` и `pm.max_requests` (перезапуск воркеров для борьбы с утечками памяти). Если FPM падает непрерывно — проверьте логи FPM: `journalctl -u php8.4-fpm`, а также не держите `pm = static` там, где трафик разнородный (используйте `dynamic` или `ondemand`).

## Лучшие практики

*   **Отдавать PHP только через regex-location** (`\.php$`) с `try_files $uri =404;` — защита от Remote Code Execution через загрузку файлов.
*   **Запрещать exec в каталогах загрузок:** для `/uploads/` исключайте `location` PHP, либо используйте `deny`/`disable_functions`.
*   **Передавать реальный протокол и IP:** после TLS-терминации всегда выставляйте `fastcgi_param HTTPS on;` (иначе PHP думает, что соединение «чистое»), а реальный IP клиента — из `X-Forwarded-For` через `set_real_ip_from` (подробнее в [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)).
*   **Включать keepalive к FPM** (`fastcgi_keep_conn on;` + `keepalive` в upstream) — сильно снижает число TCP-соединений на хосте при высоком RPS.
*   **Использовать Unix-сокет в пределах одного хоста;** TCP — только когда FPM действительно вынесен на отдельную машину.
*   **Ограничивать `fastcgi_cache` зонами и очищать** через `proxy_cache_purge` при инвалидации (см. [High Load — кэширование](./High_Load/index.md)).

## Дополнительная информация

*   [Примеры интеграции location (Nginx)](../Nginx/Core/Location/integration_examples.md) — развёрнутые конфиги PHP, WordPress, Node.js для семейства Nginx/Angie.
*   [Мониторинг PHP-FPM](../PHP/php-fpm-monitoring.md) — метрики пула, Prometheus/php-fpm-exporter, диагностика.
*   [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md) — общий прокси-контекст и таймауты.

## См. также

*   [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
*   [Высокие нагрузки и защита от атак (Angie)](./High_Load/index.md)