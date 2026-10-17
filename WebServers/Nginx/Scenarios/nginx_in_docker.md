# Nginx в Docker: эксплуатация контейнерного веб-сервера

**Актуально для:** Nginx 1.26.x / 1.27.x, Docker Engine 27.x+, Docker Compose v2

---

## Определения

- **Официальный образ Nginx (`nginx`)** — базовый OCI-образ, поддерживаемый Nginx Inc. / F5, собираемый на базе Alpine Linux или Debian (Bookworm). Поставляется с Nginx, настроенным на запуск в качестве PID 1 (`daemon off;`), стандартным набором модулей и каталогом скриптов автоконфигурации `/docker-entrypoint.d/`.
- **`nginxinc/nginx-unprivileged`** — официальный специализированный образ для запуска Nginx от непривилегированного пользователя (`nginx`, UID/GID 101). Из коробки сконфигурирован на прослушивание порта `8080`, хранение PID-файла в `/tmp/nginx.pid` и размещение временных файлов кэша в `/tmp/`.
- **PID 1 (Init-процесс контейнера)** — процесс, запускаемый первым в пространстве имён PID (PID namespace). Отвечает за получение и обработку сигналов от ядра Linux (`SIGTERM`, `SIGINT`, `SIGQUIT`), а также за сбор завершившихся дочерних процессов-зомби (reaping zombie processes).
- **Graceful Shutdown (Плавное завершение)** — процесс контролируемой остановки сервиса через сигнал `SIGQUIT` (`nginx -s quit`): мастер-процесс перестаёт принимать новые клиентские TCP-соединения, ожидает завершения обработки всех текущих HTTP-запросов существующими worker-процессами и лишь затем корректно завершает работу.
- **Embedded DNS (Встроенный DNS-резолвер Docker)** — локальный DNS-сервер Docker Engine (`127.0.0.11`), доступный внутри пользовательских сетей (bridge и overlay). Обеспечивает автоматическое разрешение имён сервисов и контейнеров в их динамические IP-адреса.
- **Immutable Container Pattern** — методология сборки контейнеров, при которой конфигурационные файлы, статические ресурсы и зависимости запекаются в образ на этапе CI/CD. Любые изменения конфигурации в production выполняются выпуском новой версии образа, а не ручной правкой файлов в работающем контейнере.
- **Entrypoint Templating (`/docker-entrypoint.d/`)** — встроенный в официальный образ Nginx механизм выполнения shell-скриптов перед запуском основного процесса `nginx`. Включает скрипт `20-envsubst-on-templates.sh` для автоматической генерации конфигурации из шаблонов на основе переменных окружения.

---

## Базовые концепции и архитектура

### Процессная модель, PID 1 и обработка сигналов

В контейнерной среде жизненный цикл контейнера жестко привязан к процессу с PID 1. При остановке контейнера команда `docker stop` посылает сигнал процессу с PID 1, после чего ожидает таймаут (по умолчанию 10 секунд) и, если процесс не завершился, отправляет `SIGKILL`.

```text
Host System (Docker Daemon)
         │
         │ docker stop (SIGQUIT / SIGTERM)
         ▼
┌────────────────────────────────────────────────────────┐
│ Container PID Namespace                                │
│                                                        │
│  [ PID 1: nginx master process ]                       │
│     ├── Чтение конфигурации и управление сокетами      │
│     ├── Перехват сигналов ОС                           │
│     │                                                  │
│     ├─── fork() ───► [ PID 12: worker process (epoll) ]│
│     └─── fork() ───► [ PID 13: worker process (epoll) ]│
└────────────────────────────────────────────────────────┘
```

1. **Директива `daemon off;`**:
   По умолчанию на bare-metal Nginx форкается в фоновый режим: родительский процесс завершается, а дочерний становится демоном. В Docker это недопустимо: завершение родительского процесса (PID 1) немедленно переводит контейнер в статус `Exited (0)`. Поэтому Nginx в контейнере всегда запускается в foreground-режиме через параметр командной строки:
   ```bash
   nginx -g "daemon off;"
   ```
2. **Маршрутизация сигналов**:
   - `SIGQUIT`: Graceful shutdown. Воркеры закрывают слушающие сокеты, дорабатывают активные запросы и завершаются.
   - `SIGTERM` / `SIGINT`: Немедленный сброс (fast shutdown). Все активные соединения принудительно разрываются.
   - `SIGHUP`: Перечитывание конфигурации (`reload`). Мастер проверяет синтаксис, открывает новые сокеты, запускает новое поколение воркеров и отправляет `SIGQUIT` старому поколению.
   - `SIGUSR1`: Повторное открытие лог-файлов (`reopen`). Применяется при ротации логов на хосте.
3. **Остановка контейнера**:
   Официальный Dockerfile Nginx объявляет `STOPSIGNAL SIGQUIT`. Однако при использовании сторонних базовых образов или запуске через кастомные shell-скрипты без команды `exec` PID 1 может занять `/bin/sh`. Shell не передает сигналы дочерним процессам, что приводит к разрыву соединений по таймауту `SIGKILL`. В Docker Compose рекомендуется явно указывать `stop_signal: SIGQUIT` и увеличивать `stop_grace_period` (например, до `30s` или `60s`), если сервер обрабатывает долгие загрузки файлов или соединения WebSocket.

### Сетевая модель и динамический DNS-резолвинг (Service Discovery)

Главная архитектурная проблема при эксплуатации Nginx в качестве Reverse Proxy в Docker — статическое DNS-кэширование:

```text
[ Клиент ] ──► [ Nginx ] ──( proxy_pass http://backend:8080 )──► [ Backend (IP: 172.18.0.3) ]
                                                                             │
                                                                   recreate / deploy
                                                                             ▼
                                                                 [ Backend (IP: 172.18.0.4) ]
                                                                             ▲
Nginx шлёт запросы на старый IP 172.18.0.3 ──────────────────────────────────┘
→ 502 Bad Gateway / Connection Refused
```

- **Статический `proxy_pass`**: Если в конфигурации указано имя хоста без переменных (`proxy_pass http://api_upstream:8080;`), Nginx запрашивает DNS-запись ровно один раз во время запуска или перечитывания конфигурации (`reload`). Если контейнер `api_upstream` перезапущен, пересоздан при деплое или масштабирован, Docker выдает ему новый IP-адрес. Nginx продолжит посылать трафик на устаревший IP-адрес, возвращая клиентам ошибки `502 Bad Gateway`.
- **Динамический `resolver`**: Для принудительного обновления DNS-записей в runtime необходимо использовать встроенный DNS-сервер Docker (`127.0.0.11`) в сочетании с промежуточной переменной в директиве `proxy_pass`:
  ```nginx
  resolver 127.0.0.11 ipv6=off valid=10s;

  location /api/ {
      set $backend_service "http://api_upstream:8080";
      proxy_pass $backend_service;
  }
  ```
  Параметр `ipv6=off` отключает ненужные запросы AAAA-записей к встроенному DNS Docker, предотвращая лишние сетевые задержки.

### Модель логирования и файловая система

Официальный образ Nginx связывает стандартные пути логов со стандартными потоками вывода контейнера через символические ссылки:
- `/var/log/nginx/access.log` -> `/dev/stdout`
- `/var/log/nginx/error.log` -> `/dev/stderr`

Это позволяет Docker Engine перехватывать все события веб-сервера своим логирующим драйвером (по умолчанию `json-file`). 

> [!WARNING]
> Если на хосте не настроена ротация логов Docker Engine, контейнер под высокой нагрузкой способен быстро исчерпать всё свободное дисковое пространство файлами `*-json.log` в каталоге `/var/lib/docker/containers/`. Обязательно ограничивайте размер логов через параметры `max-size` и `max-file` в конфигурации демона или сервиса Compose.

Для интеграции с системами сбора логов (Vector, Promtail, Fluentbit) в production-конфигурациях формат логов преобразуется в структурированный JSON с директивой `escape=json`.

### Шаблонизация конфигурации через переменные окружения

Официальный образ Nginx предоставляет встроенный механизм подстановки переменных окружения перед стартом веб-сервера с помощью скрипта `/docker-entrypoint.d/20-envsubst-on-templates.sh`:

1. Шаблоны размещаются в каталоге `/etc/nginx/templates/` с суффиксом `.template` (например, `/etc/nginx/templates/default.conf.template`).
2. При старте контейнера `envsubst` считывает переменные окружения контейнера, выполняет подстановку и записывает итоговые файлы в `/etc/nginx/conf.d/` (отбрасывая суффикс `.template`).
3. **Защита переменных Nginx (`NGINX_ENVSUBST_FILTER`)**: По умолчанию утилита `envsubst` заменяет абсолютно все конструкции вида `$имя` пустыми строками, если переменная не задана в окружении. Это ломает конфигурацию Nginx, затирая внутренние переменные (`$host`, `$remote_addr`, `$request_uri`). Чтобы избежать повреждения конфига, обязательно объявляйте переменную `NGINX_ENVSUBST_FILTER`, перечисляя в ней только те переменные, которые должны быть заменены.

### Безопасность: Non-root и Read-only корневая файловая система

Стандартный образ `nginx:alpine` запускает мастер-процесс от `root`, так как открытие портов ниже 1024 (`80`, `443`) в Linux требует привилегии `CAP_NET_BIND_SERVICE`. Затем мастер порождает воркеры от пользователя `nginx`.

Запуск от `root` несёт риски выхода за пределы контейнера (container breakout). Стандарты безопасности (CIS Docker Benchmark, PCI-DSS) требуют:
- Использования выделенного образа `nginxinc/nginx-unprivileged` (запуск от UID 101, порт по умолчанию 8080).
- Использования режима `read_only: true` (корневая файловая система монтируется только на чтение).
- Выделения `tmpfs` под каталоги, требующие записи: `/tmp`, `/var/run`, `/var/cache/nginx`.
- Полного сброса привилегий: `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`.

### Ресурсные ограничения (cgroups) и тюнинг воркеров

Директива `worker_processes auto;` определяет число рабочих процессов по количеству доступных ядер процессора через системный вызов `sysconf(_SC_NPROCESSORS_ONLN)`. 

В контейнере на многоядерном сервере (например, 64 ядра) при ограничении контейнера `cpus: 1.0` директива `auto` без вмешательства entrypoint породит 64 воркера. Это приводит к чрезмерному потреблению оперативной памяти и постоянным контекстным переключениям (context switches). В официальных образах скрипт `/docker-entrypoint.d/30-tune-worker-processes.sh` автоматически рассчитывает число воркеров с учетом cgroup CPU quota. В production рекомендуется жестко фиксировать число воркеров (`worker_processes 1;` или `2;`) в соответствии с выделенным лимитом CPU.

---

## Практические сценарии

### Сценарий 1: Production Reverse Proxy с динамическим DNS-резолвингом

Сценарий демонстрирует запуск Nginx перед бэкенд-приложением в пользовательской bridge-сети Docker. Nginx динамически отслеживает изменение IP-адресов бэкенда через встроенный DNS Docker.

**1. Структура проекта:**
```text
.
├── docker-compose.yml
└── nginx.conf
```

**2. Конфигурация Nginx (`nginx.conf`):**
```nginx
worker_processes 1;

events {
    worker_connections 2048;
    use epoll;
    multi_accept on;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    log_format json_analytics escape=json '{'
        '"time_local":"$time_local",'
        '"remote_addr":"$remote_addr",'
        '"request":"$request",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_addr":"$upstream_addr"'
    '}';

    access_log /dev/stdout json_analytics;
    error_log  /dev/stderr warn;

    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    keepalive_timeout 65;

    # Встроенный DNS-сервер Docker Engine
    resolver 127.0.0.11 ipv6=off valid=10s;

    server {
        listen 80;
        server_name _;

        location /healthz {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        location / {
            # Присвоение переменной активирует runtime DNS-резолвинг
            set $backend_target "http://app_backend:8080";
            proxy_pass $backend_target;

            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 5s;
            proxy_read_timeout    30s;
            proxy_send_timeout    30s;
        }
    }
}
```

**3. Файл развертывания (`docker-compose.yml`):**
```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    container_name: production_proxy
    restart: unless-stopped
    stop_signal: SIGQUIT
    stop_grace_period: 30s
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "3"
    depends_on:
      - app_backend
    networks:
      - internal_net

  app_backend:
    image: hashicorp/http-echo:0.2.3
    container_name: app_backend
    restart: unless-stopped
    command: ["-text=Backend Response from Container"]
    networks:
      - internal_net

networks:
  internal_net:
    driver: bridge
```

**4. Запуск и валидация:**
```bash
docker compose up -d
# → [+] Running 3/3
# →  ✔ Network internal_net           Created
# →  ✔ Container app_backend          Started
# →  ✔ Container production_proxy     Started

curl -i http://localhost/healthz
# → HTTP/1.1 200 OK
# → Content-Type: text/plain
# → healthy

curl -s http://localhost/
# → Backend Response from Container

# Проверка устойчивости к изменению IP бэкенда (recreate):
docker compose up -d --force-recreate app_backend
# → ✔ Container app_backend Recreated

sleep 2
curl -s http://localhost/
# → Backend Response from Container
```

---

### Сценарий 2: Запуск в режиме максимальной безопасности (Non-root и Read-only FS)

Запуск от непривилегированного пользователя с монтированием корневой ФС только на чтение (`read-only`), сбросом Linux capabilities и защитой от повышения привилегий.

**1. Конфигурация Nginx (`unprivileged.conf`):**
```nginx
pid /tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    client_body_temp_path /tmp/client_temp;
    proxy_temp_path       /tmp/proxy_temp_path;
    fastcgi_temp_path     /tmp/fastcgi_temp;
    uwsgi_temp_path       /tmp/uwsgi_temp;
    scgi_temp_path        /tmp/scgi_temp;

    server {
        listen 8080;
        server_name _;

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }
}
```

**2. Файл развертывания (`docker-compose.yml`):**
```yaml
services:
  nginx_secure:
    image: nginxinc/nginx-unprivileged:1.27-alpine
    container_name: nginx_secure
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    ports:
      - "8080:8080"
    volumes:
      - ./unprivileged.conf:/etc/nginx/nginx.conf:ro
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=128m
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 256M
        reservations:
          cpus: "0.2"
          memory: 64M
```

**3. Валидация безопасности:**
```bash
docker compose up -d
# → ✔ Container nginx_secure Started

# Проверка непривилегированного пользователя внутри контейнера:
docker exec nginx_secure id
# → uid=101(nginx) gid=101(nginx) groups=101(nginx)

# Проверка доступности веб-сервера на порту 8080:
curl -I http://localhost:8080/
# → HTTP/1.1 200 OK
# → Server: nginx/1.27.4

# Проверка блокировки записи в корневую файловую систему:
docker exec nginx_secure touch /root_test.txt
# → touch: /root_test.txt: Read-only file system
```

---

### Сценарий 3: Шаблонизация конфигурации через переменные окружения (`templates`)

Использование нативного механизма официального образа для передачи параметров через environment с защитой внутренних переменных Nginx.

**1. Шаблон конфигурации (`default.conf.template`):**
```nginx
server {
    listen 80;
    server_name ${VIRTUAL_HOST};

    location / {
        proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**2. Файл развертывания (`docker-compose.yml`):**
```yaml
services:
  nginx_env:
    image: nginx:1.27-alpine
    container_name: nginx_env
    restart: unless-stopped
    ports:
      - "80:80"
    environment:
      - VIRTUAL_HOST=app.internal.local
      - BACKEND_HOST=172.17.0.1
      - BACKEND_PORT=9000
      # Критично: фильтрация предотвращает затирание $host и $remote_addr
      - NGINX_ENVSUBST_FILTER=VIRTUAL_HOST BACKEND_HOST BACKEND_PORT
    volumes:
      - ./default.conf.template:/etc/nginx/templates/default.conf.template:ro
```

**3. Валидация подстановки переменных:**
```bash
docker compose up -d
# → ✔ Container nginx_env Started

# Проверка сгенерированного файла:
docker exec nginx_env cat /etc/nginx/conf.d/default.conf
# → server {
# →     listen 80;
# →     server_name app.internal.local;
# → 
# →     location / {
# →         proxy_pass http://172.17.0.1:9000;
# →         proxy_set_header Host $host;
# →         proxy_set_header X-Real-IP $remote_addr;
# →         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
# →         proxy_set_header X-Forwarded-Proto $scheme;
# →     }
# → }
```

---

### Сценарий 4: Сборка неизменяемого (Immutable) образа с валидацией синтаксиса

Production Dockerfile с предварительной валидацией конфигурации на этапе сборки, настройкой `STOPSIGNAL` и `HEALTHCHECK`.

**1. Файл сборки (`Dockerfile`):**
```dockerfile
FROM nginx:1.27-alpine

# Удаление дефолтной страницы приветствия
RUN rm -f /etc/nginx/conf.d/default.conf

# Копирование статических файлов и конфигурации
COPY html/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/nginx.conf

# Валидация синтаксиса конфигурации на этапе сборки (CI gate)
RUN nginx -t

# Корректный сигнал для плавного завершения соединений
STOPSIGNAL SIGQUIT

# Нативный Healthcheck через wget (установлен в Alpine по умолчанию)
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/healthz || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

**2. Сборка и запуск контейнера:**
```bash
docker build -t custom-nginx:1.0.0 .
# → [+] Building 1.2s (8/8) FINISHED
# → => [4/4] RUN nginx -t
# → => SUCCESS: configuration file /etc/nginx/nginx.conf test is successful

docker run -d --name my_immutable_nginx -p 80:80 custom-nginx:1.0.0
# → 5a4b3c2d1e0f...

docker inspect --format '{{.State.Health.Status}}' my_immutable_nginx
# → healthy
```

---

### Сценарий 5: Zero-Downtime Reload и ротация логов без рестарта контейнера

Обновление конфигурационных файлов без пересоздания контейнера и без сброса активных клиентских TCP-сессий.

**1. Проверка синтаксиса перед применением:**
```bash
# Валидация измененного локального файла перед копированием
docker run --rm -v $(pwd)/nginx.conf:/etc/nginx/nginx.conf:ro nginx:1.27-alpine nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

**2. Доставка конфигурации и выполнение graceful reload:**
```bash
# Копирование файла в работающий контейнер (если не используется bind mount)
docker cp nginx.conf production_proxy:/etc/nginx/nginx.conf

# Обязательная проверка синтаксиса внутри контейнера
docker exec production_proxy nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Отправка сигнала SIGHUP мастер-процессу
docker exec production_proxy nginx -s reload
# → 2026/10/17 15:10:00 [notice] 1#1: signal 1 (SIGHUP) received, reconfiguring
# → 2026/10/17 15:10:00 [notice] 1#1: start worker processes
# → 2026/10/17 15:10:00 [notice] 1#1: gracefully shutting down old worker processes
```

**3. Ротация логов на хосте без перезапуска:**
```bash
# Переименование текущего лога на хосте (если логи пишутся в volume)
mv /var/log/nginx/access.log /var/log/nginx/access.log.1

# Отправка сигнала reopen (SIGUSR1) мастеру Nginx
docker exec production_proxy nginx -s reopen
# → 2026/10/17 15:10:05 [notice] 1#1: signal 10 (SIGUSR1) received, reopening logs
```

---

### Сценарий 6: Мониторинг и экспорт метрик в Prometheus (Sidecar)

Организация сбора метрик Nginx через модуль `stub_status` и официальный экспортер `nginx-prometheus-exporter` в рамках единого стека Docker Compose.

**1. Конфигурация Nginx для отдачи статуса (`nginx.conf`):**
```nginx
server {
    listen 8081;
    server_name 127.0.0.1 localhost;

    location /stub_status {
        stub_status;
        access_log off;
        allow 127.0.0.1;
        allow 172.16.0.0/12;  # Диапазон сетей Docker bridge
        deny all;
    }
}
```

**2. Файл развертывания со скрейпером метрик (`docker-compose.yml`):**
```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    container_name: web_server
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - monitor_net

  nginx_exporter:
    image: nginx/nginx-prometheus-exporter:1.4.1
    container_name: nginx_exporter
    restart: unless-stopped
    command:
      - -nginx.scrape-uri=http://web_server:8081/stub_status
      - -web.telemetry-path=/metrics
    ports:
      - "9113:9113"
    depends_on:
      - nginx
    networks:
      - monitor_net

networks:
  monitor_net:
    driver: bridge
```

**3. Валидация сбора метрик:**
```bash
docker compose up -d
# → ✔ Container web_server       Started
# → ✔ Container nginx_exporter   Started

curl -s http://localhost:9113/metrics | grep -E '^nginx_up|^nginx_http_requests_total'
# → nginx_http_requests_total 12
# → nginx_up 1
```

---

### Сценарий 7: Интеграция с Certbot для автоматического обновления TLS-сертификатов

Автоматизация выпуска и перевыпуска Let's Encrypt сертификатов с использованием общего тома (`webroot challenge`) и планового reload Nginx.

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    container_name: nginx_ssl
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - certbot_webroot:/var/www/certbot:ro
      - certbot_certs:/etc/letsencrypt:ro
    # Фоновый цикл проверки и применения обновленных сертификатов раз в 12 часов
    command: >
      /bin/sh -c '
        while :; do
          sleep 12h & wait $${!};
          nginx -t && nginx -s reload;
        done &
        nginx -g "daemon off;"
      '

  certbot:
    image: certbot/certbot:v3.1.0
    container_name: certbot_client
    restart: unless-stopped
    volumes:
      - certbot_webroot:/var/www/certbot:rw
      - certbot_certs:/etc/letsencrypt:rw
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew --webroot -w /var/www/certbot --quiet; sleep 12h & wait $${!}; done;'"

volumes:
  certbot_webroot:
  certbot_certs:
```

> Детальные правила выпуска сертификатов, синтаксис TLS-директив и безопасность cipher suites описаны в [Настройка Let's Encrypt с Nginx](nginx_with_letsencrypt.md).

---

## Операции и команды

| Команда | Назначение | Ожидаемый результат / Контекст |
| :--- | :--- | :--- |
| `docker compose up -d` | Запуск сервиса Nginx в фоне | Запуск контейнеров согласно спецификации Compose |
| `docker exec -it <name> nginx -t` | Проверка синтаксиса конфигурации | `configuration file ... test is successful` |
| `docker exec -it <name> nginx -T` | Дамп полной конфигурации (включая все include) | Вывод единого файла со всеми подключенными контекстами |
| `docker exec -it <name> nginx -s reload` | Плавная перезагрузка конфигурации | Применение изменений без разрыва активных соединений |
| `docker exec -it <name> nginx -s reopen` | Переоткрытие файлов журналов | Переоткрытие дескрипторов при ротации логов |
| `docker kill --signal=SIGQUIT <name>` | Инициализация Graceful Shutdown вручную | Завершение работы воркеров после доработки запросов |
| `docker inspect <name> --format '{{.State.OOMKilled}}'` | Проверка аварийного завершения по памяти | `true` при срабатывании cgroups OOM Killer |
| `docker stats <name> --no-stream` | Мгновенный срез утилизации CPU и RAM | Вывод метрик потребления ресурсов контейнером |
| `docker logs --tail 100 -f <name>` | Потоковый просмотр журналов доступа и ошибок | Непрерывный мониторинг access и error логов |

---

## Устранение неполадок

### 1. Контейнер мгновенно завершается с кодом 0 (`exited with code 0`)

- **Симптомы:** После выполнения `docker run` или `docker compose up` контейнер сразу останавливается. Команда `docker ps -a` показывает статус `Exited (0)`.
- **Причина:** В конфигурации Nginx отсутствует директива `daemon off;` либо была переопределена команда запуска (`command: nginx`) без передачи флага foreground. Мастер-процесс форкнулся в фон, а процесс PID 1 завершил выполнение.
- **Диагностика:**
  ```bash
  docker inspect <container_id> --format '{{.Config.Cmd}}'
  # → [nginx]   <-- Ошибка: нет аргументов -g daemon off;
  ```
- **Решение:** Не переопределяйте стандартную `ENTRYPOINT` и `CMD` официального образа. Если команда задается явно, обязательно укажите foreground-режим:
  ```yaml
  command: ["nginx", "-g", "daemon off;"]
  ```

---

### 2. Ошибка `502 Bad Gateway` после перезапуска или пересоздания upstream-контейнеров

- **Симптомы:** При деплое новой версии бэкенда Nginx возвращает клиентам `502 Bad Gateway`. В `error.log` появляется запись `connect() failed (111: Connection refused)` или `(113: No route to host)`.
- **Причина:** Nginx разрешил DNS-имя контейнера один раз при старте. При пересоздании контейнера бэкенда Docker выделил ему новый IP-адрес, но Nginx продолжает слать запросы на старый адрес.
- **Диагностика:**
  ```bash
  docker exec -it <nginx_container> ping -c 1 backend_host
  # Проверьте сопоставление IP из ping с реальным IP:
  docker inspect <backend_container> --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
  ```
- **Решение:** Настройте директиву `resolver` и передавайте адрес проксирования через переменную:
  ```nginx
  resolver 127.0.0.11 valid=10s ipv6=off;
  set $target_backend "http://backend_host:8080";
  proxy_pass $target_backend;
  ```

---

### 3. Ошибка `nginx: [emerg] bind() to 0.0.0.0:80 failed (13: Permission denied)`

- **Симптомы:** Контейнер падает при старте, в логах фиксируется ошибка отказа в доступе к порту 80.
- **Причина:** Контейнер запущен от непривилегированного пользователя (например, `user: "101:101"`), а в конфигурации Nginx указан порт `< 1024` без наличия capability `CAP_NET_BIND_SERVICE`.
- **Диагностика:**
  ```bash
  docker logs <container_id>
  # → nginx: [emerg] bind() to 0.0.0.0:80 failed (13: Permission denied)
  ```
- **Решение:** 
  1. Переведите сервер на порт выше 1024 (например, `listen 8080;`) и пробросьте его наружу: `- "80:8080"`.
  2. Либо добавьте контейнеру необходимую capability в Compose:
     ```yaml
     cap_add:
       - NET_BIND_SERVICE
     ```

---

### 4. Ошибка `nginx: [emerg] open() "/var/run/nginx.pid" failed (13: Permission denied)`

- **Симптомы:** Падение Nginx при попытке запуска стандартного образа `nginx:alpine` с флагом `read_only: true` или под пользователем `101:101`.
- **Причина:** Каталоги `/var/run/` и `/var/cache/nginx/` в стандартном образе принадлежат пользователю `root`.
- **Диагностика:**
  ```bash
  docker logs <container_id>
  # → nginx: [emerg] mkdir() "/var/cache/nginx/client_temp" failed (13: Permission denied)
  ```
- **Решение:** Используйте официальный образ `nginxinc/nginx-unprivileged:alpine` либо переопределите пути во временную файловую систему (`tmpfs`):
  ```nginx
  pid /tmp/nginx.pid;
  client_body_temp_path /tmp/client_temp;
  ```
  И смонтируйте в Compose:
  ```yaml
  tmpfs:
    - /tmp:rw,noexec,nosuid
  ```

---

### 5. `envsubst` затирает переменные `$host`, `$uri`, `$proxy_add_x_forwarded_for`

- **Симптомы:** После генерации конфига из шаблона `/etc/nginx/templates/*.template` заголовки `proxy_set_header Host` оказываются пустыми, запросы проксируются некорректно.
- **Причина:** Утилита `envsubst` без аргументов считает любые конструкции со знаком `$` переменными окружения хоста и заменяет отсутствующие переменные пустыми строками.
- **Диагностика:**
  ```bash
  docker exec <container_id> grep "proxy_set_header Host" /etc/nginx/conf.d/default.conf
  # → proxy_set_header Host ;   <-- Значение стёрто
  ```
- **Решение:** Обязательно объявляйте переменную `NGINX_ENVSUBST_FILTER`, перечисляя только те переменные, которые реально должны быть заменены:
  ```yaml
  environment:
    - BACKEND_HOST=app_service
    - NGINX_ENVSUBST_FILTER=BACKEND_HOST
  ```

---

### 6. Контейнер завершается с кодом 137 (OOM Killer)

- **Симптомы:** Контейнер Nginx периодически аварийно завершается без записи критических ошибок в `error.log`.
- **Причина:** Потребление памяти превысило лимит, заданный в `mem_limit` (cgroups v1/v2). Воркеры Nginx аллоцировали память под большие клиентские буферы (`client_body_buffer_size`, `proxy_buffers`) или кэш.
- **Диагностика:**
  ```bash
  docker inspect <container_id> --format '{{.State.OOMKilled}}'
  # → true
  dmesg -T | grep -i oom
  # → Task in /docker/... killed as a result of limit of /docker/...
  ```
- **Решение:**
  1. Снизьте размеры буферов в `nginx.conf`:
     ```nginx
     client_body_buffer_size 128k;
     proxy_buffers 8 16k;
     proxy_buffer_size 16k;
     ```
  2. Увеличьте лимит оперативной памяти в манифесте Compose до реалистичных значений (минимум 256–512M для средних нагрузок).

---

### 7. Обрыв активных соединений при `docker stop`

- **Симптомы:** При перезапуске или остановке Nginx клиенты получают ошибки соединения `ECONNRESET` или `Broken pipe`.
- **Причина:** Docker по умолчанию отправляет сигнал `SIGTERM` вместо `SIGQUIT`, либо таймаут остановки (10с) истекает раньше, чем завершаются долгие клиентские запросы.
- **Диагностика:**
  ```bash
  docker inspect <container_id> --format '{{.Config.StopSignal}}'
  ```
- **Решение:** Установите `stop_signal` в `SIGQUIT` и увеличьте время ожидания:
  ```yaml
  stop_signal: SIGQUIT
  stop_grace_period: 45s
  ```

---

## Лучшие практики

1. **Неизменяемость образов (Immutable Infrastructure):**
   - Собирайте образы с готовыми конфигурационными файлами в CI/CD пайплайнах.
   - Избегайте ручного редактирования файлов внутри контейнера через `docker exec`.
   - Включайте проверку `RUN nginx -t` в Dockerfile для блокировки сборки битых конфигураций.
2. **Безопасность (Hardening):**
   - Используйте специализированные образы `nginxinc/nginx-unprivileged`.
   - Монтируйте корневую файловую систему в режиме только для чтения (`read_only: true`).
   - Сбрасывайте все неиспользуемые привилегии ядра через `cap_drop: [ALL]`.
   - Не используйте тег `:latest`; всегда фиксируйте точные версии (например, `nginx:1.27.4-alpine`).
3. **Надежность и Service Discovery:**
   - Для любых динамических бэкендов в Docker-сетях всегда указывайте директиву `resolver 127.0.0.11 ipv6=off valid=10s;` и передавайте upstream через промежуточную переменную.
   - Настраивайте `HEALTHCHECK` с проверкой легковесного эндпоинта (`/healthz`), возвращающего статус `200 OK` без обращения к бэкендам.
   - Задавайте `STOPSIGNAL SIGQUIT` и увеличенный `stop_grace_period` для предотвращения обрыва активных соединений.
4. **Эксплуатация и наблюдаемость (Observability):**
   - Выводите журналы доступа и ошибок в `stdout`/`stderr` в формате JSON для централизованной агрегации.
   - Ограничивайте размер файлов журналов на уровне Docker демона (`max-size`, `max-file`).
   - Используйте отдельный sidecar-контейнер `nginx-prometheus-exporter` для съёма метрик со страницы `stub_status`.
5. **Очистка окружения (Cleanup):**
   - При выводе хоста из эксплуатации или ротации стека выполняйте удаление неиспользуемых томов и анонимных сетей:
     ```bash
     docker compose down -v --remove-orphans
     ```

---

## Дополнительная информация

### Связанные документы

- **[Nginx: развертывание SPA и шлюз API](nginx_spa_and_api_gateway.md)** — контейнеризация SPA с многоэтапной сборкой и проксированием API.
- **[Nginx: шлюз централизованной аутентификации (Forward Auth / SSO)](nginx_forward_auth_sso_gateway.md)** — авторизация внутренних сервисов через OAuth2-Proxy в контейнерах.
- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — глубокая диагностика сетевого стека, epoll, дампов памяти и системных ошибок.
- **[Настройка Let's Encrypt с Nginx](nginx_with_letsencrypt.md)** — автоматизация обновления сертификатов через ACME/Certbot в контейнерах.
- **[Nginx как reverse proxy для Grafana](nginx_as_reverse_proxy_for_grafana.md)** — пример рабочего прокси-стека с WebSocket и буферизацией.
- **[Веб-серверы и reverse proxy в Docker](../../../Docker/Dockerfile/Docker_best_practices/web_servers.md)** — сравнительный анализ и базовые практики контейнеризации веб-серверов.
- **[Управление томами Docker](../../../Docker/Docker_fs/docker_volumes.md)** — постоянное хранилище и монтирование данных в контейнеры.
- **[Управление ротацией логов Docker](../../../Docker/Docker_logs/docker_log_rotation.md)** — настройка логирующих драйверов и предотвращение переполнения диска.
- **[Безопасность контейнеров Docker](../../../Docker/Docker_security/overview.md)** — изоляция пространств имён, cgroups и управление capabilities.