# Построение DAG с использованием `needs`

## Определения

**`needs`**: Директива для создания **направленного ациклического графа (DAG)**. Позволяет запускать задачи сразу после завершения их зависимостей, не дожидаясь окончания всей стадии (stage).

Подробное определение: [Определения директив](./directives_definitions.md).

## Основные концепции

По умолчанию задачи в стадии выполняются параллельно, а стадии — последовательно. `needs` нарушает эту модель:

- Задача запускается **сразу** после завершения указанных в `needs` задач
- Не нужно ждать окончания всей стадии
- Создается **направленный ациклический граф (DAG)**

**Важно:** `needs` автоматически устанавливает `dependencies`, загружая артефакты от указанных задач. Для отмены загрузки артефактов используйте: `dependencies: []`. Подробнее о директивах: [directives_definitions.md](./directives_definitions.md).

### `needs: []` — немедленный запуск

Пустой массив `needs: []` означает, что задача не зависит ни от одной другой задачи и запускается **сразу** при старте пайплайна, независимо от стадий. Используется для опциональных задач, которые не должны блокировать выполнение других: нотификации, линтеры, сбор метрик.

```yaml
notify:
  stage: final
  needs: []
  script:
    - echo "Уведомление отправляется сразу"
```

### Расширенный синтаксис `needs`

Помимо простого перечисления имён задач, `needs` поддерживает объектный синтаксис с управлением загрузкой артефактов:

```yaml
test:auth:
  stage: test
  needs:
    - job: "build:auth"
      artifacts: false  # Не загружать артефакты из build:auth
    - job: "build:payment"
      artifacts: true   # Загрузить артефакты (поведение по умолчанию)
```

- `artifacts: true` — загрузить артефакты (значение по умолчанию)
- `artifacts: false` — не загружать артефакты, используется только порядок выполнения

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

См. также:
- [Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)
- [Определения директив](./directives_definitions.md)
- [Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)
- [Матричные сборки и сериализация](./matrix_builds_and_serialization.md)
