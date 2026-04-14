# Docker Swarm: Ingress-трафик с Traefik

> **Миграция с v2 → v3:** Конфигурация обновлена для Traefik v3.6.8. Ключевое изменение: `--providers.docker.swarmMode=true` заменен на `--providers.swarm=true`.

При работе с несколькими веб-сервисами в кластере **[Docker Swarm](./docker_swarm_overview.md)** стандартный механизм **[Routing Mesh](./swarm_core_concepts.md)** направляет трафик на опубликованные порты, но не умеет различать запросы по доменным именам. Для маршрутизации по хостам используется **[Traefik](../WebServers/Traefik/traefik_overview.md)** — динамический обратный прокси с автоматическим обнаружением сервисов.

## Определения

**Ingress-трафик** — входящий сетевой трафик, поступающий извне в кластер (обычно на порты 80/443).

**Динамический обратный прокси** — прокси-сервер, который автоматически обнаруживает изменения в бэкенд-сервисах и перенастраивает правила маршрутизации без перезапуска.

**Entrypoint** — точка входа Traefik (сетевой порт), принимающая входящий трафик (например, `web` для HTTP, `websecure` для HTTPS).

**Router** — компонент Traefik, анализирующий входящие запросы (хост, путь, заголовки) и определяющий целевой сервис.

**Middleware** — компонент для модификации запроса перед отправкой сервису (аутентификация, редиректы, заголовки).

## Базовые концепции

### Принцип работы

1. **Docker Socket:** Traefik запускается как сервис в Swarm с доступом к `/var/run/docker.sock`.
2. **Service Discovery:** Traefik слушает события Docker API (создание, удаление, обновление сервисов).
3. **Labels-driven конфигурация:** Сервисы с метками `traefik.*` автоматически получают правила маршрутизации.
4. **Маршрутизация:** Трафик на порты 80/443 принимается Traefik и перенаправляется согласно правилам.
5. **SSL-автоматизация:** Traefik автоматически запрашивает и обновляет SSL-сертификаты от Let's Encrypt.

### Архитектура развертывания

```
[Клиент] → [Traefik:80/443] → [overlay-сеть] → [App-сервисы]
                    ↓
              (Docker Socket)
                    ↓
              (Service Discovery)
```

**Требования:**

- Общая `overlay`-сеть для Traefik и приложений
- Docker Socket volume (только для manager-узлов)
- Внешний доступ на порты 80, 443, 8080 (dashboard)

## Практические сценарии

### Развертывание Traefik

#### 1. Создание overlay-сети

```sh
docker network create --driver=overlay traefik-public
```

#### 2. Стек Traefik (`docker-compose.traefik.yml`)

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v3.6.8
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"
    command:
      # Docker Swarm provider (v3)
      - "--providers.swarm=true"
      - "--providers.docker.exposedByDefault=false"
      # Entrypoints
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # HTTP → HTTPS redirect
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      # Let's Encrypt ACME
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=your-email@example.com"
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
      # Dashboard (в проде защитить!)
      - "--api.insecure=true"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "letsencrypt-data:/letsencrypt"
    networks:
      - traefik-public
    deploy:
      placement:
        constraints:
          - node.role == manager

volumes:
  letsencrypt-data:

networks:
  traefik-public:
    external: true
```

**Развертывание:**

```sh
docker stack deploy -c docker-compose.traefik.yml traefik-stack
```

#### 3. Развертывание приложения (`docker-compose.app.yml`)

```yaml
version: '3.8'

services:
  nginx-app:
    image: nginx:1.26.3
    networks:
      - traefik-public
    deploy:
      replicas: 2
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.nginx-router.rule=Host(`nginx.your-domain.com`)"
        - "traefik.http.routers.nginx-router.entrypoints=websecure"
        - "traefik.http.routers.nginx-router.tls.certresolver=myresolver"
        - "traefik.http.services.nginx-service.loadbalancer.server.port=80"

networks:
  traefik-public:
    external: true
```

**Развертывание:**

```sh
docker stack deploy -c docker-compose.app.yml my-app
```

### Использование Middleware

#### BasicAuth аутентификация

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.secure-router.rule=Host(`secure.example.com`)"
  - "traefik.http.routers.secure-router.entrypoints=websecure"
  - "traefik.http.routers.secure-router.tls.certresolver=myresolver"
  # Middleware
  - "traefik.http.routers.secure-router.middlewares=auth-middleware"
  - "traefik.http.middlewares.auth-middleware.basicauth.users=admin:$$apr1$$xyz$$abc123"
  - "traefik.http.services.secure-service.loadbalancer.server.port=8080"
```

**Генерация пароля:**

```sh
docker run --rm httpd:2.4 htpasswd -nb admin password
```

#### Path Prefix маршрутизация

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.api-router.rule=Host(`api.example.com`)"
  - "traefik.http.routers.api-router.middlewares=strip-prefix"
  - "traefik.http.middlewares.strip-prefix.stripprefix.prefixes=/api"
  - "traefik.http.services.api-service.loadbalancer.server.port=3000"
```

#### Rate Limiting

```yaml
labels:
  - "traefik.http.middlewares.rate-limit.ratelimit.average=100"
  - "traefik.http.middlewares.rate-limit.ratelimit.burst=50"
```

### Отладка и диагностика

#### Проверка состояния Traefik

```sh
# Журналы Traefik
docker service logs traefik-stack_traefik --follow

# Проверка маршрутов через Dashboard
# http://<manager-ip>:8080/api/http/routers

# Проверка сервисов
docker service ls
docker service ps traefik-stack_traefik
```

#### Тестирование маршрутизации

```sh
# Проверка HTTP → HTTPS редиректа
curl -I http://nginx.your-domain.com

# Проверка SSL-сертификата
curl -vI https://nginx.your-domain.com

# Проверка разрешения DNS
nslookup nginx.your-domain.com
```

#### Частые проблемы

| Проблема | Причина | Решение |
|---|---|---|
| 404 Not Found | Сервис не имеет label `traefik.enable=true` | Добавить метку |
| 502 Bad Gateway | Неправильный порт в `loadbalancer.server.port` | Проверить порт контейнера |
| SSL не работает | ACME storage недоступен или email не указан | Проверить volume и email |
| Сервис не обнаруживается | Traefik и сервис в разных сетях | Подключить к `traefik-public` |

## Дополнительная информация

### Справочник меток

**Основные метки:**

- `traefik.enable=true` — активировать Traefik для сервиса
- `traefik.http.routers.<name>.rule=Host(\`...\`)` — правило маршрутизации по хосту
- `traefik.http.routers.<name>.entrypoints=<entrypoint>` — точка входа (`web` или `websecure`)
- `traefik.http.routers.<name>.tls.certresolver=<resolver>` — ACME resolver для SSL
- `traefik.http.services.<name>.loadbalancer.server.port=<port>` — порт внутри контейнера

**Middleware:**

- `traefik.http.routers.<name>.middlewares=<middleware>` — применение middleware
- `traefik.http.middlewares.<name>.basicauth.users=...` — BasicAuth пользователи
- `traefik.http.middlewares.<name>.stripprefix.prefixes=...` — удаление префикса пути
- `traefik.http.middlewares.<name>.ratelimit.average=...` — средняя скорость запросов

### Безопасность

**Рекомендации для продакшена:**

- Отключить `--api.insecure=true`, использовать BasicAuth для dashboard
- Настроить firewall для ограничения доступа к портам
- Использовать production ACME server (`https://acme-v02.api.letsencrypt.org/directory`)
- Регулярно обновлять образ Traefik

### Сравнение с альтернативами

| Решение | Сложность | Функциональность | Экосистема |
|---|---|---|---|
| **Traefik** | Низкая | Автоматическое обнаружение, SSL | Растущая |
| **Nginx** | Средняя | Полный контроль, кэширование | Огромная |
| **HAProxy** | Высокая | Продвинутая балансировка | Большая |

Для Kubernetes рассмотрите **[Ingress-контроллеры](../Kubernetes/Networking/Ingress/overview.md)** (Nginx, Traefik, Istio).

### Связанные документы

- **Обзор Traefik** — **[../WebServers/Traefik/traefik_overview.md](../WebServers/Traefik/traefik_overview.md)**
- **Traefik с Docker Compose** — **[../WebServers/Traefik/traefik_with_docker_compose.md](../WebServers/Traefik/traefik_with_docker_compose.md)**
- **Docker Swarm сети** — **[swarm_networking.md](./swarm_networking.md)**
- **CI/CD с Traefik** — **[CI_CD/overview.md](./CI_CD/overview.md)**
