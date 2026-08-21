# Инструкция Dockerfile: RUN

## Определения

**Инструкция `RUN`** — директива Dockerfile, которая выполняет команды в новом слое поверх текущего образа и фиксирует (commit) результаты. Это основной инструмент для установки системных пакетов, сборки зависимостей и конфигурации окружения на этапе подготовки образа.

Каждая инструкция `RUN` создаёт **новый неизменяемый слой** (OverlayFS layer), который записывается в файловую систему образа. Слои кэшируются — при повторной сборке Docker пропускает инструкции, чей ввод (текст команды, файлы из `COPY`) не изменился.

## Предварительные требования

- **Docker** версии 23.0 или новее (BuildKit включён по умолчанию).
- Для использования `--mount` необходимо добавить директиву `# syntax=docker/dockerfile:1` в начало Dockerfile.
- Базовое понимание Linux-команд (`apt-get`, `apk`, `pip`, `npm` и т.д.).
- Знание разницы между **[shell-form и exec-form](./working_context.md)** — критически важное для корректного построения команд.

## Основные концепции

### Формы записи: Shell и Exec

| Характеристика | Shell-форма | Exec-форма |
| :--- | :--- | :--- |
| **Синтаксис** | `RUN команда аргумент` | `RUN ["команда", "аргумент"]` |
| **Оболочка** | `/bin/sh -c` (Linux) или `/bin/bash -c` (если задан `SHELL`) | Выполняется напрямую (`execve`) |
| **Переменные** | Поддерживает подстановку `$VAR` | Не поддерживает подстановку напрямую |
| **Интерпретатор** | Зависит от инструкции `SHELL` | Не зависит от `SHELL` |
| **Логические операторы** | Поддерживает `&&`, `||`, `;`, `\|` | Не поддерживает |

> **Важно:** Для установки пакетов и цепочек команд (через `&&`) обычно используется **Shell-форма**, так как она позволяет использовать логические операторы и переменные окружения. Exec-форма применяется реже — например, для точного контроля над аргументами или для обхода проблем с подстановкой переменных.

**Shell-форма:**
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
```

**Exec-форма:**
```dockerfile
RUN ["apt-get", "update"]
RUN ["apt-get", "install", "-y", "--no-install-recommends", "curl"]
```

**Проблема exec-form и переменных окружения:**
```dockerfile
ENV MY_VAR=hello

# Exec-form: переменная НЕ подставляется
RUN ["echo", "$MY_VAR"]  # Выведетliteral "$MY_VAR"

# Shell-form: переменная подставляется
RUN echo $MY_VAR  # Выведет "hello"
```

### Влияние инструкции SHELL

Инструкция `RUN` в Shell-форме наследует настройки, заданные директивой **[SHELL](./working_context.md#оболочка-выполнения-shell)**. Например, если вы переключили оболочку на `bash` с `pipefail`, все последующие `RUN` будут следовать этим правилам.

```dockerfile
# Смена оболочки на bash с pipefail
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# Теперь этот RUN использует bash
RUN curl -fsSL https://example.com/install.sh | bash
# Если curl упадёт — ошибка не будет скрыта в pipe
```

**Диагностика текущей оболочки:**
```dockerfile
RUN echo $0        # Выведет: /bin/bash (или /bin/sh)
RUN readlink /proc/$$/exe  # Путь к текущему интерпретатору
```

### Надежность и безопасность скриптов

При использовании Shell-формы рекомендуется устанавливать строгий режим выполнения:

```dockerfile
# set -e: остановить сборку при любой ошибке
# set -u: ошибка при использовании необъявленных переменных
# set -o pipefail: вернуть код ошибки, если упала любая часть пайпа
RUN set -euo pipefail; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl; \
    rm -rf /var/lib/apt/lists/*
```

**Почему это важно:**
- `set -e` — без него `apt-get update` может упасть, а `apt-get install` всё равно запустится с устаревшими индексами.
- `set -o pipefail` — без него `curl ... | bash` вернёт код завершения `bash`, а не `curl`.
- `set -u` — защита от опечаток в именах переменных.

### Heredoc-синтаксис (BuildKit 1.4+)

Начиная с BuildKit 1.4 (`# syntax=docker/dockerfile:1.4`), поддерживается запись многострочных команд `RUN` без символа переноса строки `\`. Это значительно улучшает читаемость сложных скриптов:

```dockerfile
# syntax=docker/dockerfile:1.4
FROM python:3.12-slim

RUN <<EOF
apt-get update
apt-get install -y --no-install-recommends gcc libffi-dev
pip install --no-cache-dir -r requirements.txt
apt-get purge -y --auto-remove gcc libffi-dev
rm -rf /var/lib/apt/lists/*
EOF
```

**Преимущества Heredoc:**
- Убирает необходимость в `\` и `;` между строками.
- Каждая строка выполняется отдельно, но в одном слое.
- Поддерживает переменные окружения и подстановку файлов.

**Heredoc с переменными:**
```dockerfile
# syntax=docker/dockerfile:1.4
ARG BUILD_ENV=production
RUN <<EOF
echo "Building for: ${BUILD_ENV}"
if [ "${BUILD_ENV}" = "production" ]; then
    pip install --no-cache-dir gunicorn
fi
EOF
```

**Heredoc с монтированием:**
```dockerfile
# syntax=docker/dockerfile:1.4
RUN --mount=type=cache,target=/root/.cache/pip <<EOF
pip install -r requirements.txt
EOF
```

### Оптимизация слоёв: объединение команд

Каждый `RUN` создаёт отдельный слой. Объединение команд через `&&` уменьшает количество слоёв и размер образа:

```dockerfile
# ПЛОХО: 3 слоя, каждый с мусором
RUN apt-get update
RUN apt-get install -y curl
RUN rm -rf /var/lib/apt/lists/*

# ХОРОШО: 1 слой, мусор удалён
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
```

**Исключение:** Иногда раздельные `RUN` оправданы для эффективности кэширования. Если установка пакетов занимает 10 минут, а копирование кода — 1 секунду, разделите их:

```dockerfile
# Слой 1: пакеты (кэшируются, пока не изменится список зависимостей)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Слой 2: код (пересобирается часто)
COPY src/ /app/src/
```

### Кэширование и инвалидация

BuildKit использует граф зависимостей (LLB) вместо простой линейной истории слоев. Кэш инструкции `RUN` инвалидируется, если:
1. Текст команды изменился.
2. Изменились файлы, примонтированные через `--mount=type=bind`.
3. Изменились аргументы сборки (`ARG`), используемые в команде.
4. Изменился базовый слой (если не используется `--link` в `COPY`).

**Совет:** Старайтесь объединять логически связанные команды в один `RUN`, но разделяйте "тяжелые" шаги (установка зависимостей) и "легкие" (копирование кода), чтобы эффективно использовать кэш.
## Расширенные возможности BuildKit

Современный движок **[BuildKit](../dockerfile_buildkit.md)** превращает `RUN` в мощный инструмент оркестрации сборки. Требуется заголовок `# syntax=docker/dockerfile:1`.

### Флаг --mount (Типы монтирования)

| Тип | Назначение | Примеры путей (target) |
| :--- | :--- | :--- |
| **`type=cache`** | Кэш зависимостей | `~/.npm`, `/root/.cache/pip`, `/root/.cargo/registry` |
| **`type=secret`** | Безопасные секреты | `/run/secrets/api_key` |
| **`type=ssh`** | SSH-агент хоста | По умолчанию `/run/buildkit/ssh_agent.0` |
| **`type=bind`** | Монтирование файлов | Доступ к файлам контекста или `from=stage` без копирования |
| **`type=tmpfs`** | Временная RAM-диск | Для записи временных данных, не попадающих в слои |

#### Cache Mount

Кэш сохраняется между сборками. Данные не попадают в итоговый образ.

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

**Параметры sharing:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `sharing=shared` | Кэш доступен нескольким сборкам одновременно | `--mount=type=cache,target=/cache,sharing=shared` |
| `sharing=private` | Кэш изолирован для каждой сборки | `--mount=type=cache,target=/cache,sharing=private` |
| `sharing=locked` | Кэш заблокирован на время сборки | `--mount=type=cache,target=/cache,sharing=locked` |

**Размер кэша:**
```bash
# Просмотр размера кэша BuildKit
docker builder du

# Очистка кэша
docker builder prune -a  # Полная очистка
docker builder prune --filter "until=24h"  # Только за сутки
```

#### Secret Mount

Безопасная передача секретов. Секреты монтируются в tmpfs и никогда не сохраняются в слоях.

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) npm install
```

```bash
# Запуск сборки с секретом
docker build --secret id=npm_token,src=$HOME/.npm_token -t myapp .
```

**Варианты передачи секрета:**

| Способ | Синтаксис | Когда использовать |
| :--- | :--- | :--- |
| Из файла | `--secret id=key,src=./key.txt` | Статические ключи, токены |
| Из переменной | `--secret id=key,env=API_KEY` | Переменные окружения CI |
| С数千ью по умолчанию | `--secret id=key` | SSH-ключи, gpg |

#### SSH Mount

Проброс SSH-агента хоста для доступа к приватным Git-репозиториям.

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=ssh git clone git@github.com:myorg/private-repo.git /src
```

```bash
# Запуск с пробросом SSH-агента
docker build --ssh default -t myapp .
```

#### Bind Mount

Доступ к файлам из других стадий без их копирования в слой.

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22 AS builder
WORKDIR /build
COPY . .
RUN go build -o /app/server .

FROM alpine:3.21
# Используем gcc из builder для дополнительной компиляции
RUN --mount=type=bind,from=builder,source=/usr/bin/gcc,target=/usr/bin/gcc \
    gcc -o helper helper.c
```

#### Tmpfs Mount

Временное хранилище в RAM для данных, которые не должны попасть в слой.

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=tmpfs,target=/tmp \
    make test
```

### Управление сетью и безопасностью

- **`--network=<mode>`**:
  - `none`: Полная сетевая изоляция. Гарантирует, что скрипты сборки не отправят данные вовне. Идеально для проверки, что образ не пытается подключиться к интернету при сборке.
  - `host`: Использование сетевого стека хоста. Необходимо для сборок, требующих доступа к внутренним реестрам без проксирования.
  - `default`: Стандартная сеть Docker (bridge). Используется по умолчанию.
- **`--security=insecure`**: Позволяет выполнять операции, требующие привилегий (например, создание loop-устройств). Требует включения `security.insecure` в настройках демона.

```dockerfile
# Сборка с изолированной сетью
RUN --network=none pip install --no-index --find-links=/deps local-package.whl

# Сборка с доступом к хосту
RUN --network=host curl http://localhost:8080/health
```

### Флаг --link (BuildKit 1.5+)

Позволяет создавать слои `RUN`, которые не зависят от предыдущих слоёв. Это полезно для ускорения сборки при изменении базового образа:

```dockerfile
# syntax=docker/dockerfile:1.5
FROM alpine:3.21
RUN --link apk add --no-cache curl
# Если базовый образ изменится, этот слой не будет пересобран
```

## Практические сценарии

### Сценарий 1: Глобальное кэширование зависимостей (Node.js)

Использование специфических путей кэша для разных пакетных менеджеров.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine
WORKDIR /app
COPY package*.json ./

# Кэширование для npm
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Кэширование для pnpm
# RUN --mount=type=cache,target=/pnpm/store \
#     pnpm install --frozen-lockfile

# Кэширование для yarn
# RUN --mount=type=cache,target=/root/.cache/yarn \
#     yarn install --frozen-lockfile
```

### Сценарий 2: Безопасное использование приватных Git-репозиториев

Использование SSH-агента хоста исключает хранение ключей в образе.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21
RUN apk add --no-cache openssh-client git
RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts

# Клонирование через SSH-агент
RUN --mount=type=ssh git clone git@github.com:myorg/private-repo.git /src
```

```bash
# Запуск сборки с SSH-агентом
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
docker build --ssh default -t myapp .
```

### Сценарий 3: Атомарная сборка с проверкой (Build Checks)

Включение нативного линтинга Dockerfile (BuildKit v1.8+).

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true
FROM alpine:3.20

# Docker выдаст ошибку, если обнаружит плохие практики
RUN apk update && apk add curl
```

### Сценарий 4: Go-приложение с глубоким кэшированием

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./

# Кэшируем модули Go
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .

# Кэшируем результат компиляции
RUN --mount=type=cache,target=/root/.cache/go-build \
    go build -o /app/main .
```

### Сценарий 5: Python-приложение с секретами и кэшем pip

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .

# Секрет для приватного реестра + кэш pip
RUN --mount=type=secret,id=pip_conf,target=/root/.pip/pip.conf \
    --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "app.py"]
```

```bash
docker build --secret id=pip_conf,src=./pip.conf -t myapp .
```
### Сценарий 6: Java/Maven с сохранением .m2

```dockerfile
# syntax=docker/dockerfile:1
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .

# Предварительная загрузка зависимостей
RUN --mount=type=cache,target=/root/.m2 \
    mvn dependency:go-offline

COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests
```

### Сценарий 7: Rust с кэшированием Cargo

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.82-slim AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./

# Кэш реестра Cargo
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release

COPY src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && cp target/release/myapp /usr/local/bin/
```

### Сценарий 8: C++ с ccache

```dockerfile
# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ccache
WORKDIR /src
COPY . .

# Кэш компиляции ccache
RUN --mount=type=cache,target=/root/.cache/ccache \
    CC="ccache gcc" CXX="ccache g++" make -j$(nproc)
```

### Сценарий 9: Установка пакетов с apt cache mount

```dockerfile
# syntax=docker/dockerfile:1
FROM ubuntu:24.04

# Кэш apt позволяет переиспользовать скачанные пакеты
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*
```

### Сценарий 10: Отладка ошибки сборки

Когда команда `RUN` падает на промежуточном шаге:

```bash
# Запуск сборки с отладкой
DOCKER_BUILDKIT=1 docker build --progress=plain -t myapp . 2>&1 | tee build.log

# Поиск ошибки в логе
grep -A 5 "error:" build.log

# Просмотр слоёв для анализа
docker history myapp --no-trunc

# Запуск промежуточного образа для отладки
# (нужно добавить有意альную ошибку или использовать breakpoint)
docker run -it --rm $(docker build -q .) /bin/bash
```

**Breakpoint-синтаксис (BuildKit):**
```dockerfile
# Вставка breakpoint для остановки на определённом шаге
RUN echo "=== DEBUG: HERE ===" && false
# Сборка остановится, можно inspect'ить слой
```

## Типичные ошибки и их решение

### Ошибка 1: apt-get update и apt-get install в разных RUN

**Проблема:** Индексы пакетов кэшируются отдельно. Если `apt-get update` в одном слое, а `apt-get install` в другом, повторная сборка может установить неактуальные версии.

```dockerfile
# ПЛОХО: индексы и установка в разных слоях
RUN apt-get update
RUN apt-get install -y curl  # Может установить устаревший пакет!

# ХОРОШО: в одном слое
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
```

### Ошибка 2: Остатки пакетного менеджера увеличивают размер

```bash
# Проверка размера слоёв
docker history myimage --format "{{.Size}} {{.CreatedBy}}"

# Результат: 200MB от apt-get cache в отдельном RUN
```

```dockerfile
# ПЛОХО: мусор остался
RUN apt-get update && apt-get install -y curl

# ХОРОШО: мусор удалён в том же RUN
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
```

### Ошибка 3: Секрет попадает в слой

```dockerfile
# ПЛОХО: пароль навсегда в истории образа
RUN echo "my_secret_password" > /run/secrets/db_pass
RUN PGPASSWORD=$(cat /run/secrets/db_pass) pg_dump ...

# ХОРОШО: секрет через BuildKit
RUN --mount=type=secret,id=db_pass \
    PGPASSWORD=$(cat /run/secrets/db_pass) pg_dump ...
```

### Ошибка 4: Exec-form и подстановка переменных

```dockerfile
ENV APP_ENV=production

# ПЛОХО: переменная не подставится
RUN ["echo", "$APP_ENV"]  # Выведет: $APP_ENV

# ХОРОШО: shell-form или комбинация
RUN echo $APP_ENV
RUN ["/bin/sh", "-c", "echo $APP_ENV"]
```

### Ошибка 5: Кэш инвалидируется при изменении ARG

```dockerfile
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl

# Если изменить ARG, даже если RUN не изменился — кэш сбросится
ARG DEBIAN_FRONTEND=dialog  # Это сбросит кэш предыдущего RUN!
```

### Ошибка 6: Кэш apt не переиспользуется

```bash
# Каждая сборка скачивает пакеты заново
```

```dockerfile
# Решение: mount cache для apt
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y curl
```

### Ошибка 7: Breakpoint не срабатывает

```dockerfile
# Если breakpoint не останавливает сборку
RUN echo "debug" && false  # Должно остановить
```

**Причины:**
1. Используется устаревший builder (не BuildKit). Включите: `DOCKER_BUILDKIT=1`
2. Кэш: если слой уже в кэше, breakpoint пропускается. Добавьте уникальный комментарий: `RUN echo "debug $(date)" && false`

## Лучшие практики

### Безопасность

1. **Всегда используйте `--no-install-recommends`** при установке пакетов — уменьшает размер образа и поверхность атаки.
2. **Удаляйте кэш пакетного менеджера** в том же `RUN` — если оставить в отдельном `RUN`, мусор попадёт в слой.
3. **Используйте секреты через `--mount=type=secret`** — никогда не храните пароли, токены или ключи в `ENV`, `ARG` или `RUN echo`.
4. **Устанавливайте минимальный набор пакетов** — каждая зависимость потенциальный вектор атаки.
5. **Используйте `--network=none`** для сборки с локальными зависимостями — предотвращает утечку данных.

### Производительность

1. **Кэшируйте зависимости через `--mount=type=cache`** — npm, pip, cargo, maven, go modules.
2. **Объединяйте связанные команды** в один `RUN` через `&&`.
3. **Разделяйте тяжёлые и лёгкие шаги** — установка пакетов (кэшируется) отдельно от копирования кода (инвалидируется часто).
4. **Используйте Heredoc** вместо `\` для многострочных команд — улучшает читаемость и уменьшает ошибки.
5. **Используйте `--mount=type=bind`** для доступа к файлам из других стадий — без создания лишних слоёв.

### Читаемость

1. **Используйте `set -euo pipefail`** в начале сложных скриптов — Guarantees ошибки не будут проглочены.
2. **Группируйте команды по логическому принципу** — установка, конфигурация, сборка, очистка.
3. **Добавляйте комментарии** перед сложными шагами.
4. **Используйте Heredoc** для скриптов длиннее 3 строк.

## Граничные случаи и ограничения

### RUN и multiple FROM

Каждая стадия multi-stage сборки имеет свой контекст. `RUN` не может обращаться к файлам из другой стадии без `COPY --from` или `--mount=type=bind,from=stage`:

```dockerfile
FROM node:22 AS builder
RUN npm run build

FROM alpine:3.21
# ОШИБКА: /app/dist не существует в этой стадии
RUN ls /app/dist

# ПРАВИЛЬНО: сначала скопируйте
COPY --from=builder /app/dist /app/dist
RUN ls /app/dist
```

### RUN и переменные окружения

Переменные `ENV` доступны во всех последующих `RUN`, но **не сохраняются** между сборками. `ARG` доступен только во время сборки:

```dockerfile
ARG VERSION=1.0
ENV APP_VERSION=${VERSION}

# Доступно: $APP_VERSION и $VERSION
RUN echo "Building version: ${APP_VERSION}"
```

### RUN и SHELL

`SHELL` не влияет на exec-form:

```dockerfile
SHELL ["/bin/bash", "-c"]

# Shell-form: использует bash
RUN echo "Hello from bash"

# Exec-form: bash НЕ используется
RUN ["echo", "Hello directly"]
```

### RUN и именованные стадии

`RUN` не может обращаться к предыдущим стадиям по имени. Используйте `--from` в `COPY`:

```dockerfile
FROM golang:1.22 AS builder
RUN go build -o /app/server .

FROM alpine:3.21
# Нельзя: RUN --from=builder ... (нет такого синтаксиса)
# Можно: COPY --from=builder /app/server /app/server
COPY --from=builder /app/server /app/server
```

### RUN и Cleanup after apt

Правильный порядок очистки apt:

```dockerfile
# 1. Установка
# 2. Использование
# 3. Очистка — ВСЁ В ОДНОМ RUN
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    make install && \
    apt-get purge -y --auto-remove build-essential && \
    rm -rf /var/lib/apt/lists/*
```

### RUN и права доступа

`RUN` выполняется от текущего пользователя (по умолчанию root). Для создания файлов от другого пользователя:

```dockerfile
# Создаём пользователя
RUN addgroup -g 10001 appgroup && adduser -u 10001 -G appgroup -s /bin/sh -D appuser

# Копируем и устанавливаем права
COPY --chown=10001:10001 . /app

# Переключаемся на пользователя
USER 10001

# Теперь RUN выполняется от appuser
RUN ls -la /app
```

## Дополнительная информация

### Кэширование и LLB (Low-Level Builder)

BuildKit использует граф зависимостей (LLB) вместо простой линейной истории слоев. Кэш инструкции `RUN` инвалидируется, если:
1. Текст команды изменился.
2. Изменились файлы, примонтированные через `--mount=type=bind`.
3. Изменились аргументы сборки (`ARG`), используемые в команде.
4. Изменился базовый слой (если не используется `--link` в `COPY`).

### Оптимизация размера: multi-stage + RUN

```dockerfile
# Стадия сборки: тяжёлые зависимости
FROM golang:1.22 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc
RUN go build -o /app/server .

# Стадия runtime: только бинарник
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

### Kaniko и RUN

[Kaniko](../dockerfile_kaniko.md) выполняет `RUN` через chroot без Docker-демона. BuildKit-расширения (`--mount`, `--network`, `--security`) **игнорируются** Kaniko.

**См. также:**
- **[Оптимизация сборки: кэширование и Multi-stage](../Docker_best_practices/build_optimization.md)** — глубокое погружение в стратегии.
- **[Инструкции выполнения: CMD и ENTRYPOINT](./runtime_execution.md)** — разница между сборкой и рантаймом.
- **[Управление секретами сборки](../../Docker_security/secrets_management.md)** — детали `type=secret`.
- **[BuildKit в Dockerfile](../dockerfile_buildkit.md)** — архитектура современного сборщика.
- **[Docker Buildx: Мультиплатформенность](../docker_buildx.md)** — управление инстансами сборщиков.
