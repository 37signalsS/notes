# Git Commit Template — шаблоны сообщений коммитов

## Определения

**`.gitmessage`** — файл-шаблон сообщения коммита, который Git использует для предварительного заполнения текстового редактора при выполнении команды `git commit`.

**commit.template** — конфигурационный параметр Git, указывающий путь к файлу шаблона.

**Conventional Commits** — соглашение о форматировании сообщений коммитов, обеспечивающее машиночитаемую структуру для автоматизации версионирования (SemVer) и генерации чейнджлогов.

**Commitizen** — CLI-инструмент для интерактивного создания коммитов по стандарту Conventional Commits.

**Gitlint** — инструмент на Python для проверки сообщений коммитов на соответствие заданным правилам (длина, формат, запрещенные слова).

**Commitlint** — Node.js инструмент для валидации сообщений согласно спецификации Conventional Commits.

---

## Базовые концепции

### Назначение шаблона

Использование шаблона решает несколько задач:
- **Стандартизация:** Обеспечение единого стиля сообщений во всей команде.
- **Информативность:** Подсказки напоминают о необходимости указать ID задачи, описать причину изменений или BREAKING CHANGES.
- **Автоматизация:** Подготовка базы для инструментов автоматического релиза (`semantic-release`, `standard-version`).

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
| `fix` | Исправление ошибки. | `PATCH` |
| `docs` | Изменения только в документации. | `PATCH`/None |
| `style` | Правки, не влияющие на логику (пробелы, форматирование). | None |
| `refactor` | Изменение кода без исправления ошибок или добавления функций. | None |
| `perf` | Изменения для улучшения производительности. | `PATCH` |
| `test` | Добавление или исправление существующих тестов. | None |
| `build` | Изменения в системе сборки или зависимостях (npm, docker). | None |
| `ci` | Настройка CI (GitHub Actions, GitLab CI). | None |
| `chore` | Прочие изменения, не влияющие на исходный код. | None |
| `revert` | Откат предыдущего коммита. | `PATCH` |

### Правило 50/72 и гигиена сообщений

1.  **Заголовок (Subject):**
    - **Длина:** Рекомендуется до 50 символов (максимум 72).
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
    - **Трейлеры:** Стандартизированные токены (`Co-authored-by`, `Signed-off-by`, `Resolves`).

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
```

2. Добавьте в `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/jorisroovers/gitlint
    rev: v0.19.1
    hooks:
      - id: gitlint
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

---

## Дополнительная информация

### Сравнение инструментов валидации

| Инструмент | Среда | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Commitlint** | Node.js | Огромная экосистема, пресеты для всех стандартов. | Требует `node_modules` в проекте. |
| **Gitlint** | Python | Легкий, не требует JS-инфраструктуры, гибкие regex-правила. | Меньше готовых пресетов. |
| **Standard-version** | Node.js | Автоматизирует SemVer и Changelog на базе коммитов. | В режиме обслуживания (maintenance). |

### Ограничения и особенности

- **Пропуск шаблона:** Команда `git commit -m "..."` полностью игнорирует `commit.template`. Для принудительного соблюдения правил используйте хук `commit-msg`.
- **IDE:** JetBrains (IntelliJ, WebStorm) и VS Code имеют встроенную поддержку `commit.template`, но могут требовать включения в настройках ("Use commit template").
- **Revert:** При использовании `git revert` Git автоматически создает сообщение `revert: <original subject>`. Не рекомендуется менять этот формат вручную, так как он используется инструментами анализа истории.

### Официальные ресурсы

- **Спецификация Conventional Commits:** [conventionalcommits.org](https://www.conventionalcommits.org/ru/v1.0.0/)
- **Git Documentation (Templates):** [git-scm.com/docs/git-config#Documentation/git-config.txt-committemplate](https://git-scm.com/docs/git-config#Documentation/git-config.txt-committemplate)

### См. также

- [Git Hooks — автоматизация и валидация](./git_hooks.md) — механизмы запуска проверок.
- [Конфигурация Git](./git_configuration.md) — управление глобальными и локальными настройками.
- [Специальные файлы Git](./git_special_files_overview.md) — роль `.gitmessage` в иерархии файлов.
