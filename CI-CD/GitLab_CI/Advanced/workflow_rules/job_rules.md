# Правила запуска задач с `rules`

## Определения

`rules` — рекомендуемый способ контроля запуска **отдельных задач**. Поддерживает:

- `if` — условные выражения
- `changes` — изменения в файлах
- `exists` — существование файлов
- `when` — режим выполнения
- `allow_failure` — разрешение неудачи
- `variables` — переменные задачи
- `start_in` — задержка выполнения

## Основные концепции → Практические сценарии

### Условный запуск задач с `rules`

#### Запуск только для Merge Request

```yaml
test_job:
  stage: test
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

#### Запуск для MR в определённую ветку

```yaml
test_mr_to_main:
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
```

#### Запуск при изменении файлов (монорепозитории)

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

#### Комбинированное правило для деплоя

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

#### Задачи по расписанию (pipeline schedules)

```yaml
nightly_tests:
  stage: test
  script:
    - pytest --slow-tests
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
```

### Ключевые условия

| Условие | Описание | Пример |
| :--- | :--- | :--- |
| **`if`** | Проверка переменных | `if: '$CI_COMMIT_BRANCH == "main"'` |
| **`changes`** | Изменения файлов | `changes: - "src/**/*"` |
| **`exists`** | Существование файлов | `exists: - "docker-compose.yml"` |

### Режимы `when`

| Режим | Описание |
| :--- | :--- |
| `on_success` | По умолчанию, при успехе всех предыдущих |
| `on_failure` | Только при провале предыдущих |
| `always` | Всегда, независимо от статуса |
| `manual` | Ручной запуск через UI |
| `delayed` | Запуск с задержкой |
| `never` | Никогда не выполнять |

## Связанные документы

- **[Определения директив](./directives_definitions.md)** — ключевые директивы
- **[workflow:rules и pipeline inputs](./pipeline_inputs.md)** — управление пайплайнами
- **[DAG с needs](./dag_with_needs.md)** — управление зависимостями
- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — базовые концепции
