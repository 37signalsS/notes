# Использование Docker Context в CI/CD для Docker Swarm

Общие сведения о механизме контекстов см. в основном разделе **[Docker Context](../../Docker/docker_context.md)**. В данном документе рассматривается специфика использования контекстов для автоматизации развертывания в кластере Docker Swarm.

## Определения

- **[Docker Context](../../Docker/docker_context.md):** Механизм управления профилями подключения к различным Docker-хостам. Позволяет инкапсулировать параметры (адрес API, сертификаты mTLS, настройки SSH) и быстро переключаться между ними в рамках CLI.
- **Целевое окружение (Target Environment):** Конкретный экземпляр инфраструктуры (development, staging, production), на который выполняется развертывание кода или конфигураций.
- **[mTLS (mutual TLS)](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls):** Протокол взаимной проверки сертификатов, используемый контекстом для безопасной авторизации на удаленном Swarm-менеджере по порту 2376.

## Базовые концепции

### Преимущества использования в CI/CD

Использование контекстов вместо прямой передачи переменных окружения (`DOCKER_HOST`, `DOCKER_CERT_PATH`) обеспечивает:

- **Декларативность:** Параметры подключения описываются один раз при создании контекста, далее используются только короткие имена профилей.
- **Изоляция окружений:** Каждый контекст имеет собственный изолированный набор сертификатов, что исключает риск отправки команд не в тот кластер при параллельном выполнении задач.
- **Безопасность:** Снижается риск утечки `DOCKER_HOST` через логи пайплайнов, так как в основных командах деплоя фигурирует только имя контекста.
- **Унификация команд:** Пайплайны используют идентичные команды `docker stack deploy` вне зависимости от того, разворачивается ли приложение на локальный узел или удаленный продакшен.

### Схема взаимодействия компонентов

1. **Runner (CI):** Извлекает сертификаты из защищенных переменных (Secrets).
2. **CLI (Context):** Создает именованный профиль (например, `swarm-prod`), связывая адрес менеджера и пути к файлам сертификатов.
3. **API (Swarm):** Принимает команды от Runner, проверяя клиентский сертификат (mTLS).
4. **Orchestrator:** Выполняет обновление сервисов в кластере.

### Требования к инфраструктуре

- **Настроенный mTLS:** Наличие CA, серверных и клиентских сертификатов на стороне менеджера и раннера (см. **[swarm_setup.md](./swarm_setup.md)**).
- **Сетевой доступ:** Открытый порт 2376/TCP (для TLS) или 22/TCP (для SSH) на стороне Swarm Manager.
- **Версия Docker:** Рекомендуется Docker Engine и CLI версии 27.x и выше для корректной поддержки современных алгоритмов шифрования.

## Практические сценарии

### Сценарий 1: Локальная настройка и управление удаленным кластером

Для управления Swarm с рабочей станции администратора через mTLS:

1. Разместите клиентские сертификаты в директории `~/.docker/`.
2. Создайте контекст:

   ```bash
   docker context create prod-swarm \
     --docker "host=tcp://prod-manager.example.com:2376,ca=~/.docker/ca.pem,cert=~/.docker/cert.pem,key=~/.docker/key.pem"
   ```
   # → Профиль prod-swarm создан и готов к использованию

3. Активируйте контекст и проверьте связь:

   ```bash
   docker context use prod-swarm
   docker node ls
   ```
   # → Отобразится список узлов удаленного кластера

### Сценарий 2: Динамическое создание контекста в пайплайне GitLab CI

В эфемерных раннерах контекст создается "на лету" перед каждой операцией деплоя.

**Пример `.gitlab-ci.yml`:**

```yaml
deploy_prod:
  stage: deploy
  image: docker:27.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    # Удаление контекста, если он остался от предыдущих запусков (для shared runners)
    - docker context rm -f swarm-ctx || true
    - docker context create swarm-ctx \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm-ctx
  script:
    - docker stack deploy -c docker-compose.yml myapp --with-registry-auth
```

### Сценарий 3: Использование SSH контекста (Альтернатива mTLS)

Если в организации принята авторизация по SSH-ключам, Docker Context может использовать SSH-туннель:

```bash
# Создание контекста через SSH
docker context create ssh-swarm \
  --docker "host=ssh://deploy-user@swarm-manager.example.com"
```
# → Доступ к Docker API будет осуществляться через SSH (требует наличия ключа в ssh-agent)

### Сценарий 4: Верификация контекста после создания

Перед выполнением `docker stack deploy` необходимо убедиться, что контекст работает корректно. Добавьте проверку в `before_script`:

```yaml
deploy_prod:
  stage: deploy
  image: docker:27.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem && echo "$CERT_PEM" > ~/.docker/cert.pem && echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context rm -f swarm-prod || true
    - docker context create swarm-prod \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm-prod
    # Верификация: проверяем доступность кластера и роль узла
    - docker info --format '{{.Swarm.LocalNodeState}}' | grep -q "active" || (echo "ERROR: Swarm is not active" && exit 1)
    - docker node ls --format '{{.Hostname}} {{.Status}}' | head -1
  script:
    - docker stack deploy -c docker-compose.yml myapp --with-registry-auth --prune
  after_script:
    - docker context rm -f swarm-prod || true
```

**Что проверяется:**
- `docker info --format '{{.Swarm.LocalNodeState}}'` — подтверждает, что подключение к кластеру работает и Swarm активен.
- `docker node ls` — показывает список узлов (доказывает, что mTLS-аутентификация прошла успешно).

### Сценарий 5: Жизненный цикл контекста в пайплайне (after_script cleanup)

На долгоживущих раннерах (Self-hosted) контексты накапливаются между запусками. Секреты должны очищаться в `after_script`:

```yaml
deploy:
  stage: deploy
  image: docker:27.x
  variables:
    CONTEXT_NAME: "swarm-${CI_ENVIRONMENT_SLUG}"
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME} \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use ${CONTEXT_NAME}
  script:
    - docker stack deploy -c docker-compose.yml app-${CI_ENVIRONMENT_SLUG} --with-registry-auth --prune
  after_script:
    # Обязательная очистка: удаление контекста и сертификатов
    - docker context rm -f ${CONTEXT_NAME} || true
    - rm -rf ~/.docker/
```

**Важно:** На эфемерных раннерах (GitLab SaaS, GitHub Actions) `after_script` не обязателен — контейнер уничтожается после завершения. Но на Self-hosted раннерах это критично для безопасности.

### Сценарий 6: Мультиокружение через Docker Context (dev/staging/prod)

Для деплоя в несколько окружений из одного пайплайна используйте уникальные имена контекстов:

```yaml
.deploy_template: &deploy_template
  stage: deploy
  image: docker:27.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME} \
      --docker "host=${DOCKER_HOST},ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use ${CONTEXT_NAME}
    - docker info --format '{{.Swarm.LocalNodeState}}' | grep -q "active"
  script:
    - docker stack deploy -c envs/${ENVIRONMENT}/docker-compose.yml infra-${ENVIRONMENT} --with-registry-auth --prune
  after_script:
    - docker context rm -f ${CONTEXT_NAME} || true
    - rm -rf ~/.docker/

deploy_dev:
  <<: *deploy_template
  variables:
    ENVIRONMENT: dev
    CONTEXT_NAME: swarm-dev
    DOCKER_HOST: tcp://dev-manager.example.com:2376
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
      when: manual

deploy_staging:
  <<: *deploy_template
  variables:
    ENVIRONMENT: staging
    CONTEXT_NAME: swarm-staging
    DOCKER_HOST: tcp://staging-manager.example.com:2376
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual

deploy_prod:
  <<: *deploy_template
  variables:
    ENVIRONMENT: prod
    CONTEXT_NAME: swarm-prod
    DOCKER_HOST: tcp://prod-manager.example.com:2376
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
      allow_failure: false
```

### Сценарий 7: Docker Context + Buildx (кросс-платформенные сборки)

Docker Context позволяет Buildx собирать образы для нескольких архитектур (amd64, arm64) на удаленном кластере или через удаленный Docker API:

```bash
# Создание контекста для удаленного сборщика
docker context create buildkit-ctx \
  --docker "host=ssh://build-user@build-node.example.com"

# Создание buildx-инстанса, привязанного к контексту
docker buildx create --name multiarch \
  --driver docker-container \
  --use buildkit-ctx

# Сборка для двух архитектур
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myregistry/myapp:latest \
  --push .
```

**Преимущества:**
- Сборка для arm64 на x86_64 хосте (эмуляция через QEMU или нативно на ARM-нодах).
- Использование удаленного BuildKit для ускорения сборки (кэш, параллелизм).

**Важно:** Для работы `docker-container` драйвера Buildx требует, чтобы целевой Docker-хост поддерживал запуск контейнеров (не все Swarm-менеджеры подходят — лучше выделить отдельную ноду для сборки).

### Дополнительные операции и диагностика

Основные команды для обслуживания контекстов в CI:

```bash
# Список всех доступных контекстов
docker context ls

# Просмотр детальной конфигурации контекста (проверка путей и хоста)
docker context inspect swarm-ctx

# Удаление контекста после завершения задачи (гигиена пайплайна)
docker context rm swarm-ctx
```

## Дополнительная информация

### Безопасность и защита данных

- **Права доступа:** Файлы `key.pem` и приватные SSH-ключи должны иметь права доступа `600`. Команда `chmod 600 ~/.docker/*.pem` обязательна в пайплайнах.
- **Очистка данных:** При использовании долгоживущих раннеров (Self-hosted) всегда выполняйте `docker context rm` в секции `after_script`, чтобы предотвратить утечку путей к сертификатам.
- **Маскирование:** Убедитесь, что переменные `$CA_PEM`, `$CERT_PEM`, `$KEY_PEM` помечены как "Masked" в настройках CI/CD, чтобы их содержимое не попало в логи.

### Устранение типичных ошибок

| Ошибка | Причина | Способ решения |
|:---|:---|:---|
| `context already exists` | Попытка создать контекст с тем же именем на постоянном раннере | Добавить `docker context rm -f` перед созданием |
| `TLS: unknown authority` | Ошибка в сертификате CA | Проверить соответствие `ca.pem` корневому сертификату сервера |
| `permission denied` | Некорректные права на файл ключа | Применить `chmod 600` к ключу и сертификату |
| `Is the docker daemon running?` | Порт 2376 закрыт или адрес хоста неверный | Проверить доступность порта через `nc -zv <host> 2376` |
| `certificate has expired` | Сертификат клиента или сервера истек | Проверить сроки через `openssl x509 -in cert.pem -noout -dates`, при необходимости перевыпустить |
| `x509: certificate signed by unknown authority` | Сертификат подписан внутренним CA, который не добавлен в trust store | Убедиться, что `ca.pem` — корневой сертификат того же CA, которым подписан серверный сертификат |
| `Error response from daemon: context "xxx" is already in use` | Контекст активно используется другим процессом | Переключиться на `default` контекст (`docker context use default`), затем удалить |
| `error during connect: Get http://...` | Некорректный формат `DOCKER_HOST` или отсутствие `tcp://` префикса | Проверить формат: `tcp://<IP>:2376` (обязательно с `tcp://`) |

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов и настройка порта 2376.
- **[Развертывание инфраструктуры](./infra_deployment.md)** — примеры деплоя Traefik через контексты.
- **[Лучшие практики CI/CD](./best_practices.md)** — стандарты безопасности и оптимизации.
