# Матричные сборки и сериализация

## Определения

- **`parallel:matrix`**: Директива для запуска одного задания несколько раз с разными комбинациями переменных. Используется для тестирования на разных версиях ПО, архитектурах или окружениях.
- **`resource_group`**: Гарантирует, что одновременно выполняется только одна задача для определенной группы ресурсов. Предотвращает гонки состояний при деплое.

Подробные определения: [Определения директив](./directives_definitions.md).

## Основные концепции

**`parallel:matrix`** создаёт несколько экземпляров задачи с разными значениями переменных. Каждый экземпляр выполняется параллельно.

**`resource_group`** создаёт очередь на выполнение задач с одинаковым именем группы. Полезно для деплоя в одно окружение из нескольких пайплайнов.

**Различие:** `parallel:matrix` ускоряет тестирование, `resource_group` предотвращает гонки состояний.

## Практические сценарии

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

Создаётся 5 задач: 3 × unit-тесты (Node 18, 20, 22) + 2 × integration/e2e (Node 20).

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

## Ограничения

- Максимум 4 кэша на задачу
- Максимум 1000 downstream pipelines в иерархии
