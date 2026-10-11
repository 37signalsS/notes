# Миграция пайплайнов в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

*   **Migration (Миграция)** — процесс переноса существующих CI/CD пайплайнов из других систем (Jenkins, GitHub Actions, CircleCI, GitLab CI older versions) в GitLab CI.
*   **Groovy (Jenkinsfile)** — декларативный или скриптовый синтаксис конфигурации пайплайнов в Jenkins.
*   **Shared Libraries** — переиспользуемые части пайплайнов в Jenkins, хранящиеся в отдельном репозитории.
*   **CI/CD Catalog Components** — современный стандарт GitLab для переиспользуемых пайплайнов, заменяющий `include:project` и аналогичный Shared Libraries.
*   **Lift-and-Shift** — миграция пайплайна без изменения логики, только с переводом синтаксиса.
*   **Refactor-and-Adopt** — миграция с рефакторингом под idiomatic GitLab CI (DAG, components, caching).
*   **GitLab Flow** — стратегия ветвления, оптимизированная для GitLab CI/CD.
*   **CI_LINT_API** — эндпоинт `/api/v4/ci/lint` для валидации конфигурации во время миграции.
*   **Parallel Run** — параллельный запуск старого и нового пайплайнов для валидации эквивалентности результатов.
*   **Incremental Migration** — поэтапный перевод отдельных стадий/проектов в крупных монорепозиториях.

## Базовые концепции

### Предварительные требования

**Для миграции пайплайнов в GitLab CI/CD:**

*   GitLab 17.x+ (CE достаточно для базовой миграции; Premium/Ultimate для Catalog Components, Pipeline Execution Policies)
*   GitLab Runner 17.x+ (совместимый с executor'ами целевой инфраструктуры)
*   Доступ к исходным пайплайнам (Jenkinsfile, `.github/workflows/*.yml`, `.circleci/config.yml`)
*   `PRIVATE-TOKEN` с ролью Maintainer или выше в целевом проекте GitLab
*   Сетевая доступность из CI/CD Runner'ов до GitLab API и реестров контейнеров
*   Понимание исходной логики пайплайнов: переменные, секреты, артефакты, кэш, триггеры

**Для валидации миграции:**

*   Два окружения: staging (для тестирования) и production
*   Доступ к артефактам исходных пайплайнов для сравнения
*   Мониторинг метрик пайплайнов (длительность, статус, использование ресурсов)

### Стратегии миграции

Выбор стратегии зависит от сложности пайплайна, критичности downtime и требований к рискам:

| Стратегия | Подход | Применение | Риск |
|:---|:---|:---|:---|
| **Lift-and-Shift** | Прямой перевод синтаксиса Groovy/YSML → GitLab YAML | Простые пайплайны, ограниченное время | Средний |
| **Refactor-and-Adopt** | Рефакторинг под DAG, components, caching | Средние/сложные пайплайны, долгосрочная эксплуатация | Низкий |
| **Parallel Run** | Параллельный запуск старого и нового пайплайнов | Production, требующие полной валидации | Низкий |
| **Incremental Migration** | Поэтапный перевод отдельных стадий/проектов | Большие монорепозитории, множественные команды | Низкий |

### Архитектура миграции

```
[Исходная система CI/CD]
    │
    ├── Jenkins (Groovy)
    ├── GitHub Actions (YAML)
    └── CircleCI (YAML)
    │
    ▼
[Анализ и планирование]
    │
    ├── Инвентаризация пайплайнов
    ├── Карта переменных/секретов
    ├── Анализ артефактов и кэша
    └── Выбор стратегии миграции
    │
    ▼
[GitLab CI/CD]
    │
    ├── .gitlab-ci.yml
    ├── CI/CD Catalog Components
    ├── GitLab Runner'ы
    └── API / Webhooks
```

### Сравнение синтаксиса

| Концепт | Jenkins (Groovy) | GitHub Actions | GitLab CI (YAML) |
|:---|:---|:---|:---|
| Стадии | `stage('Build')` | `jobs.<job>.steps` | `stages:` + `stage:` |
| Параметры | `parameters {}` | `inputs` | `spec:inputs` (17.11+) |
| Переменные | `environment {}` | `env:` | `variables:` |
| Условия | `when {}` | `if:` | `rules:` |
| Кэш | `cache {}` | `actions/cache` | `cache:` |
| Артефакты | `archiveArtifacts` | `actions/upload-artifact` | `artifacts:` |
| Секреты | `withCredentials` | `secrets:` | `variables:` (masked/protected) |
| Дублирование | `template` | `uses:` | `include:` / components |
| Trigger | `build job:` | `workflow_call` | `trigger:` / `workflow:rules` |
| Matrix builds | `matrix { axis { ... } }` | `strategy: matrix` | `parallel:matrix` |

### Миграция Shared Libraries → CI/CD Catalog

Jenkins Shared Libraries ≈ GitLab CI/CD Catalog Components:

| Jenkins | GitLab CI |
|:---|:---|
| `vars/` | Component с `spec:inputs` |
| `src/` | Вспомогательные скрипты в репозитории component |
| `@Library` | `include:component` |

## Практические сценарии

### Сценарий 1: Простой пайплайн (Lift-and-Shift)

**Исходный Jenkinsfile:**
```groovy
pipeline {
  agent any
  stages {
    stage('Build') {
      steps {
        sh 'mvn clean package'
      }
    }
    stage('Test') {
      steps {
        sh 'mvn test'
      }
    }
    stage('Deploy') {
      when { branch 'main' }
      steps {
        sh 'deploy.sh'
      }
    }
  }
}
```

**Эквивалент `.gitlab-ci.yml`:**
```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  image: maven:3.9-eclipse-temurin-17
  script:
    - mvn clean package
  artifacts:
    paths:
      - target/*.jar
    expire_in: 1 week

test:
  stage: test
  image: maven:3.9-eclipse-temurin-17
  script:
    - mvn test

deploy:
  stage: deploy
  image: alpine:latest
  script:
    - ./deploy.sh
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 2: Параллельная миграция (Parallel Run)

Запуск пайплайнов в обеих системах для валидации:

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - build
  - test

# Валидация: сравниваем артефакты
validate_artifacts:
  stage: validate
  image: alpine:latest
  script:
    - echo "Comparing artifacts with Jenkins build..."
    - # Сравните артефакты по хэшу/размеру
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

build:
  stage: build
  image: maven:3.9-eclipse-temurin-17
  script:
    - mvn clean package
  artifacts:
    paths:
      - target/*.jar

test:
  stage: test
  image: maven:3.9-eclipse-temurin-17
  script:
    - mvn test
```

### Сценарий 3: Миграция с параметрами

**Jenkins:**
```groovy
parameters {
  string(name: 'ENV', defaultValue: 'staging', description: 'Target environment')
  booleanParam(name: 'DEPLOY', defaultValue: false, description: 'Deploy after build')
}
```

**GitLab CI:**
```yaml
spec:
  inputs:
    ENV:
      type: string
      default: "staging"
      description: "Target environment"
      options:
        - "staging"
        - "production"
    DEPLOY:
      type: boolean
      default: false
      description: "Deploy after build"

variables:
  TARGET_ENV: $ENV

build:
  stage: build
  script:
    - echo "Building for $TARGET_ENV"

deploy:
  stage: deploy
  script:
    - ./deploy.sh $TARGET_ENV
  rules:
    - if: $DEPLOY == "true"
      when: manual
```

### Сценарий 4: Миграция Shared Library → Component

**Jenkins Shared Library:**
```groovy
// vars/buildMaven.groovy
def call(String version) {
  docker.image("maven:${version}").inside {
    sh 'mvn clean package'
  }
}
```

**GitLab CI Component:**
```yaml
# В репозитории component
# .gitlab/component.yml
spec:
  inputs:
    maven_version:
      type: string
      default: "3.9"

# В пайплайне
include:
  - component: gitlab.com/components/maven-build@1.0
    inputs:
      maven_version: "3.9"

build:
  stage: build
  script:
    - mvn clean package
```

### Сценарий 5: Миграция credentials

**Jenkins:**
```groovy
withCredentials([string(credentialsId: 'db-password', variable: 'DB_PASS')]) {
  sh 'deploy.sh $DB_PASS'
}
```

**GitLab CI:**
```yaml
variables:
  DB_PASSWORD:
    value: ""
    protected: true
    masked: true
    description: "Database password"

deploy:
  stage: deploy
  script:
    - ./deploy.sh "$DB_PASSWORD"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 6: Полный enterprise-пайплайн

```yaml
stages:
  - lint
  - build
  - test
  - security
  - deploy

.default:
  image: maven:3.9-eclipse-temurin-17
  cache:
    key: ${CI_COMMIT_REF_SLUG}
    paths:
      - .m2/repository

lint:
  stage: lint
  script:
    - mvn verify -DskipTests

unit_test:
  stage: test
  script:
    - mvn test
  artifacts:
    reports:
      junit: target/surefire-reports/TEST-*.xml

integration_test:
  stage: test
  services:
    - postgres:15
  variables:
    POSTGRES_DB: test
    POSTGRES_USER: test
    POSTGRES_PASSWORD: test
  script:
    - mvn verify -DskipUnitTests

security_scan:
  stage: security
  include:
    - template: Security/SAST.gitlab-ci.yml
    - template: Security/Dependency-Scanning.gitlab-ci.yml
    - template: Security/Container-Scanning.gitlab-ci.yml

deploy_staging:
  stage: deploy
  environment:
    name: staging
  script:
    - ./deploy.sh staging
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"

deploy_prod:
  stage: deploy
  environment:
    name: production
  script:
    - ./deploy.sh production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Валидация

### Проверка синтаксиса через CI Lint API

```bash
# Валидация YAML-конфигурации
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{"content": "'"$(cat .gitlab-ci.yml | sed 's/"/\\"/g' | tr '\n' ' ')"'"}' \
  "https://gitlab.example.com/api/v4/ci/lint" | jq '.status, .errors, .warnings'

# Ожидаемый результат:
# "valid"
# []
# []
```

### Проверка strategies и переменных

```bash
# Список всех переменных проекта
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/variables" | jq '.[] | {key, protected, masked}'

# Проверка protected branches (для protected переменных)
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/protected_branches" | jq '.[].name'
```

### Сравнение артефактов между системами

```bash
# Получить артефакты из GitLab
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/jobs/123/artifacts" \
  --output gitlab_artifacts.zip

# Сравнить с Jenkins артефактами
sha256sum gitlab_artifacts.zip jenkins_artifacts.zip
# → должны совпадать (или быть эквивалентными по содержимому)
```

## Лучшие практики

### Безопасность

1.  **Не мигрируйте секреты автоматически**: Пересмотрите все credentials, используйте GitLab Secrets Manager или Vault.
2.  **Настройте Protected/Masked переменные**: В GitLab это флаги в UI, в Jenkins — отдельный механизм.
3.  **Pipeline Execution Policies**: Принудительное сканирование на уровне группы.
4.  **Scan Execution Policies**: Регулярное сканирование всех проектов.
5.  **Least Privilege**: Роли Maintainer для разработчиков, Admin для инфраструктуры.
6.  **Аудит изменений**: Логируйте все изменения пайплайнов через API.

### Организация

1.  **Используйте CI/CD Catalog**: Для переиспользуемых частей вместо `include:project` (17.3+ GA).
2.  **DAG вместо стадий**: Используйте `needs` для параллелизма и сокращения времени пайплайна.
3.  **Групповые переменные**: Общие секреты выносите на уровень группы.
4.  **GitLab Flow**: Вместо GitFlow для упрощения пайплайнов.
5.  **SemVer для компонентов**: Используйте теги (`v1.2.3`) вместо веток в `include:component`.
6.  **Изоляция окружений**: Staging/production разделены на уровне environments и rules.

### Производительность

1.  **Кэшируйте зависимости**: Настройте `cache:` для Maven, npm, pip.
2.  **Параллельные задачи**: Используйте `needs` для DAG.
3.  **Artifacts cleanup**: Настройте `expire_in` для артефактов.
4.  **Fleeting Runner'ы**: Для автоскейлинга (Kubernetes executor).
5.  **Интерполяция inputs**: Используйте `$[[ inputs.name ]]` вместо глобальных переменных для изоляции.
6.  **Лимит YAML**: Следите за размером `.gitlab-ci.yml` (макс. 2 MB) и количеством `include` (макс. 50).

### SRE/SysAdmin

1.  **Change Management**: Миграцию пайплайнов проводите по change window с approval rules.
2.  **Blast Radius**: Ограничьте параллельный запуск на этапе валидации (resource groups, rate limits).
3.  **Мониторинг**: Отслеживайте длительность пайплайнов, очередь Runner'ов, failed jobs.
4.  **Resource Quotas**: Настройте лимиты на namespace/project (concurrent jobs, artifacts size).
5.  **Runner Pools**: Разделите Runner'ы по executor'ам и тегам для изоляции workloads.
6.  **DR процедуры**: Бэкап `.gitlab-ci.yml` в репозитории; ability to revert commit.

## Особенности и ограничения (Edge Cases)

### Несовместимость

| Аспект | Jenkins | GitHub Actions | GitLab CI |
|:---|:---|:---|:---|
| Conditionals | `when { branch 'main' }` | `if: github.ref == 'refs/heads/main'` | `rules: - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH` |
| Matrix builds | `matrix { axis { ... } }` | `strategy: matrix` | `parallel:matrix` |
| Caching | `cache { paths: [...] }` | `actions/cache@v3` | `cache:` |
| Artifacts | `archiveArtifacts` | `actions/upload-artifact@v3` | `artifacts:` |
| Triggers | `build job:` | `workflow_call` | `trigger:` / parent-child |

### Лимиты

| Параметр | Лимит | Примечание |
|:---|:---|:---|
| Максимум YAML-файлов на пайплайн | 50 | Включая `include` |
| Максимум `spec:inputs` | 50 | На компонент |
| Максимум downstream пайплайнов | 100 | На родительский пайплайн |
| Максимум `needs` | 50 | На задачу |
| Максимум concurrent jobs (Free) | 400 мин | Ограничение по времени |
| Размер артефакта | По умолчанию 100 MB | Настраивается в Admin Area |
| Размер YAML | 2 MB | `max_yaml_size_bytes` |

### Известные ограничения

*   **`include:template` remote templates**: В GitLab 18.0+ remote templates поддерживаются без явного указания версии, но для production рекомендуется фиксировать версии.
*   **Matrix builds**: В GitLab CI нет встроенного аналога Jenkins matrix; используйте `parallel:matrix` с ограничениями.
*   **Scripted Pipeline**: Jenkins Scripted Pipeline (imperative) имеет более гибкий контроль flow; в GitLab CI требуется декларативный подход с `rules`.
*   **Секреты в include**: При использовании `include:component` секреты не передаются автоматически; используйте group-level variables.

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Пайплайн не запускается после миграции | Синтаксическая ошибка в `.gitlab-ci.yml` | `curl /api/v4/ci/lint` или `gitlab-runner exec` | Исправить YAML-синтаксис |
| Артефакты отличаются по размеру | Разные версии инструментов или флаги компиляции | Сравнить `target/*.jar` по SHA256 | Использовать одинаковые Docker-образы |
| `rules` не срабатывает | Неправильное условие или переменная не определена | `echo $CI_COMMIT_BRANCH` в debug-задаче | Проверить pre-defined variables и case-sensitivity |
| Кэш не обновляется | Неправильный `key` или `policy` | Проверить `cache:key` и `policy: pull-push` | Использовать `${CI_COMMIT_REF_SLUG}` или уникальный key |
| Component не найден | Неправильный путь или версия | `gitlab-rake gitlab:ci:lint` | Проверить namespace и SemVer тег |
| Переменная не маскируется | Не указан флаг `masked: true` | Проверить в UI → Settings → CI/CD | Добавить `masked: true` и убедиться, что значение не содержит спецсимволов |
| `spec:inputs` не работает | Устаревшая версия GitLab (<17.11) | `gitlab-rake gitlab:env:info` | Обновить GitLab или использовать `variables:` |
| Runner игнорирует теги | Runner не имеет соответствующего тега | `gitlab-runner list` | Добавить теги в Runner или в job `tags:` |
| Пайплайн падает на `needs` | Cyclic dependency или проект недоступен | Проверить DAG в UI | Исправить циклическую зависимость или добавить `project:` |

## Дополнительная информация

*   **[Основы GitLab CI/CD](./gitlab_ci_basics.md)** — база по стадиям, артефактам, кэшу и Runner'ам.
*   **[CI/CD Catalog Components](../Reusable_Pipelines/ci_cd_catalog_components.md)** — современный стандарт переиспользования.
*   **[GitLab CI: Эволюция переиспользуемого пайплайна](../Reusable_Pipelines/evolution_example.md)** — модель зрелости и TCO-анализ.
*   **[Обновление и обслуживание GitLab](../Advanced/gitlab_upgrades_and_maintenance.md)** — zero-downtime обновления, blue-green, maintenance.
*   **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)** — бэкап, восстановление, мониторинг.
*   **[Миграция GitLab из Docker в кластер](../Tutorials/gitlab_docker_cluster_migration.md)** — инфраструктурная миграция (не пайплайнов).
*   **[CI/CD Platform Comparison](../../ci_cd_platform_comparison.md)** — сравнение GitLab CI, GitHub Actions, Jenkins.
*   **[GitLab Flow](../Tutorials/gitlab_flow.md)** — стратегия ветвления для GitLab.
*   **[GitLab Docs: Migrate to GitLab CI](https://docs.gitlab.com/ee/ci/migration/)** — официальное руководство по миграции.

> **Критичные изменения последних версий:**
>
> *   **19.0**: `spec:inputs` доступен для корневых `.gitlab-ci.yml` (типизированные параметры).
> *   **19.0**: Минимальная версия PostgreSQL повышена до 17. Поддержка Redis 6 удалена; Valkey 7.2+ или Redis 7.2+ обязательны.
> *   **18.0**: CI/CD Catalog Components (GA) — замена `include:project`.
> *   **18.0**: `include:template` поддерживает remote templates без явного указания версии.
> *   **17.11**: `spec:inputs` в корневом `.gitlab-ci.yml` (previously только в компонентах).
> *   **17.3**: CI/CD Catalog Components (GA).
