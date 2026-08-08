# Специальные директории платформ — Git Forge Directories

## Определения

**Специальные директории платформ (Forge-specific directories)** — зарезервированные системные папки в корне репозитория (например, `.github/`, `.gitlab/`, `.bitbucket/`), используемые Git-хостингами для реализации подхода **Configuration as Code**. Они содержат метаданные, конфигурации автоматизации (CI/CD), шаблоны взаимодействия и политики безопасности, которые интерпретируются платформой автоматически.

**Git Forge (Кузница)** — веб-платформа для хостинга Git-репозиториев, дополняющая базовый протокол Git инструментами совместной разработки (Pull Requests, CI/CD, Issue Tracking).

---

## Базовые концепции

### Назначение и иерархия

Использование специализированных директорий позволяет отделить технические конфигурации платформы от основного исходного кода, сохраняя при этом версионность настроек.

**Основные задачи:**
- **Автоматизация (Workflow):** Описание конвейеров сборки и развертывания.
- **Интерфейсные формы:** Стандартизация ввода данных пользователями через шаблоны.
- **Governance:** Управление правилами ревью кода и доступом.
- **Documentation Fallback:** Хранение служебных MD-файлов (README, SECURITY), если они отсутствуют в корне.

### Сводная таблица по платформам

| Платформа | Основная директория | CI/CD конфигурация | Основные возможности |
| :--- | :--- | :--- | :--- |
| **GitHub** | `.github/` | `.github/workflows/` | Actions, Forms, Dependabot, Discussions |
| **GitLab** | `.gitlab/` | `.gitlab-ci.yml` (корень) | Templates, K8s Agents, Review Apps |
| **Bitbucket** | `.bitbucket/` | `bitbucket-pipelines.yml` | CODEOWNERS, PR Templates |
| **Gitea / Forgejo** | `.gitea/` / `.forgejo/` | `.gitea/workflows/` | Совместимость с GitHub Actions |
| **Azure DevOps** | — | `azure-pipelines.yml` | Обычно использует корень или `.azure-devops/` |
| **Woodpecker** | `.woodpecker/` | `.woodpecker/*.yml` | Декларативная CI для легковесных платформ |

### Состав директории .github (GitHub)

- `workflows/` — YAML-файлы GitHub Actions.
- `ISSUE_TEMPLATE/` — шаблоны задач. Поддерживаются Markdown и YAML-формы (`.yml`).
- `DISCUSSION_TEMPLATE/` — шаблоны категорий обсуждений (только YAML).
- `PULL_REQUEST_TEMPLATE/` — директория или файл для шаблона PR.
- `actions/` — локальные Actions репозитория.
- `CODEOWNERS` — правила назначения ревьюеров.
- `dependabot.yml` — конфигурация обновления зависимостей.
- `renovate.json` — альтернатива Dependabot (может быть в корне).
- `FUNDING.yml` — кнопки спонсирования.

### Состав директории .gitlab (GitLab)

- `issue_templates/` — шаблоны для задач (Issues).
- `merge_request_templates/` — шаблоны для Merge Requests.
- `agents/` — конфигурация **GitLab Agent for Kubernetes** (структура: `agents/<name>/config.yaml`).
- `CODEOWNERS` — правила владельцев кода (также может быть в корне).
- `route-map.yml` — соответствие путей файлов URL-адресам для Review Apps.

### Состав директории .bitbucket (Bitbucket)

- `pull_request_template.md` — основной шаблон PR.
- `pull_request_templates/` — поддержка множественных шаблонов (Bitbucket Data Center).
- `CODEOWNERS` — управление ревьюерами (рекомендуемое место).

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

---

## Дополнительная информация

### Приоритет поиска служебных файлов

Если файл (например, `README.md` или `CONTRIBUTING.md`) существует в нескольких местах, платформы обычно применяют следующий приоритет:
1. **Корень репозитория (`/`)** — наивысший приоритет, рекомендуется для основных файлов.
2. **Папка `docs/`** — для объемной документации.
3. **Спец. папка (`.github/`, `.gitlab/`)** — для "скрытия" служебных файлов из корня.

### Безопасность и политики

Файлы политик помогают поддерживать порядок в open-source и корпоративных проектах:
- **SECURITY.md**: Описывает процесс сообщения об уязвимостях (Vulnerability Disclosure Policy).
- **SUPPORT.md**: Куда обращаться за помощью.
- **CONTRIBUTING.md**: Правила внесения вклада в проект.

### См. также

- [Обзор специальных файлов Git](./git_special_files_overview.md) — `.gitignore`, `.gitattributes`.
- [GitHub Actions — синтаксис рабочих процессов](../Github_CI/Workflow_Syntax.md)
- [GitLab CI/CD — основы конфигурации](../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)
- [Интеграция GitLab с Kubernetes](../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
