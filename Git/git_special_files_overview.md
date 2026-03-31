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
- Используйте `git config` CLI для чтения/записи
- Библиотеки: `go-git` (Go), `GitPython` (Python), `libgit2` (C)

---

## Практические сценарии

### Сценарий 1: Быстрая проверка специальных файлов в проекте

```bash
# Проверить наличие основных файлов
ls -la .gitignore .gitattributes .gitmodules .mailmap 2>/dev/null

# Просмотреть содержимое .gitignore
cat .gitignore

# Проверить, какие файлы игнорируются
git check-ignore -v <файл>
```

### Сценарий 2: Валидация .gitattributes

```bash
# Проверить атрибуты для конкретного файла
git check-attr -a -- <файл>

# Проверить атрибуты для всех файлов
git check-attr -a -- '*'
```

### Сценарий 3: Проверка .mailmap

```bash
# Посмотреть статистику авторов с учётом mailmap
git shortlog -sn --all

# Проверить log с каноническими именами
git log --use-mailmap --format="%an <%ae>" | sort | uniq -c
```

---

## Дополнительная информация

### Официальные ресурсы

- **gitignore:** [git-scm.com/docs/gitignore](https://git-scm.com/docs/gitignore)
- **gitattributes:** [git-scm.com/docs/gitattributes](https://git-scm.com/docs/gitattributes)
- **gitmodules:** [git-scm.com/docs/gitmodules](https://git-scm.com/docs/gitmodules)
- **gitmailmap:** [git-scm.com/docs/gitmailmap](https://git-scm.com/docs/gitmailmap)
- **Git LFS:** [git-lfs.com](https://git-lfs.com/)

### Ресурсы

- **Шаблоны .gitignore:** [github.com/github/gitignore](https://github.com/github/gitignore)
- **GitHub Linguist:** [github.com/github-linguist/linguist](https://github.com/github-linguist/linguist)

### Связанные темы

Подробная информация о файлах: .gitignore в [git_ignore.md](./git_ignore.md), .gitattributes в [git_attributes.md](./git_attributes.md), .lfsconfig в [git_lfs_config.md](./git_lfs_config.md), .gitmodules в [git_submodules.md](./git_submodules.md), .mailmap в [git_mailmap.md](./git_mailmap.md), .git-blame-ignore-revs в [git_blame_ignore.md](./git_blame_ignore.md), .gitmessage в [git_commit_template.md](./git_commit_template.md), директории платформ в [git_forge_directories.md](./git_forge_directories.md), другие соглашения в [git_other_conventions.md](./git_other_conventions.md). Файлы версий в [version_files.md](./version_files.md), editorconfig в [editorconfig.md](./editorconfig.md).
