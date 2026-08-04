# Матричные сборки и сериализация задач

## Определения

- **`parallel:matrix`**: Директива для декларативного описания набора задач на основе комбинаций переменных. Генерирует декартово произведение входных данных, избавляя от дублирования YAML-кода.
- **`parallel: N`**: Механизм шардирования (sharding), запускающий N идентичных копий задачи для параллельной обработки данных (например, тестов).
- **`resource_group`**: Высокоуровневый механизм блокировки (мьютекс) на стороне сервера GitLab. Гарантирует эксклюзивный доступ задачи к внешнему ресурсу, предотвращая гонки состояний при развертывании.

## Основные концепции

### Параллелизм и матрицы (parallel:matrix)

Матрицы позволяют эффективно масштабировать тестирование. GitLab вычисляет комбинации и создает отдельные задачи (jobs) в рамках одной стадии.

**Технические нюансы:**
- **Лимиты (19.x):** По умолчанию лимит составляет **200 задач** на одну матрицу. Превышение лимита приведет к ошибке валидации пайплайна.
- **Исключения (`exclude`):** Позволяет точечно удалять нежелательные или несовместимые комбинации из декартова произведения.
- **Интерполяция:** Переменные матрицы могут использовать значения из `spec:inputs` или глобальных переменных.
- **Именование:** Имя задачи в интерфейсе дополняется значениями переменных в квадратных скобках (например, `test: [ubuntu, node:20]`).

### Сериализация и очереди (resource_group)

Когда задача требует монопольного доступа (например, `terraform apply` или миграция БД), используется `resource_group`.

**Режимы обработки очереди (`resource_group_process_mode`):**

| Режим | Поведение | Типовой сценарий |
| :--- | :--- | :--- |
| **`unordered`** | Запуск в порядке готовности раннеров. | Базовая блокировка без строгих требований к хронологии. |
| **`oldest_first`** | Строгое соблюдение порядка создания пайплайнов. | **Миграции БД**, последовательное накатывание патчей. |
| **`newest_first`** | Приоритет самой свежей задачи; старые могут быть пропущены. | **CD в Web-приложениях**: важен только актуальный код, старые деплои неактуальны. |

**Важно:** Для задач с `resource_group` рекомендуется устанавливать `interruptible: false`, чтобы критическая операция (например, обновление схемы БД) не была прервана механизмом `auto_cancel`.

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

### Использование исключений (exclude)

Позволяет отсекать невозможные или нежелательные комбинации, предотвращая запуск заведомо провальных задач.

```yaml
test_compatibility:
  stage: test
  parallel:
    matrix:
      - OS: [linux, windows, macOS]
        ARCH: [amd64, arm64]
        exclude:
          - OS: macOS
            ARCH: amd64 # Поддержка только Apple Silicon
          - OS: windows
            ARCH: arm64 # Специфический кейс, временно исключен
  script:
    - ./test_on_${OS}_${ARCH}.sh
```

### Динамические зависимости (needs:parallel:matrix)

До GitLab 16.3 задачи следующей стадии должны были ждать завершения *всей* матрицы предыдущей. Теперь доступно сопоставление 1:1, что критически ускоряет пайплайн.

```yaml
build:
  stage: build
  parallel:
    matrix:
      - PROVIDER: [aws, gcp, azure]
  script: ./build.sh $PROVIDER

# Каждый тест запускается СРАЗУ после завершения своей сборки
test:
  stage: test
  parallel:
    matrix:
      - PROVIDER: [aws, gcp, azure]
  needs:
    - job: build
      parallel:
        matrix:
          - PROVIDER: [$PROVIDER]
  script: ./test.sh $PROVIDER
```

## Дополнительная информация

### Выбор метода: Матрица vs Дочерние пайплайны

| Критерий | `parallel:matrix` | Downstream (trigger) |
| :--- | :--- | :--- |
| **Сложность** | Низкая (одна задача) | Высокая (целый пайплайн) |
| **Визуализация** | Группа задач в одной стадии | Отдельный граф пайплайна |
| **Артефакты** | Прямой доступ между задачами | Требуется `needs:project` или API |
| **Применение** | Разные версии языка, ОС, флаги | Разные облака, сложные релизы |

### Ограничения и лимиты

1. **Лимит задач:** По умолчанию **200** на одну матрицу. Для обхода используйте несколько блоков в `parallel:matrix` или Downstream пайплайны.
2. **Артефакты:** При матрице 50+ задач суммарный объем артефактов может исчерпать квоту проекта. Используйте `expire_in` с минимальным временем.
3. **Зависимости:** `needs` может ссылаться как на всю матрицу (по имени задачи), так и на конкретный инстанс через блок `parallel:matrix`.

### Смотрите также

- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — общие методы оптимизации, описание `workflow` и `auto_cancel`.
- **[DAG с использованием needs](./dag_with_needs.md)** — детальное построение графа зависимостей.

---

**Надёжность:** 10 (SSoT + Документация GitLab 17.x–19.x)
**Свежесть:** GitLab 19.2 (2026)
**Триггеры обновления:** Изменение дефолтных лимитов матриц, новые режимы `resource_group`.