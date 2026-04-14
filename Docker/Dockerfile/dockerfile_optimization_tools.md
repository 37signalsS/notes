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
| **hadolint** | Линтер `Dockerfile`, проверка синтаксиса и лучших практик | [github.com/hadolint/hadolint](https://github.com/hadolint/hadolint) |

### Сканирование безопасности

| Инструмент | Назначение | Репозиторий |
| :--- | :--- | :--- |
| **dockle** | Проверка на соответствие CIS Benchmarks, поиск уязвимостей | [github.com/goodwithtech/dockle](https://github.com/goodwithtech/dockle) |
| **docker-bench-security** | Аудит безопасности хоста Docker (CIS Docker Benchmark) | [github.com/docker/docker-bench-security](https://github.com/docker/docker-bench-security) |

## Практические сценарии

### Сценарий 1: Анализ слоев с dive

```bash
# Установка dive
# macOS
brew install dive

# Linux
curl -L https://github.com/wagoodman/dive/releases/download/v0.12.0/dive_0.12.0_linux_amd64.tar.gz | tar xz && sudo mv dive /usr/local/bin/

# Анализ образа
dive my-app:latest
```

**Возможности dive:**

- Просмотр содержимого каждого слоя
- Обнаружение файлов, удаленных в последующих слоях ( wasted space)
- Оценка эффективности слоев (image efficiency)

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
