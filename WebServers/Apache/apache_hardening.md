# Укрепление безопасности Apache

---







## Определения

**Укрепление безопасности Apache (Apache hardening)** — процесс настройки веб-сервера с целью уменьшения поверхности атаки и защиты от распространённых уязвимостей. Основная задача — минимизировать риски путём отключения ненужных функций, ограничения доступа и контроля над системными ресурсами.

**`mod_security`** — WAF (Web Application Firewall). Детальные настройки и правила — в [Обзор WAF](../../Security/ApplicationSecurity/waf.md).

**`mod_evasive`** — модуль, защищающий от DoS, Brute-force и атак по exhaustion на уровне IP. Включает динамический блокировочный список и throttling.

**`mod_reqtimeout`** — защита от Slowloris и Slow POST. Ограничивает время на получение заголовков и тела запроса с минимальной скоростью передачи.

**SELinux** — механизм изоляции процессов контекстами безопасности. Apache работает в домене `httpd_t`. Крайне важен для ограничения поверхности атаки при компрометации веб-процесса.

**systemd unit override** — механизм переопределения параметров службы без изменения исходного unit-файла. Используется для установки `ProtectHome`, `ProtectSystem`, `PrivateTmp`, `LimitNOFILE`.

**Fail2Ban** — daemon, сканирующий логи и автоматически блокирующий IP при превышении порога нарушений. Взаимодействует с `iptables`, `firewalld` или `ufw`.

---







## Основные концепции

### Расположение конфигурационных файлов

| Компонент | RHEL/Rocky Linux/AlmaLinux | Debian/Ubuntu |
|---|---|---|
| Основной конфиг | `/etc/httpd/conf/httpd.conf` | `/etc/apache2/apache2.conf` |
| Дополнительные конфиги | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/conf-available/*.conf` |
| Виртуальные хосты | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/sites-available/*.conf` |
| Модули | `/etc/httpd/conf.modules.d/*.conf` | `/etc/apache2/mods-available/` |
| Модули (включённые) | `conf.modules.d/` | `/etc/apache2/mods-enabled/` (symlinks) |
| Логи ошибок | `/var/log/httpd/error_log` | `/var/log/apache2/error.log` |
| Логи доступа | `/var/log/httpd/access_log` | `/var/log/apache2/access.log` |
| Unit-файл systemd | `/usr/lib/systemd/system/httpd.service` | `/usr/lib/systemd/system/apache2.service` |
| Systemd override | `/etc/systemd/system/httpd.service.d/*.conf` | `/etc/systemd/system/apache2.service.d/*.conf` |

### Почему hardening важен для DevOps/SRE

По умолчанию Apache отключает большинство hardening-директив, а legacy-решения могут оставлять включёнными устаревшие протоколы. Атака на веб-процесс может привести к:
- Чтению конфиденциальных файлов DocumentRoot
- Исполнению произвольного кода через `.htaccess` и `mod_cgi`
- DoS через Slowloris, exhaustion или SSL handshake abuse
- Утечке информации о версиях ПО через заголовки и страницы ошибок

Для hardening требуется:
1. **Ограничение поверхности атаки** — отключение ненужных модулей и функций
2. **Снижение влияния компрометации** — изоляция процессов, файловых прав, SELinux
3. **Детектирование** — логирование в SIEM, Fail2Ban, алерты по 5xx
4. **Исправление** — быстрая реакция на нарушения через audit2allow, rollback конфига

### Ключевые модули безопасности

**Обязательные к включению:**
*   **`mod_security`** — WAF. Правила OWASP Core Rule Set (CRS) + кастомные правила. Детали — в [Обзор WAF](../../Security/ApplicationSecurity/waf.md).
*   **`mod_headers`** — управление HTTP-заголовками (CSP, HSTS, X-Frame-Options, Permissions-Policy).
*   **`mod_ssl`** — TLS/HTTPS. TLS 1.3 + 1.2, устаревшие протоколы запрещены.
*   **`mod_reqtimeout`** — критически важен для защиты от Slowloris и Slow POST.
*   **`mod_evasive`** — базовый throttle по IP. Установка: `dnf install mod_evasive` или сборка из source.

**Рекомендуемые к включению:**
*   **`mod_remoteip`** — корректная обработка `X-Forwarded-For` / `X-Real-IP` за прокси/Nginx.
*   **`mod_status`** — мониторинг рабочих процессов. Должен быть защищён IP + auth.
*   **`mod_proxy` + `mod_proxy_http` + `mod_proxy_fcgi`** — обратное проксирование.

### MPM и безопасность

MPM определяет модель обработки соединений и влияет на устойчивость к DoS. Детальное сравнение — в [Обзор Apache](./apache_overview.md).

| MPM | Модель | Безопасность |
|---|---|---|
| **`event`** | асинхронная (epoll/kqueue) | По умолчанию в RHEL 9+, Ubuntu 22.04+, Debian 12+. Лучшая устойчивость к Slowloris при Keep-Alive. |
| **`prefork`** | 1 процесс = 1 соединение | Изоляция процессов выше, но уязвим к exhaustion при массовых соединениях. Legacy `mod_php`. |
| **`worker`** | процессы + потоки | Сбалансирован. Устаревает в пользу `event`. |

**Выбор:** `event` — для всех новых проектов. `prefork` — только для legacy `mod_php`. Переключение MPM требует остановки Apache.

### Цель hardening в контексте compliance

Для соответствия стандартам (PCI DSS, ISO 27001, SOC 2) требуется:
- Отключение ненужных HTTP-методов
- Маскировка версии ПО (`ServerTokens Prod`, `ServerSignature Off`)
- Принудительный HTTPS (HSTS)
- Ограничение размера запроса
- Защищённый доступ к `server-status` и `server-info`
- Аудит изменений конфигурации через Git
- Резервное копирование конфигурации и сертификатов

---







## Практические сценарии

### Безопасность файловой системы

**Цель:** ограничить права доступа так, чтобы веб-процесс мог только читать контент и писать в каталоги загрузки при необходимости.

```bash
# Владелец — root, группа — веб-пользователь
sudo chown -R root:www-data /var/www/html

# Директории: 750 (rwxr-x---)
sudo find /var/www/html -type d -exec chmod 750 {} \;

# Файлы: 640 (rw-r-----)
sudo find /var/www/html -type f -exec chmod 640 {} \;

# Каталог загрузок — только если backend требует записи
sudo chown -R www-data:www-data /var/www/html/uploads
sudo chmod 750 /var/www/html/uploads
```

**SELinux контекст:**

```bash
# Проверка контекста DocumentRoot
ls -Z /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 index.html

# Восстановление контекста для новых файлов
sudo restorecon -R /var/www/html

# Диагностика отказа в чтении
sudo ausearch -m avc -ts recent | grep httpd
```

**Принцип:** DocumentRoot должен быть `httpd_sys_content_t`. Директории с записью — `httpd_sys_rw_content_t`. Подробнее о контекстах и политиках — в [SELinux](../../Linux/Security/Mechanisms/SELinux.md).

### Защита от Slowloris (Тайм-ауты)

**Проблема:** атаки Slowloris удерживают соединения открытыми, отправляя данные крайне медленно, исчерпывая пул рабочих процессов.

**Решение:** `mod_reqtimeout` + `KeepAliveTimeout` + `RequestReadTimeout`.

```apacheconf
<IfModule mod_reqtimeout.c>
    RequestReadTimeout header=20-40,MinRate=500
    RequestReadTimeout body=20,MinRate=500
</IfModule>

# Таймаут на Keep-Alive соединение
KeepAliveTimeout 5

# Отключение Keep-Alive для максимальной устойчивости (опционально)
# KeepAlive Off

# Ограничение на строку запроса
LimitRequestFieldSize 8190
LimitRequestFields 50
```

**Диагностика:** при массовом росте рабочих процессов в `mod_status` (защищённом `server-status`) и отказе по `WorkerLimit` — проверить логи на медленные IP.

### Ограничение скорости запросов (Rate Limiting)

**Проблема:** ботов и атакующих нужно ограничивать по частоте запросов/скорости передачи, не полагаясь только на таймауты.

**Решение 1: `mod_ratelimit` (встроен в Apache 2.4+)** — ограничение скорости передачи (KB/s) для заданных путей.

```apacheconf
LoadModule ratelimit_module modules/mod_ratelimit.so

<Location "/download">
    SetOutputFilter RATE_LIMIT
    SetEnv rate-limit 50          # 50 KB/s на соединение
</Location>
```

**Решение 2: `mod_evasive`** — блокировка по частоте запросов с одного IP (пер-IP blacklist + throttling).

```apacheconf
LoadModule evasive20_module modules/mod_evasive20.so

DOSHashTableSize    3097
DOSPageCount        3            # >3 запросов одной страницы за интервал
DOSSiteCount        50           # >50 запросов всего за интервал
DOSPageInterval     1            # секунд, интервал подсчёта страниц
DOSSiteInterval     1            # секунд, интервал подсчёта по IP
DOSBlockingPeriod   10           # секунд, блокировка IP
DOSWhitelist        127.0.0.1
DOSWhitelist        10.0.0.0/8   # не блокировать внутренний периметр
# DOSSystemCommand "iptables -I INPUT -s %s -j DROP"   # опционально, интеграция с firewall
# DOSEmailNotify ops@example.com
```

Установка: `dnf install mod_evasive` (RHEL) / `apt install libapache2-mod-evasive` (Debian).

**Решение 3: `mod_qos`** (сторонний модуль) — гибкие лимиты соединений и RPS:

```apacheconf
QS_SrvRequestRate 100            # макс. запросов/сек на сервер
QS_SrvMaxConn 60                 # макс. одновременных соединений
QS_ClientEventRate 30            # макс. запросов/сек с одного IP
QS_ClientEventConnectionLimit 5  # макс. одновременных соединений с IP
# QS_LimitRequestBody 0 0 0 102400  # лимиты по типам запросов
```

**Диагностика:**
```bash
# Проверка блокировки mod_evasive (403 после превышения порога)
for i in $(seq 1 10); do curl -s -o /dev/null -w "%{http_code}\n" http://localhost/; done
# → 200 ... 200 403 403 (после DOSBlockingPeriod)

# Проверка статуса модуля
httpd -M | grep -iE "evasive|ratelimit"
# → evasive20_module (shared)
# → ratelimit_module (shared)

# Журнал блокировок mod_evasive
sudo tail -50 /var/log/httpd/error_log | grep -i evasive
```

### Дополнительные заголовки безопасности

**Цель:** защитить пользователей от кликджекинга, XSS, MIME-sniffing и передачи небезопасных данных.

```apacheconf
<IfModule mod_headers.c>
    # 1. HSTS — принудительный HTTPS на 2 года
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

    # 2. Защита от кликджекинга
    Header always set X-FrameOptions "SAMEORIGIN"

    # 3. Запрет MIME-sniffing
    Header always set X-Content-Type-Options "nosniff"

    # 4. Referrer Policy
    Header always set Referrer-Policy "strict-origin-when-cross-origin"

    # 5. Content Security Policy (CSP)
    Header always set Content-Security-Policy "default-src 'self'; script-src 'self'; object-src 'none'"

    # 6. X-XSS-Protection (legacy браузеры)
    Header always set X-XSS-Protection "1; mode=block"

    # 7. Permissions Policy (отключение геолокации, микрофона, камеры)
    Header always set Permissions-Policy "geolocation=(), microphone=(), camera=()"
</IfModule>
```

**CSP для сайтов с CDN / внешними ресурсами:**

```apacheconf
Header always set Content-Security-Policy "default-src 'self'; img-src 'self' https://cdn.example.com; script-src 'self' 'unsafe-inline'; connect-src 'self' https://api.example.com; frame-ancestors 'none'"
```

**Валидация:** проверка заголовков:

```bash
curl -I https://secure.example.com | grep -i strict-transport\|x-frame\|content-security-policy\|referrer-policy
# → Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
# → X-Frame-Options: SAMEORIGIN
# → Referrer-Policy: strict-origin-when-cross-origin
```

### Защита от атак через символические ссылки

**Проблема:** если `FollowSymLinks` включён, злоумышленник с доступом к файловой системе может создать символическую ссылку на `/etc/passwd` и получить доступ к конфиденциальным файлам.

**Решение:** заменить `FollowSymLinks` на `SymLinksIfOwnerMatch`.

```apacheconf
<Directory /var/www/html>
    Options -FollowSymLinks +SymLinksIfOwnerMatch
    AllowOverride None
    Require all granted
</Directory>
```

**Важно:** `SymLinksIfOwnerMatch` требует проверки владельца при каждом запросе, что даёт незначительное снижение производительности. Для DocumentRoot с неизменными владельцами — приемлемо.

### Отключение листинга каталогов

**Проблема:** по умолчанию Apache отображает содержимое директорий без `index.html`, раскрывая структуру DocumentRoot.

**Решение:** `Options -Indexes`.

```apacheconf
<Directory /var/www/html>
    Options -FollowSymLinks +SymLinksIfOwnerMatch -Indexes
    AllowOverride None
    Require all granted
</Directory>
```

### Защита конфиденциальных каталогов

**Цель:** ограничить доступ к служебным страницам и чувствительным каталогам.

```apacheconf
<Location "/server-status">
    SetHandler server-status
    Require ip 10.0.0.0/8
    Require ip 192.168.0.0/16
    Require ip 127.0.0.1
    # Аутентификация — обязательна при доступе извне
    AuthType Basic
    AuthName "Server status"
    AuthUserFile /etc/httpd/.htpasswd
    Require valid-user
</Location>

<Location "/server-info">
    SetHandler server-info
    Require ip 10.0.0.0/8
    Require ip 192.168.0.0/16
    Require ip 127.0.0.1
    # server-info содержит больше данных — только извнутри
    # AuthType Basic
    # AuthName "Server info"
    # AuthUserFile /etc/httpd/.htpasswd
    # Require valid-user
</Location>

<LocationMatch "^/(server-status|server-info)">
    # Дополнительная защита — маскировка server signature
    ServerSignature Off
    # Ограничение по User-Agent (опционально)
    # BrowserMatchNoCase "Googlebot" allowed_bot
    # Require env allowed_bot
    # Require ip 10.0.0.0/8
</LocationMatch>
```

**Проверка:**

```bash
curl -I https://example.com/server-status
# → HTTP/1.1 403 Forbidden (если IP не в списке)
curl -I https://example.com/server-status -H "X-Forwarded-For: 10.0.0.1"
# → HTTP/1.1 200 OK (если remoteip настроен и ip в списке)
```

### Ограничение размера запроса

**Цель:** предотвратить exhaustion диска и памяти через массовые загрузки.

```apacheconf
<VirtualHost *:80>
    ServerName example.com

    # Глобальный лимит на VHost — 100 КБ для обычных запросов
    LimitRequestBody 102400

    <Directory "/var/www/uploads">
        # Для каталога загрузок — 10 МБ
        LimitRequestBody 10485760

        # Отключение CGI/SSI в каталоге загрузок
        Options -ExecCGI -Includes
        AllowOverride None
        Require all granted
    </Directory>

    <Directory "/var/www/html">
        Options -FollowSymLinks +SymLinksIfOwnerMatch -Indexes -ExecCGI
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

**Диагностика:**

```bash
# При попытке загрузить файл больше лимита
curl -X POST -F "file=@large_file.bin" https://example.com/upload/
# → HTTP/1.1 413 Request Entity Too Large
```

### Использование пользовательских страниц ошибок

**Цель:** скрыть пути и версии через стандартные страницы ошибок.

```apacheconf
ErrorDocument 400 /errors/400.html
ErrorDocument 401 /errors/401.html
ErrorDocument 403 /errors/403.html
ErrorDocument 404 /errors/404.html
ErrorDocument 500 /errors/500.html
ErrorDocument 503 /errors/503.html
```

**Файлы ошибок:** размещаются вне DocumentRoot или в каталоге с `Require all denied` для прямого доступа.

```apacheconf
Alias /errors/ /var/www/errors/
<Directory "/var/www/errors">
    Options -Indexes -FollowSymLinks
    AllowOverride None
    Require all denied
</Directory>
```

**Диагностика:**

```bash
curl -I https://example.com/nonexistent
# → HTTP/1.1 404 Not Found
# → Server: Apache (без версии, если ServerTokens Prod)
```

### Скрытие информации о сервере

**Цель:** маскировка версии Apache и модулей в заголовках и страницах ошибок.

```apacheconf
# Скрыть версию Apache в заголовках
ServerTokens Prod

# Скрыть версию Apache в страницах ошибок
ServerSignature Off

# Отключить TRACE метод (XST уязвимость)
TraceEnable Off
```

**Проверка:**

```bash
curl -I https://example.com/
# → Server: Apache (без версии)
# → HTTP/1.1 200 OK
```

**ServerTokens варианты:**
- `Prod` — `Apache` (минимальный)
- `Major` — `Apache/2`
- `Minor` — `Apache/2.4`
- `Minimal` — `Apache/2.4.63`
- `OS` — `Apache/2.4.63 (Debian)`
- `Full` — `Apache/2.4.63 (Debian) OpenSSL/3.0.2`

### Отключение ненужных HTTP-методов

**Проблема:** по умолчанию Apache принимает все методы (GET, POST, PUT, DELETE, HEAD, OPTIONS, TRACE, CONNECT). Устаревшие методы могут использоваться для атак.

**Решение:** `LimitExcept`.

```apacheconf
<Directory "/var/www/html">
    <LimitExcept GET POST HEAD OPTIONS>
        Require all denied
    </LimitExcept>
</Directory>
```

**Для API, требующих PUT/DELETE/PATCH:**

```apacheconf
<Directory "/var/www/html/api">
    <LimitExcept GET POST PUT DELETE PATCH HEAD OPTIONS>
        Require all denied
    </LimitExcept>
</Directory>
```

**CORS preflight:**

```apacheconf
<Directory "/var/www/html/api">
    <IfModule mod_headers.c>
        Header always set Access-Control-Allow-Methods "GET, POST, PUT, DELETE, PATCH, OPTIONS"
        Header always set Access-Control-Allow-Origin "https://trusted.example.com"
    </IfModule>
</Directory>
```

### Настройка и анализ журналов

**Цель:** структурированные логи для SIEM и быстрого поиска нарушений.

```apacheconf
# Формат combined — стандарт де-факто
LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" combined

# JSON-формат для Elasticsearch/Splunk
LogFormat "{ \"remote_ip\": \"%h\", \"x_forwarded_for\": \"%{X-Forwarded-For}i\", \"request\": \"%r\", \"status\": \"%>s\", \"bytes\": \"%b\", \"user_agent\": \"%{User-Agent}i\", \"timestamp\": \"%t\" }" json_log

# Уровень логирования: debug, info, warn, error, crit, alert, emerg
LogLevel warn

# Пути логов
ErrorLog "logs/error_log"
CustomLog "logs/access_log" combined
CustomLog "logs/access_json.log" json_log
```

**Отправка логов в syslog:**

```apacheconf
CustomLog "|/usr/bin/logger -p local4.info -t apache" combined
ErrorLog syslog:local4
```

**Проверка logrotate:**

```bash
sudo cat /etc/logrotate.d/httpd
# Проверка без применения
sudo logrotate -d /etc/logrotate.d/httpd
```

### Настройка SSL/TLS

**Цель:** разрешить только современные протоколы и шифры, запретить устаревшие.

```apacheconf
<VirtualHost *:443>
    ServerName secure.example.com
    DocumentRoot /var/www/secure

    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/fullchain.pem
    SSLCertificateKeyFile /etc/pki/tls/private/privkey.pem

    # TLS 1.3 + 1.2, устаревшие протоколы запрещены
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1

    # ECDHE + RSA для forward secrecy (2026)
    SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305
    SSLHonorCipherOrder on

    # HSTS — принудительный HTTPS (2 года)
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

    # OCSP stapling — снижение задержки TLS-рукопожатия
    SSLUseStapling on
    SSLStaplingReturnResponderErrors off
    SSLStaplingCache "shmcb:/var/run/ocsp(128000)"

    # Отключение compression (CRIME атака)
    SSLCompression Off

    # Отключение renegotiation (устаревший, небезопасный)
    SSLInsecureRenegotiation Off
</VirtualHost>
```

**Для Debian/Ubuntu пути сертификатов:**

```apacheconf
SSLCertificateFile /etc/ssl/certs/fullchain.pem
SSLCertificateKeyFile /etc/ssl/private/privkey.pem
```

### Укрепление через systemd

**Цель:** ограничить возможности процесса Apache на уровне ядра через systemd unit-файл override.

```bash
# Создание override директории
sudo mkdir -p /etc/systemd/system/httpd.service.d

# Создание override.conf
sudo tee /etc/systemd/system/httpd.service.d/hardening.conf <<'EOF'
[Service]
# Ограничение открытых файлов
LimitNOFILE=65535

# Запрет доступа к /home, /root и /run/user
ProtectHome=true

# Доступ к /usr, /boot и /etc только на чтение
ProtectSystem=full

# Изолированный /tmp
PrivateTmp=true

# Запрет получения новых привилегий
NoNewPrivileges=true

# Ограничение возможностей (capabilities)
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

# Изоляция сети (опционально, если Apache только для статики)
# PrivateNetwork=true
EOF

# Применение
sudo systemctl daemon-reload
sudo systemctl restart httpd
```

**Проверка лимитов:**

```bash
cat /proc/$(pgrep -o httpd)/limits | grep "open files"
# → Max open files            65535                65535              files
```

**Важно:** `ProtectHome=true` может сломать пути к `.htpasswd` и каталогам загрузок. Использовать `ReadOnlyPaths=` / `ReadWritePaths=` для исключений.

### Интеграция с Fail2Ban

**Цель:** автоматическая блокировка IP при попытках подбора пароля или сканировании.

```bash
# Установка Fail2Ban (если не установлен)
# RHEL/Rocky
sudo dnf install fail2ban fail2ban-firewalld

# Debian/Ubuntu
sudo apt update && sudo apt install fail2ban ipset
```

```ini
# /etc/fail2ban/jail.local

[apache-auth]
enabled = true
port    = http,https
filter  = apache-auth
logpath = /var/log/apache2/error.log
maxretry = 3
findtime = 600
bantime = 3600

[apache-badbots]
enabled = true
port    = http,https
filter  = apache-badbots
logpath = /var/log/apache2/access_log
maxretry = 2
bantime = 86400

[apache-overflows]
enabled = true
port    = http,https
filter  = apache-overflows
logpath = /var/log/apache2/error_log
maxretry = 5
bantime = 3600
```

```bash
# Запуск Fail2Ban
sudo systemctl enable --now fail2ban

# Проверка статуса
sudo fail2ban-client status
# → Status
# |- Jail list: apache-auth, apache-badbots, apache-overflows
```

**Диагностика:**

```bash
# Просмотр заблокированных IP
sudo fail2ban-client status apache-auth
# → Currently banned: 203.0.113.50

# Разблокировка IP
sudo fail2ban-client unban 203.0.113.50
```

---







## Операции и команды

### Валидация конфигурации

| Команда | Назначение | Пример вывода |
|---|---|---|
| `apachectl configtest` | Синтаксическая проверка | `Syntax OK` |
| `apachectl -V` | Сборка, пути, MPM | `Server MPM: event` |
| `apachectl -S` | Виртуальные хосты | порты, домены, default |
| `apachectl -M` | Загруженные модули | `ssl_module (shared)` |
| `httpd -t` | Проверка конфига | `Syntax OK` |
| `httpd -D DUMP_VHOSTS` | Анализ VirtualHost | аналогично `-S` |

**Пример вывода `apachectl -S`:**

```text
VirtualHost configuration:
*:80                   site1.example.com (/etc/httpd/conf.d/site1.conf:1)
*:80                   site2.example.com (/etc/httpd/conf.d/site2.conf:1)
*:443                  secure.example.com (/etc/httpd/conf.d/ssl.conf:1)
ServerRoot: "/etc/httpd"
Main DocumentRoot: "/var/www/html"
```

**Пример вывода `apachectl -M`:**

```bash
apachectl -M
# → proxy_module (shared)
# → ssl_module (shared)
# → rewrite_module (shared)
# → security2_module (shared)
```

### Проверка hardening

| Команда | Назначение | Пример вывода |
|---|---|---|
| `apachectl -V` | ServerTokens, MPM | `Server MPM: event` |
| `apachectl -S` | server-status/limits | порты, домены |
| `apachectl -M` | модули | `security2_module (shared)` |
| `ss -tlpn \| grep httpd` | прослушиваемые порты | `LISTEN 0 128 *:80 *:*` |
| `cat /proc/$(pgrep -o httpd)/limits \| grep "open files"` | systemd лимиты | `Max open files 65535` |
| `sudo getsebool -a \| grep httpd` | SELinux booleans | `httpd_can_network_connect --> on` |
| `sudo ausearch -m avc -ts recent \| grep httpd` | последние отказания | `denied { read }` |
| `sudo fail2ban-client status` | Fail2Ban статус | `Jail list: apache-auth` |
| `curl -I https://example.com/ \| grep -i strict-transport\|x-frame\|server\|server-status` | заголовки безопасности | `X-Frame-Options: SAMEORIGIN` |

**Проверка server-status:**

```bash
curl -I https://example.com/server-status
# → HTTP/1.1 403 Forbidden (если IP не в списке)
```

**Проверка лимитов systemd:**

```bash
cat /proc/$(pgrep -o httpd)/limits | grep "open files"
# → Max open files            65535                65535              files
```

**Проверка SELinux denials:**

```bash
sudo ausearch -m avc -ts recent | grep httpd
# → type=AVC msg=audit(1620000000.000:123): avc:  denied  { read } for  pid=1234 comm="httpd" name="passwd" dev="dm-0" ino=12345 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:etc_t:s0 tclass=file
```

**Проверка Fail2Ban статуса:**

```bash
sudo fail2ban-client status
# → Status
# |- Jail list: apache-auth, apache-badbots, apache-overflows

sudo fail2ban-client status apache-auth
# → Currently banned: 203.0.113.50
```

### Управление конфигурацией (Ansible)

Для управления Apache в IaC:

```yaml
- name: Установить httpd
  ansible.builtin.dnf:
    name: httpd
    state: present

- name: Включить сервис
  ansible.builtin.systemd_service:
    name: httpd
    state: started
    enabled: true

- name: Скопировать VirtualHost
  ansible.builtin.copy:
    src: files/site.conf
    dest: /etc/httpd/conf.d/site.conf
    mode: '0644'
  notify: restart httpd

- name: Установить systemd hardening override
  ansible.builtin.copy:
    src: files/httpd-hardening.conf
    dest: /etc/systemd/system/httpd.service.d/hardening.conf
    mode: '0644'
  notify: restart httpd
```

Для Debian/Ubuntu заменить `httpd` на `apache2`. Детали — в [Ansible: Перекрестная совместимость LEMP/LAMP](../../Ansible/CrossPlatform/lamp-example.md).

---







## Диагностика

### HTTP 403 Forbidden

**Частые причины:**
*   Нет файла `index.html` в DocumentRoot и `Options -Indexes` включён
*   Файл DocumentRoot нечитаем пользователем `apache`
*   SELinux отказывает в доступе (проверка: `sudo ausearch -m avc -ts recent | grep httpd`)
*   `Require all denied` без исключений для IP
*   `AllowOverride None` и нет конфигурации для `.htaccess`

**Диагностика:**

```bash
# Синтаксическая проверка
sudo apachectl configtest
# → Syntax OK

# Проверка прав доступа
sudo ls -la /var/www/html
# → drwxr-x--- 2 root www-data ...

# Проверка SELinux контекста
sudo ls -Z /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 index.html

# Проверка логов ошибок
sudo tail -50 /var/log/httpd/error_log | grep -i "forbidden\|denied\|permission"
```

**Решение:** восстановить права: `sudo restorecon -R /var/www/html`, `sudo chown -R root:www-data /var/www/html`, `sudo chmod 750 /var/www/html`.

### HTTP 500 Internal Server Error

**Частые причины:**
*   Ошибка в `.htaccess` — проверить: `sudo apachectl configtest`
*   PHP/WSGI/FastCGI backend упал — проверить логи PHP-FPM/WSGI
*   Права на файлы — DocumentRoot должен быть читаемым пользователем `apache`
*   SELinux — проверка: `sudo ausearch -m avc -ts recent | grep httpd`

**Диагностика:**

```bash
# Синтаксическая проверка
sudo apachectl configtest
# → Syntax OK

# Проверка логов ошибок
sudo tail -100 /var/log/httpd/error_log | grep -i "error\|warn\|crit\|segfault"

# PHP-FPM ошибки (если используется)
sudo tail -50 /var/log/php-fpm/error.log
```

**Решение:** исправить ошибку в `.htaccess` или backend-е, восстановить права доступа.

### Address already in use

**Частые причины:**
*   Другой процесс слушает порт 80/443 (nginx, haproxy)
*   Apache был запущен дважды (не штатная остановка)
*   TIME_WAIT сокеты (после нештатной остановки)

**Диагностика:**

```bash
# Кто слушает порт 80?
sudo ss -tlpn | grep ':80'
# → LISTEN 0 128 *:80 *:* users:(("nginx",pid=1234,fd=12))

# Проверка дублирования httpd
ps aux | grep httpd
# → root     1234  0.0  0.1  12345  6789 ?  Ss   11:00   0:00 /usr/sbin/httpd -DFOREGROUND
# → apache   1235  0.0  0.1  12345  6790 ?  S    11:00   0:00 /usr/sbin/httpd -DFOREGROUND
```

**Решение:** остановить конфликтующий процесс, сменить Listen порт, подождать завершения TIME_WAIT.

### SELinux нарушение доступа

**Симптом:** Apache возвращает 403 Forbidden для конкретного файла.

**Диагностика:**

```bash
# Проверка контекста файла
ls -Z /var/www/html/private/index.html
# → unconfined_u:object_r:user_home_t:s0 ... (неправильный)

# Проверка отказов SELinux
sudo ausearch -m avc -ts recent | grep httpd
```

**Решение:**

```bash
# Восстановление контекста
sudo restorecon -R /var/www/html

# Для новых файлов
sudo chcon -R -t httpd_sys_content_t /var/www/html

# Генерация политики из логов
sudo ausearch -m avc -ts recent | audit2allow -M my_httpd
sudo semodule -i my_httpd.pp
```

### Конфликт MPM модулей

**Симптом:** `AH00558: configuration error` при старте — конфликт prefork/event/worker.

**Диагностика:**

```bash
# Проверка активного MPM
apachectl -V | grep MPM
# → Server MPM: event

# Проверка загруженных MPM модулей
grep -r "LoadModule.*mpm_" /etc/httpd/conf.modules.d/
# → должен быть только mpm_event_module
```

**Решение:** оставить только один MPM модуль, прорелоадить сервис.

### mod_ssl handshake failure

**Частые причины:**
*   Устаревший клиент (TLSv1.0/1.1) — запрещён
*   Неправильный путь к сертификату
*   Неправильные права на сертификат (должен быть читаем `apache`)
*   Истёкший сертификат

**Диагностика:**

```bash
# Проверка сертификата
openssl s_client -connect example.com:443 -servername example.com
# → SSL handshake has read ... bytes and written ... bytes

# Проверка прав на сертификат
sudo ls -la /etc/pki/tls/private/example.key
# → -rw-r----- 1 root apache 1708 Jan  1 00:00 /etc/pki/tls/private/example.key

# Проверка истечения сертификата
openssl x509 -in /etc/pki/tls/certs/fullchain.pem -noout -dates
# → notBefore=Jan  1 00:00:00 2026 GMT
# → notAfter=Dec 31 23:59:59 2026 GMT
```

**Решение:** обновить сертификат, исправить права, проверить `SSLProtocol` и `SSLCipherSuite`.

---







## Лучшие практики

### 1. Выбор MPM и обработка статики

Для новых проектов использовать `event` MPM. `prefork` — только для legacy `mod_php`. Nginx предпочтительнее для статики (C10k).

### 2. Управление конфигурацией

*   Конфигурация под управлением Git или Ansible (IaC).
*   Никогда не править конфиг на production без предварительного `apachectl configtest`.
*   Использовать `IncludeOptional` для модульной структуры.
*   Отключить `AllowOverride` везде, где возможно.

### 3. TLS 2026

*   TLSv1.2 — минимум, TLSv1.3 — предпочтительно.
*   `SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1`
*   HSTS с `preload` (подключение к [HSTS preload list](https://hstspreload.org)).
*   OCSP stapling — снижение задержки TLS-рукопожатия.

```apacheconf
SSLUseStapling on
SSLStaplingReturnResponderErrors off
SSLStaplingCache "shmcb:/var/run/ocsp(128000)"
```

### 4. Заголовки безопасности

```apacheconf
<IfModule mod_headers.c>
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
    Header always set X-FrameOptions "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Content-Security-Policy "default-src 'self'; img-src 'self' https:; script-src 'self'"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set Permissions-Policy "geolocation=(), microphone=()"
</IfModule>
```

### 5. Таймауты и защита от Slowloris

```apacheconf
KeepAliveTimeout 5
RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500
LimitRequestBody 10485760
LimitRequestFieldSize 8190
LimitRequestFields 50
```

### 6. Кэширование статики

```apacheconf
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresByType text/css "access plus 1 month"
    ExpiresByType application/javascript "access plus 1 month"
    ExpiresByType image/png "access plus 6 months"
    ExpiresByType image/jpeg "access plus 6 months"
    ExpiresByType font/woff2 "access plus 1 year"
</IfModule>

<IfModule mod_headers.c>
    <FilesMatch "\.(css|js)$">
        Header set Cache-Control "public, immutable"
    </FilesMatch>
</IfModule>
```

### 7. Мониторинг и алертинг

*   Мониторинг `error_log` через `journald`/`syslog` в SIEM.
*   Настройка алертов в Prometheus/Grafana на HTTP 5xx rate.
*   Мониторинг активности MPM (рабочих процессов) через `mod_status` (с аутентификацией).

```apacheconf
<Location "/server-status">
    SetHandler server-status
    Require ip 10.0.0.0/8
    Require ip 127.0.0.1
</Location>
```

Доступ: `curl http://localhost/server-status?auto`.

### 8. Регулярное обновление

```bash
# RHEL — патчи безопасности
sudo dnf update httpd openssl

# Debian/Ubuntu
sudo apt update && sudo apt upgrade apache2

# Проверка уязвимостей
rpm -Va httpd  # RHEL
dpkg -V apache2  # Debian
```

Проверка CVE: `https://httpd.apache.org/security/vulnerabilities_24.html`.

### 9. Права доступа к файлам

```bash
sudo chown -R root:apache /var/www/html
sudo chmod -R 750 /var/www/html
sudo find /var/www/html -type d -exec chmod 750 {} \;
sudo find /var/www/html -type f -exec chmod 640 {} \;
sudo chown root:apache /etc/httpd/.htpasswd
sudo chmod 640 /etc/httpd/.htpasswd
```

### 10. Резервное копирование

Минимальные бэкапы:
*   `/etc/httpd/` или `/etc/apache2/`
*   `/etc/pki/tls/` (сертификаты)
*   `/etc/httpd/.htpasswd`

```bash
sudo tar czf /backup/apache-conf-$(date +%F).tar.gz /etc/httpd/ /etc/pki/tls/
```

---







## Дополнительная информация

### Системы безопасности (SSoT)

| Файл | SSoT для |
|---|---|
| [Обзор Apache](./apache_overview.md) | MPM, VirtualHost, SELinux booleans, systemd hardening |
| [Обзор WAF](../../Security/ApplicationSecurity/waf.md) | mod_security правила, CRS |
| [SELinux](../../Linux/Security/Mechanisms/SELinux.md) | контексты, политики, audit2allow |
| [Fail2Ban](../../Linux/Security/Tools/fail2ban.md) | установка, фильтры, jail-конфигурации |

### Изоляция на уровне ОС

*   **SELinux**: В RHEL-системах необходимо проверять контексты файлов (`httpd_sys_content_t`). Подробнее: [SELinux](../../Linux/Security/Mechanisms/SELinux.md).
*   **AppArmor**: В Ubuntu/Debian используются профили для ограничения доступа процесса к файловой системе.

### См. также

*   **[Обзор Apache](./apache_overview.md)** — MPM, VirtualHost, SELinux.
*   **[Аутентификация и авторизация](./apache_authentication.md)** — LDAP/AD, Digest, клиентские сертификаты.
*   **[Настройка производительности](./apache_performance_tuning.md)** — MPM, scoreboard, TLS-сессии.
*   **[Прямое проксирование и защита от open proxy](./apache-forward-proxy.md)** — ProxyRequests, CONNECT, SSRF-защита.
*   **[SSO через OIDC (mod_auth_openidc)](./apache-oidc-sso.md)** — безопасная интеграция с IdP вместо локальных Basic-баз.
*   **[Обработчики и MIME](./apache-handlers-and-mime.md)** — контроль AddHandler/SetHandler, CGI, SSI.
*   **[WebDAV в Linux](../../Linux/Networking/Services/webdav/webdav_overview.md)** — включение/выключение DAV, права, проверки (настройка — там, SSoT).
*   **[Укрепление безопасности Nginx](../Nginx/Security/nginx_security_guide.md)** — сравнение подходов.
