# GitLab CI: Эволюция переиспользуемого пайплайна (практический пример)

## Практические сценарии

### Сценарий: Эволюция от дублирования к компонентам

Данный пример демонстрирует полный путь эволюции конфигурации GitLab CI — от простого дублирования кода до публикации версионируемых компонентов в каталоге.

---

## Этап 1: Проблема — Дублирование кода (Boilerplate)

### Ситуация

Команда разрабатывает несколько микросервисов. Для каждого сервиса требуется сборка Docker-образа. Разработчики копируют одинаковую конфигурацию в `.gitlab-ci.yml` каждого проекта.

### Пример boilerplate-кода

```yaml
# .gitlab-ci.yml в каждом из 10+ проектов
build-docker-image:
  stage: build
  image: docker:20.10
  services:
    - docker:20.10-dind
  variables:
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
```

### Проблемы

| Проблема | Описание |
| :--- | :--- |
| **Сложность поддержки** | При изменении версии Docker или логики сборки требуется править 10+ файлов |
| **Человеческий фактор** | При копировании легко допустить ошибку (опечатка, устаревшая версия) |
| **Загромождение** | `.gitlab-ci.yml` становится большим, трудным для чтения |
| **Отсутствие стандартизации** | Каждый проект может иметь свою версию конфигурации |

---

## Этап 2: Решение — Централизация с помощью `include`

### Решение

Вынести общий код в отдельный файл в центральном репозитории CI-шаблонов и подключать его через `include:project`.

### Создание репозитория шаблонов

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
build-docker-image:
  stage: docker-build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
```

### Использование в проекте

```yaml
# .gitlab-ci.yml проекта
stages:
  - docker-build

include:
  - project: 'group/ci-templates'
    ref: v1.0.0  # Версионирование через тег
    file: '/docker-build.yml'
```

### Результат

| Преимущество | Описание |
| :--- | :--- |
| **Централизация** | Изменения вносятся в одном месте |
| **Стандартизация** | Все проекты используют одинаковую конфигурацию |
| **Упрощение** | `.gitlab-ci.yml` проекта содержит только `include` |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Отсутствие гибкости** | Невозможно кастомизировать шаблон под конкретный проект |
| **Жёсткая конфигурация** | Все проекты вынуждены использовать одинаковые `image`, `variables` |

---

## Этап 3: Гибкость с помощью `extends`

### Решение

Превратить задачу в шаблоне в "скрытую" (начинающуюся с точки) и наследовать её в проекте через `extends`, добавляя специфичные настройки.

### Обновлённый шаблон

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
.docker-build-template:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build
        --build-arg CI_JOB_TOKEN=${CI_JOB_TOKEN}
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
        .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

### Использование в проекте с кастомизацией

```yaml
# .gitlab-ci.yml проекта
include:
  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker-build.yml'

stages:
  - build

build-my-app:
  extends: .docker-build-template
  variables:
    DOCKER_BUILDKIT: "1"  # Добавляем специфичную переменную
    IMAGE_NAME: "my-app"
  before_script:
    - echo "Custom step before building"  # Добавляем свой шаг
    - npm install  # Специфичная подготовка
```

### Результат

| Преимущество | Описание |
| :--- | :--- |
| **Централизация** | Общая логика в одном месте |
| **Гибкость** | Каждый проект может добавлять свои переменные, `before_script`, `after_script` |
| **DRY** | Нет дублирования основной логики |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Безопасность** | `docker:dind` требует привилегированного режима (`privileged`) |
| **Сложность обновления** | При изменении шаблона все проекты получают изменения немедленно |

---

## Этап 4: Абстрагирование деталей реализации (Безопасность)

### Ситуация

Платформенная команда решает, что `docker:dind` небезопасен (требует `privileged`) и нужно перейти на более безопасный сборщик — **Kaniko**.

### Решение

Так как все проекты используют централизованный шаблон, достаточно изменить только его.

### Обновление шаблона на Kaniko

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
.docker-build-template:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  variables:
    DOCKERFILE: Dockerfile
    CONTEXT: $CI_PROJECT_DIR
  script:
    - /kaniko/executor
      --context $[[ CONTEXT ]]
      --dockerfile $[[ DOCKERFILE ]]
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
      --cache=true
      --cache-repo=$CI_REGISTRY_IMAGE/cache
```

### Результат для проектов

**Проекты не требуют изменений!** Их `.gitlab-ci.yml` остаются прежними:

```yaml
# .gitlab-ci.yml проекта (без изменений)
include:
  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker-build.yml'

build-my-app:
  extends: .docker-build-template
  variables:
    DOCKERFILE: "app/Dockerfile"  # Можно переопределить
```

### Преимущества

| Преимущество | Описание |
| :--- | :--- |
| **Прозрачное обновление** | Проекты не требуют изменений |
| **Безопасность** | Kaniko не требует привилегированного режима |
| **Кэширование** | Встроенное кэширование слоёв через Kaniko |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Отсутствие типизации** | Нет явного интерфейса для входных параметров |
| **Слабая валидация** | Невозможно валидировать переменные до выполнения |
| **Документирование** | Требуется ручная документация параметров |

---

## Этап 5: Зрелость — CI/CD Catalog Components

### Решение

Переход на CI/CD Components с явным интерфейсом (`spec:inputs`), версионированием через Semver и публикацией в каталоге.

### Создание компонента

**Репозиторий:** `group/ci-components/docker-build`

**Структура:**
```
docker-build/
├── .gitlab-ci.yml          # spec:inputs + метаданные
└── templates/
    └── build.yml           # Основная логика
```

**Файл:** `.gitlab-ci.yml` (метаданные компонента)

```yaml
# .gitlab-ci.yml компонента
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage name"
    
    dockerfile:
      default: Dockerfile
      type: string
      description: "Path to Dockerfile"
    
    context:
      default: $CI_PROJECT_DIR
      type: string
      description: "Build context path"
    
    enable_cache:
      default: true
      type: boolean
      description: "Enable Kaniko caching"
    
    cache_repo:
      default: $CI_REGISTRY_IMAGE/cache
      type: string
      description: "Cache repository"

---
# Основная логика компонента (templates/build.yml)
docker-build-job:
  stage: $[[ inputs.stage ]]
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context $[[ inputs.context ]]
      --dockerfile $[[ inputs.dockerfile ]]
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
      --cache=$[[ inputs.enable_cache ]]
      --cache-repo=$[[ inputs.cache_repo ]]
```

### Публикация в каталог

**Создание релиза:**
```bash
# Создание тега с SemVer
git tag -a v1.0.0 -m "Initial release of docker-build component"
git push origin v1.0.0

# Или через GitLab UI: Releases → New release
```

**CI для автоматического релиза:**
```yaml
# .gitlab-ci.yml компонента (добавление release job)
release:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: $CI_COMMIT_TAG
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "docker-build component $CI_COMMIT_TAG"
```

### Использование компонента в проекте

```yaml
# .gitlab-ci.yml проекта
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.0.0'
    inputs:
      stage: build
      dockerfile: app/Dockerfile
      context: $CI_PROJECT_DIR
      enable_cache: true
      cache_repo: $CI_REGISTRY_IMAGE/cache
```

### Преимущества Components

| Преимущество | Описание |
| :--- | :--- |
| **Типизация** | Явные типы параметров (string, boolean, number) |
| **Валидация** | Автоматическая валидация inputs через CI Lint |
| **Документация** | Автоматическая генерация из `description` |
| **Версионирование** | Semver с поддержкой частичных версий (`@1.0`, `@1`) |
| **Каталог** | Видимость в UI GitLab, поиск компонентов |
| **Изоляция** | Полная самодостаточность компонента |

---

## Сводная таблица эволюции

| Этап | Подход | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **1** | Дублирование | Простота начала | Нет поддержки, стандартизации |
| **2** | `include:project` | Централизация | Нет гибкости |
| **3** | `include` + `extends` | Централизация + гибкость | Нет типизации, безопасности |
| **4** | Абстракция (Kaniko) | Безопасность, прозрачность | Нет явного интерфейса |
| **5** | CI/CD Components | Типизация, валидация, каталог | Высокая сложность настройки |

## Рекомендации по выбору этапа

| Размер команды | Количество проектов | Рекомендуемый этап |
| :--- | :--- | :--- |
| 1–3 разработчика | 1–3 проекта | Этап 2–3 (`include` + `extends`) |
| 5–10 разработчиков | 5–10 проектов | Этап 3–4 (абстракция) |
| 10+ разработчиков | 10+ проектов | Этап 5 (Components) |
| Публичные компоненты | Любое | Этап 5 (Components с каталогом) |

## Дополнительная информация

### Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение всех подходов
- **[Механизм `extends`](./extends_keyword.md)** — наследование конфигураций
- **[Механизм `include`](./include_keyword.md)** — все типы include
- **[CI/CD Catalog](./ci_cd_catalog_components.md)** — создание компонентов

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [GitLab CI Best Practices](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5)
