# Конфигурация Git LFS — .lfsconfig

## Определения

**`.lfsconfig`** — это файл конфигурации Git LFS, который хранится в корне репозитория и версионируется вместе с кодом. Он позволяет задавать общие настройки LFS-сервера и политики передачи данных для всех участников проекта, обеспечивая консистентность рабочего окружения.

Использование `.lfsconfig` критично для проектов с кастомными LFS-серверами или специфическими требованиями к производительности и безопасности.

Файл использует формат INI с секцией `[lfs]` и необязательными подсекциями для кастомных агентов передачи. **Важно:** `.lfsconfig` задает только параметры поведения LFS-клиента (URL сервера, параллелизм, политики fetching). Для определения, какие файлы должны обрабатываться через LFS, по-прежнему требуется файл `.gitattributes` с правилом `filter=lfs`. Отсутствие `.gitattributes` означает, что LFS не будет применяться к файлам, даже если `.lfsconfig` настроен.

---

## Базовые концепции

### Иерархия и приоритеты

Git LFS считывает конфигурацию из нескольких источников в следующем порядке (последний найденный параметр имеет приоритет):
1. **Локальный конфиг репозитория** (`.git/config`) — настройки только для текущего клона.
2. **Файл `.lfsconfig`** — настройки для всех разработчиков проекта.
3. **Глобальный конфиг пользователя** (`~/.gitconfig`) — персональные настройки.
4. **Системный конфиг.**

*Примечание: Локальные настройки в `.git/config` всегда переопределяют значения из `.lfsconfig`. Это полезно, если конкретному разработчику нужно использовать другой URL (например, через прокси).*

Если `.lfsconfig` отсутствует в репозитории, Git LFS использует значения по умолчанию и настройки из `.git/config`/`~/.gitconfig`. В этом случае каждый разработчик может иметь разное поведение LFS, что приводит к неожиданным проблемам с производительностью и безопасностью.

### Формат файла `.lfsconfig`

Файл использует синтаксис INI. Основная секция `[lfs]` содержит глобальные параметры. Для кастомных агентов передачи используются подсекции:

```ini
# .lfsconfig
[lfs]
    url = https://lfs.example.com/project
    concurrenttransfers = 16

[lfs "customtransfer.myagent"]
    path = /usr/local/bin/lfs-transfer-helper
    args = --bucket-name my-bucket
    concurrent = true
```

Имена секций и параметров чувствительны к регистру в некоторых версиях Git LFS; рекомендуется использовать нижний регистр.

### Основные параметры конфигурации

| Группа | Параметр | Описание |
| :--- | :--- | :--- |
| **Endpoint** | `lfs.url` | Основной URL LFS-сервера. Его явное указание в `.lfsconfig` предотвращает атаки через подмену URL при клонировании. |
| | `lfs.pushurl` | Отдельный URL для загрузки данных (upload), например, для CDN. |
| **Transfer** | `lfs.concurrenttransfers` | Кол-во одновременных потоков передачи (по умолчанию 8). |
| | `lfs.transfer.batchSize` | Кол-во объектов в одном API-запросе (v3.6+). Оптимально 100-500. |
| | `lfs.pathFilterCacheSize` | Размер кэша фильтров путей (v3.7+). Ускоряет работу в монорепозиториях. |
| **Fetching** | `lfs.fetchinclude` | Паттерны файлов для принудительного скачивания. |
| | `lfs.fetchexclude` | Паттерны файлов, которые не нужно скачивать по умолчанию. |
| | `lfs.fetchrecentrefsdays` | Загружать объекты, упомянутые в коммитах за последние N дней (по умолчанию 0 — только HEAD). |
| | `lfs.fetchrecentshaplimit` | Максимальное количество свежих коммитов, учитываемых при `lfs.fetchrecentrefsdays` (по умолчанию 100). |
| **Security** | `lfs.locksverify` | Проверять владение блокировкой (lock) перед push. |
| | `lfs.access` | Метод авторизации (`basic`, `private`). `basic` часто требуется для сторонних хранилищ. |
| **Pruning** | `lfs.pruneoffsetdays` | Кол-во дней хранения неиспользуемых объектов (по умолчанию 3). |
| | `lfs.pruneverifyremotealways` | Всегда проверять наличие копии на сервере перед удалением локально. |

**Примечание по `lfs.fetchrecentrefsdays`:** При значении >0 Git LFS автоматически загружает объекты, упомянутые в последних коммитах, что ускоряет работу в CI/CD и при переключении веток. Однако это увеличивает объем скачивания при первом clone.

---

## Практические сценарии

### Сценарий 1: Использование кастомного LFS-сервера
Применяется, когда LFS-объекты хранятся отдельно от основного Git-хостинга (например, в S3-совместимом хранилище).

```ini
# .lfsconfig
[lfs]
    url = https://lfs.internal.company.com/project-storage
    access = basic
```

### Сценарий 2: Оптимизация для сверхбольших репозиториев
Настройки для ускорения работы с десятками тысяч файлов (актуально для Git LFS 3.7.0 и 3.8.0).

```ini
# .lfsconfig
[lfs]
    # Увеличиваем параллелизм для высокоскоростных каналов
    concurrenttransfers = 32
    # Группируем запросы к API для уменьшения сетевых задержек
    transfer.batchSize = 500
    # Увеличиваем кэш фильтров для огромных деревьев файлов
    pathFilterCacheSize = 100000
```

### Сценарий 3: Настройка кастомного агента передачи (Custom Transfer Agent)
Используется для интеграции со сторонними инструментами передачи данных (например, `rclone` или специализированные протоколы).

```ini
# .lfsconfig
[lfs "customtransfer.myagent"]
    path = /usr/local/bin/lfs-transfer-helper
    args = --bucket-name my-lfs-bucket
    concurrent = true
```

### Сценарий 4: Политики автоматической очистки (Pruning)
Настройка того, как долго хранить старые версии файлов, которые не упоминаются в текущих ветках.

```ini
# .lfsconfig
[lfs]
    # Удалять файлы, которые не использовались более 7 дней
    pruneoffsetdays = 7
    # Обязательная проверка сервера перед локальным удалением
    pruneverifyremotealways = true
```

### Сценарий 5: Выборочная загрузка (Selective Fetching)
Позволяет экономить место на диске, не скачивая тяжелые ассеты, которые не нужны для текущей работы.

```ini
# .lfsconfig
[lfs]
    # По умолчанию игнорировать исходники видео и тяжелые датасеты
    fetchexclude = "assets/raw_video/*,data/training_sets/**"
```
*Разработчик может переопределить это локально через `git config lfs.fetchinclude "assets/raw_video/*"`.*

### Сценарий 6: Взаимодействие `.lfsconfig` и `.gitattributes`

`.lfsconfig` управляет **поведением LFS-клиента** (URL, параллелизм, политики), но **не определяет**, какие файлы обрабатываются через LFS. Для этого требуется `.gitattributes`:

```gitattributes
# .gitattributes
*.psd filter=lfs diff=lfs merge=lfs
*.mp4 filter=lfs diff=lfs merge=lfs
*.zip filter=lfs diff=lfs merge=lfs
```

**Порядок работы:**
1. `.gitattributes` указывает, что файлы `*.psd` должны обрабатываться через фильтр `lfs`.
2. `.lfsconfig` указывает, где хранятся LFS-объекты и как их передавать.
3. При `git add` clean-фильтр LFS использует настройки из `.lfsconfig` для загрузки файла.
4. При `git checkout` smudge-фильтр использует настройки из `.lfsconfig` для скачивания файла.

**Валидация:**
```bash
# Проверить, что файл отслеживается LFS
git check-attr filter path/to/file.psd
# → path/to/file.psd: filter: lfs

# Проверить, что .lfsconfig активен
git config lfs.url
# → https://lfs.internal.company.com/project-storage
```

### Сценарий 7: Оптимизация CI/CD с `.lfsconfig`

В пайплайнах часто не нужны тяжелые файлы. `.lfsconfig` может автоматически исключать их, а переменная окружения `GIT_LFS_SKIP_SMUDGE` ускоряет клонирование:

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

### Сценарий 8: Настройка SSH и HTTPS endpoints

LFS-сервер может быть доступен по разным протоколам. `.lfsconfig` позволяет явно указать URL, а `.git/config` — переопределить его для конкретного пользователя:

```ini
# .lfsconfig (версионируется)
[lfs]
    url = https://lfs.example.com/project
```

```bash
# Локальное переопределение для разработчика, у которого есть SSH-туннель
git config lfs.url ssh://git@lfs.example.com/project
```

**Валидация:**
```bash
# Проверить эффективный URL
git lfs env
# → Endpoint=https://lfs.example.com/project/info/lfs (auth=basic)

# Проверить, что локальный override применяется
git config lfs.url
# → ssh://git@lfs.example.com/project
```

### Сценарий 9: Переменные окружения, влияющие на LFS

Поведение Git LFS можно изменять без редактирования `.lfsconfig` через переменные окружения:

```bash
# Пропустить автоматическую замену указателей на реальные файлы при clone
export GIT_LFS_SKIP_SMUDGE=1

# Отключить проверку блокировок (опасно для командной работы!)
export GIT_LFS_LOCKS_VERIFY=0

# Использовать кастомный путь к LFS-кэшу
export GIT_LFS_CACHE_DIR=/tmp/lfs-cache
```

**Валидация:**
```bash
# Проверить, что переменная окружения действует
GIT_LFS_SKIP_SMUDGE=1 git lfs clone https://github.com/user/repo.git
# → Клонирование выполняется, файлы остаются указателями
```

### Сценарий 10: Проверка активности `.lfsconfig`

После добавления `.lfsconfig` в репозиторий важно убедиться, что он используется всеми участниками:

```bash
# 1. Проверить, что файл отслеживается Git
git ls-files .lfsconfig
# → .lfsconfig

# 2. Проверить эффективный URL LFS
git lfs env | grep Endpoint
# → Endpoint=https://lfs.example.com/project/info/lfs (auth=basic)

# 3. Проверить конкретные параметры
git config lfs.concurrenttransfers
# → 16
git config lfs.pruneoffsetdays
# → 7
```

Если `git config lfs.url` возвращает значение от GitHub/GitLab по умолчанию, а не из `.lfsconfig`, проверьте:
- Файл `.lfsconfig` закоммичен и доступен в текущей ветке.
- Нет локального override в `.git/config`.
- Файл имеет корректный синтаксис INI.

---

## Дополнительная информация

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `batch response: Authentication required` | `.lfsconfig` указывает неверный URL или отсутствует токен доступа | Проверить `lfs.url` и `lfs.access`, настроить credential helper |
| `LFS endpoint not configured` | `.lfsconfig` отсутствует или имеет синтаксическую ошибку | Проверить синтаксис INI, убедиться что секция `[lfs]` присутствует |
| `Smudge error: Error downloading file` | LFS-сервер недоступен или URL в `.lfsconfig` неверен | Выполнить `git lfs env`, проверить сетевую доступность URL |
| `Lock verification failed` | `lfs.locksverify=true`, но блокировка отсутствует или принадлежит другому пользователю | Запросить разблокировку у владельца или использовать `git lfs unlock --force` |
| `Pointer file instead of real file` | Файл добавлен в индекс до настройки tracking в `.gitattributes` | Выполнить миграцию: `git lfs migrate import --include="*.psd" --everything` |
| `Local config overrides ignored` | Разработчик ожидает, что `.lfsconfig` переопределит локальный `.git/config` | Помнить, что локальный конфиг имеет высший приоритет; использовать `git config --unset lfs.url` для сброса |
| `Pruning removes needed objects` | `lfs.pruneoffsetdays` слишком мал или ветка с нужными объектами не fetched | Увеличить `pruneoffsetdays`, включить `pruneverifyremotealways` |

### Ограничения и крайние случаи

1. **Отсутствие `.gitattributes`:** `.lfsconfig` не заменит `.gitattributes`. Если в репозитории нет правил `filter=lfs`, файлы будут храниться в обычном Git, даже если `.lfsconfig` полностью настроен.

2. **Bare-репозитории:** В bare-репозиториях нет рабочей директории. Smudge-фильтры (включая LFS) не запускаются автоматически при доступе через `git archive` или веб-интерфейс. Для корректной обработки объектов используйте `git config attr.tree main`.

3. **Локальные overrides:** Настройки из `.git/config` всегда имеют приоритет над `.lfsconfig`. Это может привести к ситуации, когда `.lfsconfig` кажется игнорируемым, хотя на деле работает локальный override.

4. **Версионирование секретов:** Если в `.lfsconfig` указаны учетные данные в URL (например, `https://user:pass@lfs.example.com`), они попадут в историю Git. Используйте credential helpers или переменные окружения.

5. **Кастомные Transfer Agents:** Агент, указанный в `[lfs "customtransfer.*"]`, должен быть установлен и доступен через `PATH` на всех машинах, включая CI/CD. Если агент отсутствует, все операции LFS завершатся ошибкой.

6. **Размер репозитория:** `.lfsconfig` не влияет на размер `.git` для файлов, уже добавленных до настройки LFS tracking. Требуется миграция через `git lfs migrate import`.

### Best practices

1. **Явное указание `lfs.url`:** Всегда указывайте `lfs.url` в `.lfsconfig` для предотвращения атак через подмену URL при клонировании.
2. **Синхронизация с `.gitattributes`:** Убедитесь, что `.lfsconfig` и `.gitattributes` коммитятся вместе. Изменение одного без другого приводит к неработающему LFS.
3. **Параллелизм:** Настройте `lfs.concurrenttransfers` в зависимости от пропускной способности канала (рекомендуется 8–32).
4. **Выборочная загрузка:** Используйте `lfs.fetchinclude` и `lfs.fetchexclude` для экономии места в монорепозиториях.
5. **Безопасность:** Включите `lfs.locksverify = true` для командной работы с бинарными файлами.
6. **Очистка:** Настройте `lfs.pruneoffsetdays = 7` и `lfs.pruneverifyremotealways = true`.
7. **CI/CD:** Используйте `GIT_LFS_SKIP_SMUDGE=1` и кэшируйте `.git/lfs/objects` между запусками.
8. **Миграция:** Проводите миграцию больших файлов в LFS до того, как репозиторий станет слишком большим.

### Безопасность

- **Подмена URL (URL hijacking):** Если в репозитории отсутствует `.lfsconfig` или `lfs.url`, злоумышленник может внедрить вредоносный LFS-сервер через `.gitattributes` с `filter=lfs` и перехватывать данные при клонировании. Всегда явно указывайте `lfs.url` в `.lfsconfig`.
- **Локальные overrides:** Разработчики могут переопределить `lfs.url` в `.git/config`. В корпоративной среде используйте pre-receive hooks для проверки, что `.lfsconfig` не изменен.
- **Учетные данные в URL:** Никогда не храните пароли или токены в `.lfsconfig`. Используйте Git credential helpers или SSH-ключи.

### Отладка конфигурации

Чтобы увидеть, какие именно значения и из каких источников использует LFS:

```bash
# Вывод всех переменных окружения и путей LFS
git lfs env

# Проверка источника конкретного параметра
git config --show-origin lfs.url
# → file:/Users/user/.gitconfig    lfs.url=https://lfs.example.com/project

# Проверка того, какие файлы попадают под текущие фильтры fetch
git lfs fetch --dry-run

# Проверка конфигурации в конкретном коммите
git show HEAD:.lfsconfig
```

### Официальные ресурсы

- **Сайт проекта:** [git-lfs.com](https://git-lfs.com/)
- **GitHub Repository:** [github.com/git-lfs/git-lfs](https://github.com/git-lfs/git-lfs)
- **Wiki по конфигурации:** [github.com/git-lfs/git-lfs/wiki/Configuration](https://github.com/git-lfs/git-lfs/wiki/Configuration)
- **Документация Git:** [git-scm.com/docs/gitattributes](https://git-scm.com/docs/gitattributes)
- **GitHub Linguist:** [github.com/github-linguist/linguist](https://github.com/github-linguist/linguist)

### Связанные документы

- [Обзор Git LFS](./git_lfs.md) — базовые команды и принципы работы.
- [Атрибуты Git (.gitattributes)](./git_attributes.md) — настройка отслеживания (tracking) и фильтров.
- [Конфигурация Git](./git_configuration.md) — общие настройки Git, включая `git-crypt` и `includeIf`.
- [Специальные файлы Git](./git_special_files_overview.md) — место `.lfsconfig` в иерархии репозитория.
