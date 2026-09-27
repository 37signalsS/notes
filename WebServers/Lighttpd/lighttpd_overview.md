# Lighttpd

## Определения

**Lighttpd** — легковесный веб-сервер с открытым исходным кодом, ориентированный на высокую производительность и низкое потребление памяти. Стандартный выбор для маленьких VPS, встроенных систем и сценариев, где RAM ограничена.

**FastCGI** — протокол для взаимодействия веб-сервера с внешними процессами (PHP-FPM, Python WSGI).

**Event-driven архитектура** — модель обработки запросов, при которой один процесс обслуживает множество соединений асинхронно.

**mod_compress** — модуль сжатия ответов (gzip, deflate, brotli).

**mod_rewrite** — модуль перезаписи URL (аналог `mod_rewrite` в Apache).

**mod_access** — модуль контроля доступа по IP.

**mod_auth** — модуль аутентификации (Basic, Digest).

**mod_ssl** — модуль TLS/SSL (требует OpenSSL).

---

## Основные концепции

### Архитектура

Lighttpd использует событийную архитектуру (epoll/kqueue), аналогичную Nginx и Angie. Один процесс обслуживает тысячи соединений асинхронно.

**Ключевые особенности:**
- **Низкое потребление памяти:** ~2 MB на 10 000 соединений.
- **Высокая производительность:** статика, FastCGI, проксирование.
- **Модульная система:** динамическая загрузка модулей.
- **Гибкая конфигурация:** централизованная конфигурация без `.htaccess`.

### Сравнение с Nginx и Apache

| Характеристика | Lighttpd | Nginx | Apache |
| :--- | :--- | :--- | :--- |
| **Потребление памяти** | Очень низкое (~2 MB на 10 000 соединений). | Низкое (~2-10 MB на 10 000 соединений). | Высокое (~100-300 MB на 10 000 соединений). |
| **Производительность статики** | Высокая. | Лучшая в индустрии (sendfile, Zero-Copy). | Средняя. |
| **Модули** | Динамическая загрузка. | Статическая компиляция. | Динамическая загрузка. |
| **Конфигурация** | Централизованная. | Централизованная. | Централизованная + `.htaccess`. |
| **Масштабируемость** | Деградирует при высокой нагрузке. | Линейная при добавлении ядер CPU. | Деградирует при росте соединений. |
| **Экосистема** | Маленькая. | Большая. | Самая большая. |
| **Service Discovery** | Нет нативно. | Нет нативно. | Нет нативно. |
| **TLS-терминация** | Да (mod_ssl). | Да. | Да. |
| **HTTP/2** | Да. | Да. | Да. |
| **HTTP/3 (QUIC)** | Нет. | Да (1.27+). | Экспериментально. |
| **L4-проксирование** | Да. | Да (ngx_stream_proxy_module). | Да (mod_proxy). |

### Сценарии использования Lighttpd

| Сценарий | Обоснование |
| :--- | :--- |
| **Маленький VPS (256 MB RAM)** | Низкое потребление памяти. |
| **Встроенные системы** | Маленький footprint, быстрый старт. |
| **Статика + FastCGI** | Высокая производительность при низком RAM. |
| **Legacy-приложения** | Совместимость с FastCGI, модульная система. |

### Когда выбирать Nginx вместо Lighttpd?

- **Высокая нагрузка:** Nginx лучше масштабируется.
- **Большая экосистема:** Nginx имеет больше модулей и документации.
- **L4-проксирование:** Nginx имеет встроенный модуль `ngx_stream_proxy_module`.
- **L7-балансировка:** Nginx имеет встроенный модуль `ngx_http_upstream_module`.

---

## Практические сценарии

### Сценарий 1: Базовая конфигурация

```lighttpd
server.modules = [
    "mod_access",
    "mod_auth",
    "mod_compress",
    "mod_redirect",
    "mod_rewrite",
    "mod_fastcgi",
    "mod_proxy",
    "mod_ssl"
]

server.document-root = "/var/www/html"
server.upload-dirs = [ "/var/cache/lighttpd/uploads" ]
server.errorlog = "/var/log/lighttpd/error.log"
server.pid-file = "/var/run/lighttpd.pid"
server.username = "www-data"
server.groupname = "www-data"

# Лимиты
server.max-connections = 4096
server.max-fds = 4096
server.network-backend = "writev"

# TLS
ssl.engine = "enable"
ssl.pemfile = "/etc/letsencrypt/live/example.com/fullchain.pem"
ssl.ca-file = "/etc/letsencrypt/live/example.com/chain.pem"
ssl.privkey = "/etc/letsencrypt/live/example.com/privkey.pem"
ssl.honor-cipher-order = "enable"
ssl.cipher-list = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256"
ssl.use-sslv2 = "disable"
ssl.use-sslv3 = "disable"
ssl.use-tlsv1 = "disable"
ssl.use-tlsv1.1 = "disable"

# Сжатие
compress.cache-dir = "/var/cache/lighttpd/compress/"
compress.filetype = ["text/plain", "text/html", "text/css", "application/javascript", "application/json"]
compress.allowed-encodings = ["gzip", "brotli"]

# Кэширование
$HTTP["url"] =~ "\.(css|js|png|jpg|jpeg|gif|ico|svg|woff|woff2)$" {
    expire.url = "+1 month"
    header.add "Cache-Control" "public, immutable"
}

# Логирование
accesslog.filename = "/var/log/lighttpd/access.log"
accesslog.format = "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\""
```

**Ключевые моменты:**
- `server.modules` — загружаемые модули.
- `server.document-root` — корневая директория.
- `ssl.engine` — включение TLS.
- `compress.filetype` — типы файлов для сжатия.
- `expire.url` — кэширование статики.
- `accesslog.format` — формат access log.

### Сценарий 2: FastCGI (PHP-FPM)

```lighttpd
server.modules = [
    "mod_fastcgi"
]

fastcgi.server = (
    ".php" => (
        "localhost" => (
            "socket" => "/run/php/php8.4-fpm.sock",
            "broken-scriptfilename" => "enable"
        )
    )
)

# Или TCP-соединение
fastcgi.server = (
    ".php" => (
        "localhost" => (
            "host" => "127.0.0.1",
            "port" => 9000,
            "broken-scriptfilename" => "enable"
        )
    )
)
```

**Ключеевымоменты:**
- `fastcgi.server` — конфигурация FastCGI.
- `socket` — UNIX-сокет PHP-FPM.
- `broken-scriptfilename` — обработка `SCRIPT_FILENAME` для совместимости.

### Сценарий 3: Обратный прокси

```lighttpd
server.modules = [
    "mod_proxy"
]

$HTTP["url"] =~ "^/api/" {
    proxy.server = (
        "" => (
            "api-backend" => (
                "host" => "127.0.0.1",
                "port" => 8080
            )
        )
    )
}
```

**Ключевые моменты:**
- `proxy.server` — конфигурация обратного прокси.
- `host` и `port` — бэкенд.

### Сценарий 4: Перезапись URL

```lighttpd
server.modules = [
    "mod_rewrite"
]

url.rewrite-once = (
    "^/old-path/(.*)$" => "/new-path/$1",
    "^/api/v1/(.*)$" => "/api/v2/$1"
)
```

**Ключевые моменты:**
- `url.rewrite-once` — однократная перезапись URL.
- `^/old-path/(.*)$` — регулярное выражение.
- `/new-path/$1` — замена.

### Сценарий 5: Контроль доступа

```lighttpd
server.modules = [
    "mod_access"
]

# Блокировка IP
$HTTP["remoteip"] == "192.0.2.0/24" {
    url.access-deny = ( "" )
}

# Разрешение IP
$HTTP["remoteip"] != "10.0.0.0/8" {
    url.access-deny = ( "" )
}

# Аутентификация
auth.backend = "htpasswd"
auth.backend.htpasswd.userfile = "/etc/lighttpd/htpasswd"
auth.require = (
    "/protected" => (
        "method" => "basic",
        "realm" => "Protected",
        "require" => "valid-user"
    )
)
```

**Ключевые моменты:**
- `$HTTP["remoteip"]` — фильтрация по IP.
- `url.access-deny` — denial доступа.
- `auth.require` — требование аутентификации.

### Сценарий 6: Мониторинг статуса

```lighttpd
server.modules = [
    "mod_status"
]

status.status-url = "/server-status"
status.config-url = "/server-config"
```

**Ключевые моменты:**
- `status.status-url` — страница статуса.
- `status.config-url` — страница конфигурации.
- Доступ к `/server-status` должен быть ограничен внутренней сетью.

### Сценарий 7: Graceful reload

```bash
# Перезагрузка конфигурации без разрыва соединений
lighttpd -t -f /etc/lighttpd/lighttpd.conf
systemctl reload lighttpd
```

**Ключевые моменты:**
- `lighttpd -t` — проверка конфигурации.
- `systemctl reload lighttpd` — graceful reload.

### Сценарий 8: Резервное копирование

```bash
# Минимальные бэкапы
sudo tar czf /backup/lighttpd-conf-$(date +%F).tar.gz /etc/lighttpd/ /etc/letsencrypt/
```

**Ключевые моменты:**
- `/etc/lighttpd/` — конфигурация.
- `/etc/letsencrypt/` — TLS-сертификаты.

### Сценарий 9: Disaster Recovery

*   **RPO:** 15 минут (ротация логов раз в день).
*   **RTO:** 30 минут (восстановление конфигурации из Git и развертывание на резервном сервере).
*   **Failover:** Keepalived для плавающего VIP.

---

## Дополнительная информация

### Чек-лист настройки Lighttpd

- [ ] **Модули:** загружены необходимые модули.
- [ ] **TLS:** включен, современные шифры, TLS 1.2+.
- [ ] **Сжатие:** включено для текстовых типов.
- [ ] **Кэширование:** включено для статики.
- [ ] **FastCGI:** настроено для PHP-FPM.
- [ ] **Обратный прокси:** настроен для API.
- [ ] **Контроль доступа:** настроен для защищенных ресурсов.
- [ ] **Логирование:** access log и error log.
- [ ] **Мониторинг:** статусная страница, алерты.
- [ ] **Graceful reload:** настроен, проверка конфигурации перед применением.

### См. также

- **[Сравнение веб-серверов](../Concepts/webserver_comparison.md) — Nginx, Apache, HAProxy, Traefik.
- **[Lighttpd Documentation](https://lighttpd.net/documentation.html) — официальная документация.
- **[Lighttpd Modules](https://lighttpd.net/modules.html) — список модулей.
- **[Lighttpd Configuration](https://redmine.lighttpd.net/projects/lighttpd/repository/14/entry/doc/config/lighttpd.conf) — пример конфигурации.
