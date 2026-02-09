# GitLab CI: Эволюция переиспользуемого пайплайна (практический пример)

### Практические сценарии

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
