# Практические примеры CI/CD пайплайнов в GitLab

## Определения

**GitLab Agent for Kubernetes (KAS)** — сервис интеграции, обеспечивающий безопасный двусторонний канал связи (**CI/CD Tunnel**) между GitLab и кластером. Исключает необходимость хранения `KUBECONFIG` в переменных и позволяет использовать RBAC кластера напрямую через пайплайн.

**id_tokens (OIDC)** — современный механизм генерации временных JWT-токенов для федерации идентичности (Workload Identity Federation). Позволяет аутентифицироваться в облаках (AWS, GCP) или хранилищах секретов (Vault) без использования долгоживущих паролей.

**Quality Gates (Ворота качества)** — набор автоматизированных критериев (покрытие тестами, отсутствие уязвимостей CVE, соответствие линтам), которые должны быть выполнены для продвижения артефакта на следующий этап деплоя.

**Docker-in-Docker (dind)** — паттерн запуска Docker-демона внутри контейнера задачи. Необходим для выполнения команд `docker build` и `docker push` в изолированных средах.

**SBOM (Software Bill of Materials)** — формализованный список всех компонентов и зависимостей приложения, необходимый для обеспечения безопасности цепочки поставок (Supply Chain Security).

**Атомарный деплой (Atomic Deployment)** — метод обновления приложения, при котором изменения вступают в силу одновременно, а при любой ошибке происходит автоматический откат к предыдущему стабильному состоянию (например, флаг `--atomic` в Helm).

## Основные концепции

### Жизненный цикл артефакта в GitLab 19.x

Современный пайплайн в GitLab строится по модульному принципу:
1.  **Подготовка (Prepare):** Динамическая генерация конфигурации, установка зависимостей с использованием кэширующих прокси.
2.  **Валидация (Quality Gates):** Параллельный запуск линтеров, статического анализа (SAST) и проверки секретов.
3.  **Сборка и Аттестация:** Создание Docker-образа с генерацией SBOM и подписью артефакта (стандарт SLSA).
4.  **Многоуровневое тестирование:** Unit-тесты, интеграционные тесты в Service Containers и DAST-сканирование.
5.  **Доставка (CD):** Развертывание в различные среды (Dev, Staging, Prod) с использованием GitOps или Push-модели.

### Безопасность и изоляция

*   **Zero Trust:** Использование `id_tokens` для всех внешних интеграций.
*   **Изоляция сред:** Разделение раннеров по тегам для разных уровней критичности (например, выделенные ноды для Prod-деплоя).
*   **Маскирование секретов:** Использование переменных типа `File` для предотвращения случайного вывода паролей в логи.

## Практические сценарии

### Сценарий 1: Деплой в Kubernetes через Агент (KAS) и Helm

Это наиболее безопасный и рекомендуемый метод интеграции в 2026 году.

```yaml
stages:
  - build
  - deploy

variables:
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  FULL_IMAGE: $CI_REGISTRY_IMAGE:$IMAGE_TAG
  KUBE_CONTEXT: "my-group/infra/k8s-connection:prod-agent"

# Сборка с использованием BuildKit для ускорения
build_job:
  stage: build
  image: docker:27.0
  services: [docker:27.0-dind]
  variables:
    DOCKER_BUILDKIT: 1
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
    - >
      docker build 
        --build-arg BUILDKIT_INLINE_CACHE=1
        --cache-from $CI_REGISTRY_IMAGE:latest
        -t $FULL_IMAGE 
        -t $CI_REGISTRY_IMAGE:latest .
    - docker push $FULL_IMAGE
    - docker push $CI_REGISTRY_IMAGE:latest
  tags: [docker-runner]

deploy_k8s:
  stage: deploy
  image: dtzar/helm-kubectl:3.15
  id_tokens:
    K8S_TOKEN:
      aud: https://kubernetes.default.svc.cluster.local
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - >
      helm upgrade --install my-app ./charts/app
        --namespace production
        --set image.tag=$IMAGE_TAG
        --wait --atomic --timeout 10m
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  tags: [secure-deploy-runner]
```

### Сценарий 2: Деплой на Docker-хост по SSH (Hardened Method)

Сценарий для проектов, не использующих Kubernetes. Включает проверку `known_hosts` и использование `ssh-agent`.

```yaml
deploy_ssh:
  stage: deploy
  image: alpine:3.20
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    # SSH_PRIVATE_KEY должна быть типа File для безопасности
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
        docker run -d --name my-app -p 80:8080 --restart always $FULL_IMAGE
      "
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  tags: [docker-runner]
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
  image: curlimages/curl:latest
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
  image: curlimages/curl:latest
  needs: [create_mr_auto]
  script:
    - |
      curl --request POST "$GL_PROJECT_API/merge_requests/$MR_IID/notes" \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --form "body= Пайплайн запущен. Результаты тестов будут доступны здесь: $CI_PIPELINE_URL"
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

container_security:
  stage: scan
  image: 
    name: aquasec/trivy:latest
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
```

### Сценарий 5: Динамические Parent-Child пайплайны (Монорепозитории)

Оптимизация времени выполнения за счет запуска задач только для изменившихся модулей.

```yaml
generate-config:
  stage: .pre
  image: python:3.13-slim
  script:
    - python3 scripts/generate-pipeline-config.py > child-pipeline.yml
  artifacts:
    paths: [child-pipeline.yml]

trigger-modules:
  stage: build
  trigger:
    include:
      - artifact: child-pipeline.yml
        job: generate-config
    strategy: depend
```

## Технические нюансы и Безопасность

### Интеграция с Vault через OIDC
С выходом GitLab 17.x и переходом к 19.x использование `id_tokens` для аутентификации в Vault является обязательным стандартом. Это позволяет джобе получить временный токен Vault без хранения секретов в GitLab.

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
| **dind: job failed to start** | Runner не в привилегированном режиме | Включите `privileged = true` в `config.toml` раннера. |
| **MR API returns 403** | Недостаточно прав у токена | Проверьте Scope токена (`api`) и права пользователя. |
| **KAS context not found** | Агент не авторизован в проекте | Проверьте настройки авторизации в `config.yaml` агента. |
| **SSH deploy hangs** | Нет ответа от `ssh-agent` | Убедитесь, что `eval $(ssh-agent -s)` выполнен в той же джобе. |
| **Coverage не отображается** | Неверный формат отчета | GitLab 19.x требует формат Cobertura XML для визуализации. |

## Дополнительная информация

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — архитектура и стадии.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом.
- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — глубокая настройка KAS.
- **[Кэширование в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)** — стратегии ускорения.
- **[Downstream Pipelines](../Advanced/Downstream_Pipelines/definitions.md)** — детали иерархии пайплайнов.
