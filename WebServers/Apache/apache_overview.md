# Apache HTTP Server 2.4+ (Обзор)

**Актуально для:** Apache HTTP Server 2.4.x

---

## Определения

**Apache HTTP Server** (httpd) — свободный модульный веб-сервер от Apache Software Foundation, поддерживающий протоколы HTTP/1.1, HTTP/2 и экспериментально HTTP/3. Актуальная стабильная ветка — 2.4.x (включая 2.4.62 / 2.4.63). В инфраструктуре DevOps, SRE и системного администрирования Apache выступает в роли обратного прокси (reverse proxy), фронтенда/бэкенда веб-приложений, шлюза с развитой системой аутентификации (LDAP, Kerberos, OIDC) и сервера приложений с поддержкой распределённой конфигурации `.htaccess`.

**Multi-Processing Module (MPM)** — архитектурный уровень ядра Apache, определяющий сетевую модель приёма и обработки клиентских подключений (процессы, потоки, циклы событий). По умолчанию в современных дистрибутивах (RHEL 9+, Debian 12+, Ubuntu 22.04+) используется модуль `event`.

**`<VirtualHost>`** — директива-контейнер, изолирующая конфигурацию отдельного сайта или сервиса на базе IP-адреса, порта и доменного имени (`Host`-заголовка).

**ServerRoot** — базовая директория файловой системы, относительно которой вычисляются все относительные пути сервера (конфигурационные файлы, скомпилированные модули, логи).

**DocumentRoot** — корневая директория файловой системы, из которой веб-сервер отдаёт статические файлы и ищет целевые ресурсы для входящих URL-путей.

**Dynamic Shared Object (DSO / mod_so)** — механизм динамической загрузки скомпилированных модулей (.so) в адресное пространство Apache во время старта или graceful reload без пересборки бинарного файла сервера.

**`.htaccess`** — децентрализованный текстовый файл конфигурации директории, обрабатываемый сервером «на лету» при каждом запросе к каталогу (если разрешено директивой `AllowOverride`).

**Scoreboard** — внутренняя структура разделяемой памяти (shared memory), в которой родительский процесс и воркеры Apache отслеживают состояние каждого слота обработки (чтение, ожидание, ответ, keep-alive). Доступна для мониторинга через `mod_status`.

---

## Основные концепции

### Архитектура и модель процессов

Архитектура Apache построена по схеме «родительский процесс — пул дочерних воркеров»:

```text
+-------------------------------------------------------------------------+
|                  Master Process (httpd / apache2)                       |
|        Запуск: root | Чтение конфигов | Открытие портов 80/443          |
|       Открытие дескрипторов логов | Управление пулом воркеров           |
+------------------------------------+------------------------------------+
                                     |
                                     | fork()
                                     v
+------------------------------------+------------------------------------+
|                Child Worker Processes (User: apache / www-data)         |
|                                                                         |
|  [Worker 1]                                [Worker N]                   |
|  +-------------------------------------+   +--------------------------+ |
|  | Listener Thread (epoll / kqueue)    |   | Listener Thread          | |
|  | Принимает сокеты, следит за         |   |                          | |
|  | keep-alive соединениями             |   |                          | |
|  +-------------------------------------+   +--------------------------+ |
|  | Worker Threads (ThreadsPerChild)    |   | Worker Threads           | |
|  | [Th 1] [Th 2] [Th 3] ... [Th N]     |   | [Th 1] [Th 2] ... [Th N] | |
|  | Исполняют фазы запроса, проксируют, |   |                          | |
|  | отдают контент, пишут логи          |   |                          | |
|  +-------------------------------------+   +--------------------------+ |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                   Shared Memory Scoreboard                              |
|       Синхронизация состояний воркеров для mod_status и балансировки    |
+-------------------------------------------------------------------------+
```

1. **Master/Parent Process**:
   * Запускается с привилегиями `root`.
   * Биндит привилегированные порты (80, 443), открывает системные дескрипторы логов до сброса привилегий.
   * Парсит конфигурационные файлы и распределяет задачи между дочерними процессами.
   * Не обрабатывает клиентский трафик напрямую, а управляет жизненным циклом воркеров по сигналам ОС (`SIGTERM`, `SIGUSR1`/`SIGWINCH`, `SIGHUP`).
2. **Child Worker Processes**:
   * Создаются через системный вызов `fork()` и сбрасывают привилегии до непривилегированного пользователя (`apache` в RHEL, `www-data` в Debian/Ubuntu).
   * Изолированы друг от друга; сбой одного процесса не обрушивает мастер-сервер и соседние пулы.
   * В зависимости от выбранного MPM используют процессы либо комбинацию процессов и потоков (threads).

### Модели MPM (Multi-Processing Modules)

| MPM | Архитектурная модель | Keep-Alive поведение | Область применения |
|---|---|---|---|
| **`event`** | Мультипроцессный + многопоточный с асинхронным циклом epoll/kqueue | Выделенный поток-листенер удерживает keep-alive без блокировки рабочих потоков | **Стандарт де-факто** для всех современных установок, high-load, reverse proxy и PHP-FPM. |
| **`worker`** | Мультипроцессный + многопоточный (синхронный) | Keep-alive соединение блокирует рабочий поток на всё время `KeepAliveTimeout` | Устаревающая модель, применяется при несовместимости с async-сокетами. |
| **`prefork`** | Изолированные однопоточные процессы (1 процесс = 1 соединение) | Процесс полностью занят клиентом | Исключительно для устаревших не-thread-safe модулей (например, встроенного `mod_php`). Требует больших объёмов RAM. |

**Механизм работы `event` MPM:**
Воркер запускает управляющий поток-слушатель (`Listener Thread`), который помещает неактивные клиентские сокеты (в состоянии keep-alive или ожидания TLS-рукопожатия) в системный мультиплексор `epoll`. Рабочий поток (`Worker Thread`) выделяется из пула только в момент фактического поступления порции HTTP-данных и возвращается в пул сразу после отправки ответа, не простаивая во время пауз между запросами клиента.

### Жизненный цикл обработки HTTP-запроса

Каждый входящий HTTP-запрос проходит через строго упорядоченный конвейер хуков (request processing pipeline):

1. **Post-Read-Request (`mod_unique_id`, `mod_setenvif`):** генерация уникального ID запроса, разбор базовых заголовков.
2. **URI Translation (`mod_rewrite`, `mod_alias`):** сопоставление запрашиваемого URL с файловой системой (`DocumentRoot`) либо с целевым бэкендом (`ProxyPass`).
3. **Header Parsing (`mod_headers`):** чтение и трансформация клиентских заголовков.
4. **Access Control (`mod_authz_core`):** проверка сетевых ограничений (`Require ip`, `Require all granted/denied`).
5. **Authentication & Authorization (`mod_authn_*`, `mod_authz_*`):** проверка учетных данных пользователя (Basic, Digest, LDAP, OIDC).
6. **Type Checking & MIME Mapping (`mod_mime`):** определение Content-Type и выбор целевого обработчика (Handler).
7. **Fixups (`mod_env`, `mod_headers`):** предгенерационная модификация заголовков ответа и переменных окружения.
8. **Content Generation (Handler):** генерация тела ответа (`default-handler` для статики, `proxy:fcgi://` для PHP-FPM, `proxy:http://` для reverse proxy).
9. **Logging (`mod_log_config`):** асинхронная запись транзакции в `access_log` и передача в пайпы ротации или syslog.

### Конфигурационные файлы и структура каталогов

Все настройки задаются в текстовых конфигурационных файлах. Файлы без расширения `.conf` игнорируются при использовании масок `*.conf`.

| Назначение | RHEL / Rocky Linux / AlmaLinux | Debian / Ubuntu |
|---|---|---|
| Имя сервиса systemd | `httpd.service` | `apache2.service` |
| Исполняемый бинарник | `/usr/sbin/httpd` | `/usr/sbin/apache2` |
| Утилита управления | `apachectl` | `apache2ctl` (или `a2enmod`/`a2ensite`) |
| Корневой каталог (`ServerRoot`) | `/etc/httpd` | `/etc/apache2` |
| Главный файл конфигурации | `/etc/httpd/conf/httpd.conf` | `/etc/apache2/apache2.conf` |
| Конфигурации сервисов / хостов | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/sites-available/*.conf`<br>`/etc/apache2/conf-available/*.conf` |
| Симлинки активных сайтов | Отсутствуют (включаются напрямую через `conf.d/`) | `/etc/apache2/sites-enabled/*.conf` |
| Загрузка модулей | `/etc/httpd/conf.modules.d/*.conf` | `/etc/apache2/mods-available/`<br>`/etc/apache2/mods-enabled/` |
| Каталог веб-контента по умолчанию | `/var/www/html` | `/var/www/html` |
| Системные журналы | `/var/log/httpd/` | `/var/log/apache2/` |
| Пользователь процесса по умолчанию | `apache:apache` | `www-data:www-data` |

**Ключевые директивы базового уровня:**

* **`ServerRoot "/etc/httpd"`** — корень сервера для относительных путей.
* **`Listen 80`** — привязка к IP и порту. Форматы: `Listen 80` (все IPv4/IPv6 интерфейсы), `Listen 192.168.1.10:80`, `Listen [2001:db8::1]:443`.
* **`User` / `Group`** — учетная запись для запуска дочерних воркеров.
* **`DocumentRoot "/var/www/html"`** — точка монтирования файлов сайта в URL `/`.
* **`ServerTokens Prod`** — ограничение информации о версии в заголовке `Server` (возвращает только `Server: Apache`).
* **`ServerSignature Off`** — отключение генерации футера с версией сервера на системных страницах ошибок (404, 500, 403).

### Контексты директив (Scopes)

Директивы Apache применяются на разных уровнях иерархии:

1. **Глобальный контекст (Global/Server config):** действует на весь процесс httpd вне блоков контейнеров.
2. **`<VirtualHost [IP]:[Port]>`:** группировка настроек для конкретного домена, IP или порта.
3. **`<Directory "/path/on/disk">`:** правила для абсолютного пути в файловой системе и всех его подкаталогов.
4. **`<Location "/url/path">`:** правила для запрашиваемого URL-адреса (независимо от того, где файл лежит на диске, критично для проксирования).
5. **`<Files "filename">` / `<FilesMatch "regex">`:** правила для конкретных файлов по маске имени.
6. **`.htaccess`:** локальные директивы внутри каталогов веб-сервера.

Детальный алгоритм слияния контекстов описан в документе [Порядок слияния конфигов](./apache-config-merge-order.md).

### Алгоритм выбора VirtualHost

При поступлении TCP-подключения сервер выбирает блок `<VirtualHost>` по строгому двухэтапному алгоритму:

1. **IP- and Port-Matching:**
   * Apache сопоставляет IP-адрес сетевого интерфейса и порт входящего сокета.
   * Конкретные IP-адреса имеют абсолютный приоритет над wildcard-значениями: `<VirtualHost 192.168.1.50:443>` побеждает `<VirtualHost *:443>`.
2. **Name-Based Matching:**
   * Среди всех виртуальных хостов, совпавших по IP и порту, анализируется заголовок HTTP `Host:` (или SNI в TLS-рукопожатии).
   * Проверяется точное совпадение с `ServerName`.
   * При отсутствии совпадения проверяется список псевдонимов `ServerAlias` (включая маски `*.example.com`).
   * **Правило Default VirtualHost:** Если совпадений по имени не найдено, запрос передаётся в **самый первый** объявленный в конфигурации `<VirtualHost>` для данного IP:порт (лексикографически первый файл в каталоге или верхний блок в файле).

Диагностика порядка виртуальных хостов выполняется командой:
```bash
apachectl -S
```

### Модель контроля доступа (`mod_authz_core`)

В Apache 2.4+ устаревшие директивы `Order`, `Allow`, `Deny` заменены на модульную структуру `Require`:

```apacheconf
# Разрешить доступ всем клиентам
Require all granted

# Полный запрет доступа (HTTP 403 Forbidden)
Require all denied

# Ограничение по сетевым адресам (IPv4 CIDR и отдельные хосты)
Require ip 10.0.0.0/8 192.168.1.100

# Ограничение по IPv6
Require ip 2001:db8::/32

# Требование успешной аутентификации пользователя
Require valid-user
Require user alice bob
Require group devops
```

Сложные логические условия объединяются в контейнеры `<RequireAll>`, `<RequireAny>`, `<RequireNone>`:

```apacheconf
<Directory "/var/www/internal">
    <RequireAll>
        Require ip 10.20.0.0/16
        Require valid-user
    </RequireAll>
</Directory>
```

### Файлы распределённой конфигурации (`.htaccess`)

Файлы `.htaccess` позволяют переопределять параметры веб-сервера на уровне отдельных каталогов без перезагрузки Apache:

```apacheconf
<Directory "/var/www/html">
    # Полный запрет чтения .htaccess (рекомендовано для production)
    AllowOverride None
</Directory>
```

* **Влияние на производительность:** При значении `AllowOverride All` сервер обязан при каждом входящем запросе выполнять системные вызовы `stat()` и читать файл `.htaccess` в текущем каталоге и **во всех родительских директориях** вплоть до корня файловой системы. Это снижает пропускную способность на 15–30 %.
* **Безопасность:** В продакшн-контурах рекомендуется выставлять `AllowOverride None`, а все необходимые правила (`mod_rewrite`, заголовки) переносить в статические блоки `<Directory>` основного конфигурационного файла.

---

## Практические сценарии

### 1. Установка и базовая инициализация

**RHEL 9 / Rocky Linux 9 / AlmaLinux 9:**

```bash
# Установка базового пакета и утилит администрирования
sudo dnf install -y httpd httpd-tools

# Проверка установленной версии
httpd -v
# → Server version: Apache/2.4.62 (or 2.4.63)

# Включение автозапуска и немедленный старт
sudo systemctl enable --now httpd
# → Created symlink /etc/systemd/system/multi-user.target.wants/httpd.service ...

# Открытие портов HTTP/HTTPS в межсетевом экране
sudo firewall-cmd --permanent --add-service={http,https}
sudo firewall-cmd --reload
# → success
```

**Ubuntu 22.04+ / Debian 12+:**

```bash
# Обновление индекса пакетов и установка
sudo apt update
sudo apt install -y apache2 apache2-utils

# Проверка версии
apache2 -v
# → Server version: Apache/2.4.62 (Debian) (или 2.4.63)

# Включение службы
sudo systemctl enable --now apache2
```

### 2. Управление службой и проверка сокетов

Для управления процессами Apache используется systemd. В боевых средах для обновления конфигурации применяется **graceful reload**, при котором активные TCP-соединения клиентов не сбрасываются:

```bash
# Проверка синтаксиса перед любым применением изменений (MANDATORY)
sudo apachectl configtest
# → Syntax OK

# Мягкая перезагрузка конфигурации без разрыва соединений
sudo systemctl reload httpd
# или
sudo apachectl graceful

# Полный перезапуск демона
sudo systemctl restart httpd

# Проверка сетевых сокетов, открытых процессом httpd
sudo ss -tlpn | grep -E "httpd|apache2"
# → LISTEN 0 511 *:80  *:* users:(("httpd",pid=1520,fd=4))
# → LISTEN 0 511 *:443 *:* users:(("httpd",pid=1520,fd=6))
```

### 3. Настройка типового VirtualHost с редиректом на HTTPS

В промышленной эксплуатации виртуальный хост порта 80 должен безусловно перенаправлять клиентов на защищённый протокол HTTPS с кодом `301 Moved Permanently`:

```apacheconf
# /etc/httpd/conf.d/app.example.com.conf (RHEL)
# /etc/apache2/sites-available/app.example.com.conf (Debian)

<VirtualHost *:80>
    ServerName app.example.com
    ServerAlias www.app.example.com
    ServerAdmin admin@example.com

    # Принудительный редирект всего входящего трафика на HTTPS
    RewriteEngine On
    RewriteCond %{HTTPS} off
    RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L]

    ErrorLog "/var/log/httpd/app_error.log"
    CustomLog "/var/log/httpd/app_access.log" combined
</VirtualHost>
```

**Валидация редиректа:**
```bash
curl -I http://app.example.com/api/v1/health
# → HTTP/1.1 301 Moved Permanently
# → Location: https://app.example.com/api/v1/health
```

### 4. Настройка SSL/TLS (HTTPS) и HTTP/2

Конфигурация TLS соответствует профилю Mozilla Intermediate (поддержка TLSv1.2 и TLSv1.3, современные шифры Forward Secrecy, OCSP Stapling и HTTP/2):

```apacheconf
<VirtualHost *:443>
    ServerName app.example.com
    DocumentRoot "/var/www/app/public"

    # Включение протокола HTTP/2 (с фоллбэком на HTTP/1.1)
    Protocols h2 http/1.1

    # Настройки SSL/TLS Engine
    SSLEngine on
    SSLCertificateFile "/etc/pki/tls/certs/app.example.com.crt"
    SSLCertificateKeyFile "/etc/pki/tls/private/app.example.com.key"
    SSLCertificateChainFile "/etc/pki/tls/certs/chain.crt"

    # Протоколы: только TLS 1.2 и TLS 1.3
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1

    # Наборы шифров для TLS 1.2 (TLS 1.3 управляется библиотекой OpenSSL автоматически)
    SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305
    SSLHonorCipherOrder off
    SSLSessionTickets off

    # OCSP Stapling (ускорение TLS handshake)
    SSLUseStapling on

    # Заголовок HSTS (принуждение к HTTPS на 1 год)
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"

    # Базовые заголовки безопасности
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"

    <Directory "/var/www/app/public">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    ErrorLog "/var/log/httpd/app_ssl_error.log"
    CustomLog "/var/log/httpd/app_ssl_access.log" combined
</VirtualHost>

# Настройка кэша OCSP Stapling на глобальном уровне (вне VirtualHost)
SSLStaplingCache "shmcb:/run/httpd/ssl_stapling(32768)"
```

**Валидация TLS и HTTP/2:**
```bash
curl -I --http2 https://app.example.com
# → HTTP/2 200
# → strict-transport-security: max-age=31536000; includeSubDomains
```

### 5. Настройка обратного прокси (Reverse Proxy) и WebSocket

Apache выступает в роли обратного прокси для микросервисов (Node.js, Go, Python), терминатора TLS и шлюза WebSocket:

```apacheconf
# Требуются модули: proxy, proxy_http, proxy_wstunnel
<VirtualHost *:443>
    ServerName api.example.com
    SSLEngine on
    SSLCertificateFile "/etc/pki/tls/certs/api.crt"
    SSLCertificateKeyFile "/etc/pki/tls/private/api.key"

    # Передача оригинального клиентского заголовка Host бэкенду
    ProxyPreserveHost On

    # Таймауты сетевого взаимодействия с бэкендом (секунды)
    ProxyTimeout 60

    # Проксирование WebSocket эндпоинта
    ProxyPass /ws/ ws://127.0.0.1:8080/ws/ retry=2
    ProxyPassReverse /ws/ ws://127.0.0.1:8080/ws/

    # Основное проксирование HTTP API
    ProxyPass / http://127.0.0.1:8080/ retry=2
    ProxyPassReverse / http://127.0.0.1:8080/

    # Передача признака HTTPS для бэкенда
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"
</VirtualHost>
```

**Валидация WebSocket соединения:**
```bash
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     https://api.example.com/ws/
# → HTTP/1.1 101 Switching Protocols
# → Upgrade: websocket
```

### 6. Восстановление реального IP (`mod_remoteip`)

Когда Apache установлен за внешним балансировщиком нагрузки (HAProxy, Nginx, сетевой шлюз), переменная `REMOTE_ADDR` содержит адрес прокси, а не конечного пользователя. Модуль `mod_remoteip` извлекает реальный адрес из доверенного заголовка:

```apacheconf
# Загрузка модуля (если не загружен по умолчанию)
LoadModule remoteip_module modules/mod_remoteip.so

# Чтение реального IP из заголовка X-Forwarded-For
RemoteIPHeader X-Forwarded-For

# Список IP-адресов или подсетей доверенных балансировщиков
# Клиентский заголовок принимается ТОЛЬКО от этих узлов
RemoteIPTrustedProxy 10.0.0.0/8 192.168.0.0/16 172.16.0.0/12 127.0.0.1

# Включение поддержки бинарного протокола PROXY protocol v1/v2 (например, от HAProxy)
# RemoteIPProxyProtocol On
# RemoteIPProxyProtocolExceptions 127.0.0.1

# Изменение формата логирования: спецификатор %a выводит реальный IP клиента
LogFormat "%a %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" combined_realip
CustomLog "/var/log/httpd/access_log" combined_realip
```

**Проверка:** при обращении через прокси в логе фиксируется внешний публичный адрес клиента, а правила `Require ip <адрес>` корректно фильтруют запросы по клиентскому IP.

### 7. Интеграция с PHP через PHP-FPM

В современных архитектурах встроенный `mod_php` полностью вытеснен связкой `event MPM` + `PHP-FPM` через протокол FastCGI (`mod_proxy_fcgi`):

```apacheconf
<VirtualHost *:80>
    ServerName site.example.com
    DocumentRoot "/var/www/site"

    # Маршрутизация всех файлов .php в UNIX-сокет PHP-FPM
    <FilesMatch \.php$>
        SetHandler "proxy:unix:/run/php-fpm/www.sock|fcgi://localhost"
    </FilesMatch>

    # Альтернатива: передача по TCP сокету (если FPM на отдельном хосте)
    # <FilesMatch \.php$>
    #     SetHandler "proxy:fcgi://127.0.0.1:9000"
    # </FilesMatch>

    <Directory "/var/www/site">
        DirectoryIndex index.php index.html
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

**Валидация:**
```bash
echo "<?php echo 'PHP-FPM OK: ' . phpversion();" | sudo tee /var/www/site/test.php
curl http://site.example.com/test.php
# → PHP-FPM OK: 8.3.x (или 8.2.x)
sudo rm -f /var/www/site/test.php
```

### 8. Настройка безопасности ОС: Firewall и SELinux

В RHEL-подобных дистрибутивах Apache изолирован контекстом SELinux `httpd_t`. При попытке обратиться к файлам вне `/var/www` или подключиться к бэкендам по сети SELinux блокирует операцию.

```bash
# 1. Проверка текущего контекста DocumentRoot
ls -Zd /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 /var/www/html

# Восстановление эталонного контекста для каталога контента
sudo restorecon -Rv /var/www/html

# 2. Разрешение веб-серверу подключаться к удалённым бэкендам (Reverse Proxy / FPM TCP)
sudo setsebool -P httpd_can_network_connect 1

# 3. Разрешение подключаться к СУБД (PostgreSQL, MariaDB)
sudo setsebool -P httpd_can_network_connect_db 1

# 4. Проверка отказов SELinux (AVC Denials) в реальном времени
sudo ausearch -m avc -ts recent | grep httpd
```

### 9. SRE: Настройка Healthcheck-эндпоинта без засорения логов

Балансировщики нагрузки опрашивают веб-сервер каждые несколько секунд. Чтобы healthcheck не раздувал файлы журналов, используется условное логирование через `SetEnvIf`:

```apacheconf
# Исключение проверок доступности из access.log
SetEnvIf Request_URI "^/healthz$" dontlog

# Применение фильтра к журналу
CustomLog "/var/log/httpd/access_log" combined env=!dontlog

# Легковесный эндпоинт проверки здоровья сервера
<Location "/healthz">
    # Не обращаться к файловой системе, вернуть статический ответ
    # Требует mod_echo или стандартный виртуальный ответ
    ErrorDocument 200 "OK"
    RewriteEngine On
    RewriteRule .* - [R=200,L]
    Require all granted
</Location>
```

**Валидация:**
```bash
curl -i http://localhost/healthz
# → HTTP/1.1 200 OK
# → OK
```

### 10. SRE: Zero-Downtime Reload и Graceful Shutdown

При перезапуске воркеров во время выкатки релизов или ротации сертификатов критично не прерывать длинные клиентские запросы:

```apacheconf
# /etc/httpd/conf.d/00-graceful.conf
# Время в секундах, предоставляемое воркерам на завершение активных транзакций
GracefulShutdownTimeout 30
```

Для предотвращения принудительного завершения процессов systemd раньше времени создаётся override-файл:

```ini
# /etc/systemd/system/httpd.service.d/timeout.conf
[Service]
TimeoutStopSec=35
```

```bash
sudo systemctl daemon-reload
sudo systemctl reload httpd
```

---

## Операции и команды

### Диагностика конфигурации и инспекция среды

| Команда | Назначение | Пример ожидаемого вывода |
|---|---|---|
| `apachectl configtest` | Полный синтаксический анализ конфигурации | `Syntax OK` |
| `apachectl -S` | Дерево VirtualHost (порты, имена, default хосты) | `*:80 site1.example.com (/etc/httpd/conf.d/site1.conf:1)` |
| `apachectl -M` | Список активных модулей ядра и расширений | `proxy_module (shared)`<br>`ssl_module (shared)` |
| `apachectl -V` | Параметры сборки, активный MPM, пути ServerRoot | `Server MPM: event`<br>`-D DEFAULT_PIDLOG="/run/httpd/httpd.pid"` |
| `httpd -k graceful` | Отправка сигнала мягкого релоада (`SIGWINCH`/`SIGUSR1`) | `# Сервис обновляет воркеры без разрыва соединений` |
| `httpd -k stop` | Немедленная остановка сервера (`SIGTERM`) | `# Процессы завершаются немедленно` |

### Анализ журналов на боевом сервере

```bash
# 1. Топ-20 IP-адресов по числу входящих запросов
awk '{print $1}' /var/log/httpd/access_log | sort | uniq -c | sort -rn | head -20
# →  14210 192.0.2.45
# →   8930 198.51.100.12

# 2. Распределение HTTP-кодов ответов (индикатор аномалий и всплесков 5xx)
awk '{print $9}' /var/log/httpd/access_log | sort | uniq -c | sort -rn
# → 154200 200
# →  12400 301
# →   1820 404
# →     42 500

# 3. Поиск последних критических ошибок в error_log
sudo tail -n 100 /var/log/httpd/error_log | grep -E "\[core:error\]|\[proxy:error\]|\[proxy_fcgi:error\]"
```

### Ротация журналов: logrotate против rotatelogs

В боевых системах используются два подхода к ротации журналов:

1. **Системный `logrotate` (стандарт дистрибутивов):**
   Ротирует файлы по расписанию cron/systemd-timer и отправляет сигнал `systemctl reload httpd` для открытия новых файлов.
   ```text
   # /etc/logrotate.d/httpd
   /var/log/httpd/*log {
       daily
       missingok
       rotate 14
       compress
       delaycompress
       notifempty
       sharedscripts
       postrotate
           /bin/systemctl reload httpd.service > /dev/null 2>/dev/null || true
       endscript
   }
   ```
2. **Встроенный `rotatelogs` (pipe-обработчик):**
   Позволяет ротировать логи без перезагрузки Apache по достижении фиксированного объёма (например, 50 МБ) или интервала времени:
   ```apacheconf
   CustomLog "|/usr/bin/rotatelogs -l -f /var/log/httpd/access_%Y%m%d.log 86400" combined
   ```

### Настройка производительности и расчёт пула воркеров (event MPM)

```apacheconf
# /etc/httpd/conf.modules.d/00-mpm-tuning.conf
<IfModule mpm_event_module>
    StartServers             4
    ServerLimit             16
    ThreadsPerChild         64
    MinSpareThreads         64
    MaxSpareThreads        256
    MaxRequestWorkers     1024
    MaxConnectionsPerChild 10000
    AsyncRequestWorkerFactor 2
</IfModule>
```

**Формула расчёта `MaxRequestWorkers` для системного инженера:**

$$\text{MaxRequestWorkers} = \text{ServerLimit} \times \text{ThreadsPerChild}$$

$$\text{MaxRequestWorkers} \le \frac{\text{Доступная RAM для Apache}}{\text{Средний RSS-размер одного потока/процесса}}$$

* **`MaxConnectionsPerChild 10000`** — уничтожает дочерний процесс после обработки 10 000 транзакций, предотвращая скрытые утечки памяти в C-библиотеках.
* **`AsyncRequestWorkerFactor 2`** — определяет, сколько соединений в состоянии keep-alive и ожидания может обслуживать поток-слушатель сверх лимита `MaxRequestWorkers`.

### Мониторинг через `mod_status` и Prometheus

Модуль `mod_status` экспортирует внутреннее состояние воркеров и метрики производительности:

```apacheconf
# Включение детальной статистики
ExtendedStatus On

<Location "/server-status">
    SetHandler server-status
    # Доступ разрешён строго локально или из сети мониторинга
    Require local
    Require ip 10.100.0.15
</Location>
```

**Проверка машинночитаемого вывода:**
```bash
curl -s http://127.0.0.1/server-status?auto
# → Total Accesses: 49821
# → Total kBytes: 154201
# → Uptime: 86400
# → ReqPerSec: 0.576632
# → BusyWorkers: 3
# → IdleWorkers: 125
# → Scoreboard: __W________________.....
```

**Расшифровка состояний Scoreboard:**

| Символ | Состояние | Значение для SRE / Инженера |
|---|---|---|
| `_` | Waiting for Connection | Воркер простаивает в ожидании входящего TCP-пакета |
| `S` | Starting up | Процесс/поток инициализируется |
| `R` | Reading Request | Чтение HTTP-заголовков (всплеск может указывать на Slowloris) |
| `W` | Sending Reply | Формирование и отправка ответа клиенту |
| `K` | Keepalive (read) | Соединение находится в паузе keep-alive |
| `D` | DNS Lookup | Сервер выполняет реверсивный DNS (должен быть отключен) |
| `C` | Closing connection | Закрытие TCP-сокета |
| `L` | Logging | Запись строки в файл журнала |
| `G` | Gracefully finishing | Воркер завершает обслуживание перед штатной остановкой |
| `I` | Idle cleanup of worker | Очистка ресурсов простаивающего потока |
| `.` | Open slot | Свободный слот, дочерний процесс ещё не выделен |

**Интеграция с Prometheus (`apache_exporter`):**

Экспортёр считывает эндпоинт `/server-status?auto` и преобразует его в формат Prometheus:

```bash
# Запуск официального экспортера Lusitaniae/apache_exporter
# Порт по умолчанию: 9117
/usr/local/bin/apache_exporter --scrape_uri="http://127.0.0.1/server-status?auto"
```

Метрики для алертинга:
* `apache_workers{state="busy"}` — загрузка пула воркеров (алерт при > 80% от MaxRequestWorkers).
* `apache_accesses_total` — общий rate запросов (RPS).
* `apache_scoreboard{state="reading"}` — мониторинг зависших сессий.

### Тюнинг ядра ОС (sysctl) и лимитов systemd

Для предотвращения отбрасывания входящих TCP-пакетов при пиковых нагрузках настраивается ядро Linux:

```ini
# /etc/sysctl.d/99-apache-network.conf
# Размер очереди сокетов на уровне ядра
net.core.somaxconn = 65535
# Очередь неполных TCP-соединений (SYN backlog)
net.ipv4.tcp_max_syn_backlog = 8192
# Быстрая утилизация time-wait сокетов
net.ipv4.tcp_fin_timeout = 15
```

```bash
sudo sysctl --system
```

**Ограничение и изоляция процесса через systemd override:**

```ini
# /etc/systemd/system/httpd.service.d/override.conf
[Service]
# Лимит на файловые дескрипторы (сокеты + файлы)
LimitNOFILE=65535
# Изоляция системных каталогов
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart httpd
```

---

## Типичные ошибки и диагностика

### 1. `AH00072: make_sock: could not bind to address`: конфликт портов

* **Симптом:** При запуске `systemctl start httpd` сервис переходит в статус `failed`. В журнале `error_log` запись: `(98)Address already in use: AH00072: make_sock: could not bind to address [::]:80`.
* **Причина:** Порт 80 или 443 уже занят другим процессом (Nginx, HAProxy, другой экземпляр httpd).
* **Диагностика:**
  ```bash
  sudo ss -tlpn | grep -E ":80|:443"
  # → LISTEN 0 511 *:80 *:* users:(("nginx",pid=842,fd=6))
  ```
* **Решение:** Остановить конфликтующий сервис (`sudo systemctl stop nginx`) либо изменить директиву `Listen` в конфигурации Apache на альтернативный порт (например, `Listen 8080`).

### 2. `AH00035: access to / denied (filesystem path)`: ошибки прав доступа

* **Симптом:** Браузер получает `403 Forbidden`. В `error_log`: `AH00035: access to /var/www/site/index.html denied (filesystem path /var/www/site) because search permissions are missing on a component of the path`.
* **Причина:** У пользователя `apache` / `www-data` отсутствуют права на исполнение (`+x`) на одну из родительских директорий по пути к целевому файлу.
* **Диагностика:**
  ```bash
  namei -l /var/www/site/index.html
  # → f: /var/www/site/index.html
  # → drwxr-xr-x root root /
  # → drwxr-xr-x root root var
  # → drwxr-x--- root root www      <-- ОШИБКА: нет флага x для остальных
  # → drwxr-xr-x root root site
  ```
* **Решение:** Добавить права на чтение каталогов по цепочке:
  ```bash
  sudo chmod 755 /var/www
  sudo chmod -R 755 /var/www/site
  ```

### 3. Отказ SELinux при чтении файлов или сетевом проксировании

* **Симптом:** Права в файловой системе верные (`755`), но Apache возвращает `403 Forbidden` для статики или `503 Service Unavailable` при попытке проксирования на `127.0.0.1:3000`.
* **Причина:** SELinux блокирует операцию (отсутствует контекст `httpd_sys_content_t` или выключен булеан сетевых соединений).
* **Диагностика:**
  ```bash
  # Проверка блокировок audit лога
  sudo ausearch -m avc -ts recent
  # → type=AVC msg=audit(...): avc:  denied  { name_connect } for  pid=1230 comm="httpd" dest=3000 scontext=system_u:system_r:httpd_t:s0 ...
  ```
* **Решение:**
  * Для сетевого проксирования:
    ```bash
    sudo setsebool -P httpd_can_network_connect 1
    ```
  * Для локальных файлов:
    ```bash
    sudo semanage fcontext -a -t httpd_sys_content_t "/custom/www(/.*)?"
    sudo restorecon -Rv /custom/www
    ```

### 4. `AH00534: httpd: Configuration error: More than one MPM loaded`

* **Симптом:** При старте сервера выводится критическая ошибка `AH00534: httpd: Configuration error: More than one MPM loaded.`
* **Причина:** В конфигурации одновременно раскомментированы строки `LoadModule` для нескольких модулей MPM (например, `mpm_prefork_module` и `mpm_event_module`).
* **Диагностика:**
  ```bash
  grep -rn "LoadModule mpm_" /etc/httpd/ /etc/apache2/
  # → /etc/httpd/conf.modules.d/00-mpm.conf:6:LoadModule mpm_prefork_module ...
  # → /etc/httpd/conf.modules.d/00-mpm.conf:15:LoadModule mpm_event_module ...
  ```
* **Решение:** Закомментировать все MPM, оставив строго один: `LoadModule mpm_event_module modules/mod_mpm_event.so`.

### 5. `AH00161: server reached MaxRequestWorkers setting`

* **Симптом:** Запросы клиентов висят в ожидании, растут задержки (latency), новые соединения отбрасываются по таймауту. В `error_log`: `[mpm_event:error] [pid 1201:tid ...] AH00161: server reached MaxRequestWorkers setting, consider raising the MaxRequestWorkers setting`.
* **Причина:** Все рабочие потоки заняты медленными бэкендами, атакой медленных запросов либо исчерпан расчётный лимит соединений.
* **Диагностика:**
  ```bash
  curl -s http://127.0.0.1/server-status?auto | grep -E "BusyWorkers|IdleWorkers"
  # → BusyWorkers: 1024
  # → IdleWorkers: 0
  ```
* **Решение:**
  1. Проверить, не зависли ли бэкенды (`ProxyTimeout`, PHP-FPM slow-log).
  2. Увеличить `ServerLimit` и `MaxRequestWorkers` в настройках MPM в соответствии с запасом доступной оперативной памяти.
  3. Включить защиту `mod_reqtimeout` от удержания потоков клиентами.

### 6. `AH00898: Error reading from remote server` (502 Bad Gateway)

* **Симптом:** Пользователь видит ошибку `502 Bad Gateway`. В `error_log`: `[proxy:error] AH00898: Error reading from remote server returned by /api/users`.
* **Причина:** Бэкенд аварийно завершил работу во время передачи ответа (crash, OOM killer) или разорвал TCP-соединение до отправки полных HTTP-заголовков.
* **Диагностика:** Проверить журнал приложения бэкенда (`journalctl -u backend-service`) и системный журнал ядра на предмет OOM Killer (`dmesg -T | grep -i oom`).

### 7. `AH00124: Request exceeded the limit of 10 internal redirects`

* **Симптом:** Сервер возвращает `500 Internal Server Error`. В `error_log`: `AH00124: Request exceeded the limit of 10 internal redirects due to probable configuration error. Use 'LimitInternalRecursion' to increase the limit if necessary. Use 'LogLevel rewrite:trace2' to debug.`
* **Причина:** Зацикливание правил `RewriteRule` в файле `.htaccess` или блоке `<Directory>`.
* **Решение:** Добавить условие выхода из рекурсии `RewriteCond %{REQUEST_FILENAME} !-f` либо флаг `[L]` (Last) / `[END]` в правилах перенаправления.

---

## Лучшие практики

### 1. Архитектура и сетевой стек
* **Использование `event` MPM:** Для всех новых инсталляций использовать исключительно `event`. `prefork` допустим только при поддержке устаревших монолитных библиотек.
* **Изоляция бэкендов через FastCGI/HTTP:** Запускать код приложений (PHP, Python, Ruby, Node.js) в изолированных сервисах под управлением выделенных менеджеров процессов (PHP-FPM, Uwsgi, Gunicorn), общаясь с Apache через локальные UNIX Domain сокеты или loopback TCP.

### 2. Конфигурационная гигиена и автоматизация
* **Инфраструктура как код (IaC):** Управлять файлами конфигурации централизованно через Ansible.
* **Автоматизированная валидация:** Включать `apachectl configtest` в pre-commit хуки и CI/CD пайплайны перед деплоем конфигураций на серверы.
* **Запрет `.htaccess`:** Всегда объявлять `AllowOverride None` в корневом каталоге `<Directory "/">`. Это исключает лишние дисковые I/O операции и снижает риски внедрения неавторизованных директив.

### 3. Современный TLS и криптографическая стойкость
* **Отказ от устаревших протоколов:** Запретить SSLv3, TLS 1.0, TLS 1.1 (`SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1`).
* **HSTS Preload:** Использовать директиву `Strict-Transport-Security` с длительным сроком действия (не менее 1 года) для защиты от атак типа SSL-Stripping.
* **OCSP Stapling:** Включать `SSLUseStapling on`, чтобы клиентам не требовалось запрашивать статус отзыва сертификата напрямую у удостоверяющего центра.

### 4. Заголовки безопасности HTTP
* Добавлять обязательные заголовки через модуль `mod_headers`:
  ```apacheconf
  Header always set X-Content-Type-Options "nosniff"
  Header always set X-Frame-Options "SAMEORIGIN"
  Header always set Referrer-Policy "strict-origin-when-cross-origin"
  Header always set Permissions-Policy "geolocation=(), microphone=(), camera=()"
  ```

### 5. Защита от DoS и атак типа Slowloris
* Активировать модуль `mod_reqtimeout` с жёсткими лимитами на приём заголовков и тела запроса:
  ```apacheconf
  <IfModule reqtimeout_module>
      RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500
  </IfModule>
  ```
* Устанавливать реалистичный `KeepAliveTimeout` в диапазоне `2–5` секунд. Превышение этого значения приводит к блокировке слотов воркеров простаивающими клиентами.

### 6. Кэширование статических ресурсов и ускорение I/O
* **Отдача через ядро:** Директива `EnableSendfile On` позволяет ядру Linux передавать файл напрямую из дискового кэша в сетевой сокет через системный вызов `sendfile()`, минуя контекст пользователя.
* **Заголовки кэширования:** Для неизменяемой статики (шрифты, скомпилированные JS/CSS бандлы) выставлять заголовок `Cache-Control: public, max-age=31536000, immutable`.

### 7. Мониторинг, логирование и алертинг
* **Структурированный JSON:** В высоконагруженных окружениях форматировать `CustomLog` в формате JSON для бесшовного парсинга сборщиками логов (Vector, Filebeat).
* **Скрытие служебных страниц:** Эндпоинты `/server-status` и `/server-info` должны быть защищены директивами `Require local` или `Require ip <адрес мониторинга>` и исключены из публичной маршрутизации.

### 8. Минимальные привилегии и права на файлы
* **Владение каталогами:** Все исполняемые файлы и конфигурации должны принадлежать пользователю `root`, а веб-сервер должен иметь право только на чтение (`chmod 640` для файлов, `750` для директорий).
* **Каталоги загрузок (Uploads):** В каталогах, куда пользователи могут загружать файлы, необходимо жестко запрещать исполнение скриптов:
  ```apacheconf
  <Directory "/var/www/site/uploads">
      php_admin_flag engine off
      Options -ExecCGI -Indexes
      SetHandler default-handler
  </Directory>
  ```

### 9. Резервное копирование и Disaster Recovery (DR)
* **Минимальный состав бэкапа:**
  * Каталоги конфигурации: `/etc/httpd/` или `/etc/apache2/`.
  * TLS-сертификаты и приватные ключи: `/etc/pki/tls/` или `/etc/ssl/`.
  * Файлы учетных записей: `/etc/httpd/.htpasswd`.
* **RPO и RTO:**
  * **RPO (Recovery Point Objective):** 24 часа для конфигурационных файлов (хранение версий в Git репозитории).
  * **RTO (Recovery Time Objective):** не более 15 минут при автоматизированном развёртывании через Ansible плейбук.
* **Отказоустойчивость (HA):** Для локальных отказоустойчивых кластеров использовать Keepalived с плавающим виртуальным IP-адресом (VIP) между несколькими нодами Apache.

---

## Дополнительная информация

### Архитектурное сравнение: Apache и Nginx / Angie

| Критерий | Apache HTTP Server | Nginx / Angie |
|---|---|---|
| **Модель соединений** | Многопоточная / гибридная (`event` MPM, выделенные потоки на активный запрос) | Чистый асинхронный event-loop (однопоточный рабочий процесс обслуживает тысячи сокетов) |
| **Расход памяти при C10k** | Умеренный/высокий (память стека потоков на активное соединение) | Минимальный (фиксированные пулы памяти) |
| **Децентрализация (.htaccess)** | Полная поддержка «на лету» без перезагрузки сервера | Отсутствует (только централизованный статический конфиг) |
| **Модули** | Динамическая загрузка DSO через `LoadModule` без пересборки | Динамические модули поддерживаются, но зависят от точной версии бинарника |
| **Сложные сценарии аутентификации** | Богатейшая экосистема встроенных модулей (LDAP, GSSAPI/Kerberos, OIDC, AuthNZ) | Требуются сторонние сборки или коммерческие расширения |
| **Оптимальная роль в инфраструктуре** | Сервер приложений, шлюз корпоративной аутентификации, гибкий бэкенд | Высоконагруженный пограничный обратный прокси (Edge Reverse Proxy), отдача статики |

### Статус протокола HTTP/3 (QUIC)

Поддержка HTTP/3 в ветке Apache 2.4.x реализуется через модуль `mod_http2` (экспериментальная функциональность) либо через вспомогательные библиотеки OpenSSL 3.2+ / nghttp3 / lsquic. В промышленной эксплуатации в 2026 году для обслуживания HTTP/3 на передовом контуре рекомендуется использовать Nginx или Angie в качестве TLS/QUIC терминатора, передавая трафик на Apache по HTTP/2 (`h2c`) или локальному сокету.

### См. также

* [Укрепление безопасности Apache](./apache_hardening.md) — исчерпывающее руководство по харденингу и защите сервера.
* [Перенаправления и перезапись URL](./apache_rewrite_and_redirects.md) — практические примеры `mod_rewrite`, `Redirect`, `Alias`.
* [Балансировка нагрузки](./apache_load_balancing.md) — балансировка пулов бэкендов через `mod_proxy_balancer`.
* [Аутентификация и авторизация](./apache_authentication.md) — интеграция с LDAP/AD, Kerberos, Digest и mTLS.
* [Серверное кэширование](./apache_caching.md) — ускорение ответов через `mod_cache` и `mod_cache_disk`.
* [Настройка производительности](./apache_performance_tuning.md) — детальный тюнинг параметров MPM и пулов воркеров.
* [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — тонкая настройка `mod_proxy` и gRPC.
* [Прямое проксирование](./apache-forward-proxy.md) — настройка forward-прокси и туннелирования CONNECT.
* [Порядок слияния конфигов](./apache-config-merge-order.md) — правила наследования директив в иерархии контейнеров.
* [Обработчики и MIME](./apache-handlers-and-mime.md) — настройка Handlers, Action, CGI и типов MIME.
* [Интеграция Tomcat (AJP)](./apache-tomcat-ajp.md) — подключение Java-контейнеров по бинарному протоколу AJP.
* [Интеграция Python (mod_wsgi)](./apache-python-wsgi.md) — запуск приложений WSGI в режиме демона.
* [SSO через OIDC (mod_auth_openidc)](./apache-oidc-sso.md) — единая точка входа через Keycloak и OIDC.
* [Apache в Docker](./apache-in-docker.md) — контейнеризация httpd и запуск в Docker Compose.
* [Сборка из исходников](./apache-install-from-source.md) — ручная компиляция и сборка кастомных модулей через `apxs`.
* [Тестирование производительности веб-серверов](../webserver_benchmarking.md) — профилирование утилитами `ab` и `wrk`.
* [Экспортёры Prometheus для веб-серверов](../../Prometheus/Exporters/other_exporters.md) — обзор экспортеров метрик.
* [Диагностика веб-серверов](../Concepts/webserver_troubleshooting.md) — систематический подход к решению инцидентов.
