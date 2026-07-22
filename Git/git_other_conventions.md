# Прочие соглашения и конвенции Git

## Определения

**Конвенции Git (Git conventions)** — это набор общепринятых сообществом или специфичных для инструментов файлов и практик, которые не являются встроенными функциями Git, но дополняют его возможности для совместной разработки.

**`.gitkeep`** — условное имя файла, используемого для отслеживания пустых директорий в Git (так как Git отслеживает только файлы, а не папки).

---

## Базовые концепции

### Отслеживание пустых директорий (.gitkeep)

Поскольку Git не сохраняет пустые папки, разработчики используют "заглушки".
- **Статус:** Не является официальной фичей Git.
- **Имя:** Обычно используется `.gitkeep`, но технически это может быть любой файл (например, `.placeholder` или пустой `.gitignore`).
- **Размещение:** Помещается внутрь директории, которую необходимо сохранить в структуре репозитория.

### Общие настройки проекта (.gitconfig)

Иногда в корень репозитория помещают файл `.gitconfig` с рекомендованными настройками для команды (например, алиасы или параметры `core`).
- **Безопасность:** Git никогда не загружает этот файл автоматически.
- **Подключение:** Разработчики должны вручную включить его в свой локальный конфиг командой `git config include.path ../.gitconfig`.

### Верификация подписей (.gitsigners)

Файл со списком доверенных публичных ключей (SSH или GPG) для проверки подлинности коммитов.
- **allowedSigners:** Используется для настройки `gpg.ssh.allowedSignersFile`.
- **Назначение:** Позволяет команде верифицировать коммиты коллег без импорта ключей в личное хранилище.

### Интеграция с Gerrit (.gitreview)

Используется в проектах, применяющих систему ревью Gerrit (например, OpenStack, Android).
- **Функция:** Описывает хост, порт и ветку по умолчанию для отправки кода на ревью командой `git review`.

### Линтинг и хуки

- **`.gitlint`:** Конфигурация для проверки формата сообщений коммитов (длина заголовка, наличие ID задачи).
- **`.pre-commit-config.yaml`:** Самый популярный современный стандарт для управления git-хуками через фреймворк [pre-commit](https://pre-commit.com/). Позволяет автоматически запускать линтеры и тесты перед созданием коммита.

---

## Практические сценарии

### Сценарий 1: Сохранение структуры логов и временных папок

Если проекту нужны пустые папки `logs/` или `temp/` сразу после клонирования.

```bash
# Создание папки и файла-заглушки
mkdir logs
touch logs/.gitkeep

# Добавление в Git
git add logs/.gitkeep
git commit -m "chore: add logs directory placeholder"
```

### Сценарий 2: Использование общего .gitconfig в монорепозитории

Полезно для настройки специфичных драйверов слияния или алиасов для всей команды.

1. Создайте `.gitconfig` в корне проекта:
```ini
[alias]
    st = status --short
    lg = log --oneline --graph --all
[core]
    whitespace = trailing-space,space-before-tab
```

2. Инструкция для разработчиков (выполняется один раз):
```bash
git config include.path ../.gitconfig
```

### Сценарий 3: Настройка pre-commit хуков

Стандарт де-факто для автоматизации проверок в DevOps/SRE проектах.

1. Создайте `.pre-commit-config.yaml`:
```yaml
repos:
-   repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
    -   id: trailing-whitespace
    -   id: end-of-file-fixer
    -   id: check-yaml
-   repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.0
    hooks:
    -   id: ruff
```

2. Установка:
```bash
pre-commit install
# → pre-commit installed at .git/hooks/pre-commit
```

### Сценарий 4: Настройка .gitlint для Conventional Commits

Если вы используете `gitlint` для валидации сообщений.

```ini
# .gitlint
[general]
ignore=body-is-missing

[title-max-length]
line-length=72

[title-must-not-contain-word]
words=wip,todo
```

---

## Дополнительная информация

### Ограничения

- **Необязательность:** Большинство конвенций требуют установки дополнительных инструментов (gitlint, pre-commit) или ручной настройки разработчиком.
- **Разнообразие:** Разные команды могут использовать разные имена файлов (например, `.keep` вместо `.gitkeep`).

### Официальные ресурсы

- **Gerrit Code Review:** [gerrit-review.googlesource.com](https://gerrit-review.googlesource.com/)
- **Pre-commit framework:** [pre-commit.com](https://pre-commit.com/)
- **Gitlint documentation:** [jorisroovers.com/gitlint](https://jorisroovers.com/gitlint/)

### См. также

- [Обзор специальных файлов Git](./git_special_files_overview.md) — SSoT для стандартных файлов (.gitignore, .gitattributes).
- [Шаблоны коммитов](./git_commit_template.md) — детали Conventional Commits.
- [Git Hooks — автоматизация](./git_hooks.md) — механизмы работы хуков.
