# Специальные директории платформ — Git Forge Directories

## Определения

**Специальные директории платформ (Forge-specific directories)** — зарезервированные папки в корне репозитория (например, `.github/`, `.gitlab/`, `.gitea/`), которые используются Git-хостингами для хранения конфигураций CI/CD, шаблонов взаимодействия с пользователями, политик безопасности и управления доступом.

**Git Forge (Кузница)** — платформа для хостинга Git-репозиториев (GitHub, GitLab, Codeberg и др.), предоставляющая дополнительные инструменты для совместной разработки.

---

## Базовые концепции

### Назначение директорий

Использование специальных папок позволяет хранить метаданные проекта вместе с исходным кодом, обеспечивая принцип "Configuration as Code". Основные задачи:

- **Автоматизация (CI/CD):** Описание процессов сборки, тестирования и развертывания.
- **Стандартизация коммуникаций:** Шаблоны для сообщений об ошибках (Issues) и запросов на слияние (PR/MR).
- **Управление доступом:** Назначение ответственных за определенные части кода (CODEOWNERS).
- **Юридическая и техническая информация:** Политики безопасности, руководства по участию в разработке (Contributing).

### Сводная таблица по платформам

| Платформа | Основная директория | CI/CD конфигурация | Особенности |
| :--- | :--- | :--- | :--- |
| **GitHub** | `.github/` | `.github/workflows/` | Стандарт де-факто для многих инструментов. |
| **GitLab** | `.gitlab/` | `.gitlab-ci.yml` (корень) | Шаблоны хранятся в `.gitlab/`. |
| **Gitea / Forgejo** | `.gitea/` / `.forgejo/` | `.gitea/workflows/` | Поддержка совместимости с `.github/`. |
| **Bitbucket** | `.bitbucket/` | `bitbucket-pipelines.yml` | `.bitbucket/` используется для CODEOWNERS. |
| **Azure DevOps** | — | `azure-pipelines.yml` | Обычно не использует спец. директорию в корне. |
| **Woodpecker** | `.woodpecker/` | `.woodpecker/*.yml` | Альтернативная CI для Gitea/Forgejo. |

### Состав директории .github (стандарт GitHub)

- `workflows/` — файлы рабочих процессов GitHub Actions.
- `ISSUE_TEMPLATE/` — директория с шаблонами Issue (поддерживает YAML и Markdown).
- `PULL_REQUEST_TEMPLATE/` — директория или файл шаблона для PR.
- `CODEOWNERS` — файл для автоматического назначения ревьюеров.
- `dependabot.yml` — настройка автоматического обновления зависимостей.
- `FUNDING.yml` — ссылки на спонсирование проекта.
- `SECURITY.md` — инструкции по сообщению об уязвимостях.

### Состав директории .gitlab (стандарт GitLab)

- `issue_templates/` — шаблоны для задач.
- `merge_request_templates/` — шаблоны для Merge Requests.
- `CODEOWNERS` — поддерживается в `.gitlab/` или корне.
- `route-map.yml` — маппинг путей для Review Apps.

---

## Практические сценарии

### Сценарий 1: Создание шаблона Pull Request

Для GitHub шаблон можно разместить в нескольких местах. Рекомендуется использовать `.github/PULL_REQUEST_TEMPLATE.md`.

```markdown
# Описание изменений
<!-- Опишите, что было сделано и зачем -->

## Тип изменений
- [ ] Исправление ошибки
- [ ] Новая функциональность

## Как это протестировано?
<!-- Опишите ваши тесты -->
```

### Сценарий 2: Настройка CODEOWNERS

Позволяет автоматически запрашивать ревью у нужных команд.

```text
# .github/CODEOWNERS (или .gitlab/CODEOWNERS)

# Глобальные владельцы
*       @global-admin-team

# Документация - только техписатели
/docs/  @tech-writing-team

# Конфигурации инфраструктуры
*.tf    @devops-team
*.yaml  @devops-team
```

### Сценарий 3: Автоматизация с Dependabot

Файл `.github/dependabot.yml` позволяет поддерживать зависимости в актуальном состоянии.

```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Сценарий 4: Совместимость Forgejo/Gitea с GitHub

Если вы мигрируете проект с GitHub на Forgejo, многие действия (Actions) будут работать без изменений благодаря поддержке директории `.github/workflows/`. Однако, если вы хотите переопределить поведение для Forgejo, используйте `.forgejo/workflows/`.

```bash
# Проверка структуры на Forgejo
ls -R .forgejo/workflows/
# → ci.yml release.yml
```

---

## Дополнительная информация

### Правила поиска файлов (Fallback)

Платформы часто ищут документацию (README, LICENSE, CONTRIBUTING) в нескольких местах в следующем порядке:
1. Корень репозитория (рекомендуется).
2. Директория `docs/`.
3. Директория `.github/` (для GitHub).

### Официальные ресурсы

- **GitHub Docs - Creating templates:** [docs.github.com](https://docs.github.com/en/communities/using-templates-to-encourage-high-quality-issues-and-pull-requests/syntax-for-issue-template-forms)
- **GitLab Docs - Description templates:** [docs.gitlab.com](https://docs.gitlab.com/ee/user/project/description_templates.html)
- **Forgejo - Actions:** [forgejo.org/docs/latest/user/actions/](https://forgejo.org/docs/latest/user/actions/)

### См. также

- [Обзор специальных файлов Git](./git_special_files_overview.md) — общие сведения о `.gitignore`, `.gitattributes` и др.
- [GitHub Actions — синтаксис рабочих процессов](../Github_CI/Workflow_Syntax.md)
- [GitLab CI/CD — основы конфигурации](../CI-CD/GitLab_CI/Core_Concepts/gitlab_ci_basics.md)
