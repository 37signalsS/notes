# Lighttpd

**Актуально для:** Lighttpd 1.4.x (1.4.75+)

---

## Определения

**Lighttpd** (разг. *«lighty»*) — легковесный веб-сервер и обратный прокси с открытым исходным кодом, оптимизированный для высокой производительности и критически низкого потребления оперативной памяти в окружениях с ограниченными ресурсами (VPS с объемом RAM 128–512 MB, встроенные системы, Edge-узлы).

**Event-driven архитектура** — модель асинхронной обработки сетевых соединений на базе системных вызовов мультиплексирования ввода-вывода (`epoll` в Linux, `kqueue` в FreeBSD), позволяющая одному потоку или процессу обслуживать тысячи одновременных подключений без создания отдельного потока на каждого клиента.

**FastCGI** — бинарный клиент-серверный протокол взаимодействия веб-сервера с независимыми пулами процессов приложений (PHP-FPM, Python Flup/WSGI, Go), исключающий накладные расходы на постоянный fork/exec процессов при каждом HTTP-запросе.

**mod_deflate** — модуль сжатия статических и динамических HTTP-ответов на лету (поддерживает алгоритмы Brotli, gzip, zstd, Deflate). Заменил устаревший модуль `mod_compress` начиная с версии Lighttpd 1.4.56.

**mod_openssl** — модуль шифрования TLS/SSL на базе библиотеки OpenSSL (а также BoringSSL и LibreSSL). Начиная с Lighttpd 1.4.46 выделен из ядра в отдельный динамический модуль; альтернативные TLS-модули включают `mod_mbedtls`, `mod_wolfssl` и `mod_gnutls`.

**mod_proxy** — модуль обратного проксирования HTTP-запросов к вышестоящим бэкендам (upstream) с поддержкой пулов соединений, балансировки нагрузки и таймаутов.

**mod_sockproxy** — модуль прозрачного потокового проксирования на транспортном уровне (L4) для TCP-сокетов и локальных UNIX-сокетов без модификации прикладного протокола (доступен с Lighttpd 1.4.56).

**mod_status** — модуль мониторинга и телеметрии, предоставляющий статистику работы сервера и счетчики модулей в форматах HTML, JSON и Apache-совместимого plain-text (`?auto`).

**mod_rewrite** — модуль перезаписи URI-путей на основе регулярных выражений до передачи запроса обработчикам статики, FastCGI или прокси.

**mod_access** — модуль авторизации и сетевой фильтрации запросов на основе IP-адресов или подсетей клиентов (`$HTTP["remoteip"]`).

**mod_auth** — модуль аутентификации пользователей по протоколам HTTP Basic и Digest с поддержкой бэкендов `htpasswd`, `htdigest` и LDAP.

**Zero-Copy (sendfile)** — механизм передачи данных напрямую из кэша страниц ядра Linux (page cache) в сетевой сокет минуя копирование в адресное пространство пользователя, снижающий нагрузку на CPU при отдаче статических файлов.

---

## Основные концепции

### Архитектура и принцип работы

Lighttpd спроектирован по модели **однопоточного цикла событий (single-process event loop)**. В отличие от многопроцессных серверов (Apache MPM prefork), один процесс `lighttpd` обрабатывает все входящие соединения асинхронно.

```
Входящие TCP-соединения
        │
        ▼
[ epoll / kqueue ]  ◄── Неблокирующий цикл событий (Event Loop)
        │
        ├─► Парсинг HTTP-запроса (State Machine)
        ├─► Применение условных блоков ($HTTP, $SERVER)
        ├─► Обработка статики (Zero-Copy sendfile() / writev())
        ├─► Проксирование FastCGI (UNIX-сокет / TCP) ──► [ PHP-FPM Pool ]
        └─► Обратный прокси (mod_proxy)              ──► [ Внутренний сервис ]
```

**Ключевые архитектурные характеристики:**
- **Низкий memory footprint:** Потребление оперативной памяти составляет около 2–5 MB на 10 000 неактивных keep-alive соединений.
- **Внутренний конечный автомат соединений (Connection State Machine):** Соединение проходит через строгие состояния:
  1. `CON_STATE_REQUEST_START` — принятие сокета через `accept4()`.
  2. `CON_STATE_READ` — неблокирующее чтение заголовков запроса в буфер.
  3. `CON_STATE_REQUEST_END` — парсинг структуры HTTP, валидация заголовков.
  4. `CON_STATE_HANDLE_REQUEST` — сопоставление с конфигурацией, выполнение модулей (`mod_rewrite`, `mod_access`, выбор обработчика).
  5. `CON_STATE_RESPONSE_START` / `CON_STATE_WRITE` — отправка ответа через системный вызов `sendfile()` (для файлов) или `writev()` (для динамических буферов и TLS).
  6. `CON_STATE_RESPONSE_END` — запись в `accesslog`, перевод в keep-alive или закрытие сокета.
- **Кэширование метаданных файлов (`stat-cache`):** Для предотвращения избыточных системных вызовов `stat()` при частых обращениях к статическим файлам Lighttpd поддерживает модуль кэширования метаданных файловой системы (движки `inotify`, `fam` или `simple`).
- **Многопроцессный режим (`server.max-worker`):** По умолчанию Lighttpd работает в одном процессе (`server.max-worker = 0`). При необходимости утилизации нескольких ядер CPU можно задать количество дочерних процессов, каждый из которых слушает общие сокеты через `SO_REUSEPORT` ядра Linux.

### Условные блоки конфигурации

Конфигурация Lighttpd использует декларативную модель на основе контекстных условий. Переменные окружения и заголовки сопоставляются с регулярными выражениями (`=~`, `!~`) или точными значениями (`==`, `!=`):

```lighttpd
# Проверка пути запроса
$HTTP["url"] =~ "^/api/" {
    # Директивы применяются только к путям /api/
}

# Проверка виртуального хоста
$HTTP["host"] == "example.com" {
    server.document-root = "/var/www/example.com"
}

# Проверка сокета и порта
$SERVER["socket"] == ":443" {
    ssl.engine = "enable"
}

# Проверка подсети клиента
$HTTP["remoteip"] == "192.168.1.0/24" {
    # Локальные правила доступа
}
```

### Сравнение с Nginx и Apache

| Характеристика | Lighttpd | Nginx / Angie | Apache HTTP Server (MPM event) |
| :--- | :--- | :--- | :--- |
| **Модель обработки** | Событийный цикл (epoll/kqueue). 1 процесс (или worker pool). | Событийный цикл (epoll/kqueue) с пулом воркеров на ядра CPU. | Гибридная: пул процессов с потоками внутри каждого процесса. |
| **Потребление RAM (10k соед.)** | ~2–5 MB | ~2–10 MB | ~100–300 MB |
| **Производительность статики** | Высокая (`sendfile`, `writev`). | Максимальная в индустрии (оптимизированный Zero-Copy, AIO). | Средняя (накладные расходы потоков). |
| **Конфигурация** | Централизованная (условные блоки `$HTTP`). | Централизованная (блоки `server`, `location`). | Централизованная + распределенная (`.htaccess`). |
| **Модули** | Динамическая загрузка shared libraries (`.so`). | Статическая компиляция (или динамические DSO). | Динамическая загрузка (`mod_so`). |
| **HTTP/2** | Да (нативно с версии 1.4.59 через ALPN). | Да (полная поддержка). | Да (`mod_http2`). |
| **HTTP/3 (QUIC)** | Нет (не поддерживается в ветке 1.4.x). | Да (начиная с Nginx 1.25+ / Angie 1.2+). | Экспериментально (`mod_http3`). |
| **L4-проксирование** | Да (`mod_sockproxy`, сырой TCP/UNIX). | Да (`ngx_stream_proxy_module`). | Да (`mod_proxy` в режиме TCP). |
| **Сложные L7-балансировки** | Базовые (round-robin, hash). | Продвинутые (least_conn, hash, active checks в коммерческих версиях/Angie). | Продвинутые (`mod_proxy_balancer`). |
| **Поведение при пиковых нагрузках** | Эффективен на малых VPS; деградирует при нехватке дескрипторов. | Линейная масштабируемость по ядрам CPU. | Деградирует по памяти при росте соединений. |

### Сценарии использования Lighttpd

| Сценарий | Обоснование выбора |
| :--- | :--- |
| **VPS с экстремально малым объемом RAM (128–512 MB)** | Минимальный базовый footprint позволяет сохранить ресурсы для СУБД и приложения. |
| **Встроенные платформы и IoT (OpenWrt, Raspberry Pi)** | Малый размер бинарного файла, быстрое время холодного старта, низкое энергопотребление. |
| **Выделенные узлы отдачи статики** | Высокая пропускная способность при использовании `sendfile` без лишней функциональности. |
| **Локальные WebDAV-серверы** | Наличие модуля `mod_webdav` с поддержкой свойств и базовых блокировок без внешних демонов. |
| **Legacy-инфраструктура с FastCGI/CGI** | Прямая поддержка старых сценариев взаимодействия без сложных адаптеров. |

### Когда выбирать Nginx или HAProxy вместо Lighttpd

- **Необходимость протокола HTTP/3 (QUIC):** Lighttpd 1.4.x не поддерживает транспорт QUIC.
- **Высоконагруженные кластеры с балансировкой:** Необходимы активные health checks бэкендов, плавный вывод узлов из ротации или динамическое управление upstreams через API (требуются HAProxy или Angie/Nginx).
- **Полнофункциональный WAF:** Сложные наборы правил ModSecurity / Coraza имеют лучшую поддержку и производительность в экосистеме Nginx/Apache.

---

## Практические сценарии

### Сценарий 1: Базовая производственная конфигурация

Развертывание веб-сервера для безопасной и высокопроизводительной отдачи статики и интеграции модулей.

Файл `/etc/lighttpd/lighttpd.conf`:

```lighttpd
server.modules = (
    "mod_access",
    "mod_accesslog",
    "mod_auth",
    "mod_deflate",
    "mod_expire",
    "mod_redirect",
    "mod_rewrite",
    "mod_setenv",
    "mod_openssl"
)

# Системные параметры процесса
server.document-root = "/var/www/html"
server.upload-dirs   = ( "/var/cache/lighttpd/uploads" )
server.errorlog      = "/var/log/lighttpd/error.log"
server.pid-file      = "/run/lighttpd.pid"
server.username      = "www-data"
server.groupname     = "www-data"

# Сетевые настройки и системные лимиты
server.port            = 80
server.max-connections = 4096
server.max-fds         = 8192
server.network-backend = "sendfile"
server.stat-cache-engine = "inotify"
server.listen-backlog  = 1024

# MIME-типы файлов по умолчанию
mimetype.assign = (
    ".html" => "text/html",
    ".css"  => "text/css",
    ".js"   => "application/javascript",
    ".json" => "application/json",
    ".png"  => "image/png",
    ".jpg"  => "image/jpeg",
    ".jpeg" => "image/jpeg",
    ".svg"  => "image/svg+xml",
    ".ico"  => "image/x-icon",
    ".woff2"=> "font/woff2",
    ".txt"  => "text/plain"
)

# Сжатие ответов (mod_deflate)
deflate.cache-dir = "/var/cache/lighttpd/compress/"
deflate.mimetypes = (
    "text/html",
    "text/plain",
    "text/css",
    "application/javascript",
    "application/json",
    "image/svg+xml"
)
deflate.allowed-encodings = ( "br", "gzip", "deflate" )
deflate.min-compress-size = 256
deflate.max-compress-size = 131072

# Кэширование статических ресурсов (mod_expire и mod_setenv)
$HTTP["url"] =~ "\.(css|js|png|jpg|jpeg|gif|ico|svg|woff2)$" {
    expire.url = ( "" => "access plus 30 days" )
    setenv.add-response-header = (
        "Cache-Control" => "public, max-age=2592000, immutable"
    )
}

# Журналирование запросов
accesslog.filename = "/var/log/lighttpd/access.log"
accesslog.format   = "%h %V %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" %D"
```

**Проверка синтаксиса конфигурации:**

```bash
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
# → Syntax OK
```

### Сценарий 2: Терминация TLS и принудительный редирект HTTP → HTTPS

Настройка современного стека TLS 1.2 / 1.3 с использованием `mod_openssl` и заголовков защиты.

```lighttpd
server.modules += ( "mod_openssl", "mod_redirect", "mod_setenv" )

# Сокет для HTTPS
$SERVER["socket"] == ":443" {
    ssl.engine  = "enable"
    ssl.pemfile = "/etc/letsencrypt/live/example.com/fullchain.pem"
    ssl.privkey = "/etc/letsencrypt/live/example.com/privkey.pem"

    # Ограничение минимальной версии протокола TLS 1.2
    ssl.openssl.ssl-conf-cmd = (
        "MinProtocol" => "TLSv1.2",
        "CipherString" => "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:CHACHA20-POLY1305"
    )
    ssl.honor-cipher-order = "enable"

    # Заголовки безопасности
    setenv.add-response-header = (
        "Strict-Transport-Security" => "max-age=31536000; includeSubDomains",
        "X-Frame-Options" => "DENY",
        "X-Content-Type-Options" => "nosniff",
        "Referrer-Policy" => "strict-origin-when-cross-origin",
        "Permissions-Policy" => "geolocation=(), microphone=(), camera=()"
    )

    server.document-root = "/var/www/html"
}

# Принудительное перенаправление HTTP на HTTPS
$SERVER["socket"] == ":80" {
    $HTTP["host"] =~ "(.*)" {
        url.redirect = ( "^/(.*)" => "https://%1/$1" )
    }
}
```

> [!NOTE]
> Для развертывания TLS непосредственно на публичном IP-адресе без доменного имени с использованием короткоживущих сертификатов Let's Encrypt и OCSP Stapling обратитесь к руководству [Настройка TLS для IP-адреса в Lighttpd](lighttpd-tls-ip.md).

### Сценарий 3: Интеграция с PHP-FPM через FastCGI

Подключение обработчика PHP-скриптов через локальный UNIX-сокет и резервный TCP-порт.

```lighttpd
server.modules += ( "mod_fastcgi" )

# Назначение обработчика для индексных файлов
index-file.names += ( "index.php", "index.html" )

# Подключение к пулу PHP-FPM через UNIX-сокет (рекомендуется для минимальной задержки)
fastcgi.server = (
    ".php" => (
        "php-fpm-local" => (
            "socket" => "/run/php/php8.4-fpm.sock",
            "broken-scriptfilename" => "enable",
            "check-local" => "enable",
            "idle-timeout" => 60,
            "max-procs" => 1
        )
    )
)
```

**Проверка прав доступа к сокету:**
UNIX-сокет PHP-FPM должен быть доступен для чтения и записи пользователю веб-сервера (`www-data`):

```bash
ls -la /run/php/php8.4-fpm.sock
# → srw-rw---- 1 www-data www-data 0 Oct 14 12:00 /run/php/php8.4-fpm.sock
```

### Сценарий 4: Обратный прокси (Reverse Proxy) с балансировкой

Проксирование API-запросов к внутренним сервисам с балансировкой нагрузки между инстансами.

```lighttpd
server.modules += ( "mod_proxy" )

$HTTP["url"] =~ "^/api/" {
    proxy.balance = "round-robin"
    proxy.server  = (
        "" => (
            "api-node-01" => (
                "host" => "127.0.0.1",
                "port" => 8081,
                "connect-timeout" => 3,
                "read-timeout"    => 30
            ),
            "api-node-02" => (
                "host" => "127.0.0.1",
                "port" => 8082,
                "connect-timeout" => 3,
                "read-timeout"    => 30
            )
        )
    )
}
```

### Сценарий 5: Перезапись URL для Front-Controller (SPA / REST)

Маршрутизация всех несуществующих путей на единую точку входа (`index.html` или `index.php`).

```lighttpd
server.modules += ( "mod_rewrite" )

# Исключение статических ресурсов и служебных путей
url.rewrite-once = (
    "^/(css|js|images|fonts|favicon.ico)(/.*)?$" => "$0",
    "^/api/(.*)$" => "/api/$1",
    "^/.*(\?.*)?$" => "/index.html$1"
)
```

### Сценарий 6: Ограничение доступа по сети и HTTP Basic Auth

Защита панели управления или внутренних служебных эндпоинтов.

```lighttpd
server.modules += ( "mod_access", "mod_auth" )

# Настройка провайдера аутентификации
auth.backend = "htpasswd"
auth.backend.htpasswd.userfile = "/etc/lighttpd/.htpasswd"

$HTTP["url"] =~ "^/admin/" {
    # 1. Ограничение по белому списку подсетей
    $HTTP["remoteip"] !~ "^(127\.0\.0\.1|10\.0\.0\.[0-9]+)$" {
        url.access-deny = ( "" )
    }

    # 2. Требование аутентификации для разрешенных сетей
    auth.require = (
        "/admin" => (
            "method"  => "basic",
            "realm"   => "Restricted Administration Area",
            "require" => "valid-user"
        )
    )
}
```

**Создание файла учетных записей:**

```bash
sudo htpasswd -c -B -C 10 /etc/lighttpd/.htpasswd admin_user
# → New password: ...
# → Re-type new password: ...
# → Adding password for user admin_user
sudo chmod 640 /etc/lighttpd/.htpasswd
sudo chown root:www-data /etc/lighttpd/.htpasswd
```

### Сценарий 7: Мониторинг метрик (mod_status)

Сбор телеметрии и показателей нагрузки для систем мониторинга (Prometheus, Telegraf).

```lighttpd
server.modules += ( "mod_status" )

# Ограничение доступа к эндпоинтам мониторинга только с адресов loopback
$HTTP["remoteip"] == "127.0.0.1" {
    status.status-url     = "/server-status"
    status.config-url     = "/server-config"
    status.statistics-url = "/server-counters"
}
```

**Получение метрик через CLI:**

```bash
# Получение Apache-совместимого машиночитаемого статуса
curl -s http://127.0.0.1/server-status?auto
# → Total Accesses: 10452
# → Total kBytes: 42109
# → Uptime: 86400
# → BusyServers: 3
# → IdleServers: 1

# Получение данных в формате JSON
curl -s http://127.0.0.1/server-status?json | jq .
# → {
# →   "Total Accesses": 10452,
# →   "Total kBytes": 42109,
# →   "Uptime": 86400,
# →   "BusyServers": 3
# → }
```

### Сценарий 8: Управление сервисом под systemd и Graceful Reload

Интеграция с подсистемой `systemd`, повышение лимитов дескрипторов файлов и плавное обновление конфигурации.

Файл переопределения `/etc/systemd/system/lighttpd.service.d/override.conf`:

```ini
[Service]
LimitNOFILE=65536
ExecStartPre=
ExecStartPre=/usr/sbin/lighttpd -tt -f /etc/lighttpd/lighttpd.conf
Restart=on-failure
RestartSec=3s
```

Применение изменений юнита:

```bash
sudo systemctl daemon-reload
sudo systemctl restart lighttpd
```

**Проверка конфигурации и плавный перезапуск:**

```bash
# 1. Валидация синтаксиса и связывания сокетов
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
# → Syntax OK

# 2. Плавная перезагрузка демона без сброса активных клиентских сессий
sudo systemctl reload lighttpd

# 3. Проверка статуса сервиса
sudo systemctl status lighttpd --no-pager
# → Active: active (running)
```

### Сценарий 9: Ротация логов без остановки сервера

Настройка утилиты `logrotate` с переоткрытием файлов логов по сигналу `SIGHUP`.

Файл `/etc/logrotate.d/lighttpd`:

```text
/var/log/lighttpd/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    sharedscripts
    postrotate
        /bin/kill -HUP $(cat /run/lighttpd.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

**Тестирование ротации логов:**

```bash
sudo logrotate -d /etc/logrotate.d/lighttpd
# → reading config file /etc/logrotate.d/lighttpd
# → Handling 1 logs
```

### Сценарий 10: Резервное копирование и Disaster Recovery

План обеспечения непрерывности сервиса на случай аппаратных аварий или повреждения файлов конфигурации.

*   **RPO (Recovery Point Objective):** 1 час (регулярная синхронизация конфигураций через Git/резервную копию).
*   **RTO (Recovery Time Objective):** 5 минут (запуск резервного сервера с готовой копией конфигурации).

**Скрипт создания резервной копии конфигурации и TLS:**

```bash
sudo tar czf /var/backups/lighttpd-backup-$(date +%F_%H%M%S).tar.gz \
    /etc/lighttpd/ \
    /etc/letsencrypt/live/ \
    /etc/letsencrypt/archive/
# → /var/backups/lighttpd-backup-YYYY-MM-DD_HHMMSS.tar.gz
```

**Отказоустойчивость (High Availability):**
Для обеспечения бесперебойного переключения между активным и резервным узлами на уровне сети настраивается VRRP-демон `keepalived`, удерживающий плавающий виртуальный IP-адрес (VIP). При падении основного процесса `lighttpd` резервный узел берет VIP на себя в течение 2–3 секунд.

---

## Операции и команды

### Параметры командной строки (CLI)

| Команда | Описание | Ожидаемый результат |
| :--- | :--- | :--- |
| `lighttpd -t -f /etc/lighttpd/lighttpd.conf` | Быстрая проверка синтаксиса конфигурационного файла | `Syntax OK` |
| `lighttpd -tt -f /etc/lighttpd/lighttpd.conf` | Глубокая проверка синтаксиса и тестовое связывание сокетов | `Syntax OK` |
| `lighttpd -p -f /etc/lighttpd/lighttpd.conf` | Вывод распарсенного дерева конфигурации (dump AST) | Текстовый вывод полной структуры со всеми include |
| `lighttpd -v` | Вывод версии сборки | `lighttpd/1.4.76 (ssl) - a light and fast webserver` |
| `lighttpd -V` | Подробный вывод всех скомпилированных возможностей и библиотек | Список модулей (OpenSSL, ZSTD, Brotli, PCRE2, epoll) |
| `lighttpd -D -f /etc/lighttpd/lighttpd.conf` | Запуск сервера в foreground-режиме (без демонизации) | Полезно для отладки и запуска в systemd-юнитах |

### Сигналы управления процессом

| Сигнал | Назначение | Поведение процесса |
| :--- | :--- | :--- |
| `SIGHUP` | Переоткрытие логов | Закрывает текущие дескрипторы `access.log` и `error.log` и открывает их заново (для ротации). |
| `SIGINT` / `SIGTERM` | Немедленная остановка | Прекращает обработку запросов и завершает процесс. |
| `SIGQUIT` | Плавная остановка (Graceful shutdown) | Перестает принимать новые подключения, завершает активные соединения и корректно выходит. |

### Сетевая диагностика и проверка доступности

```bash
# Проверка прослушиваемых портов процессом lighttpd
sudo ss -tulpn | grep lighttpd
# → tcp LISTEN 0 1024 0.0.0.0:80  0.0.0.0:* users:(("lighttpd",pid=1234,fd=4))
# → tcp LISTEN 0 1024 0.0.0.0:443 0.0.0.0:* users:(("lighttpd",pid=1234,fd=5))

# Проверка заголовков ответа сервера
curl -sI http://127.0.0.1/
# → HTTP/1.1 200 OK
# → Server: lighttpd/1.4.76

# Проверка ответа сжатия gzip/brotli
curl -sI -H "Accept-Encoding: br, gzip" http://127.0.0.1/index.html | grep -i content-encoding
# → Content-Encoding: br
```

---

## Устранение неисправностей

### Сценарий 1: Конфликт портов при запуске (Address already in use)

**Симптомы:** Сервер не запускается. Команда `systemctl status lighttpd` возвращает статус `failed`. В журнале `error.log`:
`can't bind to port: 0.0.0.0:80 Address already in use`.

**Причина:** Другой веб-сервер (Nginx, Apache) или процесс занимает порт 80 или 443.

**Диагностика:**

```bash
sudo ss -tlnp | grep -E ':(80|443)\b'
# → LISTEN 0 128 *:80 *:users:(("apache2",pid=842,fd=4))
```

**Решение:**
1. Остановите и отключите конкурирующий сервис:
   ```bash
   sudo systemctl stop apache2 && sudo systemctl disable apache2
   ```
2. Повторно запустите Lighttpd:
   ```bash
   sudo systemctl start lighttpd
   ```

### Сценарий 2: Ошибка 503 Service Unavailable при работе с FastCGI

**Симптомы:** Браузер возвращает HTTP 503 при запросе `.php` файлов. В `error.log`:
`backend is overloaded; or: connection failed: Connection refused`.

**Причина:** Демон `php-fpm` не запущен, UNIX-сокет отсутствует, либо права доступа к сокету запрещают чтение/запись пользователю `www-data`.

**Диагностика:**

```bash
# Проверка статуса демона PHP-FPM
sudo systemctl status php8.4-fpm --no-pager
# → Active: inactive (dead)

# Проверка наличия и прав на сокет
ls -la /run/php/php*-fpm.sock
# → srw-rw---- 1 root root 0 Oct 14 10:00 /run/php/php8.4-fpm.sock
```

**Решение:**
1. Запустите демон PHP-FPM:
   ```bash
   sudo systemctl enable --now php8.4-fpm
   ```
2. Убедитесь, что в конфигурации пула `/etc/php/8.4/fpm/pool.d/www.conf` заданы корректный владелец и права сокета:
   ```ini
   listen.owner = www-data
   listen.group = www-data
   listen.mode = 0660
   ```
3. Перезапустите PHP-FPM:
   ```bash
   sudo systemctl restart php8.4-fpm
   ```

### Сценарий 3: Ошибка 403 Forbidden при доступе к статическим ресурсам

**Симптомы:** Клиент получает ошибку 403 Forbidden. В `error.log`:
`Directory index forbidden by options: /var/www/html/`.

**Причина:** В каталоге отсутствует индексный файл (`index.html`), а листинг каталогов (`mod_dirlisting`) отключен в целях безопасности. Либо права на каталог запрещают чтение процессу веб-сервера.

**Диагностика:**

```bash
# Проверка наличия индексного файла и прав
ls -ld /var/www/html /var/www/html/index.html
# → -rw-r----- 1 root root 240 Oct 14 11:00 /var/www/html/index.html
```

**Решение:**
1. Назначьте корректные права на чтение файлов и выполнение для директорий:
   ```bash
   sudo chown -R www-data:www-data /var/www/html
   sudo find /var/www/html -type d -exec chmod 755 {} +
   sudo find /var/www/html -type f -exec chmod 644 {} +
   ```

### Сценарий 4: Ошибка исчерпания дескрипторов (Too many open files)

**Симптомы:** При росте нагрузки запросы зависают или сбрасываются. В `error.log`:
`server.max-fds is larger than system limit` или `accept failed: Too many open files`.

**Причина:** Лимит открытых файловых дескрипторов (`RLIMIT_NOFILE`) на уровне процесса или ОС ниже значения `server.max-fds`.

**Диагностика:**

```bash
# Проверка лимитов запущенного процесса Lighttpd
cat /proc/$(pgrep -o lighttpd)/limits | grep "Max open files"
# → Max open files   1024   1024   files
```

**Решение:**
1. Увеличьте лимит в юните systemd (`/etc/systemd/system/lighttpd.service.d/override.conf`):
   ```ini
   [Service]
   LimitNOFILE=65536
   ```
2. Синхронизируйте значение `server.max-fds = 65536` в `/etc/lighttpd/lighttpd.conf`.
3. Примените конфигурацию:
   ```bash
   sudo systemctl daemon-reload && sudo systemctl restart lighttpd
   ```

### Сценарий 5: Ошибки TLS-рукопожатия (SSL handshake failed)

**Симптомы:** `curl` возвращает `SSL: certificate subject name does not match target host name` или `unable to get local issuer certificate`.

**Причина:** В директиве `ssl.pemfile` указан отдельный сертификат хоста (`cert.pem`) вместо полной цепочки (`fullchain.pem`), включающей промежуточный центр сертификации.

**Диагностика:**

```bash
openssl verify -CAfile /etc/letsencrypt/live/example.com/chain.pem /etc/letsencrypt/live/example.com/cert.pem
# → OK
```

**Решение:**
В `/etc/lighttpd/lighttpd.conf` всегда указывайте `fullchain.pem`:
```lighttpd
ssl.pemfile = "/etc/letsencrypt/live/example.com/fullchain.pem"
ssl.privkey = "/etc/letsencrypt/live/example.com/privkey.pem"
```

---

## Лучшие практики

### Безопасность

- **Запуск от непривилегированного пользователя:** Всегда указывайте `server.username = "www-data"` и `server.groupname = "www-data"`. Никогда не запускайте постоянный процесс от пользователя `root`.
- **Защита от сканирования директорий:** Не включайте модуль `mod_dirlisting` в общедоступных частях сайта.
- **Ограничение опасных HTTP-методов:** Блокируйте методы `TRACE`, `TRACK`, `DELETE` на уровне `mod_access`, если приложение их явно не требует.
- **Современная криптография:** Отключайте устаревшие протоколы SSLv3, TLS 1.0, TLS 1.1 через параметр `ssl.openssl.ssl-conf-cmd = ("MinProtocol" => "TLSv1.2")`. В версиях 1.4.75+ по умолчанию включены безопасные AEAD-шифры с Perfect Forward Secrecy (PFS).
- **Заголовки безопасности:** Добавляйте заголовок `Strict-Transport-Security` (HSTS) с временем жизни не менее полугода (`max-age=15768000`), а также `X-Content-Type-Options: nosniff` и `X-Frame-Options: DENY`.

### Производительность

- **Сетевой бэкенд:** Для Linux систем используйте `server.network-backend = "sendfile"`. Для систем с высокими требованиями к кешированию в памяти проверьте `server.stat-cache-engine = "inotify"`.
- **Пулы соединений FastCGI:** Размещайте сокеты PHP-FPM в оперативной памяти (директория `/run` или `tmpfs`) для исключения дисковых операций при межпроцессном взаимодействии.
- **Сжатие Brotli и Gzip:** Включайте сжатие только для текстовых типов данных размером от 256 байт до 128 MB. Попытка сжимать уже упакованные форматы (JPEG, PNG, WOFF2) приводит к бесполезной трате процессорного времени.

### Эксплуатация и автоматизация

- **Валидация перед перезагрузкой:** Встраивайте команду `lighttpd -tt -f <config>` в скрипты деплоя и CI/CD до вызова `systemctl reload lighttpd`.
- **Мониторинг ресурсов:** Настройте алерты по числу активных файловых дескрипторов и заполненности очереди сокетов `listen-backlog`.
- **Автономная ротация логов:** Настройте регулярную ротацию через `logrotate` с сигналом `SIGHUP`.

---

## Дополнительная информация

### См. также

- **[Настройка TLS для IP-адреса в Lighttpd](lighttpd-tls-ip.md)** — развертывание короткоживущих сертификатов Let's Encrypt для IP-адресов, профиль shortlived, настройка OCSP Stapling и systemd-таймеров.
- **[Сравнение веб-серверов](../Concepts/webserver_comparison.md)** — детальный сравнительный анализ архитектурных характеристик Nginx, Apache, HAProxy, Traefik и Lighttpd.
- **[WebDAV: Обзор и настройка](../../Linux/Networking/Services/webdav/webdav_overview.md)** — реализация файлового протокола WebDAV поверх HTTP/HTTPS.
- **[Официальный сайт Lighttpd](https://www.lighttpd.net/)** — документация проекта и история релизов.
- **[Redmine Wiki Lighttpd](https://redmine.lighttpd.net/projects/lighttpd/wiki)** — полное техническое описание директив ядра и всех модулей.
