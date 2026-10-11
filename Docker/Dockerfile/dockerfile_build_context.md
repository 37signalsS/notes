# Контекст сборки Docker и .dockerignore

**Актуально для:** Docker Engine 29.x, Dockerfile syntax 1.19+ (стабильный канал `docker/dockerfile:1` — 1.27.x), Buildx v0.37.x

## Определения

**Контекст сборки (Build Context)** — это совокупность файлов и директорий, которые становятся доступными для инструкций `COPY` и `ADD` в процессе создания образа. При запуске сборки Docker-клиент применяет `.dockerignore`, упаковывает оставшиеся файлы и передаёт их сборщику (BuildKit).

**`.dockerignore`** — файл конфигурации, определяющий список исключений из контекста сборки. Файлы, подходящие под паттерны в `.dockerignore`, **не передаются сборщику вообще** — это критично для производительности и безопасности.

**Именованный контекст (Named Context)** — дополнительный источник файлов, подключаемый к сборке флагом `--build-context NAME=SOURCE` и адресуемый в Dockerfile как стадия (`COPY --from=NAME`, `RUN --mount=from=NAME`).

### Связь с инструкциями COPY и ADD

Инструкции `COPY` и `ADD` в Dockerfile могут обращаться **только** к файлам, находящимся в контексте сборки. Если файл исключён через `.dockerignore` или находится вне указанного пути — инструкция `COPY` завершится ошибкой. Контекст сборки — единственный канал передачи файлов от хоста в образ: инструкция `RUN` не видит файлов хоста ни при каких условиях, пока они не скопированы через `COPY`/`ADD` или не подключены через `RUN --mount=type=bind`.

Два свойства путей в `COPY`/`ADD` о которых чаще всего забывают:

- Ведущий слэш и навигация вверх (`../`) **автоматически удаляются**: `COPY ../something /something` эквивалентно `COPY something /something`, а `COPY something/ /something` — `COPY something /something`.
- Если Dockerfile передан через stdin (`docker build - < Dockerfile`), **файлового контекста нет вообще**. В этом случае `COPY` может обращаться только к другим стадиям, именованным контекстам или образам через `--from`. Чтобы сохранить локальный контекст при чтении Dockerfile из stdin, используйте `docker build -f- . < Dockerfile`.

## Предварительные требования

### Программное обеспечение

| Компонент | Минимальная версия | Актуальная версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Docker Engine** | 23.0 | 29.8.x | BuildKit — сборщик по умолчанию; Legacy Builder удалён из актуальных линеек |
| **Buildx** | 0.15.0 | 0.37.x | 0.15.0 — минимальная версия для `docker build --check` |
| **Dockerfile frontend** | 1.19 | 1.27.x (тег `1`) | Стабильный канал; тег `1` всегда указывает на последний стабильный минор |
| **BuildKit (в составе Engine)** | 0.11 | 0.32.x | Требуется для `SOURCE_DATE_EPOCH` и сборок с `--security` |

Порядок каналов фронтенда: `1` (стабильный), `1.27` / `1.27.1` (конкретный минорный), `1-labs` / `1.27.1-labs` (экспериментальные возможности канала labs). Канал `labs` может убрать фичу без смены мажорной версии — для продакшн-сборок его использовать не следует.

Актуальный минор всегда можно узнать из самого образа фронтенда, не полагаясь на память:

```bash
docker manifest inspect docker/dockerfile:1 --verbose \
  | grep '"org.opencontainers.image.version"'
# → "org.opencontainers.image.version": "1.27.1"
```

### Проверка работоспособности

```bash
# Проверка версии Docker
docker version --format '{{.Server.Version}}'
# → 29.8.1

# Проверка версии и коммита Buildx
docker buildx version
# → github.com/docker/buildx v0.37.1 0b265a9f62db554fa9aba6dd19e1bd5704bc7d8a

# Проверка активного сборщика (должен быть BuildKit)
docker buildx inspect --bootstrap
# → Name:          default
# → Driver:        docker
```

## Базовые концепции

### Механизм передачи контекста

В классическом Docker (Legacy Builder) весь контекст упаковывался в tar-архив целиком и отправлялся демону одним запросом — отсюда сообщение `Sending build context to Docker daemon 8.192kB`. В **BuildKit** процесс устроен иначе:

- **Фильтрация на клиенте.** Сборщик не получает файлы, отброшенные `.dockerignore`. Передаётся ровно то, что осталось после применения правил исключения.
- **Инкрементальная передача.** Между сборками передаются только изменившиеся файлы; неизменённые берутся из локального кэша сессии на стороне сборщика.
- **Ленивое чтение.** Файлы из локального источника докачиваются по мере обращения к ним в инструкциях `COPY`/`ADD`, а не сплошным потоком в начале сборки.

Практическое следствие для DevOps/SRE: при работе с **удалённым** сборщиком (`docker-container`, `remote`, собственный `buildkitd` на выделенном раннере) качество `.dockerignore` определяет не только скорость сборки, но и фактический сетевой трафик и время ожидания раннера в CI.

### Архитектура сборки BuildKit

BuildKit работает по принципу графа Directed Acyclic Graph (DAG). Каждая инструкция Dockerfile становится узлом графа, и сборщик определяет оптимальный порядок выполнения:

```
Клиент Docker                BuildKit Daemon
    |                            |
    |  1. Передача контекста      |
    |  (только нужные файлы)     |
    |--------------------------->|
    |                            | 2. Парсинг Dockerfile -> LLB Graph
    |                            | 3. Параллельное выполнение узлов
    |  4. Запрос файлов          |
    |<---------------------------|
    |  5. Передача файлов        |
    |--------------------------->|
    |                            | 6. Коммит слоёв -> Готовый образ
```

**LLB (Low-Level Builder)** — промежуточное представление графа сборки в формате Protobuf. BuildKit транслирует инструкции Dockerfile в LLB, что позволяет:
- Параллельно выполнять независимые стадии
- Кэшировать результаты промежуточных шагов
- Оптимизировать порядок операций для минимизации передачи данных

### Типы контекста

Позиционный аргумент `docker build PATH | URL | -` определяет контекст:

1. **Локальная директория:** `docker build .` — обрабатывается рекурсивно, включая все поддиректории.
2. **Git-репозиторий:** `docker build https://github.com/user/repo.git` — выполняется неглубокий клон (только HEAD), рекурсивно подтягиваются сабмодули.
3. **Удалённый тарбол:** `docker build https://example.com/context.tar.gz` — URL передаётся сборщику, скачивание выполняется на хосте, где работает BuildKit (при удалённом сборщике это **не** машина, с которой отправлена команда). Допустимое сжатие: `xz`, `bzip2`, `gzip`, `identity`.
4. **Тарбол через stdin:** `docker build - < context.tar.gz`; Dockerfile берётся из корня архива, либо указывается явно: `docker build --file build.Dockerfile - < context.tar.gz`.
5. **Dockerfile из stdin при сохранении контекста:** `docker build -f- .` — контекст берётся из `.`, Dockerfile читается из stdin.
6. **Текстовый файл (пустой контекст):** `docker build - < Dockerfile` либо URL на текстовый файл. Файлового контекста нет, `COPY` может работать только с `--from`.

### Git-контексты

Git-URL — самый недооценённый тип контекста: он снимает необходимость в локальном клонировании и позволяет собрать прямо из репозитория или его форка.

**Фрагменты URL** (формат `#ref:dir`) — исторический формат, работает, но для новых сборок предпочтительнее форма запросов:

| Суффикс | Используемый коммит | Используемый контекст |
| :--- | :--- | :--- |
| `myrepo.git` | `refs/heads/<ветка по умолчанию>` | `/` |
| `myrepo.git#mytag` | `refs/tags/mytag` | `/` |
| `myrepo.git#mybranch` | `refs/heads/mybranch` | `/` |
| `myrepo.git#pull/42/head` | `refs/pull/42/head` | `/` |
| `myrepo.git#master:myfolder` | `refs/heads/master` | `/myfolder` |

Хеш коммита в `ref` требует **полных 40 символов** SHA-1; короткий хеш не поддерживается.

**Параметры запроса** (рекомендуемый формат) позволяют задать тот же результат структурированно и, что важнее для CI, проверить, что разрешился ожидаемый коммит:

```bash
docker buildx build 'https://github.com/user/myrepo.git?branch=container&subdir=docker'

# Проверка коммита — сборка упадёт, если ref разрешится не в тот коммит
docker buildx build 'https://github.com/moby/buildkit.git?tag=v0.21.1&checksum=66735c67'
# → ERROR: expected checksum to match 66735c67, got bb41e835b6c3523c7c45b248cf4b45e7f862bc42
```

Поддерживаются `tag`, `branch`, `ref`, `subdir`, а также `checksum` (алиас `commit`). Короткий хеш допустим в `checksum`, но не в `ref`.

**Каталог `.git` по умолчанию не сохраняется** после клонирования. Если сборке нужны метаданные репозитория (номер ревизии, теги, `git describe`), включите их сохранение:

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
WORKDIR /src
RUN --mount=target=. \
  make REVISION=$(git rev-parse HEAD) build
```

```bash
docker build --build-arg BUILDKIT_CONTEXT_KEEP_GIT_DIR=1 https://github.com/user/repo.git#main
```

**Приватные репозитории.** Buildx сам подхватывает SSH-учётные данные, если адрес задан в SSH- или Git-форме; по умолчанию используется `$SSH_AUTH_SOCK`. Альтернатива — токен через `--secret`:

```bash
# SSH
docker buildx build --ssh default git@github.com:user/private.git

# Токен
GIT_AUTH_TOKEN=<token> docker buildx build \
  --secret id=GIT_AUTH_TOKEN \
  https://github.com/user/private.git
```

> **Важно:** токен передаётся только через `--secret`. Передача через `--build-arg` положит значение в историю сборки и в слои образа.

**Особенность прав доступа:** при использовании Git-репозитория как контекста биты доступа скопированных файлов принудительно выставляются в `644`, а каталогов — в `755` (исполняемый бит у файлов превращается в `755`). Это гарантия воспроизводимости, а не побочный эффект.

### Именованные контексты (Multi-context)

BuildKit позволяет подключать несколько независимых источников данных для одной сборки с помощью флага `--build-context`. Источники логически разделены и не смешиваются с контекстом по умолчанию.

Синтаксис CLI: `docker buildx build --build-context NAME=SOURCE .`
Использование в Dockerfile: `COPY --from=NAME /src /dest` и `RUN --mount=from=NAME,target=/dst`. В форме `RUN --mount` тип `bind` подставляется по умолчанию, поэтому `type=bind` указывать не обязательно — проверено сборкой с `--build-context alpine=docker-image://alpine:3.22`, где файл читался через `target`.

**Источники именованных контекстов:**

| Тип источника | Форма | Пример |
| :--- | :--- | :--- |
| Локальная директория | `NAME=./path` | `--build-context app=../myapp` |
| Docker-образ | `NAME=docker-image://REF` | `--build-context base=docker-image://alpine:3.22` |
| HTTP URL | `NAME=https://...` | `--build-context data=https://example.com/data.tar.gz` |
| Git-репозиторий | `NAME=https://...git#ref` | `--build-context repo=https://github.com/user/repo.git#main` |
| Другой Bake-таргет | `NAME=target:имя` | `--build-context mybase=target:base` (только в `docker buildx bake`) |

> **Важно:** префикс `docker-image://` **обязателен** для источника-образа. Без него `SOURCE` трактуется как путь в файловой системе, и сборка падает с ошибкой
> `ERROR: failed to build: failed to get build context base: stat alpine:3.22: no such file or directory`.
> Подробности — в разделе «[Разрешение проблем](#разрешение-проблем)».

**Ограничения и особенности:**

- Имя контекста не должно содержать пробелов и символов, недопустимых в ссылке на образ. Подчёркивание и цифры допустимы; проверка выполняется как разбор docker-ссылки, поэтому `my_ctx`, `app.v2` и `2app` проходят, а `my app` отклоняется.
- Именованный контекст адресуется **только** через `--from` в `COPY`/`ADD` и `from=` в `RUN --mount`. Обычная `COPY ./file /dst` всегда читает контекст по умолчанию.
- Стадия multi-stage не может быть подключена как именованный контекст — стадия уже является частью того же графа.
- Начиная с Dockerfile 1.11 `ONBUILD` допускает `COPY --from` и `RUN --mount=from=`; для именованного контекста он должен быть передан в последующую сборку.

### Файлы .dockerignore

#### Расположение и приоритет

При запуске сборки клиент ищет файл `.dockerignore` **в корне контекста**. Если Dockerfile вынесен в поддиректорию, корневой `.dockerignore` продолжает работать, но для него можно задать более точный аналог — Dockerfile-специфичный ignore-файл:

```text
.
├── index.ts
├── src/
├── docker
│   ├── build.Dockerfile
│   ├── build.Dockerfile.dockerignore   # применяется к build.Dockerfile
│   ├── lint.Dockerfile
│   ├── lint.Dockerfile.dockerignore
│   └── test.Dockerfile
├── package.json
└── package-lock.json
```

Правила именования: ignore-файл размещается **в том же каталоге, что и Dockerfile**, а его имя — это имя Dockerfile с суффиксом `.dockerignore`. **Dockerfile-специфичный ignore-файл имеет приоритет** над `.dockerignore` в корне контекста, если присутствуют оба.

Файл с именем `.dockerignore`, лежащий в поддиректории рядом с Dockerfile, **молча игнорируется** — ни ошибки, ни предупреждения не будет, а исключения просто не применятся. Это самая частая причина «`.dockerignore` не работает».

#### Синтаксис и правила сопоставления

Файл `.dockerignore` — список шаблонов, разделённых переводами строк, по правилам glob-оболочек Unix. Ведущие и завершающие слэши в шаблонах игнорируются, поэтому все четыре записи ниже исключают один и тот же объект `bar` внутри каталога `foo` в корне контекста:

```dockerignore
/foo/bar/
/foo/bar
foo/bar/
foo/bar
```

Сопоставление выполняется по правилам Go-функции [`filepath.Match`](https://golang.org/pkg/path/filepath#Match). Перед сопоставлением путь проходит через `filepath.Clean`, которая убирает пробелы, `.` и `..`; строки, ставшие пустыми после предобработки, игнорируются. Строка, начинающаяся с `#` в первом столбце, — комментарий.

> **Особенность:** по историческим причинам шаблон `.` игнорируется.

Docker дополнительно поддерживает специальный wildcard `**`, совпадающий с любым числом каталогов (включая ноль), — поэтому `**/*.go` исключает все `.go`-файлы на любой глубине.

Дополнительно применяется предобработка в стиле Git: суффикс `/` у каталога не влияет на сопоставление, а `\`-экранирование используется для литеральных `*` и `?`.

**Матрица поведения:**

| Правило | Поведение |
| :--- | :--- |
| `# comment` | Игнорируется. |
| `*/temp*` | Исключает файлы и каталоги, чьё имя начинается с `temp`, в любом непосредственном подкаталоге корня: `/somedir/temporary.txt` и `/somedir/temp`. |
| `*/*/temp*` | Исключает файлы и каталоги, начинающиеся с `temp`, в подкаталогах на два уровня ниже корня: `/somedir/subdir/temporary.txt`. |
| `temp?` | Исключает объекты в корне, чьё имя — `temp` с односимвольным расширением: `/tempa`, `/tempb`. |

#### Отрицания и порядок правил

Строка, начинающаяся с `!`, отменяет исключение. Поведение определяет **последняя** строка `.dockerignore`, совпавшая с конкретным файлом:

```dockerignore
*.md
!README*.md
README-secret.md
```

В контекст попадут все markdown-файлы, кроме `README-secret.md`. Обратный порядок даёт обратный результат:

```dockerignore
*.md
README-secret.md
!README*.md
```

Здесь все README-файлы включены — средняя строка не имеет эффекта, потому что `!README*.md` совпадает с `README-secret.md` и идёт последним.

**Ограничение области действия:** `*.md` исключает только markdown-файлы, лежащие непосредственно в корне контекста. Файлы в подкаталогах остаются включёнными — для рекурсивного исключения нужен `**/*.md`.

#### Dockerfile и .dockerignore не копируются в образ

В `.dockerignore` можно исключить сам `Dockerfile` и `.dockerignore`, и они действительно не попадут в копируемый набор — **но эти файлы всё равно отправляются сборщику**, поскольку необходимы для выполнения сборки. Из-за этого их невозможно скопировать в образ через `ADD`, `COPY` или bind mount. Это объясняет, почему правила `Dockerfile` и `.dockerignore` в `.dockerignore` безопасны и не приводят к ошибке `not found`.

### Исключения в инструкции COPY (--exclude)

Флаг `--exclude` в `COPY` (и в `ADD`) позволяет точечно исключать файлы, не меняя глобальный `.dockerignore`. **Требует Dockerfile syntax 1.19 или выше**; в канале `1.7-labs` он был экспериментальным, в стабильный вышел только в 1.19. Практический вывод: при указании `# syntax=docker/dockerfile:1` (тег стабильного канала) флаг доступен, а вот Dockerfile, закреплённый на `dockerfile:1.7-labs` или ниже, его не поддержит.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
WORKDIR /app
# Копируем всё, кроме тестов и временных файлов
COPY --exclude=tests/ --exclude=*.tmp . .
```

Флаг можно указывать многократно. Путь-выражение имеет тот же формат, что и `<src>`, поддерживает wildcards и сопоставляется по правилам Go-функции [`filepath.Match`](https://golang.org/pkg/path/filepath#Match):

```dockerfile
COPY --exclude=*.txt --exclude=*.md hom* /mydir/
```

Сопоставление `--exclude` идёт **по полному пути относительно контекста**, поэтому `COPY --exclude=*.tmp . .` не исключит `build/output.tmp` — для этого нужен шаблон `**/*.tmp` либо явное указание подкаталога. Кроме того, флаг **не подставляется через переменную**: `ARG EX="--exclude=a"` с `COPY "$EX" . .` не работает, так как переменные не раскрываются через границы аргументов и флагов.

**Отличие от `.dockerignore`:**

| Параметр | `.dockerignore` | `COPY --exclude` |
| :--- | :--- | :--- |
| **Область действия** | Глобально (весь контекст) | Только конкретная инструкция `COPY`/`ADD` |
| **Синтаксис** | Шаблоны glob + `**` + отрицания `!` | Шаблоны `filepath.Match` (без `**`, без `!`) |
| **Сопоставление** | По путям и именам каталогов | По полному пути относительно контекста |
| **Применяется к** | Всем инструкциям `COPY`/`ADD` | Одной инструкции |
| **Минимальная версия** | Docker 1.7+ | Dockerfile syntax 1.19 |

### Сохранение иерархии каталогов (--parents)

Смежная с `--exclude` возможность, доступная с Dockerfile syntax **1.20**: флаг `--parents` сохраняет родительские каталоги для перечисленных источников. Поведение аналогично `cp --parents` и `rsync --relative`. По умолчанию флаг выключен.

```dockerfile
# syntax=docker/dockerfile:1
FROM scratch

COPY ./x/a.txt ./y/a.txt /parents/
# /parents/x/a.txt
# /parents/y/a.txt
```

Ограничить глубину сохраняемых родительских каталогов можно вставкой `./` в путь-источник — сохраняются только каталоги после неё. Wildcard `**` совпадает с любым числом компонентов пути, включая ноль:

```dockerfile
COPY --parents ./src/**/*.txt /parents/
```

Практическая ценность для CI: несколько `COPY` из разных подкаталогов можно упаковать одним слоем, сохранив структуру, вместо того чтобы заводить слой на каждый источник.

### Аргументы сборки BuildKit

Это **встроенные build args**, а не переменные окружения оболочки. Они доступны внутри Dockerfile после объявления `ARG` и не попадают в образ, если не объявлены как `ENV`. Полный список:

| Аргумент | Тип | Назначение |
| :--- | :--- | :--- |
| `BUILDKIT_BUILD_NAME` | String | Переопределяет имя сборки в `buildx history` и в Docker Desktop Builds view. |
| `BUILDKIT_CACHE_MOUNT_NS` | String | Пространство имён (namespace) для ID cache mounts — изолирует кэш между параллельными пайплайнами. |
| `BUILDKIT_CONTEXT_KEEP_GIT_DIR` | Bool | Сохранять каталог `.git` при использовании Git-контекста. |
| `BUILDKIT_GIT_ADVICE` | Bool | Показывать advisory-сообщения Git-операций под управлением BuildKit. По умолчанию `false`. |
| `BUILDKIT_INLINE_CACHE` | Bool | Встраивать метаданные кэша в конфигурацию образа. |
| `BUILDKIT_MULTI_PLATFORM` | Bool | Детерминированный вывод независимо от мультиплатформенной сборки. |
| `BUILDKIT_SANDBOX_HOSTNAME` | String | Имя хоста внутри sandbox-контейнера (по умолчанию `buildkitsandbox`). |
| `BUILDKIT_SYNTAX` | String | Образ фронтенда. Значение `dockerfile.v0` заставляет игнорировать директиву `# syntax=` в Dockerfile и использовать встроенный фронтенд. |
| `SOURCE_DATE_EPOCH` | Int | Временная метка Unix для создаваемых образов и слоёв — база воспроизводимых сборок. Поддерживается с Dockerfile 1.5, BuildKit 0.11. |

`SOURCE_DATE_EPOCH` стоит задавать в CI явным значением, привязанным к коммиту: без него две сборки одного и того же коммита дают разные хеши, и проверка воспроизводимости становится невозможной.

### Переменные окружения клиента и сборщика

В отличие от build args, эти переменные задаются в окружении процесса и не требуют объявления `ARG` в Dockerfile.

| Переменная | Где задаётся | Назначение |
| :--- | :--- | :--- |
| `DOCKER_BUILDKIT` | Клиент | `1` — использовать BuildKit, `0` — отключить. С Docker 23.0 BuildKit является сборщиком по умолчанию, поэтому переменную задают только для принудительного отключения. |
| `BUILDKIT_PROGRESS` | Клиент | Формат прогресса: `auto`, `plain`, `tty` (по умолчанию `auto`). |
| `BUILDKIT_COLORS` | Клиент | Настройка цветов вывода. Имеет более низкий приоритет, чем `NO_COLOR`. |
| `NO_COLOR` | Клиент | Если переменная установлена, ANSI-последовательности не выводятся вовсе (согласно https://no-color.org/). |
| `BUILDKIT_HOST` | Клиент | Адрес удалённого `buildkitd` для `buildctl` (например, `tcp://localhost:1234`). |
| `BUILDKIT_STEP_LOG_MAX_SIZE` | **Демон** `buildkitd` | Максимальный размер лога одного шага в байтах. По умолчанию `2097152` (2 МиБ); значение `-1` снимает ограничение. |
| `BUILDKIT_STEP_LOG_MAX_SPEED` | **Демон** `buildkitd` | Максимальная скорость вывода лога шага в байтах в секунду. По умолчанию `204800`; значение `-1` снимает ограничение. |

> **Важно:** `BUILDKIT_STEP_LOG_MAX_SIZE` и `BUILDKIT_STEP_LOG_MAX_SPEED` — это переменные **демона** `buildkitd`, а не клиента. Задать их на конкретный сборщик можно только при его создании:
>
> ```bash
> docker buildx create --bootstrap --use --name biglog \
>   --driver-opt env.BUILDKIT_STEP_LOG_MAX_SIZE=-1 \
>   --driver-opt env.BUILDKIT_STEP_LOG_MAX_SPEED=-1
> ```
>
> Экспорт в окружение оболочки на хосте на них не подействует. Ограничения в 2 МиБ и 200 КиБ/с вычисляются в `util/progress/logs/logs.go` и применяются к обрезанному выводу шага; типичное проявление в CI — длинные логи `npm install` или `go mod download`, обрывающиеся сообщением о превышении лимита.

## Практические сценарии

### Сценарий 1: Расположение Dockerfile вне корня проекта

Если `Dockerfile` находится в поддиректории, важно правильно указать путь к файлу (`-f`) и путь к контексту (обычно корень проекта):

```bash
# Выполняется из корня проекта
docker build -f deployment/docker/Dockerfile .
```

`.dockerignore` в корне контекста (`./.dockerignore`) при этом продолжает работать — наличие `-f` его не отключает. Если правила для этого Dockerfile должны отличаться от общих, добавьте `deployment/docker/Dockerfile.dockerignore`: он имеет приоритет над корневым.

### Сценарий 2: Исключение файлов напрямую в Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24
WORKDIR /app
# Копируем всё, кроме тестов и временных файлов
COPY --exclude=tests/ --exclude=**/*.tmp . .
```

`# syntax=docker/dockerfile:1` здесь обязателен: без неё будет использован встроенный фронтенд версии, соответствующей вашему BuildKit, и на версиях младше 1.19 сборка упадёт на неизвестном флаге.

### Сценарий 3: Переопределение базового образа именованным контекстом

Позволяет подставить локальную директорию или другой образ вместо внешнего, не меняя Dockerfile:

```bash
# Локальная директория вместо удалённой зависимости
docker buildx build --build-context app=../common-lib -t app:dev .

# Другой образ вместо Alpine в FROM alpine:3.24
docker buildx build --build-context alpine:3.24=docker-image://alpine:edge -t app:dev .
```

Dockerfile при этом остаётся без изменений — ссылка на образ в `FROM` или `COPY --from` разрешается через именованный контекст.

### Сценарий 4: Оптимальный .dockerignore для DevOps/SRE

Пример файла, предотвращающего утечку секретов и ускоряющего сборку за счёт исключения тяжёлых зависимостей и Git-истории.

```dockerignore
# Системные папки
.git
.github
.gitignore

# Зависимости (должны ставиться внутри Dockerfile)
node_modules/
vendor/
.venv/
__pycache__/

# Секреты и локальные конфиги
.env
*.pem
*.key
secrets/
.docker/
.gnupg/
.netrc

# Логи и временные файлы
*.log
tmp/
.cache/

# Артефакты сборки
dist/
build/
target/

# Файлы инфраструктуры
# Эти два правила безопасны: файлы не попадут в COPY, но останутся
# доступными сборщику, поэтому ошибки "not found" не будет.
Dockerfile
.dockerignore
compose.yaml
```

### Сценарий 5: Паттерны исключений и рекурсивность

```dockerignore
# Только markdown-файлы в корне контекста
*.md

# Все markdown-файлы рекурсивно
**/*.md

# Исключить все .md, кроме README.md в корне
*.md
!README.md

# Исключить каталог src/tests, но оставить в нём один файл
src/tests/
!src/tests/*.keep

# Исключить все файлы .pyc любым способом
**/__pycache__/
*.pyc
```

Обратите внимание на строку `src/tests/` рядом с `!src/tests/*.keep`: отрицание внутри исключённого каталога работает, потому что правила применяются последовательно, а решение принимает последнее совпавшее правило. Если после отрицания вы добавите ещё одно исключение для того же пути — оно снова перекроет включение.

**Проверка исключений:**

```bash
# Передаваемый объём контекста виден в выводе сборки BuildKit
docker build --progress=plain . 2>&1 | grep "transferring"
# → #8 transferring context: 319B done

# Проверить конкретный файл: он обязан отсутствовать в выводе RUN
docker build --no-cache --progress=plain . 2>&1 | grep -A2 "not found"
```

### Сценарий 6: Контекст по умолчанию общий для всех стадий multi-stage

**Уточнение терминологии:** отдельного контекста у стадии нет. Все стадии одного Dockerfile используют **один и тот же** контекст сборки и один и тот же `.dockerignore`. Изоляция обеспечивается не контекстом, а файловой системой стадии: то, что не скопировано через `COPY --from=builder`, на следующей стадии физически отсутствует.

```dockerfile
# syntax=docker/dockerfile:1
# Стадия 1: Сборка (полный контекст)
FROM golang:1.24-alpine AS builder
WORKDIR /app
# ВСЕ файлы проекта доступны на этой стадии
COPY . .
RUN go build -o /bin/app .

# Стадия 2: Runtime (минимальный образ)
FROM alpine:3.24
# Только скомпилированный бинарник
COPY --from=builder /bin/app /usr/local/bin/app
ENTRYPOINT ["app"]
```

**Важно:** инструкция `COPY` на стадии 2 не может обращаться к файлам исходного проекта напрямую — только к тому, что попало в образ предыдущей стадии, то есть через `COPY --from=builder`.

### Сценарий 7: Доступ к приватным Git-репозиториям через SSH

Клонирование приватного репозитория в контейнере с использованием SSH-агента хоста. Такой подход предпочтительнее `ADD` по SSH-URL: ключ не попадает в слой, а сокет агента живёт только на время шага.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24
RUN apk add --no-cache git openssh-client
RUN --mount=type=ssh \
    mkdir -p -m 0700 /root/.ssh && \
    ssh-keyscan gitlab.com >> /root/.ssh/known_hosts && \
    git clone --depth 1 git@gitlab.com:group/private.git /app
WORKDIR /app
CMD ["sh"]
```

```bash
# Запуск сборки с пробросом SSH-агента
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
docker buildx build --ssh default=$SSH_AUTH_SOCK -t app:latest .
```

`ssh-keyscan` в этом примере не обязателен, но избавляет от интерактивного запроса подтверждения ключа хоста внутри неинтерактивной сборки. Ограничение сокета: путь к `.pem`-файлу с паролем на сокете агента не работает — BuildKit поддерживает либо агента, либо pem без пароля.

### Сценарий 8: Контекст в конфигурации Docker Bake

При использовании `docker buildx bake` контекст по умолчанию задаётся полем `context`, а именованные контексты — полем `contexts`.

```hcl
# docker-bake.hcl
variable "APP_VERSION" {
  default = "1.0.0"
}

group "default" {
  targets = ["app", "worker"]
}

target "app" {
  context    = "../app"
  dockerfile = "Dockerfile"
  contexts = {
    docs = "./docs"
  }
  args = {
    VERSION = APP_VERSION
  }
}

target "worker" {
  context    = "../worker"
  dockerfile = "Dockerfile"
}
```

```bash
# Сборка всех целей из bake-файла
docker buildx bake

# Переопределение контекста конкретной цели
docker buildx bake app --set app.context=../app-v2
```

Полная декларация — в разделе «[Docker Bake: Декларативная оркестрация сборки](./docker-bake.md)».

## Валидация и проверка

### Проверка конфигурации сборки без её выполнения

Build checks — механизм lint-проверок Dockerfile и параметров сборки, появившийся в Dockerfile 1.8 (требует Buildx 0.15.0 и новее). По умолчанию проверки выполняются в ходе обычной сборки и выдают предупреждения, не прерывая её; `docker build --check` запускает только проверки и возвращает ненулевой код возврата при нарушениях.

```bash
docker build --check .
```

```text
WARNING: JSONArgsRecommended - https://docs.docker.com/go/dockerfile/rule/json-args-recommended/
JSON arguments recommended for ENTRYPOINT/CMD to prevent unintended behavior related to OS signals
Dockerfile:2
--------------------
   1 |     FROM alpine:3.24
   2 | >>> CMD echo "hi"
   3 |
--------------------
```

Поведение настраивается директивой `check` (Dockerfile 1.8+) или build arg `BUILDKIT_DOCKERFILE_CHECK`:

```dockerfile
# syntax=docker/dockerfile:1
# check=skip=JSONArgsRecommended,StageNameCasing;error=true

FROM alpine:3.24
CMD echo "hi"
```

```bash
# То же с CLI, без правки Dockerfile
docker build --check --build-arg "BUILDKIT_DOCKERFILE_CHECK=error=true" .

# Пропустить отдельные проверки
docker build --check --build-arg "BUILDKIT_DOCKERFILE_CHECK=skip=JSONArgsRecommended" .

# Включить экспериментальные проверки
docker build --check --build-arg "BUILDKIT_DOCKERFILE_CHECK=experimental=all" .
```

Директива `experimental` имеет приоритет над `skip`: при `skip=all;experimental=all` экспериментальные проверки всё равно выполнятся. При использовании `error=true` рекомендуется закреплять конкретную версию `# syntax=`, иначе сборка может внезапно начать падать после выхода новых проверок.

### Проверка размера контекста

```bash
# Объём контекста в выводе BuildKit — основной индикатор качества .dockerignore
docker build --progress=plain . 2>&1 | grep "transferring context"
# → #8 transferring context: 319B done

# Объём на диске без учёта исключений (верхняя граница, до сборки)
du -sh .
# → 45M    .

# Количество файлов в контексте
find . -type f | wc -l
# → 1247
```

> **Важно:** `tar` **не** применяет `.dockerignore`. Распространённая, но неверная проверка вида
> `tar cf - . | tar tf - | grep -v "$(cat .dockerignore | tr '\n' '|')"`
> перечисляет файлы по шаблонам `grep`, а не по правилам `filepath.Match`, и выдаёт результат, не имеющий отношения к тому, что реально уходит сборщику. Единственный достоверный источник — вывод `transferring context` и содержимое, проконтролированное через `RUN` внутри сборки.

### Проверка .dockerignore

Встроенной команды валидации `.dockerignore` не существует, но результат можно проверить двумя надёжными способами.

Способ 1 — сравнить объём контекста до и после исключения:

```bash
docker build --progress=plain . 2>&1 | grep "transferring context"
# → #5 transferring context: 4.257kB done

# добавить исключение тяжёлого каталога
printf 'node_modules\n' >> .dockerignore

docker build --progress=plain . 2>&1 | grep "transferring context"
# → #5 transferring context: 96B done
```

Способ 2 — проверить фактическое содержимое внутри образа, добавив проверочный слой:

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24
WORKDIR /app
COPY . .
RUN ls -a /app | sort | tee /tmp/files
```

```bash
docker build --no-cache --progress=plain -t ctxcheck . 2>&1 | grep -A20 "^ *[0-9.]* .env\|RUN ls"
```

Способ 3 — проверить, что файл действительно недоступен, отдельной целевой проверкой:

```bash
# Ожидаемая ошибка: файл исключён, поэтому COPY его не найдёт
docker build --no-cache -f /dev/stdin . <<'EOF'
# syntax=docker/dockerfile:1
FROM alpine:3.24
COPY .env /x
EOF
# → ERROR: failed to solve: failed to compute cache key: ... "/.env": not found
```

### Проверка количества слоёв и размера

```bash
# Просмотр размера каждого слоя
docker history myimage:latest
# → IMAGE          CREATED        CREATED BY                                      SIZE
# → ...            ...           COPY . . (dockerfile:15)                        42.1MB

# Сравнение размеров ДО и ПОСЛЕ оптимизации .dockerignore
# До (без .dockerignore):
docker history myimage:latest | head -3
# → ... COPY . .    42.1MB

# После (с .dockerignore):
docker history myimage:latest | head -3
# → ... COPY . .    8.3MB
```

## Разрешение проблем

### Типичные ошибки

**1. `failed to solve: failed to compute cache key: failed to calculate checksum of ref ...: "/file": not found`**

Причина: файл исключён через `.dockerignore`, отсутствует в контексте или указан неверный путь. Это текущее сообщение BuildKit; формулировка `COPY failed: file not found in build context or excluded by .dockerignore` относится к Legacy Builder и в актуальных версиях не встречается.

Решение:

```bash
# Проверка наличия файла в контексте
ls -la my-file.txt

# Проверка .dockerignore
cat .dockerignore | grep "my-file"

# Проверка, какой ignore-файл реально применяется
ls -la .dockerignore Dockerfile.dockerignore
# → Dockerfile.dockerignore имеет приоритет, если Dockerfile лежит в корне контекста

# Проверить содержимое контекста изнутри сборки (надёжнее, чем анализ вывода)
docker build --no-cache --progress=plain . 2>&1 | grep -E "transferring context|ls -a"
```

Если файл исключён намеренно, а `COPY` к нему всё равно обращается, решение — убрать этот `COPY` или заменить его на `COPY --exclude`, исключив лишнее явно.

**2. `failed to solve with frontend dockerfile.v0: failed to create LLB definition`**

Причина: неверный синтаксис Dockerfile либо отсутствие директивы `# syntax` при использовании флагов, требующих конкретной версии фронтенда.

Решение:

```dockerfile
# Добавьте директиву в самое начало Dockerfile
# syntax=docker/dockerfile:1

FROM alpine:3.24
# ... остальной контент
```

**3. `failed to build: failed to get build context NAME: stat IMAGE: no such file or directory`**

Причина: для источника-образа не указан префикс `docker-image://`. Без него значение трактуется как путь в файловой системе.

Решение:

```bash
# Неправильно: трактуется как локальный путь
docker buildx build --build-context base=alpine:3.22 .

# Правильно
docker buildx build --build-context base=docker-image://alpine:3.22 .
```

**4. `invalid context name NAME: invalid reference format`**

Причина: имя именованного контекста содержит символы, недопустимые в docker-ссылке, — как правило, пробел.

Решение:

```bash
# Проходят проверку: дефис, подчёркивание, точка, цифры
docker buildx build --build-context my-ctx=../myapp .
docker buildx build --build-context my_ctx=../myapp .
docker buildx build --build-context app.v2=../app .
docker buildx build --build-context 2app=../app .

# Отклоняется: пробел
docker buildx build --build-context "my app=../myapp" .
# → ERROR: invalid context name my app: invalid reference format
```

**5. `.dockerignore` не исключает файлы, хотя находится рядом с Dockerfile**

Симптом: правила записаны, но объём контекста не меняется. Такой ошибки, как `error: .dockerignore must be in the build context root`, в BuildKit нет — проблема диагностируется по симптому.

Причины и решения:

```bash
# Причина 1: файл лежит в поддиректории, а не в корне контекста, и назван
# просто ".dockerignore" — он молча игнорируется
find . -name ".dockerignore"
# → ./.dockerignore            (применяется)
# → ./docker/.dockerignore     (игнорируется)

# Решение: Dockerfile-специфичный файл рядом с Dockerfile
mv docker/.dockerignore docker/Dockerfile.dockerignore

# Причина 2: правило слишком узкое и не покрывает подкаталоги
cat .dockerignore
# → node_modules     (только корневой каталог)
# Правильно для рекурсии:
# → **/node_modules
```

**6. `error: failed to solve: failed to compute cache key` после `COPY` одиночного файла**

Причина: `COPY` указывает на путь, не существующий в контексте (в том числе исключённый `.dockerignore`), либо на пустую директорию. Если путь может отсутствовать в разных ветках репозитория, разделите копирование на шаги, чтобы слой с зависимостями кэшировался независимо:

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24
WORKDIR /app
# Сначала манифесты — этот слой кэшируется независимо
COPY package*.json ./
RUN npm install
COPY . .
```

**7. Текстовый файл передан как контекст, `COPY` не находит файлы**

Причина: `docker build - < Dockerfile` создаёт сборку **без файлового контекста**, поэтому доступны только стадии, образы и именованные контексты.

Решение:

```bash
# Сохранить контекст, читая Dockerfile из stdin
docker build -f- . < Dockerfile

# Передать tar-архив целиком
docker build - < context.tar.gz
```

### Диагностические команды

```bash
# Объём контекста, который реально уходит сборщику
docker build --progress=plain . 2>&1 | grep "transferring context"

# Объём на диске и количество файлов без учёта исключений
du -sh .
find . -type f | wc -l

# Какие ignore-файлы присутствуют
find . -name "*.dockerignore" -o -name ".dockerignore"

# Просмотр .dockerignore
cat .dockerignore

# Проверка конфигурации без сборки
docker build --check .

# Подробный вывод проверок
docker --debug build --check .

# Размер каждого слоя
docker history myimage:latest

# Поиск потенциальных секретов среди файлов контекста
find . -type f \( -name ".env*" -o -name "*.pem" -o -name "*.key" -o -name "id_rsa*" \) \
    -not -path "./.git/*"

# Анализ состава и размера образа
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  wagoodman/dive myimage:latest
```

## Лучшие практики

### Стратегия «исключить всё, включить нужное»

Наиболее надёжный способ не пропустить новый тип артефактов: запретить контекст целиком и разрешить явно необходимое. Порядок правил имеет значение — сначала запрет, затем разрешения.

```dockerignore
# 1. Запрещаем всё
*

# 2. Разрешаем нужное
!src/
!package.json
!package-lock.json
!Dockerfile
!.dockerignore

# 3. Затем исключаем внутри разрешённого
src/**/*.test.js
src/**/*.spec.js
src/tests/

# 4. Системные файлы
.git
.github
.vscode
.idea

# 5. Зависимости
node_modules/
vendor/
.venv/

# 6. Секреты
.env
*.pem
*.key
secrets/
```

> **Осторожно с правилом `*`:** оно исключает и сам Dockerfile с `.dockerignore`. Как показано выше, на сборку это не влияет, но нужно помнить, что точечные разрешения (`!src/`) не отменяют правила, записанные **позже**: если `src/tests/` идёт после `!src/`, тесты останутся исключёнными.

### Рекомендации

1. **Всегда создавайте `.dockerignore`**, даже для простых проектов: это предотвращает утечку секретов и ускоряет сборку.
2. **Закрепляйте версию фронтенда** директивой `# syntax=docker/dockerfile:1` — она тянет последнюю стабильную версию и избавляет от привязки к версии BuildKit. В CI, где нужна полная воспроизводимость, указывайте конкретный минор (`1.27`) или закрепляйте образ по дайджесту.
3. **Минимизируйте контекст** — исключайте `.git`, `node_modules`, логи, артефакты сборки. Для удалённых сборщиков это прямое сокращение сетевого трафика.
4. **Изменение `.dockerignore` инвалидирует кэш слоя `COPY`.** Правка правил — не безобидная операция: она вызывает пересборку всех последующих слоёв, зависящих от `COPY`. Вносите её отдельным коммитом, чтобы облегчить откат и анализ причин ломающихся сборок.
5. **Для больших проектов** используйте `--build-context`, чтобы не раздувать контекст по умолчанию, и `--exclude` для точечных исключений без изменения глобальных правил.
6. **Не передавайте секреты через контекст и `--build-arg`** — используйте `--secret` (см. раздел «Безопасность»).
7. **Проверяйте объём контекста** перед сборкой в CI: сравнение значения `transferring context` с ожидаемым порогом ловит регрессии, которые иначе проявятся только как рост времени раннера.
8. **Пропускайте `docker build --check` в пайплайне** — это самая дешёвая проверка конфигурации, не требующая исполнения слоёв.
9. **Задавайте `SOURCE_DATE_EPOCH`** для воспроизводимых сборок.

### Очистка

```bash
# Удаление неиспользуемых образов
docker image prune -a

# Удаление неиспользуемых контейнеров
docker container prune

# Полная очистка (включая volumes и кэш сборки)
docker system prune -a --volumes

# Проверка использования диска
docker system df
# → TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# → Images          15        3         4.2GB     3.1GB (73%)
# → Containers      5         2         150MB     100MB (66%)

# Кэш сборки — отдельная сущность, очищается вместе с prune
docker builder prune
```

## Известные проблемы и ограничения

### Ограничения

- **Нет верхнего предела размера контекста.** Ни клиент, ни демон не ограничивают объём передаваемых данных; единственный механизм ограничения — `.dockerignore` и разделение сборки на несколько целей с собственными контекстами.
- **Размер лога шага.** Демон `buildkitd` обрезает вывод шага до 2 МиБ и 200 КиБ/с по умолчанию. Для тяжёлых шагов (`npm ci`, `go mod download`, компиляция C++) увеличивайте лимиты через `--driver-opt env.BUILDKIT_STEP_LOG_MAX_SIZE=...` при создании сборщика.
- **Git-контекст загружается целиком.** Неглубокий клон берёт только HEAD, но размер распакованного дерева ничем не ограничен; для крупных монорепозиториев выгоднее локальная директория с собственным `.dockerignore` либо подкаталог через `subdir=`.
- **Сборка Windows-контейнеров по умолчанию использует Legacy Builder**, где сообщение о контексте выглядит как `Sending build context to Docker daemon 3.072 kB`, а не `transferring context`. Проверки на основе второго формата к Windows-контейнерам неприменимы. Экспериментальная поддержка Windows-контейнеров в BuildKit появилась в v0.13, но `docker build` на Windows по-прежнему переключается на Legacy Builder — [`docs.docker.com/build/buildkit`](https://docs.docker.com/build/buildkit) прямо оговаривает это ограничение.
- **Пути и разделители.** Ведущий слэш и `../` в путях `COPY`/`ADD` молча удаляются, а завершающий слэш игнорируется. Это сделано ради совместимости и является источником неочевидных ошибок при переносе Dockerfile между Linux и Windows.
- **`.dockerignore` в поддиректории не действует** — без специального Dockerfile-специфичного имени файл игнорируется молча.
- **Шаблон `.` игнорируется** — по историческим причинам он не исключает весь контекст.

## Безопасность

### Утечка секретов через контекст сборки

Контекст сборки передаётся сборщику, а при использовании удалённого сборщика — по сети. Если в контексте находятся секреты, они будут доступны сборщику и могут попасть в слои образа.

**Риски:**
- `.env` файлы с ключами API
- Приватные SSH-ключи
- Сертификаты и токены
- Файлы конфигурации с паролями
- Локальные каталоги конфигурации инструментов, хранящие учётные данные (`.docker/`, `.gnupg/`, `.netrc`)

**Защита:**

```dockerignore
# ВСЕГДА исключайте секреты
.env
.env.*
!.env.example
*.pem
*.key
*.p12
secrets/
.docker/
.gnupg/
.netrc
.id_rsa*
```

Директива `!.env.example` оставляет в контексте шаблон с заведомо нерабочими значениями — так он остаётся доступным для `COPY`, а реальный `.env` исключается. Порядок правил снова имеет значение: отрицание должно идти **после** общего исключения.

> **Важно:** исключение секрета из контекста — необходимое, но не достаточное условие. Секрет, попавший в слой ранее, остаётся в образе даже после того, как его начали исключать, поскольку слои неизменяемы. Сборку образа, в который попал секрет, следует считать скомпрометированной: исправление требует пересборки, а не «зачистки».

### Безопасная передача секретов в контексте

Для передачи секретов используйте **BuildKit secrets**, а не контекст сборки:

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24
# Секрет НЕ попадает в слой образа
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm install
```

```bash
# Передача секрета через файл
docker buildx build --secret id=npmrc,src=$HOME/.npmrc .

# Передача секрета через переменную окружения
docker buildx build --secret id=API_KEY,env=API_KEY .
```

Опция `env` (Dockerfile 1.10+) монтирует значение как переменную окружения вместо файла. Флаг `required=true` заставляет сборку завершиться ошибкой, если секрет не передан, — полезно, чтобы пропуск секрета не превращался в тихую нерабочую сборку.

Аналогично устроен `--ssh` для доступа к приватным Git-репозиториям: сокет агента доступен только на время конкретного шага.

### Проверка контекста на утечки

```bash
# Поиск потенциальных секретов среди файлов проекта
find . -type f \( -name ".env*" -o -name "*.pem" -o -name "*.key" \
    -o -name "id_rsa*" -o -iname "*secret*" -o -iname "*token*" \) \
    -not -path "./.git/*"

# Проверка, что исключённый секрет действительно недоступен внутри образа
docker build --no-cache -f /dev/stdin . <<'EOF'
# syntax=docker/dockerfile:1
FROM alpine:3.24
COPY . ./
EOF
docker run --rm ctxcheck:latest ls -a /

# Проверка слоёв на наличие подозрительных инструкций COPY/ADD
docker history myimage:latest --no-trunc | grep -iE "COPY|ADD"
# Просмотрите, какие именно источники копируются, и убедитесь, что среди них нет секретов

# Сканирование итогового образа известными инструментами
docker scout cves myimage:latest
trivy image myimage:latest --scanners secret
```

## См. также

- **[Инструкции COPY и ADD](./Instructions/copying_files.md)** — механизмы импорта данных, флаги `--from`, `--link`, `--chmod`.
- **[BuildKit: Техническое устройство](./dockerfile_buildkit.md)** — детали работы LLB, фронтендов, кэша и GC.
- **[Docker Buildx: Мультиплатформенная сборка](./docker_buildx.md)** — полный справочник флагов `docker buildx build`.
- **[Docker Bake: Декларативная оркестрация сборки](./docker-bake.md)** — конфигурация контекстов и целей в HCL.
- **[Сборка образов: лучшие практики](./Docker_best_practices/security.md)** — общий чек-лист безопасности сборки, включая работу с `.dockerignore`.
- **[Git: правила исключения файлов](../../Git/git_ignore.md)** — сопоставление синтаксиса `.gitignore` и `.dockerignore`.
- **[Docker Context для удалённого управления](../docker_context.md)** — не путать с build context: это подключение к удалённому Docker-демону.
