# FastCGI и PHP-FPM в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x / PHP 8.2–8.4

## Определения

*   **FastCGI (Fast Common Gateway Interface)** — открытый бинарный протокол клиент-серверного взаимодействия веб-сервера с сервером приложений. В отличие от классического CGI, процесс интерпретатора не запускается заново на каждый входящий запрос: долгоживущие процессы-воркеры удерживают соединение или слушают очередь, принимая структурированные бинарные фреймы (заголовки, метаданные, тело запроса) и возвращая поток ответа.
*   **PHP-FPM (FastCGI Process Manager)** — стандартный высокопроизводительный менеджер процессов PHP, реализующий серверную сторону протокола FastCGI. Управляет пулами рабочих процессов (`pool`), распределяет входящую нагрузку, изолирует права выполнения через системных пользователей и предоставляет механизмы автоматического перезапуска воркеров при авариях или утечках памяти.
*   **Unix Domain Socket (UDS)** — файл сокета межпроцессного взаимодействия (IPC) в файловой системе Linux (`AF_UNIX`). Обмен данными между Angie и PHP-FPM происходит напрямую через буферы ядра без прохождения сетевого стека, контрольных сумм TCP/IP и сетевых очередей.
*   **TCP-сокет (`AF_INET` / `AF_INET6`)** — сетевой сокет (IP-адрес и порт), обеспечивающий взаимодействие по протоколу TCP/IP. Используется для выноса PHP-FPM на выделенные хосты приложений или для взаимодействия между изолированными сетевыми пространствами (network namespaces).
*   **`SCRIPT_FILENAME` и `DOCUMENT_ROOT`** — критические параметры FastCGI, передаваемые сервером Angie в интерпретатор PHP. `SCRIPT_FILENAME` задает абсолютный путь к исполняемому `.php`-файлу в файловой системе хоста, на котором выполняется PHP-FPM. При ошибке разрешения этого пути PHP-FPM возвращает статус `404 Not Found` с телом `File not found` или ошибку `Primary script unknown`.
*   **`$realpath_root`** — встроенная переменная Angie/Nginx, разрешающая все символические ссылки (symlinks) в пути `$document_root` до их абсолютного физического канонического пути. Критически важна в production-эксплуатации при атомарных релизах (symlink-based deployment) во избежание рассинхронизации OPcache.
*   **Буферизация FastCGI (`fastcgi_buffering`)** — архитектурный режим работы Angie, при котором веб-сервер максимально быстро считывает ответ от воркера PHP-FPM в свои внутренние буферы оперативной памяти (или временный файл на диске), немедленно освобождая рабочий процесс PHP для обработки следующего запроса, а отдачу клиенту ведет со скоростью канала пользователя.
*   **Пул соединений Keepalive (`fastcgi_keep_conn`)** — механизм удержания открытых FastCGI-соединений между Angie и PHP-FPM в контексте директивы `upstream`, предотвращающий постоянную процедуру открытия и закрытия TCP/UDS-соединений на каждый HTTP-запрос.
*   **FastCGI Cache (`fastcgi_cache`)** — встроенная подсистема разделяемой памяти и дискового кэширования ответов FastCGI в Angie, позволяющая отдавать динамические страницы без обращения к интерпретатору PHP.
*   **Зона статуса (`status_zone`)** — именованная область разделяемой памяти в Angie, собирающая детальную статистику по количеству запросов, кодам ответов, объемам трафика и задержкам на уровне виртуального сервера, пути (`location`) или группы серверов (`upstream`) для экспорта через консоль управления или Prometheus API.

---

## Базовые концепции и архитектура

### 1. Жизненный цикл обработки запроса в Angie и протокол FastCGI

Взаимодействие веб-сервера Angie с пулом процессов PHP-FPM строится по модели обратного шлюза (Gateway/Proxy):

```
[Клиент (Браузер / API)]
         │ HTTP/1.1, HTTP/2, HTTP/3 (TLS)
         ▼
[Angie Worker (пользователь 'angie')]
         │
         ├── 1. Сопоставление location (например, 'location ~ \.php$')
         ├── 2. Проверка существования скрипта: 'try_files $uri =404;'
         ├── 3. Формирование бинарных записей FastCGI (FCGI_BEGIN_REQUEST, FCGI_PARAMS, FCGI_STDIN)
         ▼
[Unix Domain Socket: /run/php/php8.4-fpm.sock  ИЛИ  TCP: 127.0.0.1:9000]
         │
         ▼
[PHP-FPM Master Process (root)]
         │ Маршрутизация в свободный воркер пула
         ▼
[PHP-FPM Worker Process (пользователь 'www-data')]
         │ Исполнение PHP-кода (OPcache, БД, файловая система)
         │ Генерация заголовков и тела ответа
         ▼
[Поток FCGI_STDOUT / FCGI_STDERR]
         │
         ▼
[Angie Worker] ─── Буферизация / Сжатие / fastcgi_cache ───► [Клиент]
```

Протокол FastCGI оперирует бинарными записями фиксированного формата (заголовок 8 байт + полезная нагрузка до 65535 байт):
1. **`FCGI_BEGIN_REQUEST`** — инициализация запроса с указанием роли (для PHP-FPM всегда роль `FCGI_RESPONDER`, код 1) и флагов (например, `FCGI_KEEP_CONN`).
2. **`FCGI_PARAMS`** — передача пар ключ-значение переменных окружения (`SCRIPT_FILENAME`, `QUERY_STRING`, `REQUEST_METHOD`, `HTTP_*` и т.д.).
3. **`FCGI_STDIN`** — передача тела входящего HTTP-запроса (POST/PUT payload). Завершается пустой записью `FCGI_STDIN`.
4. **`FCGI_STDOUT`** — поток HTTP-заголовков и тела ответа, генерируемый скриптом PHP.
5. **`FCGI_STDERR`** — поток сообщений об ошибках PHP, логируемый Angie в `error.log`.
6. **`FCGI_END_REQUEST`** — маркер завершения обработки запроса со статусом выполнения (`appStatus`) и причиной протокольного завершения (`protocolStatus`).

### 2. Транспортный уровень: Unix Domain Socket vs TCP-сокет

Выбор метода передачи данных определяет производительность, утилизацию CPU и архитектурную гибкость:

| Критерий | Unix Domain Socket (`unix:/path/to.sock`) | Локальный TCP (`127.0.0.1:9000`) | Сетевой TCP (Удаленный хост) |
| :--- | :--- | :--- | :--- |
| **Производительность (RPS)** | Максимальная (выше на 15–25%) | Средняя | Зависит от сети и RTT |
| **Накладные расходы CPU** | Минимальные (нет TCP-стека, контрольных сумм) | Выше (обработка loopback-интерфейса) | Заметные (сетевой стек, прерывания) |
| **Ограничения ресурсов** | Лимитируется дескрипторами и памятью ядра | Лимитируется диапазоном эфемерных портов | Лимитируется пропускной способностью сети |
| **Отказоустойчивость** | Только в пределах одной ОС | Только в пределах одной ОС | Горизонтальное масштабирование |
| **Безопасность** | Права доступа POSIX на файл сокета | Firewall (iptables/nftables), привязка к IP | Требуется сегментация сети, TLS/mTLS |

#### Проблема прав доступа к Unix-сокету в Angie

В дистрибутивах Debian/Ubuntu классический Nginx и PHP-FPM часто используют одного системного пользователя `www-data`. Официальные пакеты **Angie** поставляются и функционируют от системного пользователя и группы `angie` (в RHEL/Rocky — пользователь `angie`, в то время как PHP-FPM работает от `apache` или `nobody`).

Если сокет `/run/php/php8.4-fpm.sock` создан с правами `0660` владельца `www-data:www-data`, процесс Angie получит ошибку:
```
[crit] ... connect() to unix:/run/php/php8.4-fpm.sock failed (13: Permission denied) while connecting to upstream
```
**Системное решение:**
1. Добавить пользователя `angie` в группу владельца сокета: `usermod -aG www-data angie`.
2. Либо настроить права создания сокета в пуле PHP-FPM (`/etc/php/8.4/fpm/pool.d/www.conf`):
   ```ini
   listen = /run/php/php8.4-fpm.sock
   listen.owner = www-data
   listen.group = angie
   listen.mode = 0660
   ```

### 3. Архитектура буферизации FastCGI

По умолчанию в Angie включена буферизация (`fastcgi_buffering on;`). Это ключевой механизм защиты SRE-инфраструктуры от истощения воркеров PHP-FPM.

**Почему буферизация критична:**
Воркер PHP-FPM является синхронным однопоточным процессом (в подавляющем большинстве инсталляций). Если медленный клиент на канале 2G/EDGE скачивает динамически сгенерированный PDF-отчет размером 10 МБ в течение 60 секунд без буферизации (`fastcgi_buffering off;`), воркер PHP-FPM будет заблокирован все 60 секунд. При пуле `pm.max_children = 50` всего 50 медленных клиентов полностью парализуют приложение.

При включенной буферизации:
1. PHP-FPM генерирует ответ и отдает его со скоростью памяти в сокет ядра Linux.
2. Angie вычитывает весь ответ в свои буферы за миллисекунды.
3. Процесс PHP-FPM освобождается и сразу переходит к обработке следующего запроса.
4. Воркер Angie асинхронно через epoll/kqueue стримит ответ медленному клиенту.

#### Иерархия буферов FastCGI

```
Ответ от PHP-FPM
       │
       ▼
[fastcgi_buffer_size] (Буфер для заголовков ответа)
       │
       ├─► Если заголовки больше fastcgi_buffer_size ──► 502 Bad Gateway ("upstream sent too big header")
       │
       ▼
[fastcgi_buffers N SIZE] (Пул буферов для тела ответа в RAM)
       │
       ├─► Если тело умещается в N * SIZE ─────────────► Отдача клиенту из RAM
       │
       ▼
[fastcgi_temp_path] (Сброс во временный файл на диске)
       │ (Ограничивается fastcgi_max_temp_file_size)
       │
       ▼
[Клиент]
```

*   **`fastcgi_buffer_size`** — размер одного буфера, выделяемого **исключительно** под чтение заголовков ответа FastCGI. Если приложение передает огромные cookies, массивные заголовки отладки или тяжелые заголовки сессий, и они превышают этот размер, Angie разрывает соединение с кодом 502.
*   **`fastcgi_buffers number size`** — количество и размер буферов для считывания тела ответа. Например, `fastcgi_buffers 16 16k;` выделяет до 256 КБ оперативной памяти на запрос.
*   **`fastcgi_busy_buffers_size`** — максимальный объем буферов, которые могут находиться в состоянии отправки клиенту, пока остальные буферы продолжают наполняться из апстрима. Должен быть меньше суммарного объема `fastcgi_buffers` минимум на один-два буфера (стандартно `размер_одного_буфера × 2`).
*   **`fastcgi_temp_file_write_size`** — лимит порции записи во временный файл при исчерпании буферов в оперативной памяти.

### 4. Сквозная координация таймаутов (Timeout Chain)

Несогласованные таймауты между компонентами стека — частая причина скрытых инцидентов, утечек ресурсов и накопления зомби-процессов:

```
[Клиент] ─────────► [Angie] ──────────────────────────► [PHP-FPM Worker] ──────────► [БД / Внешний API]
  client_header_timeout   fastcgi_connect_timeout (10s)    max_execution_time (30s)    wait_timeout (5s)
  client_body_timeout     fastcgi_send_timeout (60s)       request_terminate_timeout (35s)
                          fastcgi_read_timeout (60s)
```

**Правила согласования для SRE/Sysadmin:**
1.  **`fastcgi_connect_timeout` (по умолчанию 60s):** Рекомендуется снижать до `5s–10s`. Локальный сокет или локальный сетевой апстрим обязан отвечать на handshake мгновенно. Если соединение не устанавливается за 5 секунд, апстрим перегружен либо завис.
2.  **`fastcgi_read_timeout` vs `max_execution_time` vs `request_terminate_timeout`:**
    *   Лимит выполнения PHP-скрипта (`max_execution_time = 30`) должен быть **меньше**, чем таймаут ожидания в веб-сервере (`fastcgi_read_timeout = 60s`).
    *   Аварийный убийца зависших воркеров FPM (`request_terminate_timeout = 35s`) в пуле FPM должен срабатывать, если скрипт проигнорировал `max_execution_time` (например, завис в системном вызове ввода-вывода или бесконечном цикле в C-расширении).
    *   Если `fastcgi_read_timeout` (например, 20s) меньше `max_execution_time` (60s), клиент получит ошибку `504 Gateway Timeout`, но процесс PHP продолжит бессмысленно молотить на сервере еще 40 секунд, сжигая CPU и удерживая соединения с БД.

### 5. Развертывание приложений, атомарные релизы и переменная `$realpath_root`

При использовании систем атомарного деплоя (Deployer, Capistrano, symlink-релизы в пайплайнах CI/CD) структура каталогов на сервере выглядит следующим образом:
```
/var/www/app/
├── current -> /var/www/app/releases/20261014190000
└── releases/
    ├── 20261014180000/
    └── 20261014190000/
        └── public/
            └── index.php
```

При переключении релиза утилита атомарно меняет символическую ссылку `/var/www/app/current` на новый каталог релиза.

**Ловушка `$document_root`:**
Если в конфигурации Angie указано:
```nginx
fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
```
Веб-сервер передает в PHP-FPM строку `/var/www/app/current/public/index.php`.
PHP-FPM и механизм OPcache кэшируют байт-код по пути файла. Поскольку символическая ссылка разрешается внутри PHP через внутренний кэш путей (`realpath_cache`), воркеры PHP-FPM продолжают исполнять код старого релиза вплоть до сброса `realpath_cache_ttl` или полного перезапуска пула, что приводит к неконсистентности при деплое.

**Стандарт SRE:**
Всегда используйте `$realpath_root`:
```nginx
root /var/www/app/current/public;
fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
fastcgi_param DOCUMENT_ROOT $realpath_root;
```
Переменная `$realpath_root` заставляет Angie самостоятельно разрешить символическую ссылку в реальный путь ядра (`/var/www/app/releases/20261014190000/public`) до передачи параметров в FastCGI. PHP-FPM сразу видит новый путь к файлу и мгновенно переключается на новый релиз без очистки кэшей.

---

## Практические сценарии

### Сценарий 1: Высокопроизводительный продакшен-хост с Unix-сокетом (Laravel/Symfony)

Базовый эталонный виртуальный хост с полной изоляцией привилегий, переменной `$realpath_root`, встроенной зоной мониторинга `status_zone` и защитой служебных каталогов.

```nginx
# /etc/angie/conf.d/app.example.com.conf

server {
    listen 443 ssl reuseport;
    listen [::]:443 ssl;
    server_name app.example.com;

    # Зона мониторинга виртуального хоста в Angie
    status_zone app_example_com_vhost;

    # Корневой каталог через symlink
    root /var/www/app/current/public;
    index index.php;

    # Сертификаты TLS
    ssl_certificate /etc/ssl/certs/app.example.com.crt;
    ssl_certificate_key /etc/ssl/private/app.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Логирование со временем ответа FastCGI
    access_log /var/log/angie/app_access.log combined_upstream;
    error_log /var/log/angie/app_error.log warn;

    # Безопасность: запрет доступа к служебным файлам и каталогам
    location ~ /\.(?!well-known).* {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Оптимизация отдачи статических файлов (без задействования PHP)
    location ~* \.(jpg|jpeg|gif|png|css|js|ico|webp|avif|svg|woff2|ttf)$ {
        expires 30d;
        add_header Cache-Control "public, no-transform, immutable";
        access_log off;
        log_not_found off;
        try_files $uri =404;
    }

    # Фронт-контроллер: перенаправление всех запросов в index.php
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    # Обработка PHP-скриптов
    location ~ \.php$ {
        # Защита от исполнения несуществующих файлов
        try_files $uri =404;

        # Передача запроса в Unix-сокет
        fastcgi_pass unix:/run/php/php8.4-fpm.sock;
        fastcgi_index index.php;

        # Подключение стандартных параметров
        include fastcgi_params;

        # Разрешение символических ссылок для нулевого простоя при релизах
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT $realpath_root;

        # Метаданные HTTPS и проксирования
        fastcgi_param HTTPS on;
        fastcgi_param HTTP_X_REQUEST_ID $request_id;

        # Тонкая настройка буферов FastCGI
        fastcgi_buffering on;
        fastcgi_buffer_size 16k;
        fastcgi_buffers 16 16k;
        fastcgi_busy_buffers_size 32k;
        fastcgi_temp_file_write_size 32k;

        # Таймауты FastCGI
        fastcgi_connect_timeout 5s;
        fastcgi_send_timeout 60s;
        fastcgi_read_timeout 60s;

        # Скрытие внутренней информации интерпретатора
        fastcgi_hide_header X-Powered-By;
    }
}
```

### Сценарий 2: Отказоустойчивый пул FastCGI по TCP с балансировкой и Keepalive

Используется для масштабирования PHP-FPM на несколько серверов приложений или выделенный кластер обработки.

```nginx
# /etc/angie/conf.d/php_cluster.conf

upstream php_fpm_cluster {
    # Зона разделяемой памяти для синхронизации состояния воркеров Angie
    zone php_fpm_cluster 128k;

    # Серверы пула PHP-FPM
    server 10.10.1.11:9000 max_fails=3 fail_timeout=10s weight=2;
    server 10.10.1.12:9000 max_fails=3 fail_timeout=10s weight=1;
    server 10.10.1.13:9000 backup;

    # Удержание постоянных соединений к бэкендам FastCGI
    keepalive 32;
}

server {
    listen 80;
    server_name api.example.com;

    status_zone api_vhost;
    root /var/www/api/current/public;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        try_files $uri =404;

        fastcgi_pass php_fpm_cluster;

        # Включение удержания FastCGI-соединений в апстриме
        fastcgi_keep_conn on;

        # Повтор запроса на другой сервер кластера при сетевых сбоях
        fastcgi_next_upstream error timeout invalid_header http_500 http_503;
        fastcgi_next_upstream_tries 3;
        fastcgi_next_upstream_timeout 10s;

        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT $realpath_root;
        fastcgi_param HTTP_X_REQUEST_ID $request_id;

        fastcgi_connect_timeout 2s;
        fastcgi_read_timeout 30s;
    }
}
```

> [!IMPORTANT]
> При использовании TCP-пула на удаленных хостах параметр `SCRIPT_FILENAME` передает путь к файлу **в файловой системе сервера PHP-FPM**, а не хоста Angie. Если пути к коду различаются, жестко зафиксируйте каталог в `fastcgi_param SCRIPT_FILENAME /srv/app/public$fastcgi_script_name;`.

### Сценарий 3: Роутинг с `PATH_INFO` и REST API

Для приложений (на базе legacy-фреймворков или API), где единый исполняемый скрипт принимает подпути вида `/api/v1/users` через `PATH_INFO`.

```nginx
location ~ ^/api/(.+\.php)(/.*)?$ {
    # Ограничение доступа только к существующему файлу
    try_files $1 =404;

    # Расщепление URI на имя скрипта ($1) и остаточный путь ($2)
    fastcgi_split_path_info ^/api/(.+\.php)(/.*)$;

    fastcgi_pass unix:/run/php/php8.4-fpm.sock;
    include fastcgi_params;

    fastcgi_param SCRIPT_FILENAME $realpath_root/$fastcgi_script_name;
    fastcgi_param PATH_INFO $fastcgi_path_info;
    fastcgi_param PATH_TRANSLATED $realpath_root$fastcgi_path_info;
}
```

> [!WARNING]
> Никогда не используйте ненадежные регулярные выражения в `fastcgi_split_path_info` без проверки существования файла через `try_files $uri =404;`. В противном случае обращение вида `/uploads/avatar.jpg/index.php` приведет к интерпретации картинки как PHP-скрипта (уязвимость CVE-2019-11043 и аналогичные векторы RCE).

### Сценарий 4: Микрокэширование FastCGI (`fastcgi_cache`) и защита от Cache Stampede

Микрокэширование динамических ответов на 1–5 секунд позволяет справляться с десятикратными всплесками нагрузки без деградации времени отклика.

```nginx
# В контексте http: объявление дисковой зоны кэша
# keys_zone=NAME:SIZE (1 МБ ключей хранит метаданные ~8000 страниц)
fastcgi_cache_path /var/cache/angie/fcgi
                   levels=1:2
                   keys_zone=FCGI_CACHE:32m
                   max_size=2g
                   inactive=1h
                   use_temp_path=off;

# Определение условий отключения кэша (авторизованные пользователи, POST/PUT запросы)
map $request_method $no_cache_method {
    default 0;
    POST    1;
    PUT     1;
    DELETE  1;
}

map $http_cookie $no_cache_cookie {
    default 0;
    ~*PHPSESSID 1;
    ~*wordpress_logged_in 1;
    ~*remember_token 1;
}

server {
    listen 80;
    server_name blog.example.com;
    root /var/www/blog;

    location ~ \.php$ {
        try_files $uri =404;
        fastcgi_pass unix:/run/php/php8.4-fpm.sock;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;

        # Подключение зоны кэширования
        fastcgi_cache FCGI_CACHE;
        fastcgi_cache_key "$request_method$scheme$host$request_uri";

        # Время жизни кэша для успешных ответов и редиректов
        fastcgi_cache_valid 200 301 302 10m;
        fastcgi_cache_valid 404 1m;

        # Защита от эффекта собачьей стаи (Cache Stampede / Dogpile effect):
        # Только один процесс идет в бэкенд за свежим кэшем, остальные ждут
        fastcgi_cache_lock on;
        fastcgi_cache_lock_timeout 5s;

        # Отдача устаревшего кэша при обновлении или аварии бэкенда
        fastcgi_cache_use_stale error timeout updating http_500 http_503;
        fastcgi_cache_background_update on;

        # Условия пропуска кэша
        set $skip_cache 0;
        if ($no_cache_method) { set $skip_cache 1; }
        if ($no_cache_cookie) { set $skip_cache 1; }
        if ($http_authorization) { set $skip_cache 1; }

        fastcgi_cache_bypass $skip_cache;
        fastcgi_no_cache $skip_cache;

        # Диагностический заголовок статуса кэша
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

### Сценарий 5: Сквозная безопасность и изоляция каталогов загрузок

Жесткое разделение контента исключает возможность исполнения произвольного кода (RCE) злоумышленником при загрузке вредоносных файлов через CMS.

```nginx
# Запрет обработки PHP в каталогах пользовательских файлов
location ^~ /uploads/ {
    # Директива ^~ отключает проверку любых последующих регулярных выражений!
    root /var/www/app/storage;
    expires 7d;
    add_header X-Content-Type-Options "nosniff" always;

    # Запрет выполнения скриптов любых типов
    types {
        text/plain php php3 php4 php5 php7 php8 phtml pht;
    }

    try_files $uri =404;
}

# Блокировка доступа к чувствительным файлам конфигурации и зависимостей
location ~* (\.env|composer\.(json|lock)|package\.(json|lock)|\.git|\.yml|\.yaml|\.ini)$ {
    deny all;
    access_log off;
    log_not_found off;
}
```

### Сценарий 6: Наблюдаемость, сквозной трейсинг и статусная страница FPM

Конфигурация сквозного мониторинга, связывающего логи Angie, статус пулов PHP-FPM и внутренние счетчики производительности.

#### 1. Формат расширенного лога Angie с метриками FastCGI

В блоке `http` конфигурации `/etc/angie/angie.conf`:
```nginx
log_format combined_upstream '$remote_addr - $remote_user [$time_local] '
                             '"$request" $status $body_bytes_sent '
                             '"$http_referer" "$http_user_agent" '
                             'rt=$request_time '
                             'urt=$upstream_response_time '
                             'uct=$upstream_connect_time '
                             'uht=$upstream_header_time '
                             'us=$upstream_status '
                             'req_id=$request_id';
```

#### 2. Защищенный прокси к странице статуса PHP-FPM

В пуле PHP-FPM (`/etc/php/8.4/fpm/pool.d/www.conf`):
```ini
pm.status_path = /fpm_status
ping.path = /fpm_ping
ping.response = pong
```

В виртуальном хосте Angie:
```nginx
# Защищенный служебный сервер (локальный порт 8080 для Prometheus/Zabbix)
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    access_log off;

    # Статус и пинг пула FPM
    location ~ ^/(fpm_status|fpm_ping)$ {
        allow 127.0.0.1;
        deny all;

        fastcgi_pass unix:/run/php/php8.4-fpm.sock;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $fastcgi_script_name;
    }

    # Встроенный API статистики Angie
    location /status/ {
        angie_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

---

## Операции и команды

### 1. Проверка синтаксиса и управление процессами

```bash
# Валидация конфигурации Angie перед перезагрузкой
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Бесшовная перезагрузка конфигурации Angie без разрыва соединений
sudo systemctl reload angie

# Проверка синтаксиса конфигурации пулов PHP-FPM
sudo php-fpm8.4 -t
# → [14-Oct-2026 19:10:00] NOTICE: configuration file /etc/php/8.4/fpm/php-fpm.conf test is successful

# Мягкая перезагрузка пула PHP-FPM (сигнал SIGUSR2 рабочим процессам)
sudo systemctl reload php8.4-fpm
```

### 2. Проверка сокета и диагностика прав доступа

```bash
# Проверка типа сокета, владельца и прав доступа
ls -la /run/php/php8.4-fpm.sock
# → srw-rw---- 1 www-data www-data 0 Oct 14 18:00 /run/php/php8.4-fpm.sock

# Проверка членства пользователя angie в группе www-data
id angie
# → uid=998(angie) gid=998(angie) groups=998(angie),33(www-data)

# Проверка очереди сокета в ядре Linux (Send-Q и Recv-Q)
ss -l -x -p | grep php
# → u_str LISTEN 0 511 /run/php/php8.4-fpm.sock 14210 * 0 users:(("php-fpm8.4",pid=1234,fd=7))
```

### 3. Прямой опрос сокета FastCGI через cgi-fcgi

Утилита `cgi-fcgi` (пакет `libfcgi-bin` или `libfcgi0ldbl`) позволяет тестировать доступность и ответы PHP-FPM в обход веб-сервера:

```bash
# Отправка тестового запроса напрямую в Unix-сокет
SCRIPT_FILENAME=/var/www/app/current/public/index.php \
REQUEST_METHOD=GET \
cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock
# → Status: 200 OK
# → Content-Type: text/html; charset=UTF-8
# → 
# → <!DOCTYPE html>...

# Проверка страницы статуса FPM через TCP-порт
SCRIPT_FILENAME=/fpm_status \
QUERY_STRING="json&full" \
REQUEST_METHOD=GET \
cgi-fcgi -bind -connect 127.0.0.1:9000
# → {"pool":"www","process manager":"dynamic","start time":1728921600,"accepted conn":12840,...}
```

### 4. Опрос страницы статуса PHP-FPM через HTTP

```bash
# Получение статуса в формате JSON
curl -s "http://127.0.0.1:8080/fpm_status?json"
# → {"pool":"www","process manager":"dynamic","start time":1728921600,"accepted conn":14520,"listen queue":0,"max listen queue":2,"listen queue len":511,"idle processes":8,"active processes":2,"total processes":10,"max active processes":12,"max children reached":0}

# Получение статуса в нативном формате OpenMetrics (поддерживается с PHP 8.1+)
curl -s "http://127.0.0.1:8080/fpm_status?openmetrics"
# → # HELP phpfpm_up State of the php-fpm daemon
# → # TYPE phpfpm_up gauge
# → phpfpm_up{pool="www"} 1
# → # HELP phpfpm_active_processes Number of active processes
# → # TYPE phpfpm_active_processes gauge
# → phpfpm_active_processes{pool="www"} 2
# → # HELP phpfpm_listen_queue Number of requests in the listen queue
# → # TYPE phpfpm_listen_queue gauge
# → phpfpm_listen_queue{pool="www"} 0
```

### 5. Мониторинг FastCGI-апстримов через API Angie

```bash
# Просмотр статистики всех апстрим-пулов через REST API Angie
curl -s "http://127.0.0.1:8080/status/http/upstreams/" | jq .
# → {
# →   "php_fpm_cluster": {
# →     "peers": {
# →       "10.10.1.11:9000": { "state": "up", "requests": 54201, "responses": { "2xx": 53900, "5xx": 12 }, ... },
# →       "10.10.1.12:9000": { "state": "up", "requests": 27100, "responses": { "2xx": 27050, "5xx": 4 }, ... }
# →     }
# →   }
# → }
```

---

## Устранение неисправностей

### Сводная таблица типовых ошибок FastCGI в Angie

| Код / Лог ошибки в `error.log` | Корневая причина (Root Cause) | Алгоритм диагностики и устранения |
| :--- | :--- | :--- |
| **502 Bad Gateway**<br>`connect() to unix:... failed (13: Permission denied)` | Пользователь процесса `angie` не имеет прав доступа к сокету или каталогу `/run/php/`. | Выполнить `sudo usermod -aG www-data angie`. Проверить `listen.mode = 0660` и `listen.group = angie` в `/etc/php/8.4/fpm/pool.d/www.conf`. Перезапустить службу `php8.4-fpm`. |
| **502 Bad Gateway**<br>`connect() to ... failed (111: Connection refused)` | Сервис `php-fpm` остановлен, аварийно завершился либо слушает другой TCP-порт/путь сокета. | Проверить `systemctl status php8.4-fpm`. Сверить директиву `listen =` в пуле с адресом в `fastcgi_pass`. Проверить журнал `journalctl -u php8.4-fpm -e`. |
| **502 Bad Gateway**<br>`connect() failed (11: Resource temporarily unavailable)` | Переполнение очереди входящих соединений сокета (`listen queue`). Пул воркеров заблокирован. | Увеличить `net.core.somaxconn` в `/etc/sysctl.conf` и `listen.backlog = 4096` в пуле FPM. Увеличить `pm.max_children`. Проверить `listen queue` в `/fpm_status`. |
| **502 Bad Gateway**<br>`upstream prematurely closed connection while reading response header` | Воркер PHP-FPM упал во время обработки (Segfault, OOM Killer, превышение `request_terminate_timeout`). | 1. Проверить `dmesg -T \| grep -i oom` на предмет убийства воркера ядром.<br>2. Проверить журнал ошибок PHP: `cat /var/log/php8.4-fpm.log`.<br>3. Сверить `request_terminate_timeout` в пуле с длительностью запроса. |
| **502 Bad Gateway**<br>`upstream sent too big header while reading response header` | Объем HTTP-заголовков ответа превысил `fastcgi_buffer_size`. Часто вызвано массивными `Set-Cookie` или дампом отладочных данных. | Увеличить размер буфера заголовка в блоке `location`: `fastcgi_buffer_size 32k;` и пропорционально `fastcgi_busy_buffers_size 64k;`. |
| **504 Gateway Timeout**<br>`upstream timed out (110: Connection timed out)` | Запрос выполнялся дольше, чем лимит ожидания веб-сервера `fastcgi_read_timeout`. | 1. Найти медленный скрипт в `slowlog` PHP-FPM (`/var/log/php8.4-fpm/slowlog`).<br>2. Проверить блокировки в БД (`SHOW FULL PROCESSLIST;`) или зависание внешних API.<br>3. Если операция легитимно долгая (экспорт отчета), точечно поднять `fastcgi_read_timeout 300s;` в выделенном `location`. |
| **404 Not Found**<br>`Primary script unknown` | PHP-FPM не может найти скрипт на диске по пути `SCRIPT_FILENAME`. Отсутствует `try_files $uri =404;`. | 1. Добавить `try_files $uri =404;` перед `fastcgi_pass`.<br>2. Сверить `$document_root` и путь к файлу на сервере PHP-FPM.<br>3. При использовании симлинков заменить `$document_root` на `$realpath_root`. |
| **403 Forbidden**<br>`directory index of "/var/www/..." is forbidden` | Запрос к корневому URL каталога без указания индексного файла или отсутствие файла `index.php`. | Проверить директиву `index index.php;` в блоке `server` или `location /`. Проверить права на чтение каталога пользователю `angie`. |

### Диагностика глубоких аварийных ситуаций

#### 1. Исчерпание пула воркеров PHP-FPM (`max children reached`)

Признак в журнале `/var/log/php8.4-fpm.log`:
```
WARNING: [pool www] server reached pm.max_children setting (40), consider raising it
```
Клиенты начинают испытывать задержки, запросы скапливаются в `listen queue`, после чего Angie возвращает ошибку 502 или 504.

**Расчет лимитов памяти для SRE:**
```bash
# Определение среднего объема RSS оперативной памяти одного воркера PHP-FPM (в МБ)
ps --no-headers -o rss -C php-fpm8.4 | awk '{sum+=$1; count++} END {printf "Средняя память на воркер: %.2f MB\n", (sum/count)/1024}'
# → Средняя память на воркер: 48.50 MB

# Расчет безопасного pm.max_children:
# (Общий объем RAM - Память ОС и буферов ядра - Память Angie - Кэш БД) / Средняя память воркера
# Пример для выделенного сервера приложений с 8 ГБ RAM:
# (8192 MB - 1024 MB ОС - 1024 MB Opcache/Буферы) / 50 MB ≈ 122 воркера.
```

В пуле `/etc/php/8.4/fpm/pool.d/www.conf`:
```ini
pm = dynamic
pm.max_children = 120
pm.start_servers = 20
pm.min_spare_servers = 10
pm.max_spare_servers = 30
pm.max_requests = 1000
```
Параметр `pm.max_requests = 1000` принудительно перезапускает рабочий процесс после обслуживания 1000 запросов, полностью ликвидируя утечки памяти в сторонних расширениях и фреймворках.

#### 2. Зависания скриптов и диагностика Slowlog

Включение отслеживания медленных запросов в `/etc/php/8.4/fpm/pool.d/www.conf`:
```ini
request_slowlog_timeout = 3s
slowlog = /var/log/php8.4-fpm/slowlog
request_terminate_timeout = 30s
```

Анализ трейсов в slowlog:
```bash
tail -n 25 /var/log/php8.4-fpm/slowlog
# → [14-Oct-2026 19:15:22]  [pool www] pid 24102
# → script_filename = /var/www/app/releases/20261014190000/public/index.php
# → [0x00007f3d24a08120] curl_exec() /var/www/app/releases/.../Services/ExternalApi.php:45
# → [0x00007f3d24a08080] request() /var/www/app/releases/.../Http/Client.php:112
```
Трейс однозначно указывает на блокирующий сетевой вызов `curl_exec()` без таймаута во внешнем сервисе.

---

## Лучшие практики

1.  **Применение `$realpath_root` вместо `$document_root`:**
    Всегда настраивайте `fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;` и `fastcgi_param DOCUMENT_ROOT $realpath_root;`. Это предотвращает рассинхронизацию `realpath_cache` и байт-кода OPcache при атомарных переключениях символических ссылок релизов.
2.  **Защита от RCE через `try_files $uri =404;`:**
    Любой блок `location ~ \.php$` обязан содержать валидацию существования файла на диске `try_files $uri =404;`. В конфигурации `php.ini` обязательно установите параметр `cgi.fix_pathinfo = 0`.
3.  **Изоляция каталогов загрузок (Upload Hardening):**
    Для пользовательских каталогов (`/uploads/`, `/storage/`, `/media/`) используйте модификатор `^~`: `location ^~ /uploads/ { ... }`. Это на корню предотвращает проверку регулярных выражений PHP для загруженных файлов, исключая исполнение бэкдоров под видом изображений.
4.  **Удержание соединений к апстримам (`fastcgi_keep_conn on;`):**
    При проксировании FastCGI по TCP в блоке `upstream` объединяйте директиву `keepalive 32;` с параметром `fastcgi_keep_conn on;` внутри `location`. Это исключает накладные расходы на TCP-handshake (SYN/ACK) и снижает нагрузку на стек ядра при высоком RPS.
5.  **Сквозной Request ID (`$request_id`):**
    Передавайте внутренний идентификатор запроса Angie в FastCGI через `fastcgi_param HTTP_X_REQUEST_ID $request_id;`. Логируйте его в `combined_upstream` веб-сервера и перехватывайте в приложении для вывода в журнал PHP. Это позволяет мгновенно сопоставлять сетевую ошибку 502/504 в веб-сервере с конкретным вызовом в приложении.
6.  **Тюнинг очередей сокетов ядра Linux:**
    Для высоконагруженных систем настройте размер очереди сокетов на уровне ядра в `/etc/sysctl.d/99-fastcgi.conf`:
    ```ini
    net.core.somaxconn = 4096
    net.ipv4.tcp_max_syn_backlog = 4096
    ```
    И согласуйте его в пуле PHP-FPM: `listen.backlog = 4096`. Примените настройки командой `sudo sysctl --system`.
7.  **Скрытие служебных заголовков:**
    Удаляйте заголовок идентификации версии интерпретатора через `fastcgi_hide_header X-Powered-By;` в Angie и директиву `expose_php = Off` в файле `php.ini`.

---

## Дополнительная информация

*   **Взаимодействие с модулями кэширования:** При использовании дискового кэша `fastcgi_cache` инвалидация и очистка устаревших страниц производятся через методы purge или директиву `fastcgi_cache_bypass` (детально разобрано в [Кэширование прокси в Angie](./angie-proxy-cache.md)).
*   **Сквозное логирование:** Настройка форматов журналов с временными метриками `$upstream_response_time` и переменными Angie подробно описана в [Журналирование в Angie](./angie_logging.md).
*   **Защита заголовков:** Особенности поведения директивы `add_header` при наследовании в блоках `location` описаны в руководстве [Заголовки безопасности в Angie](./angie-security-headers.md).

---

## См. также

*   **[Минимальная продакшен-конфигурация Angie](./angie-baseline-config.md)** — архитектура каталогов, процессная модель Master/Worker и базовые настройки.
*   **[Обратный HTTP-прокси в Angie](./angie_reverse_proxy.md)** — концепции проксирования, буферизация HTTP-апстримов и управление заголовками.
*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы балансировки пулов, директивы zone и проверки доступности.
*   **[Мониторинг Angie с помощью Prometheus](./angie_monitoring/angie_monitoring_prometheus.md)** — экспорт метрик веб-сервера и апстримов в формате OpenMetrics.
*   **[Тюнинг и эксплуатация PHP-FPM](../PHP/php-fpm-tuning.md)** — детальный расчет параметров пулов `dynamic`/`static` и оптимизация OPcache.
*   **[Мониторинг PHP-FPM](../PHP/php-fpm-monitoring.md)** — дашборды Grafana, алертинг PromQL и экспорт метрик пула процессов.
*   **[Примеры интеграции location в Nginx](../Nginx/Core/Location/integration_examples.md)** — сопоставление директив интеграции Nginx и бэкендов.
*   **[Устранение неполадок веб-серверов](../Concepts/webserver_troubleshooting.md)** — общая методология локализации сетевых и прикладных сбоев.