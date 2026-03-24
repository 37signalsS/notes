# Артефакты в GitLab CI

## Базовая конфигурация

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

## Ключевые параметры артефактов

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `paths` | Файлы/директории для сохранения | `paths: [dist/, build/*.jar]` |
| `exclude` | Файлы для исключения из артефактов | `exclude: ["**/*.log"]` |
| `expire_in` | Срок хранения | `expire_in: 1 week`, `expire_in: never` |
| `name` | Имя архива артефактов | `name: "build-$CI_COMMIT_SHA"` |
| `when` | Когда сохранять артефакты | `when: on_success` (по умолчанию) |
| `untracked` | Включать неотслеживаемые Git файлы | `untracked: true` |
| `reports` | Специальные отчёты (JUnit, coverage) | `reports: {junit: test.xml}` |

## Передача артефактов между задачами

### Автоматическая передача

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

### Явное указание зависимостей

```yaml
test:
  stage: test
  script:
    - ./test.sh
  dependencies:
    - build
  # Загружает артефакты только из задачи 'build'
```

### Отключение загрузки артефактов

```yaml
deploy:
  stage: deploy
  script:
    - ./deploy.sh
  dependencies: []
  # Не загружает никакие артефакты
```

## Отчёты через артефакты

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

## Срок хранения артефактов

| Значение | Описание |
| :--- | :--- |
| `30 days` | По умолчанию |
| `1 week` | Для временных артефактов |
| `never` | Для релизных артефактов |
| `1 year` | Для долгосрочного хранения |

**Пример:**

```yaml
release:
  stage: release
  script:
    - make package
  artifacts:
    paths:
      - releases/*.tar.gz
    expire_in: never  # Постоянное хранение для релизов
```

## Ограничения артефактов

| Ограничение | Значение |
| :--- | :--- |
| Максимальный размер одного артефакта | Зависит от настроек GitLab (по умолчанию 100 МБ) |
| Общий размер артефактов в пайплайне | Ограничен настройками сервера |
| Срок хранения | По умолчанию 30 дней |

## Артефакты и `needs` (DAG)

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

Для отмены: `dependencies: []`

## Связанные документы

- **[Кэширование и артефакты — Обзор](./caching_overview.md)** — общая информация, кэш vs. артефакты
- **[Ключи кэша](./cache_keys.md)** — типы ключей, политики, fallback
- **[Лучшие практики](./cache_best_practices.md)** — оптимизация и troubleshooting
- **[Артефакты и управление релизами](../../../artifact_management.md)** — общая теория
- **[Основы GitLab CI](../../Concepts/gitlab_ci_basics.md)** — базовые концепции
