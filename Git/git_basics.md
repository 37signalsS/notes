# Git — основы

## Определения

**Система контроля версий (СКВ)** — инструмент для отслеживания изменений в файлах, координации совместной работы и управления версиями исходного кода.

**Git** — распределённая система контроля версий (РСКВ), основанная на концепции **снимков (snapshots)**. В отличие от систем, хранящих разности (deltas), Git при каждом коммите сохраняет состояние всех файлов проекта. Если файл не менялся, Git просто создает ссылку на предыдущую версию.

**Типы СКВ:**
*   **Централизованные (ЦСКВ):** История хранится на одном сервере (SVN, Perforce). Недостаток — единая точка отказа и зависимость от сети.
*   **Распределённые (РСКВ):** Каждый разработчик имеет полную копию репозитория со всей историей (Git, Mercurial). Это обеспечивает автономность, скорость и надежность.

### Основные термины

*   **Репозиторий (Repository):** Хранилище всей истории проекта, метаданных и объектов. На локальном диске представлено скрытой директорией `.git`.
*   **Рабочий каталог (Working Tree):** Директория с актуальными файлами проекта, которые редактируются в данный момент.
*   **Индекс (Staging Area / Index):** Промежуточная область (дерево), где подготавливается следующий снимок (коммит).
*   **Коммит (Commit):** Снимок состояния проекта. Содержит изменения, хеш (SHA-1), автора, дату и ссылку на родительский коммит.
*   **Ветка (Branch):** Перемещаемый указатель на последний коммит в определенной цепочке изменений.
*   **HEAD:** Указатель на текущую ветку или конкретный коммит.
*   **SHA-1 (Hash):** Уникальный 40-символьный идентификатор любого объекта в Git, вычисляемый по его содержимому.

---

## Базовые концепции

### Архитектура "Трех деревьев"

Git управляет проектом через три основные области:
1.  **Рабочий каталог (Working Tree):** Файлы на диске (состояния `Modified`, `Untracked`).
2.  **Индекс (Staging Area):** Буфер между рабочим каталогом и репозиторием (`Staged`).
3.  **Репозиторий (HEAD):** Локальная база данных зафиксированных изменений (`Committed`).

### Жизненный цикл файлов

1.  **Untracked** — новый файл, о котором Git еще не знает.
2.  **Modified** — отслеживаемый файл изменен, но правки еще не в индексе.
3.  **Staged** — файл помечен для включения в следующий коммит (находится в индексе).
4.  **Committed** — изменения надежно зафиксированы в базе данных репозитория.

### Конфигурация и идентификация

Настройка данных автора и предпочтений является обязательным шагом после установки. Подробное руководство по всем уровням настроек, безопасности и оптимизации находится в файле **[Конфигурация Git (`git config`)](./git_configuration.md)**.

```bash
# Базовая настройка имени и email (глобально)
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# Просмотр всех действующих настроек с указанием источника
git config --list --show-origin
```

**Валидация:**
```bash
# Проверить текущие настройки
git config user.name
# → Your Name
git config user.email
# → your.email@example.com
```

### Игнорирование и атрибуты

*   **`.gitignore`**: Файл в корне проекта для исключения файлов из отслеживания (копируется при клонировании).
*   **`.git/info/exclude`**: Локальный список игнорирования, который не попадает в репозиторий (полезно для личных инструментов).
*   **`.gitattributes`**: Управляет обработкой файлов (окончания строк LF/CRLF, фильтры LFS, настройки слияния для конкретных расширений).

Подробнее о работе с игнорированием файлов — в файле **[Git Ignore](./git_ignore.md)**.

### Предварительные требования

*   **Версия Git:** Рекомендуется Git 2.30+ для полной поддержки современных команд (`git switch`, `git restore`).
*   **Установка:** Git должен быть установлен и доступен из командной строки (`git --version`).
*   **Начальная конфигурация:** Обязательно настройте `user.name` и `user.email` — без них коммиты не будут созданы.

---

## Практические сценарии

### Сценарий 1: Инициализация и клонирование

Создание нового репозитория или копирование существующего.

```bash
# Создание нового репозитория с явным указанием имени ветки
git init --initial-branch=main
# → Initialized empty Git repository in /path/to/repo/.git/

# Клонирование существующего репозитория
git clone https://github.com/user/repo.git
# → Cloning into 'repo'...
# → remote: Enumerating objects: 100, done.

# Клонирование с указанием имени директории
git clone https://github.com/user/repo.git my-project
```

**Валидация:**
```bash
# Проверить, что репозиторий создан
git status
# → On branch main
# → No commits yet

# Для клонированного репозитория
git log --oneline -3
# → abc1234 (HEAD -> main, origin/main) Latest commit
```

**Edge cases:**
*   Если директория уже содержит файлы, `git init` не удалит их — просто добавит контроль версий.
*   При клонировании в существующую непустую директорию Git выдаст ошибку: `fatal: destination path '.' already exists and is not an empty directory`.

### Сценарий 2: Базовый рабочий процесс (Workflow)

Стандартный цикл работы: редактирование → индексация → фиксация.

```bash
# 1. Просмотр статуса (краткий формат)
git status -s
# → M  modified_file.txt (в индексе, красный)
# →  M file_with_local_changes.txt (только в рабочем каталоге, зеленый)
# → ?? new_untracked_file.txt

# 2. Добавление изменений в индекс
git add <file>         # Добавить конкретный файл
git add .              # Добавить изменения из текущей директории и ниже
git add -A             # (All) Индексация ВСЕХ изменений (новые, измененные, удаленные во всем проекте)
git add -u             # (Update) Только измененные и удаленные отслеживаемые файлы (без новых)
git add -p             # (Patch) Интерактивный выбор конкретных частей (hunks) кода для индексации

# 3. Фиксация изменений
git commit -m "feat: add user authentication"
# → [main abc1234] feat: add user authentication
# →  1 file changed, 10 insertions(+)

# Исправление последнего коммита (добавление файлов или изменение сообщения)
git commit --amend -m "feat: add user auth and fix typo"
```

**Валидация:**
```bash
# Проверить, что коммит создан
git log --oneline -1
# → abc1234 feat: add user auth and fix typo

# Убедиться, что рабочий каталог чист
git status
# → On branch main
# → nothing to commit, working tree clean
```

**Edge cases:**
*   `git add .` не добавит файлы из `.gitignore` — для принудительного добавления используйте `git add -f <file>`.
*   `git commit` без `-m` откроет текстовый редактор (по умолчанию — Vim или тот, что настроен в `core.editor`).

### Сценарий 3: Анализ истории и сравнение

Просмотр истории изменений и сравнение различных состояний.

```bash
# Просмотр истории в виде графа
git log --oneline --graph --all
# → * abc1234 (HEAD -> main) Latest commit
# → * def5678 Previous commit
# → * * 9ab9012 (feature) Feature work

# Статистика изменений (какие файлы и сколько строк изменено)
git log --stat
# → commit abc1234...
# → Author: ...
# → 
# →     feat: add feature
# → 
# →  src/app.py | 10 ++++++++++
# →  1 file changed, 10 insertions(+)

# Сравнение рабочего каталога с индексом
git diff
# → diff --git a/file.txt b/file.txt
# → --- a/file.txt
# → +++ b/file.txt
# → @@ -1 +1 @@
# → -old content
# → +new content

# Сравнение индекса с последним коммитом
git diff --staged
# → (или git diff --cached)

# Сравнение рабочего каталога с последним коммитом
git diff HEAD
```

**Валидация:**
```bash
# Проверить количество коммитов
git rev-list --count HEAD
# → 42

# Просмотр конкретного коммита
git show abc1234
# → Покажет метаданные и diff коммита
```

**Edge cases:**
*   `git diff` без аргументов показывает только неиндексированные изменения.
*   Для сравнения с конкретной веткой: `git diff main..feature`.

### Сценарий 4: Управление файлами

Переименование, перемещение и удаление файлов с сохранением истории.

```bash
# Переименование или перемещение (автоматически индексирует действие)
git mv old_path.txt new_path.txt
# → Файл переименован и изменения в индексе

# Удаление из Git и с диска
git rm file.txt
# → rm 'file.txt'

# Удаление только из индекса (файл остается физически на диске)
git rm --cached sensitive_data.env
# → rm 'sensitive_data.env'
```

**Валидация:**
```bash
# Проверить статус после операций
git status
# → Changes to be committed:
# →   renamed:    old_path.txt -> new_path.txt
# →   deleted:    file.txt
```

**Edge cases:**
*   После `git rm --cached` файл станет `untracked` — добавьте его в `.gitignore`, чтобы он не появлялся в `git status`.
*   Для удаления директории используйте `git rm -r directory/`.

### Сценарий 5: Отмена изменений

Git предоставляет гибкие механизмы отмены на всех уровнях (рабочий каталог, индекс, коммиты). Подробный разбор всех методов переписывания истории и безопасного отката находится в файле **[Манипуляции с историей](./git_history_manipulation.md)**.

```bash
# 1. Извлечение файла из индекса (Unstage)
git restore --staged <file>
# → Файл перемещен из Staged в Modified

# 2. Отмена локальных правок в файле (Discard changes)
git restore <file>
# → Файл возвращен к состоянию последнего коммита

# 3. Откат к предыдущему коммиту (Reset)
# Внимание: переписывает локальную историю!
git reset --hard HEAD~1
# → HEAD is now at abc1234

# 4. Безопасная отмена через создание нового коммита (Revert)
# Рекомендуется для публичных веток
git revert <commit_hash>
# → [main def5678] Revert "feat: add feature"
```

**Валидация:**
```bash
# Проверить статус после отмены
git status
# → (зависит от выполненной операции)

# Просмотр истории для подтверждения
git log --oneline -5
```

**Edge cases:**
*   `git restore` необратим — изменения в рабочем каталоге теряются безвозвратно.
*   Для восстановления после `git reset --hard` используйте `git reflog` (подробнее в [Манипуляции с историей](./git_history_manipulation.md)).

### Сценарий 6: Работа с ветками и слиянием

Создание, переключение и удаление веток.

```bash
# Создание ветки
git branch feature/api

# Переход на новую ветку
git switch feature/api
# → Switched to branch 'feature/api'

# Создание и переход на новую ветку (одной командой)
git switch -c feature/api
# → Switched to a new branch 'feature/api'

# Слияние ветки в текущую
git merge feature/api
# → Updating abc1234..def5678
# → Fast-forward

# Удаление ветки (безопасное — только если слита)
git branch -d feature/api
# → Deleted branch feature/api.

# Принудительное удаление ветки
git branch -D feature/api
```

**Валидация:**
```bash
# Список всех веток
git branch -a
# → * main
# →   feature/api
# →   remotes/origin/main

# Проверить текущую ветку
git branch --show-current
# → main
```

**Edge cases:**
*   При слиянии могут возникнуть конфликты — Git пометит файлы маркерами `<<<<<<<`, `=======`, `>>>>>>>`. Подробнее о разрешении конфликтов — в [Устранение неполадок Git](./git_troubleshooting.md).
*   Нельзя удалить текущую ветку — сначала переключитесь на другую.

### Сценарий 7: Удаленные репозитории и синхронизация

Работа с удаленными репозиториями для совместной разработки.

Подробные механизмы и стратегии описаны в файле **[Синхронизация репозиториев](./git_synchronization.md)**.

```bash
# Список удаленных серверов
git remote -v
# → origin  https://github.com/user/repo.git (fetch)
# → origin  https://github.com/user/repo.git (push)

# Добавление удаленного репозитория
git remote add origin https://github.com/user/repo.git

# Получение данных без изменения рабочего каталога
git fetch origin
# → remote: Enumerating objects: 5, done.
# → Unpacking objects: 100% (3/3), done.

# Получение и слияние (fetch + merge)
git pull origin main
# → Updating abc1234..def5678
# → Fast-forward

# Отправка изменений
git push origin main
# → To https://github.com/user/repo.git
# →   abc1234..def5678  main -> main

# Отправка с защитой от перезаписи чужой истории
git push origin feature/api --force-with-lease
```

**Валидация:**
```bash
# Проверить связь локальной и удаленной ветки
git status
# → On branch main
# → Your branch is up to date with 'origin/main'.

# Просмотр различий между локальной и удаленной ветками
git log main..origin/main --oneline
# → (пусто, если ветки синхронизированы)
```

**Edge cases:**
*   При конфликте при `git pull` необходимо разрешить конфликты и выполнить `git add` + `git commit`.
*   `--force-with-lease` безопаснее `--force` — он отменит push, если удаленная ветка была изменена другим участником.

### Сценарий 8: Работа с тегами (Tags)

Теги используются для маркировки важных точек в истории (релизов).

```bash
# Создание легковесного тега (просто указатель)
git tag v1.0.0-light
# → (без вывода при успехе)

# Создание аннотированного тега (с сообщением, датой и автором — рекомендуется)
git tag -a v1.0.0 -m "Release version 1.0.0"
# → (без вывода при успехе)

# Просмотр данных тега
git show v1.0.0
# → tag v1.0.0
# → Tagger: Your Name <email>
# → ...
# → commit abc1234...

# Отправка тегов на сервер (по умолчанию push их не отправляет)
git push origin v1.0.0        # Конкретный тег
git push origin --tags         # Все локальные теги
```

**Валидация:**
```bash
# Список всех тегов
git tag -l
# → v1.0.0
# → v1.0.0-light

# Проверить, что тег указывает на правильный коммит
git rev-parse v1.0.0
# → abc1234...
```

**Edge cases:**
*   Легковесные теги не содержат метаданных — для релизов всегда используйте аннотированные (`-a`).
*   Теги не отправляются автоматически при `git push` — требуется явная отправка.

### Сценарий 9: Бинарный поиск ошибок (Bisect)

Метод бинарного поиска для нахождения коммита, внесшего баг.

```bash
# Начало поиска
git bisect start

# Отметить текущую версию как сломанную
git bisect bad HEAD           # Текущая версия сломана

# Отметить рабочую версию
git bisect good v0.9.0        # В этой версии все работало

# Git будет переключать коммиты автоматически. На каждом шаге проверяйте код:
git bisect good               # Если баг не найден
git bisect bad                # Если баг воспроизводится

# После нахождения виновника вернитесь в исходное состояние
git bisect reset
# → Switched to branch 'main'
```

**Валидация:**
```bash
# Git выведет результат поиска
# → abc1234 is the first bad commit
# → commit abc1234...
# → Author: ...
# → 
# →     feat: introduce bug
```

**Edge cases:**
*   Для автоматизации можно использовать `git bisect run <script>` — скрипт должен возвращать 0 (good) или 1 (bad).
*   При пропуске коммита используйте `git bisect skip`.

### Сценарий 10: Разрешение конфликтов слияния

Когда автоматическое слияние невозможно, требуется ручное разрешение.

```bash
# 1. Попытка слияния
git merge feature-branch
# → CONFLICT (content): Merge conflict in file.txt
# → Automatic merge failed; fix conflicts and then commit the result.

# 2. Просмотр конфликтующих файлов
git status
# → Unmerged paths:
# →   both modified:   file.txt

# 3. Разрешение конфликта (редактирование файла)
# Файл содержит маркеры:
# <<<<<<< HEAD
# ваши изменения
# =======
# изменения из ветки
# >>>>>>> feature-branch

# 4. Индексация разрешенного файла
git add file.txt

# 5. Завершение слияния
git commit -m "merge: resolve conflict in file.txt"
```

**Валидация:**
```bash
# Проверить, что конфликтов больше нет
git status
# → All conflicts fixed but you are still running a merge.
# →   (use "git commit" to conclude merge)
```

**Edge cases:**
*   Для отмены слияния используйте `git merge --abort`.
*   Для просмотра конфликтов в удобном виде: `git diff --name-only --diff-filter=U`.

---

## Оптимизация в пайплайнах CI/CD

В автоматизированных системах полная загрузка истории часто избыточна.

*   **Shallow Clone (Неглубокое клонирование):**
    Загружает только последние N коммитов. Значительно ускоряет `clone` в больших репозиториях.
    ```bash
    git clone --depth 1 https://github.com/user/repo.git
    # → Cloning into 'repo'...
    ```
*   **Sparse Checkout (Разреженное извлечение):**
    Позволяет извлекать только определенные директории или файлы из огромного монорепозитория.
    ```bash
    git clone --filter=blob:none --no-checkout https://github.com/user/repo.git
    cd repo
    git sparse-checkout set path/to/needed/dir
    git checkout
    ```

**Валидация:**
```bash
# Проверить глубину клонирования
git rev-list --count HEAD
# → 1 (для --depth 1)

# Проверить sparse checkout
git sparse-checkout list
# → path/to/needed/dir
```

---

## Troubleshooting

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: not a git repository` | Команда выполнена вне репозитория. | Выполните `git init` или перейдите в директорию репозитория. |
| `Please tell me who you are` | Не настроены `user.name` и `user.email`. | Выполните `git config --global user.name` и `git config --global user.email`. |
| `fatal: not a valid object name` | Указан несуществующий коммит или ветка. | Проверьте хэш или имя ветки через `git log` / `git branch`. |
| `error: failed to push some refs` | Удаленная ветка содержит коммиты, которых нет локально. | Выполните `git pull --rebase` перед `git push`. |
| `CONFLICT (content): Merge conflict` | Автоматическое слияние невозможно. | Разрешите конфликты вручную, выполните `git add` и `git commit`. |
| `Your local changes would be overwritten` | Переключение ветки приведет к потере изменений. | Используйте `git stash` или `git commit` перед переключением. |
| `fatal: refusing to merge unrelated histories` | Репозитории имеют независимые истории. | Используйте `git pull --allow-unrelated-histories` (осторожно). |

### Диагностика

```bash
# Проверить состояние репозитория
git status
# → Покажет текущую ветку, измененные файлы, конфликты

# Проверить конфигурацию
git config --list --show-origin
# → Покажет все настройки с указанием источника

# Проверить целостность репозитория
git fsck
# → Проверка объектов и ссылок

# Просмотр истории перемещений HEAD
git reflog
# → Полезно для восстановления после reset
```

---

## Best Practices

1.   **Частые коммиты:** Делайте коммиты часто — это упрощает откат и поиск ошибок.
2.   **Атомарные коммиты:** Каждый коммит должен содержать одно логическое изменение.
3.   **Описательные сообщения:** Используйте [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `test:`, `chore:`).
4.   **Не коммитьте сгенерированные файлы:** Добавьте в `.gitignore` зависимости (`node_modules/`), артефакты сборки, секреты.
5.   **Pull перед Push:** Всегда выполняйте `git pull` перед `git push` в общих ветках.
6.   **Используйте ветки:** Создавайте отдельные ветки для каждой задачи или бага.
7.   **Настройте `.gitignore` заранее:** Это предотвратит случайный коммит ненужных файлов.
8.   **Проверяйте перед коммитом:** Используйте `git diff --staged` для просмотра индексированных изменений.

---

## Дополнительная информация

### Официальные ресурсы
*   **[Git Documentation](https://git-scm.com/doc)** — справочник по всем командам.
*   **[Pro Git Book](https://git-scm.com/book/ru/v2)** — наиболее полное руководство по архитектуре.
*   **[Visualizing Git Concepts](https://git-school.github.io/visualizing-git/)** — интерактивная визуализация команд.

### См. также
*   [Ветвление в Git](./git_branching.md) — создание и переключение веток, merge vs rebase.
*   [Git Stash](./git_stash.md) — временное припрятывание изменений без коммита.
*   [Git Worktree](./git_worktree.md) — параллельная работа с несколькими ветками одновременно.
*   [Git Tags](./git_tags.md) — разметка версий и семантическое версионирование.
*   [Современные команды](./git_commands_modern.md) — restore, switch, clean, describe (замена checkout).
*   [Внутреннее устройство Git](./git_internals.md) — детали объектной модели.
*   [Конфигурация Git](./git_configuration.md) — подробная настройка `.gitconfig`.
*   [Инструменты TUI и CLI](./git_tools.md) — обзор Lazygit, Delta и других утилит.
*   [Манипуляции с историей](./git_history_manipulation.md) — Rebase, Cherry-pick и фильтрация.
*   [Специальные файлы Git](./git_special_files_overview.md) — обзор `.gitattributes`, `.gitmodules`.
*   [Устранение неполадок Git](./git_troubleshooting.md) — разрешение конфликтов и восстановление данных.
*   [Git Ignore](./git_ignore.md) — подробное руководство по игнорированию файлов.
