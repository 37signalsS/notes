# Правила запуска задач с `rules`

## Определения

`rules` — рекомендуемый способ контроля запуска **отдельных задач**. Правила проверяются по порядку, первое совпадение определяет поведение задачи. Поддерживает: `if`, `changes`, `exists`, `when`, `allow_failure`, `variables`, `start_in`.

## Основные концепции

По умолчанию задачи запускаются согласно разделу `stages`. `rules` переопределяет это поведение:

- Задача включается в пайплайн только при совпадении правила
- При отсутствии совпадений — задача не добавляется
- `when: never` явно исключает задачу

**Важно:** `job:rules` поддерживает `start_in`, `allow_failure`, `needs` в отличие от [`workflow:rules`](./directives_definitions.md).

### Ограничение: `rules` не видят переменные из других job

`rules` вычисляются в момент старта пайплайна — **до того как выполнилась любая job**. Переменные, которые job1 записала в `artifacts:reports:dotenv`, **недоступны в `rules:if`** job2.

```yaml
# ⛔ НЕ РАБОТАЕТ — MR_IID неизвестен на старте пайплайна
job2:
  rules:
    - if: '$MR_IID == "123"'  # переменная ещё не существует
```

Данные между jobs передаются через `artifacts` (в том числе `dotenv`) или `trigger:variables` в downstream-пайплайн — но только в `script:`, а не в `rules:`.

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

### Динамический запуск задач по событиям

Распространённый паттерн — запуск разных задач по сборке артефактов (например, Docker-образов) для разных окружений (dev, test, prod) в зависимости от события. Это позволяет избежать избыточных сборок.

**Решение:** привязать запуск каждой задачи к определённому событию через `rules`:

```yaml
# Сборка для dev — запуск при любом событии с Merge Request
build_dev:
  stage: build
  script:
    - docker build -t myapp:dev .
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

# Сборка для test — запуск при новом коммите в main
build_test:
  stage: build
  script:
    - docker build -t myapp:test .
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

# Сборка для prod — запуск при создании нового тега
build_prod:
  stage: build
  script:
    - docker build -t myapp:$CI_COMMIT_TAG .
  rules:
    - if: '$CI_COMMIT_TAG'
```

При таком подходе:

- Push в feature-ветку с открытым MR → запускается `build_dev`.
- Push в `main` → запускается `build_test`.
- Создание тега → запускается `build_prod`.

**Валидация тега по регулярному выражению:**

Можно усилить правило для тегов, чтобы оно срабатывало только для версий, соответствующих семантическому версионированию:

```yaml
build_prod:
  stage: build
  script:
    - docker build -t myapp:$CI_COMMIT_TAG .
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
```

Эта задача запустится только для тегов вида `v1.2.3`, но не для `release-candidate` или `v1.0`.

## Дополнительная информация

### Ключевые условия

| Условие | Описание | Пример |
| :--- | :--- | :--- |
| `if` | Проверка переменных | `if: '$CI_COMMIT_BRANCH == "main"'` |
| `changes` | Изменения файлов | `changes: - "src/**/*"` |
| `exists` | Существование файлов | `exists: - "docker-compose.yml"` |

### Режимы `when`

| Режим | Описание |
| :--- | :--- |
| `on_success` | По умолчанию, при успехе всех предыдущих |
| `on_failure` | Только при провале предыдущих |
| `always` | Всегда, независимо от статуса |
| `manual` | Ручной запуск через UI |
| `delayed` | Запуск с задержкой |
| `never` | Никогда не выполнять |
