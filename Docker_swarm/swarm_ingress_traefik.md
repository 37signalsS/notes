# Docker Swarm: Входящий трафик (Ingress) с Traefik

**Актуально для:** Docker Swarm 29.x

Миграция с версии v2 на v3: провайдер Swarm в Traefik v3 выделен в отдельный компонент. Вместо `--providers.docker.swarmMode=true` используется `--providers.swarm=true`.

При работе с несколькими веб-сервисами в кластере Docker Swarm стандартный механизм Routing Mesh (сетчатая маршрутизация) выполняет балансировку на уровне L4, но не поддерживает разграничение запросов по доменным именам на уровне L7. Traefik решает эту задачу, выступая в роли динамического обратного прокси-сервера и Edge Router.

## Определения

**Ingress-трафик (Входящий трафик)** — сетевой трафик, поступающий в кластер из внешних сетей (обычно по протоколам HTTP/HTTPS на порты 80/443).

**Routing Mesh (Сетчатая маршрутизация)** — встроенный механизм Swarm L4-балансировки. Подробнее: **[Сетевое взаимодействие в Swarm](./swarm_networking.md)**.

**Host Mode (Режим хоста)** — способ публикации портов, при котором контейнер слушает порт непосредственно на сетевом интерфейсе узла кластера. Позволяет сохранять реальный IP-адрес клиента и минимизировать задержки. Подробнее: **[Сетевое взаимодействие в Swarm](./swarm_networking.md)**.

**Docker Socket Proxy** — вспомогательный сервис, который предоставляет ограниченный доступ к Docker API по сети (TCP), защищая основной сокет демона `/var/run/docker.sock` от прямого доступа.

**Middleware (Промежуточное ПО)** — компоненты Traefik для модификации запросов (авторизация, заголовки, ограничение скорости) перед их отправкой в Backend. Подробнее: **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)**.

## Предварительные требования

- Docker Engine 29.x на всех менеджерах и рабочих узлах кластера
- Открытые порты между узлами: `2377/TCP` (управление кластером), `7946/TCP+UDP` (gossip), `4789/UDP` (VXLAN)
- Созданная overlay-сеть для Traefik и приложений (например, `traefik-public`)
- При использовании ACME (Let's Encrypt): порт `80/TCP` доступен из интернета для HTTP Challenge
- Для production: персистентный том для `acme.json` и `docker secret` или `docker config` для статической конфигурации Traefik
- Синхронизация времени через NTP/chrony на всех менеджерах (расхождение >100ms приводит к ошибкам сертификатов ACME)

## Базовые концепции

### Принцип работы в Swarm

1. **Обнаружение сервисов (Service Discovery):** Traefik опрашивает API менеджеров Swarm и динамически строит таблицу маршрутов на основе меток (labels) сервисов.
2. **Оверлейные сети (Overlay Networks):** Traefik и приложения должны находиться в общей оверлейной сети. Рекомендуется создавать одну внешнюю сеть `traefik-public` для всех входящих подключений.
3. **Декларативность:** Вся конфигурация маршрутизации (правила Host, middleware, TLS) описывается в секции `deploy.labels` каждого сервиса.

### Сохранение реального IP-адреса

По умолчанию Swarm балансирует трафик через VIP (Virtual IP), заменяя IP клиента на внутренний IP узла. Чтобы Traefik видел реальные адреса (важно для логирования, WAF или `IPWhiteList`), порты должны быть опубликованы в режиме `host`.

### Проблема High Availability (HA) и ACME

При использовании встроенного ACME (Let's Encrypt) возникают сложности при масштабировании Traefik (`replicas > 1`):
- Файл `acme.json` не может быть одновременно записан несколькими инстансами Traefik.
- **Решение 1:** Использование `replicas: 1` с привязкой к конкретному узлу (через `placement constraints`).
- **Решение 2:** Использование внешних сертификатов (через `docker secret` или `docker config`).
- **Решение 3:** Использование внешнего хранилища (Consul, Redis) для сертификатов (доступно в Traefik Enterprise) или DNS-01 challenge с внешним менеджером сертификатов.

### Безопасность и Socket Proxy

Запуск Traefik с прямым монтированием `/var/run/docker.sock` на менеджере является критическим риском (позволяет получить полный контроль над кластером). Использование `socket-proxy` ограничивает доступ Traefik только необходимыми операциями чтения.

## Практические сценарии

### Развертывание эталонного стека Traefik v3

Этот сценарий использует `docker config` для статической конфигурации и `socket-proxy` для безопасности.

#### 1. Подготовка инфраструктуры

```bash
# Создание сети для входящего трафика
docker network create --driver=overlay traefik-public

# Создание конфигурационного файла
cat <<EOF > traefik.yml
providers:
  swarm:
    endpoint: "tcp://socket-proxy:2375"
    exposedByDefault: false
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
certificatesResolvers:
  myresolver:
    acme:
      email: admin@example.com
      storage: /letsencrypt/acme.json
      tlsChallenge: {}
EOF

docker config create traefik-config traefik.yml
```

#### 2. Развертывание стека

Файл `traefik-stack.yml`:

```yaml
version: '3.8'

services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy
    networks:
      - traefik-internal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - SERVICES=1
      - TASKS=1
      - NETWORKS=1
      - NODES=1
      - SWARM=1
    deploy:
      placement:
        constraints: [node.role == manager]
      resources:
        limits:
          cpus: '0.1'
          memory: 64M

  traefik:
    image: traefik:v3.7
    configs:
      - source: traefik-config
        target: /etc/traefik/traefik.yml
    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
    volumes:
      - letsencrypt-data:/letsencrypt
    networks:
      - traefik-public
      - traefik-internal
    healthcheck:
      test: ["CMD", "traefik", "healthcheck"]
      interval: 10s
      timeout: 5s
      retries: 3
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == manager]

networks:
  traefik-public:
    external: true
  traefik-internal:
    driver: overlay

volumes:
  letsencrypt-data:
```

**Валидация:**
```bash
docker service ls
# → traefik_traefik в статусе Running, реплика 1/1

docker service logs traefik_traefik
# → нет ошибок конфигурации провайдера swarm

curl -s http://localhost:8080/ping
# → OK (если порт 8080 открыт)

docker network inspect traefik-public
# → Traefik подключен к сети, содержит task-эндпоинт
```

### Настройка Middlewares для приложений

Middlewares позволяют добавлять функциональность к маршрутам без изменения кода приложения.

```yaml
services:
  api:
    image: my-api:latest
    networks:
      - traefik-public
    deploy:
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.api.rule=Host(`api.example.com`)"
        - "traefik.http.routers.api.entrypoints=websecure"
        - "traefik.http.routers.api.tls.certresolver=myresolver"
        # Подключение Middleware
        - "traefik.http.routers.api.middlewares=api-auth,api-headers"
        # Basic Auth (user:password_hash)
        - "traefik.http.middlewares.api-auth.basicauth.users=user:\$$apr1\$$...hash"
        # Безопасные заголовки
        - "traefik.http.middlewares.api-headers.headers.browserXssFilter=true"
        - "traefik.http.middlewares.api-headers.headers.contentTypeNosniff=true"
        - "traefik.http.services.api.loadbalancer.server.port=8080"
```

**Валидация:**
```bash
curl -s -H "Host: api.example.com" http://<traefik-ip>/health
# → 200 OK, ответ от бэкенда

curl -s http://<traefik-ip>/api/http/routers
# → роутер api виден в списке, middlewares подключены

docker service logs api
# → запросы проходят через Traefik, IP клиента сохранен (mode: host)
```

### Мониторинг и логирование

Для интеграции с Prometheus добавьте в `traefik.yml`:

```yaml
metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addServicesLabels: true

accessLog:
  filePath: "/var/log/traefik/access.log"
  bufferingSize: 100
  fields:
    names:
      StartUTC: drop
```

## Операции и команды

| Область | Команды | Назначение |
|:---|:---|:---|
| **Развертывание** | `docker stack deploy -c traefik-stack.yml traefik` | Деплой стека Traefik |
| | `docker config create traefik-config traefik.yml` | Создание статической конфигурации |
| **Инспекция** | `docker service ls --filter name=traefik` | Проверка статуса Traefik |
| | `docker service logs traefik_traefik` | Просмотр логов (ошибки ACME, провайдер) |
| | `docker service inspect traefik_traefik --format '{{.Endpoint.Ports}}'` | Проверка опубликованных портов |
| **Диагностика** | `curl -s http://localhost:8080/ping` | Health check Traefik |
| | `curl -s http://localhost:8080/api/http/routers \| jq` | Список активных роутеров |
| | `curl -s http://localhost:8080/api/http/services \| jq` | Список сервисов и бэкендов |
| **Безопасность** | `docker swarm unlock-key ls` | Проверка ключей разблокировки (если autolock) |
| | `chmod 600 acme.json` | Исправление прав на ACME-хранилище |

## Устранение неисправностей

### Диагностика Traefik

```bash
# Проверка статуса сервисов
docker service ls
# → traefik_traefik в статусе Running

# Просмотр логов (ошибки конфигурации провайдера, ACME)
docker service logs -f traefik_traefik

# Health check через встроенный endpoint
curl -s http://localhost:8080/ping
# → OK

# Проверка открытых портов
ss -tlnp | grep -E ':(80|443|8080)'
# → подтверждение что Traefik слушает ожидаемые порты
```

### Типовые проблемы

| Проблема | Причина | Решение |
|:---|:---|:---|
| **404 Not Found** | Метки в `services.labels` | Перенести в `deploy.labels` (Swarm читает только deploy.labels) |
| **Gateway Timeout** | Разные overlay-сети | Проверить что Traefik и бэкенд в одной сети (`traefik-public`) |
| **SSL Error** | Права на `acme.json` | `chmod 600` на томе, владелец — процесс Traefik |
| **IP не совпадает** | SNAT в Routing Mesh | Использовать `mode: host` для портов Traefik |
| **502 Bad Gateway** | Бэкенд слушает `localhost` | Приложение должно слушать `0.0.0.0` внутри контейнера |
| **ACME rate limit** | Частые перезапуски Traefik | Использовать staging-сервер для тестов (`acme-staging-v02.api.letsencrypt.org`) |
| **Dashboard недоступен** | Отсутствует middleware защиты | Добавить `BasicAuth` или `ForwardAuth`, отключить `api.insecure` |
| **Ключ Traefik не разблокируется** | Autolock менеджера | Выполнить `docker swarm unlock` перед стартом Traefik на менеджере |

## Лучшие практики

1. **Версия образа:** фиксируйте версию Traefik (например, `traefik:v3.7`), не используйте `latest` в production.
2. **Socket Proxy:** никогда не монтируйте `/var/run/docker.sock` напрямую. Используйте `tecnativa/docker-socket-proxy` с минимальными правами (`SERVICES=1`, `TASKS=1`, `NETWORKS=1`, `NODES=1`, `SWARM=1`).
3. **Host Mode:** публикуйте порты Traefik в `mode: host` для сохранения реального IP клиента и минимизации задержек.
4. **ACME:** храните `acme.json` на персистентном томе с правами `600`. Используйте staging-сервер для тестов.
5. **Dashboard:** защищайте дашборд middleware `BasicAuth` или `ForwardAuth`, не открывайте на публичных entrypoints без TLS.
6. **Replicas:** для production используйте `replicas: 1` с placement constraint на менеджерском узле, либо внешнее хранилище сертификатов (Consul, Redis) для HA.
7. **Секреты:** для статической конфигурации используйте `docker config`, для чувствительных данных — `docker secret`.
8. **Мониторинг:** включите Prometheus metrics (`metrics.prometheus`) и access log в формате JSON для интеграции с ELK/Loki.

## Дополнительная информация

### Смотрите также

- **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)** — архитектура и компоненты.
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)** — Routing Mesh, Overlay, IPVS и VXLAN.
- **[Продвинутые стратегии деплоя](./swarm_stack_advanced.md)** — Canary и Blue-Green через Traefik.
- **[Диагностика сетевой связности](../Docker/Docker_troubleshooting/network_connectivity_issues.md)**
