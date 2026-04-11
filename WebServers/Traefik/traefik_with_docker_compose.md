# Traefik with Docker Compose

> **SSoT:** Теоретические концепции (Providers, Routers, Services, Middleware, SSL/TLS) — в [Traefik Overview](./traefik_overview.md).
>
> **Версия:** Конфигурация актуальна для Traefik v3.x. Для миграции с v2 см. [официальный гайд](https://doc.traefik.io/traefik/migrate/v2-to-v3/).

## Definitions

- **Статическая конфигурация** (`traefik.yml`) — entrypoints, providers, certificatesResolvers. Загружается при старте, изменения требуют перезапуска.
- **Динамическая конфигурация** (labels в `docker-compose.yml`, `dynamic.yml`) — routers, services, middleware. Обновляется на лету через `watch: true`.
- **`acme.json`** — хранилище SSL-сертификатов Let's Encrypt. Права: `600`, владелец — UID контейнера Traefik.

## Basic Concepts

### Docker Provider и Labels

Traefik подключается к Docker socket (`/var/run/docker.sock`) и обнаруживает контейнеры. Маршрутизация задаётся через labels:

| Label | Назначение |
|---|---|
| `traefik.enable=true` | Активировать Traefik для контейнера |
| `traefik.http.routers.<name>.rule` | Правило маршрутизации (Host, PathPrefix) |
| `traefik.http.routers.<name>.entrypoints` | Точка входа (`web`, `websecure`) |
| `traefik.http.routers.<name>.tls.certresolver` | ACME resolver для SSL |
| `traefik.http.routers.<name>.middlewares` | Цепочка middleware |
| `traefik.http.services.<name>.loadbalancer.server.port` | Порт внутри контейнера |

### `expose` vs `ports`

- **`expose`** — порт доступен только контейнерам в той же Docker-сети. Сервисы за Traefik должны использовать `expose`, а не `ports`, чтобы избежать обхода прокси.
- **`ports`** — публикует порт на хосте. Используется только для самого Traefik (80, 443).

### Docker Network

Traefik и сервисы должны находиться в одной сети. Для изолированных проектов создаётся пользовательская bridge-сеть:

```bash
docker network create traefik_net
```

В `docker-compose.yml` сеть объявляется как `external: true`, если создана вручную, или через секцию `networks` при авто-создании.

## Practical Scenarios

### Полная настройка: Traefik + Nginx + SSL

Цель: запустить Traefik, защитить Dashboard через BasicAuth, опубликовать Nginx с автоматическим SSL.

#### 1. Структура проекта

```
project/
├── traefik/
│   ├── traefik.yml       # статическая конфигурация
│   └── dynamic.yml       # динамическая конфигурация (middleware)
├── docker-compose.yml
└── acme.json             # chmod 600
```

```bash
touch acme.json && chmod 600 acme.json
```

#### 2. Статическая конфигурация (`traefik/traefik.yml`)

```yaml
# traefik/traefik.yml

api:
  dashboard: true
  insecure: false  # в проде — false, доступ через router

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: traefik_net
  file:
    filename: /etc/traefik/dynamic.yml
    watch: true

log:
  level: INFO  # DEBUG для отладки, WARN/ERROR для продакшена

certificatesResolvers:
  letsencrypt:
    acme:
      email: "your-email@example.com"
      storage: /etc/traefik/acme.json
      httpChallenge:
        entryPoint: web
        # delay: 0  # опционально, задержка перед ответом на challenge
      # caServer: "https://acme-staging-v02.api.letsencrypt.org/directory"  # staging для тестов
```

#### 3. Динамическая конфигурация (`traefik/dynamic.yml`)

```yaml
# traefik/dynamic.yml

http:
  middlewares:
    basic-auth:
      basicAuth:
        users:
          # Генерация: echo $(htpasswd -nb admin password) | sed -e 's/\$/\$\$/g'
          - "admin:$$apr1$$...$$..."
```

#### 4. Docker Compose (`docker-compose.yml`)

```yaml
version: "3.8"

services:
  traefik:
    image: traefik:v3.6
    container_name: traefik
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik/traefik.yml:/etc/traefik/traefik.yml:ro
      - ./traefik/dynamic.yml:/etc/traefik/dynamic.yml:ro
      - ./acme.json:/etc/traefik/acme.json
    networks:
      - traefik_net
    labels:
      - "traefik.enable=true"
      # Dashboard router
      - "traefik.http.routers.dashboard.rule=Host(`traefik.example.com`)"
      - "traefik.http.routers.dashboard.entrypoints=websecure"
      - "traefik.http.routers.dashboard.tls=true"
      - "traefik.http.routers.dashboard.tls.certresolver=letsencrypt"
      - "traefik.http.routers.dashboard.service=api@internal"
      - "traefik.http.routers.dashboard.middlewares=basic-auth@file"

  nginx:
    image: nginx:1.26
    container_name: nginx_app
    restart: always
    expose:
      - "80"
    networks:
      - traefik_net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.nginx.rule=Host(`app.example.com`)"
      - "traefik.http.routers.nginx.entrypoints=websecure"
      - "traefik.http.routers.nginx.tls=true"
      - "traefik.http.routers.nginx.tls.certresolver=letsencrypt"
      - "traefik.http.services.nginx.loadbalancer.server.port=80"

networks:
  traefik_net:
    external: true
```

#### 5. Запуск

```bash
# DNS: traefik.example.com и app.example.com → IP сервера
docker-compose up -d
```

Проверка:

```bash
docker-compose ps
docker-compose logs -f traefik
curl -I http://app.example.com  # → 301 → https://
curl -vI https://app.example.com  # → 200, valid cert
```

## Additional Information

### End-to-End Encryption

Трафик Traefik → бэкенд по умолчанию HTTP. В изолированной Docker-сети это допустимо. Для требований безопасности — настройка TLS между контейнерами через внутренние сертификаты.

### Извлечение сертификатов

Для сервисов, требующих `.crt`/`.key` файлы (gRPC, некоторые Java-приложения), используется `traefik-certs-dumper`:

```yaml
  certs-dumper:
    image: ldez/traefik-certs-dumper:v2.11.0
    container_name: certs_dumper
    restart: always
    volumes:
      - ./acme.json:/traefik/acme.json:ro
      - ./certs:/dump
    networks:
      - traefik_net
    command: >
      --source.file.path=/traefik/acme.json
      --dest.path=/dump
      --watch
```

Альтернативный форк: [kereis/traefik-certs-dumper](https://github.com/kereis/traefik-certs-dumper).

### Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| 404 | Нет `traefik.enable=true` или неверный Host | Проверить labels через `docker inspect` |
| 502 | Неверный порт в `loadbalancer.server.port` | Порт должен совпадать с `EXPOSE` контейнера |
| SSL не работает | `acme.json` имеет неверные права | `chmod 600 acme.json`, проверить email |
| Dashboard недоступен | `api.insecure: false`, нет router | Добавить router с middleware auth |

### Связанные документы

- [Traefik Overview (SSoT)](./traefik_overview.md)
- [Swarm Ingress with Traefik](../../Docker_swarm/swarm_ingress_traefik.md)
- [Docker Compose Commands](../../Docker/Docker_compose/docker_compose_cli_commands.md)
- [Docker Networks](../../Docker/Docker_network/docker_network.md)
