# GitLab CI: Каталог Компонентов — Практические сценарии

## Определения

**Практический сценарий** — пошаговое руководство по решению конкретной задачи с использованием CI/CD Components в реальных условиях.

---

## Основные концепции

### Сценарий 1: Использование компонента из каталога

```yaml
# Проект (.gitlab-ci.yml)
include:
  - component: '$CI_SERVER_FQDN/group/security/secret-detection@1.0.0'
    inputs:
      stage: security
      scan_path: './config'
```

**Преимущества:** автоматическая валидация inputs, версионирование через Semver, видимость в UI GitLab Catalog.

### Сценарий 2: Создание собственного компонента

```yaml
# Репозиторий компонента (group/ci-components/build-docker/.gitlab-ci.yml)
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage name"

    dockerfile:
      default: Dockerfile
      type: string
      description: "Path to Dockerfile"

    image:
      default: docker:24.0
      type: string
      description: "Docker image for runner"

    push_registry:
      type: boolean
      default: true
      description: "Push to registry"

---
# Основная логика компонента
build-docker-job:
  stage: $[[ inputs.stage ]]
  image:
    name: $[[ inputs.image ]]
    entrypoint: [""]
  services:
    - name: docker:24.0-dind
      command: ["--tls=false"]
  variables:
    DOCKER_TLS_CERTDIR: ""
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker build -f $[[ inputs.dockerfile ]] -t $IMAGE_TAG .
    - |
      if [[ "$[[ inputs.push_registry ]]" == "true" ]]; then
        docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
        docker push $IMAGE_TAG
      fi
```

**Использование в проекте:**

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/build-docker@1.0.0'
    inputs:
      stage: build
      dockerfile: app/Dockerfile
      image: docker:24.0
      push_registry: true
```

### Сценарий 3: Компонент с множественными jobs

```yaml
# Компонент (group/ci-components/full-pipeline/.gitlab-ci.yml)
spec:
  inputs:
    node_version:
      default: "20"
      type: string
    test_command:
      default: "npm test"
      type: string
    build_command:
      default: "npm run build"
      type: string

---
install_job:
  stage: build
  image: node:$[[ inputs.node_version ]]
  script:
    - npm ci
  cache:
    key: node-modules-$[[ inputs.node_version ]]
    paths:
      - node_modules/

test_job:
  stage: test
  image: node:$[[ inputs.node_version ]]
  script:
    - $[[ inputs.test_command ]]
  needs:
    - install_job

build_job:
  stage: build
  image: node:$[[ inputs.node_version ]]
  script:
    - $[[ inputs.build_command ]]
  artifacts:
    paths:
      - dist/
  needs:
    - test_job
```

### Сценарий 4: Версионирование компонента

**Стратегия версионирования:**

| Тип версии | Формат | Когда использовать |
| :--- | :--- | :--- |
| **Patch** | `1.0.0` → `1.0.1` | Исправления багов, обратная совместимость |
| **Minor** | `1.0.0` → `1.1.0` | Новые функции, обратная совместимость |
| **Major** | `1.0.0` → `2.0.0` | Breaking changes |

**Создание релиза:**

```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

**Варианты использования в проекте:**

```yaml
include:
  # Конкретная версия (рекомендуется для стабильности)
  - component: '$CI_SERVER_FQDN/group/component@1.0.0'

  # Частичная версия (автообновление в рамках minor)
  - component: '$CI_SERVER_FQDN/group/component@1.0'

  # Только major (автообновление в рамках major версии)
  - component: '$CI_SERVER_FQDN/group/component@1'
```

> **Важно:** для компонентов в CI/CD Catalog обязательно семантическое версионирование (GitLab 16.10+).

### Сценарий 5: Компонент с валидацией через regex

```yaml
spec:
  inputs:
    environment:
      type: string
      description: "Deployment environment"
      regex: '^(dev|staging|production)$'
      default: dev

    replica_count:
      type: number
      description: "Number of replicas"
      regex: '^([1-9]|[1-9[0-9])$'  # 1-99
      default: 3

---
deploy_job:
  stage: deploy
  script:
    - echo "Deploying to $[[ inputs.environment ]]"
    - kubectl scale deployment app --replicas=$[[ inputs.replica_count ]]
```

---

## Справочная информация

### Матрица совместимости версий

| Версия GitLab | Компоненты | SemVer обязателен | Макс. компонентов |
| :--- | :--- | :--- | :--- |
| 16.0 – 16.1 | Experimental | Нет | 10 |
| 16.2 – 16.8 | Enabled by default | Нет | 10 |
| 16.9 – 16.11 | Stable | Нет | 30 |
| 17.0 – 18.4 | GA | Да (для каталога) | 30 |
| 18.5+ | GA | Да | 100 |

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [GitLab Components Catalog](https://gitlab.com/explore/catalog)
- [Примеры компонентов GitLab](https://gitlab.com/gitlab-org/ci-cd/components)

---

## Связанные документы

- **SSoT:** [GitLab CI: Каталог Компонентов](./ci_cd_catalog_components.md)
- [Определения](./ci_cd_catalog_definitions.md)
- [Концепции](./ci_cd_catalog_concepts.md)
- [Ограничения](./ci_cd_catalog_limits.md)
- [Справочная информация](./ci_cd_catalog_reference.md)
- [Продвинутые сценарии](./ci_cd_catalog_advanced_scenarios.md)
- [Механизм include](./include_keyword.md)
