### Создание переиспользуемых и композитных пайплайнов

См. также:
*   [Семантическое Версионирование и Управление Релизом в GitLab CI](../release_management_and_semver.md)
*   [Валидация и Версионирование CI/CD Пайплайнов в GitLab](./pipeline_validation_and_versioning.md)

GitLab CI предоставляет мощные механизмы для избежания дублирования кода и создания гибких, модульных пайплайнов.

#### 1. `extends` — Наследование конфигураций

Механизм `extends` позволяет заданию унаследовать всю конфигурацию от другого, "скрытого" задания (начинающегося с точки). Это базовый способ переиспользования.

```yaml
.base_job:
  image: ruby:2.7
  script:
    - echo "This is from the base job."

test_job:
  extends: .base_job
  script:
    - echo "This is from the test job. It will run after the base script."
    # Важно: скрипт из .base_job будет объединён со скриптом test_job.
```

#### 2. YAML Anchors (`&`) и Aliases (`*`)

Помимо `!reference`, для переиспользования можно использовать стандартный механизм YAML — якоря (anchors) и псевдонимы (aliases). Это не является специфической функцией GitLab CI, но поддерживается его парсером.

-   **`&anchor_name`**: Задает якорь (имя) для любого элемента YAML.
-   **`*anchor_name`**: Вставляет содержимое, на которое указывает якорь.

```yaml
.after_script_template: &after_script_definition
  - echo "Cleaning up..."

job1:
  script:
    - echo "Running job 1"
  after_script:
    - *after_script_definition

job2:
  script:
    - echo "Running job 2"
  after_script:
    - *after_script_definition
```

#### 3. `include` — Композиция из внешних файлов

`include` — один из самых мощных механизмов, позволяющий собрать пайплайн из нескольких YAML-файлов. Это делает конфигурацию модульной и легко управляемой.

Поддерживаемые источники:

-   **`include:local`**: Файл из того же репозитория.
    ```yaml
    include: '/templates/.build-template.yml'
    ```
-   **`include:project`**: Файл из другого проекта в том же инстансе GitLab.
    ```yaml
    include:
    ref: main # Рекомендуется использовать тег (например, `ref: v1.0.0`) для версионирования шаблонов
        file: '/maven-build.yml'
    ```
-   **`include:remote`**: Файл по URL.
    ```yaml
    include:
      - remote: 'https://example.com/ci-config.yml'
    ```
-   **`include:template`**: Встроенные шаблоны GitLab (например, для `Node.js`, `Docker`, `SAST`).
    ```yaml
    include:
      - template: Security/SAST.gitlab-ci.yml
    ```

#### 4. CI/CD Catalog (Components)

Новый подход к переиспользованию, позволяющий создавать версионируемые **компоненты** — полноценные, изолированные блоки CI/CD логики, которые можно публиковать в общем каталоге и использовать в проектах.

```yaml
include:
  - component: '$CI_SERVER_HOST/my-org/my-component@1.0'
    inputs:
      stage: build
```

---

### Практический сценарий: Как избежать дублирования конфигурации?

**Вопрос:** У вас есть 5 проектов на одном языке программирования. Как организовать пайплайны, чтобы избежать дублирования конфигурации?

**Ответ:**

Для избежания дублирования конфигурации используйте следующие подходы:
    1.  **Создание общих шаблонов:** Вынесите повторяющиеся задачи (build, test, lint) в отдельный YAML-файл в централизованном репозитории.
    2.  **Использование `include`:** Подключайте эти общие шаблоны в `.gitlab-ci.yml` каждого проекта.
    3.  **Применение `extends`:** Наследуйте и кастомизируйте базовые задачи из шаблона в своих проектах, добавляя специфичные для проекта детали.

**Пример структуры:**

**1. Центральный файл шаблонов (`common-templates.yml`):**
```yaml
# common-templates.yml
.build_template:
  stage: build
  script:
    - npm install
    - npm run build
  artifacts:
    paths:
      - dist/

.test_template:
  stage: test
  script:
    - npm run test
  coverage: '/Coverage: \d+\.\d+%/'
```

**2. Файл `.gitlab-ci.yml` в каждом проекте:**
```yaml
# В каждом проекте .gitlab-ci.yml
include:
  - project: 'templates/ci-templates'
    ref: main # Рекомендуется использовать тег для версионирования
    file: 'common-templates.yml'

build_job:
  extends: .build_template

test_job:
  extends: .test_template
```

Этот подход является основой для создания масштабируемых и легко поддерживаемых CI/CD пайплайнов в GitLab.

### Эволюция переиспользуемого пайплайна: практический пример

Рассмотрим типичный путь, который проходят команды при создании и поддержке пайплайнов, и как механизмы `include` и `extends` решают возникающие проблемы.

#### Этап 1: Проблема — Дублирование кода (Boilerplate)

**Ситуация:** Команда пишет много микросервисов, и для каждого нужно собирать Docker-образ. Разработчики копируют один и тот же большой кусок YAML-кода в `.gitlab-ci.yml` каждого нового проекта.

**Пример boilerplate-кода:**
```yaml
build-docker-image:
  stage: build
  image: docker:20.10
  services:
    - docker:20.10-dind
  variables:
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
```

**Проблемы:**
1.  **Сложность поддержки:** Если нужно обновить версию Docker или изменить логику сборки (например, добавить сканирование), придется вручную править файлы во всех репозиториях.
2.  **Человеческий фактор:** При копировании легко допустить ошибку.
3.  **Загромождение:** `.gitlab-ci.yml` становится большим и трудночитаемым.

#### Этап 2: Решение — Централизация с помощью `include`

**Решение:** Вынести общий код в отдельный файл в центральном репозитории CI-шаблонов и подключать его с помощью `include`.

**Создаем репозиторий `ci-templates` с файлом `docker-build.yml`:**
```yaml
# ci-templates/docker-build.yml
build-docker-image:
  stage: docker-build
  image: docker:20.10
  services:
    - docker:20.10-dind
  variables:
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
```

**В `.gitlab-ci.yml` проекта теперь используется `include`:**
```yaml
stages:
  - docker-build # Необходимо объявить стадию из шаблона

include:
  - project: 'my-group/ci-templates'
    ref: main
    file: '/docker-build.yml'
```

**Результат:** Код централизован. Изменения вносятся в одном месте.

#### Этап 3: Проблема — Отсутствие гибкости

**Ситуация:** Шаблон `include` предоставляет готовую задачу, но не позволяет разработчикам кастомизировать ее под свои нужды (например, добавить `before_script` или передать специфичные для сборки `variables`), не отказываясь от шаблона целиком.

#### Этап 4: Решение — Гибкость с помощью `extends`

**Решение:** Превратить задачу в шаблоне в "скрытую" (начинающуюся с точки) и наследовать ее в пайплайне проекта с помощью `extends`.

**Обновляем `ci-templates/docker-build.yml`:**
```yaml
# ci-templates/docker-build.yml
# Имя задачи теперь начинается с точки, она не будет запускаться сама по себе
.docker-build-template:
  stage: build
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build 
        --build-arg CI_JOB_TOKEN=${CI_JOB_TOKEN} 
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA 
        .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

**В `.gitlab-ci.yml` проекта теперь используется `extends`:**
```yaml
include:
  - project: 'my-group/ci-templates'
    ref: main
    file: '/docker-build.yml'

stages:
  - build

build-my-app:
  stage: build
  extends: .docker-build-template
  variables:
    # Теперь можно добавлять свои переменные
    EXTRA_BUILD_ARG: "my-value"
  before_script:
    # И добавлять свои шаги
    - echo "Custom step before building"
```

**Результат:** Сохранены и централизация, и гибкость для кастомизации.

#### Этап 5: Абстрагирование деталей реализации (Безопасность)

**Ситуация:** Платформенная команда решает, что `docker:dind` небезопасен (требует привилегированного режима) и нужно перейти на более безопасный сборщик, например, **Kaniko**.

**Решение:** Так как все проекты используют централизованный шаблон, достаточно изменить только его.

**Обновляем `ci-templates/docker-build.yml`, заменяя Docker на Kaniko:**
```yaml
# ci-templates/docker-build.yml
.docker-build-template:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

**Результат:** Для конечных пользователей (разработчиков) ничего не поменялось. Их `.gitlab-ci.yml` файлы остались прежними, но сборка теперь происходит с помощью другого, более безопасного инструмента. Это демонстрирует силу абстракции через шаблоны.

#### Мораль

Команды DevOps или платформенные инженеры должны создавать и поддерживать такие шаблоны, чтобы упростить жизнь разработчикам, позволив им сосредоточиться на коде, а не на тонкостях CI/CD. Правильно спроектированные шаблоны делают "правильный" способ сборки и развертывания самым простым.
