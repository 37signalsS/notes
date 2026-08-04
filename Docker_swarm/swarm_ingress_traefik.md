# Docker Swarm: Входящий трафик (Ingress) с Traefik

Миграция с версии v2 на v3: конфигурация обновлена для Traefik v3.x. В новой версии провайдер Swarm выделен в отдельный компонент: вместо `--providers.docker.swarmMode=true` используется флаг `--providers.swarm=true`.

При работе с несколькими веб-сервисами в кластере Docker Swarm стандартный механизм Routing Mesh (сетчатая маршрутизация) выполняет балансировку на уровне L4, но не поддерживает разграничение запросов по доменным именам на уровне L7. Traefik решает эту задачу, выступая в роли динамического обратного прокси-сервера и Edge Router.

## Определения

**Ingress-трафик (Входящий трафик)** — сетевой трафик, поступающий в кластер из внешних сетей (обычно по протоколам HTTP/HTTPS на порты 80/443).

**Routing Mesh (Сетчатая маршрутизация)** — встроенный механизм Swarm, позволяющий обращаться к сервису через любой узел кластера. По умолчанию выполняет SNAT (Source Network Address Translation), что приводит к потере реального IP-адреса клиента.

**Host Mode (Режим хоста)** — способ публикации портов, при котором контейнер слушает порт непосредственно на сетевом интерфейсе узла кластера (`mode: host`). Позволяет сохранять реальный IP-адрес клиента и минимизировать задержки.

**Docker Socket Proxy** — вспомогательный сервис, который предоставляет ограниченный доступ к Docker API по сети (TCP), защищая основной сокет демона `/var/run/docker.sock` от прямого доступа.

**Middleware (Промежуточное ПО)** — компоненты Traefik для модификации запросов (авторизация, заголовки, ограничение скорости) перед их отправкой в Backend.

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
    image: traefik:v3.1
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

## Диагностика

```bash
# Проверка статуса сервисов
docker service ls
# Просмотр логов (поиск ошибок конфигурации провайдера)
docker service logs -f traefik_traefik
```

### Типовые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **404 Not Found** | Метки в `services.labels` | Перенести в `deploy.labels` |
| **Gateway Timeout** | Разные сети | Проверить наличие `traefik-public` у обоих сервисов |
| **SSL Error** | Права на `acme.json` | Убедиться в `chmod 600` на томе |
| **IP не совпадает** | SNAT в Swarm | Использовать `mode: host` для портов Traefik |

## Дополнительная информация

### Сравнение с другими решениями

| Характеристика | Traefik | Nginx Ingress | HAProxy |
| :--- | :--- | :--- | :--- |
| **Service Discovery** | Нативно (Swarm API) | Требует Nginx-скриптов | Требует Consul/DNS |
| **Auto SSL** | Встроено (ACME) | Cert-manager / Shell | Внешние скрипты |
| **Динамичность** | 10/10 | 6/10 | 5/10 |

### Смотрите также

- **[Обзор Traefik (SSoT)](../../WebServers/Traefik/traefik_overview.md)** — архитектура и компоненты.
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)** — подробности работы Overlay-сетей.
- **[Продвинутые стратегии деплоя](./swarm_stack_advanced.md)** — Canary и Blue-Green через Traefik.
- **[Диагностика сетевой связности](../Docker/Docker_troubleshooting/network_connectivity_issues.md)**
