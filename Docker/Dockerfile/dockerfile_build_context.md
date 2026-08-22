# Контекст сборки Docker и .dockerignore

## Определения

**Контекст сборки (Build Context)** — это совокупность файлов и директорий, которые становятся доступными для инструкций `COPY` и `ADD` в процессе создания образа. При запуске сборки Docker-клиент упаковывает содержимое указанного пути и передает его сборщику (BuildKit или Docker Daemon).

**`.dockerignore`** — файл конфигурации в корне контекста сборки, определяющий список исключений. Файлы, подходящие под паттерны в `.dockerignore`, не упаковываются и не передаются сборщику, что критично для производительности и безопасности.

### Связь с Copy Instruction

Инструкции `COPY` и `ADD` в Dockerfile могут обращаться **только** к файлам, находящимся в контексте сборки. Если файл исключён через `.dockerignore` или не находится в указанном пути — инструкция `COPY` завершится ошибкой. Контекст сборки — это единственный канал передачи файлов от хоста в образ.

## Предварительные требования

### Программное обеспечение

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Docker Engine** | 18.09 (BuildKit) | 23.0+ | Legacy Builder работает с 1.0, но не рекомендуется |
| **docker buildx** | 0.10+ | 0.15+ | Для `--build-context`, `--exclude`, кэширования |
| **Dockerfile syntax** | 1.7+ | 1.9+ | Для `# syntax=docker/dockerfile:1` и расширенных фич |

### Проверка работоспособности

```bash
# Проверка версии Docker
docker version --format '{{.Server.Version}}'
# -> 27.x.x

# Проверка доступности BuildKit
docker buildx version
# -> github.com/docker/buildx v0.15.x ...

# Быстрая проверка контекста (вывод размера)
docker build . 2>&1 | head -5
# -> [+] Building 0.1s (2/2) FINISHED
```

## Базовые концепции

### Механизм передачи контекста

В классическом Docker (Legacy Builder) весь контекст упаковывался в tar-архив и отправлялся демону. В современном **BuildKit** процесс оптимизирован:
- **Инкрементальная передача:** BuildKit передает только те файлы, которые изменились с момента последней сборки.
- **Селективная передача:** Сборщик запрашивает у клиента только те файлы, которые непосредственно используются в инструкциях `COPY` или `ADD`, вместо загрузки всего контекста целиком.

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

1.  **Локальная директория:** `docker build .`
2.  **Git-репозиторий:** `docker build https://github.com/user/repo.git#branch` (Docker сам клонирует репозиторий).
3.  **Удаленный тарбол:** `docker build https://example.com/context.tar.gz`
4.  **Стандартный ввод (STDIN):** `docker build - < context.tar.gz`

### Переменные окружения BuildKit

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `DOCKER_BUILDKIT` | Принудительное включение BuildKit (deprecated, игнорируется в Docker 23+) | `DOCKER_BUILDKIT=1` |
| `BUILDKIT_COLORS` | Цвета вывода (auto/always/never) | `BUILDKIT_COLORS=always` |
| `DOCKER_BUILD_EXPERIMENTAL` | Включение экспериментальных фич BuildKit | `DOCKER_BUILD_EXPERIMENTAL=1` |
| `BUILDKIT_STEP_LOG_MAX_SIZE` | Максимальный размер лога шага (байты, default: 2097152) | `BUILDKIT_STEP_LOG_MAX_SIZE=4194304` |
| `BUILDKIT_STEP_LOG_MAX_SPEED` | Максимальная скорость вывода (байты/сек) | `BUILDKIT_STEP_LOG_MAX_SPEED=1048576` |

### Флаги Docker CLI для контекста

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-f`, `--file` | Путь к Dockerfile (относительно контекста) | `docker build -f build/Dockerfile .` |
| `--build-arg` | Передача переменных в Dockerfile | `docker build --build-arg VERSION=1.0 .` |
| `--build-context` | Именованный контекст BuildKit | `docker build --build-context app=../src .` |
| `--target` | Сборка до определённой стадии | `docker build --target builder .` |
| `--no-cache` | Отключение кэша | `docker build --no-cache .` |
| `--platform` | Целевая платформа | `docker build --platform linux/arm64 .` |
| `--ssh` | Доступ к SSH-агенту | `docker build --ssh default=$SSH_AUTH_SOCK .` |

### Именованные контексты (Multi-context)

BuildKit позволяет подключать несколько независимых источников данных для одной сборки с помощью флага `--build-context`. Это позволяет объединять файлы из разных директорий или даже разных образов без их предварительного копирования.

Синтаксис: `docker build --build-context name=path .`
В Dockerfile: `COPY --from=name /src /dest`

**Источники именованных контекстов:**
- Локальная директория: `--build-context app=../myapp`
- Docker-образ: `--build-context base=docker.io/library/python:3.12-slim`
- HTTP URL: `--build-context data=https://example.com/data.tar.gz`
- Git-репозиторий: `--build-context repo=https://github.com/user/repo.git#branch`

**Ограничения именованных контекстов:**
- Имена контекстов не могут совпадать с именами стадий (`builder`, `runtime` и т.д.)
- Стадия multi-stage не может быть использована как именованный контекст
- Доступны только из инструкций `COPY --from=name`

### Исключения в инструкции COPY (--exclude)

Начиная с Dockerfile Syntax 1.7+, можно использовать флаг `--exclude` в инструкции `COPY` для точечного исключения файлов без изменения глобального `.dockerignore`:

```dockerfile
# syntax=docker/dockerfile:1
COPY --exclude=tests/ --exclude=*.tmp . .
```

**Отличие от `.dockerignore`:**

| Параметр | `.dockerignore` | `COPY --exclude` |
| :--- | :--- | :--- |
| **Область действия** | Глобально (весь контекст) | Только конкретная инструкция COPY |
| **Уровень гранулярности** | Файл/директория | Шаблоны с glob-синтаксисом |
| **Применяется к** | Все инструкции `COPY`/`ADD` | Одна инструкция `COPY` |

## Практические сценарии

### Сценарий 1: Расположение Dockerfile вне корня проекта

Если `Dockerfile` находится в поддиректории, важно правильно указать путь к файлу (`-f`) и путь к контексту (обычно корень проекта).

```bash
# Выполняется из корня проекта
docker build -f deployment/docker/Dockerfile .
```
*Важно: `.dockerignore` должен находиться в корне контекста (`.`), а не рядом с Dockerfile в `deployment/docker/`.*

### Сценарий 2: Исключение файлов напрямую в Dockerfile

Начиная с Dockerfile v1.7+, можно использовать флаг `--exclude` в инструкции `COPY` для точечного исключения файлов, не меняя глобальный `.dockerignore`.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21
WORKDIR /app
# Копируем всё, кроме тестов и временных файлов
COPY --exclude=tests/ --exclude=*.tmp . .
```

### Сценарий 3: Использование именованных контекстов (Named Contexts)

Позволяет подставить локальную директорию вместо внешнего образа или соединить два проекта.

```bash
# Переопределяем образ 'base' локальной директорией при сборке
docker build --build-context base=../common-lib .
```

### Сценарий 4: Оптимальный .dockerignore для DevOps/SRE

Пример файла, предотвращающего утечку секретов и ускоряющего сборку за счет исключения тяжелых зависимостей и Git-истории.

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
.aws/
.kube/

# Логи и временные файлы
*.log
tmp/
.cache/

# Артефакты сборки
dist/
build/
target/

# Файлы инфраструктуры
Dockerfile
.dockerignore
compose.yaml
```

### Сценарий 5: Исключение файлов посредством .dockerignore

Полный пример с комментариями по каждому паттерну и проверкой, что файлы действительно исключены.

```dockerignore
# Исключение всех .md файлов в корне
*.md

# Исключение всех .md файлов рекурсивно
**/*.md

# Исключение всех файлов, кроме README.md
*.md
!README.md

# Исключение всех файлов в src/tests, но не в src/test-utils
src/tests/
!src/tests/*.keep

# Исключение всех .pyc файлов
**/__pycache__/
*.pyc
```

**Проверка исключений:**

```bash
# Сборка с выводом процесса (видно, какие файлы загружаются)
docker build --progress=plain . 2>&1 | grep "transferring"

# Просмотр упакованного контекста (для Legacy Builder)
tar cf - . | tar tf - | grep -v "$(cat .dockerignore | tr '\n' '|')"
```

### Сценарий 6: Multi-stage сборка с изоляцией контекстов

Каждая стадия multi-stage сборки имеет свой изолированный контекст. `RUN` не может обращаться к файлам из другой стадии без `COPY --from` или `--mount=type=bind,from=stage`.

```dockerfile
# syntax=docker/dockerfile:1
# Стадия 1: Сборка (полный контекст)
FROM golang:1.24-alpine AS builder
WORKDIR /app
# ВСЕ файлы проекта доступны на этой стадии
COPY . .
RUN go build -o /bin/app .

# Стадия 2: Runtime (минимальный контекст)
FROM alpine:3.21
# Только скомпилированный бинарник
COPY --from=builder /bin/app /usr/local/bin/app
ENTRYPOINT ["app"]
```

**Важно:** Инструкция `COPY` на стадии 2 не может обращаться к файлам стадии 1 напрямую — только через `COPY --from=builder`.

### Сценарий 7: Доступ к приватным Git-репозиториям через SSH

Клонирование приватного репозитория в контейнере с использованием SSH-агента хоста.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21
RUN apk add --no-cache git openssh-client
RUN --mount=type=ssh \
    mkdir -p /root/.ssh && \
    git clone git@github.com:private/repo.git /app
WORKDIR /app
CMD ["sh"]
```

```bash
# Запуск сборки с пробросом SSH-агента
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
docker buildx build --ssh default=$SSH_AUTH_SOCK -t app:latest .
```

### Сценарий 8: Изменение контекста через Docker Bake

При использовании `docker buildx bake` контекст и игнорируемые файлы можно переопределять в HCL/YAML конфигурации.

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

# Сборка конкретной цели с переопределением контекста
docker buildx bake app --set app.context=../app-v2
```

## Валидация и проверка

### Проверка размера контекста

```bash
# Просмотр размера директории (до сборки)
du -sh .
# -> 45M    .

# Просмотр размера контекста (с учётом .dockerignore)
docker build --progress=plain . 2>&1 | grep "transferring"
# -> transferring dockerfile: 585B done
# -> transferring .dockerignore: 148B done
# -> transferring context: 42.1MB done

# Проверка количества файлов в контексте
tar cf - . | tar tf - | wc -l
# -> 1247

# Сравнение с учётом .dockerignore
tar cf - . | tar tf - | grep -v "$(cat .dockerignore | tr '\n' '|')" | wc -l
# -> 389 (после исключения)
```

### Проверка .dockerignore

```bash
# Валидация синтаксиса .dockerignore (проверка паттернов)
# Docker не имеет встроенной команды валидации, но можно проверить вручную:

# Проверка, что файл НЕ попадёт в контекст
echo "node_modules" >> .dockerignore
tar cf - . | tar tf - | grep "node_modules"
# -> (пусто, если исключение работает)

# Просмотр упакованных файлов (для BuildKit)
DOCKER_BUILDKIT=1 docker build --progress=plain . 2>&1 | \
    grep "transferring" | head -20
```

### Проверка количества слоёв и размера

```bash
# Просмотр размера каждого слоя
docker history myimage:latest
# -> IMAGE          CREATED        CREATED BY                                      SIZE
# -> ...            ...           COPY . . (dockerfile:15)                        42.1MB

# Сравнение размеров ДО и ПОСЛЕ оптимизации .dockerignore
# До (без .dockerignore):
docker history myimage:latest | head -3
# -> ... COPY . .    42.1MB

# После (с .dockerignore):
docker history myimage:latest | head -3
# -> ... COPY . .    8.3MB
```

## Разрешение проблем

### Типичные ошибки

**1. `COPY failed: file not found in build context or excluded by .dockerignore`**

Причина: Файл исключён через `.dockerignore`, не существует в контексте или указан неверный путь.

Решение:

```bash
# Проверка наличия файла в контексте
ls -la my-file.txt

# Проверка .dockerignore
cat .dockerignore | grep "my-file"

# Просмотр упакованных файлов (BuildKit)
docker build --progress=plain . 2>&1 | grep "transferring"

# Временное отключение .dockerignore (для отладки)
mv .dockerignore .dockerignore.bak
docker build . 2>&1 | head -20
mv .dockerignore.bak .dockerignore
```

**2. `failed to solve with frontend dockerfile.v0: failed to create LLB definition`**

Причина: Неверный синтаксис Dockerfile или отсутствие директивы `# syntax`.

Решение:

```dockerfile
# Добавьте директиву в самое начало Dockerfile
# syntax=docker/dockerfile:1

FROM alpine:3.21
# ... остальной контент
```

**3. `error: denied: requested access to the resource is denied`**

Причина: Попытка использовать Docker-образ как именованный контекст без авторизации.

Решение:

```bash
# Авторизация перед сборкой
docker login docker.io
# или
docker buildx build --build-context base=myregistry/custom:latest .
```

**4. `invalid reference format` при `--build-context`**

Причина: Неверный формат имени контекста (пробелы, спецсимволы).

Решение:

```bash
# Имя контекста: только буквы, цифры, дефисы, точки
# Правильно:
docker build --build-context my-app=../myapp .
docker build --build-context app.v2=../app .

# Неправильно:
docker build --build-context my app=../myapp .  # ошибка: пробел
docker build --build-context my_app=../myapp .  # ошибка: подчёркивание
```

**5. `error: .dockerignore must be in the build context root`**

Причина: Файл `.dockerignore` находится в поддиректории, а не в корне контекста.

Решение:

```bash
# Проверка расположения .dockerignore
find . -name ".dockerignore"
# -> ./.dockerignore  (корректно)
# -> ./subdir/.dockerignore  (некорректно)

# Правильное расположение: файл должен быть в корне контекста, а не рядом с Dockerfile
```

**6. `COPY failed: no source files were specified`**

Причина: Инструкция `COPY` указывает на несуществующий файл или пустую директорию.

Решение:

```dockerfile
# Проверка пути относительно контекста
COPY ./src/app.js /app/   # Путь ./src/app.js должен существовать в контексте

# Если файл может отсутствовать — используйте копирование сначала метаданных
COPY package*.json ./
RUN npm install
COPY . .
```

### Диагностические команды

```bash
# Просмотр размера контекста
du -sh .

# Просмотр количества файлов
find . -type f | wc -l

# Просмотр .dockerignore
cat .dockerignore

# Проверка, что файл НЕ исключён
cat .dockerignore | grep -c "node_modules"
# -> 1 (исключён) или 0 (не исключён)

# Просмотр упакованных файлов (BuildKit)
docker build --progress=plain . 2>&1 | grep "transferring" | head -10

# Просмотр размера каждого слоя
docker history myimage:latest

# Просмотр содержимого контекста (Legacy Builder)
tar cf context.tar .
tar tf context.tar | head -20
rm context.tar

# Анализ размера с dive
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  wagoodman/dive myimage:latest
```

## Лучшие практики

### Структура .dockerignore

```dockerignore
# 1. Сначала исключаем всё, затем включаем нужное
*
!src/
!package.json
!package-lock.json

# 2. Затем исключаем внутри включённого
src/**/*.test.js
src/**/*.spec.js
src/tests/

# 3. Системные файлы
.git
.github
.vscode
.idea

# 4. Зависимости
node_modules/
vendor/
.venv/

# 5. Секреты
.env
*.pem
*.key
secrets/
```

### Рекомендации

1. **Всегда создавайте `.dockerignore`** даже для простых проектов — это предотвращает утечку секретов и ускоряет сборку.
2. **Используйте конкретные версии тегов** (`COPY --from=builder:1.0`, а не `COPY --from=latest`) для воспроизводимости.
3. **Минимизируйте контекст** — исключайте `.git`, `node_modules`, логи, артефакты сборки.
4. **Для больших проектов** используйте `--build-context` для подключения зависимостей из внешних директорий.
5. **Используйте `--exclude`** в `COPY` для точечного исключения без изменения `.dockerignore`.
6. **Проверяйте размер контекста** перед сборкой (`du -sh .` и `docker build --progress=plain .`).
7. **Для приватных репозиториев** используйте SSH-агент (`--ssh default=$SSH_AUTH_SOCK`).
8. **В CI/CD** кэшируйте контекст через BuildKit cache mounts.

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
# -> TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# -> Images          15        3         4.2GB     3.1GB (73%)
# -> Containers      5         2         150MB     100MB (66%)
```

## Известные проблемы и ограничения

### Ограничения платформы

- **Размер контекста:** Docker Daemon по умолчанию ограничивает размер контекста (зависит от версии). Для больших проектов используйте `.dockerignore` и multi-stage сборки.
- **Git-контекст:** При использовании Git URL в качестве контекста Docker клонирует весь репозиторий. Для больших репозиториев используйте sparse checkout или локальную директорию.
- **Windows/Mac path:** На Windows и macOS путь к контексту может различаться. Используйте относительные пути и `.dockerignore` для кроссплатформенной совместимости.

### Известные проблемы

- **`.dockerignore` не влияет на `RUN`:** Исключённые файлы не доступны в инструкциях `COPY`/`ADD`, но `RUN` может обращаться к файлам, созданным внутри контейнера (например, `RUN cat /etc/resolv.conf`).
- **`COPY --from` и контекст:** Инструкция `COPY --from=builder` копирует файлы из предыдущей стадии, а не из контекста сборки хоста. Не путайте这两个概念.
- **Специальные символы в паттернах:** Паттерны `.dockerignore` поддерживают glob (`*`, `**`, `!`), но не regex. Для сложных правил используйте несколько строк.
- **Порядок правил:** В `.dockerignore` правила применяются последовательно. Последнее правило для одного файла перезаписывает предыдущие.

## Безопасность

### Утечка секретов через контекст сборки

Контекст сборки передаётся на Docker Daemon (локально или удалённо). Если в контексте находятся секреты — они будут доступны сборщику и могут попасть в слои образа.

**Риски:**
- `.env` файлы с ключами API
- Приватные SSH-ключи
- Сертификаты и токены
- Файлы конфигурации с паролями

**Защита:**

```dockerignore
# ВСЕГДА исключайте секреты
.env
*.pem
*.key
secrets/
.aws/
.kube/
.id_rsa*
```

### Безопасная передача секретов в контексте

Для передачи секретов используйте **BuildKit secrets** (не контекст):

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21
# Секрет НЕ попадает в слой образа
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm install
```

```bash
# Передача секрета через файл
docker buildx build --secret id=npmrc,src=$HOME/.npmrc .
```

### Проверка контекста на утечки

```bash
# Просмотр всех файлов в контексте (поиск секретов)
tar cf - . | tar tf - | grep -iE "(\.env|\.pem|\.key|secret|token|password)"

# Проверка .dockerignore на полноту
cat .dockerignore | wc -l
# Должно быть >= 10 для базового проекта

# Анализ образа на наличие секретов
docker history myimage:latest --no-trunc | grep -i "COPY\|ADD"
# Проверьте, что COPY не копирует .env или secrets/
```

## См. также

- **[Инструкции COPY и ADD](./Instructions/copying_files.md)** — механизмы импорта данных.
- **[BuildKit: Техническое устройство](./dockerfile_buildkit.md)** — детали работы LLB и фронтендов.
- **[Docker Context для удаленного управления](../docker_context.md)** — не путать с Build Context.

**Глубокое изучение:**
- **[.dockerignore паттерны](../../Git/git_ignore.md)** — синтаксис исключений. В Docker: `.dockerignore` работает аналогично `.gitignore`, но файлы-исключения всё равно попадают в контекст сборки (tar), просто исключаются из инструкций COPY/ADD.
- **[Multi-stage builds](./dockerfile_buildkit.md#сценарий-2-multi-stage-сборка)** — разделение сборки и рантайма. В Docker: `COPY --from=builder` для передачи артефактов между стадиями, уменьшение размера финального образа в 10-50 раз.
