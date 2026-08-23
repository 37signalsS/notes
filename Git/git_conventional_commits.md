# Conventional Commits — формат сообщений коммитов

## Определения

**Conventional Commits** — спецификация формата сообщений коммитов, добавляющая структуру для чтения человеком и автоматической обработки инструментами.

**Формат:** `<type>[scope]: <description>`

| Элемент | Описание |
| :--- | :--- |
| `type` | Тип изменения (обязательный) |
| `scope` | Область действия (необязательный) |
| `description` | Краткое описание (обязательный) |
| `body` | Дополнительное описание (необязательный) |
| `footer` | Метаданные (breaking changes, issue-ссылки) |

---

## Базовые концепции

### Типы коммитов

| Тип | Назначение | Пример |
| :--- | :--- | :--- |
| `feat` | Новая функциональность | `feat(auth): add OAuth2 support` |
| `fix` | Исправление бага | `fix: resolve memory leak` |
| `docs` | Изменения в документации | `docs: update README` |
| `style` | Форматирование (не влияет на логику) | `style: apply prettier` |
| `refactor` | Рефакторинг без изменения поведения | `refactor: extract utils module` |
| `perf` | Улучшение производительности | `perf: optimize DB queries` |
| `test` | Добавление/изменение тестов | `test: add unit tests for auth` |
| `build` | Сборочная система / зависимости | `build: update webpack config` |
| `ci` | CI/CD конфигурация | `ci: add GitHub Actions workflow` |
| `chore` | Прочее (не попадает в релиз) | `chore: update dependencies` |
| `revert` | Откат предыдущего коммита | `revert: undo feat(auth)` |

### Breaking Changes

Breaking changes обозначаются `!` после типа или `BREAKING CHANGE:` в footer:

```bash
# Вариант 1: восклицательный знак
git commit -m "feat(api)!: change response format"

# Вариант 2: footer
git commit -m "feat(api): change response format

BREAKING CHANGE: response now uses camelCase instead of snake_case"
```

### Связь с SemVer

| Тип | Версия | Пример |
| :--- | :--- | :--- |
| `fix` | PATCH (1.0.1) | `fix: resolve crash` |
| `feat` | MINOR (1.1.0) | `feat: add export` |
| `BREAKING CHANGE` | MAJOR (2.0.0) | `feat!: new API format` |

---

## Практические сценарии

### Сценарий 1: Базовый коммит

```bash
git commit -m "feat: add user registration"
git commit -m "fix(auth): handle expired tokens"
git commit -m "docs: update API documentation"
```

### Сценарий 2: Breaking change

```bash
git commit -m "feat(api)!: switch to REST v2

BREAKING CHANGE: /users endpoint now returns paginated response"
```

### Сценарий 3: Автоматический changelog

```bash
# Использовать conventional-changelog
npx conventional-changelog -p angular -i CHANGELOG.md -s

# Результат — автоматически сгенерированный CHANGELOG
# на основе формата коммитов
```

### Сценарий 4: Проверка формата (commitlint)

```bash
# Установить commitlint
npm install --save-dev @commitlint/cli @commitlint/config-conventional

# Настроить commitlint.config.js
echo "module.exports = {extends: ['@commitlint/config-conventional']};\" > commitlint.config.js

# Проверить последний коммит
git commit --amend -m "bad message"
# →⧗  input: bad message
# →✖  subject may not be empty [subject-empty]
```

### Сценарий 5: Автоматические релизы

```yaml
# GitHub Actions с semantic-release
- name: Release
  uses: cycjimmy/semantic-release-action@v4
  with:
    extra_plugins: |
      @semantic-release/changelog
      @semantic-release/git
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
# → Автоматически создаёт тег и release на основе коммитов
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `subject may not be empty` | Пустое описание | Добавить описание после типа |
| `type must be one of [feat, fix, ...]` | Неизвестный тип | Использовать стандартный тип |
| Changelog пуст | Коммиты не по формату | Переписать коммиты через `rebase -i` |
| semantic-release не триггерится | Нет `feat` или `fix` коммитов | Добавить нужный тип |

### Best Practices

1. **Используйте lowercase** — `feat`, не `Feat`.
2. **Пишите на английском** — для совместимости с инструментами.
3. **Не превышайте 50 символов** в описании (subject).
4. **Используйте императив** — `add`, не `added` или `adds`.
5. **Добавляйте scope** — для много модульных проектов.
6. **Отмечайте breaking changes** — через `!` или `BREAKING CHANGE:`.

---

## Дополнительная информация

### Связанные темы

- [Git Tags](./git_tags.md) — SemVer и автоматические теги на основе типа коммита.
- [Git Commit Template](./git_commit_template.md) — шаблоны сообщений и форматирование.
- [Git Hooks](./git_hooks.md) — валидация формата через commit-msg хук.
- [Git Workflows](./git_workflows.md) — интеграция Conventional Commits в GitFlow/Trunk-Based.

### Официальные ресурсы

- **Conventional Commits:** [conventionalcommits.org](https://www.conventionalcommits.org/)
- **Commitlint:** [commitlint.js.org](https://commitlint.js.org/)
- **Semantic Release:** [semantic-release.github.io](https://semantic-release.github.io/)
