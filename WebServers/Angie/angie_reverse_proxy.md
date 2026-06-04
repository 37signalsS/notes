# Настройка Angie в роли обратного HTTP-прокси

## Определения

**Обратный прокси-сервер (Reverse Proxy)** — сервер, принимающий запросы от клиентов и перенаправляющий их на один или несколько бэкенд-серверов. Для клиента прокси-сервер выступает как конечная точка, скрывая внутреннюю архитектуру сети. Подробнее о концепции: [Прокси-сервер](../../Networking/Concepts/proxy.md).

**Модуль `ngx_http_proxy_module`** — основной модуль в Angie (и Nginx), реализующий функции проксирования HTTP-запросов.

## Основные концепции

### Задачи обратного прокси

1. **Скрытие внутренней сети:** Клиенты взаимодействуют только с IP прокси-сервера.
2. **Балансировка нагрузки:** Распределение трафика между группой бэкендов. Подробнее: [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md).
3. **Терминация SSL/TLS:** Снятие нагрузки по шифрованию с бэкенд-серверов. Подробнее: [Настройка TLS в Angie](./angie_tls_setup.md).
4. **Кэширование:** Хранение ответов бэкендов для ускорения повторных запросов.

### Минимальная конфигурация

Базовая настройка для перенаправления всех запросов на один бэкенд:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        # Все запросы на корень сайта уходят на порт 9000
        proxy_pass http://localhost:9000;
    }
}
```

Директива `proxy_pass` определяет протокол и адрес бэкенда.

## Практические сценарии

### Управление заголовками

По умолчанию прокси-сервер изменяет или удаляет некоторые заголовки клиента. Для корректной работы приложения бэкенд должен знать реальный IP клиента и оригинальный хост.

```nginx
location / {
    proxy_pass http://localhost:9000;
    
    # Передача реального IP клиента
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    # Передача оригинального заголовка Host и протокола (http/https)
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

- `$remote_addr` — IP-адрес непосредственного клиента.
- `$proxy_add_x_forwarded_for` — добавляет адрес клиента в цепочку заголовка `X-Forwarded-For`.
- `$host` — имя хоста из запроса клиента.

### Обработка URI (слеши в proxy_pass)

Логика изменения пути (URI) зависит от наличия завершающего слеша в директиве `proxy_pass`.

1. **Без слеша:** `proxy_pass http://backend;`
    Запрос `/api/users` при `location /api/` будет проксирован на `http://backend/api/users` (путь передается целиком).
2. **Со слешем:** `proxy_pass http://backend/;`
    Запрос `/api/users` при `location /api/` будет проксирован на `http://backend/users` (часть пути, совпавшая с `location`, отбрасывается).

Подробнее о маршрутизации: [Директивы location в Angie](./angie_location_directives.md).

### Тюнинг производительности

Для высоконагруженных систем необходимо оптимизировать взаимодействие с бэкендами. Детальное описание этих параметров приведено в руководстве: [Практическая конфигурация балансировки Nginx](../Nginx/Proxy/Load_Balancing/practical_configuration.md).

- **Keep-alive соединения:** Снижают задержки на установку TCP-соединений.

    ```nginx
    # Требует настройки upstream с keepalive и следующих параметров в location:
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    ```

- **Буферизация (`proxy_buffering`):** Позволяет Angie накапливать ответ бэкенда перед отправкой клиенту, освобождая ресурсы бэкенда быстрее.
- **Таймауты:** Настройка `proxy_connect_timeout`, `proxy_read_timeout` и `proxy_send_timeout` позволяет предотвратить зависание ресурсов при сбоях бэкендов.

### Перехват ошибок (proxy_intercept_errors)

Директива позволяет Angie перехватывать HTTP-ошибки от бэкенда (коды 4xx и 5xx) и возвращать клиенту кастомные страницы, настроенные через `error_page`.

```nginx
location / {
    proxy_pass http://backend;
    proxy_intercept_errors on;
    error_page 502 503 504 /custom_50x.html;
}
```

### Проксирование на HTTPS-бэкенд

Если бэкенд требует защищенного соединения, в `proxy_pass` указывается протокол `https`.

```nginx
location / {
    proxy_pass https://secure_backend;
    
    proxy_ssl_server_name on;           # Передача SNI бэкенду
    proxy_ssl_verify on;                # Проверка сертификата бэкенда
    proxy_ssl_trusted_certificate /etc/angie/certs/ca.crt;
    proxy_ssl_session_reuse on;         # Использование кэша TLS-сессий
}
```

## Дополнительная информация

### Кэширование

Для снижения нагрузки на бэкенды Angie поддерживает мощный механизм кэширования ответов. Полное руководство по настройке зон и стратегий кэширования: [Серверное кэширование в Nginx](../Nginx/Performance/Caching/proxy_caching.md).

### См. также

- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
- [Директивы location в Angie](./angie_location_directives.md)
- [Прокси-сервер — концепция](../../Networking/Concepts/proxy.md)
