# Руководство по развертыванию Full Stack с GitLab CI/CD

## 1. Базовая настройка GitLab CI/CD

1.  **Этапы (stages):** `build`, `test`, `deploy`.
2.  **Рабочие процессы (jobs):** `build`, `unit`, `lint`, `deploy`.
3.  **Порядок выполнения:** `build` выполняется первым.
4.  **Параллельное выполнение:** `unit` и `lint` должны выполняться параллельно в рамках этапа `test`.
5.  **Обязательный `lint`:** Процесс `lint` должен выполняться всегда, даже если предыдущий шаг завершился неудачей (используйте директиву `when`).
6.  **Ручной `deploy`:** Этап `deploy` выполняется последним, и его job запускается только вручную (используйте `when`).
7.  **Команда скрипта:** В качестве `script` укажите команду `echo $CI_JOB_NAME`.

### Пример начального `.gitlab-ci.yml`:

```yaml
build:
  script:
    - docker build -t $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID .
```

## 2. Использование Docker Compose для тестирования

### Пример `.gitlab-ci.yml` с этапами и Docker Compose для теста:

```yaml
stages:
  - build
  - test
  - cleanup
  - push

build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID .

test:
  stage: test
  image:
    name: docker/compose:1.23.2
    entrypoint: [""]
  script:
    - docker-compose -p "$CI_PROJECT_NAME"_"$CI_PIPELINE_ID" up --abort-on-container-exit --exit-code-from test --quiet-pull

cleanup:
  stage: cleanup
  image:
    name: docker/compose:1.23.2
    entrypoint: [""]
  script:
    - docker-compose -p "$CI_PROJECT_NAME"_"$CI_PIPELINE_ID" down
  when: always

push:
  stage: push
  before_script:
    - docker login -u gitlab-ci-token -p $CI_BUILD_TOKEN $CI_REGISTRY
  script:
    - docker push $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID
  only:
    - main
```

### Пример `docker-compose.yml`:

```yaml
services:
  app:
    image: $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID
    ports:
      - "8080:8080"
  test:
    image: curlimages/curl:7.73.0
    command: /bin/sh -c "sleep 10 && curl -s http://app:8080/ -i -vvv"
```

## 3. Развертывание на отдельном Docker-хосте

### Настройка переменных GitLab:

В GitLab перейдите в `Settings -> CI/CD -> Variables` и добавьте следующие переменные:

*   **`PRODUCTION_SERVER_IP`**: IP-адрес вашего Docker-хоста (например, 172.15.5.6).
*   **`SSH_PRIVATE_KEY`**: Содержимое приватного ключа SSH для доступа к Docker-хосту. Получить можно командой `cat ~/.ssh/id_rsa` на хосте (`node-1.<ваш номер студента>`).

### Добавление этапа `deploy` в `.gitlab-ci.yml`:

```yaml
stages:
  - build
  - test
  - cleanup
  - push
  - deploy # Новый этап

deploy:
  stage: deploy
  before_script:
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | ssh-add -
    - mkdir -p ~/.ssh
    - chmod 700 ~/.ssh
    - ssh-keyscan $PRODUCTION_SERVER_IP >> ~/.ssh/known_hosts
    - chmod 644 ~/.ssh/known_hosts
  script:
    - ssh root@"$PRODUCTION_SERVER_IP" "echo $CI_BUILD_TOKEN | docker login -u ${CI_REGISTRY_USER} --password-stdin ${CI_REGISTRY}; docker stop app; docker rm app; docker run --name app -d -p 80:8080 $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID"
  only:
    - main
```

## 4. Развертывание в Kubernetes

### Подготовка кластера Kubernetes:

1.  **Доступ к `master-1`**: `ssh root@master-1.<ваш номер логина>`
2.  **Клонирование репозитория с материалами**: `git clone git@gitlab.slurm.io:edu/ci-cd/cicd.git`
3.  **Запуск скрипта подготовки**:
    ```bash
    cd cicd/practice/07.gitlab_ci_file
    ./setup.sh <номер своего логина>-cicd-app production
    ```
    Сохраните токен, который выдаст скрипт.
4.  **Настройка переменной GitLab `K8S_CI_TOKEN`**: В `Settings -> CI/CD -> Variables` добавьте токен, полученный на предыдущем шапе.
5.  **Создание Deploy Token в GitLab**: В `Settings -> Repository -> Deploy tokens` создайте новый токен с именем `k8s-pull-token` и галочкой `read_registry`. Сохраните его имя пользователя и пароль.
6.  **Создание `image pull secret` в Kubernetes**: На `master-1` выполните:
    ```bash
    kubectl create secret docker-registry cicd-gitlab-registry \
      --docker-email 'student@slurm.io' \
      --docker-server registry.slurm.io \
      --docker-username '<имя пользователя deploy token>' \
      --docker-password '<пароль deploy token>' \
      --namespace <номер своего логина>-cicd-app-production
    ```
7. **Получение K8S_API_URL**: На master-1 выполните `kubectl cluster-info`. Адрес master-1 будет в выводе.

### Добавление этапа `deploy` для Kubernetes в `.gitlab-ci.yml`:

```yaml
variables:
  K8S_API_URL: https://172.<xx>.<yyy>.2:6443 # Замените на адрес master-1

stages:
  - build
  - test
  - cleanup
  - push
  - deploy

build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID .

test:
  stage: test
  image:
    name: docker/compose:1.23.2
    entrypoint: [""]
  script:
    - docker-compose -p "$CI_PROJECT_NAME"_"$CI_PIPELINE_ID" up --abort-on-container-exit --exit-code-from test --quiet-pull

cleanup:
  stage: cleanup
  image:
    name: docker/compose:1.23.2
    entrypoint: [""]
  script:
    - docker-compose -p "$CI_PROJECT_NAME"_"$CI_PIPELINE_ID" down
  when: always

push:
  stage: push
  before_script:
    - docker login -u gitlab-ci-token -p $CI_BUILD_TOKEN $CI_REGISTRY
  script:
    - docker push $CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME:$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID
  only:
    - main

deploy:
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
      --set image=$CI_REGISTRY/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME \
      --set imageTag=$CI_COMMIT_REF_SLUG.$CI_PIPELINE_ID \
      --wait \
      --timeout 300s \
      --atomic \
      --debug \
      --namespace $CI_PROJECT_PATH_SLUG-$CI_ENVIRONMENT_NAME
  only:
    - main
```

### Настройка Helm Chart (`.helm/values.yaml`):

Для развертывания с Helm v3 требуется Helm Chart. Скопируйте каталог `.helm` в корень проекта. Отредактируйте файл `.helm/values.yaml`, изменив `ingress.host`:

```yaml
ingress:
  host: app.s<номер своего логина>.edu.slurm.io # Замените на свой номер логина
```

---

## Практический пример: Многоэтапный CI/CD для Go-приложения в Kubernetes

### Задача

Необходимо переписать существующий pipeline, чтобы он соответствовал следующим требованиям:

1.  **Валидация кода**:
    *   Запуск линтеров для исходного кода.
    *   Проверка корректности форматирования `.yml` файлов.
    *   Запуск unit-тестов.

2.  **Сборка и тестирование**:
    *   После успешной валидации — запуск e2e-тестов.

3.  **Сборка Docker-образа**:
    *   Приложение упаковывается в Docker-контейнер с тегом `${CI_COMMIT_SHORT_SHA}`.

4.  **Развертывание по веткам**:
    *   **Feature-ветки**: Deploy на `dev`-окружение.
    *   **`main`-(master)ветка**: Deploy на `staging`-окружение.

5.  **Релиз по тегу**:
    *   Если в `main`-ветке создается тег, ранее собранный образ скачивается, перетегируется версией из Git-тега и развертывается в `production`.

### 1. Подготовка окружения в Kubernetes

На мастер-ноде кластера необходимо создать `namespaces` и секреты для доступа к Docker Registry:

```bash
# 1. Создание namespaces
kubectl create ns dev
kubectl create ns staging
kubectl create ns production

# 2. Создание секрета для доступа к registry.slurm.io в каждом namespace
# (замените <...> на ваши данные)
kubectl create secret docker-registry slurm-registry \
  --docker-server=registry.slurm.io \
  --docker-username=<user> \
  --docker-password=<password> -n dev

kubectl create secret docker-registry slurm-registry \
  --docker-server=registry.slurm.io \
  --docker-username=<user> \
  --docker-password=<password> -n staging

kubectl create secret docker-registry slurm-registry \
  --docker-server=registry.slurm.io \
  --docker-username=<user> \
  --docker-password=<password> -n production

# 3. Настройка прав для CI/CD
kubectl create clusterrolebinding ci --clusterrole=cluster-admin --serviceaccount=default:default
```

### 2. Настройка переменных в GitLab CI

Для авторизации в кластере из пайплайна, необходимо сохранить токен и URL API в переменных CI/CD (`Settings -> CI/CD -> Variables`):

1.  **`K8S_CI_TOKEN`**:
    *   Получите токен:
        ```bash
        kubectl get secrets -o jsonpath='{.items[?(@.metadata.annotations.kubernetes\.io/service-account\.name=="default")].data.token}' | base64 -d
        ```
    *   Создайте переменную `K8S_CI_TOKEN` в GitLab со значением этого токена.

2.  **`K8S_API_URL`**:
    *   Получите URL:
        ```bash
        kubectl config view -o jsonpath='{.clusters[].cluster.server}'
        ```
    *   Создайте переменную `K8S_API_URL` со значением этого URL.

### 3. Структура `.gitlab-ci.yml`

Пайплайн будет состоять из следующих этапов:

```yaml
stages:
  - validate
  - build
  - docker
  - deploy
  - retag
  - release
```

#### Этап `validate`

Состоит из трех параллельных задач для быстрой проверки качества кода. Запускается на всех коммитах, кроме тегированных.

```yaml
.no_tags_rules: &no_tags_rules
  rules:
    - if: '$CI_COMMIT_TAG'
      when: never
    - when: on_success

lint-yaml:
  stage: validate
  image: pipelinecomponents/yamllint
  script:
    - yamllint .
  <<: *no_tags_rules

lint-go:
  stage: validate
  image: golangci/golangci-lint:v1.55
  script:
    - golangci-lint run
  <<: *no_tags_rules

unit-tests:
  stage: validate
  image: golang:1.21
  script:
    # Важно: исправьте ошибку в коде, чтобы тесты проходили
    # verybigdataapp/pkg/bigdatafuncs/funcs.go
    - cd verybigdataapp && go test
  <<: *no_tags_rules
```

#### Этап `build`

Компиляция бинарного файла и запуск e2e-тестов. Бинарник сохраняется в артефактах для следующего этапа.

```yaml
build-and-e2e:
  stage: build
  image: golang:1.21
  script:
    - cd verybigdataapp
    - go build -o /tmp/verybigdataapp
    - /tmp/verybigdataapp &
    - sleep 3
    - |
      RESULT=$(curl "localhost:58080/?a=6&b=4")
      if [[ "$RESULT" != "10" ]]; then
        echo "E2E test failed: expected 10, got $RESULT"
        exit 1
      fi
  artifacts:
    paths:
      - /tmp/verybigdataapp
  <<: *no_tags_rules
```

#### Этап `docker`

Сборка Docker-образа с использованием артефакта из предыдущей задачи.

```yaml
include:
  - local: '/.gitlab-ci-templates/docker.yml' # Путь к вашему шаблону Docker

build-docker:
  stage: docker
  extends: .build_docker_image # Имя задачи из шаблона
  variables:
    DOCKER_HOST: ""
  services: []
  tags:
    - docker
  <<: *no_tags_rules
```

#### Этап `deploy`

Развертывание приложения в `dev` или `staging` в зависимости от ветки.

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:1.21
  script:
    - |
      if [[ "$CI_COMMIT_REF_NAME" == "main" ]]; then
        ENVIRONMENT=staging
      else
        ENVIRONMENT=dev
      fi
    - echo "Deploying to $ENVIRONMENT"
    # Настройка kubeconfig
    - kubectl config set-cluster k8s --insecure-skip-tls-verify=true --server=$K8S_API_URL
    - kubectl config set-credentials ci --token=$K8S_CI_TOKEN
    - kubectl config set-context ci --cluster=k8s --user=ci
    - kubectl config use-context ci
    # Подстановка переменных и деплой
    - sed -i "s|__ENVIRONMENT__|${ENVIRONMENT}|; s|__CI_REGISTRY_IMAGE__|${CI_REGISTRY_IMAGE}|; s|__IMAGE_TAG__|${CI_COMMIT_SHORT_SHA}|" manifests/*.yml
    - kubectl apply -n $ENVIRONMENT -f manifests/
  <<: *no_tags_rules
```

#### Этапы `retag` и `release` (для Production)

Эти задачи выполняются только при создании Git-тега в `main`.

```yaml
.tags_only_rules: &tags_only_rules
  rules:
    - if: '$CI_COMMIT_TAG'
      when: on_success
    - when: never

retag-for-release:
  stage: retag
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker pull $CI_REGISTRY_IMAGE:${CI_COMMIT_SHORT_SHA}
    - docker tag $CI_REGISTRY_IMAGE:${CI_COMMIT_SHORT_SHA} $CI_REGISTRY_IMAGE:${CI_COMMIT_TAG}
    - docker push $CI_REGISTRY_IMAGE:${CI_COMMIT_TAG}
  <<: *tags_only_rules

release-to-prod:
  stage: release
  image: bitnami/kubectl:1.21
  script:
    - ENVIRONMENT=production
    - echo "Releasing to $ENVIRONMENT"
    - kubectl config set-cluster k8s --insecure-skip-tls-verify=true --server=$K8S_API_URL
    # ... (настройка kubectl как в deploy) ...
    - sed -i "s|__ENVIRONMENT__|${ENVIRONMENT}|; s|__CI_REGISTRY_IMAGE__|${CI_REGISTRY_IMAGE}|; s|__IMAGE_TAG__|${CI_COMMIT_TAG}|" manifests/*.yml
    - kubectl apply -n $ENVIRONMENT -f manifests/
  <<: *tags_only_rules
```
