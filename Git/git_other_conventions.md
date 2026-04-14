# Git Other Conventions — другие соглашения

## Определения

**Git conventions** — различные файлы-соглашения, связанные с Git, но не являющиеся стандартными фичами системы контроля версий.

---

## Базовые концепции

### .gitkeep

- **Статус:** Соглашение, **не фича Git**
- **Назначение:** Git не отслеживает пустые директории. Файл `.gitkeep` (или любой другой) помещается в пустую папку, чтобы Git имел что отслеживать
- **Имя произвольное:** Может называться как угодно, `.gitkeep` — конвенция

### .gitconfig (в репозитории)

- **Назначение:** Предлагаемая конфигурация для разработчиков
- **Ограничение:** Git **не загружает** такие файлы автоматически (безопасность)
- **Использование:** Проекты включают инструкции для ручной настройки:

  ```bash
  git config include.path ../.gitconfig
  ```

- **Применение:** Монорепозитории, проекты со специфичными настройками Git

### .gitsigners / allowedSigners

- **Назначение:** Файлы с доверенными ключами подписи (GPG/SSH) для верификации коммитов
- **Использование:** Linux kernel и другие проекты с trusted contributors
- **Настройка:** `git config gpg.ssh.allowedSignersFile <файл>` для `git log --show-signature`

### .gitreview

- **Назначение:** Конфигурация интеграции с Gerrit
- **Проекты:** OpenStack, Android, Eclipse
- **Формат:**

  ```ini
  [gerrit]
  host=review.opendev.org
  port=29418
  project=openstack/nova.git
  defaultbranch=master
  ```

- **Использование:** `git review` читает файл и пушит коммиты в Gerrit для ревью

### .gitlint

- **Назначение:** Конфигурация линтера сообщений коммитов
- **Пример:**

  ```ini
  [general]
  ignore=body-is-missing

  [title-max-length]
  line-length=72
  ```

### .jj/

- **Назначение:** Директория состояния Jujutsu (git-совместимая VCS)
- **Особенности:** Сосуществует с `.git/`, уважает все магические файлы Git (.gitignore, .gitattributes, .mailmap)

---

## Практические сценарии

### Сценарий 1: Создание пустых директорй для структуры проекта

```bash
# Создать структуру с .gitkeep
mkdir -p src/{components,hooks,utils}
mkdir -p tests/{unit,integration,e2e}
mkdir -p logs
mkdir -p tmp

# Добавить .gitkeep в пустые директории
touch src/components/.gitkeep
touch src/hooks/.gitkeep
touch logs/.gitkeep
touch tmp/.gitkeep

# Закоммитить структуру
git add .
git commit -m "chore: create project directory structure"
```

### Сценарий 2: Настройка .gitlint для валидации коммитов

```ini
# .gitlint
[general]
# Игнорировать правила
ignore=body-is-missing,conventional-commit

# Максимальная длина заголовка
[title-max-length]
line-length=72

# Минимальная длина тела
[body-min-length]
min-length=10
```

Использование:

```bash
# Проверить последний коммит
gitlint HEAD

# Проверить диапазон коммитов
gitlint HEAD~5..HEAD
```

### Сценарий 3: Настройка верификации подписей через allowedSigners

```bash
# Создать файл с доверенными ключами
cat > .gitsigners << 'EOF'
# Trusted contributors
alice@company.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...
bob@company.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...
EOF

# Настроить Git для использования файла
git config gpg.ssh.allowedSignersFile .gitsigners

# Проверить подписи коммитов
git log --show-signature
```

### Сценарий 4: Интеграция с Gerrit через .gitreview

```ini
# .gitreview
[gerrit]
host=review.example.com
port=29418
project=team/myproject.git
defaultbranch=main
```

Использование:

```bash
# Установить git-review
pip install git-review

# Отправить коммит на ревью
git review

# Отправить на ревью с указанием темы
git review -t feature-xyz
```

---

## Дополнительная информация

### Официальные ресурсы

- **Gerrit:** [gerrit-review.googlesource.com](https://gerrit-review.googlesource.com/)
- **git-review:** [pypi.org/project/git-review](https://pypi.org/project/git-review/)
- **gitlint:** [jorisroovers.com/gitlint](https://jorisroovers.com/gitlint/)
- **Jujutsu:** [github.com/martinvonz/jj](https://github.com/martinvonz/jj)

### Связанные темы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md). Шаблоны коммитов в [git_commit_template.md](./git_commit_template.md).
