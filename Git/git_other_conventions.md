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

**Сравнение альтернатив:**

| Файл | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `.gitkeep` | Нейтральное имя, не несет семантической нагрузки | По умолчанию для пустых директорий |
| `.gitignore` | Игнорирование файлов + отслеживание папки | Когда папка нужна, но содержит файлы, которые не должны отслеживаться |
| `.placeholder` | Явное указание назначения файла | Когда команда предпочитает явную семантику |

### Общие настройки проекта (.gitconfig)

Иногда в корень репозитория помещают файл `.gitconfig` с рекомендованными настройками для команды (например, алиасы или параметры `core`).

- **Безопасность:** Git никогда не загружает этот файл автоматически.
- **Подключение:** Разработчики должны вручную включить его в свой локальный конфиг командой `git config include.path ../.gitconfig`.

**Директивы включения:**

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `[include]` | Безусловное включение другого файла конфигурации | `path = ../.gitconfig` |
| `[includeIf "gitdir:PATH"]` | Условное включение на основе пути к репозиторию | `path = ~/.gitconfig-work` |
| `[includeIf "gitdir:~work/"]` | Подключение конфига для всех репозиториев в ~/work/ | Автоматический корпоративный профиль |

**Примечание:** Подробная настройка `includeIf` для разделения рабочего и личного профилей описана в [Конфигурация Git](./git_configuration.md#сценарий-2-разделение-рабочего-и-личного-профилей-includeif).

### Верификация подписей (.gitsigners)

Файл со списком доверенных публичных ключей (SSH или GPG) для проверки подлинности коммитов.

- **allowedSigners:** Используется для настройки `gpg.ssh.allowedSignersFile`.
- **Назначение:** Позволяет команде верифицировать коммиты коллег без импорта ключей в личное хранилище.

**Формат файла `.gitsigners`:**
```
# email подписанта SSH-ключ
colleague@work.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGq...
another@team.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabc...
```

**Сравнение методов подписи:**

| Критерий | GPG | SSH |
| :--- | :--- | :--- |
| **Версия Git** | Любая | 2.34+ |
| **Сложность настройки** | Высокая (gpg-agent, ключи, цепочки доверия) | Низкая (использует существующие SSH-ключи) |
| **Производительность** | Медленнее (GPG-агент) | Быстрее |
| **Интеграция с GitHub/GitLab** | Полная | Полная (с 2022) |
| **Рекомендация** | Legacy-проекты | Новые проекты |

**Примечание:** Полная инструкция по настройке SSH-подписи коммитов описана в [Конфигурация Git](./git_configuration.md#сценарий-4-подпись-коммитов-через-ssh-git-234). Отладка проблем с подписями — в [Устранение неполадок](./git_troubleshooting.md#сценарий-16-отладка-подписи-коммитов-gpg--ssh).

### Интеграция с Gerrit (.gitreview)

Используется в проектах, применяющих систему ревью Gerrit (например, OpenStack, Android).

- **Функция:** Описывает хост, порт и ветку по умолчанию для отправки кода на ревью командой `git review`.

**Формат файла `.gitreview`:**
```ini
[gerrit]
host=gerrit.example.com
port=29418
project=my-project/secure.git
```

**Ключевые параметры:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `host` | Адрес Gerrit-сервера | `gerrit.example.com` |
| `port` | SSH-порт (по умолчанию 29418) | `29418` |
| `project` | Имя проекта в Gerrit | `my-project/secure.git` |
| `defaultbranch` | Ветка по умолчанию (опционально) | `main` |

**Установка клиента:**
```bash
# macOS
brew install git-review

# Ubuntu/Debian
apt install git-review

# Проверка установки
git review --version
# → git-review 2.4.0
```

### Прочие конвенции

- **[Git Hooks — автоматизация](./git_hooks.md):** Использование фреймворков `pre-commit`, `husky` и `gitlint` для автоматизации проверок перед коммитом и пушем.

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
[diff "python"]
    xfuncname = ^[ \\t]*((class|def|async def) )?[a-zA-Z_][a-zA-Z0-9_]*\\(
```

2. Инструкция для разработчиков (выполняется один раз):
```bash
git config include.path ../.gitconfig
```

3. Проверка подключения:
```bash
git config --list --show-origin | grep "\.gitconfig"
# → file:/path/to/repo/.gitconfig	alias.st=status --short
```

### Сценарий 3: Использование .gitkeep в Docker- сборках

Инструкция `COPY` в Dockerfile не копирует пустые директории. `.gitkeep` решает эту проблему.

```dockerfile
# НЕ работает — пустые директории пропускаются
COPY logs/ /app/logs/

# РАБОТАЕТ — копируется .gitkeep, директория создается
COPY logs/.gitkeep /app/logs/.gitkeep
```

Альтернатива — создание директории через `RUN`:
```dockerfile
RUN mkdir -p /app/logs /app/temp
```

### Сценарий 4: Автоматическая настройка .gitsigners в CI/CD

При настройке верификации подписей в CI/CD-пайплайне:

```yaml
# Пример для GitHub Actions
- name: Configure commit signing verification
  run: |
    mkdir -p ~/.ssh
    echo "${{ secrets.ALLOWED_SIGNERS }}" > ~/.ssh/allowed_signers
    git config --global gpg.format ssh
    git config --global gpg.ssh.allowedSignersFile "~/.ssh/allowed_signers"
```

### Сценарий 5: Интеграция с Gerrit — отправка на ревью

```bash
# Отправить текущую ветку на ревью
git review

# Отправить конкретный коммит
git review HEAD

# Отправить с определенным темой (топиком)
git review -t feature-login

# Проверить статус ревью
git review -l
```

## Типичные ошибки при работе с конвенциями

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: Pathspec '.gitkeep' did not match any files` | Попытка добавить несуществующий `.gitkeep` | Сначала создайте файл: `touch logs/.gitkeep` |
| `error: pathspec 'review' did not match` | Утилита `git review` не установлена | Установите: `brew install git-review` или `apt install git-review` |
| `gpg: signing failed: No such file or directory` | GPG-ключ не найден или gpg-agent не запущен | Проверьте `gpg --list-secret-keys` и запустите `gpg-agent --daemon` |
| `error: Bad config line` | Невидимые символы или синтаксическая ошибка в `.gitconfig` | Проверьте файл через `git config --list --show-origin` |
| `fatal: detected dubious ownership` | Владелец директории не совпадает с текущим пользователем | `git config --global --add safe.directory $(pwd)` |
| `git review: unable to authenticate` | SSH-ключ не добавлен в Gerrit | Загрузите публичный ключ через веб-интерфейс Gerrit |

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
- [Конфигурация Git](./git_configuration.md) — подробная настройка `.gitconfig` и подпись коммитов.
