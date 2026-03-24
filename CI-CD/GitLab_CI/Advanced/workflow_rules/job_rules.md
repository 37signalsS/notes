# Правила запуска задач с `rules`

## Определения

`rules` — рекомендуемый способ контроля запуска **отдельных задач**. Правила проверяются по порядку, первое совпадение определяет поведение задачи. Поддерживает: `if`, `changes`, `exists`, `when`, `allow_failure`, `variables`, `start_in`.

## Основные концепции

По умолчанию задачи запускаются согласно разделу `stages`. `rules` переопределяет это поведение:

- Задача включается в пайплайн только при совпадении правила
- При отсутствии совпадений — задача не добавляется
- `when: never` явно исключает задачу

**Важно:** `job:rules` поддерживает `start_in`, `allow_failure`, `needs` в отличие от [`workflow:rules`](./directives_definitions.md).

## Практические сценарии

**Запуск только для Merge Request:**

```yaml
test_job:
  stage: test
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Запуск для MR в определённую ветку:**

```yaml
test_mr_to_main:
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
```

**Запуск при изменении файлов (монорепозитории):**

```yaml
# Запуск только при изменении frontend-кода
test_frontend:
  script:
    - npm run test
  rules:
    - changes:
        - "frontend/**/*"
        - "package.json"
        - "pnpm-lock.yaml"

# Запуск только при изменении backend-кода
test_backend:
  script:
    - pytest
  rules:
    - changes:
        - "backend/**/*"
        - "requirements.txt"
```

**Комбинированное правило для деплоя:**

```yaml
deploy_job:
  stage: deploy
  script:
    - ./deploy.sh
  rules:
    # Автоматический деплой для main
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: on_success
    # Ручной деплой для staging
    - if: '$CI_COMMIT_BRANCH == "staging"'
      when: manual
    # Запрет для остальных веток
    - when: never
```

**Задачи по расписанию (pipeline schedules):**

```yaml
nightly_tests:
  stage: test
  script:
    - pytest --slow-tests
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
```

**Ключевые условия:**

| Условие | Описание | Пример |
| :--- | :--- | :--- |
| `if` | Проверка переменных | `if: '$CI_COMMIT_BRANCH == "main"'` |
| `changes` | Изменения файлов | `changes: - "src/**/*"` |
| `exists` | Существование файлов | `exists: - "docker-compose.yml"` |

**Режимы `when`:**

| Режим | Описание |
| :--- | :--- |
| `on_success` | По умолчанию, при успехе всех предыдущих |
| `on_failure` | Только при провале предыдущих |
| `always` | Всегда, независимо от статуса |
| `manual` | Ручной запуск через UI |
| `delayed` | Запуск с задержкой |
| `never` | Никогда не выполнять |
