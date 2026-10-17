# Серверное кэширование (Proxy Cache) в Nginx и Angie

**Актуально для:** Nginx 1.30.x (Stable) / 1.31.x (Mainline), Angie 1.10+ / 1.12.x

---

## Определения

**Серверное кэширование (Proxy Cache)** — подсистема обратного HTTP-проксирования веб-сервера Nginx и Angie (модуль `ngx_http_proxy_module`), обеспечивающая временное сохранение ответов вышестоящих серверов (бэкендов) в локальном многоуровневом хранилище хоста. Позволяет обслуживать повторные запросы клиентов напрямую с прокси-сервера без обращения к приложениям и СУБД, снижая сетевую задержку (TTFB), защищая бэкенды от деградации и оптимизируя пропускную способность сетевого интерфейса.

**Кэш-зона (`keys_zone`)** — именованная область разделяемой памяти (shared memory), аллоцируемая ядром ОС и доступная всем рабочим процессам (worker processes) веб-сервера. Содержит бинарный индекс метаданных кэша: красно-черное дерево (Red-Black Tree) для быстрого поиска ключей по 128-битному MD5-хэшу и двухсвязный список LRU (Least Recently Used) для ротации объектов. 1 МБ разделяемой памяти вмещает приблизительно 8 000 уникальных ключей кэшированных объектов.

**Кэш-индекс (Cache Index)** — структура метаданных в оперативной памяти (`keys_zone`), хранящая хэши ключей кэша, таймстампы создания и истечения TTL, счетчики обращений и служебные флаги. Позволяет веб-серверу мгновенно проверять наличие и валидность кэша в оперативной памяти без выполнения системных вызовов к файловой системе (`stat()`, `open()`).

**Кэш-загрузчик (Cache Loader)** — специализированный служебный процесс веб-сервера, запускаемый один раз при старте сервиса. Выполняет рекурсивное сканирование каталогов на диске для восстановления индекса метаданных в `keys_zone`. На хранилищах с миллионами файлов может создавать всплеск дисковых операций ввода-вывода (IOPS).

**Кэш-менеджер (Cache Manager)** — периодический фоновый процесс веб-сервера, пробуждающийся с заданным интервалом для контроля дискового пространства кэша. Если суммарный объем данных превышает `max_size`, процесс удаляет наименее востребованные файлы по алгоритму LRU, а также вычищает файлы, время с момента последнего обращения к которым превысило параметр `inactive`.

**Ключ кэширования (`proxy_cache_key`)** — строковый шаблон, формируемый из переменных запроса (метод, схема, хост, URI, аргументы, заголовки). Хэшируется веб-сервером алгоритмом MD5 в 128-битный хэш (32 шестнадцатеричных символа), служащий уникальным идентификатором объекта в оперативной памяти и именем файла на диске.

**Условная ревалидация (Cache Revalidation)** — процедура проверки актуальности устаревшего объекта в кэше (`proxy_cache_revalidate on;`). Веб-сервер отправляет бэкенду условный HTTP-запрос с заголовками `If-Modified-Since` и `If-None-Match`. Если бэкенд возвращает статус `304 Not Modified`, Nginx обновляет TTL метаданных в оперативной памяти без повторной передачи тела ответа по сети.

**Фоновое обновление (Background Update & SWR)** — режим работы кэша (`proxy_cache_background_update on;`), реализующий концепцию Stale-While-Revalidate (RFC 5861). При истечении TTL текущему клиенту немедленно отдается устаревшая копия данных (`STALE` / `UPDATING`), пока веб-сервер в отдельном асинхронном подзапросе обновляет кэш от бэкенда.

**Блокировка кэша (`proxy_cache_lock`)** — механизм синхронизации параллельных запросов при промахе (`MISS`) или обновлении (`EXPIRED`). Разрешает отправку к бэкенду только одного запроса на генерацию контента, удерживая остальные параллельные запросы в очереди ожидания готового кэша.

**Слайсинг файлов (`ngx_http_slice_module`)** — модуль разбиения больших файлов на независимые диапазоны (ranges) фиксированного размера, каждый из которых кэшируется как отдельный объект на диске. Позволяет клиентам скачивать тяжелый контент параллельно и начинать воспроизведение видеофайлов без ожидания полной загрузки объекта в кэш.

**Инвалидация кэша (Cache Purge)** — принудительное удаление объекта из оперативной памяти и файловой системы по совпадению ключа до истечения регламентного TTL.

**Cache Stampede (Thundering Herd / «Стадо бизонов»)** — критическая системная перегрузка бэкенда, возникающая при одновременном обращении сотен или тысяч клиентов к популярному ресурсу в момент истечения его TTL или после холодного сброса кэша.

**Отравление кэша (Cache Poisoning)** — архитектурная ошибка конфигурации, при которой персонализированные данные (сессионные cookies, токены авторизации), ответы с ошибками или ответы без учета заголовков согласования контента (`Vary`) сохраняются в общий кэш и отдаются другим пользователям.

Общий концептуальный обзор всех типов кэширования доступен в [Обзоре кэширования в Nginx и Angie](./overview.md).

---

## Архитектура и принципы работы

### Двухуровневая модель хранения

Архитектура Proxy Cache в Nginx и Angie строго разделена на два физических уровня:

1. **Индекс метаданных в разделяемой памяти (RAM / `keys_zone`):**
   - Размещается в разделяемой памяти ОС (`shared memory`), совместно используемой всеми рабочими процессами веб-сервера.
   - Организован в виде красно-черного дерева (Red-Black Tree) для быстрого поиска узлов по MD5-хэшу ключа за время $O(\log N)$.
   - Содержит двухсвязный список LRU (Least Recently Used) для вытеснения устаревших данных при достижении лимита памяти или диска.
   - Содержит только метаданные: 128-битный хэш, размер тела, таймстампы (`valid_sec`, `last_modified`, `access_sec`), счетчики обращений и файловый дескриптор.
   - 1 МБ памяти вмещает ~8 000 ключей (при зоне в 64 МБ индексируется до 512 000 объектов).

2. **Хранилище полезной нагрузки на файловой системе (Disk / Page Cache):**
   - Тела ответов и служебные заголовки бэкенда сохраняются в виде бинарных файлов в каталоге, заданном в `proxy_cache_path`.
   - Имя файла на диске соответствует 32-символьному MD5-хэшу ключа кэша.
   - Ядро Linux автоматически кэширует читаемые файлы в системном Page Cache. «Горячие» файлы кэша отдаются клиентам непосредственно из оперативной памяти ядра без физического обращения к блочному устройству ввода-вывода (Zero-Disk Read).

```
                      [ Клиентский запрос ]
                                │
                                ▼
                     [ Nginx Worker Process ]
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
[ Поиск в RAM: keys_zone ]                  [ Проверка bypass ]
(Red-Black Tree: MD5 хэш)                   (proxy_cache_bypass)
          │
    ┌─────┴──────────────┬────────────────────────────┐
    ▼                    ▼                            ▼
  [ HIT ]         [ EXPIRED / STALE ]              [ MISS ]
    │                    │                            │
    │             ┌──────┴──────┐                     │
    │             ▼             ▼                     │
    │        [ Revalidate ] [ Lock / Wait ]           │
    │             │             │                     │
    │             ▼             │                     │
    │        [ 304 Upstream ]   │                     │
    │             │             │                     │
    │ ┌───────────┘             ▼                     ▼
    ▼ ▼                 [ Фоновый запрос ]     [ Запрос к Upstream ]
[ Чтение из диска /     [ proxy_cache_bg ]     [ proxy_pass ]
  Page Cache RAM ]              │                     │
    │                           ▼                     ▼
    │                   [ Атомарный rename ]   [ Атомарный rename ]
    │                   [ Обновление в RAM ]   [ Добавление в RAM ]
    │                           │                     │
    └───────────────────────────┼─────────────────────┘
                                ▼
                       [ Ответ клиенту ]
```

### Физическая структура кэш-файла на диске

Файл кэша на диске создается в специальном внутреннем формате Nginx. Он состоит из трех последовательных сегментов:

1. **Бинарный служебный заголовок Nginx (`ngx_http_file_cache_header_t`):**
   - Служебные метаданные: размер заголовка, версия протокола, контрольная сумма CRC, код ответа HTTP (`200`, `301` и т.д.).
   - Таймстампы времени валидности (`valid_sec`), времени последнего обращения (`access_sec`), времени модификации ресурса на апстриме (`last_modified`).
   - Исходный строковый ключ кэширования (`KEY: <proxy_cache_key>`), используемый для валидации совпадения хэша.
2. **Заголовки HTTP-ответа апстрима:**
   - Сырой блок HTTP-заголовков, полученных от бэкенда (`Content-Type`, `ETag`, `Last-Modified`, `Cache-Control` и др.), завершающийся последовательностью `\r\n\r\n`.
3. **Тело HTTP-ответа (Payload):**
   - Бинарные данные ответа (JSON, HTML, бинарный поток, изображение).

### Алгоритм хэширования и раскладка уровней каталогов (`levels`)

Параметр `levels` директивы `proxy_cache_path` управляет распределением файлов по поддиректориям:

- Ключ кэша хэшируется в 32 шестнадцатеричных символа (MD5), например: `b7f54b2df7bb9c354794b150c265513a`.
- Параметр `levels=1:2` предписывает веб-серверу формировать двухуровневую иерархию поддиректорий, считывая символы **с конца MD5-хэша**:
  - Первый уровень (1 символ с конца): каталог `a`.
  - Второй уровень (следующие 2 символа с конца): каталог `13`.
  - Имя файла: полный 32-символьный хэш `b7f54b2df7bb9c354794b150c265513a`.
  - Итоговый путь: `/var/cache/nginx/proxy_cache/a/13/b7f54b2df7bb9c354794b150c265513a`.

Иерархия каталогов (`levels=1:2` или `levels=1:2:2`) критически необходима для Linux-файловых систем (ext4, XFS). Размещение сотен тысяч файлов в одном каталоге приводит к линейному росту времени поиска dentry ядра, деградации системных вызовов `open()` и исчерпанию буферов каталогов.

### Механизм атомарной записи и параметр `use_temp_path=off`

По умолчанию при получении ответа от бэкенда Nginx записывает поток во временный файл в каталоге `proxy_temp_path` (по умолчанию `/var/lib/nginx/proxy`), после чего переносит его в целевую директорию кэша вызовом ядра Linux `rename()`.

- **Проблема `use_temp_path=on`:** Если директория кэша `/var/cache/nginx/proxy_cache` и директория временных файлов `/var/lib/nginx/proxy` находятся на разных точках монтирования (например, кэш смонтирован на выделенный SSD/NVMe диск или в `tmpfs`), системный вызов ядра `rename()` завершается критической ошибкой `EXDEV (18: Invalid cross-device link)`. Воркер вынужден выполнять медленное поблочное копирование файла между файловыми системами через пользовательское пространство, что создает двойную нагрузку на CPU и дисковый ввод-вывод.
- **Инженерное решение `use_temp_path=off`:** Принуждает воркер создавать временные скрытые файлы (`.0000000001`) непосредственно внутри дерева каталогов целевой директории `proxy_cache_path`. По завершении записи файл мгновенно и атомарно переименовывается в финальное имя хэша в пределах одного и того же блочного устройства.

### Жизненный цикл объекта и иерархия управления TTL

Время жизни кэшированного объекта определяется строгой иерархией приоритетов:

1. **`X-Accel-Expires`:** Заголовок от бэкенда имеет наивысший приоритет.
   - `X-Accel-Expires: 0` — запрещает кэширование ответа.
   - `X-Accel-Expires: 3600` — устанавливает TTL в 3600 секунд.
   - `X-Accel-Expires: @1776412800` — фиксирует точное время истечения по Unix Timestamp.
2. **`Cache-Control`:** Обрабатывается при отсутствии `X-Accel-Expires`.
   - Директивы `s-maxage=N` (для разделяемых кэшей) или `max-age=N`.
   - Директивы `no-cache`, `no-store`, `private` запрещают сохранение ответа в кэш.
3. **`Expires`:** Устанавливает абсолютную дату истечения свежести (RFC 9111).
4. **`proxy_cache_valid`:** Директива веб-сервера. Применяется только в том случае, если бэкенд не передал управляющие заголовки, либо если заголовки бэкенда принудительно проигнорированы директивой `proxy_ignore_headers`.
5. **Параметр `inactive` в `proxy_cache_path`:** Устанавливает интервал времени (по умолчанию 10 минут), по истечении которого объект удаляется процессом `cache manager`, если к нему не было обращений, даже если его номинальный TTL еще не истек.

### Критическое требование: буферизация ответов

> [!IMPORTANT]
> Механизм Proxy Cache функционально зависит от модуля буферизации `ngx_http_proxy_module`. Директива `proxy_buffering` должна быть включена (`proxy_buffering on;`, значение по умолчанию). Если в конфигурации глобально или внутри location задано `proxy_buffering off;`, серверное кэширование полностью отключается, а переменная `$upstream_cache_status` остается пустой.

Подробная архитектура буферизации описана в [Буферизации и стриминге в Nginx](../../Proxy/nginx_buffering_and_streaming.md).

### Разделение логики обхода и запрета сохранения

В Nginx и Angie предусмотрено разделение логики работы с кэшем на этапе чтения и на этапе записи:

| Директива | На каком этапе работает | Поведение при значении `!= 0` и `!= ""` | Статус кэша |
| :--- | :--- | :--- | :--- |
| **`proxy_cache_bypass`** | **Чтение** (до обращения к кэшу) | Воркер не ищет объект в `keys_zone`, а сразу отправляет запрос к бэкенду. Полученный ответ бэкенда **может** быть сохранен в кэш (если не запрещен `proxy_no_cache`). | `BYPASS` |
| **`proxy_no_cache`** | **Запись** (после получения ответа) | Воркер запрашивает кэш или бэкенд в обычном режиме, но полученный ответ от бэкенда **не сохраняется** на диск в кэш. | `MISS` / `EXPIRED` |

---

## Практические сценарии

### Шаг 1: Подготовка файловой системы и глобальная инициализация кэша

Для обеспечения максимальной производительности дисковый кэш размещается на отдельном блочном устройстве (SSD/NVMe) с оптимизированными параметрами монтирования.

Создание каталога и назначение прав:

```bash
mkdir -p /var/cache/nginx/proxy_cache
chown -R nginx:nginx /var/cache/nginx/proxy_cache
chmod 700 /var/cache/nginx/proxy_cache
# → Проверка прав доступа: drwx------ nginx nginx
```

Рекомендуемые параметры монтирования в `/etc/fstab` (отключение обновления atime снижает нагрузку на дисковый I/O):

```
UUID=xxxx-xxxx-xxxx  /var/cache/nginx/proxy_cache  ext4  noatime,nodiratime,data=ordered  0  2
```

Глобальная конфигурация в контексте `http` файла `/etc/nginx/nginx.conf`:

```nginx
http {
    include       mime.types;
    default_type  application/octet-stream;

    # Зона кэширования для API и динамического контента
    proxy_cache_path /var/cache/nginx/proxy_cache
                      levels=1:2
                      keys_zone=api_cache:64m
                      inactive=12h
                      max_size=20g
                      min_free=2g
                      manager_files=100
                      manager_sleep=50ms
                      manager_threshold=200ms
                      loader_files=50
                      loader_sleep=50ms
                      loader_threshold=50ms
                      use_temp_path=off;
}
```

Проверка синтаксиса конфигурации:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

Применение конфигурации без прерывания активных клиентских соединений:

```bash
nginx -s reload
# → Graceful reload выполнен успешно
```

Параметры директивы `proxy_cache_path`:
* `levels=1:2`: двухъярусная иерархия подкаталогов (предотвращает деградацию ext4/XFS при миллионах файлов).
* `keys_zone=api_cache:64m`: 64 МБ оперативной памяти для хранения ~512 000 ключей в Red-Black Tree.
* `inactive=12h`: удаление объектов, к которым не обращались более 12 часов.
* `max_size=20g`: жесткий предел дискового пространства; при превышении `cache manager` вытесняет файлы по алгоритму LRU.
* `min_free=2g`: защита от переполнения диска: кэш не расширяется, если на файловой системе остается менее 2 ГБ свободного места.
* `manager_files`, `manager_sleep`, `manager_threshold`: тюнинг нагрузки Cache Manager на CPU/IOPS при очистке.
* `loader_files`, `loader_sleep`, `loader_threshold`: плавный старт Cache Loader для предотвращения лавины IOPS.
* `use_temp_path=off`: прямая запись временных файлов в целевой каталог кэша без межсегментного `rename()`.

### Шаг 2: Производственное кэширование динамического API с защитой от Stampede

Сценарий реализует отказоустойчивое кэширование ответов бэкенда с условной ревалидацией, фоновым обновлением и защитой от перегрузки апстримов при пиковом трафике.

```nginx
upstream backend_api {
    server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    server_name api.example.internal;

    location /v1/catalog/ {
        proxy_pass http://backend_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Активация кэш-зоны и формирование ключа
        proxy_cache api_cache;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_methods GET HEAD;
        proxy_cache_convert_head on;
        proxy_cache_min_uses 1;

        # Регламентные времена жизни по кодам ответа
        proxy_cache_valid 200 301 302 15m;
        proxy_cache_valid 404         1m;
        proxy_cache_valid 500 502 503 10s;

        # Защита от Cache Stampede («стада бизонов»)
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 5s;

        # Фоновое обновление (Stale-While-Revalidate)
        proxy_cache_use_stale error timeout invalid_header updating
                              http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;

        # Условная ревалидация через If-Modified-Since и If-None-Match
        proxy_cache_revalidate on;

        # Отладочный заголовок для проверки статуса кэша
        add_header X-Cache-Status $upstream_cache_status always;
        add_header X-Cache-Key "$scheme$request_method$host$request_uri" always;
    }
}
```

Проверка поведения через `curl`:

```bash
# Первый запрос: промах кэша
curl -I http://api.example.internal/v1/catalog/items
# → HTTP/1.1 200 OK
# → X-Cache-Status: MISS

# Второй запрос: мгновенная отдача из кэша
curl -I http://api.example.internal/v1/catalog/items
# → HTTP/1.1 200 OK
# → X-Cache-Status: HIT
```

### Шаг 3: Дифференцированный обход кэша для авторизованных пользователей

В веб-приложениях публичный контент должен кэшироваться, но пользователи с авторизационными cookies (`session_id`) или заголовками `Authorization` должны получать персональные некэшированные ответы.

Конфигурация с использованием модуля `map` в контексте `http`:

```nginx
http {
    # Определение флага обхода кэша на основе входящего запроса
    map $http_authorization $skip_cache_auth {
        default 1;
        ""      0;
    }

    map $cookie_session_id $skip_cache_cookie {
        default 1;
        ""      0;
    }

    # Результирующий флаг пропуска кэша
    map "$skip_cache_auth:$skip_cache_cookie" $bypass_cache {
        "0:0"   0;
        default 1;
    }

    server {
        listen 80;
        server_name shop.example.internal;

        location /products/ {
            proxy_pass http://backend_api;

            proxy_cache api_cache;
            proxy_cache_key "$scheme$request_method$host$request_uri";

            # Обход кэша при чтении и запрет записи персонального ответа
            proxy_cache_bypass $bypass_cache;
            proxy_no_cache     $bypass_cache;

            # Игнорирование служебных заголовков бэкенда для публичных запросов
            proxy_ignore_headers Set-Cookie;
            proxy_hide_header    Set-Cookie;

            proxy_cache_valid 200 30m;
            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

Проверка дифференцированного обхода:

```bash
# Анонимный запрос (кэшируется)
curl -I http://shop.example.internal/products/100
# → X-Cache-Status: HIT

# Запрос с сессионной кукой (кэш обходится)
curl -I -b "session_id=user_secret_token" http://shop.example.internal/products/100
# → X-Cache-Status: BYPASS
```

### Шаг 4: Слайсинг тяжелого контента и медиафайлов (`ngx_http_slice_module`)

При отдаче тяжелых файлов (видео, ISO-образы, бинарные архивы) стандартное проксирование требует полной загрузки файла в кэш до начала обработки Range-запросов. Модуль `ngx_http_slice_module` разбивает файл на сегменты фиксированного размера, которые кэшируются независимо.

```nginx
# Отдельная зона для тяжелого контента
proxy_cache_path /var/cache/nginx/media_cache
                  levels=1:2
                  keys_zone=media_cache:32m
                  inactive=7d
                  max_size=100g
                  use_temp_path=off;

server {
    listen 80;
    server_name media.example.internal;

    location /videos/ {
        proxy_pass http://backend_storage;

        # Активация модуля slice с размером диапазона 10 МБ
        slice             10m;
        proxy_cache       media_cache;

        # Ключ кэша ОБЯЗАТЕЛЬНО должен включать переменную $slice_range!
        proxy_cache_key   "$uri$is_args$args$slice_range";

        # Передача диапазона бэкенду
        proxy_set_header  Range $slice_range;
        proxy_http_version 1.1;

        # Кэширование кодов 200 (полный файл) и 206 (Partial Content)
        proxy_cache_valid 200 206 7d;

        # Асинхронная отдача через потоки Linux AIO
        aio threads=default;
        directio 10m;

        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

Проверка частичного скачивания диапазона:

```bash
curl -I -r 0-1048575 http://media.example.internal/videos/demo.mp4
# → HTTP/1.1 206 Partial Content
# → Content-Range: bytes 0-1048575/52428800
# → X-Cache-Status: HIT
```

### Шаг 5: Инвалидация и очистка кэша (Cache Purge)

#### Вариант А: Нативная инвалидация в Angie

Angie содержит встроенную поддержку модуля `angie-module-cache-purge`:

```nginx
# Angie configuration
location / {
    proxy_pass http://backend_api;
    proxy_cache api_cache;
    proxy_cache_key "$scheme$request_method$host$request_uri";

    # Разрешение метода PURGE только с локального хоста и подсети мониторинга
    proxy_cache_purge PURGE from 127.0.0.1 10.0.0.0/8;
}
```

Инвалидация через CLI:

```bash
# Удаление конкретного URI
curl -X PURGE http://127.0.0.1/v1/catalog/items
# → HTTP/1.1 200 OK (Resource purged)

# Удаление по маске (Wildcard Purge в Angie)
curl -X PURGE "http://127.0.0.1/v1/catalog/*"
# → HTTP/1.1 200 OK
```

#### Вариант Б: Инвалидация в Nginx OSS (вычисление MD5 пути)

В Nginx OSS без сторонних модулей точечное удаление объекта осуществляется вычислением MD5-хэша ключа кэша и удалением соответствующего файла с диска:

Скрипт точечной инвалидации `/usr/local/bin/nginx-cache-purge.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

CACHE_DIR="/var/cache/nginx/proxy_cache"
KEY="${1:-}"

if [[ -z "$KEY" ]]; then
    echo "Использование: $0 '<proxy_cache_key>'"
    echo "Пример: $0 'httpGETapi.example.internal/v1/catalog/items'"
    exit 1
fi

MD5_HASH=$(echo -n "$KEY" | md5sum | awk '{print $1}')
LEVEL1="${MD5_HASH: -1}"
LEVEL2="${MD5_HASH: -3:2}"
TARGET_FILE="${CACHE_DIR}/${LEVEL1}/${LEVEL2}/${MD5_HASH}"

if [[ -f "$TARGET_FILE" ]]; then
    rm -f "$TARGET_FILE"
    echo "Успешно удален файл кэша: $TARGET_FILE (MD5: $MD5_HASH)"
else
    echo "Объект не найден в кэше: $TARGET_FILE"
    exit 2
fi
```

Тестирование скрипта:

```bash
chmod +x /usr/local/bin/nginx-cache-purge.sh
/usr/local/bin/nginx-cache-purge.sh "httpGETapi.example.internal/v1/catalog/items"
# → Успешно удален файл кэша: /var/cache/nginx/proxy_cache/a/13/b7f54b2df7bb9c354794b150c265513a (MD5: b7f54b2df7bb9c354794b150c265513a)
```

### Шаг 6: Персистентность индекса при рестартах

#### Angie: параметр `file=` в `proxy_cache_path`

При перезапусках веб-сервера процесс `cache loader` в стандартном Nginx выполняет холодное сканирование всего дискового массива, создавая пиковую нагрузку на IOPS, в то время как Hit Ratio падает до 0%. В Angie параметр `file=` сохраняет снимок `keys_zone` в файл при выключении и мгновенно восстанавливает его при старте:

```nginx
# Angie 1.9+
proxy_cache_path /var/cache/angie/proxy_cache
                  levels=1:2
                  keys_zone=api_cache:64m
                  inactive=24h
                  max_size=20g
                  file=/var/lib/angie/api_cache.zone
                  use_temp_path=off;
```

#### Nginx OSS: сглаживание нагрузки Cache Loader

В Nginx OSS без персистентности всплеск дискового чтения сглаживается директивами плавного наполнения:

```nginx
proxy_cache_path /var/cache/nginx/proxy_cache
                  levels=1:2
                  keys_zone=api_cache:64m
                  loader_files=50       # загружать не более 50 файлов за итерацию
                  loader_sleep=50ms     # пауза 50 мс между итерациями
                  loader_threshold=50ms # прерывать итерацию, если она длится дольше 50 мс
                  use_temp_path=off;
```

### Шаг 7: Расширенное SRE-логирование в JSON со статусом кэша

Для агрегации метрик в локальные хранилища и SIEM-системы настраивается машиночитаемый журнал доступа с телеметрией кэширования:

```nginx
log_format json_cache escape=json '{'
    '"timestamp":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"request_method":"$request_method",'
    '"request_uri":"$request_uri",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time,'
    '"upstream_response_time":"$upstream_response_time",'
    '"upstream_cache_status":"$upstream_cache_status",'
    '"upstream_status":"$upstream_status",'
    '"upstream_addr":"$upstream_addr",'
    '"pipe":"$pipe"'
'}';

access_log /var/log/nginx/cache_access.json json_cache buffer=64k flush=5s;
```

---

## Операции и команды

| Инженерная задача | Команда / Метод | Ожидаемый результат / Системный эффект |
| :--- | :--- | :--- |
| Проверка синтаксиса конфигурации | `nginx -t` | `nginx: configuration file /etc/nginx/nginx.conf test is successful` |
| Zero-Downtime перезагрузка | `systemctl reload nginx` (или `nginx -s reload`) | Обновление конфигурации воркеров без сброса активных соединений |
| Расчет коэффициента попаданий (Hit Ratio) | `awk -F'"upstream_cache_status":"' '{print $2}' /var/log/nginx/cache_access.json \| awk -F'"' '{print $1}' \| sort \| uniq -c \| awk '{s+=$1; c[$2]=$1} END {printf "Hit Ratio: %.2f%%\n", ((c["HIT"]+c["REVALIDATED"])/s)*100}'` | `Hit Ratio: 87.42%` |
| Поиск файла кэша по строке ключа | `echo -n "httpGETapi.example.internal/v1/items" \| md5sum \| awk '{print $1}'` | Получение MD5-хэша: `4a8f9c...` для поиска в каталоге кэша |
| Инспекция служебного заголовка файла кэша | `head -n 10 /var/cache/nginx/proxy_cache/a/13/b7f54b2df7bb...` (или `strings -a -n 5 <path> \| head -n 15`) | Просмотр строки `KEY:`, заголовков бэкенда (`Content-Type`, `ETag`) |
| Аудит дискового пространства кэша | `df -h /var/cache/nginx/proxy_cache` | Объем занятого и свободного пространства накопителя |
| Аудит свободных файловых дескрипторов (Inodes) | `df -i /var/cache/nginx/proxy_cache` | Процент занятых инодов (`IUse% < 80%`) |
| Анализ дисковой задержки ввода-вывода (IOPS) | `iostat -xz 1 5` | Контроль `%util`, задержек `r_await`, `w_await` накопителя кэша |
| Проверка активности фонового Cache Loader | `ps aux \| grep -E 'nginx: (cache manager\|cache loader)'` | Наличие процессов управления кэшем в списке процессов |
| Полная очистка дискового кэша (холодный сброс) | `find /var/cache/nginx/proxy_cache -type f -delete && systemctl reload nginx` | Удаление всех файлов без изменения структуры каталогов |
| Принудительная инвалидация объекта через HTTP | `curl -X PURGE -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/v1/catalog/items` | `200` (успешный сброс) или `404` (объект не найден) |

---

## Troubleshooting

### 1. Критическая ошибка `rename() failed (18: Invalid cross-device link)`

**Симптом:** В журнале `/var/log/nginx/error.log` фиксируются множественные ошибки:
```
[crit] 12345#12345: *1280 rename() "/var/lib/nginx/proxy/0/01/0000000100" to "/var/cache/nginx/proxy_cache/a/13/b7f54b2df7bb9c354794b150c265513a" failed (18: Invalid cross-device link)
```
Запросы обслуживаются со статусом `MISS`, дисковый кэш не наполняется.

**Причина:** Каталог временных файлов `proxy_temp_path` (`/var/lib/nginx/proxy`) и директория `proxy_cache_path` (`/var/cache/nginx/proxy_cache`) расположены на разных файловых системах или точках монтирования. Системный вызов ядра Linux `rename()` не поддерживает атомарный перенос файлов между разными блочными устройствами (`EXDEV`).

**Диагностика:**
```bash
# Проверка точек монтирования каталогов
df -T /var/lib/nginx/proxy /var/cache/nginx/proxy_cache
# → /var/lib/nginx/proxy      ext4  /dev/sda1 (root)
# → /var/cache/nginx/proxy_cache xfs  /dev/sdb1 (отдельный диск кэша)
```

**Решение:** Добавьте параметр `use_temp_path=off` в директиву `proxy_cache_path`. Это отключит промежуточную директорию и заставит Nginx создавать временные файлы непосредственно внутри файловой системы кэша:

```nginx
proxy_cache_path /var/cache/nginx/proxy_cache
                  levels=1:2
                  keys_zone=api_cache:64m
                  use_temp_path=off;
```

### 2. Кэширование не работает (`$upstream_cache_status` пуст или всегда MISS)

**Симптом:** Переменная `$upstream_cache_status` в логах пустая (`-`) или всегда отдает `MISS`, хотя запросы однотипные и должны кэшироваться.

**Причина 1:** Отключена буферизация прокси (`proxy_buffering off;`). Proxy Cache функционально не может работать без сохранения тела ответа в буфер.
**Причина 2:** Бэкенд отправляет заголовки `Cache-Control: private`, `no-cache`, `no-store` или `Set-Cookie`.

**Диагностика:**
```bash
# Проверка флага буферизации в конфиге
nginx -T | grep "proxy_buffering"

# Проверка заголовков ответа бэкенда
curl -I http://127.0.0.1:8080/v1/catalog/items
# → Cache-Control: no-cache, private
# → Set-Cookie: session_id=abc; path=/
```

**Решение:**
1. Убедитесь, что буферизация включена: `proxy_buffering on;`.
2. Если бэкенд не подлежит изменению, проигнорируйте блокирующие заголовки для публичной зоны:

```nginx
location /v1/catalog/ {
    proxy_pass http://backend_api;
    proxy_buffering on;
    proxy_cache api_cache;

    proxy_ignore_headers Cache-Control Expires Set-Cookie;
    proxy_hide_header    Set-Cookie;

    proxy_cache_valid 200 10m;
}
```

### 3. Исчерпание файловых дескрипторов (Inodes)

**Симптом:** При записи в кэш Nginx выдает ошибку `[crit] ... open() "/var/cache/nginx/.../..." failed (28: No space left on device)`. При этом команда `df -h` показывает, что на диске еще свободно 50% объема.

**Причина:** В кэше сохраняется огромное количество мелких объектов (файлы по 1–4 КБ). Объем дискового пространства не исчерпан, но закончились структуры метаданных файловой системы (inodes).

**Диагностика:**
```bash
df -i /var/cache/nginx/proxy_cache
# → Filesystem      Inodes   IUsed   IFree IUse% Mounted on
# → /dev/sdb1      1310720 1310720       0  100% /var/cache/nginx/proxy_cache
```

**Решение:**
1. Очистите невостребованный кэш и сократите параметр `inactive` (например, с `24h` до `2h`).
2. При форматировании диска кэша под ext4 задайте меньший размер `bytes-per-inode` (`mkfs.ext4 -i 4096 /dev/sdb1`), либо используйте файловую систему XFS с динамическим выделением инодов (`mkfs.xfs -m crc=1 /dev/sdb1`).

### 4. Всплеск задержки (Cache Stampede) и 502/504 при инвалидации кэша

**Симптом:** В момент сброса кэша популярного ресурса время ответа бэкенда подскакивает с 10 мс до 10 секунд, в логах фиксируются ошибки `502 Bad Gateway` и `504 Gateway Timeout`.

**Причина:** Отсутствуют механизмы синхронизации запросов `proxy_cache_lock` и отдачи устаревших копий `proxy_cache_use_stale`. Сотни параллельных клиентских потоков одновременно отправляются к бэкенду.

**Диагностика:**
```bash
# Анализ одномоментных запросов к бэкенду
grep ' 504 ' /var/log/nginx/cache_access.json | jq -r '.timestamp' | sort | uniq -c | sort -rn | head -n 5
```

**Решение:** Настройте блокировку и фоновое обновление:

```nginx
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
proxy_cache_background_update on;
```

### 5. Зависание воркеров на дисковом вводе-выводе (I/O Wait Spike)

**Симптом:** При отдаче тяжелых кэшированных файлов (медиа, архивы) загрузка процессора в состоянии `iowait` возрастает, воркеры Nginx блокируются на чтении файлов с диска, переставая своевременно обрабатывать события в `epoll`.

**Причина:** Стандартные дисковые операции чтения в Nginx выполняются синхронно, если не настроен пул потоков (Thread Pool).

**Диагностика:**
```bash
top -b -n 1 | grep "Cpu(s)"
# → %Cpu(s):  2.5 us,  4.1 sy,  0.0 ni, 58.2 id, 35.2 wa,  0.0 hi,  0.0 si

# Проверка блокировок Nginx через strace
strace -p <worker_pid> -c
```

**Решение:** Активируйте асинхронные потоки ядра Linux (`aio threads`) в контексте `http`:

```nginx
http {
    # Включение пула потоков по умолчанию (thread pool)
    aio threads=default;
    directio 8m;
    output_buffers 2 1m;
}
```

### 6. Отравление кэша персональными данными (Cache Poisoning)

**Симптом:** Пользователь А открывает личный кабинет или корзину и видит имя, заказы или профиль пользователя Б.

**Причина:** Неверно настроен ключ кэша `proxy_cache_key`, в зоне с авторизацией включен `proxy_ignore_headers Set-Cookie`, либо не учитывается заголовок `Vary`.

**Диагностика:**
```bash
# Проверка заголовков ответа для разных пользователей
curl -I -H "Authorization: Bearer token_A" http://api.example.internal/v1/profile
# → X-Cache-Status: HIT (Критическая уязвимость: персональный профиль отдается из кэша!)
```

**Решение:**
1. Категорически запретите кэширование персональных эндпоинтов:

```nginx
location /v1/profile/ {
    proxy_pass http://backend_api;
    proxy_cache_bypass 1;
    proxy_no_cache     1;
}
```

2. Для динамических ресурсов, зависящих от параметров заголовков (например, язык, формат сжатия gzip/brotli), включите соответствующие переменные в ключ:

```nginx
proxy_cache_key "$scheme$request_method$host$request_uri$http_accept_language$http_accept_encoding";
```

---

## Best Practices

1. **Изоляция файловой системы кэша:** Всегда монтируйте директорию кэша на выделенный дисковый накопитель (NVMe/SSD) с опциями `noatime,nodiratime`. Это гарантирует, что переполнение кэша не приведет к остановке корневой файловой системы ОС (`/`) и не заблокирует запись системных журналов `journald`.
2. **Атомарность записи (`use_temp_path=off`):** Всегда указывайте параметр `use_temp_path=off` в директиве `proxy_cache_path`. Это исключает межсегментный сбой `EXDEV` и устраняет двойную нагрузку на дисковый ввод-вывод.
3. **Разделение кэш-зон по типам нагрузки:** Создавайте независимые зоны памяти `keys_zone` для разных профилей трафика:
   - `api_cache`: малый объем диска, агрессивный LRU, короткий TTL (минуты), быстрый `inactive`.
   - `media_cache`: большой объем диска (сотни гигабайт), крупные объекты, длительный TTL (дни/недели), слайсинг `ngx_http_slice_module`.
4. **Синхронизация при промахах:** Для всех кэшируемых зон обязательно включайте связку директив защиты от Cache Stampede: `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;`, `proxy_cache_use_stale updating error timeout ...;` и `proxy_cache_background_update on;`.
5. **Контроль емкости по Inodes:** При планировании объема кэша рассчитывайте емкость не только в гигабайтах (`max_size`), но и по количеству инодов (`df -i`). Каждый сохраненный файл кэша требует один inode. Для большого числа мелких объектов форматируйте раздел с параметром `mkfs.ext4 -i 4096` или используйте XFS.
6. **Аудит безопасности заголовков:** Никогда не используйте `proxy_ignore_headers Set-Cookie` в локациях, где передаются персональные данные или авторизационные сессии. Всегда скрывайте передаваемые клиентам внутренние заголовки бэкенда (`proxy_hide_header X-Powered-By;`, `proxy_hide_header X-AspNet-Version;`).
7. **Контроль эффективности (Hit Ratio):** Регулярно отслеживайте метрику Hit Ratio в системе мониторинга. Целевой показатель для статического контента — $\ge 95\%$, для кэшируемых микросервисных API — $\ge 70\text{--}85\%$.
8. **Плавная загрузка при рестарте:** На высоконагруженных серверах с Nginx OSS настраивайте параметры `loader_files`, `loader_sleep` и `loader_threshold`, чтобы предотвратить 100% утилизацию диска процессом `cache loader`. В Angie используйте параметр `file=` для сохранения индекса на диск.
9. **Zero-Blocking дискового ввода-вывода:** При раздаче тяжелых файлов из кэша обязательно подключайте `aio threads=default;` и `directio`, чтобы чтение с накопителя не блокировало рабочий цикл событий `epoll` воркеров.

---

## Дополнительная информация

### Сравнение функциональности Nginx OSS и Angie

| Функция / Механизм | Nginx OSS (1.30.x / 1.31.x) | Angie (1.10+ / 1.12.x) | Инженерное значение |
| :--- | :--- | :--- | :--- |
| **Proxy Cache Lock** | Поддерживается нативно | Поддерживается нативно | Защита бэкендов от всплесков нагрузки (Cache Stampede) |
| **Background Update (SWR)** | Поддерживается нативно | Поддерживается нативно | Нулевая задержка клиентов при обновлении кэша |
| **Инвалидация (Purge API)** | Требует сторонних модулей (`ngx_cache_purge`) или скриптов | **Поддерживается нативно** (`angie-module-cache-purge`) | Мгновенный сброс устаревшего кэша через HTTP-метод `PURGE` |
| **Purge по маске (Wildcards `*`)** | Не поддерживается | **Поддерживается нативно** | Сброс целых разделов сайта (например, `/catalog/*`) одной командой |
| **Персистентность индекса (`file=`)** | Не поддерживается | **Поддерживается нативно** | Мгновенный старт сервиса без всплеска IOPS от Cache Loader |
| **Шардирование кэша по дискам** | Не поддерживается | **Поддерживается в Angie PRO** | Разделение кэша одной зоны на разные накопители (NVMe + HDD) |
| **Телеметрия в JSON / Prometheus** | Ограничено (`stub_status`, требует VTS-модуль) | **Встроенный Status API** и Prometheus метрики | Готовый мониторинг счетчиков HIT, MISS, BYPASS без сборки модулей |

### См. также

*   [Кэширование в Nginx и Angie: Обзор и концепции](./overview.md) — классификация кэширования, выбор стратегий и сравнение уровней.
*   [Мониторинг кэширования в Nginx и Angie](./monitoring.md) — детальный разбор `$upstream_cache_status`, экспорт в Prometheus и профилирование Page Cache Linux.
*   [Микрокэширование в Nginx и Angie](./microcaching.md) — специфика ультракороткого кэширования динамических ответов на tmpfs.
*   [Клиентское кэширование в Nginx и Angie](./client_caching.md) — управление поведением браузеров через заголовки Cache-Control и ETag.
*   [Оптимизация производительности Nginx](../nginx_performance_tuning.md) — комплексная настройка параметров ядра Linux, соединений и буферов.
*   [Буферизация и стриминг в Nginx](../../Proxy/nginx_buffering_and_streaming.md) — механика буферов проксирования и передача потоковых данных.
*   [Кэширование прокси в Angie (Proxy Cache)](../../Angie/angie-proxy-cache.md) — углубленная архитектура персистентности и шардирования в Angie.
*   [HTTP-кэширование](../../../../Networking/Protocols/HTTP/http_caching.md) — спецификации RFC 9111, заголовки и правила валидации.
