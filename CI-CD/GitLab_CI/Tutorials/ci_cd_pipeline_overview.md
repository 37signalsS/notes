### Определения

- **Docker-in-Docker (dind):** Специальный образ-сервис (`docker:dind`), который позволяет запускать Docker-команды (например, `docker build`, `docker push`) внутри задачи GitLab CI, которая сама выполняется в Docker-контейнере.
- **GitLab Container Registry:** Встроенный в GitLab приватный реестр для хранения Docker-образов. Доступ к нему упрощается с помощью предопределенных переменных.
- **`$CI_JOB_TOKEN`:** Предопределенная переменная GitLab CI, содержащая временный токен аутентификации. Используется для беспарольного доступа к GitLab Container Registry в рамках одного проекта.
- **Атомарное развертывание (`Atomic Deployment`):** Принцип развертывания, при котором обновление либо полностью успешно, либо полностью отменяется, возвращая систему в исходное стабильное состояние. В Helm это достигается флагом `--atomic`.

### Основные концепции

Типичный CI/CD пайплайн для Docker-приложений состоит из последовательных этапов (stages).

#### Этап 1: Сборка (Build)

- **Задача:** Сборка Docker-образа из `Dockerfile`.
- **Тегирование:** Каждой сборке присваивается уникальный тег, обычно короткий хеш коммита (`$CI_COMMIT_SHORT_SHA`), чтобы напрямую связать образ с версией кода.

#### Этап 2: Тестирование (Test)

- **Задача:** Проверка работоспособности приложения в изолированном окружении.
- **Инструмент:** Часто используется `docker-compose` для запуска тестов, требующих внешних зависимостей (например, базы данных).

#### Этап 3: Публикация (Push)

- **Задача:** Публикация собранного и протестированного Docker-образа в GitLab Container Registry.
- **Условие:** Выполняется только после успешного прохождения всех предыдущих этапов, как правило, только для основной ветки (`main`).

#### Этап 4: Развертывание (Deploy)

Доставка новой версии приложения в целевое окружение.

- **Сценарий А (Kubernetes):** Пайплайн с помощью `helm` или `kubectl` применяет обновленную конфигурацию в кластере, указывая новый тег Docker-образа.
- **Сценарий Б (Docker-хост):** Пайплайн подключается к серверу по SSH, скачивает новый образ из Registry и перезапускает контейнер.

### Практические сценарии

#### Сценарий 1: Развертывание в Kubernetes с помощью Helm

##### Шаг 1: Настройка доступа Kubernetes к GitLab Registry

1. **Создайте Deploy Token в GitLab:** `Settings > Repository > Deploy Tokens`, право `read_registry`. Сохраните имя пользователя и пароль.
2. **Создайте секрет `docker-registry` в Kubernetes:**

    ```bash
    kubectl create secret docker-registry gitlab-registry-secret \
      --namespace my-app-production \
      --docker-server=registry.gitlab.com \
      --docker-username=<имя-пользователя-из-deploy-token> \
      --docker-password=<пароль-из-deploy-token>
    ```

    Убедитесь, что Helm-чарт использует этот секрет через `imagePullSecrets`.

##### Шаг 2: Создание файла `.gitlab-ci.yml`

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
  image: docker:20.10
  services: [docker:20.10-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - docker build -t $FULL_IMAGE_NAME .

test_job:
  stage: test
  image: docker/compose:latest
  services: [docker:dind]
  script:
    - export FULL_IMAGE_NAME
    - docker-compose -p ${CI_PIPELINE_ID} up --abort-on-container-exit --exit-code-from app
  after_script:
    - docker-compose -p ${CI_PIPELINE_ID} down

push_job:
  stage: push
  image: docker:20.10
  services: [docker:20.10-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - docker push "$FULL_IMAGE_NAME"
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
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

#### Сценарий 2: Развертывание на Docker-хост по SSH

##### Шаг 1: Настройка переменных в GitLab CI/CD

- `PRODUCTION_SERVER_IP`: IP-адрес Docker-хоста.
- `SSH_PRIVATE_KEY`: Приватный ключ SSH для доступа к серверу.
- `SSH_USER`: Имя пользователя для подключения.

##### Шаг 2: Добавление задачи развертывания в `.gitlab-ci.yml`

```yaml
deploy_ssh_job:
  stage: deploy
  image: alpine
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | ssh-add -
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
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### Дополнительная информация

#### Поведение развертывания при сбое в Kubernetes (Helm)

- Команда `helm upgrade --install --atomic` пытается развернуть новую версию.
- Если новые поды не запускаются (например, уходят в `CrashLoopBackOff`), флаг `--wait` не дожидается их готовности, и развертывание считается проваленным.
- Благодаря флагу `--atomic`, Helm автоматически выполняет откат (`helm rollback`) к предыдущей стабильной версии.
- Для конечных пользователей сбой проходит прозрачно, а пайплайн в GitLab завершается с ошибкой, давая команде четкий сигнал о проблеме.
