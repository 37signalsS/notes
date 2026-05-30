# Docker Swarm: Входящий трафик (Ingress) с Traefik

Миграция с версии v2 на v3: конфигурация обновлена для Traefik v3.6.8. Основное изменение заключается в замене флага `--providers.docker.swarmMode=true` на `--providers.swarm=true`.

При работе с несколькими веб-сервисами в кластере Docker Swarm стандартный механизм Routing Mesh (сетчатая маршрутизация) направляет трафик на опубликованные порты, но не поддерживает разграничение запросов по доменным именам на уровне L7 (Layer 7). Для маршрутизации на основе хостов используется Traefik — динамический обратный прокси-сервер с автоматическим обнаружением сервисов.

## Определения

**Ingress-трафик (входящий трафик)** — сетевой трафик, поступающий в кластер из внешних сетей (обычно по протоколам HTTP (HyperText Transfer Protocol) / HTTPS (HyperText Transfer Protocol Secure) на порты 80/443).

**Динамический обратный прокси (Dynamic Reverse Proxy)** — прокси-сервер, который автоматически обнаруживает изменения в составе сервисов через API (Application Programming Interface) оркестратора и обновляет правила маршрутизации без перезагрузки.

**Entrypoint (точка входа)** — сетевой порт Traefik, принимающий входящие соединения (например, порт 80 для HTTP или 443 для HTTPS).

**Router (маршрутизатор)** — компонент Traefik, который анализирует параметры запроса (доменное имя, путь, заголовки) и определяет целевой сервис.

**Middleware (промежуточное ПО)** — компоненты для модификации запроса или выполнения дополнительных действий (аутентификация, перенаправления, добавление заголовков) перед отправкой трафика в сервис.

## Базовые концепции

### Принцип работы

1. **Docker Socket:** Traefik запускается как сервис в Docker Swarm и получает доступ к файлу `/var/run/docker.sock` для взаимодействия с API демона Docker.
2. **Service Discovery (обнаружение сервисов):** Traefik отслеживает события Docker API, такие как создание, удаление или масштабирование сервисов.
3. **Конфигурация через метки (Labels):** Параметры маршрутизации задаются непосредственно в описании сервисов Swarm с помощью меток `traefik.*`.
4. **Маршрутизация трафика:** Traefik принимает пакеты на внешних портах и пересылает их в оверлейную сеть (Overlay network) кластера к нужным контейнерам.
5. **Автоматизация SSL/TLS:** Traefik поддерживает протокол ACME (Automatic Certificate Management Environment) для автоматического получения и продления SSL (Secure Sockets Layer) / TLS (Transport Layer Security) сертификатов от Let's Encrypt.

### Архитектура развертывания

Входящий запрос от клиента поступает на порты 80/443 узла кластера, где Traefik перехватывает его и направляет во внутреннюю сеть кластера.

**Основные требования:**
- Наличие общей оверлейной сети для Traefik и целевых приложений.
- Монтирование Docker Socket (только на узлах с ролью `manager`).
- Доступность внешних портов 80, 443 и 8080 (для панели управления Dashboard).

## Практические сценарии

### Развертывание Traefik

#### 1. Создание оверлейной сети (Overlay network)

```bash
docker network create --driver=overlay traefik-public
```

#### 2. Стек Traefik

Конфигурация для файла `docker-compose.traefik.yml`:

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
      # Включение провайдера Docker Swarm для v3
      - "--providers.swarm=true"
      - "--providers.docker.exposedByDefault=false"
      # Точки входа (Entrypoints)
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Перенаправление HTTP → HTTPS
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      # Настройка Let's Encrypt (ACME)
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=admin@example.com"
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
      # Панель управления (Dashboard)
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

#### 3. Развертывание приложения

Пример описания сервиса в файле `docker-compose.app.yml`:

```yaml
version: '3.8'

services:
  web-app:
    image: nginx:1.26.3
    networks:
      - traefik-public
    deploy:
      replicas: 2
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.app-router.rule=Host(`app.example.com`)"
        - "traefik.http.routers.app-router.entrypoints=websecure"
        - "traefik.http.routers.app-router.tls.certresolver=myresolver"
        - "traefik.http.services.app-service.loadbalancer.server.port=80"

networks:
  traefik-public:
    external: true
```

### Использование компонентов Middleware

#### Аутентификация BasicAuth

Для защиты сервиса паролем используются следующие метки:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.secure-app.rule=Host(`secure.example.com`)"
  - "traefik.http.routers.secure-app.middlewares=auth-mw"
  - "traefik.http.middlewares.auth-mw.basicauth.users=user:$$apr1$$hashed_password"
```

#### Маршрутизация по префиксу пути (Path Prefix)

Удаление префикса перед передачей запроса приложению:

```yaml
labels:
  - "traefik.http.routers.api.rule=Host(`example.com`) && PathPrefix(`/api`)"
  - "traefik.http.routers.api.middlewares=strip-api"
  - "traefik.http.middlewares.strip-api.stripprefix.prefixes=/api"
```

### Отладка и диагностика

#### Проверка состояния Traefik

Для анализа работы сервиса используются стандартные команды CLI (Command Line Interface) Docker:

```bash
# Просмотр журналов (логов)
docker service logs traefik-stack_traefik --follow

# Проверка списка запущенных задач
docker service ps traefik-stack_traefik
```

#### Распространенные проблемы

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Ошибка 404 | Отсутствует метка `traefik.enable=true` | Добавить метку в секцию `deploy` |
| Ошибка 502 | Неверно указан порт в `loadbalancer.server.port` | Указать внутренний порт контейнера |
| Ошибка SSL | Проблемы с записью в `acme.json` | Проверить права доступа к тому (volume) |

## Дополнительная информация

### Справочник меток (Labels)

- `traefik.enable=true` — обязательная метка для активации маршрутизации.
- `traefik.http.routers.<имя>.rule` — правило отбора трафика (например, `Host(\`domain.com\`)`).
- `traefik.http.services.<имя>.loadbalancer.server.port` — порт, на котором приложение слушает трафик внутри контейнера.

### Сравнение с альтернативными решениями

| Решение | Сложность настройки | Автоматизация SSL | Динамическое обновление |
| :--- | :--- | :--- | :--- |
| **Traefik** | Низкая | Встроена (ACME) | Да (Native) |
| **Nginx** | Средняя | Требует Certbot | Требует сторонних модулей |
| **HAProxy** | Высокая | Сложная настройка | Да (через API) |

### Смотрите также

- **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)** — теоретические основы и компоненты.
- **[Сетевое взаимодействие в Docker Swarm](./swarm_networking.md)** — детали оверлейных сетей.
- **[CI/CD с использованием Traefik](./CI_CD/overview.md)** — автоматизация развертывания.
