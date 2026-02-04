### Определения

**Переиспользуемые и композитные пайплайны** в GitLab CI — это подход к организации конфигурации CI/CD, который позволяет создавать модульные, легко управляемые и обновляемые пайплайны. Это достигается за счет повторного использования общих фрагментов кода и логики, избегая дублирования и упрощая поддержку.

- **`extends`**: Механизм, позволяющий заданию наследовать всю конфигурацию от одного или нескольких "скрытых" заданий (начинающихся с точки `.`). Это базовый способ переиспользования конфигураций внутри одного файла `.gitlab-ci.yml`.
- **`!reference`, YAML Anchors (`&`) и Aliases (`*`)**: Механизмы для повторного использования фрагментов конфигурации. `!reference` — это специальный тег GitLab CI, а YAML Anchors и Aliases — стандартный механизм YAML.
- **`include`**: Мощный механизм, позволяющий собрать пайплайн из нескольких YAML-файлов, расположенных локально, в других проектах, по удаленным URL или использовать встроенные шаблоны GitLab.
- **CI/CD Catalog (Components)**: Наиболее современный и рекомендуемый подход GitLab к переиспользованию, позволяющий создавать версионируемые, строго типизированные и публикуемые в общем каталоге компоненты — полноценные, изолированные блоки CI/CD логики.

### Основные концепции

#### `extends` — Логика слияния конфигураций

Когда задание использует `extends`, GitLab CI выполняет слияние (merge) конфигураций от родительского ("скрытого") задания к дочернему. Важно понимать, как это происходит:

- **Скрипты (`script`, `before_script`, `after_script`):** Скрипты из родительского задания **конкатенируются** со скриптами дочернего задания. Если дочернее задание имеет `script` или `before_script`/`after_script`, они будут выполнены **после** соответствующих скриптов из `extends`-задания.
- **Другие ключи (например, `variables`, `rules`, `cache`):** Для большинства других ключей происходит **глубокое слияние (deep merge)**. Это означает, что если ключ присутствует как в родительском, так и в дочернем задании, значения из дочернего задания **переопределяют** или **дополняют** значения из родительского.
  - Если дочернее задание определяет ключ, отсутствующий в родительском, он добавляется.
  - Если ключ является словарем (map), его поля сливаются.
  - Если ключ является списком (list), он обычно **заменяется** списком из дочернего задания, если дочерний список не пуст.

Список ключей `extends` может быть использован для наследования от нескольких скрытых заданий. В этом случае слияние происходит последовательно, справа налево (т.е. последнее задание в списке `extends` будет иметь приоритет).

#### `!reference` vs. YAML Anchors (`&`) и Aliases (`*`)

Оба механизма используются для переиспользования фрагментов конфигурации внутри одного файла `.gitlab-ci.yml`.

- **`!reference`**: Специальный тег GitLab CI, который явно ссылается на другие элементы и вставляет их содержимое.
  - **Преимущества `!reference`:**
    - **Четкость:** Явно указывает на ссылку, улучшая читаемость.
    - **Гибкость:** Можно ссылаться на любые элементы (скрипты, правила, переменные и т.д.), в том числе на конкретные элементы списков или словарей.
    - **Валидация:** Линтер GitLab CI способен валидировать ссылки, что упрощает отладку.
- **YAML Anchors (`&`) и Aliases (`*`)**: Стандартный механизм YAML. `&anchor_name` задает якорь, `*anchor_name` вставляет содержимое.
  - Эти механизмы менее специфичны для GitLab CI и парсер GitLab не всегда полностью интерпретирует их, что может быть менее предсказуемо, чем `!reference`.

**Предпочтение:** `!reference` обычно более предпочтителен в GitLab CI, так как предоставляет лучшую читаемость и поддержку со стороны GitLab CLI Lint.

#### `include` — Композиция из внешних файлов

`include` — один из самых мощных механизмов, позволяющий собрать пайплайн из нескольких YAML-файлов, делая конфигурацию модульной и легко управляемой.

Поддерживаемые источники:

- **`include:local`**: Файл из того же репозитория.
- **`include:project`**: Файл из другого проекта в том же инстансе GitLab. Рекомендуется использовать тег (`ref: v1.0.0`) для версионирования шаблонов.
- **`include:remote`**: Файл по URL.
- **`include:template`**: Встроенные шаблоны GitLab (например, для `Node.js`, `Docker`, `SAST`).

#### CI/CD Catalog (Components) — Современный подход к переиспользованию

CI/CD Catalog — наиболее современный и рекомендуемый подход GitLab. Он позволяет создавать версионируемые **компоненты** — полноценные, изолированные блоки CI/CD логики, которые можно публиковать в общем каталоге и использовать в проектах.

**Основные преимущества компонентов над традиционными `include` шаблонами:**

1. **Явное версионирование:** Каждый компонент имеет свою версию (например, `@1.0`, `@~1.0`, `@stable`), обеспечивая стабильность и предсказуемость.
2. **Строго типизированные интерфейсы (`spec:inputs`):** Компоненты могут определять входные параметры с указанием типа, значений по умолчанию и регулярных выражений для валидации, создавая четкий API.
3. **Повышенная изоляция:** Компоненты спроектированы как самостоятельные блоки, что способствует лучшей модульности.
4. **Улучшенное обнаружение и управление:** Компоненты публикуются в централизованном каталоге GitLab, что упрощает их поиск и использование.
5. **Автоматическая документация:** Каталог может автоматически генерировать документацию.

**Структура компонента:**
Компонент обычно состоит из файла `template.yml` (основная логика CI/CD) и файла `gitlab-ci.yml` (метаданные и `spec:inputs`).

### Практические сценарии

#### Сценарий 1: Использование `extends` для наследования конфигураций

**Пример наследования от одного скрытого задания:**

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
- `image: ruby:2.7`
- `script`: объединение скриптов из `.base_job` и `test_job`.
- `variables`: `BASE_VAR: "base_value"`, `OVERRIDE_ME: "test_override"`, `TEST_VAR: "test_value"`.
- `rules`: только правило из `test_job` (`if: '$CI_PIPELINE_SOURCE == "merge_request_event"'`).

**Пример наследования от нескольких скрытых заданий:**

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

#### Сценарий 2: Использование `!reference` и YAML Anchors

**Пример использования `!reference` и YAML Anchors:**

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

**Пример с YAML Anchors (`&`) и Aliases (`*`):**

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

#### Сценарий 3: Использование CI/CD Catalog (Components)

**Пример использования компонента (в файле `.gitlab-ci.yml` проекта):**

```yaml
include:
  - component: '$CI_SERVER_HOST/my-group/my-component/my-build-component@1.0.0'
    inputs:
      stage: build
      target_branch: main
      enable_cache: true
      dockerfile_path: "app/Dockerfile"
```

**Пример определения компонента (`gitlab-ci.yml` и `template.yml` в репозитории компонента):**

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

#### Сценарий 4: Как избежать дублирования конфигурации?

**Вопрос:** У вас есть 5 проектов на одном языке программирования. Как организовать пайплайны, чтобы избежать дублирования конфигурации?

**Ответ:**

1. **Создание общих шаблонов:** Вынесите повторяющиеся задачи (build, test, lint) в отдельный YAML-файл в централизованном репозитории.
2. **Использование `include`:** Подключайте эти общие шаблоны в `.gitlab-ci.yml` каждого проекта.
3. **Применение `extends`:** Наследуйте и кастомизируйте базовые задачи из шаблона в своих проектах, добавляя специфичные для проекта детали.

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

#### Сценарий 5: Эволюция переиспользуемого пайплайна: практический пример

**Этап 1: Проблема — Дублирование кода (Boilerplate)**

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

1. **Сложность поддержки:** Если нужно обновить версию Docker или изменить логику сборки (например, добавить сканирование), придется вручную править файлы во всех репозиториях.
2. **Человеческий фактор:** При копировании легко допустить ошибку.
3. **Загромождение:** `.gitlab-ci.yml` становится большим и трудночитаемым.

**Этап 2: Решение — Централизация с помощью `include`**

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

**Этап 3: Проблема — Отсутствие гибкости**

**Ситуация:** Шаблон `include` предоставляет готовую задачу, но не позволяет разработчикам кастомизировать ее под свои нужды (например, добавить `before_script` или передать специфичные для сборки `variables`), не отказываясь от шаблона целиком.

**Этап 4: Решение — Гибкость с помощью `extends`**

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

**Этап 5: Абстрагирование деталей реализации (Безопасность)**

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
