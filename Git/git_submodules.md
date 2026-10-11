# Git Submodules — подмодули

**Актуально для:** Git 2.45+ (версии функций и CVE-исправлений указаны явно)

## Определения

**Git Submodule (Подмодуль)** — полноценный Git-репозиторий, вложенный в другой репозиторий (суперпроект, superproject) в качестве подкаталога. Позволяет использовать сторонний код, общие библиотеки или компоненты инфраструктуры, сохраняя историю коммитов каждого проекта независимой.

**`.gitmodules`** — конфигурационный файл в корне рабочего дерева (синтаксис совместим с `git-config`), описывающий маппинг имён подмодулей к путям и URL удалённых репозиториев. Не может быть симлинком: Git отказывается проверять дерево, в котором `.gitmodules` — символическая ссылка (проверка безопасности).

**Gitlink** — запись в индексе суперпроекта (режим `160000`), содержащая только SHA-1 коммита подмодуля, а не содержимое файлов.

**Detached HEAD (подмодуль)** — состояние, при котором HEAD подмодуля указывает на конкретный коммит по хешу, а не на ветку. Стандартное состояние после `git submodule update`.

**Superproject (суперпроект)** — родительский репозиторий, содержащий gitlink-записи подмодулей.

---

## Основные концепции

### Механизм отслеживания (SHA-1 Pinning)

Git не отслеживает содержимое файлов внутри подмодуля напрямую. Родительский репозиторий хранит gitlink — конкретный SHA-1 коммита:
- Любое изменение версии подмодуля требует явного `git add <путь>` в родительском проекте.
- Это обеспечивает воспроизводимость: каждый коммит суперпроекта точно знает, какую версию зависимости он использовал.
- Следствие для CI: сборка воспроизводима только если коммит из gitlink существует в удалённом репозитории подмодуля. Забытый `git push` внутри подмодуля ломает сборки коллег (`fatal: reference is not a tree`).

### Уровни конфигурации

Работа с подмодулями опирается на две зоны настроек:
1. **Shared Configuration (`.gitmodules`):** Общие настройки (URL, путь, ветка), которые коммитятся и доступны всей команде. Это «декларация» зависимостей.
2. **Local Configuration (`.git/config`):** Локальная регистрация. Команда `git submodule init` копирует `submodule.<name>.url` и `submodule.<name>.update` из `.gitmodules` в локальный конфиг. Это позволяет разработчику выбирать, какие именно подмодули инициализировать, и переопределять URL локально (например, на форк).

`git submodule init` не изменяет уже существующие записи в `.git/config` — локальные правки URL сохраняются. Если при инициализации не заданы пути и настроен `submodule.active`, инициализируются только «активные» подмодули; иначе — все.

### Формат файла `.gitmodules`

Файл использует синтаксис INI с секциями `[submodule "<путь>"]`:

```ini
[submodule "vendor/logger"]
    path = vendor/logger
    url = https://github.com/org/logger.git
    branch = main
```

Ключи (gitmodules(5)):

| Ключ | Обязательный | Назначение |
| :--- | :--- | :--- |
| `submodule.<name>.path` | да | Путь относительно корня рабочего дерева; не должен оканчиваться `/`; все пути уникальны |
| `submodule.<name>.url` | да | URL для клонирования: абсолютный или относительный (`./`, `../` — относительно origin суперпроекта) |
| `submodule.<name>.update` | нет | Процедура обновления по умолчанию: `checkout`, `rebase`, `merge` или `none`. Значение `!command` в `.gitmodules` запрещено (безопасность) — только в `.git/config` |
| `submodule.<name>.branch` | нет | Ветка для отслеживания (`git submodule update --remote`). По умолчанию — remote HEAD. Специальное значение `.` — ветка с тем же именем, что и текущая ветка суперпроекта |
| `submodule.<name>.fetchRecurseSubmodules` | нет | Рекурсивный fetch вложенных подмодулей при `git fetch`/`git pull`; переопределяется флагом `--[no-]recurse-submodules` |
| `submodule.<name>.ignore` | нет | Что считать «изменённым» в `status`/`diff`/`log`: `all`, `dirty`, `untracked`, `none` (по умолчанию). Не влияет на команды `git submodule` |
| `submodule.<name>.shallow` | нет | `true` — подмодуль клонируется как shallow (depth 1), если явно не запрошен полный клон |

Имя секции (`<name>`) по умолчанию совпадает с путём; задаётся явно через `git submodule add --name <name>`. Любые параметры секции копируются в `.git/config` при инициализации (кроме `!<command>`).

### Процедуры обновления

`git submodule update` приводит подмодуль к состоянию, ожидаемому суперпроектом. Приоритет: опция командной строки > `submodule.<name>.update` в `.git/config` > `checkout`:

- **`checkout`** (по умолчанию) — коммит из gitlink проверяется на detached HEAD; с `--force` локальные изменения подмодуля отбрасываются.
- **`rebase`** — текущая ветка подмодуля ребейзится на записанный коммит.
- **`merge`** — записанный коммит мержится в текущую ветку подмодуля.
- **`none`** — подмодуль не обновляется (нельзя задать в командной строке).
- **`!<custom-command>`** — произвольная команда с коммитом как аргументом; работает ТОЛЬКО из `.git/config` (не из `.gitmodules` и не с CLI) — защита от выполнения кода из чужого репозитория.

### Состояние Detached HEAD и префиксы status

После `git submodule update` подмодули находятся в **Detached HEAD** (привязаны к конкретному хешу, а не к ветке). Для внесения изменений необходимо явно выполнить `git checkout <branch>`.

`git submodule status` показывает SHA-1 проверенного коммита, путь и вывод `git describe` для него. Префиксы:
- `-` — подмодуль не инициализирован;
- `+` — проверенный коммит не совпадает с записанным в индексе суперпроекта;
- `U` — конфликт слияния в подмодуле.

Флаги: `--cached` — SHA-1 из индекса суперпроекта (а не из worktree); `--recursive` — вложенные подмодули. Если настроен `branch` в `.gitmodules`, Git автоматически переключает подмодуль на указанную ветку при выполнении `git submodule update --remote`.

### Внутреннее устройство (`.git/modules/`)

В современных версиях Git служебная директория `.git` внутри подмодуля является текстовым файлом-ссылкой (gitfile). Сами данные объектов и история хранятся в родительском репозитории по пути `.git/modules/<имя_подмодуля>`. Это защищает историю подмодуля от случайного удаления при манипуляциях с рабочим каталогом.

`git submodule absorbgitdirs` переносит встроенные `.git`-директории подмодулей в общее хранилище `.git/modules/` (для подмодулей, добавленных старыми версиями Git). С Git 2.35 `git submodule deinit` сам при необходимости конвертирует подмодуль в absorbed-форму.

### Взаимодействие с Worktree

Подмодули в новом рабочем дереве (`git worktree add`) не инициализируются автоматически. После создания worktree требуется отдельно выполнить:
```bash
git submodule update --init --recursive
```
При этом `git worktree remove` для деревьев с подмодулями может потребовать флага `--force`.

### Взаимодействие с fetch/pull

`git fetch` и `git pull` не обновляют содержимое подмодулей автоматически. Рекурсивный fetch вложенных подмодулей управляется ключом `submodule.<name>.fetchRecurseSubmodules` (в `.gitmodules` или `.git/config`) и флагом `--[no-]recurse-submodules`.

### Взаимодействие с Git Hooks

Хуки родительского репозитория не распространяются на подмодули автоматически. Каждый подмодуль имеет собственную директорию `.git/hooks` (или ссылку на нее), и для автоматизации процессов в подмодулях требуется настраивать хуки отдельно внутри каждого подмодуля или использовать скрипты, запускаемые через `git submodule foreach`.

### Взаимодействие со stash

`git stash` работает только с рабочим деревом суперпроекта и не затрагивает подмодули — отдельного флага `--recurse-submodules` у `git stash` нет. Чтобы спрятать изменения внутри подмодулей, выполните stash в каждом из них:
```bash
git submodule foreach --recursive 'git stash'
```

### Сравнение с альтернативами

| Критерий | Git Submodule | Git Subtree | `requirements.yml` (Ansible) |
| :--- | :--- | :--- | :--- |
| **Хранение** | Ссылка (gitlink) на коммит | Полная копия файлов и истории | Ссылка на репозиторий (загрузка при выполнении) |
| **Размер основного репо** | Почти не увеличивается | Увеличивается | Не увеличивается |
| **Независимость истории** | Полная независимость | Интегрированная | Полная независимость |
| **Доступность офлайн** | Требуется инициализация | Полностью доступно | Требуется загрузка |
| **Сложность для коллег** | Выше (нужны доп. команды) | Нулевая (просто файлы) | Средняя (ansible-galaxy install) |
| **Идеально для** | Независимые библиотеки | Ассеты, плагины, вендоринг | Управление ролями Ansible |

Детальное сравнение и критерии выбора — в [git_submodules_and_subtree.md](./git_submodules_and_subtree.md).

---

## Практические сценарии

### Сценарий 1: Добавление и настройка

При добавлении рекомендуется использовать относительные пути для обеспечения переносимости между протоколами (SSH/HTTPS). Относительный URL (`../shared-libs/logger.git`) разрешается относительно origin суперпроекта; для соседнего репозитория используется `../foo.git` (не `./foo.git` — оценка относительных URL идентична относительным директориям). Если у суперпроекта нет default remote, отсчёт идёт от текущего каталога.

```bash
# Добавить подмодуль с отслеживанием ветки main
git submodule add -b main ../shared-libs/logger.git vendor/logger
# Полезные опции add: --name <имя> (логическое имя, по умолчанию = путь),
# --reference <repo> (заимствование объектов), --depth <n> (shallow-клон)

# Изменить ветку отслеживания у существующего подмодуля
git submodule set-branch -b main vendor/logger    # --default — сброс к remote HEAD

# Изменить URL подмодуля (обновляет .gitmodules)
git submodule set-url vendor/logger git@github.com:org/logger.git

# Зафиксировать изменения
git add .gitmodules vendor/logger
git commit -m "chore: add logger submodule"
```

**Валидация:**
```bash
# Проверить содержимое .gitmodules
cat .gitmodules
# → [submodule "vendor/logger"]
#     path = vendor/logger
#     url = ../shared-libs/logger.git
#     branch = main

# Проверить, что запись в индексе — gitlink
git ls-files -s vendor/logger
# → 160000 <sha1> 0       vendor/logger
```

### Сценарий 2: Клонирование проекта

Обычный `git clone` не скачивает содержимое подмодулей.

```bash
# Клонирование со всеми вложенными зависимостями в 8 потоков
git clone --recurse-submodules -j 8 <url>

# Только указанные подмодули
git clone --recurse-submodules=vendor/logger <url>

# Shallow-клон и подмодулей (без этого флага подмодули останутся полными)
git clone --depth 1 --shallow-submodules --recurse-submodules <url>

# Если проект уже склонирован без подмодулей
git submodule update --init --recursive -j 8
```

**Валидация:**
```bash
# Проверить, что подмодули инициализированы
git submodule status
# → <sha1> vendor/logger (heads/main)

# Проверить рабочую директорию подмодуля
ls -la vendor/logger/.git
# → gitdir: ../.git/modules/vendor/logger
```

### Сценарий 3: Инициализация и выборочная загрузка

```bash
# Зарегистрировать подмодули в .git/config (копирует url и update из .gitmodules)
git submodule init [--] <путь>...

# Выборочная инициализация и обновление
git submodule update --init vendor/logger vendor/utils -j 8

# Partial clone подмодуля (только нужные объекты)
git submodule update --init --filter=blob:none vendor/logger

# Ограничить инициализацию «активными» подмодулями (полезно в монорепозиториях)
git config submodule.active 'vendor/logger'
git submodule init    # без pathspec инициализирует только активные
```

### Сценарий 4: Обновление до свежих коммитов (--remote)

По умолчанию `git submodule update` проверяет коммит, записанный в суперпроекте. Для перехода на свежие коммиты ветки используется `--remote`:

```bash
# Обновить подмодули до tip отслеживаемой ветки (branch из .gitmodules или remote HEAD)
git submodule update --remote

# Сразу замержить/заребейзить новые коммиты в текущую ветку подмодуля
git submodule update --remote --merge
git submodule update --remote --rebase

# Без предварительного fetch (использовать текущее состояние remote-tracking ветки)
git submodule update --remote --no-fetch

# Настроить отслеживаемую ветку
git config -f .gitmodules submodule.vendor/logger.branch develop
# или специальное значение "." — ветка с тем же именем, что и в суперпроекте
git config -f .gitmodules submodule.vendor/logger.branch .
```

**Валидация:**
```bash
# Подмодуль с коммитом, отличающимся от записанного в индексе, помечается "+"
git submodule status
# → +<sha1> vendor/logger (v1.5.0-2-g<sha1>)
```

### Сценарий 5: Внесение правок в подмодуль и публикация

Самая частая ошибка — забыть запушить изменения в самом подмодуле, что приводит к «битым» ссылкам у коллег (`fatal: reference is not a tree`).

**Алгоритм действий:**
1. **Подготовка:** Перейдите в каталог подмодуля и привяжите HEAD к ветке.
    ```bash
    cd vendor/logger
    git checkout main
    ```
2. **Правки:** Внесите изменения, протестируйте их.
3. **Фиксация в подмодуле:**
    ```bash
    git add .
    git commit -m "fix: resolve buffer overflow"
    # ОБЯЗАТЕЛЬНО: Отправьте изменения в удаленный репозиторий ПОДМОДУЛЯ
    git push origin main
    ```
4. **Фиксация в родительском проекте:**
    ```bash
    cd ../..
    # Git увидит изменение указателя (хеша)
    git add vendor/logger
    git commit -m "build: update logger dependency"
    git push
    ```

**Валидация:**
```bash
# Проверить, что хеш подмодуля обновился
git diff --submodule
# → Submodule vendor/logger <old_sha1>..<new_sha1> (main)

# Перед коммитом — какие коммиты подмодуля попадут в обновление
git submodule summary

# Проверить, что удаленный видит тот же коммит
git ls-remote origin refs/heads/main
# → <new_sha1>        refs/heads/main
```

### Сценарий 6: Групповые операции (Foreach)

Позволяет автоматизировать действия во всех зависимостях одновременно. Команда выполняется через shell в каждом проверенном подмодуле.

```bash
# Проверить статус во всех подмодулях рекурсивно
git submodule foreach --recursive 'git status'

# Подтянуть изменения (fetch) во всех подмодулях
git submodule foreach 'git fetch'

# Выполнить произвольный скрипт сборки
git submodule foreach 'npm install && npm run build'

# Спрятать локальные изменения во всех подмодулях (см. раздел про stash)
git submodule foreach --recursive 'git stash'
```

Переменные окружения (доступны, когда команда — один аргумент): `$name` (имя секции в `.gitmodules`), `$sm_path` (путь в непосредственном суперпроекте; `$path` — deprecated синоним), `$displaypath` (относительный путь от текущего каталога), `$sha1` (записанный коммит), `$toplevel` (корень суперпроекта).

Ненулевой код возврата команды в любом подмодуле прерывает обход; чтобы продолжить, добавьте `|| :` в конец команды. Не инициализированные подмодули игнорируются. Без `--quiet` перед командой печатается `Entering '<путь>'`.

**Валидация:**
```bash
git submodule foreach 'echo "Entering $name" && git rev-parse --abbrev-ref HEAD'
# → Entering 'vendor/logger'
# → main
# → Entering 'vendor/utils'
# → main
```

### Сценарий 7: Разрешение конфликтов слияния

Конфликт возникает, когда две ветки родительского проекта указывают на разные коммиты подмодуля (статус `U` в `git submodule status`).

```bash
# Посмотреть разницу в хешах
git diff --submodule

# Вариант А: Выбрать одну из сторон
git checkout --theirs vendor/logger  # Взять версию из вливаемой ветки
# ИЛИ
git checkout --ours vendor/logger    # Оставить текущую версию

# Вариант Б: Ручное разрешение
cd vendor/logger
git checkout <нужный_хеш_или_ветка>
cd ../..
git add vendor/logger
```

**Валидация:**
```bash
# После разрешения проверить статус подмодуля
git status
# → updated: vendor/logger (new commits)

# И посмотреть лог коммитов подмодуля
git log --oneline -3 vendor/logger
```

### Сценарий 8: Обзор изменений перед коммитом

```bash
# Коммиты подмодуля между HEAD суперпроекта и worktree/index
git submodule summary

# Между индексом и worktree подмодуля
git submodule summary --files

# Ограничить вывод N коммитами
git submodule summary -n 5

# Лог коммитов подмодуля внутри diff
git diff --submodule=log
```

### Сценарий 9: Удаление подмодуля

Требует очистки как файлов, так и конфигурации Git.

```bash
# 1. Деактивировать подмодуль в локальном конфиге (без pathspec команда ошибается;
#    --all — все подмодули; -f отбрасывает локальные изменения)
git submodule deinit -f vendor/logger

# 2. Удалить файлы, запись из .gitmodules и индекса
git rm -f vendor/logger

# 3. Очистить внутреннее хранилище (опционально, высвобождает место)
rm -rf .git/modules/vendor/logger
```

**Валидация:**
```bash
# Проверить, что запись исчезла из .gitmodules
cat .gitmodules
# → (файл пуст или секция удалена)

# Проверить, что подмодуль больше не в индексе
git ls-files vendor/logger
# → (пусто)

# Проверить, что локальный конфиг очищен
git config --list | grep submodule
# → (подмодуль не найден)
```

### Сценарий 10: Оптимизация CI/CD

```bash
# В CI/CD пайплайне: shallow-клон с shallow-подмодулями в 8 потоков
git clone --depth 1 --shallow-submodules --recurse-submodules -j 8 <url>

# Или: клонировать без подмодулей, затем инициализировать только нужные
git clone --depth 1 --no-checkout <url> repo
cd repo
git sparse-checkout set --no-cone src/ docs/
git checkout main
git submodule update --init vendor/logger vendor/utils -j 8
```

- `--depth 1` НЕ делает подмодули shallow сам — для этого нужен `--shallow-submodules` (или `submodule.<name>.shallow = true` в `.gitmodules`).
- Комбинация `--depth` с `--recurse-submodules` без `--shallow-submodules` может привести к отсутствию нужных коммитов в истории подмодулей.
- Кэшируйте директорию `.git/modules` между запусками пайплайна.
- **Локальные зеркала и `file://` URL:** с Git 2.30.6/2.38.1 (CVE-2022-39253) значение `protocol.file.allow` по умолчанию `user` — `git submodule update` откажет с `transport 'file' not allowed`. Для доверенных CI-раннеров: одноразово `git -c protocol.file.allow=always submodule update --init --recursive` или `git config --global protocol.file.allow always` (только для изолированных сред).
- Аутентификация: SSH-ключи или токены через переменные окружения и credential helper.

### Сценарий 11: Подмодули в Git Worktree

При использовании нескольких рабочих деревьев помните, что подмодули не инициализируются автоматически:

```bash
# Создать новое рабочее дерево
git worktree add ../feature-x feature-x

# Перейти в него и инициализировать подмодули
cd ../feature-x
git submodule update --init --recursive -j 8

# При удалении worktree с подмодулями
git worktree remove ../feature-x --force
```

### Сценарий 12: Безопасность

- **CVE-2024-32002** — path traversal через вредоносный `.gitmodules` при рекурсивном клонировании: выполнение произвольного кода через хуки. Исправлено в Git 2.45.1, 2.44.1, 2.43.4, 2.42.2, 2.41.1, 2.40.2, 2.39.4. Защита: актуальная версия Git; аудит `.gitmodules` сторонних проектов на подозрительные пути (симлинки, `../`).
- **CVE-2022-39253** — см. сценарий 10 (`protocol.file.allow`).
- `.gitmodules` не может быть симлинком — Git откажется проверять такое дерево.
- `submodule.<name>.update = !<command>` работает только из `.git/config`, никогда из `.gitmodules` — защита от выполнения кода из чужого репозитория.
- **Хуки в подмодулях** не наследуются от родительского репозитория — обязательные проверки (lint, tests) в подмодулях могут быть пропущены.
- **Доступ к приватным репозиториям:** убедитесь, что все участники команды имеют доступ ко всем подмодулям, иначе клонирование завершится ошибкой аутентификации.

---

## Дополнительная информация

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: reference is not a tree` | Подмодуль указывает на коммит, отсутствующий в удаленном репозитории | Убедиться, что изменения в подмодуле запушены (`git push`), или выбрать другой хеш |
| `fatal: No url found for submodule path '<путь>' in .gitmodules` | В секции подмодуля отсутствует ключ `url` | Добавить `url` в секцию `.gitmodules` |
| `fatal: no submodule mapping found in .gitmodules for path '<путь>'` | Путь отслеживается в индексе, но секции в `.gitmodules` нет | Восстановить секцию в `.gitmodules` или пере-добавить подмодуль |
| `fatal: '<путь>' already exists in the index` | `git submodule add` на уже существующий путь | Удалить запись через `git rm --cached <путь>` или `git submodule deinit` |
| `fatal: clone of '<url>' into submodule path '<путь>' failed` | URL недоступен или нет прав доступа | Проверить URL, доступы, credential helper; после смены URL — `git submodule sync --recursive` |
| `fatal: Submodule work tree '<путь>' contains local modifications; use '-f' to discard them` | `git submodule deinit` при незакоммиченных изменениях | Сначала скоммитить/stash изменения либо `git submodule deinit -f` (изменения будут потеряны) |
| `fatal: Use '--all' if you really want to deinitialize all submodules` | `git submodule deinit` без pathspec | Указать pathspec подмодулей или `--all` |
| `transport 'file' not allowed` | URL подмодуля — `file://` или локальный путь (CVE-2022-39253) | `git -c protocol.file.allow=always submodule update --init --recursive` (для доверенных сред) |
| `detached HEAD` (неожиданно) | Подмодуль не переключен на ветку, а привязан к хешу | Выполнить `git checkout main` внутри подмодуля или настроить `branch` в `.gitmodules` |
| `Authentication failed` при обновлении | URL подмодуля изменился или токен доступа невалиден | Выполнить `git submodule sync --recursive`, проверить credential helper |
| `unable to checkout` в CI/CD | Подмодуль требует интерактивной аутентификации или коммит вне shallow-истории | Настроить SSH-ключи или токены в CI/CD переменных окружения; не комбинировать `--depth` с `--recurse-submodules` без `--shallow-submodules` |

### Ограничения и крайние случаи

1. **Большие репозитории с множеством подмодулей:** Каждый подмодуль добавляет сложность в CI/CD пайплайнах. Для проектов с >50 подмодулями рассмотрите subtree или менеджеры пакетов.
2. **Ветвление подмодулей:** Если подмодуль используется в нескольких ветках родительского проекта с разными версиями, управление конфликтами усложняется.
3. **Мерж подмодулей:** Git не выполняет автоматический merge содержимого подмодулей — только обновление ссылок на коммиты.
4. **Bare-репозитории:** На серверах bare-репозитории не содержат рабочих деревьев, поэтому подмодули не могут быть инициализированы до клонирования.
5. **Рекурсивный depth:** Клонирование с ограничением глубины (`--depth`) совместно с `--recurse-submodules` может привести к отсутствию нужных коммитов в истории подмодулей — используйте `--shallow-submodules`.
6. **`submodule.<name>.ignore`:** Влияет на вывод `status`, `diff` и `log`, но не на поведение команд `git submodule`.
7. **foreach и неинициализированные подмодули:** `git submodule foreach` игнорирует подмодули, не проверенные в worktree.
8. **Вложенные подмодули:** Для операций во вложенных подмодулях требуется флаг `--recursive`; `git submodule update` поддерживает `--filter=<filter-spec>` для partial clone.

### Best practices

1. **Явное указание `branch`:** Всегда настраивайте `branch` в `.gitmodules` для подмодулей, версии которых необходимо синхронизировать; `branch = .` — для следования одноимённой ветке суперпроекта.
2. **Использование `absorbgitdirs`:** Выполняйте `git submodule absorbgitdirs` после добавления подмодулей для переноса `.git` данных в общее хранилище.
3. **Параллелизм:** Используйте флаг `-j`/`--jobs` (`git clone`, `git submodule update`) и `submodule.fetchJobs` для ускорения при множестве подмодулей.
4. **Ревью перед коммитом:** `git submodule summary` и `git diff --submodule=log` показывают, какие коммиты подмодуля попадут в изменение gitlink.
5. **Пиннинг в релизах:** В release-конвейерах фиксируйте точные коммиты; `git submodule update --remote` используйте только в dev-ветках.
6. **Относительные URL:** Используйте относительные пути (`../foo.git`) для переносимости между SSH и HTTPS.
7. **Аудит `.gitmodules`:** Регулярно проверяйте файлы `.gitmodules` сторонних проектов на наличие подозрительных URL, путей и симлинков.
8. **Версии Git:** Поддерживайте Git 2.45.1+ (или 2.44.1/2.43.4/2.42.2/2.41.1/2.40.2/2.39.4) для защиты от CVE-2024-32002.
9. **CI/CD кэширование:** Кэшируйте директорию `.git/modules` между запусками пайплайна.
10. **Альтернативы:** Если подмодули вызывают слишком много проблем, рассмотрите Git Subtree для небольших зависимостей.

### Отладка конфигурации

Чтобы увидеть состояние подмодулей и источник настроек:

```bash
# Вывод статуса всех подмодули с хешами (префиксы -, +, U)
git submodule status
git submodule status --cached --recursive

# Показать конфигурацию конкретного подмодуля
git config -f .gitmodules --list
git config --list | grep submodule

# Проверить источник настройки URL
git config --show-origin submodule.vendor/logger.url

# Принудительное обновление URL из .gitmodules
git submodule sync --recursive

# Проверить, какие файлы относятся к подмодулям
git ls-files --stage | grep 160000

# Фактические коммиты во всех вложенных подмодулях
git submodule foreach --recursive 'git rev-parse HEAD'

# Ремонт при проблемах с инициализацией
git submodule update --init --recursive --force
```

### Официальные ресурсы

- **Pro Git Book:** [Инструменты Git - Подмодули](https://git-scm.com/book/ru/v2/Инструменты-Git-Подмодули)
- **Справочник:** [git-submodule(1) Manual Page](https://git-scm.com/docs/git-submodule)
- **Справочник:** [gitmodules(5) Manual Page](https://git-scm.com/docs/gitmodules)
- **Справочник:** [gitsubmodules(7) Manual Page](https://git-scm.com/docs/gitsubmodules)

### Связанные темы

- [Git Submodules vs Subtree](./git_submodules_and_subtree.md) — детальное сравнение и критерии выбора.
- [Специальные файлы Git](./git_special_files_overview.md) — обзор `.gitmodules` и других служебных файлов.
- [Конфигурация Git](./git_configuration.md) — настройка `submodule.fetchJobs` и других параметров параллелизма.
- [Git Worktree](./git_worktree.md) — использование параллельных рабочих директорий с подмодулями.
- [Внутреннее устройство Git](./git_internals.md) — gitlink (режим `160000`) и директория `.git/modules/`.
- [Управление ролями Ansible](../Ansible/Roles/git_management.md) — использование подмодулей для версионирования ролей.
