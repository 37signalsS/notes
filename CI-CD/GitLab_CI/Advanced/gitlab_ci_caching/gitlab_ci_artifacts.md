# Артефакты в GitLab CI

## Определения

**Артефакт (Artifact)** — файлы или директории, которые сохраняются после выполнения задачи GitLab CI и передаются между стадиями пайплайна. Артефакты хранятся на сервере GitLab и используются для передачи результатов сборки, отчётов тестирования, бинарных файлов.

**Отчёт (Report)** — специальный тип артефакта, который GitLab автоматически обрабатывает и отображает в интерфейсе (JUnit, coverage, code quality).

Подробные определения и сравнение с кэшем: [Концепции кэширования](./cache_concepts.md).

## Основные концепции

### Базовая конфигурация

```yaml
job_name:
  stage: build
  script:
    - make build
  artifacts:
    paths:
      - bin/
      - dist/*.jar
    exclude:
      - "**/*.log"
    expire_in: 30 days
```

### Ключевые параметры артефактов

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `paths` | Файлы/директории для сохранения | `paths: [dist/, build/*.jar]` |
| `exclude` | Файлы для исключения из артефактов | `exclude: ["**/*.log"]` |
| `expire_in` | Срок хранения | `expire_in: 1 week`, `expire_in: never` |
| `name` | Имя архива артефактов | `name: "build-$CI_COMMIT_SHA"` |
| `when` | Когда сохранять артефакты | `when: on_success` (по умолчанию) |
| `untracked` | Включать неотслеживаемые Git файлы | `untracked: true` |
| `reports` | Специальные отчёты (JUnit, coverage) | `reports: {junit: test.xml}` |

### Передача артефактов между задачами

**Автоматическая передача** — артефакты загружаются из всех задач предыдущих стадий:

```yaml
build:
  stage: build
  script:
    - ./build.sh
  artifacts:
    paths:
      - dist/

test:
  stage: test
  script:
    - ./test.sh
  # Автоматически загружает артефакты из всех задач предыдущих стадий
```

**Явное указание зависимостей** — загрузка артефактов только из указанных задач:

```yaml
test:
  stage: test
  script:
    - ./test.sh
  dependencies:
    - build
  # Загружает артефакты только из задачи 'build'
```

**Отключение загрузки артефактов**:

```yaml
deploy:
  stage: deploy
  script:
    - ./deploy.sh
  dependencies: []
  # Не загружает никакие артефакты
```

### Отчёты через артефакты

GitLab автоматически обрабатывает специальные типы отчётов:

```yaml
test:
  stage: test
  script:
    - pytest --junitxml=test-results.xml --cov=app --cov-report=xml
  artifacts:
    reports:
      junit: test-results.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

**Поддерживаемые типы отчётов:**

- `junit` — результаты тестов
- `coverage_report` — отчёт о покрытии кода
- `codequality` — анализ качества кода
- `container_metadata` — метаданные контейнера
- `dotenv` — переменные окружения для следующих задач
- `terraform` — план Terraform
- `sast`, `dast`, `dependency_scanning` — отчёты безопасности

### Срок хранения артефактов

| Значение | Описание |
| :--- | :--- |
| `30 days` | По умолчанию |
| `1 week` | Для временных артефактов |
| `never` | Для релизных артефактов |
| `1 year` | Для долгосрочного хранения |

**Пример постоянного хранения для релизов:**

```yaml
release:
  stage: release
  script:
    - make package
  artifacts:
    paths:
      - releases/*.tar.gz
    expire_in: never
```

### Ограничения артефактов

| Ограничение | Значение |
| :--- | :--- |
| Максимальный размер одного артефакта | Зависит от настроек GitLab (по умолчанию 100 МБ) |
| Общий размер артефактов в пайплайне | Ограничен настройками сервера |
| Срок хранения | По умолчанию 30 дней |

### Артефакты и `needs` (DAG)

При использовании `needs` артефакты передаются автоматически:

```yaml
build:
  stage: build
  script:
    - ./build.sh
  artifacts:
    paths:
      - dist/

test:
  stage: test
  script:
    - ./test.sh
  needs:
    - build
  # Автоматически загружает артефакты из 'build'
```

Для отмены загрузки: `dependencies: []`

## Практические сценарии

### Сценарий 1: Передача временных артефактов

`build` стадия создает артефакт, `test` стадия его использует:

```yaml
stages:
  - build
  - test

build:
  stage: build
  script:
    - ./gradlew clean build
    - mkdir -p dist && cp build/libs/app.jar dist/app-1.2.3-${CI_COMMIT_SHORT_SHA}.jar
    - sha256sum dist/* > dist/checksums.txt
  artifacts:
    paths:
      - dist/
    expire_in: 7 days

release:
  stage: release
  script: make release
  artifacts:
    paths: [release/*.tar.gz]
    expire_in: never
```

### Сценарий 2: Отчёты о тестах и покрытии

```yaml
test:
  stage: test
  script:
    - pytest --junitxml=test-results.xml --cov=app --cov-report=xml
  artifacts:
    paths:
      - test-results/
    reports:
      junit: test-results.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 week
```

### Сценарий 3: Комбинация кэша и артефактов

Кэш ускоряет установку зависимостей, артефакты передают результаты сборки:

```yaml
build:
  stage: build
  script:
    - npm ci
    - npm run build
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
    policy: pull-push
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test:
  stage: test
  script:
    - npm test
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
    policy: pull
  dependencies:
    - build
  artifacts:
    reports:
      junit: test-results.xml
```

Подробнее о кэшировании: [обзор кэширования и артефактов](./caching_overview.md), [ключи кэша](./cache_keys.md).

## Дополнительная информация

### Общие рекомендации

1. **Устанавливайте `expire_in`** для временных артефактов, чтобы избежать переполнения хранилища
2. **Используйте `dependencies`** для явного указания задач, артефакты которых нужны
3. **Применяйте `reports`** для автоматической интеграции отчётов в интерфейс GitLab
4. **Исключайте лишние файлы** через `exclude` для уменьшения размера артефактов
5. **Для релизных артефактов** используйте `expire_in: never`

Сравнение кэша и артефактов: [концепции кэширования](./cache_concepts.md), лучшие практики: [лучшие практики кэширования](./cache_best_practices.md).
