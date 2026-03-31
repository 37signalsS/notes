# Git Forge Directories — директории платформ

## Определения

**Forge-specific директории** — специальные папки в корне репозитория (`.github/`, `.gitlab/`, `.gitea/`, `.forgejo/`), используемые Git-платформами для конфигурации CI/CD, шаблонов, ревью кода и других функций.

---

## Базовые концепции

### Назначение

Платформы (GitHub, GitLab, Gitea, Forgejo) расширяют репозитории специальными директориями для:

- **CI/CD конфигурации:** Автоматизация сборки, тестирования, деплоя
- **Шаблонов:** Issue, Pull Request, Merge Request
- **Управления доступом:** CODEOWNERS для обязательных ревьюеров
- **Безопасности:** Security policies, vulnerability reporting

### Директории по платформам

| Платформа | Директория | Fallback-цепочка |
| :--- | :--- | :--- |
| **GitHub** | `.github/` | — |
| **GitLab** | `.gitlab/` | — |
| **Gitea** | `.gitea/` | `.gitea/` → `.github/` |
| **Forgejo** | `.forgejo/` | `.forgejo/` → `.gitea/` → `.github/` |
| **Bitbucket** | `.bitbucket/` | — |
| **SourceHut** | `.build.yml` (корень) | `.builds/*.yml` |

### Типовое содержимое

**GitHub (`.github/`):**
- `workflows/` — GitHub Actions workflow-файлы
- `ISSUE_TEMPLATE/` — шаблоны для новых issue
- `PULL_REQUEST_TEMPLATE.md` — шаблон Pull Request
- `CODEOWNERS` — маппинг путей к ревьюерам
- `SECURITY.md` — политика безопасности
- `CONTRIBUTING.md` — руководство для контрибьюторов
- `FUNDING.yml` — информация о финансировании
- `dependabot.yml` — конфигурация Dependabot

**GitLab (`.gitlab/`):**
- `ci.yml` — основной CI-конфиг (альтернатива `.gitlab-ci.yml` в корне)
- `issue_templates/` — шаблоны issue
- `merge_request_templates/` — шаблоны MR
- `labelling.toml` — конфигурация лейблов

**Gitea/Forgejo (`.gitea/`, `.forgejo/`):**
- `workflows/` — workflow-файлы (совместимы с GitHub Actions)
- `issue_templates/` — шаблоны issue
- `pull_request_template.md` — шаблон PR
- `CODEOWNERS` — маппинг ревьюеров
- `wiki/` — файлы для встроенной вики

### Особенности

- **Не являются Git-фичей:** Это соглашения платформ, но следуют принципу: конфигурация путешествует с кодом
- **Fallback-цепочки:** Forgejo и Gitea проверяют несколько директорий для совместимости с GitHub-конфигурациями
- **Мультиплатформенность:** Позволяет переопределять специфичные конфиги при хостинге на нескольких платформах

---

## Практические сценарии

### Сценарий 1: Настройка GitHub Actions

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: npm test
```

### Сценарий 2: Шаблоны для Issue

```markdown
# .github/ISSUE_TEMPLATE/bug_report.md
---
name: Bug Report
about: Сообщение об ошибке
title: '[BUG] '
labels: bug
---

## Описание ошибки
Чёткое описание проблемы.

## Шаги воспроизведения
1. Шаг 1
2. Шаг 2

## Ожидаемое поведение
Что должно было произойти.
```

### Сценарий 3: CODEOWNERS для обязательного ревью

```text
# .github/CODEOWNERS
# Владелец всего кода
* @tech-lead

# Безопасность — только security-команда
/security/ @security-team

# Документация — техписатели
/docs/ @tech-writers

# Конфигурация БД — DBA
**/*.sql @dba-team
```

### Сценарий 4: Мультиплатформенная настройка

Для проекта, размещённого на GitHub и Forgejo:

```
.github/
  workflows/
    ci.yml          # GitHub Actions
.gitea/
  workflows/
    ci.yml          # Переопределение для Forgejo/Gitea
  pull_request_template.md  # Специфичный шаблон
```

Forgejo сначала проверит `.gitea/workflows/`, затем `.github/workflows/`.

### Сценарий 5: Политика безопасности

```markdown
# .github/SECURITY.md
## Сообщение об уязвимости

Пожалуйста, сообщайте об уязвимостях через GitHub Security Advisories
или на email: security@example.com

## Поддерживаемые версии
| Версия | Поддержка |
| :--- | :--- |
| 2.x | ✅ |
| 1.x | ⚠️ (только критические исправления) |
| 0.x | ❌ |
```

---

## Дополнительная информация

### Официальные ресурсы

- **GitHub:** [docs.github.com/ru/repositories/configuring-repositories](https://docs.github.com/ru/repositories/configuring-repositories)
- **GitLab:** [docs.gitlab.com/ee/user/project/](https://docs.gitlab.com/ee/user/project/)
- **Gitea:** [docs.gitea.com/usage/](https://docs.gitea.com/usage/)
- **Forgejo:** [codeberg.org/forgejo/forgejo](https://codeberg.org/forgejo/forgejo)

### Связанные документы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md).
