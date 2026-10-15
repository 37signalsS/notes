# Apache в Docker (официальный образ httpd)

**Актуально для:** Apache httpd 2.4.x (официальные Docker-образы `httpd:2.4` / `httpd:2.4-alpine`, Debian Bookworm / Alpine Linux)

---

## Определения

**Официальный образ `httpd`** — поддерживаемый сообществом Docker образ Apache HTTP Server (Docker Hub `library/httpd`), собираемый из исходных кодов с установкой в префикс `$HTTPD_PREFIX=/usr/local/apache2`. Поставляется в вариантах на базе Debian (`httpd:2.4`, `httpd:bookworm`) и Alpine Linux (`httpd:2.4-alpine`).

**Скрипт `httpd-foreground`** — специализированный entrypoint-скрипт (`/usr/local/bin/httpd-foreground`), выполняющий предварительную очистку устаревшего PID-файла (`rm -f /usr/local/apache2/logs/httpd.pid`) и запускающий процесс Apache в foreground-режиме (`exec httpd -DFOREGROUND "$@"`).

**Сигнал `SIGWINCH` (graceful-stop)** — сигнал завершения работы веб-сервера Apache, при котором родительский процесс прекращает прием новых сетевых соединений на слушающих сокетах, ожидает завершения обработки всех текущих активных клиентских запросов дочерними процессами и лишь затем завершает работу.

**Сигнал `SIGTERM` (abrupt stop)** — сигнал немедленной остановки сервера по умолчанию для Docker, при котором мастер-процесс Apache сразу отправляет сигналы уничтожения всем дочерним процессам/потокам, вызывая обрыв активных клиентских сессий и незавершенных ответов (HTTP 502/TCP Reset со стороны прокси).

**Потоковое логирование (`/proc/self/fd/1`, `/proc/self/fd/2`)** — механизм вывода журналов веб-сервера в стандартные потоки вывода (`stdout`) и ошибок (`stderr`) процесса контейнера через виртуальную файловую систему procfs, предотвращающий ошибки доступа (`Permission denied`) при сбросе привилегий воркерами на непривилегированного пользователя.

**Непривилегированный запуск (Non-root / Rootless)** — эксплуатация контейнера под пользователем с ненулевым UID (например, `daemon` / `1001` / `www-data`), исключающая использование системного пользователя `root` внутри пространства имен контейнера для соблюдения принципа наименьших привилегий (PoLP).

**ENV-шаблонизация** — динамическая генерация конфигурационных файлов веб-сервера перед его запуском с помощью подстановщика переменных окружения (например, `envsubst`) внутри кастомного entrypoint-скрипта.

**Healthcheck контейнера** — процедура проверки жизнеспособности (liveness) и готовности (readiness) сервиса средствами Docker Daemon через выполнение probe-команды к специализированному эндпоинту (например, `/server-status` модуля `mod_status`).

---

## Архитектура и базовые концепции

### Внутреннее устройство официального образа httpd

В отличие от дистрибутивных пакетов Apache в Debian/Ubuntu (`/etc/apache2/` со скриптами `a2enmod`/`a2ensite`) или RHEL/AlmaLinux (`/etc/httpd/`), официальный Docker-образ компилируется из апстрим-исходников и имеет каноническую структуру каталогов:

| Путь в контейнере | Назначение | Особенности эксплуатации в Docker |
|---|---|---|
| `/usr/local/apache2/` | Корень установки (`$HTTPD_PREFIX`) | Базовая директория веб-сервера |
| `conf/httpd.conf` | Главный конфигурационный файл | По умолчанию содержит минимальный набор активных директив; `IncludeOptional` для внешних каталогов выключен |
| `conf/extra/*.conf` | Дополнительные конфигурации | Конфигурации виртуальных хостов (`httpd-vhosts.conf`), SSL (`httpd-ssl.conf`), статуса (`httpd-info.conf`) |
| `modules/*.so` | Динамические модули Apache | Загружаются строго через директиву `LoadModule` в `httpd.conf` |
| `htdocs/` | `DocumentRoot` по умолчанию | Содержит дефолтный `index.html` ("It works!") |
| `logs/` | Каталог логов и runtime-файлов | По умолчанию содержит symlink-перенаправления и `httpd.pid` |
| `/usr/local/bin/httpd-foreground` | Исполняемый файл запуска | Удаляет старый `httpd.pid` и запускает `httpd -DFOREGROUND` через `exec` |

> [!IMPORTANT]
> В оригинальном файле `httpd.conf` официального образа директива `Include conf/conf.d/*.conf` **отсутствует**. Если вы монтируете каталог с конфигурациями в `/usr/local/apache2/conf/conf.d`, необходимо явно прописать директиву `IncludeOptional conf/conf.d/*.conf` в главном `httpd.conf` либо через `sed` при сборке Dockerfile.

### Жизненный цикл процесса, PID 1 и обработка сигналов

В контейнерной среде процесс с PID 1 несет ответственность за обработку сигналов и завершение дочерних зомби-процессов:

```
[Docker Daemon / docker stop]
         |
         | (отправляет SIGWINCH при правильной настройке)
         v
[PID 1: httpd -DFOREGROUND] (Master Process, root или daemon)
         |
         +-- [Worker Process 1] ---> дорабатывает текущий HTTP-запрос и мягко завершается
         +-- [Worker Process 2] ---> дорабатывает текущий HTTP-запрос и мягко завершается
         +-- [Worker Process N] ---> закрывает соединения
         v
[Master Process выходит с кодом 0]
```

1. **Проблема стандартного `docker stop` (`SIGTERM`):**
   По умолчанию Docker отправляет процессу PID 1 сигнал `SIGTERM`. Для Apache сигнал `SIGTERM` является аварийным завершением (`abrupt stop`): мастер немедленно рассылает `SIGTERM` всем дочерним процессам, обрывая TCP-сессии клиентов. В продакшн-окружении (особенно за внешними балансировщиками HAProxy/Nginx) это вызывает всплеск 502 Bad Gateway при каждом деплое или перезапуске контейнера.
2. **Решение через `SIGWINCH`:**
   Для корректного плавного завершения (Graceful Shutdown) необходимо настроить отправку сигнала `SIGWINCH`:
   - В `Dockerfile`: директива `STOPSIGNAL SIGWINCH`.
   - В `docker-compose.yml`: параметр `stop_signal: SIGWINCH` в связке с `stop_grace_period: 30s` (или более, в зависимости от длительности транзакций).
3. **Защита от сбоя PID-файла (`httpd-foreground`):**
   При некорректной остановке хоста (OOMKilled, отключение питания, `docker kill`) файл `/usr/local/apache2/logs/httpd.pid` остается на диске. При следующем старте веб-сервер сообщает:
   `httpd (pid 1) already running` и аварийно завершается.
   Скрипт `httpd-foreground` решает эту проблему, выполняя `rm -f /usr/local/apache2/logs/httpd.pid` непосредственно перед вызовом `exec httpd`.

### Архитектура логирования: stdout/stderr без потери прав

В стандартной установке Apache пишет логи в файлы на локальном диске (`logs/access_log`, `logs/error_log`). В микросервисной и контейнерной архитектуре логи должны транслироваться в `stdout`/`stderr` контейнера для их сбора Docker logging drivers (journald, json-file, local, vector, promtail):

- В официальном образе `httpd` выполнена замена путей логов на прямые файловые дескрипторы:
  ```apacheconf
  CustomLog /proc/self/fd/1 combined
  ErrorLog /proc/self/fd/2
  ```
- **Почему не симлинки на `/dev/stdout`?**
  Симлинки `/var/log/... -> /dev/stdout`, применяемые в Nginx, в Apache вызывают ошибку `Permission denied (13)` в момент форка воркеров. Когда мастер-процесс (root) порождает воркер под непривилегированным пользователем `daemon`, воркер не имеет прав на открытие псевдотерминала или блочного устройства `/dev/stdout`. Использование `/proc/self/fd/1` обращается к уже открытому дескриптору текущего процесса, гарантируя стабильную запись.

### Разделение привилегий и запуск под Non-Root

По умолчанию контейнер стартует от пользователя `root` (UID 0):
1. Мастер-процесс (root) запускается, открывает привилегированные порты 80 и 443 (`bind()`).
2. Читает сертификаты и ключевые файлы TLS.
3. Порождает пул воркеров и выполняет сброс привилегий на системного пользователя, указанного в директивах `User` и `Group` файла `httpd.conf` (по умолчанию `daemon:daemon`, UID 1:GID 1).

Для соответствия жестким стандартам безопасности (CIS Docker Benchmark, Rootless Docker) запуск контейнера от `root` запрещается:
- Порты веб-сервера перенастраиваются на непривилегированные (`Listen 8080`, `Listen 8443`).
- Директива `PidFile` перенаправляется в каталог, доступный пользователю на запись (`/tmp/httpd.pid` или каталог с правами пользователя).
- Контейнер запускается под `USER www-data` (UID 33) или кастомным `USER 1001:1001`.

### Сравнение базовых образов: Debian vs Alpine

| Параметр | `httpd:2.4` (Debian Bookworm slim) | `httpd:2.4-alpine` (Alpine Linux) |
|---|---|---|
| Размер образа | ~150–170 MB | ~55–65 MB |
| Системная библиотека | `glibc` | `musl libc` |
| Менеджер пакетов | `apt-get` | `apk` |
| Утилита HTTP-запросов | `wget` (GNU), `curl` отсутствует | `wget` (BusyBox), `curl` отсутствует |
| Совместимость с C-библиотеками | Максимальная (любые внешние `.so`) | Ограниченная (специфика `musl`) |
| Применение в SRE/DevOps | Сложные сборки с модулями OIDC/Auth/WAF | Минималистичный статический сервер, reverse proxy |

### Модель MPM и лимиты ресурсов контейнера

Официальный образ `httpd:2.4` по умолчанию скомпилирован и сконфигурирован с модулем `mpm_event`. В контейнерах с жесткими лимитами памяти (`--memory` в Docker или `deploy.resources.limits.memory` в Compose) неконтролируемый рост воркеров приводит к `Exit Code 137` (OOMKilled).

Расчет лимитов MPM под память контейнера:
$$\text{MaxRequestWorkers} \le \frac{\text{Лимит RAM контейнера} - \text{Базовый оверхед мастера (~30MB)}}{\text{Средний размер процесса воркера (~15-25MB)}}$$

В файле `conf/extra/httpd-mpm.conf` параметры настраиваются под выделенный ресурс:
```apacheconf
<IfModule mpm_event_module>
    StartServers             2
    MinSpareThreads         25
    MaxSpareThreads         75
    ThreadLimit             64
    ThreadsPerChild         25
    MaxRequestWorkers      100
    MaxConnectionsPerChild   0
</IfModule>
```

---

## Практические сценарии

### Сценарий 1: Запуск Apache с внешним статическим контентом и модульной конфигурацией

Использование официального образа без пересборки. Для чтения дополнительных конфигураций монтируем виртуальный хост в каталог `conf/extra/` и активируем его передачей директивы через аргументы командной строки.

Структура каталогов проекта:
```text
project/
├── conf/
│   └── site.conf
└── htdocs/
    └── index.html
```

Конфигурация виртуального хоста `conf/site.conf`:
```apacheconf
<VirtualHost *:80>
    ServerName site.local
    ServerAdmin webmaster@site.local
    DocumentRoot "/usr/local/apache2/htdocs"

    <Directory "/usr/local/apache2/htdocs">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    CustomLog /proc/self/fd/1 combined
    ErrorLog /proc/self/fd/2
</VirtualHost>
```

Команда запуска:
```bash
docker run -d \
  --name apache-web \
  --restart unless-stopped \
  -p 8080:80 \
  -v "$PWD/htdocs:/usr/local/apache2/htdocs:ro" \
  -v "$PWD/conf/site.conf:/usr/local/apache2/conf/extra/httpd-vhosts.conf:ro" \
  httpd:2.4 \
  httpd-foreground -c "Include conf/extra/httpd-vhosts.conf"
```

Проверка доступности:
```bash
curl -sI http://localhost:8080/
# → HTTP/1.1 200 OK
# → Date: Wed, 14 Oct 2026 15:45:00 GMT
# → Server: Apache/2.4.62 (Unix)
```

---

### Сценарий 2: Production Dockerfile (Immutable сборка, Non-Root, тюнинг безопасности)

Создание защищенного самодостаточного образа без запуска от root. Используются порт 8080, выделенный пользователь `www-data`, отключение раскрытия версий и настройка `STOPSIGNAL`.

`Dockerfile`:
```dockerfile
FROM httpd:2.4-alpine

# Настройка корректного graceful shutdown
STOPSIGNAL SIGWINCH

# Рабочая директория
WORKDIR /usr/local/apache2

# 1. Активация необходимых модулей через раскомментирование LoadModule
# 2. Настройка вывода версий (Security Hardening)
# 3. Перевод порта на 8080 для работы без root
# 4. Перенос PidFile в доступный каталог /tmp
RUN set -eux; \
    sed -ri \
        -e 's!^#?(Listen)\s+[0-9]+!\1 8080!g' \
        -e 's!^#?(ServerTokens)\s+\S+!\1 Prod!g' \
        -e 's!^#?(ServerSignature)\s+\S+!\1 Off!g' \
        -e 's!^#(LoadModule rewrite_module modules/mod_rewrite.so)!\1!' \
        -e 's!^#(LoadModule headers_module modules/mod_headers.so)!\1!' \
        -e 's!^#(LoadModule status_module modules/mod_status.so)!\1!' \
        -e 's!^#(Include conf/extra/httpd-vhosts.conf)!\1!' \
        conf/httpd.conf; \
    echo "ServerTokens Prod" >> conf/httpd.conf; \
    echo "ServerSignature Off" >> conf/httpd.conf; \
    echo "PidFile /tmp/httpd.pid" >> conf/httpd.conf; \
    mkdir -p conf/conf.d; \
    echo "IncludeOptional conf/conf.d/*.conf" >> conf/httpd.conf

# Копирование исходных файлов сайта и конфигураций
COPY conf/conf.d/ conf/conf.d/
COPY htdocs/ htdocs/

# Настройка прав доступа для непривилегированного пользователя daemon (UID 1 / GID 1 в Alpine)
RUN chown -R daemon:daemon htdocs/ logs/

# Переключение на непривилегированного пользователя
USER daemon

# Проверка состояния контейнера средствами wget (встроен в BusyBox Alpine)
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

EXPOSE 8080

CMD ["httpd-foreground"]
```

Сборка и проверка образа:
```bash
docker build -t custom-apache:2.4-hardened .
docker run -d --name secure-web -p 8080:8080 custom-apache:2.4-hardened
docker top secure-web
# → UID        PID     PPID    C   STIME   TTY     TIME       CMD
# → daemon     12345   12300   0   18:45   ?       00:00:00   httpd -DFOREGROUND
# → daemon     12346   12345   0   18:45   ?       00:00:00   httpd -DFOREGROUND
```

---

### Сценарий 3: ENV-шаблонизация конфигурации через envsubst

Часто требуется передавать upstream-хосты, порты или доменные имена через переменные окружения контейнера без пересборки образа.

`entrypoint.sh`:
```bash
#!/bin/sh
set -e

# Проверка обязательных переменных
if [ -z "$SERVER_NAME" ]; then
    export SERVER_NAME="localhost"
fi

if [ -z "$BACKEND_HOST" ]; then
    export BACKEND_HOST="127.0.0.1"
fi

if [ -z "$BACKEND_PORT" ]; then
    export BACKEND_PORT="9000"
fi

# Подстановка переменных из шаблона в итоговый конфиг виртуального хоста
envsubst '${SERVER_NAME} ${BACKEND_HOST} ${BACKEND_PORT}' \
  < /usr/local/apache2/templates/vhost.conf.template \
  > /usr/local/apache2/conf/conf.d/vhost.conf

# Обязательно передаем управление процессу через exec для сохранения PID 1 и сигналов
exec "$@"
```

Шаблон виртуального хоста `templates/vhost.conf.template`:
```apacheconf
<VirtualHost *:80>
    ServerName ${SERVER_NAME}

    ProxyPreserveHost On
    ProxyPass /api/ "http://${BACKEND_HOST}:${BACKEND_PORT}/"
    ProxyPassReverse /api/ "http://${BACKEND_HOST}:${BACKEND_PORT}/"

    DocumentRoot "/usr/local/apache2/htdocs"
</VirtualHost>
```

`Dockerfile` с установкой `gettext` (`envsubst`):
```dockerfile
FROM httpd:2.4-alpine

RUN apk add --no-cache gettext

RUN sed -ri \
    -e 's!^#(LoadModule proxy_module modules/mod_proxy.so)!\1!' \
    -e 's!^#(LoadModule proxy_http_module modules/mod_proxy_http.so)!\1!' \
    conf/httpd.conf; \
    echo "IncludeOptional conf/conf.d/*.conf" >> conf/httpd.conf; \
    mkdir -p /usr/local/apache2/conf/conf.d /usr/local/apache2/templates

COPY templates/ /usr/local/apache2/templates/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["httpd-foreground"]
```

Запуск с передачей переменных:
```bash
docker run -d --name templated-web \
  -e SERVER_NAME="api.company.local" \
  -e BACKEND_HOST="192.168.1.50" \
  -e BACKEND_PORT="8000" \
  -p 80:80 \
  templated-web:latest
```

---

### Сценарий 4: HTTPS/TLS с монтированием сертификатов и безопасным шифрованием

Монтирование TLS-сертификатов в контейнер в режиме "только чтение" (`:ro`) с активацией `mod_ssl` и `mod_socache_shmcb`.

Конфигурация `conf/ssl-vhost.conf`:
```apacheconf
LoadModule ssl_module modules/mod_ssl.so
LoadModule socache_shmcb_module modules/mod_socache_shmcb.so

Listen 443

SSLSessionCache shmcb:/usr/local/apache2/logs/ssl_gcache_data(512000)
SSLSessionCacheTimeout 300
SSLProtocol -all +TLSv1.2 +TLSv1.3
SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
SSLHonorCipherOrder off

<VirtualHost *:443>
    ServerName secure.example.local
    DocumentRoot "/usr/local/apache2/htdocs"

    SSLEngine on
    SSLCertificateFile "/etc/ssl/certs/tls.crt"
    SSLCertificateKeyFile "/etc/ssl/private/tls.key"

    <Directory "/usr/local/apache2/htdocs">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    CustomLog /proc/self/fd/1 combined
    ErrorLog /proc/self/fd/2
</VirtualHost>
```

Запуск контейнера:
```bash
docker run -d --name apache-ssl \
  -p 443:443 \
  -v "$PWD/certs/tls.crt:/etc/ssl/certs/tls.crt:ro" \
  -v "$PWD/certs/tls.key:/etc/ssl/private/tls.key:ro" \
  -v "$PWD/conf/ssl-vhost.conf:/usr/local/apache2/conf/extra/httpd-ssl.conf:ro" \
  httpd:2.4 \
  httpd-foreground -c "Include conf/extra/httpd-ssl.conf"
```

Проверка TLS-рукопожатия:
```bash
openssl s_client -connect localhost:443 -servername secure.example.local -brief
# → CONNECTION ESTABLISHED
# → Protocol version: TLSv1.3
# → Ciphersuite: TLS_AES_256_GCM_SHA384
```

---

### Сценарий 5: Мониторинг через mod_status и Prometheus apache_exporter

Для обеспечения наблюдаемости (Observability) веб-сервер настраивается на отдачу машиночитаемой статистики `/server-status?auto`, которую скрейпит `apache_exporter`.

Конфигурация `conf/status.conf`:
```apacheconf
LoadModule status_module modules/mod_status.so

ExtendedStatus On

<Location /server-status>
    SetHandler server-status
    Require ip 127.0.0.1 172.16.0.0/12 10.0.0.0/8
</Location>
```

Фрагмент `docker-compose.yml` со стеком мониторинга:
```yaml
services:
  apache:
    image: httpd:2.4-alpine
    container_name: production-web
    stop_signal: SIGWINCH
    stop_grace_period: 30s
    ports:
      - "80:80"
    volumes:
      - ./conf/status.conf:/usr/local/apache2/conf/extra/status.conf:ro
    command: ["httpd-foreground", "-c", "Include conf/extra/status.conf"]
    networks:
      - webnet

  apache-exporter:
    image: bitnami/apache-exporter:1.0.9
    container_name: apache-exporter
    command:
      - "--scrape_uri=http://apache:80/server-status?auto"
    ports:
      - "9117:9117"
    depends_on:
      - apache
    networks:
      - webnet

networks:
  webnet:
    driver: bridge
```

Проверка сбора метрик Prometheus:
```bash
curl -s http://localhost:9117/metrics | grep -E '^apache_workers'
# → apache_workers{state="busy"} 1
# → apache_workers{state="idle"} 49
```

---

### Сценарий 6: Продакшн Docker Compose стек: Apache (FastCGI Frontend) + PHP-FPM

Отказоустойчивая конфигурация с изоляцией сетей, строгими ограничениями cgroups по CPU/RAM и сохранением сигналов.

`docker-compose.yml`:
```yaml
services:
  web:
    image: httpd:2.4-alpine
    container_name: app-web
    restart: unless-stopped
    stop_signal: SIGWINCH
    stop_grace_period: 30s
    ports:
      - "80:8080"
    volumes:
      - ./conf/httpd.conf:/usr/local/apache2/conf/httpd.conf:ro
      - ./conf/site.conf:/usr/local/apache2/conf/conf.d/site.conf:ro
      - app-data:/var/www/html:ro
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 256M
        reservations:
          cpus: '0.25'
          memory: 64M
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:8080/healthz"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
    depends_on:
      php:
        condition: service_healthy
    networks:
      - frontend
      - backend

  php:
    image: php:8.3-fpm-alpine
    container_name: app-php
    restart: unless-stopped
    volumes:
      - app-data:/var/www/html
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 512M
    healthcheck:
      test: ["CMD-SHELL", "cgi-fcgi -bind -connect 127.0.0.1:9000 || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 3
    networks:
      - backend

volumes:
  app-data:

networks:
  frontend:
    driver: bridge
  backend:
    internal: true
```

Конфигурация `conf/site.conf` для проксирования PHP:
```apacheconf
<VirtualHost *:8080>
    ServerName app.local
    DocumentRoot "/var/www/html"

    <Directory "/var/www/html">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
        DirectoryIndex index.php index.html
    </Directory>

    # Проксирование запросов к PHP-FPM через FastCGI
    <FilesMatch \.php$>
        SetHandler "proxy:fcgi://php:9000"
    </FilesMatch>

    # Легковесный эндпоинт для healthcheck
    Alias /healthz /usr/local/apache2/htdocs/healthz.html
</VirtualHost>
```

---

## Операции и команды

| Команда | Назначение | Пример использования |
|---|---|---|
| `docker exec -i <container> apachectl configtest` | Проверка синтаксиса конфигурационных файлов | `docker exec -i web apachectl configtest` <br> `# → Syntax OK` |
| `docker exec -i <container> apachectl -M` | Список всех скомпилированных и загруженных модулей | `docker exec -i web apachectl -M \| grep proxy` |
| `docker exec -i <container> apachectl -V` | Информация о версии, дате сборки, MPM и параметрах компиляции | `docker exec -i web apachectl -V \| grep MPM` <br> `# → Server MPM: event` |
| `docker exec -i <container> apachectl -S` | Дамп настроек виртуальных хостов и маршрутизации имен | `docker exec -i web apachectl -S` <br> `# → VirtualHost configuration:` |
| `docker kill -s USR1 <container>` | Мягкая перезагрузка (graceful restart) без разрыва соединений | `docker kill -s USR1 web` |
| `docker kill -s WINCH <container>` | Плавная остановка (graceful stop) с ожиданием завершения клиентов | `docker kill -s WINCH web` |
| `docker stop -t 30 <container>` | Корректный останов контейнера с ожиданием таймаута graceful | `docker stop -t 30 web` |
| `docker top <container>` | Просмотр дерева процессов контейнера (мастер и воркеры) | `docker top web` |
| `docker stats <container>` | Потоковый мониторинг потребления CPU, памяти и сети cgroups | `docker stats --no-stream web` |
| `docker logs --tail 50 -f <container>` | Непрерывный просмотр журналов веб-сервера из stdout/stderr | `docker logs -f --tail 50 web` |

---

## Диагностика и устранение неполадок

| Симптом | Первопричина | Проверенное решение |
|---|---|---|
| `httpd (pid X) already running` при старте | Контейнер был завершен аварийно (`kill -9`, отключение хоста), и файл `httpd.pid` остался в `logs/` | Использовать штатный скрипт `httpd-foreground`, который автоматически выполняет `rm -f /usr/local/apache2/logs/httpd.pid`. Если переопределен `ENTRYPOINT`, добавить удаление PID перед стартом |
| Контейнер завершается с Exit Code 137 | Превышен лимит памяти cgroups (OOMKilled) из-за высокого `MaxRequestWorkers` в MPM | Задать `MaxRequestWorkers` в `conf/extra/httpd-mpm.conf` из расчета 20MB на поток/воркер под лимит `memory:` в Docker Compose |
| Обрыв клиентских соединений при обновлении (`docker compose up -d`) | Docker отправляет `SIGTERM` по умолчанию, вызывая мгновенный сброс соединений сервером | Добавить в конфигурацию сервиса `stop_signal: SIGWINCH` и увеличить `stop_grace_period: 30s` (или `STOPSIGNAL SIGWINCH` в Dockerfile) |
| `AH00072: make_sock: could not bind to address 0.0.0.0:80` | Попытка биндинга на порт < 1024 при запуске от непривилегированного пользователя без capability | Переключить директиву `Listen` на порт 8080 (`Listen 8080`), либо добавить контейнеру Linux capability `cap_add: [NET_BIND_SERVICE]` |
| `AH00091: ... Cannot open ... logs/error_log: Permission denied` | При запуске под `USER www-data` каталог `/usr/local/apache2/logs` принадлежит `root` | В Dockerfile выполнить `chown -R www-data:www-data /usr/local/apache2/logs`, либо перенаправить логи в `/proc/self/fd/2` и `PidFile` в `/tmp/httpd.pid` |
| Сбой Healthcheck (`unhealthy`), код выхода 127 | В базовом образе `httpd:2.4-alpine` отсутствует утилита `curl` | В команде проверки жизнеспособности использовать `wget -q --spider http://127.0.0.1:80/` вместо `curl`, либо установить `curl` через пакетный менеджер |
| Изменения в `conf.d/*.conf` не применяются | В стандартном `httpd.conf` апстрима отсутствует директива автоматического включения `conf.d` | Добавить в `httpd.conf` строку `IncludeOptional conf/conf.d/*.conf` |
| Ошибка `HTTP 403 Forbidden` при монтировании тома с хоста RHEL/Rocky | SELinux блокирует доступ контейнера к файлам на хостовой файловой системе | Добавить флаг `:z` (разделяемый доступ) или `:Z` (монопольный доступ) к монтированию тома: `-v /host/path:/usr/local/apache2/htdocs:ro,z` |

---

## Лучшие практики

1. **Неизменяемость образов (Immutability):**
   Собирайте production-образы с готовыми конфигурациями и статическими ресурсами внутри Docker-образа. Избегайте правок конфигурации на работающем сервере через `docker exec` или ручной доставки файлов через `docker cp`.
2. **Конфигурация Graceful Shutdown:**
   Всегда объявляйте `STOPSIGNAL SIGWINCH` в `Dockerfile` или `stop_signal: SIGWINCH` в `docker-compose.yml`. Устанавливайте `stop_grace_period` не менее 30 секунд для предотвращения сброса активных сессий пользователей.
3. **Безопасность процессов (Non-Root запуск):**
   Не запускайте контейнер от суперпользователя `root` в промышленной эксплуатации. Настраивайте веб-сервер на прослушивание портов `>= 1024` (например, 8080 и 8443) и переключайте пользователя директивой `USER daemon` или `USER 1001:1001`.
4. **Защита корневой файловой системы (`read_only`):**
   Запускайте контейнер с флагом `--read-only` (или директивой `read_only: true` в Compose). Для временных файлов и PID-файла монтируйте `tmpfs` в `/tmp` и `/usr/local/apache2/logs`:
   ```yaml
   read_only: true
   tmpfs:
     - /tmp:rw,noexec,nosuid,size=64m
     - /usr/local/apache2/logs:rw,noexec,nosuid,size=32m
   ```
5. **Централизация потокового логирования:**
   Используйте `/proc/self/fd/1` и `/proc/self/fd/2` для вывода журналов. Не сохраняйте access-логи внутри файловой системы контейнера во избежание переполнения дискового пространства хоста.
6. **Контроль параметров MPM и лимитов cgroups:**
   Всегда согласовывайте директиву `MaxRequestWorkers` в `httpd-mpm.conf` с лимитом памяти контейнера в Docker Compose, чтобы защитить сервис от аварийного завершения OOM Killer при всплесках трафика.
7. **Изоляция секретов и сертификатов:**
   Никогда не зашивайте приватные ключи TLS в слой Docker-образа. Монтируйте сертификаты в режиме `ro` через Docker Volumes или внешние системы управления секретами хоста.
8. **Автоматизированный мониторинг и Healthcheck:**
   Настраивайте эндпоинт `mod_status` с ограничением доступа только для доверенной локальной сети и используйте `apache_exporter` для непрерывного сбора метрик производительности и пула воркеров в Prometheus.

---

## Дополнительная информация

### См. также

*   [Укрепление безопасности Apache](./apache_hardening.md) — детальная настройка директив безопасности, лимитов буферов и защита от Slowloris.
*   [Тюнинг производительности Apache](./apache_performance_tuning.md) — глубокая оптимизация MPM, сокетов ядра Linux и параметров KeepAlive.
*   [Обзор архитектуры Apache](./apache_overview.md) — устройство ядра, обработка фаз HTTP-запроса и взаимодействие модулей.
*   [Nginx в Docker](../Nginx/Scenarios/nginx_in_docker.md) — сравнительные паттерны эксплуатации и контейнеризации для Nginx.
*   [Контейнерная безопасность: Харденинг контейнеров](../../Docker/Docker_security/container_hardening.md) — практики изоляции, capabilities и seccomp.
*   [Ограничение ресурсов контейнеров](../../Docker/Docker_security/resource_limits.md) — тонкая настройка cgroups памяти и CPU для Docker.
*   [Docker Compose: продвинутые темы](../../Docker/Docker_compose/docker_compose_advanced_topics.md) — оркестрация сетей, healthcheck и политики перезапуска.
*   [Централизованный сбор логов Docker](../../Docker/Docker_logs/docker_centralized_logging.md) — организация передачи stdout/stderr в центральные лог-коллекторы.