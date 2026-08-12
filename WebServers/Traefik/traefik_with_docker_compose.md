# Traefik с Docker Compose: Практическое руководство

Этот документ описывает практическую реализацию обратного прокси Traefik в среде Docker Compose. Теоретические основы, архитектура и компоненты Traefik v3 подробно описаны в документе **[Обзор Traefik](./traefik_overview.md)**.

## Определения

-   **Статическая конфигурация** (`traefik.yml` / CLI-флаги) — базовые настройки, определяющие точки входа (entrypoints), провайдеров и методы выпуска сертификатов. Требует перезапуска контейнера при изменении.
-   **Динамическая конфигурация** (Labels / `dynamic.yml`) — правила маршрутизации, middlewares и описания сервисов. Traefik отслеживает их изменения в реальном времени через API Docker или файловую систему.
-   **`acme.json`** — файл в формате JSON для хранения SSL-сертификатов. **Безопасность:** требует прав доступа строго `600` (`chmod 600 acme.json`), иначе Traefik проигнорирует файл.
-   **Docker Provider** — компонент Traefik, который опрашивает API демона Docker для автоматического создания маршрутов на основе метаданных (labels) контейнеров.

## Базовые концепции

### Маршрутизация через метки (Labels)

В Docker Compose управление трафиком осуществляется через секцию `labels` конкретного сервиса. Traefik сканирует эти метки и строит динамическую конфигурацию.

| Метка (Label) | Описание и пример |
| :--- | :--- |
| `traefik.enable=true` | Активация обработки контейнера (если `exposedByDefault: false`). |
| `traefik.http.routers.<name>.rule` | Условие сопоставления: `Host(\`app.example.com\`)`. |
| `traefik.http.routers.<name>.entrypoints` | Привязка к порту: `web` (80) или `websecure` (443). |
| `traefik.http.routers.<name>.tls.certresolver` | Указание резолвера для автоматического HTTPS (например, `myresolver`). |
| `traefik.http.services.<name>.loadbalancer.server.port` | Внутренний порт приложения в контейнере (например, `8080`). |

### Сетевое взаимодействие: expose vs ports

Для построения безопасной архитектуры крайне важно разделять внешний и внутренний трафик:

1.  **`expose`**: Делает порт доступным только внутри виртуальных сетей Docker. Это **рекомендуемый способ** для бэкендов. Traefik «видит» эти порты через Docker API и направляет трафик напрямую в сеть контейнеров.
2.  **`ports`**: Пробрасывает порт на хост-машину (0.0.0.0). Используется **только** для самого Traefik (порты 80, 443). Прямой проброс портов бэкендов в обход Traefik лишает систему защиты (Middlewares, TLS, WAF).

### Глобальная сеть Ingress

Для связи между разными `compose.yaml` файлами (стеками) рекомендуется использовать общую внешнюю сеть:

```bash
docker network create traefik_network
```

## Практические сценарии

### Сценарий 1: Эталонная настройка (HTTPS + Автоматизация + Безопасность)

#### 1. Структура проекта
```text
.
├── traefik/
│   ├── traefik.yml      # Статика
│   └── dynamic.yml      # Динамика (Middlewares)
├── data/
│   └── acme.json        # Сертификаты (600)
└── docker-compose.yml
```

#### 2. Статическая конфигурация (`traefik/traefik.yml`)
```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

api:
  dashboard: true  # Включает панель управления

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
    network: traefik_network # Сеть по умолчанию для поиска контейнеров
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  myresolver:
    acme:
      email: admin@example.com
      storage: /etc/traefik/acme.json
      httpChallenge:
        entryPoint: web
```

#### 3. Динамическая конфигурация (`traefik/dynamic.yml`)
```yaml
http:
  middlewares:
    # Стандартный набор заголовков безопасности
    secure-headers:
      headers:
        sslRedirect: true
        stsSeconds: 31536000
        browserXssFilter: true
        contentTypeNosniff: true
        forceSTSHeader: true

    # Аутентификация для дашборда
    auth-admin:
      basicAuth:
        users:
          - "admin:$$apr1$$V6q...base64_hash"
```

#### 4. Файл запуска (`docker-compose.yml`)
```yaml
services:
  traefik:
    image: traefik:v3.1
    container_name: traefik
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    networks:
      - traefik_network
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik/traefik.yml:/etc/traefik/traefik.yml:ro
      - ./traefik/dynamic.yml:/etc/traefik/dynamic/dynamic.yml:ro
      - ./data/acme.json:/etc/traefik/acme.json
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.dashboard.rule=Host(`traefik.example.com`)"
      - "traefik.http.routers.dashboard.service=api@internal"
      - "traefik.http.routers.dashboard.entrypoints=websecure"
      - "traefik.http.routers.dashboard.tls.certresolver=myresolver"
      - "traefik.http.routers.dashboard.middlewares=auth-admin@file"

  web-app:
    image: nginx:alpine
    networks:
      - traefik_network
    expose:
      - "80"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.webapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.webapp.entrypoints=websecure"
      - "traefik.http.routers.webapp.tls.certresolver=myresolver"

networks:
  traefik_network:
    external: true
```

### Сценарий 2: Использование Docker Socket Proxy (Production)

Для предотвращения компрометации хоста через `/var/run/docker.sock`, доступ к сокету ограничивается через специализированный прокси.

```yaml
services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - CONTAINERS=1 # Разрешить чтение данных о контейнерах
    networks:
      - socket_net

  traefik:
    image: traefik:v3.1
    depends_on:
      - socket-proxy
    environment:
      - TRAEFIK_PROVIDERS_DOCKER_ENDPOINT=tcp://socket-proxy:2375
    networks:
      - socket_net
      - traefik_network
```

## Дополнительная информация

### Проверки здоровья (Health Checks)

Traefik может исключать неисправные контейнеры из балансировки. Это настраивается через метки сервиса:

```yaml
labels:
  - "traefik.http.services.my-svc.loadbalancer.healthcheck.path=/health"
  - "traefik.http.services.my-svc.loadbalancer.healthcheck.interval=10s"
  - "traefik.http.services.my-svc.loadbalancer.healthcheck.timeout=3s"
```

### Логирование и диагностика

Для отладки сложных правил маршрутизации рекомендуется включать подробные логи:

```yaml
# traefik.yml
log:
  level: DEBUG
  format: json

accessLog:
  filePath: "/var/log/traefik/access.log"
  bufferingSize: 100
  filters:
    statusCodes:
      - "400-499"
      - "500-599"
```

### Диагностика типичных ошибок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **404 Not Found** | Неверный `Host` в метках или запрос пришел не на тот Entrypoint. | Проверьте Dashboard и `docker inspect`. |
| **502 Bad Gateway** | Приложение слушает `localhost` вместо `0.0.0.0` или неверный порт в `loadbalancer.server.port`. | Убедитесь, что приложение доступно внутри сети Docker. |
| **Bad Gateway (Socket)** | Traefik не может подключиться к `docker.sock`. | Проверьте права на файл сокета или настройки `socket-proxy`. |
| **TLS Error (Internal)** | Ошибка выпуска сертификата (Rate limit Let's Encrypt). | Проверьте логи на наличие ошибок ACME и используйте Staging-сервер для тестов. |

### См. также

-   **[Обзор Traefik (Архитектура)](./traefik_overview.md)** — концепции Providers, Routers и Middlewares.
-   **[Инструкция EXPOSE](../../Docker/Dockerfile/Instructions/networking_ports.md)** — почему важно не использовать `ports` для бэкендов.
-   **[Traefik в Docker Swarm](../../Docker_swarm/swarm_ingress_traefik.md)** — специфика меток в режиме оркестратора.
