# Git: Устранение неполадок и отладка

## Определения

*   **Устранение неполадок Git:** Систематический процесс диагностики и решения технических проблем, связанных с доступом, сетевым взаимодействием, целостностью данных, аутентификацией и логическими ошибками в истории коммитов.
*   **Отладка транспорта (Transport Debugging):** Получение низкоуровневой информации о коммуникации Git с удаленными репозиториями по протоколам HTTP/HTTPS, SSH, Git (Dаemon) или Local для выявления проблем аутентификации, прокси, сертификатов или сети.
*   **GIT_TRACE2:** Современный фреймворк телеметрии и трассировки, позволяющий собирать данные о производительности команд, времени выполнения подпроцессов и системных ошибках в структурированных форматах (Event, Perf, Normal).
*   **Разрешение конфликтов (Conflict Resolution):** Процесс ручного исправления изменений в файлах, которые Git не смог объединить автоматически из-за пересекающихся правок или структурных изменений (переименования, удаления).
*   **`git bundle`:** Инструмент для упаковки объектов и ссылок репозитория в один бинарный файл, позволяющий передавать изменения между изолированными средами (air-gap) без прямого сетевого подключения.
*   **`git bisect`:** Инструмент отладки, использующий бинарный поиск по истории коммитов для нахождения конкретного изменения, внесшего регрессию или ошибку.
*   **`git reflog`:** Журнал всех перемещений указателя `HEAD`, служащий страховочным механизмом для восстановления коммитов, которые стали недоступны через ветки.
*   **`git fsck`:** Утилита проверки целостности файловой системы Git, выявляющая поврежденные объекты и "висячие" (unreachable) ссылки.
*   **Git Forensics (Криминалистика):** Методы глубокого анализа истории через `blame` и `log -L` для определения причин, авторов и контекста конкретных изменений кода.
*   **Credential Helper:** Механизм кэширования или хранения учетных данных для аутентификации с удаленными репозиториями (store, cache, osxkeychain, wincred, libsecret, GPG).
*   **SSH Agent:** Фоновый процесс, хранящий расшифрованные приватные ключи в памяти, чтобы избежать повторного ввода парольной фразы для каждой операции.
*   **Promisor Remote:** Удаленный репозиторий, который отдает объекты по требованию (partial clone), что может приводить к ошибкам "promised" при отсутствии сетевого доступа.
*   **`git maintenance`:** Фоновая служба обслуживания репозитория, автоматически выполняющая gc, repack, prune и обновление commit-graph.

---

## Базовые концепции

### Классификация ошибок Git

Все ошибки можно categorize по источнику сбоя:

1.  **Сетевые и транспортные:** Потеря соединения, DNS-ошибки, таймауты, SSL-сертификаты, прокси, SSH handshake failures.
2.  **Аутентификация и авторизация:** Неверные ключи, истекшие токены, отсутствие прав на запись, 2FA-блокировки, блокировка ветки на сервере.
3.  **Конфигурационные:** Ошибки в `.gitconfig`, несовместимость версий Git, некорректные параметры, проблемы с кодировкой строк.
4.  **Целостности данных:** Поврежденные loose-объекты, битые pack-files, поврежденный индекс (index), зависшие lock-файлы.
5.  **Логические и пользовательские:** Конфликты слияния, неправильные параметры команд, случайная потеря данных, race conditions при параллельной работе.

### Уровни серьезности сообщений

Git использует четыре уровня сообщений:

*   **`fatal`:** Критическая ошибка, прерывающая выполнение операции. Чаще всего указывает на невозможность продолжить (поврежденный репозиторий, неверные параметры).
*   **`error`:** Ошибка, которая не позволяет завершить конкретную операцию, но не блокирует весь инструмент (например, сбой push при diverged ветках).
*   **`warning`:** Потенциальная проблема, которая не останавливает выполнение, но может привести к ошибкам в будущем (например, замена окончаний строк LF на CRLF).
*   **`hint`:** Рекомендация по устранению предупреждения или ошибки (например, подсказка использовать `--allow-unrelated-histories`).

### Диагностика сетевых соединений и SSL

Проблемы с подключением обычно делятся на три категории:
1.  **Проблемы протокола HTTP/HTTPS:** Связаны с SSL-сертификатами (самоподписанные сертификаты, отсутствие доверия к корпоративному CA), настройками прокси-серверов или неверными заголовками аутентификации. Git использует библиотеку **cURL**.
2.  **Проблемы протокола SSH:** Связаны с правами доступа к приватным ключам (требуется `chmod 600`), несоответствием алгоритмов шифрования между клиентом и сервером или неверной конфигурацией в `~/.ssh/config`.
3.  **Корпоративные фильтры и SSL-инспекция:** Требуют импорта сертификатов в хранилище Git или временного (опасного) отключения проверки через `http.sslVerify`.

### Природа конфликтов слияния

Конфликты возникают, когда алгоритм трехстороннего слияния (3-way merge) не может однозначно определить, какое изменение является приоритетным. Это происходит при `merge`, `rebase`, `cherry-pick`, `revert` и `stash pop`.

**Механизмы diff3 и rerere:**
*   **Style diff3:** Добавляет блок `||||||| base`, показывающий текст до того, как обе ветки начали его менять. Включается через `git config --global merge.conflictStyle diff3`.
*   **rerere (Reuse Recorded Resolution):** При включении Git записывает состояние файла до и после вашего ручного разрешения конфликта и применяет его автоматически при повторном возникновении такой же ситуации.

### Трассировка и профилирование (TRACE2)

`GIT_TRACE2` заменяет устаревшие `GIT_TRACE`. Он поддерживает три формата вывода:
-   **Normal:** Читаемый человеком текст, показывающий запуск команд и время их выполнения.
-   **Perf:** Столбчатый формат для детального анализа производительности каждой фазы команды.
-   **Event:** JSON-формат для автоматизированного сбора телеметрии и анализа иерархии процессов.

### Восстановление данных и целостность

В Git практически невозможно удалить данные безвозвратно, если они были закоммичены.
*   `reflog` хранит историю перемещений `HEAD` (обычно 30–90 дней).
*   `fsck` находит объекты, не связанные с ветками или тегами (dangling objects).
*   **Повреждение индекса:** Ошибка "index file corrupt" обычно лечится удалением `.git/index` и его пересозданием из базы данных объектов.

### Цепочка аутентификации Git

Понимание того, как Git получает учетные данные, критично для диагностики проблем с доступом:

1.  **Приоритет источников:**
    1.  Переменные окружения (`GIT_ASKPASS`, `GIT_USERNAME`, `GIT_PASSWORD`)
    2.  Credential helper (настроенный через `credential.helper`)
    3.  Интерактивный ввод через терминал
2.  **SSH-аутентификация:**
    *   `ssh-agent` → `ssh-add` → приватный ключ
    *   Если агент не запущен, Git запрашивает пароль для ключа напрямую
3.  **HTTPS-аутентификация:**
    *   Basic Auth (логин:пароль)
    *   Токены (Personal Access Token, OAuth)
    *   Kerberos/Negotiate в корпоративных средах

### Жизненный цикл команды Git и точки сбоя

Каждая команда проходит через несколько этапов, на каждом из которых возможен сбой:

1.  **Парсинг аргументов и конфигурации:** Ошибки `bad config line`, `fatal: bad numeric config value`.
2.  **Разрешение путей и проверка рабочего каталога:** `fatal: not a git repository`, `Filename too long`.
3.  **Чтение базы объектов и индекса:** Поврежденные loose-объекты, `index file corrupt`, `index.lock` от предыдущего сбоя.
4.  **Выполнение логики команды:** Конфликты, отсутствующие refs, diverged истории.
5.  **Обновление ссылок и рефлога:** Запрет force-push, защищенные ветки.
6.  **Сетевой транспорт:** TLS handshake, SSH handshake, HTTP/2 negotiation, proxy CONNECT.
7.  **Запись на диск и сборка мусора:** `index.lock`, `packfile` write errors, disk full.

---

## Практические сценарии

### Сценарий 1: Отладка сетевого взаимодействия

Если операции `clone`, `fetch` или `push` завершаются с ошибками или зависают.

#### Отладка HTTP/HTTPS и SSL
```bash
# Включить подробный вывод заголовков cURL и TLS-хендшейка
GIT_CURL_VERBOSE=1 git clone <url>

# Трассировка всех переданных пакетов для отладки прокси
GIT_TRACE_CURL=1 git pull origin main

# Настройка доверия к корпоративному CA ( Certificate Authority)
git config --global http.sslcainfo /path/to/corp-ca.crt
```

#### Отладка SSH
```bash
# Использовать режим максимальной детализации SSH клиента
GIT_SSH_COMMAND="ssh -vvv" git fetch origin

# Проверка, какой ключ предлагается серверу (явное указание ключа)
export GIT_SSH_COMMAND="ssh -i ~/.ssh/id_rsa_work -F /dev/null"
git push origin main
```

### Сценарий 2: Глубокое разрешение конфликтов

#### 1. Идентификация и анализ
```bash
# Список файлов с конфликтами (статус UU)
git status -s | grep "^UU"

# Включение стиля diff3 для лучшего контекста
git config --global merge.conflictStyle diff3
git diff
```

#### 2. Инструменты выбора версий
```bash
# Выбрать версию из текущей ветки (ours)
git checkout --ours path/to/file
# или (современный вариант)
git restore --source=HEAD -- path/to/file

# Выбрать версию из сливаемой ветки (theirs)
git checkout --theirs path/to/file
# или (современный вариант)
git restore --source=MERGE_HEAD -- path/to/file
```

#### 3. Таблица типов конфликтов и подходы к решению

| Тип конфликта | Ситуация | Рекомендуемое действие |
| :--- | :--- | :--- |
| `modify/modify` | Изменены одни и те же строки. | Ручное слияние логики, удаление маркеров. |
| `delete/modify` | Ветка A удалила файл, B изменила его. | Решить: `git rm` (удалить) или `git add` (оставить версию B). |
| `add/add` | Обе ветки создали файл с одним именем. | Объединить содержимое или переименовать один из файлов. |
| `rename/modify` | В A — переименование, в B — правки. | Git обычно справляется, но проверьте правильность путей. |
| `rename/rename` | Разные новые имена для одного файла. | Выбрать одно имя, исправить импорты/ссылки. |
| `binary/modify` | Бинарный файл изменен в одной ветке, удален/изменен в другой. | Выбрать одну версию полностью; слияние невозможно. |

### Сценарий 3: Поиск виновного коммита (Bisect)

Метод бинарного поиска для нахождения регрессии.

```bash
# 1. Начать процесс
git bisect start

# 2. Пометить текущее состояние как плохое, а старое как хорошее
git bisect bad HEAD
git bisect good v2.0.0

# 3. Git переключит на середину диапазона. Проверьте код и ответьте:
git bisect good  # если ошибки нет
git bisect bad   # если ошибка воспроизводится

# 4. Автоматизация через тестовый скрипт
git bisect run pytest tests/test_regression.py

# 5. Выход из режима отладки
git bisect reset
```

### Сценарий 4: Восстановление потерянных коммитов и данных

Подробное руководство по `git reflog` см. в **[Git Reflog — журнал ссылок](./git_reflog.md)**.

#### Восстановление после reset --hard или удаления ветки
```bash
# 1. Просмотреть историю перемещений HEAD
git reflog
# → 1a2b3c4 HEAD@{0}: reset: moving to HEAD~1
# → 5e6f7g8 HEAD@{1}: commit: feat: very important feature (ПОТЕРЯНО)

# 2. Восстановить коммит на новую ветку
git branch recovery-branch 5e6f7g8
```

#### Восстановление поврежденного индекса и снятие блокировок
```bash
# Если ошибка: fatal: index file corrupt
rm .git/index
git reset  # Пересоздаст индекс из HEAD

# Если ошибка: Another git process seems to be running
rm .git/index.lock
```

#### Глубокий поиск "висячих" объектов
```bash
# Найти объекты, не связанные ни с одной ссылкой
git fsck --lost-found
# Результаты будут в .git/lost-found/commit/
```

### Сценарий 5: Git Bundle (Офлайн работа)

#### Создание пакета (Машина A)
```bash
# Бандл со всей историей всех веток
git bundle create repo.bundle --all

# Инкрементальный бандл (только новые изменения в main относительно сервера)
git bundle create updates.bundle main ^origin/main
```

#### Применение пакета (Машина B)
```bash
# Проверить совместимость бандла
git bundle verify updates.bundle

# Получить изменения как из удаленного репозитория
git remote add bundle_file /path/to/updates.bundle
git pull bundle_file main
```

### Сценарий 6: Анализ истории (Forensics)

```bash
# Кто изменил конкретную строку (игнорируя коммиты с форматированием)
git blame -L 50,60 -w -C path/to/file.c

# История изменений конкретной функции
git log -L :my_function:path/to/file.c
```

### Сценарий 7: Отладка LFS и субмодулей

```bash
# Проверка окружения LFS и путей фильтрации
git lfs env

# Принудительная загрузка всех объектов (если файлы-указатели не заменились)
git lfs fetch --all
git lfs checkout

# Ремонт субмодулей
git submodule sync --recursive
git submodule update --init --recursive --force
```

### Сценарий 8: Отладка игнорирования файлов (check-ignore)

Подробное руководство по диагностике правил `.gitignore` см. в **[Игнорирование файлов в Git](./git_ignore.md#сценарий-1-отладка-невидимых-правил)**.

**Краткая справка:**
```bash
# Показать правило и файл конфигурации, вызывающий игнорирование
git check-ignore -v path/to/file.log

# Проверить все источники (включая exclude и глобальные)
git check-ignore -v --no-index path/to/file
```

### Сценарий 9: Работа с Git Worktree и очистка

```bash
# Просмотр списка всех рабочих деревьев
git worktree list

# Очистка информации о недоступных (удаленных вручную) рабочих деревьях
git worktree prune
```

**Примечание:** Полный разбор сценариев, архитектуры `$GIT_COMMON_DIR`/`$GIT_DIR`, диагностики и устранения неполадок по worktree — в **[Git Worktree — параллельные рабочие директории](./git_worktree.md)**. Ниже — только типовые точки входа.

### Сценарий 10: Удаление секретов из истории Git

Полное руководство по очистке истории от секретов см. в **[Игнорирование файлов в Git](./git_ignore.md#утечка-секретов-и-очистка-истории)**.

**Краткая справка:**
```bash
# 1. Установить git-filter-repo
pip install git-filter-repo

# 2. Удалить файл из всей истории
git filter-repo --path secrets.env --invert-paths

# 3. Добавить в .gitignore
echo "secrets.env" >> .gitignore
git add .gitignore && git commit -m "chore: add secrets.env to gitignore"

# 4. Force push (требуется согласие команды!)
git push origin --force --all
```

**Важно:**
- Все коллеги должны переклонировать репозиторий после force-push.
- Для предотвращения используйте `git-secrets`, `gitleaks` в pre-commit хуках.
- См. [Защита от секретов в Git](../Security/Tools/gitleaks.md).

### Сценарий 11: Восстановление после Detached HEAD

**Симптом:** `git status` показывает `HEAD detached at abc1234`. Изменения, сделанные в этом состоянии, не принадлежат никакой ветке.

```bash
# 1. Если коммиты еще не потеряны — создать ветку из текущего HEAD
git switch -c recovery-branch

# 2. Если переключились без создания ветки — найти коммит через reflog
git reflog
# → abc1234 HEAD@{0}: checkout: moving from main to abc1234

# 3. Вернуться на ветку
git switch main

# 4. Влить recovery-branch
git merge recovery-branch
# или
git cherry-pick abc1234
```

**Валидация:**
```bash
git status
# → На ветке main, коммиты recovery-branch доступны
```

### Сценарий 12: Отладка Credential Helpers и SSH Agent

#### Проблемы с HTTPS-credentials
```bash
# Проверить, какой credential helper активен
git config --global credential.helper
# → osxkeychain / cache / store / manager-core

# Очистить кэшированные credentials (macOS)
git credential-osxkeychain erase
host=github.com
protocol=https

# Принудительно запросить credentials
unset GIT_ASKPASS
git credential-cache exit
git pull origin main
```

#### Проблемы с SSH agent
```bash
# Проверить, запущен ли агент
ssh-add -l
# → The agent has no identities. (если пусто)

# Добавить ключ
ssh-add ~/.ssh/id_ed25519

# Если агент не отвечает — перезапустить (macOS)
launchctl unload ~/Library/LaunchAgents/ssh-agent.plist 2>/dev/null || true
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# Проверить подключение к GitHub
ssh -T git@github.com
# → Hi username! You've successfully authenticated...
```

### Сценарий 13: Диагностика HTTP-прокси и корпоративного CA

```bash
# Проверить, настроен ли прокси
git config --global --get http.proxy
# → http://proxy.corp:8080

# Отключить прокси для конкретного хоста
git config --global --unset http.proxy
# или для сессии
unset http_proxy https_proxy

# Проверить CA-сертификаты
git config --global http.sslcainfo
# → /path/to/corp-ca.crt

# Проверить цепочку сертификатов сервера
openssl s_client -connect github.com:443 -servername github.com -showcerts </dev/null

# Временное отключение проверки SSL (ТОЛЬКО ДЛЯ ДИАГНОСТИКИ)
GIT_SSL_NO_VERIFY=1 git clone https://github.com/user/repo.git
```

### Сценарий 14: Восстановление после повреждения Packfile

```bash
# Симптом: fatal: packed object ... is corrupt

# 1. Найти поврежденный pack
git fsck --full
# → error: packfile ... sha1 checksum mismatch

# 2. Восстановить из bundle или upstream
git fetch --all --prune

# 3. Если fetch не помогает — удалить поврежденный pack и пересобрать
rm -rf .git/objects/pack/pack-*.pack .git/objects/pack/pack-*.idx
git repack -a -d --depth=250 --window=250

# 4. Проверить целостность
git fsck --full
# → checking object directories: 100% (256/256), done.
```

### Сценарий 15: Диагностика производительности и GC

```bash
# Медленный git status — проверить untracked cache и fsmonitor
git config core.untrackedCache true
git config core.fsmonitor true

# Запустить фоновое обслуживание
git maintenance start

# Проверить, нужно ли обслуживание (exit 0 — нужно)
git maintenance is-needed

# Проверить размер репозитория
git count-objects -vH
# → size: 1.2 GiB
# → size-pack: 800.00 MiB

# Принудительный GC с прогрессивными параметрами
git gc --aggressive --prune=now

# Проверить эффективность pack-файлов
git verify-pack -v .git/objects/pack/pack-*.idx | sort -k3 -n | tail -5
```

### Сценарий 16: Отладка подписи коммитов (GPG / SSH)

```bash
# Проверить, настроено ли подписание
git config --global user.signingkey
git config --global commit.gpgsign

# Проверить доступность ключа
gpg --list-secret-keys --keyid-format long

# Тестовый коммит с подписью
git commit -S -m "test: signed commit"

# Если подпись не проходит проверку — проверить gpg-agent
gpgconf --kill gpg-agent
gpg-agent --daemon

# Для SSH-подписи коммитов
ssh-add -l
git commit -S -m "test: ssh-signed commit"
```

### Сценарий 17: Partial Clone и Promisor Remote

```bash
# Симптом: fatal: the remote end hung up unexpectedly при clone
# или warning: waiting for non-promisor object ...

# 1. Проверить конфигурацию partial clone
git config --local remote.origin.promisor
git config --local remote.origin.partialclonefilter

# 2. Преобразовать в полный клон
git fetch --unshallow
# или
git config --unset remote.origin.promisor
git fetch --all

# 3. Если filter работает некорректно
git config --unset remote.origin.partialclonefilter
git fetch origin --unshallow --no-filter
```

### Сценарий 18: Sparse-checkout и проблемы путей

```bash
# Симптом: файлы отсутствуют в рабочем каталоге
# или fatal: Sparse checkout leaves no entry on working directory

# 1. Проверить режим sparse-checkout
git sparse-checkout list
# → ожидаемый список путей

# 2. Переключиться на полный checkout
git sparse-checkout disable

# 3. Или явно указать нужные пути (Git 2.25+)
git sparse-checkout set src/ docs/ README.md

# 4. Для старых версий Git
git config core.sparseCheckout true
echo "src/*" > .git/info/sparse-checkout
git read-tree -mu HEAD
```

### Сценарий 19: Восстановление после сбоя rebase/merge

```bash
# Симптом: CONFLICT ... Automatic merge failed; fix conflicts and then run 'git rebase --continue'

# 1. Отмена сброшенного rebase
git rebase --abort

# 2. Просмотр статуса конфликтов
git status
# → У вас есть неразрешенные пути (both modified: file.txt)

# 3. Использование rerere (если включен)
git rerere
# → Recorded resolution for 'file.txt'

# 4. Принудительное продолжение после разрешения
git add file.txt
git rebase --continue

# 5. Если rebase застрял — сбросить на исходное состояние
git rebase --abort
git reset --hard ORIG_HEAD
```

### Сценарий 20: Отладка субмодулей (stale URLs и init failures)

```bash
# Симптом: fatal: unable to access 'https://github.com/...': Could not resolve host
# или Authentication failed for 'https://github.com/...'

# 1. Синхронизировать URL субмодулей
git submodule sync --recursive

# 2. Обновить и инициализировать заново
git submodule update --init --recursive --force

# 3. Если URL изменился (например, HTTPS → SSH)
git config -f .gitmodules submodule.<name>.url git@github.com:user/repo.git
git submodule sync --recursive
git submodule update --init --recursive

# 4. Проверить статус всех субмодулей
git submodule status
# → -abc1234... (не инициализирован)
# → +def5678... (изменен)
```

### Сценарий 21: Отладка Git Daemon и локального сервера

```bash
# Симптом: fatal: unable to connect to daemon (или localhost:9418)

# 1. Запустить daemon вручную (отладка)
git daemon --verbose --export-all --base-path=/path/to/repos/

# 2. Проверить, слушает ли порт
nc -zv localhost 9418
# → Connection to localhost 9418 port [tcp/*] succeeded!

# 3. Для systemd-службы
sudo systemctl status git-daemon
sudo journalctl -u git-daemon -f

# 4. Частые проблемы:
#    - Файрвол блокирует порт 9418
#    - base-path указывает на несуществующую директорию
#    - export-ignore в .git/export-ignore блокирует доступ к репозиторию
```

### Сценарий 22: Template Directory и инициализация репозитория

```bash
# Симптом: fatal: template [...] not found
# или кастомные хуки/файлы не появляются при git init

# 1. Проверить глобальный template
git config --global init.templateDir
# → /usr/share/git-core/templates

# 2. Создать собственный template
mkdir -p ~/.git-templates/hooks
cp my-pre-commit-hook ~/.git-templates/hooks/pre-commit
chmod +x ~/.git-templates/hooks/pre-commit

# 3. Настроить Git
git config --global init.templateDir ~/.git-templates

# 4. Проверить
git init test-repo
ls test-repo/.git/hooks/
# → должен содержать pre-commit из template
```

### Сценарий 23: Clone с неверной веткой и Shallow Clone

```bash
# Симптом: ветка не та, или shallow clone вызывает ошибки

# 1. Явно указать ветку при clone
git clone -b develop --single-branch https://github.com/user/repo.git

# 2. Преобразовать shallow в полный клон
git fetch --unshallow

# 3. Если shallow clone поврежден — удалить и клонировать заново
rm -rf repo/.git/shallow
git repack -a -d

# 4. Clone с ограничением по глубине
git clone --depth 1 --branch v1.0.0 https://github.com/user/repo.git
# → предупреждение: shallow clone, истории нет
```

### Сценарий 24: Диагностика проблем с кодировкой и локализацией

```bash
# Симптом: нечитаемые имена файлов, warning: Cannot merge binary files: ...
# или fatal: unable to access '...': Conversion from string ... to UTF-8 failed

# 1. Проверить локаль
locale
# → LANG=en_US.UTF-8

# 2. Принудительно установить UTF-8
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# 3. Для Windows — включить поддержку Unicode
git config --global core.precomposeunicode true

# 4. Проверить кодировку файлов в индексе
git ls-files -z | xargs -0 file --mime-encoding
```

---

## Дополнительная информация

### Распространенные ошибки и решения

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: not a git repository` | Команда выполнена вне репозитория или `.git` поврежден. | `git init` или перейдите в директорию; проверьте `git fsck`. |
| `Please tell me who you are` | Не настроены `user.name` и `user.email`. | `git config --global user.name` и `git config --global user.email`. |
| `fatal: not a valid object name` | Указан несуществующий коммит или ветка. | Проверьте хэш или имя ветки через `git log` / `git branch`. |
| `error: failed to push some refs` | Удаленная ветка содержит коммиты, которых нет локально. | `git pull --rebase` перед `git push`. |
| `CONFLICT (content): Merge conflict` | Автоматическое слияние невозможно. | Разрешите конфликты вручную, `git add` и `git commit`. |
| `Your local changes would be overwritten` | Переключение ветки приведет к потере изменений. | `git stash` или `git commit` перед переключением. |
| `fatal: refusing to merge unrelated histories` | Репозитории имеют независимые истории. | `git pull --allow-unrelated-histories` (осторожно). |
| `fatal: detected dubious ownership` | `safe.directory` не настроен для Docker/shared-директории. | `git config --global --add safe.directory '*'`. |
| `LF will be replaced by CRLF` | На Windows включен `core.autocrlf` без `.gitattributes`. | Настроить `.gitattributes` с `text=auto`. |
| `Filename too long` (Windows) | `core.longpaths` отключен. | `git config --global core.longpaths true`. |
| `Permission denied (publickey)` | SSH-ключ не добавлен в ssh-agent или неверные права. | `ssh-add ~/.ssh/id_ed25519`; `chmod 600 ~/.ssh/id_ed25519`. |
| `bad config line` | Ошибка синтаксиса в `~/.gitconfig` или `.git/config`. | Проверить файл на невидимые символы и опечатки. |
| `fatal: bad numeric config value` | В конфиг передано нечисловое значение. | Проверить `fetch.parallel`, `gc.auto`, `core.fsmonitor`. |
| `error setting certificate verify locations` | `http.sslcainfo` указывает на несуществующий файл. | Проверить путь к CA-файлу или удалить параметр. |
| `warning: not replacing stale url` | `remote.origin.url` переопределен локально. | Проверить `git config --local --get remote.origin.url`. |
| `fatal: index file corrupt` | Повреждение `.git/index`. | `rm .git/index && git reset`. |
| `Another git process seems to be running` | Зависший `index.lock` от предыдущего сбоя. | `rm .git/index.lock`. |
| `fatal: unable to access '...': Could not resolve host` | DNS-проблемы или нет сетевого подключения. | Проверить `/etc/resolv.conf`, `nslookup`, файрволы. |
| `fatal: the remote end hung up unexpectedly` | Сервер разорвал соединение. | Проверить SSH/HTTPS ключи, размер репозитория, лимиты. |
| `fatal: Unable to create '/path/.git/index.lock': File exists.` | Предыдущий процесс Git не завершился корректно. | Убедиться, что нет других Git-процессов, удалить `index.lock`. |
| `error: src refspec ... does not match any` | Ветка не существует локально или нет коммитов. | Проверить `git branch -a`; убедиться, что есть хотя бы один коммит. |
| `fatal: remote error: upload-pack: not our ref ...` | На сервере нет такой ветки или нет прав. | Проверить права, имя ветки, существование на сервере. |
| `hint: Updates were rejected because the remote contains work that you do not have locally` | Не-fast-forward push. | Сделать `git pull --rebase` перед push. |
| `fatal: Reference has invalid format: refs/stash` | Поврежденный ref-файл. | Удалить `.git/refs/stash` и `.git/logs/refs/stash`. |
| `error: unable to access 'https://...': SSL certificate problem: self signed certificate` | Самоподписанный сертификат. | Добавить в `http.sslcainfo` или настроить доверие. |
| `fatal: cannot lock ref ...: Unable to create '/path/.git/refs/...'` | Нет прав на запись в `.git/refs/`. | Проверить права доступа к директории репозитория. |
| `error: pathspec '...' did not match any file(s) known to git` | Файл не отслеживается или удален. | Проверить `git status`, `git ls-files`. |

### Best Practices

1.  **Включите rerere глобально:** `git config --global rerere.enabled true` — автоматически запоминает разрешения конфликтов для повторного использования.
2.  **Используйте `diff3` для конфликтов:** `git config --global merge.conflictStyle diff3` — показывает базовую версию в конфликтных маркерах.
3.  **Настройте `fsmonitor` и `untrackedCache`:** Ускоряют `git status` в 2–10 раз на репозиториях с 10k+ файлов.
4.  **Используйте `git maintenance` вместо ручного `git gc`:** Фоновое обслуживание не блокирует работу и оптимизирует расписание.
5.  **Не отключайте `http.sslVerify` в продакшене:** Вместо этого импортируйте корпоративный CA в `http.sslcainfo`.
6.  **Никогда не используйте `credential.helper store` на shared-машинах:** Предпочитайте `osxkeychain`, `wincred`, `libsecret` или `cache` с коротким TTL.
7.  **Проверяйте `git config --list --show-origin` перед коммитом настроек:** Убедитесь, что нет личных/секретных данных.
8.  **Используйте `--force-with-lease` вместо `--force`:** Защищает от перезаписи чужих коммитов.
9.  **Для больших репозиториев включите `core.bigFileThreshold` и `core.preloadIndex`:** Улучшают производительность работы с большим количеством файлов.
10. **Регулярно запускайте `git fsck` в критически важных репозиториях:** Раннее обнаружение повреждений упрощает восстановление.

### Ограничения и особенности

1.  **Reflog имеет срок хранения:** По умолчанию 30–90 дней (зависит от `gc.pruneExpire`). После expires unreachable объекты удаляются.
2.  **`git fsck` может потреблять много памяти:** На репозиториях >10 GB используйте `--no-reflogs` для пропуска проверки reflog.
3.  **SSH-ключи могут быть зашифрованы:** Если `ssh-add` запрашивает парольную фразу, убедитесь, что `ssh-agent` запущен.
4.  **HTTP/2 и прокси:** Некоторые корпоративные прокси не поддерживают HTTP/2. Если возникают ошибки, принудительно отключите: `git config --global http.version HTTP/1.1`.
5.  **Windows и долгие пути:** Даже с `core.longpaths true`, некоторые инструменты (IDE, архиваторы) могут не поддерживать пути >260 символов.
6.  **`git maintenance` требует Git ≥2.30:** На старых системах используйте `git gc --auto` в cron.
7.  **Субмодули не наследуют credential helpers:** Если родительский репозиторий использует credential helper, субмодули могут требовать отдельной аутентификации.
8.  **`safe.directory` может блокировать CI/CD:** В контейнерах и CI-средах часто требуется глобальный `safe.directory '*'`.

### Официальные ресурсы

*   **Git Internals - Debugging:** [git-scm.com/book/en/v2/Git-Internals-Debugging](https://git-scm.com/book/en/v2/Git-Internals-Debugging)
*   **Git Trace2 Documentation:** [git-scm.com/docs/api-trace2](https://git-scm.com/docs/api-trace2)

### См. также

*   [Git Basics](./git_basics.md) — архитектура трёх деревьев (HEAD, index, working tree) для понимания состояний.
*   [Разрешение конфликтов](./git_conflict_resolution.md) — паттерны, mergetool, rerere при слиянии.
*   [Конфигурация Git](./git_configuration.md) — настройка SSH, SSL и уровней конфигурации.
*   [Манипуляции с историей](./git_history_manipulation.md) — детали `reset`, `rebase` и работы с `reflog`.
*   [Внутреннее устройство Git](./git_internals.md) — объектная модель и формат базы данных.
*   [Git Reflog](./git_reflog.md) — журнал ссылок для восстановления потерянных коммитов.
