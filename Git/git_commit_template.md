# Git Commit Template — шаблоны сообщений коммитов

## Определения

**`.gitmessage`** — файл-шаблон сообщения коммита, который Git использует для предварительного заполнения текстового редактора при выполнении команды `git commit`. Файл содержит текст в формате plain text, где строки, начинающиеся с `#`, интерпретируются Git как комментарии и не попадают в итоговое сообщение коммита.

**commit.template** — конфигурационный параметр Git, указывающий путь к файлу шаблона. Может быть установлен на глобальном, системном или локальном уровне репозитория.

**prepare-commit-msg** — клиентский хук Git, который выполняется сразу после запуска редактора сообщения, но до того, как пользователь увидит текст. Хук получает путь к файлу сообщения и может динамически модифицировать содержимое шаблона (например, добавлять имя ветки, ID задачи или автоматически генерировать scope на основе пути к измененным файлам).

**Conventional Commits** — соглашение о форматировании сообщений коммитов, обеспечивающее машиночитаемую структуру для автоматизации версионирования (SemVer) и генерации чейнджлогов.

**Commitizen** — CLI-инструмент для интерактивного создания коммитов по стандарту Conventional Commits. Запрашивает тип, область, описание и генерирует правильно отформатированное сообщение.

**Gitlint** — инструмент на Python для проверки сообщений коммитов на соответствие заданным правилам (длина, формат, запрещенные слова). Подходит для проектов на любых языках, не требует Node.js-инфраструктуры.

**Commitlint** — Node.js инструмент для валидации сообщений согласно спецификации Conventional Commits. Обеспечивает строгую проверку типа, области и формата заголовка.

**scope** — необязательная часть заголовка Conventional Commits, указывающая на модуль, компонент или область изменений (например, `feat(auth)`, `fix(ui)`). Scope улучшает семантику и позволяет фильтровать историю по компонентам.

**BREAKING CHANGE** — маркер в футере коммита, сигнализирующий о критическом изменении, нарушающем обратную совместимость. Требует повышения MAJOR версии по SemVer.

**трейлер (trailer)** — стандартизированная строка в футере коммита, начинающаяся с токена, за которым следует двоеточие и значение (например, `Co-authored-by:`, `Signed-off-by:`, `Resolves:`). Трейлеры обрабатываются Git и отображаются в GitHub/GitLab.

---

## Базовые концепции

### Механизм работы commit.template

При выполнении `git commit` без флага `-m` Git запускает текстовый редактор, определенный в `core.editor`. Сначала Git считывает содержимое файла, указанного в `commit.template`, и передает его редактору как начальное содержимое. Строки, начинающиеся с `#`, автоматически исключаются из финального сообщения — это позволяет оставлять подсказки и структуру внутри файла-шаблона.

Важно: если пользователь передает сообщение напрямую через `git commit -m "..."`, шаблон полностью игнорируется. Для принудительного соблюдения правил необходимо использовать хук `commit-msg`.

Использование шаблона решает несколько задач:
- **Стандартизация:** Обеспечение единого стиля сообщений во всей команде.
- **Информативность:** Подсказки напоминают о необходимости указать ID задачи, описать причину изменений или BREAKING CHANGES.
- **Автоматизация:** Подготовка базы для инструментов автоматического релиза (`semantic-release`, `standard-version`).

### Взаимодействие с хуками

```
git commit (без -m)
  ├── prepare-commit-msg  ← может изменить содержимое шаблона
  ├── editor открывается с текстом из commit.template
  └── commit-msg           ← валидирует финальное сообщение
```

Хук `prepare-commit-msg` получает три аргумента: путь к файлу сообщения, источник сообщения (`message`, `template`, `merge`, `squash`, `commit`) и опциональный SHA-1 коммита. Это позволяет создавать динамические шаблоны, адаптирующиеся под контекст (например, автоматически добавлять `(WIP)` при коммитах из IDE).

### Структура Conventional Commits

Стандартный формат сообщения:
```text
<type>(<scope>): <subject>

<body>

<footer>
```

| Тип | Описание | SemVer |
| :--- | :--- | :--- |
| `feat` | Добавление новой функциональности. | `MINOR` |
| `fix` | Исправление ошибок. | `PATCH` |
| `docs` | Изменения только в документации. | `PATCH`/None |
| `style` | Правки, не влияющие на логику (пробелы, форматирование). | None |
| `refactor` | Изменение кода без исправления ошибок или добавления функций. | None |
| `perf` | Изменения для улучшения производительности. | `PATCH` |
| `test` | Добавление или исправление существующих тестов. | None |
| `build` | Изменения в системе сборки или зависимостях (npm, docker). | None |
| `ci` | Настройка CI (GitHub Actions, GitLab CI). | None |
| `chore` | Прочие изменения, не влияющие на исходный код. | None |
| `revert` | Откат предыдущего коммита. | `PATCH` |

### Scope: правила и рекомендации

Scope должен отражать логический модуль или компонент системы:
- Используйте существующие имена пакетов, директорий или доменных терминов (`feat(auth:oauth)`, `fix(api:users)`)
- Для небольших проектов можно опустить scope или использовать общий scope (`feat(backend:)`)
- Избегайте слишком широких scope (`feat(all):`) — они теряют смысл фильтрации
- Для нескольких скоупов используйте скобки: `feat(parser,lexer): ...` (не рекомендуется, лучше отдельные коммиты)

### Правило 50/72 и гигиена сообщений

1.  **Заголовок (Subject):**
    - **Длина:** Рекомендуется до 50 символов (максимум 72). Ограничение связано с отображением в `git log --oneline` и форматом email-коммитов.
    - **Регистр:** Обычно начинается с маленькой буквы (хотя допустимы вариации команды).
    - **Наклонение:** Повелительное (`add feature`, а не `added feature` или `adds feature`).
    - **Точка:** В конце заголовка точка **не ставится**.
2.  **Тело (Body):**
    - Отделяется от заголовка пустой строкой.
    - Перенос строк: Каждая строка не должна превышать **72 символа** (для корректного отображения в `git log`).
    - Описывает **почему** внесены изменения, а не **что** (код уже показывает "что").
3.  **Футер (Footer) и трейлеры:**
    - Используется для ссылок на задачи (Jira, GitHub Issues) и метаданных.
    - **BREAKING CHANGE:** Должен начинаться с этого текста в футере, за которым следует описание.
    - **Трейлеры:** Стандартизированные токены (`Co-authored-by`, `Signed-off-by`, `Resolves`). Каждый трейлер размещается на отдельной строке в конце футера; пустые строки между трейлерами не допускаются.

### BREAKING CHANGE: короткий и полный формат

Критическое изменение может быть обозначено двумя способами:

1.  **Короткий (в заголовке):**
    Более короткий способ. Восклицательный знак `!` сразу после scope (или типа, если scope отсутствует) сигнализирует о критическом изменении:
    `feat(api)!: remove deprecated v1 endpoints`

2.  **Полный (в футере):**
    Рекомендуется для сложных миграций, где требуется подробное описание:
    ```text
    fix(auth): update token validation logic

    BREAKING CHANGE: The `validate` method now returns a Promise instead of a boolean.
    Update all calls to use `await`.

    Migration guide: https://docs.example.com/auth/migration-v2
    ```

### Трейлеры: формат и обработка

Git извлекает трейлеры из конца сообщения коммита и делает их доступными через `git interpret-trailers` и в API GitHub/GitLab. Стандартные трейлеры:
- `Co-authored-by: Имя Фамилия <email>` — для совместных авторов
- `Signed-off-by: Имя Фамилия <email>` — для подтверждения права на код (DCO)
- `Reviewed-by:`, `Acked-by:` — для ревьюверов
- `Resolves: PROJECT-123`, `Fixes: #456` — для связывания с задачами

Трейлеры чувствительны к регистру токена, но Git нормализует их в формате с заглавной буквы и дефисом при парсинге.

---

## Практические сценарии

### Сценарий 1: Создание детального шаблона проекта

1. Создайте `.gitmessage` в корне репозитория:

```text
# <type>(<scope>): <subject> (Max 50 chars)
# <Пустая строка>
# <body> (Wrap at 72 chars. Why this change? What problem does it solve?)
# <Пустая строка>
# <footer> (Closes #123, BREAKING CHANGE: message)
# 
# TYPES: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert
# -------------------------------------------------------------------------
# Заголовок: маленькая буква, повелительное наклонение, без точки в конце.
# Тело: объясните причину изменений.
```

2. Примените локально:
```bash
git config --local commit.template .gitmessage
```

3. Для глобального применения (все репозитории):
```bash
git config --global commit.template ~/.gitmessage
```

### Сценарий 2: Валидация через pre-commit (Gitlint)

Подходит для проектов на любых языках (Python, Go, C++), не требует Node.js.

1. Настройте `.gitlint` в корне:
```ini
[general]
ignore=body-is-missing
verbosity = 2

[title-max-length]
line-length=72

[title-must-not-contain-word]
words=wip,todo,fixme

[body-max-line-length]
line-length=100
```

2. Добавьте в `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/jorisroovers/gitlint
    rev: v0.19.1
    hooks:
      - id: gitlint
        stages: [commit-msg]
```

3. Установите хуки:
```bash
pre-commit install --hook-type commit-msg
```

4. Тест валидации:
```bash
echo "invalid commit message" | gitlint
# → 1: T1 Title exceeds max length (72): Title contains non-conventional prefix

echo "feat(auth): add OAuth2 support" | gitlint
# → (пусто = нет ошибок)
```

### Сценарий 3: Интеграция Commitlint и Husky (v9+)

Классика для JavaScript/TypeScript проектов.

1. Установка:
```bash
npm install --save-dev @commitlint/config-conventional @commitlint/cli husky
```

2. Настройка `commitlint.config.js`:
```javascript
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', ['feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'build', 'ci', 'chore', 'revert']],
    'subject-case': [2, 'always', 'lower-case']
  }
};
```

3. Инициализация Husky:
```bash
npx husky init
echo "npx --no -- commitlint --edit \$1" > .husky/commit-msg
chmod +x .husky/commit-msg
```

4. package.json — обязательный скрипт для Husky v9+:
```json
{
  "scripts": {
    "prepare": "husky"
  }
}
```

5. Валидация:
```bash
# Проверить конфигурацию
npx commitlint --print-config

# Тест валидации сообщения
echo "invalid message" | npx commitlint
# → ✖ type must be one of [feat, fix, docs, ...]

echo "feat(api): add endpoint" | npx commitlint
# → (пусто = нет ошибок)
```

### Сценарий 4: Использование трейлеров для совместной работы

Git позволяет указывать соавторов прямо в коммите, что корректно отображается в GitHub/GitLab.

```text
feat(ui): add dark mode toggle

Implemented a new toggle component in the header to switch between
light and dark themes using CSS variables.

Co-authored-by: Alex Smith <alex@example.com>
Resolves: PROJECT-456
```

Для добавления `Signed-off-by` автоматически при коммите используйте флаг `-s`:
```bash
git commit -s -m "feat(api): add endpoint"
```

### Сценарий 5: BREAKING CHANGES в коммитах

Критическое изменение может быть обозначено двумя способами:

1. **Короткий (в заголовке):**
   `feat(api)!: remove deprecated v1 endpoints`
2. **Полный (в футере):**
```text
fix(auth): update token validation logic

BREAKING CHANGE: The `validate` method now returns a Promise instead of a boolean.
Update all calls to use `await`.
```

### Сценарий 6: Commitizen — интерактивный стандарт

Commitizen заменяет `git commit` на интерактивный опросник, исключая необходимость запоминать типы коммитов.

1. Установка (глобально или локально):
```bash
npm install -g commitizen cz-conventional-changelog
```

2. Конфигурация в `package.json`:
```json
{
  "scripts": {
    "commit": "cz"
  },
  "config": {
    "commitizen": {
      "path": "./node_modules/cz-conventional-changelog"
    }
  }
}
```

3. Использование:
```bash
npm run commit
# → Интерактивный выбор type, scope, subject, body
```

Для адаптера `cz-conventional-changelog` доступны типы: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

### Сценарий 7: Динамический шаблон через prepare-commit-msg

Для автоматического добавления контекста в шаблон используйте хук `prepare-commit-msg`. Пример: автоматическое добавление ID задачи из имени ветки.

1. Создайте `.git/hooks/prepare-commit-msg`:
```bash
#!/bin/bash
TEMPLATE_FILE=".gitmessage"
COMMIT_MSG_FILE="$1"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

if [[ "$BRANCH" =~ ^(feature|bugfix)/([A-Z]+-[0-9]+) ]]; then
    ISSUE="${BASH_REMATCH[2]}"
    if [ -f "$TEMPLATE_FILE" ]; then
        cp "$TEMPLATE_FILE" "$COMMIT_MSG_FILE"
    fi
    echo "# Идентификатор задачи: $ISSUE" >> "$COMMIT_MSG_FILE"
fi
```

2. Сделайте хук исполняемым:
```bash
chmod +x .git/hooks/prepare-commit-msg
```

Теперь при коммите из ветки `feature/PROJ-123` в шаблон автоматически добавляется идентификатор задачи.

### Сценарий 8: Валидация в CI/CD (GitHub Actions)

Для проектов с открытым исходным кодом рекомендуется проверять сообщения коммитов на уровне CI.

```yaml
# .github/workflows/commitlint.yml
name: Commitlint

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  commitlint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm install --save-dev @commitlint/cli @commitlint/config-conventional
      - run: npx commitlint --from ${{ github.event.pull_request.base.sha }}..HEAD --verbose
```

### Сценарий 9: Интеграция с Lefthook

Lefthook — быстрый мультиязычный фреймворк для хуков, поддерживающий параллельное выполнение.

1. Установка:
```bash
brew install lefthook
# или
go install github.com/evilmartians/lefthook@latest
```

2. Конфигурация `lefthook.yml`:
```yaml
commit-msg:
  commands:
    commitlint:
      run: npx commitlint --edit {1}
```

3. Инициализация:
```bash
lefthook install
```

---

## Дополнительная информация

### Сравнение инструментов валидации

| Инструмент | Среда | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Commitlint** | Node.js | Огромная экосистема, пресеты для всех стандартов. | Требует `node_modules` в проекте. |
| **Gitlint** | Python | Легкий, не требует JS-инфраструктуры, гибкие regex-правила. | Меньше готовых пресетов. |
| **Standard-version** | Node.js | Автоматизирует SemVer и Changelog на базе коммитов. | В режиме обслуживания (maintenance). |
| **Commitizen** | Node.js | Интерактивный CLI, стандартизирует формат без запоминания типов. | Требует обучения команды новому workflow. |

### Ограничения и особенности

- **Пропуск шаблона:** Команда `git commit -m "..."` полностью игнорирует `commit.template`. Для принудительного соблюдения правил используйте хук `commit-msg`.
- **Глобальный шаблон:** При установке `commit.template` на глобальном уровне (`--global`) шаблон применяется ко всем репозиториям пользователя. Для проектно-специфичных шаблонов используйте `--local`.
- **IDE:** JetBrains (IntelliJ, WebStorm) и VS Code имеют встроенную поддержку `commit.template`, но могут требовать включения в настройках ("Use commit template").
- **Revert:** При использовании `git revert` Git автоматически создает сообщение `revert: <original subject>`. Не рекомендуется менять этот формат вручную, так как он используется инструментами анализа истории.
- **Squash и merge:** При squash-слиянии Git создает автоматическое сообщение с перечислением коммитов. Шаблон не применяется, но `commit-msg` хук может его изменить.
- **Rebase и amend:** `git commit --amend` открывает редактор с предыдущим сообщением, к которому применяется шаблон как основа. После сохранения старые строки комментариев из шаблона не дублируются.

### Поддерживаемые редакторы

Git определяет редактор в следующем порядке приоритета:
1. `GIT_EDITOR` (переменная окружения)
2. `core.editor` (конфигурация Git)
3. `EDITOR` (переменная окружения)
4. `VISUAL` (переменная окружения)
5. Системный редактор по умолчанию (`vi` на Linux, `notepad` на Windows)

Для корректной работы шаблона используйте редактор, который поддерживает начальное содержимое файла (все стандартные редакторы: `vim`, `nano`, `code --wait`, `subl -n -w`).

### Edge Cases

- **Пустое тело:** Если коммит содержит только заголовок, хук `commit-msg` может потребовать тело (`body-is-missing` в gitlint). Это полезно для неочевидных изменений.
- **Мерж-коммиты:** При `git merge` шаблон не применяется. Для enforcing стандартов используйте серверные хуки или CI.
- **Подпись коммитов:** Команда `git commit -S` (GPG) и `git commit -s` (DCO) дополняют сообщение, но не затрагивают шаблон.
- **Многострочные трейлеры:** Трейлеры должны быть в конце коммита, после пустой строки, без пробелов перед токеном.

### Удаление и очистка

Для удаления локального шаблона:
```bash
git config --local --unset commit.template
```

Для удаления глобального шаблона:
```bash
git config --global --unset commit.template
```

Для отключения хука временно:
```bash
chmod -x .git/hooks/commit-msg
```

### Официальные ресурсы

- **Спецификация Conventional Commits:** [conventionalcommits.org](https://www.conventionalcommits.org/ru/v1.0.0/)
- **Git Documentation (Templates):** [git-scm.com/docs/git-config#Documentation/git-config.txt-committemplate](https://git-scm.com/docs/git-config#Documentation/git-config.txt-committemplate)
- **Gitlint:** [jorisroovers.com/gitlint](https://jorisroovers.com/gitlint/)
- **Commitlint:** [commitlint.js.org](https://commitlint.js.org/)
- **Commitizen:** [commitizen-tools.github.io](https://commitizen-tools.github.io/cz-cli/)

### См. также

- [Git Hooks — автоматизация и валидация](./git_hooks.md) — pre-commit, commit-msg хуки для проверки формата сообщений.
- [Conventional Commits](./git_conventional_commits.md) — формат feat/fix/chore для автоматических релизов и changelog.
- [Конфигурация Git](./git_configuration.md) — commit.template, core.commentChar настройки.
- [Специальные файлы Git](./git_special_files_overview.md) — роль `.gitmessage` в иерархии файлов.
