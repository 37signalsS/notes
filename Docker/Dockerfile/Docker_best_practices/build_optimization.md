# Оптимизация сборки Docker-образов

**Актуально для:** Docker 24.0+ / BuildKit включён по умолчанию

## Определения

- **Кэширование слоев (Layer Caching):** Механизм Docker, сохраняющий результат каждой инструкции `Dockerfile` в виде неизменяемого слоя. При повторных сборках Docker переиспользует существующие слои, если инструкция и контекст не изменились.
- **Многоэтапная сборка (Multi-stage Builds):** Техника использования нескольких инструкций `FROM` в одном файле. Позволяет разделить среду сборки (с компиляторами и зависимостями) и среду выполнения (минимально необходимый набор файлов). Итогом multistage-сборки является **Docker-образ** — по сути, tar-архив с слоями файловой системы, который можно физически распаковать и исследовать.
- **Контекст сборки (Build Context):** Набор локальных файлов, отправляемых Docker-клиентом сборщику (BuildKit) перед началом сборки. Оптимизация контекста напрямую влияет на скорость передачи данных.
- **BuildKit:** Современный движок сборки, использующий граф зависимостей (LLB) для параллельного выполнения команд и поддерживающий расширенные возможности (маунты, секреты, кэширование).
- **Монтирование кэша (Cache Mounts):** Механизм BuildKit (`--mount=type=cache`), позволяющий сохранять данные пакетных менеджеров во внешнем хранилище между сборками, не включая их в слои образа.
- **Аттестации (Attestations):** Метаданные (SBOM, Provenance), прикрепляемые к образу для подтверждения его состава и происхождения.
- **Heredoc:** Синтаксис Dockerfile, позволяющий записывать многострочные скрипты `RUN` без использования символов переноса строки `\`.
- **Distroless образы:** Минимальные базовые образы от Google, содержащие только приложение и его зависимости без оболочки, пакетного менеджера и других системных утилит. Используются как финальная стадия multi-stage для максимального уменьшения размера и поверхности атаки.
- **Squash (слоёв):** Механизм объединения всех слоёв образа в один, уменьшающий размер, но уничтожающий кэш и замедляющий повторную сборку. В BuildKit доступен через `--squash`, но не рекомендуется для production — предпочтительнее multi-stage + `COPY --link`.

## Базовые концепции

### Порядок инструкций и инвалидация кэша

Для максимальной эффективности кэширования инструкции в `Dockerfile` должны располагаться в порядке **от редко изменяемых к часто изменяемым**.

1.  **Каскадная инвалидация:** Если кэш слоя N сброшен (например, изменился текст команды или файл в `COPY`), то слои N+1, N+2 и все последующие будут пересобраны принудительно.
2.  **Инструкции RUN:** Любое изменение текста команды инвалидирует слой. Рекомендуется объединять связанные команды (например, `apt-get update && apt-get install`) для уменьшения количества слоев.
3.  **Инструкции COPY/ADD:** Docker проверяет контрольные суммы файлов. Если изменился хотя бы один файл, кэш слоя сбрасывается. **Антипаттерн:** `COPY . .` в начале файла, так как любое изменение кода сбросит кэш установки зависимостей.
4.  **`COPY --link` (BuildKit 1.5+):** Позволяет копировать файлы в независимые слои. Если предыдущие слои (например, базовый образ) изменятся, Docker просто пересоберет манифест, не перекопируя файлы заново. Это критично для ускорения сборки при обновлении базового образа.

### Стратегии оптимизации по типу приложения

| Критерий | Компилируемые (Go, Rust, C++) | Интерпретируемые (Node.js, Python) | JVM (Java, Kotlin) |
| :--- | :--- | :--- | :--- |
| **Главная цель** | Уменьшение размера образа (бинарник). | Ускорение установки зависимостей. | Уменьшение размера SDK + кэш .m2. |
| **Multi-stage** | **Критически важен** (отсечение SDK). | **Желателен** (удаление `dev-deps` и кэшей). | **Критически важен** (JDK ~300MB vs JRE ~80MB). |
| **Тип кэша** | Кэш компилятора (`target`, `build`). | Кэш пакетного менеджера (`~/.npm`, `pip`). | Кэш `.m2/repository`. |
| **Кросс-компиляция** | Нативная поддержка (`GOOS`, `TARGETARCH`). | Не применимо. | Не применимо (GraalVM — исключение). |
| **Рекомендуемый базовый образ** | `scratch`, `distroless/static`. | `alpine`, `slim`. | `eclipse-temurin-*-jre-alpine`. |

### Продвинутые возможности BuildKit

- **`COPY --link`:** Позволяет копировать файлы в абсолютно независимые слои. Если предыдущие слои (например, базовый образ) изменятся, Docker просто пересоберет манифест, не перекопируя файлы заново.
- **Временные монтирования (`--mount`):**
    - `type=cache`: Для папок зависимостей (`node_modules`, `pip cache`).
    - `type=secret`: Безопасная передача токенов без их сохранения в истории образа.
    - `type=ssh`: Использование SSH-ключей хоста для доступа к приватным репозиториям.
    - `type=bind`: Использование файлов из других стадий без их физического копирования.
    - `type=tmpfs`: Временное хранилище в RAM для промежуточных данных.
- **Reproducible Builds:** Использование переменной `SOURCE_DATE_EPOCH` для фиксации временных меток слоев, что позволяет получать идентичные дайджесты образов при сборке из того же исходного кода.
- **Build Checks:** Встроенный линтер Dockerfile (`docker buildx build --check`), проверяющий инструкции на соответствие лучшим практикам перед началом сборки.

### Удаленное кэширование (BuildKit Cache Backends)

Для CI/CD критически важно сохранять кэш между запусками. BuildKit поддерживает несколько бэкендов:

| Бэкенд | Назначение | Пример использования |
| :--- | :--- | :--- |
| **`registry`** | Универсальный, работает везде | `--cache-to type=registry,ref=reg/cache:app,mode=max` |
| **`s3`** | S3-совместимое объектное хранилище (MinIO, Ceph RGW, Harbor) | `--cache-to type=s3,region=us-east-1,bucket=cache,key=app,endpoint=minio.local` |
| **`local`** | Локальная папка на хосте | `--cache-to type=local,dest=/tmp/buildx-cache,mode=max` |
| **`inline`** | Кэш встраивается в образ (Docker Hub) | По умолчанию при `--push` |

**Режимы кэширования:**

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| `mode=min` | Кэш только финальной стадии | По умолчанию; экономит место |
| `mode=max` | Кэш всех промежуточных слоев (включая неиспользуемые в финальном образе) | Рекомендуется для CI/CD — ускоряет повторные сборки |

**Важно:** Режим `mode=max` сохраняет кэш всех промежуточных слоев, включая неиспользуемые в финальном образе стадии multi-stage. Это критично, так как при изменении только финальной стадии промежуточные стадии (builder) не пересобираются, и их кэш должен быть доступен.

### Конфигурация BuildKit и управление кэшем (DevOps/SRE)

Для эксплуатации в production и CI/CD необходимо понимать настройки демона BuildKit и политики управления кэшем:

**Конфигурация демона Docker (`/etc/docker/daemon.json`):**

```json
{
  "features": {
    "buildkit": true
  },
  "experimental": true,
  "builder": {
    "gc": {
      "enabled": true,
      "keepStorage": "10GB",
      "default": "72h"
    }
  }
}
```

- `features.buildkit`: Включение BuildKit (по умолчанию в Docker 24.0+).
- `builder.gc`: Политика автоматической очистки кэша BuildKit. `keepStorage` — максимальный размер кэша, `default` — время хранения неиспользуемых объектов.
- `experimental`: Требуется для некоторых возможностей Buildx.

**Драйверы buildx:**

| Драйвер | Изоляция | Когда использовать |
| :--- | :--- | :--- |
| **`docker`** | Использует демон Docker напрямую | Локальная разработка, быстрые сборки |
| **`docker-container`** | Изолированный контейнер с собственным демоном | CI/CD, production — стабильность и повторяемость |
| **`kubernetes`** | Pod в Kubernetes кластере | Распределённые сборки в K8s, большое количество параллельных задач |

```bash
# Создание инстанса сборщика с изолированным драйвером (рекомендуется для CI)
docker buildx create --use --driver docker-container --name ci-builder

# Просмотр инстансов
docker buildx ls
# → NAME       DRIVER       STATUS
# → ci-builder docker-container  running
# → default    docker         running
```

**Управление кэшем:**

```bash
# Просмотр использования кэша
docker buildx du
# → RECLAIMABLE   SIZE
# → 2.1GB         3.4GB

# Очистка кэша старше 72 часов
docker buildx prune --filter "until=72h"

# Принудительная очистка всего кэша
docker buildx prune --all --force

# GC только для определённого инстанса
docker buildx du --builder ci-builder
docker buildx prune --builder ci-builder --filter "until=72h"
```

**Производительность и параллелизм:**

```bash
# Параллельные стадии multi-stage выполняются автоматически в BuildKit
# Для явного управления параллелизмом используйте --jobs (buildx)
docker buildx build --jobs 4 -t myapp:latest .

# Ограничение ресурсов для сборщика (docker-container драйвер)
docker buildx create --use --driver docker-container \
  --buildkitd-flags '--debug --addr tcp://0.0.0.0:1234 --max-parallelism 4'
```

### Воспроизводимые сборки

Для получения идентичных дайджестов образов при сборке из одного исходного кода используйте `SOURCE_DATE_EPOCH`:

```bash
# Фиксация временной метки для всех слоёв
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) docker buildx build -t myapp:latest .

# Или через аргумент сборки
docker buildx build --build-arg SOURCE_DATE_EPOCH=$(date +%s) -t myapp:latest .
```

**Реестр и политики:**

- Используйте **приватный registry** с support content trust (Docker Content Trust, Notary) или **Sigstore/Cosign** для подписи образов.
- Для air-gapped сред настроите **pull-through cache** (Harbor, Nexus, registry:3 с прокси), чтобы кэшировать базовые образы внутри периметра.
- Включите **склейку кэша** (`--cache-to type=inline`) для базовых образов, чтобы ускорить повторные сборки на других хостах.

## Предварительные требования

- **Docker Engine 24.0+** (рекомендуется Docker 27.0+, где `docker buildx build` является стандартным алиасом для `docker build`).
- **BuildKit** включён по умолчанию в Docker 24.0+. Для более ранних версий необходимо установить переменную окружения `DOCKER_BUILDKIT=1`.
- **Плагин `docker-buildx`** установлен и активирован (`docker buildx create --use --driver docker-container` для изолированного драйвера).
- **Достаточно дискового пространства** для кэша BuildKit: при включённом `mode=max` кэш может занимать несколько гигабайт. Рекомендуется настроить политику очистки (`docker buildx prune --filter until=72h`).
- **Доступ к реестрам** с базовыми образами или внутренний registry с предзагруженными образами (для air-gapped сред).
- **Для multi-platform сборок:** настроен `binfmt_misc` и эмуляторы (QEMU), либо используется кросс-компиляция нативной сборкой на хосте сборки (`--platform=$BUILDPLATFORM`).
- **Для удалённого кэширования:** доступный registry с поддержкой manifests (Docker Hub, Harbor, Nexus, registry:3) или MinIO-совместимый объектный стор для S3-бэкенда.
- **Для production-сборок:** настроен admission-контроллер (Kyverno/OPA) или CI-политики для проверки SBOM и подписей перед деплоем.

## Практические сценарии

### Сценарий 1: Оптимальное кэширование Node.js

Детальный разбор `--mount=type=cache`, `COPY --link` и стратегий кэширования для npm: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

### Сценарий 2: Кэширование для Python (pip)

Детальный разбор Heredoc, `--mount=type=cache` и секретов для pip: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

### Сценарий 3: Java/Maven с сохранением .m2

Детальный разбор кэширования `.m2` и стратегий для JVM-сборок: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

### Сценарий 4: Безопасная сборка с секретами

Передача токена доступа к приватному реестру пакетов.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine
WORKDIR /app
COPY package.json ./
# Токен монтируется только на время выполнения команды и не сохраняется в образе
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) npm install
```

### Сценарий 5: Go-приложение с кросс-компиляцией и distroless

Детальный разбор кэширования модулей Go, кросс-компиляции и distroless: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

**Валидация:**
```bash
# Сборка под две архитектуры
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest .

# Проверка размера образа
docker images myapp:latest
# → REPOSITORY   TAG       SIZE
# → myapp        latest    5.8MB  (вместо ~800MB без multi-stage)

# Проверка что кэш работает
# Вторая сборка будет значительно быстрее
time docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest .
```

### Сценарий 6: Rust с кэшированием Cargo

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.98-slim AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./

# Создаём заглушку main.rs для кэширования зависимостей
RUN mkdir src && echo "fn main() {}" > src/main.rs

# Кэшируем реестр Cargo и результат компиляции зависимостей
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && \
    rm -rf src

# Копируем исходный код и пересобираем только бинарник
COPY src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && \
    cp target/release/myapp /usr/local/bin/

FROM debian:bookworm-slim
COPY --from=builder /usr/local/bin/myapp /usr/local/bin/myapp
ENTRYPOINT ["myapp"]
```

**Почему заглушка `main.rs`:** Без неё `cargo build` начнёт компиляцию зависимостей и кода одновременно. С заглушкой зависимости компилируются отдельно (кэшируются), а код — отдельно. При изменении только `src/` зависимости не пересобираются.

### Сценарий 7: C++ с ccache

Детальный разбор кэширования Cargo, заглушки `main.rs` для Rust и ccache для C++: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

### Сценарий 8: Сборка с аттестациями (SBOM) для production

```bash
# Сборка с генерацией SBOM и provenance
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  --push -t myregistry.com/app:v1 .

# Проверка SBOM
docker buildx imagetools inspect myregistry.com/app:v1 \
  --format '{{ json .SBOM }}' | jq .
```
## Анализ слоев и инструменты

### Интерактивный анализ с dive

Инструмент [dive](https://github.com/wagoodman/dive) позволяет визуализировать каждый слой образа и находить «мусор» — файлы, которые были созданы и затем удалены в разных слоях.

```bash
# Запуск анализа
dive myapp:latest

# В интерфейсе обратите внимание на колонку Efficiency
# Если она ниже 90%, образ содержит файлы-призраки
```

**Типичная проблема:** `apt-get clean` в отдельном `RUN` не уменьшает размер слоя, потому что файлы уже зафиксированы в предыдущем слое. Правильный подход — объединять установку и очистку в один `RUN`:

```dockerfile
# ПЛОХО: мусор остался в слое установки
RUN apt-get update && apt-get install -y curl
RUN apt-get clean

# ХОРОШО: мусор удалён до фиксации слоя
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
```

### Docker Scout — рекомендации по базовому образу

```bash
# Быстрый обзор и рекомендации
docker scout quickview myapp:latest

# Сравнение с другим базовым образом
docker scout compare myapp:latest --to python:3.12-slim
```

### Просмотр размера слоев

```bash
# Просмотр размера каждого слоя
docker history myapp:latest --format "{{.Size}} {{.CreatedBy}}"
# → 7.2MB  RUN apk add --no-cache tini
# → 1.1MB  COPY package.json ./
# → 42.3MB COPY . .

# Просмотр общего размера
docker image inspect myapp:latest --format='{{.Size}}'
# → 52341234 (байты)
```
## Валидация и диагностика

### Проверка Dockerfile перед сборкой

```bash
# Встроенный линтер BuildKit
docker buildx build --check .
# → [WARNING] ...: UndefinedVar: TargetStageName is not defined as an ARG

# Просмотр outline параметров сборки
docker buildx build --call=outline .
# → TARGETPLATFORM: linux/amd64
# → TARGETOS: linux
# → TARGETARCH: amd64

# Просмотр доступных таргетов (стадий)
docker buildx build --call=targets .
```

### Проверка размера контекста

```bash
# Просмотр размера директории
du -sh .
# → 45M    .

# Просмотр размера контекста (с учётом .dockerignore)
docker build --progress=plain . 2>&1 | grep "transferring"
# → transferring context: 8.3MB done

# Сравнение ДО и ПОСЛЕ оптимизации .dockerignore
# До: 42.1MB → После: 8.3MB
```

### Проверка эффективности multi-stage

```bash
# Сравнение размеров стадий
docker buildx build --target builder -t myapp:builder .
docker buildx build -t myapp:final .

docker images myapp
# → REPOSITORY   TAG      SIZE
# → myapp        builder  1.2GB   (стадия сборки)
# → myapp        final    15MB    (финальный образ)
# → Экономия: ~99%
```

### Проверка кэша

```bash
# Просмотр использования диска кэшем
docker buildx du
# → RECLAIMABLE   SIZE
# → 2.1GB         3.4GB

# Просмотр кэша за последние 24 часа
docker buildx du --filter until=24h

# Очистка старого кэша
docker buildx prune --filter "until=72h"
```

### Проверка кэша зависимостей

```bash
# Сборка дважды — вторая должна быть быстрее
time docker build -t myapp:latest .
# → real    0m45.2s

# Изменить код, пересобрать
time docker build -t myapp:latest .
# → real    0m12.8s  (зависимости из кэша)
```

### Проверка SBOM и provenance

```bash
# Просмотр SBOM в образе
docker buildx imagetools inspect myapp:latest \
  --format '{{ json .SBOM }}' | jq '.artifacts | length'
# → 42 (количество компонентов)

# Просмотр provenance
docker buildx imagetools inspect myapp:latest \
  --format '{{ json .Provenance }}' | jq '.buildType'
# → "https://github.com/moby/buildkit/client/llb"
```
## Типичные ошибки и их решение

### Ошибка 1: Кэш не переиспользуется между сборками

**Причина:** Не настроены источники кэша или используется локальный кэш в ephemeral-окружениях (CI/CD).

```bash
# Диагностика
docker buildx ls
# → Если сборщик "default" с драйвером "docker" — кэш только локальный
```

**Решение:** Настройте удаленный кэш:

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myapp:latest .
```

### Ошибка 2: Образ слишком большой после multi-stage

**Причина:** В финальную стадию попали лишние файлы или не использовался дистрибутивный образ.

```bash
# Диагностика
dive myapp:latest
# → Проверьте каждую директорию на наличие мусора
```

**Решение:**

```dockerfile
# ПЛОХО: копируем всё из builder
FROM alpine:3.24
COPY --from=builder /app /app

# ХОРОШО: копируем только нужный артефакт
FROM alpine:3.24
COPY --from=builder /app/dist /usr/share/nginx/html
```

### Ошибка 3: `COPY --link` не ускоряет сборку

**Причина:** `COPY --link` работает только если предыдущие слои изменились. Если изменяется сам файл — слой всё равно пересобирается.

**Решение:** Используйте `COPY --link` вместе с `# syntax=docker/dockerfile:1` и правильно выстроенной последовательностью инструкций:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine AS builder
WORKDIR /app

# 1. Манифест (редко меняется)
COPY --link package.json package-lock.json ./
RUN npm ci

# 2. Код (часто меняется)
COPY --link . .
RUN npm run build
```

### Ошибка 4: Heredoc не работает

**Причина:** Отсутствует директива `# syntax` или используется устаревший синтаксис.

```dockerfile
# ПЛОХО: нет директивы syntax
RUN <<EOF
apt-get update
apt-get install -y curl
EOF

# ХОРОШО: синтаксис указан
# syntax=docker/dockerfile:1.4
RUN <<EOF
apt-get update
apt-get install -y curl
EOF
```

### Ошибка 5: Кэш apt не переиспользуется

Детальный разбор кэширования apt и решения проблемы: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

### Ошибка 6: Медленная мультиплатформенная сборка

**Причина:** Эмуляция через QEMU значительно медленнее нативной сборки.

**Решение:** Используйте кросс-компиляцию для Go/Rust:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.27-alpine AS builder
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app .
```

### Ошибка 7: Секрет попадает в слой образа

**Причина:** Секрет передан через `ENV`, `ARG` или `RUN echo`.

```dockerfile
# ПЛОХО: пароль навсегда в истории
ENV DB_PASS=secret123
RUN PGPASSWORD=$DB_PASS pg_dump ...

# ХОРОШО: секрет через BuildKit
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=db_pass \
    PGPASSWORD=$(cat /run/secrets/db_pass) pg_dump ...
```

```bash
# Запуск сборки с секретом
docker buildx build --secret id=db_pass,src=./db_pass.txt -t myapp .
```
### Ошибка 8: `docker build --check` не находит проблем

Детальный разбор встроенного линтера и `check=error=true`: **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md#практические-сценарии)**.

## Граничные случаи и ограничения

### Air-gapped среды

В средах без доступа в интернет требуется:
- Предзагрузка всех базовых образов во внутренний registry.
- Предварительная загрузка кэша пакетных менеджеров (apt, npm, pip, maven, cargo).
- Офлайн-сканирование Trivy/Grype с локальной базой уязвимостей.

### Distroless и отладка

В distroless/chiseled образах нет shell, поэтому `docker exec` недоступен. Для отладки:
- Используйте debug-версии образов: Google Distroless — тег `:debug` (BusyBox); Chainguard — `-dev`-вариант (например, `cgr.dev/chainguard/static:latest-dev`).
- Добавьте временную отладочную стадию в Dockerfile для сбора артефактов.

### Rootless Docker и buildx

В Rootless Docker (без root-прав) драйвер `docker-container` для buildx может требовать дополнительной настройки:
- Убедитесь что `subuid/subgid` настроены для пользователя.
- Используйте драйвер `docker` вместо `docker-container` если изоляция не требуется.

### Large monorepos и контекст сборки

При очень больших репозиториях (>1GB):
- Используйте `docker build --no-cache-filter=unused` для управления кэшем.
- Настройте `.dockerignore` для исключения нерелевантных директорий.
- Используйте `docker buildx build --no-cache` только при необходимости полной пересборки.

Полный разбор сборки в монорепозиториях (path-based контексты, shared base images, Bake для монорепо) — в **[Сборка в монорепозиториях](../../../CI-CD/Build_Systems/monorepo_build_systems.md)**.

### BuildKit GC и диск

При активных сборках кэш BuildKit может быстро расти:
- Настройте `builder.gc.keepStorage` в `daemon.json` (рекомендуется 10-20GB).
- Используйте `docker buildx prune --filter until=72h` в cron для автоматической очистки.
- Мониторьте использование диска через `docker buildx du`.

### Multi-platform эмуляция

QEMU-эмуляция значительно медленнее нативной сборки:
- Предпочитайте кросс-компиляцию для Go/Rust (`--platform=$BUILDPLATFORM`).
- Используйте `binfmt_misc` с поддержкой `fix-binary` для ускорения.
- Для Java/JVM используйте multi-stage с нативной платформой.

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | Всегда для компилируемых языков, желательно для интерпретируемых | Уменьшение размера образа на 90-99% |
| **Cache Mounts** | `--mount=type=cache` для пакетных менеджеров | Ускорение повторных сборок в 5-10 раз |
| **COPY --link** | Использовать для копирования файлов | Независимые слои, ускорение при обновлении базового образа |
| **Heredoc** | Использовать вместо `\` для многострочных команд | Улучшает читаемость и уменьшает ошибки |
| **.dockerignore** | Всегда создавать, исключать .git, node_modules, секреты | Уменьшение контекста сборки |
| **Удаленный кэш** | Настроить `--cache-to`/`--cache-from` для CI/CD | Ускорение сборок в CI/CD |
| **Аттестации** | Включать `--sbom` и `--provenance` для production | Безопасность и аудит |
| **Build Checks** | Использовать `docker buildx build --check` | Статический анализ перед сборкой |
| **Размер контекста** | Проверять через `du -sh .` и `--progress=plain` | Скорость передачи контекста |
| **Кросс-компиляция** | Использовать для Go/Rust вместо QEMU | Ускорение multi-platform сборки |

### Порядок инструкций в Dockerfile

```dockerfile
# 1. Версия синтаксиса (всегда первой строкой)
# syntax=docker/dockerfile:1

# 2. Базовый образ (стабильная версия, не latest)
FROM node:26-alpine AS builder

# 3. SHELL (если нужен pipefail)
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 4. WORKDIR
WORKDIR /app

# 5. Системные зависимости (кэшируются долго, меняются редко)
RUN apk add --no-cache tini

# 6. Зависимости (манифест + lock-файл)
COPY --link package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# 7. Исходный код (меняется часто)
COPY --link . .

# 8. Сборка
RUN npm run build

# 9. Финальная стадия (минимальный образ)
FROM nginx:alpine
COPY --from=builder --link /app/dist /usr/share/nginx/html

# 10. Метаданные
LABEL version="1.0" maintainer="team@example.com"

# 11. Entrypoint
ENTRYPOINT ["nginx", "-g", "daemon off;"]
```

### Чек-лист перед деплоем

- [ ] Dockerfile использует exec-form для CMD/ENTRYPOINT
- [ ] Multi-stage: финальная стадия содержит только необходимые файлы
- [ ] Cache mounts настроены для пакетных менеджеров (npm, pip, maven, cargo)
- [ ] `.dockerignore` исключает .git, node_modules, секреты, артефакты сборки
- [ ] Базовый образ использует конкретную версию (не `latest`)
- [ ] `--no-install-recommends` при установке пакетов через apt
- [ ] Кэш пакетного менеджера удалён в том же RUN (или через cache mount)
- [ ] Секреты переданы через `--mount=type=secret`, не через ENV/ARG
- [ ] `--sbom` и `--provenance` включены для production-сборок
- [ ] `docker buildx build --check` не выявил проблем
- [ ] Размер образа проверен через `dive` (efficiency > 90%)
- [ ] Удалённый кэш настроен для CI/CD (`--cache-to`/`--cache-from`)
- [ ] Кросс-компиляция используется для Go/Rust multi-platform сборок

## Дополнительная информация

### Взаимодействие с CI/CD

Для сохранения кэша между запусками в CI необходимо использовать экспортеры кэша:
- `--cache-from type=registry,ref=...`
- `--cache-to type=registry,ref=...,mode=max`
Режим `mode=max` сохраняет кэш всех промежуточных слоев, включая неиспользуемые в финальном образе стадии multi-stage.

**Общие принципы для любой CI-системы:**

```bash
# 1. Создание изолированного инстанса сборщика (рекомендуется для CI)
docker buildx create --use --driver docker-container --name ci-builder

# 2. Сборка с кэшированием и аттестациями
docker buildx build \
  --cache-from type=registry,ref=registry.example.com/cache \
  --cache-to type=registry,ref=registry.example.com/cache,mode=max \
  --sbom=true \
  --provenance=mode=max \
  --push -t registry.example.com/app:$CI_COMMIT_SHA .
```

**Ключевые рекомендации для SRE/DevOps:**
- Используйте `docker-container` драйвер для изоляции сборок в CI.
- Настройте политику очистки кэша на registry (`keepStorage` в `daemon.json`).
- Включите `--check` в пайплайн для статического анализа Dockerfile.
- Храните SBOM и provenance в registry для аудита.

### Смотрите также

- **[BuildKit в Dockerfile](../dockerfile_buildkit.md)** — глубокий разбор механизмов маунтов и LLB.
- **[Docker Buildx: Мультиплатформенность](../docker_buildx.md)** — управление инстансами сборщиков и кросс-сборка.
- **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)** — правила исключения файлов.
- **[Инструменты оптимизации: dive, Scout, hadolint](../dockerfile_optimization_tools.md)** — статический и динамический анализ образов.
- **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md)** — детальный разбор `--mount` и Heredoc.
- **[Продвижение образов в CI/CD](../../Docker_fs/images/promotion_cicd.md)** — тегирование по SHA, promotion между стадиями, canary/blue-green по дайджесту.
- **[Очистка и GC-стратегии](../../Docker_fs/cleanup_gc_strategies.md)** — `docker prune`, retention-политики, garbage collection registry.
- **[Версионирование и тегирование образов](../../Docker_registries/image_versioning_and_tagging.md)** — семантическое версионирование, immutable tags, digest pinning.
- **[Kaniko: сборка без демона](../dockerfile_kaniko.md)** — сборка образов в Kubernetes и CI без Docker-демона.
- **[Альтернативные среды выполнения и инструменты](../../alternative_runtimes_and_tools.md)** — buildah, podman, img и другие сборщики.
- **[Docker-in-Docker (DinD)](../../docker-in-docker.md)** — запуск Docker-демона внутри контейнера для CI-пайплайнов.
