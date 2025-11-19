# Мониторинг Angie с помощью Console Lite и API

Это руководство описывает возможности мониторинга веб-сервера Angie (NGINX) с использованием встроенного API и консоли NG Console Lite.

## Ограничения `stub_status`

Исторически NGINX предоставлял базовый модуль `stub_status` для мониторинга. Он предоставляет минимальный набор метрик, в основном касающихся только общего состояния подключений (активные, ожидающие и т.д.), и не включает информацию о запросах, кодах ответа или состоянии апстримов. Для более детального мониторинга требовались сторонние модули, которые необходимо было компилировать и подключать отдельно, либо парсить access-логи, что неудобно и создает дополнительную нагрузку.

## Angie API и Console Lite

В Angie встроен мощный API для мониторинга, который заменяет устаревший модуль `stub_status`. Этот API отдает сотни метрик в формате JSON, на основе которых работает веб-интерфейс `Console Lite` и [экспортер для Prometheus](./monitoring_with_prometheus_and_grafana.md).

## 1. Установка Angie Console Lite

Пакет для Angie Console Lite называется `angie-console-lite`. Для Angie Pro — `angie-pro-console-lite`. Он содержит статические HTML/JS файлы веб-интерфейса. Установка производится через стандартный пакетный менеджер вашего дистрибутива.

## 2. Настройка API и Console Lite

Настройка включает два шага:
1.  Настройка `location` для доступа к API.
2.  Настройка `location` для обслуживания статических файлов Console Lite.

Рекомендуется выделять для мониторинга отдельный `server` блок, слушающий на другом порту или домене, чтобы защитить его от публичного доступа.

### Пример конфигурации

```nginx
server {
    listen 8888 ssl;
    server_name monitor.example.com;

    # Защита доступа
    allow 127.0.0.1;
    deny all;
    # Или можно использовать базовую аутентификацию
    # auth_basic "Restricted Area";
    # auth_basic_user_file /etc/angie/conf.d/.htpasswd;

    ssl_certificate /etc/angie/ssl/monitor.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/monitor.example.com.key;

    # Настройка для обслуживания файлов Angie Console Lite
    location / {
        root /usr/share/angie-console-lite/html; # Путь может отличаться
    }

    # Настройка для Angie API
    location /api/ {
        api; # В Angie 1.5.0+ можно использовать write=on/off для управления апстримами
    }
}
```

## 3. Зоны мониторинга

Чтобы API начал отдавать подробные метрики, необходимо определить "зоны" для сбора статистики в вашей основной конфигурации.

-   **Для `server` блока:**
    ```nginx
    server {
        listen 80;
        server_name example.com;
        status_zone server_example; # Имя зоны для этого сервера
        # ...
    }
    ```
-   **Для `location` блока:**
    ```nginx
    location /api/v2/ {
        status_zone api_v2; # Имя зоны для этого location
        # ...
    }
    ```
-   **Для `upstream` группы:**
    ```nginx
    upstream backend {
        zone upstream_backend 64k; # Зона разделяемой памяти для хранения состояния и метрик
        server 127.0.0.1:8080;
    }
    ```
-   **Для кэша:**
    ```nginx
    proxy_cache_path /var/cache/angie/proxy_cache keys_zone=my_cache:10m;
    ```
    Зона `my_cache` будет автоматически доступна для мониторинга.

## 4. Обзор интерфейса Console Lite

После настройки зон в веб-интерфейсе Console Lite (например, `https://monitor.example.com:8888`) появятся соответствующие вкладки:

-   **Dashboard:** Общая сводка (версия Angie, аптайм, статистика по соединениям, как в `stub_status`).
-   **HTTP Zones:** Статистика по `status_zone`, определенным в `server` и `location` блоках. Здесь можно увидеть запросы/c, трафик, количество ответов по кодам (2xx, 3xx, 4xx, 5xx) для каждой зоны отдельно.
-   **HTTP Upstreams:** Состояние и метрики для каждой `upstream` группы. Показывает, какие серверы в группе `up`, `down` или в другом состоянии, количество запросов к ним, ошибки, трафик.
-   **TCP/UDP Upstreams:** Аналогично для L4-балансировки в модуле `stream`.
-   **Caches:** Статистика по зонам кэширования (`keys_zone` из `proxy_cache_path`). Отображает размер, процент попаданий (`hit ratio`), использование диска.
-   **Shared Zones:** Обзор использования всех зон разделяемой памяти (`shared memory zones`). Это критически важный дашборд для понимания, достаточно ли выделено памяти под разные нужды (апстримы, кэш, сессии TLS, лимиты). Помогает избежать ошибок "cannot allocate memory".
-   **Resolvers:** Статистика для DNS-резолверов.

В версии **Angie Pro** через этот же интерфейс можно управлять состоянием апстримов (менять вес, статус и т.д.).

## 5. Использование API напрямую

Веб-консоль и Prometheus exporter работают через JSON API, который можно использовать напрямую.

-   **Получение всех метрик:**
    ```bash
    # Замените порт и домен на свои
    curl -s https://monitor.example.com:8888/api/ | jq
    ```

-   **Получение конкретной группы метрик (например, `http`):**
    ```bash
    curl -s https://monitor.example.com:8888/api/http/ | jq
    ```

-   **Просмотр конфигурации:**
    API также может отдавать конфигурационные файлы, что полезно для отладки (но может быть небезопасно, поэтому доступ к API должен быть строго ограничен).
    ```bash
    curl -s https://monitor.example.com:8888/api/config_files/ | jq
    ```

Прямой доступ к API позволяет интегрировать мониторинг Angie с любой системой (Zabbix, Nagios и др.), написав простой парсер JSON.

## См. также

*   [Мониторинг Angie с помощью Prometheus и Grafana](./monitoring_with_prometheus_and_grafana.md)
*   [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)
*   [Установка Angie из пакетов](./angie_installation.md)
*   [Почему стоит переходить на Angie](./angie_why_migrate.md)

