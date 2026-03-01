# Продвинутые рабочие процессы GitLab CI/CD

## Определения

- **`workflow:rules`**: Глобальное правило, контролирующее создание всего пайплайна. Если ни одно правило не выполнено — пайплайн не запускается. Заменяет устаревшие `only/except` на уровне пайплайна.
- **`rules`**: Механизм для определения условий включения **отдельной задачи** в пайплайн. Правила проверяются по порядку, первое совпадение определяет поведение задачи.
- **`needs`**: Директива для создания **направленного ациклического графа (DAG)**. Позволяет запускать задачи сразу после завершения зависимостей, не дожидаясь окончания всей стадии.
- **`parallel:matrix`**: Директива для запуска одного задания несколько раз с разными комбинациями переменных. Используется для тестирования на разных версиях ПО, архитектурах или окружениях.
- **`resource_group`**: Гарантирует, что одновременно выполняется только одна задача для определенной группы ресурсов. Предотвращает гонки состояний при деплое.

## Основные концепции

### Стратегии запуска и `workflow:rules`

GitLab CI/CD поддерживает различные события для запуска пайплайнов. Ключевая проблема — **дублирование пайплайнов**: один запускается для ветки после `push`, второй — для Merge Request из той же ветки.

**Решение:** использование `workflow:rules` для контроля создания пайплайна.

#### Рекомендуемая конфигурация workflow

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

#### Pipeline inputs (GitLab 17+)

Начиная с GitLab 17, доступна возможность использования **pipeline inputs** — типизированных параметров для передачи данных в пайплайн:

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    environment:
      description: "Окружение для деплоя"
      options:
        - staging
        - production
      default: staging
    version:
      description: "Версия приложения"
      type: string
      default: "latest"

deploy_job:
  stage: deploy
  script:
    - echo "Deploying version $[[ inputs.version ]] to $[[ inputs.environment ]]"
  rules:
    - if: '$[[ inputs.environment ]] == "production"'
      when: manual
```

**Преимущества перед переменными:**
- Валидация типов данных
- Проверка допустимых значений (`options`)
- Явное описание ожидаемых параметров
- Безопасность (защита от инъекций)

**Порядок правил критичен:** более специфичные правила должны идти перед общими.

#### Auto-cancel пайплайнов

Для автоматической отмены старых пайплайнов при новых коммитах:

```yaml
workflow:
  auto_cancel:
    on_new_commit: interruptible  # Прерывать текущие пайплайны
    on_job_failure: all           # Отменять при провале задачи
  rules:
    - if: '$CI_COMMIT_REF_PROTECTED == "true"'
      auto_cancel:
        on_new_commit: none       # Не отменять для защищённых веток
        on_job_failure: none
    - when: always
```

#### Динамические переменные на уровне пайплайна

```yaml
workflow:
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      variables:
        DEPLOY_ENV: "production"
        ENABLE_FULL_TESTS: "true"
    - if: '$CI_COMMIT_BRANCH =~ /^feature/'
      variables:
        DEPLOY_ENV: "staging"
        ENABLE_FULL_TESTS: "false"
```

### Гибкие правила запуска с `rules`

`rules` — рекомендуемый способ контроля запуска **отдельных задач**. Поддерживает:

- `if` — условные выражения
- `changes` — изменения в файлах
- `exists` — существование файлов
- `when` — режим выполнения
- `allow_failure` — разрешение неудачи
- `variables` — переменные задачи
- `start_in` — задержка выполнения

#### Ключевые условия

| Условие | Описание | Пример |
| :--- | :--- | :--- |
| **`if`** | Проверка переменных | `if: '$CI_COMMIT_BRANCH == "main"'` |
| **`changes`** | Изменения файлов | `changes: - "src/**/*"` |
| **`exists`** | Существование файлов | `exists: - "docker-compose.yml"` |

#### Режимы `when`

| Режим | Описание |
| :--- | :--- |
| `on_success` | По умолчанию, при успехе всех предыдущих |
| `on_failure` | Только при провале предыдущих |
| `always` | Всегда, независимо от статуса |
| `manual` | Ручной запуск через UI |
| `delayed` | Запуск с задержкой |
| `never` | Никогда не выполнять |

### Построение DAG с помощью `needs`

По умолчанию задачи в стадии выполняются параллельно, а стадии — последовательно. `needs` нарушает эту модель:

- Задача запускается **сразу** после завершения указанных в `needs` задач
- Не нужно ждать окончания всей стадии
- Создается **направленный ациклический граф (DAG)**

**Важно:** `needs` автоматически устанавливает `dependencies`, загружая артефакты от указанных задач. Для отмены: `dependencies: []`.

### Практические сценарии

#### Сценарий 1: Условный запуск задач с `rules`

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

#### Сценарий 2: Ускорение пайплайна с `needs` (DAG)

**Пример: независимые тесты не ждут долгих сборок**

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

build:ios:
  stage: build
  script:
    - xcodebuild -scheme MyApp
  artifacts:
    paths:
      - build/ios/

# Запускается сразу после build:web, не ждёт android/ios
test:web:
  stage: test
  needs: ["build:web"]
  script:
    - npm run test:web

# Ждёт окончания всей стадии build (классическое поведение)
test:all:
  stage: test
  script:
    - npm run test:all
```

**Порядок выполнения:**
1. Все три `build:*` запускаются параллельно
2. Через 15 сек `build:web` завершается → **сразу** запускается `test:web`
3. Через 45 сек `build:ios` завершается → запускается `test:all`

**Оптимизация с `dependencies: []`:**

```yaml
deploy:
  stage: deploy
  needs: ["test:web"]
  dependencies: []  # Не загружать артефакты, только порядок выполнения
  script:
    - echo "Deploying..."
```

#### Сценарий 3: Матричные сборки с `parallel:matrix`

**Тестирование на разных версиях:**

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

**Комбинированная матрица (OS × Version):**

```yaml
build:
  stage: build
  image: ${BUILD_IMAGE}
  parallel:
    matrix:
      - BUILD_IMAGE: ["node:18", "node:20", "node:22"]
        TEST_SUITE: ["unit"]
      - BUILD_IMAGE: ["node:20"]
        TEST_SUITE: ["integration", "e2e"]
  script:
    - echo "Testing with ${BUILD_IMAGE} - ${TEST_SUITE}"
    - npm run test:${TEST_SUITE}
```

**Создание 6 задач:**
- 3 × unit-тесты (Node 18, 20, 22)
- 2 × integration/e2e (Node 20)

#### Сценарий 4: Сериализация развертываний с `resource_group`

**Защита production от гонок состояний:**

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

**Очереди для разных окружений:**

```yaml
deploy_staging:
  stage: deploy
  resource_group: staging
  script:
    - ./deploy.sh staging

deploy_prod:
  stage: deploy
  resource_group: production
  script:
    - ./deploy.sh production
```

Если два пайплайна одновременно пытаются задеплоить в `production`, второй будет ждать завершения первого.

#### Сценарий 5: Complex DAG с несколькими зависимостями

```yaml
lint:
  stage: test
  script:
    - npm run lint

test:unit:
  stage: test
  script:
    - npm run test:unit

test:integration:
  stage: test
  needs: ["lint", "test:unit"]
  script:
    - npm run test:integration

deploy:
  stage: deploy
  needs: ["test:integration"]
  script:
    - ./deploy.sh
```

**Граф выполнения:**
```
lint ──┬─→ test:integration ──→ deploy
       │
test:unit ──┘
```

### Дополнительная информация

#### Встроенные переменные CI/CD

Ключевые переменные для управления потоком работ:

| Переменная | Описание | Пример значения |
| :--- | :--- | :--- |
| `$CI_PIPELINE_SOURCE` | Источник запуска | `push`, `merge_request_event`, `schedule`, `api`, `web` |
| `$CI_COMMIT_BRANCH` | Ветка коммита | `main`, `feature/my-feature` |
| `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` | Целевая ветка MR | `main`, `develop` |
| `$CI_COMMIT_TAG` | Тег (если есть) | `v1.2.3` |
| `$CI_OPEN_MERGE_REQUESTS` | Открытые MR | `group/project!123` |
| `$CI_COMMIT_REF_PROTECTED` | Защищённая ветка | `true`, `false` |
| `$CI_DEFAULT_BRANCH` | Default branch | `main`, `master` |

Полный список: [Predefined variables](https://docs.gitlab.com/ee/ci/variables/predefined_variables.html)

#### Best Practices (2025-2026)

1. **Используйте `workflow:rules` вместо `only/except`**
   - `only/except` устарели и не рекомендуются
   - `rules` более гибкие и мощные

2. **Порядок правил важен**
   - Размещайте специфичные правила перед общими
   - Завершайте `workflow:rules` с `when: never` для отклонения лишних

3. **Избегайте дублирования правил**
   - Если `workflow:rules` уже фильтрует пайплайны, не дублируйте в `job:rules`

4. **Используйте `changes` для монорепозиториев**
   - Запускайте тесты только для изменённых компонентов
   - Экономит ресурсы и время

5. **DAG с `needs` для ускорения**
   - Разбивайте длинные последовательности
   - Запускайте независимые задачи параллельно

6. **`resource_group` для production**
   - Всегда используйте для критичных деплоев
   - Предотвращает гонки состояний

7. **Матрицы для тестирования**
   - Используйте для множественных версий/окружений
   - Избегайте дублирования задач

8. **Pipeline inputs для типизированных параметров (GitLab 17+)**
   - Используйте `spec.inputs` вместо переменных для валидации
   - Особенно полезно для компонентов и переиспользуемых пайплайнов

9. **OIDC-аутентификация для внешних сервисов**
   - Используйте `CI_JOB_JWT_TOKEN` для аутентификации в AWS, GCP, Azure
   - Заменяет долгоживущие токены на временные
   - См. [Workload Identity Federation](https://docs.gitlab.com/ee/ci/secrets/authenticate_with_oidc.html)

10. **Компоненты GitLab CI/CD (GitLab 17+)**
    - Переиспользуемые блоки конфигурации с типизированными входами
    - Централизованное управление шаблонами
    - См. [GitLab CI/CD Components](https://docs.gitlab.com/ee/ci/components/)

#### Ограничения

- **`workflow:rules`** не поддерживает `start_in`, `allow_failure`, `needs`
- **Максимум 4 кэша** на задачу
- **Максимум 1000 downstream pipelines** в иерархии
- **`changes`** не работает для `workflow:rules` (только для `job:rules`)

### Связанные документы

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции Pipeline, Stage, Job
- **[Кэширование в GitLab CI](./gitlab_ci_caching.md)** — оптимизация скорости пайплайнов
- **[Исполнители (Runners)](./gitlab_ci_runners_executors.md)** — настройка сред выполнения
- **[Дочерние пайплайны](./gitlab_ci_downstream_pipelines.md)** — декомпозиция сложных пайплайнов
- **[Валидация и версионирование](./pipeline_validation_and_versioning.md)** — проверка конфигурации
```
