# Модуль image_filter в Angie: стратегии кэширования

**Актуально для:** Angie 1.12.x

## Определения

**Proxy Cache (Прокси-кэш)** — встроенный механизм Angie для сохранения ответов бэкенда на локальном диске с поддержанием индекса ключей в разделяемой оперативной памяти (`keys_zone`). Устраняет повторные вызовы модуля трансформации `image_filter` для идентичных запросов.

**Cache Index Persistence (Сохранение индекса)** — функциональность Angie (параметр `file=` директивы `proxy_cache_path`), обеспечивающая сериализацию метаданных разделяемой памяти на диск при остановке или перезагрузке процесса и прямое восстановление при старте. Полностью исключает фазу обхода файловой системы (`cache loader`) и сопутствующий дисковый I/O-шторм.

**Double Proxying (Двойное проксирование)** — архитектурный паттерн разделения логики обслуживания на два независимых контура (внешний фронтенд с прокси-кэшем и внутренний процессор с `image_filter`), гарантирующий кэширование уже сжатого и преобразованного изображения, а не оригинала.

**Cache Key (Ключ кэша)** — строка-дескриптор, генерируемая директивой `proxy_cache_key` на основе параметров входящего запроса. При динамической обработке изображений ключ обязан включать путь к оригиналу, параметры геометрической трансформации и согласованный целевой формат (`$http_accept`).

**Cache Stampede / Thundering Herd (Эффект «стада бизонов»)** — лавинообразный наплыв сотен или тысяч параллельных запросов на один и тот же отсутствующий в кэше объект (MISS), способный исчерпать ресурсы CPU серверов трансформации. Предотвращается директивой `proxy_cache_lock`.

**Cache Pollution / Poisoning (Отравление кэша)** — запись в кэш некорректной вариации контента (например, сохранение AVIF под общим ключом без учета заголовка `Accept`, в результате чего клиенты без поддержки AVIF получают битый файл).

**Cache Revalidation (Ревалидация кэша)** — механизм условной проверки актуальности устаревшего объекта в кэше с помощью HTTP-заголовков `If-Modified-Since` или `If-None-Match`. При получении ответа `304 Not Modified` время жизни объекта продлевается без повторной ресурсоемкой трансформации.

**Stale Cache (Устаревший контент)** — состояние объекта кэша, TTL которого истек, но который временно отдается клиентам при недоступности бэкенда или во время фоновой генерации новой версии (`proxy_cache_use_stale`).

**Bypass (Обход кэша)** — контролируемая директивой `proxy_cache_bypass` передача клиентского запроса напрямую во внутренний контур трансформации без чтения данных из кэша.

**Cache Purge (Инвалидация кэша)** — принудительное удаление устаревших данных из разделяемой памяти и с диска по ключу кэша с использованием встроенной директивы Angie `proxy_cache_purge`.

**Cache Loader и Cache Manager** — служебные системные процессы Angie: `cache loader` осуществляет сканирование файлов кэша с диска в память при холодном старте (если не настроен Persistence), а `cache manager` непрерывно отслеживает размер хранилища и вытесняет файлы по алгоритму LRU при достижении порога `max_size` или по таймауту `inactive`.

---

## Базовые концепции

### Жизненный цикл объекта в кэше image_filter

```
1. Клиент → Фронтенд (Accept: image/avif, URI: /resize/400/photo.jpg)
2. Фронтенд → Поиск ключа в разделяемой памяти (keys_zone)
   ├─ HIT  → Чтение готового AVIF с диска/page cache → Отдача клиенту (X-Cache-Status: HIT)
   └─ MISS → Захват блокировки proxy_cache_lock
             ├─ Первый запрос:
             │  Фронтенд → Unix-сокет (/var/run/angie_img_filter.sock)
             │  Бэкенд: чтение оригинала из локального хранилища → image_filter (декомпрессия, resize, AVIF)
             │  Бэкенд → Возврат AVIF фронтенду
             │  Фронтенд → Атомарная запись на диск кэша + добавление в keys_zone
             │  Фронтенд → Клиент (X-Cache-Status: MISS)
             └─ Ожидающие запросы:
                Ожидание завершения первой трансформации → Отдача из кэша (X-Cache-Status: HIT)
```

### Архитектурный подход: Двойное проксирование

Использование `image_filter` и `proxy_cache` внутри одного блока `location` невозможно, так как архитектура HTTP-пайплайна Nginx/Angie выполняет проверку и сохранение кэша в фазе контента *до* того, как фильтры вывода (`output filters`) успевают изменить тело ответа. Без разделения на два уровня кэшироваться будет исходный файл до обработки.

1. **Внешний уровень (Frontend / Cache Engine):**
   - Принимает публичный трафик (SSL/TLS termination, HTTP/2, HTTP/3).
   - Выполняет согласование контента (Content Negotiation) через директиву `map` по заголовку `Accept`.
   - Проверяет наличие ключа в зоне `keys_zone`.
   - Обеспечивает защиту от Cache Stampede и отдает устаревший кэш при фоновом обновлении.
   - Проксирует MISS-запросы во внутренний контур через Unix domain socket.
2. **Внутренний уровень (Backend / Image Processing):**
   - Доступен исключительно локально (директива `internal` или права доступа к сокету).
   - Читает оригинал изображения из локальной файловой системы или апстрим-хранилища.
   - Выделяет память `image_filter_buffer`, производит распаковку, кадрирование/ресайз и упаковку в целевой формат.
   - Возвращает готовый бинарный поток фронтенду с корректными заголовками `Content-Type`.

#### Сравнение каналов межслойного взаимодействия

| Параметр | TCP Loopback (`127.0.0.1:8081`) | Unix Domain Socket (`/var/run/angie_img_filter.sock`) |
|:---|:---|:---|
| **Сетевой стек ядра** | Полный проход TCP/IP, IP checksum, TCP state machine | Исключен (прямая передача через сокетные буферы VFS) |
| **Расход сокетов и портов** | Тратит эфемерные порты, риск состояния `TIME_WAIT` | Не использует порты, не подвержен исчерпанию портов |
| **Безопасность доступа** | Требует настройки firewall или директив `allow`/`deny` | Контролируется стандартными правами Linux (`chmod 660`, `chown`) |
| **Пропускная способность** | Дополнительный CPU overhead на упаковку TCP-сегментов | Выше на 15–25% при обработке мелких бинарных объектов |

### Конструкция ключа кэша и предотвращение Cache Pollution

Ключ кэша должен уникально описывать каждую физическую вариацию изображения. Минимально корректная структура ключа:

```nginx
proxy_cache_key "$scheme$request_method$host$uri$is_args$args$img_format";
```

**Ошибки проектирования ключа:**
- **Отсутствие формата (`$img_format` / `$http_accept`):** Если первый запрос поступил от браузера Chrome с поддержкой AVIF, сервер сформирует AVIF и закэширует его по общему URI. Следующий запрос от Safari (без поддержки AVIF) получит битое изображение из кэша (Cache Pollution).
- **Отсутствие аргументов (`$is_args$args`):** Запросы с разными размерами превью (`?w=200` и `?w=800`) перезапишут или разделят один и тот же объект.
- **Отсутствие заголовка Vary:** При адаптивной отдаче разных форматов по одинаковому URL фронтенд обязан возвращать заголовок `Vary: Accept`, иначе промежуточные корпоративные прокси и браузеры закэшируют несовместимый формат.

### Механизм Cache Index Persistence (`file=`)

При хранении сотен тысяч или миллионов изображений в кэше объемом 50–500 ГБ стандартный перезапуск веб-сервера вызывает высокую деградацию системы:
- **Без Persistence:** Процесс `cache loader` начинает рекурсивно обходить дерево директорий на диске, вычитывая заголовки каждого файла в разделяемую память. При 5 млн файлов данный процесс занимает от 5 до 25 минут, загружая подсистему дискового I/O на 100% (высокий `%iowait`) и замедляя обработку обычных клиентских запросов.
- **С Persistence (`file=`):** При плановом завершении работы (`systemctl stop angie` или `systemctl reload angie`) мастер-процесс сериализует красно-черное дерево и очереди LRU из `keys_zone` в компактный бинарный дамп на диске. При старте мастер отображает дамп в память через `read`/`mmap` менее чем за 1 секунду. Кэш сразу становится «горячим» (Cold Start Latency = 0).
- **Поведение при сбоях (Crash Recovery):** Если сервер завершился аварийно (Kernel Panic, `kill -9`), файл индекса `.zone` не обновляется или повреждается. Angie проверяет контрольную сумму и заголовок файла дампа при запуске. Если обнаружено повреждение, файл автоматически игнорируется, в `error.log` фиксируется предупреждение, и Angie запускает стандартный фоновый `cache loader` без падения сервера.

### Механизм работы Cache Manager и Cache Loader

- **Cache Manager (LRU Eviction):** Фоновый процесс, активируемый периодически для контроля объема кэша. Если суммарный объем файлов превышает `max_size`, процесс удаляет наименее востребованные файлы (по времени последнего обращения). Также процесс удаляет файлы, к которым не было обращений дольше времени `inactive`.
- **Cache Loader (Инициализация):** Работает только при старте сервера в отсутствие файла сохранения индекса или при повреждении дампа. Читает диск порциями (`loader_files`), делая паузы (`loader_sleep`), чтобы не блокировать доступ к диску воркерам.

### Защита от Stampede и фоновое обновление

При сбросе кэша популярного баннера одновременное поступление 1 000 RPS приведет к тому, что 1 000 воркеров запустят параллельную конвертацию оригинала через `image_filter`, вызвав 100% загрузку CPU и OOM.
- **`proxy_cache_lock on;`** — пропускает во внутренний контур только один запрос для формирования объекта. Все остальные запросы переводятся в состояние ожидания ответа на время `proxy_cache_lock_timeout`.
- **`proxy_cache_use_stale updating;`** — если объект уже присутствует в кэше, но его TTL истек, первый запрос уходит на фоновую генерацию нового файла, а все последующие клиенты мгновенно получают старую копию.
- **`proxy_cache_background_update on;`** — генерация обновленной копии выполняется асинхронно, клиент вообще не ждет выполнения ресайза.

### Золотые сигналы кэширования (SRE Golden Signals)

- **Hit Ratio:** Доля запросов, обслуженных из кэша без обращения к фильтру (`HIT / (HIT + MISS + BYPASS)`). Целевое значение для статических изображений: **> 95%**.
- **Cold Start Latency:** Время от запуска сервиса до достижения целевого Hit Ratio. С параметром `file=` стремится к 0.
- **Stale Ratio:** Доля ответов, отданных из устаревшего кэша во время сбоя бэкенда или фонового обновления. Должна быть < 5% в штатном режиме.
- **Bypass Rate:** Доля запросов, намеренно обошедших кэш. Превышение порога 1% свидетельствует об атаке или некорректных клиентских заголовках `Cache-Control: no-cache`.
- **Tail Latency (P95/P99):** Задержка MISS-запросов. Не должна превышать 300–600 мс для типовых изображений.

---

## Практические сценарии

### Предварительные требования

Перед развертыванием убедитесь в соблюдении системных условий:

1. **Версия ПО:** Angie >= 1.12.0 (для нативной поддержки `proxy_cache_purge` и улучшенной персистентности индекса) с модулем `ngx_http_image_filter_module`.
2. **Системные библиотеки:** `libgd` с поддержкой `libwebp` и `libavif`. Проверка в операционной системе:
   ```bash
   angie -V 2>&1 | grep -o 'gd-\S*' | sort -u
   # → gd-avif
   # → gd-jpeg
   # → gd-png
   # → gd-webp
   ```
3. **Файловая система и структура директорий:** Выделенная точка монтирования с отключенной записью времени доступа (`noatime,nodiratime`):
   ```bash
   mkdir -p /var/cache/angie/images /var/lib/angie /var/run/angie
   chown -R angie:angie /var/cache/angie /var/lib/angie /var/run/angie
   chmod 750 /var/cache/angie /var/lib/angie
   chmod 755 /var/run/angie
   ```

---

### Сценарий 1: Базовая конфигурация кэша с сохранением индекса (Persistence)

Конфигурация оптимизирована для долговременного хранения 50 ГБ медиафайлов (~2 млн уникальных трансформаций).

```nginx
# Файл: /etc/angie/conf.d/01_image_cache_zone.conf

http {
    # 256 МБ RAM вмещают около 2 000 000 метаданных ключей (из расчета ~128 байт на запись в 64-bit)
    proxy_cache_path /var/cache/angie/images
                     levels=1:2
                     keys_zone=img_cache:256m
                     file=/var/lib/angie/img_cache.zone
                     max_size=50g
                     inactive=72h
                     use_temp_path=off;
}
```

**Параметры директивы:**
- `levels=1:2` — двухуровневая структура каталогов (например, `/var/cache/angie/images/a/3f/3df51634f1e00ca...`), предотвращающая падение производительности поиска в директориях при миллионах файлов.
- `keys_zone=img_cache:256m` — выделение зоны разделяемой памяти размером 256 МБ для хранения хэшей ключей и LRU-указателей.
- `file=/var/lib/angie/img_cache.zone` — путь к файлу дампа метаданных индекса кэша.
- `max_size=50g` — верхний лимит занятого дискового пространства; при его достижении `cache manager` активирует вытеснение файлов.
- `inactive=72h` — время, после которого файл удаляется, если к нему не было обращений.
- `use_temp_path=off` — сохранение входящего потока сразу в целевую директорию кэша без промежуточного копирования из временной папки.

**Валидация:**
```bash
# Проверка синтаксиса и перезапуск Angie
angie -t && systemctl restart angie
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка создания структуры кэша
ls -la /var/cache/angie/images
# → drwxr-x--- 2 angie angie 4096 Oct 14 11:50 .
```

---

### Сценарий 2: Реализация паттерна «Двойное проксирование» через Unix-сокет

Конфигурация внешнего кэширующего фронтенда и изолированного внутреннего обработчика с автоматическим согласованием форматов (AVIF/WebP).

```nginx
# Файл: /etc/angie/conf.d/image_pipeline.conf

# 1. Согласование формата на основе заголовка Accept
map $http_accept $img_target_format {
    "~*image/avif"  "avif";
    "~*image/webp"  "webp";
    default         "original";
}

# 2. Внешний фронтенд (SSL, кэширование, защита)
server {
    listen 443 ssl http2;
    server_name images.example.com;

    ssl_certificate     /etc/ssl/certs/images.example.com.crt;
    ssl_certificate_key /etc/ssl/private/images.example.com.key;

    # Локация для динамической обработки: /resize/<width>/<path_to_image>
    location ~* ^/resize/(?<req_width>\d+)/(?<image_path>.+)$ {
        proxy_cache img_cache;
        
        # Строго детерминированный ключ кэша
        proxy_cache_key "$scheme$request_method$host$req_width$image_path$img_target_format";
        
        # Правила валидности кэша по кодам ответа
        proxy_cache_valid 200 30d;
        proxy_cache_valid 404 415 5m;
        proxy_cache_valid any 0;

        # Защита от эффекта "стада бизонов"
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;

        # Отдача устаревшего контента при обновлении или сбое
        proxy_cache_use_stale error timeout invalid_header updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;

        # Диагностические заголовки
        add_header X-Cache-Status $upstream_cache_status always;
        add_header Vary "Accept" always;

        # Передача во внутренний контур через Unix domain socket
        proxy_pass http://unix:/var/run/angie_img_filter.sock:/process?w=$req_width&img=$image_path&fmt=$img_target_format;
        proxy_set_header Host $host;
    }
}

# 3. Внутренний сервер обработки изображений (Image Processing Engine)
server {
    listen unix:/var/run/angie_img_filter.sock;

    # Доступ только для локального процесса
    location /process {
        # Корневая директория с исходными файлами высокого разрешения
        root /var/www/storage/originals;
        
        # Перенаправление на конкретный обработчик в зависимости от формата
        if ($arg_fmt = "avif") {
            rewrite ^ /transform_avif last;
        }
        if ($arg_fmt = "webp") {
            rewrite ^ /transform_webp last;
        }
        rewrite ^ /transform_resize last;
    }

    location = /transform_avif {
        internal;
        alias /var/www/storage/originals/$arg_img;
        image_filter_buffer 20M;
        image_filter resize $arg_w -;
        image_filter convert avif;
        image_filter_avif_quality 65;
        image_filter_avif_speed 9;
    }

    location = /transform_webp {
        internal;
        alias /var/www/storage/originals/$arg_img;
        image_filter_buffer 20M;
        image_filter resize $arg_w -;
        image_filter convert webp;
        image_filter_webp_quality 75;
    }

    location = /transform_resize {
        internal;
        alias /var/www/storage/originals/$arg_img;
        image_filter_buffer 20M;
        image_filter resize $arg_w -;
        image_filter_jpeg_quality 85;
        image_filter_interlace on;
    }
}
```

**Валидация работы пайплайна:**
```bash
# 1. Первый запрос с поддержкой AVIF (должен быть MISS)
curl -sI -H "Accept: image/avif,image/webp,*/*" \
     "https://images.example.com/resize/400/catalog/item123.jpg" | grep -iE "x-cache-status|content-type|vary"
# → content-type: image/avif
# → vary: Accept
# → x-cache-status: MISS

# 2. Повторный идентичный запрос (должен быть HIT)
curl -sI -H "Accept: image/avif,image/webp,*/*" \
     "https://images.example.com/resize/400/catalog/item123.jpg" | grep -i "x-cache-status"
# → x-cache-status: HIT

# 3. Запрос от клиента без поддержки AVIF (должен сформировать WebP и вернуть MISS для своего формата)
curl -sI -H "Accept: image/webp,*/*" \
     "https://images.example.com/resize/400/catalog/item123.jpg" | grep -iE "x-cache-status|content-type"
# → content-type: image/webp
# → x-cache-status: MISS
```

---

### Сценарий 3: Настройка условных запросов и фильтрации редких обращений

Для предотвращения заполнения диска «мусорными» разовыми трансформациями от поисковых роботов настраивается двухэтапное кэширование и ревалидация.

```nginx
# Файл: /etc/angie/conf.d/cache_tuning.conf

location ~* ^/resize/(?<req_width>\d+)/(?<image_path>.+)$ {
    proxy_cache img_cache;
    proxy_cache_key "$scheme$request_method$host$req_width$image_path$img_target_format";

    # Объект записывается на диск только при повторном обращении (защита от сканеров)
    proxy_cache_min_uses 2;

    # Ревалидация истекшего кэша по If-Modified-Since
    proxy_cache_revalidate on;

    # Не кэшировать запросы с заголовком отладки
    proxy_cache_bypass $http_x_debug_nocache;

    proxy_pass http://unix:/var/run/angie_img_filter.sock:/process?w=$req_width&img=$image_path&fmt=$img_target_format;
}
```

**Валидация:**
```bash
# Первый запрос: проксируется, но не кэшируется на диск (min_uses 2)
curl -sI "https://images.example.com/resize/300/banner.jpg" | grep X-Cache-Status
# → X-Cache-Status: MISS

# Второй запрос: ответ сохраняется в кэш
curl -sI "https://images.example.com/resize/300/banner.jpg" | grep X-Cache-Status
# → X-Cache-Status: MISS

# Третий запрос: обслуживается из кэша
curl -sI "https://images.example.com/resize/300/banner.jpg" | grep X-Cache-Status
# → X-Cache-Status: HIT
```

---

### Сценарий 4: Принудительная инвалидация через нативный Purge API

В Angie директива `proxy_cache_purge` встроена и позволяет удалять объекты как через HTTP-метод `PURGE` непосредственно по целевому URL, так и через служебный location.

```nginx
# Файл: /etc/angie/conf.d/image_purge.conf

server {
    listen 443 ssl http2;
    server_name images.example.com;

    # Inline-инвалидация: разрешена только доверенным административным сетям
    location ~* ^/resize/(?<req_width>\d+)/(?<image_path>.+)$ {
        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$req_width$image_path$img_target_format";

        # Включение метода PURGE для подсетей офиса/CI
        proxy_cache_purge PURGE from 127.0.0.1 192.168.10.0/24 10.50.0.0/16;

        proxy_pass http://unix:/var/run/angie_img_filter.sock:/process?w=$req_width&img=$image_path&fmt=$img_target_format;
    }
}
```

**Валидация:**
```bash
# Проверка наличия объекта в кэше
curl -sI -H "Accept: image/avif" "https://images.example.com/resize/400/photo.jpg" | grep X-Cache-Status
# → X-Cache-Status: HIT

# Отправка PURGE-запроса с указанием конкретного формата
curl -sI -X PURGE -H "Accept: image/avif" "https://images.example.com/resize/400/photo.jpg"
# → HTTP/1.1 204 No Content

# Проверка повторным GET-запросом: статус должен вернуться в MISS
curl -sI -H "Accept: image/avif" "https://images.example.com/resize/400/photo.jpg" | grep X-Cache-Status
# → X-Cache-Status: MISS
```

---

### Сценарий 5: Тонкая настройка процессов Cache Manager и Cache Loader для высоконагруженных дисков

При кэшах свыше 500 000 объектов стандартные параметры `cache manager` могут вызывать микрофризы дисковой подсистемы. Конфигурация балансирует I/O:

```nginx
# Файл: /etc/angie/conf.d/cache_manager_tuning.conf

http {
    proxy_cache_path /var/cache/angie/images
                     levels=1:2
                     keys_zone=img_cache:256m
                     file=/var/lib/angie/img_cache.zone
                     max_size=100g
                     inactive=168h
                     use_temp_path=off
                     manager_files=500
                     manager_sleep=100ms
                     manager_threshold=50ms
                     loader_files=1000
                     loader_sleep=50ms
                     loader_threshold=100ms;
}
```

**Параметры балансировки:**
- `manager_files=500` — проверка не более 500 файлов за одну итерацию очистки.
- `manager_sleep=100ms` — пауза в 100 мс между итерациями, снижающая утилизацию дисковой очереди.
- `manager_threshold=50ms` — максимальное время непрерывной работы процесса за одну итерацию.
- `loader_files=1000` / `loader_sleep=50ms` — щадящий режим первичного сканирования при холодном старте (актуален только при повреждении файла `.zone`).

**Валидация:**
```bash
# Проверка работы процесса в операционной системе
ps -eo pid,user,stat,pcpu,pmem,args | grep -E "angie: (cache manager|cache loader)"
# →  12345 angie    Ss   0.0  0.1 angie: cache manager process
```

---

### Сценарий 6: Системный тюнинг дисковой подсистемы и ОС под High Load Image Cache

Хранение миллионов мелких файлов требует специализированных параметров ядра Linux и файловой системы.

#### 1. Монтирование файловой системы (`/etc/fstab`)

Для хранилища кэша на базе XFS или ext4 обязательно отключение обновления метаданных доступа (`atime`):

```fstab
# /etc/fstab
UUID=e2b1b34c-6d91-4e78-9e12-87f54c5e6321 /var/cache/angie xfs noatime,nodiratime,logbufs=8,logbsize=256k,allocsize=64m 0 2
```

#### 2. Тюнинг systemd unit для Angie

```ini
# /etc/systemd/system/angie.service.d/override.conf
[Service]
LimitNOFILE=65536
LimitMEMLOCK=infinity
ReadWritePaths=/var/cache/angie /var/lib/angie /var/run/angie
TasksMax=infinity
```

#### 3. Настройка параметров ядра Linux (`/etc/sysctl.d/99-angie-cache.conf`)

```ini
# /etc/sysctl.d/99-angie-cache.conf
# Удержание dentry/inode кэша в оперативной памяти
vm.vfs_cache_pressure = 50

# Плавный сброс dirty pages на диск во избежание I/O-фризов
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# Увеличение очереди сокетов для Unix domain socket
net.core.somaxconn = 4096
fs.file-max = 2097152
```

**Валидация:**
```bash
# Применение параметров ядра и монтирования
sysctl --system
# → Applying /etc/sysctl.d/99-angie-cache.conf ...
# → vm.vfs_cache_pressure = 50
# → vm.dirty_background_ratio = 5
# → vm.dirty_ratio = 10
# → net.core.somaxconn = 4096

systemctl daemon-reload && systemctl restart angie
# → Проверка лимитов запущенного процесса Angie
cat /proc/$(pgrep -f "angie: master" | head -n1)/limits | grep "Max open files"
# → Max open files            65536                65536                files
```

---

### Сценарий 7: Наблюдаемость через нативный Status API и экспорт в Prometheus

Angie предоставляет встроенный REST API и модуль Prometheus для снятия метрик состояния зон кэша без внешних экспортеров.

```nginx
# Файл: /etc/angie/conf.d/observability.conf

server {
    listen 127.0.0.1:8080;

    # Нативный REST API Angie
    location /status/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }

    # Эндпоинт метрик Prometheus
    location /p8s {
        prometheus;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Валидация:**
```bash
# 1. Запрос метрик зоны через REST API
curl -s http://127.0.0.1:8080/status/http/caches/img_cache/ | jq '{size, max_size, hit, miss, stale, cold}'
# → {
# →   "size": 1548288000,
# →   "max_size": 53687091200,
# →   "hit": {"responses": 142050, "bytes": 4567890123},
# →   "miss": {"responses": 3200, "bytes": 102345678},
# →   "stale": {"responses": 15, "bytes": 450000},
# →   "cold": false
# → }

# 2. Проверка метрик Prometheus
curl -s http://127.0.0.1:8080/p8s | grep -E "^angie_http_cache" | head -n 8
# → angie_http_cache_size_bytes{cache="img_cache"} 1548288000
# → angie_http_cache_max_size_bytes{cache="img_cache"} 53687091200
# → angie_http_cache_responses_total{cache="img_cache",status="hit"} 142050
# → angie_http_cache_responses_total{cache="img_cache",status="miss"} 3200
# → angie_http_cache_responses_total{cache="img_cache",status="stale"} 15
```

---

## Операции и команды

Практический набор CLI-команд для мониторинга, обслуживания и траблшутинга кэша:

```bash
# 1. Проверка объема диска и расхода inode кэша
df -h /var/cache/angie/images
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sdb1        60G   15G   45G  25% /var/cache/angie

df -i /var/cache/angie/images
# → Filesystem       Inodes  IUsed   IFree IUse% Mounted on
# → /dev/sdb1      15728640 450200 15278440    3% /var/cache/angie

# 2. Проверка статуса фоновых процессов Angie
ps -eo pid,user,stat,args | grep -E "angie: (master|worker|cache manager|cache loader)"
# →  10101 root     Ss   angie: master process /usr/sbin/angie
# →  10102 angie    S    angie: worker process
# →  10103 angie    S    angie: cache manager process

# 3. Инспекция размера и времени модификации файла индекса Persistence
ls -lh /var/lib/angie/img_cache.zone
# → -rw-r----- 1 angie angie 128M Oct 14 11:45 /var/lib/angie/img_cache.zone

# 4. Проверка доступности внутреннего Unix-сокета фильтра
ss -xl | grep angie_img_filter
# → u_str LISTEN 0 511 /var/run/angie_img_filter.sock 123456 * 0

# 5. Тестирование отдачи формата и статуса кэша через curl
curl -sI -H "Accept: image/avif" "https://images.example.com/resize/400/catalog/photo.jpg" | grep -iE "x-cache-status|content-type|vary"
# → content-type: image/avif
# → vary: Accept
# → x-cache-status: HIT

# 6. Расчет текущего Hit Ratio зоны через Status API (однострочник bash)
curl -s http://127.0.0.1:8080/status/http/caches/img_cache/ | jq '
  (.hit.responses / (.hit.responses + .miss.responses + .bypass.responses + 0.0001) * 100) as $ratio |
  {hit_ratio_percent: $ratio, size_mb: (.size / 1024 / 1024)}'
# → {
# →   "hit_ratio_percent": 97.79,
# →   "size_mb": 1476.56
# → }
```

### Скрипт пакетной инвалидации вариаций изображения

Встроенный `proxy_cache_purge` очищает объект по точному совпадению ключа. Для инвалидации всех производных форматов (AVIF, WebP, JPEG) и типовых разрешений одного оригинала используется административный скрипт:

```bash
#!/usr/bin/env bash
# /usr/local/bin/purge_image_variants.sh
set -euo pipefail

IMAGE_PATH="${1:?Укажите относительный путь к изображению, например: catalog/item10.jpg}"
BASE_URL="https://127.0.0.1/resize"
RESOLUTIONS=("200" "400" "800" "1200")
FORMATS=("image/avif" "image/webp" "image/jpeg")

echo "[*] Инвалидация вариаций для: ${IMAGE_PATH}"

for res in "${RESOLUTIONS[@]}"; do
    for fmt in "${FORMATS[@]}"; do
        status=$(curl -k -s -o /dev/null -w "%{http_code}" -X PURGE \
            -H "Host: images.example.com" \
            -H "Accept: ${fmt}" \
            "${BASE_URL}/${res}/${IMAGE_PATH}")
        echo "  - Размер: ${res}px | Формат: ${fmt} → HTTP ${status}"
    done
done
echo "[+] Инвалидация завершена."
```

---

## Устранение неисправностей

### Диагностический алгоритм администратора

```
Проблема с кэшем изображений
 ├─ Кэш всегда MISS?
 │   ├─ Проверьте заголовок ответа бэкенда: нет ли Set-Cookie или Cache-Control: no-cache/private
 │   ├─ Проверьте proxy_cache_valid для полученного кода ответа (200, 404)
 │   └─ Проверьте права пользователя angie на директорию /var/cache/angie/images
 ├─ Браузер получает битое изображение (Cache Poisoning)?
 │   ├─ Проверьте proxy_cache_key: включен ли $img_target_format ($http_accept)
 │   └─ Проверьте наличие заголовка add_header Vary "Accept" always;
 ├─ Ошибки 504 Gateway Timeout при пике нагрузки?
 │   ├─ Включена ли директива proxy_cache_lock on;?
 │   └─ Достаточен ли image_filter_buffer на внутреннем сервере?
 └─ Сервер зависает / дисковый шторм при reload/restart?
     ├─ Настроен ли параметр file= в keys_zone?
     └─ Проверьте права и целостность /var/lib/angie/img_cache.zone
```

### Сводная таблица неисправностей

| Симптом | Причина | Команда диагностики | Решение |
|:---|:---|:---|:---|
| **Всегда `MISS`**, кэш на диске не растет | Бэкенд отдает `Set-Cookie`, `Expires: 0` или `Cache-Control: private/no-cache` | `curl -sI http://unix:/var/run/angie_img_filter.sock:/process?...` | Добавить `proxy_ignore_headers Cache-Control Set-Cookie;` и `proxy_hide_header Set-Cookie;` на фронтенде |
| **Клиент без AVIF получает битый файл** | Отравление кэша (Cache Poisoning): ключ кэша не учитывает `Accept`, нет `Vary` | `curl -sI -H "Accept: */*" https://images.example.com/resize/...` | Включить формат в `proxy_cache_key` и добавить директиву `add_header Vary "Accept" always;` |
| **504 Gateway Timeout** при всплеске трафика на новое фото | Cache Stampede: десятки воркеров одновременно запустили `image_filter` | `grep "upstream timed out" /var/log/angie/error.log` | Включить `proxy_cache_lock on;`, настроить `proxy_cache_use_stale updating;` |
| **Долгий запуск Angie / высокий `%iowait`** | Отсутствует сохранение индекса; `cache loader` сканирует миллионы файлов | `top -b -n 1 \| grep -E "(loader\|iowait)"` | Добавить параметр `file=/var/lib/angie/img_cache.zone` в `proxy_cache_path` |
| **Диск переполнен (100% Use)** | Параметр `max_size` не задан или процесс `cache manager` захлебнулся | `df -h /var/cache/angie/images` | Задать `max_size`, уменьшить `manager_sleep`, выполнить чистку по `atime` |
| **`No space left on device` при наличии свободного места** | Исчерпаны `inodes` из-за миллионов мелких файлов кэша | `df -i /var/cache/angie/images` | Переформатировать раздел с увеличенным числом инодов (`mkfs.ext4 -i 4096`) или перейти на XFS |
| **Ошибка 415 Unsupported Media Type** | Исходный файл превышает буфер декомпрессии `image_filter_buffer` | `grep "image_filter: too big image" /var/log/angie/error.log` | Увеличить `image_filter_buffer` до 25M–30M во внутреннем блоке `server` |
| **Ошибка 403 Forbidden при вызове PURGE** | IP-адрес клиента не входит в список доверенных сетей директивы `proxy_cache_purge` | `grep "access forbidden by rule" /var/log/angie/error.log` | Добавить IP источника в директиву `proxy_cache_purge PURGE from ...;` |
| **Ошибки `open() failed (2: No such file)` в `error.log`** | Ручное удаление файлов с диска через `rm -rf` на работающем сервисе | `grep "open() failed (2: No such file" /var/log/angie/error.log` | Не удалять файлы на горячую; останавливать Angie перед полной очисткой либо удалять `.zone` |
| **Предупреждение `corrupted cache file` при старте** | Аварийная остановка сервера повредила файл `.zone` Persistence | `grep "corrupted" /var/log/angie/error.log` | Удалить поврежденный `.zone` (`rm -f /var/lib/angie/img_cache.zone`), Angie выполнит штатный loader |

---

## Лучшие практики

### 1. Архитектура и изоляция контуров

- **Откажитесь от TCP loopback:** Для взаимодействия фронтенда и внутреннего сервера фильтрации используйте исключительно Unix domain socket (`/var/run/angie_img_filter.sock`). Это устраняет накладные расходы TCP-стека и риск исчерпания эфемерных портов.
- **Изолируйте обработчик директивой `internal`:** Внутренние location генерации изображений должны быть закрыты директивой `internal`, предотвращающей прямой доступ извне.

### 2. Управление ключом кэша и заголовками

- **Всегда передавайте `Vary: Accept`:** Любая схема адаптивной отдачи форматов (AVIF, WebP, JPEG) по одному URL обязана возвращать `Vary: Accept` для корректной маршрутизации в браузерах и CDN.
- **Нормализуйте аргументы ресайза:** Не используйте «сырую» строку `$args` в ключе, если клиенты могут передавать параметры в произвольном порядке (`?w=300&h=200` и `?h=200&w=300`). Применяйте именованные регулярные выражения в URL пути (`/resize/<w>/<h>/<file>`).

### 3. Оптимизация дисковой подсистемы

- **Выделенный физический диск:** Не размещайте директорию кэша (`/var/cache/angie`) на системном диске или на одном разделе с оригиналами. Заполнение кэша не должно приводить к отказу ОС.
- **Опции монтирования:** Файловая система кэша обязана монтироваться с `noatime,nodiratime`. Обновление времени доступа на каждом HIT-запросе превращает операцию чтения в тяжелую операцию записи метаданных.
- **Предпочтение XFS:** Файловая система XFS значительно лучше справляется с динамическим выделением инодов при миллионах файлов по сравнению с ext4.

### 4. Защита от деградации под нагрузкой

- **Связка `proxy_cache_lock` + `use_stale updating` + `background_update`:** Данная комбинация гарантирует, что ни один всплеск запросов не перегрузит CPU генерацией графики, а клиенты не столкнутся с задержками при истечении TTL.
- **Негативное кэширование:** Всегда настраивайте `proxy_cache_valid 404 415 5m;`. Отсутствующие или поврежденные картинки не должны приводить к постоянным повторным попыткам трансформации на каждый запрос.

### 5. Регламент планового обслуживания и процедура отката

#### Безопасная очистка всего кэша (Полный сброс)
Никогда не выполняйте `rm -rf /var/cache/angie/images/*` на работающем Angie под нагрузкой! Это приведет к лавине ошибок `open() failed` для всех запросов, ключи которых остались в RAM.

```bash
# Регламент полной очистки:
# 1. Остановка Angie (прекращение обращений к диску)
systemctl stop angie

# 2. Удаление файлов кэша и индекса
rm -rf /var/cache/angie/images/*
rm -f /var/lib/angie/img_cache.zone

# 3. Восстановление директории с правильными правами
mkdir -p /var/cache/angie/images
chown -R angie:angie /var/cache/angie/images
chmod 750 /var/cache/angie/images

# 4. Запуск Angie
systemctl start angie
```

#### Процедура отката конфигурации

```bash
# 1. Создание резервной копии перед изменениями
cp /etc/angie/conf.d/image_pipeline.conf /etc/angie/conf.d/image_pipeline.conf.bak

# 2. При сбое: восстановление резервной копии
cp /etc/angie/conf.d/image_pipeline.conf.bak /etc/angie/conf.d/image_pipeline.conf

# 3. Тест и безопасная перезагрузка конфигурации без сброса кэша
angie -t && systemctl reload angie
```

---

## Дополнительная информация

### Математический расчет памяти под keys_zone

Каждый кэшированный объект регистрируется в разделяемой памяти в виде структуры метаданных (красно-черное дерево поиска, элемент очереди LRU, 16-байтный MD5-хэш ключа, счетчики обращений, указатели на дисковый файл).
На современной **64-битной архитектуре** Linux один узел кэша занимает **128 байт**.

**Формула расчета объема RAM:**
$$\text{Размер зоны (байт)} = \text{Планируемое количество объектов} \times 128 \times 1.25 \text{ (запас 25\%)}$$

**Практические расчеты:**
- **500 000 объектов:** $500\,000 \times 128 \approx 64 \text{ МБ}$ (рекомендуется `keys_zone=img_cache:80m`)
- **2 000 000 объектов:** $2\,000\,000 \times 128 \approx 256 \text{ МБ}$ (рекомендуется `keys_zone=img_cache:300m`)
- **10 000 000 объектов:** $10\,000\,000 \times 128 \approx 1280 \text{ МБ}$ (рекомендуется `keys_zone=img_cache:1500m`)

При исчерпании памяти `keys_zone` процесс Angie не падает по OOM — активируется принудительное вытеснение старых метаданных по алгоритму LRU, что снижает Hit Ratio.

### Внутреннее устройство Persistence (`file=`)

1. **Формат дампа:** Файл дампа (`/var/lib/angie/img_cache.zone`) содержит сигнатуру Angie, версию формата, метаданные структуры `ngx_http_file_cache_t` и сериализованные узлы дерева.
2. **Атомарность записи:** При плановом завершении Angie выполняет запись во временный файл (`img_cache.zone.tmp`) и производит атомарный `rename()`, гарантируя целостность дампа даже при сбое питания во время записи.
3. **Безопасность памяти:** Если размер зоны `keys_zone` в конфигурации был изменен (например, с `128m` на `256m`), Angie распознает несоответствие размера при старте, отклонит устаревший файл `.zone` и выполнит фоновую переиндексацию.

### Пороговые значения мониторинга для SRE / Alerting

| Метрика | Целевое значение | Warning | Critical | Реакция дежурного инженера |
|:---|:---|:---|:---|:---|
| **Hit Ratio** | > 95% | < 90% | < 80% | Проверить ключ кэша на отравление, проверить время `inactive` |
| **Bypass Rate** | < 0.5% | > 2% | > 5% | Выявить источник запросов с `Cache-Control: no-cache` или проверить WAF |
| **Stale Ratio** | < 2% | > 5% | > 15% | Проверить здоровье внутреннего сервиса `image_filter` и latency хранилища |
| **Дисковая емкость** | < 75% | > 85% | > 92% | Проверить активность `cache manager`, увеличить диск или уменьшить `max_size` |
| **Расход Inodes** | < 60% | > 80% | > 90% | Запланировать миграцию на XFS или чистку устаревших файлов |
| **MISS Latency P95**| < 300 мс | > 800 мс | > 2000 мс | Оптимизировать `image_filter_avif_speed`, проверить загрузку CPU |

### Ограничения и граничные условия

- **Точность PURGE:** Встроенный механизм `proxy_cache_purge` в Angie работает по точному строковому совпадению ключа. Инвалидация по wildcard (`/resize/*`) на уровне ядра не поддерживается — для группового сброса требуется скриптовая автоматизация перебора форматов или версионирование URL (`?v=N`).
- **Синхронизация буферов:** Значение `image_filter_buffer` выделяется из кучи рабочего процесса на каждую трансформацию. При пике одновременных MISS суммарное потребление памяти воркерами может достигать `worker_processes * image_filter_buffer * 2` (с учетом внутренних структур `libgd`).
- **Фрагментация диска:** При интенсивной ротации мелких файлов (AVIF/WebP размером 10–60 КБ) файловая система фрагментируется. На XFS проблема минимизируется параметром `allocsize=64m`.

---

### См. также

- **[Обзор возможностей image_filter](./overview.md)** — архитектура модуля и поддерживаемые форматы.
- **[Конфигурация внутреннего сервера image_filter](./filter_configuration.md)** — тонкая настройка буферов и кодеков.
- **[Конфигурация фронтенда для image_filter](./site_configuration.md)** — маппинг заголовков и управление SSL.
- **[Динамический ресайз и кадрирование](./resize.md)** — параметры геометрических трансформаций.
- **[Производительность и масштабирование](./performance.md)** — бенчмарки и профилирование воркеров.
- **[Безопасность и защита от DoS в image_filter](./security.md)** — валидация входных размеров и rate limiting.
- **[Установка и сборка модуля image_filter](./installation.md)** — сборка с библиотеками libgd и кодеками.
- **[Мониторинг Angie через Status API](../../angie_monitoring/angie_monitoring_api.md)** — детальное руководство по метрикам и API.
- **[Серверное кэширование (Proxy Cache) в Nginx и Angie](../../../Nginx/Performance/Caching/proxy_caching.md)** — базовые принципы и SSoT архитектуры прокси-кэша.
