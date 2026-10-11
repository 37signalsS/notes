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

**Требования к ключам:**
- SSH-подпись поддерживается с Git 2.34+ и OpenSSH 8.1+ (OpenSSH 8.7 имеет баги — обновитесь до 8.8+).
- Рекомендуется использовать ED25519 ключи (поддержка RSA также возможна).
- Ключ должен иметь флаг `usage: Signing` (не только Authentication). Для генерации: `ssh-keygen -t ed25519 -C "comment" -f ~/.ssh/id_ed25519_sign`.

**Настройка для верификации:**
```bash
# 1. Указать формат подписи на SSH
git config --global gpg.format ssh

# 2. Указать путь к публичному ключу для подписи
git config --global user.signingkey ~/.ssh/id_ed25519_sign.pub

# 3. Указать файл с доверенными ключами (.gitsigners)
git config --global gpg.ssh.allowedSignersFile .gitsigners

# 4. Включить автоматическую подпись коммитов
git config --global commit.gpgsign true
```

**Валидация подписи:**
```bash
# Проверить подпись коммита
git verify-commit HEAD
# → Good signature (trust level: full)

# Проверить все коммиты в ветке
git log --show-signature --oneline
# → gpg: Signature made ... using SSH key ...
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

> **Статус:** Gerrit — активно развивается (последняя стабильная версия 3.14.x, 3.16 в разработке). `git-review` — официальный клиент, последняя версия 2.5.0 (OpenDev). Используется в проектах, применяющих систему ревью Gerrit (например, OpenStack, Android).

- **Функция:** Описывает хост, порт и ветку по умолчанию для отправки кода на ревью командой `git review`.

**Формат файла `.gitreview`:**
```ini
[gerrit]
host=gerrit.example.com
port=29418
project=my-project/secure.git
defaultbranch=main
```

**Ключевые параметры:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `host` | Адрес Gerrit-сервера | `gerrit.example.com` |
| `port` | SSH-порт (по умолчанию 29418) | `29418` |
| `project` | Имя проекта в Gerrit | `my-project/secure.git` |
| `defaultbranch` | Ветка по умолчанию (опционально) | `main` |
| `topic` | Топик (название задачи) по умолчанию | `feature-login` |
| `reviewers` | Список ревьюеров по умолчанию | `user1,user2` |
| `cc` | Список CC по умолчанию | `user3` |

**Установка клиента:**
```bash
# macOS
brew install git-review

# Ubuntu/Debian
apt install git-review

# Проверка установки
git review --version
# → git-review 2.5.0
```

**Валидация конфигурации:**
```bash
# Проверить, что git-review видит конфигурацию
git review --help
# → отображает параметры из .gitreview

# Проверить подключение к Gerrit
git review --version
# → git-review 2.5.0

# Проверить, что настроен правильный хост
git config --get remote.gerrit.url
# → ssh://gerrit.example.com:29418/my-project/secure.git
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

> **Важно:** Инструкция `COPY` в Dockerfile не копирует пустые директории. `.gitkeep` решает эту проблему.

**Валидация:**
```bash
# Проверить, что .gitkeep попал в образ
docker run --rm <image> ls -la /app/logs/
# → .gitkeep

# Или проверить через docker build
docker build -t test-image .
# → Successfully built <hash>
```

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

## Лучшие Practices (Best Practices)

### Общие принципы

- **Единый стандарт для команды:** Выберите одну конвенцию (например, `.gitkeep` вместо `.keep`) и документируйте её в `README.md` или `CONTRIBUTING.md`, чтобы все участники использовали одинаковые имена файлов.
- **Версионируйте конфигурации:** Файлы `.gitconfig`, `.gitsigners`, `.gitreview` должны коммититься в репозиторий, чтобы вся команда имела доступ к одинаковым настройкам.
- **Безопасность:** `.gitsigners` содержит публичные ключи — это безопасно, но `.gitconfig` может содержать персональные данные. Храните индивидуальные настройки (например, `user.name`, `user.email`) в глобальном конфиге `~/.gitconfig`, а общие — в репозитории.
- **Автоматизация:** Используйте `includeIf` в `.gitconfig` для автоматического переключения профилей между рабочими и личными проектами.
- **Проверка перед коммитом:** Используйте хуки (pre-commit, husky) для валидации конфигурационных файлов (например, проверка синтаксиса `.gitconfig`, валидация `.gitreview`).
- **Документирование:** Комментируйте нетривиальные настройки (например, назначение `.gitsigners`, структуру `.gitreview`) прямо в файлах.

### Рекомендации по конкретным конвенциям

| Конвенция | Рекомендация |
| :--- | :--- |
| `.gitkeep` | Используйте по умолчанию для пустых директорий. Избегайте `.placeholder` или `.keep` без явной необходимости — это вводит путаницу. |
| `.gitconfig` (в репозитории) | Используйте только для общих настроек (алиасы, `core.whitespace`, драйверы слияния). Персональные данные (email, ключи) должны быть в `~/.gitconfig`. |
| `.gitsigners` | Храните в репозитории, если команда требует подписи всех коммитов. Регулярно обновляйте ключи при уходе сотрудников. |
| `.gitreview` | Используйте в проектах с Gerrit. Добавьте в `README.md` инструкцию по установке `git-review` и настройке `.gitreview`. |

### Очистка (Cleanup)

```bash
# Удалить .gitkeep из директории, которая больше не нужна
git rm logs/.gitkeep
rmdir logs 2>/dev/null || true

# Удалить общую .gitconfig (если больше не используется)
git rm .gitconfig

# Очистить кэш credential helper
git config --global --unset credential.helper

# Удалить .gitsigners (если больше не используется)
git rm .gitsigners
```

---

## Типичные ошибки при работе с конвенциями

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: Pathspec '.gitkeep' did not match any files` | Попытка добавить несуществующий `.gitkeep` | Сначала создайте файл: `touch logs/.gitkeep` |
| `error: pathspec 'review' did not match` | Утилита `git review` не установлена | Установите: `brew install git-review` или `apt install git-review` |
| `gpg: signing failed: No such file or directory` | GPG-ключ не найден или gpg-agent не запущен | Проверьте `gpg --list-secret-keys` и запустите `gpg-agent --daemon` |
| `ssh-keygen: signing failed: incompatible option` | Используется SSH-ключ только для аутентификации | Пересоздайте ключ с флагом Signing: `ssh-keygen -t ed25519 -C "comment" -f ~/.ssh/id_ed25519_sign` |
| `git verify-commit: no public key found` | Файл `.gitsigners` не настроен или ключ не добавлен | Настройте `gpg.ssh.allowedSignersFile` и добавьте публичный ключ в `.gitsigners` |
| `error: Bad config line` | Невидимые символы или синтаксическая ошибка в `.gitconfig` | Проверьте файл через `git config --list --show-origin` |
| `fatal: detected dubious ownership` | Владелец директории не совпадает с текущим пользователем | `git config --global --add safe.directory $(pwd)` |
| `git review: unable to authenticate` | SSH-ключ не добавлен в Gerrit | Загрузите публичный ключ через веб-интерфейс Gerrit |
| `git review: fatal: not a git repository` | `.gitreview` находится не в корне репозитория | Убедитесь, что `.gitreview` находится в корне репозитория |

---

## Дополнительная информация

### Ограничения

- **Необязательность:** Большинство конвенций требуют установки дополнительных инструментов (gitlint, pre-commit) или ручной настройки разработчиком.
- **Разнообразие:** Разные команды могут использовать разные имена файлов (например, `.keep` вместо `.gitkeep`).
- **Совместимость с Git:** `.gitconfig` в репозитории не загружается автоматически — требуется ручное подключение через `include.path`. Это мера безопасности, предотвращающая произвольное выполнение конфигурации.
- **SSH-подпись:** Требует Git 2.34+ и OpenSSH 8.1+ (OpenSSH 8.7 имеет баги — обновитесь до 8.8+). Не поддерживается в старых версиях Git.
- **Gerrit:** `git-review` требует установки отдельного клиента и настройки SSH-доступа к Gerrit-серверу. Не совместим с GitHub/GitLab.

### Крайние случаи

1. **`.gitkeep` в ветках с `sparse-checkout`:** Если используется `sparse-checkout`, `.gitkeep` может не отображаться в рабочем дереве. Проверьте настройки `core.sparseCheckout`.
2. **`.gitconfig` и `includeIf`:** Пути в `includeIf` интерпретируются относительно домашней директории. Используйте `~` для указания путей в пределах home directory.
3. **`.gitsigners` и цепочка доверия:** SSH-подпись не имеет концепции цепочки доверия (как GPG). Доверие основывается на наличии ключа в `.gitsigners`. Если ключ удалён из `.gitsigners`, все подписи становятся недействительными.
4. **`.gitreview` и multiple remotes:** `git-review` поддерживает только один remote для Gerrit. Если у вас несколько Gerrit-инстансов, используйте разные `.gitreview` файлы или переключайте remote вручную.
5. **Конфликт имен файлов:** `.gitconfig` в репозитории может конфликтовать с глобальным `~/.gitconfig`. Приоритет — локальный конфиг репозитория (если подключен через `include.path`).

### Официальные ресурсы

- **Gerrit Code Review:** [gerrit-review.googlesource.com](https://gerrit-review.googlesource.com/)
- **Pre-commit framework:** [pre-commit.com](https://pre-commit.com/)
- **Gitlint documentation:** [jorisroovers.com/gitlint](https://jorisroovers.com/gitlint/)
- **OpenSSH signing keys:** [openssh.com/releasenotes.html](https://www.openssh.com/releasenotes.html) — Release notes for OpenSSH 8.1+
- **Git documentation — gpg.ssh.allowedSignersFile:** [git-scm.com/docs/git-config](https://git-scm.com/docs/git-config) — Описание `gpg.ssh.allowedSignersFile`
- **Git documentation — signature-format:** [git-scm.com/docs/signature-format](https://git-scm.com/docs/signature-format) — Форматы подписей (PGP, SSH, X.509)

### См. также

- [Обзор специальных файлов Git](./git_special_files_overview.md) — SSoT для стандартных файлов (.gitignore, .gitattributes).
- [Шаблоны коммитов](./git_commit_template.md) — детали Conventional Commits.
- [Git Hooks — автоматизация](./git_hooks.md) — механизмы работы хуков.
- [Конфигурация Git](./git_configuration.md) — подробная настройка `.gitconfig` и подпись коммитов.
