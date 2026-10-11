# Git: Оптимизация производительности

**Актуально для:** Git 2.54–2.56 (локально проверено на 2.54.0); отдельные механизмы описаны начиная с версии их введения (2.24–2.47). Содержание остаётся корректным для 2.54–2.56 — изменений в описанных механизмах не было.

## Определения

**Оптимизация производительности Git** — комплекс конфигурационных настроек, инструментов и стратегий, направленных на минимизацию времени выполнения операций (`clone`, `fetch`, `status`, `log`) в репозиториях сверхбольшого объема (монорепозитории) или при работе в условиях ограниченной пропускной способности сети.

**Scalar** — инструмент Microsoft для больших репозиториев: применяет набор выверенных настроек и ведёт фоновое обслуживание. С Git 2.38 входит в состав Git for Windows; в других дистрибутивах устанавливается отдельно (в данной системе `git scalar` недоступен). Документация входит в комплект документации Git (git-scm.com/docs/scalar).

**Multi-pack-index (MIDX)** — сводный индекс `.git/objects/pack/multi-pack-index`, объединяющий информацию о расположении объектов во всех pack-файлах. Устраняет необходимость поиска объекта в сотнях отдельных `.idx` файлов.

**Bundle URIs** — механизм ускорения клонирования: Git скачивает предварительно подготовленные пакеты данных (bundles) с быстрых CDN до основного взаимодействия с Git-сервером. Refs бандла помещаются в скрытое пространство имён `refs/bundle/*`.

**FSMonitor (File System Monitor)** — встроенный демон (`git-fsmonitor--daemon`) или интеграция с Watchman, отслеживающая изменения файлов. Позволяет `git status` избегать полного сканирования рабочего дерева.

**Sparse-Checkout (Разреженное извлечение)** — механизм, позволяющий «материализовать» на диске только подмножество файлов репозитория, необходимых для конкретной задачи, при сохранении доступа ко всей истории.

**Sparse Index** — (Git 2.25+, экспериментально) разреженный индекс: его размер уменьшается до подмножества рабочего дерева, определённого sparse-checkout. Ускоряет `git status` и `git add`; управляется опцией `--[no-]sparse-index` команд `init`/`set`. Внутренний ключ конфигурации — `extensions.sparseIndex` (а не `index.sparse`); конфигурационного ключа `core.sparseIndex` не существует.

**Pack-файл (`.pack`)** — сжатый архив объектов Git, создаваемый `git gc` или `git repack`. Использует дельта-компрессию: хранит базовый объект и только различия с последующими объектами, что радикально уменьшает размер хранилища.

**Loose-объект** — отдельный сжатый файл объекта в `.git/objects/`, создаваемый при каждом `git commit` до момента упаковки. При превышении порога `gc.auto` (по умолчанию ~6700 loose-объектов) Git автоматически запускает `git gc --auto` для их объединения в pack-файлы.

**Bitmap (Reachability Bitmap)** — файлы `.bitmap` в `.git/objects/pack/`, содержащие предвычисленные множества достижимых объектов для конкретных веток. Позволяют `git fetch`/`push` быстро вычислять, какие объекты нужно передавать, без полного обхода графа. Оптимизированы для серверной стороны; Scalar отключает их на клиенте (`pack.useBitmaps=false`).

**Background Maintenance (Фоновое обслуживание)** — механизм (Git 2.30+), запускающий фоновый процесс, который периодически выполняет задачи обслуживания (`git maintenance`): обновляет `commit-graph`, `multi-pack-index`, упаковывает объекты без вмешательства пользователя.

**Promisor Remote** — часть механизма Partial Clone. Удаленный репозиторий, на который ссылаются promisor-объекты (blob или tree), отсутствующие локально. При обращении к отсутствующему объекту Git автоматически загружает его с promisor remote.

**feature.manyFiles** — (Git 2.24+) одним ключом включает набор оптимизаций для репозиториев с большим числом файлов: `index.version=4` и `core.untrackedCache=true`; с Git 2.40 добавлен `index.skipHash=true` (ускоряет запись индекса).

---

## Основные концепции

### Почему падает производительность

С ростом репозитория производительность падает по нескольким независимым осям:

1.  **Сетевой трафик:** При `clone` или `fetch` передается весь объем истории. Для монорепозиториев размером 50 ГБ это может занимать десятки минут даже на оптоволоконных каналах.
2.  **Объем индекса:** Бинарный файл `.git/index` становится слишком тяжелым для чтения/записи. При 500k+ файлах операция `git add` или `git status` может занимать секунды только на обновление индекса.
3.  **Дисковый I/O:** `git status` вынужден вызывать `lstat()` для каждого из 100k+ файлов, чтобы проверить изменения. На медленных дисках (HDD, сетевые шары) это становится узким местом.
4.  **Глубина истории:** Чем больше коммитов, тем дольше `git log` и операции слияния (`merge`, `rebase`) вычисляют достижимость и историю.
5.  **Количество ссылок:** При тысячах веток и тегов операции со ссылками (`git branch -a`, `git show-ref`) замедляются из-за линейного обхода файлов в `refs/` или `packed-refs`.

### Архитектура хранения объектов

Понимание внутреннего устройства помогает выбирать правильные методы оптимизации:

```
.git/objects/
├── 00/                           # Поддиректории по первым 2 символам хэша
│   ├── 0123456789abcdef...       # Loose-объект (zlib-сжатый blob/tree/commit/tag)
│   └── ...
├── pack/
│   ├── pack-abc123.pack          # Упакованные объекты (дельта-сжатие)
│   ├── pack-abc123.idx           # Индекс для быстрого поиска в .pack
│   ├── pack-abc123.bitmap        # Битмапы для быстрой достижимости
│   ├── pack-abc123.rev           # Reverse index (RIDX): позиция объекта по смещению
│   └── multi-pack-index          # Сводный индекс для всех .pack файлов
└── info/
    └── commit-graph               # Граф коммитов для быстрого обхода истории
```

- **Loose objects:** Каждый объект хранится отдельным файлом. Удобно для частых записей, но неэффективно при чтении (множество файловых операций).
- **Pack files:** Объекты упаковываются вместе. Дельта-компрессия находит похожие blob и сохраняет только разницу. Экономит место и ускоряет чтение (меньше файлов).
- **MIDX:** Объединяет индексы всех pack-файлов в одну структуру. Критично при наличии сотни pack-файлов (актуально для старых репозиториев без регулярного `gc`).

### Сводная таблица методов оптимизации

| Метод | Что ускоряет | Целевая область |
| :--- | :--- | :--- |
| **Scalar** | Комплексная скорость | Монорепозитории (>100k файлов). |
| **feature.manyFiles** | `status`, `add`, `checkout` | Репозитории с 10k+ файлов. |
| **MIDX & Bitmaps** | `fetch`, `push`, `gc` | Оптимизация поиска объектов. |
| **Commit-Graph** | `log`, `graph`, `merge` | Ускорение обхода истории. |
| **Sparse-Checkout (Cone Mode)** | `status`, `checkout`, `add` | Уменьшение рабочего дерева. |
| **Partial Clone** | `clone` (трафик) | Исключение ненужных blob-объектов. |
| **Bundle URIs** | `clone` (время) | Использование CDN для «разогрева» репозитория. |
| **FSMonitor** | `status` | Устранение сканирования диска. |
| **Reftable** | Работа со ссылками | Репозитории с десятками тысяч веток. |
| **Pack-настройки** | `gc`, `repack` | Серверы с ограниченной памятью. |

---

## Практические сценарии

### Сценарий 1: Использование Scalar для монорепозиториев

Scalar применяет выверенный набор настроек одной командой.

```bash
# Клонирование с автоматической настройкой оптимизаций:
# partial clone (только commit и tree объекты), sparse-checkout
# (только верхний уровень), worktree в <enlistment>/src,
# фоновое обслуживание включено по умолчанию
scalar clone <url>

# Регистрация существующего репозитория (включает фоновое обслуживание)
cd my-big-repo
scalar register

# После обновления Scalar — обновить рекомендованные настройки
scalar reconfigure --all

# Сбор диагностики для отчётов об ошибках
scalar diagnose
```

**Что именно настраивает Scalar** (список рекомендуемых значений приведён по состоянию на Scalar 2.53 / Git 2.54–2.56; `git-scm.com/docs/scalar`):

- `am.keepCR=true` — сохранение `\r` при переносе между Windows и non-Windows платформами.
- `core.autoCRLF=false`, `core.safeCRLF=false` — отключить преобразование CRLF для производительности; репозитории, использующие CRLF, должны коммитить файлы с соответствующими концовками.
- `core.logAllRefUpdates=true` — включить reflog на всех ветках (цена — производительность, но важно для восстановления).
- `credential.https://dev.azure.com.useHttpPath=true` — включить `credential.useHttpPath` только для Azure DevOps.
- `feature.experimental=false` — отключить экспериментальные оптимизации; все значимые настройки заданы явно. Среди намеренных отличий — битмапы, отключаемые на клиенте.
- `feature.manyFiles=false` — Scalar не использует `feature.manyFiles`, задавая все нужные ключи явно.
- `gui.GCWarning=false` — отключить предупреждение `git-gui` о `gc.auto=0`.
- `index.version=4`, `index.skipHash=true`, `index.threads=true` — сжатие путей, отключение хэша индекса и параллельное чтение. `index.threads=true` по умолчанию также включает расширение индекса `IEOT` (Index Entry Offset Table) для параллельного парсинга; ключ `index.recordOffsetTable` существует отдельно (по умолчанию true при `index.threads=true`, false при `index.threads=false`).
- `merge.renames=true` — при слияниях в больших репозиториях важно обнаруживать rename для валидности результата.
- `core.untrackedCache=true` — на всех платформах, кроме Windows (там `false` из-за багов на Windows-файловых системах).
- `commitGraph.changedPaths=true` — Bloom-фильтры в commit-graph для ускорения истории файлов. Scalar не задаёт `commitGraph.generationVersion` (предпочитаемый вариант 2); при ручной настройке generationVersion=2 требует перегенерации графа.
- `fetch.unpackLimit=1`, `fetch.writeCommitGraph=false`, `gc.auto=0`, `receive.autoGC=false` — сборку мусора и графы переносят на фоновое обслуживание (стратегия `incremental`: commit-graph и prefetch — hourly, loose-objects и incremental-repack — daily, gc отключён).
- `status.aheadBehind=false`, `merge.stat=false`, `fetch.showForcedUpdates=false` — отключение дорогих вычислений в монорепозиториях.
- `pack.useBitmaps=false`, `pack.usePathWalk=true` — битмапы отключаются на клиенте (они для серверов), включается обход путей при упаковке.
- `log.excludeDecoration=refs/prefetch/*` — прятать refs фонового prefetch из `git log`.

### Сценарий 2: Разреженное извлечение (Sparse-Checkout) в режиме Cone

Режим **Cone** значительно быстрее классического, так как использует хэш-таблицы для сопоставления путей вместо регулярных выражений.

```bash
# Инициализация в режиме Cone
git sparse-checkout init --cone

# Выбор необходимых директорий
git sparse-checkout set src/backend docs/

# Разреженный индекс (Git 2.25+, экспериментально): размер индекса
# уменьшается до подмножества рабочего дерева
git sparse-checkout init --cone --sparse-index
```

**Важно:** конфигурационного ключа `core.sparseIndex` не существует — разреженный индекс включается опцией `--[no-]sparse-index` команд `init`/`set`. Не работает в non-cone режиме; внешние инструменты могут не понимать разреженные записи индекса (отключение: `git sparse-checkout init --no-sparse-index`).

### Сценарий 3: Ускорение клонирования через Bundle URIs

Позволяет скачивать основные данные с CDN, снижая нагрузку на основной Git-сервер.

```bash
# Клонирование с использованием внешнего бандла
git clone --bundle-uri=https://cdn.example.com/main.bundle https://github.com/user/repo.git

# Включение автоматического использования бандлов, если сервер их рекламирует
# (default: false)
git config --global transfer.bundleURI true
```

**Ограничения:** `--bundle-uri` несовместим с `--depth`, `--shallow-since` и `--shallow-exclude`. Refs из бандла доступны в скрытом namespace `refs/bundle/*`.

### Сценарий 4: Тонкая настройка Staging Area и статуса

Если Scalar не используется, настройки можно применить точечно:

```bash
# Одним ключом — набор оптимизаций для репозиториев с большим числом файлов
# (Git 2.24+; с Git 2.40 добавляется index.skipHash=true)
git config --global feature.manyFiles true
# Эквивалент вручную: index.version=4 + core.untrackedCache=true
# Внимание: индекс со skipHash не читают Git < 2.13, а Git < 2.40
# сообщит о повреждении индекса при git fsck

# Встроенный монитор файловой системы (git-fsmonitor--daemon)
git config core.fsmonitor true

# Кэш неотслеживаемых файлов (default: keep). Перед включением
# проверьте, что mtime работает корректно (актуально для NFS)
git config core.untrackedCache true

# Параллельная предзагрузка индекса (включена по умолчанию;
# заметно ускоряет git diff/git status на NFS)
git config core.preloadIndex true
```

### Сценарий 5: «Ленивая» загрузка (Partial Clone) в CI/CD

Для минимизации времени сборки и трафика используйте фильтры объектов.

```bash
# Blobless клон: скачивает коммиты и деревья, но не blob-ы.
# Содержимое файлов догружается по требованию (checkout).
git clone --filter=blob:none <url>

# Treeless клон: не скачивает деревья вообще — только коммиты.
# Максимально быстрый клон для проверки истории и метаданных.
git clone --filter=tree:0 <url>
```

**Как это работает:** promisor remote помечается в `extensions.partialClone`; промисорные pack-файлы имеют соседний файл `<name>.promisor`. Динамическая догрузка отсутствующих объектов идёт по одному (медленно), но `checkout` догружает все нужные blob-ы одной партией. Partial clone независим от shallow clone: первый ограничивает объекты, второй — историю коммитов.

```bash
# Смена фильтра без догрузки объектов
git fetch --refetch

# Массовая предзагрузка объектов для диапазона (быстрее поштучной догрузки)
git rev-list --objects --quiet --missing=print A..B
```

### Сценарий 6: Фоновое обслуживание (git maintenance)

Фоновое обслуживание автоматически обновляет критически важные индексы и упаковывает объекты (Git 2.30+).

```bash
# Включение фонового обслуживания (регистрация + планировщик)
git maintenance start

# Проверка, нужно ли обслуживание (exit 0 — нужно)
git maintenance is-needed

# Ручной запуск конкретной задачи
git maintenance run --task=gc
git maintenance run --task=commit-graph
git maintenance run --task=incremental-repack

# Регистрация без планировщика / снятие с учёта
git maintenance register
git maintenance unregister

# Отключение фонового обслуживания
git maintenance stop
```

**Задачи** (`--task=<task>` или `maintenance.<task>.enabled`): `commit-graph`, `prefetch`, `gc`, `loose-objects`, `incremental-repack`, `pack-refs`, `reflog-expire`, `rerere-gc`, `worktree-prune`. По умолчанию включена только `maintenance.gc.enabled`.

**Стратегии** (`maintenance.strategy`): `none` (default для scheduled), `gc`, `geometric` (геометрический repack), `incremental`. Команда `git maintenance register` устанавливает `incremental`: commit-graph и prefetch — hourly, loose-objects и incremental-repack — daily, gc — disabled.

**Планировщики** (`git maintenance start --scheduler=<scheduler>`): `auto` (default; Linux — systemd-timer при наличии, иначе crontab), `crontab`, `systemd-timer`, `launchctl` (macOS), `schtasks` (Windows). Частота задаётся ключом `maintenance.<task>.schedule` = `hourly`/`daily`/`weekly`.

**Проверка, что обслуживание активно:**
```bash
# POSIX (cron): записи Git в crontab
crontab -l | grep "GIT MAINTENANCE SCHEDULE"
# → 0 1-23 * * * ".../git" --exec-path="..." for-each-repo --config=maintenance.repo maintenance run --schedule=hourly

# Linux (systemd): пользовательские таймеры
systemctl --user list-timers | grep git-maintenance
# → git-maintenance@hourly.timer  git-maintenance@hourly.service

# macOS (launchctl)
ls ~/Library/LaunchAgents/org.git-scm.git*
# → org.git-scm.git.daily.plist  org.git-scm.git.hourly.plist  org.git-scm.git.weekly.plist

# Список зарегистрированных репозиториев
git config --get-all maintenance.repo
```

**Важно для автоматизации:** `git gc` не следует сочетать с `git maintenance run` — у них разная семантика блокировки object database. Вместо `git gc` используйте `git maintenance run --task=gc`. Параллельные `git maintenance run` на одном репозитории столкнутся на блокировке ODB — один из процессов не выполнит задачи.

### Сценарий 7: Анализ репозитория (git-sizer)

Утилита `git-sizer` выявляет проблемные места репозитория (слишком большие деревья, глубокая история, огромные файлы).

```bash
# Установка (Go-based инструмент)
# macOS: brew install git-sizer   (формула 1.5.0)
# Или скачать бинарник с github.com/github/git-sizer

# Анализ текущего репозитория
git-sizer --verbose
# → Git repository size statistics:
# →   Blobs:
# →     Total size (human): 1.2 GB
# →     Largest size (human): 45.2 MB
# →   Trees:
# →     Total entries: 1,250,000
# →   Commits:
# →     Maximum depth: 85,000
# →   References:
# →     Total count: 3,500
```

**Действия по результатам:**
- Если `Trees: Total entries` > 1M — рассмотреть Sparse-Checkout.
- Если `Commits: Maximum depth` > 50k — использовать Shallow Clone в CI.
- Если `Blobs: Largest size` > 10MB — перенести файлы в Git LFS.

### Сценарий 8: Параллельная загрузка и тонкая настройка сети

Git поддерживает параллельные соединения для fetch/push и подмодулей.

```bash
# Параллельные fetch-операции (подмодули или remote-ы при --multiple)
# default: 1; значение 0 = разумный default
git config --global fetch.parallel 8

# Параллельное клонирование подмодулей
git config --global submodule.fetchJobs 8

# Лимит одновременных HTTP-запросов (default: 5;
# переопределяется переменной GIT_HTTP_MAX_REQUESTS)
git config --global http.maxRequests 64

# Принудительная версия HTTP (default зависит от libcurl;
# доступные значения: HTTP/2, HTTP/1.1)
git config --global http.version HTTP/2
```

**Валидация:**
```bash
# Включить трассировку HTTP для проверки параллельных запросов
GIT_TRACE_CURL=1 git fetch origin
# → * About to connect() to github.com port 443 (#0)
# → *   Trying 140.82.121.4...
# → * Connected to github.com (140.82.121.4) port 443 (#0)
```

### Сценарий 9: Диагностика производительности (GIT_TRACE2)

Современный фреймворк трассировки позволяет точно замерить время каждой фазы Git-команды.

```bash
# Perf-формат: столбчатая статистика времени выполнения
GIT_TRACE2_PERF=1 git status
# → D0129 16:04:10.123456 git status ................... main
# → | main|total_ms=1245|flat_ms=1200|squelch_ms=0|...
# → |  main|read_cache=800|preload_index=200|scan_working_dir=150|...

# Event-формат: JSON для автоматизированного анализа
GIT_TRACE2_EVENT=1 git fetch origin > trace.json 2>&1

# Включение трассировки в глобальном конфиге
git config --global trace2.perfTarget ~/git-perf.log
```

**Ключевые метрики:**
- `total_ms` — общее время команды
- `read_cache` — время чтения индекса
- `scan_working_dir` — время сканирования рабочего дерева
- `preload_index` — время предзагрузки данных

### Сценарий 10: Миграция на Reftable для десятков тысяч веток

Бинарный бэкенд `reftable` (интегрирован в Git 2.45, с 2.47 не является экспериментальным; станет форматом по умолчания для новых репозиториев в Git 3.0) заменяет файловую систему `refs/` и `packed-refs` на единый бинарный формат.

```bash
# Для НОВЫХ репозиториев:
# канонический ключ конфигурации — init.defaultRefStorageFormat;
#  init.defaultRefFormat — действующий ключ (с Git 2.47, не deprecated);
#  есть env GIT_DEFAULT_REF_STORAGE_FORMAT
git init --ref-format=reftable

# Для СУЩЕСТВУЮЩИХ репозиториев (миграция):
# (--ref-format — устаревший синоним; --dry-run — проверка без изменений;
#  --no-reflog — отменить перенос reflog, по умолчанию reflog мигрируется)
git refs migrate --ref-storage-format=reftable

# Проверка текущего формата
git config extensions.refStorage
# → reftable (или пусто/files для классического формата)
```

**Ограничения:**
- Миграция делает репозиторий несовместимым с Git < 2.45.
- `git refs migrate` не может мигрировать репозитории с worktree — сначала удалите worktree (`git worktree remove`).
- Во время миграции нет блокировки записей — параллельные записи могут привести к неконсистентному состоянию. Если репозиторий зарегистрирован в фоновом обслуживании, сначала `git maintenance unregister`.
- После миграции `git fsck` и низкоуровневые инструменты должны поддерживать reftable.

### Сценарий 11: Настройка упаковки (pack) и gc на серверах

Для серверов и CI-runner'ов с ограниченной памятью настройки упаковки предотвращают OOM при `gc`/`repack` больших репозиториев:

```bash
# Число потоков поиска дельт при упаковке (требует pthreads)
git config --global pack.threads 4

# Лимит памяти на поток при поиске дельт (k/m/g; без настройки — без ограничения)
git config --global pack.windowMemory 256m

# Кэш дельт перед записью pack (важен при repack больших репозиториев)
git config --global pack.deltaCacheSize 256m

# Максимальный размер pack-файла (только repack; превышение лимита
# порождает несколько pack-файлов; переопределяется --max-pack-size)
git config --global pack.packSizeLimit 2g

# Уровень сжатия объектов в pack (-1..9; -1 = default zlib;
# наследует core.compression)
git config --global pack.compression 6

# Порог «большого» pack-файла для gc (позволяет gc пропустить огромные pack)
git config --global gc.bigPackThreshold 512m

# Ручной repack с контролем глубины/окна дельт
git repack -a -d --depth=250 --window=250
```

**Пороги автоматического gc:** `gc.auto` (default 6700 loose-объектов), `gc.autoPackLimit` (default 50 pack-файлов без `.keep`; 0 отключает), `gc.autoDetach` (default true — `gc --auto` отцепляется в фон).

---

## Типичные ошибки и их решение

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `git status` зависает на >30с при 100k+ файлах | Отсутствует `core.fsmonitor` или `core.untrackedCache` | Включить `git config core.fsmonitor true` и `git config core.untrackedCache true` (или `feature.manyFiles`) |
| `scalar clone` недоступен | Git < 2.38 или Scalar не установлен (вне Git for Windows) | Обновить Git до 2.38+ или установить Scalar отдельно |
| `fatal: invalid object` после clone с `--filter` | Поврежденный promisor remote или неполный bundle | Удалить репозиторий и клонировать заново; проверить сеть |
| `git sparse-checkout` работает медленно | Используется классический режим вместо Cone | Переключиться: `git sparse-checkout init --cone` |
| Фоновое обслуживание не запускается | Устаревший Git (<2.30) или отключено | Обновить Git или запустить `git maintenance start` |
| Параллельные `git maintenance run` не выполняются | Столкновение на блокировке object database | Не запускать вручную во время scheduled прогонов; дорогие задачи (gc) переносить на менее частое расписание |
| `git-sizer` сообщает о "huge blobs" | В репозитории есть файлы >50MB в обычном Git | Перенести их в Git LFS через `git lfs migrate import` |
| MIDX не создается | `git multi-pack-index write` не был вызван или `gc` отключен | Запустить `git maintenance run --task=incremental-repack` |
| Reftable-репозиторий не открывается в старом Git | Git версии < 2.45 | Использовать Git 2.45+ или откатить миграцию |
| `git refs migrate` отказывается на репозитории с worktree | Миграция не поддерживает worktree | `git worktree remove` для всех worktree, затем повторить |
| Clone с `--bundle-uri` и `--depth` отклоняется | Опции несовместимы | Убрать `--depth` или не использовать `--bundle-uri` |

---

## Ограничения и крайние случаи

1.  **Partial Clone и сеть:** Динамическая догрузка отсутствующих объектов идёт по одному объекту и требует доступа к promisor remote. Для офлайн-работы предзагрузите нужные объекты (`git rev-list --objects --quiet --missing=print` + `git fetch`) или не используйте фильтры.
2.  **Sparse Index и совместимость:** Разреженный индекс — экспериментальная функция; некоторые команды могут работать медленнее, а внешние инструменты — не понимать разреженные записи индекса. При проблемах: `git sparse-checkout init --no-sparse-index`.
3.  **Scalar и Windows:** Scalar отключает `core.untrackedCache` на Windows (баги на Windows-файловых системах) и переключает `http.sslBackend=schannel`. На Windows используйте встроенный FSMonitor.
4.  **Bundle URIs и shallow-клон:** `--bundle-uri` несовместим с `--depth`, `--shallow-since`, `--shallow-exclude`; refs бандла хранятся в `refs/bundle/*`.
5.  **Background Maintenance и ресурсы:** Фоновое обслуживание использует CPU и I/O. На слабых машинах (CI runners, старые ноутбуки) отключите дорогие задачи (`git config maintenance.gc.enabled false`) или реже запускайте (`git config maintenance.incremental-repack.schedule weekly`) и запускайте вручную. Ключ `maintenance.auto` управляет только автозапуском `git maintenance run --auto` после команд, записывающих данные (default: true), — не частотой расписания.
6.  **Reftable и инструменты:** Некоторые сторонние инструменты (например, старые версии `git-filter-repo`, `git-sizer`) могут не распознавать reftable. Проверяйте совместимость перед миграцией.

---

## Best practices

1.  **Начинайте с Scalar** для монорепозиториев. Если Scalar не подходит (например, требуется точечный контроль), применяйте настройки по отдельности.
2.  **Включайте `core.fsmonitor` и `core.untrackedCache`** (или `feature.manyFiles`) глобально. Это почти бесплатно даёт заметное ускорение `git status` в репозиториях с 10k+ файлов.
3.  **Используйте Cone Mode** для Sparse-Checkout. Классический режим с регулярными выражениями становится медленным при >100 правилах.
4.  **Настраивайте Bundle URIs** на уровне хостинга для публичных репозиториев с высокой посещаемостью. Это снижает нагрузку на Git-сервер в десятки раз.
5.  **Запускайте `git maintenance`** вместо `git gc` в автоматизации. `maintenance` оптимизирует расписание и не блокирует работу пользователя; вместо `git gc` используйте `git maintenance run --task=gc`.
6.  **Анализируйте репозиторий** через `git-sizer` перед оптимизацией. Это помогает выбрать правильный метод (LFS, Sparse-Checkout, Partial Clone) вместо случайного.
7.  **Измеряйте, а не гадайте.** Используйте `GIT_TRACE2_PERF=1` или `hyperfine` для сравнения времени команд до и после изменений.
8.  **Для CI/CD комбинируйте** `--filter=blob:none` + Sparse-Checkout. Это дает минимальный трафик и максимальную скорость. (`--depth=1` тоже допустим, но не сочетается с `--bundle-uri`.)
9.  **Не смешивайте** Partial Clone и Sparse-Checkout без необходимости. Оба механизма добавляют сложность; достаточно одного.
10. **Планируйте рост:** если репозиторий растет >20% в год, заранее внедряйте reftable и background maintenance, пока репозиторий еще не достиг предела.

---

## Безопасность

- **Bundle URIs и MITM:** Bundle URI передается по HTTP/HTTPS. Для публичных репозиториев предпочитайте HTTPS с валидным сертификатом. Для приватных — используйте VPN или аутентифицированный прокси.
- **Partial Clone и промисорные удаленные репозитории:** Злоумышленник, контролирующий промисор remote, может отдавать вредоносные объекты. Используйте только доверенные серверы для `--filter`.
- **Background Maintenance в shared-средах:** На multiuser-серверах фоновый `git gc` может конкурировать за I/O. Ограничьте `git maintenance` через `cron` или `systemd` timers с nice-приоритетом.
- **Reftable и целостность:** Как и `packed-refs`, reftable критична для истории. Регулярно выполняйте `git fsck` после миграции.

---

## Дополнительная информация

### Рекомендации по обслуживанию

- **Фоновое обслуживание:** Используйте `git maintenance start`, чтобы Git обновлял `commit-graph` и упаковывал объекты в фоновом режиме, не прерывая работу.
- **Регулярный `git gc`:** Если background maintenance недоступен, настройте `git config --global gc.auto 256` (запускать `gc --auto` при наличии 256+ loose-объектов; по умолчанию 6700) и `git config --global gc.autoPackLimit 50`.
- **Мониторинг размера:** Используйте утилиту `git-sizer` для анализа проблемных мест репозитория (слишком большие деревья, глубокая история) и `git count-objects -v` для быстрой статистики loose/packed-объектов.
- **Очистка LFS:** Для репозиториев с LFS регулярно выполняйте `git lfs prune` и `git lfs fetch --recent`.
- **Проверка целостности:** Выполняйте `git fsck --strict` в CI или cron для раннего обнаружения повреждений.

### Связанные темы

- [Внутреннее устройство Git](./git_internals.md) — детали MIDX, Commit-Graph, Pack-файлов и Reftable.
- [Конфигурация Git](./git_configuration.md) — глобальные настройки производительности (`core.fsmonitor`, `fetch.parallel`).
- [Синхронизация репозиториев](./git_synchronization.md) — оптимизация `fetch` и `push` для больших репозиториев.
- [Git LFS](./git_lfs.md) — обработка тяжелых бинарных данных как альтернатива Partial Clone.
- [Git Worktree](./git_worktree.md) — производительность при использовании нескольких рабочих деревьев (общая база объектов).

### Официальные ресурсы

- **Git Performance Blog (GitHub):** [github.blog/category/engineering/](https://github.blog/category/engineering/)
- **Git Documentation - Performance:** [git-scm.com/docs/git-config#_core](https://git-scm.com/docs/git-config#_core)
- **Scalar Documentation:** [git-scm.com/docs/scalar](https://git-scm.com/docs/scalar)
- **Git Maintenance:** [git-scm.com/docs/git-maintenance](https://git-scm.com/docs/git-maintenance)
- **Partial Clone:** [git-scm.com/docs/partial-clone](https://git-scm.com/docs/partial-clone)
- **Bundle URIs:** [git-scm.com/docs/git-clone#_bundle_uri](https://git-scm.com/docs/git-clone#_bundle_uri)
