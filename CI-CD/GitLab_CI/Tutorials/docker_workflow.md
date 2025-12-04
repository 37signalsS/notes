# Практическое руководство: CI/CD пайплайн для Docker-приложений в GitLab

Это руководство демонстрирует создание полного CI/CD пайплайна в GitLab для Docker-приложения, включающего этапы сборки образа, тестирования с `docker-compose`, публикации в GitLab Container Registry и последующего развертывания на различные окружения.

См. также:
*   [Основы GitLab CI/CD](./gitlab_ci_concepts.md)
*   [Реестры Docker](../../Docker/docker_registries.md)
*   [Docker Compose](../../Docker/docker_compose.md)

---

## 1. Общая схема пайплайна

Наш пайплайн будет состоять из следующих стадий:
1.  **`build`**: Сборка Docker-образа приложения.
2.  **`test`**: Запуск контейнера с приложением и запуск тестов для проверки его работоспособности с помощью `docker-compose`.
3.  **`push`**: Если тесты прошли успешно, загрузка (push) собранного образа в GitLab Container Registry.
4.  **`deploy`**: Развертывание приложения в целевое окружение (Docker-хост или Kubernetes).
5.  **`cleanup`**: Очистка временных ресурсов (`docker-compose` контейнеров и сетей) после завершения тестов.

---

## 2. Подготовка: `Dockerfile` и `docker-compose.yml`

Для реализации пайплайна нам понадобится `Dockerfile` для сборки образа и `docker-compose.yml` для организации тестовой среды.

### Пример `docker-compose.yml` для тестирования
```yaml
version: '3.8'
services:
  app:
    image: ${FULL_DOCKER_IMAGE}
    ports:
      - "80:80"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
  test:
    image: alpine/curl:latest
    command: ["/bin/sh", "-c", "apk add --no-cache curl && while ! curl -s app:80; do echo waiting for app; sleep 1; done"]
    depends_on:
      app:
        condition: service_healthy
```
*   **`app` сервис:** Использует Docker-образ, собранный на этапе `build`. Имя образа передается через переменную `${FULL_DOCKER_IMAGE}`.
*   **`test` сервис:** Ждет, пока сервис `app` станет работоспособным (`service_healthy`), а затем выполняет `curl` запрос для проверки доступности.

---

## 3. Настройка `.gitlab-ci.yml`

Ниже представлен полный пайплайн, включающий все стадии от сборки до развертывания.

```yaml
stages:
  - build
  - test
  - cleanup
  - push
  - deploy

variables:
  # Используем короткий SHA коммита для тега, чтобы обеспечить уникальность и трассировку
  FULL_DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build_job:
  stage: build
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - docker build -t $FULL_DOCKER_IMAGE .

test_job:
  stage: test
  image: docker/compose:latest
  services:
    - docker:dind
  script:
    - echo "Running tests with docker-compose..."
    - envsubst < docker-compose.yml > docker-compose-ci.yml
    - docker-compose -f docker-compose-ci.yml up -d
    - docker-compose -f docker-compose-ci.yml logs app
    - docker-compose -f docker-compose-ci.yml run --rm test
  after_script:
    - echo "Cleaning up docker-compose resources..."
    - envsubst < docker-compose.yml > docker-compose-ci.yml
    - docker-compose -f docker-compose-ci.yml down

push_job:
  stage: push
  image: docker:latest
  services:
    - docker:dind
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
  script:
    - echo "Pushing Docker image to registry..."
    - docker push "$FULL_DOCKER_IMAGE"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

```

### Пояснения к `.gitlab-ci.yml`

*   **`variables.FULL_DOCKER_IMAGE`**: Мы определяем полное имя образа с тегом на основе короткого хеша коммита (`$CI_COMMIT_SHORT_SHA`). Это лучшая практика по сравнению с `CI_PIPELINE_ID`, так как хеш коммита напрямую связан с версией кода.
*   **`build_job`**: Собирает образ. Здесь также добавлена аутентификация (`docker login`), так как собранный слой будет использоваться для push на следующей стадии.
*   **`test_job`**: Запускает `docker-compose` для тестирования. Важно отметить, что очистка (`docker-compose down`) вынесена в `after_script`, чтобы она выполнялась **всегда**, даже если тесты упадут. Это предотвращает засорение Runner'а.
*   **`push_job`**: Загружает образ в GitLab Container Registry. Выполняется только для `main` ветки.

---

## 4. Развертывание на отдельном Docker-хосте по SSH

Для развертывания на выделенный Docker-хост необходимо настроить переменные CI/CD в GitLab.

### Настройка переменных GitLab:

В GitLab перейдите в `Settings -> CI/CD -> Variables` и добавьте следующие переменные:

*   **`PRODUCTION_SERVER_IP`**: IP-адрес вашего Docker-хоста.
*   **`SSH_PRIVATE_KEY`**: Содержимое приватного ключа SSH для доступа к Docker-хосту.

### Добавление этапа `deploy` в `.gitlab-ci.yml`:

```yaml
deploy_docker_host:
  stage: deploy
  before_script:
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | ssh-add -
    - mkdir -p ~/.ssh
    - chmod 700 ~/.ssh
    - ssh-keyscan $PRODUCTION_SERVER_IP >> ~/.ssh/known_hosts
    - chmod 644 ~/.ssh/known_hosts
  script:
    - ssh root@"$PRODUCTION_SERVER_IP" "echo $CI_JOB_TOKEN | docker login -u ${CI_REGISTRY_USER} --password-stdin ${CI_REGISTRY}; docker stop app || true; docker rm app || true; docker run --name app -d -p 80:8080 $FULL_DOCKER_IMAGE"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## 5. Развертывание в Kubernetes с помощью Helm

Развертывание в Kubernetes требует предварительной подготовки кластера и настройки переменных.

### Подготовка кластера Kubernetes:

1.  **Настройте Service Account и получите токен** для доступа CI/CD к кластеру.
2.  **Создайте Deploy Token в GitLab** (`Settings -> Repository -> Deploy tokens`) с правами `read_registry`.
3.  **Создайте `image pull secret` в Kubernetes**, используя Deploy Token, чтобы кластер мог скачивать образы из вашего приватного Registry.
    ```bash
    kubectl create secret docker-registry your-registry-secret \
      --docker-server registry.example.com \
      --docker-username <имя_пользователя_deploy_token> \
      --docker-password <пароль_deploy_token> \
      --namespace <ваш_namespace>
    ```
4.  Убедитесь, что ваш **Helm-чарт** (`values.yaml`) использует этот секрет:
    ```yaml
    imagePullSecrets:
      - name: your-registry-secret
    ```

### Настройка переменных GitLab:
*   `K8S_API_URL`: URL API-сервера вашего кластера.
*   `K8S_CI_TOKEN`: Токен Service Account для доступа к кластеру.

### Добавление задачи `deploy` для Kubernetes в `.gitlab-ci.yml`:

```yaml
deploy_kubernetes:
  stage: deploy
  image: centosadmin/kubernetes-helm:3.1.2
  environment:
    name: production
  script:
    - kubectl config set-cluster k8s --insecure-skip-tls-verify=true --server=$K8S_API_URL
    - kubectl config set-credentials ci --token=$K8S_CI_TOKEN
    - kubectl config set-context ci --cluster=k8s --user=ci
    - kubectl config use-context ci
    - helm upgrade --install $CI_PROJECT_PATH_SLUG .helm \
      --set image.repository=$CI_REGISTRY_IMAGE \
      --set image.tag=$CI_COMMIT_SHORT_SHA \
      --wait \
      --timeout 300s \
      --atomic \
      --debug \
      --namespace my-production-ns
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## 6. Результат

После коммита этого файла, пайплайн выполнит все шаги. Если вы работаете в `main` ветке, после успешного прохождения тестов вы сможете найти опубликованный образ в разделе **Deploy > Container Registry** вашего проекта, а затем вручную запустить задачу развертывания, которая доставит приложение в целевое окружение.

