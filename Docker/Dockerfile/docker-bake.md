# Docker Bake: Декларативная оркестрация сборки

**Актуально для:** Docker 24.0+ / Docker Desktop 4.38+ / Buildx v0.12+

## Определения

**Docker Bake** — это высокоуровневый инструмент оркестрации сборки, входящий в состав **Docker Buildx**. Он позволяет декларативно описывать параметры сборки одного или нескольких образов в конфигурационных файлах, заменяя сложные команды `docker build` с множеством флагов. Инструмент автоматически строит граф зависимостей и выполняет сборку независимых компонентов параллельно, оптимизируя использование кэша и передачу контекста сборки.

В феврале 2025 года с релизом **Docker Desktop 4.38** инструмент официально перешел в статус **General Availability (GA)** и включен в состав Buildx по умолчанию.

## Предварительные требования

### Программное обеспечение

- **Docker Engine** версии 24.0 или новее (рекомендуется Docker 27.0+, где `docker buildx build` является стандартным алиасом для `docker build`)
- **Docker Buildx** плагин (встроен в Docker Desktop; на Linux может потребоваться отдельная установка через `docker buildx install`)
- **BuildKit** — включен по умолчанию в Docker 24.0+; для более ранних версий необходимо установить переменную окружения `DOCKER_BUILDKIT=1`

### Проверка установки

```bash
# Проверка версии Docker
docker --version
# -> Docker version 27.x.x, build xxxxxxx

# Проверка наличия Buildx
docker buildx version
# -> github.com/docker/buildx v0.xx.x ...

# Проверка доступных сборщиков
docker buildx ls
# -> NAME/NODE     DRIVER/ENDPOINT STATUS   BUILDKIT
# -> default*      docker
# ->                 default         default  v0.xx.x
```

### Создание сборщика с расширенными возможностями

Для использования матричных сборок, мультиархитектурности и расширенного кэширования рекомендуется создать сборщик с драйвером `docker-container`:

```bash
# Создание и активация нового сборщика
docker buildx create --name bake-builder --driver docker-container --use
docker buildx inspect --bootstrap
```

## Основные концепции

### Ключевые особенности

- **Декларативность:** Описание всей логики сборки (аргументы, теги, секреты, маунты) в едином файле.
- **Параллелизм:** Одновременная сборка нескольких независимых образов, что значительно ускоряет пайплайны.
- **Матричные сборки (Matrix):** Динамическая генерация множества вариантов образов (например, под разные версии языков или ОС) из одного описания.
- **Наследование (Inheritance):** Использование механизмов `inherits` для переиспользования общих настроек между разными таргетами. Поддерживается множественное наследование.
- **Аттестации (Attestations):** Встроенная поддержка генерации SBOM (состав образа) и Provenance (история сборки) для соответствия стандартам безопасности (SLSA).
- **Интеграция с Compose:** Возможность использования существующих `compose.yaml` файлов в качестве источника данных для сборки.
- **Валидация переменных:** Проверка значений переменных с помощью пользовательских правил перед началом сборки.
- **Паттерн-матчинг:** Поддержка шаблонов подстановки для массового запуска таргетов (аналогично glob-паттернам в shell).

### Архитектура Bake

Bake работает как прослойка между пользовательским вводом (HCL/YAML/JSON файлы) и движком BuildKit:

1. **Парсинг файлов:** Bake загружает один или несколько конфигурационных файлов и объединяет их в единое определение сборки.
2. **Резолвинг переменных:** Все переменные вычисляются, включая переопределения из переменных окружения и CLI. Поддерживаются CSV и JSON override-ы для сложных типов.
3. **Построение графа:** Определяется порядок выполнения таргетов и их зависимости.
4. **Параллельное выполнение:** Независимые таргеты собираются одновременно через BuildKit.
5. **Вывод результатов:** Образы сохраняются в локальное хранилище, реестр или файловую систему в соответствии с настройками `output`.

### Docker Bake vs Docker Compose

Хотя синтаксис файлов может быть похож (особенно в YAML), эти инструменты решают принципиально разные задачи:

| Характеристика | Docker Bake | Docker Compose |
| :--- | :--- | :--- |
| **Основная цель** | Сборка артефактов (Build) | Запуск и работа сервисов (Run/Ops) |
| **Фокус** | Аргументы сборки, теги, платформы, аттестации | Сети, тома, переменные окружения, лимиты |
| **Сценарии** | CI/CD, подготовка релизов, мультиархитектурность | Локальная разработка, оркестрация стека |
| **Результат** | Образ (Image) в реестре или локальном хранилище | Запущенная группа контейнеров |
| **Параллелизм** | Встроенная поддержка параллельной сборки | Ограничен параллельным запуском сервисов |

> **Примечание:** Bake может использовать `compose.yaml` как источник конфигурации для сборки, но не запускает контейнеры.

## Форматы конфигурации

Bake поддерживает несколько форматов конфигурации: **HCL** (рекомендуется), **JSON** и **YAML** (Docker Compose).

### Порядок поиска файлов по умолчанию

Если не указан конкретный файл, Bake выполняет поиск в следующем порядке:

1. `compose.yaml`
2. `compose.yml`
3. `docker-compose.yml`
4. `docker-compose.yaml`
5. `docker-bake.json`
6. `docker-bake.hcl`
7. `docker-bake.override.json`
8. `docker-bake.override.hcl`
9. `docker-bake.override.yaml` (неофициальный, но широко используемый)

Если найдено несколько файлов, они объединяются в единое определение. Файлы загружаются в порядке поиска, при этом более поздние файлы переопределяют значения предыдущих.

Некоторые атрибуты переопределяются последним файлом: `cache-to`, `dockerfile-inline`, `dockerfile`, `output`, `platforms`, `pull`, `tags`, `target`. Остальные атрибуты объединяются.

### Использование HCL (`docker-bake.hcl`)

HCL (HashiCorp Configuration Language) является стандартом де-факто для Bake, так как поддерживает переменные, функции, условную логику и матрицы.

#### Структура HCL-файла

HCL-файл Bake состоит из четырех основных типов блоков:

**1. Блок `variable` — определение переменных:**

```hcl
variable "TAG" {
  default = "latest"
  description = "Тег для публикуемых образов"
}

variable "REGISTRY" {
  default = "docker.io/myorg"
}

variable "NODE_VERSION" {
  default = 22
  type = number
  validation {
    condition = NODE_VERSION >= 18
    error_message = "Версия Node.js должна быть не менее 18."
  }
}
```

**2. Блок `group` — группы таргетов:**

```hcl
# Группа позволяет запустить сборку нескольких таргетов одной командой
group "default" {
  targets = ["db", "api"]
}

group "all" {
  targets = ["frontend", "backend", "db", "api"]
}

group "backend-services" {
  targets = ["backend", "db"]
}
```

**3. Блок `target` — параметры сборки:**

```hcl
target "db" {
  context = "./database"
  dockerfile = "Dockerfile.prod"
  tags = ["${REGISTRY}/db:${TAG}"]
  platforms = ["linux/amd64", "linux/arm64"]
  args = {
    POSTGRES_VERSION = "16"
  }
  cache-from = ["type=registry,ref=${REGISTRY}/db:cache"]
  cache-to = ["type=registry,ref=${REGISTRY}/db:cache,mode=max"]
  attest = [
    { type = "provenance", mode = "max" },
    { type = "sbom" }
  ]
}
```

**4. Блок `function` — переиспользуемые функции (HCL):**

```hcl
function "tag" {
  params = [image, tag]
  result = ["${REGISTRY}/${image}:${tag}"]
}

target "api" {
  tags = tag("api", TAG)
}
```

#### Полный пример HCL-файла

```hcl
variable "REGISTRY" {
  default = "docker.io/myorg"
  description = "Реестр и namespace"
}

variable "TAG" {
  default = "latest"
  description = "Версионный тег"
  type = string
}

variable "NODE_VERSION" {
  default = 22
  type = number
  validation {
    condition = NODE_VERSION >= 18
    error_message = "Node.js версия должна быть >= 18."
  }
}

group "default" {
  targets = ["frontend", "backend"]
}

group "all" {
  targets = ["frontend", "backend", "worker"]
}

target "base" {
  platforms = ["linux/amd64", "linux/arm64"]
  args = {
    ORGANIZATION = "mycorp"
  }
  cache-from = ["type=gha"]
  cache-to = ["type=gha,mode=max"]
}

target "frontend" {
  inherits = ["base"]
  context = "./frontend"
  dockerfile = "Dockerfile"
  tags = ["${REGISTRY}/frontend:${TAG}"]
}

target "backend" {
  inherits = ["base"]
  context = "./backend"
  dockerfile = "Dockerfile.prod"
  tags = ["${REGISTRY}/backend:${TAG}"]
  args = {
    GO_VERSION = "1.22"
  }
  secret = [
    { type = "file", id = "npmrc", src = "${HOME}/.npmrc" }
  ]
}

target "worker" {
  context = "./worker"
  tags = ["${REGISTRY}/worker:${TAG}"]
  output = ["type=local,dest=./artifacts"]
}
```

### Использование JSON (`docker-bake.json`)

Формат JSON удобен для программной генерации конфигураций:

```json
{
  "group": {
    "default": {
      "targets": ["frontend", "backend"]
    }
  },
  "target": {
    "frontend": {
      "context": "./frontend",
      "tags": ["myorg/frontend:latest"]
    },
    "backend": {
      "context": "./backend",
      "tags": ["myorg/backend:latest"]
    }
  }
}
```

### Использование YAML (`docker-bake.yaml`)

Этот формат удобен для команд, которые уже используют Docker Compose и хотят сохранить визуальное сходство:

```yaml
services:
  myapp:
    context: ./app
    dockerfile: Dockerfile.prod
    image: mycompany/app:latest
    args:
      BUILD_ENV: production
      NODE_VERSION: 22
```

> **Примечание:** При использовании YAML-формата Bake интерпретирует секцию `services` как набор таргетов для сборки.

## Переменные и их валидация

### Определение переменных

Переменные позволяют параметризовать конфигурацию сборки и переопределять её без изменения файла:

```hcl
variable "TAG" {
  default = "latest"
  description = "Тег образа"
  type = string
}

variable "REGISTRY" {
  default = "docker.io/myorg"
  description = "Docker реестр"
}

variable "DEBUG" {
  default = false
  type = bool
}
```

### Встроенные переменные Bake

Bake предоставляет набор встроенных переменных, доступных без явного определения:

| Переменная | Описание |
| :--- | :--- |
| `TARGETPLATFORM` | Целевая платформа (например, `linux/amd64`) |
| `TARGETOS` | Операционная система цели (например, `linux`) |
| `TARGETARCH` | Архитектура цели (например, `amd64`) |
| `TARGETVARIANT` | Вариант платформы (например, `v7` для ARM) |
| `BUILDPLATFORM` | Платформа, на которой выполняется сборка |
| `BUILDOS` | ОС сборщика |
| `BUILDARCH` | Архитектура сборщика |
| `BAKE_CMD_CONTEXT` | Основной контекст при сборке из удаленного файла |
| `BAKE_LOCAL_PLATFORM` | Платформа по умолчанию для текущей машины |

```hcl
target "app" {
  args = {
    BUILD_ARCH = BUILDARCH
    TARGET_ARCH = TARGETARCH
  }
  platforms = ["linux/amd64", "linux/arm64"]
}
```

### Валидация переменных

Bake поддерживает пользовательскую валидацию переменных с помощью блока `validation`:

```hcl
variable "PORT" {
  default = 3000
  validation {
    condition = PORT >= 1024
    error_message = "Порт должен быть >= 1024."
  }
}

variable "IMAGE_NAME" {
  default = ""
  validation {
    condition = IMAGE_NAME != ""
    error_message = "Имя образа не может быть пустым."
  }
  validation {
    condition = IMAGE_NAME == regex("[a-zA-Z0-9._-]+", IMAGE_NAME)
    error_message = "Имя образа может содержать только буквы, цифры, точки, подчеркивания и дефисы."
  }
}
```

Если условие `condition` вычисляется в `false`, сборка прерывается с сообщением об ошибке.

### Экранирование интерполяции

Для отмены интерполяции переменных используйте двойной знак доллора (`$$`):

```hcl
target "app" {
  dockerfile-inline = <<EOF
  FROM alpine
  ARG TARGETARCH
  RUN echo "Building for $${TARGETARCH/amd64/x64}"
  EOF
  platforms = ["linux/amd64", "linux/arm64"]
}
```

### Переопределение переменных через окружение

Переменные окружения переопределяют значения `variable`-блоков. Для сложных типов (list, map, object) используйте JSON-override с суффиксом `_JSON`:

```bash
# Переопределение простой переменной
export TAG=$(git rev-parse --short HEAD)
docker buildx bake

# Переопределение списка через CSV
TAGS=dev,latest,2 docker buildx bake

# Переопределение сложного типа через JSON
VALS_JSON='["hello","with,comma"]' docker buildx bake
```

```hcl
variable "TAG" {
  default = "latest"
}

variable "TAGS" {
  type = list(string)
  default = ["latest"]
}

target "app" {
  tags = [for tag in TAGS: "myorg/app:${tag}"]
}
```

> **Примечание:** Переменные окружения применяются только к блокам `variable`. Прямое переопределение атрибутов таргетов через окружение невозможно — используйте `--set`. Чтобы отключить автоматический lookup переменных в окружении, установите `BUILDX_BAKE_DISABLE_VARS_ENV_LOOKUP=1`.

### Относительные пути

По умолчанию пути в `context` и `contexts` разрешаются относительно текущей рабочей директории. Для разрешения относительно расположения Bake-файла установите:

```bash
export BUILDX_BAKE_FILE_RELATIVE_PATHS=1
```

## Переопределение конфигураций

Bake поддерживает три способа переопределения конфигурации: файлы, командная строка и переменные окружения.

### Файловые переопределения

Можно загружать несколько файлов, которые объединяются в единое определение:

```bash
# Загрузка базового файла и файла переопределения
docker buildx bake -f docker-bake.hcl -f overrides.hcl

# Использование стандартного порядка поиска
docker buildx bake  # Автоматически найдет docker-bake.override.hcl
```

### Переопределение через командную строку (`--set`)

Флаг `--set` позволяет изменять атрибуты таргетов без изменения файлов:

```bash
# Переопределение аргумента сборки
docker buildx bake --set app.args.VERSION=2.0.0

# Переопределение платформы для всех таргетов
docker buildx bake --set *.platform=linux/arm64

# Переопределение тегов с оператором += (дополнение без замены)
docker buildx bake --set app.tags+=myorg/app:hotfix

# Отключение кэша для конкретного таргета
docker buildx bake --set app.no-cache

# Паттерн-матчинг для массового переопределения
docker buildx bake --set frontend*.args.NODE_VERSION=20

# Переопределение секрета
docker buildx bake --set "default.secret.npmrc=env=NPMRC_TOKEN"
```

**Доступные атрибуты для переопределения:**

- `annotations` — OCI-аннотации
- `args` — аргументы сборки
- `attest` — аттестации
- `cache-from` — источники кэша
- `cache-to` — назначения кэша
- `call` — метод оценки
- `context` — контекст сборки
- `contexts` — именованные контексты
- `dockerfile` — путь к Dockerfile
- `entitlements` — привилегии сборки
- `extra-hosts` — кастомные DNS-записи
- `labels` — метаданные образа
- `network` — сетевой режим
- `no-cache` — отключение кэша
- `no-cache-filter` — отключение кэша для этапов
- `output` — тип вывода
- `platform` — целевая платформа
- `pull` — принудительное обновление базовых образов
- `resources` — лимиты ресурсов
- `secret` — секреты
- `secrets` — устаревшее название, используйте `secret`
- `shm-size` — размер shared memory
- `ssh` — SSH-ключи
- `tags` — теги образа
- `target` — целевой этап в multi-stage
- `ulimits` — лимиты ulimit

### Переопределение через переменные окружения

Переменные окружения переопределяют значения `variable`-блоков:

```bash
# Установка тега через переменную окружения
export TAG=$(git rev-parse --short HEAD)
docker buildx bake

# Использование с .env файлом
echo "TAG=production" > .env
docker buildx bake
```

```hcl
variable "TAG" {
  default = "latest"
}

target "app" {
  tags = ["myorg/app:${TAG}"]
}
```

> **Примечание:** Переменные окружения применяются только к блокам `variable`. Прямое переопределение атрибутов таргетов через окружение невозможно — используйте `--set`.

### Иерархия переопределений

Порядок приоритетов (от низшего к высшему):

1. Значения по умолчанию в `variable`-блоках
2. Файлы в порядке поиска (compose.yaml -> docker-bake.override.hcl)
3. Явные файлы через `-f`
4. Переменные окружения
5. Переопределения через `--set`

## Наследование и переиспользование

### Механизм `inherits`

Позволяет наследовать настройки от базового таргета для соблюдения принципа DRY. Поддерживается множественное наследование:

```hcl
target "base" {
  platforms = ["linux/amd64", "linux/arm64"]
  args = {
    ORGANIZATION = "mycorp"
  }
  cache-from = ["type=gha"]
  cache-to = ["type=gha,mode=max"]
}

target "frontend" {
  inherits = ["base"]
  context = "./frontend"
  tags = ["myreg.com/frontend:v1"]
}

target "backend" {
  inherits = ["base", "_release"]
  context = "./backend"
  tags = ["myreg.com/backend:v1"]
  args = merge(base.args, {
    GO_VERSION = "1.22"
  })
}
```

> **Примечание:** При наследовании из нескольких таргетов приоритет имеет последний в списке. Скалярные значения (строки, числа) заменяются, а списки и карты объединяются.

### Функции HCL

Bake поддерживает функции HCL для вычисления значений, включая пользовательские функции:

```hcl
function "tag" {
  params = [image, tag]
  result = ["${REGISTRY}/${image}:${tag}"]
}

function "latest" {
  params = [image]
  result = tag(image, "latest")
}

target "api" {
  tags = tag("api", TAG)
}

target "web" {
  tags = latest("web")
}
```

### Именованные контексты (Named Contexts)

Позволяют переопределять базовые образы без изменения Dockerfile:

```hcl
target "app" {
  context = "."
  contexts = {
    base = "docker.io/library/alpine:3.21"
    python = "docker.io/library/python:3.12-slim"
  }
}
```

В Dockerfile:

```dockerfile
FROM base AS runtime
# Будет использовать alpine:3.21 вместо дефолтного base image
COPY --from=python /usr/local/lib/python3.12 /usr/local/lib/python3.12
```

## Практические сценарии

### Сценарий 1: Мультисервисная сборка с общими настройками

Использование наследования для соблюдения DRY (Don't Repeat Yourself):

```hcl
target "base" {
  platforms = ["linux/amd64", "linux/arm64"]
  args = {
    ORGANIZATION = "mycorp"
  }
}

target "frontend" {
  inherits = ["base"]
  context = "./frontend"
  tags = ["myreg.com/frontend:v1"]
}

target "backend" {
  inherits = ["base"]
  context = "./backend"
  tags = ["myreg.com/backend:v1"]
}
```

**Запуск:**

```bash
docker buildx bake frontend backend
# Или через группу:
docker buildx bake default
```

### Сценарий 2: Условные сборки и тернарные операторы

Управление тегами и аргументами в зависимости от значения переменной окружения:

```hcl
variable "ENVIRONMENT" {
  default = "dev"
}

target "app" {
  context = "."
  args = {
    ENV_TYPE = "${ENVIRONMENT}"
  }
  tags = [
    "myapp:${ENVIRONMENT}",
    # Если среда prod, добавляем тег stable, иначе latest
    ENVIRONMENT == "prod" ? "myapp:stable" : "myapp:latest"
  ]
}
```

**Запуск:**

```bash
ENVIRONMENT=prod docker buildx bake app --print
# -> tags: ["myapp:prod", "myapp:stable"]
```

### Сценарий 3: Матричные сборки (Matrix Builds)

Создание сетки образов для разных версий Node.js и базовых ОС:

```hcl
target "app-matrix" {
  matrix = {
    node_version = ["18", "20", "22"]
    os_variant = ["alpine", "slim"]
  }
  # Динамическое имя таргета
  name = "app-node${node_version}-${os_variant}"
  context = "."
  args = {
    BASE_IMAGE = "node:${node_version}-${os_variant}"
  }
  tags = ["myreg.com/app:node-${node_version}-${os_variant}"]
}
```

**Запуск:**

```bash
# Сборка всех вариантов матрицы
docker buildx bake app-matrix*

# Сборка конкретного варианта
docker buildx bake app-node22-alpine
```

### Сценарий 4: Инспекция сборки

Флаги `--call` и `--print` позволяют проверить конфигурацию без запуска реальных процессов:

```bash
# Просмотр "очертаний" сборки: все аргументы, секреты и теги, которые будут применены
docker buildx bake --call=outline

# Проверка Dockerfile на наличие ошибок и неоптимальных инструкций
docker buildx bake --call=check

# Список всех доступных таргетов с их описаниями
docker buildx bake --call=targets

# Просмотр полной конфигурации в формате JSON
docker buildx bake --print

# Вывод списка всех таргетов
docker buildx bake --list=targets

# Вывод списка переменных
docker buildx bake --list=variables

# Вывод в JSON-формате для программной обработки
docker buildx bake --list=type=targets,format=json
```

### Сценарий 5: Сборка с секретами и SSH

Безопасная передача секретов и SSH-ключей в процесс сборки:

```hcl
target "app" {
  context = "."
  secret = [
    { type = "file", id = "npmrc", src = "${HOME}/.npmrc" },
    { type = "env", id = "aws_credentials", src = "AWS_CREDENTIALS" }
  ]
  ssh = [
    { id = "default" }
  ]
  args = {
    AWS_REGION = "eu-central-1"
  }
}
```

В Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm install
RUN --mount=type=ssh git clone git@github.com:private/repo.git
```

**Запуск:**

```bash
docker buildx bake app
```

### Сценарий 6: Сборка с кэшированием в реестре

Настройка удаленного кэширования для ускорения повторных сборок в CI/CD:

```hcl
target "app" {
  context = "."
  tags = ["myreg.com/app:latest"]
  cache-from = [
    { type = "registry", ref = "myreg.com/app:cache" },
    { type = "gha" }
  ]
  cache-to = [
    { type = "registry", ref = "myreg.com/app:cache", mode = "max" },
    { type = "gha", mode = "max" }
  ]
}
```

### Сценарий 7: Локальный вывод без сохранения в реестр

Экспорт собранных артефактов в файловую систему:

```hcl
target "binaries" {
  context = "."
  output = ["type=local,dest=./dist"]
  platforms = ["linux/amd64"]
}

target "multi-platform" {
  context = "."
  output = [
    "type=local,dest=./dist/amd64",
    "type=local,dest=./dist/arm64"
  ]
  platforms = ["linux/amd64", "linux/arm64"]
}
```

### Сценарий 8: Изменение контекста и базовых образов

Использование `contexts` для переопределения базовых образов без изменения Dockerfile:

```hcl
target "app" {
  context = "../app"
  contexts = {
    base = "docker-image://alpine:3.21"
    python = "docker-image://python:3.12-slim"
  }
}
```

## CLI-опции Bake

### Полный список опций

| Опция | Описание |
| :--- | :--- |
| `--allow ENTITLEMENT` | Предоставление дополнительных привилегий (например, `network.host`, `security.insecure`) |
| `--call METHOD` | Метод оценки сборки: `build` (по умолчанию), `check`, `outline`, `targets` |
| `--check` | Сокращение для `--call=check` |
| `-f`, `--file` | Указание файла конфигурации (можно указать несколько раз) |
| `--list WHAT` | Вывод списка таргетов или переменных (`targets`, `variables`, или `type=...,format=json`) |
| `--load` | Сокращение для `--set=*.output=type=docker`. Не переопределяет выводы `local` и `tar`. |
| `--metadata-file` | Запись метаданных сборки в файл |
| `--no-cache` | Отключение использования кэша |
| `--print` | Вывод итоговой конфигурации в JSON без запуска сборки |
| `--progress TYPE` | Тип вывода прогресса: `auto`, `none`, `plain`, `quiet`, `rawjson`, `tty` |
| `--provenance` | Сокращение для `--set=*.attest=type=provenance` |
| `--pull` | Принудительное обновление всех базовых образов |
| `--push` | Сокращение для `--set=*.output=type=registry`. Не переопределяет выводы `local` и `tar`. |
| `--sbom` | Сокращение для `--set=*.attest=type=sbom` |
| `--set KEY=VALUE` | Переопределение атрибутов таргетов (паттерн-матчинг поддерживается) |
| `--var NAME=VALUE` | Установка значения переменной |

### Примеры использования

```bash
# Вывод итоговой конфигурации
docker buildx bake --print db

# Переопределение аргументов и платформы
docker buildx bake --set app.args.VERSION=2.0.0 --set app.platform=linux/arm64 app

# Массовое переопределение с паттерном
docker buildx bake --set frontend*.args.NODE_VERSION=20

# Сборка с аттестациями
docker buildx bake --provenance=mode=max --sbom app

# Просмотр конфигурации без сборки
docker buildx bake -f docker-bake.hcl --print
```

## Интеграция в CI/CD

### GitHub Actions

Bake позволяет избежать длинных shell-скриптов и гарантирует идентичность сборки локально и в CI:

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Build with Bake
  uses: docker/bake-action@v6
  with:
    files: docker-bake.hcl
    push: true
    # Переопределение параметров на лету
    set: |
      *.cache-from=type=gha
      *.cache-to=type=gha,mode=max
    # Экспорт метаданных сборки (digest, SBOM) в файл
    metadata-file: build-metadata.json
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
  COMPOSE_DOCKER_CLI_BUILD: 1

stages:
  - build

build_job:
  stage: build
  script:
    - docker buildx create --use
    - docker buildx bake --file docker-bake.hcl --set app.tags=$CI_REGISTRY_IMAGE/app:$CI_COMMIT_SHA --push
```

### Jenkins

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'docker buildx create --use || true'
                sh 'docker buildx bake -f docker-bake.hcl --push'
            }
        }
    }
}
```

## Удаленные контексты и конфигурации

Bake может работать напрямую с Git-репозиториями или HTTP-ресурсами:

```bash
# Сборка из Git-репозитория
docker buildx bake https://github.com/user/repo.git

# Сборка с использованием удаленного HCL-файла
docker buildx bake -f https://example.com/shared-config.hcl

# Сборка из Git-репозитория с указанием ветки
docker buildx bake https://github.com/user/repo.git#main

# Сборка из Git-репозитория с указанием подкаталога
docker buildx bake https://github.com/user/repo.git#:docker
```

## Разрешение проблем

### Типичные ошибки

**1. Ошибка: `no bake files found`**

Причина: В текущей директории нет файлов конфигурации Bake.

Решение: Создайте файл `docker-bake.hcl` или укажите путь через `-f`:

```bash
docker buildx bake -f docker-bake.hcl
```

**2. Ошибка: `target "X" not found`**

Причина: Указан несуществующий таргет или группа.

Решение: Проверьте список доступных таргетов:

```bash
docker buildx bake --list=targets
```

**3. Ошибка: `variable "X" validation failed`**

Причина: Значение переменной не прошло валидацию.

Решение: Проверьте значение переменной и исправьте его:

```bash
# Просмотр текущего значения
docker buildx bake --print

# Переопределение значения
docker buildx bake --var PORT=8080
```

**4. Медленная сборка multi-platform образов**

Причина: Эмуляция через QEMU значительно медленнее нативной сборки.

Решение: Используйте кросс-компиляцию (для Go, Rust) или физические узлы с нужными архитектурами:

```hcl
target "app" {
  # Используйте BUILDPLATFORM для сборщика и TARGETPLATFORM для цели
  args = {
    TARGETOS = TARGETOS
    TARGETARCH = TARGETARCH
  }
}
```

**5. Кэш не работает между сборками**

Причина: Не настроены источники кэша или используется локальный кэш в ephemeral-окружениях.

Решение: Настройте удаленный кэш (registry, GHA, S3):

```hcl
target "app" {
  cache-from = ["type=registry,ref=myreg.com/app:cache"]
  cache-to = ["type=registry,ref=myreg.com/app:cache,mode=max"]
}
```

**6. `--load` не экспортирует образ**

Причина: В определении таргета задан `output = ["type=local,..."]`. Флаг `--load` не переопределяет выводы типа `local` и `tar`.

Решение: Удалите `output` из bake-файла или используйте `--set "*.output=type=docker"`.

**7. Секреты не видны в Dockerfile**

Причина: Секрет объявлен в Bake, но не смонтирован в Dockerfile, или указан неверный `id`.

Решение: Убедитесь, что `id` в `secret` совпадает с `id` в `RUN --mount=type=secret`, и что секрет передается через `--set` или объявлен в HCL.

### Диагностические команды

```bash
# Вывод полной конфигурации для анализа
docker buildx bake --print

# Проверка Dockerfile без реальной сборки
docker buildx bake --call=check

# Просмотр outline всех параметров
docker buildx bake --call=outline

# Сборка с подробным выводом
docker buildx bake --progress=plain
```

## Лучшие практики

### Структура проекта

```
.
├── docker-bake.hcl           # Основной файл конфигурации Bake
├── docker-bake.override.hcl  # Локальные переопределения (не коммитить)
├── docker-bake.override.yaml # Альтернативные переопределения (не коммитить)
├── docker-compose.yaml       # Для локальной разработки и запуска
├── app/
│   ├── Dockerfile
│   └── ...
├── api/
│   ├── Dockerfile
│   └── ...
└── worker/
    ├── Dockerfile
    └── ...
```

### Рекомендации

1. **Используйте группы** для логической организации таргетов (например, `dev`, `prod`, `all`).
2. **Настройте кэширование** — всегда определяйте `cache-from` и `cache-to` для production-сборок.
3. **Параметризуйте** через переменные — выносите реестр, теги, версии в `variable`-блоки.
4. **Валидируйте переменные** — добавляйте `validation` для критичных параметров.
5. **Используйте `--print`** перед пушем — проверяйте итоговую конфигурацию.
6. **Храните override-файлы** отдельно и не коммитьте конфиденциальные переопределения.
7. **Используйте наследование** для общих настроек (платформы, кэш, метаданные).
8. **Интегрируйте с CI/CD** — один и тот же `docker-bake.hcl` для локальной и CI-сборки.
9. **Используйте `description`** в `target` и `variable` — облегчает навигацию по большим конфигурациям через `--list=targets` и `--list=variables`.
10. **Избегайте `output` в Bake-файле**, если собираетесь использовать `--load` или `--push` — это предотвращает конфликты.

### Очистка

```bash
# Удаление неиспользуемых образов
docker image prune -f

# Удаление сборщика (если больше не нужен)
docker buildx rm bake-builder

# Очистка кэша BuildKit
docker builder prune -a
```

## Границы и ограничения

- **Версия HCL:** Bake использует HCL2. Старый синтаксис HCL1 (с `=` вместо блоков) не поддерживается.
- **Матричные сборки:** Количество комбинаций матрицы не должно превышать разумные пределы (рекомендуется < 50 таргетов) для избежания проблем с производительностью.
- **Наследование:** Поддерживается множественное наследование, но circular inheritance приводит к ошибке.
- **Переменные окружения:** Переопределяют только `variable`-блоки. Атрибуты таргетов (tags, args, platforms) недоступны для прямого переопределения через env.
- **YAML-формат:** Ограничен возможностями по сравнению с HCL. Рекомендуется использовать HCL для сложных конфигураций.
- **Параллелизм:** Зависит от возможностей BuildKit и настроек демона Docker. В CI-окружениях может потребоваться явное создание сборщика с драйвером `docker-container`.
- **Обратная совместимость:** Команда `buildx bake` может получать обратно несовместимые изменения в будущих версиях (согласно официальной документации Docker).
- **`--load` и `--push`:** Не переопределяют выводы `type=local` и `type=tar`. Для изменения типа вывода используйте `--set`.
- **Ширина контекста:** Bake собирает весь контекст перед сборкой. Для больших репозиториев используйте `.dockerignore` или явно указывайте `context`.

## См. также

- **[Docker Buildx: Мультиплатформенная сборка](./docker_buildx.md)** — управление инстансами сборщиков.
- **[BuildKit: Техническое устройство движка](./dockerfile_buildkit.md)** — глубокий разбор LLB, кэша и аттестаций.
- **[Оптимизация сборки Docker-образов](./Docker_best_practices/build_optimization.md)** — стратегии кэширования и Multi-stage.
- **[Docker Compose: Сборка и CI/CD](./Docker_compose/docker_compose_ci_cd_testing.md)** — интеграция Bake через Compose.
