# BuildKit: Современный движок сборки Docker

## Определения

**BuildKit** — это высокопроизводительный движок (backend) для сборки контейнерных образов, который полностью заменяет устаревший (legacy) механизм Docker. Он представляет собой оркестратор процессов сборки, преобразующий инструкции в эффективный граф выполнения.

Ключевые компоненты:
- **LLB (Low-Level Builder):** Промежуточное двоичное представление графа сборки. Это контентно-адресуемый граф зависимостей, который определяет, как данные должны трансформироваться.
- **Frontend:** Компонент, преобразующий высокоуровневое описание (Dockerfile, HCL, Buildpacks) в LLB. Фронтенды распространяются как обычные Docker-образы.
- **Buildkitd:** Фоновый демон, выполняющий сборку.
- **Buildctl:** CLI-утилита для прямого взаимодействия с `buildkitd` (без участия Docker-демона).

В современных версиях Docker (23.0+) BuildKit является стандартом по умолчанию и управляется через плагин `buildx`.

### Два режима использования

BuildKit может работать в двух режимах:

1. **Встроенный в Docker Engine** — активируется флагом `DOCKER_BUILDKIT=1` (по умолчанию с Docker 23.0+). Демон `buildkitd` встроен в Docker-демон, взаимодействие через `docker build` / `docker buildx build`.
2. **Standalone (отдельный демон)** — запуск `buildkitd` как самостоятельного процесса (в контейнере или на хосте). Взаимодействие через `buildctl`. Идеально для Kubernetes, CI/CD без Docker-демона и сред с жёсткими ограничениями безопасности.

## Предварительные требования

### Программное обеспечение

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Docker Engine** | 19.03 | 23.0+ | `docker build` = alias `docker buildx build` с 23.0 |
| **Docker Buildx** | 0.7 | 0.14+ | Встроен в Docker Desktop; для Linux может потребоваться установка |
| **buildctl** (standalone) | 0.11 | 0.16+ | Только для standalone-режима |

### Установка Buildx (Linux)

```bash
# Установка через apt (Debian/Ubuntu)
sudo apt-get update && sudo apt-get install -y docker-buildx-plugin

# Или через скрипт Docker
docker buildx install

# Проверка
docker buildx version
# -> github.com/docker/buildx v0.14.0 ...
```

### Проверка работоспособности

```bash
# Проверка, что BuildKit активен
docker version --format '{{.Server.Version}}'
# -> 27.x.x

# Проверка доступных сборщиков
docker buildx ls
# -> NAME/NODE     DRIVER/ENDPOINT STATUS   BUILDKIT
# -> default*      docker
# ->                 default         default  v0.16.x

# Быстрая проверка — сборка простого образа
echo 'FROM alpine:3.20' | docker buildx build --no-cache -
# -> [internal] load build definition from Dockerfile
# -> [internal] load .dockerignore
# -> [builder 1/2] FROM docker.io/library/alpine:3.20
# -> [builder 2/2] RUN ...
# -> exporting to image
```

### Настройка для standalone-режима

Если вы используете `buildctl` напрямую (без Docker Engine):

```bash
# Запуск buildkitd в контейнере
docker run -d --name buildkitd \
  --privileged \
  -p 1234:1234 \
  moby/buildkit:latest \
  --addr tcp://0.0.0.0:1234

# Подключение buildctl
export BUILDKIT_HOST=tcp://localhost:1234
buildctl build \
  --frontend=dockerfile.v0 \
  --local context=. \
  --local dockerfile=.
```

## Базовые концепции

### Эволюция архитектуры (LLB vs Legacy)
В отличие от старого линейного сборщика, BuildKit строит **граф зависимостей**:
- **Параллелизм:** Если стадии сборки (multi-stage) не зависят друг от друга, BuildKit запускает их одновременно.
- **Ленивые вычисления (Lazy Pulling):** BuildKit может начать сборку, скачивая только необходимые части базовых образов, или вовсе пропустить скачивание, если результат стадии уже есть в кэше.
- **Интеллектуальная инвалидация:** Кэш инвалидируется только для измененных веток графа, не затрагивая соседние независимые инструкции.

### Временные монтирования (Mounts)
BuildKit ввел концепцию «временных подключений» ресурсов в процессе сборки через флаг `--mount` в инструкции `RUN`:
- **Cache Mounts (`type=cache`):** Монтирует директорию, которая сохраняется между сборками. Идеально для кэшей пакетных менеджеров (apt, pip, npm, cargo). Данные не попадают в итоговый образ.
- **Secret Mounts (`type=secret`):** Безопасный проброс чувствительных данных (ключи, токены). Секреты монтируются в оперативную память (tmpfs) и никогда не сохраняются в истории слоев.
- **SSH Mounts (`type=ssh`):** Проброс SSH-агента хоста для доступа к приватным Git-репозиториям без копирования ключей в контейнер.
- **tmpfs Mounts (`type=tmpfs`):** Временное хранилище в оперативной памяти для промежуточных данных.
- **Bind Mounts (`type=bind`):** Монтирование директорий хоста в процесс сборки (только для `security.insecure` entitlement).

### Декларативная безопасность
BuildKit поддерживает **Entitlements** — расширенные разрешения, которые необходимо явно запрашивать при сборке:
- `network.host`: Доступ к сетевому стеку хоста.
- `security.insecure`: Разрешение потенциально опасных операций (требует специальной настройки демона).

### Аттестации (Attestations)
BuildKit поддерживает генерацию аттестаций — метаданных о составе и provenance образа:
- **SBOM (Software Bill of Materials):** Список всех компонентов в образе (пакеты, библиотеки, зависимости).
- **Provenance:** Информация о том, как был собран образ (кто, где, когда, из какого исходного кода).

## Техническая архитектура

### Директива # syntax
Первая строка Dockerfile определяет версию используемого фронтенда:
```dockerfile
# syntax=docker/dockerfile:1
```
Это позволяет использовать новые функции (например, новые типы маунтов) мгновенно, не дожидаясь обновления версии самого Docker Engine на серверах.

### Управление кэшем (Backends)
BuildKit поддерживает экспорт кэша в различные хранилища:
- **Inline:** Кэш встраивается прямо в образ (стандарт Docker Hub).
- **Registry:** Кэш пушится как отдельный манифест (идеально для `mode=max`).
- **Local:** Кэш сохраняется в директорию на хосте.
- **GHA / S3 / AzBlob:** Специализированные бэкенды для облачных сред (GitHub Actions, AWS, Azure).

### Garbage Collection

BuildKit автоматически очищает неиспользуемые кэшированные слои. Параметры GC настраиваются через `buildkitd.toml`:

```toml
# /etc/buildkit/buildkitd.toml
[worker.oci]
  gc = true
  gckeepBytes = 10737418240  # 10 GB
  gcReservedSpace = 2147483648  # 2 GB

[[worker.oci.gcpolicy]]
  keepBytes = 5368709120  # 5 GB
  keepDuration = 604800  # 7 дней (в секундах)
  filters = ["type==source.local", "type==exec.cachemount"]
```

Для Docker-integrated BuildKit GC настраивается через `daemon.json`:

```json
{
  "builder": {
    "gc": {
      "enabled": true,
      "policy": [
        {
          "keepBytes": 10737418240,
          "keepDuration": 604800,
          "filters": ["type==source.local", "type==exec.cachemount"]
        }
      ]
    }
  }
}
```

## CLI reference

### buildctl (standalone BuildKit)

`buildctl` — прямой CLI для взаимодействия с `buildkitd` без Docker-демона.

#### Основные команды

| Команда | Описание |
| :--- | :--- |
| `buildctl build` | Сборка образа |
| `buildctl prune` | Очистка кэша |
| `buildctl debug info` | Информация о демоне |
| `buildctl debug workers` | Список воркеров |
| `buildctl du` | Использование диска кэшем |

#### Параметры buildctl build

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--frontend` | Используемый фронтенд | `--frontend=dockerfile.v0` |
| `--local context` | Контекст сборки | `--local context=/workspace` |
| `--local dockerfile` | Директория Dockerfile | `--local dockerfile=/workspace` |
| `--output` | Экспорт результата | `--output type=image,name=reg/app:v1,push=true` |
| `--opt` | Опции фронтенда | `--opt target=builder` |
| `--export-cache` | Экспорт кэша | `--export-cache type=registry,ref=reg/cache` |
| `--import-cache` | Импорт кэша | `--import-cache type=registry,ref=reg/cache` |
| `--secret` | Проброс секретов | `--secret id=mysecret,src=./secret.txt` |
| `--ssh` | Проброс SSH | `--ssh default` |
| `--detach` | Фоновый режим | `--detach=true` |

#### Примеры buildctl

```bash
# Базовая сборка
buildctl build \
    --frontend=dockerfile.v0 \
    --local context=. \
    --local dockerfile=. \
    --output type=image,name=myreg.com/app:v1,push=true

# Сборка с кэшированием
buildctl build \
    --frontend=dockerfile.v0 \
    --local context=. \
    --local dockerfile=. \
    --export-cache type=registry,ref=myreg.com/cache:latest \
    --import-cache type=registry,ref=myreg.com/cache:latest \
    --output type=image,name=myreg.com/app:v1,push=true

# Сборка целевой стадии multi-stage
buildctl build \
    --frontend=dockerfile.v0 \
    --local context=. \
    --local dockerfile=. \
    --opt target=runtime \
    --output type=image,name=myreg.com/app:v1,push=true

# Очистка кэша
buildctl prune --all
```

### docker buildx build (Docker-integrated)

Основные флаги `docker buildx build`:

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `--platform` | Целевые платформы | `--platform linux/amd64,linux/arm64` |
| `--push` | Отправка в реестр | `--push -t reg/app:v1` |
| `--load` | Загрузка в локальный Docker | `--load -t app:local` |
| `--cache-from` | Источник кэша | `--cache-from type=registry,ref=reg/cache` |
| `--cache-to` | Экспорт кэша | `--cache-to type=registry,ref=reg/cache,mode=max` |
| `--secret` | Проброс секретов | `--secret id=token,src=./token.txt` |
| `--ssh` | Проброс SSH | `--ssh default=$SSH_AUTH_SOCK` |
| `--build-arg` | Аргументы сборки | `--build-arg VERSION=1.0` |
| `--target` | Целевая стадия | `--target builder` |
| `--no-cache` | Отключение кэша | `--no-cache` |
| `--sbom` | Генерация SBOM | `--sbom=true` |
| `--provenance` | Генерация provenance | `--provenance=mode=max` |
| `--check` | Линтер Dockerfile | `--check` |
| `--output` | Экспорт результата | `--output type=local,dest=./dist` |
| `--label` | Метаданные образа | `--label version=1.0` |
| `--metadata-file` | Запись метаданных в файл | `--metadata-file=meta.json` |

## Переменные окружения

| Переменная | Описание |
| :--- | :--- |
| `DOCKER_BUILDKIT` | Активация BuildKit (1 = включен, по умолчанию с Docker 23.0+) |
| `BUILDKIT_HOST` | Адрес удалённого `buildkitd` для `buildctl` (например, `tcp://localhost:1234`) |
| `BUILDKIT_PROGRESS` | Формат прогресса: `auto`, `plain`, `tty` (по умолчанию `auto`) |
| `BUILDKIT_EXPERIMENTAL` | Включение экспериментальных функций (`1` = включено) |
| `DOCKER_CONFIG` | Путь к директории конфигурации Docker (по умолчанию `~/.docker`) |
| `BUILDKIT_DOCKER_DRIVER_DUMP` | Дамп LLB-графа для отладки (`1` = включено) |
| `SSH_AUTH_SOCK` | Путь к сокету SSH-агента (для `--ssh default`) |

## Сравнение механизмов сборки

| Критерий | Legacy Builder | BuildKit (buildx) | Kaniko |
| :--- | :--- | :--- | :--- |
| **Параллелизм** | Нет | Нативный (LLB) | Последовательно |
| **Монтирование кэша** | Нет | Да (`--mount`) | Игнорируется |
| **Секреты** | Через `ARG` (небезопасно) | Да (`type=secret`) | Поддерживается |
| **Аттестации** | Нет | SBOM и Provenance | Нет |
| **Multi-arch** | Последовательно | Одновременно | Ограниченно |
| **Демон Docker** | Нужен | Не нужен (standalone) | Не нужен |
| **Привилегии** | Нужны | Rootless (standalone) | Не нужны |
| **BuildKit функции** | Нет | Полная поддержка | Игнорируются |
| **Совместимость Dockerfile** | 100% | Высокая (~99%) | Средняя (~95%) |
| **Multi-stage** | Последовательно | Параллельно | Последовательно |
| **Рекомендуемый сценарий** | Устаревшие системы | CI/CD, production | Kubernetes (restricted PSS) |

## Практические сценарии

### Сценарий 1: Глубокое кэширование зависимостей (Cache Mount)
Ускорение сборки Go-приложения в десятки раз при повторных запусках.

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
# Кэшируем модули Go на хосте сборщика
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .
# Кэшируем результат компиляции
RUN --mount=type=cache,target=/root/.cache/go-build \
    go build -o /app/main .
```

### Сценарий 2: Использование секретов без следов в истории
Передача токена для скачивания приватных зависимостей.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim
RUN --mount=type=secret,id=pip_config,target=/root/.pip/pip.conf \
    pip install --no-cache-dir private-package
```
Команда запуска:
```bash
docker build --secret id=pip_config,src=./secrets/pip.conf -t app:v1 .
```

### Сценарий 3: Сборка с аттестациями (SBOM)
Автоматическая генерация состава образа для аудита безопасности.

```bash
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --push -t myreg.com/app:v1 .
```

### Сценарий 4: Прямое использование buildctl
Для сред, где нет Docker-демона (например, чистый Kubernetes).

```bash
buildctl build \
    --frontend=dockerfile.v0 \
    --local context=. \
    --local dockerfile=. \
    --output type=image,name=myreg.com/app:v1,push=true
```

### Сценарий 5: Кэширование npm зависимостей
Ускорение повторных сборок Node.js проектов за счёт кэширования `node_modules`.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
# Кэшируем node_modules — при изменении только package.json слой пересоздаётся
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
```

```bash
docker buildx build \
  --cache-from type=local,src=/tmp/.buildx-cache \
  --cache-to type=local,dest=/tmp/.buildx-cache,mode=max \
  -t myapp:latest .
```

### Сценарий 6: Мультиплатформенная сборка (linux/amd64 + linux/arm64)

```bash
# Создание сборщика с поддержкой multi-platform
docker buildx create --name multi-arch --driver docker-container --use
docker buildx inspect --bootstrap

# Сборка под две архитектуры
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myreg.com/app:latest \
  --push .
```

### Сценарий 7: Сборка с SSH-агентом (приватные репозитории)

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.24-alpine
WORKDIR /src
# Подключаем SSH-агент для доступа к приватным модулям Go
RUN --mount=type=ssh \
    apk add --no-cache git && \
    git clone git@github.com:private/repo.git
```

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
docker buildx build --ssh default=$SSH_AUTH_SOCK -t app:latest .
```

### Сценарий 8: Сборка с именованными контекстами (Named Contexts)

Переопределение базового образа без изменения Dockerfile:

```bash
docker buildx build \
  --build-context baseimage=myreg.com/custom-base:latest \
  --build-context src=./my-src \
  -t myapp:latest .
```

В Dockerfile:

```dockerfile
FROM baseimage
COPY --from=src /app /app
```

## Интеграция в CI/CD

### GitHub Actions

```yaml
name: Build with BuildKit
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: myorg/app:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64,linux/arm64
```

### GitLab CI

```yaml
build:
  stage: build
  image: docker:27
  services:
    - docker:29.8-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker buildx create --use --driver docker-container
    - docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
        --push -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
```

### Jenkins Pipeline

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh '''
                    docker buildx build \
                      --cache-from type=local,src=/tmp/.buildx-cache \
                      --cache-to type=local,dest=/tmp/.buildx-cache,mode=max \
                      --load -t myapp:${BUILD_NUMBER} .
                '''
            }
        }
        stage('Test') {
            steps {
                sh "docker run --rm myapp:${BUILD_NUMBER} npm test"
            }
        }
        stage('Push') {
            steps {
                sh "docker push myapp:${BUILD_NUMBER}"
            }
        }
    }
}
```

## Разрешение проблем

### Типичные ошибки

**1. `error: docker exporter does not currently support exporting to the local image`**

Причина: Используется драйвер `docker-container`, который не может напрямую загружать образы в локальный Docker.

Решение: Используйте флаг `--load` для драйвера `docker` или `--push` для `docker-container`:

```bash
# Для локальной загрузки (драйвер docker)
docker buildx build --load -t app:local .

# Для отправки в реестр (драйвер docker-container)
docker buildx build --push -t reg/app:v1 .
```

**2. `ERROR: failed to solve: mount cache: permission denied`**

Причина: Нет прав на запись в директорию кэша.

Решение: Убедитесь, что директория кэша доступна для записи:

```bash
mkdir -p /tmp/.buildx-cache
chmod -R 777 /tmp/.buildx-cache
```

**3. `error: multiple platforms is only supported with a containerd image store`**

Причина: Multi-platform сборка требует containerd image store.

Решение: Включите containerd в `daemon.json`:

```json
{
  "features": {
    "containerd-snapshotter": true
  }
}
```

**4. `ERROR: failed to push: unauthorized`**

Причина: Отсутствуют credentials для реестра.

Решение: Выполните авторизацию перед сборкой:

```bash
docker login myreg.com
# Или через --secret
docker buildx build \
  --secret id=dockerconfig,json=$HOME/.docker/config.json \
  --push -t myreg.com/app:v1 .
```

**5. Медленная мультиплатформенная сборка**

Причина: Эмуляция архитектуры через QEMU без кэширования.

Решение: Настройте кэш и используйте нативные билдеры:

```bash
# Использование нативных билдеров для разных архитектур
docker buildx create --name multi-arch \
  --driver docker-container \
  --driver-opt network=host \
  --use

# Кэширование для ускорения
docker buildx build \
  --cache-from type=registry,ref=reg/cache \
  --cache-to type=registry,ref=reg/cache,mode=max \
  --platform linux/amd64,linux/arm64 \
  -t reg/app:v1 --push .
```

**6. `ERROR: Max agent workers exceeded`**

Причина: Превышено максимальное количество параллельных воркеров BuildKit.

Решение: Увеличьте лимит в конфигурации `buildkitd.toml`:

```toml
[worker.oci]
  max-parallelism = 8
```

### Диагностические команды

```bash
# Проверка статуса сборщика
docker buildx ls

# Просмотр логов BuildKit (docker-container driver)
docker logs $(docker ps -q --filter "name=buildkit_buildkitd" | head -1)

# Очистка кэша
docker buildx prune --all

# Просмотр дискового использования кэша
docker buildx du

# Вывод LLB-графа для отладки
DOCKER_BUILDKIT_DUMPl=1 docker buildx build -t app . 2>&1 | head -50
```

## Лучшие практики

### Структура Dockerfile

```dockerfile
# 1. Всегда указывайте версию синтаксиса
# syntax=docker/dockerfile:1

# 2. Используйте multi-stage для минимизации размера образа
FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /bin/app .

# 3. Финальная стадия — минимальный образ
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /bin/app /app
ENTRYPOINT ["/app"]
```

### Рекомендации

1. **Используйте Cache Mounts** для пакетных менеджеров (apt, pip, npm, cargo, go mod).
2. **Настройте Garbage Collection** чтобы предотвратить бесконтрольный рост дискового пространства.
3. **Используйте `--cache-from` и `--cache-to`** для удалённого кэширования в CI/CD.
4. **Включайте `--sbom` и `--provenance`** для production-сборок.
5. **Используйте `.dockerignore`** для исключения ненужных файлов из контекста сборки.
6. **Проверяйте Dockerfile перед сборкой** через `docker buildx build --check .`
7. **Используйте `--metadata-file`** для записи информации о сборке в CI/CD.
8. **Для multi-platform** создавайте выделенных сборщиков с драйвером `docker-container`.

### Очистка

```bash
# Очистка неиспользуемых кэшированных слоёв
docker buildx prune

# Полная очистка кэша
docker buildx prune --all

# Очистка остановленных сборщиков
docker buildx rm multi-arch-builder

# Очистка дискового пространства
docker system prune -a --volumes
```

## Известные проблемы и ограничения

### Проблемы совместимости

- **`RUN --mount=type=cache`** — требует `# syntax=docker/dockerfile:1` в начале Dockerfile. Без этой директивы инструкция игнорируется или вызывает ошибку.
- **Multi-platform без containerd** — требует включённого `containerd-snapshotter` в `daemon.json` для Docker 25+.
- **Кэширование в Docker Desktop** —有些 бэкенды кэша (GHA, S3) могут работать нестабильно в Docker Desktop из-за ограничений виртуальной сети.

### Ограничения производительности

- **QEMU-эмуляция** значительно медленнее нативной сборки. Для регулярных multi-platform сборок рекомендуется использовать нативные билдеры (отдельные машины/контейнеры для каждой архитектуры).
- **Кэширование через Registry** добавляет накладные расходы на сеть. При частых сборках рассмотрите `local` или `gha` бэкенд.

### Устаревшие функции

- **`DOCKER_BUILDKIT=0`** — отключение BuildKit рекомендуется только для отладки. Legacy Builder будет удалён в будущих версиях Docker.
- **`docker build` без `buildx`** — с Docker 23.0+ является псевдонимом для `docker buildx build`.

## См. также

- **[Docker Buildx: Мультиплатформенность](./docker_buildx.md)** — управление инстансами сборщиков.
- **[Docker Bake: Декларативная сборка](./docker-bake.md)** — HCL/YAML конфигурации.

**Глубокое изучение:**
- **[BuildKit Secrets](../../Vault/guides/vault_docker_integration.md)** — секреты в сборке. В Docker: `--mount=type=secret,id=mysecret` для передачи паролей/ключей без попадания в слои образа, совместимость с Vault Agent.
- **[Cache Mounts](../../Linux/Core/kernel/psi.md)** — кэширование зависимостей. В Docker: `--mount=type=cache,target=/root/.cache/pip` для ускорения pip install, `--mount=type=cache,target=/go/pkg/mod` для Go модулей.