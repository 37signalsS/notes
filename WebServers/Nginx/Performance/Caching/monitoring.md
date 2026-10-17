# Мониторинг кэширования в Nginx и Angie

**Актуально для:** Nginx 1.26.x - 1.30.x, Angie 1.9+ - 1.11+

## Определения

**Коэффициент попаданий в кэш (Cache Hit Ratio)** — процентное соотношение запросов, обслуженных из локального хранилища без обращения к бэкенду, к общему числу поступивших кэшируемых запросов. Базовая формула вычисления:
$$\text{Hit Ratio} = \frac{\text{HIT} + \text{REVALIDATED}}{\text{HIT} + \text{MISS} + \text{EXPIRED} + \text{STALE} + \text{UPDATING} + \text{REVALIDATED} + \text{BYPASS}} \times 100\%$$
Целевой уровень в SRE-практике зависит от типа контента: $\ge 95\%$ для статических медиаресурсов и $\ge 60\text{--}80\%$ для динамических микросервисных API. Ответы со статусом `REVALIDATED` включаются в число успешных попаданий, так как тело ответа отдается из локального хранилища после подтверждения бэкендом актуальности заголовком `304 Not Modified`, что экономит пропускную способность канала.

**`$upstream_cache_status`** — встроенная контекстная переменная Nginx и Angie, отражающая статус взаимодействия модуля кэширования с кэш-зоной и вышестоящим сервером:

| Статус | Описание поведения | Состояние подсистемы ввода-вывода и Page Cache ОС |
| :--- | :--- | :--- |
| **HIT** | Ответ найден в кэше, актуален по TTL и отдан клиенту напрямую. | Чтение из Page Cache RAM (горячий кэш) либо чтение блока с диска. |
| **MISS** | Запрашиваемый ключ отсутствует в `keys_zone`; запрос передан бэкенду. | Запись нового файла во временную/целевую директорию кэша. |
| **EXPIRED** | Объект найден, но его TTL истек; запрошены свежие данные с апстрима. | Перезапись существующего файла кэша на диске и обновление индекса. |
| **STALE** | Отдан устаревший объект при недоступности апстрима (`proxy_cache_use_stale`). | Чтение из Page Cache RAM или диска без блокировки запроса. |
| **UPDATING** | Отдан устаревший объект, пока фоновый запрос обновляет кэш на бэкенде. | Параллельное чтение старого файла и запись нового потока. |
| **BYPASS** | Кэш намеренно обойден по условию директивы `proxy_cache_bypass`. | Прямое проксирование на бэкенд без обращения к `keys_zone`. |
| **REVALIDATED** | Бэкенд подтвердил валидность истекшего кэша кодом `304 Not Modified`. | Обновление служебных метаданных TTL в оперативной памяти `keys_zone`. |

**Page Cache (системный кэш страниц)** — структура ядра Linux в оперативной памяти, прозрачно кэширующая страницы файлов с блочных устройств. Nginx и Angie хранят в разделяемой памяти только метаданные и хэш-ключи, тогда как тела ответов размещаются в файловой системе. При высокой эффективности Page Cache дисковое чтение обслуживается на скорости шины RAM без физических операций ввода-вывода (Zero-Disk Read).

**Cache Loader** — системный дочерний процесс Nginx/Angie, запускаемый при старте сервиса для последовательного сканирования дерева каталогов кэша и первичного наполнения красно-черного дерева метаданных в `keys_zone`. На хранилищах с миллионами файлов создает пиковую утилизацию дисковых операций (IOPS).

**Cache Manager** — периодический фоновый процесс веб-сервера, контролирующий соответствие фактического размера кэша директиве `max_size` и удаляющий невостребованные объекты по алгоритму LRU (Least Recently Used), а также файлы, не запрашивавшиеся дольше интервала `inactive`.

**Status Zone (Angie)** — область разделяемой памяти веб-сервера Angie, аккумулирующая runtime-метрики по виртуальным серверам, апстримам и зонам кэширования для выгрузки через встроенный JSON API и нативный Prometheus-эндпоинт без сторонних модулей.

**`nginx-module-vts` (Virtual Host Traffic Status)** — сторонний динамический C-модуль для Nginx OSS, организующий сбор расширенной телеметрии по кэш-зонам (`cache_zones`), кодам ответов и гистограммам задержек с отдачей в формате Prometheus.

**`ngx_http_stub_status_module`** — стандартный минималистичный модуль Nginx OSS, предоставляющий глобальные счетчики соединений (active, reading, writing, waiting) и запросов. Модуль не содержит информации о дисковом кэше и статусах `$upstream_cache_status`.

**`ngx_otel_module`** — официальный модуль распределенной трассировки OpenTelemetry для Nginx OSS (начиная с 1.25.3) и Angie, передающий контекст трассировки W3C и атрибуты спанов (включая статус кэша) по протоколу OTLP/gRPC в локальный коллектор.

---

## Основные концепции

### Двухуровневая архитектура мониторинга

Надежный мониторинг кэширования веб-сервера строится на одновременном контроле двух независимых уровней:

```
+-----------------------------------------------------------------------------------+
| Уровень приложения (L7 Application Layer)                                         |
|  - Переменная $upstream_cache_status (HIT, MISS, EXPIRED, STALE, BYPASS)          |
|  - HTTP-заголовки: X-Cache-Status, Age, Cache-Control, Vary                       |
|  - Задержки: $request_time vs $upstream_response_time                             |
|  - Нативные счетчики Angie (Status API / Prometheus) и Nginx (VTS)                |
+────────────────────────────────────────┬──────────────────────────────────────────+
                                         │ (обращение к файлам кэша)
                                         ▼
+-----------------------------------------------------------------------------------+
| Системный уровень (OS Kernel, VFS & Storage Subsystem)                            |
|  - Linux Page Cache (попадания и промахи через eBPF / bcc cachestat)              |
|  - VFS слябы ядра: dentry cache, inode cache (slabtop)                            |
|  - Блочные устройства: IOPS (r/s, w/s), задержки await, утилизация %util (iostat) |
|  - Файловые дескрипторы и емкость: использование диска и inodes (df -h, df -i)    |
+-----------------------------------------------------------------------------------+
```

1. **Прикладной уровень (L7):** Анализ статусов отдачи, распределения HTTP-кодов, выявление аномалий инвалидации контента, отслеживание времени ответа бэкендов при промахах.
2. **Системный уровень (Ядро Linux и СХД):** Диагностика эффективности Page Cache ядра, предотвращение насыщения дисковой очереди ввода-вывода, контроль деградации файловой системы из-за фрагментации метаданных (dentry/inodes).

### Механика хранения и взаимодействие с ядром Linux

Nginx и Angie принципиально разделяют хранение метаданных и полезной нагрузки:
- **Оперативная память (`keys_zone`):** Выделенный блок Shared Memory (shm), управляемый slab-аллокатором. Содержит 64-битные хэши ключей, указатели на файлы, счетчики обращений и временные метки. Накладные расходы: 1 МБ памяти вмещает около 8 000 ключей кэша (10 МБ $\approx$ 80 000 объектов).
- **Дисковая подсистема (`proxy_cache_path`):** Тела ответов сохраняются в виде бинарных файлов со служебным заголовком Nginx. Иерархия каталогов (`levels=1:2`) предотвращает деградацию производительности файловых систем (ext4, XFS) при наличии сотен тысяч файлов в одном каталоге.
- **Роль системного Page Cache:** При запросе со статусом `HIT` Nginx выполняет системные вызовы открытия и чтения файла. Если страницы файла уже находятся в Page Cache ядра, данные передаются в сетевой сокет через `sendfile()` или epoll без обращения к физическому диску. Если Page Cache вытеснен другими процессами хоста, каждый `HIT` вызывает реальное чтение с накопителя, приводя к деградации задержек P99.

### Влияние процессов Cache Loader и Cache Manager

- **Cache Loader (Холодный старт):** При перезапуске сервиса процесс обходит дерево директорий на диске, выполняя системные вызовы `stat()` и `read()` для восстановления структуры `keys_zone`. На хранилищах с 500 000+ файлов это вызывает всплеск дисковой очереди и деградацию производительности.
  - *Параметры регулирования в Nginx:* `loader_files` (максимум файлов за итерацию, по умолчанию 100), `loader_sleep` (пауза между итерациями, по умолчанию 50ms), `loader_threshold` (длительность итерации, по умолчанию 200ms).
  - *Архитектурное решение в Angie 1.9+:* Параметр `file=/var/lib/angie/cache.zone` сохраняет образ памяти индекса на диск при остановке и восстанавливает его за доли секунды при старте, полностью устраняя фазу Cache Loader.
- **Cache Manager (Очистка и LRU):** Процесс просыпается периодически (по умолчанию каждые 10 секунд при наличии активности) и при превышении порога `max_size` удаляет наименее востребованные файлы. Мониторинг I/O во время работы Cache Manager позволяет вовремя выявить нехватку дискового пространства или заниженный размер кэш-зоны.

---

## Практические сценарии

### Сценарий 1: Структурированное JSON-логирование для аудита кэша

В production-средах анализ кэширования базируется на агрегации логов в системах сбора телеметрии (Vector, Fluentbit, Loki, ClickHouse, ELK). Конфигурация включает подробные тайминги и статус кэша.

```nginx
# Определение формата структурированного лога в контексте http
log_format cache_json escape=json '{'
    '"timestamp": "$time_iso8601", '
    '"client_ip": "$remote_addr", '
    '"vhost": "$host", '
    '"method": "$request_method", '
    '"uri": "$uri", '
    '"query": "$args", '
    '"status": $status, '
    '"cache_status": "$upstream_cache_status", '
    '"request_time": $request_time, '
    '"upstream_time": "$upstream_response_time", '
    '"upstream_connect_time": "$upstream_connect_time", '
    '"upstream_header_time": "$upstream_header_time", '
    '"bytes_sent": $bytes_sent, '
    '"pipe": "$pipe"'
'}';

server {
    listen 127.0.0.1:80;
    server_name api.local;

    access_log /var/log/nginx/cache_access.json cache_json buffer=64k flush=5s;

    location /api/ {
        proxy_pass http://backend_cluster;
        proxy_cache api_cache;
        proxy_cache_valid 200 302 10m;
        proxy_cache_valid 404 1m;
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

**Анализ логов через CLI-инструменты:**
```bash
# 1. Сводное распределение запросов по статусам кэша
jq -r '.cache_status' /var/log/nginx/cache_access.json | sort | uniq -c | sort -rn
# → 84210 HIT
# →  4320 MISS
# →   612 EXPIRED
# →   145 REVALIDATED
# →    89 UPDATING
# →    34 BYPASS

# 2. Вычисление точного коэффициента Hit Ratio через jq и awk
jq -r '.cache_status' /var/log/nginx/cache_access.json | awk '
{
    total++;
    if ($1 == "HIT" || $1 == "REVALIDATED") hits++;
}
END {
    if (total > 0)
        printf "Total: %d | Hits: %d | Hit Ratio: %.2f%%\n", total, hits, (hits/total)*100;
}'
# → Total: 89410 | Hits: 84355 | Hit Ratio: 94.35%

# 3. Топ-10 URI с наибольшим количеством промахов (MISS) для оптимизации TTL
jq -r 'select(.cache_status=="MISS") | .uri' /var/log/nginx/cache_access.json | sort | uniq -c | sort -rn | head -n 10
# →   1240 /api/v1/products/live-stock
# →    820 /api/v1/pricing/exchange-rates
# →    412 /api/v1/auth/token-verify
```

### Сценарий 2: Метрики в Prometheus через нативный модуль Angie

Веб-сервер Angie поддерживает экспорт телеметрии по кэш-зонам через встроенный модуль `prometheus` и JSON Status API.

```nginx
http {
    # Подключение кэш-зоны с персистентным индексом
    proxy_cache_path /var/cache/angie/proxy_cache
                      levels=1:2
                      keys_zone=main_cache:32m
                      inactive=12h
                      max_size=20g
                      file=/var/lib/angie/main_cache.zone;

    # Служебный виртуальный хост управления и мониторинга
    server {
        listen 127.0.0.1:9113;
        server_name localhost;

        access_log off;

        # Нативный эндпоинт метрик Prometheus
        location = /metrics {
            prometheus all;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }

        # REST API статуса кэша и соединений
        location /status/ {
            api /status/;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }
    }
}
```

**Валидация экспорта и сбор метрик в CLI:**
```bash
# 1. Проверка синтаксиса и перезагрузка конфигурации
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

angie -s reload
# → # сигнал отправлен без разрыва пользовательских сессий

# 2. Запрос нативных метрик кэша Angie в формате Prometheus
curl -sf http://127.0.0.1:9113/metrics | grep -E "^angie_http_cache"
# → angie_http_cache_size_bytes{cache="main_cache"} 345288704
# → angie_http_cache_max_size_bytes{cache="main_cache"} 21474836480
# → angie_http_cache_responses_total{cache="main_cache",status="hit"} 184500
# → angie_http_cache_responses_total{cache="main_cache",status="miss"} 12100
# → angie_http_cache_responses_total{cache="main_cache",status="stale"} 45
# → angie_http_cache_responses_total{cache="main_cache",status="updating"} 12
# → angie_http_cache_responses_total{cache="main_cache",status="revalidated"} 890
# → angie_http_cache_responses_total{cache="main_cache",status="expired"} 1400
# → angie_http_cache_responses_total{cache="main_cache",status="bypass"} 320

# 3. Получение структурированного состояния через JSON API
curl -sf http://127.0.0.1:9113/status/http/caches/main_cache/ | jq .
# → {
# →   "size": 345288704,
# →   "max_size": 21474836480,
# →   "cold": false,
# →   "hit": { "responses": 184500, "bytes": 4829104800 },
# →   "miss": { "responses": 12100, "bytes": 312040100 },
# →   "stale": { "responses": 45, "bytes": 1152000 },
# →   "updating": { "responses": 12, "bytes": 305000 },
# →   "revalidated": { "responses": 890, "bytes": 22400000 },
# →   "expired": { "responses": 1400, "bytes": 36800000 },
# →   "bypass": { "responses": 320, "bytes": 8450000 }
# → }
```

**PromQL-запросы для дашбордов Grafana и алертинга (Angie):**
```promql
# Текущий Cache Hit Ratio за последние 5 минут
(
  sum(rate(angie_http_cache_responses_total{status=~"hit|revalidated"}[5m]))
  /
  sum(rate(angie_http_cache_responses_total[5m]))
) * 100

# Заполненность дискового пространства кэша в процентах
(
  angie_http_cache_size_bytes
  /
  angie_http_cache_max_size_bytes
) * 100
```

### Сценарий 3: Экспорт метрик Nginx OSS через `nginx-module-vts`

Стандартный `stub_status` в Nginx OSS не выгружает телеметрию кэша. Для получения метрик в формате Prometheus подключается модуль `vts`.

```nginx
# Подключение динамического модуля в начале файла /etc/nginx/nginx.conf
load_module modules/ngx_http_vhost_traffic_status_module.so;

http {
    # Выделение разделяемой памяти под статистику хостов и кэшей
    vhost_traffic_status_zone;

    proxy_cache_path /var/cache/nginx/api_cache
                      levels=1:2
                      keys_zone=api_cache:20m
                      inactive=24h
                      max_size=10g;

    server {
        listen 127.0.0.1:8080;
        server_name localhost;

        location /status {
            vhost_traffic_status_display;
            vhost_traffic_status_display_format prometheus;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }
    }
}
```

**Проверка работы модуля через CLI:**
```bash
# Проверка эндпоинта метрик
curl -sf http://127.0.0.1:8080/status/format/prometheus | grep -E "nginx_vts_cache"
# → nginx_vts_cache_max_bytes{zone="api_cache"} 10737418240
# → nginx_vts_cache_used_bytes{zone="api_cache"} 2147483648
# → nginx_vts_cache_in_bytes{zone="api_cache"} 4294967296
# → nginx_vts_cache_out_bytes{zone="api_cache"} 38654705664
# → nginx_vts_cache_requests_total{zone="api_cache",status="hit"} 452100
# → nginx_vts_cache_requests_total{zone="api_cache",status="miss"} 21400
# → nginx_vts_cache_requests_total{zone="api_cache",status="bypass"} 1540
# → nginx_vts_cache_requests_total{zone="api_cache",status="expired"} 4120
# → nginx_vts_cache_requests_total{zone="api_cache",status="stale"} 310
# → nginx_vts_cache_requests_total{zone="api_cache",status="updating"} 95
# → nginx_vts_cache_requests_total{zone="api_cache",status="revalidated"} 8420
```

**PromQL-формула для расчета Hit Ratio в VTS:**
```promql
(
  sum(rate(nginx_vts_cache_requests_total{status=~"hit|revalidated"}[5m]))
  /
  sum(rate(nginx_vts_cache_requests_total[5m]))
) * 100
```

### Сценарий 4: Трассировка OpenTelemetry (`ngx_otel_module`)

Модуль `ngx_otel_module` передает метаданные каждого HTTP-запроса в локальный OpenTelemetry Collector по OTLP/gRPC. Передача статуса кэша позволяет находить промахи непосредственно в распределенных спанах Jaeger/Tempo.

```nginx
# Подключение модуля (Debian/Ubuntu пакет nginx-module-otel)
load_module modules/ngx_otel_module.so;

http {
    # Настройка экспортера OTLP/gRPC
    otel_exporter {
        endpoint 127.0.0.1:4317;
        interval 5s;       # Максимальный интервал между экспортами батчей
        batch_size 512;    # Максимальное количество спанов в одном батче
        batch_count 4;     # Максимальное число буферизуемых батчей
    }

    otel_service_name nginx-ingress-edge;
    otel_trace on;

    server {
        listen 127.0.0.1:80;
        server_name api.local;

        location /data/ {
            otel_span_name "http_cache_proxy";
            # Передача статуса подсистемы кэширования как атрибута спана
            otel_span_attr "http.cache.status" $upstream_cache_status;
            otel_span_attr "http.response.status_code" $status;

            proxy_pass http://backend_upstream;
            proxy_cache my_zone;
            proxy_cache_valid 200 5m;
        }
    }
}
```

**Проверка синтаксиса и работы модуля:**
```bash
# Проверка наличия символов модуля в установленном Nginx
nginx -V 2>&1 | grep -o "ngx_otel_module"
# → ngx_otel_module

# Проверка корректности директив
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### Сценарий 5: Мониторинг Page Cache и дискового ввода-вывода (eBPF/bcc)

Инструменты bcc и eBPF позволяют сопоставить прикладные метрики `$upstream_cache_status: HIT` с физическим поведением подсистемы памяти ядра Linux.

```bash
# 1. Анализ попаданий в Page Cache ядра в реальном времени с интервалом 5 секунд
cachestat 5
# →    TOTAL_READ    PAGE_CACHE_HITS    PAGE_CACHE_MISSES    DIRTIES   BUFFERS_MB    CACHED_MB
# →        154201             153980                  221        452          128        14250
# →        168940             168710                  230        510          128        14258

# 2. Выявление процессов с наибольшим процентом промахов системного кэша страниц
cachetop 1
# → PID      UID      CMD              HITS     MISSES   DIRTIES  READ_HIT%  WRITE_HIT%
# → 14205    nginx    nginx: worker   12450         12        42      99.9%       88.2%
# → 14206    nginx    nginx: worker   11980          8        39      99.9%       89.1%
# → 14210    nginx    nginx: cache m     15        142       180       9.5%       20.0%

# 3. Анализ задержек дисковой подсистемы (iostat) для устройства, где размещен кэш (/dev/nvme0n1)
iostat -xz 1 5
# → Device            r/s     w/s     rkB/s    wkB/s  rrqm/s  wrqm/s  %rrqm  %wrqm  r_await  w_await  aqu-sz  %util
# → nvme0n1          12.4   345.1     496.0  14520.0    0.00   24.10   0.00   6.53     0.21     0.45    0.15   8.20

# 4. Проверка слябов дескрипторов файлов ядра (dentry и inode кэш)
slabtop -o | grep -E 'dentry|inode'
# → 2450120 2445100  99%    0.19K 122506       20K    490024K dentry
# → 1845120 1841000  99%    1.05K 115320       16K   1845120K ext4_inode_cache
```

---

## Операции и команды

Сводная таблица процедур аудита, валидации и мониторинга кэша:

| Задача / Операция | Команда | Назначение и ожидаемый результат |
| :--- | :--- | :--- |
| **Синтаксис (Nginx)** | `nginx -t` | Проверка синтаксиса директив и доступности путей. Вывод: `syntax is ok`. |
| **Синтаксис (Angie)** | `angie -t` | Проверка конфигурации Angie. Вывод: `syntax is ok`. |
| **Бесшовный reload** | `systemctl reload nginx` | Применение новых правил без разрыва активных соединений. |
| **Аудит процессов кэша** | `ps -eo pid,user,stat,command \| grep -E "nginx: cache\|angie: cache"` | Контроль активности процессов `cache manager` и `cache loader`. |
| **Статус stub_status** | `curl -sf http://127.0.0.1:8080/nginx_status` | Проверка общего числа активных соединений и обработанных запросов. |
| **Статистика Angie (API)**| `curl -sf http://127.0.0.1:9113/status/http/caches/` | Получение JSON со счетчиками байт и ответов по зонам кэша. |
| **Метрики Angie (Prom)** | `curl -sf http://127.0.0.1:9113/metrics \| grep angie_http_cache` | Выгрузка нативных метрик кэша в формате OpenMetrics. |
| **Метрики Nginx VTS** | `curl -sf http://127.0.0.1:8080/status/format/prometheus \| grep nginx_vts_cache` | Выгрузка метрик дискового кэша модуля VTS в формате Prometheus. |
| **Занятое место и иноды** | `df -h /var/cache/nginx && df -i /var/cache/nginx` | Проверка свободного места и дескрипторов (inodes) файловой системы. |
| **Размер директории кэша**| `du -sh /var/cache/nginx/api_cache/` | Фактический объем файлов кэша на накопителе. |
| **Мониторинг Page Cache** | `cachestat 2` | Динамический замер соотношения hit/miss системного кэша страниц ядра. |
| **Задержки ввода-вывода** | `iostat -xz 1 5` | Оценка утилизации накопителя (`%util`) и задержек ожидания (`r_await`). |

### Оперативные однострочники для дежурного инженера

```bash
# Расчет задержки P95 и среднего времени ответа для MISS относительно HIT из JSON-лога
jq -s '
  def p95(arr): arr | sort | .[(length * 0.95 | floor)];
  {
    hit_avg_time:  ([.[] | select(.cache_status=="HIT") | .request_time] | add / length),
    miss_avg_time: ([.[] | select(.cache_status=="MISS") | .request_time] | add / length),
    miss_p95_time: ([.[] | select(.cache_status=="MISS") | .request_time] | p95(.))
  }' /var/log/nginx/cache_access.json
# → {
# →   "hit_avg_time": 0.0012,
# →   "miss_avg_time": 0.1450,
# →   "miss_p95_time": 0.4200
# → }

# Поиск запросов, которые принудительно обошли кэш со статусом BYPASS
jq -r 'select(.cache_status=="BYPASS") | "\(.timestamp) \(.client_ip) \(.uri)"' /var/log/nginx/cache_access.json | tail -n 5
# → 2026-10-16T12:01:10+03:00 10.12.4.55 /api/v1/user/cart
# → 2026-10-16T12:01:12+03:00 10.12.4.98 /api/v1/user/profile
```

---

## Troubleshooting

### Всплеск задержек и падение Hit Ratio до 0% после перезапуска

**Симптом:** После выполнения `systemctl restart nginx` утилизация диска вырастает до 100%, процент попадания в кэш падает до нуля, время ответа пользователям деградирует.
**Причина:** Процесс Cache Loader инициирует холодное сканирование директорий кэша. Пока дескрипторы не внесены в разделяемую память `keys_zone`, входящие запросы не находят совпадений по хэшу и уходят на бэкенд со статусом `MISS`.
**Диагностика:**
```bash
# Проверка нагрузки процесса loader
ps -eo pid,pcpu,pmem,command | grep "cache loader"
# → 18451  45.2  3.1 [nginx: cache loader process]

# Проверка очереди диска
iostat -x 1 3 | grep -E "Device|nvme0n1"
# → nvme0n1  1240.50  14.20  45200.0   120.0  ...  12.40  0.80  98.5%
```
**Решение:**
1. В **Angie 1.9+** добавить параметр `file=` в `proxy_cache_path` для мгновенной загрузки индекса:
   ```nginx
   proxy_cache_path /var/cache/angie/proxy_cache levels=1:2 keys_zone=my_cache:32m
                     inactive=24h max_size=20g file=/var/lib/angie/my_cache.zone;
   ```
2. В **Nginx OSS** ограничить скорость сканирования, чтобы предотвратить насыщение дисковой подсистемы:
   ```nginx
   proxy_cache_path /var/cache/nginx/proxy_cache levels=1:2 keys_zone=my_cache:32m
                     loader_files=200 loader_sleep=100 loader_threshold=50;
   ```

### Лавинообразная перегрузка бэкенда при истечении TTL (Cache Stampede)

**Симптом:** При истечении TTL высоконагруженного эндпоинта (например, `/api/v1/catalog`) тысячи параллельных клиентских запросов одновременно получают статус `MISS`/`EXPIRED` и транслируются на бэкенд, вызывая отказ БД или HTTP 504 Gateway Timeout.
**Диагностика:**
```bash
# Анализ лога по конкретному URI с фильтрацией по статусу EXPIRED
jq -r 'select(.cache_status=="EXPIRED" and .uri=="/api/v1/catalog") | .timestamp' /var/log/nginx/cache_access.json | uniq -c
# → 1450 2026-10-16T12:00:00+03:00
```
**Решение:** Настроить мьютекс первого запроса (`proxy_cache_lock`) и отдачу устаревшего контента во время фонового обновления:
```nginx
location /api/v1/catalog {
    proxy_pass http://catalog_backend;
    proxy_cache api_cache;
    proxy_cache_valid 200 5m;

    # Отправлять на бэкенд только один запрос на обновление; остальные ожидают в очереди
    proxy_cache_lock on;
    proxy_cache_lock_timeout 3s;
    proxy_cache_lock_age 5s;

    # Отдавать старый кэш во время обновления или при ошибках бэкенда
    proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
    proxy_cache_background_update on;
}
```

### Повсеместный статус BYPASS для запросов с Cookie или Authorization

**Симптом:** Клиентские запросы не кэшируются, метрики показывают преобладание статусов `BYPASS` или `MISS`, бэкенд перегружен сессионными запросами.
**Причина:** Некорректно составленная директива `proxy_cache_bypass` или присутствие заголовка `Set-Cookie` в ответах бэкенда, из-за которого Nginx по умолчанию блокирует сохранение объекта.
**Диагностика:**
```bash
# Проверка заголовков ответа бэкенда
curl -sI -H "Host: api.local" http://127.0.0.1:8080/api/data | grep -iE "set-cookie|cache-control|x-cache"
# → Set-Cookie: session_id=abc12345; Path=/; HttpOnly
# → X-Cache-Status: MISS
```
**Решение:**
1. Если бэкенд отдает публичные неизменяемые данные, но ошибочно шлет `Set-Cookie`, игнорировать заголовок для кэш-подсистемы:
   ```nginx
   proxy_ignore_headers Set-Cookie;
   proxy_hide_header Set-Cookie;
   ```
2. Разграничить условия обхода кэша через директиву `map`:
   ```nginx
   map $http_cookie $bypass_cache {
       default 0;
       ~*auth_token 1;  # Обходить кэш только для авторизованных сессий
   }

   server {
       location /api/ {
           proxy_cache_bypass $bypass_cache;
           proxy_no_cache $bypass_cache;
       }
   }
   ```

### Ошибки «could not allocate new entry in keys_zone»

**Симптом:** В `/var/log/nginx/error.log` фиксируются ошибки `[alert] could not allocate new cache entry in keys_zone "api_cache"`. Новые ответы перестают кэшироваться.
**Причина:** Недостаточный объем разделяемой памяти (`keys_zone`), выделенный под хэш-индекс, при огромном числе уникальных URL или бесконтрольном росте кардинальности ключей.
**Диагностика:**
```bash
# Подсчет количества уникальных файлов в хранилище кэша
find /var/cache/nginx/api_cache/ -type f | wc -l
# → 324100
# 324 100 ключей требуют не менее 324100 / 8000 ≈ 41 МБ разделяемой памяти
```
**Решение:** Увеличить размер `keys_zone` в директиве `proxy_cache_path`:
```nginx
# Было: keys_zone=api_cache:10m (до 80 000 ключей)
# Стало: keys_zone=api_cache:64m (до 512 000 ключей)
proxy_cache_path /var/cache/nginx/api_cache levels=1:2 keys_zone=api_cache:64m max_size=20g;
```

### Зависание воркеров при чтении с диска (Disk I/O Event Loop Stall)

**Симптом:** Задержка обработки запросов резко возрастает при чтении «холодных» файлов со статусом `HIT`, вывод `top` показывает высокий процент `%wa` (iowait), воркеры Nginx временно прекращают обрабатывать сетевые события.
**Причина:** Синхронные системные вызовы чтения больших файлов из дискового кэша блокируют неблокирующий цикл событий (event loop) воркера.
**Диагностика:**
```bash
# Проверка потоков воркера и iowait
pidstat -p $(pgrep -d',' -f "nginx: worker") -d 1
```
**Решение:** Включить асинхронный ввод-вывод с пулом потоков (`aio threads`) в [Оптимизации производительности Nginx](../nginx_performance_tuning.md):
```nginx
# В контексте main или http
thread_pool cache_pool threads=32 max_queue=65536;

http {
    proxy_cache_path /var/cache/nginx/api_cache levels=1:2 keys_zone=api_cache:64m max_size=30g;

    server {
        location /media/ {
            proxy_pass http://media_upstream;
            proxy_cache api_cache;
            aio threads=cache_pool;
            directio 8m;
        }
    }
}
```

### Исчерпание индексных дескрипторов (Inode Starvation)

**Симптом:** При записи в кэш Nginx возвращает ошибку `No space left on device`, хотя команда `df -h` показывает достаточное количество гигабайт свободного места.
**Причина:** Дисковый кэш содержит миллионы мелких объектов, что привело к 100% исчерпанию доступных индексных дескрипторов (`inodes`) файловой системы ext4.
**Диагностика:**
```bash
# Проверка утилизации inode
df -i /var/cache/nginx
# → Filesystem      Inodes   IUsed   IFree IUse% Mounted on
# → /dev/nvme0n1p3 2621440 2621440       0  100% /var/cache/nginx
```
**Решение:**
1. Принудительно очистить устаревший кэш или уменьшить параметр `inactive`.
2. В долгосрочной перспективе переформатировать раздел под файловую систему XFS (с динамическим выделением инодов) либо создать ext4 с увеличенным количеством дескрипторов (`mkfs.ext4 -N 10000000 ...`).

---

## Best Practices

1. **Архитектурная изоляция хранилища:** Размещайте директорию `/var/cache/nginx` или `/var/cache/angie` на отдельном выделенном блочном устройстве (быстрый NVMe/SSD) с монтированием с опциями `noatime,nodiratime`. Это защищает корневой раздел ОС от переполнения и исключает лишние операции записи метаданных при чтении кэша.
2. **Отключение промежуточных временных путей (`use_temp_path=off`):** Всегда указывайте `use_temp_path=off` в `proxy_cache_path`. Это гарантирует, что Nginx сохраняет временные файлы непосредственно в целевой файловой системе кэша, исключая межсегментное копирование между `/var/lib/nginx/proxy` и директорией кэша.
3. **Расчет памяти `keys_zone`:** Рассчитывайте объем разделяемой памяти исходя из формулы: $1\text{ МБ shm} \approx 8\,000\text{ объектов}$. Для кэша на 1 000 000 файлов требуется зона размером не менее $128\text{ МБ}$.
4. **Контроль вариативности (Cache Poisoning):** Включайте в `proxy_cache_key` все переменные, влияющие на различие контента для пользователей:
   ```nginx
   proxy_cache_key "$scheme$request_method$host$request_uri";
   ```
   Если бэкенд сжимает контент (gzip/brotli), убедитесь, что в ответе бэкенда присутствует заголовок `Vary: Accept-Encoding`, либо добавьте `$http_accept_encoding` в ключ.
5. **Защита эндпоинтов телеметрии:** Служебные эндпоинты метрик (`/status`, `/metrics`) должны быть защищены директивами `allow` для доверенных IP-адресов серверов мониторинга и `deny all` для внешнего сетевого периметра.
6. **Производственные правила алертинга (Prometheus Alertmanager):**
   ```yaml
   groups:
     - name: nginx_cache_alerts
       rules:
         # Оповещение о деградации Hit Ratio ниже 75%
         - alert: NginxCacheHitRatioLow
           expr: |
             (
               sum(rate(angie_http_cache_responses_total{status=~"hit|revalidated"}[5m]))
               /
               sum(rate(angie_http_cache_responses_total[5m]))
             ) * 100 < 75
           for: 10m
           labels:
             severity: warning
           annotations:
             summary: "Низкий коэффициент попаданий в кэш на {{ $labels.instance }}"
             description: "Hit Ratio составляет {{ $value | printf \"%.2f\" }}% за последние 10 минут."

         # Оповещение об исчерпании дисковой емкости кэша (> 92%)
         - alert: NginxCacheDiskNearFull
           expr: (angie_http_cache_size_bytes / angie_http_cache_max_size_bytes) * 100 > 92
           for: 15m
           labels:
             severity: critical
           annotations:
             summary: "Дисковое пространство кэш-зоны близко к исчерпанию на {{ $labels.instance }}"
             description: "Кэш-зона {{ $labels.cache }} заполнена на {{ $value | printf \"%.2f\" }}%."
   ```

---

## Дополнительная информация

### Взаимосвязь с компонентами инфраструктуры

* **Loki / Vector / VictoriaMetrics Logs:** Сбор логов из `cache_json` с парсингом полей в лейблы позволяет строить визуализацию распределения статусов и локализовать медленные запросы.
* **OpenTelemetry Collector:** Прием спанов с атрибутом `http.cache.status` связывает сквозной трейс пользователя с внутренним состоянием кэш-подсистемы обратного прокси.
* **Grafana Dashboards:** Рекомендуется визуализировать RPS по статусам кэша, коэффициент Hit Ratio, объем занятой дисковой памяти кэш-зон и P95 задержек в разрезе `HIT` vs `MISS`.

### Связанные темы

* [Обзор кэширования в Nginx и Angie](./overview.md) — фундаментальные архитектурные концепции, жизненный цикл и стратегии инвалидации.
* [Серверное кэширование (Proxy Cache)](./proxy_caching.md) — детальная настройка директив `proxy_cache`, ключей, заголовков и разделения зон.
* [Микрокэширование в Nginx](./microcaching.md) — техники сверхкороткого кэширования для сглаживания пиковых всплесков трафика.
* [Оптимизация производительности Nginx](../nginx_performance_tuning.md) — настройка пулов потоков (`aio threads`), `sendfile` и сетевого стека ядра Linux.
* [Настройка мониторинга Nginx с VTS-модулем](../../Operations/nginx_vts_monitoring_setup.md) — сборка модуля VTS, развертывание в production и экспозиция метрик.
* [Анализ логов Nginx](../../Operations/nginx_log_analysis.md) — паттерны структурированного логирования и методы траблшутинга.
