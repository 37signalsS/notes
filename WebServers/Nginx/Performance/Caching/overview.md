# Кэширование в Nginx и Angie: Обзор и концепции

**Актуально для:** Nginx 1.30.x (Stable) / 1.31.x (Mainline), Angie 1.10+ / 1.12.x

---

## Определения

**Кэширование (Caching)** — процесс промежуточного сохранения копий ответов на локальных ресурсах веб-сервера или клиента для ускорения обработки повторных обращений, минимизации времени отклика (Time to First Byte, TTFB), защиты вышестоящих бэкендов от пиковых нагрузок и снижения потребления ресурсов CPU, RAM и дисковой подсистемы. В Nginx и Angie кэширование является центральным архитектурным компонентом для построения высоконагруженных обратных прокси-серверов ([Оптимизация производительности Nginx и Angie](../nginx_performance_tuning.md)).

**Клиентское кэширование (Browser Caching)** — управление локальным хранилищем веб-браузеров и промежуточных шлюзов через заголовки HTTP (`Cache-Control`, `Expires`, `ETag`, `Last-Modified`). Исключает или минимизирует передачу сетевых запросов при повторных обращениях. Подробный разбор — в файле [Клиентское кэширование в Nginx и Angie](./client_caching.md).

**Серверное кэширование (Server-Side Caching)** — подсистема Nginx и Angie, сохраняющая ответы вышестоящих серверов на локальных блочных накопителях хоста:
*   **Proxy Cache (`ngx_http_proxy_module`):** Кэширование ответов от HTTP/HTTPS-бэкендов (`proxy_pass`).
*   **FastCGI Cache (`ngx_http_fastcgi_module`):** Кэширование ответов от демонов приложений FastCGI (например, PHP-FPM).
*   **uWSGI / SCGI Cache (`ngx_http_uwsgi_module`, `ngx_http_scgi_module`):** Кэширование ответов от серверов приложений Python (uWSGI, Gunicorn) и SCGI.
*   Детальная реализация и директивы — в [Серверном кэшировании (Proxy Cache) в Nginx и Angie](./proxy_caching.md).

**Кэш-индекс (`keys_zone`)** — область разделяемой памяти (shared memory), аллоцируемая ядром Linux при старте Nginx/Angie и доступная всем рабочим процессам (worker processes). Хранит метаданные кэшированных объектов в виде красно-черного дерева (Red-Black Tree) для поиска по 128-битному MD5-хэшу ключа ($O(\log N)$) и двухсвязного списка LRU (Least Recently Used) для вытеснения. На 64-битных системах 1 МБ памяти вмещает ~8 000 ключей кэша (10 МБ — ~80 000 ключей, 64 МБ — ~512 000 ключей).

**Кэш-загрузчик (Cache Loader)** — специализированный служебный дочерний процесс Nginx/Angie, запускаемый один раз при старте сервиса. Выполняет рекурсивный обход директории кэша на диске для восстановления индекса метаданных в `keys_zone`. На хранилищах с миллионами файлов может вызывать лавинообразный всплеск операций ввода-вывода (IOPS).

**Кэш-менеджер (Cache Manager)** — фоновый процесс, периодически просыпающийся для контроля объема занятого дискового пространства и удаления неактуальных данных. Если объем превышает лимит `max_size`, процесс удаляет наименее востребованные файлы по алгоритму LRU; также удаляются объекты, к которым не было обращений дольше периода `inactive`.

**Кэш-блокировка (`proxy_cache_lock`)** — механизм синхронизации параллельных запросов при промахе (`MISS`) или устаревании (`EXPIRED`). Пропускает к бэкенду только один первичный запрос для генерации ответа, удерживая остальные параллельные запросы в очереди ожидания готового файла кэша.

**Фоновое обновление (Background Update & SWR)** — режим (`proxy_cache_background_update on;`), реализующий концепцию Stale-While-Revalidate (RFC 5861). При истечении TTL текущему клиенту мгновенно отдается устаревшая копия данных (`STALE` / `UPDATING`), пока веб-сервер в асинхронном подзапросе запрашивает свежий контент у бэкенда.

**Слайсинг контента (`ngx_http_slice_module`)** — модуль разбиения больших файлов (медиа, дистрибутивы) на фрагменты фиксированного размера (`slice`), кэшируемые как независимые объекты. Обеспечивает мгновенный старт отдачи контента и поддержку Range-запросов без необходимости выкачивать весь файл целиком.

**Микрокэширование (Microcaching)** — стратегия серверного кэширования динамических ответов с ультракоротким временем жизни (1–5 секунд), нивелирующая нагрузку на приложения при всплесках трафика. Подробный разбор — в [Микрокэшировании в Nginx и Angie](./microcaching.md).

**Согласование кэша (Cache Revalidation)** — отправка бэкенду условного HTTP-запроса (`If-None-Match`, `If-Modified-Since`) для проверки актуальности устаревшего объекта (`proxy_cache_revalidate on;`). При получении `304 Not Modified` тело заново не скачивается, обновляется только TTL метаданных.

**Инвалидация кэша (Cache Purge)** — принудительное удаление объекта из оперативной памяти `keys_zone` и файловой системы по совпадению ключа до истечения регламентного TTL.

**Cache Stampede (Thundering Herd / «Стадо бизонов»)** — лавинообразный одновременный всплеск однотипных запросов к бэкенду в момент холодного старта или истечения TTL популярного ресурса, способный привести к исчерпанию пула воркеров бэкенда и каскадному отказу сервиса.

**Отравление кэша (Cache Poisoning)** — архитектурный дефект конфигурации, при котором персональные данные пользователей (сессионные cookies, токены), ответы с ошибками или ответы без учета заголовков согласования контента (`Vary`) сохраняются в разделяемый кэш и отдаются другим клиентам.

---

## Архитектура и принципы работы

### Многоуровневая топология кэширования

В промышленной инфраструктуре кэширование организуется в виде эшелонированной цепочки уровней:

```
[ Клиент / Браузер ]
        │  (HTTP Cache-Control: max-age, immutable, SWR, ETag)
        ▼
[ Edge / Ingress / Nginx / Angie Reverse Proxy ]
        │  (Proxy Cache / Microcache на NVMe или tmpfs)
        ▼
[ Сервер приложений (PHP-FPM / uWSGI / Node.js / Go) ]
        │  (FastCGI Cache / In-App Cache)
        ▼
[ СУБД / Хранилище (PostgreSQL / Redis / S3) ]
```

Каждый последующий уровень защищает предыдущий от нагрузки:
1. **Клиентский уровень:** Полностью устраняет сетевой трафик к серверу при наличии валидного кэша в браузере.
2. **Reverse Proxy уровень (Nginx/Angie):** Централизует кэширование динамики и статики для тысяч одновременных клиентов, реализует блокировки Stampede и отдачу устаревших копий при сбоях бэкенда.
3. **Application уровень:** Кэширует фрагменты страниц, результаты тяжелых SQL-запросов и внутренние вычисления.

Детальное описание протокольного взаимодействия доступно в [HTTP-кэшировании](../../../../Networking/Protocols/HTTP/http_caching.md).

### Модель памяти и дисковой подсистемы

Архитектура серверного кэша в Nginx и Angie строго разделена на два физических уровня:

1. **Индекс метаданных в разделяемой памяти (RAM / `keys_zone`):**
   - Выделяется ядром ОС в Shared Memory и монтируется в общее адресное пространство всех воркеров веб-сервера.
   - Организован в виде красно-черного дерева (Red-Black Tree) для быстрого поиска узлов по MD5-хэшу ключа за время $O(\log N)$.
   - Содержит двухсвязный список LRU (Least Recently Used) для ротации и вытеснения объектов.
   - Хранит только метаданные: 128-битный хэш ключа, размер тела, счетчики обращений, таймстампы (`valid_sec`, `last_modified`, `access_sec`) и файловый дескриптор.
   - Тело ответа в разделяемой памяти Nginx не хранится.

2. **Хранилище полезной нагрузки на файловой системе (Disk / Page Cache):**
   - Тела ответов и служебные заголовки бэкенда сохраняются в виде бинарных файлов в каталоге, заданном в `proxy_cache_path` (или `fastcgi_cache_path`).
   - Имя файла на диске соответствует 32-символьному hex-представлению MD5-хэша ключа кэша.
   - **Взаимодействие с системным Page Cache:** Читаемые и записываемые файлы кэша автоматически попадают в системный кэш страниц ядра Linux. На серверах с достаточным объемом свободной оперативной памяти «горячие» файлы отдаются непосредственно из RAM без физического обращения к блочному устройству ввода-вывода (Zero-Disk Read).

```
                      [ Клиентский запрос ]
                                │
                                ▼
            ┌───────────────────────────────────────┐
            │       Nginx / Angie Worker            │
            └───────────────────┬───────────────────┘
                                │
                    Поиск по хэш-ключу MD5
                                │
                                ▼
            ┌───────────────────────────────────────┐
            │   Shared Memory Zone (keys_zone)      │
            │   [Red-Black Tree]  &  [LRU Queue]    │
            └───────────┬───────────────────┬───────┘
                        │                   │
                  HIT   │             MISS  │
                        ▼                   ▼
            ┌───────────────────┐   ┌───────────────────┐
            │  Linux Page Cache │   │  Апстрим / Бэкенд │
            │   (Оперативная    │   │  (Генерация       │
            │    память ядра)   │   │   ответа)         │
            └───────────┬───────┘   └─────────┬─────────┘
                        │                     │
                  MISS  │ Page Fault          │ use_temp_path=off
                        ▼                     ▼
            ┌───────────────────┐   ┌───────────────────┐
            │  Блочный диск /   │   │  Атомарная запись │
            │  Файловая система │   │  нового файла на  │
            │  (NVMe / SSD)     │◄──┤  диск             │
            └───────────────────┘   └───────────────────┘
```

### Анатомия файла кэша на диске

Файл кэша Nginx представляет собой бинарный контейнер со следующей структурой:
1. **Служебный заголовок Nginx (Binary Header):** Содержит структуру `ngx_http_file_cache_header_t`:
   - Контрольная сумма и версия формата кэша.
   - 128-битный MD5-хэш ключа кэширования.
   - Временные метки: время создания (`date`), время истечения TTL (`valid_msec`), время последнего изменения бэкендом (`last_modified`).
   - Код статуса ответа бэкенда (200, 301, 404 и т.д.).
   - Длина заголовков ответа и длина тела.
2. **Оригинальные заголовки HTTP ответа:** Все HTTP-заголовки, возвращенные бэкендом (например, `Content-Type`, `Content-Length`, `ETag`, кастомные заголовки).
3. **Тело ответа (Payload):** Неизмененное тело ответа бэкенда (HTML, JSON, бинарный поток).

При инспекции файла утилитами `head` или `strings` сначала отображаются служебные бинарные байты, затем текстовые заголовки HTTP, пустая строка `\r\n\r\n` и тело данных.

### Иерархия каталогов (`levels`)

Для предотвращения деградации производительности файловых систем (ext4, XFS) при наличии сотен тысяч файлов в одной директории используется параметр `levels`:
- Формат: `levels=1:2` (рекомендуемый промышленный стандарт).
- При хэше ключа `b7f5c2d3e4f6a7b8c9d0e1f2a3b4c567`:
  - `1`: берется последний 1 символ (`7`) для каталога первого уровня (всего 16 подпапок: `0`–`f`).
  - `2`: берутся предшествующие 2 символа (`c5`) для каталога второго уровня (всего 256 подпапок: `00`–`ff`).
  - Результирующий путь: `/var/cache/nginx/proxy_cache/7/c5/b7f5c2d3e4f6a7b8c9d0e1f2a3b4c567`.
- Всего формируется $16 \times 256 = 4096$ подкаталогов, что устраняет блокировки inode и долгий поиск в каталогах ядра ОС.

### Атомарность записи (`use_temp_path=off`)

По умолчанию Nginx создает временный файл в директории `proxy_temp_path` (обычно `/var/lib/nginx/proxy`), а после завершения передачи ответа бэкенда переименовывает его в целевую директорию кэша вызовом ядра Linux `rename()`.
*   **Проблема:** Если `proxy_temp_path` и `proxy_cache_path` расположены на разных точках монтирования или дисковых разделах, системный вызов `rename()` завершается критической ошибкой `EXDEV (18: Invalid cross-device link)`. Веб-сервер вынужден выполнять медленное межсегментное копирование байт за байтом, удваивая нагрузку на ввод-вывод.
*   **Инженерный стандарт:** Параметр `use_temp_path=off` отключает использование промежуточной директории. Воркер Nginx создает скрытый временный файл вида `.0000000001` непосредственно внутри целевого дерева каталогов `proxy_cache_path`, после чего выполняет атомарный мгновенный `rename()` в пределах одной файловой системы.

### Таксономия и сравнение модулей кэширования Nginx и Angie

| Модуль | Директива пути | Протокол взаимодействия | Контекст применения | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **`ngx_http_proxy_module`** | `proxy_cache_path` | HTTP / HTTPS / gRPC | Reverse proxy к API, микросервисам, внешним апстримам | Наиболее функциональный: поддержка SWR, `background_update`, Purge, блокировок |
| **`ngx_http_fastcgi_module`** | `fastcgi_cache_path` | FastCGI бинарный протокол | Интеграция с PHP-FPM, классическими стеками | Прямое кэширование без промежуточного HTTP-прокси, обход через cookie сессий |
| **`ngx_http_uwsgi_module`** | `uwsgi_cache_path` | uwsgi бинарный протокол | Интеграция с Python (Django/Flask via uWSGI) | Высокая производительность сериализации параметров вызова |
| **`ngx_http_scgi_module`** | `scgi_cache_path` | SCGI протокол | Нишевые приложения на C, Lisp, Python | Упрощенный протокол передачи данных |
| **`ngx_http_slice_module`** | Использует `proxy_cache` | HTTP Range requests | Раздача тяжелого медиа, ISO, видеопотоков | Нарезка файла на сегменты, параллельный прогрев кэша |

### Жизненный цикл объекта кэша

1. **Холодный старт и инициализация:**
   - При запуске сервиса мастер-процесс инициализирует Shared Memory (`keys_zone`).
   - В Nginx OSS запускается процесс Cache Loader, сканирующий диск и наполняющий красно-черное дерево.
   - В Angie 1.9+ при наличии параметра `file=` индекс мгновенно восстанавливается из бинарного снимка на диске без обращения к файловой системе кэша.
2. **Обработка запроса (Request Evaluation):**
   - Вычисляется строковый ключ по шаблону `proxy_cache_key`.
   - Генерируется MD5-хэш ключа.
   - Выполняется поиск узла в красно-черном дереве `keys_zone`.
3. **Маршрутизация статуса:**
   - **HIT:** Объект найден в `keys_zone`, файл существует на диске, TTL не истек. Ответ отдается из Page Cache или диска.
   - **MISS:** Объект отсутствует. Запрос передается бэкенду. При получении ответа файл сохраняется на диске, метаданные заносятся в `keys_zone`.
   - **EXPIRED:** Объект найден, но TTL истек. Nginx инициирует условную ревалидацию (`If-None-Match`/`If-Modified-Since`) либо запрашивает полный ответ заново.
   - **UPDATING / STALE:** Если настроено фоновое обновление или апстрим недоступен, клиенту возвращается старая копия, пока Nginx обновляет кэш.
   - **BYPASS:** Запрос намеренно отправлен в обход кэша по директиве `proxy_cache_bypass`.
4. **Устаревание и вытеснение:**
   - **TTL (`proxy_cache_valid`):** Логический срок свежести контента.
   - **`inactive`:** Физический интервал неактивности. Если к объекту не обращались в течение этого периода (по умолчанию 10 минут), Cache Manager удаляет его независимо от TTL.
   - **LRU ротация при `max_size`:** Если суммарный объем файлов на диске достигает `max_size`, Cache Manager удаляет наименее востребованные файлы из конца LRU-очереди.
5. **Инвалидация (Purge):** Досрочное удаление узла из `keys_zone` и удаление файла с накопителя.

---

## Практические сценарии и конфигурация

### Системные требования и подготовка ОС (Sysadmin / DevOps)

Для обеспечения высокой доступности и надежности дисковой подсистемы кэша сервер настраивается на уровне операционной системы:

#### 1. Выделенный дисковый раздел и опции монтирования

Размещение кэша на корневом разделе (`/`) категорически не рекомендуется: при переполнении кэша или отказе ротации переполняется корневая файловая система, приводя к сбою системных служб (`journald`, `ssh`, СУБД).

Выделите отдельный LVM-том или NVMe-раздел и смонтируйте его с оптимизированными опциями в `/etc/fstab`:

```bash
# Пример записи в /etc/fstab для файловой системы ext4 / XFS
/dev/mapper/vg0-nginx_cache  /var/cache/nginx  xfs  defaults,noatime,nodiratime,allocsize=64k  0  2
```

Параметры:
*   `noatime,nodiratime`: Полностью отключают запись времени последнего доступа к файлам и каталогам при чтении. Это устраняет паразитные операции записи при отдаче кэша из Page Cache и снижает Write Amplification на SSD/NVMe.
*   `allocsize=64k` (для XFS): Увеличивает предварительное выделение непрерывных экстентов для предотвращения фрагментации при параллельной записи потоков.

#### 2. Тюнинг ядра Linux (sysctl)

Создайте файл `/etc/sysctl.d/99-nginx-cache.conf` для оптимизации сброса грязных страниц Page Cache:

```ini
# Максимальный процент RAM для "грязных" страниц перед принудительным синхронным сбросом
vm.dirty_ratio = 15

# Порог RAM, при котором фоновые потоки ядра (flusher) начинают асинхронный сброс на диск
vm.dirty_background_ratio = 5

# Агрессивность освобождения метаданных и inode из VFS кэша (дефолт 100, 50 - сохранять в RAM дольше)
vm.vfs_cache_pressure = 50
```

Применение настроек ядра:
```bash
sysctl --system
# → * Applying /etc/sysctl.d/99-nginx-cache.conf ...
```

#### 3. Права доступа, SELinux и systemd

Создание структуры каталогов с корректными правами доступа:

```bash
# Создание каталогов хранения
mkdir -p /var/cache/nginx/proxy_cache /var/cache/nginx/fastcgi_cache
chown -R nginx:nginx /var/cache/nginx
chmod 700 /var/cache/nginx/proxy_cache /var/cache/nginx/fastcgi_cache
```

Настройка контекстов безопасности SELinux (для систем RHEL, AlmaLinux, Rocky Linux):

```bash
# Назначение постоянного контекста httpd_cache_t
semanage fcontext -a -t httpd_cache_t "/var/cache/nginx(/.*)?"
restorecon -Rv /var/cache/nginx
# → Relabeled /var/cache/nginx from var_t to httpd_cache_t
```

Подробнее о системных ограничениях и изоляции юнитов — в [Харденинге Nginx: systemd-юнит, SELinux, AppArmor](../../Security/nginx_systemd_selinux_hardening.md). При использовании директивы `ProtectSystem=strict` в systemd-юните добавьте путь кэша в разрешенные:
```ini
# /etc/systemd/system/nginx.service.d/cache.conf
[Service]
ReadWritePaths=/var/cache/nginx /var/log/nginx
```

---

### Сценарий 1: Базовая архитектура HTTP Reverse Proxy Cache

Универсальная промышленная конфигурация для кэширования ответов микросервисов и API-эндпоинтов с регулированием Cache Loader.

Контекст `http` (`/etc/nginx/nginx.conf`):

```nginx
# Определение пути и параметров разделяемой памяти
proxy_cache_path /var/cache/nginx/proxy_cache
                  levels=1:2
                  keys_zone=api_cache:32m
                  inactive=12h
                  max_size=20g
                  use_temp_path=off
                  loader_files=200
                  loader_sleep=50ms
                  loader_threshold=100ms;

# Нормализация формата логирования статуса кэша
log_format cache_extended '$remote_addr - $remote_user [$time_local] '
                          '"$request" $status $body_bytes_sent '
                          'cache_status=$upstream_cache_status '
                          'rt=$request_time uct=$upstream_connect_time uht=$upstream_header_time urt=$upstream_response_time';
```

Контекст `server` (`/etc/nginx/conf.d/api.conf`):

```nginx
server {
    listen 80;
    server_name api.example.internal;

    access_log /var/log/nginx/api_access.log cache_extended;

    location /v1/catalog/ {
        proxy_pass http://catalog_backend;
        
        # Активация кэш-зоны
        proxy_cache api_cache;
        
        # Шаблон ключа: схема, метод, хост, URI со строкой аргументов
        proxy_cache_key "$scheme$request_method$host$request_uri";
        
        # Регламентные TTL по кодам ответа
        proxy_cache_valid 200 302 10m;
        proxy_cache_valid 404      1m;
        
        # Игнорирование управляющих заголовков бэкенда при необходимости жесткого кэширования
        proxy_ignore_headers Set-Cookie X-Accel-Expires;
        proxy_hide_header    Set-Cookie;
        
        # Информационный заголовок для аудита и отладки
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

---

### Сценарий 2: Кэширование FastCGI (PHP-FPM)

Схема для ускорения монолитных веб-приложений (WordPress, Laravel, кастомные PHP-сервисы).

Контекст `http`:

```nginx
fastcgi_cache_path /var/cache/nginx/fastcgi_cache
                    levels=1:2
                    keys_zone=php_cache:32m
                    inactive=24h
                    max_size=15g
                    use_temp_path=off;
```

Контекст `server`:

```nginx
server {
    listen 80;
    server_name app.example.internal;
    root /var/www/app/public;

    # Логика обхода кэша для авторизованных сессий
    set $skip_cache 0;

    # POST-запросы и запросы с аргументами не кэшируются
    if ($request_method = POST) {
        set $skip_cache 1;
    }
    if ($query_string != "") {
        set $skip_cache 1;
    }

    # Не кэшировать запросы при наличии сессионных cookie
    if ($http_cookie ~* "comment_author|wordpress_[a-f0-9]+|wp-postpass|wordpress_logged_in|PHPSESSID") {
        set $skip_cache 1;
    }

    location ~ \.php$ {
        include fastcgi_params;
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;

        # Подключение кэша
        fastcgi_cache php_cache;
        fastcgi_cache_key "$scheme$request_method$host$request_uri";
        fastcgi_cache_valid 200 301 302 1h;
        
        # Директивы обхода
        fastcgi_cache_bypass $skip_cache;
        fastcgi_no_cache     $skip_cache;

        add_header X-FastCGI-Cache $upstream_cache_status always;
    }
}
```

---

### Сценарий 3: Защита от Cache Stampede и аварийный режим (Graceful Degradation)

Для критически важных эндпоинтов, где падение бэкенда недопустимо, настраивается комбинация мьютекса, фонового обновления и отдачи устаревшего контента при сбоях:

```nginx
location /api/products/ {
    proxy_pass http://product_service;
    proxy_cache api_cache;
    proxy_cache_key "$scheme$request_method$host$request_uri";
    proxy_cache_valid 200 5m;

    # 1. Защита от Stampede: пропускать к бэкенду только 1 параллельный запрос
    proxy_cache_lock on;
    proxy_cache_lock_timeout 3s;
    proxy_cache_lock_age 5s;

    # 2. Асинхронное фоновое обновление (Stale-While-Revalidate)
    proxy_cache_background_update on;
    proxy_cache_use_stale updating;

    # 3. Отказоустойчивость: отдача старого кэша при отказе бэкенда (Circuit Breaker)
    proxy_cache_use_stale error timeout invalid_header http_500 http_502 http_503 http_504;

    # 4. Условная ревалидация по 304 Not Modified
    proxy_cache_revalidate on;

    add_header X-Cache-Status $upstream_cache_status always;
}
```

Пояснение механики:
*   `proxy_cache_lock on;`: При истечении TTL сотни параллельных клиентов не обрушиваются на базу данных. Один клиент отправляется на бэкенд, остальные ждут до 3 секунд.
*   `proxy_cache_use_stale updating;`: Клиенты получают мгновенный ответ со статусом `UPDATING` из имеющейся копии, пока фоновый воркер скачивает новый контент.
*   `proxy_cache_use_stale error ...`: Если бэкенд вернул 502 Bad Gateway или упал по таймауту, Nginx не показывает клиенту ошибку, а возвращает закэшированную копию (`STALE`), гарантируя непрерывность сервиса.

---

### Сценарий 4: Селективный обход кэша через `map` (Bypass & No-Cache)

Директива `if` в контексте `location` в Nginx имеет архитектурные недостатки (If-is-Evil). Правильный промышленный подход управления директивами `proxy_cache_bypass` (не читать из кэша) и `proxy_no_cache` (не сохранять в кэш) — использование декларативных блоков `map` в контексте `http`:

```nginx
# Определение условий исключения из кэша
map $http_authorization $bypass_auth {
    default 0;
    "~.+"   1; # Если есть заголовок Authorization - обходить кэш
}

map $cookie_session_id $bypass_cookie {
    default 0;
    "~.+"   1; # Если установлена сессия - обходить кэш
}

map $http_pragma $bypass_pragma {
    default       0;
    "no-cache"    1; # Заголовок Pragma: no-cache от клиента
}
```

Применение в `location`:

```nginx
location /api/ {
    proxy_pass http://backend_pool;
    proxy_cache api_cache;

    # Кэш обходится, если хотя бы один флаг равен 1
    proxy_cache_bypass $bypass_auth $bypass_cookie $bypass_pragma $arg_nocache;
    proxy_no_cache     $bypass_auth $bypass_cookie;

    add_header X-Cache-Status $upstream_cache_status always;
}
```

---

### Сценарий 5: Раздача тяжелого контента через Slice Module

Модуль `ngx_http_slice_module` позволяет разбивать многогигабайтные файлы на независимые сегменты (например, по 10 МБ).

```nginx
proxy_cache_path /var/cache/nginx/media_cache
                  levels=1:2
                  keys_zone=media_zone:64m
                  inactive=7d
                  max_size=100g
                  use_temp_path=off;

server {
    listen 80;
    server_name cdn.example.internal;

    location /videos/ {
        proxy_pass http://storage_backend;
        proxy_cache media_zone;

        # Размер слайса
        slice 10m;

        # Обязательно: передача диапазона в бэкенд
        proxy_set_header Range $slice_range;

        # Обязательно: включение $slice_range в ключ кэширования
        proxy_cache_key "$scheme$request_method$host$uri$slice_range";

        # Поддержка 206 Partial Content
        proxy_cache_valid 200 206 7d;

        proxy_ignore_headers Set-Cookie;
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

---

### Сценарий 6: Персистентность кэш-индекса в Angie (`file=`)

В Angie 1.9+ параметр `file=` позволяет сохранять бинарный образ разделяемой памяти на диск при остановке сервера и мгновенно восстанавливать его при запуске. Это исключает длительное дисковое сканирование Cache Loader на серверах с миллионами закэшированных файлов.

```nginx
# Конфигурация для Angie
proxy_cache_path /var/cache/angie/proxy_cache
                  levels=1:2
                  keys_zone=prod_cache:128m
                  inactive=48h
                  max_size=150g
                  use_temp_path=off
                  file=/var/cache/angie/prod_cache.zone;
```

---

## Операции и команды

### Валидация и применение конфигурации

```bash
# Проверка синтаксиса и корректности путей cache_path
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Просмотр полной собранной конфигурации с директивами кэширования
nginx -T | grep -E 'proxy_cache_path|fastcgi_cache_path'
# → proxy_cache_path /var/cache/nginx/proxy_cache levels=1:2 keys_zone=api_cache:32m ...

# Перечитывание конфигурации без сброса соединений (Graceful Reload)
systemctl reload nginx
# → Job for nginx.service finished with result 'done'.
```

### Инспекция состояния диска и inode

```bash
# Проверка свободного места на точке монтирования кэша
df -h /var/cache/nginx
# → Filesystem                  Size  Used Avail Use% Mounted on
# → /dev/mapper/vg0-nginx_cache   50G   18G   32G  36% /var/cache/nginx

# Проверка использования дескрипторов inode (критично для миллионов мелких файлов)
df -i /var/cache/nginx
# → Filesystem                   Inodes  IUsed   IFree IUse% Mounted on
# → /dev/mapper/vg0-nginx_cache 3276800 421050 2855750   13% /var/cache/nginx

# Оценка физического размера каталога кэша
du -sh /var/cache/nginx/proxy_cache
# → 18G    /var/cache/nginx/proxy_cache
```

### Инспекция структуры закэшированного файла

```bash
# Поиск конкретного файла кэша на диске
find /var/cache/nginx/proxy_cache -type f | head -n 1
# → /var/cache/nginx/proxy_cache/7/c5/b7f5c2d3e4f6a7b8c9d0e1f2a3b4c567

# Просмотр служебного бинарного заголовка и оригинальных HTTP-заголовков Nginx
head -n 15 /var/cache/nginx/proxy_cache/7/c5/b7f5c2d3e4f6a7b8c9d0e1f2a3b4c567
# → ^E^@^@^@^@^@^@^@^P^@^@^@^@^@...
# → KEY: httpGETapi.example.internal/v1/catalog/items
# → HTTP/1.1 200 OK
# → Server: nginx
# → Date: Fri, 17 Oct 2026 11:20:00 GMT
# → Content-Type: application/json
# → Content-Length: 1024
```

### Безопасная очистка и ротация кэша (Operational Runbook)

#### 1. Выборочная инвалидация по URL (HTTP PURGE)

При настроенном модуле `ngx_cache_purge` (Nginx OSS) или встроенной директиве `proxy_cache_purge` (Angie):

```bash
# Отправка запроса PURGE на инвалидацию конкретного ресурса
curl -X PURGE -i http://127.0.0.1/v1/catalog/items
# → HTTP/1.1 200 OK
# → Content-Type: text/html
# → Content-Length: 265
# → <h2>Successful purge</h2>
```

#### 2. Фоновая очистка старых файлов без остановки сервиса

Для удаления невостребованных файлов без перезапуска Nginx и без блокировки файловой системы:

```bash
# Поиск и удаление файлов кэша, к которым не было обращений более 7 дней
find /var/cache/nginx/proxy_cache -type f -atime +7 -delete
# → Команда отрабатывает в фоне без блокировки процессов веб-сервера
```

#### 3. Экстренная полная очистка при переполнении диска

В случае исчерпания дискового пространства категорически запрещено удалять саму директорию `/var/cache/nginx` (команда `rm -rf /var/cache/nginx`), так как это удалит права доступа, и Nginx не сможет пересоздать структуру.

```bash
# Шаг 1. Перемещение наполненного каталога в сторону (атомарная операция)
mv /var/cache/nginx/proxy_cache /var/cache/nginx/proxy_cache_old

# Шаг 2. Создание нового чистого каталога с сохранением прав
mkdir -p /var/cache/nginx/proxy_cache
chown nginx:nginx /var/cache/nginx/proxy_cache
chmod 700 /var/cache/nginx/proxy_cache

# Шаг 3. Перезагрузка Nginx для очистки keys_zone в памяти
systemctl reload nginx
# → Nginx мгновенно переключается на пустую директорию

# Шаг 4. Безопасное асинхронное удаление старого каталога с диска
rm -rf /var/cache/nginx/proxy_cache_old
```

### Проверка статуса кэширования через клиентский запрос

```bash
# Первый запрос: ожидается MISS
curl -I -s http://api.example.internal/v1/catalog/items | grep -i X-Cache-Status
# → X-Cache-Status: MISS

# Второй запрос: ожидается HIT
curl -I -s http://api.example.internal/v1/catalog/items | grep -i X-Cache-Status
# → X-Cache-Status: HIT
```

---

## Устранение неполадок

### Сводная таблица типовых сбоев

| Симптом / Ошибка | Диагностика | Первопричина | Инженерное решение |
| :--- | :--- | :--- | :--- |
| `rename() failed (18: Invalid cross-device link)` | `grep "Invalid cross-device link" /var/log/nginx/error.log` | Временный путь `proxy_temp_path` и `proxy_cache_path` находятся на разных файловых системах | Добавить `use_temp_path=off;` в `proxy_cache_path` |
| `could not allocate node in cache keys zone` | `grep "could not allocate node" /var/log/nginx/error.log` | Исчерпан объем разделяемой памяти `keys_zone` из-за огромного числа объектов | Увеличить размер зоны памяти (например, с `32m` до `128m`) |
| Запросы всегда возвращают `MISS` или `BYPASS` | Проверка `curl -I`, аудит заголовков бэкенда | Бэкенд шлет `Set-Cookie`, `Cache-Control: private, no-cache`, или есть `Authorization` | Добавить `proxy_ignore_headers Set-Cookie Cache-Control;` и `proxy_hide_header Set-Cookie;` |
| Пиковая загрузка диска (100% IOPS) при старте | `iostat -xz 1`, `iotop -o` | Cache Loader сканирует миллионы файлов без ограничений по скорости | Настроить `loader_files`, `loader_sleep`, `loader_threshold` либо в Angie использовать `file=` |
| `No space left on device` при незаполненном `max_size` | `df -h /var/cache/nginx` и `df -i /var/cache/nginx` | Исчерпаны inode на файловой системе либо Cache Manager не успевает вычищать диск | Создать ФС с увеличенным пулом inode (`mkfs.xfs`) или уменьшить лимит `inactive` |
| Персональные данные одного пользователя отдаются другому | Пользователь видит чужой профиль / корзину | `Set-Cookie` был проигнорирован в общей зоне с авторизацией (Cache Poisoning) | Убрать кэширование с приватных путей, добавить обход по сессионной cookie |
| Всплеск `504 Gateway Timeout` при включенном `proxy_cache_lock` | `grep "upstream timed out" /var/log/nginx/error.log` | Бэкенд отвечает дольше `proxy_cache_lock_timeout`, очередь запросов сбрасывается | Оптимизировать ответ бэкенда или увеличить `proxy_cache_lock_timeout` |

### Разбор критических инцидентов

#### 1. Ошибка межсегментной ссылки `18: Invalid cross-device link`

*   **Лог ошибки:** `[crit] 1234#1234: *567 rename() "/var/lib/nginx/proxy/0/01/0000000010" to "/var/cache/nginx/proxy_cache/7/c5/b7f5c2..." failed (18: Invalid cross-device link)`
*   **Причина:** Директория `/var/cache/nginx` смонтирована на отдельном блочном диске или LVM-томе, а временные файлы пишутся на корневую систему `/var/lib/nginx`. Системный вызов ядра Linux `rename()` не может атомарно перемещать дескрипторы файлов между разными суперблоками файловых систем.
*   **Решение:** Отредактируйте директиву `proxy_cache_path`, добавив параметр `use_temp_path=off`:
    ```nginx
    proxy_cache_path /var/cache/nginx/proxy_cache levels=1:2 keys_zone=my_cache:32m use_temp_path=off;
    ```
    Выполните `nginx -t && systemctl reload nginx`.

#### 2. Переполнение разделяемой памяти `keys_zone`

*   **Лог ошибки:** `[alert] 1234#1234: *890 could not allocate node in cache keys zone "api_cache"`
*   **Причина:** Число уникальных закэшированных объектов превысило емкость выделенного размера `keys_zone` (например, выделено 10 МБ на 80 000 ключей, а в кэш поступило 200 000 уникальных URL). При нехватке памяти Nginx прекращает кэширование новых объектов и передает все запросы напрямую на бэкенд.
*   **Решение:**
    1. Рассчитайте необходимый размер зоны: $N_{\text{objects}} / 8000 \text{ MB}$. Для 500 000 объектов: $500000 / 8000 \approx 62.5 \text{ MB} \rightarrow 64\text{m}$.
    2. Увеличьте параметр: `keys_zone=api_cache:64m`.
    3. Выполните перезапуск `systemctl restart nginx` (изменение размера shared memory требует полного рестарта для переаллокации структуры ядром).

#### 3. Нулевой Cache Hit Ratio из-за заголовков бэкенда

*   **Симптом:** Все запросы в access-логах имеют статус `cache_status=MISS` или `cache_status=BYPASS`.
*   **Причина:** Бэкенд возвращает заголовок `Set-Cookie` (даже для анонимных пользователей) либо заголовок `Cache-Control: no-cache, private`. Согласно спецификации RFC 9111 Nginx по умолчанию защищает пользователей и не сохраняет такие ответы в разделяемый кэш.
*   **Решение:** Если контент публичный и не содержит персональных данных:
    ```nginx
    location /public/ {
        proxy_pass http://backend;
        proxy_cache api_cache;
        
        # Принудительно игнорировать директивы запрета кэша от бэкенда
        proxy_ignore_headers Set-Cookie Cache-Control Expires;
        
        # Скрыть заголовок Set-Cookie из ответа клиенту
        proxy_hide_header Set-Cookie;
    }
    ```

---

## Best Practices

1. **Изоляция хранилища на выделенный раздел:** Всегда монтируйте директорию кэша (`/var/cache/nginx`) на отдельный логический том (LVM) или выделенный NVMe-накопитель. Это исключает отказ всей операционной системы при заполнении диска.
2. **Атомарность записи (`use_temp_path=off`):** Всегда явно указывайте `use_temp_path=off` во всех директивах `proxy_cache_path` и `fastcgi_cache_path`. Это гарантирует отсутствие ошибок `EXDEV` и устраняет паразитные операции копирования между разделами.
3. **Оптимизация файловой системы (`noatime,nodiratime`):** При монтировании файловых систем с кэшем отключайте обновление временных меток доступа. Это продлевает ресурс SSD-дисков и устраняет задержки дискового контроллера.
4. **Резервирование inode на этапе форматирования:** Для хранилищ кэша на ext4 задавайте уменьшенный шаг байт на inode (`mkfs.ext4 -i 8192 /dev/...`) или используйте файловую систему XFS, которая динамически выделяет структуры inode по мере создания файлов.
5. **Предотвращение Cache Loader Stampede:** На высоконагруженных узлах с Nginx OSS настраивайте параметры плавного сканирования: `loader_files=200 loader_sleep=50ms loader_threshold=100ms`. В Angie используйте параметр `file=` для мгновенного сохранения и загрузки индекса из файла.
6. **Обязательная связка Stampede-защиты:** Для динамических ресурсов комбинируйте директивы `proxy_cache_lock on;`, `proxy_cache_use_stale updating error timeout;` и `proxy_cache_background_update on;`. Это обеспечивает непрерывную доступность сервиса при падении бэкендов.
7. **Разделение кэш-зон по типам трафика:** Не используйте одну общую зону памяти для всех сервисов. Создавайте независимые зоны: для статики (большой TTL, редкая ротация), для API (короткий TTL, агрессивный LRU) и для медиа-слайсов.
8. **Асинхронный ввод-вывод (`aio threads`):** На высоконагруженных инсталляциях с дисковым кэшем включайте пулы потоков:
   ```nginx
   aio threads=default;
   directio 10m;
   ```
   Это предотвращает блокировку рабочих процессов Nginx при чтении крупных файлов с диска.
9. **Защита эндпоинта PURGE:** Инвалидация кэша должна быть строго защищена на уровне сети (разрешена только локальному хосту `127.0.0.1` или доверенной подсети управления):
   ```nginx
   location ~ /purge(/.*) {
       allow 127.0.0.1;
       allow 10.0.0.0/8;
       deny all;
       proxy_cache_purge api_cache "$scheme$request_method$host$1";
   }
   ```
10. **Защита от утечки персональных данных:** Категорически запрещено добавлять `proxy_ignore_headers Set-Cookie;` на эндпоинтах личных кабинетов, оформления заказов и авторизации.

---

## Дополнительная информация

### Связанные темы

*   [Серверное кэширование (Proxy Cache) в Nginx и Angie](./proxy_caching.md) — детальный справочник по директивам `proxy_cache_*`, ключам кэширования и тонкой настройке заголовков.
*   [Клиентское кэширование (Browser Caching) в Nginx и Angie](./client_caching.md) — управление заголовками `Cache-Control`, `ETag`, Early Hints (HTTP 103) и Cache Busting.
*   [Микрокэширование (Microcaching) в Nginx и Angie](./microcaching.md) — техника кэширования динамики на ультракороткие сроки (1–5 секунд) на файловой системе `tmpfs`.
*   [Мониторинг кэширования в Nginx и Angie](./monitoring.md) — метрики Hit Ratio, Prometheus-экспортеры, парсинг `$upstream_cache_status` и алерты SRE.
*   [Оптимизация производительности Nginx и Angie](../nginx_performance_tuning.md) — тюнинг worker processes, event loop, сокетов и системных параметров Linux.
*   [Харденинг Nginx на уровне системы: systemd-юнит, SELinux, AppArmor](../../Security/nginx_systemd_selinux_hardening.md) — изоляция прав, ограничения ФС и контексты безопасности.
*   [Паттерны кэширования](../../../../Concepts/Caching/caching_patterns.md) — общие архитектурные паттерны (Cache-Aside, Read-Through, Write-Through).
*   [HTTP-кэширование: Механизмы и управление](../../../../Networking/Protocols/HTTP/http_caching.md) — протокольные механизмы и директивы RFC 9111.
