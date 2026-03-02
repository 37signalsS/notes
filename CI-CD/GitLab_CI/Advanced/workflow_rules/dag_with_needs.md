# Построение DAG с `needs`

## Определения

**`needs`**: Директива для создания **направленного ациклического графа (DAG)**. Позволяет запускать задачи сразу после завершения зависимостей, не дожидаясь окончания всей стадии.

## Основные концепции

По умолчанию задачи в стадии выполняются параллельно, а стадии — последовательно. `needs` нарушает эту модель:

- Задача запускается **сразу** после завершения указанных в `needs` задач
- Не нужно ждать окончания всей стадии
- Создается **направленный ациклический граф (DAG)**

**Важно:** `needs` автоматически устанавливает `dependencies`, загружая артефакты от указанных задач. Для отмены: `dependencies: []`.

## Практические сценарии

### Ускорение пайплайна с `needs` (DAG)

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

### Complex DAG с несколькими зависимостями

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

### Сериализация развертываний с `resource_group`

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

## Связанные документы

- **[Определения директив](./directives_definitions.md)** — ключевые директивы
- **[workflow:rules и pipeline inputs](./pipeline_inputs.md)** — управление пайплайнами
- **[Правила запуска задач](./job_rules.md)** — условия для задач
- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции
