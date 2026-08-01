# Настройка Angie в роли обратного HTTP-прокси

## Определения

**Обратный прокси-сервер (Reverse Proxy)** — промежуточный сервер, который принимает запросы от внешних клиентов и перенаправляет их на один или несколько бэкенд-серверов. Для клиента прокси-сервер является единственной точкой входа, скрывающей внутреннюю топологию сети. Подробнее о концепции: [Прокси-сервер](../../Networking/Concepts/proxy.md).

**Бэкенд (Upstream)** — целевой сервер или группа серверов (приложение, база данных, другой прокси), обрабатывающих запрос.

## Базовые концепции

В Angie (и Nginx) функциональность обратного прокси реализуется модулем `ngx_http_proxy_module`. Он позволяет не только пересылать трафик, но и модифицировать его «на лету».

### Основные задачи
1. **Терминация TLS:** прокси берет на себя ресурсоемкие операции шифрования.
2. **Балансировка:** распределение трафика для масштабирования. Подробнее: [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md).
3. **Безопасность:** защита бэкендов от прямых атак и сокрытие их реальных IP.
4. **Оптимизация протоколов:** возможность принимать запросы по HTTP/3 и транслировать их на бэкенд по HTTP/1.1.

### Минимальная конфигурация
```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        # Пересылка всех запросов на локальное приложение
        proxy_pass http://127.0.0.1:8080;
    }
}
```

## Практические сценарии

### Управление заголовками и реальный IP
Чтобы бэкенд-приложение могло идентифицировать клиента и оригинальный хост, необходимо передать соответствующие заголовки.

```nginx
location / {
    proxy_pass http://backend_pool;
    
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Обработка путей (URI)
Важно помнить о влиянии завершающего слеша в директиве `proxy_pass`:
*   `proxy_pass http://app;` (без слеша) — путь передается в бэкенд полностью.
*   `proxy_pass http://app/;` (со слешем) — часть пути, совпавшая с `location`, заменяется на `/`.

Подробнее о выборе блоков: [Директивы location в Angie](./angie_location_directives.md).

### Проксирование WebSocket
Для работы WebSocket требуется явное переключение протокола через заголовки `Upgrade` и `Connection`.

```nginx
http {
    # Динамическое определение значения заголовка Connection
    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
    }

    server {
        location /ws/ {
            proxy_pass http://ws_backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            
            # Увеличение таймаутов для долгоживущих соединений
            proxy_read_timeout 3600s;
        }
    }
}
```

### Поддержка gRPC
Angie поддерживает нативное проксирование gRPC-трафика (включая работу через UNIX-сокеты).

```nginx
location /api.v1.Service/ {
    # Использование специализированной директивы
    grpc_pass grpc://unix:/tmp/grpc.sock;
    
    # Для шифрованного gRPC используйте grpcs://
}
```

### Проксирование по HTTP/3 на бэкенд (Angie-specific)
В отличие от стандартного Nginx, Angie умеет общаться с бэкендами по протоколу HTTP/3.

```nginx
location /high-speed/ {
    proxy_pass https://modern_backend;
    # Включение HTTP/3 для взаимодействия с бэкендом
    proxy_http_version 3.0;
}
```

### Проксирование на UNIX-сокеты
Использование UNIX domain sockets вместо TCP-портов повышает производительность при размещении прокси и бэкенда на одной машине.

```nginx
location /app/ {
    proxy_pass http://unix:/var/run/python_app.sock;
}
```

## Дополнительная информация

### Оптимизация и таймауты
Для предотвращения накопления «зависших» соединений всегда настраивайте таймауты:
*   `proxy_connect_timeout`: время ожидания установки соединения.
*   `proxy_read_timeout`: ожидание ответа от бэкенда (важно для тяжелых запросов).
*   `proxy_buffering on`: позволяет Angie вычитывать ответ бэкенда в память, быстрее освобождая воркер приложения.

### Кэширование ответов
Снижает нагрузку на бэкенд за счет хранения статических или редко меняющихся ответов. Полное руководство: [Серверное кэширование в Nginx](../Nginx/Performance/Caching/proxy_caching.md).

## См. также

* [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
* [Настройка TLS в Angie](./angie_tls_setup.md)
* [Оптимизация производительности Angie](./High_Load/performance_optimization.md)
