# Специальные файлы конфигурации Git

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

## .gitignore

### Назначение

Файл `.gitignore` указывает Git, какие файлы и директории следует игнорировать и не включать в систему контроля версий. Используется для исключения временных файлов, логов, скомпилированных артефактов, зависимостей и чувствительных данных.

### Синтаксис паттернов

| Паттерн | Описание |
| :--- | :--- |
| `*.log` | Игнорировать все файлы с расширением `.log` |
| `build/` | Игнорировать директорию `build` и всё её содержимое |
| `/TODO` | Игнорировать файл `TODO` только в корневой директории |
| `!important.log` | Не игнорировать `important.log` (исключение из правил) |
| `docs/**/*.txt` | Игнорировать все `.txt` файлы в `docs` и поддиректориях |
| `**/node_modules/` | Игнорировать `node_modules` на любом уровне вложенности |

### Порядок проверки игнорирования

Git проверяет ignore-файлы в следующем порядке:

1. `.gitignore` в каждой директории (от корня к текущей папке)
2. `.git/info/exclude` — локальные игноры, не коммитятся
3. Глобальный файл (`~/.config/git/ignore` или путь из `core.excludesFile`)

Глобальные игноры удобны для OS-специфичных файлов (`.DS_Store`, `Thumbs.db`), которые не должны загромождать каждый проект.

### Важные особенности

* **Только для неотслеживаемых файлов:** `.gitignore` влияет только на новые, не отслеживаемые Git файлы. Файлы, которые уже были закоммичены до добавления в `.gitignore`, остаются в репозитории.
* **Удаление из трекинга:** Для удаления уже отслеживаемого файла из Git (но оставления на диске) используйте `git rm --cached <файл>`.
* **Веб-интерфейсы форджей:** GitHub, GitLab, Forgejo и Gitea позволяют создать файл,_matching_ игнорируемый паттерн, через веб-редактор без предупреждений.
* **Менеджеры пакетов:** Часто поставляются с собственными игнор-паттернами (`node_modules/`, `vendor/`, `target/`), которые ожидаются в `.gitignore`.

### Практические примеры

```gitignore
# Зависимости
node_modules/
vendor/
target/

# Логи
*.log
logs/

# Переменные окружения
.env
.env.local

# Артефакты сборки
dist/
build/
*.exe
*.dll

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
```

### Временное игнорирование изменений в отслеживаемом файле

```bash
# Начать игнорировать изменения в файле, который уже в репозитории
git update-index --assume-unchanged <файл>

# Возобновить отслеживание изменений
git update-index --no-assume-unchanged <файл>
```

---

## .gitattributes

### Назначение

Файл `.gitattributes` указывает Git, как обрабатывать конкретные файлы: фильтры, драйверы diff/merge, нормализация окончаний строк, переопределения для определения языка.

### Основные атрибуты

```gitattributes
# Фильтры clean/smudge (Git LFS)
*.psd filter=lfs diff=lfs merge=lfs

# Нормализация окончаний строк
*.sh text eol=lf
*.bat text eol=crlf

# Обработка как бинарных
*.png binary
*.jpg binary

# Кастомный драйвер diff
*.json diff=json

# Стратегия слияния
package-lock.json merge=ours

# GitHub Linguist — переопределение определения языка
vendor/* linguist-vendored
*.gen.go linguist-generated
docs/* linguist-documentation
```

### Описание атрибутов

| Атрибут | Описание |
| :--- | :--- |
| `text` | Нормализовать окончания строк (CRLF ↔ LF) |
| `binary` | Не делать diff/merge, просто выбрать одну версию |
| `eol=lf` / `eol=crlf` | Принудительная нормализация к LF или CRLF |
| `merge=ours` | Всегда сохранять вашу версию при конфликтах слияния |
| `filter=lfs` | Использовать Git LFS для обработки файла |
| `linguist-vendored` | Исключить из статистики языков GitHub |
| `linguist-generated` | Сворачивать в diffs на GitHub |
| `linguist-documentation` | Исключить из статистики языков |

### Порядок проверки

Git проверяет `.gitattributes` в каждой директории и `.git/info/attributes` для локальных атрибутов.

---

## .lfsconfig

### Назначение

Файл конфигурации Git LFS, который путешествует с репозиторием. Позволяет закоммитить настройки LFS (URL эндпоинта, параметры передачи), чтобы все разработчики использовали одинаковые настройки.

### Формат

```ini
[lfs]
    url = https://lfs.example.com/repo

[lfs "transfer"]
    maxretries = 3
    timeout = 60
```

### Особенности

* Git LFS читает `.lfsconfig` автоматически при выполнении LFS-команд.
* Без этого файла разработчикам нужно вручную настраивать локальный LFS.
* LFS также использует `.gitattributes` для указания, какие файлы обрабатывать через LFS.
* **Миграция:** Если добавляете паттерны LFS после того, как файлы уже закоммичены, нужно выполнить `git lfs migrate` для переписывания истории.

---

## .gitmodules

### Назначение

Файл конфигурации для Git submodules. Git записывает в него информацию при выполнении `git submodule add` и читает при `git submodule update`.

### Формат

```ini
[submodule "vendor/lib"]
    path = vendor/lib
    url = https://github.com/example/lib.git
    branch = main

[submodule "themes/default"]
    path = themes/default
    url = https://github.com/example/theme.git
```

### Особенности submodules

* **Расположение:** Файл находится в корне репозитория.
* **Автоматическая инициализация:** `git clone` не загружает содержимое подмодулей автоматически. Требуется:
  ```bash
  git submodule update --init --recursive
  # или
  git clone --recurse-submodules <url>
  ```
* **Версионирование:** Подмодули отслеживают конкретный коммит, а не диапазон версий.
* **Проблемы:** Вложенные `.git` директории, забывчивость обновления создают запутанные состояния.
* **Применение:** Вендоринг контролируемого кода, монорепозитории с частичной выгрузкой.

---

## .mailmap

### Назначение

Файл `.mailmap` маппит имена и email авторов на канонические идентичности. Git использует его для вывода `git log`, `git shortlog`, `git blame`.

### Формат

```mailmap
# Маппинг старого email на новый
Jane Developer <jane@company.com> <jane@oldcompany.com>

# Стандартизация написания имени
Jane Developer <jane@company.com> Jane Dev <jane@company.com>

# Исправление обоих
Jane Developer <jane@company.com> <janed@personal.com>
Jane Developer <jane@company.com> J Developer <janed@personal.com>
```

Формат: `Proper Name <proper@email.com> Commit Name <commit@email.com>`

### Особенности

* **Инструменты:** `git shortlog -sn`, `git log`, `git blame` используют mailmap для агрегации коммитов.
* **GitHub:** Графики контрибьюторов GitHub **не используют** `.mailmap`, дубликаты сохраняются в веб-интерфейсе.
* **Расположение:** По умолчанию `.mailmap` в корне репозитория или путь настраивается через `mailmap.file`.

---

## .git-blame-ignore-revs

### Назначение

Файл содержит список коммитов, которые `git blame` должен пропускать. Используется для исключения коммитов с массовыми изменениями (форматирование, линтинг, рефакторинг).

### Формат

```text
# .git-blame-ignore-revs
# Запуск prettier на всей кодовой базе
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0

# Миграция на ESLint flat config
b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1
```

### Настройка

```bash
# Локальная настройка
git config blame.ignoreRevsFile .git-blame-ignore-revs

# Глобальная настройка (требует наличия файла в каждом репо)
git config --global blame.ignoreRevsFile .git-blame-ignore-revs
```

### Поддержка форджами

* **GitHub:** Читает автоматически без конфигурации
* **GitLab:** Поддержка с версии 15.4+
* **Gitea:** Читает автоматически

### Особенности

* **Проблема:** После запуска форматтера на всей кодовой базе `git blame` становится бесполезным.
* **Решение:** Файл позволяет пропустить шумные коммиты и показать автора реальных изменений.
* **Предостережение:** Глобальная настройка без файла в репо вызовет ошибки. Нужна per-repo конфигурация или пустой файл в каждом репозитории.

---

## .gitmessage

### Назначение

Шаблон для сообщений коммитов. Git предварительно заполняет редактор сообщений этим содержимым.

### Пример

```text
# .gitmessage
# <type>: <subject>
#
# <body>
#
# <footer>
#
# Types: feat, fix, docs, style, refactor, test, chore
```

### Настройка

```bash
git config commit.template .gitmessage
```

### Особенности

* **Требует ручной настройки:** Каждый разработчик должен выполнить `git config` после клонирования.
* **Автоматизация:** Команды используют setup-скрипты или husky для автоматической настройки.
* **Альтернатива:** Хук `commit-msg` для валидации формата вместо шаблона.

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

## Другие соглашения

### .gitkeep

* **Статус:** Соглашение, **не фича Git**.
* **Назначение:** Git не отслеживает пустые директории. Файл `.gitkeep` (или любой другой) помещается в пустую папку, чтобы Git имел что отслеживать.
* **Имя произвольное:** Может называться как угодно, `.gitkeep` — конвенция.

### .gitconfig (в репозитории)

* **Назначение:** Предлагаемая конфигурация для разработчиков.
* **Ограничение:** Git **не загружает** такие файлы автоматически (безопасность).
* **Использование:** Проекты включают инструкции для ручной настройки:
  ```bash
  git config include.path ../.gitconfig
  ```
* **Применение:** Монорепозитории, проекты со специфичными настройками Git.

### .gitsigners / allowedSigners

* **Назначение:** Файлы с доверенными ключами подписи (GPG/SSH) для верификации коммитов.
* **Использование:** Linux kernel и другие проекты с trusted contributors.
* **Настройка:** `git config gpg.ssh.allowedSignersFile <файл>` для `git log --show-signature`.

### .gitreview

* **Назначение:** Конфигурация интеграции с Gerrit.
* **Проекты:** OpenStack, Android, Eclipse.
* **Формат:**
  ```ini
  [gerrit]
  host=review.opendev.org
  port=29418
  project=openstack/nova.git
  defaultbranch=master
  ```
* **Использование:** `git review` читает файл и пушит коммиты в Gerrit для ревью.

### .gitlint

* **Назначение:** Конфигурация линтера сообщений коммитов.
* **Пример:**
  ```ini
  [general]
  ignore=body-is-missing

  [title-max-length]
  line-length=72
  ```

### .jj/

* **Назначение:** Директория состояния Jujutsu (git-совместимая VCS).
* **Особенности:** Сосуществует с `.git/`, уважает все магические файлы Git (.gitignore, .gitattributes, .mailmap).

---

## Файлы вне Git

### .editorconfig

**Назначение:** Стандартизация поведения редакторов (indent style, line endings, trailing whitespace, encoding).

**Пример:**
```editorconfig
root = true

[*]
indent_style = space
indent_size = 2
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true

[*.md]
trim_trailing_whitespace = false
```

**Поддержка:** VS Code, Vim, Emacs, Sublime — нативно или через плагины.

### .ruby-version, .node-version, .python-version

**Назначение:** Указание версии языка для менеджеров версий (rbenv, nodenv, pyenv, nvm, asdf).

**Пример:**
```text
# .ruby-version
3.3.0

# .node-version
20.11.0
```

**Поведение:** Инструменты автоматически переключают версию при `cd` в директорию.

### .tool-versions

**Назначение:** Мультиязычный файл версий для asdf.

**Пример:**
```text
ruby 3.3.0
nodejs 20.11.0
python 3.12.0
```

### .dockerignore

**Назначение:** Исключение файлов из контекста сборки Docker (аналогично `.gitignore`).

**Пример:**
```dockerignore
.git
node_modules
*.log
.env
```

**Особенности:**
* Ускоряет сборку (меньше файлов отправляется демону)
* Предотвращает попадание секретов в образы
* Синтаксис идентичен `.gitignore`: wildcards, negation, directory markers

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

## Дополнительная информация

* **Официальная документация:**
  * [gitignore](https://git-scm.com/docs/gitignore)
  * [gitattributes](https://git-scm.com/docs/gitattributes)
  * [gitmodules](https://git-scm.com/docs/gitmodules)
  * [gitmailmap](https://git-scm.com/docs/gitmailmap)
  * [Git LFS](https://git-lfs.com/)
* **Шаблоны .gitignore:** [GitHub gitignore templates](https://github.com/github/gitignore)
* **GitHub Linguist:** [Атрибуты для переопределения языков](https://github.com/github-linguist/linguist/blob/master/README.md)
