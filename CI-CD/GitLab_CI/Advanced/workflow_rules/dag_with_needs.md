# Построение DAG с использованием needs

## Определения

**needs**: Директива для создания **направленного ациклического графа (DAG)**. Позволяет запускать задачи сразу после завершения их зависимостей, не дожидаясь окончания всей стадии (stage).

**Типы зависимостей:**
- **Внутри пайплайна:** Зависимость от задачи в том же пайплайне.
- **Опциональная (`optional: true`):** Задача запустится, даже если указанная зависимость была исключена из пайплайна (например, через `rules`).
- **Кросс-проектная (`project`):** Загрузка артефактов и ожидание завершения задачи в другом проекте (GitLab Premium+).

## Основные концепции

По умолчанию задачи в стадии выполняются параллельно, а стадии — последовательно. `needs` нарушает эту модель:

- Задача запускается **сразу** после завершения указанных в `needs` задач.
- Не нужно ждать окончания всей стадии.
- Создается **направленный ациклический граф (DAG)**.

**Важно:** `needs` автоматически устанавливает `dependencies`, загружая артефакты от указанных задач. Для отмены загрузки артефактов используйте: `artifacts: false`.

### Опциональные зависимости (optional)

Используется в динамических пайплайнах, где некоторые задачи могут не существовать в зависимости от условий (MR, ветка, тег).

```yaml
deploy:
  stage: deploy
  needs:
    - job: "security-scan"
      optional: true  # Пайплайн не упадет, если security-scan пропущен
```

### Кросс-проектные зависимости (project)

Позволяет построить цепочку поставок между разными репозиториями без использования API-скриптов.

```yaml
integration-test:
  stage: test
  needs:
    - project: "my-group/backend-api"
      job: "build-assets"
      ref: "main"
      artifacts: true
```

### Немедленный запуск (needs: [])

Пустой массив `needs: []` означает, что задача не зависит ни от одной другой задачи и запускается **сразу** при старте пайплайна, независимо от стадий. Используется для независимых задач: нотификации, линтеры, сбор метрик.

```yaml
lint:
  stage: test
  needs: []
  script:
    - npm run lint
```

## Практические сценарии

### Ускорение пайплайна с использованием `needs` (DAG)

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

1. Все три `build:*` запускаются параллельно.
2. Через 15 сек `build:web` завершается → **сразу** запускается `test:web`.
3. Через 45 сек `build:ios` завершается → запускается `test:all`.

**Оптимизация с `dependencies: []`:**

```yaml
deploy:
  stage: deploy
  needs: ["test:web"]
  dependencies: []  # Не загружать артефакты, только порядок выполнения
  script:
    - echo "Deploying..."
```

Для сериализации развертываний и защиты от гонок состояний используется `resource_group` ([matrix_builds_and_serialization.md](./matrix_builds_and_serialization.md)).

### Сложный DAG с несколькими зависимостями

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

## Дополнительная информация

### Особенности загрузки артефактов

При использовании `needs` загружаются артефакты только от задач, указанных в этом блоке. Это значительно ускоряет выполнение задачи, так как не загружаются ненужные данные из всей стадии `build`.

Для полного отключения загрузки артефактов используйте сокращенную форму:
```yaml
job:
  needs: ["other_job"]
  artifacts: false
```

### Смотрите также

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — базовый синтаксис и стадии.
- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — оптимизация и масштабирование.
- **[Матричные сборки и сериализация](./matrix_builds_and_serialization.md)** — управление параллелизмом.
