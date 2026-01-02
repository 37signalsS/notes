### Создание переиспользуемых и композитных пайплайнов

#### 1. `extends` — Наследование конфигураций

Механизм `extends` позволяет заданию унаследовать всю конфигурацию от одного или нескольких "скрытых" заданий (начинающихся с точки `.` ). Это базовый способ переиспользования конфигураций.

**Логика слияния `extends`:**

Когда задание использует `extends`, GitLab CI выполняет слияние (merge) конфигураций. Важно понимать, как это происходит:

*   **Скрипты (`script`, `before_script`, `after_script`):** Скрипты из родительского задания **конкатенируются** со скриптами дочернего задания. Если дочернее задание имеет `script` или `before_script`/`after_script`, они будут выполнены **после** соответствующих скриптов из `extends`-задания.
*   **Другие ключи (например, `variables`, `rules`, `cache`):** Для большинства других ключей происходит **глубокое слияние (deep merge)**. Это означает, что если ключ присутствует как в родительском, так и в дочернем задании, значения из дочернего задания **переопределяют** или **дополняют** значения из родительского.
    *   Если дочернее задание определяет ключ, отсутствующий в родительском, он добавляется.
    *   Если ключ является словарем (map), его поля сливаются.
    *   Если ключ является списком (list), он обычно **заменяется** списком из дочернего задания.

**Пример:**

```yaml
.base_job:
  image: ruby:2.7
  script:
    - echo "This is from the base job."
  variables:
    BASE_VAR: "base_value"
    OVERRIDE_ME: "base_override"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

test_job:
  extends: .base_job
  script:
    - echo "This is from the test job. It will run after the base script."
  variables:
    TEST_VAR: "test_value"
    OVERRIDE_ME: "test_override" # Переопределит BASE_VAR
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"' # Заменит правило из .base_job
```

В результате `test_job` будет иметь:

*   `image: ruby:2.7`
*   `script`: объединение скриптов из `.base_job` и `test_job`.
*   `variables`: `BASE_VAR: "base_value"`, `OVERRIDE_ME: "test_override"`, `TEST_VAR: "test_value"`.
*   `rules`: только правило из `test_job` (`if: '$CI_PIPELINE_SOURCE == "merge_request_event"'`).

Список ключей `extends` может быть использован для наследования от нескольких скрытых заданий. В этом случае слияние происходит последовательно, справа налево (т.е. последнее задание в списке `extends` будет иметь приоритет).

```yaml
.base_defaults:
  image: alpine:latest

.test_rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

my_test_job:
  extends:
    - .base_defaults
    - .test_rules
  script:
    - echo "Running tests"
```

В этом примере `my_test_job` сначала наследует от `.base_defaults`, затем сливается с `.test_rules`.

#### 2. `!reference`, YAML Anchors (`&`) и Aliases (`*`)

GitLab CI предоставляет несколько механизмов для повторного использования фрагментов конфигурации внутри одного файла `.gitlab-ci.yml`.

##### `!reference` — Ссылки на существующие элементы

`!reference` — это специальный тег GitLab CI, который позволяет ссылаться на другие элементы в файле `.gitlab-ci.yml` и вставлять их содержимое. Это мощный инструмент для сокращения дублирования и создания более читаемых конфигураций, особенно для сложных структур.

**Преимущества `!reference`:**

*   **Четкость:** Явно указывает на ссылку, улучшая читаемость.
*   **Гибкость:** Можно ссылаться на любые элементы (скрипты, правила, переменные и т.д.).
*   **Валидация:** Линтер GitLab CI способен валидировать ссылки, чего не скажешь о более низкоуровневых YAML-якорях, которые парсер GitLab не всегда полностью интерпретирует.

**Пример использования `!reference`:**

```yaml
.script_template:
  - echo "Running common script part 1"
  - echo "Running common script part 2"

.default_tags: &default_runner_tags
  tags:
    - linux
    - shell

build_job:
  stage: build
  script:
    - !reference [.script_template] # Вставка содержимого .script_template
    - echo "Running build specific script"
  <<: *default_runner_tags # Использование YAML-якоря

test_job:
  stage: test
  script:
    - !reference [.script_template]
    - echo "Running test specific script"
  tags:
    - !reference [.default_tags, tags, 0] # Ссылка на конкретный элемент списка из якоря
```

##### YAML Anchors (`&`) и Aliases (`*`)

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
Важно отметить, что `!reference` обычно более предпочтителен в GitLab CI, так как предоставляет лучшую читаемость и поддержку со стороны GitLab CLI Lint.

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

**CI/CD Catalog (Каталог CI/CD)** — это наиболее современный и рекомендуемый подход GitLab к переиспользованию логики пайплайнов. Он позволяет создавать версионируемые **компоненты** — полноценные, изолированные блоки CI/CD логики, которые можно публиковать в общем каталоге и использовать в проектах.

**Основные преимущества компонентов над традиционными `include` шаблонами:**

1.  **Явное версионирование:** Каждый компонент имеет свою версию (например, `@1.0`, `@~1.0`, `@stable`). Это обеспечивает стабильность и предсказуемость, так как обновления не ломают зависимые проекты, пока версия не будет явно изменена.
2.  **Строго типизированные интерфейсы (`spec:inputs`):** Компоненты могут определять входные параметры с указанием типа (строка, число, булево, список), значения по умолчанию и даже регулярных выражений для валидации. Это создает четкий API для компонента, упрощает его использование и предотвращает ошибки.
3.  **Повышенная изоляция:** Компоненты спроектированы как самостоятельные блоки, что способствует лучшей модульности.
4.  **Улучшенное обнаружение и управление:** Компоненты публикуются в централизованном каталоге GitLab, что упрощает их поиск, понимание и использование другими командами.
5.  **Автоматическая документация:** Каталог может автоматически генерировать документацию на основе описаний компонентов.

**Структура компонента:**

Компонент обычно состоит из файла `template.yml` (который содержит основную логику CI/CD) и файла `gitlab-ci.yml` (который определяет метаданные и `spec:inputs`).

**Пример использования компонента:**

```yaml
# .gitlab-ci.yml в проекте, использующем компонент
include:
  - component: '$CI_SERVER_HOST/my-group/my-component/my-build-component@1.0.0'
    inputs:
      stage: build
      target_branch: main
      enable_cache: true
      dockerfile_path: "app/Dockerfile"
```

**Пример определения компонента (`gitlab-ci.yml` в репозитории компонента):**

```yaml
# gitlab-ci.yml (в репозитории компонента 'my-build-component')
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage for the build job."
    target_branch:
      type: string
      default: main
      description: "The branch to trigger the build on."
      regex: '^(main|develop|feature/.*)$' # Валидация через regex
    enable_cache:
      type: boolean
      default: true
      description: "Enable Docker layer caching."

---

# template.yml (основная логика компонента)
# Использует переменные, переданные через `inputs`
build-component-job:
  stage: $[[ inputs.stage ]]
  rules:
    - if: '$CI_COMMIT_BRANCH == $[[ inputs.target_branch ]]'
  script:
    - echo "Building image for stage: $[[ inputs.stage ]]"
    - if [[ "$[[ inputs.enable_cache ]]" == "true" ]]; then echo "Cache enabled."; fi
    - docker build -f $[[ inputs.dockerfile_path ]] .
  # ... остальная логика сборки ...
```

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

### Эволюция переиспользуемого пайплайна: практический пример

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

**Результат:** Для конечных пользователей (разработчиков) ничего не поменялось. Их `.gitlab-ci.yml` файлы остались прежними, но сборка теперь происходит с помощью другого, более безопасного инструмента.
