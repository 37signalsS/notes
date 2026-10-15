# Инструменты оптимизации и анализа Dockerfile

**Актуально для:** Docker BuildKit v1.8+, Docker Buildx v0.14+, современная экосистема Docker (2024–2026)

## Определения

**Инструментарий анализа и оптимизации** — набор утилит для статического и динамического исследования Docker-образов и Dockerfile с целью уменьшения их размера, повышения безопасности и соответствия индустриальным стандартам.

Ключевые направления:
- **Линтинг:** Статический анализ текста Dockerfile для выявления синтаксических ошибок и неоптимальных инструкций.
- **Анализ слоев:** Исследование файловой структуры образа для поиска дубликатов и лишних данных.
- **Сканирование безопасности:** Поиск известных уязвимостей (CVE), секретов и мисконфигураций.
- **Управление составом (SBOM):** Генерация и анализ перечня программных компонентов образа.

## Основные концепции

### Линтинг и статический анализ

| Инструмент | Назначение | Особенности |
| :--- | :--- | :--- |
| **BuildKit Checks** | Встроенный линтер Docker | Запускается через `docker build --check` (и `docker buildx build --check`). Нативный стандарт с BuildKit v1.8+. |
| **hadolint** | Индустриальный стандарт линтинга | Проверяет инструкции на соответствие лучшим практикам (правила DLxxxx). |
| **Checkov** | Сканер IaC-безопасности | Находит мисконфигурации (запуск от root, открытый SSH и др.) применительно к Dockerfile/IaC. |
| **D-roast** | "Прожарка" Dockerfile | Rust-утилита, дающая лаконичные и конструктивные замечания по оптимизации и стилю Dockerfile. |

### Оптимизация и аудит слоев

Для глубокого анализа файловой системы образов используются специализированные инструменты, позволяющие визуализировать процесс сборки.

| Инструмент | Назначение | Репозиторий |
| :--- | :--- | :--- |
| **dive** | Интерактивный анализ слоев | [wagoodman/dive](https://github.com/wagoodman/dive) |
| **Docker Scout** | Аналитика образов Docker | Встроен в Docker CLI. Дает рекомендации по смене базового образа и оптимизации. |
| **docker-slim** | Автоматическая минимизация образа | [docker-slim/docker-slim](https://github.com/docker-slim/docker-slim). Создаёт облегчённые образы, исключая файлы, не используемые в рантайме. |

> Подробный разбор работы со слоями см. в **[Анализ и управление слоями образа](../Docker_fs/images/layer_management.md)**.

### Безопасность и сканирование CVE

Современный подход (Shift Left) подразумевает проверку образов на всех этапах жизненного цикла.

| Инструмент | Назначение | SSoT документ |
| :--- | :--- | :--- |
| **Trivy** | Универсальный сканер (CVE, секреты, мисконфигурации, лицензии) | **[Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md)** |
| **Grype** | Быстрый сканер уязвимостей | **[Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md)** |
| **Syft** | Генерация SBOM | **[SBOM для Docker](../Docker_security/docker_sbom.md)** |
| **dockle** | Проверка на соответствие лучшим практикам (включая CIS-подходы) | — |
| **Copacetic** | Патчинг уязвимостей в образе без полной пересборки исходного Dockerfile | — |

### Мониторинг и рантайм-анализ

| Инструмент | Назначение | Особенности |
| :--- | :--- | :--- |
| **Dozzle** | Веб-интерфейс для логов контейнеров | Легковесный просмотр логов в реальном времени. |
| **ctop** | TUI для мониторинга ресурсов контейнеров | Отображает CPU/Mem/Net в стиле `top`. |
| **Lazydocker** | Полноценный TUI для Docker | Управление контейнерами, образами, сетями, томами и логами из терминала. |

## Практические сценарии

### Сценарий 1: Нативный линтинг через BuildKit (Стандарт 2026)

Начиная с Docker Buildx v0.14+ и BuildKit v1.8, проверки встроены непосредственно в процесс сборки.

```bash
# Проверка Dockerfile без выполнения сборки
docker build --check .

# Перевод предупреждений в ошибки для CI/CD
# syntax=docker/dockerfile:1
# check=error=true
```

### Сценарий 2: Комплексный аудит образа (Scout + Trivy)

Использование Docker Scout для получения рекомендаций и Trivy для глубокого сканирования.

```bash
# 1. Быстрый обзор и рекомендации по базовому образу
docker scout quickview my-app:latest

# 2. Сканирование только исправляемых (fixed) критических уязвимостей
trivy image --severity CRITICAL --ignore-unfixed my-app:latest
```

### Сценарий 3: Поиск "мусора" в слоях с dive

```bash
# Запуск анализа
dive my-app:latest

# CI-режим: падать при низкой эффективности слоёв (>5% мусора) или избыточном размере
CI=true dive --lowestEfficiency 0.95 --highestWastedBytes 20MB <reg>/<name>:tag
```
В интерфейсе обратите внимание на колонку **Efficiency**. Если она ниже 90%, образ содержит файлы, которые были созданы и затем удалены в разных слоях (типичная ошибка — `apt-get clean` в отдельной инструкции `RUN`).

### Сценарий 4: Генерация SBOM для комплаенса

```bash
# Генерация в формате CycloneDX JSON
syft my-app:latest -o cyclonedx-json > sbom.json
```

## Installation and Setup

### BuildKit Checks (встроенный)

BuildKit Checks доступен нативно при использовании Docker с BuildKit (v1.8+). Дополнительной установки не требуется.

```bash
# Проверка версии BuildKit через сборку
DOCKER_BUILDKIT=1 docker build --check .
```

### hadolint

| Способ установки | Примечания |
|---|---|
| `docker run --rm -i hadolint/hadolint:latest-debian < Dockerfile` | Универсальный вариант (без локальной установки). |
| `brew install hadolint` (macOS) | Через Homebrew. |
| `curl -L https://github.com/hadolint/hadolint/releases/latest/download/hadolint-Linux-x86_64 -o /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint` | Linux (x86_64). |

### dive

```bash
# macOS (Homebrew)
brew install dive

# Linux (go install)
go install github.com/wagoodman/dive@latest

# Docker (без установки в систему)
docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock wagoodman/dive:latest <image>
```

### Trivy

```bash
# macOS
brew install trivy

# Linux
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin
```

### Grype, Syft

```bash
# Grype
curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin

# Syft
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin
```

### dockle, Copacetic, Checkov, docker-slim, D-roast

Установка через релизы GitHub или пакетные менеджеры (в зависимости от платформы). Для CI/CD предпочтительно использовать готовые контейнерные образы.

## Configuration

### hadolint — конфигурация

Hadolint поддерживает конфигурационный файл `.hadolint.yaml` (или `.hadolint.yml`) в корне проекта.

```yaml
# .hadolint.yaml
ignored:
  - DL3008  # Pin versions in apt-get install (опционально)
  - DL3018  # Pin versions in apk add

trustedRegistries:
  - docker.io
  - ghcr.io
```

Проверка с явным указанием конфигурации:

```bash
hadolint --config .hadolint.yaml Dockerfile
```

### BuildKit Checks — поведение в Dockerfile

Для управления строгостью проверок можно использовать директиву `check`:

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true
```

Данная настройка полезна для CI/CD (превращает предупреждения в ошибки).

## Operations and Commands

Ниже приведены базовые рабочие варианты использования инструментов. Детальные сценарии см. выше в разделе «Практические сценарии».

| Инструмент | Базовая команда | Примечания |
|---|---|---|
| BuildKit Checks | `docker build --check .` (или `docker buildx build --check .`) | Проверка без сборки образа. |
| hadolint | `hadolint Dockerfile` | Статический линтинг. |
| Checkov | `checkov -f Dockerfile` | Анализ Dockerfile на мисконфигурации. |
| D-roast | `d-roast Dockerfile` | Рекомендации по оптимизации (формат вывода зависит от версии). |
| dive | `dive <image>` | Интерактивный анализ слоёв (TUI). |
| Docker Scout | `docker scout quickview <image>` / `docker scout recommendations <image>` | Работает при авторизации в Docker Hub/Docker Scout в соответствующих окружениях. |
| docker-slim | `docker-slim build <image>` | Создаёт минимизированную версию образа (требует осторожной валидации работоспособности). |
| Trivy | `trivy image --severity CRITICAL --ignore-unfixed <image>` | Фильтр по критическим, ещё не исправленным уязвимостям. |
| Grype | `grype <image>` | Быстрое сканирование CVE. |
| Syft | `syft <image> -o cyclonedx-json > sbom.json` | Генерация SBOM. |
| dockle | `dockle <image>` | Проверка соответствия лучшим практикам. |
| Copacetic | `copa patch -i <image> -t <patched>` | Патчинг образа без пересборки по Dockerfile (требует соответствующих условий). |

## Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| `dive` не видит образы | Отсутствует доступ к Docker daemon (`/var/run/docker.sock`). | Запускать с монтированием сокета Docker (см. Installation and Setup). |
| BuildKit Checks не срабатывает | Используется старый Docker/BuildKit без поддержки `--check`. | Обновить Docker/Buildx, использовать `DOCKER_BUILDKIT=1` или Buildx. |
| hadolint выдаёт много ложных срабатываний | Нет конфигурации под проект. | Добавить `.hadolint.yaml` с `ignored` правилами (только при обоснованной необходимости). |
| docker-slim сильно урезает образ | Автоматическая минимизация может удалить нужные файлы/библиотеки (динамическая загрузка). | Тестировать работоспособность минимизированного образа, использовать `--include`/опции docker-slim для сохранения необходимых компонентов. |
| Trivy не находит свежие БД | Устаревшие локальные БД или проблемы с доступом. | Обновить БД (`trivy image --update`) или использовать настройки оффлайн-обновления в изолированных окружениях (см. Docker/Harbor). |

## Best Practices

- **Shift Left:** выполнять статический линтинг (BuildKit Checks, hadolint) ещё до отправки в реестр (в локальной разработке и CI/CD).
- **Комбинировать инструменты:** линтинг (hadolint/BuildKit) + аудит слоёв (dive) + сканирование безопасности (Trivy/Grype) + SBOM (Syft) — наиболее сбалансированный подход.
- **Не дублировать очистку слоёв:** `apt-get clean`, `rm -rf /var/lib/apt/lists/*` выполнять в той же инструкции `RUN`, где производилась установка (см. [оптимизацию сборки](./Docker_best_practices/build_optimization.md)).
- **Верифицировать минимизацию:** перед продакшен-использованием образа, созданного `docker-slim`, обязательно проверить его работоспособность (health-check'и, ключевые эндпоинты/процессы).
- **Сканировать только то, что нужно:** использовать `--ignore-unfixed`, фильтрацию по severity, чтобы фокусироваться на реально устраняемых уязвимостях без блокировки по нефиксируемым в базовом образе.
- **Pin-версии обоснованно:** при использовании hadolint с DL3008/DL3018 — игнорировать правило только при наличии веской причины и документировать её.
- **Использовать нативное:** отдавать предпочтение встроенным возможностям (BuildKit Checks) там, где они покрывают потребности, не вводя лишних зависимостей.

## Дополнительная информация

### Смотрите также
- **[Оптимизация сборки Docker-образов](./Docker_best_practices/build_optimization.md)** — архитектурные приёмы оптимизации.
- **[Безопасность в Dockerfile](./Docker_best_practices/security.md)** — правила написания защищённого Dockerfile.
- **[Анализ и управление слоями образа](../Docker_fs/images/layer_management.md)** — SSoT по работе со слоями образа (в т.ч. практика работы с `dive`).
- **[Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md)** — SSoT по работе с `Trivy` и `Grype`.
- **[SBOM для Docker](../Docker_security/docker_sbom.md)** — SSoT по генерации и работе с SBOM (Syft).
- **[Оффлайн-обновление Trivy](../Docker_registries/Harbor/offline_trivy_update.md)** — особенности работы Trivy в изолированных (закрытых) контурах (без доступа к интернету).
