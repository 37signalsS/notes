# Git Hooks — автоматизация проверок

## Определения

**Git Hooks** — исполняемые скрипты, которые Git запускает автоматически при определенных событиях в жизненном цикле репозитория (коммит, пуш, мерж). Позволяют автоматизировать задачи, обеспечивать соблюдение стандартов и предотвращать ошибки.

**Клиентские хуки (Client-Side Hooks)** — хуки, выполняемые на локальной машине разработчика до отправки кода в репозиторий.

**Серверные хуки (Server-Side Hooks)** — хуки, выполняемые на удаленном Git-сервере для применения политик на уровне команды или проекта.

---

## Базовые концепции

### Расположение и активация

Хуки находятся в директории `.git/hooks` каждого репозитория. По умолчанию там присутствуют примеры с расширением `.sample`. Для активации хука нужно удалить расширение `.sample` и сделать файл исполняемым:

```bash
chmod +x .git/hooks/pre-commit
```

Скрипты могут быть написаны на любом языке, поддерживаемом системой: Bash, Python, Ruby, Node.js и другие.

### Жизненный цикл хуков

| Хук | Тип | Момент запуска | Код выхода != 0 |
| :--- | :--- | :--- | :--- |
| `pre-commit` | Клиентский | Перед созданием коммита | Отменяет коммит |
| `prepare-commit-msg` | Клиентский | Перед открытием редактора сообщения | Отменяет коммит |
| `commit-msg` | Клиентский | После ввода сообщения, перед коммитом | Отменяет коммит |
| `post-commit` | Клиентский | После успешного коммита | Не влияет на коммит |
| `pre-push` | Клиентский | Перед `git push` | Отменяет push |
| `pre-receive` | Серверный | При получении push на сервере | Отклоняет push |
| `update` | Серверный | Для каждой обновляемой ветки | Отклоняет обновление ветки |
| `post-receive` | Серверный | После успешного push | Не влияет на push |
| `post-update` | Серверный | После обновления ссылок | Не влияет на push |

### Клиентские хуки

Выполняются локально, позволяют проверять код до отправки на сервер:

* **`pre-commit`** — линтинг, форматирование (`eslint`, `prettier`, `black`), проверка синтаксиса, поиск отладочных выражений (`console.log`, `print`).
* **`commit-msg`** — проверка сообщения коммита на соответствие стандартам (наличие номера задачи, Conventional Commits).
* **`pre-push`** — запуск быстрых тестов или сканирования на секреты перед публикацией.

### Серверные хуки

Выполняются на сервере, применяются для глобальных политик:

* **`pre-receive`** — запуск глубокого анализа кода, проверка прав доступа, защита веток от force-push.
* **`post-receive`** — запуск CI/CD пайплайнов, отправка уведомлений (Slack, email), обновление внешних систем.

### Фреймворки для управления хуками

Ручное управление хуками затруднено в командах. Фреймворки упрощают установку и синхронизацию:

* **[pre-commit](https://pre-commit.com/):** Фреймворк для управления клиентскими хуками. Конфигурируется через `.pre-commit-config.yaml`, поддерживает множество языков и инструментов.
* **[Husky](https://typicode.github.io/husky/):** Управление хуками через `package.json` для JavaScript/Node.js проектов.

---

## Практические сценарии

### Сценарий 1: Pre-commit — линтинг и форматирование

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running pre-commit checks..."

# Проверка синтаксиса Python
echo "Checking Python syntax..."
if ! git diff --cached --name-only --diff-filter=ACM | grep '\.py$' | xargs -r python3 -m py_compile 2>/dev/null; then
    echo "ERROR: Ошибка синтаксиса Python"
    exit 1
fi

# Поиск забытых отладочных выражений
if git diff --cached -S "console.log" -- '*.js' -- '*.ts' | grep -q 'console.log'; then
    echo "ERROR: Обнаружены console.log в коммите"
    exit 1
fi

echo "All checks passed."
exit 0
```

### Сценарий 2: Commit-msg — валидация Conventional Commits

```bash
#!/bin/bash
# .git/hooks/commit-msg

commit_msg=$(cat "$1")
pattern='^(feat|fix|docs|style|refactor|test|chore)(\(.+\))?: .+'

if ! echo "$commit_msg" | grep -qE "$pattern"; then
    echo "ERROR: Сообщение коммита должно соответствовать Conventional Commits"
    echo "Пример: feat(auth): добавить OAuth2 аутентификацию"
    exit 1
fi
```

### Сценарий 3: Pre-push — сканирование на секреты

```bash
#!/bin/bash
# .git/hooks/pre-push

echo "Scanning for secrets before push..."

# Поиск паттернов, похожих на секреты
if git diff --cached -S "AWS_SECRET_ACCESS_KEY" | grep -q "AWS_SECRET_ACCESS_KEY"; then
    echo "ERROR: Обнаружены потенциальные AWS секреты"
    exit 1
fi

if git diff --cached -S "PRIVATE KEY" | grep -q "PRIVATE KEY"; then
    echo "ERROR: Обнаружен приватный ключ"
    exit 1
fi

echo "No secrets detected."
exit 0
```

### Сценарий 4: Распространение хуков в команде

Директория `.git/hooks` не отслеживается Git. Два способа синхронизации хуков:

**Способ A: Символические ссылки**

```bash
# Создать директорию для хуков в репозитории
mkdir -p scripts/git-hooks

# Создать символическую ссылку
ln -s -f ../../scripts/git-hooks/pre-commit .git/hooks/pre-commit
```

**Способ B: `core.hooksPath`**

```bash
# Указать Git директорию с хуками
git config core.hooksPath scripts/git-hooks
```

Способ B предпочтительнее для командной работы, так как не требует ручного создания ссылок каждым разработчиком.

### Сценарий 5: Настройка через pre-commit фреймворк

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/psf/black
    rev: 24.2.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
```

```bash
# Установка pre-commit фреймворка
pip install pre-commit

# Инициализация в репозитории
pre-commit install

# Запуск всех хуков вручную
pre-commit run --all-files
```

---

## Дополнительная информация

### Предостережения

* Клиентские хуки можно обойти флагом `--no-verify` (`git commit --no-verify`, `git push --no-verify`)
* Хуки не заменяют CI/CD пайплайны — они только первый рубеж проверки
* `post-commit` и `post-receive` не могут отменить операцию, только зафиксировать результат

### Официальные ресурсы

* **Документация Git:** [git-scm.com/book/en/v2/Customizing-Git-Git-Hooks](https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks)
* **pre-commit:** [pre-commit.com](https://pre-commit.com/)

### Связанные темы

Шаблон коммитов и валидация через commit-msg в [git_commit_template.md](./git_commit_template.md). Защита от секретов в [git_history_manipulation.md](./git_history_manipulation.md).
