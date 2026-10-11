# Git Hooks — автоматизация проверок

**Актуально для:** Git 2.54.x

## Определения

* **Git Hooks** — исполняемые скрипты, которые Git запускает автоматически при определенных событиях в жизненном цикле репозитория (коммит, пуш, мерж). Позволяют автоматизировать задачи, обеспечивать соблюдение стандартов и предотврать ошибки.
* **Клиентские хуки (Client-Side Hooks)** — хуки, выполняемые на локальной машине разработчика до отправки кода в репозиторий.
* **Серверные хуки (Server-Side Hooks)** — хуки, выполняемые на удалённом Git-сервере для применения политик на уровне команды или проекта.
* **Shebang** — первая строка скрипта вида `#!/bin/bash`, указывающая интерпретатор для выполнения хука.
* **Exit code** — код возврата хука. Нулевой (0) означает успех, ненулевой — ошибку и прерывает операцию (для blocking-хуков).

---

## Базовые концепции

### Расположение и активация

Хуки находятся в директории `.git/hooks` каждого репозитория. По умолчанию Git размещает там примеры с расширением `.sample`. Для активации хука нужно удалить расширение `.sample` и сделать файл исполняемым:

```bash
# Проверка наличия примеров хуков
ls -la .git/hooks/
# → pre-commit.sample
# → commit-msg.sample
# → pre-push.sample

# Активация хука pre-commit
cp .git/hooks/pre-commit.sample .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Скрипты могут быть написаны на любом языке: Bash, Python, Ruby, Node.js и другие. Ключевое требование — наличие корректного shebang в первой строке:

```bash
#!/bin/bash
# или
#!/usr/bin/env python3
```

**Важно:** Git выполняет хуки как исполняемые файлы напрямую, без автоматического определения интерпретатора. Если shebang отсутствует или некорректен, хук завершится с ошибкой `exec format error`.

### Контекст выполнения

При запуске хука Git устанавливает переменную окружения `GIT_DIR` — путь к директории `.git`. Рабочая директория (CWD) при выполнении клиентских хуков — корень рабочего дерева репозитория (не `.git`).

Для серверных хуков `GIT_DIR` указывает на директорию bare-репозитория, а CWD может отличаться в зависимости от конфигурации сервера. Хуки, запускаемые во время push (`pre-receive`, `update`, `post-receive`, `post-update`, `push-to-checkout`), всегда выполняются в `$GIT_DIR`.

```bash
# Пример хука, логирующего контекст выполнения
#!/bin/bash
echo "GIT_DIR: $GIT_DIR"
echo "CWD: $(pwd)"
echo "GIT_WORK_TREE: ${GIT_WORK_TREE:-not set}"
```

### Конфигурация хуков через Git config (Git 2.9+)

Начиная с Git 2.9, хуки можно определять не только через скрипты в `.git/hooks/`, но и через конфигурацию Git. Это позволяет управлять хуками без создания исполняемых файлов — достаточно указать команду и событие в конфиге.

Хуки из конфигурации выполняются **до** хуков из `hookdir` (`.git/hooks/` или `core.hooksPath`). Порядок выполнения: сначала все конфиг-хуки для события (в порядке обхода конфигурации), затем хук из `hookdir` последним.

```bash
# Определить хук через конфиг
git config set hook.linter.command "~/bin/linter --cpp20"
git config set --append hook.linter.event pre-commit

# Добавить второй хук для того же события
git config set hook.security-scan.command "gitleaks protect"
git config set --append hook.security-scan.event pre-commit

# Проверить, какие хуки назначены на событие
git hook list pre-commit
# → linter
# → security-scan

# Запустить хук вручную (без создания коммита)
git hook run pre-commit
# → (вывод хуков)
```

Конфигурация в файле `.git/config`:
```ini
[hook "linter"]
  event = pre-commit
  command = ~/bin/linter --cpp20
[hook "security-scan"]
  event = pre-commit
  command = gitleaks protect
```

Допустимые флаги `git hook run`:
* `--ignore-missing` — не ошибиться, если хук отсутствует
* `--to-stdin=<file>` — передать содержимое файла через stdin хуку
* `--allow-unknown-hook-name` — разрешить неизвестные имена хуков
* `-j, --jobs <n>` — параллельное выполнение хуков

### Шаблонная директория и автоустановка хуков

При `git init` Git копирует содержимое шаблонной директории в `.git/` нового репозитория. По умолчанию это системная директория (`/usr/share/git-core/templates` или `/usr/local/share/git-core/templates`). Хуки из `<templateDir>/hooks/` автоматически попадают в `.git/hooks/` каждого нового репозитория.

Для DevOps и администрирования это позволяет:
* Автоматически устанавливать хуки во все новые репозитории пользователей
* Централизованно управлять базовыми проверками (например, проверка размера файлов, поиск секретов)
* Обеспечивать минимальные стандарты без участия разработчика

```bash
# 1. Создать собственную шаблонную директорию
mkdir -p ~/.git-templates/hooks

# 2. Добавить шаблонный хук
cat > ~/.git-templates/hooks/pre-commit << 'EOF'
#!/bin/bash
echo "Checking for secrets..."
gitleaks git pre-commit --staged --redact
EOF
chmod +x ~/.git-templates/hooks/pre-commit

# 3. Настроить Git использовать шаблон
git config --global init.templateDir ~/.git-templates

# 4. Проверить — новые репозитории получат хук автоматически
git init my-project
ls -la my-project/.git/hooks/pre-commit
# → .git/hooks/pre-commit
```

**Важно:**
* Хуки из шаблона не активируются автоматически — файлы должны быть исполняемыми (`chmod +x`).
* Шаблон применяется только при `git init`, а не при `git clone`. Для существующих репозиториев используйте `core.hooksPath` (см. [Сценарий 6](#сценарий-6-распространение-хуков-через-core.hookspath)).
* Системный шаблон по умолчанию содержит примеры хуков с расширением `.sample` — Git копирует их, но не активирует.

### Жизненный цикл хуков

| Хук | Тип | Момент запуска | Код выхода != 0 | Входные параметры |
| :--- | :--- | :--- | :--- | :--- |
| `pre-commit` | Клиентский | Перед созданием коммита | Отменяет коммит | Нет |
| `prepare-commit-msg` | Клиентский | Перед открытием редактора сообщения | Отменяет коммит | Путь к файлу сообщения, источник коммита, SHA |
| `commit-msg` | Клиентский | После ввода сообщения, перед коммитом | Отменяет коммит | Путь к файлу сообщения |
| `post-commit` | Клиентский | После успешного коммита | Не влияет на коммит | Нет |
| `post-checkout` | Клиентский | После `git checkout` или `git switch` | Не влияет на операцию | prev_HEAD, new_HEAD, flag (1=branch, 0=file) |
| `post-merge` | Клиентский | После `git merge` (успешного) | Не влияет на операцию | Флаг squash |
| `pre-push` | Клиентский | Перед `git push` | Отменяет push | Имя и URL удаленного репозитория (через аргументы + stdin) |
| `pre-receive` | Серверный | При получении push на сервере | Отклоняет push | Данные через stdin |
| `update` | Серверный | Для каждой обновляемой ветки | Отклоняет обновление ветки | Имя рефы, oldrev, newrev |
| `post-receive` | Серверный | После успешного push | Не влияет на push | Данные через stdin |

### Порядок выполнения

Git выполняет хуки строго в определенном порядке внутри одной операции:

1. `pre-commit` → `prepare-commit-msg` → `commit-msg` → `post-commit`
2. `pre-push` (только перед push, не затрагивает коммиты)
3. `post-checkout` (после переключения веток)

Если любой blocking-хук завершается с ненулевым кодом, последующие хуки в цепочке не выполняются.

### Типы клиентских хуков

* **`pre-commit`** — линтинг, форматирование (`eslint`, `prettier`, `ruff`), проверка синтаксиса, поиск отладочных выражений (`console.log`). Не получает параметров — анализирует файлы самостоятельно через `git diff --cached`.
* **`prepare-commit-msg`** — изменение шаблона сообщения коммита перед открытием редактора. Используется для добавления номеров задач, форматирования или удаления вспомогательных строк. Получает путь к файлу сообщения, источник коммита и SHA.
* **`commit-msg`** — проверка сообщения коммита на соответствие стандартам (Conventional Commits). Получает путь к файлу сообщения как первый аргумент.
* **`post-commit`** — уведомления, запуск CI/CD, очистка. Выполняется после успешного коммита, не может отменить операцию.
* **`pre-push`** — запуск тяжелых тестов или сканирования на секреты (`gitleaks`) перед публикацией. Получает имя и URL удаленного репозитория как параметры командной строки, а данные о рефах — через stdin в формате `<local-ref> SP <local-sha> SP <remote-ref> SP <remote-sha> LF`.
* **`post-checkout` / `post-merge`** — автоматизация обновления зависимостей (`npm install`, `terraform init`). Не могут отменить операцию.

### Типы серверных хуков

* **`pre-receive`** — глобальная проверка прав, защита веток, проверка подписи, запрет на push больших файлов. Выполняется один раз для всего push. Не получает аргументов, но для каждой рефы читает из stdin строку в формате `<old-value> SP <new-value> SP <ref-name> LF`. Exit code != 0 отклоняет весь push.
* **`update`** — выполняется отдельно для каждой обновляемой рефы. Принимает три параметра: имя рефы, old-value, new-value. Позволяет разрешить/запретить обновление конкретных веток.
* **`post-receive`** — запуск CI/CD пайплайнов через вебхуки, уведомления, обновление документации. Выполняется после применения всех изменений. Получает данные через stdin в том же формате, что и `pre-receive`.

### Особенности выполнения

* **Bare-репозитории:** В bare-репозиториях (на серверах) клиентские хуки не выполняются, так как отсутствует рабочее дерево.
* **Submodules:** Хуки родительского репозитория не распространяются на субмодули. Для субмодулей необходимо настраивать хуки отдельно.
* **Worktrees:** При работе с `git worktree` хуки общие для всех рабочих деревьев (находятся в основной `.git/hooks`), но выполняются в контексте конкретного дерева.
* **Partial Clone / Sparse Checkout:** Хуки выполняются как обычно, но при работе с partial clone нужно учитывать возможное отсутствие некоторых объектов в локальном репозитории.
* **Push-хуки на сервере:** Хуки `pre-receive`, `update`, `post-receive`, `post-update` и `push-to-checkout` на сервере всегда выполняются в `$GIT_DIR` (корне bare-репозитория), а не в рабочем дереве.

### Инструменты управления хуками

* **[pre-commit](https://pre-commit.com/):** Мультиязычный фреймворк. Конфигурируется через `.pre-commit-config.yaml`. Управляет изоляцией окружений и кэшированием. Требует Python 3.10+.
* **[Husky](https://typicode.github.io/husky/):** Стандарт для JS/TS проектов. Автоматически устанавливает хуки при `npm install`. Требует Node.js 18+.
* **[Lefthook](https://github.com/evilmartians/lefthook):** Быстрый инструмент на Go с параллельным выполнением хуков. Поддерживает YAML-конфигурацию.
* **[git-hooks](https://github.com/icefox/git-git-hooks) / [git-hooks-list](https://github.com/cfpb/hookshot):** Альтернативные менеджеры для специфичных случаев.

**Сравнение инструментов:**

| Характеристика | pre-commit | Husky | Lefthook |
| :--- | :--- | :--- | :--- |
| **Язык** | Python | Node.js | Go |
| **Параллелизм** | Да (секция `parallel`) | Нет (последовательный) | Да (по умолчанию) |
| **Изоляция** | Виртуальные окружения | npm-пакеты | Бинарный файл |
| **Конфигурация** | YAML | package.json / файлы хуков | YAML |
| **Автоустановка** | `pre-commit install` | `npm install` | `lefthook install` |
| **Кроссплатформенность** | Отличная | Отличная | Отличная |

---

## Практические сценарии

### Предварительные требования

**Системные требования:**
* Git версии 2.54+ (для использования всех функций, включая `core.hooksPath` и `git hook run`)
* Для Python-хуков: Python 3.10+ (pre-commit 4.x требует Python 3.10+)
* Для Node.js-хуков: Node.js 18+ и npm/yarn
* Для Lefthook: установленный бинарный файл (v2.2.1+)

**Установка инструментов:**
```bash
# macOS (Homebrew)
brew install pre-commit lefthook

# Ubuntu/Debian
sudo apt-get install pre-commit
# Lefthook: скачать с https://github.com/evilmartians/lefthook/releases

# Windows (Chocolatey)
choco install pre-commit lefthook

# Проверка установки
pre-commit --version
# → pre-commit 4.6.2
lefthook version
# → lefthook 2.2.1
```

### Сценарий 1: Конфигурация pre-commit фреймворка

Использование современных линтеров и проверок безопасности с автоматическим управлением окружениями.

```yaml
# .pre-commit-config.yaml
default_language_version:
  python: python3.12
  node: 20

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
        args: [--markdown-linebreak-ext=md]
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: check-merge-conflict
      - id: detect-private-key

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.10
    hooks:
      - id: ruff
        args: [ --fix ]
      - id: ruff-format

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
```

**Установка и активация:**
```bash
# Установка хуков в .git/hooks (создает pre-commit хук-обёртку)
pre-commit install
# → pre-commit installed at .git/hooks/pre-commit

# Установка дополнительных типов хуков
pre-commit install --hook-type commit-msg
pre-commit install --hook-type pre-push

# Проверка конфигурации
pre-commit validate-config
```

**Основные команды:**
* `pre-commit install` — установка хуков в `.git/hooks`.
* `pre-commit run --all-files` — ручной запуск всех проверок на всех файлах.
* `pre-commit run ruff` — запуск конкретного хука.
* `pre-commit autoupdate` — обновление версий хуков в конфиге.
* `pre-commit clean` — очистка кэша окружений.

**Валидация:**
```bash
# Проверить, что хуки установлены
ls -la .git/hooks/pre-commit
# → .git/hooks/pre-commit

# Тестовый запуск на всех файлах
pre-commit run --all-files
# → Trim Trailing Whitespace.................................Passed
# → Fix End of Files.........................................Passed
# → Check Yaml...............................................Passed
# → ruff.....................................................Passed

# Проверить, что хук блокирует невалидный коммит
echo "invalid yaml: [" > test.yaml
git add test.yaml
git commit -m "test"
# → Check Yaml...............................................Failed
```

**Edge cases:**
* При использовании monorepo используйте `files:` и `exclude:` для фильтрации путей.
* Для медленных хуков добавьте `stages: [manual]` для запуска только по требованию.
* `SKIP=hook-id` позволяет пропустить конкретный хук без отключения всех проверок.

### Сценарий 2: Валидация сообщений с Gitlint

Контроль формата коммитов (Conventional Commits) без использования Node.js.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/jorisroovers/gitlint
    rev: v0.19.1
    hooks:
      - id: gitlint
        stages: [commit-msg]
```

```ini
# .gitlint — конфигурация правил валидации
[general]
ignore=body-is-missing
verbosity=2

[title-max-length]
line-length=72

[title-must-not-contain-word]
words=wip,todo,fixme,WIP

[title-match-regex]
regex=^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?: .+

[body-max-line-length]
line-length=100
```

**Установка и валидация:**
```bash
# Установка gitlint через pre-commit
pre-commit install --hook-type commit-msg

# Тест валидации
echo "invalid commit message" | gitlint
# → 1: T1 Title exceeds max length (72): Title contains non-conventional prefix

echo "feat(auth): add OAuth2 support" | gitlint
# → (пусто = нет ошибок)
```

**Edge cases:**
* Gitlint проверяет только текущий коммит — для проверки всей ветки используйте `gitlint --commits origin/main..HEAD`.
* Для игнорирования мерж-коммитов добавьте `ignore-revert-commits=True` и `ignore-merge-commits=True`.
* Подробная настройка правил `commitlint` и интеграция с Husky описаны в документе: [Интеграция Commitlint и Husky](./git_commit_template.md#сценарий-3-интеграция-commitlint-и-husky-v9).

### Сценарий 3: Автоматизация Node.js с Husky (v9+)

Современный способ инициализации хуков в JS-проектах для проверки Conventional Commits.

```bash
# Инициализация Husky (добавляет postinstall-скрипт в package.json)
npx husky init

# Проверка созданной структуры
ls -la .husky/
# → _/ (внутренние скрипты Husky)
# → pre-commit (пример)

# Добавление хука проверки сообщения
echo "npx --no -- commitlint --edit \$1" > .husky/commit-msg
chmod +x .husky/commit-msg
```

**Конфигурация commitlint:**
```javascript
// commitlint.config.js
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', [
      'feat', 'fix', 'docs', 'style', 'refactor',
      'perf', 'test', 'build', 'ci', 'chore', 'revert'
    ]],
    'subject-max-length': [2, 'always', 72],
    'subject-case': [2, 'always', 'lower-case']
  }
};
```

**package.json (зависимости):**
```json
{
  "devDependencies": {
    "@commitlint/cli": "^21.0.0",
    "@commitlint/config-conventional": "^21.0.0",
    "husky": "^9.0.0"
  },
  "scripts": {
    "prepare": "husky"
  }
}
```

**Валидация:**
```bash
# Проверить конфигурацию
npx commitlint --print-config

# Тест валидации сообщения
echo "invalid message" | npx commitlint
# → ✖ type must be one of [feat, fix, docs, ...]

echo "feat(api): add endpoint" | npx commitlint
# → (пусто = нет ошибок)
```

**Edge cases:**
* Husky v9+ требует `prepare` скрипт в package.json для автоматической установки.
* При использовании `npm install --ignore-scripts` Husky не установится автоматически.
* Для monorepo используйте `@commitlint/config-conventional` с `parserPreset` для корневых коммитов.

### Сценарий 4: Быстрые хуки с Lefthook

Параллельное выполнение хуков для максимальной скорости.

```yaml
# lefthook.yml
pre-commit:
  parallel: true
  commands:
    lint:
      glob: "*.{js,ts,jsx,tsx}"
      run: npx eslint --fix {staged_files}
      stage_fixed: true
    format:
      glob: "*.{js,ts,css,scss,json,md}"
      run: npx prettier --write {staged_files}
      stage_fixed: true
    types:
      glob: "*.{ts,tsx}"
      run: npx tsc --noEmit

commit-msg:
  commands:
    commitlint:
      run: npx commitlint --edit {1}

pre-push:
  parallel: true
  commands:
    test:
      run: npm test
    security:
      run: npm audit --audit-level=high
```

```bash
# Установка хуков
lefthook install

# Проверка конфигурации
lefthook validate

# Ручной запуск
lefthook run pre-commit
```

**Валидация:**
```bash
# Проверка скорости (параллельное выполнение)
time lefthook run pre-commit
# → 0.5s (vs 2.0s последовательного выполнения)
```

**Преимущества Lefthook:**
* Нативный бинарный файл — нет зависимости от Python/Node.js.
* Автоматический параллелизм на уровне команд.
* Подготовленные файлы (`stage_fixed: true`) автоматически добавляются в коммит.

### Сценарий 5: Серверные хуки в GitLab (Custom Hooks)

Реализация жестких проверок на стороне сервера, которые невозможно обойти локально.

**Предварительные требования:**
* Доступ к серверу GitLab с правами администратора.
* Директория custom_hooks должна быть доступна для записи пользователю `git`.

```bash
# Создание директории custom_hooks (на сервере)
sudo -u git mkdir -p /var/opt/gitlab/git-data/repositories/@hashed/path.git/custom_hooks

# Создание файла pre-receive (без расширения)
sudo -u git nano /path.git/custom_hooks/pre-receive
```

```bash
#!/bin/bash
# pre-receive хук: защита веток и валидация

# Чтение входных данных из stdin
while read oldrev newrev refname; do
  # Защита ветки main от прямого push
  if [[ "$refname" == "refs/heads/main" ]] || [[ "$refname" == "refs/heads/master" ]]; then
    echo "ERROR: Direct push to $refname is prohibited. Use merge requests."
    exit 1
  fi

  # Проверка подписи коммитов
  if [[ "$oldrev" == "0000000000000000000000000000000000000000" ]]; then
    # Новая ветка — проверяем все коммиты
    commits=$(git rev-list "$newrev" --not --all)
  else
    commits=$(git rev-list "$oldrev..$newrev")
  fi

  for commit in $commits; do
    if ! git verify-commit "$commit" 2>/dev/null; then
      echo "ERROR: Commit $commit is not signed. All commits must be GPG-signed."
      exit 1
    fi
  done
done

exit 0
```

```bash
# Сделать файл исполняемым
chmod +x /path.git/custom_hooks/pre-receive

# Проверка прав
ls -la /path.git/custom_hooks/
# → -rwxr-xr-x git git pre-receive
```

**Валидация:**
```bash
# Тест с неподписанным коммитом
git push origin feature-branch
# → ERROR: Commit abc123 is not signed. All commits must be GPG-signed.
# → error: failed to push some refs to 'origin'

# Тест с подписанным коммитом
git commit -S -m "feat: signed commit"
git push origin feature-branch
# → (успешно)
```

**Edge cases:**
* При ошибке в скрипте хука push отклоняется без деталей — используйте `logger` для логирования на сервере.
* Custom hooks не работают в GitLab SaaS (cloud) — только для self-hosted инсталляций.
* Для проверки множественных реф используйте `update` хук вместо `pre-receive`.

### Сценарий 6: Распространение хуков через core.hooksPath

Версионирование хуков в репозитории и автоматическая установка для всей команды.

```bash
# Создание директории с хуками в репозитории
mkdir -p .githooks

# Создание pre-commit хука
cat > .githooks/pre-commit << 'EOF'
#!/bin/bash
echo "Running pre-commit checks..."
npm run lint
EOF

chmod +x .githooks/pre-commit

# Настройка Git для использования кастомного пути
git config core.hooksPath .githooks

# Проверка настройки
git config --get core.hooksPath
# → .githooks
```

**Автоматическая установка для команды (через скрипт инициализации):**
```bash
# scripts/setup-hooks.sh
#!/bin/bash
set -e

echo "Configuring Git hooks..."
git config core.hooksPath .githooks

# Проверка прав выполнения
for hook in .githooks/*; do
  if [[ -f "$hook" ]] && [[ ! -x "$hook" ]]; then
    chmod +x "$hook"
    echo "Fixed permissions: $hook"
  fi
done

echo "Hooks configured successfully!"
```

```bash
# Добавить в README или документацию
# После клонирования репозитория выполнить:
# chmod +x scripts/setup-hooks.sh && ./scripts/setup-hooks.sh
```

**Валидация:**
```bash
# Проверить текущий путь к хукам
git config --get core.hooksPath
# → .githooks

# Проверить, что хуки работают
git commit --allow-empty -m "test hooks"
# → Running pre-commit checks...
```

**Edge cases:**
* При клонировании репозитория `core.hooksPath` не настраивается автоматически — требуется ручная настройка или скрипт инициализации.
* Для обратной совместимости можно использовать symlink: `ln -s ../../.githooks .git/hooks`.
* Husky v9+ и pre-commit автоматически используют свои пути, но уважают `core.hooksPath` если он явно настроен.

### Сценарий 7: Написание кастомного хука с нуля

Создание собственного хука для специфичных требований проекта.

**Пример: pre-commit хук с проверкой нескольких условий**

```bash
#!/bin/bash
# .githooks/pre-commit — пример комплексного хука

set -euo pipefail

ERRORS=""
WARNINGS=""

# 1. Проверка наличия секретов в коммите
echo "Checking for secrets..."
SECRETS=$(git diff --cached -p | grep -iE '(password|api_key|secret)\s*=\s*["'\''][^"'\'']+["'\'']' || true)
if [[ -n "$SECRETS" ]]; then
  ERRORS+="ERROR: Potential secrets detected in commit:\n$SECRETS\n\n"
fi

# 2. Проверка размера файлов
echo "Checking file sizes..."
while IFS= read -r file; do
  if [[ -f "$file" ]]; then
    SIZE=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo 0)
    if [[ "$SIZE" -gt 5242880 ]]; then  # 5 MB
      WARNINGS+="WARNING: Large file detected: $file ($(($SIZE / 1024 / 1024))MB)\n"
    fi
  fi
done < <(git diff --cached --name-only --diff-filter=ACMR)

# 3. Проверка TODO/FIXME в новых строках
echo "Checking for TODO markers..."
TODOS=$(git diff --cached -p | grep -E '^\+' | grep -iE '(TODO|FIXME|XXX|HACK)' || true)
if [[ -n "$TODOS" ]]; then
  WARNINGS+="WARNING: TODO/FIXME markers found:\n$TODOS\n\n"
fi

# Вывод предупреждений
if [[ -n "$WARNINGS" ]]; then
  echo -e "\n$WARNINGS"
fi

# Проверка ошибок
if [[ -n "$ERRORS" ]]; then
  echo -e "\n$ERRORS"
  echo "Commit blocked. Fix errors or use --no-verify to bypass (not recommended)."
  exit 1
fi

echo "All checks passed!"
exit 0
```

```bash
chmod +x .githooks/pre-commit
```

**Валидация:**
```bash
# Тест 1: Коммит с секретом
echo 'password = "secret123"' > config.env
git add config.env
git commit -m "add config"
# → ERROR: Potential secrets detected in commit
# → Commit blocked

# Тест 2: Коммит с большим файлом
dd if=/dev/zero of=large.bin bs=1M count=10
git add large.bin
git commit -m "add large file"
# → WARNING: Large file detected: large.bin (10MB)
# → All checks passed!
```

### Сценарий 8: Интеграция с CI/CD (pre-commit CI)

Автоматическая проверка и автоисправление кода в CI.

**Pre-commit CI (бесплатный для open-source):**
```yaml
# .pre-commit-config.yaml
ci:
  autofix_prs: true
  autofix_commit_msg: '[pre-commit.ci] auto fixes'
  autoupdate_branch: 'pre-commit-autoupdate'
  skip: [gitleaks]  # Пропустить в CI (уже проверен GitHub Secret Scanning)
```

**GitHub Actions (ручная настройка):**
```yaml
# .github/workflows/pre-commit.yml
name: pre-commit checks

on: [push, pull_request]

jobs:
  pre-commit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - uses: pre-commit/action@v3.0.1
        with:
          extra_args: --from-ref ${{ github.event.pull_request.base.sha }} --to-ref ${{ github.sha }}
    ```

**Валидация:**
```bash
# Проверка работы CI локально (через pre-commit CI playground)
# Или через GitHub Actions:
gh run list --workflow=pre-commit.yml
# → STATUS  WORKFLOW              EVENT  ID
# → ✓      pre-commit checks      push   1234567890
```

---

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `exec format error` | Отсутствует или некорректный shebang | Добавьте `#!/bin/bash` или `#!/usr/bin/env python3` в начало скрипта |
| Хук не выполняется | Файл не является исполняемым | `chmod +x .git/hooks/pre-commit` |
| `pre-commit: command not found` | pre-commit не установлен или не в PATH | `pip install pre-commit` или `brew install pre-commit` |
| Хук игнорируется при clone | `.git/hooks` не версионируется | Используйте `core.hooksPath` с директорией в репозитории |
| `cannot run hooks/post-receive: No such file or directory` | Windows: shebang с Unix-форматом | Используйте `#!/bin/bash` и убедитесь что Git Bash доступен |
| Хук блокирует все коммиты | Синтаксическая ошибка в скрипте | Проверьте через `bash -n .git/hooks/pre-commit` |
| `SKIP` не работает | Неправильный ID хука | Используйте ID из `.pre-commit-config.yaml`, а не имя |

### Отладка хуков

```bash
# Проверка синтаксиса скрипта
bash -n .git/hooks/pre-commit
# → (пусто = нет ошибок)

# Запуск с трассировкой
bash -x .git/hooks/pre-commit
# → + echo "Running checks..."
# → Running checks...

# Запуск хука через git hook (Git 2.9+)
git hook run pre-commit
# → GIT_DIR=/path/to/repo/.git
# → GIT_WORK_TREE=/path/to/repo

# Логирование в файл (добавить в начало хука)
exec > /tmp/hook-debug.log 2>&1
set -x
echo "Hook started at $(date)"
```

### Обход проверок (для экстренных случаев)

* **Полный пропуск хуков:** Если нужно срочно закоммитить код без проверок, используйте флаг `--no-verify` (или `-n`).
  ```bash
  git commit -m "fix: quick fix" --no-verify
  git push --no-verify
  ```
* **Пропуск конкретного хука pre-commit:**
  ```bash
  SKIP=ruff git commit -m "message"
  SKIP=eslint,prettier git commit -m "message"
  ```
* **Пропуск хука pre-push:**
  ```bash
  SKIP=test git push origin main
  ```

**Важно:** `--no-verify` отключает ВСЕ хуки для операции. Используйте `SKIP` для избирательного пропуска.

---

## Best Practices

1. **Скорость:** Клиентские хуки должны выполняться быстро (<5 секунд). Для тяжелых проверок используйте `pre-push` или CI/CD.
2. **Идемпотентность:** Хуки должны давать одинаковый результат при повторном запуске.
3. **Обработка ошибок:** Используйте `set -euo pipefail` для bash-скриптов и `try/except` для Python.
4. **Кроссплатформенность:** Избегайте специфичных для ОС команд. Используйте `pre-commit` или `lefthook` для универсальности.
5. **Документирование:** Добавьте в README инструкцию по установке хуков для новых участников команды.
6. **Версионирование:** Храните конфигурации хуков (`.pre-commit-config.yaml`, `lefthook.yml`) в репозитории.
7. **Тестирование:** Тестируйте хуки локально перед добавлением в репозиторий через `pre-commit run --all-files`.
8. **Автообновление:** Настройте `pre-commit autoupdate` в CI для автоматического обновления версий хуков.

**Best practices для кастомных хуков:**
* Используйте `set -euo pipefail` для раннего завершения при ошибках.
* Разделяйте критические ошибки (блокирующие) и предупреждения (информационные).
* Добавляйте `SKIP` или `FORCE` механизмы для экстренных случаев.
* Документируйте требования хука в README проекта.

---

## Дополнительная информация

### Безопасность

* **Клиентские хуки не являются гарантией:** Их легко обойти через `--no-verify` или не установить. Никогда не полагайтесь на них для критических проверок безопасности.
* **Серверная валидация:** Для критических проверок (права, секреты, тесты) всегда используйте серверные хуки или CI/CD пайплайны.
* **Доверие к сторонним хукам:** Запуск `pre-commit install` выполняет код из сторонних репозиториев. Проверяйте `rev` (хеши или теги) в конфигурации.
* **Hook injection:** При работе с публичными репозиториями проверяйте `.git/hooks` и `.githooks` на наличие подозрительных файлов перед запуском хуков.
* **safe.directory:** Git 2.36+ требует явного доверия к директориям, принадлежащим другим пользователям:
  ```bash
  git config --global --add safe.directory /path/to/shared/repo
  ```

### Ограничения и особенности

* **Производительность:** Каждый хук задерживает Git-операцию. Оптимизируйте скрипты для быстрого выполнения.
* **Параллелизм:** pre-commit и lefthook поддерживают параллельное выполнение — используйте его для ускорения.
* **Сложность отладки:** Хуки выполняются в изолированном окружении. Используйте логирование для диагностики проблем.
* **Зависимости:** Хуки могут требовать установки дополнительных инструментов. Документируйте зависимости.
* **Bare-репозитории:** В bare-репозиториях клиентские хуки не выполняются. Используйте серверные хуки или CI/CD для реализма.

### Официальные ресурсы

* **Git Book — Customizing Git:** [git-scm.com/book/ru/v2/Настройка-Git-Git-Hooks](https://git-scm.com/book/ru/v2/Customizing-Git-Git-Hooks)
* **Pre-commit documentation:** [pre-commit.com](https://pre-commit.com/)
* **Lefthook documentation:** [github.com/evilmartians/lefthook](https://github.com/evilmartians/lefthook)
* **Husky documentation:** [typicode.github.io/husky](https://typicode.github.io/husky/)
* **Каталог хуков pre-commit:** [pre-commit.com/hooks.html](https://pre-commit.com/hooks.html)
* **Git hooks reference:** [git-scm.com/docs/githooks](https://git-scm.com/docs/githooks)
* **Git hook command:** [git-scm.com/docs/git-hook](https://git-scm.com/docs/git-hook)

### См. также

* [Шаблон коммитов и валидация](./git_commit_template.md) — настройка шаблонов сообщений и форматирование.
* [Conventional Commits](./git_conventional_commits.md) — формат сообщений feat/fix/chore для автоматизации релизов.
* [Конфигурация Git](./git_configuration.md) — `core.hooksPath`, `includeIf`, `safe.directory`.
* [Очистка истории и защита от секретов](./git_history_manipulation.md) — gitleaks, удаление секретов.
* [Прочие соглашения и конвенции Git](./git_other_conventions.md) — .gitkeep, .gitconfig, .gitsigners.
