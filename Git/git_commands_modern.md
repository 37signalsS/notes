# Git — современные команды (restore, switch, clean, describe)

**Актуально для:** Git 2.23–2.56 (локально проверено на 2.54.0). Команды `restore`/`switch` появилась в 2.23; `range-diff` — в 2.23, `describe --broken` — в 2.40. Изменений в описанных командах с 2.48.1 до 2.56.0 не было.

## Определения

**git restore** — команда для восстановления файлов из индекса или из конкретного коммита. Заменяет части `git checkout` и `git reset` (Git 2.23+).

**git switch** — команда для переключения между ветками. Заменяет `git checkout` для переключений (Git 2.23+).

**git clean** — команда для удаления неотслеживаемых файлов из рабочего дерева.

**git describe** — команда для генерации человекочитаемого имени версии на основе ближайшего тега.

**git shortlog** — команда для генерации отчёта по авторам коммитов.

**git range-diff** — команда для сравнения двух версий цепочки коммитов (полезна при rebase). Появилась в Git 2.23.

---

## Базовые концепции

### restore vs switch vs checkout

| Задача | Старый способ | Новый способ (2.23+) |
| :--- | :--- | :--- |
| Переключение на ветку | `git checkout feature` | `git switch feature` |
| Переключение на коммит | `git checkout abc123` | `git switch --detach abc123` |
| Восстановить файл из HEAD | `git checkout -- file` | `git restore file` |
| Восстановить файл из индекса | `git reset HEAD file` | `git restore --staged file` |
| Восстановить файл из коммита | `git checkout abc123 -- file` | `git restore --source=abc123 file` |

### clean: удаление неотслеживаемых файлов

| Флаг | Описание |
| :--- | :--- |
| `-n` / `--dry-run` | Показать, что будет удалено (без удаления) |
| `-f` / `--force` | Принудительное удаление (обязательно для `-d`) |
| `-d` | Удалять также неотслеживаемые директории |
| `-x` | Включая файлы из `.gitignore` |
| `-X` | Только файлы из `.gitignore` |
| `-fd` | Принудительное удаление с директориями |

### describe: генерация версии

Формат: `v<тег>-<число>-g<хеш>`

Примеры:
- `v1.0.0` — HEAD на теге
- `v1.0.0-5-gabc1234` — 5 коммитов после тега v1.0.0, текущий хеш abc1234
- `abc1234` — нет тегов (только хеш)

| Флаг | Описание |
| :--- | :--- |
| `--tags` | Использовать также lightweight (неаннотированные) теги (по умолчанию — только аннотированные) |
| `--all` | Использовать все refs из `refs/` (ветки, remote-tracking, lightweight-теги) |
| `--abbrev=<n>` | Количество шестнадцатеричных цифр (по умолчанию 7); `0` — только ближайший тег без суффикса |
| `--long` | Всегда выводить длинный формат, даже если HEAD совпадает с тегом |
| `--match <glob>` | Учитывать только теги, соответствующие шаблону (например, `v*`) |
| `--exclude <glob>` | Исключить теги по шаблону; `--no-exclude` сбрасывает список |
| `--contains` | Найти тег, который *содержит* коммит (а не предшествует ему); автоматически включает `--tags` |
| `--candidates=<n>` | Учитывать только N самых последних тегов (по умолчанию 10); `0` — только точные совпадения |
| `--exact-match` | Синоним для `--candidates=0` — выводить только точные совпадения |
| `--always` | Fallback — выводить усечённый хеш, если тегов нет |
| `--first-parent` | При merge-коммитах идти только по первому родителю |
| `--dirty[=<mark>]` | Добавить суффикс `-dirty` (или кастомный `<mark>`) при наличии немокоммичных изменений |
| `--broken[=<mark>]` | Как `--dirty`, но при ошибке определения состояния добавить `-broken` вместо сбоя |
| `--debug` | Выводить информацию о стратегии поиска тегов в stderr |

---

## Практические сценарии

### Сценарий 1: Восстановление файла из HEAD

```bash
# Отменить локальные изменения в файле
git restore src/app.py

# Восстановить из индекса (отменить git add)
git restore --staged src/app.py

# Восстановить из конкретного коммита
git restore --source=abc1234 src/app.py

# Восстановить несколько файлов
git restore src/*.py
```

**Валидация:**
```bash
git status
# → (пусто, если файлы были восстановлены)
```

### Сценарий 2: Переключение между ветками

```bash
# Переключиться на ветку
git switch feature

# Создать новую ветку и переключиться
git switch -c new-feature

# Переключиться на коммит (detached HEAD)
git switch --detach abc1234

# Вернуться на предыдущую ветку
git switch -
```

**Edge cases:**
- `git switch` отказывается переключаться при наличии uncommitted изменений, конфликтующих с целевой веткой.
- Используйте `--discard-changes` для принудительного переключения (опасно).

### Сценарий 3: Очистка неотслеживаемых файлов

```bash
# Предварительный просмотр (ничего не удаляя)
git clean -fdn
# → Would remove debug.log
# → Would remove temp/

# Удалить неотслеживаемые файлы и директории
git clean -fd

# Удалить ВСЁ, включая .gitignore
git clean -fdx

# Только файлы из .gitignore
git clean -fX
```

**Валидация:**
```bash
git status
# → (только tracked файлы)
```

**Edge cases:**
- `git clean -fd` не удаляет файлы из `.gitignore`. Для этого нужен `-x`.
- Без `-d` директории не удаляются.

### Сценарий 4: Генерация версии через describe

```bash
# Автоматическая версия на основе ближайшего тега
git describe --tags --always
# → v1.0.0-12-gabc1234

# Только тег (без числа и хеша)
git describe --tags --abbrev=0
# → v1.0.0

# Использование в сборке
VERSION=$(git describe --tags --always)
echo "Building version: $VERSION"
```

### Сценарий 5: Отчёт по авторам

```bash
# Список авторов и количество коммитов
git shortlog -sn
# → 42  Developer 1
# → 15  Developer 2

# С email-адресами
git shortlog -sne
# → 42  Developer 1 <dev1@company.com>

# Только последние 100 коммитов
git shortlog -sn -100

# Без merge-коммитов
git shortlog -sn --no-merges
```

> **См. также:** Полный справочник по `git shortlog` (все флаги `--group`, `--wrap`, `--stdin`, SRE-контекст) — [Git Shortlog](./git_shortlog.md).

### Сценарий 6: Сравнение версий после rebase

```bash
# Сохранить SHA до rebase
BEFORE=$(git rev-parse HEAD)

# Выполнить rebase
git rebase main

# Сравнить, что изменилось
git range-diff $BEFORE...HEAD
# → Покажет разницу между двумя версиями цепочки
```

**Валидация:**
```bash
# Проверить, что range-diff показывает пусто (нет изменений)
git range-diff $BEFORE...HEAD --no-patch
# → (пусто, если цепочки совпадают)
```

**Особенности:**
- `git range-diff` сравнивает *цепочки коммитов*, а не отдельные диффы — идеален для проверки rebase/cherry-pick.
- Формат вывода: `±` — коммит добавлен/удалён, `→` — коммит заменён, `..` — коммит перенесён.
- Поддерживает все флаги `git diff` (`-p`, `-U`, `-M`, `-C`, `-w`, `-b`, `-a` и др.).
- Сравнивает два диапазона: `OLD...NEW` (три точки — merge-base) или `OLD..NEW` (две точки — прямая цепочка).

### Сценарий 7: Комбинирование restore + clean

```bash
# Полный сброс рабочего дерева
git restore .
git clean -fd
# → Рабочее дерево полностью чистое
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: this operation must be run in a work tree` | Команда в bare-репозитории | Перейти в рабочий каталог |
| `error: path 'file' is unmerged` | Файл в состоянии конфликта | `git add <file>` или `git reset HEAD <file>` |
| `git clean: nothing to clean` | Нет неотслеживаемых файлов | Проверить `git status` |
| `fatal: invalid reference: abc123` | Некорректный хеш | Указать полный 40-символьный хеш |
| `fatal: bad revision 'abc123'` | `git restore --source` с несуществующим ref | Проверить `git rev-parse` перед использованием |
| `git clean: unable to remove 'dir'` | Права доступа к директории | Запускать clean от имени owners или с `sudo` |
| `fatal: no tag matches 'v*'` | `--match` не нашёл тегов | Проверить `git tag` и шаблон |
| `fatal: ambiguous argument 'HEAD'` | `git describe` без тегов и без `--always` | Добавить `--always` или `--tags` |
| `error: could not resolve HEAD` | Detached HEAD без тегов | Использовать `--always` или `git switch` на ветку |
| `range-diff: no common ancestor` | Два диапазона без общего предка | Использовать `git merge-base` для проверки |

### Best Practices

1. **Используйте `git restore`** вместо `git checkout --` для ясности.
2. **Используйте `git switch`** вместо `git checkout` для переключений.
3. **Всегда делайте `-n` перед `git clean`** — чтобы понять, что будет удалено.
4. **Используйте `git describe --tags`** в CI для генерации версий.
5. **Комбинируйте `shortlog --no-merges`** для точной статистики.
6. **Проверяйте `git range-diff` после rebase** — это единственный способ убедиться, что цепочка коммитов не искажена.

---

## Дополнительная информация

### Связанные темы

- [Git Basics](./git_basics.md) — архитектура трёх деревьев (HEAD, index, working tree).
- [Git History Manipulation](./git_history_manipulation.md) — reset, revert, rebase (старые альтернативы restore/switch).
- [Git Branching](./git_branching.md) — ветвление, detached HEAD, переключение веток.
- [Git Tags](./git_tags.md) — describe и семантическое версионирование.
- [Git Shortlog](./git_shortlog.md) — SSoT для отчётов по авторам (все флаги `--group`, `--wrap`, `--stdin`).
- [Конфигурация Git](./git_configuration.md) — настройка clean.exclude, restore.useBuiltin.

### Официальные ресурсы

- **Git Restore Documentation:** [git-scm.com/docs/git-restore](https://git-scm.com/docs/git-restore)
- **Git Switch Documentation:** [git-scm.com/docs/git-switch](https://git-scm.com/docs/git-switch)
- **Git Clean Documentation:** [git-scm.com/docs/git-clean](https://git-scm.com/docs/git-clean)
- **Git Describe Documentation:** [git-scm.com/docs/git-describe](https://git-scm.com/docs/git-describe)
- **Git Shortlog Documentation:** [git-scm.com/docs/git-shortlog](https://git-scm.com/docs/git-shortlog)
- **Git Range-Diff Documentation:** [git-scm.com/docs/git-range-diff](https://git-scm.com/docs/git-range-diff)

---

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `git restore <file>` | Восстановить файл из индекса | `git restore src/app.py` |
| `git restore --staged <file>` | Отменить `git add` | `git restore --staged src/app.py` |
| `git restore --source=abc1234 <file>` | Восстановить из коммита | `git restore --source=abc1234 src/app.py` |
| `git restore --patch <file>` | Интерактивное восстановление | `git restore -p src/app.py` |
| `git restore --ours <file>` | Восстановить нашу версию при конфликте | `git restore --ours conflict.txt` |
| `git restore --theirs <file>` | Восстановить чужую версию при конфликте | `git restore --theirs conflict.txt` |
| `git restore --source=HEAD~1 --staged --worktree <file>` | Полный сброс до коммита | `git restore -s HEAD~1 -S -W file` |
| `git switch <branch>` | Переключиться на ветку | `git switch feature` |
| `git switch -c <branch>` | Создать и переключиться | `git switch -c new-feature` |
| `git switch --detach <commit>` | Detached HEAD | `git switch --detach abc1234` |
| `git switch --force <branch>` | Принудительное переключение | `git switch -f main` |
| `git switch --merge <branch>` | 3-way merge при переключении | `git switch -m feature` |
| `git switch --orphan <branch>` | Создать пустую ветку | `git switch --orphan docs` |
| `git clean -fdn` | Предпросмотр удаления | `git clean -fdn` |
| `git clean -fd` | Удалить неотслеживаемые файлы и директории | `git clean -fd` |
| `git clean -fdx` | Удалить всё, включая `.gitignore` | `git clean -fdx` |
| `git clean -fdi` | Интерактивное удаление | `git clean -fdi` |
| `git clean -e "*.log"` | Исключить шаблон | `git clean -fdx -e "*.log"` |
| `git describe --tags --always` | Версия по ближайшему тегу | `git describe --tags --always` |
| `git describe --tags --abbrev=0` | Только ближайший тег | `git describe --tags --abbrev=0` |
| `git describe --tags --dirty` | Учитывать немокоммичные изменения | `git describe --tags --dirty` |
| `git describe --tags --match "v*"` | Только теги по шаблону | `git describe --tags --match "v*"` |
| `git describe --long --tags` | Длинный формат | `git describe --long --tags` |
| `git shortlog -sn` | Подсчёт коммитов по авторам | `git shortlog -sn` |
| `git shortlog -sne` | С email-адресами | `git shortlog -sne` |
| `git shortlog -nsc` | По коммиттеру | `git shortlog -nsc` |
| `git shortlog --no-merges` | Без merge-коммитов | `git shortlog -sn --no-merges` |
| `git range-diff BEFORE...HEAD` | Сравнить цепочки коммитов | `git range-diff $BEFORE...HEAD` |
| `git range-diff -p main~3..main` | Сравнить два диапазона | `git range-diff -p main~3..main` |

---

## Автоматизация и мониторинг (SRE / DevOps-аспект)

Конфигурация Git — часть инфраструктуры, а не только личные предпочтения. Ключевые аспекты для автоматизированных сред:

- **Идентификация в CI/CD:** `user.name` / `user.email` для ботов (например, `github-actions[bot]`) задаются через `git config` в скрипте инициализации или через переменные окружения `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` / `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL`. Это исключает коммиты от случайного пользователя.
- **Хуки и безопасность:** `core.hooksPath` позволяет централизованно внедрять проверки (lint, тесты, секреты) в `.githooks/`. Каталог должен быть защищён от записи посторонних — модифицированный хук может украсть секреты или внести вредоносный код.
- **Мониторинг размера репозитория:** Утилита `git-sizer` анализирует размер репозитория и выявляет узкие места (количество объектов, pack-файлов, веток). Регулярный запуск в CI/CD позволяет ловить несанкционированный рост (например, при добавлении больших бинарных файлов).
- **Фоновое обслуживание:** `git maintenance start` с планировщиком (`maintenance.<task>.schedule`) заменяет ручной `git gc`. В shared-средах (multiuser-серверы) фоновый `git gc` конкурирует за I/O — ограничивайте расписание через `cron`/`systemd` timers с nice-приоритетом.
- **Блокировки ODB:** `git gc` и `git maintenance run` используют разную семантику блокировки object database. Не запускайте их параллельно на одном репозитории — один из процессов не выполнит задачи.
- **Доверенные директории (`safe.directory`):** В Docker-контейнерах и CI-runners репозиторий часто владеет другой пользователь. `safe.directory '*'` разрешает всё, что опасно в shared-средах; ограничивайте конкретными путями, где возможно.
- **Конфигурация и версионирование:** Настройки, специфичные для репозитория (`blame.ignoreRevsFile`, `core.hooksPath`, `safe.directory`), не передаются при `git clone`. Добавляйте их в скрипт инициализации (`setup.sh`) или в `.gitconfig` репозитория (если совместимость с Git < 2.20 не требуется).
- **Секреты в конфиге:** Никогда не храните пароли/токены в `~/.gitconfig` — файл бэкапируется и синхронизируется. Используйте credential helpers или переменные окружения (`GIT_ASKPASS`, `GITHUB_TOKEN`, `GITLAB_TOKEN`).

### SRE-специфичные сценарии

**Безопасность и аудит (SRE):**
```bash
# Кто коммитил в sensitive-файлы за последний год (без merge-коммитов)
git shortlog -sne --no-merges --since="1 year ago" -- config/ secrets/ infra/

# Выявить "одиночных" авторов — подозрительные аккаунты
git shortlog -sn | awk '$1 == 1'
# → 1  service-account-123

# Отслеживание изменений инфраструктуры (sysadmin)
git shortlog -sn --no-merges -- infra/ansible/ terraform/
```

**CI/CD и pipeline-интеграция:**
```bash
# Генерация версии сборки в pipeline (describe)
VERSION=$(git describe --tags --dirty --always)
echo "Building version: $VERSION"

# Release notes по авторам между тегами
git shortlog -sne "$LAST_TAG..$CURRENT_TAG" > release_notes.txt

# Проверка активности разработчиков (SRE-мониторинг)
git shortlog -sn --since="7 days ago" | wc -l
# → 5 (активных разработчика за неделю)
```

**Проверка целостности history после rebase/merge (SRE):**
```bash
# Сохранить SHA перед rebase
BEFORE=$(git rev-parse HEAD)

# Выполните rebase
git rebase main

# Проверить, что цепочка коммитов не искажена
git range-diff $BEFORE...HEAD --no-color
# → Покажет, какие коммиты добавлены/удалены/переименованы
```

**Очистка CI-кэша и рабочих директорий (sysadmin):**
```bash
# Очистить всё, включая .gitignore-файлы (например, кэши сборок)
git clean -fdx

# Предпросмотр перед очисткой (всегда начинайте с -n)
git clean -fdxn
```

**Edge cases (SRE):**
- При аудите всегда используйте `--no-merges` — merge-коммиты могут маскировать реальных авторов.
- Для репозиториев с ботами (GitHub Actions, Dependabot) добавьте `--author="!bot"` или фильтр по email.
- `git shortlog` не учитывает `co-authored-by` по умолчанию — для полного учёта вклада используйте `--group=trailer:co-authored-by`.
- `git clean` необратим — удаленные файлы не попадают в `reflog`. В CI всегда начинайте с `git clean -fdn`.
- `git describe` без тегов и без `--always` завершится ошибкой — в CI используйте `--always` как fallback.
