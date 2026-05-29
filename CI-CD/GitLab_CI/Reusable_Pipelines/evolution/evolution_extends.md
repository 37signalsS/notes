# Гибкость шаблонов через `extends`

## Определения

**`extends`** — механизм наследования конфигурации в GitLab CI. Позволяет job наследовать настройки от другого job (обычно скрытого, с именем начинающимся на `.`).

**Скрытый job** — job с именем, начинающимся на точку (например, `.docker-build-template`). Не выполняется в пайплайне, используется как шаблон.

**Контекст этапа:** Решение проблемы жёсткой конфигурации после централизации через `include:project` — добавление гибкости для кастомизации шаблонов в конкретных проектах.

## Базовые концепции

### Принцип работы `extends`

```yaml
# Шаблон (не выполняется)
.base-job:
  image: docker:24.0
  script:
    - echo "Base script"

# Реальный job (наследуется от шаблона)
my-job:
  extends: .base-job
  variables:
    MY_VAR: "value"
```

> **Важно:** При наследовании применяется механизм **обратного глубокого слияния (reverse deep merge)**. Дочерние элементы переопределяют родительские. Подробные правила слияния конфигураций (включая работу со скриптами, переменными и множественным наследованием) описаны в главном документе — [Механизм `extends`](../extends_keyword.md).

### Комбинация `include` + `extends`

```yaml
# 1. Подключаем внешний шаблон
include:
  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker-build.yml'

# 2. Наследуем и кастомизируем
build-job:
  extends: .docker-build-template
  variables:
    CUSTOM_VAR: "value"
```

## Практические сценарии

### Обновлённый шаблон с скрытым job

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
.docker-build-template:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build \
        --build-arg CI_JOB_TOKEN=${CI_JOB_TOKEN} \
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA \
        .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

### Использование с кастомизацией в проекте

```yaml
# .gitlab-ci.yml проекта
include:
  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker-build.yml'

stages:
  - build

build-my-app:
  extends: .docker-build-template
  variables:
    DOCKER_BUILDKIT: "1"
    IMAGE_NAME: "my-app"
  before_script:
    - echo "Custom step before building"
    - npm install
```

### Преимущества подхода

| Преимущество | Описание |
| :--- | :--- |
| **Централизация** | Общая логика в одном месте |
| **Гибкость** | Каждый проект добавляет свои переменные, `before_script`, `after_script` |
| **DRY** | Нет дублирования основной логики |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Безопасность** | `docker:dind` требует привилегированного режима (`privileged`) |
| **Сложность обновления** | При изменении шаблона все проекты получают изменения немедленно |

**Следующий этап:** [Абстрагирование с Kaniko](./evolution_kaniko.md) решает проблему безопасности через переход на непривилегированный сборщик.

## Дополнительная информация

**Предыдущий этап:** [Централизация с `include`](./evolution_include.md) описывает вынос шаблонов в центральный репозиторий.

**Детали механизма:** [Механизм `extends`](../extends_keyword.md) содержит полное описание слияния конфигураций и множественного наследования.
