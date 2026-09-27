# Apache в Docker (официальный образ httpd)

---

## Определения

**Официальный образ `httpd`** — поддерживаемый образ Apache HTTP Server (Docker Hub). Минимальная основа (Debian/Alpine), конфигурация в `/usr/local/apache2/conf/httpd.conf`, модули — в `LoadModule`-блоках.

**apachectl** — утилита управления внутри контейнера; запуск сервера в foreground (`httpd -DFOREGROUND`), что важно для контейнера без `init`.

**Entrypoint / ENV-шаблонизация** — способ параметризации конфигурации: подстановка переменных окружения (`envsubst`) или перегенерация конфигов на старте контейнера.

**Healthcheck** — встроенная проверка живости контейнера (через `mod_status`), влияющая на orchestration-решения (restart, LB, readiness).

---

## Основные концепции

### Структура официального образа

| Путь | Назначение |
|---|---|
| `/usr/local/apache2/conf/httpd.conf` | Основной конфиг |
| `/usr/local/apache2/conf/extra/` | Подключённые конфиги |
| `/usr/local/apache2/htdocs/` | DocumentRoot по умолчанию |
| `/usr/local/apache2/logs/` | Логи (в т.ч. `error_log`, `access_log`) |
| `CMD ["httpd-foreground"]` | Запуск `apachectl -DFOREGROUND` |

Загрузка модулей в образе — через `LoadModule` (все модули статические `.so` в `/usr/local/apache2/modules/`).

### Почему foreground

Контейнер должен держать процесс в foreground (PID 1), иначе Docker считает контейнер завершённым. `CMD ["httpd-foreground"]` запускает `apachectl -DFOREGROUND`.

### Поведение сигналов и graceful

`apachectl` при `SIGTERM`/`SIGWINCH` выполняет graceful shutdown/restart. Для приёма изменённого конфига в контейнере — перемонтировать конфиг и сделать `docker exec ... apachectl graceful` (или пересоздать контейнер, что надёжнее в оркестрации).

---

## Практические сценарии

### 1. Запуск с монтированием конфигурации и контента

```bash
docker run -d --name web \
  -p 8080:80 \
  -v "$PWD/conf:/usr/local/apache2/conf/conf.d:ro" \
  -v "$PWD/htdocs:/usr/local/apache2/htdocs:ro" \
  -v "$PWD/logs:/usr/local/apache2/logs" \
  httpd:2.4
```

Проверка:

```bash
curl -sI http://localhost:8080/
# → HTTP/1.1 200 OK
```

### 2. Кастомный Dockerfile с vhost/templates

```dockerfile
FROM httpd:2.4

# Копирование конфигов (Include conf.d/*.conf уже есть в httpd.conf)
COPY conf/site.conf /usr/local/apache2/conf/conf.d/site.conf
COPY htdocs/ /usr/local/apache2/htdocs/

# Контейнер должен быть способен слушать 443/нестандартные порты:
USER root
```

### 3. ENV-шаблонизация через envsubst

```dockerfile
FROM httpd:2.4

COPY tools/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["httpd-foreground"]
```

```bash
#!/bin/sh
# tools/entrypoint.sh
set -e
envsubst < /etc/httpd-templates/vhost.tpl > /usr/local/apache2/conf/conf.d/vhost.conf
exec "$@"
```

Шаблон:

```apacheconf
# /etc/httpd-templates/vhost.tpl
Listen ${APACHE_PORT}
<VirtualHost *:${APACHE_PORT}>
    ServerName ${APP_HOST}
    DocumentRoot /usr/local/apache2/htdocs
</VirtualHost>
```

```bash
docker run -d -p 8080:8080 -e APACHE_PORT=8080 -e APP_HOST=app.example.com web:latest
```

### 4. Включение модуля и HTTPS в контейнере

```apacheconf
# conf/conf.d/ssl.conf
LoadModule ssl_module modules/mod_ssl.so
Listen 443
<VirtualHost *:443>
    SSLEngine on
    SSLCertificateFile /certs/fullchain.pem
    SSLCertificateKeyFile /certs/privkey.pem
    DocumentRoot /usr/local/apache2/htdocs
</VirtualHost>
```

```bash
docker run -d --name web-ssl \
  -p 443:443 \
  -v "$PWD/certs:/certs:ro" \
  -v "$PWD/conf:/usr/local/apache2/conf/conf.d:ro" \
  httpd:2.4
```

### 5. Healthcheck

```dockerfile
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -fsS http://localhost/server-status || exit 1
```

или в compose:

```yaml
services:
  web:
    image: httpd:2.4
    ports: ["8080:80"]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost/server-status"]
      interval: 10s
      timeout: 3s
      retries: 3
```

### 6. Docker Compose со связанным PHP-бэкендом

```yaml
services:
  web:
    image: httpd:2.4
    ports: ["8080:80"]
    volumes:
      - ./conf:/usr/local/apache2/conf/conf.d:ro
      - ./app:/usr/local/apache2/htdocs
    depends_on:
      - php
  php:
    image: php:8.3-fpm
```

```apacheconf
# conf/conf.d/php.conf
<FilesMatch \.php$>
    SetHandler "proxy:fcgi://php:9000"
</FilesMatch>
<Directory "/usr/local/apache2/htdocs">
    AllowOverride All
    Require all granted
</Directory>
```

---

## Операции и команды

| Команда | Назначение |
|---|---|
| `docker exec -ti web apachectl -M` | Список загруженных модулей |
| `docker exec -ti web apachectl configtest` | Проверка синтаксиса в контейнере |
| `docker exec -ti web apachectl graceful` | Graceful reload без разрыва |
| `docker logs web` | Логи контейнера (stdout) |
| `docker cp conf/site.conf web:/usr/local/apache2/conf/conf.d/` | Доставка конфига на лету (не рекомендуется в стеке) |
| `docker port web` | Маппинг портов |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `HTTP/1.1 403` для смонтированного каталога | Права на том/другой User; SELinux | `sudo chcon -Rt container_file_t` или `:ro,Z` на тома; выровнять владельца |
| Контейнер сразу завершается | Запущен не в foreground | `CMD ["httpd-foreground"]`; `-DFOREGROUND` |
| Модуль «не подгружается» | В conf.d нет `LoadModule`, или модуля нет в образе | Добавить `LoadModule`; расширить образ |
| `AH00072: make_sock: could not bind to address` | Host-порт занят/privileged-порт | `-p 8080:80`, проверка `ss` |
| Конфиг «не подхватился» после изменения | Изменён файл, но процесс не перечитал | `docker exec ... apachectl graceful` или пересоздать контейнер |
| Healthcheck «ложный» red | `mod_status` скрыт или curl в образе нет | Включить `server-status`; базовый образ → добавить curl или healthcheck на `nc` |

---

## Лучшие практики

1. Конфиг и контент — монтировать read-only; логи — в общий каталог/fluent-логи.
2. Не запускать процессы внутри контейнера как root: для production использовать образы с непривилегированным пользователем или `USER` в Dockerfile.
3. Изменения конфигурации — через пересоздание образа/контейнера (immutable), не `docker exec`-правки.
4. TLS-сертификаты монтировать `:ro` и держать секреты вне репозитория.
5. Healthcheck через `server-status` обязателен для оркестрации/LB.
6. Для балансировки нескольких контейнеров — выносить проксирование на фронт (Nginx/Apache/HAProxy) и не плодить порты.

---

## Дополнительная информация

### См. также

*   [Nginx в Docker](../Nginx/Scenarios/nginx_in_docker.md) — аналогичные паттерны для Nginx.
*   [Dockerfile: базовые образы и метаданные](../../Docker/Dockerfile/Instructions/base_image_and_metadata.md) — HEALTHCHECK, USER, CMD.
*   [Docker Compose: продвинутые темы](../../Docker/Docker_compose/docker_compose_advanced_topics.md) — сети, depends_on, healthchecks.