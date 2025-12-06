### Расширенное управление Workflow

#### `rules` — Гибкие правила запуска

`rules` — это более мощная и гибкая альтернатива устаревшим директивам `only/except`. Они позволяют определять сложные условия для включения задачи в пайплайн. Правила проверяются по порядку, и первое же совпадение определяет поведение задачи.

**Ключевые условия в `rules`:**
- **`if`**: Основное условие, которое проверяет значение переменных.
- **`changes`**: Задача добавляется в пайплайн, только если были изменены указанные файлы или пути. Это **чрезвычайно полезно для монорепозиториев**, так как позволяет запускать сборку и тесты только для затронутых компонентов.
- **`when`**: Определяет, как будет выполняться задача (`on_success`, `manual`, `always`, `delayed`).

### Запуск задач только для Merge Request'ов

Используйте директиву `rules` с условием проверки источника пайплайна (`$CI_PIPELINE_SOURCE == "merge_request_event"`) для запуска задач только при создании merge request.

```yaml
test_job:
  stage: test
  script:
    - echo "Running tests for merge request"
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Дополнительные варианты контроля:**

```yaml
# Запуск только для MR в определенную ветку
test_mr_to_main:
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'

# Запуск при изменении определенных файлов
test_on_changes:
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes:
        - "src/**/*"
        - "tests/**/*"
```

Документация: [Merge Request Pipelines](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/)

### Контроль запуска задач (Jobs)

Существует несколько механизмов для контроля выполнения задачи (job):

1.  **Rules (рекомендуемый способ)**

    Наиболее гибкий и современный подход, позволяющий определять сложные условия для включения задачи в пайплайн. Правила проверяются по порядку, и первое же совпадение определяет поведение задачи.

    ```yaml
    deploy_job:
      script:
        - echo "Deploying to production"
      rules:
        - if: '$CI_COMMIT_BRANCH == "main"'
        - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
          when: manual
        - when: never
    ```

2.  **Only/Except (устаревший)**

    Устаревшие директивы, которые позволяют запускать или исключать задачи на основе имени ветки, тега или типа события. Рекомендуется использовать `rules` вместо `only/except`.

    ```yaml
    build_job:
      script:
        - echo "Building application"
      only:
        - main
        - develop
      except:
        - tags
    ```

3.  **Встроенные переменные**

    Использование предопределенных переменных GitLab CI в условиях `if` внутри `rules` позволяет гибко реагировать на различные события и состояния репозитория.

    *   `$CI_COMMIT_BRANCH` - название текущей ветки.
    *   `$CI_PIPELINE_SOURCE` - источник запуска пайплайна (например, `push`, `merge_request_event`, `schedule`).
    *   `$CI_COMMIT_TAG` - тег коммита.
    *   `$CI_PROJECT_NAME`: Имя проекта.
    *   `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` - целевая ветка Merge Request'а.

4.  **Changes и Paths**

    Директива `changes` в `rules` позволяет запускать задачи только в том случае, если были изменены определенные файлы или пути. Это очень полезно для монорепозиториев, где разные части проекта находятся в разных директориях.

    ```yaml
    test_frontend:
      script:
        - npm run test
      rules:
        - changes:
            - "frontend/**/*"
            - "package.json"
    ```

5.  **Manual jobs**

    Задачи с `when: manual` требуют ручного запуска через интерфейс GitLab. Это часто используется для деплоя в production или других критически важных операций, которые требуют подтверждения человеком.

    ```yaml
    deploy_production:
      script:
        - echo "Deploying to production"
      when: manual
      only:
        - main
    ```

6.  **Через `when`**

    Директива `when` определяет, при каких условиях будет выполняться задача:

    *   `when: always` - всегда выполнять, независимо от статуса предыдущих задач.
    *   `when: on_success` - только при успешном завершении всех предыдущих задач в этой стадии (по умолчанию).
    *   `when: on_failure` - только при провале хотя бы одной предыдущей задачи в этой стадии.
    *   `when: manual` - запуск вручную.
    *   `when: delayed` - запуск с задержкой после успешного завершения предыдущих задач.
    *   `when: never` - никогда не выполнять (может использоваться в `rules` для исключения задач).

```yaml
deploy_job:
  stage: deploy
  script:
    - echo "Deploying to production"
  rules:
    # Запускать, только если изменены файлы в директории 'backend/'
    - changes:
        - backend/**/*
    # И при этом только для ветки main
    - if: '$CI_COMMIT_BRANCH == "main"' 
    # Или для любого тега
    - if: '$CI_COMMIT_TAG'
    # Во всех остальных случаях — не запускать задачу
    - when: never
```
Задачи по расписанию (Cron-like): GitLab CI можно использовать для выполнения задач по расписанию, аналогично `cron` в Linux. Это делается путем создания "Расписания" (Schedules) для пайплайна через интерфейс GitLab. В `rules` можно использовать `$CI_PIPELINE_SOURCE == "schedule"` для запуска определенных заданий только при таком типе триггера.

#### `needs` — Построение направленного ациклического графа (DAG)

Ключевая возможность для оптимизации времени выполнения пайплайна. По умолчанию, все задачи в одной стадии (`stage`) должны успешно завершиться, прежде чем начнется следующая стадия. `needs` ломает эту строгую последовательность и превращает пайплайн в направленный ациклический граф (DAG).

Задача с директивой `needs` может стартовать, как только завершатся указанные в `needs` задачи, **не дожидаясь окончания всей их стадии**.

**Пример:**

Рассмотрим пайплайн со стадиями `build` и `test`.
- Стадия `build` содержит три параллельные задачи: `build:web` (15 сек), `build:android` (30 сек), `build:ios` (45 сек).
- Стадия `test` содержит две задачи: `test:web` и `test:all`.
- `test:web` зависит только от `build:web`.

```yaml
stages:
  - build
  - test

build:web:
  stage: build
  script:
    - sleep 15
    - echo "Web built"

build:android:
  stage: build
  script:
    - sleep 30
    - echo "Android built"

build:ios:
  stage: build
  script:
    - sleep 45
    - echo "iOS built"

test:web:
  stage: test
  needs: ["build:web"] # Эта задача зависит только от build:web
  script:
    - echo "Testing web..."

test:all:
  stage: test
  script: # Нет 'needs', значит, ждет окончания всей стадии 'build'
    - echo "Testing all platforms..."
```

**Порядок выполнения:**
1.  Запускаются все три задачи `build:*` одновременно.
2.  Через **15 секунд** `build:web` завершается.
3.  **Сразу после этого** запускается `test:web`, не дожидаясь `build:android` и `build:ios`.
4.  Через **45 секунд** `build:ios` (самая долгая задача в стадии `build`) завершается.
5.  **Только после этого** запускается `test:all`, так как она следует стандартному порядку стадий.

Таким образом, `needs` позволяет значительно ускорить получение обратной связи, запуская зависимые задачи раньше.

#### `parallel:matrix` — Матричные сборки

Позволяет запускать одно и то же задание несколько раз с разными комбинациями переменных. Идеально для тестирования на разных версиях ПО или для разных архитектур.

```yaml
test:
  stage: test
  script: "echo 'Testing with $PROVIDER on $STACK'"
  parallel:
    matrix:
      - PROVIDER: [aws, gcp]
        STACK: [nodejs, python]
```
Этот пример создаст 4 параллельных задания `test`.
