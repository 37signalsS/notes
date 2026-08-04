# Практические примеры CI/CD пайплайна в GitLab

> Этот документ предоставляет практические сценарии и примеры конфигурации `.gitlab-ci.yml` для различных этапов CI/CD в GitLab. Он дополняет общий обзор концепций CI/CD, описанный в **[CI/CD: Обзор](../../ci_cd_overview.md)**, фокусируясь на конкретных реализациях.

## Определения

- **GitLab Agent for Kubernetes (KAS):** Современный механизм интеграции, обеспечивающий безопасный доступ к кластеру через **CI/CD Tunnel**. Исключает передачу `KUBECONFIG` через переменные.
- **`id_tokens` (OIDC):** Механизм генерации временных JWT-токенов для аутентификации в облаках и K8s без использования паролей.
- **Docker-in-Docker (dind):** Специальный образ-сервис, позволяющий запускать Docker-команды внутри контейнера задачи.
- **Атомарный деплой (Atomic Deployment):** Принцип, при котором обновление либо полностью успешно, либо автоматически откатывается при малейшей ошибке (флаг `--atomic` в Helm).

## Основные концепции

### Жизненный цикл артефакта
1. **Сборка (Build):** Создание Docker-образа с тегом коммита (`$CI_COMMIT_SHORT_SHA`).
2. **Валидация (Quality Gates):** Линтинг, Unit-тесты, сканирование уязвимостей.
3. **Публикация (Push):** Загрузка проверенного образа в Registry.
4. **Развертывание (Deploy):** Применение манифестов в целевое окружение.

## Практические сценарии

### Сценарий 1: Деплой в Kubernetes через Агент (KAS)

Использование Агента — стандарт безопасности. Вам не нужно создавать секреты `docker-registry` вручную, так как Агент может использовать права пайплайна.

```yaml
stages:
  - build
  - deploy

variables:
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  FULL_IMAGE_NAME: $CI_REGISTRY_IMAGE:$IMAGE_TAG
  # Формат: путь/к/проекту-агента:имя-агента
  KUBE_CONTEXT: "group/infra/k8s-connection:prod-agent"

build_job:
  stage: build
  image: docker:24.0
  services: [docker:24.0-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - docker build -t $FULL_IMAGE_NAME .
    - docker push $FULL_IMAGE_NAME

deploy_k8s:
  stage: deploy
  image: dtzar/helm-kubectl:3.14
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - >
      helm upgrade --install my-app ./chart
        --namespace production
        --set image.tag=$IMAGE_TAG
        --wait --atomic --timeout 5m
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 2: Деплой на Docker-хост по SSH (Безопасный метод)

Использование `ssh-agent` и проверка ключей хоста предотвращают перехват данных (MitM).

```yaml
deploy_ssh:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - >
      ssh $SSH_USER@"$PRODUCTION_IP" "
        docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY &&
        docker pull $FULL_IMAGE_NAME &&
        docker stop my-app || true &&
        docker rm my-app || true &&
        docker run --name my-app -d -p 80:8080 $FULL_IMAGE_NAME
      "
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 3: Автоматическое создание Merge Request и уведомление через API

Позволяет автоматизировать процесс код-ревью при пуше в feature-ветки.

```yaml
stages:
  - automation
  - test

variables:
  GL_PROJECT_API: "$CI_API_V4_URL/projects/$CI_PROJECT_ID"

create_mr_automation:
  stage: automation
  image: python:3.12-slim
  script:
    - |
      MR_IID=$(curl -s --request POST "$GL_PROJECT_API/merge_requests" \
        --header "PRIVATE-TOKEN: $GL_ACCESS_TOKEN" \
        --form "source_branch=$CI_COMMIT_BRANCH" \
        --form "target_branch=$CI_DEFAULT_BRANCH" \
        --form "title=Auto-MR: $CI_COMMIT_TITLE" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('iid',''))")
      echo "MR_IID=$MR_IID" > mr.env
  artifacts:
    reports:
      dotenv: mr.env
  rules:
    - if: '$CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH && $CI_PIPELINE_SOURCE == "push"'

post_comment:
  stage: test
  needs: [create_mr_automation]
  script:
    - |
      curl -s --request POST "$GL_PROJECT_API/merge_requests/$MR_IID/notes" \
        --header "PRIVATE-TOKEN: $GL_ACCESS_TOKEN" \
        --form "body=Пайплайн запущен для ветки $CI_COMMIT_BRANCH. Ссылка на артефакты: $CI_JOB_URL"
```

### Сценарий 4: Quality Gates (JUnit, Coverage и блокировка MR)

Пайплайн визуализирует результаты тестов и покрытие кода прямо в интерфейсе Merge Request.

```yaml
test_job:
  stage: test
  image: python:3.12-slim
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
  allow_failure: false # Блокирует Merge при падении тестов
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 5: Оптимизация сборки через BuildKit и кэширование

Ускорение пайплайна за счет переиспользования слоев Docker из Registry.

```yaml
build_optimized:
  stage: build
  image: docker:24.0
  services: [docker:24.0-dind]
  variables:
    DOCKER_BUILDKIT: 1
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - >
      docker build 
        --cache-from $CI_REGISTRY_IMAGE:cache
        --build-arg BUILDKIT_INLINE_CACHE=1
        -t $FULL_IMAGE_NAME 
        -t $CI_REGISTRY_IMAGE:cache .
    - docker push $FULL_IMAGE_NAME
    - docker push $CI_REGISTRY_IMAGE:cache
```

## Технические нюансы и Безопасность

### Безопасность ID Tokens
С версии **17.0** вместо `CI_JOB_JWT` рекомендуется использовать `id_tokens`. Это позволяет настроить доверительные отношения (Trust Relationship) с AWS/GCP/Vault на основе конкретных параметров пайплайна (проект, ветка).

### Маскирование секретов
Никогда не используйте `echo $SECRET` в скриптах. GitLab автоматически маскирует переменные в логах, если они помечены как **Masked**, но принудительный вывод через команды отладки может обойти эту защиту.

### Использование CI/CD Components
Для типичных задач (сборка, деплой) рекомендуется переходить на компоненты:
```yaml
include:
  - component: $CI_SERVER_FQDN/gitlab-components/sast/sast@1.2.0
    inputs:
      stage: test
```

## Дополнительная информация

### Смотрите также

- **[Основы GitLab CI](../Concepts/gitlab_ci_basics.md)** — архитектура и стадии.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом.
- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — глубокая настройка KAS.
- **[Кэширование в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)** — стратегии ускорения.
