# Практические примеры CI/CD пайплайна в GitLab

> Этот документ предоставляет практические сценарии и примеры конфигурации `.gitlab-ci.yml` для различных этапов CI/CD в GitLab. Он дополняет общий обзор концепций CI/CD, описанный в **[CI/CD: Обзор](../../ci_cd_overview.md)**, фокусируясь на конкретных реализациях.

## Определения

- **Docker-in-Docker (dind):** Специальный образ-сервис (`docker:dind`), который позволяет запускать Docker-команды (например, `docker build`, `docker push`) внутри задачи GitLab CI, которая сама выполняется в Docker-контейнере. Подробнее: **[Обзор Runner'ов и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)**.
- **GitLab Container Registry:** Встроенный в GitLab приватный реестр (Registry) для хранения Docker-образов. Доступ к нему упрощается с помощью предопределенных переменных. Подробнее: **[Реестры Docker](../../../Docker/docker_registries.md)**.
- **`$CI_JOB_TOKEN`:** Предопределенная переменная GitLab CI, содержащая временный токен аутентификации. Используется для беспарольного доступа к GitLab Container Registry в рамках одного проекта. Подробнее: **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)**.
- **Атомарный деплой (Atomic Deployment):** Принцип деплоя, при котором обновление либо полностью успешно, либо полностью отменяется, возвращая систему в исходное стабильное состояние. В Helm это достигается флагом `--atomic`. Подробнее: **[Проверки здоровья и откат деплоя](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.

## Основные концепции

### Этап 1: Сборка (Build)

- **Задача:** Сборка Docker-образа из `Dockerfile`.
- **Тегирование:** Каждой сборке присваивается уникальный тег, обычно короткий хеш коммита (`$CI_COMMIT_SHORT_SHA`), чтобы напрямую связать образ с версией кода.

### Этап 2: Тестирование (Test)

- **Задача:** Проверка работоспособности приложения в изолированном окружении.
- **Инструмент:** Часто используется `docker-compose` для запуска тестов, требующих внешних зависимостей (например, базы данных).

### Этап 3: Публикация (Push)

- **Задача:** Публикация собранного и протестированного Docker-образа в GitLab Container Registry.
- **Условие:** Выполняется только после успешного прохождения всех предыдущих этапов, как правило, только для основной ветки (`main`).

### Этап 4: Деплой (Deploy)

- **Сценарий А (Kubernetes):** Пайплайн с помощью `helm` или `kubectl` применяет обновленную конфигурацию в кластере, указывая новый тег Docker-образа.
- **Сценарий Б (Docker-хост):** Пайплайн подключается к серверу по SSH, скачивает новый образ из Registry и перезапускает контейнер.

## Практические сценарии

### Сценарий 1: Деплой в Kubernetes с помощью Helm

#### Шаг 1: Настройка доступа Kubernetes к GitLab Registry

1. **Создайте Deploy Token в GitLab:** `Settings > Repository > Deploy Tokens`, право `read_registry`. Сохраните имя пользователя и пароль.
2. **Создайте секрет `docker-registry` в Kubernetes:**

    ```bash
    kubectl create secret docker-registry gitlab-registry-secret \
      --namespace my-app-production \
      --docker-server=registry.gitlab.com \
      --docker-username=<имя-пользователя-из-deploy-token> \
      --docker-password=<пароль-из-deploy-token>
    # → secret/gitlab-registry-secret created
    ```

    Убедитесь, что Helm-чарт использует этот секрет через `imagePullSecrets`.

#### Шаг 2: Создание файла `.gitlab-ci.yml`

```yaml
stages:
  - build
  - test
  - push
  - deploy

variables:
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  FULL_IMAGE_NAME: $CI_REGISTRY_IMAGE:$IMAGE_TAG

build_job:
  stage: build
  image: docker:24.0
  services: [docker:24.0-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    # → Login Succeeded
    - docker build -t $FULL_IMAGE_NAME .
    # → Successfully built ...

test_job:
  stage: test
  image: docker/compose:v2.24.6
  services: [docker:dind]
  script:
    - export FULL_IMAGE_NAME
    - docker-compose -p ${CI_PIPELINE_ID} up --abort-on-container-exit --exit-code-from app
    # → Container test-app-1  Exited with code 0
  after_script:
    - docker-compose -p ${CI_PIPELINE_ID} down
    # → Removing network ...

push_job:
  stage: push
  image: docker:24.0
  services: [docker:24.0-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    # → Login Succeeded
    - docker push "$FULL_IMAGE_NAME"
    # → The push refers to repository ...
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy_k8s_job:
  stage: deploy
  image: dtzar/helm-kubectl
  script:
    - echo "$KUBECONFIG" > kubeconfig.yaml
    - export KUBECONFIG=kubeconfig.yaml
    - >
      helm upgrade --install my-release-name ./path/to/chart \
        --namespace my-app-production \
        --set image.tag=$IMAGE_TAG \
        --wait --atomic --timeout 5m0s
    # → Release "my-release-name" has been upgraded. Happy Helming!
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### Сценарий 2: Деплой на Docker-хост по SSH

#### Шаг 1: Настройка переменных в GitLab CI/CD

- `PRODUCTION_SERVER_IP`: IP-адрес Docker-хоста.
- `SSH_PRIVATE_KEY`: Приватный ключ SSH для доступа к серверу.
- `SSH_USER`: Имя пользователя для подключения.

#### Шаг 2: Добавление задачи деплоя в `.gitlab-ci.yml`

```yaml
deploy_ssh_job:
  stage: deploy
  image: alpine
  before_script:
    - apk add --no-cache openssh-client
    # → OK: 5 MiB in 16 packages
    - eval $(ssh-agent -s)
    # → Agent pid 123
    - echo "$SSH_PRIVATE_KEY" | ssh-add -
    # → Identity added: (stdin)
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - ssh-keyscan $PRODUCTION_SERVER_IP >> ~/.ssh/known_hosts && chmod 644 ~/.ssh/known_hosts
  script:
    - >
      ssh $SSH_USER@"$PRODUCTION_SERVER_IP" "
        echo $CI_JOB_TOKEN | docker login -u ${CI_REGISTRY_USER} --password-stdin ${CI_REGISTRY} &&
        docker stop my-app || true &&
        docker rm my-app || true &&
        docker run --name my-app -d -p 80:8080 $FULL_IMAGE_NAME
      "
    # → Login Succeeded
    # → [container_id]
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### Сценарий 3: Автоматическое создание Merge Request, тесты и комментарий

Пайплайн, который при пуше в не-default ветку создаёт MR, запускает тесты и постит результат комментарием.

Ключевые механизмы:
- `workflow:rules` — пайплайн запускается только на feature-ветках, не на `main`.
- `artifacts:reports:dotenv` — передача `MR_IID` между задачами.
- `needs` — явная цепочка зависимостей (DAG).
- API `POST /merge_requests` / `POST .../notes` — создание MR и комментарий.
- `artifacts:reports:junit` — нативный отчёт в UI MR (без комментария).
- `GL_ACCESS_TOKEN` — project access token (masked, protected) в CI/CD variables.

```yaml
stages:
  - create-mr
  - test
  - notify

variables:
  GL_PROJECT_API: "$CI_API_V4_URL/projects/$CI_PROJECT_ID"

# Все задачи — только на не-default ветках
workflow:
  rules:
    - if: '$CI_COMMIT_BRANCH && $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH'

create-mr:
  stage: create-mr
  script:
    - |
      MR_IID=$(curl -s --request POST "$GL_PROJECT_API/merge_requests" \
        --header "PRIVATE-TOKEN: $GL_ACCESS_TOKEN" \
        --form "source_branch=$CI_COMMIT_BRANCH" \
        --form "target_branch=$CI_DEFAULT_BRANCH" \
        --form "title=Draft: $CI_COMMIT_TITLE" \
        --form "remove_source_branch=true" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('iid',''))")
      echo "MR_IID=$MR_IID" > mr.env
    # → MR_IID=42
  artifacts:
    reports:
      dotenv: mr.env  # MR_IID станет переменной в downstream задачах

run-tests:
  stage: test
  needs: [create-mr]
  script:
    - go test -v ./... 2>&1 | tee test-results.txt
    # → PASS: TestMain (0.00s)
    - echo "EXIT_CODE=${PIPESTATUS[0]}" >> test-summary.env
  artifacts:
    paths: [test-results.txt]
    reports:
      dotenv: test-summary.env
      junit: report.xml

post-comment:
  stage: notify
  needs: [create-mr, run-tests]
  script:
    - BODY=$(cat test-results.txt | tail -20)
    - |
      curl -s --request POST \
        "$GL_PROJECT_API/merge_requests/$MR_IID/notes" \
        --header "PRIVATE-TOKEN: $GL_ACCESS_TOKEN" \
        --form "body=\`\`\`\n$BODY\n\`\`\`"
    # → {"id":123,"body":"...","author":...}
```

### Сценарий 4: MR-triggered pipeline (тесты + комментарий в MR)

Пайплайн, который запускается только при создании или обновлении Merge Request, прогоняет тесты, публикует JUnit-отчёт (нативно в UI) и оставляет кастомный комментарий.

**Ключевые отличия от Сценария 3:** MR уже существует — пайплайн не создаёт его, а реагирует на событие `merge_request_event`. `$CI_MERGE_REQUEST_IID` доступен как built-in переменная.

```yaml
stages:
  - test
  - notify

workflow:
  rules:
    # Запускать только для событий Merge Request
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    # Для остальных триггеров — не запускать
    - when: never

variables:
  # Built-in переменная GitLab API
  GITLAB_API: "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID"

run-tests:
  stage: test
  script:
    - pytest --junitxml=report.xml
    # → 15 passed, 1 warning in 2.34s
  artifacts:
    reports:
      junit: report.xml  # GitLab рендерит в виджет MR
  # failing tests блокируют merge
  allow_failure: false

post-comment:
  stage: notify
  needs: [run-tests]
  script:
    - |
      curl -s --request POST "$GITLAB_API/notes" \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        --form "body=Tests passed: $(grep -c 'testsuite' report.xml 2>/dev/null || echo 0)"
    # → {"id":124,"body":"Tests passed: 1"}
  rules:
    # Комментарий — только после завершения тестов
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**JUnit-отчёт** — GitLab рендерит результаты тестов на вкладке `Tests` в MR без единой строчки API-кода. Кастомный комментарий через `POST .../notes` используется для дополнительной информации (статистика, ссылки, артефакты).

`allow_failure: false` — если тесты падают, пайплайн завершается с ошибкой, и кнопка `Merge` блокируется до исправления.

### Сценарий 5: Диагностика и ускорение медленного пайплайна

Если пайплайн занимает 40+ минут, сначала профилировать — посмотреть, что именно долго.

**Типичные виновники и их исправление:**

**1. Зависимости каждый раз с нуля.**  
Fix: `cache:` в GitLab CI по ключу `go.sum`/`package-lock.json`; в Dockerfile — `COPY go.mod go.sum && RUN go mod download` до `COPY . .`.

**2. Линейные стадии, когда можно параллельно.**  
Fix: `needs:` (DAG) — scan и validate могут идти одновременно с тестами, а не ждать своей очереди.

**3. Тесты не распараллелены.**  
Fix: `parallel: matrix:` для sharding тестов; разделить unit (быстрые) и integration (медленные) в разные стадии (stages) с разным расписанием.

**4. Docker build без layer-кэша.**  
Fix: `--cache-from registry/image:cache + --cache-to type=registry,...` (BuildKit); или Kaniko с `--cache=true`.

**5. Большой build context.**  
Fix: `.dockerignore`.

**6. Тяжёлый образ раннера.**  
Fix: использовать pre-pulled образы, пинить версии.

## Дополнительная информация

### Поведение деплоя при сбое в Kubernetes (Helm)

- Команда `helm upgrade --install --atomic` пытается задеплоить новую версию.
- Если новые поды не запускаются (например, уходят в `CrashLoopBackOff`), флаг `--wait` не дожидается их готовности, и деплой считается проваленным.
- Благодаря флагу `--atomic`, Helm автоматически выполняет откат (`helm rollback`) к предыдущей стабильной версии.
- Для конечных пользователей сбой проходит прозрачно, а пайплайн в GitLab завершается с ошибкой, давая команде четкий сигнал о проблеме.
