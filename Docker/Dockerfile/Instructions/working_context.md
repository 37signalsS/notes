# Инструкции Dockerfile: WORKDIR и SHELL

## Определения

**`WORKDIR`** — инструкция Dockerfile, устанавливающая текущий рабочий каталог для всех последующих инструкций `RUN`, `CMD`, `ENTRYPOINT`, `COPY` и `ADD`. Она действует аналогично команде `cd`, но в отличие от неё, эффект `WORKDIR` сохраняется между слоями сборки и применяется ко всем последующим инструкциям, а не только к текущему `RUN`.

**`SHELL`** — инструкция Dockerfile, позволяющая переопределить оболочку (shell) по умолчанию, которая используется для выполнения команд в формате строки (shell form). Она позволяет использовать альтернативные интерпретаторы (bash, powershell, python, node) для выполнения шагов сборки, обеспечивая доступ к расширенным возможностям оболочки.

## Предварительные требования

Для работы с инструкциями `WORKDIR` и `SHELL` необходимо:

- **Docker** версии 20.10 или новее (для полной поддержки BuildKit).
- **BuildKit** — активирован по умолчанию в Docker 23.0+. Для более ранних версий: `DOCKER_BUILDKIT=1`.
- Понимание базовых концепций: **[CMD и ENTRYPOINT](./runtime_execution.md)** (exec-form vs shell-form), **[ENV и ARG](./environment_variables.md)** (подстановка переменных).
- Базовое понимание Linux-файловой системы: абсолютные и относительные пути, права доступа (UID/GID), структура каталогов.

## Рабочая директория: WORKDIR

Инструкция устанавливает контекст выполнения и автоматически создает директорию (аналог `mkdir -p`), если она не существует. Это критически важная инструкция для структурирования Dockerfile и обеспечения предсказуемости сборки.

### Синтаксис и подстановка переменных

```dockerfile
# Использование абсолютного пути (рекомендуется)
WORKDIR /app

# Использование переменных окружения
ENV APP_HOME=/opt/myapp
WORKDIR $APP_HOME

# Использование переменных с дефолтными значениями
ARG WORKSPACE=/workspace
WORKDIR ${WORKSPACE}/src
```

**Важно:** `WORKDIR` поддерживает подстановку как `ENV`, так и `ARG` переменных. Однако переменные `ARG` доступны только на этапе сборки, а `ENV` — и при сборке, и в рантайме.

### Нюансы вложенности и относительных путей

Если вы используете относительный путь, он будет разрешен относительно пути предыдущей инструкции `WORKDIR`. Каждая новая инструкция `WORKDIR` с относительным путём добавляет его к уже существующему.

```dockerfile
WORKDIR /a
WORKDIR b
WORKDIR c
RUN pwd # -> /a/b/c
```

> **Важно (Best Practice 2026):** Избегайте накопления относительных путей. Это делает Dockerfile хрупким при рефакторинге. Используйте либо абсолютные пути, либо явную конкатенацию переменных: `WORKDIR $APP_HOME/src`.

### Автоматическое создание директорий

`WORKDIR` автоматически создаёт все промежуточные директории в пути, если они не существуют:

```dockerfile
# Все директории будут созданы автоматически
WORKDIR /app/src/main/java
# Эквивалентно: RUN mkdir -p /app/src/main/java
```

Это исключает необходимость использования `RUN mkdir -p`, что уменьшает количество слоёв и упрощает Dockerfile.

### Взаимодействие с правами доступа (BuildKit vs Classic)

Поведение при автоматическом создании директории критично для безопасности:

| Сборщик | Поведение при наличии `USER` | Владелец директории |
| :--- | :--- | :--- |
| **Classic Builder** | Игнорирует текущего пользователя | `root:root` |
| **BuildKit** | Наследует текущего пользователя | Текущий `USER` |

**Рекомендация по безопасности:** Всегда устанавливайте `WORKDIR` до переключения на не-root пользователя или явно задавайте владельца, чтобы избежать ошибок `Permission Denied` при записи данных приложением.

```dockerfile
# ПРАВИЛЬНО: WORKDIR создан до USER, BuildKit создаст с правами root
WORKDIR /app
COPY . .
RUN chown -R appuser:appuser /app
USER appuser

# ТАКЖЕ ПРАВИЛЬНО: WORKDIR после USER создаст с правами appuser (BuildKit)
USER appuser
WORKDIR /app
COPY --chown=appuser:appuser . .
```

### WORKDIR и файловый контекст сборки

Инструкция `WORKDIR` определяет контекст для `COPY` и `ADD`. Путь назначения в `COPY` интерпретируется относительно текущего `WORKDIR`:

```dockerfile
WORKDIR /app
COPY package.json .          # -> /app/package.json
COPY src/ ./src/             # -> /app/src/
COPY --from=builder /out .   # -> /app/out
```

### WORKDIR и динамические пути (BuildKit)

В BuildKit можно использовать `ARG` для динамической настройки рабочей директории:

```dockerfile
# syntax=docker/dockerfile:1
ARG APP_DIR=/app
WORKDIR ${APP_DIR}
COPY . .
```

Это позволяет менять путь при сборке без изменения Dockerfile:

```bash
docker build --build-arg APP_DIR=/opt/myapp .
```

## Оболочка выполнения: SHELL

Инструкция определяет, какая оболочка используется для выполнения команд в shell-form. По умолчанию это `["/bin/sh", "-c"]` на Linux и `["cmd", "/S", "/C"]` на Windows. SHELL влияет на `RUN`, `CMD` и `ENTRYPOINT` в shell-form, но **не влияет** на exec-form (JSON-массив).

### Синтаксис (только Exec-форма)

```dockerfile
SHELL ["executable", "parameters"]
```

**Обязательное требование:** Последний элемент массива должен быть `-c` (или аналогичным флагом), так как Docker добавляет команду после него.

### Влияние SHELL на формы записи

| Форма записи | Влияние SHELL | Пример |
| :--- | :--- | :--- |
| **Shell-form** | Да — команда выполняется через указанную оболочку | `RUN echo hello` |
| **Exec-form** | Нет — команда выполняется напрямую | `RUN ["echo", "hello"]` |

```dockerfile
SHELL ["/bin/bash", "-c"]

# Shell-form: использует bash
RUN echo "Hello from $BASH_VERSION"

# Exec-form: НЕ использует bash, запускается напрямую
RUN ["echo", "Hello directly"]
```

### Настройка надежности (pipefail)

В Linux-образах оболочкой по умолчанию является `["/bin/sh", "-c"]`. Она не останавливает выполнение при ошибке в середине конвейера (`pipe`). Это приводит к тому, что сборка может успешно завершаться даже при критических ошибках в промежуточных командах.

**Проблема без pipefail:**

```dockerfile
# Если curl упадет, но wc -ln выполнится — сборка будет успешной
RUN curl -fsSL https://example.com/data | wc -l > /number
```

**Решение с pipefail:**

```dockerfile
# Сборка упадет, если упадет любая часть пайпа
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL https://example.com/data | wc -l > /number
```

**Рекомендация (2025-2026):** Используйте расширенный набор флагов для maximum надежности:

```dockerfile
# -e: выход при ошибке
# -u: ошибка при неопределённых переменных
# -o pipefail: ошибка пайпа при падении любой команды
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
```

Hadolint (линтер Dockerfile) выдаёт предупреждение DL4006, если `RUN` содержит пайп без `pipefail`.

### SHELL на Alpine Linux

Alpine использует `ash` (busybox) по умолчанию и **не включает bash**. Для использования bash необходимо установить его предварительно:

```dockerfile
FROM alpine:3.21

# Установка bash (увеличивает размер образа на ~5MB)
RUN apk add --no-cache bash

# Переключение на bash с pipefail
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN curl -fsSL https://example.com/data | wc -l > /number
```

**Альтернатива без установки bash:** Используйте `ash` с pipefail (поддерживается в busybox):

```dockerfile
FROM alpine:3.21
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
RUN curl -fsSL https://example.com/data | wc -l > /number
```

**Компромисс:** Если pipefail не критичен, можно добавлять `set -o pipefail` в каждый `RUN`:

```dockerfile
RUN set -o pipefail && curl -fsSL https://example.com/data | wc -l > /number
```

Однако этот подход errores-prone и загромождает Dockerfile.

### Кастомные интерпретаторы как SHELL

Вы можете использовать Python, Node.js или другие языки для выполнения сложной логики сборки без создания отдельных `.sh` файлов.

**Python как оболочка:**

```dockerfile
FROM python:3.12-slim
SHELL ["python", "-c"]
RUN """
import os, json
config = {"app": "myapp", "version": "1.0"}
os.makedirs("/app/config", exist_ok=True)
with open("/app/config/settings.json", "w") as f:
    json.dump(config, f, indent=2)
print(f"Config created in: {os.getcwd()}")
"""
```

**Node.js как оболочка:**

```dockerfile
FROM node:22-alpine
SHELL ["node", "-e"]
RUN """
const fs = require('fs');
const path = require('path');
fs.mkdirSync('/app/logs', { recursive: true });
console.log(`Directory created: ${path.resolve('/app/logs')}`);
"""
```

**Ruby как оболочка:**

```dockerfile
FROM ruby:3.3-slim
SHELL ["ruby", "-e"]
RUN """
require 'fileutils'
FileUtils.mkdir_p('/app/tmp')
puts "Created /app/tmp"
"""
```

> **Ограничение:** При использовании кастомных интерпретаторов стандартные функции оболочки (пайпы `|`, перенаправления `>`, переменные `$HOME`) будут недоступны, если они не реализованы в самом языке. Также увеличивается время сборки из-за запуска интерпретатора.

### Многократное использование SHELL

Инструкцию `SHELL` можно использовать несколько раз для переключения между оболочками:

```dockerfile
FROM ubuntu:22.04

# Основные операции с bash
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN apt-get update && apt-get install -y curl

# Специфичные операции с Python
SHELL ["python3", "-c"]
RUN """
import subprocess
result = subprocess.run(['curl', '--version'], capture_output=True, text=True)
print(result.stdout.split('\\n')[0])
"""

# Возврат к bash для финальных шагов
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN echo "Build complete"
```

### SHELL в многоэтапочных сборках

Настройка `SHELL` действует только в пределах текущей стадии. Каждая новая стадия (`FROM`) сбрасывает оболочку по умолчанию:

```dockerfile
# Stage 1: сборка с bash
FROM golang:1.22 AS builder
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
WORKDIR /build
COPY . .
RUN go build -o app

# Stage 2: runtime без bash (Alpine по умолчанию)
FROM alpine:3.21
WORKDIR /app
COPY --from=builder /build/app .
# SHELL здесь: ["/bin/sh", "-c"] (по умолчанию)
ENTRYPOINT ["./app"]
```

### SHELL и отладка сборки

Для отладки проблем со сборкой можно включить расширенное логирование:

```dockerfile
# Режим отладки: -x выводит каждую команду перед выполнением
SHELL ["/bin/bash", "-euxo", "pipefail", "-c"]

WORKDIR /app
RUN echo "Debug: current directory is $(pwd)"
RUN ls -la
RUN echo "Debug: environment variables"
RUN env | sort
```

## Практические сценарии

### Сценарий 1: Предсказуемая структура (Variables First)

Использование переменных для управления путями во всех стадиях сборки обеспечивает единообразие и упрощает рефакторинг:

```dockerfile
ENV APP_ROOT=/usr/src/app
WORKDIR $APP_ROOT

# Копирование в текущий WORKDIR
COPY package.json .
RUN npm install
COPY . .
```

### Сценарий 2: PowerShell в Windows-контейнерах

Стандартная оболочка Windows (`cmd`) ограничена. Переключение на PowerShell — стандарт для современных Windows-образов:

```dockerfile
FROM mcr.microsoft.com/windows/servercore:ltsc2022
SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop';"]
RUN New-Item -Path 'C:\App' -ItemType Directory
WORKDIR C:\App
COPY . .
RUN Install-Module -Name Az -Force -Scope CurrentUser
```

### Сценарий 3: Multi-stage и сброс контекста

Каждая новая стадия (`FROM`) сбрасывает `WORKDIR` в корень (`/`) и `SHELL` — к значению по умолчанию:

```dockerfile
# Stage 1
FROM golang:1.22 AS builder
WORKDIR /build
COPY . .
RUN go build -o app

# Stage 2
FROM alpine
# Сбрасываем в корень явно для чистоты
WORKDIR /app
COPY --from=builder /build/app .
ENTRYPOINT ["./app"]
```

### Сценарий 4: Node.js с зависимостями (кэширование)

Правильный порядок инструкций `WORKDIR` + `COPY` maximizes кэширование слоёв:

```dockerfile
FROM node:22-alpine
WORKDIR /app

# Сначала зависимости (кэшируются, пока package.json не изменится)
COPY package.json package-lock.json ./
RUN npm ci --production

# Затем исходный код (пересоздаётся при каждом изменении)
COPY src/ ./src/

EXPOSE 3000
CMD ["node", "src/server.js"]
```

### Сценарий 5: Go multi-stage с distroless

Комбинация `WORKDIR` и `SHELL` в builder-стадии с минимальным runtime:

```dockerfile
# Stage 1: сборка
FROM golang:1.22-alpine AS builder
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /server .

# Stage 2: runtime (distroless без оболочки)
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /server /server
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

### Сценарий 6: Alpine с непривилегированным пользователем

Безопасная конфигурация с правильным порядком `WORKDIR` и `USER`:

```dockerfile
FROM alpine:3.21

# Установка зависимостей и создание пользователя
RUN apk add --no-cache curl \
    && addgroup -g 10001 appgroup \
    && adduser -u 10001 -G appgroup -s /bin/sh -D appuser

# WORKDIR до USER (BuildKit создаст с правами root)
WORKDIR /app
COPY --chown=appuser:appgroup . .

# Переключение на непривилегированного пользователя
USER appuser:appgroup

HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["./app"]
```

### Сценарий 7: Bash строгий режим для критических сборок

Максимально надёжная сборка с полной проверкой ошибок:

```dockerfile
FROM ubuntu:22.04

# Строгий режим: все ошибки фатальны
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

WORKDIR /app

# Объединение команд для уменьшения слоёв
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Безопасное скачивание с проверкой
RUN curl -fsSL https://example.com/app.tar.gz | tar xz \
    && ./app --version
```

### Сценарий 8: NVM и Node.js через SHELL

NVM (Node Version Manager) — shell-функция, требующая特殊ной настройки в non-interactive оболочке:

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y curl bash

# Переключение на bash и настройка BASH_ENV для non-interactive сессий
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV BASH_ENV=/root/.bash_env
RUN touch "${BASH_ENV}" && echo '. "${BASH_ENV}"' >> ~/.bashrc

# Установка NVM
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.5/install.sh | \
    PROFILE="${BASH_ENV}" bash

# Установка Node.js через NVM
RUN nvm install 20 && nvm use 20 && nvm alias default 20

# Проверка
RUN node --version && npm --version
```

### Сценарий 9: Rust с кастомной оболочкой для логирования

Создание wrapper-скрипта для логирования всех команд сборки:

```dockerfile
FROM rust:1.75

# Создание скрипта логирования
RUN echo '#!/bin/bash \
set -euo pipefail \
echo "[BUILD] $(date +%H:%M:%S) $@" \
exec bash -c "$@"' > /usr/local/bin/build-shell \
    && chmod +x /usr/local/bin/build-shell

# Использование кастомной оболочки
SHELL ["/usr/local/bin/build-shell"]

WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src/ src/

RUN cargo build --release
```

### Сценарий 10: WORKDIR с динамическим контекстом (BuildKit)

Использование BuildKit-специфичных возможностей для динамической настройки:

```dockerfile
# syntax=docker/dockerfile:1
ARG BASE_DIR=/app
WORKDIR ${BASE_DIR}

# Копирование с исключением файлов
COPY --exclude='*.md' --exclude='.git' . .

# Проверка структуры
RUN find . -maxdepth 2 -type f | head -20
```

## Типичные ошибки и их решение

### Ошибка 1: Ошибка Permission Denied при записи в WORKDIR

**Причина:** `WORKDIR` создан до переключения на `USER`, но файлы скопированы без `--chown`.

**Диагностика:**
```bash
docker run --rm myimage ls -la /app
# Проверьте владельца файлов и директорий
```

**Решение:**
```dockerfile
# Вариант 1: WORKDIR + COPY с --chown
WORKDIR /app
COPY --chown=appuser:appgroup . .

# Вариант 2: WORKDIR после USER (BuildKit)
USER appuser
WORKDIR /app
COPY . .
```

### Ошибка 2: cd не сохраняется между RUN

**Причина:** Каждый `RUN` выполняется в новом shell-процессе. `cd` внутри `RUN` не влияет на последующие `RUN`.

```dockerfile
# ПЛОХО: cd не сохраняется
RUN cd /app && npm install
RUN npm run build  # Выполнится в корне!

# ХОРОШО: используйте WORKDIR
WORKDIR /app
RUN npm install
RUN npm run build
```

### Ошибка 3: Пайп маскирует ошибки (отсутствие pipefail)

**Причина:** `/bin/sh -c` возвращает код последней команды в пайпе. Если `curl` упадёт, но `wc` выполнится — сборка будет «успешной».

```dockerfile
# ПЛОХО: ошибка замаскирована
RUN curl -fsSL https://broken.example.com | wc -l > /number

# ХОРОШО: pipefail ловит ошибку
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
RUN curl -fsSL https://broken.example.com | wc -l > /number
```

### Ошибка 4: SHELL не применяется к exec-form

**Причина:** `SHELL` влияет только на shell-form. Exec-form (JSON-массив) выполняется напрямую.

```dockerfile
SHELL ["/bin/bash", "-c"]

# Shell-form: использует bash
RUN echo "Hello from bash"

# Exec-form: bash НЕ используется
RUN ["echo", "Hello directly"]
```

### Ошибка 5: Неправильный порядок WORKDIR и COPY

**Причина:** `COPY` копирует в текущий `WORKDIR`. Если `WORKDIR` не установлен, файлы копируются в корень (`/`).

```dockerfile
# ПЛОХО: WORKDIR не установлен
COPY package.json /app/

# ХОРОШО: сначала WORKDIR
WORKDIR /app
COPY package.json .
```

### Ошибка 6: WORKDIR с относительными путями при рефакторинге

**Причина:** Накопление относительных путей делает Dockerfile хрупким.

```dockerfile
# ПЛОХО: хрупкая цепочка
WORKDIR /a
WORKDIR b
WORKDIR c
# Итог: /a/b/c — но кто помнит путь?

# ХОРОШО: явный абсолютный путь
WORKDIR /a/b/c
```

### Ошибка 7: SHELL не сбрасывается между стадиями

**Причина:** Каждая стадия `FROM` сбрасывает `SHELL` к значению по умолчанию. Если вы настроили `bash` в builder-стадии, runtime-стадия будет использовать `/bin/sh`.

```dockerfile
# Stage 1: bash настроен
FROM ubuntu:22.04 AS builder
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN echo "Using bash: $BASH_VERSION"

# Stage 2: SHELL сброшен к /bin/sh
FROM alpine:3.21
# SHELL здесь: ["/bin/sh", "-c"] (по умолчанию)
RUN echo "Using default shell"
```

## Лучшие практики

### WORKDIR: рекомендации

1. **Абсолютные пути:** Всегда используйте абсолютные пути для `WORKDIR`. Это делает Dockerfile читаемым и предсказуемым.

2. **Раннее определение:** Устанавливайте `WORKDIR` в начале Dockerfile, после `FROM`, но до `COPY` и `RUN`.

3. **Переменные для конфигурируемости:** Используйте `ENV` или `ARG` для путей, которые могут изменяться:

```dockerfile
ARG APP_HOME=/app
WORKDIR ${APP_HOME}
```

4. **Избегайте `RUN cd`:** Эффект `cd` ограничен одним `RUN`. Используйте `WORKDIR`.

5. **Не создавайте вручную:** `WORKDIR` автоматически создаёт директории. `RUN mkdir -p` избыточен.

6. **Порядок с USER:** Для безопасности определяйте `WORKDIR` до `USER` (BuildKit создаст с правами текущего пользователя) или используйте `--chown` в `COPY`.

### SHELL: рекомендации

1. **Строгий режим для критических сборок:** Всегда используйте `-euo pipefail` для production-сборок:

```dockerfile
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
```

2. **Раннее определение:** Устанавливайте `SHELL` в начале Dockerfile, до инструкций, которые нуждаются в расширенных возможностях оболочки.

3. **Alpine + bash:** Если используете Alpine и нужен bash, устанавливайте его явно:

```dockerfile
RUN apk add --no-cache bash
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
```

4. **Alpine без bash:** Для Alpine можно использовать `ash` с pipefail:

```dockerfile
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
```

5. **Документируйте:** Добавляйте комментарии, почему изменена оболочка:

```dockerfile
# Bash для pipefail — ошибки в пайпах не должны маскироваться
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
```

6. **Не используйте для exec-form:** `SHELL` не влияет на exec-form (JSON-массив). Помните об этом при написании `CMD` и `ENTRYPOINT`.

### Порядок инструкций в Dockerfile

```dockerfile
# 1. FROM (базовый образ)
FROM node:22-alpine

# 2. SHELL (если нужен bash/pipefail) — до всех RUN
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 3. WORKDIR (рабочая директория) — до COPY
WORKDIR /app

# 4. Установка системных зависимостей
RUN apk add --no-cache curl

# 5. COPY зависимостей (кэшируются)
COPY package.json package-lock.json ./
RUN npm ci --production

# 6. COPY исходного кода
COPY src/ ./src/

# 7. USER (безопасность)
USER node

# 8. CMD/ENTRYPOINT
CMD ["node", "src/server.js"]
```

## Граничные случаи и ограничения

### WORKDIR не влияет на существующие файлы

`WORKDIR` устанавливает рабочую директорию для **последующих** инструкций. Он не перемещает файлы, уже скопированные в предыдущих слоях:

```dockerfile
COPY . /tmp/files
WORKDIR /app
# Файлы по-прежнему в /tmp/files, НЕ в /app
```

### WORKDIR и VOLUME

Если `WORKDIR` указывает на директорию, объявленную как `VOLUME`, данные будут сохранены в volume при записи:

```dockerfile
VOLUME /data
WORKDIR /data
RUN echo "test" > file.txt  # file.txt будет в volume
```

### SHELL и переменные окружения

Переменные, установленные через `ENV`, доступны в shell-form, но не в exec-form:

```dockerfile
ENV MY_VAR=hello

# Shell-form: MY_VAR доступна
RUN echo $MY_VAR

# Exec-form: MY_VAR НЕ доступна
RUN ["echo", "$MY_VAR"]  # Выведетliteral "$MY_VAR"
```

### SHELL и команда по умолчанию (dash)

Многие Debian/Ubuntu-образы используют `dash` как `/bin/sh`. `dash` **не поддерживает** `pipefail`. Если вы используете `set -o pipefail` внутри `RUN`, убедитесь, что оболочка поддерживает эту опцию:

```dockerfile
# ПЛОХО: dash не поддерживает pipefail
RUN set -o pipefail && curl url | wc -l

# ХОРОШО: явное указание оболочки
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
RUN curl url | wc -l
```

### WORKDIR и docker run -w

Рабочую директорию можно переопределить при запуске контейнера:

```bash
# Переключение на /tmp при запуске
docker run -w /tmp myimage pwd  # -> /tmp

# В docker-compose.yml
services:
  app:
    working_dir: /app/src
```

Это полезно для отладки без изменения образа.

### SHELL не сохраняется в OCI-образе (Podman)

При использовании Podman с форматом OCI (по умолчанию) настройка `SHELL` **не сохраняется** в образе. Она действует только на этапе сборки. Если нужна persistence — используйте `--format docker` или определяйте оболочку в `CMD`/`ENTRYPOINT`.

## Дополнительная информация

### Отладка путей

Если вы не уверены, какая директория является текущей, используйте временный слой для проверки:

```bash
docker build --target=check-path -t path-debug .
# В Dockerfile:
# FROM builder AS check-path
# RUN pwd && ls -la
```

**Другие методы отладки:**

```bash
# Просмотр WORKDIR из Dockerfile
docker inspect --format='{{.Config.WorkingDir}}' myimage

# Проверка текущей директории в запущенном контейнере
docker exec myimage pwd

# Просмотр всех инструкций образа
docker history myimage --no-trunc
```

### Резюме по использованию

1. **Используйте абсолютные пути** для `WORKDIR`.
2. **Устанавливайте `WORKDIR` до `COPY`**, чтобы упростить пути назначения.
3. **Используйте `SHELL` с `-euo pipefail`** для критических сборок в CI/CD.
4. **Избегайте `RUN cd`**, так как его эффект ограничен одним слоем.
5. **Устанавливайте `SHELL` в начале Dockerfile**, до инструкций, нуждающихся в bash.
6. **На Alpine устанавливайте bash явно**, если он необходим.
7. **Документируйте** причины изменения оболочки.

**См. также:**
- **[Инструкции выполнения: CMD и ENTRYPOINT](./runtime_execution.md)** — влияние `SHELL` на запуск процессов и exec-form vs shell-form.
- **[Переменные окружения: ENV и ARG](./environment_variables.md)** — правила подстановки переменных в `WORKDIR`.
- **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)** — стратегии кэширования слоёв и оптимизация Dockerfile.
