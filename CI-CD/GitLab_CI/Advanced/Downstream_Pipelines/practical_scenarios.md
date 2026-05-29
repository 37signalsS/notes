# Практические сценарии использования downstream pipelines

## Определения

**Практические сценарии** — типовые примеры использования parent-child и multi-project pipelines для реальных задач CI/CD.

## Основные концепции

## Практические сценарии

### 1. Передача переменных в multi-project pipeline

Передача переменных в downstream проект требует явного указания в `trigger:variables`. Project/Group variables не наследуются.

```yaml
trigger_downstream_build:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
  variables:
    UPSTREAM_PIPELINE_ID: $CI_PIPELINE_ID
    CUSTOM_MESSAGE: "Hello from upstream!"
```

Подробно о наследовании: [Наследование переменных](./variable_inheritance.md).

### 2. Pipeline для монорепозитория

Определение изменённых файлов и запуск задач только для затронутых компонентов:

```yaml
detect-changes:
  stage: .pre
  script:
    - |
      CHANGED=$(git diff --name-only $CI_MERGE_REQUEST_DIFF_BASE_SHA...$CI_COMMIT_SHA)
      echo "CHANGED_FILES=$CHANGED" >> variables.env
  artifacts:
    reports:
      dotenv: variables.env

build-frontend:
  stage: build
  rules:
    - if: $CHANGED_FILES =~ /frontend/
  script:
    - cd frontend && npm install && npm run build

build-backend:
  stage: build
  rules:
    - if: $CHANGED_FILES =~ /backend/
  script:
    - cd backend && make build
```

### 3. Динамическая генерация пайплайнов

Генерация конфигурации `.gitlab-ci.yml` во время выполнения родительского пайплайна. Используется для сложных сценариев в монорепозиториях.

Подробный пример с Python и Jinja2: [Динамическая генерация](./dynamic_generation.md).

## Дополнительная информация

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Рекомендации](./best_practices.md)
- [Стратегии выполнения](./strategies.md)
- [Динамическая генерация](./dynamic_generation.md)
- [Наследование переменных](./variable_inheritance.md)
