# Git LFS (Large File Storage)

**Актуально для:** Git LFS 3.8.0

## Определения

* **Git LFS (Large File Storage):** Расширение для Git, предназначенное для эффективного управления большими бинарными файлами (изображения, видео, датасеты, артефакты сборки). Оно заменяет реальные файлы в репозитории на текстовые указатели (pointer files), сохраняя сами данные на удалённом LFS-сервере.
* **Pointer File (файл-указатель):** Текстовый файл фиксированного формата, хранящийся в Git вместо оригинального бинарного файла. Содержит SHA-256 хеш (OID), размер файла и версию спецификации LFS.
* **OID (Object IDentifier):** Уникальный SHA-256 хеш содержимого файла, используемый для идентификации и адресации объектов в хранилище LFS.
* **Smudge Filter:** Фильтр, который автоматически заменяет указатель на реальный файл при извлечении из репозитория (`checkout`).
* **Clean Filter:** Фильтр, который автоматически заменяет реальный файл на указатель при добавлении в индекс (`staging`).
* **Merge Driver (lfs-text):** Пользовательский merge-драйвер, объединяющий текстовые файлы, хранящиеся в LFS, посредством `git lfs merge-driver`. Не включён по умолчанию; требует регистрации через `git config merge.lfs-text.driver`.
* **Lockable file:** Файл, отмеченный `git lfs track --lockable`, делаемый read-only в working copy, пока не заблокирован текущим пользователем.
* **Copy-on-write (CoW):** Файловая операция, при которой файлы-клоны ссылаются на одни и те же блоки данных до первой записи. Используется `git lfs dedup` для экономии диска.

## Базовые концепции

### Механизм работы

Традиционный Git хранит полную историю всех версий каждого файла. Для тяжёлых бинарных данных это приводит к экспоненциальному росту размера директории `.git`, так как Git не может эффективно применить дельта-сжатие к бинарным форматам.

**Git LFS работает следующим образом:**
1. В локальном репозитории вместо файла `image.psd` (например, 500 МБ) хранится текстовый файл-указатель (Pointer File) размером ~130 байт.
2. Указатель содержит версию спецификации, уникальный SHA-256 хеш (OID) и размер оригинального файла.
3. При операциях `checkout` или `pull` Git LFS перехватывает запрос через smudge-фильтр и скачивает нужную версию файла с LFS-сервера в локальный кэш (`.git/lfs/objects`), после чего заменяет указатель на реальные данные.
4. При добавлении файла в индекс (`git add`) clean-фильтр вычисляет OID, загружает файл на LFS-сервер и заменяет содержимое на указатель.

**Пример структуры файла-указателя:**
```text
version https://git-lfs.github.com/spec/v1
oid sha256:1a2b3c4d5e6f7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f
size 524288000
```

**Архитектура фильтров:**
* **Clean filter** (при `git add`): Читает рабочий файл → вычисляет SHA-256 → загружает на сервер → заменяет содержимое в индексе на pointer.
* **Smudge filter** (при `git checkout`): Читает pointer из индекса → проверяет наличие в локальном кэше → при отсутствии скачивает с сервера → заменяет pointer на реальный файл в working directory.

### Структура локального кэша

LFS-объекты хранятся в `.git/lfs/objects/` в иерархической структуре, аналогичной Git object store:
```
.git/lfs/objects/
├── 1a/           # Первые 2 символа SHA-256
│   └── 2b/       # Следующие 2 символа
│       └── 3c4d5e6f...  # Оставшиеся символы = полный OID
└── tmp/          # Временные файлы при загрузке
```

**Важно:** Локальный кэш может значительно превышать размер рабочей директории, так как хранит все скачанные версии файлов.

### Преимущества

* **Производительность клонирования:** Клонирование репозитория происходит быстрее, так как по умолчанию скачиваются только указатели для текущей ветки (smudge-фильтр обрабатывает только HEAD).
* **Экономия места:** На диске разработчика находятся только те версии файлов, которые используются в текущем `checkout`.
* **Масштабируемость:** Позволяет хранить терабайты данных, не нарушая стабильность работы стандартных команд Git.
* **Эффективная передача:** Поддержка параллельных загрузок (`lfs.concurrenttransfers`, по умолчанию 8) и пакетных операций для ускорения работы с тысячами файлов.

### Ограничения и недостатки

* **Стоимость хранения:** Популярные хостинги взимают плату за хранение и трафик LFS сверх бесплатных лимитов.
* **Несовместимость с GitHub Pages:** Файлы, хранящиеся в LFS, не будут отображаться на статических сайтах.
* **Трудности удаления данных:** Простое удаление файла из коммита не удаляет его физически с LFS-сервера (требуется очистка через API хостинга или `git lfs prune` с последующей синхронизацией).
* **Vendor Lock-in:** Перенос LFS-данных между разными хостингами сложнее, чем перенос обычного репозитория, из-за привязки к конкретному LFS-серверу.
* **Зависимость от сервера:** При недоступности LFS-сервера невозможно получить актуальные версии файлов (только из локального кэша).

### Сравнение Git LFS и нативного Partial Clone

| Характеристика | Git LFS | Git Partial Clone |
| :--- | :--- | :--- |
| **Тип** | Внешнее расширение | Нативная функция Git |
| **Хранение** | Отдельный LFS-сервер | Тот же Git-сервер |
| **Механизм** | Файлы-указатели (pointers) + фильтры | «Ленивая» загрузка объектов (promisor remotes) |
| **Когда использовать** | Огромные бинарные файлы (>100 МБ) | Файлы любого размера, нужные выборочно |
| **Сложность** | Требует настройки `.gitattributes` | Проще в использовании (флаг при клонировании) |
| **Поддержка merge** | Требует lock или custom merge driver (`merge=lfs-text`) | Нативная поддержка |

---

## Практические сценарии

### Предварительные требования

**Системные требования:**
* Git 2.0.0 или выше (рекомендуется 2.30+; на 2026 год — Git 2.56.0)
* Установленный клиент Git LFS (отдельный бинарный файл)
* Доступ к LFS-серверу (встроенный в хостинг или кастомный)

**Установка Git LFS:**
```bash
# macOS (Homebrew)
brew install git-lfs

# Ubuntu/Debian
sudo apt-get install git-lfs

# Windows (Chocolatey)
choco install git-lfs

# Проверка версии
git lfs version
# → git-lfs/3.8.0 (GitHub; darwin arm64; go 1.25.0)
```

### Установка и инициализация

Команда `git lfs install` настраивает **глобальные clean/smudge-фильтры** для Git и устанавливает хуки в текущем репозитории. Выполняется один раз на машине разработчика.

```bash
# Установка clean/smudge-фильтров LFS и хуков в глобальный конфиг Git
git lfs install
# → Updated Git hooks.
# → Git LFS initialized.

# Проверка корректной установки (выводит текущее окружение и пути)
git lfs env
# → git-lfs/3.8.0 (GitHub; darwin arm64; go 1.25.0)
# → git version 2.56.0
# → Endpoint=https://github.com/user/repo.git/info/lfs (auth=basic)
# → LocalWorkingDir=/path/to/repo
# → LocalGitDir=/path/to/repo/.git
# → LocalMediaDir=/path/to/repo/.git/lfs/objects
# → ConcurrentTransfers=8
```

**Валидация:**
```bash
# Убедиться, что хуки LFS установлены
ls -la .git/hooks/ | grep lfs
# → post-checkout
# → post-commit
# → post-merge
# → pre-push
```
**Примечание:** `git lfs install` устанавливает четыре хука: `pre-push` (загрузка LFS-объектов перед `git push`) и `post-checkout`/`post-commit`/`post-merge` (поддержка lockable-файлов: делают бинарники read-only, пока не заблокированы).

### Отслеживание файлов

Правила отслеживания сохраняются в файле `.gitattributes` и должны быть закоммичены для применения ко всем участникам проекта.

```bash
# Начать отслеживание всех PSD-файлов (добавит filter=lfs diff=lfs merge=lfs -text)
git lfs track "*.psd"
# → Tracking "*.psd"

# Отслеживание конкретной директории
git lfs track "assets/textures/**"
# → Tracking "assets/textures/**"

# Бинарные файлы: включить блокировку до редактирования (--lockable делает файлы read-only, пока не заблокированы)
git lfs track --lockable "*.psd"
# → Tracking "*.psd"

# Просмотр всех текущих правил отслеживания
git lfs track
# → Listing tracked patterns
# →     *.psd (.gitattributes)

# Добавить .gitattributes в индекс (обязательно для совместной работы)
git add .gitattributes
git commit -m "chore: configure LFS tracking"
```

**Слияние текстовых LFS-файлов (`merge=lfs-text`):** по умолчанию `git lfs track` ставит атрибут `merge=lfs` (пасстхру-заглушка, не выполняющая слияния). Для текстовых файлов (например, CSV), которые нужно сливать как обычный Git-текст, замените `merge=lfs` на `merge=lfs-text` в `.gitattributes` и зарегистрируйте merge-драйвер через `git config` (он использует `git lfs merge-driver`):
```bash
# 1. В .gitattributes поменяйте merge=lfs на merge=lfs-text:
#    *.csv filter=lfs diff=lfs merge=lfs-text -text

# 2. Зарегистрировать merge-драйвер через Git
git config merge.lfs-text.driver \
  'git lfs merge-driver --ancestor %O --current %A --other %B --marker-size %L --output %A'

# 3. Зафиксировать
git add .gitattributes
git commit -m "feat: enable text merge for CSV via lfs-text driver"
```

**Валидация:**
```bash
# Проверить, что файл отслеживается LFS
git check-attr filter path/to/file.psd
# → path/to/file.psd: filter: lfs

# Убедиться, что .gitattributes закоммичен
git ls-files .gitattributes
# → .gitattributes
```

**Важно:** Файлы, уже добавленные в Git до настройки LFS tracking, остаются в истории как обычные объекты. Для переноса их в LFS необходима миграция (см. раздел «Миграция существующих файлов»).

### Блокировка файлов (File Locking)

Бинарные файлы невозможно эффективно объединить (`merge`). Чтобы избежать конфликтов при параллельной работе, используется механизм блокировки на сервере.

**Важно:** File Locking поддерживается не всеми LFS-серверами. Доступен в GitHub, GitLab, Bitbucket и кастомных серверах с поддержкой LFS Locks API.

```bash
# Заблокировать файл для редактирования
git lfs lock design.psd
# → Locked design.psd

# Заблокировать файл с указанием пути
git lfs lock assets/models/character.fbx
# → Locked assets/models/character.fbx

# Список всех заблокированных файлов в репозитории
git lfs locks
# → design.psd  User Name  ID:123
# → assets/models/character.fbx  Another User  ID:124

# Разблокировать файл
git lfs unlock design.psd
# → Unlocked design.psd

# Принудительная разблокировка (только для владельца блокировки или администратора)
git lfs unlock design.psd --force
# → Unlocked design.psd
```

**Валидация:**
```bash
# Проверить статус блокировки конкретного файла
git lfs locks --path=design.psd
# → design.psd  User Name  ID:123
```

**Edge cases:**
* При попытке заблокировать файл, уже заблокированный другим пользователем, получите ошибку: `Lock already created by another user`
* При попытке `push` заблокированного файла без владения блокировкой: `Lock verification failed`. Для проверки блокировок перед `push` используется настройка `lfs.locksverify`.
* Чтобы увидеть собственные блокировки с пометкой `O` (владелец), используйте `git lfs locks --verify`.

### Оптимизация для CI/CD и пакетные операции

В пайплайнах часто не нужны тяжелые файлы (например, если выполняется только линтинг кода или тесты логики).

```bash
# Пропустить загрузку LFS-объектов при клонировании (ускорение CI)
export GIT_LFS_SKIP_SMUDGE=1
git clone https://github.com/user/repo.git

# После клонирования с SKIP_SMUDGE файлы-указатели нужно заменить вручную
cd repo
git lfs pull
# → Downloading LFS objects: 100% (150/150), 2.3 GB | 45 MB/s

# Принудительная загрузка ВСЕХ LFS-объектов для всех веток (актуально для бэкапов)
git lfs fetch --all
# → Downloading LFS objects: 100% (450/450), 12 GB | 15 MB/s

# Загрузка объектов только для конкретных веток
git lfs fetch origin main develop

# Выборочная загрузка по паттернам (настраивается lfs.fetchinclude / lfs.fetchexclude)
git lfs fetch --include="assets/textures/**" --exclude="assets/videos/**"

# Быстрая загрузка recent-объектов для PR (объекты из последних коммитов)
git lfs fetch --recent
```

**Валидация:**
```bash
# Проверить, что файл загружен (не является указателем)
git lfs pointer --check --file=path/to/file.psd
# → (ничего не выводит; exit 0 = файл является корректным указателем LFS)
# → (exit != 0 = файл — реальные данные, а не указатель)

# Проверить статус LFS в репозитории
git lfs status
# → On branch main
# → 
# → Objects to be committed:
# →     image.psd (LFS: 1a2b3c4)
# → 
# → Objects not staged for commit:
# →     image.psd (LFS: 1a2b3c4)
```

**Best practices для CI/CD:**
* Используйте `GIT_LFS_SKIP_SMUDGE=1` для ускорения клонирования, если LFS-файлы не нужны.
* Кэшируйте директорию `.git/lfs/objects` между запусками пайплайна для ускорения.
* Для монорепозиториев настраивайте `lfs.fetchinclude` и `lfs.fetchexclude` в `.lfsconfig`.
* Если CI выполняет `git push`, убедитесь, что объекты доступны локально, либо задайте `GIT_LFS_SKIP_PUSH=1`, чтобы пропустить загрузку LFS-объектов на сервер.

### Обслуживание и очистка

Локальный кэш LFS может быстро разрастаться за счёт хранения старых версий тяжёлых файлов.

```bash
# Размер локального LFS-кэша (стандартная утилита du; git lfs du больше не существует)
du -sh .git/lfs/objects
# → 1.2G    .git/lfs/objects

# Симуляция очистки (без удаления): покажет, что будет удалено
git lfs prune --dry-run
# → 45 local objects, 0 retained
# → 45 files would be pruned (3.2 GB)

# Удалить старые объекты, не используемые последние N дней
git lfs prune --recent
# → 45 local objects, 0 retained

# Подробная очистка с верификацией на удалённом сервере (медленнее, но надёжнее)
git lfs prune --verbose --recent --verify-remote
# → 45 local objects, 0 retained, 45 verified with remote
# → 1a2b3c4d5e (5.2 MB)
# → 4d5e6f6a7b (3.1 MB)
```

**Валидация:**
```bash
# После очистки проверить размер кэша
du -sh .git/lfs/objects
# → 500M    .git/lfs/objects

# Убедиться, что все текущие файлы доступны
git lfs fsck
# → Git LFS fsck OK
```

**Best practices:**
* Настройки `prune` нельзя задавать в `.lfsconfig` — используйте локальный или глобальный Git-конфиг. Рекомендуемое смещение «окна recent» — 7 дней:
```bash
git config lfs.pruneoffsetdays 7
git config lfs.pruneverifyremotealways true
```
* Запускайте `git lfs prune` периодически или настраивайте cron/scheduled task.
* `lfs.storage` (локальный/глобальный конфиг, не `.lfsconfig`) переносит кэш за пределы `.git` — удобно для выделенного тома. Не запускайте `git lfs prune` для репозиториев, разделяющих одно и то же хранилище.

### Миграция существующих файлов

Если тяжёлые файлы уже находятся в истории Git (раздут `.git`), их нужно перенести в LFS через перезапись истории.

**Важно:** Миграция изменяет историю коммитов (переписывает SHA). Требует force push и координации с командой.

```bash
# Анализ истории: топ-10 типов файлов по занимаемому объёму
git lfs migrate info --everything --top=10
# → Fetching remote refs: ..., done
# → Sorting commits: ..., done
# → Examining commits: 100% (4550/4550), done
# → *.psd   45.2 GB   1500/1600 files(s)   100%
# → *.mp4   120.5 GB  200/250 files(s)   100%

# Анализ файлов больше 100 МБ (процент = доля файлов типа выше порога)
git lfs migrate info --everything --above=100MB
# → *.psd   45.2 GB   1500/1600 files(s)   95%
# → *.mp4   120.5 GB  200/250 files(s)   80%

# Миграция всех ZIP и MP4 во всех ветках (перезапись истории)
git lfs migrate import --everything --include="*.zip,*.mp4"
# → Fetching remote refs: ..., done
# → Sorting commits: ..., done
# → Rewriting commits: 100% (4550/4550), done
# →   main  d2b959babd... -> 136e706bf1...
# → Updating refs: ..., done

# Миграция с исключением определённых путей
git lfs migrate import --everything --include="*.psd" --exclude="legacy/**"
# → Rewriting commits: 100% (120/120), done
# →   main  d2b959babd... -> 136e706bf1...

# Миграция только для конкретной ветки
git lfs migrate import --include-ref=main --include="*.zip"

# Миграция без перезаписи истории (новый коммит, без изменения SHA существующих)
git lfs migrate import --no-rewrite --yes -m "Import large assets" images/*.psd
```

**Валидация после миграции:**
```bash
# Проверить, что файлы теперь отслеживаются LFS
git lfs ls-files | head -5
# → 1a2b3c4d5e * archive.zip
# → 4d5e6f6a7b * video.mp4

# Убедиться, что старые объекты удалены из Git-хранилища
git count-objects -v
# → size: 45232  # Размер должен значительно уменьшиться

# Проверить целостность
git lfs fsck
# → Git LFS fsck OK
```

**После миграции:**
```bash
# Принудительный push всех веток (опасно для общих веток!)
git push --force --all
git push --force --tags

# Очистка старых объектов и рефлога
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**Важно для команды:**
* Все разработчики должны переклонировать репозиторий или выполнить `git rebase` после force-push.
* Рекомендуется проводить миграцию в период низкой активности.
* Создайте бэкап репозитория перед миграцией.

### Отладка и диагностика

```bash
# Полная информация об окружении LFS
git lfs env
# → git-lfs/3.8.0 (GitHub; darwin arm64; go 1.25.0)
# → git version 2.56.0
# → Endpoint=https://github.com/user/repo.git/info/lfs (auth=basic)
# → LocalWorkingDir=/path/to/repo
# → LocalGitDir=/path/to/repo/.git
# → LocalMediaDir=/path/to/repo/.git/lfs/objects
# → ConcurrentTransfers=8

# Проверка конфигурации и путей фильтрации
git lfs fetch --dry-run
# → 45 objects found

# Вывод статуса LFS в формате JSON (удобно для автоматизации)
git lfs status --json
# → {"files":{"path/to/file.bin":{"status":"modified"}}}
```

---

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Lock verification failed` | Файл заблокирован другим пользователем | Дождаться разблокировки или обратиться к владельцу блокировки |
| `batch response: Authentication required` | Проблема с аутентификацией на LFS-сервере | Проверить токен/SSH-ключ, настроить `lfs.access` |
| `Smudge error: Error downloading file` | Файл отсутствует в локальном кэше и недоступен на сервере | Проверить сеть, выполнить `git lfs fetch --all` |
| `Pointer file not found` | Указатель не распознан как LFS-объект | Проверить `.gitattributes`, убедиться в корректности правил |
| `LFS object is missing` | Объект удалён из локального кэша | Выполнить `git lfs pull` для повторной загрузки |
| `Filename too long` (Windows) | Ограничение длины пути в Windows | `git config --global core.longpaths true` |
| `Smudge error: Error buffering for ...` (macOS) | Размер файла превышает лимит Git (4 ГБ на Windows < 2.34.0) | Включить `lfs.largefilewarning=false` или разбить файл |

**Диагностические команды:**
```bash
# Проверка целостности объектов (перемещает повреждённые в .git/lfs/bad)
git lfs fsck --objects
# → Git LFS fsck OK

# Проверка конкретного файла на соответствие LFS (выводит указатель на stderr)
git lfs pointer --file=path/to/file.psd
# → Git LFS pointer for path/to/file.psd
# → version https://git-lfs.github.com/spec/v1
# → oid sha256:1a2b3c4d5e6f...
# → size 524288000

# Проверить, является ли файл указателем (exit 0 = указатель, exit 1 = файл)
git lfs pointer --check --file=path/to/file.psd
# → (ничего не выводит; exit 0 = файл является корректным указателем LFS)

# Трассировка сетевых операций LFS
GIT_TRACE=1 git lfs pull
```

---

## Best practices

1. **Настройка `.lfsconfig`:** Всегда явно указывайте `lfs.url` в `.lfsconfig` для предотвращения атак через подмену URL.
2. **Выборочная загрузка:** Используйте `lfs.fetchinclude` и `lfs.fetchexclude` в `.lfsconfig` для экономии места в монорепозиториях.
3. **Параллелизм:** Настройте `lfs.concurrenttransfers` (по умолчанию 8; рекомендуется 8–32 в зависимости от канала).
4. **Блокировка:** Всегда блокируйте бинарные файлы перед редактированием в командной работе (`git lfs track --lockable` + `git lfs lock`).
5. **Очистка:** Настройте автоматическую очистку через `lfs.pruneoffsetdays` и `lfs.pruneverifyremotealways` в Git-конфиге (не в `.lfsconfig`).
6. **CI/CD:** Используйте `GIT_LFS_SKIP_SMUDGE=1` и кэшируйте `.git/lfs/objects` между запусками.
7. **Миграция:** Переносите большие файлы в LFS до того, как репозиторий станет слишком большим; всегда делайте бэкап и согласовывайте force-push с командой.

---

## Дополнительная информация

### Операционная инженерия (SRE / DevOps / Sysadmin)

В производстве Git LFS требует администрирования, отличного от обычного Git: бинарные артефакты живут в отдельном кэше и синхронизируются с LFS-сервером. Ниже — проверенные практики, не зависящие от облачных провайдеров.

**Контроль целостности в CI:** `git lfs fsck` проверяет, что все LFS-объекты в актуальном HEAD существуют на диске и соответствуют своим SHA-256. Добавьте шаг после `checkout`, чтобы ловить повреждённые или потерянные объекты:
```bash
git lfs fsck
# → Git LFS fsck OK
```

**Мониторинг диска LFS-кэша:** Кэш `.git/lfs/objects` хранит все версии скачанных файлов и часто превышает размер `working directory`. На CI-раннерах с ограниченным диском измеряйте объём кэша (стандартная утилита `du`, так как `git lfs du` удалена):
```bash
du -sh .git/lfs/objects
# → 1.2G    .git/lfs/objects
```

**Дедупликация Copy-on-write:** `git lfs dedup` пересоздаёт working tree-файлы как CoW-клоны объектов LFS (требует поддержки файловой системы: Btrfs, APFS). Полезно для образов контейнеров и VM, где артефакты сборки копируются между слоями:
```bash
git lfs dedup --test
# → OK: This platform and repository support file de-duplication.

git lfs dedup
# → Finished successfully.
# →   De-duplicated  size: 2345678901 bytes
# →               count: 15
```

**Автоматическая очистка:** Периодический `prune` освобождает диск. Поскольку настройки `prune` нельзя задать в `.lfsconfig` (см. выше), используйте локальный или глобальный конфиг и планируйте через cron/scheduled task:
```bash
git config lfs.pruneoffsetdays 7
git config lfs.pruneverifyremotealways true
git lfs prune --verify-remote --recent
```

**Поведение pre-push hook в CI:** Хук `pre-push` (устанавливается `git lfs install`) загружает очередные LFS-объекты перед `git push`. При недоступности LFS-сервера `push` отменяется. Если CI выполняет `git push`, но не должен загружать LFS (например, публикация тега без артефактов), задайте `GIT_LFS_SKIP_PUSH=1`.

**Безопасность:**
* `lfs.url` в `.lfsconfig` фиксирует сервер LFS, предотвращая атаки типа «одолжи репозиторий — подмени URL».
* `lfs.<url>.locksverify` контролирует проверку блокировок перед `push` (по умолчанию `null` — LFS пытается вызвать сервер, а если ответ `501 Not Implemented`, отключает проверку).
* `GIT_LFS_SKIP_DOWNLOAD_ERRORS=1` (или `lfs.skipdownloaderrors`) позволяет выполнять `checkout` даже при сбое скачивания — удобно для автономной работы, но меняет семантику команд.

### Будущее: Promisor Remotes

В современных версиях Git активно развивается механизм **Promisor Remotes** (часть Partial Clone). Он позволяет Git взаимодействовать с внешними хранилищами напрямую через нативный протокол, что в долгосрочной перспективе может упростить работу с большими файлами за счёт глубокой интеграции «ленивой» загрузки в ядро Git. Однако на текущий момент (2026) Git LFS остаётся основным решением для работы с большими бинарными файлами благодаря зрелости экосистемы и широкой поддержке хостингами.

### Официальные ресурсы

* **Git LFS:** [git-lfs.com](https://git-lfs.com/)
* **Wiki на GitHub:** [github.com/git-lfs/git-lfs/wiki](https://github.com/git-lfs/git-lfs/wiki)
* **Документация Git Partial Clone:** [git-scm.com/docs/partial-clone](https://git-scm.com/docs/partial-clone)

### Связанные темы

* [Конфигурация Git LFS (.lfsconfig)](./git_lfs_config.md) — детальная настройка серверов, параллелизма и кэширования.
* [Атрибуты Git (.gitattributes)](./git_attributes.md) — механизмы фильтрации и обработки типов данных.
* [Обзор специальных файлов Git](./git_special_files_overview.md) — место LFS в общей структуре конфигурации репозитория.
