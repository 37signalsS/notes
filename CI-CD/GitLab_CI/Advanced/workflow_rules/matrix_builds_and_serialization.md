# Матричные сборки и сериализация

## Определения

- **`parallel:matrix`**: Директива для запуска одного задания несколько раз с разными комбинациями переменных. Используется для тестирования на разных версиях ПО, архитектурах или окружениях.
- **`resource_group`**: Гарантирует, что одновременно выполняется только одна задача для определенной группы ресурсов. Предотвращает гонки состояний при деплое.

## Основные концепции

**`parallel:matrix`** создаёт несколько экземпляров задачи с разными значениями переменных. Каждый экземпляр выполняется параллельно.

**`resource_group`** создаёт очередь на выполнение задач с одинаковым именем группы. Полезно для деплоя в одно окружение из нескольких пайплайнов.

**Различие:** `parallel:matrix` ускоряет тестирование, `resource_group` предотвращает гонки состояний.

## Практические сценарии

### Параллелизация тестов с `parallel: N` (sharding)

`parallel: N` запускает N идентичных копий job. Каждая копия получает переменные `$CI_NODE_INDEX` (1..N) и `$CI_NODE_TOTAL` (N) — можно делить тест-файлы по индексу.

```yaml
test:
  stage: test
  parallel: 4
  script:
    - pytest --shard=$CI_NODE_INDEX/$CI_NODE_TOTAL tests/
```

GitLab создаст 4 job: `test 1/4`, `test 2/4`, `test 3/4`, `test 4/4`.

### Параметризация деплоя с `parallel: matrix`

`parallel:matrix` запускает копии job с разными комбинациями переменных. Имена формируются автоматически: `deploy: [dev]`, `deploy: [stage]`, `deploy: [prod]`.

```yaml
deploy:
  stage: deploy
  script:
    - helm upgrade --install app ./chart --namespace $ENV
  parallel:
    matrix:
      - ENV: [dev, stage, prod]
        REGION: [ru-1]
      - ENV: [prod]
        REGION: [ru-1, ru-2]
```

GitLab развернёт в конкретные job: `deploy: [dev, ru-1]`, `deploy: [stage, ru-1]`, `deploy: [prod, ru-1]`, `deploy: [prod, ru-2]`.

### Тестирование на разных версиях с `parallel:matrix`

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

**Go-сервис: тесты на 3 версиях + артефакты в следующую стадию:**

```yaml
stages:
  - test
  - coverage

variables:
  COVERAGE_FILE: "coverage-${GO_VERSION}.out"  # суффикс версии — без конфликтов имён

test:
  stage: test
  image: golang:${GO_VERSION}
  parallel:
    matrix:
      - GO_VERSION: ["1.21", "1.22", "1.23"]
  script:
    - go test -race -coverprofile="$COVERAGE_FILE" ./...
  artifacts:
    paths:
      - "$COVERAGE_FILE"
    expire_in: 1 hour

merge-coverage:
  stage: coverage
  needs:
    - job: test
      parallel:
        matrix:
          - GO_VERSION: ["1.21", "1.22", "1.23"]
  script:
    - go tool cover -html=coverage-1.23.out -o coverage.html
```

- `$GO_VERSION` в имени файла — разные матрицы не перезаписывают артефакты друг друга
- `expire_in: 1 hour` — артефакты не засоряют хранилище после сборки отчёта
- `needs` с `parallel: {matrix: ...}` — следующая стадия ждёт ВСЕ матричные джобы
- Артефакты каждой матричной джобы изолированы: `test: [1.21]`, `test: [1.22]`, `test: [1.23]`

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

## Альтернативы

Для более сложной параметризации или когда нужна полноценная изоляция (отдельный pipeline per env) — используйте `trigger` + downstream pipeline:

```yaml
deploy:
  stage: deploy
  trigger:
    include: .gitlab-ci-deploy.yml
    strategy: depend
  parallel:
    matrix:
      - ENV: [dev, stage, prod]
```

Каждая job из матрицы запустит свой downstream-пайплайн с переменной `ENV`.

## См. также

- [Определения директив](./directives_definitions.md) — подробное описание `parallel:matrix` и `resource_group`
- [DAG с needs](./dag_with_needs.md) — организация зависимостей между задачами
- [Правила запуска задач](./job_rules.md) — условия выполнения jobs через `rules`
