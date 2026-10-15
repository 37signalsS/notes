# Кэширование прокси в Angie (Proxy Cache)

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Кэширование прокси (Proxy Cache)** — подсистема обратного HTTP-проксирования веб-сервера Angie (модуль `ngx_http_proxy_module`), сохраняющая ответы вышестоящих бэкендов в локальном многоуровневом хранилище (индекс метаданных в разделяемой оперативной памяти и тела ответов на дисковой подсистеме). Позволяет обслуживать повторные запросы клиентов без повторного обращения к приложениям и базам данных, снижая TTFB и предотвращая перегрузку бэкендов.

**Кэш-зона (`keys_zone`)** — именованный сегмент разделяемой памяти (shared memory), доступный всем рабочим процессам (worker processes) Angie. Хранит двоичный красно-черный индекс ключей, хэши MD5, таймстампы свежести, счетчики обращений и метаданные заголовков. 1 МБ памяти зоны вмещает приблизительно 8 000 уникальных ключей кэша.

**Персистентность индекса (`keys_zone ... :file=`)** — системный механизм Angie, сохраняющий снимок бинарного индекса `keys_zone` на диск при корректном завершении мастера (`SIGQUIT`, `SIGTERM`, бинарный апгрейд) и восстанавливающий его в то же виртуальное адресное пространство при запуске. Исключает «холодный старт» и всплески IOPS от процесса `cache loader`.

**Шардирование кэша (Cache Sharding)** — функциональность Angie PRO, позволяющая объявлять несколько директив `proxy_cache_path` с одним и тем же именем `keys_zone` и распределять сохраняемые ответы по разным путям файловой системы (например, по типу контента, статусу ответа или типу дискового накопителя NVMe/HDD) с помощью параметра `path=` в `proxy_cache`.

**Инвалидация кэша (Cache Purge)** — принудительное немедленное удаление объекта или группы объектов из оперативной памяти и дискового хранилища по совпадению ключа кэша без ожидания истечения TTL. В Angie реализуется модулем `ngx_http_cache_purge_module` (пакет `angie-module-cache-purge`), поддерживающим очистку по HTTP-методу `PURGE`, через выделенный location, а также групповой сброс по маске (wildcard `*`).

**Микрокэширование (Microcaching)** — архитектурный паттерн кэширования динамических ответов на экстремально короткое время (от 1 до 10 секунд). Гарантирует актуальность данных для пользователей и одновременно защищает бэкенды от лавинообразной нагрузки при всплесках популярности контента.

**Cache Stampede (Thundering Herd / Эффект стада)** — критическая системная ситуация, при которой истечение TTL одного высоконагруженного ресурса приводит к одновременной отправке сотен параллельных запросов на бэкенд, вызывая деградацию пула приложений и отказ СУБД.

## Архитектура и базовые концепции

### Двухуровневая модель хранения

Архитектура кэширования в Angie строго разделена на два физических уровня:

1. **Индекс метаданных (Shared Memory):**
   - Находится в общей оперативной памяти воркеров (`keys_zone`).
   - Использует красно-черное дерево (Red-Black Tree) для быстрого поиска ключа по 128-битному MD5-хэшу (`O(log N)`).
   - Ведет двухсвязный список LRU (Least Recently Used) для эффективного вытеснения устаревших данных при нехватке памяти или дискового пространства.
   - 1 МБ памяти вмещает ~8 000 ключей кэша (при 100 МБ кэш индексирует до 800 000 объектов).

2. **Хранилище полезной нагрузки (Дисковая подсистема и Page Cache ядра Linux):**
   - Тела ответов и служебные заголовки сериализуются в файлы на файловой системе (`ext4`, `xfs`).
   - Имя файла на диске формируется как MD5-хэш ключа кэша. Иерархия каталогов (`levels=1:2`) предотвращает деградацию производительности файловой системы при наличии сотен тысяч файлов в одном каталоге.
   - Ядро Linux автоматически удерживает «горячие» файлы кэша в системном Page Cache. Благодаря этому наиболее востребованные ответы фактически отдаются из RAM без физических обращений к блочному устройству.
   - Использование `use_temp_path=off` гарантирует атомарную запись: воркер сразу создает временный файл внутри целевого дерева кэша на том же блочном устройстве и переименовывает его через системный вызов `rename()`, исключая накладные расходы на копирование между точками монтирования.

```
[Клиентский HTTP-запрос]
         │
         ▼
[Angie Worker Process] ────► [Поиск в RAM: keys_zone (Red-Black Tree)]
         │                                      │
    MISS / EXPIRED                        HIT / REVALIDATED
         │                                      │
         ▼                                      ▼
[Запрос к Upstream-бэкенду]              [Чтение из диска / Page Cache]
         │                                      │
[Запись во временный файл]                       │
         │                                      │
[Атомарный rename() в кэш]                       │
         │                                      │
         └───────────────┬──────────────────────┘
                         ▼
             [HTTP-ответ клиенту]
```

### Фоновые процессы управления кэшем

Angie управляет состоянием кэша с помощью специализированных дочерних процессов:

* **Cache Manager:** Периодически просыпается для проверки лимитов `max_size` и `min_free`. При превышении порогов удаляет наименее востребованные данные по алгоритму LRU. Параметры `manager_files`, `manager_threshold` и `manager_sleep` позволяют точно регулировать нагрузку процесса на дисковую подсистему и процессор.
* **Cache Loader:** Выполняется однократно при запуске сервера для обхода дискового каталога кэша и наполнения `keys_zone` метаданными существующих файлов. В классическом Nginx этот процесс генерирует высокий всплеск произвольного чтения (IOPS starvation). В Angie при использовании параметра `:file=` процесс Cache Loader полностью пропускает этап сканирования диска, мгновенно считывая сохраненный индекс из бинарного файла.

### Жизненный цикл и статусы переменной `$upstream_cache_status`

Состояние объекта отслеживается встроенной переменной `$upstream_cache_status`:

| Статус | Описание | Механизм обработки |
| :--- | :--- | :--- |
| `HIT` | Ответ успешно отдан из кэша | Бэкенд не задействован; ответ сформирован из локального хранилища. |
| `MISS` | Запрашиваемый ресурс отсутствует в кэше | Запрос передан бэкенду; полученный ответ сохранен в кэш. |
| `EXPIRED` | Срок жизни TTL истек | Запрос направлен бэкенду для обновления содержимого. |
| `STALE` | Отдан устаревший кэш | Бэкенд недоступен или возвращает ошибку (`proxy_cache_use_stale`). |
| `UPDATING` | Кэш обновляется параллельным запросом | Текущий запрос получил старую копию, пока первый воркер обновляет кэш (`proxy_cache_use_stale updating`). |
| `REVALIDATED` | Кэш подтвержден бэкендом (304 Not Modified) | Angie выполнил условный запрос (`If-Modified-Since`/`If-None-Match`), бэкенд вернул `304`, TTL продлен без повторной передачи тела. |
| `BYPASS` | Кэш намеренно пропущен | Сработала директива `proxy_cache_bypass` (например, для сессий администраторов). |

### Отличия и преимущества Angie перед Nginx OSS

1. **Нативная поддержка Cache Purge:** Модуль `ngx_http_cache_purge_module` доступен в виде официального динамического пакета `angie-module-cache-purge` и поддерживает как точечную инвалидацию по URI/методу, так и групповую очистку по маске `*`.
2. **Персистентность индекса (`:file=`):** Индекс разделяемой памяти сохраняется в дамп при остановке и восстанавливается без фазы прогрева и сканирования диска.
3. **Шардирование кэша (Angie PRO):** Несколько независимых хранилищ могут обслуживаться единой зоной памяти, маршрутизируя контент через `path=` (например, разделение быстрых SSD и емких HDD).
4. **Контроль свободного места (`min_free=`):** Встроенный мониторинг файловой системы предотвращает переполнение дискового раздела (`100% disk full`).
5. **Глубокая телеметрия (Status API и Prometheus):** Нативный сбор детальных метрик по каждой зоне кэша через REST API `/status/http/caches/<zone>/` и экспорт в Prometheus без внешних парсеров логов.

## Практические сценарии

### Требования к окружению и предварительная подготовка

Перед развертыванием кэширования подготовьте операционную систему Linux и установите необходимые пакеты:

```bash
# 1. Установка Angie и модуля Cache Purge в дистрибутивах на базе Debian/Ubuntu
sudo apt update
sudo apt install -y angie angie-module-cache-purge

# Для дистрибутивов RHEL/AlmaLinux/Rocky Linux:
# sudo dnf install -y angie angie-module-cache-purge

# 2. Подготовка каталогов для хранения данных кэша и бинарных дампов
sudo mkdir -p /var/cache/angie/proxy /var/lib/angie
sudo chown -R angie:angie /var/cache/angie /var/lib/angie
sudo chmod 700 /var/cache/angie /var/lib/angie
```

### Сценарий 1: Базовая производственная конфигурация с персистентностью и защитой диска

Конфигурация настраивает отказоустойчивый дисковый кэш с контролем свободного пространства, сохранением бинарного индекса на диск и мониторингом через Status API.

```nginx
# /etc/angie/angie.conf

user angie;
worker_processes auto;
worker_rlimit_nofile 65535;
error_log /var/log/angie/error.log warn;
pid /run/angie.pid;

events {
    worker_connections 8192;
    use epoll;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;

    # Формат логирования с обязательной фиксацией статуса кэша и времени ответа бэкенда
    log_format cache_combined '$remote_addr - $remote_user [$time_local] '
                             '"$request" $status $body_bytes_sent '
                             '"$http_referer" "$http_user_agent" '
                             'cache_status=$upstream_cache_status '
                             'upstream_addr=$upstream_addr '
                             'rt=$request_time uct=$upstream_connect_time '
                             'uht=$upstream_header_time urt=$upstream_response_time';

    access_log /var/log/angie/access.log cache_combined;

    # Определение пути кэша:
    # - levels=1:2 создает двухуровневую иерархию (например, /a/b1/d41d8cd98f00b204e9800998ecf8427e)
    # - keys_zone=main_cache:20m:file=/var/lib/angie/main_cache.zone резервирует 20 МБ RAM (~160 000 ключей)
    #   и сохраняет снимок памяти в файл при рестартах
    # - max_size=10g ограничивает суммарный объем данных кэша
    # - min_free=1g активирует очистку LRU, если на диске остается менее 1 ГБ свободного места
    # - inactive=12h удаляет данные при отсутствии обращений в течение 12 часов
    # - use_temp_path=off выполняет прямую атомарную запись в каталог кэша
    proxy_cache_path /var/cache/angie/proxy
                     levels=1:2
                     keys_zone=main_cache:20m:file=/var/lib/angie/main_cache.zone
                     max_size=10g
                     min_free=1g
                     inactive=12h
                     use_temp_path=off;

    upstream app_cluster {
        zone app_cluster 512k;
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
        keepalive 32;
    }

    server {
        listen 80;
        server_name api.example.internal;

        # Защита от Stampede и фоновое обновление
        location / {
            proxy_pass http://app_cluster;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

            # Параметры кэширования
            proxy_cache main_cache;
            proxy_cache_key "$scheme$request_method$host$request_uri";
            proxy_cache_methods GET HEAD;

            # Время жизни кэша для разных HTTP-кодов
            proxy_cache_valid 200 301 302 10m;
            proxy_cache_valid 404 1m;

            # Защита от одновременных запросов к бэкенду (Cache Stampede)
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;
            proxy_cache_lock_age 10s;

            # Отдача устаревшего контента при сбоях и во время обновления
            proxy_cache_use_stale error timeout invalid_header updating
                                  http_500 http_502 http_503 http_504;
            proxy_cache_background_update on;

            # Условная ревалидация через If-Modified-Since / If-None-Match
            proxy_cache_revalidate on;

            # Диагностический заголовок для клиентов и систем мониторинга
            add_header X-Cache-Status $upstream_cache_status always;
        }
    }

    # Сервер телеметрии и Status API
    server {
        listen 127.0.0.1:8888;
        server_name localhost;

        access_log off;

        location /status/ {
            api /status/;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Валидация и применение:**
```bash
# Проверка синтаксиса конфигурации
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Применение изменений без остановки обслуживания трафика
angie -s reload
```

### Сценарий 2: Принудительная инвалидация через модуль Cache Purge (Inline и Dedicated)

В сценарии демонстрируются оба режима инвалидации:
1. Очистка по HTTP-методу `PURGE` на основном URL с поддержкой группового сброса (`wildcard`).
2. Очистка через служебный административный `location /purge/`.

```nginx
# Включение динамического модуля в начале конфигурации (main контекст)
load_module modules/ngx_http_cache_purge_module.so;

http {
    proxy_cache_path /var/cache/angie/proxy
                     levels=1:2
                     keys_zone=api_cache:20m:file=/var/lib/angie/api_cache.zone
                     max_size=5g
                     inactive=24h
                     use_temp_path=off;

    # Нормализация URI для выделенного location очистки
    map $uri $purge_target_uri {
        "~/purge(?<clean_path>/.*)" $clean_path;
        default $uri;
    }

    server {
        listen 80;
        server_name api.example.internal;

        # 1. Выделенный location для автоматизации (CI/CD, webhooks)
        location /purge {
            allow 127.0.0.1;
            allow 10.100.0.0/16;   # Подсеть CI/CD и серверов деплоя
            deny all;

            # Синтаксис: proxy_cache_purge <имя_зоны> <ключ_кэша>
            proxy_cache_purge api_cache "$scheme$request_method$host$purge_target_uri$is_args$args";
        }

        # 2. Основной маршрут с поддержкой inline метода PURGE
        location /api/ {
            proxy_pass http://app_cluster;
            proxy_cache api_cache;
            proxy_cache_key "$scheme$request_method$host$request_uri";
            proxy_cache_valid 200 30m;

            # Синтаксис inline PURGE: proxy_cache_purge PURGE from <доверенные_IP>
            proxy_cache_purge PURGE from 127.0.0.1 10.100.0.0/16;

            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

**Валидация инвалидации кэша через curl:**
```bash
# 1. Первичный запрос ресурса (наполнение кэша)
curl -sI http://api.example.internal/api/v1/products/42 | grep X-Cache-Status
# → X-Cache-Status: MISS

# 2. Повторный запрос (подтверждение попадания в кэш)
curl -sI http://api.example.internal/api/v1/products/42 | grep X-Cache-Status
# → X-Cache-Status: HIT

# 3. Инвалидация конкретного URL методом PURGE
curl -s -X PURGE http://127.0.0.1/api/v1/products/42
# → <html><head><title>Successful purge</title></head><body><h1>Successful purge</h1><p>Key : httpGETapi.example.internal/api/v1/products/42</p></body></html>

# 4. Проверка статуса после сброса (объект снова запрашивается с бэкенда)
curl -sI http://api.example.internal/api/v1/products/42 | grep X-Cache-Status
# → X-Cache-Status: MISS

# 5. Групповая очистка по маске (Wildcard Purge) через служебный location
curl -s -X PURGE "http://127.0.0.1/purge/api/v1/products/*"
# → <html><head><title>Successful purge</title></head><body><h1>Successful purge</h1><p>Key : httpGETapi.example.internal/api/v1/products/*</p></body></html>
```

### Сценарий 3: Высоконагруженное микрокэширование (Microcaching) в tmpfs

Микрокэширование динамических страниц и каталогов с размещением кэша в оперативной памяти (`tmpfs`), изоляцией авторизованных пользователей и обходом кэша.

```bash
# Создание точки монтирования tmpfs для микрокэша
sudo mkdir -p /var/cache/angie/microcache
sudo mount -t tmpfs -o size=1G,noatime,mode=0700,uid=angie,gid=angie tmpfs /var/cache/angie/microcache

# Фиксация в /etc/fstab для сохранения после перезагрузки ОС:
# tmpfs /var/cache/angie/microcache tmpfs size=1G,noatime,mode=0700,uid=angie,gid=angie 0 0
```

```nginx
http {
    # Кэш-зона на базе RAM-диска с коротким временем неактивности
    proxy_cache_path /var/cache/angie/microcache
                     levels=1:2
                     keys_zone=micro_zone:10m
                     max_size=800m
                     inactive=60s
                     use_temp_path=off;

    # Определение условий пропуска кэша
    map $http_authorization $skip_cache_auth {
        default 0;
        "~.+"   1; # Если передан Authorization header, не использовать кэш
    }

    map $http_cookie $skip_cache_cookie {
        default 0;
        "~*(sessionid|jwt|auth_token)" 1; # Не кэшировать для авторизованных сессий
    }

    server {
        listen 80;
        server_name portal.example.internal;

        location / {
            # Вычисление общего флага пропуска
            set $skip_cache 0;
            if ($skip_cache_auth) {
                set $skip_cache 1;
            }
            if ($skip_cache_cookie) {
                set $skip_cache 1;
            }

            proxy_pass http://app_cluster;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            proxy_cache micro_zone;
            proxy_cache_key "$scheme$request_method$host$request_uri";

            # TTL всего 5 секунд для защиты бэкенда при сохранении свежести
            proxy_cache_valid 200 5s;
            proxy_cache_valid 301 302 10s;

            # Управление пропуском и запретом сохранения
            proxy_cache_bypass $skip_cache;
            proxy_no_cache     $skip_cache;

            # Защита от Stampede
            proxy_cache_lock on;
            proxy_cache_lock_timeout 2s;
            proxy_cache_use_stale updating error timeout http_500 http_502 http_503;

            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

### Сценарий 4: Шардирование кэша по типам накопителей (Angie PRO)

В Angie PRO поддерживается маршрутизация кэшированных данных между несколькими физическими каталогами (например, горячий NVMe и холодный HDD массив), привязанными к единой зоне ключей.

```nginx
http {
    # Единая зона keys_zone=shared_cache объявлена в первой директиве
    proxy_cache_path /mnt/nvme/angie_cache
                     levels=1:2
                     keys_zone=shared_cache:50m:file=/var/lib/angie/shared_cache.zone
                     max_size=20g
                     inactive=24h
                     use_temp_path=off;

    # Вторая директива ссылается на ту же зону без указания размера памяти
    proxy_cache_path /mnt/hdd/angie_cache
                     levels=1:2
                     keys_zone=shared_cache
                     max_size=500g
                     inactive=7d
                     use_temp_path=off;

    # Маршрутизация на основе MIME-типа ответа бэкенда
    map $upstream_http_content_type $target_cache_path {
        ~*image/                  /mnt/hdd/angie_cache;
        ~*video/                  /mnt/hdd/angie_cache;
        ~*application/octet-stream /mnt/hdd/angie_cache;
        default                   /mnt/nvme/angie_cache;
    }

    server {
        listen 80;
        server_name media.example.internal;

        location / {
            proxy_pass http://storage_backend;
            proxy_cache shared_cache;
            # Параметр path динамически выбирает директорию размещения на диске
            proxy_cache shared_cache path=$target_cache_path;
            proxy_cache_valid 200 12h;

            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

### Сценарий 5: Сбор метрик кэша через Status API и экспорт в Prometheus

Angie собирает детальные счетчики по попаданиям, промахам и объему кэша, доступные как в формате JSON, так и в стандарте Prometheus.

```nginx
http {
    # Подключение стандартных шаблонов Prometheus
    include /etc/angie/prometheus_all.conf;

    server {
        listen 127.0.0.1:9113;
        server_name localhost;

        access_log off;

        # JSON Status API
        location /status/ {
            api /status/;
            allow 127.0.0.1;
            allow 10.100.0.0/16;
            deny all;
        }

        # Метрики Prometheus (нативный эндпоинт)
        location = /metrics {
            prometheus all;
            allow 127.0.0.1;
            allow 10.100.0.0/16;
            deny all;
        }
    }
}
```

**Проверка метрик через CLI:**
```bash
# 1. Запрос статистики кэш-зоны в формате JSON
curl -sf http://127.0.0.1:9113/status/http/caches/main_cache/ | jq .
# → {
# →   "size": 345288704,
# →   "max_size": 10737418240,
# →   "cold": false,
# →   "hit": { "responses": 184500, "bytes": 4829104800 },
# →   "miss": { "responses": 12100, "bytes": 312040100 },
# →   "stale": { "responses": 45, "bytes": 1152000 },
# →   "updating": { "responses": 12, "bytes": 305000 },
# →   "revalidated": { "responses": 890, "bytes": 22400000 },
# →   "expired": { "responses": 1400, "bytes": 36800000 },
# →   "bypass": { "responses": 320, "bytes": 8450000 }
# → }

# 2. Вычисление коэффициента попадания (Hit Ratio)
curl -sf http://127.0.0.1:9113/status/http/caches/main_cache/ | jq '
  (.hit.responses) as $h |
  ($h + .miss.responses + .bypass.responses + .expired.responses) as $total |
  {
    total_requests: $total,
    hit_ratio_percent: (if $total > 0 then (($h / $total) * 100 | round) else 0 end),
    used_mb: (.size / 1024 / 1024 | round)
  }'
# → {
# →   "total_requests": 198320,
# →   "hit_ratio_percent": 93,
# →   "used_mb": 329
# → }

# 3. Чтение метрик в формате Prometheus
curl -sf http://127.0.0.1:9113/metrics | grep -E "^angie_http_cache"
# → angie_http_cache_size_bytes{cache="main_cache"} 345288704
# → angie_http_cache_max_size_bytes{cache="main_cache"} 10737418240
# → angie_http_cache_responses_total{cache="main_cache",status="hit"} 184500
# → angie_http_cache_responses_total{cache="main_cache",status="miss"} 12100
# → angie_http_cache_responses_total{cache="main_cache",status="stale"} 45
```

## Операции и команды

Сводная таблица ключевых процедур администрирования, обслуживания и аудита кэша Angie:

| Операция | Команда / Запрос | Назначение и ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка конфигурации** | `angie -t` | Проверка синтаксиса директив и доступности путей. Вывод: `syntax is ok`. |
| **Бесшовный reload** | `angie -s reload` | Применение новых параметров кэша без разрыва соединений. |
| **Аудит процессов** | `ps -eo pid,user,stat,command \| grep "angie: cache"` | Контроль активности процессов `cache manager` и `cache loader`. |
| **Проверка файла индекса** | `ls -lh /var/lib/angie/*.zone` | Проверка наличия и размера файла бинарного дампа памяти. |
| **Контроль диска и inodes** | `df -h /var/cache/angie && df -i /var/cache/angie` | Проверка доступного места и остатка свободных дескрипторов (inodes). |
| **Статистика Page Cache** | `cachestat 5` | Мониторинг процента попаданий в системный Page Cache ядра Linux (bcc-tools). |
| **Статистика дискового ввода-вывода** | `iostat -x 2` | Оценка утилизации диска (`%util`) и задержек (`await`) хранилища кэша. |
| **Точечная инвалидация** | `curl -s -X PURGE http://127.0.0.1/api/path` | Мгновенный сброс одного объекта по ключу. |
| **Инвалидация по маске** | `curl -s -X PURGE http://127.0.0.1/purge/api/path/*` | Групповой сброс дочерних ресурсов (требует `angie-module-cache-purge`). |
| **Экстренная очистка кэша** | `rm -rf /var/cache/angie/proxy/* && angie -s reload` | Полный сброс всех кэшированных файлов при аварии (кэш переходит в холодный режим). |

## Troubleshooting

### Проблема 1: Ошибка восстановления индекса `failed to restore zone at address`

**Симптом:** После рестарта сервера или обновления ОС в `/var/log/angie/error.log` появляется предупреждение:
```
[warn] 14201#14201: failed to restore zone "main_cache" at address 00007F12A0000000, using old style initialization
```
Hit Ratio временно падает, нагрузка на диски возрастает из-за работы `cache loader`.

**Причина:** 
1. Сработало системное рандомизирование адресного пространства (ASLR) ядра Linux, либо виртуальный адрес, куда проецировался `keys_zone`, оказался занят другой библиотекой.
2. Был изменен размер зоны в конфигурации (`keys_zone=main_cache:20m` изменен на `30m`).

**Диагностика:**
```bash
grep -E "failed to restore zone|using old style" /var/log/angie/error.log
# Проверка наличия файла с суффиксом .old, созданного Angie автоматически
ls -l /var/lib/angie/
# → -rw-r----- 1 angie angie 20971520 Oct 14 10:00 main_cache.zone.old
```

**Решение:**
- Ситуация штатная: Angie автоматически переименовывает несовместимый файл в `.old`, не прерывает работу сервиса и запускает стандартный `cache loader` для сканирования диска.
- Если менялся размер зоны, удалите старый дамп вручную:
  ```bash
  sudo rm -f /var/lib/angie/main_cache.zone.old
  ```
- При регулярных сбоях из-за ASLR убедитесь, что размер зоны кратен размеру страницы памяти (`getconf PAGE_SIZE`, обычно 4096 байт).

### Проблема 2: Исчерпание inode при наличии свободного дискового пространства

**Симптом:** При записи ответов в логе появляются ошибки:
```
[crit] 15102#15102: open() "/var/cache/angie/proxy/3/ab/..." failed (28: No space left on device)
```
При этом утилита `df -h` показывает достаточное количество свободного объема диска (>30%).

**Причина:** Каталог кэша заполнен огромным количеством мелких файлов (микрокэш, фрагменты API), что привело к исчерпанию таблицы индексных дескрипторов (inode) файловой системы.

**Диагностика:**
```bash
df -i /var/cache/angie
# → Filesystem      Inodes   IUsed IFree IUse% Mounted on
# → /dev/sdb1      1310720 1310720     0  100% /var/cache/angie
```

**Решение:**
1. Если кэш размещен на отдельном томе `ext4`, файловую систему необходимо пересоздать с увеличенным количеством inode (`mkfs.ext4 -i 4096 /dev/sdb1`). Для файловой системы `xfs` дескрипторы выделяются динамически.
2. Ограничьте суммарный объем и сократите время жизни `inactive` в директиве `proxy_cache_path`:
   ```nginx
   proxy_cache_path /var/cache/angie/proxy levels=1:2 keys_zone=main_cache:20m inactive=2h max_size=5g;
   ```
3. Выполните немедленную ротацию старых файлов через `find`:
   ```bash
   sudo find /var/cache/angie/proxy -type f -amin +120 -delete
   ```

### Проблема 3: Блокировка рабочих процессов (Worker Block) на дисковых операциях

**Симптом:** В моменты высокой нагрузки возрастает latency всех запросов (включая некэшируемые). Утилита `top` показывает высокую загрузку CPU в состоянии `iowait` (`%wa > 15%`).

**Причина:** Чтение холодных данных с медленного диска выполняется воркером синхронно, блокируя обработку событий в цикле `epoll`.

**Диагностика:**
```bash
# Проверка iowait
iostat -xz 1 5
# Проверка блокировок воркера с помощью pstack/gdb
pstack $(pgrep -f "angie: worker" | head -n 1) | grep -iE "pread|pwrite|read"
```

**Решение:**
Включите асинхронный дисковый ввод-вывод через пул потоков (Thread Pools) в контексте `http`:
```nginx
# Включение пула потоков для неблокирующего чтения кэша
thread_pool default_pool threads=32 max_queue=65536;

http {
    aio threads=default_pool;
    directio 10m; # Прямой ввод-вывод в обход Page Cache для очень больших файлов
    ...
}
```

### Проблема 4: Ошибка 403 Forbidden при вызове PURGE

**Симптом:** Запрос на инвалидацию возвращает статус `403 Forbidden`:
```
<html><head><title>403 Forbidden</title></head><body><center><h1>403 Forbidden</h1></center></body></html>
```

**Причина:** IP-адрес клиента, отправляющего запрос, не совпадает со списком сетей, разрешенных в блоке `allow` или директиве `proxy_cache_purge ... from`.

**Диагностика:**
```bash
grep "access forbidden by rule" /var/log/angie/error.log
# → [error] 16200#16200: *451 access forbidden by rule, client: 192.168.1.50, server: api.example.internal
```

**Решение:**
Добавьте IP-адрес источника (CI/CD runner, балансировщик, адрес администратора) в список доверенных:
```nginx
proxy_cache_purge PURGE from 127.0.0.1 192.168.1.50 10.100.0.0/16;
```

### Проблема 5: Утечка персональных данных через кэширование ответов с Set-Cookie

**Симптом:** Пользователи получают чужие сессионные куки или видят данные чужих личных кабинетов.

**Причина:** Некорректно применена директива `proxy_ignore_headers Set-Cookie;` для динамических бэкендов, выдающих идентификаторы пользовательских сессий.

**Диагностика:**
```bash
# Проверка заголовков ответов бэкенда
curl -sI http://127.0.0.1:8080/api/profile | grep -i Set-Cookie
# → Set-Cookie: session_id=xyz987; Path=/; HttpOnly
```

**Решение:**
1. Ни в коем случае не отключайте обработку `Set-Cookie` глобально. По умолчанию Angie **не кэширует** ответы с `Set-Cookie`, `Cache-Control: private` или `no-cache`.
2. Если кэширование публичной части API необходимо, на бэкенде удалите генерацию кук для публичных эндпоинтов либо используйте точечное скрытие заголовков:
   ```nginx
   location /api/public/ {
       proxy_pass http://app_cluster;
       proxy_cache main_cache;
       # Скрывать заголовок Set-Cookie при отдаче клиентам, если бэкенд ошибочно его шлет
       proxy_hide_header Set-Cookie;
       proxy_ignore_headers Set-Cookie;
   }
   ```

## Best Practices

1. **Монтирование файловой системы с опцией `noatime`:**
   Файловая система с кэшем должна монтироваться с параметрами `noatime,nodiratime`. Это устраняет необходимость обновления метаданных времени последнего доступа при каждом чтении файла из кэша, экономя до 30% дисковых операций записи:
   ```
   # /etc/fstab
   UUID=xxxx-xxxx-xxxx /var/cache/angie ext4 defaults,noatime,nodiratime 0 2
   ```

2. **Обязательное использование `use_temp_path=off`:**
   Всегда указывайте `use_temp_path=off` в директиве `proxy_cache_path`. Это исключает промежуточную запись во временный каталог `/var/lib/angie/proxy_temp` и гарантирует атомарное переименование файла внутри одной файловой системы.

3. **Защита от Thundering Herd (Cache Stampede):**
   На производственных серверах для публичных и высоконагруженных маршрутов всегда активируйте связку директив:
   ```nginx
   proxy_cache_lock on;
   proxy_cache_lock_timeout 5s;
   proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
   proxy_cache_background_update on;
   ```
   Это гарантирует, что только один запрос обратится к бэкенду за обновлением, а остальные клиенты мгновенно получат предыдущую версию из кэша.

4. **Защита от переполнения диска (`min_free=`):**
   Задавайте параметр `min_free=` с запасом не менее 1–5 ГБ в зависимости от размера накопителя. При исчерпании диска процесс Cache Manager начнет экстренную утилизацию LRU до того, как ОС вернет ошибку `No space left on device`.

5. **Безопасность ключа кэша и учет вариативности (`Vary`):**
   Включайте в `proxy_cache_key` только те параметры, которые реально влияют на ответ (`$scheme$request_method$host$request_uri`). Если бэкенд отдает сжатый контент (`gzip` или `brotli`), убедитесь, что бэкенд отдает заголовок `Vary: Accept-Encoding`, либо добавьте `$http_accept_encoding` в ключ кэша.

6. **Ограничение прав на файлы дампа и кэша:**
   Каталоги `/var/cache/angie` и `/var/lib/angie` должны принадлежать системному пользователю `angie:angie` с правами `0700`. Прямой доступ непривилегированных локальных пользователей к файлам кэша должен быть исключен.

7. **Пул потоков (`aio threads`) для предотвращения блокировок:**
   Для высоконагруженных кэш-серверов с объемом данных более десятков гигабайт используйте `aio threads=default_pool;`, чтобы операции чтения с накопителей выполнялись в отдельных системных потоках без блокировки сетевого цикла воркера.

## Дополнительная информация

### Сравнительный анализ возможностей кэширования

| Характеристика | Nginx OSS (1.26.x / 1.28.x) | Angie OSS (1.12.x) | Angie PRO (1.12.x) |
| :--- | :--- | :--- | :--- |
| **Базовый Proxy Cache** | Поддерживается | Поддерживается | Поддерживается |
| **Cache Stampede Lock** | Поддерживается | Поддерживается | Поддерживается |
| **Фоновое обновление кэша** | Поддерживается | Поддерживается | Поддерживается |
| **Модуль Cache Purge** | Требует сторонней сборки | **Официальный пакет (`angie-module-cache-purge`)** | **Официальный пакет (`angie-pro-module-cache-purge`)** |
| **Групповая очистка (Wildcard `*`)** | Только со сторонними патчами | **Поддерживается нативно** | **Поддерживается нативно** |
| **Персистентность индекса (`:file=`)** | Отсутствует | **Поддерживается нативно** | **Поддерживается нативно** |
| **Контроль свободного места (`min_free`)** | Отсутствует (только `max_size`) | **Поддерживается нативно** | **Поддерживается нативно** |
| **Шардирование кэша (Cache Sharding)** | Отсутствует | Отсутствует | **Поддерживается (`proxy_cache path=...`)** |
| **Мониторинг зон через REST API** | Отсутствует | **Встроенный Status API** | **Встроенный Status API** |
| **Нативный экспорт в Prometheus** | Требует `nginx-prometheus-exporter` | **Встроенный модуль (`prometheus all`)** | **Встроенный модуль (`prometheus all`)** |

### См. также

* [Обратный HTTP-прокси в Angie](./angie_reverse_proxy.md) — базовая архитектура обратного прокси, буферизация соединений и upstream keepalive.
* [Мониторинг Angie: REST API](./angie_monitoring/angie_monitoring_api.md) — детальное описание всех эндпоинтов `/status/http/caches/`.
* [Мониторинг Angie: Prometheus](./angie_monitoring/angie_monitoring_prometheus.md) — экспорт телеметрии в Prometheus и настройка алертов.
* [Серверное кэширование в Nginx и Angie](../Nginx/Performance/Caching/proxy_caching.md) — концептуальная база кэширования и алгоритмы LRU.
* [Микрокэширование](../Nginx/Performance/Caching/microcaching.md) — углубленный разбор паттернов микрокэширования.
* [Мониторинг кэширования](../Nginx/Performance/Caching/monitoring.md) — анализ Page Cache ОС Linux и метрик дисковой подсистемы.