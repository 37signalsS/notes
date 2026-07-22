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

Скрипты могут быть написаны на любом языке, поддерживаемом системой: Bash, Python, Ruby, Node.js и другие. В первой строке (shebang) должен быть указан путь к интерпретатору.

### Жизненный цикл хуков

| Хук | Тип | Момент запуска | Код выхода != 0 |
| :--- | :--- | :--- | :--- |
| `pre-commit` | Клиентский | Перед созданием коммита | Отменяет коммит |
| `prepare-commit-msg` | Клиентский | Перед открытием редактора сообщения | Отменяет коммит |
| `commit-msg` | Клиентский | После ввода сообщения, перед коммитом | Отменяет коммит |
| `post-commit` | Клиентский | После успешного коммита | Не влияет на коммит |
| `post-checkout` | Клиентский | После `git checkout` или `git switch` | Не влияет на операцию |
| `post-merge` | Клиентский | После `git merge` (успешного) | Не влияет на операцию |
| `pre-push` | Клиентский | Перед `git push` | Отменяет push |
| `pre-receive` | Серверный | При получении push на сервере | Отклоняет push |
| `update` | Серверный | Для каждой обновляемой ветки | Отклоняет обновление ветки |
| `post-receive` | Серверный | После успешного push | Не влияет на push |
| `reference-transaction` | Клиент/Сервер | При любом обновлении ссылок | Может отменить транзакцию |

### Типы клиентских хуков

* **`pre-commit`** — линтинг, форматирование (`eslint`, `prettier`, `black`, `ruff`), проверка синтаксиса, поиск отладочных выражений (`console.log`, `print`).
* **`commit-msg`** — проверка сообщения коммита на соответствие стандартам (Conventional Commits).
* **`pre-push`** — запуск тяжелых тестов или сканирования на секреты (`gitleaks`) перед публикацией.
* **`post-checkout` / `post-merge`** — автоматизация обновления зависимостей (`npm install`, `terraform init`) при смене ветки или получении изменений.

### Типы серверных хуков

* **`pre-receive`** — глобальная проверка прав, защита веток, проверка подписей коммитов, запрет на push больших файлов.
* **`post-receive`** — запуск CI/CD пайплайнов через вебхуки, уведомления в мессенджеры, обновление документации.

### Фреймворки для управления хуками

* **[pre-commit](https://pre-commit.com/):** Мультиязычный фреймворк. Конфигурируется через `.pre-commit-config.yaml`. Позволяет использовать готовые хуки без их ручного написания.
* **[Husky](https://typicode.github.io/husky/):** Основной инструмент для JavaScript-экосистемы. Начиная с v9.0, процесс инициализации упрощен до одной команды `npx husky init`.
* **[Lefthook](https://github.com/evilmartians/lefthook):** Быстрый и мощный инструмент на Go, поддерживающий параллельное выполнение хуков.

---

## Практические сценарии

### Сценарий 1: Автоматизация с Ruff (замена Black и Flake8)

**Ruff** — крайне быстрый линтер и форматировщик для Python, написанный на Rust.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff
        args: [ --fix ]
      - id: ruff-format
```

### Сценарий 2: Автоматическое обновление зависимостей

Хук `post-merge` позволяет автоматически запускать установку пакетов после `git pull`.

```bash
#!/bin/bash
# .git/hooks/post-merge

changed_files=$(git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD)

check_run() {
    echo "$changed_files" | grep --quiet "$1" && eval "$2"
}

echo "Checking for dependency updates..."
check_run "package-lock.json" "npm install"
check_run "requirements.txt" "pip install -r requirements.txt"
```

### Сценарий 3: Проверка сообщения коммита (Commitlint)

Использование Husky и Commitlint для соблюдения Conventional Commits.

```bash
# Установка
npm install --save-dev @commitlint/config-conventional @commitlint/cli
npx husky init
# Добавление хука
echo "npx --no -- commitlint --edit \$1" > .husky/commit-msg
```

### Сценарий 4: Распространение хуков в команде

1. **`core.hooksPath`**: Переопределение пути к хукам на директорию, отслеживаемую Git (например, `.githooks`).
   ```bash
   git config core.hooksPath .githooks
   ```
2. **`git init --template`**: Использование шаблонов для автоматической установки хуков при создании (`git init`) или клонировании (`git clone`) репозитория.
   ```bash
   git config --global init.templateDir ~/.git-template
   # Положить хуки в ~/.git-template/hooks
   ```

### Сценарий 5: Современный конфиг pre-commit (v5.0.0+)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/psf/black
    rev: 25.1.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/flake8
    rev: 7.1.0
    hooks:
      - id: flake8
```

---

## Дополнительная информация

### Безопасность и обход проверок

* **Локальный обход**: Любой клиентский хук можно обойти флагом `--no-verify`.
* **Доверие**: Никогда не полагайтесь на клиентские хуки как на единственный механизм безопасности. Они предназначены для удобства разработчика.
* **Серверная валидация**: Окончательная проверка должна всегда происходить на сервере (через `pre-receive` или CI/CD) — этот этап невозможно обойти локально.

### Ограничения

* Хуки не копируются при клонировании репозитория (по соображениям безопасности).
* Скрипты должны быть переносимыми (не использовать пути, специфичные для конкретной ОС, если команда работает на разных платформах).

### Официальные ресурсы

* **Git Book - Hooks:** [git-scm.com/book/ru/v2/Настройка-Git-Git-Hooks](https://git-scm.com/book/ru/v2/Customizing-Git-Git-Hooks)
* **Pre-commit Framework:** [pre-commit.com](https://pre-commit.com/)

### См. также

* [Шаблон коммитов и валидация](./git_commit_template.md)
* [Очистка истории и защита от секретов](./git_history_manipulation.md)
* [Специальные файлы Git](./git_special_files_overview.md)
