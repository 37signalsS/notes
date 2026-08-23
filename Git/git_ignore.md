# Игнорирование файлов в Git

## Определения

**`.gitignore`** — зарезервированный конфигурационный файл, содержащий шаблоны (patterns) путей к файлам и директориям, которые Git должен исключить из отслеживания и индексации.

**Игнорируемые файлы** — ресурсы проекта, не подлежащие версионированию. К ним относятся:
*   Временные файлы ОС (`.DS_Store`, `Thumbs.db`).
*   Специфические настройки IDE и редакторов (`.idea/`, `.vscode/`).
*   Артефакты сборки и бинарные файлы (`bin/`, `dist/`, `*.exe`).
*   Зависимости пакетов (`node_modules/`, `vendor/`).
*   Чувствительные данные и секреты (`.env`, `*.pem`, `vault_pass.txt`).

---

## Базовые концепции

### Синтаксис паттернов и нюансы

Git использует расширенный синтаксис glob-шаблонов. С версии 2.50+ паттерны с двойной звездочкой (`**`) значительно оптимизированы и рекомендуются для рекурсивных правил.

| Паттерн | Область действия | Технический нюанс |
| :--- | :--- | :--- |
| `temp/` | Директория `temp` и её содержимое | Слэш в конце ограничивает правило только директориями. |
| `/TODO` | Файл `TODO` только в корне | Ведущий слэш привязывает паттерн к конкретному `.gitignore`. |
| `*.log` | Все файлы `.log` рекурсивно | Без ведущего слэша ищет совпадения на любом уровне вложенности. |
| `!important.log` | Исключение из игнорирования | **Важно:** Не работает, если родительская папка уже проигнорирована. |
| `docs/**/*.txt` | Файлы `.txt` во всех подпапках `docs` | Двойная звездочка — стандарт для рекурсии в 2026 году. |
| `**/build/` | Директории `build` на любом уровне вложенности | Универсальный паттерн для игнорирования артефактов сборки. |
| `!src/**/build/` | Исключение из правила | Отменяет игнорирование для конкретного пути. |

### Иерархия и приоритетность

Git проверяет правила в следующем порядке (последнее найденное правило побеждает):
1.  **`.gitignore` в поддиректориях**: Имеют наивысший приоритет для файлов внутри своего пути.
2.  **`.gitignore` в корне репозитория**: Основной список исключений проекта.
3.  **`.git/info/exclude`**: Локальные правила для конкретной копии репозитория. Физически этот файл располагается в общей директории `$GIT_COMMON_DIR` (а не в приватной `$GIT_DIR` конкретного дерева), поэтому его правила **разделяются между всеми рабочими деревьями (worktrees)** одного репозитория. Это поведение актуально для всех версий Git с поддержкой worktree; официальная документация явно закрепила этот факт начиная с Git 2.52 (2026).
4.  **Глобальный файл (`core.excludesFile`)**: Обычно `~/.gitignore_global`. Применяется ко всем проектам пользователя на машине.

### Технические ограничения

*   **Лимит размера**: Начиная с Git 2.46, система может отклонять или игнорировать чрезмерно большие файлы `.gitignore` (сотни килобайт) во избежание деградации производительности при обходе дерева.
*   **Отслеживаемые файлы**: Правила игнорирования применяются только к файлам в состоянии `Untracked`. Если файл уже закоммичен, запись в `.gitignore` не удалит его из истории.

### Предварительные требования

*   **Версия Git:** Рекомендуется Git 2.46+ для полной поддержки современных функций игнорирования.
*   **Базовые знания:** Понимание жизненного цикла файлов в Git (Untracked, Modified, Staged, Committed). Подробнее — в [Основы Git](./git_basics.md).

---

## Практические сценарии

### Сценарий 1: Отладка "невидимых" правил

Если файл не добавляется или, наоборот, игнорируется вопреки ожиданиям, используйте `check-ignore`:

```bash
# Показать файл, номер строки и правило, которое сработало
git check-ignore -v config/settings.local.php
# → .gitignore:42:*.local.php  config/settings.local.php

# Проверить несколько файлов одновременно
git check-ignore -v src/*.log config/*.tmp
# → .gitignore:10:*.log  src/app.log

# Проверить все игнорируемые файлы в директории
git check-ignore *
```

**Валидация:**
```bash
# Если файл НЕ игнорируется — команда вернет пустой вывод и код 1
git check-ignore -v file.txt
# → (пустой вывод)
echo $?
# → 1

# Если файл игнорируется — код возврата 0
git check-ignore -v file.log
# → .gitignore:1:*.log  file.log
echo $?
# → 0
```

**Edge cases:**
*   Правило `!important.log` не сработает, если родительская директория уже проигнорирована (например, `logs/`).
*   `check-ignore` не показывает правила из `.git/info/exclude` и глобального `.gitignore` — используйте флаг `--no-index` для проверки без индекса.

### Сценарий 2: Принудительное обновление индекса (Refresh)

Классическое решение ситуации, когда вы добавили правила в `.gitignore`, но Git продолжает отслеживать старые файлы:

```bash
# 1. Удалить всё из индекса (не с диска!)
git rm -r --cached .
# → rm 'file1.txt'
# → rm 'file2.log'

# 2. Добавить всё заново (индекс пересчитается с учетом .gitignore)
git add .
# → (файлы из .gitignore не будут добавлены)

# 3. Зафиксировать изменения
git commit -m "chore: refresh ignore rules according to updated .gitignore"
# → [main abc1234] chore: refresh ignore rules according to updated .gitignore
# →  5 files changed, 5 deletions(-)
```

**Валидация:**
```bash
# Проверить, что файлы из .gitignore больше не отслеживаются
git status
# → On branch main
# → nothing to commit, working tree clean

# Проверить, что файлы физически остались на диске
ls -la file.log
# → -rw-r--r--  1 user  staff  123 Aug 23 14:00 file.log
```

**Edge cases:**
*   Команда `git rm -r --cached .` удаляет файлы только из индекса, не с диска.
*   Если после `git add .` файлы всё ещё в индексе — проверьте синтаксис `.gitignore` (нет ли лишних пробелов, правильный ли формат).

### Сценарий 3: Скрытие локальных правок без удаления файла

Для файлов, которые должны быть в репозитории (например, `web.config`), но требуют локальных правок:
*   **`skip-worktree`**: Рекомендуемый вариант для SRE. Сохраняется при `git checkout` и переключении веток.
*   **`assume-unchanged`**: Более "слабый" флаг, сбрасывается при операциях вроде `git reset --hard`.

```bash
# Установить флаг (Git перестанет замечать изменения на диске)
git update-index --skip-worktree config/database.yml
# → (без вывода при успехе)

# Проверить список файлов с этим флагом (статус 'S')
git ls-files -v | grep ^S
# → S config/database.yml

# Снять флаг (вернуть отслеживание)
git update-index --no-skip-worktree config/database.yml
# → (без вывода при успехе)

# Альтернатива — assume-unchanged (менее надежный)
git update-index --assume-unchanged config/settings.local.yml
git ls-files -v | grep ^h
# → h config/settings.local.yml

# Снять assume-unchanged
git update-index --no-assume-unchanged config/settings.local.yml
```

**Валидация:**
```bash
# После установки skip-worktree изменения не видны в статусе
echo "test" >> config/database.yml
git status
# → On branch main
# → nothing to commit, working tree clean
```

**Edge cases:**
*   `skip-worktree` сохраняется при `git checkout` и переключении веток.
*   `assume-unchanged` сбрасывается при `git reset --hard` — Git может потерять локальные изменения.
*   Эти флаги локальные — не распространяются на других разработчиков.

### Сценарий 4: Создание базового .gitignore для проекта

Создание комплексного `.gitignore` для типового проекта:

```gitignore
# === OS generated files ===
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
Thumbs.db
ehthumbs.db
Desktop.ini

# === IDE / Editor ===
.idea/
.vscode/
*.swp
*.swo
*~
.project
.settings/
*.sublime-workspace

# === Dependencies ===
node_modules/
vendor/
.venv/
venv/
__pycache__/
*.pyc

# === Build artifacts ===
dist/
build/
target/
*.o
*.exe
*.dll
*.so

# === Environment and secrets ===
.env
.env.local
.env.*.local
*.pem
*.key
secrets/

# === Logs ===
*.log
logs/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# === Testing ===
coverage/
.nyc_output/

# === Temporary files ===
tmp/
temp/
*.tmp
*.bak
```

**Валидация:**
```bash
# Проверить, что .gitignore работает корректно
touch .DS_Store test.log node_modules/test.js
git status
# → On branch main
# → Untracked files:
# →   .gitignore
# → (другие файлы не видны — работает игнорирование)

# Очистить тестовые файлы
rm .DS_Store test.log
rm -rf node_modules/
```

**Edge cases:**
*   Файлы, уже отслеживаемые Git, не будут проигнорированы — сначала выполните `git rm --cached`.
*   `.gitignore` должен быть закоммичен, чтобы правила применялись у всех разработчиков.

### Сценарий 5: Использование .git/info/exclude

Локальные правила игнорирования, которые не попадают в репозиторий (полезно для личных настроек IDE):

```bash
# Открыть файл локальных исключений
nano .git/info/exclude

# Или добавить правила через командную строку
echo "# Personal ignores" >> .git/info/exclude
echo ".vscode/" >> .git/info/exclude
echo "*.personal-notes.md" >> .git/info/exclude
echo "experiments/" >> .git/info/exclude
```

**Содержимое `.git/info/exclude`:**
```gitignore
# Личные настройки IDE
.vscode/
*.personal-notes.md

# Экспериментальные директории
experiments/
playground/

# Локальные конфиги
.env.local.private
```

**Валидация:**
```bash
# Проверить, что файлы игнорируются
touch .vscode/settings.json experiments/test.py
git status
# → (файлы не видны в untracked)

# Убедиться, что файл не в репозитории
git ls-files --error-unmatch .git/info/exclude
# → fatal: pathspec '.git/info/exclude' did not match any file(s) known to git
```

**Edge cases:**
*   Файл `.git/info/exclude` не коммитится — это локальные настройки.
*   Этот файл разделяется между всеми worktrees одного репозитория, так как физически находится в общей директории `$GIT_COMMON_DIR` (официально документировано начиная с Git 2.52 / 2026).

### Сценарий 6: Глобальный .gitignore

Настройка глобального игнорирования для всех проектов на машине:

```bash
# Создать глобальный файл игнорирования
touch ~/.gitignore_global

# Добавить системные файлы macOS/Linux
cat >> ~/.gitignore_global << 'EOF'
# macOS
.DS_Store
.AppleDouble
.LSOverride
._*

# Linux
*~
.fuse_hidden*
.directory
.Trash-*

# Windows
Thumbs.db
ehthumbs.db
Desktop.ini
RECYCLER/
EOF

# Указать Git использовать этот файл
git config --global core.excludesFile ~/.gitignore_global
```

**Валидация:**
```bash
# Проверить настройку
git config --global core.excludesFile
# → /Users/username/.gitignore_global

# Проверить, что глобальные правила работают
cd /tmp && git init test-global-ignore && cd test-global-ignore
touch .DS_Store test.txt
git status
# → Untracked files:
# →   test.txt
# → (.DS_Store не виден — работает глобальное игнорирование)
cd .. && rm -rf test-global-ignore
```

**Edge cases:**
*   Глобальный `.gitignore` применяется ко всем репозиториям на машине.
*   Путь к файлу можно изменить через `git config --global core.excludesFile`.

---

## Связанные механизмы игнорирования в пайплайнах

При построении CI/CD процессов важно синхронизировать `.gitignore` с другими инструментами:
*   **`.dockerignore`**: Исключает файлы из контекста сборки Docker-образа. Рекомендуется дублировать в него содержимое `.gitignore`, чтобы избежать попадания `.git/`, локальных зависимостей и секретов в слои образа.
*   **`.helmignore`**: Аналог для Helm-чартов. Исключает временные файлы и документацию из состава релиза Kubernetes.

---

## Утечка секретов и очистка истории

Если проигнорированный файл (например, `.env` с ключами) был случайно закоммичен до добавления в `.gitignore`:
1.  **Недостаточно** просто добавить его в `.gitignore` и сделать `rm --cached`. Секрет останется в истории коммитов.
2.  **Решение**: Используйте `git-filter-repo` (рекомендуемая замена BFG) для полного удаления файла из всей истории репозитория.

**Полное решение:**

```bash
# 1. Установить git-filter-repo
pip install git-filter-repo

# 2. Удалить файл из всей истории
git filter-repo --path secrets.env --invert-paths
# → (перезапись истории)

# 3. Добавить файл в .gitignore (чтобы не повторить ошибку)
echo "secrets.env" >> .gitignore
git add .gitignore
git commit -m "chore: add secrets.env to gitignore"

# 4. Принудительный push (требуется согласие команды!)
git push origin --force --all
# → (отправка перезаписанной истории)
```

**Валидация:**
```bash
# Проверить, что файл отсутствует в истории
git log --all --full-history -- secrets.env
# → (пусто — файл удален из истории)

# Проверить, что файл игнорируется
git check-ignore -v secrets.env
# → .gitignore:1:secrets.env  secrets.env
```

**Edge cases:**
*   После `git filter-repo` все коллеги должны переклонировать репозиторий.
*   Для предотвращения утечек используйте pre-commit хуки (`git-secrets`, `gitleaks`).
*   Подробнее об очистке истории — в [Устранение неполадок Git](./git_troubleshooting.md).

---

## Troubleshooting

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Файл не игнорируется | Файл уже отслеживается Git. | Выполните `git rm --cached <file>`. |
| Правило `!` не работает | Родительская директория уже проигнорирована. | Исключите родительскую директорию, затем включите нужный путь. |
| `.gitignore` не работает после создания | Файлы уже в индексе. | Выполните `git rm -r --cached . && git add .`. |
| Конфликт с глобальным `.gitignore` | Правила в `~/.gitignore_global` переопределяют локальные. | Проверьте глобальные настройки: `git config --global core.excludesFile`. |
| Файл игнорируется в IDE, но не в Git | IDE использует собственные настройки исключений. | Настройте `.gitignore` отдельно от IDE. |

### Диагностика

```bash
# Проверить, какое правило игнорирует файл
git check-ignore -v path/to/file
# → .gitignore:10:*.log  path/to/file.log

# Проверить все источники игнорирования
git check-ignore -v --no-index path/to/file
# → .git/info/exclude:5:*.tmp  path/to/file.tmp

# Проверить глобальные настройки
git config --global core.excludesFile
# → /Users/username/.gitignore_global

# Просмотреть содержимое глобального .gitignore
cat ~/.gitignore_global
```

---

## Best Practices

1.  **Создайте `.gitignore` в начале проекта** — это предотвратит случайный коммит ненужных файлов.
2.  **Используйте шаблоны** — база [GitHub gitignore](https://github.com/github/gitignore) содержит готовые шаблоны для большинства языков и фреймворков.
3.  **Дублируйте правила в `.dockerignore`** — синхронизируйте исключения для CI/CD.
4.  **Используйте `.git/info/exclude`** для личных настроек, которые не должны влиять на команду.
5.  **Настройте глобальный `.gitignore`** для системных файлов (`.DS_Store`, `Thumbs.db`).
6.  **Не коммитьте секреты** — используйте `.env.example` вместо `.env`, добавьте `.env` в `.gitignore`.
7.  **Проверяйте `.gitignore` перед первым коммитом** — `git status` покажет, какие файлы будут добавлены.
8.  **Документируйте неочевидные правила** — комментируйте специфичные исключения в `.gitignore`.

---

## Дополнительная информация

### Официальные ресурсы
*   **[Git Doc: gitignore](https://git-scm.com/docs/gitignore)** — официальная спецификация.
*   **[GitHub Templates](https://github.com/github/gitignore)** — база эталонных шаблонов.

### См. также
*   [Обзор специальных файлов](./git_special_files_overview.md) — SSoT для `.git*` файлов.
*   [Атрибуты файлов (.gitattributes)](./git_attributes.md) — отличия в логике обработки.
*   [Основы Git](./git_basics.md) — жизненный цикл файлов.
*   [Устранение неполадок Git](./git_troubleshooting.md) — разрешение конфликтов и очистка истории.
*   [Конфигурация Git](./git_configuration.md) — настройка `core.excludesFile`.
*   [Прочие соглашения Git](./git_other_conventions.md) — `.gitkeep` и другие соглашения.
