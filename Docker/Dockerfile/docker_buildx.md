# Docker Buildx: Мультиплатформенная сборка

## Определения

**Docker Buildx** — это плагин командной строки (CLI), расширяющий возможности стандартной команды `docker build` с помощью движка **BuildKit**. Он является основным инструментом для создания современных пайплайнов сборки, поддерживающим изоляцию процессов сборки в независимых инстансах (builders).

Ключевые возможности:
- Одновременная сборка под несколько архитектур (multi-arch).
- Расширенное управление кэшем (экспорт в Registry, S3, GHA).
- Поддержка аттестаций (SBOM и Provenance).
- Гибкое управление секретами и SSH-ключами без сохранения их в слоях образа.
- Использование декларативных конфигураций через инструмент **Bake**.

В современных версиях Docker (23.0+) команда `docker build` является псевдонимом (alias) для `docker buildx build`.

## Основные концепции

### Драйверы сборщиков
Драйвер определяет среду, в которой работает BuildKit, и доступный функционал.

1. **`docker` (стандартный)**:
   - Использует BuildKit, встроенный в демон Docker.
   - Работает напрямую с локальным хранилищем образов.
   - **Ограничения**: Не поддерживает одновременную сборку под несколько платформ и расширенные типы кэша.
2. **`docker-container`**:
   - Запускает BuildKit в выделенном контейнере.
   - Позволяет собирать multi-arch образы и экспортировать кэш в удаленные хранилища.
   - Рекомендуется для большинства CI/CD сценариев.
3. **`kubernetes`**:
   - Развертывает сборщики как Pods в кластере Kubernetes.
   - Идеально для масштабируемых ферм сборки.
4. **`remote`**:
   - Подключается к уже запущенному инстансу `buildkitd` по TCP или SSH.

### Механизмы мультиплатформенности
Buildx поддерживает три способа сборки для разных архитектур:
- **QEMU (Эмуляция)**: Самый простой способ. Позволяет запускать бинарные файлы одной архитектуры на другой через `binfmt_misc`. Требует предустановленных эмуляторов (в Docker Desktop они встроены).
- **Native Cross-compilation**: Использование возможностей компилятора (Go, Rust, C++) для создания бинарного файла под целевую архитектуру без выполнения кода этой архитектуры во время сборки. Самый быстрый метод.
- **Native Nodes**: Использование нескольких физических узлов с разными архитектурами, объединенных в один инстанс сборщика.

### Управление секретами и SSH
Buildx позволяет безопасно передавать конфиденциальные данные в процесс сборки:
- **Secrets**: Файлы или переменные окружения, которые монтируются как временная файловая система и не попадают в итоговый образ.
  - Синтаксис: `--secret id=mysecret,src=secret.txt`
  - В Dockerfile: `RUN --mount=type=secret,id=mysecret cat /run/secrets/mysecret`
- **SSH Forwarding**: Проброс SSH-агента хоста внутрь контейнера для доступа к приватным репозиториям.
  - Синтаксис: `--ssh default=$SSH_AUTH_SOCK`
  - В Dockerfile: `RUN --mount=type=ssh git clone ...`

### Проверки сборки (Build Checks)
Buildx включает встроенный линтер Dockerfile, который анализирует инструкции перед началом сборки и выдает предупреждения о потенциальных проблемах (например, использование `latest`, отсутствие `--no-install-recommends` в `apt`).
Команда: `docker buildx build --check .`

## Процесс работы с билдерами

### Создание и настройка инстанса
Для использования всех возможностей BuildKit необходимо создать и активировать новый инстанс:

1. **Создание билдера с драйвером контейнера**:
   ```bash
   docker buildx create --name multi-arch-builder --driver docker-container --use
   ```
2. **Инициализация**:
   ```bash
   docker buildx inspect --bootstrap
   ```
   *Результат: Будет запущен контейнер с `moby/buildkit`.*
3. **Проверка статуса**:
   ```bash
   docker buildx ls
   ```

### Экспорт кэша
Buildx позволяет выносить кэш за пределы хоста сборки, что критично для CI/CD:
- **Registry**: `--cache-to type=registry,ref=repo/cache --cache-from type=registry,ref=repo/cache`
- **GitHub Actions**: `--cache-to type=gha,mode=max --cache-from type=gha`
- **S3 / Azure / Local**: Поддерживаются специализированные драйверы для хранения слоев в облачных объектных хранилищах.

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
Инструмент `bake` позволяет описать параметры сборки в HCL файле (`docker-bake.hcl`), что удобнее длинных CLI команд.

```hcl
variable "TAG" {
  default = "latest"
}

group "default" {
  targets = ["api", "worker"]
}

target "api" {
  context = "./api"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = ["myreg.com/api:${TAG}"]
}

target "worker" {
  context = "./worker"
  tags = ["myreg.com/worker:${TAG}"]
}
```
**Запуск:** `docker buildx bake --set TAG=v1.2.0`

## Дополнительная информация

### Аттестации безопасности
Buildx может автоматически генерировать и прикреплять к образу метаданные:
- **SBOM (Software Bill of Materials)**: Список всех пакетов и зависимостей в образе.
- **Provenance**: История процесса сборки (кто, когда и на каком узле собирал).

Команда для сборки с аттестациями:
```bash
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --push -t myreg.com/app:secure .
```

### Привилегии сборки (Entitlements)
В некоторых случаях сборке требуются расширенные права (например, доступ к сети хоста или запуск привилегированных команд):
- `--allow network.host`: Разрешает использование сети хоста.
- `--allow security.insecure`: Разрешает небезопасные операции (требует настройки `buildkitd`).

## См. также
- **[BuildKit: Техническое устройство движка](./dockerfile_buildkit.md)**
- **[Безопасность Docker-образов](../Docker_security/overview.md)**
- **[SBOM и аудит состава образа](../Docker_security/docker_sbom.md)**
