# Этап 2: Решение — Централизация с помощью `include`

## Практические сценарии

### Решение

Вынести общий код в отдельный файл в центральном репозитории CI-шаблонов и подключать его через `include:project`.

### Создание репозитория шаблонов

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
build-docker-image:
  stage: docker-build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
```

### Использование в проекте

```yaml
# .gitlab-ci.yml проекта
stages:
  - docker-build

include:
  - project: 'group/ci-templates'
    ref: v1.0.0  # Версионирование через тег
    file: '/docker-build.yml'
```

### Результат

| Преимущество | Описание |
| :--- | :--- |
| **Централизация** | Изменения вносятся в одном месте |
| **Стандартизация** | Все проекты используют одинаковую конфигурацию |
| **Упрощение** | `.gitlab-ci.yml` проекта содержит только `include` |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Отсутствие гибкости** | Невозможно кастомизировать шаблон под конкретный проект |
| **Жёсткая конфигурация** | Все проекты вынуждены использовать одинаковые `image`, `variables` |

## Дополнительная информация

### Связанные документы

- **[Этап 1: Дублирование кода](./evolution/stage1_boilerplate.md)** — проблема до централизации
- **[Этап 3: Гибкость с extends](./evolution/stage3_extends.md)** — решение проблемы гибкости
- **[Механизм `include`](./include_keyword.md)** — все типы include
