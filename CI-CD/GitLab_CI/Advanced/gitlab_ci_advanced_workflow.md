# Продвинутые рабочие процессы GitLab CI/CD

## Определения

**Продвинутые рабочие процессы GitLab CI/CD** — набор директив и механизмов для управления сложными пайплайнами: условный запуск, оптимизация выполнения через DAG, матричные сборки, сериализация развертываний.

**Ключевые директивы:**

- `workflow:rules` — глобальное правило создания пайплайна
- `rules` — условный запуск отдельных задач
- `needs` — создание DAG для ускорения выполнения
- `parallel:matrix` — запуск задачи с разными комбинациями переменных
- `resource_group` — сериализация выполнения для защиты от гонок состояний

Подробные определения: [Определения директив](./workflow_rules/directives_definitions.md).

## Основные концепции

### Архитектура управления пайплайнами

Продвинутые рабочие процессы решают три основные задачи:

1. **Контроль запуска** — когда и при каких условиях создавать пайплайн и задачи
2. **Оптимизация выполнения** — ускорение через параллелизм и DAG
3. **Безопасность развертывания** — предотвращение гонок состояний при деплое

### Связь с базовыми концепциями

Базовая структура пайплайна (`stages` → `jobs` → `script`) определяет последовательное выполнение. Продвинутые директивы нарушают эту модель:

- `needs` позволяет задачам запускаться вне очереди стадий
- `rules` динамически включают/исключают задачи из пайплайна
- `parallel:matrix` умножает количество выполняемых задач
- `resource_group` добавляет очереди на выполнение

### Версионирование и совместимость

- **Pipeline inputs (GitLab 17+)** — типизированные параметры пайплайна
- **Компоненты GitLab (GitLab 17+)** — переиспользуемые блоки конфигурации
- **OIDC-аутентификация** — аутентификация во внешних облаках через `CI_JOB_JWT_TOKEN`

Подробнее: [Переменные и Best Practices](./workflow_rules/variables_best_practices.md).

## Практические сценарии

### Сценарий 1: Контроль дублирования пайплайнов

**Проблема:** при `push` в ветку с открытым MR создаются два пайплайна — для ветки и для MR.

**Решение:** `workflow:rules` с проверкой открытых MR:

```yaml
workflow:
  rules:
    # Всегда запускать для Merge Request
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    # Всегда запускать для default branch
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    # Не запускать для push, если есть открытый MR
    - if: '$CI_OPEN_MERGE_REQUESTS'
      when: never
    # Запускать для всех остальных веток
    - if: '$CI_COMMIT_BRANCH'
```

Порядок правил критичен: специфичные правила должны идти перед общими.

### Сценарий 2: Ускорение пайплайна через DAG

**Проблема:** задачи ждут окончания всей стадии, хотя могут выполняться раньше.

**Решение:** `needs` для создания зависимостей между конкретными задачами:

```yaml
stages:
  - build
  - test

build:web:
  stage: build
  script:
    - npm run build:web
  artifacts:
    paths:
      - dist/web/

build:android:
  stage: build
  script:
    - ./gradlew assembleDebug
  artifacts:
    paths:
      - app/build/outputs/apk/

# Запускается сразу после build:web, не ждёт android/ios
test:web:
  stage: test
  needs: ["build:web"]
  script:
    - npm run test:web
```

Подробнее: [DAG с `needs`](./workflow_rules/dag_with_needs.md).

### Сценарий 3: Монорепозиторий с условным запуском

**Проблема:** в монорепозитории все тесты запускаются при любом изменении.

**Решение:** `rules:changes` для запуска только затронутых задач:

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

Подробнее: [Правила запуска задач](./workflow_rules/job_rules.md).

### Сценарий 4: Матричное тестирование

**Проблема:** нужно протестировать приложение на разных версиях Python/Node.js.

**Решение:** `parallel:matrix` для создания комбинаций:

```yaml
test:
  stage: test
  image: python:${PYTHON_VERSION}
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
  script:
    - pip install -r requirements.txt
    - pytest -q
```

Создаётся 3 независимые задачи с разными версиями интерпретатора.

### Сценарий 5: Защита production от гонок состояний

**Проблема:** два пайплайна одновременно пытаются задеплоить в production.

**Решение:** `resource_group` создаёт очередь на выполнение:

```yaml
deploy_prod:
  stage: deploy
  script:
    - ./scripts/deploy.sh production
  resource_group: production
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

Если два пайплайна одновременно пытаются задеплоить в `production`, второй будет ждать завершения первого.

Подробнее: [Матричные сборки и сериализация](./workflow_rules/practical_scenarios.md).

## Дополнительная информация

### Ограничения

- `workflow:rules` не поддерживает `start_in`, `allow_failure`, `needs`
- `changes` не работает для `workflow:rules` (только для `job:rules`)
- Максимум 1000 downstream pipelines в иерархии

### Связанные документы

- [Определения директив](./workflow_rules/directives_definitions.md) — полные определения всех директив
- [Правила запуска задач](./workflow_rules/job_rules.md) — условный запуск, `changes`, pipeline schedules
- [DAG с `needs`](./workflow_rules/dag_with_needs.md) — направленный ациклический граф, Complex DAG
- [Матричные сборки и сериализация](./workflow_rules/practical_scenarios.md) — `parallel:matrix`, `resource_group`
- [Переменные и Best Practices](./workflow_rules/variables_best_practices.md) — встроенные переменные, OIDC, компоненты GitLab
- [Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md) — базовые концепции
- [Конструктор рабочих процессов](./gitlab_ci_workflow_builder.md) — `stages`, `jobs`, `artifacts`, `cache`
