# GitLab CI: Сервисные контейнеры и services в переиспользуемых пайплайнах

**Актуально для:** GitLab CI 19.x; Docker 29.x; Kubernetes 1.37.x

## Определения

**Сервисный контейнер (Service Container)** — дополнительный контейнер, запускаемый параллельно с основным заданием (job container) и доступный по DNS-имени или алиасу. Используется для инфраструктурных зависимостей: баз данных, кэшей, очередей, Docker-демона.

**Job Container** — основной контейнер задания, в котором выполняется `script`. Имеет доступ к сервисным контейнерам через сетевые алиасы.

**Service Alias** — краткое DNS-имя, по которому сервис доступен из job container. Если alias не задан, используется имя сервиса (образ) как hostname.

**Health Check** — механизм ожидания готовности сервисного контейнера перед выполнением `script`. Настройка через `health_check` в определении сервиса. GitLab Runner ожидает доступности портов, объявленных в образе, и может использовать встроенный Docker HEALTHCHECK.

**DinD (Docker-in-Docker)** — паттерн запуска Docker-демона внутри сервисного контейнера. Используется для сборки и пуша образов из CI. Требует `privileged: true` на Runner'е или отдельный Docker Socket Mount.

## Основные концепции

### Архитектура сервисных контейнеров

```
┌──────────────────────────────────────────────────────────────┐
│  Задание: build-and-test                                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Job Container (alpine:3.24)                            │  │
│  │ - script: npm test                                     │  │
│  │ - доступ к сервисам по alias                           │  │
│  └───────────────┬────────────────────────────────────────┘  │
│                  │ сеть GitLab CI                             │
│     ┌────────────┼────────────┐                               │
│     │            │            │                               │
│     ▼            ▼            ▼                               │
│  ┌────────┐  ┌────────┐  ┌────────┐                          │
│  │ docker │  │ postgres│  │ redis  │                          │
│  │ :29-dind│  │ :18    │  │ :8     │                          │
│  │ alias: │  │ alias: │  │ alias: │                          │
│  │ docker │  │ db     │  │ cache  │                          │
│  └────────┘  └────────┘  └────────┘                          │
└──────────────────────────────────────────────────────────────┘
```

### Жизненный цикл сервисных контейнеров

1. **Запуск:** GitLab запускает сервисные контейнеры **до** запуска job container.
2. **Health check:** Если задан `health_check`, GitLab ожидает готовности сервиса перед выполнением `script`.
3. **Выполнение:** Job container запускается и получает доступ к сервисам по alias.
4. **Остановка:** После завершения задания все сервисные контейнеры останавливаются и удаляются.

### Сравнение подходов к сборке образов

| Подход | Изоляция | Привилегии Runner'а | Безопасность | Производительность |
| :--- | :--- | :--- | :--- | :--- |
| **Docker-in-Docker** | Низкая | `privileged: true` | Низкая (Container Escape риск) | Средняя |
| **Docker Socket Mount** | Низкая | Монтирование `/var/run/docker.sock` | Низкая (доступ к хосту) | Высокая |
| **Kaniko** | Высокая | Без привилегий | Высокая | Средняя |
| **Buildah** | Высокая | Без привилегий | Высокая | Средняя |

### Типичные сервисы в reusable templates

| Сервис | Образ | Алиас | Назначение |
| :--- | :--- | :--- | :--- |
| **Docker DinD** | `docker:29.8-dind` | `docker` | Сборка и пуш образов |
| **PostgreSQL** | `postgres:18` | `db` | Интеграционные тесты |
| **Redis** | `redis:8` | `cache` | Кэширование в тестах |
| **Kafka** | `apache/kafka:4.3` | `kafka` | Тестирование consumer/producer |
| **Elasticsearch** | `docker.elastic.co/elasticsearch/elasticsearch:9.5` | `es` | Тестирование поиска |
| **MinIO** | `minio/minio:latest` | `minio` | Тестирование S3-совместимого хранилища |

## Практические сценарии

### Предварительные условия

Для использования сервисных контейнеров в reusable пайплайнах необходимо:
- **Runner:** Docker executor с доступом к Docker-демону (для DinD) или Kubernetes executor с поддержкой sidecar-контейнеров.
- **Сеть:** Сервисы должны быть доступны из job container по alias. В Kubernetes это обеспечивается через CNI.
- **Health checks:** Для длительно запускающихся сервисов (БД, Elasticsearch) настройте `health_check` с явной проверкой порта или HTTP-эндпоинта.
- **Безопасность:** Для DinD требуется `privileged: true` — используйте отдельный pool Runner'ов, изолированный от production.

### Сценарий 1: DinD для сборки образов в reusable template

```yaml
# shared/ci-templates/templates/docker-build.yml
.docker-build-base:
  stage: build
  image: docker:29.8
  services:
    - name: docker:29.8-dind
      alias: docker
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    DOCKER_DRIVER: overlay2
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```

**Использование в проекте:**
```yaml
include:
  - project: 'shared/ci-templates'
    file: '/templates/docker-build.yml'
    ref: 'v2.1.0'

build-app:
  extends: .docker-build-base
  variables:
    DOCKER_BUILDKIT: "1"
```

> **Важно:** `DOCKER_TLS_CERTDIR: "/certs"` обязательно для DinD с TLS. Если задать `DOCKER_TLS_CERTDIR: ""`, Docker отключит TLS и будет использовать порт 2375 без шифрования.

### Сценарий 2: База данных для интеграционных тестов

```yaml
# shared/ci-templates/templates/test-with-db.yml
.test-with-postgres:
  stage: test
  image: python:3.12-alpine
  services:
    - name: postgres:18
      alias: db
      health_check:
        test: ["pg_isready", "-U", "postgres"]
        interval: 2s
        timeout: 5s
        retries: 10
  variables:
    DATABASE_URL: "postgresql://postgres:postgres@db:5432/test_db"
  before_script:
    - pip install -r requirements.txt
  script:
    - pytest tests/integration
```

**Использование в проекте:**
```yaml
include:
  - project: 'shared/ci-templates'
    file: '/templates/test-with-db.yml'
    ref: 'v1.2.0'

integration-tests:
  extends: .test-with-postgres
  variables:
    DATABASE_URL: "postgresql://testuser:testpass@db:5432/myapp_test"
```

### Сценарий 3: Redis для кэширования в тестах

```yaml
# shared/ci-templates/templates/test-with-redis.yml
.test-with-redis:
  stage: test
  image: node:22-alpine
  services:
    - name: redis:8-alpine
      alias: cache
      health_check:
        test: ["redis-cli", "ping"]
        interval: 1s
        timeout: 3s
        retries: 5
  variables:
    REDIS_URL: "redis://cache:6379"
  script:
    - npm ci
    - npm run test:with-cache
```

### Сценарий 4: Несколько сервисов одновременно

```yaml
# shared/ci-templates/templates/full-stack-tests.yml
.full-stack-tests:
  stage: test
  image: python:3.12-alpine
  services:
    - name: postgres:18
      alias: db
      health_check:
        test: ["pg_isready", "-U", "postgres"]
        interval: 2s
        timeout: 5s
        retries: 10
    - name: redis:8-alpine
      alias: cache
      health_check:
        test: ["redis-cli", "ping"]
        interval: 1s
        timeout: 3s
        retries: 5
    - name: rabbitmq:4.3-management
      alias: rabbit
      health_check:
        test: ["rabbitmq-diagnostics", "ping"]
        interval: 2s
        timeout: 5s
        retries: 10
  variables:
    DATABASE_URL: "postgresql://postgres:postgres@db:5432/test_db"
    REDIS_URL: "redis://cache:6379"
    RABBITMQ_URL: "amqp://guest:guest@rabbit:5672/"
  script:
    - pytest tests/integration --cov=app
```

### Сценарий 5: DinD с Kaniko-альтернативой в reusable template

```yaml
# shared/ci-templates/templates/docker-build.yml
.docker-build-dind:
  stage: build
  image: docker:29.8
  services:
    - name: docker:29.8-dind
      alias: docker
  variables:
    DOCKER_TLS_CERTDIR: "/certs"

.docker-build-kaniko:
  stage: build
  image: ghcr.io/osscontainertools/kaniko:v1.28.4
  entrypoint: [""]
  variables:
    KANIKO_CACHE: "true"
    KANIKO_CACHE_REPO: "$CI_REGISTRY_IMAGE/cache"

# Проект выбирает стратегию
build-dind:
  extends: .docker-build-dind
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"

build-kaniko:
  extends: .docker-build-kaniko
  script:
    - /kaniko/executor --context "$CI_PROJECT_DIR" --destination "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
```

### Сценарий 6: Health check для длительно запускающихся сервисов

```yaml
# shared/ci-templates/templates/test-with-elasticsearch.yml
.test-with-elasticsearch:
  stage: test
  image: python:3.12-alpine
  services:
    - name: docker.elastic.co/elasticsearch/elasticsearch:9.5
      alias: es
      health_check:
        test: ["curl", "-f", "http://es:9200/_cluster/health"]
        interval: 5s
        timeout: 10s
        retries: 30
  variables:
    ELASTICSEARCH_URL: "http://es:9200"
  script:
    - pip install -r requirements.txt
    - pytest tests/search
```

### Сценарий 7: Взаимодействие services с extends и !reference

Сервисы в reusable templates наследуются через `extends`, но массивы `services` полностью заменяются, как и `script`.

```yaml
# templates/base.yml
.base-test:
  image: python:3.12-alpine
  services:
    - name: postgres:18
      alias: db
  variables:
    DATABASE_URL: "postgresql://postgres:postgres@db:5432/test_db"

# Проект: добавление второго сервиса
# ПРОБЛЕМА: services полностью заменятся, db потеряется
integration-tests:
  extends: .base-test
  services:
    - name: redis:8-alpine
      alias: cache

# РЕШЕНИЕ 1: дублировать полный список сервисов
integration-tests-fixed:
  extends: .base-test
  services:
    - name: postgres:18
      alias: db
    - name: redis:8-alpine
      alias: cache

# РЕШЕНИЕ 2: использовать !reference для явного включения базовых сервисов
.base-services:
  services:
    - name: postgres:18
      alias: db

integration-tests-with-reference:
  extends: .base-test
  services:
    - !reference [.base-services, services]
    - name: redis:8-alpine
      alias: cache
```

## Валидация и отладка

### Диагностические команды

```bash
# Проверка доступности сервиса из job container
docker run --rm alpine:3.24 ping -c 3 db

# Проверка порта сервиса
docker run --rm alpine:3.24 nc -zv db 5432

# Проверка DNS-резолвинга
docker run --rm alpine:3.24 nslookup db

# Проверка health check
docker run --rm alpine:3.24 curl -f http://es:9200/_cluster/health
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` к сервису | Сервис не готов (health check провален или не настроен) | Увеличьте `retries` или `interval` в `health_check`. Проверьте alias. |
| `Could not resolve host` | Неверный alias или DNS-проблема | Проверьте имя alias в `services`. Убедитесь, что сервис запущен. |
| `Service не виден из шаблона` | `extends` полностью заменяет массив `services` | Дублируйте полный список сервисов в дочернем задании. |
| `privileged: true` не работает | Runner не поддерживает privileged | Используйте отдельный pool Runner'ов с `privileged = true` в config.toml. |
| `DinD: Cannot connect to Docker daemon` | `DOCKER_TLS_CERTDIR` не настроен или сертификаты не готовы | Установите `DOCKER_TLS_CERTDIR: "/certs"` и добавьте `health_check` для DinD. |
| `Health check timeout` | Сервис слишком долго запускается | Увеличьте `timeout` и `retries`. Проверьте ресурсы Runner'а (CPU/RAM). |
| `Service не exposes порты, но health_check зависает` | Runner не может определить готовность сервиса | Укажите `ports` в определении сервиса или используйте внешний curl/nc в `health_check`. |
| `UI-переменная не доступна в сервисе` | Переменная не объявлена в YAML | Переобъявите UI-переменную в `.gitlab-ci.yml` для передачи в сервис. |

## Особенности и ограничения

1. **Массив `services` не сливается через `extends`.** Полная замена, как и `script`. Для добавления сервиса дублируйте весь список.
2. **Сервисы не поддерживаются в компонентах CI/CD Catalog.** Глобальный ключ `services` запрещён в компонентах. Используйте шаблоны `include:project` с `extends` для сервисных зависимостей.
3. **DinD и Kubernetes:** На Kubernetes DinD работает через privileged pod. Убедитесь, что namespace имеет политику `baseline` или выше, и Pod Security Admission не блокирует `privileged`.
4. **Сеть:** Все сервисы и job container находятся в одной сети. Сервисы доступны по alias из job container, но не из других сервисов по умолчанию (требуется явное указание `links`).
5. **Ограничение количества сервисов:** На практике рекомендуется не более 3-5 сервисов на задание. Большее количество замедляет запуск и увеличивает потребление ресурсов Runner'а.
6. **Верификация готовности:** Runner ожидает открытия портов, объявленных в образе сервиса. Если сервис не exposes порты, Runner считает его готовым сразу. Для сервисов без встроенного HEALTHCHECK используйте `health_check` с внешней проверкой (curl, nc).

## Преимущества и недостатки

| Преимущество | Описание |
| :--- | :--- |
| **Изоляция зависимостей** | Каждое задание получает "свою" БД/кэш, нет конфликтов между параллельными задачами. |
| **Воспроизводимость** | Версия сервиса зафиксирована в образе — нет "работает на моей машине". |
| **Стандартизация** | Один шаблон с сервисами используется во всех проектах. |

| Недостаток | Описание | Решение |
| :--- | :--- | :--- |
| **Производительность** | Запуск сервисов добавляет 5-30 секунд к заданию | Используйте `health_check` для быстрого detection ready. |
| **Потребление ресурсов** | Каждый сервис потребляет CPU/RAM Runner'а | Ограничьте количество сервисов, используйте lightweight-образы. |
| **DinD security** | `privileged: true` увеличивает поверхность атаки | Переходите на Kaniko/Buildah где возможно. |
| **Сетевая сложность** | Aliases, порты, DNS могут конфликтовать | Используйте явные alias и проверяйте connectivity. |

## Конфигурация сервисных контейнеров

Сервисный контейнер может принимать дополнительные параметры, расширяющие стандартное поведение Docker.

```yaml
services:
  - name: postgres:18
    alias: db
    entrypoint: ["/bin/bash", "-c"]
    command: ["docker-entrypoint.sh", "postgres"]
    variables:
      POSTGRES_PASSWORD: "secret"
      POSTGRES_DB: "test_db"
    pull_policy: if-not-present
    ports:
      - "5432"
```

| Параметр | Назначение |
| :--- | :--- |
| `name` | Полное имя образа сервиса. Обязателен при указании дополнительных опций. |
| `alias` | DNS-имя для доступа из job container. Если не задан, используется имя образа. |
| `entrypoint` | Переопределяет entrypoint образа. Полезно для кастомных скриптов инициализации. |
| `command` | Переопределяет CMD образа. Позволяет передавать аргументы сервису. |
| `variables` | Переменные окружения, передаваемые в сервис. Доступны в `.gitlab-ci.yml`, UI-переменные по умолчанию не передаются. |
| `pull_policy` | Стратегия загрузки образа: `always`, `if-not-present`, `never`. |
| `ports` | Список портов, которые сервис exposes. Runner использует их для проверки готовности. |

### Отладка сервисов

Включите логирование сервисных контейнеров для диагностики:

```yaml
job:
  variables:
    CI_DEBUG_SERVICES: "true"
  services:
    - name: postgres:18
      alias: db
```

`CI_DEBUG_SERVICES` доступен начиная с GitLab Runner 15.7. При включении в лог задания выводятся логи всех сервисных контейнеров.

### Передача переменных в сервисы

Переменные, объявленные в `.gitlab-ci.yml`, автоматически передаются во все сервисные контейнеры. UI-переменные (Protected, Masked) по умолчанию не передаются, так как сервисы не являются доверенными. Для передачи UI-переменной переобъявите её в YAML:

```yaml
variables:
  SA_PASSWORD_YAML_FILE: $SA_PASSWORD_UI
```

## Best Practices

1. **Явные alias:** Всегда задавайте `alias` для сервисов — это делает шаблон предсказуемым и упрощает отладку.
2. **Health checks:** Настраивайте `health_check` для всех сервисов, кроме самых быстрых (Redis). Это исключает race condition.
3. **Lightweight образы:** Используйте Alpine-версии сервисов где возможно (`redis:8-alpine`, `postgres:18-alpine`).
4. **DinD только где нужно:** Для сборки образов предпочитайте Kaniko. DinD оставьте для legacy-сценариев.
5. **Сериализация:** Если несколько заданий через общий шаблон работают с одним сервисом (например, общая БД), добавьте `resource_group`.
6. **Версионирование:** Фиксируйте версии сервисов в шаблонах (`postgres:18`, а не `postgres:latest`).
7. **Расширение services через !reference:** При необходимости добавить сервис к базовому шаблону используйте `!reference` для явного включения списка сервисов, чтобы избежать дублирования полного массива.

## Дополнительная информация

### Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — архитектурные подходы.
- **[Механизм extends](./extends_keyword.md)** — наследование и замена массивов (`services` полностью замещаются).
- **[Механизм !reference](./reference_and_yaml_anchors.md)** — точечная вставка фрагментов.
- **[Сборка образов: Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — альтернатива DinD.
- **[Сканирование безопасности в GitLab CI](../Concepts/gitlab_ci_security_scanning.md)** — SAST, DAST, Secret Detection.
- **[Раннеры и исполнители](../Advanced/gitlab_ci_runners_executors.md)** — Docker, Kubernetes, Shell executor.
- **[Матричные сборки](../Advanced/workflow_rules/matrix_builds_and_serialization.md)** — `parallel:matrix`, `resource_group`.

### Внешние ресурсы

- [GitLab Docs: Services](https://docs.gitlab.com/ee/ci/services/)
- [GitLab Docs: Docker-in-Docker](https://docs.gitlab.com/ee/ci/docker/using_docker_build.html)
- [GitLab Docs: Health checks](https://docs.gitlab.com/ee/ci/services/#health_check)
