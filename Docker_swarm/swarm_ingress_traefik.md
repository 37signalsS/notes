# Docker Swarm: Входящий трафик (Ingress) с Traefik

Миграция с версии v2 на v3: конфигурация обновлена для Traefik v3.x. В новой версии провайдер Swarm выделен в отдельный компонент: вместо `--providers.docker.swarmMode=true` используется флаг `--providers.swarm=true`.

При работе с несколькими веб-сервисами в кластере Docker Swarm стандартный механизм Routing Mesh (сетчатая маршрутизация) выполняет балансировку на уровне L4, но не поддерживает разграничение запросов по доменным именам на уровне L7. Traefik решает эту задачу, выступая в роли динамического обратного прокси-сервера.

## Определения

**Ingress-трафик (Входящий трафик)** — сетевой трафик, поступающий в кластер из внешних сетей (обычно по протоколам HTTP/HTTPS на порты 80/443).

**Routing Mesh (Сетчатая маршрутизация)** — встроенный механизм Swarm, позволяющий обращаться к сервису через любой узел кластера. По умолчанию выполняет SNAT (Source Network Address Translation), что приводит к потере реального IP-адреса клиента.

**Host Mode (Режим хоста)** — способ публикации портов, при котором контейнер слушает порт непосредственно на сетевом интерфейсе узла кластера. Позволяет сохранять реальный IP-адрес клиента и минимизировать задержки.

**Docker Socket Proxy** — вспомогательный сервис, который предоставляет ограниченный доступ к Docker API по сети (TCP), защищая основной сокет демона `/var/run/docker.sock` от прямого доступа потенциально уязвимых веб-сервисов.

## Базовые концепции

### Принцип работы в Swarm

1. **Обнаружение сервисов (Service Discovery):** Traefik опрашивает API менеджеров Swarm и динамически строит таблицу маршрутов на основе меток (labels) сервисов.
2. **Оверлейные сети (Overlay Networks):** Traefik и приложения должны находиться в общей оверлейной сети для передачи трафика внутри кластера.
3. **Декларативность:** Вся конфигурация маршрутизации (правила Host, middleware, TLS) описывается в секции `deploy.labels` файла `docker-compose.yml`.

### Сохранение реального IP-адреса

По умолчанию Swarm балансирует трафик через VIP (Virtual IP) и Ingress-сеть, заменяя IP клиента на внутренний IP узла. Чтобы Traefik видел реальные адреса для логирования или безопасности (например, Fail2Ban), порты должны быть опубликованы в режиме `host`:

```yaml
ports:
  - target: 80
    published: 80
    protocol: tcp
    mode: host
  - target: 443
    published: 443
    protocol: tcp
    mode: host
```

### Безопасность Docker Socket

Запуск Traefik с прямым монтированием `/var/run/docker.sock` на менеджере является риском безопасности. Рекомендуется использовать `docker-socket-proxy`, который разрешает только `GET` запросы к `/containers/*`, `/services/*` и `/tasks/*`.

## Практические сценарии

### Развертывание Traefik v3

#### 1. Создание внешней оверлейной сети

```bash
docker network create --driver=overlay traefik-public
# → <NETWORK_ID>
```

#### 2. Стек Traefik с проксированием сокета

Файл `docker-compose.traefik.yml`:

```yaml
version: '3.8'

services:
  # Прокси для безопасного доступа к API
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
        constraints:
          - node.role == manager

  traefik:
    image: traefik:v3.1
    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
    command:
      - "--providers.swarm=true"
      - "--providers.swarm.endpoint=tcp://socket-proxy:2375"
      - "--providers.swarm.exposedByDefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Авто-редирект на HTTPS
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      # Настройка SSL (Let's Encrypt)
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=admin@example.com"
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
    volumes:
      - "letsencrypt-data:/letsencrypt"
    networks:
      - traefik-public
      - traefik-internal
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == manager

networks:
  traefik-public:
    external: true
  traefik-internal:
    driver: overlay

volumes:
  letsencrypt-data:
```

### Настройка приложения (Backend)

Метки **обязательно** должны находиться в секции `deploy.labels`, а не в `services.labels`.

```yaml
services:
  my-app:
    image: nginx:alpine
    networks:
      - traefik-public
    deploy:
      replicas: 3
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.myapp.rule=Host(`myapp.example.com`)"
        - "traefik.http.routers.myapp.entrypoints=websecure"
        - "traefik.http.routers.myapp.tls.certresolver=myresolver"
        - "traefik.http.services.myapp.loadbalancer.server.port=80"
```

### Диагностика

```bash
# Просмотр логов Traefik
docker service logs -f traefik_traefik
# → level=info msg="Configuration loaded from flags."
# → level=info msg="Starting provider *swarm.Provider"

# Проверка конфигурации через Dashboard (если включен)
# curl -I http://localhost:8080/api/rawdata
```

#### Частые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **404 Not Found** | Метки в `services.labels` вместо `deploy.labels` | Перенести метки в секцию `deploy` |
| **Gateway Timeout** | Приложение не в сети `traefik-public` | Добавить сеть в описание сервиса |
| **SSL handshake error** | `acme.json` имеет слишком широкие права | `chmod 600 /path/to/acme.json` |

## Дополнительная информация

### Сравнение режимов публикации портов

| Функция | Ingress Mode (default) | Host Mode |
| :--- | :--- | :--- |
| **Балансировка** | Встроенный Swarm L4 LB | Прямое попадание на узел |
| **Client IP** | Теряется (SNAT) | Сохраняется |
| **Порты** | Виртуализированы | Привязаны к узлу (конфликт портов) |

### Смотрите также

- **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)** — общие концепции v3.
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)** — подробности работы Overlay-сетей.
- **[Продвинутые стратегии деплоя](./swarm_stack_advanced.md)** — Canary и Blue-Green через Traefik.
