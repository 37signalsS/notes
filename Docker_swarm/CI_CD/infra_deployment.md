# CI/CD в Docker Swarm: Развертывание инфраструктуры

## Определения

- **Инфраструктурный стек (Infrastructure Stack):** Набор общих сервисов (Traefik, базы данных, системы мониторинга), развертываемых в Docker Swarm как единый логический блок.
- **Общие сервисы (Shared Services):** Компоненты инфраструктуры, используемые несколькими приложениями одновременно (например, Ingress-прокси или централизованный реестр секретов).
- **Оверлейная сеть (Overlay Network):** Виртуальная сеть Docker Swarm, обеспечивающая сетевую связность между контейнерами на разных узлах кластера.
- **[Traefik](../swarm_ingress_traefik.md):** Динамический обратный прокси-сервер, выступающий в роли Ingress-контроллера для Swarm-кластера.

## Базовые концепции

### Архитектура инфраструктурного стека

Вынос инфраструктурных сервисов в отдельный репозиторий (`infra-stack`) обеспечивает:

- **Изоляцию изменений:** Модернизация прокси или БД не затрагивает пайплайны приложений.
- **Контроль версий:** Отдельная история конфигураций всей базовой инфраструктуры.
- **Безопасность:** Разграничение прав доступа (RBAC в GitLab/GitHub) к критическим настройкам кластера.
- **Стабильность:** Единая точка входа для трафика и централизованные сетевые политики.

### Механизм развертывания через CI/CD

1. **Декларативное описание:** Конфигурация хранится в виде Docker Compose файлов версии 3.8+.
2. **Безопасное соединение:** GitLab Runner подключается к Swarm Manager через **[mTLS](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls)** (порт 2376).
3. **Использование контекстов:** **[Docker Context](./docker_context_setup.md)** абстрагирует параметры подключения (хост, сертификаты) для CLI.
4. **Оркестрация стека:** Команда `docker stack deploy` обновляет состояние сервисов, используя механизмы Rolling Update.

## Практические сценарии

### Сценарий 1: Подготовка внешних сетей

Перед развертыванием инфраструктуры необходимо вручную или через автоматизацию создать общие overlay-сети с флагом `--attachable`, чтобы сервисы из других стеков могли к ним подключаться.

```bash
# Создание публичной сети для входящего трафика
docker network create --driver overlay --attachable public
```
# → Сеть доступна на всех узлах Swarm

### Сценарий 2: Конфигурация инфраструктурного стека (Traefik)

Пример отказоустойчивого `docker-compose.yml` для Traefik с лимитами и проверками здоровья:

```yaml
version: '3.8'
services:
  traefik:
    image: traefik:v3.6
    command:
      - "--providers.swarm=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Редирект HTTP -> HTTPS
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      # Включение Dashboard
      - "--api.dashboard=true"
    ports:
      - target: 80
        published: 80
        mode: host    # Прямая публикация на хосте для сохранения IP клиента
      - target: 443
        published: 443
        mode: host
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
    networks:
      - public
    healthcheck:
      test: ["CMD", "traefik", "healthcheck"]
      interval: 10s
      timeout: 5s
      retries: 3
    deploy:
      replicas: 2
      placement:
        constraints:
          - "node.role==manager"
      update_config:
        parallelism: 1
        order: start-first
      resources:
        limits:
          cpus: '0.50'
          memory: 256M
        reservations:
          cpus: '0.10'
          memory: 64M
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.api.rule=Host(`traefik.example.com`)"
        - "traefik.http.routers.api.service=api@internal"
        - "traefik.http.routers.api.entrypoints=websecure"
        - "traefik.http.routers.api.tls=true"
        # Middleware для защиты Dashboard (требует создания секрета)
        - "traefik.http.routers.api.middlewares=auth"
        - "traefik.http.middlewares.auth.basicauth.users=admin:$$apr1$$..."

networks:
  public:
    external: true
```

### Сценарий 3: Настройка переменных GitLab CI

Для работы пайплайна задайте переменные в **Settings → CI/CD → Variables**:

| Переменная | Тип | Назначение |
|:---|:---|:---|
| `DOCKER_HOST` | Variable | Адрес Docker API (tcp://<IP>:2376) |
| `CA_PEM` | File | Корневой сертификат CA |
| `CERT_PEM` | File | Клиентский сертификат для Runner |
| `KEY_PEM` | File | Клиентский приватный ключ |

### Сценарий 4: Пайплайн развертывания инфраструктуры

Пример `.gitlab-ci.yml` с автоматической очисткой и верификацией:

```yaml
deploy_infra:
  stage: deploy
  image: docker:27.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/key.pem
    - docker context create swarm-ctx \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm-ctx
  script:
    - docker stack deploy -c docker-compose.yml shared-infra --with-registry-auth
    - # Верификация деплоя
    - docker service ls --filter name=shared-infra
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Дополнительная информация

### Безопасность инфраструктурного слоя

- **Защита сокета:** Использование `:ro` (read-only) для проброса `/var/run/docker.sock` в Traefik.
- **Firewall:** Ограничение доступа к порту 2376 (API) и портам управления Swarm (2377, 7946, 4789) только для доверенных сетей.
- **Секреты:** Используйте `docker secret` для хранения SSL-сертификатов (если они не управляются Traefik) и паролей БД.

### Диагностика типовых проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| `network public not found` | Сеть не создана заранее | Выполнить `docker network create` на менеджере |
| `context already exists` | Повторный запуск `create` | Добавить `docker context rm swarm-ctx -f` перед созданием |
| Traefik не находит бэкенды | Приложения не в сети `public` | Проверить секцию `networks` в Compose-файлах приложений |
| 404 Not Found | Ошибка в метках (labels) | Проверить соответствие `Host()` и `entrypoints` |

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов.
- **[Docker Context для CI/CD](./docker_context_setup.md)** — управление профилями подключения.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — глубокая настройка Ingress.
- **[Развертывание приложения](./app_deployment.md)** — интеграция с инфраструктурным стеком.
- **[Лучшие практики](./best_practices.md)** — безопасность и оптимизация.
