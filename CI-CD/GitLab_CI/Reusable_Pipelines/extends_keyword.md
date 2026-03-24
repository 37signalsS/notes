# GitLab CI: Механизм `extends`

## Определения

**`extends`** — ключевое слово GitLab CI для наследования конфигурации от одного или нескольких "скрытых" заданий (начинающихся с точки `.`). Позволяет избегать дублирования кода внутри одного файла `.gitlab-ci.yml` или подключенного через `include`.

**Скрытое задание (Hidden Job)** — задание, имя которого начинается с точки (`.base_job`). Не выполняется напрямую, используется как шаблон для наследования.

## Основные концепции

### Механизм слияния конфигураций

При использовании `extends` GitLab выполняет **обратное глубокое слияние (reverse deep merge)** конфигураций от родительского задания к дочернему.

#### Поведение для различных типов ключей

| Тип ключа | Поведение | Пример |
| :--- | :--- | :--- |
| **`script`** | **Перезаписывается** полностью | Дочерний `script` заменяет родительский |
| **`before_script`** | **Перезаписывается** полностью | Дочерний `before_script` заменяет родительский |
| **`after_script`** | **Перезаписывается** полностью | Дочерний `after_script` заменяет родительский |
| **`variables`** | **Глубокое слияние** | Дочерние значения переопределяют родительские, новые добавляются |
| **`rules`** | **Перезаписывается** полностью | Дочерние правила заменяют родительские |
| **`cache`** | **Перезаписывается** | Дочерний `cache` заменяет родительский |
| **`dependencies`** | **Перезаписывается** | Дочерний `dependencies` заменяет родительский |
| **`tags`, `image`, `stage`** | **Перезаписывается** | Дочернее значение заменяет родительское |
| **`artifacts`** | **Перезаписывается** | Дочерний `artifacts` заменяет родительский |

> **Важно:** Скрипты **не конкатенируются** — дочерний `script` полностью заменяет родительский. Для выполнения общей логики используйте `!reference` для вставки фрагментов.

### Множественное наследование

`extends` поддерживает наследование от нескольких родительских заданий:

```yaml
extends: [.parent_a, .parent_b, .parent_c]
```

**Порядок слияния:** справа налево — последнее задание в списке имеет наивысший приоритет.

```yaml
.base_defaults:
  image: alpine:latest
  tags:
    - docker

.test_rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

.custom_vars:
  variables:
    TEST_ENV: staging

my_test_job:
  extends: [.base_defaults, .test_rules, .custom_vars]
  script:
    - echo "Running tests"
```

В результате `my_test_job` получит:

- `image: alpine:latest` (из `.base_defaults`)
- `tags: [docker]` (из `.base_defaults`)
- `rules` из `.test_rules`
- `variables: {TEST_ENV: staging}` (из `.custom_vars`)
- `script` из `my_test_job`

### Ограничения

| Ограничение | Значение |
| :--- | :--- |
| Максимальная глубина наследования | **11 уровней** (рекомендуется ≤3) |
| Количество родителей в `extends` | Не ограничено (рекомендуется ≤3) |
| Область видимости | Один файл `.gitlab-ci.yml` или подключенный через `include` |

## Практические сценарии

### Сценарий 1: Наследование от одного скрытого задания

**Базовый шаблон для тестирования:**

```yaml
.tests_template:
  stage: test
  image: ruby:3.2
  before_script:
    - bundle install
  script:
    - bundle exec rspec
  artifacts:
    reports:
      junit: reports/junit.xml

rspec_job:
  extends: .tests_template
  variables:
    RSPEC_OPTS: "--format progress"

rubocop_job:
  extends: .tests_template
  script:
    - bundle exec rubocop
  artifacts: {}  # Отключаем артефакты для линтера
```

**Результат:**

- `rspec_job`: наследует `image`, `before_script`, `stage`, добавляет `variables`
- `rubocop_job`: наследует всё, но переопределяет `script` и отключает `artifacts`

### Сценарий 2: Переопределение переменных и правил

```yaml
.base_deploy:
  stage: deploy
  image: alpine:latest
  variables:
    DEPLOY_ENV: development
    NOTIFY_SLACK: "true"
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'
  script:
    - echo "Deploying to $DEPLOY_ENV"

deploy_staging:
  extends: .base_deploy
  variables:
    DEPLOY_ENV: staging
    # NOTIFY_SLACK наследуется из базового шаблона
  rules:
    - if: '$CI_COMMIT_BRANCH == "staging"'

deploy_production:
  extends: .base_deploy
  variables:
    DEPLOY_ENV: production
    NOTIFY_SLACK: "false"  # Переопределяем
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### Сценарий 3: Комбинация `include` + `extends`

**Централизованный шаблон (`ci-templates/docker-build.yml`):**

```yaml
# В репозитории group/ci-templates
.docker_build_base:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

**Проект (`.gitlab-ci.yml`):**

```yaml
include:
  - project: 'group/ci-templates'
    ref: v1.2.0  # Используем тег для стабильности
    file: '/docker-build.yml'

stages:
  - build

build_app:
  extends: .docker_build_base
  variables:
    DOCKER_BUILDKIT: "1"
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
```

### Сценарий 4: Множественное наследование с переопределением

```yaml
.global_defaults:
  retry:
    max: 2
    when:
      - runner_system_failure
  timeout: 30m

.nodejs_base:
  image: node:20-alpine
  before_script:
    - npm ci

.test_rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main"'

unit_tests:
  extends: [.global_defaults, .nodejs_base, .test_rules]
  script:
    - npm run test:unit
  coverage: '/Lines\s*:\s*\d+.\d+\%/'
```

**Результат слияния:**

1. Применяются `.global_defaults` (retry, timeout)
2. Добавляются `.nodejs_base` (image, before_script)
3. Добавляются `.test_rules` (rules)
4. Переопределяются `unit_tests` (script, coverage)

## Дополнительная информация

### Отличия от `!reference`

| Характеристика | `extends` | `!reference` |
| :--- | :--- | :--- |
| **Назначение** | Наследование всей конфигурации задания | Вставка конкретных фрагментов |
| **Слияние** | Reverse deep merge | Прямая подстановка |
| **Область** | Только задания (jobs) | Любые ключи (script, rules, variables) |
| **Валидация** | Полная через CI Lint | Полная через CI Lint |

**Пример выбора:**

- Используйте `extends` для создания шаблонов jobs
- Используйте `!reference` для вставки общих скриптов или правил

### Валидация через CI Lint

```bash
# Проверка конфигурации с extends
gitlab-ci lint --project=my-group/my-project

# Просмотр развернутой конфигурации
gitlab-ci lint --include-debug
```

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `circular reference detected` | Циклическое наследование | Убедитесь, что цепочка `extends` не замыкается |
| `exceeded max levels of extends` | Глубина >11 уровней | Упростите иерархию шаблонов |
| `job references unknown extends` | Родительское задание не найдено | Проверьте имя и порядок объявления |

### Связанные документы

[Обзор переиспользуемых пайплайнов](./overview.md) — сравнение всех подходов, [`!reference` и YAML Anchors](./reference_and_yaml_anchors.md) — вставка фрагментов, [Механизм `include`](./include_keyword.md) — подключение внешних файлов, [Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md) — управление переменными.

### Внешние ресурсы

[Официальная документация: `extends`](https://docs.gitlab.com/ci/yaml/#extends), [GitLab CI Best Practices](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5).
