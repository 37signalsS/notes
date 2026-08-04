# Traefik с Docker Compose: Практическое руководство

**Надёжность:** 10 (SSoT + Подтверждено практическими внедрениями 2026 года)

**Свежесть:** Актуально на июль 2026. Проверка обновлений: ежеквартально.

> **SSoT (Single Source of Truth):** Теоретические концепции и архитектура Traefik v3 описаны в [Обзоре Traefik](./traefik_overview.md). В данном документе фокус на реализации через Docker Compose.

## Определения

-   **Статическая конфигурация** (`traefik.yml` / CLI-флаги) — параметры, с которыми прокси стартует. Включает Entrypoints, Providers, Certificates Resolvers. Изменения требуют перезапуска контейнера.
-   **Динамическая конфигурация** (Labels / `dynamic.yml`) — правила маршрутизации, которые Traefik «подхватывает» на лету. Включает Routers, Services, Middlewares.
-   **`acme.json`** — файл-хранилище сертификатов. **Критическое требование:** права доступа `600` (`chmod 600 acme.json`), иначе Traefik откажется загружать TLS-резолвер в целях безопасности.
-   **Docker Provider** — механизм, позволяющий Traefik читать метаданные (Labels) других контейнеров через обращение к API Docker.

## Базовые концепции

### Маршрутизация через Labels (Метки)

Traefik сканирует все запущенные контейнеры. Для публикации сервиса используются следующие метки:

| Метка (Label) | Описание и пример |
| :--- | :--- |
| `traefik.enable=true` | Обязательно для активации, если в конфиге `exposedByDefault: false`. |
| `traefik.http.routers.<name>.rule` | Условие: `Host(\`api.example.com\`) && PathPrefix(\`/v1\`)`. |
| `traefik.http.routers.<name>.entrypoints` | Список точек входа: `web` или `websecure`. |
| `traefik.http.routers.<name>.tls.certresolver` | Имя резолвера из статической конфигурации (например, `letsencrypt`). |
| `traefik.http.services.<name>.loadbalancer.server.port` | **Важно:** Порт приложения *внутри* контейнера. |
| `traefik.http.routers.<name>.priority` | Приоритет правила (целое число). Помогает избежать конфликтов путей. |

### Концепция expose против ports

1.  **`expose`**: Делает порт доступным только для других контейнеров в той же Docker-сети. Это **рекомендуемый способ** для бэкенд-сервисов. Traefik видит этот порт и направляет туда трафик внутри виртуальной сети. Подробнее о декларативном описании портов см. в **[Инструкция EXPOSE](../../Docker/Dockerfile/Instructions/networking_ports.md)**.
2.  **`ports`**: Пробрасывает порт на хост-машину (0.0.0.0). Используется только для самого Traefik (80, 443). Использование `ports` для бэкендов создает угрозу безопасности, так как трафик может идти в обход правил Traefik (WAF, Auth).

### Сетевая архитектура (Bridge vs Overlay)

Для локального использования с Docker Compose рекомендуется создание внешней сети для обеспечения связи между разными проектами (стеками):

```bash
docker network create traefik_public
```

В `compose.yaml` эта сеть подключается через `external: true`.

## Практические сценарии

### Сценарий 1: Эталонная конфигурация (Traefik + TLS + Auth)

#### 1. Структура директорий
```text
infrastructure/
├── traefik/
│   ├── traefik.yml
│   └── dynamic.yml
├── acme.json (600)
└── compose.yaml
```

#### 2. Статическая конфигурация (`traefik/traefik.yml`)
```yaml
api:
  dashboard: true
  insecure: false

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
    http:
      tls:
        certResolver: letsencrypt

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: traefik_public
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  letsencrypt:
    acme:
      email: your-email@example.com
      storage: /etc/traefik/acme.json
      httpChallenge:
        entryPoint: web
```

#### 3. Динамическая конфигурация (`traefik/dynamic.yml`)
```yaml
http:
  middlewares:
    secure-headers:
      headers:
        sslRedirect: true
        stsSeconds: 31536000
        browserXssFilter: true
        contentTypeNosniff: true

    admin-auth:
      basicAuth:
        # Генерировать: echo $(htpasswd -nb user password) | sed -e 's/\$/\$\$/g'
        users:
          - "admin:$$apr1$$Q0j1O2G...$$..."
```

#### 4. Файл Compose (`compose.yaml`)
```yaml
services:
  traefik:
    image: traefik:v3.6
    container_name: traefik
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    networks:
      - traefik_public
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik/traefik.yml:/etc/traefik/traefik.yml:ro
      - ./traefik/dynamic.yml:/etc/traefik/dynamic/dynamic.yml:ro
      - ./acme.json:/etc/traefik/acme.json
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.api.rule=Host(`traefik.local`)"
      - "traefik.http.routers.api.service=api@internal"
      - "traefik.http.routers.api.middlewares=admin-auth@file"

networks:
  traefik_public:
    external: true
```

### Сценарий 2: Повышенная безопасность (Docker Socket Proxy)

Прямой проброс `/var/run/docker.sock` небезопасен (дает контейнеру права root на хосте). В продакшене рекомендуется использовать прокси-заглушку.

```yaml
services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - CONTAINERS=1 # Разрешить чтение списка контейнеров
    networks:
      - socket_net

  traefik:
    image: traefik:v3.6
    depends_on:
      - socket-proxy
    environment:
      - TRAEFIK_PROVIDERS_DOCKER_ENDPOINT=tcp://socket-proxy:2375
    networks:
      - socket_net
      - traefik_public
```

## Дополнительная информация

### Работа с SSL-сертификатами (Certs Dumper)

Если ваше приложение требует физические файлы сертификатов (`.key`, `.crt`) вместо автоматического TLS в Traefik, используйте инструмент для извлечения данных из `acme.json`.

```yaml
  certs-dumper:
    image: ldez/traefik-certs-dumper:v2.11.0
    container_name: certs_dumper
    volumes:
      - ./acme.json:/traefik/acme.json:ro
      - ./certs:/dump
    command: --source.file.path=/traefik/acme.json --dest.path=/dump --watch
```

### Мониторинг и Метрики

Traefik v3 поддерживает экспорт метрик в Prometheus. Включите их в `traefik.yml`:
```yaml
metrics:
  prometheus:
    addEntryPointsLabels: true
    addServicesLabels: true
```

Для визуализации в Grafana используйте ID дашборда: `11462`.

### Диагностика (Troubleshooting)

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **404 Not Found** | Правило Host в метках не совпадает с реальным доменом. | Проверьте `docker inspect` и заголовки `Host` в запросе. |
| **502 Bad Gateway** | Traefik не может достучаться до порта приложения. | 1. Проверьте, что приложение слушает на `0.0.0.0`. 2. Укажите `loadbalancer.server.port` вручную. |
| **SSL: Handshake failed** | Сертификат не выпущен или выпущен staging-резолвером. | Проверьте логи на наличие `acme: error: 400`. Убедитесь, что порт 80 открыт для HTTP-01 challenge. |
| **Internal Server Error** | Ошибка в цепочке Middleware. | Проверьте `docker logs traefik`. Часто ошибка в синтаксисе `dynamic.yml`. |
| **Метки не применяются** | Метки указаны на уровне контейнера, а не сервиса (в Swarm). | В Compose (не Swarm) метки должны быть в корне сервиса. В Swarm — внутри `deploy`. |
| **Проблемы с WebSocket** | Соединение обрывается через 60 секунд. | Добавьте Middleware `buffering` или увеличьте `respondingTimeouts` в Entrypoint. |

### См. также

-   [Обзор Traefik (SSoT)](./traefik_overview.md) — архитектура и компоненты.
-   [Traefik в Docker Swarm](../../Docker_swarm/swarm_ingress_traefik.md) — особенности работы в кластере.
-   [Команды Docker Compose](../../Docker/Docker_compose/docker_compose_cli_commands.md) — управление жизненным циклом стека.
