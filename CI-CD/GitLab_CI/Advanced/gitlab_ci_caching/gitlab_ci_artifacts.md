# Артефакты в GitLab CI

## Определения

**Артефакт (Artifact)** — файлы или директории, которые сохраняются после выполнения задачи GitLab CI и передаются между стадиями пайплайна. Артефакты хранятся на сервере GitLab и используются для передачи результатов сборки, отчётов тестирования, бинарных файлов.

**Отчёт (Report)** — специальный тип артефакта, который GitLab автоматически обрабатывает и отображает в интерфейсе (JUnit, coverage, code quality).

Подробные определения и сравнение с кэшем: [Обзор кэширования](./caching_overview.md).

## Базовые концепции

### Эфемерность контейнеров и необходимость артефактов

GitLab Runner с типом Docker запускает каждую задачу (job) в отдельном изолированном контейнере. Контейнеры — эфемерные среды: при завершении задачи контейнер уничтожается вместе со всеми файлами, которые были созданы в процессе выполнения скриптов.

Это означает, что без механизма артефактов:

- Файл, созданный в одной задаче, **недоступен** в другой задаче, даже если они в одном пайплайне
- Каждая задача начинает работу с чистого образа, без следов предыдущих задач
- Попытка прочитать файл, созданный в другой задаче, приведёт к ошибке (файл не найден)

**Артефакты решают эту проблему:** GitLab Runner автоматически архивирует указанные файлы, загружает их на сервер GitLab, а затем восстанавливает в контейнерах следующих задач.

```yaml
# БЕЗ артефактов — вторая задача упадёт с ошибкой «file not found»
create_file:
  stage: create
  script:
    - echo "Привет, мир" > hello.txt
    - ls -la hello.txt  # файл существует в рамках текущей задачи

use_file:
  stage: use
  script:
    - cat hello.txt  # ОШИБКА: файла нет, контейнер создан заново

# С артефактами — файл передаётся между задачами
create_file:
  stage: create
  script:
    - echo "Привет, мир" > hello.txt
  artifacts:
    paths:
      - hello.txt
    expire_in: 1 hour

use_file:
  stage: use
  script:
    - cat hello.txt  # → Привет, мир
```

По умолчанию артефакты задачи доступны **во всех задачах последующих стадий** того же пайплайна. Для передачи артефактов между разными пайплайнами (downstream pipelines) используются механизмы [multi-project pipelines](../Downstream_Pipelines/multi_project_pipelines.md) и [parent-child pipelines](../Downstream_Pipelines/parent_child_pipelines.md).

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

Срок хранения задаётся параметром `expire_in`. Формат: `<число> <единица>` (`1 hour`, `7 days`, `30 days`) или `never` (бессрочно).

| Значение | Когда использовать |
| :--- | :--- |
| `1 week` | Для временных артефактов (промежуточные сборки, логи отладки) |
| `30 days` | По умолчанию в GitLab (баланс между доступностью и хранилищем) |
| `1 year` | Для артефактов, которые нужно сохранить долгосрочно |
| `never` | Для релизных артефактов, которые не должны удаляться автоматически |

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
| Максимальный размер артефакта | Настраивается на уровне экземпляра GitLab (по умолчанию зависит от версии) |
| Общий размер всех артефактов проекта | Ограничен настройками сервера и доступным хранилищем |
| Срок хранения | По умолчанию 30 дней (настраивается через `expire_in`) |

**Примечание:** Конкретные лимиты зависят от версии GitLab (Self-Managed, SaaS) и конфигурации администратора. Актуальные значения можно проверить в настройках экземпляра (**Admin Area → Settings → General → Continuous Integration and Deployment**).

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

Кэш ускоряет установку зависимостей, артефакты передают результаты сборки — подробный пример конфигурации приведён в разделе **[Комбинация кэша и артефактов](./cache_scenarios.md#сценарий-7--комбинация-кэша-и-артефактов)**.

### Сценарий 4: Отладка — сохранение логов приложения при падении задачи

Артефакты полезны не только для передачи файлов между задачами, но и для отладки. Если задача завершается с ошибкой, логи приложения могут помочь в диагностике — даже если они не попали в стандартный вывод (stdout) задачи.

```yaml
integration_test:
  stage: test
  script:
    - ./run_tests.sh --log-file=test-debug.log 2>&1
  artifacts:
    paths:
      - test-debug.log
    expire_in: 3 days
    when: always  # Сохранять артефакты независимо от результата задачи
```

Ключевой параметр `when: always` гарантирует, что артефакты будут сохранены даже при failed-задаче. Это позволяет скачать и проанализировать логи после сбоя через интерфейс GitLab (кнопка **Job Artifacts** на странице задачи).

### Просмотр артефактов в интерфейсе GitLab

После выполнения задачи с артефактами в GitLab появляется секция **Job Artifacts** на странице задачи. Доступные действия:

- **Download** — скачать архив со всеми артефактами задачи
- **Browse** — просмотр содержимого архива (для поддерживаемых форматов, например HTML-отчёты)

Артефакты также доступны через API GitLab:

```bash
# Скачать артефакты конкретной задачи
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<id>/jobs/<job_id>/artifacts"
```

## Дополнительная информация

### Общие рекомендации

1. **Устанавливайте `expire_in`** для временных артефактов, чтобы избежать переполнения хранилища
2. **Используйте `dependencies`** для явного указания задач, артефакты которых нужны
3. **Применяйте `reports`** для автоматической интеграции отчётов в интерфейс GitLab
4. **Исключайте лишние файлы** через `exclude` для уменьшения размера артефактов
5. **Для релизных артефактов** используйте `expire_in: never`
6. **Для отладки** используйте `when: always`, чтобы артефакты сохранялись даже при падении задачи

### См. также

- [Обзор кэширования и артефактов](./caching_overview.md)
- [Лучшие практики кэширования](./cache_best_practices.md)
- [Управление артефактами](../../../CI-CD/artifact_management.md)
