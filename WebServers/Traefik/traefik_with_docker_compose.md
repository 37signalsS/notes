# Traefik с Docker Compose: развертывание, маршрутизация, сети

**Актуально для:** Traefik v3.x / Docker Compose v2.x (Docker Engine 29.x)

## Определения

**Docker Compose** — инструмент декларативного описания и управления multi-container приложениями на одном хосте (спецификация Compose v2), координирующий жизненный цикл сервисов, виртуальных сетей и томов.

**Docker provider** — встроенный в Traefik провайдер динамической конфигурации, опрашивающий события Docker Engine через API сокета (`/events`, `start`, `die`, `health_status`) и генерирующий роутеры, middleware и сервисы на лету.

**Метки (Labels)** — атрибуты контейнера в формате ключ-значение, через которые Traefik считывает правила маршрутизации (Host, Path, TLS, балансировку, middleware) без правки конфигурационных файлов и перезапуска proxy.

**Docker socket proxy** — защитный шлюз для Unix-сокета Docker демона (`/var/run/docker.sock`), ограничивающий API только безопасными операциями чтения (`CONTAINERS`, `NETWORKS`, `SERVICES`) и предотвращающий повышение привилегий до root хоста.

**Bridge network** — изолированный программный L2/L3 сетевой сегмент хоста со встроенным DNS-сервером Docker; обеспечивает изоляцию трафика и связь Traefik с бэкендами по именам сервисов.

**ACME storage (`acme.json`)** — локальный файл хранения приватных ключей и TLS-сертификатов Let's Encrypt; требует строгих прав доступа (`0600`).

**Active health check** — периодический фоновый опрос бэкендов со стороны Traefik (`loadbalancer.healthcheck.*`) для исключения сбойных контейнеров из пула балансировки до возврата ошибки клиенту.

## Базовые концепции

### Архитектура docker-provider

Traefik функционирует как event-driven edge router. В отличие от традиционных веб-серверов (Nginx, Apache), требующих генерации статических конфигураций и reload-сигналов, Traefik подписывается на поток событий Docker Engine:

```
+-------------------------------------------------------------------------+
|                              Docker Engine                              |
|                                                                         |
|  +-----------------------+              +----------------------------+  |
|  |     tecnativa/        |  UNIX Sock   |        traefik:v3.x        |  |
|  |  docker-socket-proxy  |<=============| (providers.docker.endpoint |  |
|  +-----------------------+              |   =tcp://socket-proxy:2375)|  |
|             ^                           +----------------------------+  |
|             | GET /events                             |                 |
|             | GET /containers/json                    |                 |
|  +-----------------------+                            | (proxy-tier)    |
|  |     Docker Daemon     |                            |                 |
|  +-----------------------+                            v                 |
|             |                             +-----------------------+     |
|             +-- events: start/die ------->|   App Container (x3)  |     |
|                                           |  Round-Robin Balance  |     |
|                                           +-----------------------+     |
+-------------------------------------------------------------------------+
```

1. **Подключение к API демона:** Traefik подключается либо напрямую к Unix-сокету (`unix:///var/run/docker.sock`), либо через TCP-прокси (`tcp://socket-proxy:2375`).
2. **Обработка событий:** При запуске (`start`), остановке (`die`) или изменении состояния (`health_status`) контейнера Traefik считывает его labels, сеть и IP-адрес.
3. **Безопасность по умолчанию:** Опция `exposedByDefault: false` обязательна для production. При ее включении Traefik игнорирует любые контейнеры, пока на них явно не задана метка `traefik.enable=true`. Это исключает непреднамеренную публикацию баз данных, redis или служебных утилит.

### Иерархия меток в Traefik v3

В Traefik v3 синтаксис меток унифицирован и строго структурирован:

```ini
# Активация обработки контейнера
traefik.enable=true

# Сеть для взаимодействия (критично при подключении к нескольким сетям)
traefik.docker.network=proxy-tier

# Роутер (входная точка и правила матчинга)
traefik.http.routers.<router-name>.rule=Host(`app.example.com`) && PathPrefix(`/api`)
traefik.http.routers.<router-name>.entrypoints=websecure
traefik.http.routers.<router-name>.service=<service-name>
traefik.http.routers.<router-name>.middlewares=<mw1>@docker,<mw2>@docker

# TLS и Let's Encrypt
traefik.http.routers.<router-name>.tls=true
traefik.http.routers.<router-name>.tls.certresolver=le

# Сервис и балансировка нагрузки
traefik.http.services.<service-name>.loadbalancer.server.port=8080
traefik.http.services.<service-name>.loadbalancer.server.scheme=http
traefik.http.services.<service-name>.loadbalancer.healthcheck.path=/healthz
traefik.http.services.<service-name>.loadbalancer.healthcheck.interval=10s
traefik.http.services.<service-name>.loadbalancer.healthcheck.timeout=3s

# Sticky sessions (привязка сессий по cookie)
traefik.http.services.<service-name>.loadbalancer.sticky.cookie=true
traefik.http.services.<service-name>.loadbalancer.sticky.cookie.name=lb_session
traefik.http.services.<service-name>.loadbalancer.sticky.cookie.secure=true
traefik.http.services.<service-name>.loadbalancer.sticky.cookie.httponly=true
```

Правила применения:
- Метки задаются в блоке `services.<service-name>.labels` в `compose.yaml`. При масштабировании (`--scale <service>=N`) все реплики наследуют одинаковые метки и автоматически объединяются Traefik в один upstream-сервис с балансировкой Round-Robin.
- Если контейнер слушает более одного порта (или в Dockerfile объявлено несколько `EXPOSE`), указание `loadbalancer.server.port` является **строго обязательным**. Без него Traefik выберет случайный порт или проигнорирует сервис.
- Префикс провайдера `@docker` при обращении к middleware необходим, если middleware объявлен в контексте Docker provider.

### Сетевая топология и изоляция

В промышленной эксплуатации на одном сервере используется многоконтурная сетевая модель:

1. **Внешняя публичная сеть (`proxy-tier`):**
   - Создается как глобальная bridge-сеть хоста (`docker network create proxy-tier`).
   - К ней подключены Traefik и публичные веб-интерфейсы приложений.
   - Никакие порты приложений не пробрасываются на хост через `ports:` (это предотвращает обход фильтрации Traefik).
2. **Внутренние изолированные сети (`backend-tier`):**
   - Создаются внутри каждого Compose-стека с флагом `internal: true`.
   - Доступны только веб-сервису и его хранилищам данных (PostgreSQL, Redis, RabbitMQ).
   - Traefik не имеет доступа в эту сеть.
3. **Разрешение адреса контейнера (Multi-Homed Issue):**
   - Если контейнер подключен одновременно к `proxy-tier` и `backend-tier`, у него появляется два IP-адреса.
   - Без явного указания `traefik.docker.network=proxy-tier` (или глобального параметра `providers.docker.network=proxy-tier`) Traefik может зарегистрировать IP-адрес из сети `backend-tier` и возвращать клиентам ошибку `502 Bad Gateway`.

### Безопасность сокета Docker

Прямой проброс `/var/run/docker.sock` в контейнер дает права, эквивалентные root-доступу на хосте (RCE в Traefik позволяет создать привилегированный контейнер с монтированием `/` хостовой ОС).

Для снижения рисков:
- В продакшене Traefik изолируется от сокета с помощью вспомогательного контейнера `tecnativa/docker-socket-proxy`.
- Прокси разрешает только безопасные запросы чтения API (`GET /v*/containers/*`, `GET /v*/networks/*`, `GET /v*/services/*`, `GET /v*/events`), блокируя любые `POST`, `DELETE` и команды создания контейнеров или изменения томов.

## Практические сценарии

### Сценарий 1: Инфраструктурный стек Traefik v3 с Docker Socket Proxy и Let's Encrypt

Развертывание Traefik в выделенном каталоге `/opt/infra/traefik/compose.yaml`. Маршрутизация HTTP с глобальным автоматическим редиректом на HTTPS, получение сертификатов Let's Encrypt по TLS-ALPN-01 challenge и безопасный доступ к сокету.

```yaml
# /opt/infra/traefik/compose.yaml
name: infra-traefik

networks:
  proxy-tier:
    name: proxy-tier
    driver: bridge
  socket-net:
    internal: true

volumes:
  traefik-certificates:

services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy:0.1.1
    restart: unless-stopped
    read_only: true
    environment:
      - CONTAINERS=1
      - NETWORKS=1
      - SERVICES=1
      - EVENTS=1
      - PING=1
      - VERSION=1
      - POST=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - socket-net

  traefik:
    image: traefik:v3.7
    restart: unless-stopped
    depends_on:
      - socket-proxy
    command:
      # Логирование
      - "--log.level=INFO"
      - "--accesslog=true"
      - "--accesslog.format=json"
      - "--accesslog.bufferingSize=100"
      # Встроенный healthcheck
      - "--ping=true"
      - "--ping.entrypoint=traefik"
      # Входные точки
      - "--entrypoints.traefik.address=:8080"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Глобальный редирект HTTP -> HTTPS на уровне entrypoint
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--entrypoints.web.http.redirections.entrypoint.permanent=true"
      # Провайдер Docker через Socket Proxy
      - "--providers.docker=true"
      - "--providers.docker.endpoint=tcp://socket-proxy:2375"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.network=proxy-tier"
      - "--providers.docker.watch=true"
      # Let's Encrypt сертификаты (TLS-ALPN-01)
      - "--certificatesresolvers.le.acme.tlschallenge=true"
      - "--certificatesresolvers.le.acme.email=admin@example.com"
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"
      # Dashboard (API)
      - "--api.dashboard=true"
    ports:
      - "80:80"
      - "443:443"
    networks:
      - proxy-tier
      - socket-net
    volumes:
      - traefik-certificates:/letsencrypt
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=proxy-tier"
      # Защита Dashboard через BasicAuth и HTTPS
      - "traefik.http.routers.dashboard.rule=Host(`traefik.example.com`)"
      - "traefik.http.routers.dashboard.entrypoints=websecure"
      - "traefik.http.routers.dashboard.service=api@internal"
      - "traefik.http.routers.dashboard.tls.certresolver=le"
      - "traefik.http.routers.dashboard.middlewares=admin-auth@docker"
      # admin / secretpass (пароль генерируется: htpasswd -nb admin secretpass)
      - "traefik.http.middlewares.admin-auth.basicauth.users=admin:$$apr1$$XQZg9q6J$$zC4ZgPZ3vE0EevZzKzY8H."
    healthcheck:
      test: ["CMD", "traefik", "healthcheck", "--ping"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
```

Запуск инфраструктурного стека:

```bash
docker network create proxy-tier
# → d8a1c97efb1234567890abcdef1234567890abcdef1234567890abcdef12345678

docker compose -f /opt/infra/traefik/compose.yaml up -d
# → [+] Running 3/3
#  ✔ Network infra-traefik_socket-net  Created
#  ✔ Container infra-traefik-socket-proxy-1  Started
#  ✔ Container infra-traefik-traefik-1       Started
```

### Сценарий 2: Подключение независимого Compose-стека приложения

Развертывание веб-приложения в отдельном каталоге `/opt/apps/my-app/compose.yaml`. Приложение подключается к существующей сети `proxy-tier` и закрытой сети базы данных.

```yaml
# /opt/apps/my-app/compose.yaml
name: my-app

networks:
  proxy-tier:
    external: true
  db-tier:
    internal: true

volumes:
  pgdata:

services:
  db:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: appdb
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - db-tier

  backend:
    image: traefik/whoami:latest
    restart: unless-stopped
    networks:
      - proxy-tier
      - db-tier
    # Прямых портов на хост нет: доступ только через Traefik
    labels:
      - "traefik.enable=true"
      # Обязательно указываем сеть маршрутизации при наличии нескольких сетей
      - "traefik.docker.network=proxy-tier"
      # Маршрутизатор HTTPS
      - "traefik.http.routers.myapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.myapp.entrypoints=websecure"
      - "traefik.http.routers.myapp.tls.certresolver=le"
      - "traefik.http.routers.myapp.service=myapp-svc"
      # Конфигурация сервиса и балансировщика
      - "traefik.http.services.myapp-svc.loadbalancer.server.port=80"
      # Активный healthcheck бэкенда
      - "traefik.http.services.myapp-svc.loadbalancer.healthcheck.path=/health"
      - "traefik.http.services.myapp-svc.loadbalancer.healthcheck.interval=5s"
      - "traefik.http.services.myapp-svc.loadbalancer.healthcheck.timeout=2s"
      # Sticky session cookie
      - "traefik.http.services.myapp-svc.loadbalancer.sticky.cookie=true"
      - "traefik.http.services.myapp-svc.loadbalancer.sticky.cookie.name=APP_STICKY"

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

Проверка публикации сервиса:

```bash
docker compose -f /opt/apps/my-app/compose.yaml up -d
# → [+] Running 3/3
#  ✔ Container my-app-db-1       Started
#  ✔ Container my-app-backend-1  Started

curl -I https://app.example.com
# → HTTP/2 200 
#   set-cookie: APP_STICKY=http://172.18.0.4:80; Path=/; HttpOnly; Secure
```

### Сценарий 3: Динамическое масштабирование и балансировка нагрузки

В отличие от ручной настройки `upstream` в Nginx, Traefik автоматически обнаруживает появление новых реплик контейнеров и добавляет их IP-адреса в пул балансировки без перезагрузки:

```bash
# Масштабирование сервиса до 3 реплик
docker compose -f /opt/apps/my-app/compose.yaml up -d --scale backend=3
# → [+] Running 3/3
#  ✔ Container my-app-backend-1  Running
#  ✔ Container my-app-backend-2  Started
#  ✔ Container my-app-backend-3  Started
```

Проверка распределения запросов по репликам:

```bash
for i in {1..4}; do curl -s -k https://app.example.com | grep "Hostname:"; done
# → Hostname: 9b2d86a11e01
#   Hostname: 4c3fa77b02c8
#   Hostname: e18bc32a90df
#   Hostname: 9b2d86a11e01
```

Если один из контейнеров выходит из строя (active healthcheck возвращает 5xx или не отвечает за 2s), Traefik автоматически исключает его адрес из пула до восстановления.

### Сценарий 4: Middleware-цепочка в метках (RateLimit, Security Headers, IPAllowList)

Создание цепочки промежуточного ПО для защиты API от DDoS, инъекций и несанкционированного доступа:

```yaml
services:
  api:
    image: my-api:v1.4
    networks:
      - proxy-tier
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=proxy-tier"
      # Ограничение частоты запросов: среднее 20 rps, burst до 50
      - "traefik.http.middlewares.api-ratelimit.ratelimit.average=20"
      - "traefik.http.middlewares.api-ratelimit.ratelimit.burst=50"
      - "traefik.http.middlewares.api-ratelimit.ratelimit.period=1s"
      # Ограничение по IP-адресам для служебных подсетей
      - "traefik.http.middlewares.office-only.ipallowlist.sourcerange=192.168.1.0/24, 10.0.0.0/8"
      # Заголовки безопасности (HSTS, Content-Type, X-Frame)
      - "traefik.http.middlewares.api-sec-headers.headers.stsseconds=31536000"
      - "traefik.http.middlewares.api-sec-headers.headers.stsincludesubdomains=true"
      - "traefik.http.middlewares.api-sec-headers.headers.stspreload=true"
      - "traefik.http.middlewares.api-sec-headers.headers.contenttypenosniff=true"
      - "traefik.http.middlewares.api-sec-headers.headers.customframeoptionsvalue=DENY"
      # Сжатие ответов (gzip, zstd)
      - "traefik.http.middlewares.api-compress.compress=true"
      # Связывание цепочки middleware с роутером
      - "traefik.http.routers.api.middlewares=api-sec-headers@docker,api-ratelimit@docker,api-compress@docker"
      - "traefik.http.routers.api.rule=Host(`api.example.com`)"
      - "traefik.http.routers.api.entrypoints=websecure"
      - "traefik.http.routers.api.tls.certresolver=le"
      - "traefik.http.services.api.loadbalancer.server.port=3000"
```

Проверка срабатывания Rate Limit:

```bash
# Серия быстрых запросов для превышения burst
for i in {1..60}; do curl -s -o /dev/null -w "%{http_code}\n" https://api.example.com; done | sort | uniq -c
# → 50 200
#   10 429
```

### Сценарий 5: Управление файлом `acme.json` и правами 0600

Traefik требует, чтобы файл `acme.json` имел права ровно `0600` (`-rw-------`). При нарушении прав сервис завершает работу с ошибкой:
`permissions 0755 for /letsencrypt/acme.json are too open, it should be 0600`.

Для надежного монтирования с хоста (bind mount) без конфликтов прав доступа используется pattern с init-контейнером:

```yaml
services:
  traefik-init:
    image: alpine:3.21
    command: >
      sh -c "touch /letsencrypt/acme.json && chmod 600 /letsencrypt/acme.json"
    volumes:
      - ./letsencrypt:/letsencrypt
    restart: "no"

  traefik:
    image: traefik:v3.7
    depends_on:
      traefik-init:
        condition: service_completed_successfully
    volumes:
      - ./letsencrypt:/letsencrypt
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

При использовании Docker Named Volume (`volumes: traefik-certificates:`) Traefik создает файл автоматически с корректными правами внутри volume.

### Сценарий 6: Маршрутизация в Docker Swarm

В Docker Swarm оркестрация контейнеров принципиально отличается от standalone Docker Compose. В Traefik v3 провайдер Swarm выделен в отдельный компонент:
- Вместо провайдера `docker` используется флаг `--providers.swarm=true`.
- Метки задаются не в `services.<name>.labels`, а исключительно в секции `deploy.labels`.
- Трафик балансируется через оверлейные сети (`overlay`) с публикацией портов в режиме `mode: host`.

Детальное руководство по развертыванию в кластере Swarm см. в [Docker Swarm: Входящий трафик (Ingress) с Traefik](../../Docker_swarm/swarm_ingress_traefik.md).

## Операции и команды

### Диагностика и инспекция состояния

```bash
# 1. Проверка версии Traefik в контейнере
docker compose exec traefik traefik version
# → Version:      3.7.0
#   Codename:     faubourg
#   Go version:   go1.24.0
#   Built:        2025-02-18T14:30:00Z
#   OS/Arch:      linux/amd64

# 2. Проверка встроенного healthcheck
docker compose exec traefik traefik healthcheck --ping
# → OK

# 3. Список активных HTTP-роутеров через Traefik API
curl -s http://127.0.0.1:8080/api/http/routers | jq '.[] | {name: .name, rule: .rule, status: .status, entryPoints: .entryPoints}'
# → {
#     "name": "myapp@docker",
#     "rule": "Host(`app.example.com`)",
#     "status": "enabled",
#     "entryPoints": ["websecure"]
#   }

# 4. Список сервисов и статус бэкенд-серверов
curl -s http://127.0.0.1:8080/api/http/services | jq '.[] | {name: .name, serverCount: (.serverStatus | length), status: .status}'
# → {
#     "name": "myapp-svc@docker",
#     "serverCount": 3,
#     "status": "enabled"
#   }

# 5. Просмотр зарегистрированных реплик сервиса
curl -s http://127.0.0.1:8080/api/http/services/myapp-svc@docker | jq '.serverStatus'
# → {
#     "http://172.18.0.4:80": "UP",
#     "http://172.18.0.5:80": "UP",
#     "http://172.18.0.6:80": "UP"
#   }

# 6. Проверка валидности сертификатов в acme.json
docker compose exec traefik sh -c "cat /letsencrypt/acme.json | jq -r '.le.Certificates[] | \"\(.domain.main): действителен до \(.certificates[0].domain.validTo // \"OK\")\"'"
# → app.example.com: действителен до 2026-05-15T12:00:00Z
```

### Мониторинг логов и тестирование трафика

```bash
# Просмотр access-логов с фильтрацией ошибок 5xx
docker compose exec traefik sh -c "tail -n 100 /var/log/traefik/access.log 2>/dev/null" || docker compose logs traefik --tail 100 | grep '"DownstreamStatus":5'
# → {"ClientHost":"192.168.1.50","DownstreamStatus":502,"Duration":120456,"OriginStatus":502,"RequestPath":"/api/data","RouterName":"myapp@docker"}

# Тестирование автоматического редиректа HTTP -> HTTPS
curl -Iv http://app.example.com
# → HTTP/1.1 301 Moved Permanently
#   Location: https://app.example.com/

# Тестирование HTTPS соединения и TLS рукопожатия
curl -Iv https://app.example.com 2>&1 | grep -E "SSL connection|HTTP/"
# → * SSL connection using TLSv1.3 / TLS_AES_128_GCM_SHA256
#   < HTTP/2 200
```

## Устранение неисправностей

| Проблема | Диагностика | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **404 Not Found** | `curl -Iv https://example.com`<br>Лог Traefik: `Router not found` | 1. `exposedByDefault: false` и нет метки `traefik.enable=true`.<br>2. Ошибка в правиле `Host(...)`.<br>3. Не указан `entrypoints=websecure`. | 1. Добавить `traefik.enable=true`.<br>2. Проверить синтаксис Host (в v3 используется обратный апостроф или кавычка).<br>3. Указать `entrypoints=websecure`. |
| **502 Bad Gateway** | Лог Traefik: `dial tcp 172.19.0.5:8080: connect: no route to host` | Контейнер подключен к нескольким сетям; Traefik выбрал IP из изолированной сети `db-tier`. | Задать явную метку `traefik.docker.network=proxy-tier` на сервисе приложения. |
| **502 Bad Gateway (порт)** | В логе: `dial tcp 172.18.0.4:0: connect: invalid port` | В Dockerfile не указан `EXPOSE` или приложение слушает порт, отличный от дефолтного 80. | Явно указать `traefik.http.services.<name>.loadbalancer.server.port=<порт>`. |
| **Ошибка прав `acme.json`** | Лог Traefik: `permissions 0755 for .../acme.json are too open` | Файл `acme.json` создан на хосте с дефолтной маской umask (`0644` или `0755`). | Выполнить `chmod 600 acme.json` или использовать init-контейнер для установки прав. |
| **Traefik не видит контейнеры** | Лог: `Failed to retrieve information of the docker client: permission denied` | Сокет `/var/run/docker.sock` недоступен по правам или `socket-proxy` остановлен. | Проверить права на сокет (`chmod 660 /var/run/docker.sock`) или статус сервиса `socket-proxy`. |
| **Конфликт портов при `--scale`** | `docker compose up --scale app=3`<br>Ошибка: `port is already allocated` | В секции `app` указана директива `ports: ["8080:8080"]`. | Заменить `ports:` на `expose:` или полностью удалить директиву (Traefik обращается по внутренней сети). |
| **Сертификат ACME не выпускается** | Лог: `acme: Error -> Cannot negotiate ALPN protocol` или timeout | 1. Порт 80/443 недоступен из интернета (NAT/Firewall).<br>2. DNS-запись домена не указывает на IP хоста. | Проверить `ufw allow 80,443/tcp`, доступность с внешнего IP и соответствие A/AAAA записей. |
| **WebSocket соединение обрывается** | Соединение закрывается через 30–60 секунд без ошибок приложения. | Срабатывают таймауты простоя Traefik `transport.respondingTimeouts`. | Настроить `serversTransport.forwardingTimeouts.responseHeaderTimeout=0` или настроить ping/pong в WebSocket. |

## Рекомендации и Best Practices

1. **Изолируйте Docker Socket:** Категорически избегайте прямого монтирования `/var/run/docker.sock` в публичный контейнер Traefik в production. Используйте `tecnativa/docker-socket-proxy` в режиме `read-only` (`POST=0`).
2. **Всегда включайте `exposedByDefault: false`:** Публикуйте сервисы только осознанно через метку `traefik.enable=true`.
3. **Разделяйте сетевые контуры:**
   - Публичные веб-сервисы и Traefik подключайте к выделенной сети `proxy-tier`.
   - Базы данных, кэш и очереди сообщений подключайте исключительно к внутренним сетям стеков с `internal: true`.
4. **Фиксируйте сеть маршрутизации:** Всегда указывайте `traefik.docker.network=proxy-tier` на многосетевых контейнерах во избежание маршрутизации на недоступные внутренние IP-адреса.
5. **Не публикуйте порты приложений на хосте:** Исключите использование `ports: ["8080:8080"]` для сервисов за Traefik. Приложение должно быть доступно только через внутреннюю сеть Docker.
6. **Настраивайте редирект на уровне Entrypoint:** Не дублируйте middleware редиректа на каждом сервисе. Включайте глобальный HTTP -> HTTPS редирект в статической конфигурации Traefik на порту 80.
7. **Защищайте Dashboard:** Никогда не включайте `api.insecure=true` в боевом окружении. Доступ к панели управления должен быть закрыт с помощью BasicAuth или ForwardAuth и ограничен по IP (`ipallowlist`).
8. **Используйте Active Health Checks:** Для критичных сервисов задавайте `loadbalancer.healthcheck.path`, чтобы Traefik оперативно выводил сбойные экземпляры из пула балансировки.
9. **Ограничивайте размер логов в Compose:** Настройте параметры драйвера логирования Docker (`max-size: "10m"`, `max-file: "3"`), чтобы предотвратить переполнение диска журналом `access.log`.
10. **Обеспечивайте персистентность `acme.json`:** Храните сертификаты в named volume или проверяйте права `chmod 600` при использовании bind mount, чтобы не исчерпать лимиты (rate limits) Let's Encrypt при перезапусках контейнера.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура, провайдеры, роутеры и сервисы.
- [Security Hardening Traefik](./traefik-security-hardening.md) — защита сокета, TLS hardening, DDoS и заголовки безопасности.
- [Health Checks в Traefik](./traefik-health-checks.md) — активные и пассивные проверки доступности бэкендов.
- [Наблюдаемость Traefik](./traefik-observability.md) — метрики Prometheus, экспорт access-логов и трассировка.
- [Middlewares безопасности](./traefik-middlewares-security.md) — настройка BasicAuth, IPAllowList и ForwardAuth.
- [Middlewares управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, CircuitBreaker, Retry и сжатие.
- [Безопасность Docker Compose](../../Docker/Docker_compose/docker_compose_security.md) — детальная настройка docker-socket-proxy и разграничение прав.
- [Продвинутые возможности Compose](../../Docker/Docker_compose/docker_compose_advanced_topics.md) — многосетевые конфигурации и управление ресурсами.
- [Docker Swarm: Входящий трафик (Ingress) с Traefik](../../Docker_swarm/swarm_ingress_traefik.md) — организация ingress-маршрутизации в кластере Swarm.
