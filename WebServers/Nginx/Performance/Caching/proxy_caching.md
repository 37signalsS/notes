# Серверное кэширование (Proxy Cache) в Nginx и Angie

## Определения

**Серверное кэширование (Proxy Cache)** — механизм, при котором Nginx или Angie сохраняет ответы от бэкенд-серверов в локальном хранилище, чтобы отдавать их последующим клиентам напрямую. Это радикально снижает нагрузку на приложение и базу данных, а также минимизирует TTFB (Time to First Byte).

**Кэш-зона (Cache Zone)** — именованная область в разделяемой памяти (`keys_zone`), где хранятся ключи кэшированных объектов и их метаданные (TTL, время доступа, счетчики). Сами тела ответов хранятся на диске. 1 МБ зоны вмещает примерно 8 000 ключей.

**Кэш-индекс (Cache Index)** — база метаданных в оперативной памяти (`keys_zone`), содержащая хэши ключей и информацию о расположении файлов на диске. Nginx/Angie обращаются к индексу, чтобы определить наличие ресурса, не сканируя файловую систему.

**Кэш-загрузчик (Cache Loader)** — дочерний процесс, который при старте сервера сканирует директорию кэша для наполнения `keys_zone`. На высоконагруженных системах это создает всплеск IOPS.

**Кэш-менеджер (Cache Manager)** — периодический процесс, который удаляет устаревшие или невостребованные данные при превышении `max_size` по алгоритму LRU (Least Recently Used).

**Микрокэширование (Microcaching)** — стратегия кэширования динамического контента на очень короткий срок (обычно 1–5 секунд) для защиты от всплесков нагрузки (Cache Stampede).

**Cache Stampede (Стадо бизонов)** — одновременный всплеск запросов к бэкенду при истечении TTL популярного ресурса из-за массового сброса кэша.

**Cache Poisoning (Отравление кэша)** — риск отдачи неверного контента из-за недостаточно точного ключа кэша или игнорирования заголовков, влияющих на вариативность ответа.

Общий обзор всех типов кэширования доступен в [Обзоре кэширования](./overview.md).

## Основные концепции

### Двухуровневая архитектура

Proxy Cache в Nginx и Angie строится на двух уровнях хранения:

1.  **RAM (Shared Memory):** Зона `keys_zone` обеспечивает доступ всем воркерам к метаданным. Размер зоны напрямую определяет максимальное количество объектов в кэше: 1 МБ ≈ 8 000 ключей. При заполнении зоны старые записи вытесняются.
2.  **Диск (Filesystem):** Тела ответов хранятся в директории, заданной в `proxy_cache_path`. Использование системного Page Cache в Linux позволяет «горячим» файлам фактически отдаваться из оперативной памяти. Подробнее о взаимодействии с ОС см. в [Мониторинге кэширования](./monitoring.md).

Nginx не хранит тело ответа в своей оперативной памяти (только индекс в `keys_zone`). Это отличает Proxy Cache от некоторых других reverse-proxy решений, которые буферизуют тело в пользовательском пространстве.

### Жизненный цикл объекта

*   **TTL (Time To Live):** Определяется директивой `proxy_cache_valid` или заголовками бэкенда (`X-Accel-Expires`, `Cache-Control`, `Expires`).
*   **Inactive:** Параметр в `proxy_cache_path`, удаляющий данные, к которым не было обращений в течение указанного времени, независимо от их TTL.
*   **Purge:** Принудительное удаление объекта по его ключу. В Nginx OSS требует стороннего модуля (`ngx_cache_purge`), в Angie поддерживается нативно.
*   **Revalidate:** При истечении TTL Nginx отправляет условный GET с заголовками `If-None-Match` / `If-Modified-Since`. Если бэкенд возвращает `304`, объект продлевается без повторной передачи тела.

### Директивы управления потоком запросов

*   **`proxy_cache_bypass`** — позволяет обойти кэш для определенных запросов (например, при наличии куки авторизации).
*   **`proxy_no_cache`** — определяет условия, при которых ответ не должен сохраняться в кэш.
*   **`proxy_cache_lock`** — при истечении TTL популярного ресурса отправляет только один запрос к бэкенду, остальные ожидают появления данных в кэше.
*   **`proxy_cache_background_update`** — отдает устаревший контент клиенту, пока фоновый запрос обновляет кэш.

## Практические сценарии

### Шаг 1: Глобальное определение пути кэша

Настройка выполняется в контексте `http`. Приведите конфигурацию к следующему виду:

```nginx
http {
    proxy_cache_path /var/cache/nginx/proxy_cache
                      levels=1:2
                      keys_zone=my_cache:100m
                      inactive=24h
                      max_size=10g
                      use_temp_path=off;
}
```

Проверка конфигурации:

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

Применение без потерь соединений:

```bash
nginx -s reload
```

Параметры:
*   **`levels=1:2`**: Группировка файлов в подпапки. Предотвращает замедление работы файловой системы (XFS/ext4) при наличии миллионов объектов.
*   **`use_temp_path=off`**: Отключает промежуточную директорию для временных файлов. Nginx пишет файлы сразу в целевую директорию кэша, избегая лишнего копирования.
*   **`max_size=10g`**: Порог, при котором процесс `cache manager` начинает удалять наименее востребованные данные (LRU).
*   **`inactive=24h`**: Данные, к которым не обращались в течение 24 часов, удаляются независимо от TTL.

### Шаг 2: Базовое кэширование API

```nginx
server {
    location /api/v1/ {
        proxy_pass http://backend_cluster;

        proxy_cache my_cache;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_methods GET HEAD;
        proxy_cache_convert_head on;
        proxy_cache_min_uses 3;
        proxy_cache_valid 200 10m;

        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

Ожидаемое поведение:
*   Первые 2 запроса к ресурсу проходят на бэкенд (`MISS`), начиная с 3-го — отдается из кэша (`HIT`).
*   HEAD-запросы считаются как GET, увеличивая коэффициент попаданий.

### Шаг 3: Stale-While-Revalidate и защита от Cache Stampede

Этот сценарий обеспечивает нулевую задержку для пользователей при обновлении кэша и отказоустойчивость при сбоях бэкенда:

```nginx
location /api/v1/ {
    proxy_pass http://backend_cluster;
    proxy_cache my_cache;

    proxy_cache_key "$scheme$request_method$host$request_uri";
    proxy_cache_valid 200 10m;

    # Фоновое обновление: отдать старый кэш, пока идет запрос к бэкенду
    proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
    proxy_cache_background_update on;

    # Защита от «стада бизонов»
    proxy_cache_lock on;
    proxy_cache_lock_timeout 5s;

    # Условные GET при обновлении
    proxy_cache_revalidate on;

    add_header X-Cache-Status $upstream_cache_status;
}
```

### Шаг 4: Кэширование публичного API при наличии Set-Cookie

По умолчанию Nginx не кэширует ответы с заголовком `Set-Cookie`. Для публичных API часто требуется принудительно игнорировать инструкции приложения:

```nginx
location /api/public/ {
    proxy_cache my_cache;
    proxy_ignore_headers Cache-Control Expires Set-Cookie;
    proxy_hide_header Set-Cookie;

    proxy_cache_valid 200 1h;
}
```

### Шаг 5: Очистка кэша (Purge)

В **Angie** функционал встроен в ядро. В **Nginx OSS** требуется сторонний модуль (например, `ngx_cache_purge`).

```nginx
# Angie: встроенный PURGE
location / {
    proxy_cache my_cache;
    proxy_cache_purge PURGE from 127.0.0.1 10.0.0.0/8;
    proxy_pass http://backend;
}
```

Очистка из CLI:

```bash
# Angie/Nginx: полная очистка кэша
systemctl stop nginx
rm -rf /var/cache/nginx/proxy_cache/*
systemctl start nginx

# Частичная очистка по пути
curl -X PURGE http://localhost/api/v1/resource
```

### Шаг 6: Персистентность индекса (Angie 1.9+)

В Angie 1.9+ добавьте параметр `file=` для сохранения индекса на диск:

```nginx
proxy_cache_path /var/cache/angie/proxy_cache
                  levels=1:2
                  keys_zone=my_cache:100m
                  inactive=24h
                  max_size=10g
                  file=/var/lib/angie/my_cache.zone;
```

Это исключает фазу сканирования диска (cache loader) при холодном старте. При перезапуске индекс загружается мгновенно, Hit Ratio не падает до 0%.

## Операции и команды

| Задача | Команда / Директива | Ожидаемый результат |
| :--- | :--- | :--- |
| Проверка конфигурации | `nginx -t` | `test is successful` |
| Применение конфигурации | `nginx -s reload` | Перезагрузка без потерь соединений |
| Статистика кэш-зоны | `curl http://127.0.0.1/status/http/cache_zones/` | JSON со счетчиками HIT/MISS/BYPASS |
| Подсчет статусов из лога | `jq -r '.cache_status' /var/log/nginx/cache_access.json \| sort \| uniq -c \| sort -rn` | Распределение статусов кэша |
| Проверка Page Cache | `cachestat 5` (требует bcc/bpf) | `HITS` / `MISSES` в реальном времени |
| Мониторинг slab | `slabtop -o` | Использование dentry/inode cache ядра |
| Проверка диска | `iostat -x 5` | await, %util для устройства кэша |
| Полная очистка | `rm -rf /var/cache/nginx/proxy_cache/* && systemctl reload nginx` | Директория пуста, кэш холодный |
| Purge ресурса | `curl -X PURGE http://localhost/api/v1/resource` | `200 OK` или `404 Not Found` (если не найден) |

## Troubleshooting

### Низкий Cache Hit Ratio после рестарта

**Симптом:** После `systemctl restart nginx` Hit Ratio падает до 0%, нагрузка на диск резко возрастает.

**Причина:** Cache Loader сканирует директорию кэша и загружает ключи в `keys_zone`. Пока индекс не готов, все запросы идут в MISS.

**Диагностика:**
```bash
# Проверка процессов
ps aux | grep -E 'nginx: cache|loader'

# Нагрузка на диск
iostat -x 5
```

**Решение:**
*   Angie 1.9+: добавьте `file=/var/lib/angie/my_cache.zone` в `proxy_cache_path`.
*   Nginx OSS: предварительный прогрев кэша (cache warm-up) или увеличение `loader_threshold`.

### Cache Stampede при истечении TTL

**Симптом:** Всплеск latency и ошибок 502 при одновременном обновлении популярного ресурса.

**Причина:** Множество запросов одновременно попадают на MISS и конкурируют за бэкенд.

**Диагностика:**
```bash
# Одинаковое время запросов в логе
grep "GET /api/v1/trending" /var/log/nginx/access.log | awk '{print $4}' | sort | uniq -c | sort -rn | head
```

**Решение:**
```nginx
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
```

### Отсутствие кэширования авторизованных сессий

**Симптом:** Все запросы с `Cookie` возвращают `BYPASS` или `MISS`.

**Причина:** По умолчанию Nginx не кэширует ответы с заголовком `Set-Cookie` и при наличии куки в запросе.

**Диагностика:**
```bash
curl -I -b "session=abc123" http://localhost/api/v1/resource
```

**Решение:** Для публичных API, не зависящих от сессии:
```nginx
proxy_ignore_headers Set-Cookie;
proxy_hide_header Set-Cookie;
proxy_cache_bypass $cookie_session;
```

### Кэш не обновляется

**Симптом:** Контент устарел, хотя TTL истек.

**Причина:** Слишком длинный `inactive` или достигнут `max_size`, и `cache manager` не удалил старые данные.

**Диагностика:**
```bash
du -sh /var/cache/nginx/proxy_cache/*
```

**Решение:** Увеличить `max_size` или настроить `proxy_cache_valid` в соответствии с SLO обновления контента.

### Ошибка 502 при обновлении кэша

**Симптом:** Клиенты получают 502 при истечении TTL, даже если бэкенд здоров.

**Причина:** Отсутствует `proxy_cache_use_stale`, поэтому при проблемах с бэкендом во время обновления кэш не может отдать устаревшую версию.

**Решение:**
```nginx
proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
```

### Отравление кэша (Cache Poisoning)

**Симптом:** Разные клиенты получают контент, предназначенный для других (язык, устройство, регион).

**Причина:** `proxy_cache_key` не включает переменные, влияющие на ответ.

**Диагностика:** Проверка конфигурации на полноту ключа.

**Решение:**
```nginx
proxy_cache_key "$scheme$request_method$host$request_uri";
```

Если бэкенд отдает разный контент по `Accept-Encoding`, убедитесь в наличии заголовка `Vary: Accept-Encoding`.

## Best Practices

1.  **Разделение кэшей:** Используйте отдельные зоны `keys_zone` для разных типов контента (API, статика, изображения). Это упрощает управление TTL и очистку.
2.  **Ключ кэша:** Всегда включайте в `proxy_cache_key` параметры, влияющие на ответ (язык, `Accept-Encoding`, протокол). Пример: `proxy_cache_key "$scheme$request_method$host$request_uri";`
3.  **Заголовки Vary:** Если бэкенд отдает разный контент по заголовку `Accept-Encoding` (gzip/brotli), убедитесь, что он шлет `Vary: Accept-Encoding`.
4.  **Защита от Stampede:** Для популярных ресурсов всегда используйте `proxy_cache_lock on;` с `proxy_cache_lock_timeout 5s;`.
5.  **Безопасность:** Категорически запрещено использовать `proxy_ignore_headers Set-Cookie` в зонах с авторизацией (личные кабинеты), так как это приведет к кэшированию персональных данных.
6.  **IO Performance:** На высоконагруженных системах используйте `aio threads` вместе с кэшем, чтобы операции чтения с диска не блокировали воркеры Nginx. Подробнее см. в [Тюнинге производительности Nginx](../nginx_performance_tuning.md).
7.  **Персистентность:** В Angie 1.9+ всегда используйте `file=` в `proxy_cache_path` для ускорения холодного старта.
8.  **Мониторинг:** Включите `add_header X-Cache-Status $upstream_cache_status;` для аудита эффективности кэширования.
9.  **Безопасность интерфейсов:** Ограничьте доступ к статус-эндпоинтам и API директивой `allow` для доверенных IP и `deny all` для всего остального.
10. **Capacity Planning:** Размер `keys_zone` должен покрывать максимальное количество уникальных объектов. Формула ориентировочная: 8 000 ключей на 1 МБ. Мониторьте `max_size` и `inactive` в соответствии с ростом контента.

## Дополнительная информация

### Сравнение возможностей

| Функция | Nginx OSS (1.30.x stable / 1.31.x mainline) | Angie (1.12.x) |
| :--- | :--- | :--- |
| **Proxy Cache Lock** | Да | Да |
| **Background Update** | Да | Да |
| **Purge (Wildcards/\*)** | Только модули | **Да (нативно)** |
| **Index Persistence** | Нет | **Да (`file=`)** |
| **JSON Status API** | Нет | **Да (нативно)** |

### См. также

*   [Обзор кэширования в Nginx и Angie](./overview.md) — классификация и стратегии.
*   [Мониторинг кэширования](./monitoring.md) — детальный разбор `$upstream_cache_status` и метрик.
*   [Клиентское кэширование](./client_caching.md) — управление поведением браузеров.
