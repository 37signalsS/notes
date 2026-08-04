# Развертывание инфраструктуры Docker Swarm через CI/CD

## Определения

- **Инфраструктурный стек (Infrastructure Stack):** Логическая группа общекластерных сервисов (Ingress-прокси, мониторинг, логирование), управляемая как единый объект. Служит фундаментом для запуска прикладных приложений.
- **Общие сервисы (Shared Services):** Компоненты, предоставляющие функциональность нескольким стекам одновременно (например, Traefik для маршрутизации или Redis как общий кэш).
- **Внешняя оверлейная сеть (External Overlay Network):** Сеть Swarm, создаваемая вне жизненного цикла конкретного приложения. Позволяет сервисам из разных стеков взаимодействовать друг с другом.
- **[Traefik](../swarm_ingress_traefik.md):** Cloud Native Ingress-прокси. В Swarm-кластере автоматически обнаруживает новые сервисы через Docker API и настраивает маршрутизацию на основе меток (labels).

## Базовые концепции

### Архитектура системного слоя кластера

Вынос базовых компонентов в отдельный репозиторий (`infra-stack`) реализует принцип **Infrastructure as Code (IaC)** и обеспечивает:

1. **Изоляцию критических изменений:** Обновление версии Traefik или конфигурации Prometheus не требует перезапуска прикладных пайплайнов.
2. **Централизованное сетевое управление:** Все общие сети (`public`, `monitoring`, `db_net`) создаются и описываются в одном месте.
3. **Безопасность (POLP):** Доступ к репозиторию инфраструктуры ограничивается узким кругом системных администраторов/SRE.
4. **Preservation of Source IP:** Использование режима `mode: host` для портов 80/443 позволяет Traefik видеть реальные IP-адреса клиентов, что критично для логирования и систем защиты (WAF/Fail2Ban).

### Механизм автоматизации деплоя

1. **Декларативность:** Вся структура инфраструктуры описана в `docker-compose.yml` (v3.8+).
2. **Безопасное соединение:** Использование порта 2376 с **mTLS** аутентификацией для удаленного управления менеджерами.
3. **Docker Context:** Позволяет пайплайну переключаться между кластерами (staging/production) без изменения скриптов деплоя.

## Практические сценарии

### Сценарий 1: Автоматизация подготовки сетей

Общие сети должны существовать *до* того, как прикладные стеки попытаются к ним подключиться.

```bash
# Создание сети с поддержкой шифрования трафика и корректным MTU
docker network create \
  --driver overlay \
  --attachable \
  --opt encrypted \
  --opt mtu=1450 \
  public_net
```
# Результат: Сеть доступна на всех узлах Swarm для динамического подключения контейнеров.

### Сценарий 2: Конфигурация Ingress-слоя (Traefik v3)

Пример оптимального `docker-compose.yml` для высокодоступного Ingress:

```yaml
version: '3.8'
services:
  traefik:
    image: traefik:v3.1 # Используйте фиксированные версии
    command:
      - "--providers.swarm=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Редирект на HTTPS на уровне Entrypoint
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      # Включение Dashboard
      - "--api.dashboard=true"
    ports:
      - target: 80
        published: 80
        mode: host # Важно для сохранения Client IP
      - target: 443
        published: 443
        mode: host
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro" # Доступ только на чтение
    networks:
      - public_net
    deploy:
      replicas: 3
      placement:
        constraints:
          - "node.role==manager" # Traefik должен быть там, где есть Docker API
      update_config:
        parallelism: 1
        order: start-first
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 128M
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
  public_net:
    external: true
```

### Сценарий 3: Переменные GitLab CI для инфраструктуры

Для безопасного управления кластером настройте следующие переменные (тип **File**):

| Переменная | Назначение | Описание |
|:---|:---|:---|
| `DOCKER_CA` | File | Содержимое `ca.pem` |
| `DOCKER_CERT` | File | Содержимое `cert.pem` |
| `DOCKER_KEY` | File | Содержимое `key.pem` |
| `DOCKER_HOST` | Variable | Строка вида `tcp://<MANAGER_IP>:2376` |

### Сценарий 4: Пайплайн доставки инфраструктуры

Пример `.gitlab-ci.yml`, реализующий чистый деплой через Docker Context:

```yaml
deploy_infra:
  stage: deploy
  image: docker:27.x
  before_script:
    # Удаление старого контекста, если он остался от прошлых запусков
    - docker context rm swarm-prod -f || true
    - docker context create swarm-prod \
      --docker "host=$DOCKER_HOST,ca=$DOCKER_CA,cert=$DOCKER_CERT,key=$DOCKER_KEY"
    - docker context use swarm-prod
  script:
    # Авторизация в Registry для скачивания образов мониторинга/прокси
    - echo "$CI_REGISTRY_PASSWORD" | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
    # Развертывание стека
    - docker stack deploy -c docker-compose.yml infra --with-registry-auth --prune
    # Верификация деплоя
    - docker service ls --filter name=infra
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual # Инфраструктурные изменения требуют ручного подтверждения
```

## Дополнительная информация

### Безопасность инфраструктурного слоя

- **Защита сокета:** Использование `:ro` (read-only) для проброса `/var/run/docker.sock` в Traefik.
- **Firewall:** Ограничение доступа к порту 2376 (API) и портам управления Swarm (2377, 7946, 4789) только для доверенных сетей.
- **Секреты:** Используйте `docker secret` для хранения SSL-сертификатов (если они не управляются Traefik) и паролей БД.

### Диагностика типовых проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| `network public_net not found` | Сеть не была создана вручную | Запустите Сценарий 1 на одном из менеджеров. |
| `context already exists` | Повторный запуск `create` без очистки | Добавить `docker context rm -f` в `before_script`. |
| Traefik не видит сервисы | Ошибка в `constraints` | Проверьте, что Traefik запущен на узле с ролью `manager`. |
| SSL не работает | Порт 443 закрыт или лимит LE | Проверьте Firewall и логи Traefik (`docker service logs`). |
| 502 Bad Gateway | Приложение не в сети `public_net` | Проверьте секцию `networks` в Compose-файле приложения. |

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов и настройка API.
- **[Настройка Docker Context](./docker_context_setup.md)** — глубокое погружение в управление контекстами.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — детальная настройка маршрутизации.
- **[Развертывание прикладных приложений](./app_deployment.md)** — пайплайны для бизнес-логики.
- **[Лучшие практики CI/CD](./best_practices.md)** — стандарты безопасности и оптимизации.
