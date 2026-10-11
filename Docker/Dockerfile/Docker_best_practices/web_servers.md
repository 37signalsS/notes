# Веб-серверы и reverse proxy в Docker

**Актуально для:** nginx 1.30+, Traefik 3.7, HAProxy 3.4, Caddy 2.11, Docker 29.x

## Определения

- **Reverse proxy:** Сервер, принимающий клиентские запросы и пересылающий их backend-приложениям. В Docker — стандартный entry point: терминирует TLS, маршрутизирует по доменам/путям, добавляет заголовки.
- **Load balancer (LB):** Reverse proxy с распределением нагрузки между несколькими upstream-инстансами (round-robin, least_conn, hash).
- **upstream:** Группа backend-серверов в конфигурации nginx/HAProxy, к которым проксируются запросы.
- **worker_processes:** Число воркер-процессов nginx. `auto` = число CPU ядер; в контейнере с лимитом CPU `auto` видит ядра хоста, а не лимит — задавайте явно.
- **resolver:** Директива nginx для DNS-резолвинга upstream-имён в runtime. Без неё nginx резолвит имена только при старте — IP-изменение контейнера не подхватывается.
- **Labels-based config (Traefik):** Конфигурация Traefik через Docker-метки контейнеров (`traefik.http.routers...`) — автоматическое обнаружение сервисов без правки конфигов.
- **Caddyfile:** Декларативный конфиг Caddy. Автоматический HTTPS (Let's Encrypt) из коробки — минимальная конфигурация для TLS.
- **envsubst:** Утилита для подстановки переменных окружения в шаблоны конфигов (nginx). Позволяет генерировать конфиг при старте контейнера.
- **Zero-downtime reload:** Перезагрузка конфигурации без разрыва соединений: `nginx -s reload` (новые воркеры плавно заменяют старые), `haproxy -sf` (socket transfer).

## Базовые концепции

### Предпосылки

- **Docker Engine 29.x**; для multi-arch сборок — Buildx.
- Понимание сетей Docker: контейнеры в одной сети резолвятся по имени сервиса.
- Знание проблемы DNS в nginx: [Troubleshooting](../../Docker_network/troubleshooting/).

### Выбор веб-сервера (Сравнение 2026)

| Сервер | Сильная сторона | Конфигурация | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **nginx** | Производительность, гибкость, static-файлы | `/etc/nginx/conf.d/*.conf` | Стандарт де-факто, static, API gateway |
| **Traefik** | Автоконфигурация из меток/Ingress | labels, Ingress, file | Docker/K8s без ручных конфигов |
| **HAProxy** | TCP/L4 балансировка, stats page | `haproxy.cfg` | TCP-сервисы, точный LB, финансы |
| **Caddy** | Автоматический HTTPS | Caddyfile | Быстрый HTTPS без сертификатной инфраструктуры |
| **Envoy** | Service mesh, L7 observability | YAML | Service mesh (Istio), gRPC |

Подробное сравнение серверов: [WebServers overview](../../../WebServers/), [HAProxy overview](../../../WebServers/haproxy_overview.md).

### Официальные образы

| Сервер | Образ | Конфиг | Порт |
| :--- | :--- | :--- | :--- |
| nginx | `nginx:1.30-alpine` | `/etc/nginx/conf.d/default.conf` | 80, 443 |
| Traefik | `traefik:3.7` | CLI-флаги / файл / labels | 80, 443, 8080 (dashboard) |
| HAProxy | `haproxytech/haproxy:3.4-alpine` | `/usr/local/etc/haproxy/haproxy.cfg` | 80, 8404 (stats) |
| Caddy | `caddy:2.11-alpine` | `/etc/caddy/Caddyfile` | 80, 443 |
| Envoy | `envoyproxy/envoy:v1.31-latest` | `/etc/envoy/envoy.yaml` | 80, 8001 (admin) |

### Конфигурация через volumes

Три способа (в порядке предпочтения):

1. **Bind mount конфига:** `-v ./nginx.conf:/etc/nginx/conf.d/default.conf:ro` — конфиг живёт в репозитории.
2. **Кастомный образ:** `COPY nginx.conf /etc/nginx/conf.d/` — конфиг зафиксирован в образе, воспроизводимость.
3. **Шаблонизация:** `envsubst` подставляет env-переменные при старте — для multi-окружений (dev/stage/prod).

### Reload без даунтайма

```bash
# nginx: плавная перезагрузка (новые воркеры берут новые соединения)
docker exec <nginx_container> nginx -s reload

# HAProxy: socket transfer (соединения не разрываются)
docker exec <haproxy_container> haproxy -f /usr/local/etc/haproxy/haproxy.cfg -sf $(pgrep haproxy)
```

**Валидация reload:**
```bash
# До reload
docker exec <nginx_container> nginx -T 2>&1 | grep -c "server_name"
# → 3

# Проверка синтаксиса перед reload (обязательно)
docker exec <nginx_container> nginx -t
# → syntax is ok
# → test is successful
```

### DNS-резолвинг в nginx

nginx резолвит `proxy_pass http://app:3000` **один раз при старте**. Если контейнер `app` пересоздался с новым IP — nginx продолжает слать запросы на старый IP.

**Решение — resolver + переменная:**

```nginx
resolver 127.0.0.11 valid=10s;  # Docker embedded DNS

location / {
    set $backend "http://app:3000";
    proxy_pass $backend;
}
```

### Логирование в stdout/stderr

Официальный образ nginx уже симлинкует access/error логи в `/dev/stdout` и `/dev/stderr`. Для кастомных образов:

```nginx
access_log /dev/stdout;
error_log /dev/stderr warn;
```

HAProxy: `log stdout format raw local0` — логи в stdout.

### Ресурсы и graceful shutdown

Для production-стека задавайте лимиты CPU/memory и политику завершения:

```yaml
services:
  nginx:
    image: nginx:1.30-alpine
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
    stop_grace_period: 30s
    stop_signal: SIGQUIT   # плавное завершение соединений
    tmpfs:
      - /var/cache/nginx
      - /var/run
    read_only: true
```

- **`stop_signal: SIGQUIT`** — nginx корректно закрывает соединения перед выходом; `SIGTERM` (по умолчанию) может оборвать активные запросы.
- **`stop_grace_period`** — должен превышать `keepalive_timeout` + `client_header_timeout` в конфиге.
- **`tmpfs`** — для кеша и `/var/run` (pid, sockets) при read-only FS.
- **`deploy.resources.limits`** — защита от OOM и noisy-neighbor.

### Операционный контекст (DevOps / SRE / Sysadmin)

#### SLI/SLO для web-тier

| SLI | Цель (SLO) | Как измерять |
| :--- | :--- | :--- |
| Доступность | 99.9% (43 мин простоя/месяц) | `up` из blackbox exporter |
| Latency p99 | < 250 мс | histogram `nginx_http_request_duration_seconds` |
| Error rate | < 0.1% | `rate(nginx_http_requests_total{status=~"5.."}[5m])` |
| Change failure rate | < 5% | CI/CD gates + reload failures |

#### MTTR и change failure rate

- **MTTR (Mean Time To Recover)** — автоматизируйте rollback: фиксируйте предыдущий конфиг в git, деплой через immutable artifact.
- **Change failure rate** — `nginx -t` в CI, canary deploy (Traefik weighted service / HAProxy backend с `weight`), observability на каждом релизе.

#### Supply chain security

- Пиньте образы по digest (`nginx@sha256:...`) или версии (`nginx:1.30-alpine`, не `nginx:latest`).
- Сканируйте образы: `trivy image nginx:1.30-alpine`, `grype nginx:1.30-alpine`.
- Минимальный базовый слой: Alpine для nginx/Caddy, Debian-slim для Traefik.
- SBOM: `syft nginx:1.30-alpine -o spdx-json > sbom.json`.

#### CI/CD gates

```yaml
# Пример: GitHub Actions
- name: Validate nginx config
  run: docker run --rm -v ${{ github.workspace }}/nginx.conf:/etc/nginx/nginx.conf:ro nginx:1.30-alpine nginx -t
- name: Scan image
  run: trivy image --severity HIGH,CRITICAL --exit-code 1 nginx:1.30-alpine
```

#### Health check orchestration

- `depends_on` с `condition: service_healthy` в Compose — старт backend'ов до proxy.
- Backend health: `httpchk` в HAProxy, `proxy_next_upstream` в nginx.
- Circuit breaker: Traefik `forwardedHeaders.trustedIPs` + middleware.

#### Высокая доступность прокси

Для самого proxy (не backend'ов):

- **keepalived + VRRP:** два инстанса nginx/HAProxy с виртуальным IP.
- **Структура:**
  ```
  [Client] → [VIP:80/443] → [nginx-01] ┐
                                        ├→ [app-backend]
                         [nginx-02] ┘
  ```
- Конфиг sync: shared NFS/GlusterFS для `/etc/nginx/conf.d/` или GitOps push.

#### DR drill для web-тier

1. Остановите primary proxy-контейнер.
2. Проверьте переключение на secondary (VRRP) или поднятие нового контейнера.
3. Измерьте RTO (цель < 30 сек для stateless proxy).
4. Проверьте TLS-сертификаты на secondary (ACME/Let's Encrypt автоматически выдаёт повторно).

#### Алертинг

| Алерт | Порог | Действие |
| :--- | :--- | :--- |
| `up{job="nginx"} == 0` | > 30 сек | PagerDuty / Opsgenie |
| `rate(nginx_http_requests_total{status=~"5.."}[5m]) > 0.05` | > 5% | Проверить backend |
| `nginx_http_request_duration_seconds{quantile="0.99"} > 0.5` | > 500 мс | Масштабирование backend'ов |
| `haproxy_backend_active_servers < 2` | < min backup | Failover |

## Практические сценарии

### Сценарий 1: Кастомный nginx (Dockerfile)

```dockerfile
# syntax=docker/dockerfile:1
FROM nginx:1.30-alpine

# Конфиг сайта
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static-файлы (для SPA/статики)
COPY --from=frontend:latest /app/dist /usr/share/nginx/html

# Healthcheck: curl есть в alpine-образе nginx
HEALTHCHECK --interval=30s --timeout=3s \
    CMD wget -qO- http://localhost/health || exit 1

EXPOSE 80
```

`nginx.conf` (reverse proxy к приложению):

```nginx
server {
    listen 80;
    server_name _;

    # Gzip
    gzip on;
    gzip_types application/json text/css application/javascript;

    # Static
    location /static/ {
        alias /usr/share/nginx/html/static/;
        expires 30d;
    }

    # Proxy к приложению
    location / {
        proxy_pass http://app:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Валидация:**
```bash
docker build -t my-nginx:latest .
docker run -d --name web -p 8080:80 my-nginx:latest
curl -s http://localhost:8080/health
# → OK
docker exec web nginx -t
# → syntax is ok / test is successful
```

### Сценарий 2: nginx как reverse proxy (Compose)

```yaml
services:
  app:
    image: my-app:latest
    expose:
      - "3000"
    # Нет ports: — приложение недоступно напрямую

  nginx:
    image: nginx:1.30-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      app:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost/health"]
      interval: 30s
      timeout: 3s
      retries: 3
```

### Сценарий 3: Traefik (автоконфигурация через labels)

Traefik читает метки контейнеров и автоматически создаёт маршрутизаторы:

```yaml
services:
  traefik:
    image: traefik:3.7
    command:
      - "--api.dashboard=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik_certs:/letsencrypt

  whoami:
    image: traefik/whoami
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.whoami.rule=Host(`whoami.example.com`)"
      - "traefik.http.routers.whoami.entrypoints=websecure"
      - "traefik.http.routers.whoami.tls.certresolver=letsencrypt"

volumes:
  traefik_certs:
```

**Валидация:**
```bash
docker compose up -d
curl -H "Host: whoami.example.com" http://localhost/health
# → {"hostname":"...","ip":"..."}

# Dashboard
curl -s http://localhost:8080/api/overview | head
# → JSON с маршрутизаторами
```

### Сценарий 4: HAProxy (TCP/HTTP балансировка)

```yaml
services:
  haproxy:
    image: haproxytech/haproxy:3.4-alpine
    ports:
      - "80:80"
      - "8404:8404"   # stats page
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro

  app1:
    image: my-app:latest
  app2:
    image: my-app:latest
```

`haproxy.cfg`:

```
global
    log stdout format raw local0

defaults
    mode http
    timeout connect 5s
    timeout client 30s
    timeout server 30s

frontend http
    bind *:80
    default_backend app_servers

backend app_servers
    balance roundrobin
    option httpchk GET /health
    server app1 app1:3000 check
    server app2 app2:3000 check

listen stats
    bind *:8404
    stats enable
    stats uri /
```

**Валидация:**
```bash
docker compose up -d
for i in $(seq 1 4); do curl -s http://localhost/hostname; done
# → app1-ip
# → app2-ip  (чередование round-robin)

# Stats page
curl -s http://localhost:8404 | grep -o "app[12]"
```

### Сценарий 5: Caddy (автоматический HTTPS)

```yaml
services:
  caddy:
    image: caddy:2.11-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

  app:
    image: my-app:latest
    expose:
      - "3000"

volumes:
  caddy_data:
  caddy_config:
```

`Caddyfile`:

```
example.com {
    reverse_proxy app:3000
}
```

Caddy автоматически получает и обновляет Let's Encrypt сертификаты. Дополнительная конфигурация не требуется.

### Сценарий 6: Read-only FS + non-root

nginx в read-only режиме требует tmpfs для кеша и временных файлов:

```yaml
services:
  nginx:
    image: nginx:1.30-alpine
    read_only: true
    tmpfs:
      - /var/cache/nginx
      - /var/run
      - /tmp
    ports:
      - "80:80"
    # Non-root: слушать 8080 вместо 80 или добавить NET_BIND_SERVICE
    command: ["/bin/sh", "-c", "sed -i 's/listen       80;/listen       8080;/' /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
```

**Альтернатива:** запуск от non-root с портом >1024 — безопаснее, чем `cap_add: NET_BIND_SERVICE`.

## Безопасность и верификация

### Аудит и проверка

1. **Синтаксис перед reload:** `nginx -t` / `haproxy -c -f config` — обязательно в CI.
2. **Non-root:** nginx master по умолчанию от root (для порта 80). Для production: порт 8080 + `USER nginx` или `cap_drop: ALL` + `cap_add: NET_BIND_SERVICE`.
3. **Read-only FS:** `read_only: true` + tmpfs — блокирует запись в ФС.
4. **Секреты:** TLS-ключи в named volume или secrets, не в образе.
5. **Версии:** пиньте образы (`nginx:1.30-alpine`, не `nginx:latest`).
6. **Supply chain security:** сканируйте уязвимости (`trivy image`, `grype`), проверяйте digests (`nginx@sha256:...`), собирайте SBOM (`syft`).
7. **CI/CD gates:** `nginx -t` / `haproxy -c` / `caddy validate` — обязательны в пайплайне; блокируйте мерж при ошибке синтаксиса.

### Заголовки безопасности

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'" always;
```

## Типичные ошибки и их решение

### Ошибка 1: nginx не подхватывает новый IP контейнера

**Причина:** nginx резолвит upstream-имя один раз при старте.

```nginx
# Решение: resolver + переменная
resolver 127.0.0.11 valid=10s;
location / {
    set $backend "http://app:3000";
    proxy_pass $backend;
}
```

### Ошибка 2: "worker_processes auto" игнорирует лимит CPU

**Причина:** nginx видит ядра хоста, а не cgroup-лимит контейнера.

```nginx
# Решение: явное значение под лимит
worker_processes 2;  # при --cpus=2
```

### Ошибка 3: 502 Bad Gateway

**Причина:** Backend недоступен (не запущен, не в сети, не слушает порт) или таймаут.

```bash
# Диагностика
docker exec <nginx_container> wget -qO- http://app:3000/health
# → Connection refused → backend не слушает

# Проверка сети
docker network inspect <network> | grep -A2 Containers
```

### Ошибка 4: Reload ломает конфигурацию

**Причина:** Синтаксическая ошибка в конфиге; `nginx -s reload` применяет только валидный конфиг, но `docker exec` без проверки рискованен.

```bash
# Всегда проверяйте перед reload
docker exec <nginx_container> nginx -t && docker exec <nginx_container> nginx -s reload
```

### Ошибка 5: Traefik не видит контейнеры

**Причина:** `exposedbydefault=false` и нет метки `traefik.enable=true`, или нет доступа к docker.sock.

```yaml
# Проверка
docker exec traefik traefik healthcheck
# → OK

# Метки на контейнере
docker inspect <app_container> --format='{{json .Config.Labels}}'
```

### Ошибка 6: Caddy не получает сертификат

**Причина:** Домен не указывает на сервер, или порты 80/443 закрыты (ACME challenge).

```bash
# Диагностика
docker logs caddy
# → acme: error: 403 ... (DNS не указывает на сервер)

# Проверка
dig +short example.com
# → IP хоста
```

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Entry point** | Reverse proxy единственная точка входа | TLS, заголовки, маршрутизация |
| **Конфиг** | Bind mount `:ro` или COPY в образ | Воспроизводимость |
| **Reload** | `nginx -t` перед `nginx -s reload` | Без даунтайма и без ошибок |
| **DNS** | `resolver` + переменная для upstream | Пересоздание контейнеров |
| **Логи** | stdout/stderr | `docker logs` и сборщики |
| **Healthcheck** | `wget`/`curl` на `/health` | Зависимость от backend |
| **Non-root** | Порт 8080 + `USER nginx` | Меньше привилегий |
| **Read-only** | `read_only: true` + tmpfs | Защита ФС |
| **Traefik** | labels-based config | Автоконфигурация |
| **Caddy** | Автоматический HTTPS | Минимум инфраструктуры |
| **Образы** | Пин по версии/digest, Trivy/Grype scan | Supply chain security |
| **CI/CD** | `nginx -t` / `haproxy -c` / `caddy validate` | Gate перед деплоем |
| **Graceful shutdown** | `stop_signal: SIGQUIT`, `stop_grace_period` | Zero data loss |
| **Ресурсы** | `deploy.resources.limits` cpus/memory | OOM protection |
| **HA** | keepalived + VRRP для proxy | Отказоустойчивость самого proxy |
| **DR drill** | Регулярное тестирование failover | RTO < 30 сек |
| **SLI/SLO** | Availability 99.9%, p99 latency, error rate | Observability |

### Чек-лист перед деплоем

- [ ] Конфиг проверен (`nginx -t` / `haproxy -c` / `caddy validate`)
- [ ] Healthcheck настроен
- [ ] Backend недоступен напрямую извне (только через proxy)
- [ ] Логи в stdout/stderr
- [ ] Заголовки безопасности добавлены
- [ ] TLS терминируется на proxy (не на приложении)
- [ ] `worker_processes` соответствует лимиту CPU
- [ ] Read-only FS + tmpfs (production)
- [ ] Образ зафиксирован по версии/digest
- [ ] Образ отсканирован (`trivy image` / `grype`)
- [ ] `stop_signal: SIGQUIT` и `stop_grace_period` заданы
- [ ] `deploy.resources.limits` (cpus, memory) заданы
- [ ] HA proxy (keepalived/VRRP) протестирован
- [ ] DR drill пройден (RTO измерен)
- [ ] SLI/SLO метрики экспортированы (Prometheus)
- [ ] Алерты настроены (availability, latency, error rate)

## Смотрите также

- **[Nginx](../../../WebServers/Nginx/)** — конфигурация, тюнинг, сценарии.
- **[HAProxy overview](../../../WebServers/haproxy_overview.md)** — балансировка, stats.
- **[Traefik](../../../WebServers/Traefik/)** — автоконфигурация, middleware.
- **[Apache](../../../WebServers/Apache/)** — mod_proxy, PHP-FPM.
- **[Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md)** — nginx + php-fpm в одном контейнере.
- **[Frontend best practices](./frontend.md)** — сборка SPA для nginx.
- **[Docker network troubleshooting](../../Docker_network/troubleshooting/)** — DNS, сети.
- **[Stateful-сервисы](./stateful_services.md)** — БД за reverse proxy.
- **[Nginx в Docker: эксплуатация](../../../WebServers/Nginx/Scenarios/nginx_in_docker.md)** — PID 1, graceful shutdown, healthcheck, immutable образ.
