# GitLab CI: Механизм `include`

## Определения

**`include`** — ключевой механизм GitLab CI/CD для композиции конфигурационных файлов. Позволяет подключать внешние YAML-ресурсы (локальные файлы, проекты, удалённые URL, встроенные шаблоны GitLab и компоненты каталога), разделяя монолитные описания пайплайнов на логические, повторно используемые модули. Обработка `include` происходит **первым этапом** компиляции пайплайна — до `extends`, `inputs` и валидации.

**Раскрытие (Expansion)** — процесс, при котором GitLab загружает все включённые файлы, рекурсивно обрабатывает их собственные `include` и объединяет в единую структуру (expanded YAML) до начала валидации и выполнения заданий. Итоговый раскрытый YAML является唯一 источником правды для пайплайна и доступен во вкладке «View merged YAML» Pipeline Editor или через `glab ci lint --show-expanded`.

**Configuration Drift (Расхождение конфигураций)** — проблема, при которой пайплайны разных проектов начинают сильно отличаться друг от друга из-за ручного копирования и локальных правок. Массовое обновление стандартов безопасности становится невозможным без централизации. Механизм `include` решает эту проблему, вводя модель «подключай и используй».

> [!WARNING]
> **Лимиты и лучшие практики:**
> - Максимальное количество файлов `include` (включая рекурсию): **150**.
> - Таймаут загрузки каждого внешнего запроса: **30 секунд**.
> - Размер итогового смерженного YAML: **5 МБ**.
> - Рекомендуемая глубина вложенности: **3–5 уровней** для удобства отладки.
> - Категорически не рекомендуется использовать `ref: main` / `ref: master` — изменения могут мгновенно сломать сотни пайплайнов.
> - YAML Anchors (`&`/`*`) **не работают между файлами**. При выносе кода в шаблоны всегда заменяйте их на `!reference`.
> - Переменные в `include:rules` вычисляются в момент **создания** пайплайна. Переменные из `dotenv` артефактов **недоступны**.

### Архитектура централизации

```
┌───────────────────────────────────────────────────────────┐
│  Центральная библиотека: shared/ci-templates              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────┐  │
│  │ docker-build   │  │ security-scan  │  │ deploy.yml │  │
│  │ .yml           │  │ .yml           │  │            │  │
│  └────────────────┘  └────────────────┘  └────────────┘  │
│       SSoT для логики     SSoT для        SSoT для       │
│       сборки образов      сканирования    деплоя         │
└───────────────────────────────────────────────────────────┘
         │                   │                │
         │ include:project   │ include:       │ include:
         │ (ref: v1.5.2)     │ template       │ component
         ▼                   ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Сервис А    │  │  Сервис Б    │  │  Сервис N    │
│  .gitlab-ci  │  │  .gitlab-ci  │  │  .gitlab-ci  │
│  5 строк     │  │  8 строк     │  │  6 строк     │
└──────────────┘  └──────────────┘  └──────────────┘
```

## Основные концепции

### Эволюционное преимущество перед Boilerplate

На предыдущем этапе каждый проект содержал полную копию CI/CD-конфигурации. При изменении стандарта (например, добавлении сканера безопасности) требовалось вручную править сотни репозиториев — процесс, занимающий недели и подверженный ошибкам. `include` решает эту проблему, вводя модель «подключай и используй».

| Характеристика | Этап 1 (Boilerplate) | Этап 2 (Include) |
| :--- | :--- | :--- |
| **Хранение логики** | В каждом проекте (дублирование) | В центральном репозитории |
| **Обновление стандарта** | Ручные правки в сотнях репозиториев | Одна правка в центральном шаблоне |
| **Версионирование** | Неуправляемое | Git-теги, SemVer, фиксация через `ref` |
| **Время внедрения патча** | Дни–недели (массовый пр) | Мгновенно (для проектов без фиксации на SHA) |
| **Configuration Drift** | Неизбежен со временем | Минимален (централизованное управление) |
| **Кастомизация** | Полная (каждый проект уникален) | Ограничена (шаблон «монолитный» без `extends`) |
| **Стоимость ошибки** | Локальная (только один проект) | Глобальная (ошибка в шаблоне ломает все проекты) |

**Ключевой переход:** от «каждый проект содержит свой CI» к «проекты подключают общий CI». Ценою этого перехода становится жёсткость шаблонов — решается на следующем этапе ([extends](./extends_keyword.md)).

### Пять типов `include`: детальный разбор

| Тип | Описание | Область применения | Версия GitLab |
| :--- | :--- | :--- | :--- |
| **`include:local`** | Файл в том же репозитории и ветке | Модульность внутри проекта (разделение `.gitlab-ci.yml`) | Любая |
| **`include:project`** | Файл из другого проекта на том же инстансе | Корпоративные библиотеки шаблонов | Любая |
| **`include:remote`** | Файл по HTTP/HTTPS URL | Сторонние шаблоны, публичные библиотеки | Любая |
| **`include:template`** | Встроенные шаблоны GitLab | SAST, DAST, Auto DevOps, Secret Detection | Любая |
| **`include:component`** | CI/CD компонент из каталога | Типизированные модули с `spec:inputs` | 16.2+ |

#### `include:local`

Подключает файл из того же репозитория. Используется та же ветка, в которой запущен пайплайн.

```yaml
include:
  - local: '.gitlab-ci/build.yml'
  - local: '.gitlab-ci/test.yml'
```

**Ограничения:**
- Путь должен быть относительным или начинаться с `/` (от корня репозитория).
- Git submodules **не видны** парсеру YAML — их нельзя использовать как источник `include`.
- Допустимые расширения: `.yml`, `.yaml`.

#### `include:project`

Фундамент корпоративной библиотеки шаблонов. Файл загружается из другого проекта на том же инстансе GitLab.

```yaml
include:
  - project: 'infrastructure/ci-templates'
    ref: v2.4.0
    file: '/docker/build-kaniko.yml'
```

**Версионирование (`ref`):**
- **Git-тег (SemVer):** Рекомендуется (`ref: v1.2.0`). Гарантирует стабильность и плановое обновление.
- **Commit SHA:** Максимальная безопасность (защита от перезаписи тега). Минус — нет автоматических обновлений.
- **Ветка:** Категорически не рекомендуется для production. Изменения мгновенно ломают все проекты-потребители.

#### `include:remote`

Подключает файлы по публичному URL. Используется для сторонних шаблонов и публичных библиотек.

```yaml
include:
  - remote: 'https://example.com/global-defaults.yml'
    integrity: 'sha256-L3/GAoKaw0Arw6hDCKeKQlV1QPEgHYxGBHsH4zG1IY8='
```

**Параметр `integrity` (v17.9+):** SHA256-хеш (Base64) для защиты от атак типа Supply Chain. Гарантирует, что файл не был подменён на стороне поставщика.

**Параметр `cache` (v18.9+, эксперимент):** Кэширование удалённого файла на стороне GitLab для ускорения старта пайплайна.

#### `include:template`

Использует встроенную библиотеку GitLab (SAST, DAST, Secret Detection, Dependency Scanning и др.).

```yaml
include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
```

> **Рекомендация (2026):** Постепенно переходите с `include:template` на `include:component` для лучшего контроля версий и типизации входных параметров.

#### `include:component`

Наиболее современный и безопасный способ. Подключает типизированные модули из CI/CD Catalog с явно определённым интерфейсом (`spec:inputs`).

```yaml
include:
  - component: $CI_SERVER_FQDN/gitlab-components/sast/sast@2.1.0
    inputs:
      stage: test
```

Подробнее в [CI/CD Catalog](./ci_cd_catalog_components.md).

### Архитектура слияния (Merge Behavior)

Когда GitLab встречает `include`, он выполняет глубокое слияние (deep merge) структур. Приоритет слияния:

1. **Задания в `.gitlab-ci.yml`** — наивысший приоритет.
2. **Задания из `include`** — приоритет зависит от порядка: нижний в списке переопределяет верхний.

**Типы слияния для ключей:**

| Тип данных | Поведение | Примеры ключей |
| :--- | :--- | :--- |
| **Словари (Hashes)** | Глубокое слияние по ключам. Локальные ключи переопределяют или дополняют родительские. | `variables`, `cache:paths` |
| **Массивы (Arrays)** | **Полная замена.** Если в импортированном файле 10 строк `script`, а в локальном 1 — итог будет содержать 1 строку. | `script`, `rules`, `tags`, `services` |

> **Критическое замечание:** Для дополнения массивов (а не их полной замены) используйте механизм [`!reference`](./reference_and_yaml_anchors.md) или комбинируйте `include` с `extends`.

### Приоритет переменных при `include`

Переменные, определённые в подключённых файлах, сливаются с локальными по стандартному приоритету GitLab CI:

1. Переменные в `variables` текущего задания (наивысший приоритет).
2. Переменные в `variables` `.gitlab-ci.yml` проекта.
3. Переменные из `include` файлов.
4. Переменные CI/CD Settings проекта (UI).
5. Переменные группы/инстанса.

> Важно: `CI_JOB_TOKEN`, `CI_COMMIT_SHA`, `CI_PIPELINE_SOURCE` и другие предопределённые переменные **нельзя переопределить** через `variables`.

### Условное включение через `include:rules`

Позволяет подключать файлы только при выполнении определённых условий:

```yaml
include:
  - local: '.gitlab-ci/deploy-prod.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
  - local: '.gitlab-ci/security-scans.yml'
    rules:
      - exists:
          - docker-compose.yml
  - project: 'security/scanners'
    file: '/container-scanning.yml'
    rules:
      - if: '$CI_COMMIT_TAG'
```

**Критический нюанс:** Переменные в `include:rules` вычисляются в момент **создания** пайплайна. Переменные, передаваемые через `dotenv` артефакты от предыдущих заданий, здесь **недоступны**, так как слияние YAML происходит до запуска любого задания.

### Параметризация через `include:inputs` (v16.0+)

Позволяет передавать входные параметры в подключаемый файл, содержащий блок `spec:inputs`. Обеспечивает строгую типизацию и валидацию конфигурации.

```yaml
# Подключение шаблона с входными параметрами
include:
  - project: 'shared/templates'
    file: 'build.yml'
    inputs:
      stage: pre-build
      verbose: true
      docker_version: "27.0"
```

```yaml
# Внутри шаблона (build.yml)
spec:
  inputs:
    stage:
      type: string
      default: build
    verbose:
      type: boolean
      default: false
    docker_version:
      type: string
      default: "24.0"
---
# Реализация шаблона
build-app:
  stage: $[[ inputs.stage ]]
  script:
    - docker build --build-arg DOCKER_VERSION=$[[ inputs.docker_version ]] .
```

### Порядок обработки директив

Понимание последовательности компиляции критично для отладки и предсказания поведения пайплайна:

1. **Разрешение `include`** — загрузка и объединение всех YAML-файлов из локальных, проектных, удаленных и компонентных источников.
2. **Интерполяция `inputs`** — подстановка значений параметров через `$[[ inputs.key ]]`. Разрешается **до** `variables` и `extends`.
3. **Обработка `variables`** — разрешаются статические переменные. Значения из `inputs` уже доступны.
4. **Применение `extends`** — слияние структур заданий по алгоритму Reverse Deep Merge.
5. **Разрешение `!reference`** — финальная вставка фрагментов кода.

> **Важно:** Порядок обработки объясняет, почему:
> - `inputs` нельзя использовать для динамического формирования имен переменных в том же блоке `variables` (шаг 2 до шага 3).
> - `!reference` не может обращаться к переменным, определенным в том же блоке (шаг 5 после шага 4).
> - Локальные задания всегда перезаписывают включенные через `include` (шаг 1).

### Рекомендуемый стек версий

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| GitLab | 11.3 | 17.x+ | `include:component` требует 16.2+; `integrity` — 17.9+ |
| GitLab Runner | 12.0 | 17.x+ | Совместимость с последними фичами |
| `inputs` + `include` | 16.0 | 17.x+ | Параметризация шаблонов |
| `include:component` | 16.2 | 17.x+ | CI/CD Catalog, типизация |
| `integrity` (remote) | 17.9 | 17.x+ | Проверка целостности удалённых файлов |
| `!reference` | 13.9 | 17.2+ | Индексы массивов |

### Предварительные условия

Для внедрения централизации через `include` необходимо:
- **Доступ к репозиторию:** Проекты-потребители должны иметь права на чтение (`Reporter`+) репозитория с шаблонами. Для приватных групп может потребоваться настройка `Token Access` (Allowlist).
- **Единый инстанс:** Директива `project` работает только в пределах одного инстанса GitLab. Для внешних подключений используется `include:remote`.
- **Глобальные переменные:** Наличие в проектах-потребителях предопределённых переменных, которые ожидает шаблон (например, `$CI_REGISTRY_IMAGE`).
- **Согласованность стадий:** Стадии (`stages`), указанные в шаблонах, должны быть определены в локальном файле `.gitlab-ci.yml`. Иначе пайплайн не пройдёт валидацию.
- **GitLab Runner:** Настроенный с Docker или Kubernetes исполнителем. Для `include` нет особых требований к типу раннера — механизм работает на уровне компиляции пайплайна.

## Практические сценарии

### Сценарий 1: Создание переиспользуемого модуля сборки

В библиотеке создается шаблон, использующий скрытые задания (`.job_name`) для предотвращения автоматического запуска при подключении.

```yaml
# shared/ci-templates/docker-build.yml
.docker-build-base:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  variables:
    DOCKER_DRIVER: overlay2
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

**Рабочий пайплайн проекта (`.gitlab-ci.yml`):**
```yaml
include:
  - project: 'shared/ci-templates'
    ref: 'v1.5.2'
    file: '/docker-build.yml'

stages:
  - build
  - test
  - deploy

# Активация задания через наследование
build-docker-image:
  extends: .docker-build-base
```

### Сценарий 2: Условное подключение (Edge Case)

Использование `rules` внутри `include` позволяет подключать шаблоны только при определенных условиях (наличие файла, специфическое окружение, ветка):

```yaml
include:
  - project: 'shared/ci-templates'
    file: '/security-scanners.yml'
    rules:
      - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

  - project: 'shared/ci-templates'
    file: '/container-scanning.yml'
    rules:
      - exists:
          - Dockerfile

  - local: '.gitlab-ci/deploy-staging.yml'
    rules:
      - if: $CI_COMMIT_BRANCH == "develop"
```

### Сценарий 3: Модульная конфигурация проекта (Domain-driven CI)

Разделение ответственности между командами через локальные `include`:

```yaml
include:
  - local: '.gitlab-ci/security.yml'   # Security Team
  - local: '.gitlab-ci/tests.yml'      # QA Team
  - local: '.gitlab-ci/deploy.yml'     # DevOps Team
  - local: '.gitlab-ci/monitoring.yml' # SRE Team

stages:
  - build
  - test
  - security
  - deploy
  - monitor
```

### Сценарий 4: Централизация стандартов (SSoT) и миграция инструмента

Все проекты компании используют единый стандарт сборки Docker-образов. При обновлении стандарта (например, переход с Docker-in-Docker на Kaniko) изменения вносятся один раз:

```yaml
# shared/ci-templates/docker-build.yml (ДО)
.docker-build-base:
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker build -t $IMAGE .

# shared/ci-templates/docker-build.yml (ПОСЛЕ)
.docker-build-base:
  image: gcr.io/kaniko-project/executor:v1.23.0
  script:
    - /kaniko/executor --context $CI_PROJECT_DIR --destination $IMAGE
  variables:
    DOCKER_CONFIG: "/kaniko/.docker"
```

Проекты-потребители **не изменяются** — обновление происходит автоматически при смене тега шаблона.

### Сценарий 5: Шаблон с `inputs` для типизации (v16.0+)

Создание универсального шаблона деплоя, который адаптируется под тип приложения:

```yaml
# shared/ci-templates/deploy.yml
spec:
  inputs:
    environment:
      type: string
      description: "Целевое окружение"
    replicas:
      type: integer
      default: 2
    manual:
      type: boolean
      default: false
---
deploy-app:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl scale deployment/$APP --replicas=$[[ inputs.replicas ]] -n $[[ inputs.environment ]]
  environment:
    name: $[[ inputs.environment ]]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: $[[ inputs.manual && 'manual' || 'on_success' ]]
```

```yaml
# my-app/.gitlab-ci.yml
include:
  - project: 'shared/ci-templates'
    ref: v3.0.0
    file: '/deploy.yml'
    inputs:
      environment: production
      replicas: 3
      manual: true
```

### Сценарий 6: Комбинация `include:project` и `include:template` для безопасности

Подключение корпоративных шаблонов безопасности и стандартных сканеров GitLab:

```yaml
include:
  # Корпоративные стандарты (SSoT)
  - project: 'security/ci-templates'
    ref: v2.0.0
    file: '/license-scanning.yml'

  # Стандартные сканеры GitLab
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml
```

### Сценарий 7: Enterprise-паттерн «Platform CI»

Для крупных организаций (100+ проектов):

```yaml
# Центральный репозиторий: shared/ci-templates
# Шаблон с !reference для SSH-деплоя
.ssh_deploy_base:
  stage: deploy
  image: alpine:3.19
  before_script:
    - apk add --no-cache openssh-client
  script:
    - ssh -o StrictHostKeyChecking=no $DEPLOY_USER@$DEPLOY_HOST "cd /app && docker pull $IMAGE && docker-compose up -d"

# Проект: включение шаблона с кастомизацией
include:
  - project: 'shared/ci-templates'
    file: '/templates/ssh-deploy.yml'
    ref: 'v3.0.0'

deploy_staging:
  extends: .ssh_deploy_base
  variables:
    DEPLOY_HOST: "staging.internal"
    DEPLOY_USER: "deploy-bot"
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy_production:
  extends: .ssh_deploy_base
  variables:
    DEPLOY_HOST: "prod.internal"
    DEPLOY_USER: "deploy-bot"
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  when: manual
```

### Сценарий 8: Выделенный репозиторий CI (Platform CI Repository)

В крупных инфраструктурах (100+ сервисов) часто создается отдельный репозиторий, содержащий **все** определения пайплайнов. Проекты с кодом содержат минимальный `.gitlab-ci.yml`, который подключает шаблоны из центрального репозитория:

```yaml
# my-service/.gitlab-ci.yml (минимальный)
include:
  - project: 'platform/ci'
    ref: v4.2.0
    file: '/pipelines/java-service.yml'
  - project: 'platform/ci'
    ref: v4.2.0
    file: '/pipelines/security-sast.yml'
```

```yaml
# platform/ci/pipelines/java-service.yml
stages:
  - build
  - test
  - deploy

.build-base:
  image: maven:3.9-eclipse-temurin-21
  cache:
    paths:
      - .m2/repository

build:
  extends: .build-base
  stage: build
  script:
    - mvn compile -DskipTests

test:
  extends: .build-base
  stage: test
  script:
    - mvn test

deploy:
  stage: deploy
  script:
    - ./deploy-to-argocd.sh
```

**Преимущества:**
- **Единый стандарт:** Все изменения в пайплайнах (добавление стадии, обновление сканеров) выполняются в одном месте.
- **Версионирование:** Teams обновляют версию шаблона по мере готовности (`ref: v4.2.0` → `ref: v4.3.0`).
- **Изоляция:** Проекты с кодом не содержат CI-логики, что снижает когнитивную нагрузку на разработчиков.
- **Безопасность:** Security-команда управляет сканерами в центральном репозитории, разработчики не могут их отключить.

**Ограничения:**
- При изменении шаблона необходимо тестировать влияние на все потребителей.
- Требуется настройка `Token Access` в GitLab для доступа из проектов к центральному репозиторию.

### Сценарий 9: Отладка итоговой конфигурации

Проверка результата всех `include` перед коммитом:

```bash
# Просмотр полной (развернутой) конфигурации
glab ci lint --show-expanded

# Проверка конкретного файла
glab ci lint --show-expanded | grep -A10 "build-app"

# Экспорт для аудита
glab ci lint --show-expanded > full_pipeline.yml
```

**Чеклист валидации:**
1. `Pipeline Editor` → вкладка «View merged YAML» — визуальная проверка итога.
2. `glab ci lint --show-expanded` — локальная проверка перед пушем.
3. Проверьте, что все `include:project` пути корректны и `ref` существует.
4. Убедитесь, что `include:rules` не ссылаются на переменные из `dotenv` (они ещё не доступны).

## Валидация и отладка

### Инструменты валидации

| Инструмент | Назначение | Команда / Доступ |
| :--- | :--- | :--- |
| **Pipeline Editor** | Визуальный просмотр раскрытого YAML с подсветкой ошибок интерполяции `inputs`. | Web UI → CI/CD → Pipeline Editor → вкладка «View merged YAML» |
| **GitLab CLI (`glab`)** | Локальная проверка синтаксиса и раскрытие `include`/`extends`/`inputs`. | `glab ci lint` / `glab ci lint --show-expanded` |
| **CI Lint API** | Программная проверка через HTTP (для использования в CI-пайплайнах шаблонов). | `POST /api/v4/projects/:id/ci/lint` |
| **Dry Run (v16.11+)** | Глубокая валидация, имитирующая создание пайплайна. Проверяет права, наличие образов, корректность `rules`. | `glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event` |

### Чек-лист валидации

Перед коммитом убедитесь:
- [ ] `glab ci lint` проходит без ошибок.
- [ ] `glab ci lint --show-expanded` показывает корректный раскрытый YAML.
- [ ] Блок `spec:inputs` заполнен и синтаксически верен (для компонентов).
- [ ] Все внутренние ссылки (относительные пути) проверены и работают.
- [ ] Создан релиз с тегом SemVer (для компонентов CI/CD Catalog).

### Отладка в логах

При возникновении ошибок с переменными добавьте команду `export` или `env` в `script`, чтобы увидеть финальные значения, полученные в результате слияния:

```yaml
script:
  - export  # Показать все переменные окружения
  - env | grep -E "^(CI_|DOCKER_)"  # Фильтр по префиксу
```

### CI Lint API (программная проверка)

```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"content": "include:\n  - project: shared/ci-templates\n    file: templates/build.yml"}' \
  "https://gitlab.example.com/api/v4/ci/lint?include_merged_yaml=true"
```

## Устранение неполадок

### Системные ограничения и лимиты

| Ограничение | Значение | Описание |
| :--- | :--- | :--- |
| **Максимум файлов** | **150** | Общее количество файлов (включая рекурсию) |
| **Таймаут загрузки** | **30 секунд** | Лимит на каждый внешний запрос (`remote`/`project`) |
| **Глубина вложенности** | Не ограничена явно | Рекомендуется до 3–5 уровней для удобства отладки |
| **Размер YAML** | **5 МБ** | Лимит на итоговый смерженный файл |
| **Максимум компонентов** | **100** | Для проектов-ресурсов CI/CD Catalog (v18.5+) |

### Сводная таблица ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Included file not found` | Неверный путь к файлу или опечатка в имени проекта. | Проверьте путь от корня репозитория шаблонов и `Visibility` проекта. Убедитесь, что `ref` существует. |
| `Project not found` | У Runner или пользователя нет прав на чтение репозитория шаблонов. | Проверьте настройки `Token Access` (Allowlist) в репозитории шаблонов. Роль `Reporter`+. |
| `Job name conflict` | Задание в проекте имеет то же имя, что и в `include`. | Используйте скрытые задания (с префиксом `.`) в шаблонах или уникальные префиксы в именах. |
| `Include limit exceeded` | Глубина вложенности `include` превысила 150 уровней. | Проведите рефакторинг иерархии, избегайте циклических подключений (A → B → A). |
| `exceeded max includes` | Циклические или слишком глубокие `include`. | Устраните кольцевые ссылки. Проверьте, не подключает ли шаблон сам себя (через рекурсию). |
| `file does not exist` | Файл отсутствует в указанном `ref` (ветке/теге). | Проверьте, существует ли файл в целевом теге. Используйте `git show v1.0.0:path/to/file.yml`. |
| `include timeout` | Внешний URL (`remote`) недоступен или тормозит (>30 сек). | Проверьте сеть, доступность URL. Используйте локальные копии шаблонов или кэширование (v18.9+). |
| `rules condition failed` | Ошибка в синтаксисе `if` или отсутствие переменной в `rules`. | Проверьте доступность переменных на этапе компиляции. Переменные из `dotenv` недоступны в `include:rules`. |
| `integrity check failed` | SHA256-хеш удалённого файла не совпадает с указанным. | Обновите значение `integrity` или проверьте, не был ли файл подменён. |
| `Input 'X' must match regex` | При комбинации с `inputs`: переданное значение нарушает правила валидации из `spec:inputs`. | Проверьте входные данные на соответствие регулярному выражению в шаблоне. |
| `included file not found` (локальный) | Файл не виден парсеру (Git submodule, `.gitignore`, неправильное расширение). | Убедитесь, что файл не в submodule, имеет расширение `.yml`/`.yaml` и не в `.gitignore`. |
| Изменение шаблона ломает проекты | Родительский шаблон изменил структуру (добавил обязательный ключ или переименовал переменную). | Используйте SemVer для версионирования шаблонов. Закрепляйте версию через `ref: vX.Y.Z`. |

## Особенности и ограничения

1. **Лимит вложенности:** Максимум 150 файлов `include` (включая рекурсию). Практический лимит — 3–5 уровней для удобства отладки.
2. **Единый инстанс:** Директива `include:project` работает только в пределах одного инстанса GitLab. Для внешних подключений используется `include:remote`.
3. **Замена массивов:** Массивы (`script`, `rules`, `tags`) полностью замещаются, не дополняются. Для обхода required `!reference`.
4. **YAML Anchors не работают между файлами:** При выносе кода в шаблоны всегда заменяйте их на `!reference`.
5. **Переменные в rules:** Переменные в `include:rules` вычисляются в момент создания пайплайна. Переменные из `dotenv` артефактов недоступны.
6. **Глобальные ключи в компонентах:** Компоненты CI/CD Catalog не могут использовать `stages:`, `default:`, `workflow:` — они навязывают поведение всему проекту.
7. **Глобальные ключи deprecated:** GitLab 18.x/19.x считает устаревшими глобальные `before_script`, `image`, `cache` на верхнем уровне YAML — рекомендуется блок `default`.

## Преимущества и недостатки

| Преимущество | Описание |
| :--- | :--- |
| **Масштабируемость** | Возможность внедрять критические патчи безопасности во все проекты одной правкой в центральном шаблоне. |
| **Чистота кода** | Удаление сотен строк YAML-кода из прикладных репозиториев. Проект содержит только специфичную логику. |
| **Версионирование** | Git-теги и SemVer позволяют планово обновлять стандарты, фиксировать откат. |
| **Безопасность** | Централизованное управление сканерами (SAST, DAST, Secret Detection) через `include:template` и компоненты. |
| **Совместимость** | Работает с любым типом Runner и версией GitLab 11.3+. Интегрируется с `extends`, `!reference`, `inputs`. |

| Недостаток | Описание | Решение |
| :--- | :--- | :--- |
| **Жёсткость шаблонов** | Проект не может изменить стадию, образ или набор команд без правки шаблона. | Решается комбинацией с [extends](./extends_keyword.md). |
| **Скрытые зависимости** | Падение центрального репозитория или ошибки в нём блокируют работу всей компании. | Требует отказоустойчивости (Mirror, Backup). |
| **Глобальная ошибка** | Опечатка в центральном шаблоне мгновенно ломает все проекты-потребители. | Требует строгого CI-тестирования шаблонов и SemVer. |
| **Замена массивов** | Массивы (`script`, `rules`, `tags`) полностью замещаются, не дополняются. | Для обхода required `!reference`. |
| **Лимит вложенности** | Максимум 150 файлов `include`. | Практический лимит — 3–5 уровней. |

## Дополнительная информация

### Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — архитектурное сравнение всех методов.
- **[Механизм extends](./extends_keyword.md)** — наследование и переопределение внутри включенных файлов.
- **[Механизм !reference](./reference_and_yaml_anchors.md)** — точечная вставка фрагментов кода между файлами.
- **[CI/CD Catalog](./ci_cd_catalog_components.md)** — современная альтернатива классическим шаблонам.
- **[CI/CD Catalog: ограничения](./ci_cd_catalog_limits.md)** — системные лимиты вложенности, размера и inputs.
- **[Переменные и секреты](../../Concepts/gitlab_ci_variables_secrets.md)** — как переменные пробрасываются через `include`.
- **[Директивы GitLab CI/CD](../../Advanced/workflow_rules/directives_definitions.md)** — полный справочник `default`, `rules`, `!reference`, `inputs`.
- **[Эволюция переиспользуемых пайплайнов](./evolution/evolution_include.md)** — контекст этапа и архитектура централизации.

### Внешние ресурсы

- [GitLab Docs: CI/CD YAML include](https://docs.gitlab.com/ee/ci/yaml/#include)
- [GitLab CI Templates Library](https://gitlab.com/gitlab-org/gitlab/-/tree/master/lib/gitlab/ci/templates)
- [Integrity check for remote includes](https://docs.gitlab.com/ee/ci/pipelines/pipeline_architectures.html#integrity-check-for-remote-includes)
