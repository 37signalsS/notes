# Microcaching в Nginx и Angie

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), Angie 1.8+ / 1.10+

## Определения

**Microcaching (Микрокэширование)** — техника серверного кэширования динамических ответов с ультракоротким временем жизни (обычно от 1 до 5 секунд). Используется как защитный буфер между входящим клиентским трафиком и динамическим бэкендом (PHP-FPM, Python/WSGI, Node.js, Go), снижая пиковую нагрузку на серверы приложений и базы данных на 90–99% при минимальной потере актуальности данных.

**Cache Stampede (Thundering Herd / «Стадо бизонов»)** — лавинообразный одновременный всплеск однотипных запросов к бэкенду, возникающий в момент истечения TTL популярного ресурса или при холодном старте кэша, приводящий к исчерпанию пула воркеров бэкенда и каскадному отказу сервиса.

**Кэш-блокировка (Cache Lock)** — механизм синхронизации запросов (`proxy_cache_lock` / `fastcgi_cache_lock`), при котором в момент отсутствия или устаревания кэша только один запрос передается на генерацию бэкенду, а все остальные параллельные запросы к тому же ресурсу удерживаются в очереди ожидания готового ответа из кэша.

**Асинхронная ревалидация (Stale-While-Revalidate / Background Update)** — подход, при котором клиент немедленно получает устаревшую (stale) копию ответа из кэша, пока Nginx в фоновом субреквесте (`proxy_cache_background_update`) асинхронно запрашивает у бэкенда свежие данные и обновляет кэш.

**RAM-кэш на tmpfs** — архитектурное размещение каталога хранения файлов кэша в оперативной памяти Linux посредством файловой системы `tmpfs`. Исключает дисковые операции ввода-вывода (I/O), снижает износ дисков SSD/NVMe (write amplification) и предотвращает задержки ядра на сброс dirty pages при миллисекундной ротации файлов кэша.

**Кэш-индекс (keys_zone)** — именованная область разделяемой памяти (shared memory), доступная всем рабочим процессам Nginx/Angie, хранящая хэшированные 128-битные ключи (MD5), метаданные валидности (TTL), таймстампы и счетчики популярности объектов. На 64-битных системах 1 МБ памяти вмещает ~8 000 ключей кэша.

**Обход кэша (Cache Bypass & No-Cache)** — механизмы гибкой фильтрации: директива `proxy_cache_bypass` предписывает пропустить чтение из кэша (запрос отправляется бэкенду), а директива `proxy_no_cache` запрещает сохранять полученный ответ в кэш.

**Отравление кэша (Cache Poisoning)** — архитектурная ошибка, при которой в общий кэш попадают персонализированные данные (сессионные cookies, токены авторизации, приватная информация пользователя) либо кэшируются ответы с некорректным статусом (5xx/4xx), после чего они начинают отдаваться всем остальным посетителям сайта.

**SSI (Server Side Includes)** — механизм сборки HTML-страницы из независимых фрагментов на уровне Nginx, позволяющий отдавать общий каркас страницы из микрокэша, а динамические персональные виджеты (профиль, корзина) загружать внутренними некэшируемыми подзапросами.

**Коэффициент попаданий (Cache Hit Ratio)** — процент запросов, успешно обслуженных кэшем (`HIT`, `STALE`, `UPDATING`), относительно общего входящего трафика к кэшируемой зоне. В условиях микрокэширования целевой показатель на высоконагруженных эндпоинтах составляет 90–99%.

Общий обзор всех типов и уровней кэширования представлен в [Кэширование в Nginx и Angie: Обзор и концепции](./overview.md).

---

## Архитектура и принципы работы

### Математическая модель и физика микрокэширования

Бэкенды динамических приложений (PHP, Python, Ruby, Node.js) тратят на обработку одного запроса десятки или сотни миллисекунд процессорного времени и ресурсов СУБД. В моменты пикового трафика (маркетинговые акции, Breaking News, DDoS, бот-активность) входящий поток может достигать 5 000 – 50 000 запросов в секунду на главную страницу или каталог.

При отсутствии кэширования сервер приложений мгновенно исчерпывает пул процессов или потоков, образуется очередь подключений, растет TTFB (Time To First Byte), после чего наступает отказ по таймауту (`HTTP 504 Gateway Timeout` или `HTTP 502 Bad Gateway`).

Микрокэширование вводит квантование времени:

$$\text{RPS}_{\text{backend}} \le \frac{1}{\text{TTL}}$$

Если популярный URL запрашивают 10 000 раз в секунду:
- При $\text{TTL} = 1\text{ c}$ на бэкенд поступает ровно **1 запрос в секунду**.
- Нагрузка на приложение снижается в **10 000 раз** (offload = 99.99%).
- 9 999 клиентов получают ответ за доли миллисекунды прямо из памяти Nginx.
- Актуальность данных отстает максимум на 1 000 мс, что абсолютно незаметно для человека при просмотре новостной ленты, витрины товаров или чтении блогов.

### Жизненный цикл микрокэшированного объекта

```
 [ Клиент ]
     │
     │ 1. GET /catalog HTTP/1.1
     ▼
 ┌────────────────────────────────────────────────────────┐
 │ Nginx Worker Process                                   │
 │                                                        │
 │ 2. Вычисление кэш-ключа: MD5(scheme + host + uri)      │
 │ 3. Поиск ключа в keys_zone (Shared Memory / RAM)       │
 └────────────────────────────────────────────────────────┘
     │
     ├───► [ Хит в кэше ] ──► (Статус: HIT) ──────────────┐
     │                                                    │
     └───► [ Промах или истекший TTL ]                    │
               │                                          │
               ▼                                          │
       ┌──────────────────────────────────────┐           │
       │ Проверка proxy_cache_lock            │           │
       └──────────────────────────────────────┘           │
         │                                  │             │
         │ (Первый запрос)                  │ (Параллельные запросы)
         ▼                                  ▼             │
 ┌────────────────────────┐      ┌──────────────────────┐ │
 │ Запрос к бэкенду       │      │ Ожидание в очереди   │ │
 │ (Upstream / FastCGI)   │      │ или отдача STALE     │ │
 └────────────────────────┘      └──────────────────────┘ │
         │                                  │             │
         ▼ 4. Ответ бэкенда (200 OK)        │             │
 ┌────────────────────────┐                 │             │
 │ Сохранение в tmpfs     │                 │             │
 │ (use_temp_path=off)    │                 │             │
 └────────────────────────┘                 │             │
         │                                  │             │
         ▼ 5. Обновление ключа в keys_zone  │             │
 ┌──────────────────────────────────────────┘             │
 │ 6. Раздача ответа ожидающим клиентам                   │
 ▼                                                        ▼
 [ Отдача ответа клиенту с заголовком X-Cache-Status ] ◄──┘
```

Состояния жизненного цикла фиксируются встроенной переменной `$upstream_cache_status`:
- `MISS` — первый запрос при пустом кэше; объект получен от бэкенда и записан в хранилище.
- `HIT` — объект найден в `keys_zone`, TTL не истек, ответ мгновенно отдан клиенту.
- `EXPIRED` — срок жизни TTL истек; инициирован запрос к бэкенду на обновление данных.
- `UPDATING` — ответ отдан из устаревшего кэша, пока фоновый воркер выполняет `proxy_cache_background_update`.
- `STALE` — отдан устаревший кэш из-за ошибки, таймаута или недоступности бэкенда (`proxy_cache_use_stale error timeout http_502`).
- `BYPASS` — кэш намеренно обойден по условию `proxy_cache_bypass` (например, авторизованный пользователь).

### Уровень хранения: tmpfs против блочных накопителей (NVMe/SSD)

В классическом серверном кэшировании с TTL в часы или дни запись файлов на NVMe/SSD накопители допустима. При микрокэшировании с TTL в 1–5 секунд файловые операции происходят с колоссальной частотой: тысячи созданий, чтений и удалений файлов в минуту.

Запись микрокэша на стандартный блочный накопитель приводит к трем критическим системным проблемам:
1. **Деградация ресурса накопителей (SSD Write Endurance):** непрерывная перезапись десятков гигабайт микрофайлов многократно увеличивает показатель Write Amplification (WA) и быстро исчерпывает ресурс TBW (Total Bytes Written).
2. **Блокировки ядра Linux и сброс dirty pages:** ядро накапливает измененные страницы в буфере оперативной памяти, после чего системные потоки `kworker/flush` синхронизируют их с диском. Это вызывает скачки `iowait`, всплески задержек дискового ввода-вывода и деградацию p99 latency веб-сервера.
3. **Фрагментация файловой системы и нагрузка на журнал (JBD2):** постоянное выделение и освобождение inode в ext4/XFS создает узкое место на дисковом контроллере.

**Системное решение:** монтирование каталога кэша в оперативную память через `tmpfs`. 
- Скорость чтения и записи ограничена только пропускной способностью системной шины RAM.
- Полное отсутствие дисковых транзакций и износа флэш-памяти.
- Автоматическое динамическое выделение памяти: `tmpfs` занимает ровно столько RAM, сколько весят текущие закэшированные файлы, не резервируя весь объем на старте.

> [!CRITICAL]
> **Архитектурный капкан `EXDEV: Invalid cross-device link`**
> По умолчанию Nginx сначала записывает временный файл ответа бэкенда в директорию `proxy_temp_path` (обычно расположенную в `/var/lib/nginx/proxy` на корневом диске), а затем вызывает функцию `rename()` для перемещения файла в `proxy_cache_path`.
> В Unix-системах системный вызов `rename()` **не может перемещать файлы между разными файловыми системами**. Если `proxy_cache_path` смонтирован на `tmpfs`, а `proxy_temp_path` остался на корневой ФС (`/`), Nginx аварийно завершит операцию с ошибкой `[crit] ... rename() failed (18: Invalid cross-device link)` и кэширование полностью перестанет работать!
> **Обязательное решение:** добавление параметра `use_temp_path=off` в директиву `proxy_cache_path` (или `fastcgi_cache_path`). В этом случае временные файлы создаются непосредственно в целевой директории `tmpfs`.

### Защита от каскадных сбоев и фоновое обновление

При стандартном поведении кэша в момент истечения TTL на первой секунде все пришедшие клиенты получают статус `EXPIRED` и синхронно отправляют запросы на бэкенд, порождая Cache Stampede.

Для абсолютной стабилизации бэкенда применяются три взаимосвязанных механизма:

1. **Мьютекс на уровне запроса (`proxy_cache_lock on;`):**
   Только один клиентский поток уходит в бэкенд. Все последующие запросы к тому же URI блокируются на время `proxy_cache_lock_timeout` (по умолчанию 5 секунд). Как только первый запрос завершился и заполнил кэш, все заблокированные клиенты мгновенно получают ответ из кэша.
2. **Отказоустойчивость при сбоях (`proxy_cache_use_stale`):**
   Если бэкенд перегружен, отдает 500/502/503/504 или не успевает ответить по таймауту, Nginx не показывает клиенту экран ошибки, а отдает предыдущую (устаревшую) копию страницы из микрокэша (`stale`).
3. **Бесшовное фоновое обновление (`proxy_cache_background_update on;`):**
   При истечении TTL клиент, сделавший запрос, **не ждет ответа бэкенда**. Nginx мгновенно отдает ему устаревший кэш (статус `UPDATING`), а сам в фоновом режиме формирует асинхронный субреквест к бэкенду. В результате клиенты вообще никогда не сталкиваются с задержкой генерации страниц приложением.

### Нормализация ключа кэширования и защита от отравления

По умолчанию ключ формируется как `proxy_cache_key $scheme$proxy_host$request_uri;`. Переменная `$request_uri` включает полный исходный путь со всеми параметрами строки запроса (`query string`).

Маркетинговые и аналитические метки (`utm_source`, `utm_medium`, `gclid`, `fbclid`, `_openstat`), а также случайный порядок параметров приводят к тому, что один и тот же контент кэшируется под тысячами разных ключей. Это разрушает Hit Ratio (он падает до 0%) и переполняет память `tmpfs`.

**Правила нормализации:**
1. Очистка ключа от незначащих параметров через `map`.
2. Явное ограничение кэшируемых методов через `proxy_cache_methods GET HEAD;` (POST, PUT, DELETE никогда не должны попадать в кэш).
3. Изоляция `Set-Cookie`: если динамический бэкенд генерирует cookie для анонимного пользователя, этот заголовок нельзя сохранять в микрокэш, иначе Nginx раздаст одну и ту же сессию всем посетителям сайта. Для этого применяется `proxy_hide_header Set-Cookie;` и `proxy_ignore_headers Cache-Control Expires Set-Cookie;`.

### Гибридная сборка страниц через SSI (Server Side Includes)

Если веб-страница содержит персональный блок (например: «Привет, Иван! Корзина: 3 товара»), ее нельзя полностью кэшировать под общим ключом. Полный отказ от кэширования возвращает всю нагрузку на бэкенд.

Классическое архитектурное решение для высоконагруженных порталов — разделение страницы на уровне Nginx через **SSI**:
- Каркас страницы (каталог, статьи, меню, футер — 98% объема DOM-дерева) кэшируется на 1–5 секунд.
- Персональный блок оформляется тегом `<!--# include virtual="/api/user_widget" -->`.
- Nginx обрабатывает директиву `ssi on;`: при отдаче закэшированного каркаса он выполняет легковесный внутренний подзапрос (`subrequest`) к `/api/user_widget` с передачей клиентских сессионных cookies без кэширования и склеивает поток на лету.

---

## Практические сценарии

### Подготовка операционной системы: выделение RAM-диска (tmpfs)

Перед включением микрокэширования выделите изолированный раздел оперативной памяти под каталог кэша.

#### Шаг 1. Расчет ресурсов памяти и инодов

- **Размер хранилища (`size`):** Зависит от количества одновременных уникальных URL в секунду и среднего веса страницы. При 2 000 страниц по 50 КБ требуется ~100 МБ. Стандартный безопасный резерв для большинства production-серверов — `512M` или `1G`.
- **Количество дескрипторов файлов (`nr_inodes`):** По умолчанию Linux выделяет половину количества страниц RAM под иноды. Для исключения ситуации `No space left on device` при свободном объеме памяти явно задайте `nr_inodes=200k`.

#### Шаг 2. Создание каталога и монтирование

Выполните настройку точки монтирования:

```bash
# 1. Создание каталога для кэша Nginx
sudo mkdir -p /var/cache/nginx/microcache
sudo chown -R nginx:nginx /var/cache/nginx/microcache
sudo chmod 0700 /var/cache/nginx/microcache

# 2. Монтирование файловой системы tmpfs с флагами безопасности и производительности
sudo mount -t tmpfs -o size=512M,nr_inodes=200k,noatime,nodiratime,mode=0700,uid=nginx,gid=nginx tmpfs /var/cache/nginx/microcache

# 3. Проверка успешности монтирования
mount | grep microcache
# → tmpfs on /var/cache/nginx/microcache type tmpfs (rw,noatime,nodiratime,size=524288k,nr_inodes=200k,mode=700,uid=101,gid=101)
```

#### Шаг 3. Фиксация в `/etc/fstab`

Чтобы точка монтирования сохранялась после перезагрузки сервера, добавьте запись в `/etc/fstab`:

```ini
# /etc/fstab
tmpfs  /var/cache/nginx/microcache  tmpfs  defaults,size=512M,nr_inodes=200k,noatime,nodiratime,mode=0700,uid=nginx,gid=nginx  0  0
```

Проверка конфигурации fstab без перезагрузки:

```bash
sudo mount -a
df -h /var/cache/nginx/microcache
# → Filesystem      Size  Used Avail Use% Mounted on
# → tmpfs           512M     0  512M   0% /var/cache/nginx/microcache
```

---

### Сценарий 1: Production HTTP Reverse Proxy Microcaching

Базовый эталонный сценарий микрокэширования для динамических сервисов (Node.js, Go, Python/Gunicorn, upstream-кластеры). Включает защиту от Stampede, асинхронную ревалидацию и корректную обработку заголовков.

#### Конфигурация Nginx (`/etc/nginx/nginx.conf` и `/etc/nginx/conf.d/microcache.conf`)

```nginx
# В контексте http
http {
    # 1. Определение формата лога с параметрами производительности кэша
    log_format microcache_log '$remote_addr - [$time_local] "$request" '
                             'status=$status cache=$upstream_cache_status '
                             'rt=$request_time urt=$upstream_response_time '
                             'host="$host"';

    # 2. Определение зоны кэша на RAM-диске tmpfs
    # use_temp_path=off предотвращает ошибку EXDEV при переименовании
    proxy_cache_path /var/cache/nginx/microcache
                     levels=1:2
                     keys_zone=micro_zone:10m
                     max_size=512m
                     inactive=60s
                     use_temp_path=off;

    # 3. Фильтрация сессионных запросов для обхода кэша
    map $http_cookie $no_cache_cookie {
        default 0;
        ~*session 1;
        ~*auth_token 1;
        ~*logged_in 1;
    }

    # 4. Запрет кэширования небезопасных методов (POST, PUT, DELETE)
    map $request_method $no_cache_method {
        default 1;
        GET 0;
        HEAD 0;
    }

    upstream app_backend {
        server 127.0.0.1:8000 max_fails=3 fail_timeout=10s;
        keepalive 32;
    }

    server {
        listen 80;
        server_name example.com;

        access_log /var/log/nginx/access_micro.log microcache_log;
        error_log  /var/log/nginx/error.log warn;

        # Объединение условий обхода кэша
        set $bypass_cache 0;
        if ($no_cache_cookie) {
            set $bypass_cache 1;
        }
        if ($no_cache_method) {
            set $bypass_cache 1;
        }

        location / {
            # Активация зоны
            proxy_cache micro_zone;

            # Управление чтением и записью в кэш
            proxy_cache_bypass $bypass_cache;
            proxy_no_cache     $bypass_cache;

            # Ключ кэширования (схема, хост, URI без персональных cookie)
            proxy_cache_key "$scheme$request_method$host$request_uri";

            # Микро-TTL: успешные ответы кэшируются на 1 секунду
            proxy_cache_valid 200 301 302 1s;
            proxy_cache_valid 404          2s;
            proxy_cache_valid any          0s;

            # Предотвращение Cache Stampede
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;
            proxy_cache_lock_age 5s;

            # Отдача устаревшего контента при сбоях бэкенда и фоновом обновлении
            proxy_cache_use_stale error timeout invalid_header updating
                                  http_500 http_502 http_503 http_504;

            # Фоновая асинхронная ревалидация (клиенты не ждут ответа бэкенда)
            proxy_cache_background_update on;
            proxy_cache_revalidate on;

            # Игнорирование анти-кэш заголовков бэкенда для принудительного микрокэша
            proxy_ignore_headers Cache-Control Expires;

            # Удаление Set-Cookie из закэшированного ответа для исключения утечки сессий
            proxy_hide_header Set-Cookie;

            # Проброс заголовков бэкенду
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Connection "";
            proxy_http_version 1.1;

            # Диагностический заголовок в ответе клиенту
            add_header X-Cache-Status $upstream_cache_status always;

            proxy_pass http://app_backend;
        }
    }
}
```

---

### Сценарий 2: FastCGI Microcaching для PHP-FPM / CMS

Для веб-приложений на базе PHP (WordPress, Laravel, Drupal, Bitrix) микрокэширование устраняет вызовы интерпретатора PHP-FPM для сотен параллельных запросов анонимных пользователей.

```nginx
# В контексте http
fastcgi_cache_path /var/cache/nginx/microcache_fastcgi
                   levels=1:2
                   keys_zone=fastcgi_micro:10m
                   max_size=512m
                   inactive=60s
                   use_temp_path=off;

# Карта проверки авторизованных пользователей CMS
map $http_cookie $cms_logged_in {
    default 0;
    ~*wordpress_logged_in 1;
    ~*comment_author 1;
    ~*PHPSESSID 1;
    ~*laravel_session 1;
}

server {
    listen 80;
    server_name blog.example.com;
    root /var/www/html;
    index index.php index.html;

    set $skip_cache 0;

    # Не кэшировать POST-запросы
    if ($request_method = POST) {
        set $skip_cache 1;
    }

    # Не кэшировать запросы с query string (поиск, фильтры)
    if ($query_string != "") {
        set $skip_cache 1;
    }

    # Не кэшировать авторизованных пользователей
    if ($cms_logged_in) {
        set $skip_cache 1;
    }

    # Не кэшировать панель управления
    if ($request_uri ~* "/(wp-admin/|admin/|login|cart|checkout)") {
        set $skip_cache 1;
    }

    location ~ \.php$ {
        try_files $uri =404;

        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;

        # Подключение микрокэша FastCGI
        fastcgi_cache fastcgi_micro;
        fastcgi_cache_key "$scheme$request_method$host$request_uri";

        fastcgi_cache_bypass $skip_cache;
        fastcgi_no_cache     $skip_cache;

        fastcgi_cache_valid 200 301 302 2s;
        fastcgi_cache_valid 404          1s;

        # Защита от Stampede и фоновое обновление
        fastcgi_cache_lock on;
        fastcgi_cache_lock_timeout 4s;
        fastcgi_cache_use_stale error timeout updating http_500 http_503;
        fastcgi_cache_background_update on;

        # Игнорирование управляющих заголовков PHP для публичных страниц
        fastcgi_ignore_headers Cache-Control Expires Set-Cookie;

        # Маскировка заголовка Set-Cookie для исключения отравления сессий
        fastcgi_hide_header Set-Cookie;

        add_header X-FastCGI-Cache $upstream_cache_status always;
    }
}
```

---

### Сценарий 3: Microcaching REST API с динамическим управлением TTL через бэкенд

В микросервисной архитектуре API-бэкенд может сам точно знать, на какое время безопасно кэшировать конкретный ответ. Это реализуется через специальный внутренний HTTP-заголовок `X-Accel-Expires`.

Если бэкенд возвращает:
- `X-Accel-Expires: 3` — Nginx кэширует данный JSON-ответ ровно на 3 секунды.
- `X-Accel-Expires: 0` — Nginx гарантированно не кэширует данный ответ.
- `X-Accel-Expires: @1735689600` — кэширование до определенного Unix Timestamp.

#### Конфигурация Nginx

```nginx
location /api/v1/ {
    proxy_pass http://api_upstream;

    proxy_cache micro_zone;
    proxy_cache_key "$scheme$request_method$host$uri$is_args$args";

    # Если бэкенд не вернул X-Accel-Expires, действует fallback:
    proxy_cache_valid 200 1s;
    proxy_cache_valid 404 1s;
    proxy_cache_valid 500 502 503 504 0s;

    # Nginx обрабатывает заголовок X-Accel-Expires по умолчанию.
    # Скрываем внутренний служебный заголовок от внешнего клиента:
    proxy_hide_header X-Accel-Expires;

    # Запрет кэширования при наличии заголовка авторизации
    proxy_cache_bypass $http_authorization;
    proxy_no_cache     $http_authorization;

    proxy_cache_lock on;
    proxy_cache_use_stale updating error timeout;
    proxy_cache_background_update on;

    add_header X-API-Cache $upstream_cache_status always;
}
```

Пример ответа бэкенда (Python/FastAPI или Go):

```http
HTTP/1.1 200 OK
Content-Type: application/json
X-Accel-Expires: 2
Content-Length: 154

{"status":"ok","crypto_rate":{"BTC_USD":64230.50},"updated_at":"2026-10-16T13:10:00Z"}
```

---

### Сценарий 4: Гибридная сборка динамических страниц через SSI

Сценарий позволяет кэшировать тяжелый рендеринг страницы (каталог интернет-магазина) на 2 секунды, подставляя динамический блок авторизованного пользователя («Здравствуйте, Алексей | Корзина: 2») отдельным внутренним запросом.

#### Главный шаблон страницы (`index.html` на бэкенде)

```html
<!DOCTYPE html>
<html>
<head><title>Каталог товаров</title></head>
<body>
    <header>
        <h1>Супермаркет</h1>
        <!-- Блок пользователя загружается через SSI подзапрос -->
        <!--# include virtual="/_internal/auth_widget" -->
    </header>
    <main>
        <!-- Тяжелый блок товаров, закэшированный в microcache -->
        <h2>Список популярных товаров</h2>
        <div class="catalog">...</div>
    </main>
</body>
</html>
```

#### Конфигурация Nginx

```nginx
server {
    listen 80;
    server_name shop.example.com;

    # 1. Основной location с microcaching и обработкой SSI
    location / {
        ssi on; # Активация сборщика SSI в теле ответа
        ssi_silent_errors off;

        proxy_cache micro_zone;
        proxy_cache_valid 200 2s;
        proxy_cache_lock on;
        proxy_cache_use_stale updating error;

        # Кэшируем страницу целиком под общим ключом для всех пользователей
        proxy_cache_key "$scheme$host$uri";

        proxy_pass http://catalog_backend;
        add_header X-Page-Cache $upstream_cache_status always;
    }

    # 2. Внутренний location для сборки персонального виджета
    location = /_internal/auth_widget {
        internal; # Доступен только для внутренних вызовов из SSI

        # Полный запрет кэширования для виджета пользователя
        proxy_cache off;

        # Проброс оригинальных cookie клиента в бэкенд авторизации
        proxy_set_header Cookie $http_cookie;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        proxy_pass http://auth_backend/widget;
    }
}
```

---

### Сценарий 5: SRE Observability — Логирование, аудит и расчет Hit Ratio

Для операционной надежности инженер SRE должен в режиме реального времени контролировать эффективность микрокэша и нагрузку на диск.

#### Шаг 1. Расчет Hit Ratio в реальном времени из логов

Используя формат лога `microcache_log` со значением `$upstream_cache_status`:

```bash
# Потоковый расчет Hit Ratio за последние 1000 запросов
tail -n 1000 /var/log/nginx/access_micro.log | awk '{
    for(i=1;i<=NF;i++) {
        if ($i ~ /^cache=/) {
            split($i, a, "=");
            status = a[2];
            total++;
            if (status == "HIT" || status == "UPDATING" || status == "STALE") {
                hits++;
            }
            counts[status]++;
        }
    }
}
END {
    printf "=== Анализ эффективности микрокэша ===\n";
    printf "Всего запросов: %d\n", total;
    for (s in counts) {
        printf "Статус %-10s: %d (%.2f%%)\n", s, counts[s], (counts[s]/total)*100;
    }
    printf "--------------------------------------\n";
    printf "Итоговый Hit Ratio: %.2f%%\n", (hits/total)*100;
}'
```

Ожидаемый результат выполнения:

```text
# → === Анализ эффективности микрокэша ===
# → Всего запросов: 1000
# → Статус HIT       : 942 (94.20%)
# → Статус MISS      : 18 (1.80%)
# → Статус UPDATING  : 28 (2.80%)
# → Статус EXPIRED   : 12 (1.20%)
# → --------------------------------------
# → Итоговый Hit Ratio: 97.00%
```

#### Шаг 2. Проверка отсутствия дискового I/O через `iostat`

Убедитесь, что запись в кэш не создает нагрузки на физические накопители:

```bash
# Наблюдение за дисковой активностью NVMe/SSD накопителя (интервал 1 сек)
iostat -xz 1 5
```

Ожидаемый результат:

```text
# → Device    r/s    w/s   rkB/s   wkB/s  rrqm/s  wrqm/s  %rrqm  %wrqm  r_await w_await aqu-sz rareq-sz wareq-sz  %util
# → nvme0n1  0.00   1.20    0.00   16.00    0.00    0.00   0.00   0.00     0.10    0.25   0.00     0.00    13.33   0.08
```
Показатель `%util` и `wkB/s` близок к нулю, так как весь поток микрокэширования локализован в `tmpfs`.

#### Шаг 3. Экспорт метрик в Prometheus через `nginx-module-vts`

При установленном модуле `http_vts_module` добавьте мониторинг зоны кэша:

```nginx
http {
    vhost_traffic_status_zone;

    server {
        listen 9913;
        server_name 127.0.0.1;

        location /status/format/prometheus {
            vhost_traffic_status_display;
            vhost_traffic_status_display_format prometheus;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }
    }
}
```

Проверка метрик в консоли:

```bash
curl -s http://127.0.0.1:9913/status/format/prometheus | grep nginx_vts_cache
# → # HELP nginx_vts_cache_requests_total The number of requests for cache
# → # TYPE nginx_vts_cache_requests_total counter
# → nginx_vts_cache_requests_total{backend="micro_zone",status="hit"} 48120
# → nginx_vts_cache_requests_total{backend="micro_zone",status="miss"} 320
# → nginx_vts_cache_requests_total{backend="micro_zone",status="expired"} 114
# → nginx_vts_cache_requests_total{backend="micro_zone",status="updating"} 205
# → nginx_vts_cache_requests_total{backend="micro_zone",status="bypass"} 45
```

PromQL формула расчета Hit Ratio для алерта в Alertmanager:

```promql
sum(rate(nginx_vts_cache_requests_total{status=~"hit|updating|stale"}[5m]))
/
sum(rate(nginx_vts_cache_requests_total[5m])) * 100 < 80
```

---

### Сценарий 6: Нагрузочное тестирование и бенчмаркинг (`wrk`)

Сравнение поведения сервиса под нагрузкой 5 000 RPS до и после включения микрокэширования.

#### Шаг 1. Запуск стресс-теста до включения микрокэша

```bash
wrk -t8 -c200 -d10s http://example.com/catalog
```

Ожидаемый результат (бэкенд перегружен):

```text
# → Running 10s test @ http://example.com/catalog
# →   8 threads and 200 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency   482.12ms  124.50ms   1.89s    78.20%
# →     Req/Sec   112.40     34.20   210.00     69.50%
# →   8942 requests in 10.05s, 42.15MB read
# →   Socket errors: connect 0, read 420, write 0, timeout 312
# → Requests/sec:    889.75
# → Non-2xx or 3xx responses: 45
```

#### Шаг 2. Запуск стресс-теста после активации микрокэширования (TTL 1s, tmpfs)

```bash
wrk -t8 -c200 -d10s http://example.com/catalog
```

Ожидаемый результат:

```text
# → Running 10s test @ http://example.com/catalog
# →   8 threads and 200 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     1.15ms  640.20us  14.25ms   89.40%
# →     Req/Sec     6.12k     1.02k    8.94k    71.20%
# →   489120 requests in 10.01s, 2.30GB read
# → Requests/sec:  48863.14
```

**Результат:** Пропускная способность выросла в **55 раз**, средняя задержка упала с **482 мс** до **1.15 мс**, устранены сетевые таймауты и ошибки 5xx.

---

## Операции и команды

### Сводная таблица директив микрокэширования

| Директива | Контекст | Рекомендуемое значение | Назначение |
| :--- | :--- | :--- | :--- |
| `proxy_cache_path` | `http` | `/var/cache/... use_temp_path=off` | Инициализация каталога кэша и зоны разделяемой памяти в `tmpfs` |
| `proxy_cache` | `http`, `server`, `location` | `micro_zone` | Подключение именованной зоны кэширования к контексту |
| `proxy_cache_valid` | `http`, `server`, `location` | `200 301 302 1s;` | Время жизни микрокэша для успешных кодов ответа |
| `proxy_cache_lock` | `http`, `server`, `location` | `on` | Включение мьютекса для предотвращения Cache Stampede |
| `proxy_cache_lock_timeout` | `http`, `server`, `location` | `5s` | Предельное время ожидания ответа первым запросом |
| `proxy_cache_lock_age` | `http`, `server`, `location` | `5s` | Защита от зависшего бэкенда: сброс блокировки через N секунд |
| `proxy_cache_use_stale` | `http`, `server`, `location` | `updating error timeout http_502` | Разрешение отдачи устаревшего кэша при сбоях и ревалидации |
| `proxy_cache_background_update` | `http`, `server`, `location` | `on` | Асинхронное фоновое обновление устаревших записей |
| `proxy_cache_revalidate` | `http`, `server`, `location` | `on` | Отправка условных запросов `If-Modified-Since` / `If-None-Match` |
| `proxy_cache_bypass` | `http`, `server`, `location` | `$variable` | Пропуск чтения из кэша (непустое значение и не `0` = bypass) |
| `proxy_no_cache` | `http`, `server`, `location` | `$variable` | Запрет сохранения ответа в кэш |
| `proxy_ignore_headers` | `http`, `server`, `location` | `Cache-Control Expires` | Игнорирование анти-кэш заголовков от приложения |
| `proxy_hide_header` | `http`, `server`, `location` | `Set-Cookie` | Скрытие заголовка `Set-Cookie` для предотвращения отравления |
| `use_temp_path=off` | параметр `proxy_cache_path` | `off` | Прямая запись во временные файлы `tmpfs` без вызова межфайлового `rename` |

### Системные команды обслуживания микрокэша

#### Аудит использования памяти и инодов на tmpfs

```bash
# 1. Проверка свободного объема и количества свободных inode
df -h /var/cache/nginx/microcache
# → Filesystem      Size  Used Avail Use% Mounted on
# → tmpfs           512M   48M  464M  10% /var/cache/nginx/microcache

df -i /var/cache/nginx/microcache
# → Filesystem      Inodes  IUsed   IFree IUse% Mounted on
# → tmpfs           200000   1420  198580    1% /var/cache/nginx/microcache
```

#### Инспекция закэшированного файла

```bash
# Поиск первого попавшегося файла в каталоге кэша
CACHE_FILE=$(find /var/cache/nginx/microcache -type f | head -n 1)

# Просмотр бинарного заголовка Nginx и HTTP-заголовков бэкенда
head -n 25 "$CACHE_FILE"
```

Пример вывода структуры файла кэша:

```text
# → KEY: httpGETexample.com/catalog
# → HTTP/1.1 200 OK
# → Server: nginx
# → Date: Fri, 16 Oct 2026 13:10:05 GMT
# → Content-Type: text/html; charset=UTF-8
# → Connection: close
# → X-Powered-By: PHP/8.3.6
```

#### Безопасная очистка (Purge) зоны микрокэша

> [!WARNING]
> Никогда не выполняйте `rm -rf /var/cache/nginx/microcache` на работающем сервере! Это удалит точку монтирования или права доступа каталога. Воркеры Nginx не смогут пересоздать структуру подкаталогов `levels=1:2` и начнут возвращать ошибки 500.

Правильная процедура очистки:

```bash
# Быстрое удаление всех закэшированных файлов с сохранением структуры каталогов
find /var/cache/nginx/microcache -type f -delete

# Проверка очистки
df -h /var/cache/nginx/microcache
# → Filesystem      Size  Used Avail Use% Mounted on
# → tmpfs           512M     0  512M   0% /var/cache/nginx/microcache
```

---

## Устранение неполадок

### Сводная таблица типовых неисправностей

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `[crit] ... rename() ... failed (18: Invalid cross-device link)` | Попытка атомарного перемещения файла между разными ФС (диск → tmpfs) | `grep "Invalid cross-device link" /var/log/nginx/error.log` | Добавить `use_temp_path=off;` в директиву `proxy_cache_path` |
| Hit Ratio равен 0%, статус всегда `MISS` | Бэкенд возвращает `Set-Cookie`, `Cache-Control: no-cache` или меняется `$request_uri` | `curl -I http://127.0.0.1:8000/path`<br>`tail -f /var/log/nginx/access_micro.log` | Добавить `proxy_ignore_headers Cache-Control Expires;`, канонизировать ключ |
| `No space left on device` при свободном объеме RAM | Исчерпаны иноды (`IFree = 0`) в `tmpfs` из-за большого числа мелких файлов | `df -i /var/cache/nginx/microcache` | Перемонтировать `tmpfs` с `nr_inodes=500k`, уменьшить `inactive=30s` |
| Пользователь А видит корзину/профиль пользователя Б | Отравление кэша: страница закэширована вместе с персональным `Set-Cookie` | `grep -a "Set-Cookie" /var/cache/nginx/microcache/*/*/*` | Настроить `proxy_hide_header Set-Cookie;` и обход кэша через `$http_cookie` |
| Всплески задержек и 504 Gateway Timeout каждые N секунд | Cache Stampede в момент истечения TTL | Мониторинг задержек upstream в логах в моменты смены секунды | Включить `proxy_cache_lock on;` и `proxy_cache_background_update on;` |
| Ошибка `500 Internal Server Error` после ручной очистки кэша | Удален рабочий каталог или сбиты права `nginx:nginx` | `ls -ld /var/cache/nginx/microcache` | Восстановить права `chown -R nginx:nginx` и структуру каталогов |

### Детальный разбор аварийных ситуаций

#### 1. Ошибка `Invalid cross-device link (18)`

**Симптомы:** В `error.log` Nginx фиксируются критические ошибки:
```text
2026/10/16 13:12:01 [crit] 12450#12450: *1204 rename() "/var/lib/nginx/proxy/7/01/0000000107" to "/var/cache/nginx/microcache/3/a4/6a8b79e728469a" failed (18: Invalid cross-device link)
```
Запросы проксируются, но ответы никогда не сохраняются в кэше (постоянный `MISS`).

**Причина:** Директива `proxy_cache_path` не содержит параметра `use_temp_path=off`. Nginx записывает буфер в `/var/lib/nginx/proxy/` (находящийся на root файловой системе `/dev/sda1`), а затем пытается переместить файл в `/var/cache/nginx/microcache` (файловая система `tmpfs`). Системный вызов `rename()` в ядре Linux возвращает ошибку `EXDEV`.

**Решение:**
1. Отредактируйте конфигурацию `proxy_cache_path`:
   ```nginx
   proxy_cache_path /var/cache/nginx/microcache
                    levels=1:2
                    keys_zone=micro_zone:10m
                    max_size=512m
                    inactive=60s
                    use_temp_path=off; # <-- КРИТИЧЕСКИЙ ПАРАМЕТР
   ```
2. Проверьте синтаксис и перезагрузите Nginx:
   ```bash
   sudo nginx -t && sudo nginx -s reload
   ```

---

#### 2. Исчерпание инодов на tmpfs (`No space left on device`)

**Симптомы:** При наличии сотен мегабайт свободной оперативной памяти запись в кэш прекращается, в `error.log` появляется ошибка:
```text
2026/10/16 13:14:15 [crit] 12450#12450: *8451 open() "/var/cache/nginx/microcache/..." failed (28: No space left on device)
```

**Диагностика:**
```bash
df -h /var/cache/nginx/microcache
# → Filesystem      Size  Used Avail Use% Mounted on
# → tmpfs           512M   45M  467M  10% /var/cache/nginx/microcache  <-- Место есть!

df -i /var/cache/nginx/microcache
# → Filesystem      Inodes  IUsed  IFree IUse% Mounted on
# → tmpfs            50000  50000      0  100% /var/cache/nginx/microcache <-- Иноды исчерпаны!
```

**Причина:** Значение параметра `inactive=...` слишком велико (например, 1 день), либо при монтировании `tmpfs` не был задан параметр `nr_inodes`, и ядро выделило лимит по умолчанию. Тысячи файлов с истекшим TTL продолжают занимать дескрипторы до срабатывания Cache Manager.

**Решение:**
1. Немедленно перемонтируйте `tmpfs` с увеличенным лимитом инодов на лету:
   ```bash
   sudo mount -o remount,size=512M,nr_inodes=300k /var/cache/nginx/microcache
   ```
2. В файле конфигурации Nginx уменьшите время `inactive`:
   ```nginx
   # Для микрокэша с TTL 1s значение inactive должно быть в диапазоне 30s - 120s
   proxy_cache_path /var/cache/nginx/microcache ... inactive=60s;
   ```
3. Зафиксируйте опцию `nr_inodes=300k` в `/etc/fstab`.

---

#### 3. Отравление кэша сессионными данными (Session Leakage)

**Симптомы:** Пользователи жалуются, что после входа на сайт они видят имя, аватар или товары в корзине другого пользователя.

**Причина:** Бэкенд на любой входящий запрос (даже к главной странице) генерирует заголовок `Set-Cookie: session_id=...`. Nginx сохранил ответ в кэш вместе с этим заголовком и начал отдавать один и тот же `session_id` всем последующим посетителям.

**Диагностика:**
```bash
# Проверка наличия Set-Cookie в кэшированных объектах
grep -ri "Set-Cookie" /var/cache/nginx/microcache/
```

**Решение:**
1. Очистите скомпрометированный кэш:
   ```bash
   find /var/cache/nginx/microcache -type f -delete
   ```
2. Добавьте жесткую изоляцию заголовков в блок `location`:
   ```nginx
   # Запретить сохранение Set-Cookie в кэш
   proxy_ignore_headers Set-Cookie;

   # Удалить Set-Cookie из заголовков ответа, отдаваемых из кэша клиенту
   proxy_hide_header Set-Cookie;

   # Запретить кэширование, если клиент сам пришел с cookie сессии
   proxy_cache_bypass $cookie_sessionid $cookie_auth_token;
   proxy_no_cache     $cookie_sessionid $cookie_auth_token;
   ```
3. Перезагрузите Nginx:
   ```bash
   sudo nginx -t && sudo nginx -s reload
   ```

---

## Лучшие практики

### Архитектурные и системные рекомендации (Sysadmin & SRE)

1. **Всегда размещайте микрокэш в `tmpfs`:**
   Никогда не используйте механические HDD или стандартные разделы SSD для хранения кэша с TTL 1–5 секунд. Работа с оперативной памятью гарантирует нулевой дисковый I/O и микросекундный доступ.
2. **Контролируйте `use_temp_path=off`:**
   Параметр обязателен при размещении кэша на отдельной файловой системе (`tmpfs`) для предотвращения системных ошибок `EXDEV`.
3. **Монтируйте с `noatime,nodiratime`:**
   Отключение обновления времени доступа к файлам и каталогам экономит процессорные такты ядра при тысячах операций в секунду.
4. **Ограничивайте `inactive` пропорционально TTL:**
   При TTL в 1–2 секунды параметр `inactive` не должен превышать `60s` – `120s`. Большие значения бесполезно забивают оперативную память и исчерпывают иноды устаревшими файлами.
5. **Планируйте объем `keys_zone`:**
   1 МБ зоны вмещает ~8 000 ключей. Зоны `10m` (80 000 ключей) достаточно для подавляющего большинства высоконагруженных порталов. Избыточный размер зоны напрасно аллоцирует неизменяемую shared memory.

### Конфигурационные стандарты Nginx (DevOps)

1. **Тройка стабильности (Stampede Immunity):**
   Каждая зона микрокэширования должна содержать связку директив:
   ```nginx
   proxy_cache_lock on;
   proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
   proxy_cache_background_update on;
   ```
2. **Безопасная длина TTL:**
   Начинайте внедрение с `1s` или `2s`. Даже 1 секунда TTL снижает нагрузку на 95–99%. Увеличивайте TTL до 5–10 секунд только при подтверждении от бизнеса, что такая задержка не ломает пользовательский опыт.
3. **Изоляция авторизованных пользователей:**
   Всегда анализируйте `$http_cookie` и `$http_authorization` через `map` и отключайте кэш (`proxy_cache_bypass`, `proxy_no_cache`) для зарегистрированных пользователей, либо используйте архитектуру SSI.
4. **Скрывайте `Set-Cookie`:**
   Всегда указывайте `proxy_hide_header Set-Cookie;` для публичных динамических страниц, чтобы исключить утечки сессий между пользователями.
5. **Нормализация строки запроса:**
   Удаляйте аналитические и рекламные метки (`utm_*`, `fbclid`) из ключа кэширования через регулярные выражения в `map` до вычисления `proxy_cache_key`.
6. **Диагностические заголовки:**
   Всегда передавайте статус кэша клиенту или системам тестирования через `add_header X-Cache-Status $upstream_cache_status always;`.

---

## Дополнительная информация

### Связь с другими техниками

- **[Кэширование в Nginx и Angie: Обзор и концепции](./overview.md)** — архитектура клиентского и серверного кэша, выбор стратегии кэширования.
- **[Серверное кэширование (Proxy Cache) в Nginx и Angie](./proxy_caching.md)** — полное описание работы `ngx_http_proxy_module`, иерархия каталогов `levels`, механизм Purge.
- **[Клиентское кэширование в Nginx и Angie](./client_caching.md)** — заголовки `Cache-Control`, ETag, 304 Not Modified, оптимизация кэширования в браузерах.
- **[Мониторинг кэширования в Nginx и Angie](./monitoring.md)** — углубленный аудит Page Cache Linux, JSON-логирование, Prometheus, экспорт метрик и eBPF.
- **[Оптимизация производительности Nginx и Angie](../nginx_performance_tuning.md)** — системный тюнинг ядра Linux, буферов сокетов, `epoll`, пулов `keepalive` соединений.

### См. также

- [Архитектура и обзор Nginx](../../Core/nginx_overview.md) — внутреннее устройство рабочих процессов, event-driven модель.
- [Примеры интеграции Nginx с бэкендами](../../Core/Location/integration_examples.md) — схемы взаимодействия с FastCGI (PHP-FPM), uWSGI, Node.js, Go.