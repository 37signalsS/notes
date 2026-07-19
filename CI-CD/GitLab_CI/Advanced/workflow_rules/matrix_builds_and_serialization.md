# Матричные сборки и сериализация задач

## Определения

- **parallel:matrix**: Директива для запуска задачи в нескольких экземплярах с разными комбинациями переменных. Позволяет избежать дублирования кода при тестировании на различных версиях или окружениях.
- **resource_group**: Механизм блокировки (мьютекс), гарантирующий, что в один момент времени выполняется только одна задача из группы. Используется для предотвращения конфликтов при развертывании (гонки состояний).

## Основные концепции

### Параллелизм и матрицы (parallel:matrix)

Директива `parallel:matrix` создает набор задач на основе декартова произведения указанных переменных.

**Ключевые особенности:**
- **Изоляция:** Каждая задача в матрице имеет собственный контекст и артефакты.
- **Именование:** GitLab автоматически добавляет значения переменных в имя задачи (например, `test: [ruby:3.0, postgres:14]`).
- **Лимиты:** (версия 18.x+) Введены настраиваемые лимиты конкурентности для матриц, чтобы один пайплайн не занимал все доступные раннеры.

### Сериализация и очереди (resource_group)

`resource_group` необходим, когда задача взаимодействует с внешним ресурсом, не поддерживающим параллельный доступ (например, база данных при миграции).

**Режимы обработки очереди (Process Modes):**
- **unordered:** (по умолчанию) Задачи запускаются по мере готовности без соблюдения очередности.
- **oldest_first:** Гарантирует выполнение в порядке создания пайплайнов. Рекомендуется для соблюдения хронологии изменений.
- **newest_first:** Приоритет отдается самой свежей задаче, остальные могут быть отменены или ждать. Полезно для деплоя, где важен только последний результат.

**Важно:** Для задач с `resource_group` рекомендуется устанавливать `interruptible: false`, чтобы автоотмена не прервала критическую операцию.

## Практические сценарии

### Параллелизация тестов с `parallel: N` (sharding)

`parallel: N` запускает N идентичных копий задач (jobs). Каждая копия получает переменные `$CI_NODE_INDEX` (1..N) и `$CI_NODE_TOTAL` (N) — можно делить тест-файлы по индексу.

```yaml
test:
  stage: test
  parallel: 4
  script:
    - pytest --shard=$CI_NODE_INDEX/$CI_NODE_TOTAL tests/
```

GitLab создаст 4 задачи (jobs): `test 1/4`, `test 2/4`, `test 3/4`, `test 4/4`.

### Параметризация деплоя с `parallel: matrix`

`parallel:matrix` запускает копии задач (jobs) с разными комбинациями переменных. Имена формируются автоматически: `deploy: [dev]`, `deploy: [stage]`, `deploy: [prod]`.

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

GitLab развернёт в конкретные задачи (jobs): `deploy: [dev, ru-1]`, `deploy: [stage, ru-1]`, `deploy: [prod, ru-1]`, `deploy: [prod, ru-2]`.

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
- `needs` с `parallel: {matrix: ...}` — следующая стадия ждёт ВСЕ матричные задачи (jobs)
- Артефакты каждой матричной задачи (job) изолированы: `test: [1.21]`, `test: [1.22]`, `test: [1.23]`

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

### Сериализация развертываний с resource_group

**Защита промышленной среды (Production):**

```yaml
deploy_prod:
  stage: deploy
  script:
    - ./scripts/deploy.sh production
  resource_group: production
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

**Использование режима хронологической очереди:**

```yaml
database_migration:
  stage: deploy
  resource_group: db_migrate
  resource_group_process_mode: oldest_first # Строго по порядку коммитов
  script:
    - ./migrate.sh
```

## Дополнительная информация

### Выбор метода: Матрица vs Дочерние пайплайны

- **Используйте parallel:matrix**, если задачи простые и отличаются только переменными. Это быстрее и нагляднее в интерфейсе.
- **Используйте trigger (downstream)**, если для каждого варианта (например, для каждого облачного провайдера) нужен полноценный набор стадий (сборка, тест, деплой) с независимым жизненным циклом.

### Ограничения и лимиты

1. **Артефакты:** Помните, что каждая задача в матрице создает свой набор артефактов. При большой матрице (например, 50 комбинаций) это может существенно нагрузить хранилище.
2. **Зависимости:** При использовании `needs` в матричных задачах можно указывать зависимость как от всей матрицы целиком, так и от конкретных экземпляров (через `needs:parallel:matrix`).

### Смотрите также

- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — общие методы оптимизации, описание `workflow` и `auto_cancel`.
- **[DAG с использованием needs](./dag_with_needs.md)** — построение графа зависимостей.