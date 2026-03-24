# Руководство по пайплайну для Go-приложения

## Определения

**Пайплайн для Go-приложения** — многоэтапный CI/CD-процесс для компиляции, тестирования, упаковки и развертывания приложений на языке Go. Характеризуется использованием артефактов сборки между этапами, E2E-тестированием запущенного бинарного файла и стратегией развертывания на основе веток и тегов.

**Ключевые компоненты:**

- **Артефакты (`artifacts`)** — передача бинарного файла между этапами пайплайна
- **E2E-тесты** — интеграционное тестирование запущенного приложения
- **Workflow rules** — условный запуск задач на основе веток и тегов
- **Kubernetes Executor** — безопасное выполнение задач развертывания в изолированных Pod

## Основные концепции

### Стратегия пайплайна

Пайплайн состоит из пяти этапов:

| Этап | Задачи | Описание |
| :--- | :--- | :--- |
| `validate` | `lint-yaml`, `lint-go`, `unit-tests` | Параллельные быстрые проверки для ускорения обратной связи |
| `build` | `build-and-e2e` | Компиляция приложения и запуск E2E-тестов |
| `docker` | `build-docker` | Упаковка в Docker-образ с тегом `$CI_COMMIT_SHORT_SHA` |
| `deploy` | `deploy` | Развертывание в `dev` или `staging` в зависимости от ветки |
| `release` | `retag-for-release`, `release-to-prod` | Релиз в `production` по Git-тегу |

### Логика развертывания

- **Feature-ветки** (`*`) → окружение `dev`
- **Ветка `main`** → окружение `staging`
- **Git-тег в `main`** → окружение `production` с версионированием по тегу

Эта логика реализуется через директиву [`rules`](../Advanced/gitlab_ci_advanced_workflow.md) с использованием YAML-якорей для переиспользования.

### Требования к инфраструктуре

Пайплайн использует **Kubernetes Executor** — наиболее безопасный способ интеграции. Каждая задача выполняется в изолированном Pod с временными учетными данными.

**Необходимые компоненты:**

1. GitLab Runner с Kubernetes Executor (настройка в **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**)
2. Namespaces: `dev`, `staging`, `production`
3. Deploy Token с правом `read_registry` для доступа к GitLab Registry
4. Secret `gitlab-registry-secret` в каждом namespace для pull образов

Подробнее о типах executor'ов — в **[Обзоре Runner'ов и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)**.

## Практические сценарии

### Шаг 1: Подготовка Kubernetes-кластера

**Создание namespaces:**

```bash
kubectl create ns dev
kubectl create ns staging
kubectl create ns production
```

**Создание секрета для доступа к Registry:**

```bash
# Создать Deploy Token в GitLab: Settings → Repository → Deploy Tokens (право read_registry)

kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=$CI_REGISTRY \
  --docker-username=<deploy_token_user> \
  --docker-password=<deploy_token_password> \
  -n dev

# Повторить для staging и production
```

### Шаг 2: Конфигурация `.gitlab-ci.yml`

**Шаблоны правил (YAML Anchors):**

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

**Этап `build` — сборка и E2E-тесты:**

```yaml
build-and-e2e:
  stage: build
  image: golang:1.21
  script:
    - cd verybigdataapp
    - go build -o /tmp/verybigdataapp
    - /tmp/verybigdataapp & # Запуск в фоне
    - sleep 3
    - |
      RESULT=$(curl "localhost:58080/?a=6&b=4")
      if [[ "$RESULT" != "10" ]]; then
        echo "E2E test failed: expected 10, got $RESULT"; exit 1;
      fi
  artifacts:
    paths: [/tmp/verybigdataapp]
  <<: *no_tags_rules
```

**Этап `docker` — сборка образа:**

```yaml
build-docker:
  stage: docker
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - cp /tmp/verybigdataapp ./app # Использование артефакта
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  dependencies:
    - build-and-e2e
  <<: *no_tags_rules
```

**Этап `deploy` — развертывание по веткам:**

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:1.21
  tags: [kubernetes] # Требуется Runner с Kubernetes Executor
  script:
    - |
      if [ "$CI_COMMIT_REF_NAME" == "main" ]; then
        export ENVIRONMENT=staging
      else
        export ENVIRONMENT=dev
      fi
    - echo "Deploying to $ENVIRONMENT"
    - apt-get update && apt-get install -y gettext-base
    - export CI_REGISTRY_IMAGE
    - export CI_COMMIT_SHORT_SHA
    - envsubst < manifests/deployment.template.yml | kubectl apply -n $ENVIRONMENT -f -
  <<: *no_tags_rules
```

Файл `manifests/deployment.template.yml` должен содержать переменные вида `$CI_REGISTRY_IMAGE` и `$CI_COMMIT_SHORT_SHA` для подстановки через `envsubst`.

**Этап `release` — релиз по тегу:**

```yaml
retag-for-release:
  stage: release
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - docker pull $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
  <<: *tags_only_rules

release-to-prod:
  stage: release
  image: bitnami/kubectl:1.21
  tags: [kubernetes]
  script:
    - export ENVIRONMENT=production
    - echo "Releasing to $ENVIRONMENT with tag ${CI_COMMIT_TAG}"
    - apt-get update && apt-get install -y gettext-base
    - export CI_REGISTRY_IMAGE
    - export CI_COMMIT_TAG
    - envsubst < manifests/deployment.template.yml | kubectl apply -n $ENVIRONMENT -f -
  <<: *tags_only_rules
```

### Шаг 3: Шаблон манифеста Kubernetes

**Файл `manifests/deployment.template.yml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: verybigdataapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: verybigdataapp
  template:
    metadata:
      labels:
        app: verybigdataapp
    spec:
      imagePullSecrets:
        - name: gitlab-registry-secret
      containers:
        - name: app
          image: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
          ports:
            - containerPort: 58080
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
```

## Дополнительная информация

**Оптимизация Docker-сборки:** для Go-приложений используйте multi-stage builds в Dockerfile. Это позволяет создать минимальный финальный образ без компилятора и исходного кода, что уменьшает размер и повышает безопасность.

**GitOps-альтернатива:** данный пайплайн реализует Push-based CI/CD. Для более строгого следования методологии GitOps рассмотрите интеграцию с **[ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)** — в этом случае CI отвечает только за сборку образов, а CD-агент синхронизирует состояние кластера с Git-репозиторием манифестов.

**Безопасность:** использование Kubernetes Executor обеспечивает изоляцию задач — каждая выполняется в отдельном Pod с временными учетными данными. Это безопаснее хранения долгоживущих токенов в CI-переменных.

**Управление окружениями:** подробная информация о создании и управлении окружениями в GitLab — в **[Концепциях окружений и развертываний](../Concepts/environments_and_deployments.md)**.

**Динамические окружения:** для создания временных окружений на каждый Merge Request (Review Apps) см. **[Настройку динамических окружений с Kubernetes](./kubernetes_review_apps.md)**.
