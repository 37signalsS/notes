# Docker Buildx: Мультиплатформенная сборка

## Определения

**Docker Buildx** — это плагин командной строки (CLI), расширяющий возможности стандартной команды `docker build` с помощью движка **[BuildKit](./dockerfile_buildkit.md)**. Он является основным инструментом для создания современных пайплайнов сборки, поддерживающим изоляцию процессов сборки в независимых инстансах (builders).

В современных версиях Docker (23.0+) команда `docker build` является псевдонимом (alias) для `docker buildx build`. Это означает, что все улучшения BuildKit доступны «из коробки» без явного вызова Buildx.

### Архитектура

Buildx выступает прослойкой между пользовательским интерфейсом (CLI) и ядром сборки BuildKit:

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
       ├── Формирование LLB-графа (представление Dockerfile)
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

- **Мультиплатформенность**: Одновременная сборка под несколько архитектур (amd64, arm64, arm/v7, s390x и др.).
- **Расширенное управление кэшем**: Экспорт кэша в Registry, GitHub Actions Cache, S3, локальную папку и др.
- **Поддержка аттестаций**: Генерация SBOM и Provenance как неотделимых частей образа.
- **Безопасная работа с секретами**: Передача конфиденциальных данных без попадания в слои образа.
- **Декларативные конфигурации**: Использование инструмента **[Bake](./docker-bake.md)** для описания сборки в HCL/YAML/JSON файлах.
- **Встроенные проверки**: Линтер Dockerfile для обнаружения проблем перед сборкой.
- **Named contexts**: Переопределение базовых образов без изменения Dockerfile.

## Предварительные требования

### Программное обеспечение

- **Docker Engine** версии 19.03 или новее (рекомендуется Docker 23.0+, где `docker buildx build` является стандартным алиасом)
- **Docker Buildx** плагин (встроен в Docker Desktop; для Linux может потребоваться отдельная установка)
- **BuildKit** (встроен в Docker Engine с версии 23.0+)

### Проверка установки

```bash
# Проверка версии Docker
docker version --format '{{.Server.Version}}'
# -> 27.x.x

# Проверка версии Buildx
docker buildx version
# -> github.com/docker/buildx v0.xx.x ...

# Проверка доступных сборщиков
docker buildx ls
# -> NAME/NODE     DRIVER/ENDPOINT STATUS   BUILDKIT
# -> default*      docker
# ->                 default         default  v0.xx.x
```

### Создание сборщика с расширенными возможностями

Для использования всех возможностей BuildKit (мультиплатформенность, удаленный кэш и т.д.) необходимо создать сборщик с драйвером `docker-container`:

```bash
# Создание и активация нового сборщика
docker buildx create --name multi-arch-builder --driver docker-container --use
# -> multi-arch-builder

# Инициализация (запуск контейнера с BuildKit)
docker buildx inspect --bootstrap
# -> [+] Building 0.7s (1/1) FINISHED
# -> => [internal] booting buildkit
# => => pulling image moby/buildkit:latest
# => => creating container buildx_buildkit_multi-arch-builder0

# Проверка статуса
docker buildx ls
# -> NAME/NODE              DRIVER/ENDPOINT STATUS   BUILDKIT
# -> multi-arch-builder*    docker-container
# ->   multi-arch-builder0  default         running  v0.xx.x
# -> default                docker
# ->   default              default         running  v0.xx.x
```

> **Примечание:** Сборщик с драйвером `docker-container` запускается как отдельный контейнер. Это обеспечивает изоляцию, но требует дополнительных ресурсов (CPU, RAM, дисковое пространство для образов сборщика).

## Основные концепции

### Драйверы сборщиков

Драйвер определяет среду, в которой работает BuildKit, и доступный функционал.

| Драйвер | Описание | Использование | Ограничения |
| :--- | :--- | :--- | :--- |
| **`docker`** | Использует BuildKit, встроенный в демон Docker | Локальная разработка, быстрые сборки | Не поддерживает multi-platform, ограниченный кэш |
| **`docker-container`** | Запускает BuildKit в выделенном контейнере | CI/CD, multi-platform сборка | Требует bootstrap, дополнительные ресурсы |
| **`kubernetes`** | Развертывает сборщики как Pods в кластере K8s | Масштабируемые фермы сборки | Требует настроенный кластер |
| **`remote`** | Подключается к удаленному `buildkitd` по TCP/SSH | Удаленные сборщики, разделяемые команды | Требует настройки сети и аутентификации |

### Механизмы мультиплатформенности

Buildx поддерживает три способа сборки для разных архитектур:

**1. QEMU (Эмуляция)**
Самый простой способ. Позволяет запускать бинарные файлы одной архитектуры на другой через `binfmt_misc`. Требует предустановленных эмуляторов (в Docker Desktop они встроены).

```bash
# Регистрация эмуляторов (Linux, если не установлены)
docker run --privileged multiarch/qemu-user-static --reset -p yes
```

**Преимущества:** Простота настройки, не требует изменения Dockerfile.
**Недостатки:** Значительное замедление сборки (в 5-10 раз медленнее нативной сборки).

**2. Native Cross-compilation**
Использование возможностей компилятора (Go, Rust, C++) для создания бинарного файла под целевую архитектуру без выполнения кода этой архитектуры во время сборки. Самый быстрый метод.

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app .
```

**Преимущества:** Максимальная скорость, нативная производительность компиляции.
**Недостатки:** Требует поддержки кросс-компиляции в Dockerfile.

**3. Native Nodes**
Использование нескольких физических узлов с разными архитектурами, объединенных в один инстанс сборщика.

```bash
# Добавление удаленного узла с ARM64
docker buildx create --name multi-arch --driver docker-container \
  --node arm64-node ssh://user@arm64-host

# Сборка будет автоматически распределена по узлам
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest .
```

**Преимущества:** Максимальная производительность, нативная сборка без эмуляции.
**Недостатки:** Требует физического доступа к узлам разных архитектур.

### Управление секретами и SSH

Buildx позволяет безопасно передавать конфиденциальные данные в процесс сборки без попадания их в слои образа:

**Secrets:**

```bash
# Передача секрета через файл
docker buildx build --secret id=npmrc,src=$HOME/.npmrc -t myapp .

# Передача секрета через переменную окружения
docker buildx build --secret id=api_key,src=API_KEY -t myapp .
```

В Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm install
```

**SSH Forwarding:**

```bash
# Проброс SSH-агента хоста
docker buildx build --ssh default=$SSH_AUTH_SOCK -t myapp .
```

В Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=ssh git clone git@github.com:private/repo.git
```

### Именованные контексты (Named Contexts)

Позволяют переопределять базовые образы или контексты сборки без изменения Dockerfile:

```bash
# Переопределение базового образа
docker buildx build \
  --build-arg BASE_IMAGE=python:3.12-slim \
  --build-context python=docker.io/library/python:3.12-slim \
  -t myapp .
```

В Dockerfile:

```dockerfile
FROM base AS runtime
# Будет использовать переопределенный образ вместо дефолтного base image
```

### Проверки сборки (Build Checks)

Buildx включает встроенный линтер Dockerfile, который анализирует инструкции перед началом сборки и выдает предупреждения о потенциальных проблемах:

```bash
# Проверка Dockerfile на наличие проблем
docker buildx build --check .
# -> [WARNING] ...: FromAsCasing: 'FROM ... AS' should match the casing of the FROM statement
# -> [WARNING] ...: UndefinedVar: TargetStageName is not defined as an ARG in Dockerfile
```

Типичные проверки:
- Использование `latest` вместо конкретных версий
- Отсутствие `--no-install-recommends` в `apt`
- Неправильный порядок инструкций (COPY до установки зависимостей)
- Неиспользуемые или неопределённые ARG/ENV

### Типы вывода (Output Types)

Buildx поддерживает различные типы вывода собранных образов:

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| `docker` | Загрузка в локальный Docker (по умолчанию) | `--load` или `--output type=docker` |
| `registry` | Отправка в Docker Registry | `--push` или `--output type=registry` |
| `local` | Экспорт файлов в локальную папку | `--output type=local,dest=./dist` |
| `tar` | Экспорт в tar-архив | `--output type=tar,dest=./image.tar` |
| `oci` | Экспорт в OCI-формат | `--output type=oci,dest=./image.tar` |
| `image` | Экспорт как Docker-образ | `--output type=image,name=myapp,push=true` |

```bash
# Примеры использования
docker buildx build --load -t myapp:local .           # Локальная загрузка
docker buildx build --push -t registry/app:v1 .       # Отправка в реестр
docker buildx build --output type=local,dest=./dist .  # Экспорт файлов
```

## Процесс работы с билдерами

### Создание и настройка инстанса

Для использования всех возможностей BuildKit необходимо создать и активировать новый инстанс:

1. **Создание билдера с драйвером контейнера:**
   ```bash
   docker buildx create --name multi-arch-builder --driver docker-container --use
   ```
2. **Инициализация:**
   ```bash
   docker buildx inspect --bootstrap
   ```
   *Результат: Будет запущен контейнер с `moby/buildkit`.*
3. **Проверка статуса:**
   ```bash
   docker buildx ls
   ```

### Удаление сборщиков

```bash
# Удаление конкретного сборщика
docker buildx rm multi-arch-builder

# Удаление всех неиспользуемых сборщиков
docker buildx prune -f
```

### Экспорт кэша

Buildx позволяет выносить кэш за пределы хоста сборки, что критично для CI/CD:

**Registry:**

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp \
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

### Инспекция образов

```bash
# Просмотр манифеста multi-arch образа
docker buildx imagetools inspect myapp:latest

# Просмотр конкретного слоя
docker buildx imagetools inspect myapp:latest --format '{{ json .Manifest }}'

# Просмотр SBOM в образе
docker buildx imagetools inspect myapp:latest --format '{{ json .SBOM }}'
```

## CLI-команды и опции

### Основные команды Buildx

| Команда | Описание |
| :--- | :--- |
| `docker buildx build` | Сборка образа |
| `docker buildx create` | Создание нового сборщика |
| `docker buildx inspect` | Инспекция сборщика |
| `docker buildx ls` | Вывод списка всех сборщиков |
| `docker buildx rm` | Удаление сборщика |
| `docker buildx prune` | Очистка кэша и неиспользуемых ресурсов |
| `docker buildx imagetools` | Управление манифестами и метаданными образов |
| `docker buildx bake` | Декларативная сборка (см. **[Docker Bake](./docker-bake.md)**) |

### Опции команды `build`

| Опция | Описание |
| :--- | :--- |
| `--platform PLATFORMS` | Целевые платформы (например, `linux/amd64,linux/arm64`) |
| `-t, --tag TAG` | Тег образа (можно указать несколько раз) |
| `--push` | Отправить образ в реестр после сборки |
| `--load` | Загрузить образ в локальный Docker (по умолчанию для одной платформы) |
| `-f, --file PATH` | Путь к Dockerfile |
| `--build-arg KEY=VALUE` | Передача аргументов сборки |
| `--secret ID=VALUE` | Передача секретов |
| `--ssh ID=SOCK` | Проброс SSH-агента |
| `--cache-from SOURCE` | Источник кэша (можно указать несколько раз) |
| `--cache-to DEST` | Назначение кэша |
| `--no-cache` | Отключение использования кэша |
| `--pull` | Принудительное обновление базовых образов |
| `--output OUTPUT` | Тип и назначение вывода |
| `--check` | Проверка Dockerfile без реальной сборки |
| `--progress TYPE` | Тип вывода прогресса (`auto`, `plain`, `tty`, `rawjson`) |
| `--metadata-file FILE` | Запись метаданных сборки в файл |
| `--allow ENTITLEMENT` | Предоставление расширенных привилегий |
| `--call METHOD` | Метод оценки сборки (`build`, `check`, `outline`, `targets`) |
| `--sbom` | Генерация SBOM-аттестации |
| `--provenance` | Генерация Provenance-аттестации |
| `--label KEY=VALUE` | Метаданные образа |
| `--network MODE` | Сетевой режим (`default`, `host`, `none`) |
| `--iidfile FILE` | Запись ID образа в файл |
| `--annotation KEY=VALUE` | Аннотации OCI |

### Примеры использования

```bash
# Сборка multi-platform образа и отправка в реестр
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myregistry.com/app:v1.0 \
  --push .

# Сборка с кэшированием из GitHub Actions
docker buildx build \
  --cache-from type=gha \
  --cache-to type=gha,mode=max \
  -t myapp:latest .

# Сборка с аттестациями
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  -t myapp:secure .

# Сборка и экспорт метаданных
docker buildx build \
  --metadata-file build-metadata.json \
  -t myapp:latest .

# Проверка Dockerfile без реальной сборки
docker buildx build --check .

# Сборка с расширенными привилегиями
docker buildx build --allow network.host --allow security.insecure .
```

### Паттерн-матчинг для переопределения

При работе с Bake и несколькими таргетами поддерживается паттерн-матчинг:

```bash
# Переопределение аргумента для всех таргетов, начинающихся на "frontend"
docker buildx bake --set frontend*.args.NODE_VERSION=20

# Переопределение платформы для всех таргетов
docker buildx bake --set *.platform=linux/arm64

# Переопределение тега с дополнением (не заменой)
docker buildx bake --set app.tags+=myorg/app:hotfix
```

## Практические сценарии

### Сценарий 1: Эффективная мультиплатформенная сборка (Go)

Использование кросс-компиляции вместо медленной эмуляции.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder

# Автоматически заполняются BuildKit
ARG TARGETOS TARGETARCH 
WORKDIR /src
COPY . .

# Компиляция под целевую платформу
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -o /bin/myapp main.go

FROM alpine:3.21
COPY --from=builder /bin/myapp /usr/local/bin/myapp
ENTRYPOINT ["/usr/local/bin/myapp"]
```

**Запуск сборки:**
```bash
docker buildx build --platform linux/amd64,linux/arm64 -t myreg.com/app:v1 --push .
```

### Сценарий 2: Использование Build Secrets для сборки фронтенда

Передача NPM токена без риска его утечки.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:23-alpine AS builder
WORKDIR /app
COPY package*.json ./
# Монтируем секрет во время установки зависимостей
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm install
COPY . .
RUN npm run build
```

**Запуск сборки:**
```bash
docker buildx build --secret id=npmrc,src=$HOME/.npmrc -t my-app:safe-build .
```

### Сценарий 3: Декларативная сборка через Bake

Инструмент `bake` позволяет описать параметры сборки в HCL или YAML файлах, что удобнее длинных CLI команд. Поддерживает параллелизм, матричные сборки и наследование.

Подробное руководство см. в разделе **[Docker Bake: Декларативная оркестрация сборки](./docker-bake.md)**.

**Запуск:** `docker buildx bake`

### Сценарий 4: Сборка с удаленным кэшированием

Настройка кэширования для ускорения повторных сборок в CI/CD:

```bash
# Сборка с кэшированием в Docker Registry
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myregistry.com/app:v1 \
  --push .

# Сборка с кэшированием в GitHub Actions Cache
docker buildx build \
  --cache-to type=gha,mode=max \
  --cache-from type=gha \
  -t myapp:latest \
  --push .
```

### Сценарий 5: Сборка с проверками и валидацией Dockerfile

Использование встроенного линтера для обнаружения проблем перед сборкой:

```bash
# Проверка Dockerfile на наличие проблем
docker buildx build --check .
# -> [WARNING] ...: FromAsCasing: 'FROM ... AS' should match the casing of the FROM statement

# Просмотр outline всех параметров сборки
docker buildx build --call=outline .

# Просмотр списка доступных таргетов
docker buildx build --call=targets .
```

### Сценарий 6: Экспорт артефактов без сохранения в реестр

Экспорт собранных артефактов в файловую систему:

```bash
# Экспорт в tar-архив
docker buildx build --output type=tar,dest=./image.tar .

# Экспорт в OCI-формат
docker buildx build --output type=oci,dest=./image.tar .

# Экспорт файлов в папку
docker buildx build --output type=local,dest=./dist .

# Локальная загрузка в Docker
docker buildx build --load -t myapp:local .
```

### Сценарий 7: Сборка с SSH-агентом для доступа к приватным репозиториям

```bash
# Проброс SSH-агента хоста внутрь контейнера сборки
docker buildx build --ssh default=$SSH_AUTH_SOCK -t myapp .

# В Dockerfile:
# syntax=docker/dockerfile:1
RUN --mount=type=ssh git clone git@github.com:private/repo.git
```

### Сценарий 8: Многоархитектурная сборка и публикация

Полный цикл сборки multi-platform образа с отправкой в реестр и проверкой:

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
# -> Name:      myregistry.com/app:v1.0
# -> MediaType: application/vnd.docker.distribution.manifest.list.v2+json
# -> Digest:    sha256:...
# -> Platform:
# ->   - Architecture: amd64
# ->     Os: linux
# ->   - Architecture: arm64
# ->     Os: linux
# ->   - Architecture: arm
# ->     Os: linux
# ->     Variant: v7

# 4. Проверка SBOM (если включены аттестации)
docker buildx imagetools inspect myregistry.com/app:v1.0 \
  --format '{{ json .SBOM }}' | jq .
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
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
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
    # Установка QEMU для multi-platform сборки
    - docker run --privileged multiarch/qemu-user-static --reset -p yes
    # Создание сборщика
    - docker buildx create --use
    # Сборка и отправка
    - docker buildx build --platform linux/amd64,linux/arm64
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max
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

**1. Ошибка: `no matching manifest for linux/arm64/v8`**

Причина: Образ отсутствует для запрашиваемой платформы.

Решение: Укажите нужную платформу явно:

```bash
docker buildx build --platform=linux/arm64 .
# Или при запуске/вытягивании:
docker run --platform=linux/arm64 myapp:latest
```

**2. Ошибка: `failed to solve: ...` при buildx multi-arch**

Причина: Нет эмуляции QEMU.

Решение: Зарегистрируйте бинформаты:

```bash
docker run --privileged multiarch/qemu-user-static --reset -p yes
```

**3. Ошибка: `error: cannot connect to daemon`**

Причина: Docker daemon не запущен или недоступен.

Решение:

```bash
# Проверка статуса Docker
sudo systemctl status docker
# Запуск Docker
sudo systemctl start docker
```

**4. Ошибка: `permission denied` при использовании `--ssh`**

Причина: SSH-агент не доступен или ключи не добавлены.

Решение:

```bash
# Проверка SSH-агента
ssh-add -l
# Добавление ключа
ssh-add ~/.ssh/id_rsa
# Проброс агента в Docker
docker buildx build --ssh default=$SSH_AUTH_SOCK .
```

**5. Медленная сборка multi-platform образов**

Причина: Эмуляция через QEMU значительно медленнее нативной сборки.

Решение: Используйте кросс-компиляцию (для Go, Rust) или физические узлы:

```hcl
# В Dockerfile
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app .
```

**6. Кэш не работает между сборками**

Причина: Не настроены источники кэша или используется локальный кэш в ephemeral-окружениях.

Решение: Настройте удаленный кэш (registry, GHA, S3):

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myapp:latest .
```

### Диагностические команды

```bash
# Вывод полной конфигурации сборщика
docker buildx inspect

# Просмотр всех доступных сборщиков
docker buildx ls

# Просмотр outline всех параметров сборки
docker buildx build --call=outline .

# Проверка Dockerfile без реальной сборки
docker buildx build --check .

# Сборка с подробным выводом
docker buildx build --progress=plain .
```

## Лучшие практики

### Структура проекта

```
.
├── docker-bake.hcl           # Основной файл конфигурации Bake
├── docker-bake.override.hcl  # Локальные переопределения
├── docker-compose.yaml       # Для локальной разработки и запуска
├── Dockerfile                # Multi-stage Dockerfile
├── .dockerignore             # Исключения из контекста сборки
└── src/
    └── ...
```

### Рекомендации

1. **Используйте кросс-компиляцию** вместо эмуляции QEMU для языков, которые её поддерживают (Go, Rust, C++).
2. **Настройте кэширование** — всегда определяйте `cache-from` и `cache-to` для production-сборок.
3. **Используйте `--check`** перед пушем — проверяйте Dockerfile на наличие проблем.
4. **Параметризуйте** через переменные — выносите реестр, теги, версии в `--build-arg`.
5. **Используйте `--metadata-file`** для сохранения метаданных сборки (digest, SBOM) в файл.
6. **Настройте удаленные сборщики** для CI/CD — это обеспечит консистентность сборки.
7. **Используйте аттестации** (`--sbom`, `--provenance`) для повышения безопасности образов.
8. **Регулярно очищайте** неиспользуемые сборщики и кэш.

### Очистка

```bash
# Удаление неиспользуемых образов
docker image prune -f

# Удаление неиспользуемых сборщиков
docker buildx prune -f

# Удаление конкретного сборщика
docker buildx rm multi-arch-builder

# Очистка всего кэша BuildKit
docker builder prune -a -f

# Удаление всех сборщиков (кроме активного)
docker buildx rm $(docker buildx ls -q | grep -v $(docker buildx inspect --format '{{.Name}}'))
```

## Границы и ограничения

- **Производительность QEMU:** Эмуляция значительно медленнее нативной сборки. Используйте кросс-компиляцию или физические узлы для production-сборок.
- **Размер кэша:** Multi-platform сборки занимают больше места в кэше. Настройте удалённое кэширование для CI/CD.
- **Драйвер `docker`:** Ограничен по возможностям — не поддерживает multi-platform, удалённый кэш и аттестации.
- **Параллелизм:** Зависит от возможностей BuildKit и настроек демона Docker. В CI-окружениях может потребоваться явное создание сборщика с драйвером `docker-container`.
- **Named contexts:** Ограничены возможностями HCL/YAML конфигураций. Для сложных сценариев используйте `--build-context` или `--build-arg`.
- **Аттестации:** Увеличивают размер образа. Используйте `mode=min` для production-сборок, если критичен размер.
- **Обратная совместимость:** Команда `buildx build` может получать обратно несовместимые изменения в будущих версиях (согласно официальной документации Docker).
- **Количество платформ:** Рекомендуется ограничивать количество платформ (3-5) для оптимального баланса между覆盖面 и временем сборки.

## См. также

- **[BuildKit: Техническое устройство движка](./dockerfile_buildkit.md)** — глубокий разбор LLB, кэша и аттестаций.
- **[Docker Bake: Декларативная оркестрация сборки](./docker-bake.md)** — управление параметрами сборки через HCL/YAML.
- **[Безопасность Docker-образов](../Docker_security/overview.md)** — SBOM, сканирование уязвимостей и подпись образов.