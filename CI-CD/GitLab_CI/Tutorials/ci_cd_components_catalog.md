# CI/CD Components Catalog в GitLab CI/CD

**Актуально для:** GitLab 17.x / 19.x

## Определения

**CI/CD Component** — автономный, версионируемый блок конфигурации CI/CD, хранящийся в директории `templates/` репозитория-компонента и имеющий строго типизированный публичный интерфейс через `spec:inputs`. Компонент подключается в потребительские пайплайны через `include:component`.

**CI/CD Catalog** — централизованный реестр GitLab для публикации, обнаружения и управления версиями компонентов. Проект, помеченный как «Catalog resource», становится источником компонентов для всей организации.

**`spec:inputs`** — декларативный блок в компоненте, описывающий входные параметры: типы (`string`, `number`, `boolean`, `array`), значения по умолчанию, валидацию через `regex` и `options`, а также документацию через `description`.

**Интерполяция `$[[ inputs.<name> ]]`** — механизм подстановки значений параметров в конфигурацию компонента. Выполняется на этапе компиляции пайплайна до разрешения `variables` и `extends`, что исключает конфликты имен с переменными окружения.

**Контекстная интерполяция `$[[ component.* ]]`** — механизм (GA в 18.7), позволяющий компоненту получать доступ к собственным метаданным (`name`, `version`, `sha`, `reference`) без явной передачи через `inputs`. Для работы поля должны быть объявлены в `spec:component`.

**SemVer (Semantic Versioning)** — схема версионирования `MAJOR.MINOR.PATCH` (например, `1.2.3`), обязательная для публикации компонентов в Catalog. GitLab поддерживает частичные версии (`@1.2`, `@1`) и указатель `~latest` для автоматического получения обновлений.

**Catalog resource** — проект GitLab, включивший тумблер **Settings > General > Visibility, project features, permissions > CI/CD Catalog project**. Только такие проекты публикуют компоненты в каталог.

**Публикация (Registration)** — процесс создания GitLab Release на тег SemVer, делающий версию компонента доступной в Catalog для `include:component` другими проектами.

**Валидация компонента** — процесс проверки синтаксиса `spec:inputs`, корректности интерполяции и соблюдения лимитов. Выполняется автоматически при публикации и доступна для ручного запуска через `glab ci lint` или API `/ci/lint`.

## Основные концепции

### Архитектура и жизненный цикл компонента

```
┌──────────────────────────────────────────────────────────────┐
│  Репозиторий компонента (Catalog resource)                    │
│                                                              │
│  ├── templates/                                              │
│  │   ├── build.yml        # spec:inputs + --- + задания      │
│  │   └── security/        # Вложенный компонент              │
│  │       └── scan.yml     # (вызов: .../security/scan)       │
│  ├── tests/                 # Интеграционные тесты            │
│  ├── README.md              # Документация для UI каталога    │
│  └── .gitlab-ci.yml         # CI/CD самого компонента        │
│      stages: [lint, test, publish]                           │
└──────────────────────────────────────────────────────────────┘
         │                  │                  │
         │ include:component │ include:component │ include:component
         │ @1.2.0            │ @1.2.0            │ @1.2.0
         ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Проект A    │   │  Проект B    │   │  Проект N    │
│  .gitlab-ci  │   │  .gitlab-ci  │   │  .gitlab-ci  │
│  5 строк     │   │  8 строк     │   │  6 строк     │
└──────────────┘   └──────────────┘   └──────────────┘
```

Компонент проходит три стадии:
1. **Разработка** — написание `spec:inputs`, реализация заданий, локальное тестирование через `glab ci lint`.
2. **Публикация** — создание GitLab Release с тегом SemVer, что делает версию видимой в Catalog.
3. **Потребление** — подключение через `include:component` в проектах-потребителях с передачей `inputs`.

### Интерполяция и порядок разрешения

GitLab обрабатывает конфигурацию в строгом порядке. Понимание этого порядка критично для отладки:

1. **Разрешение `include`** — сбор всех файлов (компоненты, шаблоны, локальные include).
2. **Интерполяция `inputs`** — подстановка значений `$[[ inputs.<name> ]]` во все блоки YAML, включая `script`, `rules`, `variables`. Теги `!reference` разрешаются после интерполяции.
3. **Обработка `variables`** — разрешение переменных окружения. Значения из `inputs` уже доступны.
4. **Разрешение `extends` и `!reference`** — финальное слияние структур.

### Управление версиями и SemVer

Компоненты в Catalog требуют SemVer для публикации. GitLab разрешает версии по строгому приоритету:

1. **Commit SHA** — высший приоритет. Если имя тега совпадает с коротким SHA, приоритет отдается SHA.
2. **Тег** — приоритет над веткой при совпадении имен.
3. **Ветка** — только для разработки, не публикуется в Catalog без Release.
4. **`~latest`** — выбирает самый свежий Release, исключая пре-релизы (RC, beta).
5. **Частичный SemVer** (`@1.2`, `@1`) — автоматически получает обновления patch/minor.

> **Best Practice:** В production-пайплайнах используйте полный SemVer (`@1.2.3`) или Commit SHA. Частичные версии и `~latest` допустимы только для development.

### Структура репозитория компонента

Для корректной публикации и поиска репозиторий должен следовать стандартной иерархии:

```text
component-repo/
├── templates/
│   ├── build.yml            # Вариант 1: плоский файл
│   │                        # (вызов: .../component-repo/build)
│   └── security/
│       └── scan.yml         # Вариант 2: подкаталог
│                            # (вызов: .../component-repo/security)
├── tests/                   # Интеграционные тесты (рекомендация)
├── README.md                # Парсится каталогом для UI
├── CHANGELOG.md             # История изменений
└── .gitlab-ci.yml           # Пайплайн тестирования и релиза
```

**Важно:** каталог `templates/` — единственное место, из которого GitLab читает компоненты. Файлы за его пределами в каталог не публикуются.

## Предварительные требования

- **GitLab:** 17.0+ (GA CI/CD Catalog и компонентов). Для контекстной интерполяции `$[[ component.* ]]` требуется 18.7+. Для аналитики использования — 19.0+ (Premium/Ultimate).
- **GitLab Runner:** любой поддерживаемый исполнитель (Docker, Shell, Kubernetes). Компоненты работают на уровне компиляции пайплайна и не требуют специальных раннеров.
- **Статус проекта:** проект-компонент должен быть помечен как «Catalog resource» в настройках. Включить тумблер может только роль **Owner**.
- **Права доступа:** `Maintainer` или `Owner` — для публикации релиза; `Developer` и выше — для вызова компонента. Для приватных проектов потребитель должен иметь роль не ниже **Reporter**.
- **SemVer:** публикация в Catalog требует тегов SemVer, созданных как GitLab Release (простой git-тег без Release не попадет в каталог).
- **Сетевой доступ:** Runner → API GitLab (порты 80/443) для загрузки компонентов при компиляции пайплайна.
- **CLI:** `glab` версии 1.40+ рекомендуется для локальной валидации и отладки.

## Практические сценарии

### Сценарий 1: Создание и публикация компонента сборки Docker

Компонент-композиция для сборки и публикации Docker-образа с поддержкой multi-arch.

**Файл компонента (`templates/build-docker.yml`):**

```yaml
spec:
  inputs:
    image_name:
      type: string
      default: "app"
      description: "Name of the Docker image"
    image_tag:
      type: string
      default: "latest"
      description: "Tag of the Docker image"
    dockerfile_path:
      type: string
      default: "Dockerfile"
      description: "Path to Dockerfile"
    build_args:
      type: array
      default: []
      description: "Build arguments for docker build"
    platforms:
      type: array
      default: ["linux/amd64"]
      description: "Platforms for multi-arch build"
---
build-docker:
  stage: build
  image: docker:29
  services:
    - docker:29-dind
  variables:
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_CERTDIR: /certs
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - |
      BUILD_ARGS=""
      for arg in $[[ inputs.build_args ]]; do
        BUILD_ARGS="$BUILD_ARGS --build-arg $arg"
      done
    - |
      docker buildx create --use --name multiarch-builder || true
      docker buildx inspect --bootstrap || true
    - docker buildx build \
        --platform $[[ inputs.platforms ]] \
        --file $[[ inputs.dockerfile_path ]] \
        $BUILD_ARGS \
        -t $CI_REGISTRY_IMAGE/$[[ inputs.image_name ]]:$[[ inputs.image_tag ]] \
        --push \
        .
  rules:
    - if: $CI_PIPELINE_SOURCE == "pipeline"
```

**Публикация в Catalog (`.gitlab-ci.yml` репозитория компонента):**

```yaml
stages:
  - lint
  - test
  - publish

lint:
  stage: lint
  image: alpine:3.21
  script:
    - apk add --no-cache yamllint
    - yamllint -d relaxed templates/*.yml

test:
  stage: test
  image: docker:29
  services:
    - docker:29-dind
  script:
    - echo "Run integration tests with various inputs"

publish:
  stage: publish
  image: registry.gitlab.com/gitlab-org/cli:latest
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  script:
    - echo "Publishing component $CI_COMMIT_TAG"
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: './CHANGELOG.md'
```

**Использование в проекте-потребителе:**

```yaml
include:
  - component: gitlab:$CI_SERVER_FQDN/group/components/build-docker@1.2.0
    inputs:
      image_name: "myapp"
      image_tag: "$CI_COMMIT_SHORT_SHA"
      build_args:
        - "NODE_ENV=production"
        - "API_URL=https://api.example.com"
      platforms:
        - "linux/amd64"
        - "linux/arm64"
```

### Сценарий 2: Компонент сканирования безопасности

Универсальный компонент для запуска Trivy с поддержкой разных типов сканирования.

```yaml
# templates/security-scan.yml
spec:
  inputs:
    scan_type:
      type: string
      default: "sast"
      options: [sast, dast, secret, dependency]
    fail_on_vulnerability:
      type: boolean
      default: true
    severity_threshold:
      type: string
      default: "HIGH,CRITICAL"
      description: "Severity levels to fail on"
---
security-scan:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    - |
      case $[[ inputs.scan_type ]] in
        sast)
          trivy fs --format json --output report.json .
          ;;
        dast)
          trivy image --format cyclonedx --output report.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
          ;;
        secret)
          trivy fs --scanners secret --format json --output report.json .
          ;;
        dependency)
          trivy fs --scanners vuln --format json --output report.json .
          ;;
      esac
    - |
      if [ "$[[ inputs.fail_on_vulnerability ]}" = "true" ]; then
        trivy exit-code --severity $[[ inputs.severity_threshold ]] report.json
      fi
  artifacts:
    reports:
      cyclonedx: report.json
    expire_in: 30 days
```

**Использование:**

```yaml
include:
  - component: gitlab:$CI_SERVER_FQDN/group/components/security-scan@1.1.0
    inputs:
      scan_type: "secret"
      fail_on_vulnerability: true
      severity_threshold: "CRITICAL"
```

### Сценарий 3: Компонент деплоя

Компонент для деплоя приложения через Helm. В качестве образа используйте сборку с предустановленным Helm, либо установите Helm в скрипте.

```yaml
# templates/k8s-deploy.yml
spec:
  inputs:
    namespace:
      type: string
      default: "default"
      description: "Kubernetes namespace"
    release_name:
      type: string
      default: "myapp"
      description: "Helm release name"
    chart_path:
      type: string
      default: "./charts/app"
      description: "Path to Helm chart"
    values_file:
      type: string
      default: "values.yaml"
      description: "Helm values file"
    image_tag:
      type: string
      description: "Docker image tag"
    timeout:
      type: string
      default: "300s"
      description: "Helm upgrade timeout"
---
deploy-k8s:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm repo add bitnami https://charts.bitnami.com/bitnami
    - helm upgrade --install $[[ inputs.release_name ]] $[[ inputs.chart_path ]] \
        --namespace $[[ inputs.namespace ]] \
        --values $[[ inputs.values_file ]] \
        --set image.tag=$[[ inputs.image_tag ]] \
        --timeout $[[ inputs.timeout ]] \
        --wait \
        --atomic
  environment:
    name: $[[ inputs.namespace ]]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Использование:**

```yaml
include:
  - component: gitlab:$CI_SERVER_FQDN/group/components/k8s-deploy@1.0.0
    inputs:
      namespace: "production"
      release_name: "myapp"
      chart_path: "./charts/production"
      values_file: "values-production.yaml"
      image_tag: "$CI_COMMIT_SHORT_SHA"
      timeout: "600s"
```

### Сценарий 4: Наследование и переопределение компонентов

Один и тот же компонент можно подключить несколько раз с разными `inputs`. Для avoidance конфликтов имен заданий используйте `alias`.

```yaml
include:
  # Первое подключение: сборка для staging
  - component: gitlab:$CI_SERVER_FQDN/group/components/build-docker@1.2.0
    inputs:
      image_name: "myapp"
      image_tag: "$CI_COMMIT_SHORT_SHA"
      platforms:
        - "linux/amd64"

  # Второе подключение: сборка для production с другими параметрами
  - component: gitlab:$CI_SERVER_FQDN/group/components/build-docker@1.2.0
    alias: build-production
    inputs:
      image_name: "myapp"
      image_tag: "$CI_COMMIT_SHORT_SHA"
      platforms:
        - "linux/amd64"
        - "linux/arm64"
```

> **Важно:** `alias` предотвращает конфликт имен заданий при повторном подключении одного компонента. Без `alias` задания с одинаковыми именами будут объединены по правилам `deep_merge`.

### Сценарий 5: Compliance-компонент

Компонент для проверки compliance-правил и audit events через GitLab API.

```yaml
# templates/compliance-check.yml
spec:
  inputs:
    framework:
      type: string
      default: "soc2"
      options: [soc2, hipaa, pci-dss, iso27001]
    fail_on_non_compliance:
      type: boolean
      default: true
---
compliance-check:
  stage: compliance
  image: curlimages/curl:8.21.0
  script:
    - |
      case $[[ inputs.framework ]] in
        soc2)
          curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "https://gitlab.example.com/api/v4/compliance/compliance_management/compliance_frameworks" | \
            jq -r '.[] | select(.name == "SOC 2")'
          ;;
        hipaa)
          curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "https://gitlab.example.com/api/v4/compliance/compliance_management/compliance_frameworks" | \
            jq -r '.[] | select(.name == "HIPAA")'
          ;;
      esac
    - |
      curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.example.com/api/v4/audit_events" | \
        jq '.[] | select(.event_name == "user_login")'
  allow_failure: false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Использование:**

```yaml
include:
  - component: gitlab:$CI_SERVER_FQDN/group/components/compliance-check@1.0.0
    inputs:
      framework: "soc2"
      fail_on_non_compliance: true
```

### Сценарий 6: Многокомпонентный пайплайн

Композиция нескольких компонентов в единый пайплайн с дополнительной задачей деплоя.

```yaml
include:
  # Build
  - component: gitlab:$CI_SERVER_FQDN/group/components/build-docker@1.2.0
    inputs:
      image_name: "myapp"
      image_tag: "$CI_COMMIT_SHORT_SHA"
      platforms:
        - "linux/amd64"
        - "linux/arm64"

  # Security
  - component: gitlab:$CI_SERVER_FQDN/group/components/security-scan@1.1.0
    inputs:
      scan_type: "dependency"
      fail_on_vulnerability: true

  # Deploy
  - component: gitlab:$CI_SERVER_FQDN/group/components/k8s-deploy@1.0.0
    inputs:
      namespace: "staging"
      release_name: "myapp"
      image_tag: "$CI_COMMIT_SHORT_SHA"

stages:
  - build
  - security
  - deploy

deploy-production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/production \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Валидация и проверка

1. **Catalog UI:** Проверьте **CI/CD > Catalog** — компонент должен отображаться с описанием и входными параметрами.
2. **Component Test:** Запустите пайплайн с компонентом — должны выполняться задания из компонента.
3. **Inputs Validation:** Проверьте, что параметры передаются корректно и типы соблюдаются.
4. **Merged YAML:** В Pipeline Editor проверьте **View merged YAML** — убедитесь, что интерполяция `$[[ inputs.* ]]` заменилась на фактические значения.
5. **Version Resolution:** Проверьте, что версия компонента указывается явно (`@1.2.0` или SHA).
6. **Dependencies:** В логах Runner'а проверьте строки `Downloading artifacts` — убедитесь, что загружаются только нужные артефакты.

**Инструменты валидации:**

```bash
# Быстрая проверка синтаксиса
glab ci lint

# Просмотр итогового YAML с интерполяцией
glab ci config compile

# Валидация в контексте другого проекта
glab ci config compile --project my-org/target-app

# Валидация через API
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"content": "include:\n  - component: gitlab.example.com/org/comp@1.0.0"}' \
  "https://gitlab.example.com/api/v4/projects/<id>/ci/lint?include_merged_yaml=true"
```

## Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Component not found** | Неверный путь, отсутствие Release или проект не помечен как Catalog resource | Проверьте путь `$FQDN/group/project/name@version` и статус «Catalog resource». Убедитесь, что тег создан как GitLab Release. |
| **Unknown input: 'X'** | Параметр используется в YAML, но не описан в `spec:inputs` | Добавьте параметр в секцию `spec:inputs` или удалите использование. |
| **Input 'X' must match regex** | Значение нарушает правила валидации `regex` | Проверьте входные данные на соответствие регулярному выражению в `spec:inputs`. |
| **Input type mismatch** | Несоответствие типов (например, строка вместо числа) | Убедитесь, что типы в `inputs` и передаваемых значениях совпадают. |
| **Spec must be a valid json schema** | Блок `spec:inputs` объявлен, но пуст | Замените `spec:inputs:` на пустой `spec:` либо опишите хотя бы один вход. |
| **Component content not found** | Файл компонента отсутствует по указанному пути | Проверьте форму пути: `templates/<name>.yml` или `templates/<name>/template.yml`. |
| **Invalid global key: stages/default/workflow** | Использование глобальных ключей в компоненте | Перенесите настройки в задания компонента или передавайте через `inputs`. |
| **Maximum 150 includes are allowed** | Превышен суммарный лимит включений | Объедините мелкие include-файлы, используйте `!reference` для фрагментов кода. |
| **Component load timeout** | Превышение времени загрузки компонента | Проверьте сетевую доступность и размер компонента. Рассмотрите кэширование. |
| **Release job fails on existing release** | `release:tag_name` уже существует | Релиз не обновляется. Удалите старый релиз через `glab release list` и `glab release delete`. |
| **401 Unauthorized при создании релиза** | `GITLAB_TOKEN`/`GITLAB_ACCESS_TOKEN` переопределяет `CI_JOB_TOKEN` | Удалите эти переменные из задания или выдайте токену необходимые права. |
| **Image not found: release-cli (19.x)** | `release-cli` удален в GitLab 19.0 | Используйте `registry.gitlab.com/gitlab-org/cli:latest` — ключ `release:` работает через `glab`. |

## Лучшие практики (Best Practices)

**Безопасность:**
- Используйте Commit SHA для критических пайплайнов. Теги Git не являются неизменяемыми и могут быть перевешены.
- Включайте Publication Allowlist для каталога, чтобы контролировать, кто может публиковать компоненты.
- Используйте `compliance: true` для компонентов, прошедших compliance review.
- Валидируйте `spec:inputs` на уровне типов и `regex` для критических параметров.
- Никогда не используйте `@latest` в production-пайплайнах.

**Производительность:**
- Один компонент — одна ответственность. Компонент, который «собирает, тестирует, деплоит и сканирует», невозможно версионировать независимо.
- Используйте `dependencies: []` для задач, которые не используют результаты сборки (линтеры).
- Добавьте вход `job_name_prefix` и используйте `$[[ inputs.job_name_prefix ]]-task`, чтобы задания с одинаковыми именами не сливались молча.
- Документируйте все `inputs` через `description` — это единственный источник документации, который увидит пользователь в UI каталога.
- Используйте `rules:changes` внутри компонентов для запуска только при изменении релевантных файлов.

**Надёжность:**
- Всегда указывайте `expire_in` для артефактов компонентов.
- Тестируйте компоненты в изоляции перед публикацией: хотя бы happy path + edge cases + negative tests.
- Используйте semantic versioning (`@1.0.0`, `@1.1.0`, `@2.0.0`) и документируйте breaking changes в CHANGELOG.
- Для критичных компонентов используйте `interruptible: false`, чтобы результаты не потерялись при `auto_cancel`.
- Настройте автоматическую очистку устаревших версий компонентов.

**Governance (DevOps/SRE):**
- Назначьте Catalog Owner с правами `Owner` в проекте-каталоге.
- Включите Audit Events для проекта-каталога для отслеживания всех изменений.
- Настройте `resource_group` для пайплайна публикации, чтобы избежать гонок состояний при параллельных релизах.
- Объявляйте компонент устаревшим минимум за 2 мажорных релиза до удаления.
- Регулярно аудируйте потребителей компонентов (ежеквартально) через Catalog Analytics (19.0+).

**Эксплуатация:**
- Используйте `glab ci config compile --show-expanded` для отладки интерполяции.
- Фиксируйте production на полном SemVer или SHA; `~latest` и частичные версии — для development.
- При breaking change создайте новый мажорный тег. Старый мажор остается доступен для всех потребителей, зафиксировавших `@1.x.0`.

## Ограничения и граничные случаи

- **Глобальные ключи:** В компонентах не рекомендуются глобальные ключи (`stages`, `default`, `workflow`, `variables`) — они влияют на все джобы конвейера потребителя; альтернатива из документации: конфигурация в каждом джобе или `extends` с уникальными именами. В блоке `spec:` разрешены только `inputs`, `component` и `description`. `spec:include` использовать нельзя — компонент обязан быть самодостаточным; `include:local` для локальных файлов компонента, наоборот, рекомендован документацией.
- **Лимит компонентов:** Максимум 100 файлов в `templates/` одного проекта (18.5+; ранее 30 в 16.9).
- **Лимит входов:** Максимум 20 входов (`spec:inputs` верхнего уровня) у одного пайплайна. Для одного входа допускается до 50 значений в `options` (19.0+ для массивов в `options`).
- **Размер входов:** Строка внутри входа — < 1 КБ; суммарное содержимое входов — < 1 МБ.
- **Лимит include:** Суммарное количество узлов `include` (включая компоненты) — 150. На Self-Managed настраивается администратором.
- **Размер YAML:** Один файл — 2 МБ (`max_yaml_size_bytes`, 17.3+); суммарный раскрытый YAML — 314,6 МБ (`ci_max_total_yaml_size_bytes`).
- **Глубина extends:** Максимум 11 уровней (`MAX_NESTING_LEVELS = 10`). Рекомендуется не более 3–4.
- **Вложенность массивов:** В `script`, `before_script`, `after_script` и `rules` — максимум 10 уровней (`MAX_NESTING_LEVEL`).
- **~latest и частичные версии:** Работают только с компонентами, опубликованными в Catalog. Для обычных `include:component` по `project`/`ref` доступно только точное имя тега или SHA. Тег должен быть создан как GitLab Release.
- **dotenv и matrix:** Переменные из `dotenv`-артефактов не работают между инстансами матричных сборок (`parallel:matrix`).
- **Cross-project:** Для `needs:project` требуется настройка Inbound Allowlist (Zero Trust, GitLab 17.0+). Без этого возвращается `403 Forbidden`.
- **Перевес тегов:** Теги Git не являются неизменяемыми. В production используйте Commit SHA для защиты от отравления тегов.

## Очистка

```bash
# Удаление устаревших версий компонентов
glab api "projects/${PROJECT_ID}/ci/components" | \
  jq -r '.[] | select(.version | startswith("v1.")) | .id' | \
  xargs -I {} glab api "projects/${PROJECT_ID}/ci/components/{}" -X DELETE

# Инвентаризация компонентов, используемых в проектах группы
glab api "/groups/my-org/projects?include_subgroups=true&per_page=100" \
  | jq -r '.[].path_with_namespace' | while read -r p; do
    glab api "projects/${p//\//%2F}/repository/files/.gitlab-ci.yml/raw?ref=main" 2>/dev/null \
      | grep -oE 'component:.*@[^ ]+' | sed "s|^|${p}: |"
  done
```

## Дополнительная информация

### Смотрите также

- **[GitLab CI: Каталог компонентов](../Reusable_Pipelines/ci_cd_catalog_components.md)** — архитектура, `spec:inputs`, интерполяция, жизненный цикл
- **[Справочник CI/CD Catalog](../Reusable_Pipelines/ci_cd_catalog_reference.md)** — API, CLI, валидация, диагностические команды
- **[Ограничения каталога компонентов](../Reusable_Pipelines/ci_cd_catalog_limits.md)** — системные лимиты, запрещенные ключи, TCO
- **[Продвинутые сценарии Catalog](../Reusable_Pipelines/ci_cd_catalog_advanced_scenarios.md)** — миграция с `include:project`, цепочки компонентов, монорепозитории
- **[Компоненты CI/CD каталога — эволюция](../Reusable_Pipelines/evolution/evolution_components.md)** — эволюционный подход, безопасность цепочки поставок, тестирование компонентов
