# Apache HTTP Server 2.4+ (Обзор)

---







## Определения

**Apache HTTP Server** (часто называемый просто Apache) — свободный веб-сервер от Apache Software Foundation, обрабатывающий HTTP/1.1, HTTP/2 и экспериментально HTTP/3. Актуальная стабильная версия — 2.4.63 (2026 год). Apache обслуживает более 30 % всех активных сайтов в мире и является стандартным инструментом shared-хостинга, корпоративных сред и инфраструктурных задач (обратный прокси, SSL-терминация, балансировка). В 2026 году Apache критически важен для сценариев, требующих динамической конфигурации через `.htaccess` и богатой экосистемы модулей.

**Multi-Processing Modules (MPM)** — архитектурный слой Apache, определяющий модель обработки соединений. По умолчанию во всех современных дистрибутивах (RHEL 9+, Ubuntu 22.04+, Debian 12+) используется `event` MPM.

**`<VirtualHost>`** — контейнер конфигурации для одного сайта на конкретном IP/порту и доменном имени.

---







## Основные концепции

### Конфигурационные файлы

Все конфигурации хранятся в текстовых файлах. Пути зависят от дистрибутива ОС:

| Компонент | RHEL/Rocky Linux/AlmaLinux | Debian/Ubuntu |
|---|---|---|
| Основной конфиг | `/etc/httpd/conf/httpd.conf` | `/etc/apache2/apache2.conf` |
| Дополнительные конфиги | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/conf-available/*.conf` |
| Виртуальные хосты | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/sites-available/*.conf` |
| Модули (файлы) | `/etc/httpd/conf.modules.d/*.conf` | `/etc/apache2/mods-available/` |
| Модули (развёрнутые) | `conf.modules.d/` | `/etc/apache2/mods-enabled/` (symlinks) |
| Логи ошибок | `/var/log/httpd/error_log` | `/var/log/apache2/error.log` |
| Логи доступа | `/var/log/httpd/access_log` | `/var/log/apache2/access.log` |

**Абсолютно для всех дистрибутивов:** все конфигурационные файлы должны иметь расширение `.conf`. Файлы без этого расширения могут быть проигнорированы без предупреждения.

**Ключевые директивы `httpd.conf` / `apache2.conf`:**

*   **`ServerRoot "/etc/httpd"`** — корневая директория сервера. Все относительные пути (логи, модули) разрешаются относительно неё.
*   **`Listen 80`** — IP и порт прослушивания. Для IPv6: `Listen [::]:80`. Для конкретного интерфейса: `Listen 192.168.1.100:80`.
*   **`User apache` / `Group apache`** — непривилегированный пользователь/группа дочерних процессов.
*   **`DocumentRoot "/var/www/html"`** — корневая директория веб-контента.
*   **`IncludeOptional conf.d/*.conf`** — автоподгрузка конфигурационных файлов из директории.
*   **`ServerTokens Prod`** — маскировка версии Apache в заголовках (безопасность).
*   **`ServerSignature Off`** — отключение версии Apache в страницах ошибок.

**Пример: отключение SSLv3 и старых протоколов:**

```apacheconf
# В httpd.conf или conf.modules.d/
SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
```

### Уровни конфигурации (Scopes)

Директивы Apache могут быть ограничены контекстом:

1.  **Глобальный** — вне любых контейнеров.
2.  **`<Directory "/var/www/private">`** — путь файловой системы и рекурсивно.
3.  **`<Location "/api">`** — URL-путь запроса.
4.  **`<Files ".env">`** — конкретные файлы по имени.
5.  **`<VirtualHost *:443>`** — группировка для домена/IP.

Контексты вкладываются. Вложенная секция наследует и может переопределять родительскую директиву.

### Контроль доступа

В Apache 2.4+ используется `mod_authz_core`:

```apacheconf
<Directory "/var/www/html/private">
    Options -Indexes
    Require ip 192.168.1.0/24
    Require ip 10.0.0.0/8
    # Require all denied — запрет всем по умолчанию
</Directory>

<Directory "/var/www/html/secure">
    AuthType Basic
    AuthName "Restricted"
    AuthUserFile /etc/httpd/.htpasswd
    Require valid-user
</Directory>
```

**Важно:** порядок секций имеет значение. Первое совпадение `Require` определяет результат.

### Модульная система

Apache имеет модульную архитектуру. Каждая функция подключается отдельным модулем. Модули можно загружать статически или динамически.

| Дистрибутив | Включение модуля | Отключение модуля |
|---|---|---|
| RHEL/Rocky | `LoadModule proxy_module modules/mod_proxy.so` в конфиге | удалить или закомментировать строку `LoadModule` |
| Debian/Ubuntu | `a2enmod proxy_http` | `a2dismod proxy_http` |

**Критически важные для sysadmin модули:**

*   **`mod_proxy` + `mod_proxy_http` + `mod_proxy_fcgi`** — обратное проксирование, интеграция с PHP-FPM/Go/Node.js.
*   **`mod_ssl`** — TLS/HTTPS.
*   **`mod_rewrite`** — перенаправления URL (Regexp).
*   **`mod_headers`** — управление HTTP-заголовками.
*   **`mod_security`** — WAF. Детали — в [Обзор WAF](../../Security/ApplicationSecurity/waf.md).
*   **`mod_http2`** — поддержка HTTP/2.
*   **`mod_reqtimeout`** — защита от Slowloris.
*   **`mod_deflate`** — сжатие ответов.

**Команды проверки загруженных модулей:**

```bash
# Список модулей, скомпилированных динамически (RHEL)
grep -E "^LoadModule" /etc/httpd/conf.modules.d/*.conf

# Активные модули (Debian)
apache2ctl -M # → proxy_module (shared)
```

### Логирование

Apache использует кастомную систему логирования. Каждая секция `<VirtualHost>` может иметь свои пути.

```apacheconf
# Формат combined — стандарт де-факто
LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" combined

CustomLog "logs/access_log" combined
ErrorLog "logs/error_log"

# Уровень логирования: debug, info, warn, error, crit, alert, emerg
LogLevel warn
```

**Пример JSON-логирования для Elasticsearch/Splunk:**

```apacheconf
LogFormat "{\"remote_ip\":\"%h\",\"request\":\"%r\",\"status\":\"%>s\",\"bytes\":\"%b\"}" json
CustomLog "logs/access_json.log" json
```

### Виртуальные хосты

Каждый сайт описывается в отдельном `<VirtualHost>`. Настройки по умолчанию идут в первый совпавший VirtualHost (обычно `_default_:80`).

```apacheconf
<VirtualHost *:80>
    ServerName site1.example.com
    ServerAlias www.site1.example.com
    DocumentRoot /var/www/site1
    DirectoryIndex index.html index.php

    ErrorLog logs/site1_error.log
    CustomLog logs/site1_access.log combined

    <Directory "/var/www/site1">
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>

<VirtualHost [2001:db8::10]:80>
    ServerName ipv6.example.com
    DocumentRoot /var/www/ipv6
</VirtualHost>
```

**Активация виртуального хоста:**

```bash
# RHEL — достаточно положить файл в /etc/httpd/conf.d/
sudo systemctl reload httpd

# Debian/Ubuntu
sudo a2ensite site1.conf
sudo systemctl reload apache2
```

Для прослушивания дополнительного порта — добавить `Listen 8080` в основной конфиг и прорелоадить сервис.

### Правила выбора VirtualHost

Исполнение определяется в порядке parse-time (во время конфигурации), не runtime:

1.  **По порту/адресу:** сначала сопоставление IP/порта из `<VirtualHost>` (IP-based). Записи с конкретным IP (`<VirtualHost 203.0.113.5:443>`) считаются более специфичными, чем `*:443`.
2.  **По Host (name-based):** среди совпавших по IP:порт Apache выбирает точное `ServerName` → затем лучший `ServerAlias` (в т.ч. wildcard `*.example.com`) → затем **первый** подходящий VirtualHost в конфиге (англ. *default*, обычно `_default_`).
3.  Если для IP:порт нет VirtualHost — используется Global-конфигурация.

```apacheconf
# «Первый в списке» становится default для :80
<VirtualHost *:80>
    ServerName default.example.com    # совпадает по умолчанию
    DocumentRoot /var/www/default
</VirtualHost>

<VirtualHost *:80>
    ServerName app.example.com
    ServerAlias *.example.com         # + любые поддомены
    DocumentRoot /var/www/app
</VirtualHost>
```

**Правила:**

*   Порядок `<VirtualHost>` в конфиге важен только для default (имя до точного не «перебивает» точное).
*   По умолчанию name-based объявлен для `*:80`/`*:443`; для двух IP-based-хостов на одном IP требуется `<NameVirtualHost>` (Apache 2.4+ автодетект).
*   `Listen` не влияет на выбор — только `ServerName`/`ServerAlias` внутри VirtualHost.
*   Проверка: `apachectl -S` (см. ниже) — показывает порядок и default для каждого порта.

### Файлы `.htaccess`

`.htaccess` — распределённые конфигурационные файлы, активные при `AllowOverride All` или частичном значении:

```apacheconf
<Directory "/var/www/html/uploads">
    AllowOverride All # включает чтение .htaccess
</Directory>
```

*   **Преимущества:** делегирование конфигурации без доступа к основным файлам (shared-хостинг, разработчики).
*   **Недостатки:** снижение производительности на 10–30 % (чтение файловой системы при каждом запросе).
*   **Рекомендация:** `AllowOverride None` везде, где возможно. Выносить конфигурацию в основной конфиг. Отключать `Options -Indexes` основным конфигом, а не через `.htaccess`.

Nginx не поддерживает аналог `.htaccess`. Подробнее — в [сравнение с Nginx](../Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md).

### Домашние каталоги пользователей и AccessFileName

**`UserDir`** (модуль `mod_userdir`) — виртуальные каталоги вида `/~user` на shared-хостинге:

```apacheconf
UserDir public_html          # каталог внутри HOME пользователя
UserDir disabled root        # запрет для системных пользователей
# UserDir enabled alice bob  # разрешить только перечисленным
```

```apacheconf
<VirtualHost *:80>
    ServerName host.example.com
    UserDir public_html
    <Directory "/home/*/public_html">
        Options +Indexes
        Require all granted
    </Directory>
</VirtualHost>
```

Доступ: `http://host.example.com/~alice/` → `/home/alice/public_html/`. Влияет на security: каталоги пользователей должны иметь корректные права (`chmod 711` на HOME, `755` на `public_html`), иначе `403`.

**`AccessFileName`** — имя файла распределённой конфигурации (по умолчанию `.htaccess`). Переопределяется глобально:

```apacheconf
AccessFileName .htaccess
# Совместимость с общими файлами:
<Files ~ "^\.ht">
    Require all denied
</Files>
```

### Директивы управления доступом

Apache 2.4 использует `Require` как основной механизм:

| Контекст | Пример | Эффект |
|---|---|---|
| IP-сеть | `Require ip 192.168.1.0/24` | Только из локальной сети |
| Конкретный IP | `Require ip 203.0.113.50` | Только один адрес |
| Аутентификация | `Require valid-user` | Любой из `.htpasswd` |
| Пользователь | `Require user admin` | Конкретный пользователь |
| Группа | `Require group admins` | Группа из `.htpasswd` |
| Все | `Require all granted` | Разрешить всем |
| Отказ | `Require all denied` | Запретить всем |

**Совместимость Apache 2.2 → 2.4:** старые `Order/Deny/Allow` заменены на `Require`. Не оставлять старые директивы в 2.4+.

---







## Практические сценарии

### Установка

**RHEL/Rocky Linux/AlmaLinux 9+:**

```bash
sudo dnf install httpd httpd-tools

# Для управления модулями (Debian-стиль)
sudo dnf install httpd-tools

# Автозагрузка
sudo systemctl enable --now httpd

# Открыть порты firewall-cmd
sudo firewall-cmd --permanent --add-service={http,https}
sudo firewall-cmd --reload
# → success
```

**Ubuntu 22.04+/Debian 12+:**

```bash
sudo apt update
sudo apt install apache2 apache2-utils

# Проверка установки
apache2 -v
# → Server version: Apache/2.4.63 (Debian)
```

### Управление службой

Используется `systemctl` (systemd):

```bash
sudo systemctl status httpd # → active (running)

# Старт, остановка, релоад
sudo systemctl restart httpd
sudo systemctl reload httpd  # без потерь соединений ( graceful reload )

# Отключение автозагрузки
sudo systemctl disable httpd

# Прослушиваемые порты
sudo ss -tlpn | grep httpd
# → LISTEN 0 128 *:80 *:*
```

**Утилиты управления (Debian/Ubuntu):**

```bash
sudo a2ensite example.conf   # включить виртуальный хост
sudo a2dissite example.conf  # отключить виртуальный хост
sudo a2enmod proxy_http     # включить модуль
sudo apache2ctl configtest  # синтаксическая проверка
```

**Graceful restart** (релоад без разрывов соединений):

```bash
sudo apachectl graceful
# или
sudo systemctl reload httpd
```

### Включение HTTP/2

Требует `mod_http2` и TLS (сейчас все браузеры требуют HTTPS для HTTP/2):

```apacheconf
# В основном конфиге или VirtualHost
LoadModule http2_module modules/mod_http2.so
Protocols h2 http/1.1

<VirtualHost *:443>
    ServerName secure.example.com
    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/example.crt
    SSLCertificateKeyFile /etc/pki/tls/private/example.key
    Protocols h2 http/1.1
</VirtualHost>
```

**Проверка:**

```bash
curl -I --http2 https://secure.example.com
# → HTTP/2 200
```

### Настройка SSL/TLS (HTTPS)

Требует модуля `mod_ssl`. Актуальные настройки TLS 2026:

```apacheconf
<VirtualHost *:443>
    ServerName secure.example.com
    DocumentRoot /var/www/secure

    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/fullchain.pem
    SSLCertificateKeyFile /etc/pki/tls/private/privkey.pem

    # TLS 1.3 + 1.2, устаревшие протоколы запрещены
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1

    # ECDHE + RSA для forward secrecy
    SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
    SSLHonorCipherOrder on

    # HSTS — принудительный HTTPS (2 года)
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
</VirtualHost>
```

**Для Debian/Ubuntu пути сертификатов:**

```apacheconf
SSLCertificateFile /etc/ssl/certs/example.crt
SSLCertificateKeyFile /etc/ssl/private/example.key
```

### Настройка обратного прокси (Reverse Proxy)

Apache проксирует входящие запросы к backend-приложениям (Node.js, Python/WSGI, PHP-FPM):

```apacheconf
<VirtualHost *:80>
    ServerName app.example.com

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3000/ retry=3
    ProxyPassReverse / http://127.0.0.1:3000/

    # Таймаут для long-running запросов (например, API)
    ProxyTimeout 120
</VirtualHost>
```

**SSL-терминация Apache с бэкендом HTTP:**

```apacheconf
<VirtualHost *:443>
    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/app.crt
    SSLCertificateKeyFile /etc/pki/tls/private/app.key

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3000/
    ProxyPassReverse / http://127.0.0.1:3000/

    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"
</VirtualHost>
```

**Логирование заголовков X-Forwarded (диагностика):**

```apacheconf
LogFormat "%h %{X-Forwarded-Proto}i %{X-Forwarded-For}i %r %>s" proxy_log
CustomLog "logs/proxy_access.log" proxy_log
```

**Определение реального IP клиента (mod_remoteip):**

Apache за reverse-прокси (Nginx/HAProxy/LB) видит IP прокси, а не клиента. `mod_remoteip` подменяет `REMOTE_ADDR` значением из доверенного заголовка — корректные логи, `Require ip`, `mod_evasive` и лимиты:

```apacheconf
LoadModule remoteip_module modules/mod_remoteip.so

# Считать реальный IP из X-Forwarded-For, доверяя только перечисленным прокси
RemoteIPHeader X-Forwarded-For
RemoteIPTrustedProxy 10.0.0.0/8 192.168.0.0/16 172.16.0.0/12
RemoteIPProxiesHeader X-Forwarded-For

# Формат лога меняется: %a теперь даёт реальный IP
LogFormat "%a %l %u %t \"%r\" %>s %b \"%{X-Forwarded-Proto}i\"" real_ip
CustomLog "logs/access_real.log" real_ip
```

**Важно:** без `RemoteIPTrustedProxy` Apache будет доверять заголовку от любого клиента (подделка IP). На RHEL также учитывать SELinux-булеан `httpd_can_network_connect` при обращении к исходному прокси. Nginx-аналог — в [Nginx: реальный IP](../../Networking/Protocols/HTTP/http_servers_proxies.md).

**Проксирование WebSocket (`mod_proxy_wstunnel`):**

```apacheconf
LoadModule proxy_wstunnel_module modules/mod_proxy_wstunnel.so

<VirtualHost *:80>
    ServerName ws.example.com

    ProxyPass /ws/ ws://10.0.0.11:8080/ws/
    ProxyPassReverse /ws/ ws://10.0.0.11:8080/ws/
    # Upgrade: websocket заголовок передаётся прозрачно
</VirtualHost>
```

Для нестандартных путей/после Rewrite (смешивание с mod_rewrite не рекомендуется):

```apacheconf
RewriteEngine On
RewriteCond %{HTTP:Upgrade} websocket [NC]
RewriteRule ^/stream(.*)$ ws://127.0.0.1:3000$1 [P,L]
```

**Проверка:**
```bash
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     http://localhost/ws/
# → HTTP/1.1 101 Switching Protocols
```

### Интеграция с PHP через PHP-FPM

PHP-FPM — рекомендуемый подход для производительности (постоянный пул процессов, изоляция):

```apacheconf
<VirtualHost *:80>
    ServerName php.example.com
    DocumentRoot /var/www/php

    <FilesMatch \.php$>
        SetHandler "proxy:fcgi://127.0.0.1:9000"
    </FilesMatch>

    <Directory "/var/www/php">
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
```

Для нескольких PHP-FPM пулов (разные версии PHP):

```apacheconf
<FilesMatch \.php$>
    # PHP 8.2 — основной
    SetHandler "proxy:fcgi://127.0.0.1:9000"
    # PHP 8.1 — legacy
    # SetHandler "proxy:fcgi://127.0.0.1:9001"
</FilesMatch>
```

### Базовая аутентификация (HTTP Auth)

`mod_auth_basic` + `mod_authn_file`:

```bash
# Создание файла паролей
sudo htpasswd -c /etc/httpd/.htpasswd admin
# → Adding password for admin
sudo htpasswd /etc/httpd/.htpasswd operator # дополнительный пользователь
```

```apacheconf
<Directory "/var/www/html/admin">
    AuthType Basic
    AuthName "Restricted Area"
    AuthUserFile /etc/httpd/.htpasswd
    Require valid-user
</Directory>
```

**Групповая авторизация:**

```bash
sudo htpasswd -b /etc/httpd/.htpasswd alice admin123
sudo htpasswd -b /etc/httpd/.htpasswd bob operator1

# Файл групп
echo "admins: alice" | sudo tee /etc/httpd/.htgroups
```

```apacheconf
AuthType Basic
AuthName "Admin Panel"
AuthUserFile /etc/httpd/.htpasswd
AuthGroupFile /etc/httpd/.htgroups
Require group admins
```

### Настройка Firewall

**RHEL/Rocky Linux (firewall-cmd):**

```bash
sudo firewall-cmd --permanent --add-service={http,https}
sudo firewall-cmd --permanent --add-port=8080/tcp # нестандартный порт
sudo firewall-cmd --reload

# Проверка
sudo firewall-cmd --list-all
```

**Debian/Ubuntu (ufw):**

```bash
sudo ufw allow http/tcp
sudo ufw allow https/tcp
sudo ufw allow 8080/tcp
sudo ufw enable
sudo ufw status
```

### SELinux и Apache (RHEL-семейство)

SELinux ограничивает процессы контекстами безопасности. Apache работает в домене `httpd_t`:

```bash
# Проверка контекста DocumentRoot
ls -Z /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 index.html

# Установка контекста для новых файлов
sudo chcon -R -t httpd_sys_content_t /var/www/html
# Постоянно (reboot-безопасно):
sudo restorecon -R /var/www/html

# Просмотр политик для httpd
sudo ausearch -m avc -ts recent | grep httpd
```

**Важные SELinux booleans для Apache:**

```bash
# Разрешить Apache подключаться к удалённым портам (проксирование, веб-сервисы)
sudo setsebool -P httpd_can_network_connect 1

# Разрешить подключение к базе данных (PostgreSQL, MySQL)
sudo setsebool -P httpd_can_network_connect_db 1

# Разрешить отправку почты (PHP mail)
sudo setsebool -P httpd_can_sendmail 1

# Проверка активных booleans
sudo getsebool -a | grep httpd
```

**Диагностика нарушения SELinux:**

```bash
# Просмотр последних отказов
sudo ausearch -m avc -ts recent | grep httpd

# Генерация политики из логов
sudo ausearch -m avc -ts recent | audit2allow -M my_httpd
sudo semodule -i my_httpd.pp
```

---







## Операции и команды

### Диагностика конфигурации

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
```

### Управление конфигурацией (Ansible)

Для управления Apache в инфраструктуре как код (IaC):

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
```

Для Debian/Ubuntu заменить `httpd` на `apache2`. Детали — в [Ansible: Перекрестная совместимость LEMP/LAMP](../../Ansible/CrossPlatform/lamp-example.md).

### Анализ логов

**Логи доступа — топ IP:**

```bash
awk '{print $1}' /var/log/httpd/access_log | sort | uniq -c | sort -rn | head -20
# →  1245 203.0.113.50
# →   892 198.51.100.10
```

**HTTP-статусы:**

```bash
awk '{print $9}' /var/log/httpd/access_log | sort | uniq -c | sort -rn
# → 12450 200
# →   345 404
# →    89 500
```

**User-Agent:**

```bash
awk -F'"' '{print $6}' /var/log/httpd/access_log | sort | uniq -c | sort -rn | head -10
```

**Логи ошибок — последние ошибки:**

```bash
sudo tail -100 /var/log/httpd/error_log | grep -i "error\|warn\|crit"
# → [Mon Sep 23 10:00:00.123456 2026] [php7:error] [pid 1234] ...
```

**Поиск по PID:**

```bash
sudo grep "pid 1234" /var/log/httpd/error_log
```

### Ротация логов (rotatelogs)

`rotatelogs` из пакета `httpd-tools` ротирует лог-файлы без перезапуска Apache (в отличие от logrotate не требует reload). Подключается как pipe-обработчик:

```apacheconf
# Ротация по времени: ежедневно, в локальном времени, с суффиксом даты
CustomLog "|/usr/bin/rotatelogs -l /var/log/httpd/access_%Y%m%d.log 86400" combined

# Ротация по размеру (10 МБ) и по времени одновременно
ErrorLog "|/usr/bin/rotatelogs -l /var/log/httpd/error_%Y-%m-%d.log 10M"
```

| Опция `rotatelogs` | Назначение |
|---|---|
| `-l` | Использовать локальное время (по умолчанию UTC) |
| `-f` | Форсировать создание файла сразу |
| `86400` / `10M` | Период в секундах или лимит размера |
| `-n count` | Хранить не более N файлов (перезапись) |

**Проверка:**
```bash
curl -s http://localhost/ -o /dev/null
ls -la /var/log/httpd/ | grep "$(date +%Y%m%d)"
# → -rw-r--r-- 1 apache apache 1234 Sep 24 10:00 access_20260924.log
```

### Настройка производительности

**Увеличение количества соединений (event MPM):**

```apacheconf
<IfModule mpm_event_module>
    StartServers           4
    ServerLimit           16
    MinSpareThreads        75
    MaxSpareThreads       150
    ThreadsPerChild        64
    MaxRequestWorkers    1024    # = ThreadsPerChild * ServerLimit
    MaxConnectionsPerChild 10000
</IfModule>
```

**Понимание `MaxConnectionsPerChild` (MaxRequestsPerChild в Prefork):**

*   `0` — бесконечный жизненный цикл (по умолчанию).
*   `> 0` — ограничение запросов на процесс. Рекомендуется `5000–10000` для предотвраления утечек памяти.

### Оптимизация буферов

```apacheconf
# Отправка данных буферами (меньше syscalls)
EnableSendfile On
EnableMMAP On

# Заголовки кэширования статики
<FilesMatch "\.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$">
    ExpiresActive On
    ExpiresDefault "access plus 1 month"
    Header set Cache-Control "public, immutable"
</FilesMatch>
```

### Мониторинг

**Prometheus экспортёр Apache:**

```bash
# Установка
sudo dnf install prometheus-apache-exporter
# или
sudo useradd --no-create-home prometheus
sudo wget https://github.com/bitly/prometheus_exporters/releases/download/... -O /usr/local/bin/apache_exporter

# Запуск
sudo systemctl enable --now prometheus-apache-exporter

# Пример метрик:
#   apache_accessed_total{method="GET"} 12345
#   apache_active_connections 5
#   apache_workers_idle 120
```

**ApacheBench (ab) — быстрый smoke-тест:**

```bash
ab -n 1000 -c 50 -g results.data http://localhost/

# Вывод:
# Requests per second:    5234.56 [#/sec] (mean)
# Time per request:       9.551 [ms] (mean)
```

Детали — в [Тестирование производительности веб-серверов](../webserver_benchmarking.md).

---







## Типичные ошибки и диагностика

### HTTP 500 (Internal Server Error)

**Диагностика:**

```bash
# Синтаксическая проверка
sudo apachectl configtest
# → AH00558: ... (предупреждение)
# → Syntax OK

# Точное время ошибки в логе
sudo tail -100 /var/log/httpd/error_log | grep -i "error\|crit\|segfault"

# PHP-ошибки (если используется mod_php или PHP-FPM)
sudo tail -50 /var/log/php-fpm/error.log
```

**Частые причины:**
*   Ошибки в `.htaccess` — проверить: `sudo apachectl configtest`
*   Права на файлы — DocumentRoot должен быть читаемым пользователем `apache`
*   SELinux — проверка: `sudo ausearch -m avc -ts recent | grep httpd`

### Ошибка `Address already in use` при старте Apache

```bash
# Кто слушает порт 80?
sudo ss -tlpn | grep ':80'
# → LISTEN 0 128 *:80 *:* users:(("nginx",pid=1234,fd=12))

# Файл уже занят другим процессом (nginx, haproxy)
# Вариант решения — сменить Listen порт
# Или остановить конфликтующий процесс
sudo systemctl stop nginx
sudo systemctl start httpd
```

### Отказ SELinux при чтении файлов DocumentRoot

```bash
# Симптом: Apache возвращает 403 Forbidden для конкретного файла

# Проверка контекста файла
ls -Z /var/www/html/private/index.html
# → unconfined_u:object_r:user_home_t:s0 ... (неправильный)

# Исправление
sudo restorecon -R /var/www/html
# или для новых файлов
sudo chcon -R -t httpd_sys_content_t /var/www/html
```

### Конфликт MPM модулей

```bash
# Симптом: AH00558 при старте — конфликт prefork/event/worker

# Проверка активного MPM
apachectl -V | grep MPM
# → Server MPM: event

# Убедиться, что в конфиге загружен только event
grep -r "LoadModule.*mpm_" /etc/httpd/conf.modules.d/
# → должен быть только mpm_event_module
```

### Конфигурация логирования нарушений (JSON для SIEM)

```apacheconf
# В httpd.conf или conf.d/
LogFormat "{ \"remote_ip\": \"%h\", \"request\": \"%r\", \"status\": \"%>s\", \"user_agent\": \"%{User-Agent}i\", \"timestamp\": \"%t\" }" json_log
CustomLog "logs/access_json.log" json_log

# Логирование нарушений ModSecurity (если установлен)
<IfModule security2_module>
    SecAuditEngine On
    SecAuditLog logs/modsec_audit.log
    SecAuditLogFormat JSON
</IfModule>
```

**Отправка логов в syslog:**

```bash
# Apache → syslog (файл конфигурации)
CustomLog "|/usr/bin/logger -p local4.info -t apache_access" combined
CustomLog "|/usr/bin/logger -p local4.err -t apache_error" error
```

**Настройка logrotate (RHEL/Debian — обычно поставляется в пакете):**

```bash
sudo cat /etc/logrotate.d/httpd
# Проверка logrotate
sudo logrotate -d /etc/logrotate.d/httpd
```

### Настройка limits (systemd override)

**Ограничение ресурсов Apache через systemd unit:**

```ini
# /etc/systemd/system/httpd.service.d/hardening.conf
[Service]
LimitNOFILE=65535
# Ограничить доступ к /home, /root
ProtectHome=true
# /usr, /boot, /etc только на чтение
ProtectSystem=full
# Изолированный /tmp
PrivateTmp=true
# Запрет на повышение привилегий
NoNewPrivileges=true
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart httpd
# Проверка лимитов
cat /proc/$(pgrep -o httpd)/limits | grep "open files"
# → Max open files            65535                65535              files
```

---







## Лучшие практики

### 1. Выбор MPM и обработка статики

Для новых проектов использовать `event` MPM. `prefork` — только для legacy `mod_php`. Nginx/Angie предпочтительнее для статики (C10k).

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
# OCSP stapling
SSLUseStapling on
SSLStaplingReturnResponderErrors off
SSLStaplingCache "shmcb:/var/run/ocsp(128000)"
```

### 4. Заголовки безопасности

```apacheconf
# XSS защита
Header always set X-XSS-Protection "1; mode=block"
# Кликджекинг
Header always set X-FrameOptions "SAMEORIGIN"
# Управление MIME-типами
Header always set X-Content-Type-Options "nosniff"
# Content Security Policy (CSP)
Header always set Content-Security-Policy "default-src 'self'; img-src 'self' https:; script-src 'self'"
# Referrer Policy
Header always set Referrer-Policy "strict-origin-when-cross-origin"
# Permissions Policy
Header always set Permissions-Policy "geolocation=(), microphone=()"
```

### 5. Таймауты и защита от Slowloris

```apacheconf
# Таймаут на Keep-Alive соединения
KeepAliveTimeout 5

# Защита от Slowloris (TCP handshake + headers)
RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500

# Лимит на размер запроса
LimitRequestBody 10485760  # 10 MB

# Лимит на строку запроса
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
rpm -Va httpd  # RHEL (проверка целостности)
dpkg -V apache2  # Debian
```

Проверка CVE: `https://httpd.apache.org/security/vulnerabilities_24.html`.

### 9. Права доступа к файлам

```bash
# DocumentRoot
sudo chown -R root:apache /var/www/html
sudo chmod -R 750 /var/www/html
sudo find /var/www/html -type d -exec chmod 750 {} \;
sudo find /var/www/html -type f -exec chmod 640 {} \;

# .htpasswd
sudo chown root:apache /etc/httpd/.htpasswd
sudo chmod 640 /etc/httpd/.htpasswd
```









### 10. Graceful shutdown и rolling deploy

`apachectl graceful` перечитывает конфигурацию без разрыва соединений. Для zero-downtime deploy используйте `GracefulShutdownTimeout` (Apache 2.4+):

```apacheconf
GracefulShutdownTimeout 30
```

В systemd установите `TimeoutStopSec=30`, чтобы SIGTERM давал воркерам время завершить активные запросы.

### 11. CORS

```apacheconf
<IfModule mod_headers.c>
    Header always set Access-Control-Allow-Origin "https://app.example.com"
    Header always set Access-Control-Allow-Methods "GET, POST, OPTIONS"
    Header always set Access-Control-Allow-Headers "Authorization, Content-Type"
    Header always set Access-Control-Allow-Credentials "true"

    RewriteEngine On
    RewriteCond %{REQUEST_METHOD} OPTIONS
    RewriteRule ^(.*)$ $1 [R=204,L]
</IfModule>
```

### 12. PROXY protocol

```apacheconf
RemoteIPHeader X-Forwarded-For
RemoteIPTrustedProxy 10.0.0.0/8
```

### 13. WebSocket и gRPC

```apacheconf
ProxyPass /ws ws://backend/ retry=0
ProxyPass /grpc grpc://backend/
```

### 14. Резервное копирование

Минимальные бэкапы:
*   `/etc/httpd/` или `/etc/apache2/`
*   `/etc/pki/tls/` (сертификаты)
*   `/etc/httpd/.htpasswd`

```bash
sudo tar czf /backup/apache-conf-$(date +%F).tar.gz /etc/httpd/ /etc/pki/tls/
```

### 15. Disaster Recovery

*   **RPO:** 15 минут (ротация логов раз в день).
*   **RTO:** 30 минут (восстановление конфигурации из Git и развертывание на резервном сервере).
*   **Failover:** Keepalived для плавающего VIP.

---
## Дополнительная информация

### Архитектура и MPM

| MPM | Модель | Активность |
|---|---|---|
| **`event`** | асинхронная (epoll/kqueue) | По умолчанию (RHEL 9+, Ubuntu 22.04+). Лучшая производительность при Keep-Alive. |
| **`prefork`** | 1 процесс = 1 соединение | Только для legacy `mod_php`. Простота отладки. |
| **`worker`** | процессы + потоки | Устаревает в пользу `event`. Используется для обратной совместимости. |

**Переключение MPM (RHEL):**

```bash
# Проверка активного модуля
grep -r "LoadModule.*mpm_event" /etc/httpd/conf.modules.d/

# Переключение на prefork
sudo mv /etc/httpd/conf.modules.d/00-mpm.conf{,.bak}
sudo cp /etc/httpd/conf.modules.d/00-mpm.conf.prefork /etc/httpd/conf.modules.d/00-mpm.conf
sudo systemctl restart httpd
```

**Какой MPM выбрать:** `event` — для всех новых проектов и когда используется PHP-FPM. `prefork` — только для legacy `mod_php`.

### Протокол HTTP/3 (QUIC)

На июль 2026 года поддержка HTTP/3 в Apache экспериментальна. Полноценное внедрение требует патчи или отдельные сборки. Для production чаще используются Nginx или Angie как фронтенд, а Apache как бэкенд.

### Сравнение с Nginx

Apache — лидер в гибкости (`.htaccess`, динамические модули). Nginx — лидер в статике и C10k (десятки тысяч одновременных соединений). Оптимальная связка: Nginx (SSL + статика + Keep-Alive) + Apache (PHP + динамика) + ModSecurity. Сравнение — в [сравнение с Nginx](../Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md).

### См. также

*   [Укрепление безопасности Apache](./apache_hardening.md) — руководство по защите сервера.
*   [Перенаправления и перезапись URL](./apache_rewrite_and_redirects.md) — mod_rewrite, Redirect, Alias, SetEnvIf.
*   [Балансировка нагрузки](./apache_load_balancing.md) — mod_proxy_balancer, sticky sessions, health checks.
*   [Аутентификация и авторизация](./apache_authentication.md) — LDAP/AD, Digest, клиентские сертификаты.
*   [Серверное кэширование](./apache_caching.md) — mod_cache, mod_cache_disk, mod_cache_socache.
*   [Настройка производительности](./apache_performance_tuning.md) — MPM, scoreboard, TLS-сессии, HTTP/2.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — ProxyPassMatch, ProxyErrorOverride, cookie-rewrite, gRPC.
*   [Прямое проксирование](./apache-forward-proxy.md) — ProxyRequests, CONNECT, open proxy.
*   [Порядок слияния конфигов](./apache-config-merge-order.md) — Directory/Files/Location и AllowOverride.
*   [Обработчики и MIME](./apache-handlers-and-mime.md) — AddType/AddHandler/SetHandler, CGI, SSI.
*   [Интеграция Tomcat (AJP)](./apache-tomcat-ajp.md) — mod_proxy_ajp, балансировка Tomcat.
*   [Интеграция Python (mod_wsgi)](./apache-python-wsgi.md) — daemon-режим, uWSGI, Passenger.
*   [SSO через OIDC (mod_auth_openidc)](./apache-oidc-sso.md) — интеграция с Keycloak/Okta.
*   [Apache в Docker](./apache-in-docker.md) — официальный образ, envsubst, healthcheck.
*   [Сборка из исходников](./apache-install-from-source.md) — configure, apxs, мульти-инстансы.
*   [Тестирование производительности веб-серверов](../webserver_benchmarking.md) — использование `ab` (Apache Benchmark).
*   [Мониторинг Apache](../../Prometheus/Exporters/other_exporters.md#apache_exporter) — использование экспортера для Prometheus.
*   [Диагностика веб-серверов](../Concepts/webserver_troubleshooting.md) — общий подход к troubleshooting.
