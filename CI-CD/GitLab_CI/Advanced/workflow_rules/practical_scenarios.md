# Матричные сборки и сериализация

## Определения

- **`parallel:matrix`**: Директива для запуска одного задания несколько раз с разными комбинациями переменных. Используется для тестирования на разных версиях ПО, архитектурах или окружениях.
- **`resource_group`**: Гарантирует, что одновременно выполняется только одна задача для определенной группы ресурсов. Предотвращает гонки состояний при деплое.

## Практические сценарии

### Матричные сборки с `parallel:matrix`

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

## Ограничения

- **Максимум 4 кэша** на задачу
- **Максимум 1000 downstream pipelines** в иерархии

## Связанные документы

- **[Определения директив](./directives_definitions.md)** — ключевые директивы
- **[DAG с needs](./dag_with_needs.md)** — управление зависимостями
- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции
