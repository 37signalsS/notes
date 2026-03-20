# Обзор специальных файлов конфигурации Git

## Определения

* **Специальные файлы Git:** Файлы конфигурации, которые коммитятся в репозиторий и управляют поведением Git, в отличие от файлов настроек в `.git/`, которые локальны для каждого клона.
* **`.gitignore`:** Файл с паттернами файлов, которые Git никогда не должен отслеживать.
* **`.gitattributes`:** Файл, определяющий, как Git обрабатывает конкретные файлы (фильтры, драйверы diff/merge, нормализация окончаний строк).
* **`.gitmodules`:** Файл конфигурации для Git submodules, хранящий пути, URL и ветки подмодулей.
* **`.lfsconfig`:** Файл конфигурации Git LFS, который путешествует с репозиторием.
* **`.mailmap`:** Файл для маппинга имён и email авторов на канонические идентичности.
* **`.git-blame-ignore-revs`:** Файл со списком коммитов, которые `git blame` должен пропускать.
* **`.gitmessage`:** Шаблон для сообщений коммитов.
* **Forge-specific директории:** Специальные папки (.github/, .gitlab/, .gitea/, .forgejo/) для конфигурации CI/CD и других функций платформ.

## Базовые концепции

### Принцип работы специальных файлов

Git ищет специальные файлы в нескольких местах в определённом порядке:

1. **Корень репозитория** — основные файлы (.gitignore, .gitattributes, .gitmodules)
2. **Вложенные директории** — файлы в подкаталогах переопределяют правила для этих директорий
3. **`.git/info/`** — локальные файлы, не коммитятся в репозиторий (`.git/info/exclude`, `.git/info/attributes`)
4. **Глобальные файлы** — настраиваются через `core.excludesFile` или `~/.config/git/ignore`

Эти файлы коммитятся в репозиторий и «путешествуют» вместе с кодом, обеспечивая консистентное поведение для всех разработчиков.

---

## Поддержка в инструментах

Если вы разрабатываете инструменты для работы с Git-репозиториями, рекомендуется уважать следующие файлы:

| Файл | Когда читать |
| :--- | :--- |
| `.gitignore` | При обходе дерева репозитория |
| `.gitattributes` | Для определения бинарных/вендорных/сгенерированных файлов |
| `.mailmap` | При отображении информации об авторах |
| `.gitmodules` | При работе с подмодулями |
| `.lfsconfig` | При работе с Git LFS |
| `.git-blame-ignore-revs` | При отображении blame-информации |

### Парсинг git-config формата

Формат: `[section "subsection"] key = value`

**Рекомендации:**
* Используйте `git config` CLI для чтения/записи
* Библиотеки: `go-git` (Go), `GitPython` (Python), `libgit2` (C)

---

## Связанные документы

### Git-файлы
- **Git Ignore**: [git_ignore.md](./git_ignore.md) — .gitignore и .dockerignore
- **Git Attributes**: [git_attributes.md](./git_attributes.md) — .gitattributes
- **Git LFS Config**: [git_lfs_config.md](./git_lfs_config.md) — .lfsconfig
- **Git Submodules**: [git_submodules.md](./git_submodules.md) — .gitmodules
- **Git Mailmap**: [git_mailmap.md](./git_mailmap.md) — .mailmap
- **Git Blame Ignore**: [git_blame_ignore.md](./git_blame_ignore.md) — .git-blame-ignore-revs
- **Git Commit Template**: [git_commit_template.md](./git_commit_template.md) — .gitmessage
- **Git Forge Directories**: [git_forge_directories.md](./git_forge_directories.md) — .github/, .gitlab/ и др.
- **Git Other Conventions**: [git_other_conventions.md](./git_other_conventions.md) — .gitkeep, .gitreview, .gitlint и др.

### Другие файлы конфигурации
- **Version Files**: [version_files.md](./version_files.md) — .ruby-version, .tool-versions и др.
- **Editorconfig**: [editorconfig.md](./editorconfig.md) — .editorconfig

---

## Дополнительная информация

* **Официальная документация:**
  * [gitignore](https://git-scm.com/docs/gitignore)
  * [gitattributes](https://git-scm.com/docs/gitattributes)
  * [gitmodules](https://git-scm.com/docs/gitmodules)
  * [gitmailmap](https://git-scm.com/docs/gitmailmap)
  * [Git LFS](https://git-lfs.com/)
* **Шаблоны .gitignore:** [GitHub gitignore templates](https://github.com/github/gitignore)
* **GitHub Linguist:** [Атрибуты для переопределения языков](https://github.com/github-linguist/linguist/blob/master/README.md)
