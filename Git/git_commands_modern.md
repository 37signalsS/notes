# Git — современные команды (restore, switch, clean, describe)

## Определения

**git restore** — команда для восстановления файлов из индекса или из конкретного коммита. Заменяет части `git checkout` и `git reset` (Git 2.23+).

**git switch** — команда для переключения между ветками. Заменяет `git checkout` для переключений (Git 2.23+).

**git clean** — команда для удаления неотслеживаемых файлов из рабочего дерева.

**git describe** — команда для генерации человекочитаемого имени версии на основе ближайшего тега.

**git shortlog** — команда для генерации отчёта по авторам коммитов.

**git range-diff** — команда для сравнения двух версий цепочки коммитов (полезна при rebase).

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

### Best Practices

1. **Используйте `git restore`** вместо `git checkout --` для ясности.
2. **Используйте `git switch`** вместо `git checkout` для переключений.
3. **Всегда делайте `-n` перед `git clean`** — чтобы понять, что будет удалено.
4. **Используйте `git describe --tags`** в CI для генерации версий.
5. **Комбинируйте `shortlog --no-merges`** для точной статистики.

---

## Дополнительная информация

### Связанные темы

- [Git Basics](./git_basics.md) — архитектура трёх деревьев (HEAD, index, working tree).
- [Git History Manipulation](./git_history_manipulation.md) — reset, revert, rebase (старые альтернативы restore/switch).
- [Git Tags](./git_tags.md) — describe и семантическое версионирование.
- [Конфигурация Git](./git_configuration.md) — настройка clean.exclude, restore.useBuiltin.

### Официальные ресурсы

- **Git Restore Documentation:** [git-scm.com/docs/git-restore](https://git-scm.com/docs/git-restore)
- **Git Switch Documentation:** [git-scm.com/docs/git-switch](https://git-scm.com/docs/git-switch)
- **Git Clean Documentation:** [git-scm.com/docs/git-clean](https://git-scm.com/docs/git-clean)
- **Git Describe Documentation:** [git-scm.com/docs/git-describe](https://git-scm.com/docs/git-describe)
- **Git Shortlog Documentation:** [git-scm.com/docs/git-shortlog](https://git-scm.com/docs/git-shortlog)
