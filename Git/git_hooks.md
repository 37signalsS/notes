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

Скрипты могут быть написаны на любом языке: Bash, Python, Ruby, Node.js и другие. В первой строке (shebang) должен быть указан путь к интерпретатору.

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

### Типы клиентских хуков

* **`pre-commit`** — линтинг, форматирование (`eslint`, `prettier`, `ruff`), проверка синтаксиса, поиск отладочных выражений (`console.log`).
* **`commit-msg`** — проверка сообщения коммита на соответствие стандартам (Conventional Commits).
* **`pre-push`** — запуск тяжелых тестов или сканирования на секреты (`gitleaks`) перед публикацией.
* **`post-checkout` / `post-merge`** — автоматизация обновления зависимостей (`npm install`, `terraform init`).

### Типы серверных хуков

* **`pre-receive`** — глобальная проверка прав, защита веток, проверка подписей, запрет на push больших файлов.
* **`post-receive`** — запуск CI/CD пайплайнов через вебхуки, уведомления, обновление документации.

### Инструменты управления хуками

* **[pre-commit](https://pre-commit.com/):** Мультиязычный фреймворк. Конфигурируется через `.pre-commit-config.yaml`.
* **[Husky](https://typicode.github.io/husky/):** Стандарт для JS/TS проектов.
* **[Lefthook](https://github.com/evilmartians/lefthook):** Быстрый инструмент на Go с параллельным выполнением.

---

## Практические сценарии

### Сценарий 1: Конфигурация pre-commit фреймворка

Использование современных линтеров и проверок безопасности.

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

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff
        args: [ --fix ]
      - id: ruff-format

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.2
    hooks:
      - id: gitleaks
```

**Основные команды:**
* `pre-commit install` — установка хуков в `.git/hooks`.
* `pre-commit run --all-files` — ручной запуск всех проверок на всех файлах.
* `pre-commit autoupdate` — обновление версий хуков в конфиге.

### Сценарий 2: Валидация сообщений с Gitlint

Контроль формата коммитов (Conventional Commits) без использования Node.js.

1. Установите `pre-commit` и настройте хук в `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/jorisroovers/gitlint
    rev: v0.19.1
    hooks:
      - id: gitlint
```

2. Настройте правила валидации в файле `.gitlint`. Примеры конфигурации и описание правил доступны в разделе **[Валидация через pre-commit (Gitlint)](./git_commit_template.md#сценарий-2-валидация-через-pre-commit-gitlint)**.

### Сценарий 3: Автоматизация Node.js с Husky (v9+)

Современный способ инициализации хуков в JS-проектах для проверки Conventional Commits.

```bash
# Инициализация Husky
npx husky init

# Добавление хука проверки сообщения
echo "npx --no -- commitlint --edit \$1" > .husky/commit-msg
```

Подробная настройка правил `commitlint` и интеграция с Husky описаны в документе: **[Интеграция Commitlint и Husky](./git_commit_template.md#сценарий-3-интеграция-commitlint-и-husky-v9)**.

### Сценарий 4: Серверные хуки в GitLab (Custom Hooks)

Реализация жестких проверок на стороне сервера, которые невозможно обойти локально.

1. Создайте директорию `custom_hooks` в корне репозитория на сервере (или `hashed/path.git/custom_hooks`).
2. Создайте файл `pre-receive` (без расширения):
```bash
#!/bin/bash
# Запрет push в ветку main напрямую
while read oldrev newrev refname
do
  if [[ $refname == "refs/heads/main" ]]; then
    echo "Direct push to main is prohibited!"
    exit 1
  fi
done
```
3. Сделайте файл исполняемым: `chmod +x pre-receive`.

### Сценарий 5: Распространение хуков через core.hooksPath

Если вы хотите хранить хуки в репозитории (например, в папке `.githooks`) и версионировать их.

```bash
# Переопределение пути к хукам для текущего репозитория
git config core.hooksPath .githooks

# Команда для всей команды (добавить в README или скрипт инициализации)
git config --local core.hooksPath .githooks
```

---

## Дополнительная информация

### Устранение неполадок и обход проверок

* **Пропуск хуков:** Если нужно срочно закоммитить код без проверок, используйте флаг `--no-verify` (или `-n`).
  ```bash
  git commit -m "fix: quick fix" --no-verify
  ```
* **Пропуск конкретного хука pre-commit:**
  ```bash
  SKIP=ruff git commit -m "message"
  ```
* **Проблема с путями в Windows:** При использовании Bash-скриптов в хуках на Windows убедитесь, что пути к интерпретаторам корректны (используйте `/bin/bash`).

### Безопасность

* **Клиентские хуки не являются гарантией:** Их легко обойти или не установить.
* **Серверная валидация:** Для критических проверок (права, секреты, тесты) всегда используйте серверные хуки или CI/CD пайплайны.
* **Доверие:** Запуск `pre-commit install` выполняет код из сторонних репозиториев. Проверяйте `rev` (хеши или теги) в конфигурации.

### Официальные ресурсы

* **Git Book — Настройка Git:** [git-scm.com/book/ru/v2/Настройка-Git-Git-Hooks](https://git-scm.com/book/ru/v2/Customizing-Git-Git-Hooks)
* **Каталог хуков pre-commit:** [pre-commit.com/hooks.html](https://pre-commit.com/hooks.html)

### См. также

* [Шаблон коммитов и валидация](./git_commit_template.md)
* [Очистка истории и защита от секретов](./git_history_manipulation.md)
* [Прочие соглашения и конвенции Git](./git_other_conventions.md)
