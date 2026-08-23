# Специальные директории платформ — Git Forge Directories

## Определения

**Специальные директории платформ (Forge-specific directories)** — зарезервированные системные папки в корне репозитория (например, `.github/`, `.gitlab/`, `.bitbucket/`), используемые Git-хостингами для реализации подхода **Configuration as Code**. Они содержат метаданные, конфигурации автоматизации (CI/CD), шаблоны взаимодействия и политики безопасности, которые интерпретируются платформой автоматически при каждом событии (push, PR, issue creation).

**Configuration as Code (CaC)** — практика управления конфигурацией инфраструктуры и платформ через файлы в репозитории, а не через веб-интерфейс. В контексте forges это означает версионность настроек CI/CD, шаблонов и политик наравне с исходным кодом.

**Git Forge (Кузница)** — веб-платформа для хостинга Git-репозиториев, дополняющая базовый протокол Git инструментами совместной разработки (Pull/Merge Requests, CI/CD, Issue Tracking, Code Review).

**Platform Metadata** — служебные файлы и директории, которые не являются частью бизнес-логики приложения, но управляют поведением платформы относительно репозитория.

**Forge-Specific Workflow** — автоматизированный процесс, описанный в YAML/JSON/MD-файлах внутри специальной директории, который выполняется платформой без участия разработчика (например, линтинг при каждом push, авто-merge при получении апрува).

**Децентрализованный forge** — платформа, поддерживающая федерацию через протокол **ActivityPub** (ForgeFed), что позволяет репозиториям на разных инстансах взаимодействовать между собой ( Issues, PR, Follow ) без центрального координатора.

---

## Базовые концепции

### Назначение и иерархия

Использование специализированных директорий позволяет отделить технические конфигурации платформы от основного исходного кода, сохраняя при этом версионность настроек и возможность code review для инфраструктурных изменений.

**Основные задачи:**
- **Автоматизация (Workflow):** Описание конвейеров сборки, тестирования и развертывания.
- **Интерфейсные формы:** Стандартизация ввода данных пользователями через шаблоны issues и PR.
- **Governance:** Управление правилами ревью кода, CODEOWNERS, политиками безопасности.
- **Documentation Fallback:** Хранение служебных MD-файлов (README, SECURITY, CONTRIBUTING), если они отсутствуют в корне.
- **Dependency Management:** Автоматическое обновление зависимостей (Dependabot, Renovate).
- **Funding:** Спонсорские кнопки и информация о поддержке проекта.

### Механизм разрешения конфликтов и приоритеты

Когда платформа ищет конфигурационный файл, она обычно проверяет несколько locations в строгом порядке:

1. **Корень репозитория (`/`)** — наивысший приоритет для глобальных файлов (`README.md`, `CONTRIBUTING.md`, `LICENSE`).
2. **Специальная директория (`.github/`, `.gitlab/`)** — для служебных файлов платформы.
3. **Другие locations** (например, `.github/ISSUE_TEMPLATE/` vs корневой `ISSUE_TEMPLATE/`) — платформы имеют собственную логику fallback.

**Важно:** Если один и тот же файл существует в корне и в специальной директории, платформа может:
- Использовать корневой файл (игнорируя директорию).
- Объединять их (например, `CODEOWNERS` в корне + в `.github/`).
- Выдавать предупреждение или ошибку о дублировании.

### Взаимодействие с механизмами Git

Forge-specific директории не существуют в изоляции. Они взаимодействуют с ядром Git:

- **`.gitattributes`** может управлять атрибутами файлов внутри `.github/workflows/` (например, `*.yml linguist-language=YAML` или `*.json filter=lfs` для больших артефактов).
- **Git Hooks** не влияют на интерпретацию forge-директорий платформой (платформа работает на сервере), но клиентские хуки могут валидировать YAML-файлы перед push (`pre-commit` с `actionlint`, `gitlab-ci-lint`).
- **LFS (Large File Storage)** рекомендуется для артефактов CI (>100 MB), которые хранятся в `.github/` или `.gitlab/`.
- **Submodules** могут включать шаблоны или общие библиотеки workflows из других репозиториев.
- **Sparse-Checkout** позволяет клонировать только конфигурационные файлы без полного исходного кода для быстрого аудита.

### Децентрализованные forges (ForgeFed)

С развитием федеративных протоколов emerged класс forges, не зависящих от единого центра:

| Платформа | Протокол федерации | Особенности |
| :--- | :--- | :--- |
| **Forgejo** | ActivityPub (ForgeFed) | Полная совместимость с GitHub API, federation Issues/PR |
| **Gitea** | ActivityPub (опционально) | Легковесная альтернатива GitLab, встроенная federation |
| **Gogs** | Нет | Простейшая self-hosted платформа, без federation |
| **SourceHut** | Email-based | Минималистичный подход, без JavaScript, federation через email |

**ForgeFed** — расширение ActivityPub, стандартизирующее vocabulary для forge-объектов (Repository, Issue, PullRequest, Comment). Позволяет пользователю с аккаунтом на instance A комментировать issue на instance B, если оба инстанса поддерживают стандарт.

### Self-hosted решения

Корпоративные и приватные инсталляции делятся на:

- **Универсальные:** GitLab CE/EE, Gitea/Forgejo, Gogs.
- **Специализированные:** Bitbucket Data Center ( enterprise), Azure DevOps Server.
- **Минималистичные:** Gitolite (управление доступом) + gitlist (веб-интерфейс) + собственная CI.
- **Managed:** GitHub Enterprise, GitLab.com SaaS, Bitbucket Cloud.

### Безопасность

Forge-директории часто становятся целью атак, так как выполняют код в CI/CD:

- **Секреты в репозитории:** Никогда не коммитьте токены в `.github/workflows/` или `.gitlab-ci.yml`. Используйте платформенные секреты (`${{ secrets.GITHUB_TOKEN }}`, `$CI_JOB_TOKEN`).
- **CODEOWNERS и защита веток:** Ограничивайте, кто может изменять файлы в `.github/` или `.gitlab/`.
- **Third-party Actions:** Используйте `@v4` вместо веток, проверяйте SHA-хеши действий.
- **Branch Protection:** Ветка `main` должна требовать review для изменений в forge-директориях.
- **Audit Log:** Все изменения в конфигурациях логируются платформой.

### Сводная таблица по платформам

| Платформа | Основная директория | CI/CD конфигурация | Форматы форм | Federation | Локализация | Enterprise-функции |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **GitHub** | `.github/` | `.github/workflows/` | YAML (Forms), Markdown | Нет (закрытый) | 12+ языков | GitHub Enterprise, Advanced Security |
| **GitLab** | `.gitlab/` | `.gitlab-ci.yml` (корень) | Markdown, веб-интерфейс | Нет | 15+ языков | GitLab EE, Geo, Kubernetes Agent |
| **Bitbucket** | `.bitbucket/` | `bitbucket-pipelines.yml` | Markdown | Нет | 6+ языков | Bitbucket Data Center, Pipelines |
| **Gitea / Forgejo** | `.gitea/` / `.forgejo/` | `.gitea/workflows/` | Markdown | ActivityPub | 30+ языков | Gitea Enterprise |
| **Azure DevOps** | `.azure-devops/` | `azure-pipelines.yml` | Markdown | Нет | 15+ языков | Azure DevOps Server |
| **Woodpecker** | `.woodpecker/` | `.woodpecker/*.yml` | Нет | Нет | EN | Self-hosted, Kubernetes-native |

### Состав директории .github (GitHub)

- `workflows/` — YAML-файлы GitHub Actions.
- `ISSUE_TEMPLATE/` — шаблоны задач. Поддерживаются Markdown и YAML-формы (`.yml`).
- `DISCUSSION_TEMPLATE/` — шаблоны категорий обсуждений (только YAML).
- `PULL_REQUEST_TEMPLATE/` — директория или файл для шаблона PR.
- `actions/` — локальные Actions репозитория (dockerfile, action.yml).
- `CODEOWNERS` — правила назначения ревьюеров.
- `dependabot.yml` — конфигурация обновления зависимостей (npm, pip, docker, github-actions).
- `renovate.json` — альтернатива Dependabot (может быть в корне).
- `FUNDING.yml` — кнопки спонсирования (GitHub Sponsors, Patreon, Ko-fi).
- `SECURITY.md` — политика сообщения об уязвимостях.
- `CONTRIBUTING.md` — правила внесения вклада.
- `stale.yml` — конфигурация GitHub Stale бота.
- `dependabot/` — альтернативная директория для конфигураций Dependabot (>= v2).
- `workflow-templates/` — шаблоны workflows для предложения контрибьюторам через "Use this template".

### Состав директории .gitlab (GitLab)

- `issue_templates/` — шаблоны для задач (Issues).
- `merge_request_templates/` — шаблоны для Merge Requests.
- `agents/` — конфигурация **GitLab Agent for Kubernetes** (структура: `agents/<name>/config.yaml`).
- `CODEOWNERS` — правила владельцев кода (также может быть в корне).
- `route-map.yml` — соответствие путей файлов URL-адресам для Review Apps.
- `include/` — локальные include-шаблоны для `.gitlab-ci.yml`.
- `settings/` — специфичные настройки проекта (например, `settings/lfs_locks.yml`).
- `licenses/` — лицензии для License Management.
- `templates/` — шаблоны для CI/CD (Deprecated: лучше использовать include-проекты).

### Состав директории .bitbucket (Bitbucket)

- `pull_request_template.md` — основной шаблон PR.
- `pull_request_templates/` — поддержка множественных шаблонов (Bitbucket Data Center).
- `CODEOWNERS` — управление ревьюерами (рекомендуемое место).
- `branch_restrictions.yml` — ограничения на ветки (кто может push).
- `pipelines/` — локальные шаблоны и snippets для `bitbucket-pipelines.yml`.
- `downloads/` — файлы для раздела Downloads репозитория.

### Состав директории .gitea / .forgejo (Gitea / Forgejo)

- `workflows/` — YAML-файлы, совместимые с GitHub Actions синтаксисом.
- `actions/` — локальные Actions.
- `ISSUE_TEMPLATE/` — шаблоны задач (Markdown и YAML).
- `PULL_REQUEST_TEMPLATE/` — шаблоны PR.
- `CODEOWNERS` — правила назначения ревьюеров.
- `linters/` — конфигурация встроенных линтеров (Markdown, JSON).

### Состав директории .woodpecker (Woodpecker CI)

- `*.yml` — пайплайны (например, `deploy.yml`, `test.yml`).
- `plugins/` — кастомные плагины пайплайнов.
- `secrets/` — секреты (чаще управляются через веб-интерфейс, но файлы поддерживаются в self-hosted).

### Состав директории .azure-devops (Azure DevOps)

- `pipelines/` — YAML-пайплайны.
- `environments/` — дефиниции окружений.
- `library/` — variable groups и общие шаблоны.

---

## Практические сценарии

### Сценарий 1: Создание современной формы GitHub Issue (YAML)

В отличие от Markdown, YAML-формы позволяют создавать структурированные поля с валидацией.
Файл: `.github/ISSUE_TEMPLATE/bug-report.yml`

```yaml
name: Bug Report
description: Сообщить об ошибке в работе приложения
body:
  - type: markdown
    attributes:
      value: |
        Спасибо за сообщение об ошибке!
  - type: input
    id: version
    attributes:
      label: Версия приложения
      placeholder: "v1.2.3"
    validations:
      required: true
  - type: dropdown
    id: os
    attributes:
      label: Операционная система
      options:
        - Linux
        - macOS
        - Windows
  - type: textarea
    id: reproduction
    attributes:
      label: Шаги воспроизведения
      description: Как мы можем увидеть проблему?
    validations:
      required: true
```

### Сценарий 2: Конфигурация GitLab Agent for Kubernetes

Для работы агента необходимо создать файл конфигурации в строго определенной директории.
Файл: `.gitlab/agents/prod-cluster/config.yaml`

```yaml
# Настройка Pull-based GitOps
gitops:
  manifest_projects:
    - id: group/manifest-repo
      paths:
        - glob: '/**/*.yaml'

# Разрешение CI/CD доступа из других проектов
ci_access:
  projects:
    - id: group/application-repo
```

### Сценарий 3: Настройка CODEOWNERS для Bitbucket

Автоматическое добавление команд в ревьюеры на основе путей.
Файл: `.bitbucket/CODEOWNERS`

```text
# Все изменения инфраструктуры требуют одобрения DevOps-команды
/terraform/ @devops_team

# Изменения в документации могут проверять техписатели
/docs/*.md @tech_writers

# Глобальный владелец для остальных файлов
* @platform_leads
```

### Сценарий 4: Автоматическое обновление зависимостей (GitHub Dependabot)

Dependabot автоматически создает PR с обновлениями зависимостей.
Файл: `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    reviewers:
      - "frontend-team"
    assignees:
      - "dependabot-manager"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Сценарий 5: Альтернативный менеджер зависимостей (Renovate)

Renovate поддерживает больше ecosystems, чем Dependabot, и предлагает более гибкую конфигурацию.
Файл: `.github/renovate.json`

```json
{
  "extends": ["config:base"],
  "packageRules": [
    {
      "matchUpdateTypes": ["minor", "patch"],
      "automerge": true,
      "automergeType": "branch"
    },
    {
      "matchPackageNames": ["@types/node"],
      "groupName": "Node.js types"
    }
  ],
  "schedule": ["before 3am on monday"],
  "timezone": "Europe/Moscow"
}
```

### Сценарий 6: Локальные Actions в репозитории (GitHub)

Позволяют инкапсулировать повторяемую логику без публикации в Marketplace.
Файл: `.github/actions/setup-node/action.yml`

```yaml
name: "Setup Node with Cache"
description: "Установка Node.js с кэшированием npm"
inputs:
  node-version:
    required: true
    default: "20.x"
runs:
  using: "composite"
  steps:
    - uses: actions/setup-node@v4
      with:
        node-version: ${{ inputs.node-version }}
        cache: "npm"
    - run: npm ci
      shell: bash
```

Использование в workflow:
```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/setup-node
        with:
          node-version: "20.x"
```

### Сценарий 7: Multi-platform monorepo (GitHub + GitLab)

В крупных организациях репозиторий может быть зеркалирован между GitHub и GitLab. Для совместимости создают обе директории:

```
repo/
├── .github/
│   └── workflows/
│       └── ci.yml          # GitHub Actions
├── .gitlab/
│   └── agents/
│       └── k8s-agent/
│           └── config.yaml # GitLab K8s Agent
└── src/
```

**Важно:** Не дублируйте одну и ту же логику в `.github/workflows/` и `.gitlab-ci.yml`. Используйте общий скрипт в `scripts/` и вызывайте его из обеих платформ.

### Сценарий 8: Migration GitHub → GitLab (перенос конфигураций)

При миграции платформы требуется перенести CI/CD конфигурации:

1. `.github/workflows/*.yml` → `.gitlab-ci.yml` (или `.gitlab/ci/`).
2. `ISSUE_TEMPLATE/` → `issue_templates/` (формат сохраняется).
3. `PULL_REQUEST_TEMPLATE/` → `merge_request_templates/`.
4. `CODEOWNERS` остается на месте (GitLab также поддерживает).
5. `dependabot.yml` → GitLab Dependency Scanning (встроенный) или Renovate.
6. `FUNDING.yml` → `.gitlab/funding.yml` (не поддерживается на уровне UI, но файл сохраняется).

### Сценарий 9: Self-hosted Gitea с собственным CI

Минимальная конфигурация для Gitea + Woodpecker:

```yaml
# .woodpecker/deploy.yml
steps:
  build:
    image: node:20
    commands:
      - npm ci
      - npm run build

  deploy:
    image: alpine
    commands:
      - scp dist/ user@server:/var/www/html/
    when:
      branch: [main]
```

Конфигурация Woodpecker происходит через веб-интерфейс или переменные окружения, а не через файлы в репозитории (в отличие от GitHub/GitLab).

### Сценарий 10: Bitbucket Pipelines — базовая структура

Файл: `bitbucket-pipelines.yml` (в корне, так как Bitbucket не использует отдельную директорию по умолчанию).

```yaml
image: node:20

pipelines:
  default:
    - step:
        name: "Test"
        script:
          - npm ci
          - npm test

  branches:
    main:
      - step:
          name: "Deploy to Production"
          deployment: "production"
          script:
            - npm run build
            - pipe: atlassian/aws-s3-deploy:1.2.0
              variables:
                AWS_ACCESS_KEY_ID: $AWS_ACCESS_KEY_ID
                AWS_SECRET_ACCESS_KEY: $AWS_SECRET_ACCESS_KEY
                S3_BUCKET: "my-app-prod"
                LOCAL_PATH: "dist"
```

### Сценарий 11: GitLab — include-шаблоны и Review Apps

Централизация CI/CD через include из отдельного репозитория:

```yaml
# .gitlab-ci.yml
include:
  - project: 'group/ci-templates'
    ref: v1.2.0
    file: '/templates/nodejs.yml'

review_apps:
  stage: deploy
  script:
    - kubectl apply -f k8s/overlays/review-$CI_COMMIT_REF_SLUG
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.example.com
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 12: Security policies в GitHub

Множественные политики безопасности в `.github/`:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10

# .github/codeql/codeql-config.yml
name: "Default"
queries:
  - uses: security-and-quality
paths:
  - src/

# SECURITY.md (в корне или .github/)
## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Email security@example.com with details.
```

### Сценарий 13: Template inheritance и формы (GitHub)

Можно комбинировать Markdown и YAML-формы в одном шаблоне:

```markdown
<!-- .github/ISSUE_TEMPLATE/feature_request.md -->
---
name: Feature Request
about: Предложить новую функциональность
title: '[FEATURE] '
labels: 'enhancement'
assignees: ''

---

**Что вы хотите реализовать?**
<!-- Краткое описание -->

```yaml
# Дополнительная YAML-форма (если поддерживается плагином)
priority: P1
effort: M
```
```

### Сценарий 14: Troubleshooting — CI не запускается

**Симптом:** Пайплайн не запускается после push в `.github/workflows/`.

**Диагностика:**
```bash
# 1. Проверить синтаксис YAML
cat .github/workflows/ci.yml | python3 -c "import yaml, sys; yaml.safe_load(sys.stdin)"

# 2. Проверить, что файл имеет корректное расширение
ls -la .github/workflows/

# 3. Проверить webhook (GitHub)
# Settings → Webhooks → Recent Deliveries

# 4. Проверить фильтры (paths, branches)
grep -r "on:" .github/workflows/
```

**Частые причины:**
- Отсутствует триггер `on: push` или `on: pull_request`.
- Неверный `paths` фильтр (файл workflow исключен из изменений).
- Организация отключила Actions в настройках.
- Dependabot коммит помечен как `[skip ci]`.

### Сценарий 15: Troubleshooting — дублирование конфигураций

**Симптом:** Один и тот же workflow запускается дважды или конфликтуют `CODEOWNERS` в корне и в `.github/`.

**Решение:**
```bash
# Найти все CODEOWNERS
find . -name "CODEOWNERS" -o -name "OWNERS"

# Найти дублирующиеся workflow names
grep -r "name:" .github/workflows/ | sort | uniq -d
```

**Best Practice:** Храните только одну копию конфигурации. Если нужен fallback — используйте симлинки или includes.

---

## Дополнительная информация

### Приоритет поиска служебных файлов

Если файл (например, `README.md` или `CONTRIBUTING.md`) существует в нескольких местах, платформы обычно применяют следующий приоритет:
1. **Корень репозитория (`/`)** — наивысший приоритет, рекомендуется для основных файлов.
2. **Папка `docs/`** — для объемной документации.
3. **Спец. папка (`.github/`, `.gitlab/`)** — для "скрытия" служебных файлов из корня.

### Ограничения и особенности

1. **Размер файлов:** Некоторые платформы ограничивают размер отдельных файлов в директориях (например, GitHub Actions YAML ≤ 1 MB).
2. **Лимиты concurrent jobs:** На бесплатных тарифах количество параллельных пайплайнов ограничено (GitHub: 20 concurrent jobs для публичных репозиториев).
3. **Версионирование:** Платформы не версионируют конфигурации внутри `.github/` самостоятельно; версионность обеспечивается Git.
4. **Совместимость форматов:** GitHub Actions YAML не совместим с GitLab CI YAML один-в-один; требуется миграция синтаксиса.
5. **Кэширование:** Платформы кэшируют результаты выполнения пайплайнов; изменения в `.github/workflows/` не всегда вызывают немедленный инвалидацию кэша.
6. **Self-hosted ограничения:** Gitea и GitLab CE имеют ограниченный набор функций по сравнению с облачными SaaS.
7. **Federation:** ForgeFed все еще на ранней стадии; не все forges поддерживают полный набор функций (PR, Reviews, Actions).
8. **Секреты и шифрование:** Файлы в forge-директориях не шифруются; секреты хранятся отдельно в менеджере секретов платформы.

### Best Practices

1. **Одна платформа — один SSoT:** Не пытайтесь поддерживать полную паральность GitHub и GitLab конфигураций; выберите основную платформу.
2. **Валидация перед push:** Используйте `actionlint`, `gitlab-ci-lint`, `bitbucket-pipelines` в pre-commit хуках.
3. **Семантическое именование файлов:** Используйте описательные имена (`ci.yml`, `deploy-prod.yml`, `test-unit.yml`), а не `1.yml`, `2.yml`.
4. **Секреты никогда в коде:** Используйте `${{ secrets.NAME }}` и `$CI_VARIABLE`, а не hardcoded значения.
5. **Минимизация scope секретов:** Разделяйте секреты по окружениям (dev, staging, prod).
6. **Branch Protection:** Защищайте ветки от прямых пушей в конфигурационные файлы.
7. **Документация:** В каждом workflow добавляйте `name:` и `description:` для читаемости в UI.
8. **Атомарность:** Один файл — одна ответственность. Не смешиваете deploy, test и lint в одном `ci.yml`.
9. **Reusable workflows:** Используйте `uses:` в GitHub Actions и `include:` в GitLab CI для избежания дублирования.
10. **Аудит:** Периодически пересматривайте конфигурации на предмет устаревших Actions и неиспользуемых секретов.

### Безопасность и политики

Файлы политик помогают поддерживать порядок в open-source и корпоративных проектах:
- **SECURITY.md**: Описывает процесс сообщения об уязвимостям (Vulnerability Disclosure Policy).
- **SUPPORT.md**: Куда обращаться за помощью.
- **CONTRIBUTING.md**: Правила внесения вклада в проект.
- **CODE_OF_CONDUCT.md**: Правила поведения в сообществе.
- **GOVERNANCE.md**: Процессы принятия решений в проекте (для крупных open-source).

### Официальные ресурсы

- **GitHub:** [docs.github.com/en/get-started/](https://docs.github.com/en/get-started/)
- **GitLab:** [docs.gitlab.com/ee/ci/](https://docs.gitlab.com/ee/ci/)
- **Bitbucket:** [support.atlassian.com/bitbucket-cloud/](https://support.atlassian.com/bitbucket-cloud/)
- **Gitea:** [docs.gitea.com/next/](https://docs.gitea.com/next/)
- **Woodpecker:** [woodpecker-ci.org/docs/](https://woodpecker-ci.org/docs/)
- **ForgeFed:** [codeberg.org/forgejo/forgejo/forge-fed](https://codeberg.org/forgejo/forgejo/forge-fed)

### См. также

- [Обзор специальных файлов Git](./git_special_files_overview.md) — `.gitignore`, `.gitattributes`.
- [GitHub Actions — синтаксис рабочих потоков](../Github_CI/Workflow_Syntax.md)
- [GitLab CI/CD — основы конфигурации](../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)
- [Интеграция GitLab с Kubernetes](../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
- [Git Hooks — автоматизация проверок](./git_hooks.md) — валидация конфигураций на клиенте.
- [Git LFS — конфигурация](./git_lfs_config.md) — хранение больших артефактов CI/CD.
