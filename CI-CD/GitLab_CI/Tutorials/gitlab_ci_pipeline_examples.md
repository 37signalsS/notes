# Практические примеры CI/CD пайплайнов в GitLab

**Актуально для:** GitLab 19.x

## Определения

**Quality Gates (Ворота качества)** — набор автоматизированных критериев (покрытие тестами, отсутствие уязвимостей CVE, соответствие линтам), которые должны быть выполнены для продвижения артефакта на следующий этап деплоя.

**Docker-in-Docker (dind)** — паттерн запуска Docker-демона внутри контейнера задачи. Необходим для выполнения команд `docker build` и `docker push` в изолированных средах CI.

**SBOM (Software Bill of Materials)** — формализованный список всех компонентов и зависимостей приложения, необходимый для обеспечения безопасности цепочки поставок (Supply Chain Security).

**Атомарный деплой (Atomic Deployment)** — метод обновления приложения, при котором изменения вступают в силу одновременно, а при любой ошибке происходит автоматический откат к предыдущему стабильному состоянию.

**id_tokens (OIDC)** — современный механизм генерации временных JWT-токенов для федерации идентичности (Workload Identity Federation). Позволяет аутентифицироваться в HashiCorp Vault или других системах хранения секретов без использования долгоживущих паролей.

**GitLab CI Components** — версионируемые фрагменты конфигурации пайплайна из официального каталога GitLab, заменяющие устаревшие `include:template` и обеспечивающие единообразное применение лучших практик.

## Основные концепции

### Жизненный цикл артефакта в GitLab 19.x

Современный пайплайн в GitLab строится по модульному принципу:
1.  **Подготовка (Prepare):** Динамическая генерация конфигурации, установка зависимостей с использованием кэширующих прокси.
2.  **Валидация (Quality Gates):** Параллельный запуск линтеров, статического анализа и проверки секретов.
3.  **Сборка и Аттестация:** Создание Docker-образа с генерацией SBOM и подписью артефакта (стандарт SLSA).
4.  **Многоуровневое тестирование:** Unit-тесты, интеграционные тесты в Service Containers.
5.  **Доставка (CD):** Развертывание в различные среды (Dev, Staging, Prod) с использованием GitLab Flow или Push-модели.

### Безопасность и изоляция

*   **Изоляция сред:** Разделение раннеров по тегам для разных уровней критичности (например, выделенные ноды для Prod-деплоя).
*   **Маскирование секретов:** Использование переменных типа `File` для предотвращения случайного вывода паролей в логи.
*   **Protected Runners:** Использование защищенных раннеров, которые запускают задачи только из защищенных веток.

## Практические сценарии

### Предварительные требования

Перед запуском сценариев убедитесь, что выполнены следующие условия:

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| **GitLab** | Версия 19.x | `Help -> About` в UI |
| **GitLab Runner** | Версия 19.3.x, Docker Executor | `gitlab-runner --version` |
| **Container Registry** | Включен в настройках проекта | Deploy -> Container Registry |
| **Docker-in-Docker** | Runner настроен с `privileged = true` | `config.toml` раннера |
| **Переменные** | `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`, `GITLAB_API_TOKEN` добавлены в CI/CD -> Variables | CI/CD -> Variables |
| **SSH-доступ** | SSH-ключ добавлен на целевой сервер (для сценариев деплоя) | `ssh $USER@$HOST echo ok` |

**Общие рекомендации:**
- Используйте отдельные Runner'ы для разных сред (Dev/Staging/Prod) с соответствующими тегами.
- Все секреты должны быть типа `masked` и `protected` в CI/CD Variables.
- Для продакшен-деплоев всегда используйте `when: manual` в rules.
- Используйте `default:`-блок для общих настроек (образ, теги, кэш) вместо устаревших глобальных ключевых слов.

### Сценарий 1: Multi-stage build с BuildKit и параллельным тестированием

Оптимизированная сборка Docker-образа с использованием BuildKit и параллельного запуска линтера и тестов.

```yaml
stages:
  - lint
  - test
  - build
  - deploy

default:
  tags:
    - docker-runner

variables:
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  FULL_IMAGE: $CI_REGISTRY_IMAGE:$IMAGE_TAG
  DOCKER_BUILDKIT: 1

lint:
  stage: lint
  image: python:3.13-slim
  script:
    - pip install ruff
    - ruff check src/
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

unit-tests:
  stage: test
  image: python:3.13-slim
  script:
    - pip install pytest pytest-cov
    - pytest --junitxml=report.xml --cov=src/ --cov-report=xml:coverage.xml
  artifacts:
    when: always
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

build-image:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - >
      docker build
        --build-arg BUILDKIT_INLINE_CACHE=1
        --cache-from $CI_REGISTRY_IMAGE:latest
        -t $FULL_IMAGE
        -t $CI_REGISTRY_IMAGE:latest
        -f Dockerfile.prod
        src/
    - docker push $FULL_IMAGE
    - docker push $CI_REGISTRY_IMAGE:latest
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 2: Деплой на bare metal/VM через SSH с systemd и health check

Сценарий для деплоя на выделенные серверы без использования контейнерной оркестрации. Включает проверку `known_hosts`, использование `ssh-agent`, управление systemd-сервисом и health check.

```yaml
deploy-prod:
  stage: deploy
  image: alpine:3.21
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - chmod 600 "$SSH_PRIVATE_KEY"
    - ssh-add "$SSH_PRIVATE_KEY"
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - >
      ssh $SSH_USER@"$PRODUCTION_IP" "
        docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY &&
        docker pull $FULL_IMAGE &&
        docker stop my-app || true &&
        docker rm my-app || true &&
        docker run -d --name my-app -p 5000:5000 --restart always $FULL_IMAGE
      "
    - >
      ssh $SSH_USER@"$PRODUCTION_IP" "
        sleep 5 &&
        curl -f http://localhost:5000/health || exit 1
      "
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  timeout-minutes: 30
  retry: 2
  interruptible: true
```

### Сценарий 3: Автоматизация Merge Request и нотификации через API

Позволяет автоматически создавать MR и информировать команду о статусе пайплайна.

```yaml
stages:
  - automation
  - notify

variables:
  GL_PROJECT_API: "$CI_API_V4_URL/projects/$CI_PROJECT_ID"

create_mr_auto:
  stage: automation
  image: curlimages/curl:8.11
  script:
    - |
      RESPONSE=$(curl --silent --request POST "$GL_PROJECT_API/merge_requests" \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --form "source_branch=$CI_COMMIT_BRANCH" \
        --form "target_branch=$CI_DEFAULT_BRANCH" \
        --form "title=WIP: $CI_COMMIT_TITLE" \
        --form "remove_source_branch=true")
      MR_IID=$(echo $RESPONSE | jq -r '.iid')
      echo "MR_IID=$MR_IID" > mr.env
  artifacts:
    reports:
      dotenv: mr.env
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH'

notify_mr:
  stage: notify
  image: curlimages/curl:8.11
  needs: [create_mr_auto]
  script:
    - |
      curl --request POST "$GL_PROJECT_API/merge_requests/$MR_IID/notes" \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --form "body=Пайплайн запущен. Результаты тестов будут доступны здесь: $CI_PIPELINE_URL"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH'
```

### Сценарий 4: Quality Gates (JUnit, Coverage и SBOM)

Обеспечивает визуализацию качества кода и безопасность зависимостей.

```yaml
stages:
  - test
  - scan

test_python:
  stage: test
  image: python:3.13-slim
  script:
    - pip install pytest pytest-cov
    - pytest --junitxml=report.xml --cov=src/ --cov-report=xml:coverage.xml
  artifacts:
    when: always
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
  allow_failure: false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

container_security:
  stage: scan
  image:
    name: aquasec/trivy:0.74.0
    entrypoint: [""]
  script:
    - trivy image --format json --output report.json --exit-code 0 $FULL_IMAGE
    - trivy image --format cyclonedx --output sbom.json $FULL_IMAGE
  artifacts:
    reports:
      cyclonedx: sbom.json
    paths: [report.json]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: true
```

### Сценарий 5: Динамические Parent-Child пайплайны (Монорепозитории)

Оптимизация времени выполнения за счет запуска задач только для изменившихся модулей.

```yaml
stages:
  - generate
  - trigger

generate-config:
  stage: generate
  image: python:3.13-slim
  script:
    - python3 scripts/generate-pipeline-config.py > child-pipeline.yml
  artifacts:
    paths: [child-pipeline.yml]

trigger-modules:
  stage: trigger
  trigger:
    include:
      - artifact: child-pipeline.yml
        job: generate-config
    strategy: depend
    - if: $CI_PIPELINE_SOURCE == "push"
```

### Сценарий 6: Мульти-окружейный пайплайн через общий CI-шаблон (`include:project`)

В этом сценарии описана модель организации CI/CD для множества backend-сервисов, каждый из которых подключает **общий** `.gitlab-ci.yml` из центрального CI/CD-проекта через `include:project`. Единый пайплайн управляет четырьмя средами деплоя — Development, Test/Demo, Pre-production и Production — с разграничением автоматических и ручных деплоев по веткам и ролям.

#### Архитектура

```
Центральный CI/CD-проект (ci/common-ci, ветка dev)
  └─ ci-cd/dotnet/.gitlab-ci.yml  ← workflow.rules, stages, job-шаблоны (.deploy, .grafana:notify, .cover_compare)

Сервис my-service
  └─ .gitlab-ci.yml  ← ТОЛЬКО variables + include:project
```

**Принцип работы:**
- Проект содержит минимальный `.gitlab-ci.yml` с `include`-ом из центрального репозитория и сервис-специфичными переменными.
- Центральный файл определяет все `stages`, `workflow:rules`, скрытые job-шаблоны (`.deploy`, `.grafana:notify`, `.cover_compare`) и переиспользуемые job.
- Проект переопределяет переменные, но job наследует целиком через `extends`.
- Подробнее о механизме `include:project` и версионировании через `ref` — в [Механизм `include`](../Reusable_Pipelines/include_keyword.md).

#### Модель ветвления и сред

| Ветка | Build | Test | Deploy |
| :--- | :--- | :--- | :--- |
| `feat/*` | Нет | Да | Нет |
| `fix/*` | Нет | Да | Нет |
| MR → `dev` | Нет | Да | Нет |
| `dev` | Да | Да | Development (авто) |
| `rel/*` | Да | Да | Test/Demo (авто), Pre-production (вручную), Production (вручную) |

#### 1. Минимальный `.gitlab-ci.yml` в репозитории приложения

```yaml
# В репозитории приложения
variables:
  CUSTOM_PROJECT_NAME: my-service
  CHART_NAME: my-service

include:
  - project: "ci/common-ci"
    ref: dev
    file: ci-cd/dotnet/.gitlab-ci.yml
```

`ref: dev` указывает ветку центрального CI/CD-проекта. Для production-проектов рекомендуется фиксировать `ref` на SemVer-тег (например, `v4.2.0`) — см. [Управление библиотекой шаблонов](../Reusable_Pipelines/include_keyword.md#управление-библиотекой-шаблонов).

#### 2. `workflow:rules` — что запускает пайплайн

Без `workflow:rules` GitLab создаёт пайплайн на каждый push и каждый MR — job дублируются, ресурсы раннеров тратятся впустую. Правила разрешают только значимые события:

```yaml
workflow:
  rules:
    # Запускать на MR (для code review и тестов)
    - if: $CI_MERGE_REQUEST_ID
    # Запускать при push в ветку dev
    - if: $CI_COMMIT_BRANCH == "dev"
    # Запускать на feature/fix/release ветках
    - if: $CI_COMMIT_BRANCH =~ /^feat\/.*/
    - if: $CI_COMMIT_BRANCH =~ /^fix\/.*/
    - if: $CI_COMMIT_BRANCH =~ /^rel\/.*/
    # Запускать на MR в dev или release ветку
    - if: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "dev"
    - if: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME =~ /^rel\/.*/
    # Подавить дублирующий пайплайн когда для ветки открыт MR
    - if: "$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS"
      when: never
```

Последнее правило — критично: если для ветки есть открытый MR, не запускать branch-пайплайн — запускается только MR-пайплайн. Без этого каждый push в feature-ветку с открытым MR создаёт два пайплайна. Подробнее о типичных ошибках `workflow:rules` — в [Правила запуска задач](../Advanced/workflow_rules/job_rules.md#проблемы-с-workflowrules).

#### 3. Stages

```yaml
stages:
  - sonarqube    # статический анализ, только на ветке dev
  - test         # dotnet test, на большинстве веток
  - cover_compare # проверка регрессии покрытия, на MR
  - build        # docker build + push, на dev + rel/*
  - deploy       # helm upgrade по средам, для prod — вручную
  - autotests    # интеграционные тесты через API
```

#### 4. Test job: image tag в зависимости от ветки

Версия .NET SDK отличается от проекта к проекта. Вместо отдельного job на каждую версию SDK единственный `test` job переключает тег образа, переопределяя переменные в `rules`:

```yaml
test:
  stage: test
  image: ${DOCKER_TEST_IMAGE}
  variables:
    DOCKER_TEST_IMAGE: registry.example.com/ci-images/dotnet-build:${DOCKER_TEST_IMAGE_TAG}
    DOCKER_TEST_IMAGE_TAG: net6   # значение по умолчанию
  script:
    - dotnet build -c Release src/
    - dotnet test -c Release --no-build --filter Category!~IntegrationExternal src/
    - dotnet publish -c Release -o app/ src/ --no-build
  artifacts:
    paths:
      - app/
    expire_in: 100 days
  rules:
    # Переопределить на .net8 для нужных проектов
    - if: $CI_PROJECT_PATH_SLUG =~ /^(my-api|other-api|...)/
      variables:
        DOCKER_TEST_IMAGE_TAG: net8
    # Пропустить дублирующий пайплайн на ветке с открытым MR
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_OPEN_MERGE_REQUESTS == "true"'
      when: never
    - if: $CI_COMMIT_BRANCH == "dev"
    - if: $CI_COMMIT_BRANCH =~ /^rel\/.*/
    - if: $CI_COMMIT_BRANCH =~ /^feat\/.*/
    - if: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "dev"
    - if: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME =~ /^rel\/.*/
```

> **См. также:** Полный пример выбора образа по проекту через `CI_PROJECT_PATH_SLUG` в контексте SonarQube-анализа — в [Выбор образа по проекту (rules)](../Tutorials/sonarqube_integration.md#выбор-образа-по-проекту-rules).

#### 5. Deploy jobs: по одному на среду

Все deploy job расширяют `.deploy`, где лежит сама логика `helm upgrade`. Каждый job только задаёт `APP_ENV` и переопределяет `rules`:

```yaml
deploy_dev:
  extends: .deploy
  before_script:
    - *auth_jwt
  variables:
    APP_ENV: Development
  rules:
    - if: $CI_COMMIT_BRANCH == "dev"
      # автоматически — каждый push в dev деплоится

deploy_test:
  extends: .deploy
  before_script:
    - *auth_jwt
  variables:
    APP_ENV: Test
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^rel\/.*/
      # автоматически на release ветках

deploy_demo:
  extends: .deploy
  before_script:
    - *auth_jwt
  variables:
    APP_ENV: Demo
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^rel\/.*/

deploy_pre_prod:
  extends:
    - .deploy
    - .grafana:notify   # постит аннотацию в Grafana после деплоя
  before_script:
    - *auth_jwt
  variables:
    APP_ENV: Pre-production
    ENV_PREFIX: -preprod   # суффикс имени helm release

deploy_prod:
  extends:
    - .deploy
    - .grafana:notify
  before_script:
    - *auth_jwt
  variables:
    APP_ENV: Production
  rules:
    # Для критичных сервисов: ограничить конкретными пользователями
    - if: >
        $CI_COMMIT_BRANCH =~ /^rel\/.*/ &&
        ($GITLAB_USER_LOGIN == "alice" || $GITLAB_USER_LOGIN == "bob") &&
        $CI_PROJECT_PATH_SLUG =~ /^(critical-service-1|critical-service-2)$/
      when: manual
    # Для остальных на release-ветке
    - if: >
        $CI_COMMIT_BRANCH =~ /^rel\/.*/ &&
        $CI_PROJECT_PATH_SLUG !~ /^(critical-service-1|critical-service-2)$/
      when: manual
```

С `when: manual` job не стартует сам — в UI пайплайна GitLab появляется кнопка. Деплой в Production всегда ручной: кто-то должен нажать.

**Ограничения доступа через `$GITLAB_USER_LOGIN`:** данный подход позволяет ограничить запуск production-деплоя на уровне `rules` конкретными пользователями. Это альтернатива [Protected Environments](../Tutorials/environments_and_protected_environments.md) — выбирайте подходящий вариант:

- **`$GITLAB_USER_LOGIN` в `rules`** — прост, работает в Community Edition, но не масштабируется на большие команды. Не подходит для API/Schedule-триггеров (переменная пуста).
- **Protected Environments + Approval Rules** — более надёжный, масштабируемый подход для production. Требует Premium/Ultimate.

#### 6. Проверка регрессии покрытия (`cover_compare`)

Job `cover_compare` — скрытый (с префиксом `.`); при необходимости его расширяют в конкретном проекте. Он через GitLab API сравнивает покрытие текущего пайплайна с последним успешным на целевой ветке:

```yaml
.cover_compare:
  stage: cover_compare
  image: alpine:latest
  script:
    - apk add --no-cache jq curl
    # Получить покрытие текущего пайплайна
    - latest=$(curl -sH "PRIVATE-TOKEN: $ACCESS_TOKEN_READ"
        "$CI_API_V4_URL/projects/${CI_PROJECT_ID}/pipelines/${CI_PIPELINE_ID}"
        | jq -r '.coverage // "0"' | cut -d. -f1)
    # Получить покрытие последнего успешного пайплайна на целевой ветке
    - success_id=$(curl -sH "PRIVATE-TOKEN: $ACCESS_TOKEN_READ"
        "$CI_API_V4_URL/projects/${CI_PROJECT_ID}/pipelines?ref=${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-$CI_COMMIT_REF_NAME}&status=success"
        | jq -r '.[0].id')
    - prev=$(curl -sH "PRIVATE-TOKEN: $ACCESS_TOKEN_READ"
        "$CI_API_V4_URL/projects/${CI_PROJECT_ID}/pipelines/${success_id}"
        | jq -r '.coverage // "0"' | cut -d. -f1)
    # Уведомить в любом случае — job не падает, просто отправляет сообщение
    - |
      if [ "$latest" -ge "$prev" ]; then
        msg="${CI_PROJECT_PATH_SLUG}: coverage ${latest}% >= ${prev}% OK"
      else
        msg="${CI_PROJECT_PATH_SLUG}: coverage dropped ${latest}% < ${prev}%"
      fi
      curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" -d text="$msg"
  rules:
    - if: $CI_MERGE_REQUEST_ID
  allow_failure: true
```

`allow_failure: true` — падение покрытия не блокирует MR, это только информационное сообщение. Уведомление в Telegram идёт в выделенный QA-канал.

> **См. также:** Более детальная версия `cover_compare` для .NET-проектов с `dotnet-coverage` — в [Сравнение дельты покрытия в MR (cover_compare)](../Tutorials/sonarqube_integration.md#сравнение-дельты-покрытия-в-mr-cover_compare).

**Требования:**
- `ACCESS_TOKEN_READ` — групповой токен GitLab со скоупом `read_api`. Достаточно для чтения метаданных пайплайнов, без доступа к коду.
- `TG_BOT_TOKEN`, `TG_CHAT_ID` — для уведомления в Telegram.

> **Примечание:** GitLab API возвращает `coverage` в виде числа/строки (чаще с десятичной частью). В примере выше для сравнения берётся целая часть (`cut -d. -f1`).

> **Важно:** используется `CI_MERGE_REQUEST_TARGET_BRANCH_NAME` (имя целевой ветки MR), а не `CI_COMMIT_REF_SLUG` — в MR-пайплайне `CI_COMMIT_REF_SLUG` соответствует slug **источника** ветки, а не целевой. API `pipelines?ref=` принимает имя ветки, поэтому для slug с именем ветки, содержащим специальные символы (например, `rel/1.2.3`), нужно использовать `CI_MERGE_REQUEST_TARGET_BRANCH_NAME` или `CI_COMMIT_REF_NAME`.

#### 7. Аннотация деплоя в Grafana

Каждый деплой в production и pre-production постит аннотацию в Grafana. На дашбордах появляется отметка времени деплоя — изменения метрик легко соотнести с релизами:

```yaml
.grafana:notify:
  after_script:
    - >
      curl -sX POST ${GRAFANA_URL}/api/annotations
      -H "Content-Type: application/json"
      -H "Authorization: Bearer ${GRAFANA_TOKEN}"
      -d "{
        \"text\": \"Deployed ${CI_PROJECT_PATH_SLUG} ${CI_COMMIT_BRANCH}\",
        \"tags\": [\"deployment\", \"env:${APP_ENV}\"]
      }"
```

Job, которым это нужно, расширяют и `.deploy`, и `.grafana:notify`:

```yaml
deploy_prod:
  extends:
    - .deploy
    - .grafana:notify
```

GitLab объединяет `after_script` из `.grafana:notify` в job. Аннотация появляется на каждом Grafana-дашборде как вертикальная линия с именем сервиса.

> **Важно:** конечная точка API — `/api/annotations` (множественное число). Использование `/api/annotation` (единственное число) вернёт `404 Not Found`. Аутентификация через `Authorization: Bearer ${GRAFANA_TOKEN}` требует API-токена с правом `annotations:create`.

#### 8. Валидация и проверка

1. **CI Lint:** `glab ci lint` или `POST /api/v4/ci/lint` — проверка синтаксиса.
2. **Слияние конфигурации:** `glab ci config compile` — проверка раскрытого YAML после `include` и `extends`.
3. **Проверка workflow.rules:** имитация событий через `glab ci lint --dry-run --variable CI_COMMIT_BRANCH=rel/1.2.3 --variable CI_PIPELINE_SOURCE=push`.
4. **Проверка deploy_prod:** убедиться, что `when: manual` появляется в UI только для `rel/*` веток.
5. **Grafana annotation:** после деплоя в pre-production/production проверить наличие аннотации на дашборде с тегом `deployment`.

## Архитектура Runner для Sysadmin

Для администратора инфраструктуры важно понимание конфигурации Runner на уровне хоста. GitLab Runner хранит настройки в `/etc/gitlab-runner/config.toml`.

### Ключевые параметры config.toml для Docker Executor

```toml
concurrent = 4
check_interval = 3

[[runners]]
  name = "docker-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-xxxxxxxx"
  executor = "docker"
  limit = 2
  [runners.docker]
    image = "docker:27.0"
    privileged = true
    volumes = ["/cache", "/var/run/docker.sock:/var/run/docker.sock"]
    shm_size = "1gb"
    pull_policy = ["if-not-present"]
    allowed_images = ["docker:27.0", "docker:27.0-dind", "python:3.13-slim"]
  [runners.cache]
    Type = "s3"
    Path = "runner-cache"
    Shared = true
    [runners.cache.s3]
      server_address = "s3.example.com"
      bucket_name = "gitlab-runner-cache"
      bucket_location = "us-east-1"
```

**Пояснение параметров:**
- `concurrent` — глобальное ограничение параллельных задач на менеджере.
- `limit` — максимальное количество задач, выполняемых раннером одновременно (0 = без ограничения).
- `privileged` — разрешение на запуск привилегированных контейнеров (обязательно для dind).
- `shm_size` — размер разделяемой памяти для Docker (важно для сборки больших образов).
- `pull_policy` — стратегия загрузки образов; `if-not-present` ускоряет выполнение за счет локального кэша.
- `allowed_images` — белый список образов, разрешенных для выполнения (безопасность).

### Валидация Runner

```bash
# Проверка статуса Runner'ов
gitlab-runner list
# → docker-runner: Executor=docker, Token=glrt-xxxx, Limit=2

# Проверка конфигурации
gitlab-runner verify
# → Runner is up and ready to accept jobs

# Просмотр логов Runner'а
journalctl -u gitlab-runner -f
# → time="2026-09-28T10:00:00Z" level=info msg="Starting runner" ...
```

## Валидация и проверка

Для подтверждения успешной настройки выполните следующие действия:
1.  **CI Lint:** В интерфейсе GitLab перейдите в **CI/CD > Editor** и нажмите **Validate**. Убедитесь, что синтаксис корректен и все `extends`/`include` раскрыты.
2.  **Проверка статуса пайплайна:** В интерфейсе GitLab (Build -> Pipelines) все стадии должны быть отмечены зеленым цветом.
3.  **Просмотр артефактов:** Убедитесь, что в задаче `unit-tests` появился вкладка **Tests** с результатами `pytest`.
4.  **Проверка Registry:** Перейдите в **Deploy -> Container Registry**. Там должен появиться новый образ с тегом (коротким SHA коммита).
5.  **Проверка Runner'ов:** Выполните на хосте с Runner'ом:
    ```bash
    gitlab-runner list
    # → docker-runner: Executor=docker, Token=glrt-xxxx, Limit=2
    ```
6.  **Проверка connectivity:** Убедитесь, что Runner может подключаться к GitLab:
    ```bash
    gitlab-runner verify
    # → Runner is up and ready to accept jobs
    ```

## Технические нюансы и Безопасность

### Интеграция с Vault через OIDC
С выходом GitLab 17.x и переходом к 19.x использование `id_tokens` для аутентификации в HashiCorp Vault является обязательным стандартом. Это позволяет джобе получить временный токен Vault без хранения секретов в GitLab.

### Оптимизация кэширования
Используйте `cache:key:files` для привязки кэша к файлам манифестов (например, `package-lock.json` или `uv.lock`). Это гарантирует, что кэш будет пересобираться только при изменении зависимостей.

### Использование CI/CD Components (Catalog)
В 2026 году рекомендуется заменять стандартные `include:template` на компоненты из каталога. Это обеспечивает версионирование логики пайплайна.

```yaml
include:
  - component: $CI_SERVER_FQDN/gitlab-components/sast/sast@2.1.0
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **dind: job failed to start** | Runner не в привилегированном режиме | Включите `privileged = true` в `config.toml` раннера и перезапустите его. |
| **SSH deploy hangs** | Нет ответа от `ssh-agent` | Убедитесь, что `eval $(ssh-agent -s)` выполнен в той же джобе и ключ добавлен через `ssh-add`. |
| **Coverage не отображается** | Неверный формат отчета | GitLab 19.x требует формат Cobertura XML для визуализации покрытия. |
| **Container Registry 401 Unauthorized** | Истекший или неверный токен | Используйте `CI_JOB_TOKEN` (auto-generated) вместо личных Access Tokens. |
| **SSH: Host key verification failed** | `SSH_KNOWN_HOSTS` не содержит fingerprint сервера | Выполните `ssh-keyscan -H $PRODUCTION_IP` и обновите переменную. |
| **Dynamic pipeline: child-pipeline.yml not found** | Артефакт не был создан или устарел | Убедитесь, что `generate-config` завершился успешно и `artifacts:paths` содержит `child-pipeline.yml`. |
| **Merge Request не создается автоматически** | Ветка уже имеет активный MR или нет прав | Проверьте, нет ли существующего MR через API: `GET /merge_requests?source_branch=$CI_COMMIT_BRANCH`. |
| **Cache не восстанавливается** | Неверный `key` или изменение файлов манифеста | Используйте `cache:key:files` с привязкой к `package-lock.json` или `uv.lock`. |
| **Runner: OOMKilled** | Недостаточно RAM на хосте | Увеличьте `limit` в `config.toml` или добавьте swap. Проверьте: `docker inspect <runner_container>`. |
| **cannot allocate memory (DinD)** | `shm_size` слишком мал | Установите `shm_size = "1gb"` в `config.toml` или `--shm-size=1g` в `docker run`. |
| **Permission denied (Docker)** | Runner не имеет прав на Docker Socket | Проверьте, что volume `/var/run/docker.sock:/var/run/docker.sock` смонтирован в `config.toml`. |
| **ModuleNotFoundError** | Зависимость не установлена в образе | Проверьте, добавлен ли пакет в `pyproject.toml` и выполнен ли `pip install`. |
| **Runner: job timeout** | Задача превысила `timeout-minutes` | Увеличьте таймаут или оптимизируйте скрипт (кэширование, параллелизм). |

### Sysadmin Troubleshooting

> **Примечание:** Данный раздел содержит краткие решения для типичных проблем инстанса. Для систематического troubleshooting, управления базами данных и hardening используйте:
> * **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)**
> * **[Безопасность и закрепление GitLab Server](../Advanced/gitlab_server_security_hardening.md)**
> * **[Управление базами данных GitLab](../Advanced/gitlab_database_management.md)**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Gitaly: 502 Bad Gateway** | Недостаточно RAM или перегрузка диска | Проверьте логи: `gitlab-ctl tail gitaly`. Увеличьте RAM или добавьте swap. |
| **PostgreSQL 17: connection refused** | База данных остановлена или переполнена | Проверьте статус: `gitlab-ctl status postgresql`. Проверьте disk usage: `df -h`. |
| **Sidekiq: backlog growing** | Недостаточно воркеров или блокирующие задачи | Проверьте очередь: `gitlab-rails runner 'puts Sidekiq::Queue.all.map(&:size).sum'`. |
| **SELinux/AppArmor блокирует dind** | Политика безопасности блокирует контейнеры | На RHEL/CentOS/Fedora добавьте опции `:z` или `:Z` для томов, или отключите SELinux для тестирования. |
| **Runner не подключается к GitLab** | Брандмауэр или DNS | Проверьте connectivity: `curl -I $CI_SERVER_URL`. Проверьте DNS: `nslookup gitlab.example.com`. |

## Лучшие практики (Best Practices)

**Безопасность:**
- Используйте `CI_JOB_TOKEN` для всех операций с Container Registry — токен автоматически истекает после задачи.
- Все секреты (SSH-ключи, API-токены) должны быть типа `masked` и `protected` в CI/CD Variables.
- Используйте `id_tokens` (OIDC) для интеграции с HashiCorp Vault — это стандарт 2026 года.
- Никогда не храните секреты в переменных типа `Variable` — используйте `File` для ключей.
- Ограничьте `allowed_images` в `config.toml` — разрешайте только доверенные образы.

**Производительность:**
- Используйте `cache:key:files` для привязки кэша к файлам зависимостей.
- Включите BuildKit (`DOCKER_BUILDKIT=1`) для ускорения сборки Docker-образов.
- Используйте `needs:` для параллельного запуска независимых задач.
- Для монорепозиториев используйте Parent-Child пайплайны — запускайте задачи только для изменившихся модулей.
- Используйте `default:`-блок в `.gitlab-ci.yml` для DRY и соответствия GitLab 19.x.

**Надёжность:**
- Добавьте `HEALTHCHECK` в Dockerfile для корректной работы с оркестраторами (Docker Compose, systemd).
- Используйте `timeout-minutes` к задачам для защиты от бесконечных пайплайнов.
- Пинкуйте версии образов: `docker:27.0` вместо `docker:latest`.
- Для продакшен-деплоев всегда используйте `when: manual` в rules.
- Добавьте `retry: 2` для задач, зависящих от внешних сетей (SSH, API).

**Деплой:**
- Используйте `resource_group` для предотвращения одновременного деплоя в одну и ту же среду.
- Всегда проверяйте health endpoint после деплоя (`curl -f http://localhost:5000/health`).
- Настройте `rollback` через повторный деплой предыдущего тега для быстрого отката.

## Очистка артефактов (Cleanup)

**Удаление Container Registry тегов:**
```bash
# Удаление тега через API
curl --request DELETE \
  "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/<repo_id>/tags/<tag_name>" \
  --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN"

# Очистка всех тегов кроме latest и release-*
curl -s "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/<repo_id>/tags" \
  --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" | \
  jq -r '.[] | select(.name | test("^(latest|release-)$") | not) | .name' | \
  head -n -5 | xargs -I {} curl -s --request DELETE \
  "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/<repo_id>/tags/{}" \
  --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN"
```

**Очистка кэша Runner'а:**
```bash
# На хосте с Runner'ом
gitlab-runner cache-clear
# или вручную
rm -rf /var/cache/gitlab-runner/*
```

**Очистка артефактов через GitLab UI:**
1. Перейдите в **CI/CD > Pipelines**.
2. Выберите пайплайн и нажмите **Delete**.
3. Включите **Delete associated pipeline branches** и **Keep artifacts** по необходимости.

## Мониторинг

**Базовый мониторинг Runner'а:**
```bash
# Статус Runner'а
gitlab-runner list
# → docker-runner: Executor=docker, Token=glrt-xxxx, Limit=2

# Проверка конфигурации
gitlab-runner verify
# → Runner is up and ready to accept jobs

# Просмотр логов Runner'а
journalctl -u gitlab-runner -f
# → time="2026-09-28T10:00:00Z" level=info msg="Starting runner" ...
```

**Мониторинг инфраструктуры GitLab (Sysadmin):**
```bash
# Общий статус инстанса
gitlab-ctl status
# → run: gitaly: (pid 1234) 1s
# → run: postgresql: (pid 1235) 1s
# → run: sidekiq: (pid 1236) 1s

# Логи Gitaly (хранилище репозиториев)
gitlab-ctl tail gitaly
# → time="2026-09-28T10:00:00Z" level=info msg="Received RPC" ...

# Размер очереди Sidekiq
gitlab-rails runner 'puts Sidekiq::Queue.all.map(&:size).sum'
# → 42

# Проверка диска (критично для Registry и Gitaly)
df -h /var/opt/gitlab
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       100G   85G   15G  85% /
```

> **Примечание:** Для систематического мониторинга и управления компонентами GitLab используйте **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)** и **[Sidekiq: глубинное погружение](../Advanced/gitlab_sidekiq_deep_dive.md)**.

## Граничные случаи (Edge Cases)

**Монорепозитории с динамическими пайплайнами:**
- Если `generate-pipeline-config.py` генерирует YAML с ошибкой, дочерний пайплайн не запустится. Всегда валидируйте YAML перед передачей в `trigger:include`.
- Рекомендуется добавить задачу `validate-config` перед `generate-config` для проверки синтаксиса.

**Параллельные деплои:**
- Используйте `resource_group` для предотвращения одновременного деплоя в одну и ту же среду:
```yaml
deploy_prod:
  stage: deploy
  resource_group: production
  script: ...
```

**Многоуровневые MR:**
- При быстром пуше нескольких коммитов подряд MR API может вернуть 409 Conflict. Добавьте `retry: 2` к задаче создания MR.

**Ограничения Container Registry:**
- По умолчанию GitLab ограничивает размер образа (по умолчанию ~5 ГБ). Настройте через `registry.available_size` в `gitlab.rb`.

**Одновременный доступ к Vault:**
- При параллельных задачах, запрашивающих секреты из Vault, используйте `id_tokens` с уникальным `aud` для каждой задачи, чтобы избежать конфликтов токенов.

## Дополнительная информация

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — архитектура и стадии пайплайна.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом и безопасность переменных.
- **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — установка и конфигурация Runner'ов.
- **[Родительско-дочерние пайплайны](../Advanced/Downstream_Pipelines/parent_child_pipelines.md)** — декомпозиция монорепозиториев и оптимизация.
- **[Оптимизация производительности пайплайнов](../Advanced/pipeline_performance_optimization.md)** — кэширование, параллелизм, ресурсные группы.
- **[Отладка и устранение неполадок](../Advanced/debugging_and_troubleshooting.md)** — диагностика проблем в CI/CD.
