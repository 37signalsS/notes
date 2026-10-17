# Миграция с Apache на Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), Apache HTTP Server 2.4.x, Linux (Debian 12 / Ubuntu 24.04 / RHEL 9 / Rocky Linux 9)

---

## Определения

**Миграция веб-сервера** — плановый технологический процесс перевода обслуживания входящего HTTP/HTTPS-трафика с Apache HTTP Server на Nginx: перенос виртуальных хостов, модулей, правил маршрутизации, списков доступа, параметров безопасности и логирования с сохранением или улучшением характеристик доступности сервиса.

**Директива-аналог** — директива Nginx, выполняющая эквивалентную семантическую функцию по отношению к директиве Apache (например, `Require ip` → `allow`/`deny`, `ProxyPass` → `proxy_pass`, `CustomLog` → `access_log`, `DirectoryIndex` → `index`). Прямое соответствие 1:1 существует не всегда из-за различий в архитектуре обработки запросов.

**Распределенная конфигурация (`.htaccess`)** — механизм локальных конфигурационных файлов каталога в Apache, считываемый и интерпретируемый ядром сервера на каждый входящий HTTP-запрос при включенном `AllowOverride`. В архитектуре Nginx распределенная конфигурация отсутствует: все директивы компилируются в единое дерево в оперативной памяти при запуске демона.

**Блок сопоставления (`location` vs `<Directory>`)** — фундаментальная единица маршрутизации запросов:
- В Apache блок `<Directory>` осуществляет сопоставление с абсолютным путем в файловой системе сервера, а `<Location>` — с путем в URL.
- В Nginx директива `location` выполняет сопоставление исключительно с нормализованным URI запроса.

**Модели параллелизма (MPM vs Event-Driven)**:
- **Apache Multi-Processing Modules (MPM):** `prefork` (один процесс на соединение), `worker` (пул процессов с фиксированным числом потоков), `event` (выделенные потоки-слушатели со сбросом Keep-Alive в неблокирующий режим).
- **Nginx Master-Worker Event Loop:** мастер-процесс управляет непривилегированными рабочими процессами (`worker_processes`), каждый из которых использует однопоточный неблокирующий событийный цикл (системный вызов `epoll` в Linux) для мультиплексирования десятков тысяч одновременных сетевых соединений.

**FastCGI Process Manager (PHP-FPM)** — независимый сервис обработки динамического PHP-кода по протоколу FastCGI. Заменяет встроенный модуль `mod_php` Apache, отделяя жизненный цикл веб-сервера от среды выполнения скриптов.

**Промежуточный обратный прокси (Reverse Proxy Transition Pattern)** — архитектурная стратегия поэтапной миграции, при которой Nginx развертывается в качестве пограничного шлюза (Front-End) перед существующим экземпляром Apache (Back-End), терминируя TLS-сессии, отдавая статические файлы и проксируя динамические вызовы на Apache через локальный порт или UNIX-сокет.

**Плавный перезапуск (Graceful / Hitless Reload)** — процедура обновления конфигурации или бинарных файлов без разрыва активных соединений клиентов: мастер-процесс Nginx проверяет валидность синтаксиса, запускает новый пул рабочих процессов с обновленным конфигом и плавно завершает старые воркеры по мере окончания обработки текущих сессий.

**Параллельное развертывание (Side-by-side / Dual-Run)** — методология внедрения, при которой Nginx запускается на вспомогательном сетевом порту или изолированном IP-адресе параллельно работающему сервису Apache. Трафик перенаправляется канареечно или переключением портов после сквозного функционального тестирования.

---

## Архитектура и основные концепции

### Зачем мигрируют

Переход с Apache HTTP Server на Nginx в DevOps/SRE-практике обусловлен следующими факторами:

1. **Плотность соединений и утилизация памяти:** Nginx удерживает 10 000 неактивных Keep-Alive соединений, расходуя порядка 2–4 МБ оперативной памяти. В Apache под управлением `mpm_prefork` аналогичная нагрузка требует выделения отдельного процесса на соединение, что исчерпывает оперативную память (гигабайты RAM) и приводит к сбоям по OOM Killer. Модель `mpm_event` сокращает разрыв, но все еще уступает Nginx по накладным расходам на переключение контекста потоков.
2. **Нулевое копирование при отдаче статики (Zero-Copy I/O):** Nginx применяет системный вызов `sendfile()`, позволяющий передавать байты с диска напрямую в сетевой сокет внутри пространства ядра Linux, минуя промежуточную буферизацию в пространстве пользователя.
3. **Устранение дискового I/O от `.htaccess`:** Apache вынужден выполнять системный вызов `stat()` для каждого каталога вверх по дереву файловой системы при каждом HTTP-запросе, если активна директива `AllowOverride All`. Nginx читает и парсит конфигурацию один раз при старте или перезагрузке, сохраняя древовидную структуру маршрутов в памяти.
4. **Унификация пограничного шлюза (Edge Gateway):** Nginx объединяет в одном сервисе функционал высокоскоростного L7-балансировщика, кэширующего обратного прокси, шлюза сжатия данных (Gzip, Brotli) и точки терминации современных протоколов TLSv1.3, HTTP/2 и HTTP/3 (QUIC). Архитектурные особенности балансировки Nginx подробно рассмотрены в [сравнении балансировщиков нагрузки](../Proxy/Load_Balancing/additional_info_and_comparisons.md).

### Сравнительный анализ моделей обработки запросов

| Параметр | Apache HTTP Server 2.4 | Nginx 1.26+ / 1.28+ |
|---|---|---|
| **Модель ввода-вывода (I/O)** | Процессы (`prefork`) / Потоки (`worker`, `event`) | Однопоточный неблокирующий Event Loop (`epoll`, `kqueue`) |
| **Расход RAM на 10k соединений** | ~100–500 МБ (`event`) до >5 ГБ (`prefork`) | ~2–4 МБ |
| **Управление конфигурацией** | Централизованная + распределенная (`.htaccess`) | Строго централизованная (файлы `*.conf`) |
| **Загрузка модулей** | Динамическая в runtime (`LoadModule`) | Статическая компиляция или динамические модули `.so` через `load_module` |
| **Исполнение динамики (PHP/Python)** | Встроенные интерпретаторы (`mod_php`, `mod_wsgi`) или FastCGI | Внешние сервисы по протоколам FastCGI, uWSGI, SCGI, HTTP (`proxy_pass`) |
| **Селекция виртуального хоста** | Секция `<VirtualHost>` (первый совпавший по IP/порту) | Блок `server` (сопоставление по кортежу `listen` + `server_name`) |
| **Порядок применения директив** | Сложный иерархический merge (`<Directory>` → `<Files>` → `<Location>`) | Иерархия `http` → `server` → `location`; внутри `location` нет слияния |
| **Приоритет правил сопоставления** | По порядку фаз слияния ядра Apache | Точный (`=`) > Префикс без regex (`^~`) > Регулярные выражения (`~`, `~*`) > Длинный префикс |

### Разница в логике сопоставления правил маршрутизации

Главный источник регрессий при миграции — различие между концепцией пути в файловой системе и пути в URI:

- В Apache директива `<Directory "/var/www/site/admin">` привязывается к реальной файловой структуре. Если запрос приходит на `/admin/index.php` или `/secret-symlink/`, Apache проверяет права целевого файла на диске. Детали слияния секций описаны в [порядке слияния секций Apache](../../Apache/apache-config-merge-order.md).
- В Nginx директива `location /admin/` анализирует исключительно HTTP URI. Если внутри `location` задан `root /var/www/site;`, Nginx конкатенирует значение `root` и `$uri`, формируя путь `/var/www/site/admin/`.
- **Merge Order:** В Apache вложенные секции дополняют и переопределяют директивы родительских секций. В Nginx директивы модуля `ngx_http_headers_module` (например, `add_header`) не наследуются из блока `server`, если в текущем блоке `location` объявлен хотя бы один свой `add_header`.

```
Порядок сопоставления location в Nginx:
[Входящий URI]
      │
      ├─► 1. Точное совпадение: location = /path
      │      └─► [Найдено] ──► Немедленная обработка, поиск завершен
      │
      ├─► 2. Самый длинный префикс с запретом regex: location ^~ /path/
      │      └─► [Найдено] ──► Немедленная обработка, поиск завершен
      │
      ├─► 3. Регулярные выражения: location ~ /path/ или ~* (case-insensitive)
      │      └─► [Найдено] ──► Выбор первого совпавшего в порядке следования в конфиге
      │
      └─► 4. Стандартный префикс: location /path/
             └─► Выбор наиболее специфичного (самого длинного) совпадения
```

### Стратегии миграции

1. **Двухэтапная гибридная миграция (Nginx как Reverse Proxy):**
   - *Фаза 1:* Nginx развертывается на портах 80/443. Apache переносится на внутренний локальный адрес `127.0.0.1:8080`.
   - *Фаза 2:* Nginx терминирует TLS, выполняет сжатие, раздает статические файлы (`/static/`, `/images/`, `.css`, `.js`), а динамические запросы и сложные маршруты проксирует на Apache через `proxy_pass`.
   - *Фаза 3:* Поэтапный разбор правил `.htaccess` и перевод приложений на нативный стек (PHP-FPM, uWSGI, Gunicorn).
   - *Фаза 4:* Окончательный вывод Apache из эксплуатации.
   - *Преимущества:* Нулевой простой (Zero Downtime), мгновенное снятие нагрузки со статики, возможность постепенной трансляции правил.

2. **Параллельный запуск (Side-by-side / Canary):**
   - Nginx настраивается полностью независимо на портах 8080/8443 или на отдельном сетевом интерфейсе (IP alias).
   - Инфраструктурные тесты выполняются синтетическими запросами.
   - Переключение трафика осуществляется изменением записи в локальном DNS, перенастройкой внешнего балансировщика (HAProxy / Keepalived) либо атомарной сменой портов демонов через systemd.
   - *Преимущества:* Изоляция боевого стенда, тривиальный и мгновенный откат.

3. **Атомарное переключение (Big-Bang с откатом):**
   - Подготовка полной конфигурации Nginx на тестовом стенде.
   - Во время технологического окна сервис Apache останавливается, порты 80/443 освобождаются, и запускается демон Nginx.
   - При обнаружении критических регрессий выполняется заранее подготовленный скрипт отката (`systemctl stop nginx && systemctl start apache2`).
   - *Применение:* Изолированные системы, монолитные приложения с предсказуемой архитектурой.

---

## Практические сценарии

### Сценарий 1: Комплексный аудит существующего сервера Apache

Перед началом миграции собираются полные диагностические данные о конфигурации, модулях, правилах перезаписи и сокетах.

```bash
# Проверка используемого MPM и списка загруженных модулей
apache2ctl -M 2>/dev/null | sort || httpd -M 2>/dev/null | sort
# → Loaded Modules:
# →  core_module (static)
# →  mpm_event_module (shared)
# →  rewrite_module (shared)
# →  ssl_module (shared)
# →  remoteip_module (shared)

# Инвентаризация виртуальных хостов, имен доменов и портов
apache2ctl -S 2>/dev/null || httpd -S 2>/dev/null
# → VirtualHost configuration:
# → *:80                   site.example.com (/etc/apache2/sites-enabled/site.conf:1)
# → *:443                  site.example.com (/etc/apache2/sites-enabled/site-ssl.conf:1)
# → port 80 namevhost site.example.com (/etc/apache2/sites-enabled/site.conf:1)
# →         alias www.site.example.com

# Поиск всех файлов распределенной конфигурации .htaccess в веб-корнях
find /var/www -type f -name '.htaccess' -exec ls -l {} +
# → -rw-r--r-- 1 www-data www-data 428 Oct 12 10:14 /var/www/site/public/.htaccess

# Выгрузка всех активных правил перенаправления и перезаписи URL
grep -rnE "(RewriteEngine|RewriteRule|RewriteCond|Redirect|RedirectMatch)" /etc/apache2/ /etc/httpd/ 2>/dev/null
# → /etc/apache2/sites-enabled/site.conf:14:    RewriteEngine On
# → /etc/apache2/sites-enabled/site.conf:15:    RewriteCond %{HTTPS} off
# → /etc/apache2/sites-enabled/site.conf:16:    RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L]

# Проверка конфигурации SSL/TLS (сертификаты, протоколы, ключи)
grep -rnE "(SSLCertificateFile|SSLCertificateKeyFile|SSLCACertificateFile|SSLProtocol)" /etc/apache2/ /etc/httpd/ 2>/dev/null
# → /etc/apache2/sites-enabled/site-ssl.conf:8:    SSLCertificateFile /etc/ssl/certs/site.example.com.crt
# → /etc/apache2/sites-enabled/site-ssl.conf:9:    SSLCertificateKeyFile /etc/ssl/private/site.example.com.key

# Фиксация активных слушающих сокетов
ss -tulpn | grep -E ':(80|443)\s'
# → tcp   LISTEN 0      511          0.0.0.0:80        0.0.0.0:*    users:(("apache2",pid=1420,fd=4))
# → tcp   LISTEN 0      511          0.0.0.0:443       0.0.0.0:*    users:(("apache2",pid=1420,fd=5))
```

### Сценарий 2: Базовый виртуальный хост и маппинг директив

Исходный виртуальный хост Apache 2.4:

```apacheconf
# /etc/apache2/sites-available/site.example.com.conf
<VirtualHost *:80>
    ServerName site.example.com
    ServerAlias www.site.example.com
    ServerAdmin sysadmin@example.com

    DocumentRoot /var/www/site/public
    DirectoryIndex index.html index.php

    ErrorLog ${APACHE_LOG_DIR}/site_error.log
    CustomLog ${APACHE_LOG_DIR}/site_access.log combined

    ServerTokens Prod
    LimitRequestBody 16777216
    Timeout 60
    KeepAliveTimeout 15

    <Directory "/var/www/site/public">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

Эквивалентный блок `server` в Nginx 1.26+:

```nginx
# /etc/nginx/conf.d/site.example.com.conf
server {
    listen 80;
    listen [::]:80;
    server_name site.example.com www.site.example.com;

    root /var/www/site/public;
    index index.html index.php;

    server_tokens off;             # Аналог ServerTokens Prod
    client_max_body_size 16m;      # Аналог LimitRequestBody 16777216 байт
    keepalive_timeout 15s;         # Аналог KeepAliveTimeout 15
    send_timeout 60s;              # Аналог Timeout 60

    autoindex off;                 # Аналог Options -Indexes
    disable_symlinks off;          # Аналог Options +FollowSymLinks (разрешены)

    access_log /var/log/nginx/site_access.log combined buffer=64k flush=5s;
    error_log  /var/log/nginx/site_error.log warn;

    location / {
        try_files $uri $uri/ =404; # Базовое сопоставление файлов с диска
    }
}
```

#### Сводная таблица маппинга директив ядра

| Категория | Директива Apache 2.4 | Директива Nginx 1.26+ | Особенности поведения |
|---|---|---|---|
| **Сетевой сокет** | `Listen 80` | `listen 80;` | В Nginx можно явно задавать `reuseport`, `backlog=N` |
| **Доменные имена** | `ServerName example.com`<br>`ServerAlias *.example.com` | `server_name example.com *.example.com;` | Поддерживаются точные совпадения, wildcards и regex |
| **Файловый корень** | `DocumentRoot /var/www` | `root /var/www;` | В Nginx `root` конкатенирует URI: `root + $uri` |
| **Индексный файл** | `DirectoryIndex index.php` | `index index.php;` | Поиск выполняется слева направо |
| **Листинг каталога** | `Options +Indexes` / `-Indexes` | `autoindex on;` / `autoindex off;` | В Nginx по умолчанию `autoindex off;` |
| **Символические ссылки** | `Options +FollowSymLinks` | `disable_symlinks off;` | В Nginx переходы по symlinks по умолчанию включены |
| **Маскировка версии** | `ServerTokens Prod` | `server_tokens off;` | Скрывает номер версии в заголовках и стандартных страницах ошибок |
| **Лимит тела запроса** | `LimitRequestBody 10485760` | `client_max_body_size 10m;` | В Nginx при превышении возвращается код `413 Payload Too Large` |
| **Таймаут Keep-Alive** | `KeepAliveTimeout 15` | `keepalive_timeout 15s;` | Время удержания неактивного клиентского соединения |
| **Кодировка ответов** | `AddDefaultCharset UTF-8` | `charset utf-8;` | Автоматически добавляет параметр кодировки в `Content-Type` |
| **Страницы ошибок** | `ErrorDocument 404 /404.html` | `error_page 404 /404.html;` | Для внутреннего вызова рекомендуется использовать `internal;` |

### Сценарий 3: Перенос правил `.htaccess` и `mod_rewrite`

В Nginx обработка правил маршрутизации выполняется модулем `ngx_http_rewrite_module`. Правила переносятся в контекст `server` или заменяются декларативной директивой `try_files`. Принципы работы механизма подробно изложены в руководстве по [перенаправлениям и перезаписи URI в Nginx](../Core/nginx_rewrite_rules_and_try_files.md) и правилам [Apache mod_rewrite](../../Apache/apache_rewrite_and_redirects.md).

#### 1. Фронт-контроллер CMS/фреймворков (WordPress, Laravel, Symfony)

Apache (`.htaccess`):
```apacheconf
RewriteEngine On
RewriteBase /
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^(.*)$ index.php [L,QSA]
```

Nginx (`nginx.conf`):
```nginx
location / {
    # Последовательная проверка: реальный файл -> реальная директория -> фронт-контроллер
    try_files $uri $uri/ /index.php?$args;
}
```
*Примечание:* Параметр `$args` обеспечивает передачу строки запроса (Query String), полностью дублируя флаг `[QSA]`.

#### 2. Маппинг регулярных выражений и флагов

Apache (`.htaccess`):
```apacheconf
RewriteEngine On

# 301 Permanent Redirect c сохранением пути
RewriteRule ^old-blog/(.*)$ /articles/$1 [R=301,L]

# Нечувствительное к регистру сопоставление (NC) и запрет доступа (Forbidden)
RewriteRule ^private/.* - [NC,F]

# Запрос ресурса, который был удален навсегда (Gone)
RewriteRule ^deprecated-api/.* - [G]
```

Nginx (`nginx.conf`):
```nginx
# 301 редирект: директива rewrite с флагом permanent
rewrite ^/old-blog/(.*)$ /articles/$1 permanent;

# Регистронезависимое совпадение (~*) и возврат статуса 403 (аналог [NC,F])
location ~* ^/private/ {
    return 403;
}

# Возврат статуса 410 Gone (аналог [G])
location ^~ /deprecated-api/ {
    return 410;
}
```

#### 3. Нормализация хостов и принудительный редирект на HTTPS

В Apache редирект часто строился на тяжелых конструкциях `RewriteCond`:

```apacheconf
RewriteEngine On
RewriteCond %{HTTPS} off [OR]
RewriteCond %{HTTP_HOST} ^www\.(.*)$ [NC]
RewriteRule ^ https://example.com%{REQUEST_URI} [R=301,L]
```

В Nginx каноническим и наиболее быстрым методом является разделение виртуальных хостов на отдельные блоки `server`:

```nginx
# Блок перенаправления с HTTP на HTTPS для всех доменов
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    return 301 https://example.com$request_uri;
}

# Блок канонизации имени хоста (редирект с www на non-www)
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name www.example.com;

    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    return 301 https://example.com$request_uri;
}

# Основной рабочий сервер
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name example.com;

    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    # ... конфигурация сайта ...
}
```

#### 4. Защита служебных файлов метаданных

Apache автоматически скрывает файлы `.ht*`. Nginx отдает статические файлы «как есть», поэтому защиту dot-файлов (`.git`, `.env`, `.htaccess`) необходимо конфигурировать явно:

```nginx
# Запрет доступа ко всем скрытым файлам и каталогам (начинающимся с точки), кроме .well-known
location ~ /\.(?!well-known).* {
    deny all;
    access_log off;
    log_not_found off;
}
```

### Сценарий 4: Аутентификация и контроль доступа (ACL)

#### 1. Basic-аутентификация через htpasswd

Файлы `.htpasswd`, созданные стандартной утилитой Apache `htpasswd`, совместимы с Nginx без перегенерации паролей (поддерживаются алгоритмы MD5 apr1 и Crypt):

Apache:
```apacheconf
<Location "/admin">
    AuthType Basic
    AuthName "Restricted Administration"
    AuthUserFile /etc/apache2/.htpasswd
    Require valid-user
</Location>
```

Nginx:
```nginx
location /admin/ {
    auth_basic "Restricted Administration";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

#### 2. Фильтрация по IP-адресам клиентов

Apache 2.4:
```apacheconf
<Directory "/var/www/site/public/internal">
    Require ip 192.168.1.0/24
    Require ip 10.10.50.15
</Directory>
```

Nginx:
```nginx
location /internal/ {
    allow 192.168.1.0/24;
    allow 10.10.50.15;
    deny all;
}
```

#### 3. SSO / LDAP аутентификация

В Apache интеграция с LDAP выполняется через модуль `mod_authnz_ldap`, а с OpenID Connect — через `mod_auth_openidc`. В Nginx Open Source встроенная поддержка LDAP отсутствует. В корпоративных инфраструктурах применяется модуль `ngx_http_auth_request_module`:

```nginx
location /secure/ {
    # Проверка сессии через локальный демон аутентификации (Authelia, Vouch Proxy, OAuth2-Proxy)
    auth_request /auth-verify;

    auth_request_set $user $upstream_http_x_auth_request_user;
    proxy_set_header X-User $user;

    proxy_pass http://internal_backend;
}

location = /auth-verify {
    internal;
    proxy_pass http://127.0.0.1:9099/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
}
```

### Сценарий 5: Перенос динамических приложений (PHP, Python, Java/Tomcat)

#### 1. Перенос стека PHP (с `mod_php` на PHP-FPM)

Apache (`mod_php` или `mod_proxy_fcgi`):
```apacheconf
<FilesMatch \.php$>
    SetHandler "proxy:unix:/run/php/php8.3-fpm.sock|fcgi://localhost/"
</FilesMatch>
```

Nginx:
Конфигурация включает защиту от выполнения произвольного кода при передаче несуществующих файлов интерпретатору (`try_files $fastcgi_script_name =404;`) и защиту от уязвимости HTTPoxy (`fastcgi_param HTTP_PROXY "";`):

```nginx
location ~ \.php$ {
    # Защита от уязвимостей типа path-info и передачи несуществующих файлов на сокет PHP
    try_files $uri =404;

    fastcgi_split_path_info ^(.+\.php)(/.+)$;
    fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    fastcgi_index index.php;

    include fastcgi_params;

    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    fastcgi_param PATH_INFO       $fastcgi_path_info;
    fastcgi_param HTTP_PROXY      "";

    # Тюнинг буферов для предотвращения сброса промежуточных данных на диск
    fastcgi_buffer_size          32k;
    fastcgi_buffers              8 16k;
    fastcgi_busy_buffers_size    64k;
    fastcgi_temp_file_write_size 64k;

    fastcgi_connect_timeout 5s;
    fastcgi_send_timeout    60s;
    fastcgi_read_timeout    60s;
}
```

Настройка пула PHP-FPM (`/etc/php/8.3/fpm/pool.d/www.conf`):
```ini
[www]
user = www-data
group = www-data
listen = /run/php/php8.3-fpm.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660

pm = dynamic
pm.max_children = 50
pm.start_servers = 10
pm.min_spare_servers = 5
pm.max_spare_servers = 20
pm.max_requests = 1000
```

#### 2. Перенос стека Python (с `mod_wsgi` на Gunicorn/uWSGI)

Apache (`mod_wsgi` daemon mode):
```apacheconf
WSGIDaemonProcess myapp processes=4 threads=2 display-name=%{GROUP} python-home=/var/www/myapp/venv
WSGIProcessGroup myapp
WSGIScriptAlias / /var/www/myapp/wsgi.py
```

Nginx + Gunicorn (через UNIX-сокет):

```nginx
# Запуск сервиса Gunicorn: gunicorn --workers 4 --bind unix:/run/myapp/gunicorn.sock myapp.wsgi:application
location / {
    proxy_pass http://unix:/run/myapp/gunicorn.sock;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

#### 3. Перенос стека Java/Tomcat (с `mod_proxy_ajp` на HTTP Reverse Proxy)

В Apache для связи с Tomcat традиционно применялся бинарный протокол AJP (`mod_proxy_ajp`). В современных системах протокол AJP признан устаревшим из-за уязвимости Ghostcat (CVE-2020-1938). Nginx не поддерживает протокол AJP в основном репозитории; трафик переводится на стандартный HTTP-коннектор Tomcat (порт 8080) с поддержкой Keep-Alive:

Apache (`mod_proxy_ajp`):
```apacheconf
ProxyPass /app ajp://127.0.0.1:8009/app
ProxyPassReverse /app ajp://127.0.0.1:8009/app
```

Nginx (`proxy_pass` по HTTP/1.1):
```nginx
upstream tomcat_cluster {
    server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

location /app/ {
    proxy_pass http://tomcat_cluster;
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_cookie_path /app/ /app/;
}
```

### Сценарий 6: Переходная архитектура — Nginx как Reverse Proxy перед Apache

Данная схема обеспечивает прозрачный и безопасный перенос нагрузки. Nginx принимает внешние запросы, обрабатывает TLS и статику, а динамические вызовы передает на локальный Apache.

```
[Клиентский браузер]
         │ HTTPS / HTTP/2 (порт 443)
         ▼
[Nginx Reverse Proxy]
   │                 │
   │ Отдача статики  │ Проксирование динамики (127.0.0.1:8080)
   │ (.css, .js, img)│ Заголовки: X-Forwarded-For, X-Forwarded-Proto
   ▼                 ▼
[Диск сервера]    [Apache HTTP Server] (mpm_event)
   /var/www/site     │
                     ├─► mod_remoteip (восстановление реального IP)
                     └─► Исполнение legacy .htaccess и скриптов
```

#### 1. Конфигурация Nginx (Front-End)

```nginx
# /etc/nginx/sites-available/frontend-proxy.conf
upstream apache_backend {
    server 127.0.0.1:8080;
    keepalive 64;
}

server {
    listen 80;
    server_name site.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name site.example.com;

    ssl_certificate     /etc/ssl/certs/site.example.com.crt;
    ssl_certificate_key /etc/ssl/private/site.example.com.key;

    root /var/www/site/public;
    index index.php index.html;

    # 1. Прямая высокоскоростная отдача статических файлов через Nginx
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|pdf|txt|tar|gz|svg|woff2)$ {
        expires 30d;
        add_header Cache-Control "public, no-transform";
        access_log off;
        try_files $uri =404;
    }

    # 2. Запрет доступа к служебным файлам
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    # 3. Проксирование всех остальных запросов на Apache
    location / {
        proxy_pass http://apache_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;

        proxy_connect_timeout 5s;
        proxy_read_timeout    60s;
        proxy_send_timeout    60s;

        # Буферизация ответов для освобождения процессов Apache
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 8 32k;
    }
}
```

#### 2. Конфигурация Apache (Back-End)

В Apache изменяется слушающий порт и включается модуль `mod_remoteip` для корректного определения клиентских IP-адресов в логах и правилах авторизации:

```apacheconf
# /etc/apache2/ports.conf (или /etc/httpd/conf/httpd.conf)
Listen 127.0.0.1:8080

# /etc/apache2/conf-available/remoteip.conf
<IfModule mod_remoteip.c>
    RemoteIPHeader X-Forwarded-For
    RemoteIPInternalProxy 127.0.0.1
</IfModule>
```

Формат логирования в `/etc/apache2/apache2.conf`:
```apacheconf
LogFormat "%a %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" combined_proxied
CustomLog ${APACHE_LOG_DIR}/access.log combined_proxied
```
*Важно:* Спецификатор `%a` в Apache выводит реальный адрес клиента, определенный через `mod_remoteip`, тогда как стандартный `%h` вывел бы адрес `127.0.0.1`.

### Сценарий 7: Обратное проксирование, балансировка и keepalive

Apache (`mod_proxy_balancer`):
```apacheconf
<Proxy "balancer://appcluster">
    BalancerMember "http://10.0.0.11:8080" route=node1 retry=5
    BalancerMember "http://10.0.0.12:8080" route=node2 retry=5
    ProxySet lbmethod=byrequests
    ProxySet stickysession=JSESSIONID
</Proxy>

<VirtualHost *:80>
    ServerName app.example.com
    ProxyPass / balancer://appcluster/
    ProxyPassReverse / balancer://appcluster/
</VirtualHost>
```

Nginx:
В Nginx Open Source балансировка настраивается через блок `upstream`. Для привязки сессий (Sticky Sessions) по cookie в OSS применяется детерминированное хэширование `hash $cookie_jsessionid consistent`:

```nginx
upstream app_cluster {
    # Алгоритм Sticky Sessions по идентификатору cookie
    hash $cookie_jsessionid consistent;

    server 10.0.0.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.12:8080 max_fails=3 fail_timeout=10s;

    # Пул открытых соединений между воркерами Nginx и бэкендами
    keepalive 32;
}

server {
    listen 80;
    server_name app.example.com;

    location / {
        proxy_pass http://app_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection ""; # Очистка заголовка для удержания Keep-Alive

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Обработка сбоев и переключение на резервный узел
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_timeout 5s;
        proxy_next_upstream_tries 3;
    }
}
```

### Сценарий 8: Безопасный TLS/SSL, HTTP/2 и HTTP/3 (QUIC)

Современная конфигурация Nginx исключает устаревший параметр `listen ... http2;` (начиная с Nginx 1.25.1 заменен директивой `http2 on;`) и реализует поддержку HTTP/3 по UDP.

```nginx
server {
    # TCP-сокеты для HTTP/1.1 и HTTP/2
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # UDP-сокет для протокола HTTP/3 (QUIC)
    listen 443 quic reuseport;
    listen [::]:443 quic reuseport;
    http3 on;

    server_name site.example.com;

    # Пути к сертификату и закрытому ключу
    ssl_certificate         /etc/ssl/certs/site.example.com.fullchain.pem;
    ssl_certificate_key     /etc/ssl/private/site.example.com.key;
    ssl_trusted_certificate /etc/ssl/certs/site.example.com.ca-bundle.pem;

    # Протоколы и безопасные шифры (Mozilla Intermediate)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Оптимизация возобновления сессий (Session Resumption)
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Проверка статуса сертификата (OCSP Stapling)
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 127.0.0.53 valid=300s;
    resolver_timeout 5s;

    # Объявление поддержки HTTP/3 клиентам через заголовок Alt-Svc
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # Базовые заголовки безопасности
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    root /var/www/site/public;
    index index.html;
}
```

### Сценарий 9: Оптимизация статического контента, кэширование и заголовки

Nginx оптимизирует отдачу статических файлов за счет прямого взаимодействия с ядром ОС и механизмов предварительного сжатия:

```nginx
http {
    # Передача файла из дискового кэша напрямую в сокет ядра Linux
    sendfile on;

    # Отправка заголовков и начала файла в одном сетевом пакете
    tcp_nopush on;

    # Отключение алгоритма Нагла для минимизации задержек интерактивных ответов
    tcp_nodelay on;

    # Динамическое сжатие Gzip
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml+rss image/svg+xml;

    # Использование предварительно сжатых файлов (.gz) при их наличии на диске
    gzip_static on;
}

server {
    listen 80;
    server_name site.example.com;
    root /var/www/site/public;

    # Кэширование статических ассетов
    location /static/ {
        expires 365d;
        add_header Cache-Control "public, immutable";
        access_log off;
        log_not_found off;
    }
}
```

*Подводный камень наследования:* В Nginx директивы `add_header`, объявленные на уровне `http` или `server`, **полностью игнорируются** в блоке `location`, если внутри этого `location` определен хотя бы один локальный заголовок `add_header`. Если в локации со статикой задается `Cache-Control`, заголовки безопасности (`X-Frame-Options`, `X-Content-Type-Options`) необходимо повторить явно.

### Сценарий 10: Пошаговый ввод в эксплуатацию, тестирование и откат (Rollback Runbook)

Пошаговая инструкция перевода боевого трафика с Apache на Nginx с валидацией каждого этапа.

```bash
# 1. Запуск Nginx на вспомогательном порту (например, 8080) для предрелизного тестирования
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Проверка соответствия заголовков и кодов ответов между Apache (80) и Nginx (8080)
curl -sI -H "Host: site.example.com" http://127.0.0.1:80/ | head -n 5
# → HTTP/1.1 200 OK
# → Date: Sat, 17 Oct 2026 12:00:00 GMT
# → Server: Apache/2.4.58 (Ubuntu)
# → Content-Type: text/html; charset=UTF-8

curl -sI -H "Host: site.example.com" http://127.0.0.1:8080/ | head -n 5
# → HTTP/1.1 200 OK
# → Date: Sat, 17 Oct 2026 12:00:01 GMT
# → Server: nginx
# → Content-Type: text/html; charset=utf-8

# 3. Атомарное переключение сервисов через systemd
# Остановка Apache и перевод Nginx на основные порты 80 и 443
sudo systemctl stop apache2 && sudo systemctl restart nginx

# 4. Проверка статуса сокетов и процесса Nginx
sudo ss -tulpn | grep -E ':(80|443)\s'
# → tcp   LISTEN 0      511          0.0.0.0:80        0.0.0.0:*    users:(("nginx",pid=28510,fd=6))
# → tcp   LISTEN 0      511          0.0.0.0:443       0.0.0.0:*    users:(("nginx",pid=28510,fd=7))

# 5. Проверка внешнего ответа после переключения
curl -sI https://site.example.com/ | grep -E "(HTTP/|Server:)"
# → HTTP/2 200
# → server: nginx

# 6. Отключение автозапуска Apache и включение автозапуска Nginx
sudo systemctl disable apache2
# → Removed /etc/systemd/system/multi-user.target.wants/apache2.service.
sudo systemctl enable nginx
# → Synchronizing state of nginx.service with SysV service script with /lib/systemd/systemd-sysv-install.
# → Executing: /lib/systemd/systemd-sysv-install enable nginx
```

#### План экстренного отката (Rollback Runbook)

Если после переключения обнаружены массовые ошибки (рост кодов 5xx, поломка авторизации):

```bash
# Немедленный возврат на исходный Apache
sudo systemctl stop nginx && sudo systemctl start apache2

# Валидация восстановления работы Apache
sudo ss -tulpn | grep -E ':(80|443)\s'
# → tcp   LISTEN 0      511          0.0.0.0:80        0.0.0.0:*    users:(("apache2",pid=31200,fd=4))

curl -sI http://localhost/ | grep "Server:"
# → Server: Apache/2.4.58 (Ubuntu)
```

---

## Операции и команды

Сводная таблица эксплуатационных команд администратора:

| Операция | Команда | Назначение и ожидаемый результат |
|---|---|---|
| **Валидация синтаксиса** | `sudo nginx -t` | Проверка синтаксиса и путей к файлам сертификатов |
| **Полный дамп конфигурации** | `sudo nginx -T \| grep -i "server_name"` | Разворачивание всех `include` для поиска дубликатов vhost |
| **Бесшовная перезагрузка** | `sudo systemctl reload nginx` | Отправка сигнала `HUP` без разрыва клиентских TCP-сессий |
| **Плавная остановка** | `sudo nginx -s quit` | Завершение работы после обработки активных запросов |
| **Проверка версий и модулей** | `nginx -V` | Список параметров сборки, путей и динамических модулей |
| **Анализ сокетов** | `sudo ss -tulpn \| grep -E ':(80\|443)'` | Определение демона, занимающего рабочие сетевые порты |
| **Мониторинг журнала ошибок** | `sudo journalctl -u nginx -n 50 -f` | Просмотр системных событий запуска и аварийных воркеров |
| **Контроль ошибок бэкенда** | `tail -f /var/log/nginx/error.log` | Отслеживание таймаутов FastCGI и недоступности `upstream` |

#### Автоматизированный скрипт валидации кодов ответов

Скрипт выполняет параллельный опрос критических эндпоинтов для проверки корректности миграции:

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="127.0.0.1:8080"
DOM_HEADER="site.example.com"

declare -A ROUTES=(
    ["/"]="200"
    ["/index.php"]="200"
    ["/static/style.css"]="200"
    ["/nonexistent-page-test"]="404"
    ["/admin/"]="401"
)

echo "Запуск верификации маршрутизации Nginx..."

for uri in "${!ROUTES[@]}"; do
    expected="${ROUTES[$uri]}"
    actual=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${DOM_HEADER}" "http://${TARGET_HOST}${uri}")
    if [[ "${actual}" == "${expected}" ]]; then
        echo -e "[\e[32mOK\e[0m] ${uri} -> HTTP ${actual}"
    else
        echo -e "[\e[31mFAIL\e[0m] ${uri} -> Ожидалось: ${expected}, получено: ${actual}"
    fi
done
# → Запуск верификации маршрутизации Nginx...
# → [OK] / -> HTTP 200
# → [OK] /index.php -> HTTP 200
# → [OK] /static/style.css -> HTTP 200
# → [OK] /nonexistent-page-test -> HTTP 404
# → [OK] /admin/ -> HTTP 401
```

---

## Устранение неисправностей

| Симптом | Возможная причина | Метод диагностики | Инженерное решение |
|---|---|---|---|
| **`404 Not Found` на статических файлах** | Несоответствие путей в директивах `root` и `alias`. | Выполнить `nginx -T`, сопоставить директиву `root` и URI. | Помнить: `root` добавляет `$uri` к пути, `alias` заменяет совпавшую часть `location`. |
| **`404 Not Found` на всех страницах CMS** | Не перенесены правила Front-Controller из `.htaccess`. | Запрос на `/about` не находит файл на диске. | Добавить `try_files $uri $uri/ /index.php?$args;` в блок `location /`. |
| **PHP-код скачивается как файл** | Отсутствует блок `location ~ \.php$` или директива `fastcgi_pass`. | Проверить ответ через `curl -I http://site/test.php` (Content-Type: application/x-httpd-php). | Сконфигурировать `fastcgi_pass` на сокет PHP-FPM и подключить `fastcgi_params`. |
| **`403 Forbidden` при обращении к сайту** | 1. Нет индексного файла и выключен `autoindex`.<br>2. Права доступа на файлы каталога. | Проверить журнал `/var/log/nginx/error.log`: "directory index of ... is forbidden". | Установить права: `chown -R www-data:www-data /var/www/site` и проверить `index index.php index.html;`. |
| **`403 Forbidden` на SELinux (RHEL/Rocky)** | Контекст безопасности файлов не соответствует `httpd_sys_content_t`. | Проверить журнал аудита: `ausearch -m avc -ts recent \| audit2why`. | Восстановить контекст: `restorecon -Rv /var/www/site` и включить `setsebool -P httpd_can_network_connect 1`. |
| **`.htaccess` скачивается из браузера** | Nginx не скрывает файлы с точкой по умолчанию. | Запрос `curl http://site/.htaccess` отдает содержимое файла. | Добавить правило блокировки: `location ~ /\.(?!well-known).* { deny all; }` и удалить файлы `.htaccess`. |
| **`502 Bad Gateway` при вызове динамики** | Демон PHP-FPM или gunicorn не запущен, либо не совпадают права на UNIX-сокет. | В `error.log`: "connect() to unix:/run/php/php8.3-fpm.sock failed (13: Permission denied / 111: Connection refused)". | 1. `systemctl restart php8.3-fpm`<br>2. Проверить `listen.owner` и `listen.group` в `www.conf`. |
| **`504 Gateway Timeout`** | Превышен таймаут выполнения тяжелого скрипта бэкенда. | В `error.log`: "upstream timed out (110: Connection timed out)". | Увеличить `fastcgi_read_timeout 120s;` (или `proxy_read_timeout`) и `max_execution_time` в `php.ini`. |
| **Бесконечный редирект (Redirect Loop)** | Конфликт между внешним HTTPS-терминатором и бэкендом (бэкенд не видит заголовок HTTPS). | В браузере: `ERR_TOO_MANY_REDIRECTS`. Проверка через `curl -sIL http://site/`. | Передавать бэкенду заголовок `proxy_set_header X-Forwarded-Proto $scheme;` (или `fastcgi_param HTTPS on;`). |
| **Клиентский IP в приложении равен 127.0.0.1** | При миграции через Reverse Proxy на Apache не настроен `mod_remoteip`. | В логах Apache отображается только `127.0.0.1`. | Включить `mod_remoteip`, задать `RemoteIPHeader X-Forwarded-For` и доверенный прокси `RemoteIPInternalProxy 127.0.0.1`. |
| **Заголовки безопасности пропадают в `location`** | Механизм переопределения `add_header` в дочерних блоках. | Проверить ответ через `curl -I`: заголовки сервера отсутствуют в ответах статики. | Повторить необходимые заголовки безопасности внутри блока `location` либо вынести их в отдельный файл `include`. |

---

## Лучшие практики

1. **Предварительный аудит и инвентаризация:** До начала работ зафиксировать полный перечень доменов, алиасов, SSL-сертификатов, файлов `.htaccess` и внешних портов. Любая скрытая директива в `.htaccess` может привести к сбою бизнес-логики.
2. **Использование переходной архитектуры (Reverse Proxy):** На высоконагруженных монолитах не переключать стек методом Big-Bang. Развертывание Nginx в качестве шлюза перед Apache дает 80% прироста производительности в первый день и оставляет время на вдумчивый рефакторинг rewrite-правил.
3. **Полное удаление `.htaccess` после миграции:** После переноса правил в основной конфиг Nginx удалять файлы `.htaccess` из файловой системы. Это исключает риск утечки служебных данных и случайного возврата устаревших директив.
4. **Сохранение SEO-веса URL:** Все исторические пути страниц должны сопровождаться корректными редиректами `301 Permanent Redirect` (`return 301 ...;`). Использование статуса `302` для постоянных правил недопустимо из-за риска деиндексации поисковыми системами.
5. **Отказ от директивы `if` в блоках `location`:** Директива `if` внутри `location` выполняется на фазе rewrite и имеет недетерминированное поведение (известный антипаттерн "If is Evil"). Для разветвления логики использовать директивы `try_files`, `return`, именованные локации (`@name`) или модуль `map`.
6. **Безопасная изоляция PHP-FPM:** Запускать пулы PHP-FPM через локальные UNIX-сокеты с правами `0660` и отдельными пользователями для разных приложений. На уровне Nginx всегда экранировать вызовы директивой `try_files $uri =404;`.
7. **Контроль ротации журналов:** При отключении Apache скорректировать конфигурации в `/etc/logrotate.d/`. Для Nginx ротация выполняется отправкой сигнала `USR1` мастер-процессу (`kill -USR1 $(cat /run/nginx.pid)`), что заставляет воркеры атомарно переоткрыть дескрипторы лог-файлов без перезапуска демона.
8. **Мониторинг метрик телеметрии:** Заменить опрос Apache `mod_status` (`/server-status`) на эндпоинт Nginx `stub_status` либо использовать специализированный экспортер метрик для Prometheus (`nginx-prometheus-exporter` или модуль `nginx-module-vts`).
9. **Проверка прав SELinux и AppArmor:** На дистрибутивах семейств RHEL/CentOS/Rocky при смене путей к веб-корням (`/var/www` на отдельный диск) не отключать SELinux, а назначать правильные контексты `chcon -R -t httpd_sys_content_t /path` и сохранять их в базе через `semanage fcontext`.

---

## Дополнительная информация

### См. также

*   [Сравнение Nginx и Apache (архитектура)](../Proxy/Load_Balancing/additional_info_and_comparisons.md) — архитектурные модели, потребление ресурсов, алгоритмы балансировки.
*   [Перенаправления и перезапись URI в Nginx](../Core/nginx_rewrite_rules_and_try_files.md) — подробный справочник директив `rewrite`, `return`, `try_files` и модуля `map`.
*   [Best Practices для блоков Location](../Core/Location/best_practices.md) — оптимизация алгоритма поиска, структура префиксов и безопасность сопоставлений.
*   [Примеры интеграции Location и PHP-FPM](../Core/Location/integration_examples.md) — тюнинг FastCGI, буферизация, таймауты и предотвращение уязвимостей.
*   [Руководство по безопасности Nginx](../Security/nginx_security_guide.md) — ограничение доступа, скрытие служебных файлов, харденинг заголовков.
*   [Харденинг Nginx: systemd, SELinux, AppArmor](../Security/nginx_systemd_selinux_hardening.md) — мандатный контроль доступа и изоляция процессов на уровне ОС.
*   [Анализ и ротация логов Nginx](../Operations/nginx_log_analysis.md) — форматы `access_log`, ротация без простоя через `logrotate`.
*   [Apache: Перенаправления и перезапись URL (mod_rewrite, mod_alias)](../../Apache/apache_rewrite_and_redirects.md) — детальный синтаксис директив и флагов Apache.
*   [Apache: Обзор архитектуры и конфигурации](../../Apache/apache_overview.md) — модули MPM, конфигурация виртуальных хостов и `mod_remoteip`.
*   [Apache: Порядок слияния секций конфигурации](../../Apache/apache-config-merge-order.md) — алгоритмы наследования и приоритеты директив Apache.
*   [Миграция с Nginx на Angie](../../Angie/migration_from_nginx.md) — дальнейшая эволюция стека и переход на сервер Angie.