# CI/CD Catalog Components — зрелый подход к переиспользованию

## Определения

**CI/CD Components** — версионируемые, типизированные компоненты GitLab с публикуемым интерфейсом (`spec:inputs`). Предоставляют каталог переиспользуемых пайплайнов.

**`spec:inputs`** — явный интерфейс компонента, определяющий входные параметры с типами, значениями по умолчанию и описаниями.

**Semver** — семантическое версионирование (`MAJOR.MINOR.PATCH`). Для компонентов GitLab поддерживает частичные версии (`@1.0`, `@1`).

**Контекст этапа:** Финальный этап эволюции — решение проблем типизации, валидации и документирования через CI/CD Components.

## Базовые концепции

### Архитектура компонентов

```
┌─────────────────────────────────────────────────────────────┐
│  Репозиторий компонента: group/ci-components/docker-build   │
│  ├── .gitlab-ci.yml      (spec:inputs + метаданные)         │
│  └── templates/                                             │
│      └── build.yml       (основная логика)                  │
└─────────────────────────────────────────────────────────────┘
                          ↓ include:component
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Проект 1    │  │  Проект 2    │  │  Проект N    │
│  (явные      │  │  (явные      │  │  (явные      │
│   inputs)    │  │   inputs)    │  │   inputs)    │
└──────────────┘  └──────────────┘  └──────────────┘
```

### Типы входных параметров

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| `string` | Строковое значение | `dockerfile: Dockerfile` |
| `boolean` | Логическое значение | `enable_cache: true` |
| `number` | Числовое значение | `timeout: 3600` |
| `array` | Массив значений | `tags: [docker, k8s]` |

### Версионирование компонентов

| Версия | Описание |
| :--- | :--- |
| `@1.0.0` | Точная версия |
| `@1.0` | Последняя минорная версия 1.0.x |
| `@1` | Последняя мажорная версия 1.x.x |

### Синтаксис подстановки inputs

```yaml
# В шаблонах компонентов используется $[[ inputs.<name> ]]
stage: $[[ inputs.stage ]]
dockerfile: $[[ inputs.dockerfile ]]
cache: $[[ inputs.enable_cache ]]
```

## Практические сценарии

### Создание компонента

**Репозиторий:** `group/ci-components/docker-build`

**Структура:**

```
docker-build/
├── .gitlab-ci.yml          # spec:inputs + метаданные
└── templates/
    └── build.yml           # Основная логика
```

**Файл:** `.gitlab-ci.yml` (метаданные компонента)

```yaml
# .gitlab-ci.yml компонента
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

    context:
      default: $CI_PROJECT_DIR
      type: string
      description: "Build context path"

    enable_cache:
      default: true
      type: boolean
      description: "Enable Kaniko caching"

    cache_repo:
      default: $CI_REGISTRY_IMAGE/cache
      type: string
      description: "Cache repository"

---
# Основная логика компонента (templates/build.yml)
docker-build-job:
  stage: $[[ inputs.stage ]]
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - /kaniko/executor \
        --context $[[ inputs.context ]] \
        --dockerfile $[[ inputs.dockerfile ]] \
        --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA \
        --cache=$[[ inputs.enable_cache ]] \
        --cache-repo=$[[ inputs.cache_repo ]]
```

### Публикация в каталог

**Создание релиза:**

```bash
# Создание тега с SemVer
git tag -a v1.0.0 -m "Initial release of docker-build component"
git push origin v1.0.0
```

**CI для автоматического релиза:**

```yaml
# .gitlab-ci.yml компонента (добавление release job)
release:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: $CI_COMMIT_TAG
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "docker-build component $CI_COMMIT_TAG"
```

### Использование компонента в проекте

```yaml
# .gitlab-ci.yml проекта
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.0.0'
    inputs:
      stage: build
      dockerfile: app/Dockerfile
      context: $CI_PROJECT_DIR
      enable_cache: true
      cache_repo: $CI_REGISTRY_IMAGE/cache
```

### Преимущества Components

| Преимущество | Описание |
| :--- | :--- |
| **Типизация** | Явные типы параметров (string, boolean, number) |
| **Валидация** | Автоматическая валидация inputs через CI Lint |
| **Документация** | Автоматическая генерация из `description` |
| **Версионирование** | Semver с поддержкой частичных версий (`@1.0`, `@1`) |
| **Каталог** | Видимость в UI GitLab, поиск компонентов |
| **Изоляция** | Полная самодостаточность компонента |

## Дополнительная информация

**Предыдущий этап:** [Абстрагирование с Kaniko](./stage4_kaniko.md) описывает переход на безопасный сборщик образов.

**Детали создания:** [CI/CD Catalog](../ci_cd_catalog_components.md) содержит полное руководство по созданию компонентов.

**Сравнение подходов:** [Обзор переиспользуемых пайплайнов](../../overview.md) содержит таблицу всех механизмов переиспользования.

**Внешние ресурсы:** [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/), [GitLab CI Best Practices](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5).
