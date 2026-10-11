# Сравнение CI/CD платформ: GitLab CI vs GitHub Actions vs CircleCI vs Jenkins

**Актуально для:** self-hosted CI/CD (GitLab CE/EE, GitHub Enterprise Server, CircleCI self-hosted, Jenkins) 2024–2026

> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.

## Определения

- **CI/CD платформа** — система автоматизации жизненного цикла разработки, объединяющая сборку, тестирование, безопасность и деплой кода.
- **Downstream pipeline / reusable workflow** — механизм вызова одного пайплайна из другого для декомпозиции конфигурации и переиспользования логики.
- **Trigger / webhook** — событие, инициирующее запуск пайплайна (push, MR, schedule, API, webhook от другого проекта).
- **Workload Identity Federation** — модель аутентификации без статических секретов, использующая кратковременные JWT-токены (OIDC).
- **Matrix Build** — параллельный запуск одной задачи с разными наборами переменных (платформа, версия, окружение).
- **Self-hosted runner** — исполнитель пайплайна, управляемый командой на собственной инфраструктуре, а не на инфраструктуре провайдера.
- **SBOM (Software Bill of Materials)** — инвентаризация компонентов ПО, используемая для безопасности и compliance.

## Основные концепции

### Почему выбор платформы важен для DevOps, SRE и SysAdmin

- **DevOps:** Архитектура платформы определяет скорость доставки и частоту релизов (Deployment Frequency). Встроенные downstream-механизмы и reusable workflows сокращают handoff между стадиями и командами.
- **SRE:** Чётко спроектированная DAG-модель снижает риск каскадных отказов и упрощает расчёт MTTR. Изолированные fan-out-задачи не блокируют критические деплои при падении побочных проверок.
- **SysAdmin:** Архитектура влияет на утилизацию раннеров, планирование дисков/инодов и тепловыделение флота. Глубокие вложенности downstream-пайплайнов создают burst-нагрузку на API и очереди задач.

### Сравнительная таблица: downstream-механизмы

| Возможность | GitLab CI | GitHub Actions | CircleCI | Jenkins |
| :--- | :--- | :--- | :--- | :--- |
| **Native downstream trigger** | `trigger:project`, parent-child | `workflow_call` (reusable workflows) | `trigger` в workflows | `build job:` (Pipeline plugin) |
| **Cross-project trigger** | Да (`trigger:project`) | Да (`workflow_call` между репозиториями) | Да (`trigger` между проектами) | Да (`build` с параметрами) |
| **Глубина вложенности** | 2 уровня через `trigger`; неограниченно через API | 4 уровня reusable workflows | 2 уровня через `trigger` | Ограничена конфигурацией |
| **Стратегии синхронизации** | `mirror`, `depend`, fire-and-forget | `strategy: matrix` (GitHub-hosted) | `snapshot` (legacy) | Нет встроенной стратегии |
| **Типизация входов** | `spec:inputs` (string, number, boolean, array) | `inputs` (string, number, boolean) | `parameters` (string, number, boolean) | `parameters` (строка, Boolean) |
| **Валидация входов** | До создания пайплайна (compile-time) | До запуска reusable workflow | При создании workflow | При загрузке конфигурации |
| **Zero Trust / inbound allowlist** | Inbound Allowlist (17.0+), Fine-grained Permissions (18.3+) | `GITHUB_TOKEN` с ограниченными правами; `permissions` ключ | `api-token` с правами проекта; Context API | Нет встроенной модели; требует ручной настройки RBAC |
| **OIDC / Workload Identity** | `id_tokens` (GitLab 16.0+) | `id_tokens` (GitHub Actions OIDC) | `oidc` context (CircleCI OIDC) | Требует плагинов (Kubernetes, OpenShift) |
| **Артефакты между проектами** | `needs:project`, cross-project artifacts | `needs` с репозиториями, `actions/cache` | `workspaces` (CircleCI), `attach_workspace` | `copyArtifact` plugin, `stash/unstash` |
| **Matrix builds** | `parallel:matrix` | `strategy: matrix` | `matrix` в workflows | `matrix` в Pipeline plugin |
| **Кэширование зависимостей** | `cache` с ключами, S3-compatible backend | `actions/cache`, `actions/setup-node` и аналоги | `save_cache` / `restore_cache` | `cache` directive, S3 backend |
| **Self-hosted runners** | GitLab Runner (Docker, Kubernetes, Shell) | Self-hosted runners (Docker, VM, Kubernetes) | CircleCI Runner (Docker, Kubernetes) | Agent (Kubernetes, Docker, SSH) |
| **Enterprise-фичи** | Pipeline Execution Policies (17.3+), Compliance Pipelines | Environment protection rules, OIDC, CodeQL | Orbs, Context, Namespaces | Plugin ecosystem, Role-Based Strategy |

### Сравнительная таблица: безопасность и compliance

| Возможность | GitLab CI | GitHub Actions | CircleCI | Jenkins |
| :--- | :--- | :--- | :--- | :--- |
| **Встроенное сканирование SAST/DAST** | Да (GitLab Ultimate) | Нет (требуется GitHub Advanced Security) | Нет (требуется third-party) | Нет (требуется плагины) |
| **SBOM генерация** | Да (`artifacts:reports:cyclonedx`) | Да (через actions) | Да (через orbs) | Нет (требуется плагины) |
| **Аудит событий** | Audit Events (Premium/Ultimate) | Audit log (Enterprise) | Audit log (Enterprise) | Основной журнал (не структурирован) |
| **Секрет-менеджер** | GitLab Secrets Manager (19.2+), Vault, id_tokens | GitHub Secrets, OIDC, HashiCorp Vault | CircleCI Context, OIDC, HashiCorp Vault | Credentials plugin, Vault plugin |
| **Ротация секретов** | Встроенная ротация (19.2+) | OIDC (нет статических секретов) | OIDC (нет статических секретов) | Требует внешнего менеджера |
| **Compliance as Code** | Policy-as-Code, Scheduled Execution Policies | Policy as Code (enterprise) | Policy as Code (enterprise) | Compliance plugin |

### Сравнительная таблица: производительность и масштабируемость

| Возможность | GitLab CI | GitHub Actions | CircleCI | Jenkins |
| :--- | :--- | :--- | :--- | :--- |
| **Параллельные задачи (бесплатно)** | 400 мин (Free) / ∞ (Premium) | 2000 мин (Free) / ∞ (Pro) | 6000 кредитов (Free) | Ограничено ресурсами инстанса |
| **Self-hosted execution** | GitLab Runner (Docker, K8s, Shell) | Self-hosted runners | CircleCI Runner (Docker, K8s) | Agent (K8s, Docker, SSH) |
| **Автомасштабирование runners** | Docker Machine, K8s executor | Автомасштабирование (GitHub-hosted / self-hosted) | CircleCI Runner autoscaling | Kubernetes plugin, Swarm plugin |
| **Кэширование артефактов** | S3, GCS, Azure, MinIO, Ceph | Локальный кэш runner'а, S3 | Workspace caching, S3 | Сторонние плагины (S3, GCS) |
| **Мониторинг метрик** | Prometheus metrics (встроенный) | GitHub-native metrics, Insights | CircleCI Insights | Prometheus plugin, Grafana |

### Сравнительная таблица: экосистема и интеграции

| Возможность | GitLab CI | GitHub Actions | CircleCI | Jenkins |
| :--- | :--- | :--- | :--- | :--- |
| **Marketplace / Catalog** | CI/CD Catalog (компоненты) | GitHub Marketplace (actions) | CircleCI Orbs | Plugin Center (2000+ плагинов) |
| **Количество интеграций** | ~100 встроенных + Catalog | ~10000+ actions | ~200 orbs | ~2000 плагинов |
| **Kubernetes интеграция** | Встроенная (Auto DevOps, Review Apps) | Встроенная (actions/deploy) | Оркестрация через orbs | Kubernetes plugin, OpenShift |
| **Terraform / IaC** | Встроенные отчёты (`reports:terraform`) | actions/terraform | Orbs для Terraform | Terraform plugin |
| **Архитектурные паттерны** | Parent-Child, Multi-project, Dynamic Generation | Reusable workflows, Monorepo actions | Workflows, Reusable commands | Pipeline as Code, Shared Libraries |

## Предпосылки

- **Инфраструктура:** Self-hosted CI/CD-сервер (GitLab CE/EE, GitHub Enterprise Server, Jenkins) с выделенными раннерами. CircleCI self-hosted требует отдельного оркестратора.
- **Сеть:** Доступность API CI-сервера, registry и хранилищ артефактов внутри ЦОДа без зависимостей от внешних облачных провайдеров.
- **Раннеры:** Достаточный пул исполнителей с поддержкой требуемых executors (Docker, Kubernetes, shell, Windows). Для Jenkins — Java 11+ на контроллере.
- **Безопасность:** RBAC настроен; секреты хранятся в менеджере секретов (Vault), OIDC доверие установлено.
- **Мониторинг:** Метрики пайплайнов экспортируются в Prometheus; алерты настроены на деградацию очередей и рост MTTR.
- **Документация:** Runbook'ы и escalation matrix утверждены для каждой платформы.

## Практические сценарии

### Сценарий 1: Базовая конфигурация пайплайна

#### GitLab CI (.gitlab-ci.yml)
```yaml
stages:
  - lint
  - test
  - build
  - deploy

lint:
  stage: lint
  image: python:3.13-slim
  script: [flake8 src/]

test:
  stage: test
  image: python:3.13-slim
  script: [pytest tests/]

build:
  stage: build
  image: docker:24
  script: [docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .]

deploy:
  stage: deploy
  script: [./deploy.sh]
```

#### GitHub Actions (.github/workflows/ci.yml)
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - run: flake8 src/

  test:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/

  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t ${{ github.repository }}:${{ github.sha }} .
```

#### Jenkins (Jenkinsfile)
```groovy
pipeline {
  agent any
  stages {
    stage('Lint') {
      agent { docker { image 'python:3.13-slim' } }
      steps { sh 'flake8 src/' }
    }
    stage('Test') {
      agent { docker { image 'python:3.13-slim' } }
      steps { sh 'pytest tests/' }
    }
    stage('Build') {
      agent { docker { image 'docker:24' } }
      steps { sh 'docker build -t $IMAGE:$GIT_COMMIT .' }
    }
    stage('Deploy') {
      steps { sh './deploy.sh' }
    }
  }
}
```

#### CircleCI (.circleci/config.yml)
```yaml
version: 2.1
jobs:
  lint:
    docker:
      - image: python:3.13-slim
    steps: [run: flake8 src/]
  test:
    docker:
      - image: python:3.13-slim
    steps: [run: pytest tests/]
  build:
    docker:
      - image: docker:24
    steps: [run: docker build -t $CIRCLE_PROJECT_REPONAME:$CIRCLE_SHA1 .]
workflows:
  ci:
    jobs: [lint, test, build]
```

### Сценарий 2: Выбор платформы для микросервисной архитектуры

**Критерии выбора:**
- **GitLab CI:** Если команда уже использует GitLab для репозиториев, требует встроенной безопасности (SAST/DAST/SBOM) и Zero Trust модели.
- **GitHub Actions:** Если репозитории на GitHub, нужен доступ к largest marketplace actions и GitHub Advanced Security.
- **CircleCI:** Если требуется простая конфигурация и fast feedback для фронтенд-проектов.
- **Jenkins:** Если нужна максимальная гибкость, legacy-поддержка или сложные кастомные пайплайны.

### Сценарий 3: Сравнение downstream-триггеров для monorepo

| Платформа | Механизм | Ограничения | Рекомендация |
| :--- | :--- | :--- | :--- |
| **GitLab CI** | Parent-Child с `rules:changes` | 2 уровня вложенности | Для large monorepos с 10+ сервисами |
| **GitHub Actions** | Reusable workflows с `if: always()` | 4 уровня вложенности | Для средних monorepos |
| **CircleCI** | Dynamic config + `trigger` | 2 уровня вложенности | Для простых monorepos |
| **Jenkins** | Multibranch + `build` job | Нет встроенного лимита | Для legacy monorepos с кастомной логикой |

### Сценарий 4: Миграция с Jenkins на GitLab CI

**Основные отличия:**
- Jenkins: Groovy-скрипты, Shared Libraries, multibranch pipelines
- GitLab CI: YAML-конфигурация, CI/CD Catalog компоненты, `spec:inputs`

**Миграционные шаги:**
1. Инвентаризация существующих Jenkins пайплайнов.
2. Выделение общих паттернов (build, test, deploy) в GitLab CI компоненты.
3. Постепенная миграция по группам сервисов (canary подход).
4. Настройка реестра мигрированных пайплайнов.

## Ограничения и крайние случаи

- **Глубина вложенности:** GitLab CI ограничивает 2 уровня `trigger`. Для большей глубины используйте API-оркестратор.
- **Cyclic dependencies:** A → B → A через триггеры вызывает deadlock. Избегайте циклов.
- **Rate limiting:** Массовый fan-out (>20 downstream) вызывает 429. Используйте throttling.
- **Artifact size:** Большие артефакты (>100MB) между downstream-пайплайнами вызывают таймауты. Используйте registry.
- **Cache poisoning:** Общий кэш между проектами — поверхность атаки. Изолируйте кэш.
- **Cold start:** Эфемерные раннеры добавляют латентность. Используйте warm pools для latency-чувствительных пайплайнов.
- **Platform lock-in:** Глубокие platform-specific директивы усложняют перенос пайплайнов. Выносите общую логику в переиспользуемые компоненты.
- **Jenkins plugin compatibility:** При обновлении Jenkins проверяйте совместимость плагинов; не все поддерживают новые версии Pipeline plugin.
- **CircleCI credit exhaustion:** При исчерпании бесплатных кредитов пайплайны останавливаются. Мониторьте usage в Insights.
- **GitHub Actions runner queue:** При превышении лимита параллельных jobs на self-hosted runners задания становятся `queued`. Увеличьте пул или используйте `concurrency` для ограничения.

## Валидация и проверка

### Ожидаемые результаты

**GitLab CI:**
- `pipeline succeeded` → все задачи завершены успешно.
- `passed` / `failed` / `canceled` статусы задач в UI.

**GitHub Actions:**
- `All checks passed` → пайплайн завершён успешно.
- `completed` / `failure` / `cancelled` статусы в Actions tab.

**Jenkins:**
- `Success` / `Failure` / `Aborted` в Blue Ocean или Classic UI.
- `SUCCESS` / `FAILURE` / `ABORTED` в `currentBuild.result`.

**CircleCI:**
- `Success` / `Failed` / `Canceled` в workflows tab.
- `held` статус при approval-этапах.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Downstream не запускается** | Не настроен inbound allowlist (GitLab) или permissions (GitHub) | Проверьте настройки доступа в целевом проекте. |
| **Входные параметры не передаются** | Несоответствие типов или имен параметров | Сравните `spec:inputs` / `inputs` / `parameters` между upstream и downstream. |
| **Массовый 429** | Превышен rate limit при fan-out | Используйте exponential backoff, уменьшите burst, добавьте задержки. |
| **Вложенность превышена** | Попытка запустить 3-й уровень через native trigger | Используйте API-оркестратор или перепроектируйте архитектуру. |
| **Циклические зависимости** | A → B → A через триггеры | Используйте реестр триггеров и избегайте циклов. |
| **Runner не подключается** | Неверный токен регистрации или сетевые ограничения | Проверьте `runner registration token`, firewall rules, DNS. |
| **Пайплайн зависает в pending** | Недостаточно раннеров с нужным тегом | Проверьте теги runner'ов и concurrency limits. |
| **Артефакт не передаётся между стадиями** | `dependencies` не указан или артефакт удалён retention-политикой | Проверьте `dependencies` и настройки retention артефактов. |
| **OIDC не работает** | OIDC endpoint недоступен из runner'а | Проверьте сетевую доступность `/.well-known/openid-configuration` CI-сервера. |
| **Matrix build создаёт слишком много задач** | Неограниченная комбинация платформ/версий | Ограничьте `matrix` через `exclude`, используйте `rules`. |

## Лучшие практики

### Выбор платформы

1. **Используйте одну платформу для всех проектов:** Не смешивайте GitLab CI, GitHub Actions и Jenkins в одной организации без явной необходимости.
2. **Оцените total cost of ownership:** Учитывайте не только цену лицензии, но и стоимость поддержки runners, интеграций, обучения команды.
3. **Проверьте enterprise-требования:** SAST/DAST, compliance reporting, audit logs — часто определяют выбор платформы.

### Переносимый дизайн пайплайнов

1. **Используйте declarative конфигурацию:** YAML (GitLab, GitHub, CircleCI) или Groovy (Jenkins) — избегайте imperative-скриптов где возможно.
2. **Выделяйте общую логику в библиотеки:** GitLab CI Catalog components, GitHub Actions composite actions, CircleCI Orbs, Jenkins Shared Libraries.
3. **Типизируйте входы:** `spec:inputs`, `inputs`, `parameters` — предотвращают ошибки при вызове downstream.
4. **Версионируйте шаблоны:** Используйте теги SemVer или commit SHA в `ref` для включения общих шаблонов.

### Безопасность

1. **OIDC вместо статических секретов:** Все платформы поддерживают Workload Identity Federation. Используйте её для доступа к Vault, реестрам, локальным сервисам.
2. **Least Privilege:** Минимальные права для `GITHUB_TOKEN`, `CI_JOB_TOKEN`, Project Access Token.
3. **Аудит:** Включите audit log на уровне инстанса для отслеживания запусков пайплайнов и изменений конфигурации.

### Cleanup и retention

1. **Артефакты:** Настраивайте retention-политики для артефактов (GitLab: `expire_in`, GitHub: `actions/cache` retention, Jenkins: `logRotator`).
2. **Registry GC:** Планируйте garbage collection для container registry (Harbor, Nexus, GitLab Registry).
3. **Эфемерные окружения:** Используйте `stop_review` и `auto_stop_in` для Review Apps.
4. **Кэш:** Очищайте устаревшие кэши; используйте scoped ключи для изоляции.

## Дополнительная информация

### См. также

- **[Архитектура пайплайнов](./Core_Concepts/pipeline_architecture.md)** — паттерны DAG, fan-out/fan-in, matrix builds.
- **[Глоссарий пайплайнов](./Core_Concepts/pipeline_glossary.md)** — термины и определения.
- **[DAG с needs](./GitLab_CI/Advanced/workflow_rules/dag_with_needs.md)** — глубинное погружение в графы зависимостей GitLab CI.
- **[Downstream Pipelines](./GitLab_CI/Advanced/Downstream_Pipelines/strategies.md)** — стратегии кросс-проектных пайплайнов.
- **[Миграция в GitLab CI](./GitLab_CI/Concepts/gitlab_ci_migration.md)** — перенос пайплайнов из Jenkins и GitHub Actions.
- **[CI/CD Catalog компоненты](./GitLab_CI/Reusable_Pipelines/ci_cd_catalog_components.md)** — современный стандарт переиспользования.
- **[Обзор CI/CD](./ci_cd_overview.md)** — базовые концепции и компоненты.
- **[Анти-паттерны CI/CD](./ci_cd_antipatterns.md)** — типичные ошибки и способы их избежать.
- **[Управление артефактами](./artifact_management.md)** — стратегии хранения и retention.
- **[Сборка в монорепозиториях](./Build_Systems/monorepo_build_systems.md)** — инкрементальные сборки и DAG.

### Рекомендованные ссылки

- **[GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)** — официальная документация.
- **[GitHub Actions Documentation](https://docs.github.com/en/actions)** — reusable workflows, OIDC, self-hosted runners.
- **[CircleCI Documentation](https://circleci.com/docs/)** — workflows, orbs, performance insights.
- **[Jenkins Documentation](https://www.jenkins.io/doc/)** — Pipeline plugin, Shared Libraries.

### Миграционные руководства

- **Jenkins → GitLab CI:** [GitLab Migration Guide](https://docs.gitlab.com/ee/ci/migration/)
- **Jenkins → GitHub Actions:** [GitHub Actions Migration Guide](https://docs.github.com/en/actions/migration/quickstart-for-migrating-from-jenkins-to-github-actions)
- **CircleCI → GitLab CI:** Нет официального руководства; используйте comparative таблицы выше.
