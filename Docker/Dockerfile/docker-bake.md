# Docker Bake: Декларативная оркестрация сборки

## Определения

**Docker Bake** — это высокоуровневый инструмент оркестрации сборки, входящий в состав **Docker Buildx**. Он позволяет декларативно описывать параметры сборки одного или нескольких образов в конфигурационных файлах, заменяя сложные команды `docker build` с множеством флагов. Инструмент автоматически строит граф зависимостей и выполняет сборку независимых компонентов параллельно, оптимизируя использование кэша и передачу контекста сборки.

В феврале 2025 года с релизом **Docker Desktop 4.38** инструмент официально перешел в статус **General Availability (GA)**.

## Основные концепции

### Ключевые особенности
- **Декларативность:** Описание всей логики сборки (аргументы, теги, секреты, маунты) в едином файле.
- **Параллелизм:** Одновременная сборка нескольких независимых образов, что значительно ускоряет пайплайны.
- **Матричные сборки (Matrix):** Динамическая генерация множества вариантов образов (например, под разные версии языков или ОС) из одного описания.
- **Наследование (Inheritance):** Использование механизмов `inherits` для переиспользования общих настроек между разными таргетами.
- **Аттестации (Attestations):** Встроенная поддержка генерации SBOM (состав образа) и Provenance (история сборки) для соответствия стандартам безопасности (SLSA).
- **Интеграция с Compose:** Возможность использования существующих `compose.yaml` файлов в качестве источника данных для сборки.

### Docker Bake vs Docker Compose

Хотя синтаксис файлов может быть похож (особенно в YAML), эти инструменты решают принципиально разные задачи:

| Характеристика | Docker Bake | Docker Compose |
| :--- | :--- | :--- |
| **Основная цель** | Сборка артефактов (Build) | Запуск и работа сервисов (Run/Ops) |
| **Фокус** | Аргументы сборки, теги, платформы, аттестации | Сети, тома, переменные окружения, лимиты |
| **Сценарии** | CI/CD, подготовка релизов, мультиархитектурность | Локальная разработка, оркестрация стека |
| **Результат** | Образ (Image) в реестре или локальном хранилище | Запущенная группа контейнеров |

## Форматы конфигурации

Bake поддерживает два основных формата: **HCL** (рекомендуется) и **YAML**.

### Использование YAML (`docker-bake.yaml`)
Этот формат удобен для команд, которые уже используют Docker Compose и хотят сохранить визуальное сходство.

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

### Использование HCL (`docker-bake.hcl`)
HCL (HashiCorp Configuration Language) является стандартом де-факто для Bake, так как поддерживает переменные, функции, условную логику и матрицы.

```hcl
variable "TAG" {
  default = "latest"
  description = "Тег для публикуемых образов"
}

# Группа позволяет запустить сборку нескольких таргетов одной командой
group "default" {
  targets = ["db", "api"]
}

target "db" {
  context = "./database"
  tags = ["myreg.com/db:${TAG}"]
}

target "api" {
  context = "./api"
  dockerfile = "Dockerfile.prod"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = ["myreg.com/api:${TAG}"]
  attest = [
    "type=provenance,mode=max",
    "type=sbom"
  ]
}
```

## Практические сценарии

### Сценарий 1: Мультисервисная сборка с общими настройками
Использование наследования для соблюдения DRY (Don't Repeat Yourself).

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

### Сценарий 2: Условные сборки и тернарные операторы
Управление тегами и аргументами в зависимости от значения переменной окружения.

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

### Сценарий 3: Матричные сборки (Matrix Builds)
Создание сетки образов для разных версий Node.js и базовых ОС.

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

### Сценарий 4: Инспекция сборки (Новое в 2025)
Флаг `--call` позволяет проверить конфигурацию без запуска реальных процессов.

```bash
# Просмотр "очертаний" сборки: все аргументы, секреты и теги, которые будут применены
docker buildx bake --call=outline

# Проверка Dockerfile на наличие ошибок и неоптимальных инструкций
docker buildx bake --call=check

# Список всех доступных таргетов с их описаниями
docker buildx bake --call=targets
```

## Интеграция в CI/CD (GitHub Actions)

Bake позволяет избежать длинных shell-скриптов и гарантирует идентичность сборки локально и в CI.

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

## Дополнительная информация

### Удаленные контексты и конфигурации
Bake может работать напрямую с Git-репозиториями или HTTP-ресурсами:
- `docker buildx bake https://github.com/user/repo.git`
- Сборка с использованием удаленного HCL-файла: `docker buildx bake -f https://example.com/shared-config.hcl`

### См. также
- **[Docker Buildx: Мультиплатформенная сборка](./docker_buildx.md)** — управление инстансами сборщиков.
- **[BuildKit: Техническое устройство движка](./dockerfile_buildkit.md)** — глубокий разбор LLB, кэша и аттестаций.
- **[Оптимизация сборки Docker-образов](./Docker_best_practices/build_optimization.md)** — стратегии кэширования и Multi-stage.
- **[Подписание и верификация образов](../Docker_security/image_signature_and_verification.md)** — использование аттестаций в процессах безопасности.
