### Определения

-   **`rules`**: Мощный и гибкий механизм для определения сложных условий включения задачи в пайплайн. Является современной альтернативой устаревшим директивам `only/except`. Правила проверяются по порядку, и первое же совпадение определяет поведение задачи.
-   **`needs`**: Ключевая возможность для оптимизации времени выполнения пайплайна. `needs` ломает строгую последовательность стадий и превращает пайплайн в **направленный ациклический граф (DAG)**, позволяя запускать задачи сразу после завершения их зависимостей, не дожидаясь всей стадии.
-   **`parallel:matrix`**: Директива, которая позволяет запускать одно и то же задание несколько раз с разными комбинациями переменных. Идеально для тестирования на разных версиях ПО или для разных архитектур.

### Основные концепции

#### Гибкие правила запуска с `rules`

`rules` является рекомендуемым способом контроля запуска задач.

**Ключевые условия в `rules`:**
-   **`if`**: Основное условие, которое проверяет значение переменных.
-   **`changes`**: Задача добавляется в пайплайн, только если были изменены указанные файлы или пути. Это **чрезвычайно полезно для монорепозиториев**, так как позволяет запускать сборку и тесты только для затронутых компонентов.
-   **`when`**: Определяет, как будет выполняться задача. Возможные значения:
    *   `on_success`: Только при успешном завершении всех предыдущих задач в этой стадии (по умолчанию).
    *   `on_failure`: Только при провале хотя бы одной предыдущей задачи.
    *   `always`: Всегда выполнять, независимо от статуса предыдущих задач.
    *   `manual`: Запуск вручную через интерфейс GitLab.
    *   `delayed`: Запуск с задержкой после успешного завершения предыдущих задач.
    *   `never`: Никогда не выполнять (используется в `rules` для явного исключения задач).

#### Построение DAG с помощью `needs`

По умолчанию, все задачи в одной стадии (`stage`) должны успешно завершиться, прежде чем начнется следующая. Задача с директивой `needs` может стартовать, как только завершатся указанные в `needs` задачи, **не дожидаясь окончания всей их стадии**. Таким образом, `needs` позволяет значительно ускорить получение обратной связи, запуская зависимые задачи раньше.

### Практические сценарии

#### Сценарий 1: Условный запуск задач с `rules`

**Запуск только для Merge Request'ов:**
Используйте `$CI_PIPELINE_SOURCE == "merge_request_event"` для запуска задач только при создании merge request.
```yaml
test_job:
  stage: test
  script:
    - echo "Running tests for merge request"
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Запуск для MR в определенную ветку:**
```yaml
# Запуск только для MR в определенную ветку
test_mr_to_main:
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
```

**Запуск при изменении определенных файлов (для монорепозиториев):**
```yaml
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
```yaml
# Другой пример с changes
test_frontend:
  script:
    - npm run test
  rules:
    - changes:
        - "frontend/**/*"
        - "package.json"
```

**Комбинированное правило для деплоя:**
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
```yaml
# Комплексный пример для деплоя
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

**Задачи по расписанию (Cron-like):**
GitLab CI можно использовать для выполнения задач по расписанию. В `rules` можно использовать `$CI_PIPELINE_SOURCE == "schedule"` для запуска определенных заданий только при таком типе триггера.

#### Сценарий 2: Ускорение пайплайна с `needs`

Рассмотрим пайплайн, где `test:web` зависит только от `build:web` и не должен ждать долгих сборок `build:android` и `build:ios`.

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

#### Сценарий 3: Матричные сборки с `parallel:matrix`

Этот пример создаст 4 параллельных задания `test` для разных комбинаций провайдеров и стеков.
```yaml
test:
  stage: test
  script: "echo 'Testing with $PROVIDER on $STACK'"
  parallel:
    matrix:
      - PROVIDER: [aws, gcp]
        STACK: [nodejs, python]
```

### Дополнительная информация

#### Встроенные переменные CI/CD

Использование предопределенных переменных GitLab CI в условиях `if` внутри `rules` позволяет гибко реагировать на различные события и состояния репозитория.
*   `$CI_COMMIT_BRANCH` - название текущей ветки.
*   `$CI_PIPELINE_SOURCE` - источник запуска пайплайна (например, `push`, `merge_request_event`, `schedule`).
*   `$CI_COMMIT_TAG` - тег коммита.
*   `$CI_PROJECT_NAME`: Имя проекта.
*   `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` - целевая ветка Merge Request'а.

Документация: [Merge Request Pipelines](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/)

#### Only/Except (устаревший подход)

Устаревшие директивы, которые позволяют запускать или исключать задачи на основе имени ветки, тега или типа события. **Рекомендуется использовать `rules` вместо `only/except`**.

**Пример с `only/except`:**
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

**Пример ручного запуска с `only`:**
Задачи с `when: manual` требуют ручного запуска. Это часто используется для деплоя в production.
```yaml
deploy_production:
  script:
    - echo "Deploying to production"
  when: manual
  only:
    - main
```