# Продвинутый CI/CD пайплайн для Go-приложения

## Обзор стратегии пайплайна

1. **Валидация (`validate`)**: Параллельный запуск быстрых проверок (линтинг, unit-тесты) для ускорения обратной связи.
2. **Сборка (`build`)**: Компиляция приложения и запуск E2E-тестов. Бинарный файл передается дальше как артефакт.
3. **Упаковка (`docker`)**: Приложение упаковывается в Docker-образ с тегом `$CI_COMMIT_SHORT_SHA`.
4. **Развертывание по веткам**:
    * **Feature-ветки** (`*`) -> `dev`-окружение.
    * **`main`**-ветка -> `staging`-окружение.
5. **Релиз по тегу**:
    * Создание Git-тега в `main`-ветке инициирует релиз. Образ перетегируется версией из Git-тега (`$CI_COMMIT_TAG`) и развертывается в `production`.

Эта логика реализуется с помощью директивы [`rules`](../Advanced/gitlab_ci_advanced_workflow.md).

## Пошаговая реализация

### Шаг 1: Настройка Kubernetes и Runner'а

Этот пайплайн использует **Kubernetes Executor** — наиболее безопасный и рекомендуемый способ интеграции.

1. **Настройте GitLab Runner с Kubernetes Executor.** Подробные инструкции находятся в руководствах:
    * **[Обзор Runner'ов и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)**
    * **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** (см. "Сценарий 1: Развертывание в "Push"-модели с Helm и Kubernetes Executor")

2. **Создайте `namespaces`** для каждого окружения:

    ```bash
    kubectl create ns dev
    kubectl create ns staging
    kubectl create ns production
    ```

3. **Создайте секрет для доступа к GitLab Registry**. CI/CD-задачи будут использовать его для скачивания образов. Создайте **Deploy Token** в GitLab (`Settings -> Repository -> Deploy Tokens`) с правом `read_registry` и выполните команду для каждого namespace:

    ```bash
    kubectl create secret docker-registry gitlab-registry-secret \
      --docker-server=$CI_REGISTRY \
      --docker-username=<deploy_token_user> \
      --docker-password=<deploy_token_password> -n dev
    # Повторите для -n staging и -n production
    ```

### Шаг 2: Реализация `.gitlab-ci.yml`

Пайплайн состоит из этапов: `validate`, `build`, `docker`, `deploy`, `retag`, `release`.

**Шаблоны правил (YAML Anchors)**

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

**Этапы `validate`, `build` и `docker`**
Эти этапы не требуют доступа к Kubernetes.

```yaml
# ... (задачи lint-yaml, lint-go, unit-tests как в оригинале) ...

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

build-docker:
  stage: docker
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - cp /tmp/verybigdataapp ./app # Используем артефакт
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  dependencies:
    - build-and-e2e
  <<: *no_tags_rules
```

**Этап `deploy`**
Этот этап использует `envsubst` для подстановки переменных в манифесты.

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:1.21
  tags: [kubernetes] # Указываем, что нужен Runner в Kubernetes
  script:
    - |
      if [[ "$CI_COMMIT_REF_NAME" == "main" ]]; then
        export ENVIRONMENT=staging
      else
        export ENVIRONMENT=dev
      fi
    - echo "Deploying to $ENVIRONMENT"
    # Устанавливаем утилиту envsubst
    - apt-get update && apt-get install -y gettext-base
    # Экспортируем переменные, которые нужно подставить
    - export CI_REGISTRY_IMAGE
    - export CI_COMMIT_SHORT_SHA
    # envsubst ищет в файле '$VAR' или '${VAR}' и заменяет их значениями из окружения
    - envsubst < manifests/deployment.template.yml | kubectl apply -n $ENVIRONMENT -f -
  <<: *no_tags_rules
```

*Предполагается, что в `manifests/deployment.template.yml` используются переменные вида `$CI_REGISTRY_IMAGE` и `$CI_COMMIT_SHORT_SHA`.*

**Этапы `retag` и `release` (для Production)**

```yaml
retag-for-release:
  # ... (без изменений) ...

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

## Дополнительная информация

* **GitOps**: Этот пайплайн реализует "Push-based" CI/CD. Для более строгого следования методологии GitOps, рассмотрите интеграцию с **[ArgoCD](../../../GitOps/ArgoCD.md)**.
* **Безопасность**: Использование **Kubernetes Executor** — ключевое улучшение. Каждая задача выполняется в своем изолированном Pod с временными учетными данными, что гораздо безопаснее хранения долгоживущих токенов в переменных CI.
* **Оптимизация Docker-сборки**: Для Go-приложений используйте **multi-stage builds** в Dockerfile. Это позволяет создать минимальный финальный образ, не содержащий компилятора и исходного кода, что уменьшает его размер и повышает безопасность.
