# Конфигурация Git — git config

## Определения

*   **Конфигурация Git (`git config`):** Механизм управления параметрами Git на различных уровнях (системном, глобальном, локальном, рабочем дереве), определяющий поведение команд, интерфейс, сетевое взаимодействие и безопасность.
*   **Иерархия уровней:** Система приоритетов, где настройки более специфичного уровня (например, локального) переопределяют настройки общего уровня (системного).
*   **Условные инклуды (`includeIf`):** Механизм динамического подключения конфигурационных файлов в зависимости от условий, таких как путь к текущему репозиторию. Позволяет автоматически переключать профили (email, ключи) между рабочими и личными проектами.
*   **Безопасная директория (`safe.directory`):** Мера защиты, предотвращающая выполнение команд Git в репозиториях, владельцем которых не является текущий пользователь (актуально для общих сетевых ресурсов и Docker-контейнеров).
*   **Бэкенд `reftable`:** (Git 3.0+) Новый бинарный формат хранения ссылок (веток, тегов), обеспечивающий атомарность обновлений и масштабируемость для репозиториев с огромным количеством ссылок.
*   **Окончания строк (CRLF/LF):** Символы завершения строки, различающиеся в Windows (`CRLF` — `\r\n`) и Unix-системах (`LF` — `\n`). Несогласованность настроек приводит к конфликтам слияния и ложным изменениям в истории.
*   **SSH-подпись коммитов:** Современный метод верификации автора коммита с использованием SSH-ключа вместо классического GPG.
*   **`ssh-agent`:** Фоновая программа для хранения расшифрованных приватных ключей в памяти, избавляющая от повторного ввода парольной фразы (passphrase).
*   **`git-crypt`:** Утилита для прозрачного симметричного шифрования файлов при их добавлении в индекс, позволяющая безопасно хранить секреты (.env, сертификаты) непосредственно в репозитории.
*   **`credential.helper`:** Механизм кэширования и хранения учетных данных (логин, пароль, токен) для HTTPS-удаленных репозиториев. Поддерживаемые бэкенды: `cache` (временный кэш в памяти), `store` (plain-text файл), `osxkeychain` (macOS Keychain), `wincred` (Windows Credential Manager), `libsecret` (Linux Secret Service).
*   **`core.ignoreCase`:** Логическое значение, указывающее, должно ли Git игнорировать регистр букв при отслеживании файлов. Актуально для файловых систем Windows (NTFS) и macOS (APFS), где `file.txt` и `File.txt` могут указывать на один и тот же файл.
*   **`core.longpaths`:** (Git 2.10+) Разрешает использование длинных путей (более 260 символов) на Windows. Необходим для монорепозиториев с глубокой вложенностью директорий.
*   **`core.sparseIndex`:** (Git 2.25+) Ускоряет работу разреженного извлечения (`sparse-checkout`) в режиме Cone, заменяя сканирование всего индекса на точечный доступ.
*   **`core.untrackedCache`:** (Git 2.5+) Кэширует информацию об неотслеживаемых файлах между вызовами `git status`, что сокращает время сканирования рабочего дерева.
*   **`core.commitGraph` / `fetch.writeCommitGraph`:** Включение и автоматическую запись графа коммитов (`commit-graph`), ускоряющую обход истории (`git log`, `merge`, `rebase`) на десятки процентов в репозиториях с >100k коммитов.
*   **`http.proxy` / `https.proxy`:** Настройка HTTP/HTTPS-прокси для доступа к удаленным репозиториям через корпоративные шлюзы.
*   **`merge.conflictStyle`:** Стиль отображения конфликтов слияния. `diff3` добавляет блок с базовой версией, `merge` — минимальный. `zdiff3` (Git 2.35+) — улучшенная версия diff3 с whitespace-нормализацией.
*   **`init.defaultBranch`:** Имя ветки, создаваемой по умолчанию командой `git init` (вместо устаревшего `master`).
*   **`pull.rebase`:** Поведение `git pull`: `true` — rebase локальных коммитов поверх удаленных; `false` (по умолчанию) — merge; `merges` — rebase с сохранением merge-коммитов.
*   **`rebase.autostash`:** Автоматически создавать stash перед интерактивным rebase и восстанавливать его после завершения. Полезно, когда незакоммиченные изменения мешают перебазированию.
*   **`rebase.autosquash`:** Автоматически перемещать и сжимать коммиты с префиксами `fixup!` и `squash!` во время `git rebase -i`.
*   **`fetch.prune` / `fetch.pruneTags`:** Автоматически удалять локальные ветки, исчезнувшие на удаленном сервере (`fetch.prune=true`), и удалять локальные теги, которых нет на remote (`fetch.pruneTags=true`).
*   **`push.default`:** Стратегия `git push` по умолчанию: `simple` (современный стандарт: пушить текущую ветку в одноименную на remote), `current` (любая ветка в одноименную), `upstream` (ветка в ее upstream), `matching` (все ветки с совпадающими именами — устарел).
*   **`gc.auto` / `gc.autoPackLimit` / `gc.pruneExpire`:** Пороги для автоматического запуска сборщика мусора: `gc.auto` — запускать gc при наличии N недостаточно упакованных объектов; `gc.autoPackLimit` — при превышении количества pack-файлов; `gc.pruneExpire` — минимальный возраст объектов для удаления.
*   **`extensions.worktreeConfig`:** (Git 2.20+) Разрешает каждому рабочему дереву иметь собственную конфигурацию (файл `.git/worktrees/<id>/config.worktree`), например, разные `user.email` для разных веток.
*   **`core.hooksPath`:** Каталог, в котором Git ищет хуки вместо стандартного `.git/hooks`. Позволяет версионировать хуки в отдельной директории (например, `.githooks/`).
*   **`blame.ignoreRevsFile`:** Путь к файлу `.git-blame-ignore-revs`, содержащему хэши коммитов (форматирование, рефакторинг), которые `git blame` должен пропускать.
*   **`git-lfs`:** Конфигурация Git LFS наследует иерархию `git config`, но также поддерживает файл `.lfsconfig` в корне репозитория для проектных настроек (URL сервера, параллелизм, политики fetching).

---

## Базовые концепции

### Иерархия уровней конфигурации

Git ищет настройки в следующем порядке (последнее найденное значение побеждает):

1.  **Системный (`--system`):** Параметры для всех пользователей системы. Файл: `/etc/gitconfig` или `C:\ProgramData\Git\config`.
2.  **Глобальный (`--global`):** Параметры текущего пользователя. Файл: `~/.gitconfig` или `~/.config/git/config`. Здесь настраиваются персональные данные и предпочтения.
3.  **Локальный (`--local`):** Параметры конкретного репозитория. Файл: `.git/config`. Переопределяет глобальные настройки для текущего проекта.
4.  **Рабочее дерево (`--worktree`):** (Git 2.20+) Параметры для конкретного `worktree`. Позволяет иметь разные настройки (например, email) для разных веток одного проекта в разных деревьях.

**Важность порядка:** Поскольку более специфичный уровень переопределяет общий, локальный конфиг всегда побеждает над глобальным. Это позволяет иметь универсальные предпочтения (`--global`) и точечные исключения (`--local`) без конфликтов.

**Команды управления:**
```bash
# Чтение конкретного параметра с указанием источника
git config --show-origin --get user.name

# Чтение всех параметров с источниками
git config --list --show-origin

# Удаление параметра с определенного уровня
git config --global --unset user.email
```

### Управление окончаниями строк (CRLF ↔ LF)

Неправильная настройка `core.autocrlf` может привести к тому, что Git будет видеть изменения в каждой строке файла при простом открытии его в редакторе на другой ОС.
*   **Логика Git:** Внутри базы объектов Git (в репозитории) файлы всегда должны храниться с окончаниями `LF`.
*   **`core.autocrlf true`** (Windows): Конвертирует `LF` в `CRLF` при извлечении (checkout) и `CRLF` в `LF` при коммите.
*   **`core.autocrlf input`** (macOS/Linux): Конвертирует `CRLF` в `LF` только при коммите.
*   **`core.autocrlf false`** (по умолчанию): Нет конвертации; ответственность лежит на разработчике и `.gitattributes`.

**Взаимодействие с `.gitattributes`:** Для точечного контроля над конкретными типами файлов используйте `.gitattributes` ([Атрибуты Git](./git_attributes.md)). Правила в `.gitattributes` имеют приоритет над `core.autocrlf` для соответствующих путей.

**Проблема на macOS (APFS):** APFS по умолчанию case-preserving, но case-insensitive. Это означает, что `File.txt` и `file.txt` — один и тот же файл. Если в репозитории есть файлы с одинаковыми именами в разном регистре, Git на macOS может вести себя неожиданно. Решение: `git config core.ignoreCase false` (но это может привести к ложным изменениям при работе с клонированным репозиторием на NTFS).

### Изменения прав доступа (`core.fileMode`)

Git отслеживает исполняемый бит файла (режимы `100644` vs `100755`).
*   **Проблема:** На файловых системах, не поддерживающих Unix-права (например, FAT32, NTFS в определенных режимах или SMB/NFS шары), права доступа могут эмулироваться некорректно. Это вызывает ложные срабатывания Git (файл помечен как измененный, хотя код не менялся).
*   **Решение:** Установка `git config core.fileMode false` заставляет Git игнорировать разницу в правах доступа, фокусируясь только на содержимом файлов.

### Прозрачное шифрование секретов (`git-crypt`)

Интегрируется через механизмы Git-фильтров (`clean`/`smudge`).
*   **Clean-фильтр:** Шифрует файл при выполнении `git add` (перед попаданием в индекс).
*   **Smudge-фильтр:** Дешифрует файл при выполнении `git checkout` (при попадании в рабочую директорию).
Это позволяет хранить чувствительные данные в публичных репозиториях, предоставляя доступ только владельцам ключей (GPG или симметричный ключ).

### Учетные данные и credential helpers

Git хранит учетные данные для HTTPS-удаленных репозиториев через механизм credential helpers. Это предотвращает повторный ввод логина и пароля при каждом push/pull.

**Архитектура:**
1. Git запрашивает credentials через `git credential fill`.
2. Helper возвращает `username=...` и `password=...`.
3. При успешной аутентификации Git вызывает `git credential approve` для сохранения.

**Доступные бэкенды:**

| Хелпер | Хранилище | Безопасность | Платформа | Пример команды |
|--------|-----------|--------------|-----------|----------------|
| `cache` | Память (TTL) | Средняя (пароль в памяти) | Все | `git config --global credential.helper 'cache --timeout=3600'` |
| `store` | Plain-text файл | Низкая | Все | `git config --global credential.helper store` |
| `osxkeychain` | macOS Keychain | Высокая | macOS | `git config --global credential.helper osxkeychain` |
| `wincred` | Windows Credential Manager | Высокая | Windows | `git config --global credential.helper wincred` |
| `libsecret` | Linux Secret Service | Высокая | Linux | `git config --global credential.helper libsecret` |
| `gpg` | Зашифрованный файл | Высокая | Все | `git config --global credential.helper 'gpg --default-key <id>'` |

> **Важно:** `store` сохраняет пароль в открытом виде в `~/.git-credentials`. Не используйте его на shared-машинах.

### Настройка HTTP/HTTPS и прокси

Git использует библиотеку `cURL` для сетевых операций. В корпоративных окружениях часто требуется настройка прокси и доверия к корпоративным SSL-сертификатам.

```bash
# Прокси для HTTP и HTTPS
git config --global http.proxy http://proxy.company.com:8080
git config --global https.proxy http://proxy.company.com:8080

# Отключение проверки SSL (НЕ рекомендуется для продакшена)
git config --global http.sslVerify false

# Указание корпоративного CA (Certificate Authority)
git config --global http.sslcainfo /path/to/corp-ca.crt

# Таймаут для медленных соединений (в секундах)
git config --global http.lowSpeedLimit 1000
git config --global http.lowSpeedTime 60
```

**Валидация:**
```bash
# Проверить действующие настройки прокси
git config --global http.proxy
# → http://proxy.company.com:8080

# Проверить SSL-сертификат
GIT_CURL_VERBOSE=1 git ls-remote https://github.com/user/repo.git
```

### Поведение слияния и rebase

Git предоставляет детальный контроль над поведением merge и rebase через конфигурационные параметры.

**Merge config:**
```bash
# Стиль отображения конфликтов: diff3 (с базовой версией)
git config --global merge.conflictStyle diff3

# Или zdiff3 (Git 2.35+): улучшенный diff3 с whitespace-нормализацией
git config --global merge.conflictStyle zdiff3

# Автоматическое сохранение разрешений конфликтов
git config --global rerere.enabled true
```

**Pull config:**
```bash
# Всегда rebase при pull (чистота истории)
git config --global pull.rebase true

# Rebase с сохранением merge-коммитов
git config --global pull.rebase merges

# Автоматический stash перед rebase
git config --global rebase.autostash true
```

**Push config:**
```bash
# Стратегия push: только текущую ветку в одноименную (современный стандарт)
git config --global push.default simple

# Или current: любую ветку в одноименную на remote
git config --global push.default current
```

### Сборка мусора и обслуживание (gc & maintenance)

Git автоматически упаковывает loose-объекты в pack-файлы и удаляет недоступные объекты через `git gc`. Современный `git maintenance` (Git 2.30+) предоставляет более эффективное фоновое обслуживание.

```bash
# Автоматический запуск gc при превышении порога loose-объектов
git config --global gc.auto 256

# Запуск gc при превышении количества pack-файлов
git config --global gc.autoPackLimit 50

# Срок хранения неиспользуемых объектов (по умолчанию 2 недели)
git config --global gc.pruneExpire "2.weeks.ago"

# Автоматическое обновление commit-graph при push/fetch
git config --global fetch.writeCommitGraph true
git config --global core.commitGraph true

# Фоновое обслуживание вместо gc
git config --global maintenance.auto true
git maintenance start
```

### Конфигурация рабочих деревьев (worktreeConfig)

По умолчанию все `worktree` используют общий `.git/config`. Для изолированных настроек (например, разных `user.email` для разных веток) включите `extensions.worktreeConfig`:

```bash
# Включить поддержку per-worktree конфига
git config extensions.worktreeConfig true

# Установить параметр только для текущего worktree
git config --worktree user.email "feature-work@dev.com"
git config --worktree user.name "Feature Bot"

# Проверить конфиг текущего дерева
git config --worktree --list
# → user.email=feature-work@dev.com
```

> **Внимание:** Включение `extensions.worktreeConfig` делает репозиторий нечитаемым для Git < 2.20.

### Игнорирование коммитов в blame

Файл `.git-blame-ignore-revs` позволяет скрывать «шумные» коммиты (автоформатирование, рефакторинг) из вывода `git blame`. Настройка выполняется через переменную `blame.ignoreRevsFile`:

```bash
# Локальная настройка для репозитория
git config --local blame.ignoreRevsFile .git-blame-ignore-revs

# Глобальная настройка (влияет на все репозитории)
git config --global blame.ignoreRevsFile ~/.git-blame-ignore-revs
```

**Взаимодействие с `.mailmap`:** Оба механизма действуют независимо: `.mailmap` нормализует имя автора, `ignore-revs` скрывает технические коммиты.

### Хуки и core.hooksPath

По умолчанию Git ищет хуки в `.git/hooks/`. Для версионирования и общего доступа можно изменить путь:

```bash
# Указать каталог с версионированными хуками
git config --global core.hooksPath .githooks

# Или на уровне репозитория
git config --local core.hooksPath .githooks
```

После этого хуки из `.githooks/` будут выполняться вместо `.git/hooks/`. Это позволяет коммитить хуки в репозиторий и автоматически подключать их для всей команды.

---

## Практические сценарии

### Сценарий 1: Первоначальная настройка и идентификация

```bash
# Идентификация автора (базовые настройки)
git config --global user.name "Ivan Ivanov"
git config --global user.email "ivan@example.com"

# Настройка редактора (рекомендуется VS Code, Vim или Nano)
git config --global core.editor "code --wait"

# Поведение при pull (стандарт 2026: rebase для чистоты истории)
git config --global pull.rebase true

# Кэширование паролей HTTPS (на 1 час, чтобы не вводить постоянно)
git config --global credential.helper 'cache --timeout=3600'
```

### Сценарий 2: Разделение рабочего и личного профилей (`includeIf`)

Позволяет автоматически использовать корпоративный email в папке `~/work/` и личный во всех остальных местах.

В основном `~/.gitconfig`:
```ini
[user]
    name = Ivan Ivanov
    email = ivan@personal.me

# Если путь к репозиторию начинается с ~/work/, подключить другой конфиг
[includeIf "gitdir:~/work/"]
    path = ~/.gitconfig-work
```

В файле `~/.gitconfig-work`:
```ini
[user]
    email = i.ivanov@company.com
```

### Сценарий 3: Работа с несколькими SSH-ключами

Если у вас разные ключи для GitHub, GitLab и корпоративного сервера.

**1. Добавление ключей в ssh-agent:**
```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_personal
ssh-add ~/.ssh/id_ed25519_work
```

**2. Настройка `~/.ssh/config` для автоматического выбора ключа:**
```ssh
# Рабочий аккаунт на GitLab
Host gitlab.company.com
    IdentityFile ~/.ssh/id_ed25519_work
    User git

# Личный аккаунт на GitHub
Host github.com
    IdentityFile ~/.ssh/id_ed25519_personal
    User git
```

### Сценарий 4: Подпись коммитов через SSH (Git 2.34+)

Более простой и современный способ, чем использование GPG.

```bash
# 1. Настроить формат подписи на SSH
git config --global gpg.format ssh

# 2. Указать путь к публичному ключу
git config --global user.signingkey ~/.ssh/id_ed25519.pub

# 3. Включить обязательную подпись коммитов и тегов
git config --global commit.gpgsign true
git config --global tag.gpgsign true

# 4. Настроить список доверенных лиц для верификации подписей коллег
git config --global gpg.ssh.allowedSignersFile "~/.ssh/allowed_signers"
# Добавить коллегу: echo "colleague@work.com ssh-ed25519 AAAAC3..." >> ~/.ssh/allowed_signers
```

### Сценарий 5: Безопасность в Docker и на сетевых дисках (`safe.directory`)

Если при попытке выполнить команду в контейнере вы видите ошибку `fatal: detected dubious ownership`.

```bash
# Добавить текущую директорию в список доверенных
git config --global --add safe.directory $(pwd)

# В CI/CD средах или полностью изолированных Docker-окружениях можно разрешить всё
git config --global --add safe.directory '*'
```

### Сценарий 6: Оптимизация для сверхбольших репозиториев (2026)

В 2026 году для монорепозиториев (1M+ файлов) критичны следующие настройки:

```bash
# Включить встроенный монитор файловой системы (ускоряет git status в разы)
git config --global core.fsmonitor true

# Ускорение работы с графом коммитов
git config --global core.commitGraph true
git config --global fetch.writeCommitGraph true

# Параллельная загрузка объектов (использовать 8 потоков)
git config --global fetch.parallel 8
git config --global submodule.fetchJobs 8

# Использование нового формата ссылок reftable (для новых проектов)
# git init --ref-format=reftable
```

### Сценарий 7: Прозрачное шифрование с git-crypt

1.  **Инициализация:** `git-crypt init`
2.  **Настройка доступа (через GPG):** `git-crypt add-gpg-user user@email.com`
3.  **Определение файлов для шифрования в `.gitattributes`:**
    ```text
    *.env filter=git-crypt diff=git-crypt
    config/secrets.json filter=git-crypt diff=git-crypt
    ```
4.  **Проверка:** `git-crypt status -v` покажет статус шифрования для каждого файла.

### Сценарий 8: Настройка корпоративного прокси и SSL

Для доступа к внутренним Git-серверам через корпоративный прокси:

```bash
# HTTP/HTTPS прокси
git config --global http.proxy http://proxy.corp:8080
git config --global https.proxy http://proxy.corp:8080

# Если прокси требует аутентификацию
git config --global http.proxy http://user:pass@proxy.corp:8080

# Доверие к корпоративному CA
git config --global http.sslcainfo /path/to/corp-ca.crt
```

**Валидация:**
```bash
# Проверить подключение через прокси
GIT_CURL_VERBOSE=1 git ls-remote https://gitlab.company.com/user/repo.git
# → Вывод cURL с указанием proxy
```

### Сценарий 9: Автоматическая очистка локальных веток (fetch.prune)

По умолчанию локальные ветки-тени (ветки, удаленные на remote) накапливаются. Включите `prune` для автоматической очистки:

```bash
# Автоматически удалять исчезнувшие ветки при fetch/pull
git config --global fetch.prune true

# Автоматически удалять теги, которых нет на remote
git config --global fetch.pruneTags true

# Ручной prune без fetch
git remote prune origin
```

**Валидация:**
```bash
# После fetch.prune=true исчезнувшие ветки удаляются автоматически
git branch -r
# → только актуальные remote-ветки
```

### Сценарий 10: Настройка поведенческих стратегий (push.default, rebase.autostash)

Современные стандарты для минимизации конфликтов:

```bash
# Push: только текущая ветка в одноименную (simple — стандарт Git 2.0+)
git config --global push.default simple

# Rebase: автоматический stash перед перебазированием
git config --global rebase.autostash true

# Rebase: автоматическое сжатие fixup!/squash! коммитов
git config --global rebase.autosquash true
```

### Сценарий 11: Настройка init.defaultBranch (Git 2.28+)

```bash
# Установить имя ветки по умолчанию для новых репозиториев
git config --global init.defaultBranch main

# Проверка
git init test-repo && cd test-repo && git branch --show-current
# → main
```

### Сценарий 12: Настройка core.longpaths для Windows (Git 2.10+)

```bash
# Разрешить пути длиннее 260 символов (требуется для монорепозиториев)
git config --global core.longpaths true

# Проверка
git config --global core.longpaths
# → true
```

### Сценарий 13: Настройка core.ignoreCase для кроссплатформенных проектов

```bash
# macOS/Windows (APFS/NTFS): игнорировать регистр при отслеживании
git config --global core.ignoreCase true

# Linux (ext4/xfs): чувствительность к регистру
git config --global core.ignoreCase false

# Проверка текущего значения
git config core.ignoreCase
# → true или false
```

> **Предупреждение:** Изменение `core.ignoreCase` в существующем репозитории может вызвать ложные изменения при переключении между ОС.

### Сценарий 14: Конфигурация Git LFS через .lfsconfig

Настройки LFS хранятся в `.lfsconfig` в корне репозитория. Для локальных override используйте `git config`:

```ini
# .lfsconfig (версионируется)
[lfs]
    url = https://lfs.internal.company.com/project
    concurrenttransfers = 16
    fetchexclude = "assets/raw_video/*,data/training_sets/**"
```

```bash
# Локальный override для разработчика с SSH-туннелем
git config lfs.url ssh://git@lfs.internal.company.com/project
```

**Валидация:**
```bash
# Проверить эффективный URL
git lfs env | grep Endpoint
# → Endpoint=https://lfs.internal.company.com/project/info/lfs
```

### Сценарий 15: Версионирование хуков через core.hooksPath

```bash
# Создание директории с хуками в репозитории
mkdir -p .githooks

# Создание pre-commit хука
cat > .githooks/pre-commit << 'EOF'
#!/bin/bash
echo "Running pre-commit checks..."
npm run lint
EOF
chmod +x .githooks/pre-commit

# Настройка Git на использование директории
git config --local core.hooksPath .githooks
```

### Сценарий 16: Игнорирование коммитов форматирования в blame

```bash
# Настроить файл игнорирования
git config --local blame.ignoreRevsFile .git-blame-ignore-revs

# Добавить коммит с форматированием
COMMIT_HASH=$(git rev-parse HEAD)
echo "# Black reformat 2024-06-01" >> .git-blame-ignore-revs
echo $COMMIT_HASH >> .git-blame-ignore-revs

# Проверить
git blame --mark-ignored path/to/file.py
```

### Сценарий 17: Изолированная конфигурация для Worktree

```bash
# Включить per-worktree конфигурацию
git config extensions.worktreeConfig true

# Создать worktree с отдельной конфигурацией
git worktree add -b feature-auth ../feature-auth main
cd ../feature-auth

# Настроить отдельный email для этого дерева
git config --worktree user.email "feature-auth@dev.com"

# Проверить
git config --worktree user.email
# → feature-auth@dev.com
```

### Сценарий 18: Оптимизация сборки мусора (gc)

```bash
# Настройка автоматического gc
git config --global gc.auto 256
git config --global gc.autoPackLimit 50
git config --global gc.pruneExpire "2.weeks.ago"

# Включение фонового обслуживания (альтернатива gc)
git maintenance start

# Проверка статуса
git maintenance run --verbose
# → Auto packing the repository in background
# → Auto updating the commit-graph
```

---

## Типичные ошибки и их решение

| Ошибка / Симптом | Причина | Решение |
|------------------|---------|---------|
| `fatal: detected dubious ownership` | `safe.directory` не настроен для Docker/shared-директории | `git config --global --add safe.directory '*'` |
| `LF will be replaced by CRLF` | На Windows включен `core.autocrlf` без `.gitattributes` | Настроить `.gitattributes` с `text=auto` или явно указать `eol=lf` |
| `Filename too long` (Windows) | `core.longpaths` отключен | `git config --global core.longpaths true` |
| `fatal: not a git repository` | Команда выполнена вне репозитория или репозиторий поврежден | Выполните `git init` или проверьте целостность через `git fsck` |
| `Please tell me who you are` | Не настроены `user.name` и `user.email` | `git config --global user.name "..."` и `git config --global user.email "..."` |
| `Permission denied (publickey)` | SSH-ключ не добавлен в ssh-agent или неверные права | `ssh-add ~/.ssh/id_ed25519` и `chmod 600 ~/.ssh/id_ed25519` |
| `bad config line` | Ошибка синтаксиса в `~/.gitconfig` или `.git/config` | Проверить файл конфигурации на невидимые символы, опечатки, отсутствие кавычек |
| `fatal: bad numeric config value` | В конфиг передано нечисловое значение там, где ожидается число | Проверить значения `fetch.parallel`, `gc.auto`, `core.fsmonitor` |
| `error setting certificate verify locations` | `http.sslcainfo` указывает на несуществующий файл | Проверить путь к CA-файлу или удалить параметр |
| `warning: not replacing stale url` при pull | `remote.origin.url` переопределен локально | Проверить `git config --local --get remote.origin.url` |
| `merge.conflictStyle diff3` не работает | Параметр установлен глобально, но в репозитории переопределен | `git config --local merge.conflictStyle diff3` |
| `git blame` не игнорирует коммиты | `blame.ignoreRevsFile` не установлен или хэш неполный | `git config --local blame.ignoreRevsFile .git-blame-ignore-revs` |
| `core.hooksPath` игнорируется | Хук не исполняемый (`chmod +x`) или путь относительный | Проверить права и использовать абсолютный/относительный от корня репозитория путь |
| `LFS endpoint not configured` | `.lfsconfig` отсутствует или имеет синтаксическую ошибку | Проверить синтаксис INI, секцию `[lfs]` |
| `git-crypt` не шифрует файлы | В `.gitattributes` отсутствует `filter=git-crypt` | Добавить `*.env filter=git-crypt diff=git-crypt` |
| `worktreeConfig` не работает на старом Git | Git версии < 2.20 | Обновить Git или использовать ручное управление конфигами |

---

## Ограничения и крайние случаи

1.  **Локальная природа большинства настроек:** Настройки `blame.ignoreRevsFile`, `safe.directory`, `core.hooksPath` не передаются при `git clone`. Их нужно настраивать отдельно для каждого клона или добавлять в скрипт инициализации.

2.  **`core.ignoreCase` и кроссплатформенность:** Изменение значения на противоположное в существующем репозитории может вызвать массовые ложные изменения при `git add`. Лучше настроить сразу после `git init`.

3.  **Credential helpers и CI/CD:** В CI-средах credential helper не сохраняется между запусками. Используйте переменные окружения (`GIT_ASKPASS`, `GITHUB_TOKEN`, `GITLAB_TOKEN`) или секреты пайплайна.

4.  **`extensions.worktreeConfig` и совместимость:** Включение делает репозиторий несовместимым с Git < 2.20. Участники со старым Git не смогут работать с таким репозиторием.

5.  **`gc.auto` и фоновые процессы:** Агрессивные значения `gc.auto` (например, 1) приводят к постоянному запуску gc, что замедляет коммиты. Рекомендуется 256–1024.

6.  **reftable и инструменты:** Некоторые сторонние инструменты (старые `git-filter-repo`, `git-sizer`) могут не распознавать `reftable`. Проверяйте совместимость перед миграцией.

7.  **HTTP/2 и прокси:** Некоторые корпоративные прокси не поддерживают HTTP/2. Если возникают ошибки, принудительно отключите: `git config --global http.version HTTP/1.1`.

8.  **`credential.helper store` и безопасность:** Хранит пароль в открытом виде в `~/.git-credentials`. Никогда не используйте на shared-машинах или с правами суперпользователя.

---

## Best Practices

1.  Используйте `includeIf` для разделения рабочих и личных профилей. Это исключает риск случайного коммита с личным email в корпоративный репозиторий.

2.  Настраивайте `pull.rebase true` глобально для чистоты истории. Merge-коммиты из pull создают шум в линейных проектах.

3.  Используйте `credential.helper osxkeychain` / `wincred` / `libsecret` вместо `store` для безопасности. Кэшируйте пароль только в памяти (`cache`) с коротким TTL.

4.  Настраивайте `core.hooksPath` для версионирования хуков. Это гарантирует, что все участники команды используют одинаковые проверки (lint, tests, secrets).

5.  Включайте `fetch.prune true`, чтобы локальные ветки не накапливались. Особенно актуально для активных проектов с частым удалением веток.

6.  Используйте `core.fsmonitor` и `core.untrackedCache` глобально. Это почти бесплатно даёт ускорение `git status` на 2–10x в репозиториях с 10k+ файлов.

7.  Настраивайте `gc.auto` и `gc.autoPackLimit` для автоматического обслуживания в фоне, но не делайте значения слишком агрессивными.

8.  Используйте `git maintenance start` вместо ручного `git gc` в автоматизации. `maintenance` оптимизирует расписание и не блокирует работу пользователя.

9.  Документируйте корпоративные настройки в `README.md` или `CONTRIBUTING.md` (прокси, CA, hooksPath), чтобы новые участники могли быстро настроить окружение.

10. Проверяйте конфигурацию через `git config --list --show-origin` перед коммитом настроек в репозиторий, чтобы убедиться, что нет личных/секретных данных.

---

## Безопасность

- **Не храните секреты в `~/.gitconfig`:** Файл глобального конфига часто бэкапится или синхронизируется. Используйте credential helpers вместо plain-text паролей.

- **`safe.directory '*'` в CI/CD:** Разрешает работу в любых директориях, что может быть опасно в shared-средах. Ограничьте конкретными путями там, где возможно.

- **`core.hooksPath` и целостность:** Убедитесь, что каталог с хуками защищен от записи посторонними. Злоумышленник, могущий модифицировать хук, может украсть секреты или внести вредоносный код.

- **`git-crypt` и доступ:** Управление ключами через GPG требует четкой политики отзыва. При увольнении сотрудника удалите его ключ через `git-crypt remove-gpg-user`.

- **HTTP/HTTPS и MITM:** Для корпоративных прокси используйте `http.sslcainfo` с валидным CA-файлом. Никогда не отключайте `http.sslVerify` в продакшене.

- **`credential.helper store`:** Никогда не используйте на shared-машинах. Предпочитайте `osxkeychain`, `wincred`, `libsecret` или `cache` с коротким TTL.

---

## Рекомендации по обслуживанию

- **Фоновое обслуживание:** Используйте `git maintenance start`, чтобы Git обновлял commit-graph и упаковывал объекты в фоновом режиме, не прерывая работу.

- **Регулярный `git gc`:** Если background maintenance недоступен, настройте `git config --global gc.auto 256` (запускать gc при наличии 256+ pack-файлов).

- **Мониторинг размера:** Используйте утилиту `git-sizer` для анализа размера репозитория и выявления узких мест.

---

## Дополнительная информация

### Официальные ресурсы
*   **[Git Config Documentation](https://git-scm.com/docs/git-config):** Полный и актуальный список всех ключей.
*   **[GitHub: SSH Commit Verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification):** Руководство по настройке.

### См. также
*   **[Атрибуты Git (.gitattributes)](./git_attributes.md):** Тонкая настройка фильтров, merge strategies и нормализации строк.
*   **[Git Ignore (.gitignore)](./git_ignore.md):** Паттерны игнорирования файлов и三级优先ности (global/local/system).
*   **[Внутреннее устройство Git](./git_internals.md):** Как Git хранит конфигурацию (.git/config, includeIf, reftable).
*   **[Git Basics](./git_basics.md):** Базовые определения, архитектура трёх деревьев, SHA-1.
*   **[Оптимизация производительности](./git_performance.md):** core.fsmonitor, core.untrackedCache, Scalar.
*   **[Специальные файлы Git](./git_special_files_overview.md):** Обзор всех конфигурационных файлов проекта.
