# Git Commit Template — шаблон коммитов

## Определения

**`.gitmessage`** — файл-шаблон сообщения коммита, который Git использует для предварительного заполнения редактора при создании коммита.

**commit.template** — конфигурационная директива Git, указывающая путь к файлу шаблона сообщения.

---

## Базовые концепции

### Назначение шаблона

Шаблон коммитов решает следующие задачи:

- **Стандартизация:** Единый формат сообщений для всей команды
- **Напоминание:** Комментарии в шаблоне напоминают о структуре сообщения
- **Conventional Commits:** Поддержка машиночитаемого формата для автоматизации релизов

### Формат шаблона

```text
# .gitmessage
# <type>: <subject>
#
# <body>
#
# <footer>
#
# Types: feat, fix, docs, style, refactor, test, chore
# Пример: feat(auth): добавить OAuth2 аутентификацию
```

### Настройка

```bash
# Локальная настройка для текущего репозитория
git config commit.template .gitmessage

# Глобальная настройка для всех репозиториев
git config --global commit.template ~/.gitmessage
```

### Conventional Commits

Стандарт форматирования сообщений коммитов:

| Тип | Описание |
| :--- | :--- |
| `feat` | Новая функция |
| `fix` | Исправление ошибки |
| `docs` | Изменения в документации |
| `style` | Форматирование, пробелы, точки с запятой |
| `refactor` | Изменение кода без изменения поведения |
| `test` | Добавление или изменение тестов |
| `chore` | Изменения в сборке, зависимостях, инструментах |

**Формат:** `<type>(<scope>): <subject>`

**Примеры:**

- `feat(auth): добавить OAuth2 аутентификацию`
- `fix(api): исправить утечку памяти в обработчике`
- `docs(readme): обновить инструкции по установке`

---

## Практические сценарии

### Сценарий 1: Настройка шаблона в проекте

1. Создайте файл `.gitmessage` в корне репозитория:

```bash
cat > .gitmessage << 'EOF'
# <type>(<scope>): <subject>
#
# <body>
#
# <footer>
#
# Types: feat, fix, docs, style, refactor, test, chore
# Subject: краткое описание в повелительном наклонении
# Body: подробное описание изменений (опционально)
# Footer: связанные задачи, BREAKING CHANGE (опционально)
EOF
```

1. Настройте локальный шаблон:

```bash
git config commit.template .gitmessage
```

1. Закоммитьте шаблон:

```bash
git add .gitmessage
git commit -m "chore: add commit message template"
```

### Сценарий 2: Глобальная настройка для разработчика

Для личной продуктивности настройте глобальный шаблон:

```bash
# Создать глобальный шаблон
cat > ~/.gitmessage << 'EOF'
# <type>(<scope>): <subject>
#
# <body>
#
# <footer>
#
# Examples:
#   feat(users): add user registration endpoint
#   fix(api): resolve memory leak in handler
#   docs: update API documentation
EOF

# Применить глобально
git config --global commit.template ~/.gitmessage
```

### Сценарий 3: Автоматизация через setup-скрипт

Для командной работы добавьте настройку в скрипт инициализации:

```bash
#!/bin/bash
# setup.sh

# Настроить шаблон коммита
git config commit.template .gitmessage

# Опционально: настроить hook для валидации
cp hooks/commit-msg .git/hooks/commit-msg
chmod +x .git/hooks/commit-msg
```

### Сценарий 4: Валидация через commit-msg hook

Шаблон не гарантирует соблюдение формата. Для строгой валидации используйте хук `commit-msg` — пример в [git_hooks.md](./git_hooks.md#сценарий-2-commit-msg--валидация-conventional-commits).

### Сценарий 5: Интеграция с Husky (для JavaScript-проектов)

```json
// package.json
{
  "husky": {
    "hooks": {
      "commit-msg": "commitlint -E HUSKY_GIT_PARAMS"
    }
  },
  "devDependencies": {
    "@commitlint/cli": "^17.0.0",
    "@commitlint/config-conventional": "^17.0.0"
  }
}
```

```javascript
// commitlint.config.js
module.exports = {
  extends: ['@commitlint/config-conventional']
};
```

---

## Дополнительная информация

### Предостережения

- **Требует ручной настройки:** Каждый разработчик должен выполнить `git config` после клонирования
- **Не является обязательным:** Шаблон только заполняет редактор, но не валидирует сообщение
- **Альтернатива:** Хук `commit-msg` для строгой валидации формата

### Официальные ресурсы

- **Документация Git:** [git-scm.com/docs/git-commit](https://git-scm.com/docs/git-commit)
- **Conventional Commits:** [conventionalcommits.org](https://www.conventionalcommits.org/)

### Связанные документы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md). Git hooks описаны в [git_hooks.md](./git_hooks.md).
