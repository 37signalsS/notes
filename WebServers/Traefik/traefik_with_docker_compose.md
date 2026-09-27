# Traefik с Docker Compose: развертывание, метки, сети

## Определения

**Docker Compose** — декларативный формат (`compose.yaml`) для определения multi-container приложений. В контексте Traefik используется для запуска edge-router вместе с приложениями в единой сети.

**Docker provider** — встроенный провайдер Traefik, который отслеживает контейнеры Docker через сокет `/var/run/docker.sock` и автоматически строит маршруты по меткам (labels).

**Метки (labels)** — ключ-значение атрибуты Docker, которые Traefik читает для генерации роутеров, middleware и сервисов без изменения кода приложения.

**Docker network** — изолированный сетевой сегмент, в котором контейнеры могут общаться по имени сервиса. Traefik и приложения должны находиться в одной сети для маршрутизации.

## Базовые концепции

### Архитектура docker-provider

Traefik подключается к Docker через сокет (read-only recommended):

```yaml
# traefik.yml (статическая конфигурация)
api:
  insecure: true  # только для dev; в проде — entrypoint с auth

entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false  # безопасность: включать только по метке
    network: "edge"          # фильтр по сети (опционально)
    watch: true
```

Провайдер слушает события Docker (`start`, `stop`, `destroy`, `create`) и перестраивает конфиг без рестарта Traefik.

### Иерархия меток

Метки имеют строгую иерархию:

```
traefik.enable=true/false
traefik.http.routers.<name>.rule=Host(`example.com`)
traefik.http.routers.<name>.entrypoints=web,websecure
traefik.http.routers.<name>.service=<service-name>
traefik.http.routers.<name>.middlewares=<middleware-list>
traefik.http.services.<name>.loadbalancer.server.port=8080
traefik.http.middlewares.<name>.<type>.<option>=<value>
```

Правила:
- `<name>` — любое уникальное имя в рамках контейнера.
- Метки на уровне **сервиса** (Compose v2 `services.<name>.labels`) применяются ко всем контейнерам сервиса.
- Если метка содержит точку с запятой или запятую — экранируйте или используйте quoted YAML-строки.
- Для middleware в цепочке: `traefik.http.routers.app.middlewares=auth@docker,rate-limit@docker`

### Сети в Compose

Рекомендуемая топология:

```yaml
networks:
  edge:
    driver: bridge
  backend:
    driver: bridge
    internal: true  # нет выхода в интернет
```

- **edge** — сеть, где живут Traefik и все public-facing сервисы.
- **backend** — внутренняя сеть для приложений, не exposed наружу.
- Traefik подключается к обеим сетям, чтобы маршрутизировать и external, и internal трафик.

### Volumes и права

```yaml
services:
  traefik:
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"  # read-only recommended
      - "traefik-letsencrypt:/letsencrypt"               # acme.json
```

Для production монтируйте `acme.json` в named volume (не теряется при `docker compose down` без `-v`).

## Практические сценарии

### Сценарий 1: Базовый Compose (HTTP + HTTPS с Let's Encrypt)

```yaml
# compose.yaml
version: "3.8"

volumes:
  traefik-letsencrypt:

networks:
  edge:
  backend:

services:
  traefik:
    image: traefik:v3.7
    restart: unless-stopped
    command:
      - "--api.insecure=true"                          # dashboard на :8080 (dev only!)
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.le.acme.tlschallenge=true"
      - "--certificatesresolvers.le.acme.email=admin@example.com"
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.network=edge"
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"  # dashboard
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "traefik-letsencrypt:/letsencrypt"
    networks:
      - edge
      - backend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.dashboard.rule=Host(`traefik.example.com`)"
      - "traefik.http.routers.dashboard.service=api@internal"
      - "traefik.http.routers.dashboard.entrypoints=websecure"
      - "traefik.http.routers.dashboard.tls.certresolver=le"

  app:
    image: myapp:latest
    restart: unless-stopped
    networks:
      - backend
      - edge
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`app.example.com`)"
      - "traefik.http.routers.app.entrypoints=websecure"
      - "traefik.http.routers.app.tls.certresolver=le"
      - "traefik.http.services.app.loadbalancer.server.port=8080"
```

Проверка:

```bash
docker compose up -d
curl -I https://app.example.com
# → HTTP/2 200
docker compose ps
# → traefik, app running
```

### Сценарий 2: Middleware-цепочка (RateLimit + BasicAuth + Headers)

```yaml
services:
  traefik:
    # ... (как выше)
    labels:
      - "traefik.enable=true"
      # RateLimit middleware
      - "traefik.http.middlewares.api-rate-limit.rateLimit.average=50"
      - "traefik.http.middlewares.api-rate-limit.rateLimit.period=1s"
      - "traefik.http.middlewares.api-rate-limit.rateLimit.burst=100"
      # BasicAuth middleware
      - "traefik.http.middlewares.api-auth.basicauth.users=admin:$$apr1$$H6uskkkW$$IgXLP6ewTrSuBkTrqE8wj/"
      # Secure headers middleware
      - "traefik.http.middlewares.secure-headers.headers.stsSeconds=31536000"
      - "traefik.http.middlewares.secure-headers.headers.browserXssFilter=true"
      - "traefik.http.middlewares.secure-headers.headers.contentTypeNosniff=true"
      # Chain
      - "traefik.http.routers.api.middlewares=secure-headers@docker,api-rate-limit@docker,api-auth@docker"
      - "traefik.http.routers.api.rule=Host(`api.example.com`)"
      - "traefik.http.routers.api.entrypoints=websecure"
      - "traefik.http.routers.api.tls.certresolver=le"
      - "traefik.http.services.api.loadbalancer.server.port=8080"
```

Проверка:

```bash
curl -u admin:password https://api.example.com/health
# → 200
curl https://api.example.com/health
# → 401 Unauthorized
```

### Сценарий 3: Traefik Pilot / Hub (опционально)

Traefik Hub (commercial) добавляет centralized config и analytics. В OSS можно использовать Traefik Pilot для базовой телеметрии:

```yaml
command:
  - "--pilot.token=${TRAEFIK_PILOT_TOKEN}"
```

Для multi-cluster analytics без Traefik Hub используйте Prometheus + Grafana (см. [Наблюдаемость Traefik](./traefik-observability.md)).

### Сценарий 4: Docker Swarm mode

Traefik в Swarm использует режим `swarm` provider вместо `docker`:

```yaml
services:
  traefik:
    deploy:
      placement:
        constraints:
          - node.role == manager
      replicas: 2
    command:
      - "--providers.docker.swarmMode=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
    ports:
      - target: 80
        published: 80
        protocol: tcp
        mode: host
      - target: 443
        published: 443
        protocol: tcp
        mode: host
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
```

Приложения в Swarm получают метки через `deploy.labels` или через service metadata.

### Сценарий 5: Overlay network для multi-host

```yaml
networks:
  traefik-public:
    external: true
    name: traefik-public

services:
  traefik:
    networks:
      - traefik-public
  app:
    networks:
      - traefik-public
```

Создание overlay-сети:

```bash
docker network create --driver overlay --attachable traefik-public
```

## Операции и команды

```bash
# Проверка конфигурации
docker compose exec traefik traefik healthcheck
docker compose exec traefik traefik version

# Просмотр роутеров
curl -s http://localhost:8080/api/http/routers | jq '.[].name'

# Просмотр middleware
curl -s http://localhost:8080/api/http/middlewares | jq '.[].name'

# Просмотр сервисов
curl -s http://localhost:8080/api/http/services | jq '.[].name'

# Логи Traefik
docker compose logs traefik --tail 100 -f

# Перезагрузка конфигурации (не нужна при docker provider — авто)
docker compose exec traefik traefik reload

# Проверка сертификатов
docker compose exec traefik cat /letsencrypt/acme.json | jq '.Certificates[] | {domain: .main, expires: .certificates[0].domain.validTo}'
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Роутер не создается** | `exposedByDefault: false`, нет `traefik.enable=true` | Добавить метку `traefik.enable=true` на сервис |
| **502 Bad Gateway** | Приложение не слушает на порту из метки `server.port` | Проверить `docker compose ps`, порт контейнера, метку |
| **TLS-сертификат не выдается** | ACME challenge не проходит, порт 80 закрыт | Убедиться, что `web` entrypoint открыт, email правильный |
| **Dashboard недоступен** | `api.insecure: false`, нет маршрута для dashboard | Создать IngressRoute/middleware для dashboard или использовать `insecure: true` только в dev |
| **Метки игнорируются** | Неправильный синтаксис, метка на уровне `build` вместо `services` | Метки только в `services.<name>.labels`, проверить YAML |
| **WebSocket рвется** | Buffering/compress middleware в цепочке | Убрать стриминговые middleware для WebSocket-роутов |
| **Контейнер не в сети** | Traefik подключен к другой сети, нет `network: edge` на сервисе | Привести сервис и Traefik к одной сети |

## Рекомендации

- Всегда используйте `exposedByDefault: false` — включайте сервисы явно меткой.
- Монтируйте docker socket read-only (`:ro`).
- Dashboard в production: отключите `api.insecure`, защитите BasicAuth/ForwardAuth.
- Для multi-host: используйте overlay-сети и host-mode published ports (Swarm).
- Версионируйте `compose.yaml` в Git; актуальные теги образов фиксируйте (`traefik:v3.7.0`, не `:latest`).
- Named volume для `acme.json` сохраняет сертификаты при `docker compose down`.
- При обновлении Traefik: `docker compose up -d --force-recreate traefik` — приложение не пересоздается.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура и компоненты.
- [Traefik на bare-metal](./traefik-bare-metal.md) — systemd-юнит и альтернативный запуск.
- [Провайдеры конфигурации](./traefik-providers-advanced.md) — приоритет провайдеров, Go-шаблоны.
- [Docker Networking](../../Docker/Docker_network/network_basics.md) — типы сетей Docker.
- [Docker Compose Overview](../../Docker/Docker_compose/docker_compose_overview.md) — основы Compose.
- [Helm deployment](../../Kubernetes/Networking/Ingress/installation/helm-installation.md) — альтернатива для K8s.
