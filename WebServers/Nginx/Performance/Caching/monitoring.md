# Мониторинг кэширования в Nginx и Angie

## Определения

**Коэффициент попаданий в кэш (Cache Hit Ratio)** — доля запросов, отданных из кэша (`HIT`), относительно общего числа запросов. Выражается в процентах. Целевые значения зависят от типа контента: >95% для статики, >50% для динамического API.

**`$upstream_cache_status`** — встроенная переменная Nginx/Angie, фиксирующая результат обработки запроса подсистемой кэширования.

| Статус | Описание | Состояние Page Cache ОС |
| :--- | :--- | :--- |
| **HIT** | Ответ отдан напрямую из кэша. | Чтение из RAM (горячий) или диска. |
| **MISS** | Запрос не найден, данные получены от бэкенда. | Запись нового файла на диск. |
| **EXPIRED** | TTL истек, Nginx запросил обновление у бэкенда. | Перезапись существующего файла. |
| **STALE** | Отдан устаревший ответ (бэкенд недоступен или настроен `use_stale`). | Чтение из диска/RAM. |
| **UPDATING** | Отдан старый ответ, пока идет фоновое обновление. | Чтение + фоновая запись. |
| **BYPASS** | Кэш намеренно обойден (например, через `proxy_cache_bypass`). | Прямое проксирование. |
| **REVALIDATED** | Бэкенд подтвердил актуальность (`304 Not Modified`). | Обновление метаданных TTL в RAM. |

**Cache Stampede (Стадо бизонов)** — одновременный всплеск запросов к бэкенду при истечении TTL популярного ресурса из-за массового сброса кэша.

**Cache Loader** — дочерний процесс Nginx/Angie, который при старте сканирует директорию кэша для наполнения `keys_zone`. На холодном старте создает всплеск IOPS.

**Cache Manager** — периодический процесс, удаляющий устаревшие или невостребованные данные при превышении `max_size` по алгоритму LRU (Least Recently Used).

**Page Cache (ОС)** — механизм ядра Linux, кэширующий файлы в оперативной памяти. Nginx хранит в `keys_zone` только индекс (метаданные), а тела ответов лежат на диске и обслуживаются Page Cache. Если Page Cache эффективен, «чтение с диска» фактически происходит из RAM.

**Status Zone (Angie)** — именованная разделяемая память для сбора статистики по кэш-зонам, доступная через встроенный API без сторонних модулей.

**stub_status** — стандартный модуль Nginx (`ngx_http_stub_status_module`), предоставляющий базовые счетчики (активные соединения, принятые/обработанные запросы). Не содержит информации о кэше.

## Основные концепции

### Двухуровневая архитектура мониторинга

Эффективный мониторинг кэширования требует наблюдения за двумя уровнями одновременно:

1.  **Прикладной уровень (L7):** Анализ `$upstream_cache_status`, HTTP-заголовков и метрик Nginx/Angie. Позволяет понять логику: почему запрос попал в MISS или почему кэш не срабатывает для авторизованных пользователей.
2.  **Системный уровень (Page Cache + IO):** Наблюдение за оперативной памятью ядра, дисковыми операциями и устройствами хранения. Позволяет отличить настоящий MISS (файл отсутствует) от ложного MISS (файл есть, но был вытеснен из Page Cache).

### Взаимодействие Nginx с операционной системой

Nginx и Angie не хранят тело ответа в своей оперативной памяти (только индекс в `keys_zone`). Тело файла кэшируется Page Cache ядра Linux. Это означает:

- При HIT Nginx обращается к индекс в RAM, находит путь к файлу и читает его. Если файл находится в Page Cache, операция происходит без физического обращения к диску.
- При MISS Nginx запрашивает данные у бэкенда и записывает новый файл на диск, после чего он попадает в Page Cache.
- При переполнении `max_size` Cache Manager удаляет файлы по LRU. Если файл был «горячим» (в Page Cache), его удаление может вызвать кратковременный всплеск磁盘ных операций.

### Cache Loader и холодный старт

При старте Nginx/Angie процесс Cache Loader сканирует директорию кэша и загружает ключи в `keys_zone`. На высоконагруженных системах с миллионами объектов это создает пиковую нагрузку на диск (IOPS), которая может снизить производительность на несколько секунд.

**Решение (Angie 1.9+):** Параметр `file=` в `proxy_cache_path` сохраняет индекс на диск. При перезапуске индекса загружается мгновенно, исключая фазу сканирования.

### Cache Manager и пороговые значения

Cache Manager работает периодически (по умолчанию каждые 10 секунд при наличии изменений). Он удаляет объекты, которые не запрашивались дольше `inactive`, а при достижении `max_size` — наименее востребованные по LRU. Отслеживание активности Cache Manager важно для планирования дискового пространства.

## Практические сценарии

### Сценарий 1: JSON-логирование для аудита кэша

Для глубокого анализа используйте формат JSON, совместимый с ELK, Loki или VictoriaMetrics Logs. Обязательно включите `$upstream_cache_status`.

```nginx
log_format cache_json escape=json '{'
    '"time": "$time_iso8601", '
    '"remote_addr": "$remote_addr", '
    '"host": "$host", '
    '"request": "$request", '
    '"status": "$status", '
    '"cache_status": "$upstream_cache_status", '
    '"request_time": "$request_time", '
    '"upstream_response_time": "$upstream_response_time", '
    '"body_bytes_sent": "$body_bytes_sent"'
'}';

access_log /var/log/nginx/cache_access.json cache_json;
```

**Быстрая диагностика через консоль:**
```bash
# Подсчет статистики статусов кэша из JSON-лога
jq -r '.cache_status' /var/log/nginx/cache_access.json | sort | uniq -c | sort -rn
# →    4521 HIT
# →     312 MISS
# →      78 EXPIRED
```

### Сценарий 2: OpenTelemetry (Nginx 1.25.3+, Angie 1.9+)

Начиная с версии 1.25.3 в Nginx OSS доступен нативный модуль `ngx_otel_module` (пакет `nginx-module-otel`). В Angie поддержка OpenTelemetry также присутствует. Модуль экспортирует traces и может передавать статус кэша как атрибут span.

Для on-premise инфраструктуры используйте локальный OpenTelemetry Collector, принимающий данные по OTLP/gRPC.

```nginx
# Загрузка модуля (Debian/Ubuntu: пакет nginx-module-otel)
load_module modules/ngx_otel_module.so;

http {
    otel_exporter {
        endpoint 127.0.0.1:4317;
        # Время ожидания отправки батча
        batch_count 8;
    }
    otel_service_name nginx-proxy;
    otel_trace on;

    server {
        location /api/ {
            # Передача статуса кэша как атрибута трассировки
            otel_span_attr "http.cache.status" $upstream_cache_status;
            proxy_cache my_api_cache;
            proxy_pass http://backend;
        }
    }
}
```

**Валидация:**
```bash
# Проверка загрузки модуля
nginx -V 2>&1 | grep -o otel
# → module: /usr/lib/nginx/modules/ngx_otel_module.so

# Проверка конфигурации
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### Сценарий 3: Prometheus экспорт

#### Nginx OSS

Стандартный модуль `stub_status` не содержит информации о кэше. Для получения детальных метрик используйте:

1.  **nginx-vts-exporter** (требует сторонний модуль `nginx-module-vts`): предоставляет статистику по кэш-зонам, upstream, SSL и HTTP-кодам.
2.  **nginx-prometheus-exporter**: работает через `stub_status`, но кэш-специфичных метрик не дает (подходит только для общего health check).

#### Angie

Angie экспортирует метрики в формате Prometheus через встроенный модуль `prometheus` без сторонних экспортеров.

```nginx
http {
    # Включение встроенного Prometheus модуля
    prometheus;

    # Статистика по кэш-зонам
    # (если proxy_cache_path определен с keys_zone)
    server {
        listen 127.0.0.1:8080;

        location /metrics {
            allow 127.0.0.1;
            deny all;
            # Метрики доступны здесь
        }
    }
}
```

**Проверка:**
```bash
curl -s http://127.0.0.1:8080/metrics | grep -i cache
# → nginx_http_proxy_cache_hits{zone="my_cache"} 4521
# → nginx_http_proxy_cache_misses{zone="my_cache"} 312
```

### Сценарий 4: Мониторинг через Status Zones (Angie)

В Angie метрики по кэш-зонам доступны через встроенный API без сторонних экспортеров.

```nginx
http {
    # Определение зоны статистики (10 MB хватит для тысяч ключей)
    status_zone $host zone=cache_stats:10m;

    server {
        listen 127.0.0.1:8080;
        location /status {
            api /status/;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Запрос метрик:**
```bash
curl -s http://127.0.0.1:8080/status | jq '.caches'
# → {
#   "my_cache": {
#     "hits": 4521,
#     "misses": 312,
#     "expired": 78,
#     "bypass": 15
#   }
# }
```

### Сценарий 5: Мониторинг системного Page Cache (eBPF/bcc)

Чтобы подтвердить, что HIT действительно обслуживаются из оперативной памяти, используйте инструменты bcc/bpftrace. Это критично для производительности: если Page Cache неэффективен, каждый HIT превращается в физическое чтение с диска.

```bash
# Мониторинг попаданий в Page Cache в реальном времени
cachestat 5
# → HITS: 1245  MISSES: 12  DIRTIES: 340  BUFFERS_MB: 128

# Топ файлов по попаданиям в Page Cache
cachetop 1
# → UID   PID   COMM         HITS   MISSES  HIT_RATIO
# → root  1024  nginx: worker 9852   12      99.8%
```

**Дополнительные инструменты:**
```bash
# Анализ dentry/inode cache (важно для кэша Nginx)
slabtop -o | grep -E 'dentry|inode'
# →   OBJ   USED  OBJ_SIZE  SLABS  OBJ/SLAB  CACHE   NAME
# → dentry 124500   192      ...
# → inode_cache 89000    ...

# Мониторинг IOPS диска, где расположен кэш
iostat -x 1 10
# → Device            r/s     w/s     rkB/s    wkB/s  ...
# → sda              120.5   450.2    2048.0   8192.0  ...

# Анализ IO по процессам
iotop -p $(pgrep -f "nginx: worker") -b -n 1
```

## Операции и команды

### Валидация конфигурации

```bash
# Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Применение без потерь соединений
nginx -s reload
```

### Проверка stub_status (Nginx OSS)

```bash
# Активные соединения и базовые счетчики
curl -s http://127.0.0.1:8080/nginx_status
# → Active connections: 291
# → server accepts handled requests
# → 16630948 16630948 31070465
# → Reading: 6 Writing: 179 Waiting: 106
```

### Проверка API / Metrics (Angie)

```bash
# Статус через API
curl -s http://127.0.0.1:8080/status | jq '.caches'

# Прометейские метрики
curl -s http://127.0.0.1:8080/metrics | grep nginx_http_proxy_cache
```

### Анализ логов

```bash
# Распределение по статусам кэша
jq -r '.cache_status' /var/log/nginx/cache_access.json | sort | uniq -c | sort -rn

# Фильтр по времени (последний час)
jq -r 'select(.time > "2026-09-23T09:") | .cache_status' /var/log/nginx/cache_access.json | sort | uniq -c | sort -rn

# Среднее время ответа для MISS vs HIT
jq -r 'select(.cache_status=="MISS") | .upstream_response_time' /var/log/nginx/cache_access.json | awk '{s+=$1; n++} END {print s/n}'
```

### Мониторинг диска и памяти

```bash
# Использование места кэшем
du -sh /var/cache/nginx/proxy_cache/*
# → 4.2G    /var/cache/nginx/proxy_cache/0

# IOPS и задержки диска
iostat -x -d 1 5

# Использование Page Cache
echo 3 > /proc/sys/vm/drop_caches && cachestat 5
```

## Troubleshooting

### Высокий % MISS после рестарта

**Симптом:** После `systemctl restart nginx` Hit Ratio падает до 0%, нагрузка на диск резко возрастает.

**Причина:** Cache Loader сканирует директорию кэша и загружает ключи в `keys_zone`. Пока индекс не готов, все запросы идут в MISS.

**Диагностика:**
```bash
# Проверка активности дочерних процессов loader/manager
ps aux | grep -E "nginx: cache|nginx: loader"
# → nginx    1024  0.5  1.2  123456  23456 ?  Ssl  10:00   0:00 nginx: cache manager process
# → nginx    1025  2.1  3.4  234567  56789 ?  Sl   10:00   0:02 nginx: cache loader process

# Мониторинг IOPS во время старта
iostat -x 1
```

**Решение:**
- Angie 1.9+: добавьте `file=/var/lib/angie/my_cache.zone` в `proxy_cache_path`.
- Nginx OSS: предварительный прогрев кэша (cache warm-up) или увеличение `loader_threshold`.

### Резкие всплески MISS для одного ресурса (Cache Stampede)

**Симптом:** Один и тот же ресурс одновременно генерирует сотни MISS.

**Причина:** TTL истек одновременно для множества копий в промежуточных кэшах.

**Диагностика:**
```bash
# Логи с одинаковым временем запроса к одному URI
jq -r 'select(.cache_status=="MISS" and .request=="/api/data") | .time' /var/log/nginx/cache_access.json | sort | uniq -c | sort -rn | head -5
```

**Решение:**
```nginx
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
```

### Отсутствие кэша для авторизованных сессий

**Симптом:** Все запросы с `Authorization` или `Cookie` имеют статус BYPASS.

**Причина:** По умолчанию Nginx не кэширует ответы с заголовком `Set-Cookie`.

**Диагностика:**
```bash
curl -I -H "Cookie: session=abc" http://localhost/api/data
# Проверьте наличие Set-Cookie в ответе бэкенда
```

**Решение:** Для публичных API можно игнорировать `Set-Cookie`, но категорически запрещено делать это в зонах с авторизацией.

```nginx
proxy_ignore_headers Set-Cookie;  # только для публичных эндпоинтов
```

### Кэш не обновляется (вечные HIT с устаревшим контентом)

**Симптом:** После деплоя новый контент не появляется, хотя бэкенд отдает свежие данные.

**Причина:** Слишком длинный `inactive` или достигнут `max_size`, старый файл защищен от удаления.

**Диагностика:**
```bash
# Проверка размера кэша
du -sh /var/cache/nginx/proxy_cache

# Проверка TTL файла
find /var/cache/nginx/proxy_cache -type f -mtime +1 | head
```

**Решение:** Настройте `proxy_cache_valid` и `inactive` соответственно SLO обновления контента.

### Ошибка 502 при истечении TTL

**Симптом:** При обновлении кэша клиенты получают 502 Bad Gateway.

**Причина:** Бэкенд перезагружается или слишком долго отвечает при обновлении кэша. Nginx OSS без `use_stale` отдает 502.

**Диагностика:**
```bash
# Временные метки в логах
jq -r 'select(.status=="502") | .time' /var/log/nginx/cache_access.json | tail
```

**Решение:**
```nginx
proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
```

### Отравление кэша (Cache Poisoning)

**Симптом:** Разные клиенты получают разный контент из одного и того же кэшированного URI.

**Причина:** Неполный `proxy_cache_key` — не учтены заголовки, влияющие на ответ (язык, протокол, Device).

**Диагностика:**
```bash
# Проверка ключа
grep proxy_cache_key /etc/nginx/conf.d/*.conf
```

**Решение:** Всегда включайте в ключ все переменные, влияющие на ответ.

```nginx
proxy_cache_key "$scheme$request_method$host$request_uri";
```

### Подозрение на Cache Poisoning через Vary

**Симптом:** Клиент с `Accept-Encoding: gzip` получает несжатый контент.

**Причина:** Бэкенд не шлет `Vary: Accept-Encoding`, и Nginx создает только одну копию в кэше.

**Решение:** Убедитесь, что бэкенд корректно формирует заголовок `Vary`.

## Best Practices

1.  **Разделение кэшей:** Используйте отдельные зоны `keys_zone` для разных типов контента (API, статика, изображения). Это упрощает управление TTL и очистку.
2.  **Ключ кэша:** Всегда включайте в `proxy_cache_key` параметры, влияющие на ответ (язык, `Accept-Encoding`, протокол). Пример: `proxy_cache_key "$scheme$request_method$host$request_uri";`
3.  **Заголовки Vary:** Если бэкенд отдает разный контент по заголовку `Accept-Encoding` (gzip/brotli), убедитесь, что он шлет `Vary: Accept-Encoding`.
4.  **Защита от Stampede:** Для популярных ресурсов всегда используйте `proxy_cache_lock on;` с `proxy_cache_lock_timeout 5s;`.
5.  **Безопасность:** Категорически запрещено использовать `proxy_ignore_headers Set-Cookie` в зонах с авторизацией (личные кабинеты), так как это приведет к кэшированию персональных данных.
6.  **IO Performance:** На высоконагруженных системах используйте `aio threads` вместе с кэшем, чтобы операции чтения с диска не блокировали воркеры Nginx. Подробнее см. в [Оптимизации производительности Nginx](../nginx_performance_tuning.md).
7.  **Персистентность:** В Angie 1.9+ всегда используйте `file=` в `proxy_cache_path` для ускорения холодного старта.
8.  **Безопасность интерфейсов:** Ограничьте доступ к `stub_status`, API метрик и эндпоинтам Prometheus директивой `allow` для доверенных IP и `deny all` для всего остального.
9.  **Мониторинг:** Включите `add_header X-Cache-Status $upstream_cache_status;` или JSON-логирование для аудита эффективности кэширования.
10. **Алертинг:** Настройте оповещения при падении Hit Ratio ниже порога и при всплесках Cache Loader IOPS.

## Дополнительная информация

### Безопасность и целостность

**Отравление кэша (Cache Poisoning):** Риск отдачи неверного контента из-за недостаточно точного ключа кэша.
- Всегда включайте в `proxy_cache_key` параметры, влияющие на ответ (язык, формат сжатия, тип устройства).
- Используйте заголовок `Vary`, чтобы уведомить промежуточные кэши о факторах вариативности.

### Мониторинг эффективности

Эффективность кэширования оценивается через **Cache Hit Ratio**.
- Переменная `$upstream_cache_status` (HIT, MISS, EXPIRED, BYPASS, STALE, UPDATING, REVALIDATED).
- **Status Zones (Angie):** Позволяют собирать статистику по кэш-зонам в реальном времени через API.
- **OpenTelemetry:** Передача статуса кэша как атрибута span позволяет коррелировать кэш-промахи с трейсами запросов.
- **Page Cache (bcc):** Подтверждает, что попадания в кэш действительно обслуживаются из RAM.

### Связанные темы

*   [Обзор кэширования в Nginx/Angie](./overview.md) — базовые концепции и определения.
*   [Серверное кэширование (Proxy Cache)](./proxy_caching.md) — детальная настройка TTL и параметров зон.
*   [Тюнинг производительности Nginx](../nginx_performance_tuning.md) — оптимизация дискового ввода-вывода (`aio threads`).
