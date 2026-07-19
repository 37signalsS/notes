# Инструменты оптимизации и анализа Dockerfile

## Определения

**Оптимизация размера образа** — уменьшение размера Docker-образов для ускорения сборки, развертывания и сокращения поверхности атаки.

**Линтинг** — статический анализ `Dockerfile` на соответствие лучшим практикам до начала сборки.

**Анализ безопасности** — сканирование образов на уязвимости (CVE), небезопасные конфигурации и секреты.

## Основные концепции

### Анализ и оптимизация размера

| Инструмент | Назначение | Репозиторий |
| :--- | :--- | :--- |
| **dive** | Интерактивное исследование слоев образа, поиск файлов, увеличивающих размер | [github.com/wagoodman/dive](https://github.com/wagoodman/dive) |
| **docker-slim** | Автоматическое уменьшение размера образов (до 30 раз) | [github.com/docker-slim/docker-slim](https://github.com/docker-slim/docker-slim) |
| **strip** | Удаление отладочной информации из бинарных файлов (GNU Binutils) | — |

### Линтинг

| Инструмент | Назначение | Репозиторий |
| :--- | :--- | :--- |
| **hadolint** | Линтер `Dockerfile`, проверка синтаксиса и лучших практик. | [github.com/hadolint/hadolint](https://github.com/hadolint/hadolint) |
| **D-roast** | Rust-утилита для "прожарки" (roasting) Dockerfile. Дает советы по оптимизации (например, замена `npm install` на `npm ci`) в ироничном или обычном стиле. | [github.com/nottheshrimp/d-roast](https://github.com/nottheshrimp/d-roast) |
| **semgrep** | Универсальный SAST-сканер, поддерживающий `Dockerfile`. | [github.com/semgrep/semgrep](https://github.com/semgrep/semgrep) |

### Анализ и мониторинг рантайма

| Инструмент | Назначение | Репозиторий |
| :--- | :--- | :--- |
| **Dozle** | Легковесный веб-интерфейс для мониторинга логов и метрик контейнеров в реальном времени. | [github.com/amir20/dozzle](https://github.com/amir20/dozzle) |
| **ctop** | Интерфейс в стиле top для контейнеров (метрики CPU, Mem). Подробное сравнение в **[TUI инструментах](../docker_tools.md)**. | [github.com/bcicen/ctop](https://github.com/bcicen/ctop) |

### Сканирование безопасности

| Инструмент | Назначение | Репозиторий |
| :--- | :--- | :--- |
| **dockle** | Проверка образа на соответствие CIS Benchmarks. Находит забытые папки `.git`, пароли в переменных, неочищенный кэш. *Особенности:* возможны false positives (например, ругается на сам факт установки `sudo`). | [github.com/goodwithtech/dockle](https://github.com/goodwithtech/dockle) |
| **checkov** | Инструмент для сканирования IaC (Infrastructure as Code). В `Dockerfile` находит открытые опасные порты (например, 22), запуск под `root`, а также небезопасные флаги в командах (отключение проверки SSL в `curl`/`wget`). Правила пишутся на Python и YAML. | [github.com/bridgecrewio/checkov](https://github.com/bridgecrewio/checkov) |
| **kics** | Open-source сканер от Checkmarx. *Преимущество:* умеет сканировать мисконфигурации не только в `Dockerfile`, но и в `docker-compose.yml`, что отличает его от многих других инструментов. | [github.com/Checkmarx/kics](https://github.com/Checkmarx/kics) |
| **docker-bench-security** | Аудит безопасности хоста Docker (CIS Docker Benchmark) | [github.com/docker/docker-bench-security](https://github.com/docker/docker-bench-security) |

## Практические сценарии

### Сценарий 1: Анализ слоев с dive

Инструмент `dive` предназначен для интерактивного исследования структуры слоев Docker-образа и поиска возможностей для уменьшения его размера.

Подробные инструкции по установке и использованию `dive` для оптимизации образов см. в разделе **[Анализ и управление слоями образа](../Docker_fs/images/layer_management.md)**.

### Сценарий 2: Линтинг Dockerfile с hadolint

```bash
# Запуск через Docker
docker run --rm -i hadolint/hadolint < Dockerfile

# Локальная установка (macOS)
brew install hadolint
hadolint Dockerfile
```

**Пример вывода:**

```
Dockerfile:5 DL3008: Pin versions in apt get install.
Dockerfile:12 DL3002: Warning: Last USER should not be root
```

### Сценарий 3: Сканирование безопасности с dockle

```bash
# Запуск через Docker
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/goodwithtech/dockle:v0.4.15 my-image:latest

# Локальная установка
dockle my-image:latest
```

**Пример вывода:**

```
FATAL - CIS-DI-0010: Suspicious mount: '/var/run/docker.sock'
WARN  - CIS-DI-0001: Create a user for the container
```

### Сценарий 4: Автоматическая оптимизация с docker-slim

```bash
# Запуск через Docker
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  dockerslim/docker-slim:latest build my-app:latest

# Результат: my-app.slim:latest (уменьшенная версия)
```

## Дополнительная информация

- **[Оптимизация сборки](./Docker_best_practices/build_optimization.md)** — принципы кэширования и multi-stage сборок
- **[Docker Images](../Docker_fs/images/docker_images_basics.md)** — основы работы с образами
- **[Docker Security](../Docker_security/overview.md)** — комплексная защита контейнеров
