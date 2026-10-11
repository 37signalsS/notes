# Docker Buildx: Мультиплатформенная сборка

**Актуально для:** Docker 24.0+ / Docker Desktop 4.38+ / Buildx v0.12+

## Определения

**Docker Buildx** — это плагин CLI, расширяющий `docker build` на основе движка BuildKit. Он предоставляет управление инстансами сборщиков (builders), мультиплатформенную сборку, расширенное кэширование, аттестации и декларативные конфигурации через **[Bake](./docker-bake.md)**.

С Docker 23.0+ команда `docker build` является алиасом для `docker buildx build`, поэтому все возможности BuildKit доступны «из коробки».

### Архитектура

```
Пользователь (CLI)
       │
       ▼
   docker buildx build
       │
       ▼
   Buildx (плагин)
       │
       ├── Управление инстансами сборщиков
       ├── Формирование LLB-графа
       ├── Параллельное выполнение этапов
       └── Экспорт артефактов
       │
       ▼
   BuildKit (движок)
       │
       ├── Кэширование слоёв
       ├── Multi-platform эмуляция/кросс-компиляция
       └── Аттестации (SBOM, Provenance)
```

### Ключевые особенности

- **Мультиплатформенность**: сборка под amd64, arm64, arm/v7, s390x и др.
- **Расширенное кэширование**: Registry, GitHub Actions Cache, S3, MinIO, локальная папка.
- **Аттестации**: SBOM и Provenance как неотделимые части образа.
- **Безопасные секреты**: передача confidential data без попадания в слои.
- **Named contexts**: переопределение базовых образов без изменения Dockerfile.
- **Build checks**: встроенный линтер Dockerfile.
- **История сборок**: трассировка OpenTelemetry, сравнение запусков, экспорт записей.

## Предварительные требования

### Программное обеспечение

- **Docker Engine** 24.0+ (рекомендуется Docker 27.0+, где `docker buildx build` является стандартным алиасом).
- **Docker Buildx** плагин (встроен в Docker Desktop; на Linux — `docker buildx install`).
- **BuildKit** включен по умолчанию в Docker 24.0+.

### Проверка установки

```bash
docker --version
# -> Docker version 27.x.x, build xxxxxxx

docker buildx version
# -> github.com/docker/buildx v0.xx.x ...

docker buildx ls
# -> NAME/NODE     DRIVER/ENDPOINT STATUS   BUILDKIT
# -> default*      docker
# ->                 default         default  v0.xx.x
```

### Создание сборщика с расширенными возможностями

Для мультиплатформенности, удаленного кэша и аттестаций требуется сборщик с драйвером `docker-container`:

```bash
docker buildx create --name multi-arch-builder --driver docker-container --use
docker buildx inspect --bootstrap
```

> **Примечание:** Сборщик `docker-container` запускается как отдельный контейнер. Это обеспечивает изоляцию, но требует дополнительных ресурсов.

## Драйверы сборщиков

| Драйвер | Описание | Использование | Ограничения |
| :--- | :--- | :--- | :--- |
| **`docker`** | BuildKit, встроенный в демон Docker | Локальная разработка | Не поддерживает multi-platform, ограниченный кэш |
| **`docker-container`** | BuildKit в выделенном контейнере | CI/CD, multi-platform | Требует bootstrap, дополнительные ресурсы |
| **`kubernetes`** | Сборщики как Pods в K8s | Масштабируемые фермы | Требует настроенный кластер |
| **`remote`** | Удаленный `buildkitd` по TCP/SSH | Удаленные сборщики | Требует сетевой настройки и аутентификации |

## Механизмы мультиплатформенности

**1. QEMU (эмуляция)**

Самый простой способ. Требует `binfmt_misc` и предустановленных эмуляторов.

```bash
docker run --privileged multiarch/qemu-user-static --reset -p yes
```

**Преимущества:** простота настройки. **Недостатки:** в 5–10 раз медленнее нативной сборки.

**2. Native Cross-compilation**

Кросс-компиляция через компилятор (Go, Rust, C++). Самый быстрый метод.

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS builder
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app .
```

**3. Native Nodes**

Несколько физических узлов с разными архитектурами в одном инстансе.

```bash
docker buildx create --name multi-arch --driver docker-container \
  --node arm64-node ssh://user@arm64-host
```

## Управление секретами и SSH

**Secrets (современный синтаксис):**

```bash
docker buildx build --secret id=npmrc,src=${HOME}/.npmrc -t myapp .
docker buildx build --secret id=api_key,env=API_KEY -t myapp .
```

В Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm install
```

**SSH Forwarding (современный синтаксис):**

```bash
docker buildx build --ssh default=$SSH_AUTH_SOCK -t myapp .
```

В Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=ssh git clone git@github.com:private/repo.git
```

## Именованные контексты (Named Contexts)

Переопределение базовых образов без изменения Dockerfile:

```bash
docker buildx build \
  --build-arg BASE_IMAGE=python:3.12-slim \
  --build-context python=docker.io/library/python:3.12-slim \
  -t myapp .
```

Для сложных сценариев с несколькими контекстами используйте **[Docker Bake](./docker-bake.md)**.

## Проверки сборки (Build Checks)

Встроенный линтер Dockerfile:

```bash
docker buildx build --check .
# -> [WARNING] ...: FromAsCasing: 'FROM ... AS' should match the casing
```

Другие методы оценки:

- `--call=build` — стандартная сборка
- `--call=check` — только проверка
- `--call=outline` — вывод всех параметров сборки
- `--call=targets` — список доступных таргетов

## Типы вывода (Output Types)

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| `docker` | Загрузка в локальный Docker | `--load` |
| `registry` | Отправка в реестр | `--push` |
| `local` | Экспорт файлов в папку | `--output type=local,dest=./dist` |
| `tar` | Экспорт в tar-архив | `--output type=tar,dest=./image.tar` |
| `oci` | Экспорт в OCI-формат | `--output type=oci,dest=./image.tar` |
| `image` | Экспорт как Docker-образ | `--output type=image,name=myapp,push=true` |

```bash
docker buildx build --load -t myapp:local .
docker buildx build --push -t registry/app:v1 .
docker buildx build --output type=local,dest=./dist .
```

> **Важно:** `--load` и `--push` не переопределяют явные выводы `type=local` и `type=tar`. Для изменения типа вывода используйте `--set` в Bake или перечислите нужные `--output`.

## Процесс работы с билдерами

### Создание и настройка инстанса

```bash
# Создание с именем и драйвером
docker buildx create --name multi-arch-builder --driver docker-container --use

# С явным указанием ноды и платформ
docker buildx create \
  --name multi-arch \
  --driver docker-container \
  --node arm64-node \
  --platform linux/arm64 \
  --use

# Инициализация (запуск контейнера с BuildKit)
docker buildx inspect --bootstrap

# Проверка статуса
docker buildx ls
```

### Параметры `docker buildx create`

| Опция | Описание |
| :--- | :--- |
| `--name` | Имя инстанса сборщика |
| `--driver` | Драйвер (`docker-container`, `kubernetes`, `remote`) |
| `--driver-opt` | Драйвер-специфичные опции (например, `network=host`) |
| `--node` | Имя ноды внутри инстанса |
| `--platform` | Фиксированные платформы для ноды |
| `--bootstrap` | Запустить сборщик после создания |
| `--buildkitd-config` | Путь к конфигу `buildkitd.toml` |
| `--buildkitd-flags` | Флаги запуска `buildkitd` |
| `--use` | Сделать инстанс активным |
| `--append` | Добавить ноду в существующий инстанс |
| `--leave` | Удалить ноду из инстанса |
| `--timeout` | Таймаут загрузки статуса (по умолчанию `20s`) |

### Верификация образов сборщика

Начиная с Buildx v0.32+, `docker-container` driver может проверять подпись тегов `moby/buildkit`:

```bash
BUILDX_DEFAULT_POLICY=1 docker buildx create --driver docker-container
```

Для доверенных (неподписанных) образов:

```bash
BUILDX_DEFAULT_POLICY=1 docker buildx create \
  --driver docker-container \
  --driver-opt allow-untrusted-image=true
```

### Удаление сборщиков

```bash
docker buildx rm multi-arch-builder
docker buildx prune -f

# Удаление всех кроме активного
docker buildx rm $(docker buildx ls -q | grep -v $(docker buildx inspect --format '{{.Name}}'))
```

### Очистка

```bash
docker image prune -f
docker buildx prune -f
docker builder prune -a -f
```

## Экспорт кэша

**Registry:**

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myapp:latest .
```

**GitHub Actions:**

```bash
docker buildx build \
  --cache-to type=gha,mode=max \
  --cache-from type=gha \
  -t myapp:latest .
```

**S3 / MinIO:**

```bash
docker buildx build \
  --cache-to type=s3,region=eu-central-1,bucket=my-cache,key=myapp \
  --cache-from type=s3,region=eu-central-1,bucket=my-cache,key=myapp \
  -t myapp:latest .
```

**Локальная папка:**

```bash
docker buildx build \
  --cache-to type=local,dest=/tmp/cache \
  --cache-from type=local,src=/tmp/cache \
  -t myapp:latest .
```

## Инспекция образов

```bash
# Просмотр манифеста multi-arch образа
docker buildx imagetools inspect myapp:latest

# Просмотр конкретного слоя
docker buildx imagetools inspect myapp:latest --format '{{ json .Manifest }}'

# Просмотр SBOM
docker buildx imagetools inspect myapp:latest --format '{{ json .SBOM }}'
```

## Создание и управление манифестами

`docker buildx imagetools create` позволяет создавать manifest list из существующих образов:

```bash
# Создание manifest list из нескольких образов
docker buildx imagetools create \
  --annotation "index:org.opencontainers.image.authors=dvdksn" \
  --tag myregistry.com/app:v1.0 \
  myregistry.com/app:linux-amd64 \
  myregistry.com/app:linux-arm64

# Дополнение существующего manifest list
docker buildx imagetools create \
  --append \
  --tag myregistry.com/app:v1.0 \
  myregistry.com/app:linux-arm/v7

# Dry-run: посмотреть результат без пуш
docker buildx imagetools create --dry-run \
  alpine@sha256:5c40b3c27b9f13c873fefb2139765c56ce97fd50230f1f2d5c91e55dec171907

# Запись метаданных созданного образа
docker buildx imagetools create \
  --tag myapp:latest \
  --metadata-file metadata.json \
  -f source1.json -f source2.json
```

## История сборок

```bash
# Список последних сборок
docker buildx history ls

# Детали конкретной сборки
docker buildx history inspect <build-id>

# Открыть запись в Docker Desktop
docker buildx history open <build-id>

# Просмотр OpenTelemetry трассы в Jaeger UI
docker buildx history trace <build-id>

# Сравнение двух сборок
docker buildx history trace --compare=<other-build-id> <build-id>

# Экспорт записи сборки
docker buildx history export <build-id> > build-record.json
```

> **Примечание:** Функция трассировки основана на OpenTelemetry и может требовать включения экспериментальных функций в Docker Desktop.

## CLI-команды и опции

### Основные команды Buildx

| Команда | Описание |
| :--- | :--- |
| `docker buildx build` | Сборка образа |
| `docker buildx create` | Создание нового сборщика |
| `docker buildx inspect` | Инспекция сборщика |
| `docker buildx ls` | Список сборщиков |
| `docker buildx rm` | Удаление сборщика |
| `docker buildx prune` | Очистка кэша и ресурсов |
| `docker buildx imagetools` | Управление манифестами |
| `docker buildx bake` | Декларативная сборка (см. **[Docker Bake](./docker-bake.md)**) |
| `docker buildx history` | История и трассировка сборок |

### Опции команды `build`

| Опция | Описание |
| :--- | :--- |
| `--platform PLATFORMS` | Целевые платформы |
| `-t, --tag TAG` | Тег образа |
| `--push` | Отправка в реестр |
| `--load` | Загрузка в локальный Docker |
| `-f, --file PATH` | Путь к Dockerfile |
| `--build-arg KEY=VALUE` | Аргументы сборки |
| `--secret ID=SRC` | Секреты (файл или env) |
| `--ssh ID=SOCK` | Проброс SSH-агента |
| `--cache-from SOURCE` | Источник кэша |
| `--cache-to DEST` | Назначение кэша |
| `--no-cache` | Отключение кэша |
| `--no-cache-filter STAGE` | Отключение кэша для конкретного stage |
| `--pull` | Обновление базовых образов |
| `--output OUTPUT` | Тип и назначение вывода |
| `--build-context NAME=PATH` | Дополнительный контекст сборки |
| `--exclude PATH` | Исключение путей из контекста |
| `--check` | Проверка Dockerfile без сборки |
| `--progress TYPE` | Тип прогресса (`auto`, `plain`, `tty`, `rawjson`, `none`) |
| `--metadata-file FILE` | Запись метаданных в файл |
| `--allow ENTITLEMENT` | Расширенные привилегии |
| `--call METHOD` | Метод оценки (`build`, `check`, `outline`, `targets`) |
| `--sbom` | Генерация SBOM |
| `--provenance` | Генерация Provenance |
| `--label KEY=VALUE` | Метаданные образа |
| `--annotation KEY=VALUE` | Аннотации OCI |
| `--network MODE` | Сетевой режим (`default`, `host`, `none`) |
| `--iidfile FILE` | Запись ID образа в файл |
| `--timeout DURATION` | Таймаут для remote builder |

## Практические сценарии

### Сценарий 1: Мультиплатформенная сборка (Go)

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS builder
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /bin/myapp main.go

FROM alpine:3.21
COPY --from=builder /bin/myapp /usr/local/bin/myapp
ENTRYPOINT ["/usr/local/bin/myapp"]
```

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t myreg.com/app:v1 --push .
```

### Сценарий 2: Build Secrets для сборки фронтенда

```dockerfile
# syntax=docker/dockerfile:1
FROM node:23-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm install
COPY . .
RUN npm run build
```

```bash
docker buildx build --secret id=npmrc,src=${HOME}/.npmrc -t my-app:safe-build .
```

### Сценарий 3: Декларативная сборка через Bake

Инструмент Bake описывает параметры сборки в HCL/YAML. Подробнее — **[Docker Bake: Декларативная оркестрация сборки](./docker-bake.md)**.

```bash
docker buildx bake
```

### Сценарий 4: Удаленное кэширование

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myregistry.com/app:v1 \
  --push .
```

### Сценарий 5: Проверка и валидация Dockerfile

```bash
docker buildx build --check .
docker buildx build --call=outline .
docker buildx build --call=targets .
```

### Сценарий 6: Экспорт артефактов

```bash
docker buildx build --output type=tar,dest=./image.tar .
docker buildx build --output type=oci,dest=./image.tar .
docker buildx build --output type=local,dest=./dist .
docker buildx build --load -t myapp:local .
```

### Сценарий 7: SSH-агент для приватных репозиториев

```bash
docker buildx build --ssh default=$SSH_AUTH_SOCK -t myapp .
```

### Сценарий 8: Многоархитектурная сборка и проверка манифеста

```bash
# 1. Создание сборщика (одноразово)
docker buildx create --name multi-arch --driver docker-container --use

# 2. Сборка и отправка
docker buildx build \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t myregistry.com/app:v1.0 \
  --push .

# 3. Проверка манифеста
docker buildx imagetools inspect myregistry.com/app:v1.0

# 4. Создание manifest list вручную
docker buildx imagetools create \
  --tag myregistry.com/app:v1.0 \
  myregistry.com/app:linux-amd64 \
  myregistry.com/app:linux-arm64
```

## Интеграция в CI/CD

### GitHub Actions

```yaml
name: Build and Push
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v4

      - name: Login to Docker Hub
        uses: docker/login-action@v4
        with:
          username: ${{ vars.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v7
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: myorg/app:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          sbom: true
          provenance: mode=max
```

### GitLab CI/CD

```yaml
image: docker:latest
services:
  - docker:dind

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""
  DOCKER_BUILDKIT: 1

stages:
  - build

build_job:
  stage: build
  script:
    - docker run --privileged multiarch/qemu-user-static --reset -p yes
    - docker buildx create --use
    - docker buildx build --platform linux/amd64,linux/arm64 \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
        --push -t $CI_REGISTRY_IMAGE/app:$CI_COMMIT_SHA .
```

### Jenkins

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'docker run --privileged multiarch/qemu-user-static --reset -p yes'
                sh 'docker buildx create --use || true'
                sh """
                    docker buildx build \
                        --platform linux/amd64,linux/arm64 \
                        --cache-from type=gha \
                        --cache-to type=gha,mode=max \
                        --push -t myregistry.com/app:${BUILD_NUMBER} .
                """
            }
        }
    }
}
```

## Разрешение проблем

### Типичные ошибки

**1. `no matching manifest for linux/arm64/v8`**

Причина: образ отсутствует для платформы.

```bash
docker buildx build --platform=linux/arm64 .
```

**2. `failed to solve: ...` при multi-arch**

Причина: нет эмуляции QEMU.

```bash
docker run --privileged multiarch/qemu-user-static --reset -p yes
```

**3. `error: cannot connect to daemon`**

Причина: Docker daemon не запущен.

```bash
sudo systemctl status docker
sudo systemctl start docker
```

**4. `permission denied` при `--ssh`**

Причина: SSH-агент не доступен или ключи не добавлены.

```bash
ssh-add -l
ssh-add ~/.ssh/id_rsa
docker buildx build --ssh default=$SSH_AUTH_SOCK .
```

**5. Медленная multi-platform сборка**

Причина: эмуляция QEMU медленная.

Решение: используйте кросс-компиляцию или физические узлы.

**6. Кэш не работает между сборками**

Причина: локальный кэш в ephemeral-окружениях.

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myapp:latest .
```

### Диагностические команды

```bash
docker buildx inspect
docker buildx ls
docker buildx build --call=outline .
docker buildx build --check .
docker buildx build --progress=plain .
docker buildx history ls
```

## Rootless режим

Buildx поддерживает rootless Docker. Для работы с `docker-container` driver в rootless режиме убедитесь, что `buildkitd` доступен в пользовательском namespace и Docker socket корректно проброшен.

```bash
# Включение rootless mode
export DOCKER_HOST=unix:///run/user/1000/docker.sock

# Проверка
docker buildx ls
```

## Лучшие практики

1. **Кросс-компиляция вместо QEMU** для поддерживаемых языков.
2. **Удаленный кэш** для всех production-сборок.
3. **`--check`** перед пушем.
4. **`--metadata-file`** для сохранения digest и SBOM.
5. **Аттестации** (`--sbom`, `--provenance`) для production-образов.
6. **Очистка** неиспользуемых сборщиков и кэша.
7. **`BUILDX_DEFAULT_POLICY=1`** для проверки подписи builder image.
8. **Историю сборок** для оптимизации медленных пайплайнов.

### Очистка

```bash
docker image prune -f
docker buildx prune -f
docker builder prune -a -f
docker buildx rm $(docker buildx ls -q | grep -v $(docker buildx inspect --format '{{.Name}}'))
```

## Границы и ограничения

- **Производительность QEMU:** в 5–10 раз медленнее нативной сборки.
- **Размер кэша:** multi-platform сборки занимают больше места.
- **Драйвер `docker`:** нет multi-platform, удаленного кэша и аттестаций.
- **Параллелизм:** зависит от BuildKit и демона Docker.
- **Количество платформ:** рекомендуется 3–5 для баланса времени и coverage.
- **Обратная совместимость:** `buildx build` может получать несовместимые изменения.
- **`--load` и `--push`:** не переопределяют `type=local` и `type=tar`.
- **Rootless:** некоторые драйверы требуют дополнительной конфигурации.
- **История сборок:** требует BuildKit с поддержкой OpenTelemetry.

## См. также

- **[BuildKit: Техническое устройство движка](./dockerfile_buildkit.md)** — LLB, кэш, аттестации.
- **[Docker Bake: Декларативная оркестрация сборки](./docker-bake.md)** — HCL/YAML конфигурации.
- **[Оптимизация сборки Docker-образов](./Docker_best_practices/build_optimization.md)** — стратегии кэширования и Multi-stage.
- **[Docker Compose: Сборка и CI/CD](./Docker_compose/docker_compose_ci_cd_testing.md)** — интеграция Buildx в Compose.
