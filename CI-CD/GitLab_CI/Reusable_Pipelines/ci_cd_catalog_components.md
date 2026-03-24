# GitLab CI: Каталог Компонентов (CI/CD Catalog)

## Определения

**CI/CD Catalog (Components)** — современный подход GitLab к переиспользованию конфигураций, позволяющий создавать версионируемые, типизированные и публикуемые в общем каталоге компоненты — полноценные, изолированные блоки CI/CD логики с явным интерфейсом (`spec:inputs`).

**Компонент** — YAML-файл (или директория) в репозитории, содержащий конфигурацию GitLab CI с метаданными `spec:inputs` для определения входных параметров.

**`spec:inputs`** — схема входных параметров компонента, определяющая типы, значения по умолчанию и валидацию через regex.

**Интерполяция** — механизм подстановки значений параметров через синтаксис `$[[ inputs.<name> ]]`.

---

## Основные концепции

### Преимущества компонентов перед `include`

| Критерий | `include:project` | CI/CD Catalog (Components) |
| :--- | :--- | :--- |
| **Версионирование** | Теги (рекомендуется) | **Semver** (обязательно для каталога) |
| **Типизация** | Нет | **Да** (`spec:inputs` с типами) |
| **Валидация** | Базовая | **Полная** (валидация inputs) |
| **Каталог** | Внешний репозиторий | **Встроенный в GitLab** (UI, поиск) |
| **Документация** | Ручная | **Автоматическая** (из `spec:inputs`) |
| **Изоляция** | Высокая | **Полная** (самодостаточные блоки) |

### Архитектура компонента

**Минимальная структура (один файл):**

```
component-repo/
└── .gitlab-ci.yml          # spec:inputs + логика
```

**Структура с шаблонами (множественные файлы):**

```
component-repo/
├── .gitlab-ci.yml          # Метаданные: spec:inputs
└── templates/
    └── build.yml           # Основная логика компонента
```

### Синтаксис `spec:inputs`

```yaml
spec:
  inputs:
    <input-name>:
      default: <value>          # Необязательно: значение по умолчанию
      description: "<text>"     # Необязательно: описание для документации
      type: <string|boolean|number>  # Необязательно: тип данных
      regex: "<pattern>"        # Необязательно: валидация через regex
```

**Пример с разными типами параметров:**

```yaml
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage for the job"

    target_branch:
      type: string
      default: main
      description: "Branch to Trigger on"
      regex: '^(main|develop|feature/.*)$'

    enable_cache:
      type: boolean
      default: true
      description: "Enable caching"

    timeout:
      type: number
      default: 30
      description: "Job timeout in minutes"
```

> **Важно:** `spec:inputs` не может быть пустым. Если входы не используются, сделайте `spec:` пустым:
>
> ```yaml
> spec:
> ---
> ```

### Интерполяция переменных

Компоненты поддерживают интерполяцию через синтаксис `$[[ inputs.<name> ]]`:

```yaml
# templates/build.yml
build_job:
  stage: $[[ inputs.stage ]]
  image: $[[ inputs.image ]]
  timeout: $[[ inputs.timeout ]]m
  rules:
    - if: '$CI_COMMIT_BRANCH == $[[ inputs.target_branch ]]'
  script:
    - echo "Building with cache: $[[ inputs.enable_cache ]]"
```

---

## Практические сценарии

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
# Создание тега
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

### Ограничения

| Ограничение | Значение |
| :--- | :--- |
| Максимум компонентов на проект | **100** (GitLab 18.5+) |
| Лимит вложенности | **150** include (включая компоненты) |
| Глобальные ключи в компоненте | ❌ Запрещены (`stages:`, `default:`, `workflow:`) |
| `spec:include` в компоненте | ❌ Запрещено (компоненты должны быть самодостаточными) |

### Форматы версий для компонентов

| Формат | Пример | Рекомендация |
| :--- | :--- | :--- |
| **SemVer (полный)** | `@1.2.0` | ✅ Для релизов |
| **SemVer (частичный)** | `@1.2` или `@1` | ✅ Для автообновлений |
| **Commit SHA** | `@e3262fd...` | ✅ Для максимальной стабильности |
| **~latest** | `@~latest` | ⚠️ Только если доверяете автору |
| **Ветка** | `@main` | ❌ Не рекомендуется |

**Правила разрешения версий:**

- При совпадении имени тега и SHA — приоритет у SHA
- При совпадении имени тега и ветки — приоритет у тега
- `~latest` не включает pre-release версии (`1.0.1-rc`)

### Валидация компонента

```bash
# Проверка конфигурации компонента
gitlab-ci lint --project=group/ci-components/build-docker

# Проверка использования в проекте
gitlab-ci lint --project=my-group/my-project
```

### Публикация в каталог

**Требования для публикации:**

1. Семантическое версионирование (SemVer)
2. Файл `.gitlab-ci.yml` с `spec:inputs`
3. Созданный GitLab Release с тегом

**Процесс публикации:**

```yaml
# .gitlab-ci.yml в репозитории компонента
release:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: $CI_COMMIT_TAG  # Запуск только при создании тега
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "Component release $CI_COMMIT_TAG"
```

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Spec must be a valid json schema` | Пустой `spec:inputs` | Используйте пустой `spec:` без `inputs` |
| `content not found` | Использование `~latest` без релиза | Создайте новый релиз с тегом |
| `invalid input type` | Несоответствие типа в inputs | Проверьте тип значения (string/boolean/number) |
| `regex validation failed` | Значение не соответствует regex | Исправьте значение или regex |

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [Официальная документация: `spec:inputs`](https://docs.gitlab.com/ci/components/#specinputs)
- [GitLab Components Catalog](https://gitlab.com/explore/catalog)

---

## Связанные документы

- Детальные определения — [ci_cd_catalog_definitions.md](./ci_cd_catalog_definitions.md)
- Расширенные концепции — [ci_cd_catalog_concepts.md](./ci_cd_catalog_concepts.md)
- Базовые сценарии — [ci_cd_catalog_scenarios.md](./ci_cd_catalog_scenarios.md)
- Продвинутые сценарии — [ci_cd_catalog_advanced_scenarios.md](./ci_cd_catalog_advanced_scenarios.md)
- Полные ограничения — [ci_cd_catalog_limits.md](./ci_cd_catalog_limits.md)
- Справочные материалы — [ci_cd_catalog_reference.md](./ci_cd_catalog_reference.md)
- Обзор переиспользуемых пайплайнов — [overview.md](./overview.md)
- Механизм `include` — [include_keyword.md](./include_keyword.md)
- Механизм `extends` — [extends_keyword.md](./extends_keyword.md)
