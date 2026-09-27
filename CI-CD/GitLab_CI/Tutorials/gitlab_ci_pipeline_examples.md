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

### Предварительные требования

Перед запуском сценариев убедитесь, что выполнены следующие условия:

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| **GitLab** | Версия 17.0+ (рекомендуется 19.x) | `Help -> About` в UI |
| **GitLab Runner** | Версия 16.0+, Docker Executor | `gitlab-runner --version` |
| **Container Registry** | Включен в настройках проекта | Deploy -> Container Registry |
| **Docker-in-Docker** | Runner настроен с `privileged = true` | `config.toml` раннера |
| **Переменные** | `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`, `GITLAB_API_TOKEN` добавлены в CI/CD -> Variables | CI/CD -> Variables |
| **Kubernetes** | Kubectl доступен (для сценария 1) | `kubectl cluster-info` |
| **SSH-доступ** | SSH-ключ добавлен на целевой сервер (для сценария 2) | `ssh $USER@$HOST echo ok` |

**Общие рекомендации:**
- Используйте отдельные Runner'ы для разных сред (Dev/Staging/Prod) с соответствующими тегами.
- Все секреты должны быть типа `masked` и `protected` в CI/CD Variables.
- Для продакшен-деплоев всегда используйте `when: manual` в rules.

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
  image: docker:29.8
  services: [docker:29.8-dind]
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
| **dind: job failed to start** | Runner не в привилегированном режиме | Включите `privileged = true` в `config.toml` раннера и перезапустите его. |
| **MR API returns 403** | Недостаточно прав у токена | Проверьте Scope токена (`api`) и права пользователя (должен быть Maintainer). |
| **KAS context not found** | Агент не авторизован в проекте | Проверьте настройки авторизации в `config.yaml` агента и привязку агента к проекту. |
| **SSH deploy hangs** | Нет ответа от `ssh-agent` | Убедитесь, что `eval $(ssh-agent -s)` выполнен в той же джобе и ключ добавлен через `ssh-add`. |
| **Coverage не отображается** | Неверный формат отчета | GitLab 19.x требует формат Cobertura XML для визуализации покрытия. |
| **Helm upgrade --atomic failed** | Таймаут деплоя или ошибка в манифестах | Увеличьте `--timeout` или проверьте шаблоны Helm: `helm template ./charts/app`. |
| **Container Registry 401 Unauthorized** | Истекший или неверный токен | Используйте `CI_JOB_TOKEN` (auto-generated) вместо личных Access Tokens. |
| **Kubernetes: pods CrashLoopBackOff** | Ошибка в приложении или конфигурации | Проверьте логи: `kubectl logs <pod-name> -n production`. Частая причина — отсутствие `HEALTHCHECK` или неверный `entrypoint`. |
| **SSH: Host key verification failed** | `SSH_KNOWN_HOSTS` не содержит fingerprint сервера | Выполните `ssh-keyscan -H $PRODUCTION_IP` и обновите переменную. |
| **Dynamic pipeline: child-pipeline.yml not found** | Артефакт не был создан или устарел | Убедитесь, что `generate-config` завершился успешно и `artifacts:paths` содержит `child-pipeline.yml`. |
| **Merge Request не создается автоматически** | Ветка уже имеет активный MR или нет прав | Проверьте, нет ли существующего MR через API: `GET /merge_requests?source_branch=$CI_COMMIT_BRANCH`. |
| **Cache не восстанавливается** | Неверный `key` или изменение файлов манифеста | Используйте `cache:key:files` с привязкой к `package-lock.json` или `uv.lock`. |

## Лучшие практики (Best Practices)

**Безопасность:**
- Используйте `CI_JOB_TOKEN` для всех операций с Container Registry — токен автоматически истекает после задачи.
- Все секреты (SSH-ключи, API-токены) должны быть типа `masked` и `protected` в CI/CD Variables.
- Используйте `id_tokens` (OIDC) для интеграции с Vault и Kubernetes — это стандарт 2026 года.
- Для Kubernetes-деплоев используйте RBAC с минимальными привилегиями: только `deployments` и `services` в целевом namespace.
- Никогда не храните `KUBECONFIG` в переменных — используйте GitLab Agent (KAS).

**Производительность:**
- Используйте `cache:key:files` для привязки кэша к файлам зависимостей.
- Включите BuildKit (`DOCKER_BUILDKIT=1`) для ускорения сборки Docker-образов.
- Используйте `needs:` для параллельного запуска независимых задач.
- Для монорепозиториев используйте Parent-Child пайплайны — запускайте задачи только для изменившихся модулей.

**Надёжность:**
- Всегда используйте `--atomic` при `helm upgrade` — автоматический откат при ошибке.
- Добавьте `HEALTHCHECK` в Dockerfile для корректной работы с оркестраторами.
- Используйте `timeout-minutes` к задачам для защиты от бесконечных пайплайнов.
- Пинайте версии образов: `docker:29.8` вместо `docker:latest`.

**Деплой:**
- Для продакшен-деплоев всегда используйте `when: manual` в rules.
- Используйте `--wait` при `helm upgrade` для ожидания готовности всех подов.
- Настройте `rollback` через `helm rollback` или `helm undo` для быстрого отката.

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

**Откат Kubernetes-деплоя:**
```bash
# Просмотр истории релизов
helm history my-app -n production

# Откат к предыдущей версии
helm rollback my-app 0 -n production

# Откат к конкретной версии
helm rollback my-app <revision_number> -n production
```

**Откат SSH-деплоя:**
```bash
# На целевом сервере — запуск предыдущего Docker-образа
ssh $SSH_USER@$PRODUCTION_IP << 'EOF'
docker stop my-app && docker rm my-app
docker pull $CI_REGISTRY_IMAGE:previous_tag
docker run -d --name my-app -p 80:8080 --restart always $CI_REGISTRY_IMAGE:previous_tag
EOF
```

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
- По умолчанию GitLab ограничивает размер образа (по умолчанию ~5 ГБ). Настройте через `registry.available_size` в `gitlab.yml`.

**Одновременный доступ к Vault:**
- При параллельных задачах, запрашивающих секреты из Vault, используйте `id_tokens` с уникальным `aud` для каждой задачи, чтобы избежать конфликтов токенов.

## Дополнительная информация

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — архитектура и стадии пайплайна.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом и безопасность переменных.
- **[Родительско-дочерние пайплайны](../Advanced/Downstream_Pipelines/parent_child_pipelines.md)** — декомпозиция монорепозиториев и оптимизация.
