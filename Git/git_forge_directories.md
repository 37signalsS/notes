# Git Forge Directories — директории платформ

## Определения

**Forge-specific директории:** Специальные папки (.github/, .gitlab/, .gitea/, .forgejo/) для конфигурации CI/CD и других функций платформ.

---

## Forge-Specific директории

### Назначение

Платформы (GitHub, GitLab, Gitea, Forgejo) расширяют репозитории специальными директориями для конфигурации CI/CD, шаблонов, ревью кода.

### Директории по платформам

| Платформа | Директория | fallback-цепочка |
| :--- | :--- | :--- |
| **GitHub** | `.github/` | — |
| **GitLab** | `.gitlab/` | — |
| **Gitea** | `.gitea/` | `.gitea/` → `.github/` |
| **Forgejo** | `.forgejo/` | `.forgejo/` → `.gitea/` → `.github/` |
| **Bitbucket** | `.bitbucket/` | — |
| **SourceHut** | `.build.yml` (корень) | `.builds/*.yml` |

### Содержимое

* **CI/CD workflows:** `.github/workflows/`, `.gitlab-ci.yml`
* **Шаблоны issue/PR:** `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`
* **CODEOWNERS:** Файл для маппинга путей к обязательным ревьюерам
* **Другие конфигурации:** Зависит от платформы

### Особенности

* **Не являются Git-фичей:** Это соглашения платформ, но следуют тому же принципу: конфигурация путешествует с кодом.
* **Fallback-цепочки:** Forgejo и Gitea проверяют несколько директорий для совместимости с GitHub-конфигурациями.
* **Мультиплатформенность:** Позволяет переопределять GitHub-специфичные конфиги при хостинге на нескольких платформах.

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
