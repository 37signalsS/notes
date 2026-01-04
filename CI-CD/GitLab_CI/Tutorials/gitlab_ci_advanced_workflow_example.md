### Определения

**Многоэтапный CI/CD пайплайн** — автоматизированный процесс, демонстрирующий комплексный подход к сборке, тестированию и развертыванию приложения в нескольких окружениях (`dev`, `staging`, `production`) на основе Git-Flow. Пайплайн использует advanced-функции GitLab CI, такие как `rules` и `dependencies`, для реализации сложной логики.

---

### Основные концепции

Данный пайплайн реализует стратегию, где жизненный цикл приложения управляется ветками и тегами в Git.

1.  **Валидация кода**: Первый этап (`validate`) состоит из параллельных задач для быстрой проверки качества кода (линтинг, unit-тесты). Это пример оптимизации пайплайна, где независимые быстрые проверки вынесены на самый ранний этап для ускорения обратной связи.

2.  **Сборка и тестирование**: После валидации происходит компиляция приложения и запуск E2E-тестов. Артефакт сборки (`binary`) передается на следующий этап, чтобы избежать повторной компиляции.

3.  **Упаковка в Docker**: Приложение упаковывается в Docker-образ с тегом, соответствующим короткому хешу коммита (`$CI_COMMIT_SHORT_SHA`).

4.  **Развертывание по веткам (Branch-based Deployment)**:
    *   **Feature-ветки**: Любая ветка, кроме `main`, автоматически развертывается в `dev`-окружение.
    *   **`main`-ветка**: Используется для развертывания в `staging`-окружение, представляя собой релиз-кандидата.

5.  **Релиз по тегу (Tag-based Release)**:
    *   Создание Git-тега в `main`-ветке инициирует релизный процесс. Ранее собранный Docker-образ перетегируется версией из Git-тега (`$CI_COMMIT_TAG`) и развертывается в `production`.

Эта логика реализуется с помощью директивы [`rules`](../Advanced/gitlab_ci_advanced_workflow.md), которая позволяет гибко управлять запуском задач в зависимости от условий, таких как имя ветки или наличие тега.

---

### Практические сценарии

#### Сценарий: Настройка CI/CD для Go-приложения в Kubernetes

**1. Подготовка окружения в Kubernetes**

На мастер-ноде кластера необходимо создать `namespaces` для каждого окружения и секреты для доступа к приватному GitLab Docker Registry.

```bash
# 1. Создание namespaces
kubectl create ns dev
kubectl create ns staging
kubectl create ns production

# 2. Создание секрета для доступа к registry.gitlab.com в каждом namespace
# (замените <...> на ваши данные Deploy Token)
kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=<user> \
  --docker-password=<password> -n dev

kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=<user> \
  --docker-password=<password> -n staging

kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=<user> \
  --docker-password=<password> -n production

# 3. Настройка прав для CI/CD (Service Account)
# Для простоты примера даем права cluster-admin. В реальных проектах используйте RoleBinding с минимально необходимыми правами.
kubectl create clusterrolebinding ci-cd-admin --clusterrole=cluster-admin --serviceaccount=default:default
```

**2. Настройка переменных в GitLab CI**

Для авторизации в кластере из пайплайна, необходимо сохранить токен и URL API в переменных CI/CD проекта (`Settings -> CI/CD -> Variables`):

1.  **`K8S_API_URL`**:
    *   Получите URL: `kubectl config view -o jsonpath='{.clusters[].cluster.server}'`
    *   Создайте переменную `K8S_API_URL` со значением этого URL.

2.  **`K8S_CI_TOKEN`**:
    *   Получите токен ServiceAccount'а `default`:
        ```bash
        kubectl get secrets -o jsonpath='{.items[?(@.metadata.annotations.kubernetes.io/service-account.name=="default")].data.token}' | base64 -d
        ```
    *   Создайте переменную `K8S_CI_TOKEN` в GitLab со значением этого токена. Подробнее о работе с секретами в [документации](../Concepts/gitlab_ci_variables_secrets.md).

**3. Реализация `.gitlab-ci.yml`**

Пайплайн состоит из следующих этапов: `validate`, `build`, `docker`, `deploy`, `retag`, `release`.

**Шаблоны правил (YAML Anchors)**

Для переиспользования логики `rules` определим два якоря: один для задач, которые не должны запускаться для тегов, и второй — для задач, которые запускаются *только* для тегов.

```yaml
.no_tags_rules: &no_tags_rules
  rules:
    - if: '$CI_COMMIT_TAG'
      when: never
    - when: on_success

.tags_only_rules: &tags_only_rules
  rules:
    - if: '$CI_COMMIT_TAG'
      when: on_success
    - when: never
```

**Этап `validate`**

Три параллельные задачи для быстрой проверки качества кода.

```yaml
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
    - cd verybigdataapp && go test ./...
  <<: *no_tags_rules
```

**Этап `build`**

Компиляция и E2E-тестирование. Бинарный файл сохраняется в артефактах.

```yaml
build-and-e2e:
  stage: build
  image: golang:1.21
  script:
    - cd verybigdataapp
    - go build -o /tmp/verybigdataapp
    - /tmp/verybigdataapp & # Запуск приложения в фоне
    - sleep 3 # Даем время на запуск
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

**Этап `docker`**

Сборка Docker-образа с использованием артефакта из `build-and-e2e`.

```yaml
build-docker:
  stage: docker
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - cp /tmp/verybigdataapp ./app # Копируем артефакт в контекст сборки
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  dependencies:
    - build-and-e2e # Зависимость от задачи, создающей артефакт
  <<: *no_tags_rules
```

**Этап `deploy`**

Развертывание в `dev` или `staging` в зависимости от ветки.

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

**Этапы `retag` и `release` (для Production)**

Выполняются только при создании Git-тега в `main`-ветке.

```yaml
retag-for-release:
  stage: retag
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - docker pull $CI_REGISTRY_IMAGE:${CI_COMMIT_SHORT_SHA}
    - docker tag $CI_REGISTRY_IMAGE:${CI_COMMIT_SHORT_SHA} $CI_REGISTRY_IMAGE:${CI_COMMIT_TAG}
    - docker push $CI_REGISTRY_IMAGE:${CI_COMMIT_TAG}
  <<: *tags_only_rules

release-to-prod:
  stage: release
  image: bitnami/kubectl:1.21
  script:
    - ENVIRONMENT=production
    - echo "Releasing to $ENVIRONMENT with tag ${CI_COMMIT_TAG}"
    # Настройка kubeconfig ...
    - kubectl config set-cluster k8s --insecure-skip-tls-verify=true --server=$K8S_API_URL
    - kubectl config set-credentials ci --token=$K8S_CI_TOKEN
    - kubectl config set-context ci --cluster=k8s --user=ci
    - kubectl config use-context ci
    # Подстановка переменных и деплой
    - sed -i "s|__ENVIRONMENT__|${ENVIRONMENT}|; s|__CI_REGISTRY_IMAGE__|${CI_REGISTRY_IMAGE}|; s|__IMAGE_TAG__|${CI_COMMIT_TAG}|" manifests/*.yml
    - kubectl apply -n $ENVIRONMENT -f manifests/
  <<: *tags_only_rules
```

---

### Дополнительная информация

*   **GitOps**: Хотя данный пайплайн автоматизирует развертывание, он является примером "Push-based" CI/CD. Для более строгого следования методологии GitOps, где кластер сам синхронизирует свое состояние с Git-репозиторием, можно интегрировать такие инструменты, как [ArgoCD](../../../GitOps/ArgoCD.md) или Flux. В этом случае GitLab CI будет отвечать только за сборку и публикацию образов, а деплой будет управляться GitOps-оператором.