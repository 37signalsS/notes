# Миграция с Apache на Nginx

---

## Определения

**Миграция веб-сервера** — плановый перенос обслуживания веб-трафика с Apache HTTP Server на Nginx: конфигурация, модули, правила перезаписи, аутентификация и логи переписываются под модель Nginx с сохранением внешнего поведения сервиса.

**Директива-аналог** — директива Nginx, выполняющая функцию Apache-директивы (например `Require ip` → `allow`/`deny`, `ProxyPass` → `proxy_pass`, `CustomLog` → `access_log`). Маппинг не всегда 1:1 из-за разницы моделей.

**`.htaccess`** — распределённый конфигурационный файл Apache; в Nginx отсутствует. Все правила должны быть перенесены в централизованный конфиг, а сами файлы удалены из каталогов контента.

**`location`** — основной блок сопоставления в Nginx. В отличие от Apache `<Directory>` (сопоставление с файловой системой), `location` сопоставляется с URI запроса. Разница критична при переносе конфигурации.

**PHP-FPM / uwsgi / proxy_pass** — способы обслуживания динамики в Nginx: бэкенд-процессы (PHP-FPM, uWSGI, gunicorn) или проксирование на приложение. Apache-style разделение статика/динамика сохраняется, но «движок» выносится из сервера.

**Side-by-side (dual-run) миграция** — стратегия, при которой Nginx разворачивается параллельно Apache (на другом порту/хосте), трафик переключается постепенно, а откат выполняется переключением обратно.

---

## Основные концепции

### Зачем мигрируют

Nginx превосходит Apache в плотности соединений (событийный цикл epoll/kqueue), отдаче статики (`sendfile`, zero-copy) и предсказуемости конфигурации (считывается один раз при старте, без проверки `.htaccess` на каждый запрос). Архитектурное сравнение моделей — в [сравнение Nginx против Apache](../Proxy/Load_Balancing/additional_info_and_comparisons.md), здесь — только практика переноса.

Миграция оправдана, когда:
- рост конкурентных соединений упирается в модель «процесс/поток на запрос»;
- `.htaccess`-фермы создают накладные расходы на проверки ФС;
- нужна унифицированная edge-схема (TLS, кэш, балансировка) с единым централизованным конфигом;
- legacy `mod_php`/`prefork` заменяется на PHP-FPM.

### Различия, влияющие на перенос

| Аспект | Apache | Nginx |
|---|---|---|
| Сопоставление директорий | `<Directory>` — путь в ФС, `<Location>` — URI | `location` — только URI |
| Конфигурация | Динамическая, `.htaccess` на каждый запрос | Компилируется при старте, один файл |
| Модули | Загружаются динамически (`LoadModule`) | Собираются в бинарь; OSS не допускает загрузку на лету |
| Динамика приложений | `mod_php`, `mod_wsgi`, AJP-коннекторы | Внешние процессы: PHP-FPM, uWSGI, `proxy_pass` |
| Виртуальные хосты | `<VirtualHost>` (default = первый совпавший) | `server` блок (выбор по `listen` + `server_name`) |
| Merge order | Секции `<Directory>/<Location>/<Files>/<If>` сливаются по фиксированному порядку | Иерархия `http → server → location`; внутри `location` нет наследования-слияния |
| Выбор блока | По merge-правилам | `=` > `^~` > regex (`~`,`~*`) в порядке появления > самый длинный префикс |

**Практический вывод:** правилу Apache `<Directory "/var/www/html">` в Nginx чаще всего соответствует `location / { root /var/www/html; }`, но проверять надо по URI, а не по пути. Преобразование `RewriteRule` из `.htaccess` — отдельная задача (см. ниже).

### Стратегии миграции

1. **Big-bang с откатом:** останавливаем Apache, запускаем Nginx на тех же портах, проверяем, при проблеме возвращаемся. Быстро, но рискованно.
2. **Side-by-side (рекомендуемая):** Nginx поднимается параллельно (`listen 8080` или отдельный IP/vhost), нагрузки постепенно переключаются (DNS / балансировщик), каждый шаг валидируется, откат — переключение обратно.
3. **Поэтапная:** сначала статика/кэш/TLS на Nginx, динамика пока на Apache через `proxy_pass`; затем перенос динамики по приложениям.

### Предмиграционный аудит

До переноса собрать полную картину эксплуатируемого Apache:

- все `<VirtualHost>` и их `ServerName`/`ServerAlias`, порты;
- список активных модулей (`apache2ctl -M`, `httpd -M`);
- все `.htaccess`-файлы и правила в них;
- `mod_rewrite`, `Redirect`, `Alias`;
- конфигурации TLS (`SSLCertificateFile`, `SSLProtocol`, OCSP);
- аутентификацию (htpasswd-файлы, LDAP), заголовки, редиректы.
- backend-приложения, к которым обращается Apache (PHP, Python, Tomcat, статика).

---

## Практические сценарии

### Сценарий 1: Инвентаризация и план переноса

```bash
# модули и vhosts
apache2ctl -M | sort
apache2ctl -S

# все .htaccess в DocumentRoot
find /var/www -name '.htaccess' -print

# редиректы/rewrite (сразу оценки масштаба)
grep -rE "RewriteRule|Redirect|RewriteCond" /etc/httpd/ /etc/apache2/ 2>/dev/null

# бэкенды, которые обслуживает Apache (proxy)
grep -rE "ProxyPass|BalancerMember" /etc/httpd/ /etc/apache2/ 2>/dev/null

# TLS-параметры
grep -rE "SSLCertificate|SSLProtocol|SSLCipherSuite|SSLUseStapling" /etc/httpd/ /etc/apache2/ 2>/dev/null
```

Результат — список участков конфигурации с приоритетами (статика/TLS → rewrite → auth → динамика).

### Сценарий 2: Базовый server-блок (маппинг директив)

Apache:

```apacheconf
<VirtualHost *:80>
    ServerName site.example.com
    ServerAlias www.site.example.com
    DocumentRoot /var/www/site
    DirectoryIndex index.html index.php
    ErrorLog logs/site_error.log
    CustomLog logs/site_access.log combined
    Options -Indexes
    <Directory "/var/www/site">
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

Nginx:

```nginx
server {
    listen 80;
    server_name site.example.com www.site.example.com;

    root /var/www/site;
    index index.html index.php;

    error_log /var/log/nginx/site_error.log;
    access_log /var/log/nginx/site_access.log main;

    autoindex off;                 # аналог Options -Indexes

    location / {
        try_files $uri $uri/ =404; # fallback: 404 вместо листинга каталога
    }
}
```

Таблица базового маппинга:

| Apache | Nginx | Примечание |
|---|---|---|
| `Listen 80` / `Listen 443` | `listen 80;` / `listen 443 ssl;` | `ssl` — только при TLS |
| `ServerName` / `ServerAlias` | `server_name` | wildcard: `*.example.com` |
| `DocumentRoot` | `root` | путь напрямую без `<Directory>` |
| `DirectoryIndex` | `index` | |
| `ErrorLog` / `CustomLog` | `error_log` / `access_log` | форматы — через `log_format` и переменные |
| `<Directory>` | `location /` | сопоставление по URI, а не ФС |
| `<DirectoryMatch>` | `location ~` / `location ~*` | regex-локации |
| `<Files~ "\.php$">` | `location ~ \.php$` | |
| `Options -Indexes` | `autoindex off;` | и так по умолчанию |
| `Options +FollowSymLinks` | по умолчанию разрешены | при запрете — `disable_symlinks on;` |
| `AllowOverride All` | — (нет `.htaccess`) | правила переносятся в конфиг |
| `ServerTokens Prod` | `server_tokens off;` | |
| `AddDefaultCharset utf-8` | `charset utf-8;` | |
| `LimitRequestBody` | `client_max_body_size` | аналог лимита тела запроса |
| `Timeout` | `proxy_*_timeout`, `send_timeout` | таймауты на уровне блоков |
| `KeepAliveTimeout` | `keepalive_timeout` | |
| `mod_log_config`: `%r %s %b` | `$request $status $body_bytes_sent` | переменные вместо форматов |

`main` — формат по умолчанию; при желании перенести формат combined дословно:

```nginx
http {
    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent"';
}
```

### Сценарий 3: Перенос `.htaccess` и mod_rewrite

`.htaccess` не существует в Nginx — каждое правило переносится в центр конфигурации. Типовые преобразования:

| `.htaccess` / директива | Nginx |
|---|---|
| `Options -Indexes` | `autoindex off;` (по умолчанию) |
| `deny from all` | `deny all;` |
| `allow from 10.0.0.0/8` | `allow 10.0.0.0/8;` |
| `AuthType Basic` + `AuthUserFile` | `auth_basic` + `auth_basic_user_file` |
| `AddType text/html .shtml` | `types { text/html shtml; }` или `include mime.types;` |
| `ExpiresByType text/css "access plus 30 days"` | `expires 30d;` (в `location` под файлы) |
| `ErrorDocument 404 /404.html` | `error_page 404 /404.html;` |
| `Header set X-Frame-Options SAMEORIGIN` | `add_header X-Frame-Options SAMEORIGIN always;` |
| `php_value` / `php_flag` | параметры PHP-FPM (`fastcgi_param`) |

**mod_rewrite → Nginx `rewrite`/`return`:**

```apacheconf
# Apache: .htaccess
RewriteEngine On
RewriteRule ^/old/(.*)$ /new/$1 [R=301,L]
```

```nginx
# Nginx: внутри server (regex-rewrite на уровне сервера)
rewrite ^/old/(.*)$ /new/$1 permanent;    # R=301
#                       ^^^^^^^^^^^ — [L]=last подразумевается для redirect
```

**RewriteCond (хост) → `if` на уровне server (допустимый сценарий):**

```apacheconf
RewriteCond %{HTTP_HOST} ^www\.(.*)$ [NC]
RewriteRule ^(.*)$ http://%1$1 [R=301,L]
```

```nginx
if ($host ~ ^www\.(.*)$) {
    return 301 http://$1$request_uri;
}
```

`$request_uri` сохраняет исходный URI с query-строкой — это эквивалент `[QSA]`.

**Простой Redirect (без регулярных выражений):**

```apacheconf
Redirect 301 /about /o-kompanii
```

```nginx
location = /about {
    return 301 /o-kompanii;
}
```

**Важно:** не использовать `if` внутри `location` для перезаписи маршрутизации (непредсказуемое поведение). Тяжёлые rewrite-правила из приложений (CMS: WordPress, Joomla, Drupal) переносятся в типовой паттерн `try_files $uri $uri/ /index.php?$args;`.

### Сценарий 4: Аутентификация и авторизация

**Basic Auth (htpasswd-файл совместим с Apache без перегенерации):**

```apacheconf
# Apache
AuthType Basic
AuthName "Restricted"
AuthUserFile /etc/httpd/.htpasswd
Require valid-user
```

```nginx
location /private/ {
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

**Доступ по IP (`Require ip`):**

```apacheconf
Require ip 10.0.0.0/8
Require ip 127.0.0.1
```

```nginx
location /admin/ {
    allow 10.0.0.0/8;
    allow 127.0.0.1;
    deny all;              # все остальные — 403
}
```

**LDAP-аутентификация:** Nginx OSS не имеет встроенного LDAP-модуля (только Plus `ngx_http_auth_ldap_module` в коммерческой версии). Варианты: `ngx_http_auth_ldap_module` (сборка стороннего модуля) или вынос аутентификации на слой SSO (см. OIDC-интеграцию). В модуль `mod_auth_openidc` аналог — `ngx_http_auth_jwt_module`/`auth_request`.

### Сценарий 5: Перенос динамики (PHP, Python, Tomcat)

**PHP (`mod_php`/prefork → PHP-FPM):**

```apacheconf
# Apache (legacy mod_php или PHP-FPM через SetHandler)
<FilesMatch \.php$>
    SetHandler "proxy:fcgi://127.0.0.1:9000"
</FilesMatch>
```

```nginx
location ~ \.php$ {
    include fastcgi_params;                        # Debian: /etc/nginx/fastcgi_params
    fastcgi_pass 127.0.0.1:9000;                   # или unix:/run/php/php-fpm.sock
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}
```

**Python (mod_wsgi → uWSGI/gunicorn):**

```nginx
location / {
    include uwsgi_params;                          # Debian: /etc/nginx/uwsgi_params
    uwsgi_pass unix:/tmp/uwsgi.sock;               # uWSGI
}
# или HTTP-прокси на gunicorn/uvicorn
location /api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
}
```

**Tomcat/JSP (mod_proxy_ajp → HTTP-прокси):**

Nginx не говорит по AJP; включаем HTTP-коннектор Tomcat (порт 8080) и проксируем:

```nginx
location /app/ {
    proxy_pass http://tomcat:8080/app/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

### Сценарий 6: Обратное проксирование и балансировка

Apache:

```apacheconf
ProxyPass /api/ http://backend:8080/api/
ProxyPassReverse /api/ http://backend:8080/api/
```

Nginx:

```nginx
location /api/ {
    proxy_pass http://backend:8080/api/;   # с URI — замена части path
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_redirect default;                # аналог ProxyPassReverse
}
```

Балансировка (`mod_proxy_balancer` → `upstream`):

```apacheconf
# Apache
<Proxy balancer://webcluster>
    BalancerMember http://10.0.0.11:8080 route=node1
    BalancerMember http://10.0.0.12:8080 route=node2
    ProxySet stickysession=JSESSIONID
</Proxy>
ProxyPass / balancer://webcluster/
```

```nginx
upstream webcluster {
    server 10.0.0.11:8080;                 # route=node1 → weight/backup
    server 10.0.0.12:8080;
    keepalive 32;                          # пул соединений к бэкендам
}

server {
    location / {
        proxy_pass http://webcluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";    # для keepalive между Nginx и backend
        # Sticky (OSS): ip_hash / hash $cookie_jsessionid; Plus: sticky cookie ...;
    }
}
```

**Sticky:** в OSS недоступна нативная STICKY-седация через cookie; применения: `ip_hash`, `hash $cookie_jsessionid consistent` или `hash $request_uri`. Для полноценных sticky-кук — Nginx Plus или Angie (drop-in замена Nginx).

### Сценарий 7: TLS и редирект HTTP → HTTPS

Apache:

```apacheconf
SSLEngine on
SSLCertificateFile /etc/pki/tls/certs/site.crt
SSLCertificateKeyFile /etc/pki/tls/private/site.key
SSLProtocol all -TLSv1 -TLSv1.1
```

Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name site.example.com;

    ssl_certificate     /etc/pki/tls/certs/site.crt;
    ssl_certificate_key /etc/pki/tls/private/site.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
}

server {
    listen 80;
    server_name site.example.com;
    return 301 https://$host$request_uri;   # аналог Redirect https
}
```

### Сценарий 8: Статика, кэш и заголовки

```nginx
location /static/ {
    alias /var/www/site/static/;
    expires 30d;                              # аналог ExpiresByType
    add_header Cache-Control "public";        # add_header ... always (для 4xx/5xx)
    access_log off;
}

location ~ /\. {                              # скрыть dotfiles и .htaccess
    deny all;
}
```

`add_header` в Nginx не наследуется в `location`, где определён свой `add_header`; безопасные заголовки размещают на уровне `http`/`server` либо повторяют в каждой локации.

### Сценарий 9: Параллельный запуск и откат

```bash
# 1. Nginx на временном порту (Apache продолжает работать)
sudo nginx -c /etc/nginx/nginx.conf
sudo ss -tlnp | grep 8080                     # Nginx слушает 8080

# 2. Проверка конфигурации перед переключением
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 3. Переключение: освободить 80/443, поднять Nginx там
sudo systemctl stop httpd
sudo nginx -s reload                          # перечитать конфиг с listen 80/443

# 4. Валидация доступности
curl -sI http://site.example.com/  | head -1
# → HTTP/1.1 200 OK

# 5. Откат (в любой момент)
sudo nginx -s quit && sudo systemctl start httpd
```

Для edge-миграции без простоя — переключение через DNS (TTL) или внешний балансировщик: Nginx остаётся на внутренних портах, трафик льётся через LB.

---

## Операции и команды

| Операция | Команда | Назначение |
|---|---|---|
| Проверка конфигурации | `nginx -t` | `test is successful` — синтаксис корректен |
| Полный дамп конфига | `nginx -T` | выгрузка всех `include` для аудита |
| Graceful reload | `sudo nginx -s reload` | перечитывание конфига без разрыва соединений |
| Остановка | `sudo nginx -s quit` | плавное завершение (сохраняет соединения) |
| Инвентаризация модулей | `nginx -V 2>&1` | список `--with-...` (статические) |
| Сравнение vhost-ов | `diff <(httpd -S) <(nginx -T)` | контроль полноты переноса |
| Порты | `sudo ss -tlnp \| grep -E ':(80\|443)'` | кто слушает после переключения |
| Логи 5xx в переходный период | `sudo tail /var/log/nginx/access.log` | `$status` — выявление регрессий |

**Проверка переноса rewrite без влияния на пользователей:**

```bash
# локальный деплой на временном порту, сравнение статусов
for u in /about /contact /api/v1/users; do
  a=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080$u)
  echo "$u $a"
done
```

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| `404` при живом PHP | `location ~ \.php$` не проходит: root/alias не совпал, SCRIPT_FILENAME неверен | Проверить `$document_root` (`nginx -T`), `fastcgi_param SCRIPT_FILENAME` |
| `404` после переноса CRM/CMS | .htaccess-rewrite утерян | Добавить `try_files $uri $uri/ /index.php?$args;` |
| PHP скачивается файлом | Нет `fastcgi_pass` / `location ~ \.php$` | Включить блок PHP-FPM |
| `403 Forbidden` для каталога | Неверный путь `root`/`alias` при запрете | Согласовать `location` с фактическим каталогом |
| `.htaccess` выкачивается как файл | Nginx (в отличие от Apache) не скрывает dotfile | `location ~ /\. { deny all; }` и удалить `.htaccess` |
| Редирect гоняет (loop) | rewrite c `return` в `location`, конфликт с `try_files` | Переписать в `return` на уровне server; `rewrite` + `last` |
| www→root не работает | `if ($host ...)` отсутствует на уровне server | Добавить `return 301` в блок server |
| Sticky не работает (сессия теряется) | несовпадение `hash`; кука JSESSIONID не в том алгоритме | `hash $cookie_jsessionid consistent`; для куки-route — Plus/Angie |
| Тайм-ауты к бэкенду | `proxy_read_timeout` по умолчанию 60 c | Увеличить для долгих запросов/SSE |
| 502 Bad Gateway | бэкенд (FPM/socket) не стартовал | `systemctl status php-fpm`; проверить `fastcgi_pass` и права сокета |
| Нет доступа к статике после Auth Apache | `auth_basic` локации конфликтует | Вынести статику за пределы защищённой локации |
| SELinux-блокировка (RHEL) | контексты/булеаны после переноса | `restorecon -Rv /var/www`; `setsebool -P httpd_can_network_connect 1` (прокси к backend) |
| Порты 80/443 заняты Apache | оба сервиса пытаются слушать | Остановить httpd до переключения; side-by-side на 8080 |

---

## Лучшие практики

1. **Side-by-side вместо big-bang:** Nginx поднимайте параллельно, переключайте трафик по шагам, держите откат в один шаг.
2. **Полная инвентаризация до старта:** `.htaccess`-фермы и rewrite-правила — главный источник потерь; выявить до перехода.
3. **Удалить `.htaccess`:** после переноса файлы удаляются из DocumentRoot (иначе — риск выкачивания как контента).
4. **SEO-преемственность:** все старые URL должны отдавать 301 на новые (`return`/`rewrite permanent`), иначе потеря позиций.
5. **Динамика через бэкенд-процессы:** PHP-FPM/uWSGI/gunicorn, а не модули в сервере; вынести security-заголовки на `server`-уровень с `add_header ... always`.
6. **Валидация на реальном трафике:** сравнивать коды ответов и статus до/после (см. проверку `for u in ...`), мониторить 5xx первый момент после переключения.
7. **Модули check-in advance:** если нужны LDAP-Auth или sticky-cookie — проверить наличие сторонних модулей/Plus заранее (в OSS придётся собирать или использовать обходные методы).
8. **Формат логов:** форсировать совместимые поля лога во время переходного периода для анализа в старой BI-системе.

---

## Дополнительная информация

### См. также

*   [Сравнение Nginx и Apache (архитектура)](../Proxy/Load_Balancing/additional_info_and_comparisons.md) — различия моделей, когда что выбирать.
*   [Миграция с Nginx на Angie](../../Angie/migration_from_nginx.md) — если конечной целью является Angie (drop-in замена Nginx).
*   [Руководство по безопасности Nginx](../Security/nginx_security_guide.md) — ограничение доступа, dotfiles, SELinux-настройка.