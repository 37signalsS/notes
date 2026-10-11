# Конфигурация Git LFS — .lfsconfig

**Актуально для:** Git LFS 3.8.x (текущая версия 3.8.0 от 27.08.2026; whitelist ключей `.lfsconfig`, иерархия и значения по умолчанию проверены по `git-lfs-config(5)` и исходникам git-lfs main; `lfs.transfer.batchSize` — с 3.6.0)

## Определения

**`.lfsconfig`** — файл конфигурации Git LFS, который хранится в корне репозитория и версионируется вместе с кодом. Позволяет задать общие для всех участников проекта настройки LFS-сервера и политики передачи данных. Формат — тот же, что у `.gitconfig` (INI с секцией `[lfs]` и подсекциями).

**Safe keys** — подмножество ключей `lfs.*`, разрешённых в `.lfsconfig`. Ключи вне этого списка игнорируются с предупреждением на stderr. Ограничение введено из соображений безопасности (см. раздел «Безопасность»).

Использование `.lfsconfig` критично для проектов с кастомными LFS-серверами или специфическими требованиями к производительности и безопасности.

**Важно:** `.lfsconfig` задаёт только параметры поведения LFS-клиента (URL сервера, политики fetching). Для определения, какие файлы обрабатываются через LFS, по-прежнему требуется файл `.gitattributes` с правилом `filter=lfs` (см. git_attributes.md). Отсутствие `.gitattributes` означает, что LFS не будет применяться к файлам, даже если `.lfsconfig` настроен.

---

## Базовые концепции

### Иерархия и приоритеты

Git LFS читает конфигурацию из всех файлов, поддерживаемых `git config -l` (системный, глобальный, локальный), плюс `.lfsconfig`. Приоритет — выше переопределяет ниже (документировано в `git-lfs-config(5)`: «Settings from Git configuration files override the `.lfsconfig` file»):

1. **Локальный конфиг** (`.git/config`; при множественных worktree — worktree-конфиг) — высший приоритет.
2. **Глобальный конфиг пользователя** (`~/.gitconfig` / `$XDG_CONFIG_HOME/git/config`).
3. **Системный конфиг** (`/etc/gitconfig`).
4. **`.lfsconfig`** — низший приоритет.

Следовательно, `.lfsconfig` задаёт *значения по умолчанию для проекта*, а не жёсткую политику: локальный `git config lfs.url ...` всегда победит значение из `.lfsconfig`. Это полезно, если конкретному разработчику нужен другой URL (например, через прокси или SSH-туннель).

Если `.lfsconfig` отсутствует в рабочей директории, Git LFS проверяет индекс (`:.lfsconfig`), затем `HEAD:.lfsconfig`. В bare-репозитории проверяется только `HEAD`.

Если `.lfsconfig` отсутствует совсем, Git LFS использует значения по умолчанию и настройки из `.git/config`/`~/.gitconfig`. В этом случае каждый разработчик может иметь разное поведение LFS, что приводит к неожиданным проблемам с производительностью и безопасностью.

### Формат файла `.lfsconfig`

Синтаксис INI, как у `.gitconfig`. Секции и имена переменных **не чувствительны к регистру** (Git приводит их к нижнему регистру), а вот **имена подсекций чувствительны**: если задано `lfs.customTransfer.myAdapter.path`, то ключ `lfs.customtransfer.myadapter.args` принято не будет (разные подсекции). То же касается имён remote и URL в трёхчастных ключах.

Пример корректного файла (только разрешённые ключи):

```ini
# .lfsconfig
[lfs]
    url = https://lfs.example.com/project/info/lfs
    fetchexclude = assets/raw_video/*,data/training_sets/**
```

Записать файл можно и командой (пример из `git-lfs-config(5)`):

```bash
git config -f .lfsconfig lfs.url https://lfs.example.com/foo/bar/info/lfs
```

### LFSCONFIG: какие ключи разрешены в `.lfsconfig`

Из соображений безопасности в `.lfsconfig` работает только whitelist (раздел LFSCONFIG в `git-lfs-config(5)`):

- `lfs.url` и `remote.<remote>.lfsurl`
- `lfs.pushurl`
- `lfs.fetchinclude`, `lfs.fetchexclude`
- `lfs.locksverify` (per-URL-вариант `lfs.<url>.locksverify` — только в Git-конфиге)
- `lfs.allowincompletepush`
- `lfs.skipdownloaderrors`
- `lfs.gitprotocol` (в whitelist; не описан в разделе опций `git-lfs-config(5)`)
- `lfs.<url>.access` (любой трёхчастный ключ, оканчивающийся на `.access`)
- `remote.<name>.lfsurl`
- `lfs.extension.<name>.priority` (из исходников; свойства `clean`/`smudge` расширений в `.lfsconfig` игнорируются)

Всё остальное — `concurrenttransfers`, `transfer.batchSize`, `pathFilterCacheSize`, `fetchrecentrefsdays`, `pruneoffsetdays`, `customtransfer.<name>.*`, `storage` и т.д. — в `.lfsconfig` **игнорируется**. При чтении конфигурации выводится предупреждение:

```bash
# → warning: These unsafe '.lfsconfig' keys were ignored:
#
#   lfs.concurrenttransfers
#   lfs.transfer.batchSize
```

Такие параметры задаются в локальном `.git/config` или глобальном `~/.gitconfig`.

### Основные параметры, разрешённые в `.lfsconfig`

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.url` / `remote.<remote>.lfsurl` | URL LFS API. Явное указание в `.lfsconfig` предотвращает атаки через подмену URL при клонировании | пусто (выводится из URL клона) |
| `lfs.pushurl` | Отдельный URL для загрузки данных (push) | пусто (от непуш-URL или URL клона) |
| `lfs.fetchinclude` | При fetch скачивать только объекты, чьи пути matching хотя бы одному элементу списка через запятую; wildcards как в gitignore(5) | — |
| `lfs.fetchexclude` | При fetch не скачивать объекты, matching списку через запятую | — |
| `lfs.locksverify` | Проверка блокировок перед push (подробно — в сценарии 6) | `null` (попытка вызова с предупреждением) |
| `lfs.<url>.access` | Метод авторизации для URL. Обычно LFS выставляет сам при ответе 401; значение `basic` — запрашивать credentials до batch-запросов, иначе сначала делается публичный запрос | публичный запрос сначала |
| `lfs.allowincompletepush` | Разрешить push, если объекты отсутствуют в локальном кэше | `false` |
| `lfs.skipdownloaderrors` | Не прерывать smudge-фильтр при ошибке загрузки: checkout завершается успешно, а недоступный файл остаётся pointer-ом (аналог — переменная `GIT_LFS_SKIP_DOWNLOAD_ERRORS=1`). Внимание: git-команды будут сообщать об успехе даже при неудачной загрузке | `false` |

**Примечание по `lfs.fetchinclude`/`lfs.fetchexclude`:** паттерны matching по правилам gitignore(5), разделитель — запятая. Параметры применяются к `git lfs fetch`/`git lfs pull` (включая `--recent`-окно) и к `--include`/`-I`/`--exclude`/`-X` на уровне команд.

### Основные параметры только для Git-конфига (НЕ в `.lfsconfig`)

**Передача и retry:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.concurrenttransfers` | Количество одновременных загрузок/выгрузок | 8 |
| `lfs.transfer.batchSize` | Объектов в одном batch-запросе к LFS API (с 3.6.0). Менять с осторожностью: влияет на нагрузку на сервер, который может вернуть HTTP 413 при слишком большом значении | 100 |
| `lfs.transfer.maxretries` | Число retry на OID до признания передачи неудачной | 8 |
| `lfs.transfer.maxretrydelay` | Макс. задержка между retry (экспоненциальный backoff; `Retry-After` от сервера переопределяет задержку для этого запроса); 0 — без задержек | 10 с |
| `lfs.transfer.maxRetryTime` | Макс. ожидание при `Retry-After` от сервера; при большем запросе — предупреждение и провал передачи | 300 с |
| `lfs.transfer.maxverifies` | Число запросов верификации на OID | 3 |
| `lfs.transfer.httpDownloadEncoding` / `lfs.transfer.<url>.httpDownloadEncoding` | Кодирование при HTTP-скачивании: `gzip` или `zstd` | `gzip` |
| `lfs.transfer.enablehrefrewrite` | Переписывать href объектов через `url.*.insteadof`/`pushinsteadof` | `false` |
| `lfs.basictransfersonly` | Только простые HTTP-передачи (обход багов/несовместимостей; отключает resumable-загрузки и tus.io) | `false` |
| `lfs.tustransfers` | Включить возобновляемые выгрузки через tus.io API (фича в разработке) | `false` |
| `lfs.standalonetransferagent` | Использовать указанный кастомный агент напрямую, не спрашивая сервер; либо внутренний `lfs-standalone-file` для `file:///` URL | — |
| `lfs.customtransfer.<name>.path` | Путь к процессу кастомного агента передачи (протокол описан в docs/custom-transfers.md) | — |
| `lfs.customtransfer.<name>.args` | Аргументы кастомного агента (раскрываются оболочкой) | — |
| `lfs.customtransfer.<name>.concurrent` | Запускать агент параллельно (по `lfs.concurrenttransfers`) | `true` |
| `lfs.customtransfer.<name>.direction` | Направление: `download`, `upload` или `both` | `both` |

**Таймауты и keepalive:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.dialtimeout` | Макс. ожидание установления соединения (не включает время запроса/ответа) | 30 с |
| `lfs.tlstimeout` | Макс. ожидание TLS handshake | 30 с |
| `lfs.activitytimeout` / `lfs.<url>.activitytimeout` | Макс. ожидание следующего read/write по TCP; `< 1` отключает таймаут | 30 с |
| `lfs.keepalive` | Время жизни keepalive-соединений | 30 мин |

**SSH:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.ssh.automultiplex` | Мультиплексировать запросы в одно SSH-соединение (требует OpenSSH-совместимый клиент) | `false` на Windows, иначе `true` |
| `lfs.ssh.retries` | Число попыток получить авторизацию по SSH | 5 |
| `lfs.sshtransfer` / `lfs.<url>.sshtransfer` | Использование чистого SSH-протокола: `negotiate` (сначала чистый, затем гибридный), `always` (только чистый), `never` (только гибридный) | `negotiate` |

**Обнаружение remote:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `remote.lfsdefault` | Remote для поиска LFS API; переопределяется `lfs.url` и `branch.*.remote` | единственный remote, иначе `origin` |
| `remote.lfspushdefault` | Remote для push; иначе `remote.pushdefault`, затем логика `remote.lfsdefault` | — |
| `lfs.remote.autodetect` | Выводить remote из информации о коммите, игнорируя `remote.lfsdefault`/`lfsurl` | `false` |
| `lfs.remote.searchall` | Fallback: искать LFS-данные во всех зарегистрированных remote | `false` |

**Fetch-recent окно:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.fetchrecentrefsdays` | Если не ноль — скачивать refs с коммитами за последние N дней (база для pruning) | 7 дней |
| `lfs.fetchrecentremoterefs` | Включать remote-refs в recent-окно (полезно для веток, которые планируется checkout-ить) | `true` |
| `lfs.fetchrecentcommitsdays` | Дополнительно скачивать изменения за N дней от последнего коммита на ref (база для pruning) | 0 |
| `lfs.fetchrecentalways` | Вести себя так, будто `git lfs fetch` всегда вызван с `--recent` | `false` |

**Prune:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.pruneoffsetdays` | Дней, добавляемых к `lfs.fetchrecent*` для определения удаляемых объектов | 3 |
| `lfs.pruneremotetocheck` | Remote, на который объекты должны быть запушены, чтобы их можно было удалить локально; также используется при `--verify-remote` | `origin` |
| `lfs.pruneverifyremotealways` | Всегда запускать `git lfs prune` как с `--verify-remote` | `false` |
| `lfs.pruneverifyunreachablealways` | Всегда запускать `git lfs prune` как с `--verify-unreachable` | `false` |

**Хранилище и прочее:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `lfs.storage` | Каталог хранилища LFS; неабсолютный путь — внутри Git-каталога репозитория. Внимание: не запускайте `git lfs prune` для репозиториев, разделяющих одно хранилище | `lfs` в Git-каталоге (обычно `.git/lfs`) |
| `lfs.pathFilterCacheSize` | Размер кэша results matching путей против фильтра `lfs.fetchinclude`/`lfs.fetchexclude` (или `--include`/`--exclude`); `0`/`none` — отключить, `unlimited` — без ограничений | 10 000 путей |
| `lfs.cachecredentials` | Кэширование SSH и Git Credential в памяти в рамках одной команды `git lfs` | включено |
| `lfs.extension.<name>.{clean,smudge,priority}` | Расширения Git LFS: команды обработки потоков при clean/smudge и приоритет (в `.lfsconfig` допустим только `priority`) | — |
| `lfs.<url>.contenttype` | Детектировать HTTP `Content-Type` при basic-upload; `false` — всегда `application/octet-stream` | `true` |
| `lfs.largefilewarning` | Предупреждать о файлах ≥ 4 ГиБ (искажаются на Windows при Git for Windows < 2.34.0) | `true` при Git < 2.34.0, иначе `false` |
| `lfs.lockignoredfiles` | Делать read-only также ignored-файлы, matching lockable-паттерну | `false` |
| `lfs.setlockablereadonly` | Делать файлы с атрибутом `lockable` read-only, когда они не залочены текущим пользователем (аналог — `GIT_LFS_SET_LOCKABLE_READONLY`) | `true` |
| `lfs.defaulttokenttl` | TTL токена по умолчанию, когда git-lfs-authenticate не вернул TTL в JSON | — |

---

## Практические сценарии

### Сценарий 1: Использование кастомного LFS-сервера

Применяется, когда LFS-объекты хранятся отдельно от основного Git-хостинга (например, в S3-совместимом хранилище). В `.lfsconfig` достаточно URL; настройка `access` обычно не нужна — LFS выставляет её сам при ответе 401:

```ini
# .lfsconfig
[lfs]
    url = https://lfs.internal.company.com/project-storage/info/lfs
```

Если сервер требует credentials до batch-запросов (иначе первый публичный запрос возвращает 401), задайте доступ per-URL — этот ключ тоже входит в whitelist:

```ini
# .lfsconfig
[lfs "https://lfs.internal.company.com/"]
    access = basic
```

**Валидация:**

```bash
git lfs env | grep -E "Endpoint|Access"
# → Endpoint=https://lfs.internal.company.com/project-storage/info/lfs (auth=basic)
# → AccessDownload=basic
```

### Сценарий 2: Оптимизация для сверхбольших репозиториев

Параметры производительности (`concurrenttransfers`, `transfer.batchSize`, `pathFilterCacheSize`) **не входят в whitelist** `.lfsconfig` и будут проигнорированы с предупреждением «unsafe '.lfsconfig' keys were ignored». Настройте их в Git-конфиге — локально (`.git/config`) или глобально (`~/.gitconfig`) для всех репозиториев:

```ini
# ~/.gitconfig (глобально) или .git/config (локально) — НЕ .lfsconfig
[lfs]
    # Увеличиваем параллелизм для высокоскоростных каналов
    concurrenttransfers = 32
    # Группируем запросы к API для уменьшения сетевых задержек
    [lfs "transfer"]
        batchSize = 500
    # Увеличиваем кэш фильтров для огромных деревьев файлов
    pathFilterCacheSize = 100000
```

**Валидация:**

```bash
# Проверить эффективные значения
git lfs env | grep -E "ConcurrentTransfers"
# → ConcurrentTransfers=32

# Убедиться, что в .lfsconfig нет заблокированных ключей (предупреждение отсутствует)
git lfs env 2>&1 >/dev/null
```

### Сценарий 3: Настройка кастомного агента передачи (Custom Transfer Agent)

Кастомные агенты выполняют внешние процессы, поэтому их настройка допустима только в Git-конфиге (в `.lfsconfig` ключи `lfs.customtransfer.*` игнорируются). Используется для интеграции со сторонними протоколами передачи (например, `rclone` или специализированные системы):

```ini
# .git/config или ~/.gitconfig — НЕ .lfsconfig
[lfs "customtransfer.myagent"]
    path = /usr/local/bin/lfs-transfer-helper
    args = --bucket-name my-lfs-bucket
    concurrent = true
    direction = both
```

**Валидация:**

```bash
git lfs env | grep UploadTransfers
# → UploadTransfers=basic,myagent
```

Агент должен быть установлен и доступен через `PATH` на всех машинах, включая CI/CD. Имя подсекции чувствительно к регистру: все ключи агента должны использовать одинаковое написание имени. Протокол взаимодействия git-lfs с агентом описан в [docs/custom-transfers.md](https://github.com/git-lfs/git-lfs/blob/main/docs/custom-transfers.md).

### Сценарий 4: Политики автоматической очистки (Pruning)

Параметры prune не входят в whitelist `.lfsconfig` — задаются в Git-конфиге:

```ini
# .git/config или ~/.gitconfig — НЕ .lfsconfig
[lfs]
    # Удалять файлы, не попадающие в окно recent + 7 дней
    pruneoffsetdays = 7
    # Обязательная проверка сервера перед локальным удалением
    pruneverifyremotealways = true
    # Remote, на котором проверяется наличие объектов
    pruneremotetocheck = origin
```

Окно удаления определяется суммой: `lfs.fetchrecentrefsdays` (7) + `lfs.fetchrecentcommitsdays` (0) + `lfs.pruneoffsetdays` (3 по умолчанию). Планируйте `git lfs prune` через cron/scheduled task.

### Сценарий 5: Выборочная загрузка (Selective Fetching)

`lfs.fetchinclude`/`lfs.fetchexclude` **входят в whitelist** и могут задаваться в `.lfsconfig` — позволяет экономить место на диске, не скачивая тяжелые ассеты, которые не нужны для текущей работы:

```ini
# .lfsconfig
[lfs]
    # По умолчанию игнорировать исходники видео и тяжелые датасеты
    fetchexclude = assets/raw_video/*,data/training_sets/**
```

*Разработчик может переопределить это локально через `git config lfs.fetchinclude "assets/raw_video/*"` — локальный Git-конфиг имеет приоритет над `.lfsconfig`.*

### Сценарий 6: Проверка блокировок перед push (`locksverify`)

Ключ `lfs.locksverify` (whitelisted) управляет поведением pre-push хука — он предотвращает push в файлы, залоченные другими пользователями:

- **`null` (по умолчанию)** — Git LFS пытается вызвать API блокировок; при валидном ответе выставляет `true` и блокирует push в файлы, залоченные другими; при `501 Not Implemented` — выставляет `false`.
- **`true`** — проверка обязательна: push останавливается при любых проблемах с сервером или при попытке обновить чужой lock.
- **`false`** — проверка полностью пропускается (для сред без File Locking или с серверной проверкой).

```ini
# .lfsconfig — проектная политика
[lfs]
    locksverify = true
```

Per-host/per-URL настройка — только в Git-конфиге:

```bash
git config --global lfs.https://github.com/.locksverify false
```

**Валидация:**

```bash
# Текущее значение для endpoint
git config lfs.locksverify
# → true
```

### Сценарий 7: Взаимодействие `.lfsconfig` и `.gitattributes`

`.lfsconfig` управляет **поведением LFS-клиента** (URL, политики), но **не определяет**, какие файлы обрабатываются через LFS. Для этого требуется `.gitattributes`:

```gitattributes
# .gitattributes
*.psd filter=lfs diff=lfs merge=lfs
*.mp4 filter=lfs diff=lfs merge=lfs
*.zip filter=lfs diff=lfs merge=lfs
```

**Порядок работы:**
1. `.gitattributes` указывает, что файлы `*.psd` должны обрабатываться через фильтр `lfs`.
2. `.lfsconfig` указывает, где хранятся LFS-объекты и как их передавать.
3. При `git add` clean-фильтр LFS использует настройки из конфигурации для загрузки файла.
4. При `git checkout` smudge-фильтр использует настройки из конфигурации для скачивания файла.

**Валидация:**

```bash
# Проверить, что файл отслеживается LFS
git check-attr filter path/to/file.psd
# → path/to/file.psd: filter: lfs

# Проверить, что .lfsconfig активен
git config lfs.url
# → https://lfs.internal.company.com/project-storage/info/lfs
```

### Сценарий 8: Оптимизация CI/CD с `.lfsconfig`

В пайплайнах часто не нужны тяжелые файлы. `.lfsconfig` может автоматически исключать их (whitelisted), а переменная окружения `GIT_LFS_SKIP_SMUDGE` ускоряет клонирование:

```ini
# .lfsconfig
[lfs]
    # В CI не скачивать видео и датасеты по умолчанию
    fetchexclude = "assets/videos/*,data/datasets/**"
```

```bash
# В CI/CD пайплайне
export GIT_LFS_SKIP_SMUDGE=1
git clone https://github.com/user/repo.git
cd repo

# Затем выборочно скачать только нужные файлы
git lfs pull --include="assets/textures/**"
```

Если часть LFS-файлов недоступна, но checkout должен завершиться — используйте `lfs.skipdownloaderrors` (whitelisted) или `GIT_LFS_SKIP_DOWNLOAD_ERRORS=1`: недоступные файлы останутся pointer-ами, а команда завершится успешно.

**Валидация:**

```bash
# Убедиться, что файлы-указатели не заменены на реальные
ls -la assets/textures/image.psd
# → -rw-r--r--  130 bytes (pointer file)

# Скачать только текстуры
git lfs pull --include="assets/textures/**"
ls -la assets/textures/image.psd
# → -rw-r--r--  50 MB (real file)
```

**Best practices для CI/CD:**
- Используйте `GIT_LFS_SKIP_SMUDGE=1` для ускорения клонирования, если LFS-файлы не нужны.
- Кэшируйте директорию `.git/lfs/objects` между запусками пайплайна для ускорения.
- Для монорепозиториев настройте `lfs.fetchinclude` и `lfs.fetchexclude` в `.lfsconfig`.

### Сценарий 9: SSH и HTTPS endpoints

LFS-сервер может быть доступен по разным протоколам. `.lfsconfig` позволяет явно указать URL, а `.git/config` — переопределить его для конкретного пользователя:

```ini
# .lfsconfig (версионируется)
[lfs]
    url = https://lfs.example.com/project/info/lfs
```

```bash
# Локальное переопределение для разработчика, у которого есть SSH-туннель
git config lfs.url ssh://git@lfs.example.com/project
```

Для управления протоколом передачи по SSH (только в Git-конфиге): `lfs.sshtransfer = negotiate|always|never`.

**Валидация:**

```bash
# Проверить эффективный URL
git lfs env | grep Endpoint
# → Endpoint=https://lfs.example.com/project/info/lfs (auth=basic)

# Проверить, что локальный override применяется
git config lfs.url
# → ssh://git@lfs.example.com/project
```

### Сценарий 10: Переменные окружения, влияющие на LFS

Поведение Git LFS можно изменять без редактирования конфигов через переменные окружения (все перечисленные проверены в `git-lfs-config(5)`):

```bash
# Пропустить автоматическую замену указателей на реальные файлы
# (действует на git lfs smudge и git lfs filter-process)
export GIT_LFS_SKIP_SMUDGE=1

# Пропустить выгрузку новых объектов в pre-push хуке
export GIT_LFS_SKIP_PUSH=1

# Не прерывать smudge при ошибках скачивания (аналог lfs.skipdownloaderrors)
export GIT_LFS_SKIP_DOWNLOAD_ERRORS=1

# Писать прогресс в файл (формат строки:
# <direction> <current>/<total files> <downloaded>/<total> <name>)
export GIT_LFS_PROGRESS=/tmp/lfs-progress.log

# Принудительно показывать прогресс, даже если stdout — не терминал
export GIT_LFS_FORCE_PROGRESS=1

# Не делать lockable-файлы read-only (по умолчанию true)
export GIT_LFS_SET_LOCKABLE_READONLY=0

# Программа для получения пароля при авторизации против LFS API
export GIT_ASKPASS=/usr/local/bin/askpass-script
```

**Валидация:**

```bash
# Проверить, что переменная окружения действует
GIT_LFS_SKIP_SMUDGE=1 git lfs clone https://github.com/user/repo.git
# → Клонирование выполняется, файлы остаются указателями
```

### Сценарий 11: Проверка активности `.lfsconfig`

После добавления `.lfsconfig` в репозиторий важно убедиться, что он используется всеми участниками:

```bash
# 1. Проверить, что файл отслеживается Git
git ls-files .lfsconfig
# → .lfsconfig

# 2. Полный отчёт LFS-среды (endpoint, доступ, передачи, окна fetch/prune)
git lfs env
# → LocalWorkingDir=/path/to/repo
# → LocalGitDir=/path/to/repo/.git
# → LocalMediaDir=/path/to/repo/.git/lfs/objects
# → ConcurrentTransfers=8
# → FetchRecentRefsDays=7
# → PruneOffsetDays=3
# → LfsStorageDir=/path/to/repo/.git/lfs
# → Endpoint=https://lfs.example.com/project/info/lfs (auth=basic)
# → AccessDownload=basic
# → AccessUpload=basic
# → DownloadTransfers=basic
# → UploadTransfers=basic
# → git config "filter.lfs.process" = "git-lfs filter-process"

# 3. Проверить конкретные параметры и источник
git config --show-origin lfs.url
# → file:.lfsconfig    lfs.url=https://lfs.example.com/project/info/lfs

# 4. Проверить, что в .lfsconfig нет неразрешённых ключей
#    (предупреждение «unsafe '.lfsconfig' keys were ignored» отсутствует)
git lfs env 2>&1 >/dev/null

# 5. Что попадёт под текущие фильтры fetch (без реального скачивания)
git lfs fetch --dry-run
```

Если `git config lfs.url` возвращает значение, отличное из `.lfsconfig`, проверьте:
- Файл `.lfsconfig` закоммичен и доступен в текущей ветке (иначе читается копия из индекса или `HEAD`).
- Нет локального override в `.git/config` — он имеет приоритет над `.lfsconfig`.
- Файл имеет корректный синтаксис INI.
- Ключ входит в whitelist LFSCONFIG — иначе он молча игнорируется.

---

## Дополнительная информация

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `warning: These unsafe '.lfsconfig' keys were ignored` | Параметр вне whitelist LFSCONFIG (например, `concurrenttransfers`, `pruneoffsetdays`, `customtransfer.*`) | Перенести параметр в `.git/config` или `~/.gitconfig` |
| `batch response: Authentication required` | `.lfsconfig` указывает неверный URL или отсутствует токен доступа | Проверить `lfs.url` и `lfs.<url>.access`, настроить credential helper |
| `LFS endpoint not configured` | `.lfsconfig` отсутствует или имеет синтаксическую ошибку | Проверить синтаксис INI, убедиться что секция `[lfs]` присутствует |
| `Smudge error: Error downloading file` | LFS-сервер недоступен или URL в конфигурации неверен | Выполнить `git lfs env`, проверить сетевую доступность URL |
| `Lock verification failed` | `lfs.locksverify=true`, но блокировка отсутствует или принадлежит другому пользователю | Запросить разблокировку у владельца или использовать `git lfs unlock --force` |
| `Pointer file instead of real file` | Файл добавлен в индекс до настройки tracking в `.gitattributes` | Выполнить миграцию: `git lfs migrate import --include="*.psd" --everything` |
| `Local config overrides ignored` | Разработчик ожидает, что `.lfsconfig` переопределит локальный `.git/config` | Помнить, что локальный конфиг имеет высший приоритет; использовать `git config --unset lfs.url` для сброса |
| `Pruning removes needed objects` | `lfs.pruneoffsetdays` слишком мал или ветка с нужными объектами не fetched | Увеличить `pruneoffsetdays`, включить `pruneverifyremotealways` |
| Кастомный агент не вызывается | Настройки `lfs.customtransfer.*` помещены в `.lfsconfig`, где игнорируются | Перенести в `.git/config`/`~/.gitconfig`; следить за регистром имени подсекции |

### Ограничения и крайние случаи

1. **Отсутствие `.gitattributes`:** `.lfsconfig` не заменит `.gitattributes`. Если в репозитории нет правил `filter=lfs`, файлы будут храниться в обычном Git, даже если `.lfsconfig` полностью настроен.

2. **Bare-репозитории:** В bare-репозиториях нет рабочей директории. Smudge-фильтры (включая LFS) не запускаются автоматически при доступе через `git archive` или веб-интерфейс; `.lfsconfig` читается только из `HEAD`. С Git 2.46 bare-репозиторий по умолчанию не читает `.gitattributes` из HEAD — для корректной обработки объектов задайте источник атрибутов явно (`git config attr.tree main`, `git --attr-source=main` или `GIT_ATTR_SOURCE`).

3. **`.lfsconfig` — не политика, а умолчание:** Настройки из `.git/config` (локального), `~/.gitconfig` и `/etc/gitconfig` имеют приоритет над `.lfsconfig`. Это может привести к ситуации, когда `.lfsconfig` кажется игнорируемым, хотя на деле работает локальный override.

4. **Версионирование секретов:** Если в `.lfsconfig` указаны учетные данные в URL (например, `https://user:pass@lfs.example.com`), они попадут в историю Git. Используйте credential helpers или переменные окружения.

5. **Кастомные Transfer Agents:** Агент, указанный в `[lfs "customtransfer.*"]`, должен быть установлен и доступен через `PATH` на всех машинах, включая CI/CD. Если агент отсутствует, все операции LFS завершатся ошибкой. Настройка агентов допустима только в Git-конфиге, не в `.lfsconfig`.

6. **Размер репозитория:** `.lfsconfig` не влияет на размер `.git` для файлов, уже добавленных до настройки LFS tracking. Требуется миграция через `git lfs migrate import`.

7. **Расшаренное хранилище:** При использовании `lfs.storage` несколькими репозиториями не запускайте `git lfs prune` — удаление в одном репозитории сломает объекты в другом.

8. **Расширения:** свойства `clean` и `smudge` расширений (`lfs.extension.<name>.*`) игнорируются в `.lfsconfig`; в нём допустим только `priority`.

### Best practices

1. **Явное указание `lfs.url`:** Всегда указывайте `lfs.url` в `.lfsconfig` для предотвращения атак через подмену URL при клонировании.
2. **Синхронизация с `.gitattributes`:** Убедитесь, что `.lfsconfig` и `.gitattributes` коммитятся вместе. Изменение одного без другого приводит к неработающему LFS.
3. **Только whitelist в `.lfsconfig`:** Перед коммитом проверяйте отсутствие предупреждения «unsafe keys»: `git lfs env 2>&1 >/dev/null`. Производительность, prune и таймауты настраивайте в Git-конфиге.
4. **Параллелизм:** Настройте `lfs.concurrenttransfers` в зависимости от пропускной способности канала (рекомендуется 8–32) — в `~/.gitconfig`.
5. **Выборочная загрузка:** Используйте `lfs.fetchinclude` и `lfs.fetchexclude` в `.lfsconfig` для экономии места в монорепозиториях.
6. **Безопасность:** Включите `lfs.locksverify = true` для командной работы с бинарными файлами.
7. **Очистка:** Настройте `lfs.pruneoffsetdays = 7` и `lfs.pruneverifyremotealways = true` в Git-конфиге, планируйте `git lfs prune` через cron.
8. **CI/CD:** Используйте `GIT_LFS_SKIP_SMUDGE=1` и кэшируйте `.git/lfs/objects` между запусками.
9. **Миграция:** Проводите миграцию больших файлов в LFS до того, как репозиторий станет слишком большим.
10. **Запись значений:** используйте `git config -f .lfsconfig <key> <value>` вместо ручного редактирования — это гарантирует корректный INI-синтаксис.

### Безопасность

- **Почему whitelist:** `.lfsconfig` читается при каждой операции в репозитории, включая клоны из недоверенных источников. Ключи вроде `lfs.customtransfer.<name>.path` задают внешние процессы — вредоносный репозиторий мог бы заставить клиент выполнить произвольную программу при fetch. Поэтому в `.lfsconfig` работает только фиксированный набор безопасных ключей, а всё, что исполняет код или меняет локальное поведение, требует явного действия пользователя в Git-конфиге.
- **Подмена URL (URL hijacking):** Если в репозитории отсутствует `.lfsconfig` или `lfs.url`, злоумышленник может внедрить вредоносный LFS-сервер через `.gitattributes` с `filter=lfs` и перехватывать данные при клонировании. Всегда явно указывайте `lfs.url` в `.lfsconfig`.
- **Локальные overrides:** Разработчики могут переопределить `lfs.url` в `.git/config`. В корпоративной среде используйте pre-receive hooks для проверки, что `.lfsconfig` не изменен.
- **Учетные данные в URL:** Никогда не храните пароли или токены в `.lfsconfig`. Используйте Git credential helpers или SSH-ключи.

### Отладка конфигурации

Чтобы увидеть, какие именно значения и из каких источников используется LFS:

```bash
# Вывод всех переменных окружения и путей LFS (endpoint, access,
#ConcurrentTransfers, окна fetch/prune, transfer-адаптеры)
git lfs env

# Проверка источника конкретного параметра
git config --show-origin lfs.url
# → file:.lfsconfig    lfs.url=https://lfs.example.com/project/info/lfs

# Проверка того, какие файлы попадают под текущие фильтры fetch
git lfs fetch --dry-run

# Дамп содержимого .lfsconfig как git-config
git config -f .lfsconfig -l

# Проверка конфигурации в конкретном коммите
git show HEAD:.lfsconfig

# Поиск проблем в работе LFS (логи последней операции)
git lfs logs
```

### Официальные ресурсы

- **Сайт проекта:** [git-lfs.com](https://git-lfs.com/)
- **GitHub Repository:** [github.com/git-lfs/git-lfs](https://github.com/git-lfs/git-lfs)
- **Справочная страница `git-lfs-config(5)`:** [docs/man/git-lfs-config.adoc](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-config.adoc) — полный список опций и раздел LFSCONFIG
- **Протокол кастомных передач:** [docs/custom-transfers.md](https://github.com/git-lfs/git-lfs/blob/main/docs/custom-transfers.md)
- **Wiki по конфигурации:** [github.com/git-lfs/git-lfs/wiki/Configuration](https://github.com/git-lfs/git-lfs/wiki/Configuration)
- **Документация Git:** [git-scm.com/docs/gitattributes](https://git-scm.com/docs/gitattributes)
- **GitHub Linguist:** [github.com/github-linguist/linguist](https://github.com/github-linguist/linguist)

### Связанные документы

- [Обзор Git LFS](./git_lfs.md) — базовые команды и принципы работы.
- [Атрибуты Git (.gitattributes)](./git_attributes.md) — настройка отслеживания (tracking) и фильтров.
- [Конфигурация Git](./git_configuration.md) — общие настройки Git, включая `git-crypt` и `includeIf`.
- [Специальные файлы Git](./git_special_files_overview.md) — место `.lfsconfig` в иерархии репозитория.
