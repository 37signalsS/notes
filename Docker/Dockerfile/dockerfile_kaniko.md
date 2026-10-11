# Kaniko: Сборка Docker-образов без демона

**Актуально для:** osscontainertools/kaniko 1.28.x (форк сообщества); официальная Google-ветка (kaniko 1.23.x) архивирована и более не поддерживается.

> [!WARNING]
> **Статус проекта (2025):** Официальный репозиторий Google (`GoogleContainerTools/kaniko`) был **архивирован 3 июня 2025 года**. Новые функции и патчи безопасности от Google более не выпускаются. В актуальных инфраструктурах рекомендуется использовать форк от сообщества — **[osscontainertools/kaniko](https://github.com/osscontainertools/kaniko)** или мигрировать на **[BuildKit (Standalone)](./dockerfile_buildkit.md)**.

## Определения

**Kaniko** — инструмент для сборки образов контейнеров из `Dockerfile` без зависимости от Docker-демона. Он выполняет инструкции внутри пользовательского пространства (userspace), что делает его стандартом для сред с жесткими ограничениями безопасности (Kubernetes, GitLab CI), где использование привилегированных контейнеров или монтирование Docker Socket запрещено.

Ключевые особенности:
- Работает без root-прав и привилегий на хосте.
- Не требует `--privileged` режима.
- Совместим с **Pod Security Standards (Baseline)** (профиль `restricted` недостижим для стокового образа — см. ниже).
- Использует изоляцию в пользовательском пространстве: распаковывает файловую систему базового образа непосредственно в корень своего контейнера (без `chroot` и bind-mount).
- Поддерживает multi-stage сборки и удалённое кэширование.

### Архитектура

```
┌─────────────────────────────────────────────────┐
│                  Kaniko Executor                │
│  ┌───────────────────────────────────────────┐  │
│  │            Пространство пользователя      │  │
│  │  ┌─────────────┐  ┌──────────────────┐   │  │
│  │  │  Executor   │  │  Snapshot Manager│   │  │
│  │  │  (парсинг   │  │  (diff слоёв)    │   │  │
│  │  │  Dockerfile)│  │                  │   │  │
│  │  └──────┬──────┘  └────────┬─────────┘   │  │
│  │         │                  │              │  │
│  │         ▼                  ▼              │  │
│  │  ┌──────────────────────────────────┐    │  │
│  │  │  Извлечение base image прямо      │    │  │
│  │  │  в корень контейнера (без chroot) │    │  │
│  │  └──────────────────────────────────┘    │  │
│  └───────────────────────────────────────────┘  │
│                                                   │
│  ┌───────────────────────────────────────────┐  │
│  │         Push к клиенту реестра            │  │
│  │    (Registry API / OCI Distribution)      │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Предварительные требования

### Программное обеспечение

- **Docker** (для локальной отладки) или **Kubernetes** / **CI-runner** (для production)
- **Dockerfile** — стандартный синтаксис Docker (поддерживает большинство инструкций, есть ограничения — см. ниже)
- **Доступ к реестру образов** (Docker Hub, GCR, Harbor, ECR и др.) — для пуша результатов

### Доступные образы Kaniko

| Образ | Назначение |
| :--- | :--- |
| `gcr.io/kaniko-project/executor:latest` | Официальный образ Google (архивирован) |
| `gcr.io/kaniko-project/executor:debug` | С поддержкой shell для отладки (архивирован) |
| `ghcr.io/osscontainertools/kaniko:v1.28.5` | Актуальный форк сообщества (рекомендуется, основной реестр) |
| `ghcr.io/osscontainertools/kaniko:v1.28.5-debug` | Форк + shell для отладки |
| `ghcr.io/osscontainertools/kaniko:v1.28.5-warmer` | Предварительный нагрев кэша базовых образов |
| `ghcr.io/osscontainertools/kaniko:v1.28.5-bootstrap` | Сборка кастомных образов kaniko |
| `ghcr.io/osscontainertools/kaniko:v1.28.5-slim` | Минимальный образ без credential-helpers |
| `ghcr.io/osscontainertools/kaniko:v1.28.5-alpine` | Alpine-вариант образа |
| `martizih/kaniko:v1.28.5` | Форк сообщества (Docker Hub-зеркало) |

> **Рекомендация:** Используйте форк `osscontainertools` (`ghcr.io/osscontainertools/kaniko`, Docker Hub — зеркало) для получения актуальных обновлений безопасности. Официальный образ Google (`gcr.io/kaniko-project/*`) не обновляется с момента архивации.

### Проверка работоспособности

```bash
# Проверка доступа к реестру
docker login registry.example.com

# Быстрая проверка Kaniko (сборка без пуша)
docker run --rm \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5-debug \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --no-push
# → Building... Done.
```

## Базовые концепции

### Принцип работы Kaniko (пошагово)

Главное отличие Kaniko от классического Docker заключается в том, что он **вообще не запускает контейнеры** для сборки. Вместо механизмов ядра (namespaces) он использует эмуляцию в пользовательском пространстве (userspace).

1.  **Распаковка базового образа:** При обработке инструкции `FROM`, Kaniko скачивает образ и **распаковывает** его файловую систему **непосредственно в корень собственного контейнера** (`/`). `chroot` и bind-mount не используются — они требуют прав `CAP_SYS_ADMIN`, которых у обычного контейнера нет.
2.  **Выполнение команд (RUN) в том же контейнере:** Команды `RUN` исполняются как обычные процессы внутри контейнера Kaniko, **видя распакованную файловую систему образа в качестве корня** `/`.
3.  **Снапшоты (Snapshots):** После каждой команды `RUN` Kaniko сравнивает текущее состояние файлов с предыдущим, вычисляет разницу (diff) и упаковывает измененные файлы в новый слой (`tar.gz`).
4.  **Multi-stage сборки и оптимизация:** 
    - **Статический анализ (Built cross stage deps):** Перед началом работы Kaniko строит карту зависимостей между стадиями. Это позволяет заранее знать, какие файлы из ранних стадий понадобятся позже.
    - **Сохранение артефактов:** При завершении стадии Kaniko физически копирует нужные файлы (логи: `Saving file <path> for later use`) во внутреннее временное хранилище.
    - **Полная очистка (Deleting filesystem):** Перед началом новой стадии Kaniko полностью удаляет содержимое рабочего пространства, оставляя только сохраненные артефакты. Это гарантирует изоляцию стадий и отсутствие лишнего мусора в финальном образе.
5.  **Формирование и отправка:** В конце процесса Kaniko собирает все слои и манифест, отправляя их в реестр через HTTP API.

### Модель эшелонированной защиты (Defense-in-depth)

Kaniko обеспечивает безопасность через несколько уровней изоляции:

1.  **Отсутствие `chroot` и привилегированных механизмов:** Kaniko не использует `chroot` и не требует `CAP_SYS_ADMIN` — изоляция достигается развёртыванием в обычном контейнере. (Примечание: executor исполняется с UID 0 внутри своего контейнера — это необходимо для записи распакованного образа в корень `/`; отдельный не-root пользователь в стоковом образе не предусмотрен.)
2.  **Отсутствие привилегий ядра:** Контейнер Kaniko запускается без `--privileged`. У него нет прав на монтирование устройств или изменение параметров ядра хоста.
3.  **Ограничения оркестратора:** В Kubernetes NetworkPolicy может жестко ограничить сетевую активность процесса сборки, не позволяя ему сканировать внутреннюю сеть.

> **Соответствие PSS:** стоковый образ Kaniko проходит профиль `baseline` (в `deploy/Dockerfile` задано `ENV USER=root`, процесс исполняется с UID 0 — это необходимо для записи распакованного образа в корень `/`). Профиль `restricted` требует `runAsNonRoot: true`, `runAsUser ≠ 0` и `allowPrivilegeEscalation: false`, что для стокового образа невозможно. Варианты для `restricted`-сред: сборка собственного образа kaniko с директивой `USER` (и учётом реальных прав на запись), либо выделение отдельного неймспейса сборки с профилем `baseline` + NetworkPolicy.

### Особенности кэширования

Логика кэширования в Kaniko фундаментально отличается от Docker:
-   **Удаленный кэш (Remote-only):** Kaniko по умолчанию хранит кэшированные слои в удаленном Registry (`--cache-repo`). Локального постоянного кэша на диске не существует (контейнер удаляется после сборки).
-   **Транзитная природа:** Контейнер полностью удаляется вместе со всеми данными. Кэш "внутри себя" Kaniko сохранить не может.
-   **Логика "все или ничего":** Для работы кэша (`--cache=true`) обязательно требуется внешний реестр, даже если финальный образ не пушится (`--no-push`).
-   **Оптимизация (v1.24+):** Поддержка флага `--no-push-cache=false` (по умолчанию) позволяет пушить кэш даже при использовании `--no-push` для основного образа.

### Контекст сборки

Параметр `--context` определяет источник исходного кода. Для локальной файловой системы Kaniko требует префикс протокола:
-   `dir://` — локальная директория (например, `--context=dir:///workspace`).
-   `git://` — Git-репозиторий. Начиная с v1.22+, поддерживаются расширенные опции: `--git=branch=main,recursive=true` и использование `GIT_TOKEN`.
-   `s3://`, `gs://` — облачные хранилища.

## Флаги executor (CLI Options Reference)

### Основные команды Kaniko

| Команда | Описание |
| :--- | :--- |
| `/kaniko/executor` | Сборка и пуш образа (основной flow) |
| `/kaniko/executor login <registry>` | Аутентификация в реестре (сохраняет в `config.json`) |
| `/kaniko/executor push <path>` | Пуш pre-built образа из tar/OCI-layout |
| `/kaniko/executor bake <file>` | Декларативная сборка из HCL-файла (аналог Bake) |

### Основные флаги

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `--dockerfile` | Путь к Dockerfile | `--dockerfile=./Dockerfile` |
| `--context` | Источник исходного кода | `--context=dir:///workspace` |
| `--destination` | Целевой реестр и тег (можно несколько раз) | `--destination=reg/app:v1` |
| `--no-push` | Сборка без отправки в реестр | `--no-push` |
| `--tar-path` | Экспорт образа в tar-файл | `--tar-path=/workspace/image.tar` |
| `--digest-file` | Запись SHA256 digest в файл | `--digest-file=/kaniko/digest.txt` |

### Кэширование

| Флаг | Описание |
| :--- | :--- |
| `--cache=true` | Включение удалённого кэширования |
| `--cache-repo` | Реестр для хранения кэшированных слоёв (по умолчанию выводится из `--destination`) |
| `--cache-dir` | Локальная директория для кэша базовых образов (по умолчанию `/cache`) |
| `--cache-ttl` | Время жизни кэша (по умолчанию 336h — две недели) |
| `--cache-run-layers` | Кэшировать слои `RUN` (по умолчанию true) |
| `--cache-copy-layers` | Кэшировать слои `COPY` (по умолчанию false — `COPY` не кэшируется) |
| `--no-push-cache` | Отключение пуша кэша при `--no-push` (по умолчанию false) |
| `--snapshot-mode` | Режим снапшотов: `full` (по умолчанию, точный), `redo` (быстрый), `time` |

### Безопасность и аутентификация

| Флаг | Описание |
| :--- | :--- |
| `--registry-certificate` | Сертификат для конкретного реестра |
| `--credential-helpers` | Встроенные credential helpers: `env`, `google`, `ecr`, `acr`, `gitlab` (default: все) |
| `--insecure` | Использовать HTTP вместо HTTPS (push) |
| `--skip-tls-verify` | Пропустить проверку TLS-сертификата (push) |
| `--insecure-pull` / `--skip-tls-verify-pull` | То же для pull |
| `--insecure-registry` / `--skip-tls-verify-registry` | То же для pull+push конкретного реестра |

### Сборка

| Флаг | Описание |
| :--- | :--- |
| `--build-arg` | Передача аргументов сборки |
| `--label` | Метаданные образа |
| `--secret` | Секреты сборки: `--secret id=NAME,env=VAR` или `--secret id=NAME,src=/path` (в Dockerfile — `RUN --mount=type=secret`) |
| `--target` | Целевая стадия multi-stage (можно несколько раз) |
| `--custom-platform` | Целевая платформа (например, `linux/arm64`); последовательно, без эмуляции |
| `--annotation` | Метаданные-аннотации образа (key=value, повторяемый) |
| `--reproducible` | Убрать временные метки из образа |
| `--git` | Git-опции контекста: `--git=branch=main,recursive=true` |
| `--context-sub-path` | Подпуть внутри контекста (для сборки поддиректории git-репо) |

### Вывод

| Флаг | Описание |
| :--- | :--- |
| `--image-name-with-digest-file` | Запись имени образа с digest в файл |
| `--image-name-tag-with-digest-file` | Запись имени образа, тега и digest в файл |
| `--oci-layout-path` | Экспорт в OCI-layout |
| `--image-format` | Формат образа: `docker` (schema2) или `oci` (по умолчанию наследуется от base image) |
| `--tar-path` | Экспорт в tar (schema2; не совместим с `--image-format=oci`) |
| `--single-snapshot` | Один снапшот на всю стадию (ускорение) |
| `--compressed-caching` | Сжатие кэшированных слоёв (по умолчанию true) |
| `--compression` | Алгоритм сжатия слоёв: `gzip` (по умолчанию) или `zstd` |
| `--compression-level` | Уровень сжатия: для gzip `-2..9`, для zstd `1..22` (по умолчанию — fastest) |
| `--use-new-run` | Экспериментальная реализация RUN без снапшотов ФС |

### Диагностика

| Флаг | Описание |
| :--- | :--- |
| `--verbosity` | Уровень логирования (trace, debug, info, warn, error) |
| `--log-timestamp` | Добавлять временны́е метки в логи |
| `--log-format` | Формат логов: `color` (default), `text`, `json` |
| `--push-retry` | Количество повторов при push |
| `--image-download-retry` | Повторы при сбое скачивания образа |
| `--image-fs-extract-retry` | Повторы при сбое распаковки образа |
| `--cleanup` / `--pre-cleanup` | Очистка ФС в конце / перед сборкой |
| `--digest-file` | Запись SHA256 digest в файл |

### Переменные окружения

Kaniko поддерживает несколько переменных окружения для настройки без флагов:

| Переменная | Описание |
| :--- | :--- |
| `GOOGLE_APPLICATION_CREDENTIALS` | Путь к JSON-ключу сервисного аккаунта GCP (для GCR/AR) |
| `DOCKER_CONFIG` | Путь к директории с конфигурацией Docker (по умолчанию `/kaniko/.docker`) |
| `DOCKER_AUTH_CONFIG` | JSON-конфигурация `auths`; приоритет над `config.json` |
| `AWS_ACCESS_KEY_ID` | Ключ доступа AWS (для ECR) |
| `AWS_SECRET_ACCESS_KEY` | Секретный ключ AWS (для ECR) |
| `AWS_DEFAULT_REGION` | Регион AWS |
| `GIT_TOKEN` | Токен для доступа к приватным Git-репозиториям |
| `KANIKO_<HOST_WITH_UNDERSCORES>_USER` / `_PASSWORD` | Credential helper `env`: `KANIKO_REGISTRY_EXAMPLE_COM_USER/PASSWORD` |
| `CI_REGISTRY` / `CI_REGISTRY_USER` / `CI_REGISTRY_PASSWORD` | GitLab Registry (читает helper `gitlab`) |
| `KANIKO_DIR` | Расположение рабочих файлов Kaniko (по умолчанию `/kaniko`; замена deprecated `--kaniko-dir`) |
| `KANIKO_CLEANUP` / `KANIKO_PRE_CLEANUP` | Очистка ФС в конце / перед сборкой |
| `KANIKO_TELEMETRY_ENDPOINT` | OTLP-эндпоинт трейсов (телеметрия выключена по умолчанию) |

### Аутентификация в реестрах

Kaniko использует тот же формат конфигурации Docker для аутентификации:

```bash
# Создание конфигурации
mkdir -p /kaniko/.docker
echo "{\"auths\":{\"$REGISTRY\":{\"auth\":\"$(printf '%s:%s' "$USER" "$PASS" | base64)\"}}}" \
  > /kaniko/.docker/config.json

# Или с токеном
echo "{\"auths\":{\"$REGISTRY\":{\"auth\":\"$(printf 'oauth2accesstoken:%s' "$TOKEN" | base64)\"}}}" \
  > /kaniko/.docker/config.json
```

## Сравнение методов сборки

| Критерий | DinD (Docker-in-Docker) | BuildKit (Standalone) | Kaniko |
| :--- | :--- | :--- | :--- |
| **Демон Docker** | Нужен | Не нужен (`buildkitd`) | Не нужен |
| **Привилегии** | Нужны (`--privileged`) | Не нужны (rootless) | Не нужны |
| **Безопасность / PSS** | Низкая (privileged) | Высокая | Высокая (baseline, не restricted) |
| **Кэширование** | Локальное | Локальное / Remote | Только Remote |
| **Совместимость** | 100% | Высокая | Высокая (с ограничениями) |
| **BuildKit функции** | Поддерживаются | Полная поддержка | `RUN --mount=type=cache/secret/bind` в v1.28+ |
| **Multi-arch** | Последовательно | Одновременно | Последовательно (`--custom-platform`) |
| **Аттестации (SBOM)** | Нет | Да | Нет |
| **Параллелизм** | Нет | Нативный (LLB) | Последовательно |
| **Multi-stage** | Поддерживается | Поддерживается | Поддерживается |
| **Secrets** | Через ARG (небезопасно) | `type=secret` | `--secret` (`RUN --mount=type=secret`) |
| **Ресурсоемкость** | Высокая | Средняя | Низкая |
| **Рекомендуемый сценарий** | Локальная разработка | CI/CD, production | CI/CD, Kubernetes (неймспейс baseline) |

## Практические сценарии

### Сценарий 1: Сборка в GitLab CI (форк v1.28.5)

Рекомендуется использовать образ из форка `osscontainertools` (`ghcr.io/osscontainertools/kaniko`) для получения актуальных обновлений.

```yaml
build-app:
  stage: build
  image:
    # Использование актуального форка сообщества
    name: ghcr.io/osscontainertools/kaniko:v1.28.5-debug
    entrypoint: [""]
  script:
    # Аутентификация встроенным credential helper 'gitlab'
    # (читает CI_REGISTRY / CI_REGISTRY_USER / CI_REGISTRY_PASSWORD)
    - /kaniko/executor \
        --context "dir://${CI_PROJECT_DIR}" \
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}" \
        --credential-helpers gitlab \
        --cache=true \
        --cache-repo "${CI_REGISTRY_IMAGE}/cache" \
        --digest-file=/kaniko/digest.txt
  artifacts:
    paths:
      - /kaniko/digest.txt
```

### Сценарий 2: Локальная отладка через Docker

```bash
docker run \
    -v $(pwd):/workspace \
    ghcr.io/osscontainertools/kaniko:v1.28.5 \
    --dockerfile=/workspace/Dockerfile \
    --context=dir:///workspace \
    --no-push
```

### Сценарий 3: Сборка с кэшированием и отправкой в Harbor

```bash
docker run \
  -v $(pwd):/workspace \
  -v $HOME/.docker/config.json:/kaniko/.docker/config.json:ro \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --destination=harbor.example.com/myproject/app:$(git rev-parse --short HEAD) \
  --cache=true \
  --cache-repo=harbor.example.com/myproject/cache \
  --digest-file=/workspace/digest.txt
```

### Сценарий 4: Сборка с секретами (private npm packages)

```bash
# Подготовка секретов
echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > .npmrc

# Запуск сборки
docker run \
  -v $(pwd):/workspace \
  -v $(pwd)/.npmrc:/workspace/.npmrc:ro \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --destination=reg/app:v1 \
  --build-arg=NPM_TOKEN=${NPM_TOKEN} \
  --no-push
```

В Dockerfile:

```dockerfile
FROM node:22-alpine
ARG NPM_TOKEN
RUN echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > /root/.npmrc && \
    npm install && \
    rm /root/.npmrc
COPY . .
CMD ["node", "server.js"]
```

### Сценарий 5: Сборка с добавлением метаданных и лейблов

```bash
docker run \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --destination=reg/app:v1.2.3 \
  --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
  --label "org.opencontainers.image.version=1.2.3" \
  --label "maintainer=team@example.com"
```

### Сценарий 6: Сборка multi-stage с сохранением артефактов

```dockerfile
# Стадия сборки
FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /bin/app .

# Стадия runtime
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /bin/app /app
ENTRYPOINT ["/app"]
```

```bash
docker run \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --destination=reg/app:v1 \
  --no-push
```

> **Примечание:** Kaniko корректно обрабатывает multi-stage сборки, сохраняя артефакты из предыдущих стадий. Однако из-за последовательного выполнения сборка может быть медленнее, чем в BuildKit.

### Сценарий 7: Сборка из Git-репозитория

```bash
docker run \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --git=branch=main,recursive=true \
  --context=git://github.com/user/repo.git \
  --destination=reg/app:v1
```

С использованием токена:

```bash
export GIT_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

docker run \
  -e GIT_TOKEN=${GIT_TOKEN} \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --git=branch=main,recursive=true \
  --context=git://github.com/user/private-repo.git \
  --destination=reg/app:v1
```

### Сценарий 8: Декларативная сборка через `kaniko bake`

Начиная с v1.28.5, Kaniko поддерживает экспериментальную команду `bake` для сборки нескольких образов из одного Dockerfile через HCL-файл:

`bake.hcl`:
```hcl
target "app" {
  destination = ["registry.example.com/app:latest"]
}

target "tools" {
  destination = ["registry.example.com/tools:latest"]
}
```

Запуск:
```bash
docker run \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  bake /workspace/bake.hcl \
  --context=dir:///workspace \
  --dockerfile=/workspace/Dockerfile \
  --cache=true \
  --cache-repo=registry.example.com/cache
```

> **Примечание:** `kaniko bake` — экспериментальная функция. Синтаксис HCL отличается от `docker-bake.hcl` (Buildx); файлы несовместимы между инструментами.

## Работа с результатом сборки

Поскольку Kaniko не сохраняет образ в `docker images` локально, существуют специальные методы извлечения результата.

### Метод 1: Экспорт в TAR-архив
Позволяет сохранить образ в файл для последующей загрузки через `docker load`.

```bash
/kaniko/executor \
    --context=dir:///workspace \
    --destination=my-app:latest \
    --tar-path=/workspace/my-app.tar \
    --no-push
```

Затем загрузка в Docker:

```bash
docker load -i my-app.tar
docker run --rm my-app:latest
```

### Метод 2: Использование локального реестра
```bash
# Запуск локального реестра
docker run -d -p 5000:5000 --name registry registry:3

# Сборка и отправка
docker run --rm --network host \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --destination=localhost:5000/my-app:latest \
  --insecure \
  --skip-tls-verify
```

### Метод 3: Запись digest для использования в Kubernetes

```bash
/kaniko/executor \
    --context=dir:///workspace \
    --destination=reg/app:v1 \
    --digest-file=/workspace/digest.txt

# Использование digest в kubectl
kubectl set image deployment/app app=reg/app@$(cat digest.txt)
```

## Интеграция в CI/CD

### GitHub Actions

```yaml
name: Build with Kaniko
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build with Kaniko
        run: |
          docker run --rm \
            -v "$PWD":/workspace \
            -e DOCKER_CONFIG=/kaniko/.docker \
            ghcr.io/osscontainertools/kaniko:v1.28.5 \
            --dockerfile=/workspace/Dockerfile \
            --context=dir:///workspace \
            --destination=myregistry.com/app:${{ github.sha }} \
            --cache=true \
            --cache-repo=myregistry.com/cache \
            --push-retry=3
```

### Jenkins (Pipeline)

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh '''
                    docker run --rm \
                      -v $(pwd):/workspace \
                      -v $HOME/.docker/config.json:/kaniko/.docker/config.json:ro \
                      ghcr.io/osscontainertools/kaniko:v1.28.5 \
                      --dockerfile=/workspace/Dockerfile \
                      --context=dir:///workspace \
                      --destination=myregistry.com/app:${BUILD_NUMBER} \
                      --cache=true \
                      --cache-repo=myregistry.com/cache
                '''
            }
        }
    }
}
```

### Kubernetes Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: kaniko-build
spec:
  template:
    spec:
      containers:
        - name: kaniko
          image: ghcr.io/osscontainertools/kaniko:v1.28.5-debug
          args:
            - "--dockerfile=/workspace/Dockerfile"
            - "--context=dir:///workspace"
            - "--destination=reg/app:v1"
            - "--cache=true"
            - "--cache-repo=reg/cache"
          volumeMounts:
            - name: docker-config
              mountPath: /kaniko/.docker/
            - name: workspace
              mountPath: /workspace
      volumes:
        - name: docker-config
          secret:
            secretName: registry-credentials
            items:
              - key: config.json
                path: config.json
        - name: workspace
          persistentVolumeClaim:
            claimName: source-code-pvc
      restartPolicy: Never
```

> **Примечание:** В Kubernetes Job секреты аутентификации передаются через Kubernetes Secrets и монтируются в `/kaniko/.docker/config.json`.

## Разрешение проблем

### Типичные ошибки

**1. Ошибка: `UNAUTHORIZED` или `authentication required`**

Причина: Неверные credentials или отсутствует конфигурация реестра.

Решение:

```bash
# Проверка наличия конфигурации
cat /kaniko/.docker/config.json

# Пересоздание конфигурации
echo "{\"auths\":{\"registry.example.com\":{\"auth\":\"$(printf '%s:%s' "$USER" "$PASS" | base64)\"}}}" \
  > /kaniko/.docker/config.json
```

**2. Ошибка: `failed to extract layer` / `read-only file system` при распаковке образа**

Причина: Kaniko распаковывает файловую систему базового образа в корень собственного контейнера (`/`) (`constants.RootDir = "/"`). Если корневой слой смонтирован read-only (например, `readOnlyRootFilesystem: true` в Kubernetes), распаковка падает.

Решение: Убедитесь, что у контейнера Kaniko есть записываемый корневой слой. Не задавайте `readOnlyRootFilesystem: true` для executor; рабочие каталоги (`/kaniko`, workspace) должны быть доступны на запись:

```bash
docker run -v $(pwd):/workspace ghcr.io/osscontainertools/kaniko:v1.28.5-debug
```

**3. Ошибка: `error building image: failed to get reader: Get https://registry...: tls: certificate signed by unknown authority`**

Причина: Самоподписанный сертификат реестра.

Решение:

```bash
# Монтирование сертификата
docker run \
  -v /path/to/ca.crt:/kaniko/ssl/certs/ca-certificates.crt:ro \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --registry-certificate=registry.example.com=/path/to/ca.crt \
  ...
```

**4. Ошибка: «read-only file system» при работе с `/kaniko` (например, `mkdir /kaniko/...` / `moveKanikoDir`)**

Причина: рабочий каталог `/kaniko` смонтирован read-only или раннер запрещает запись в него; некоторые контейнерные рантаймы накладывают ограничения на запись в корневой каталог.

Решение: **не добавляйте capabilities** — это противоречит модели безопасности Kaniko. Переместите рабочий каталог через переменную окружения `KANIKO_DIR`:

```bash
docker run \
  -e KANIKO_DIR=/workspace/kaniko \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --no-push
```

> Переменная `KANIKO_DIR` заменила устаревший флаг `--kaniko-dir`. При её изменении путь к `config.json`, digest-файлам и внутренним каталогам также меняется.

**5. Медленная сборка больших проектов**

Причина: отсутствие кэширования или полное сканирование ФС при `--snapshot-mode=full` (режим по умолчанию).

Решение:

```bash
# Включение кэширования
--cache=true --cache-repo=reg/cache

# Быстрый режим снапшотов (проверяйте корректность слоёв!)
--snapshot-mode=redo
```

**6. Ошибка: `error pushing image: ... Name unknown`**

Причина: Репозиторий не существует в реестре.

Решение: Убедитесь, что репозиторий создан в реестре (Docker Hub, Harbor, ECR) перед пушем. Для ECR:

```bash
aws ecr create-repository --repository-name my-app
```

### Диагностические команды

```bash
# Проверка версии Kaniko
docker run --rm ghcr.io/osscontainertools/kaniko:v1.28.5 version

# Сборка с подробным логированием
docker run --rm \
  -v $(pwd):/workspace \
  ghcr.io/osscontainertools/kaniko:v1.28.5-debug \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --no-push \
  --verbosity=trace

# Просмотр внутренней структуры образа
docker run --rm -it ghcr.io/osscontainertools/kaniko:v1.28.5-debug shell
# Внутри контейнера:
ls -la /kaniko/
ls -la /kaniko/workspace/
cat /kaniko/.docker/config.json
```

## Лучшие практики

### Структура проекта

```
.
├── Dockerfile
├── .dockerignore
├── .kaniko/
│   └── cache/          # Локальный кэш (для отладки)
└── .gitlab-ci.yml      # Или .github/workflows/
```

### Рекомендации

1. **Используйте форк `osscontainertools`** (`ghcr.io/osscontainertools/kaniko`) вместо официального образа Google (архивирован).
2. **Настройте кэширование** — указывайте `--cache-repo` и `--cache-copy-layers=true` для ускорения повторных сборок.
3. **Используйте `--digest-file`** для интеграции с Kubernetes (точное указание образа по SHA256).
4. **Понимайте дефолты снапшотов:** по умолчанию активен `--snapshot-mode=full` (точный, медленнее). `--snapshot-mode=redo` быстрее, но подходит не для всех Dockerfile — переключайте осознанно и проверяйте корректность слоёв.
5. **Передавайте секреты через `--secret id=NAME,env=VAR`** (в Dockerfile — `RUN --mount=type=secret,id=NAME`) или монтируйте файлы `.npmrc`/`.env` как ро-файлы, а не через `ARG` (ARG оседает в слоях image history).
6. **Используйте `--verbosity=debug`** для отладки проблемных сборок.
7. **Указывайте `--push-retry=3`** для fault-tolerance в CI/CD.
8. **Регулярно обновляйте** образ Kaniko: форк выпускает патч-релизы каждые ~2 недели (без изменения поведения), версия пиннится в шаблоне.

### Очистка

```bash
# Удаление локальных кэшированных образов
docker image prune -f

# Удаление временных файлов Kaniko
docker run --rm -v $(pwd):/workspace ghcr.io/osscontainertools/kaniko:v1.28.5 \
  rm -rf /kaniko/workspace/

# Удаление кэша в реестре
# (зависит от реестра — для Harbor используйте GC, для Docker Hub — ручное удаление)
```

## Известные проблемы и совместимость

### Ограничения совместимости

Kaniko **не поддерживает** следующие инструкции и функции:

- **`--mount=type=ssh`** — не поддерживается (флага `--ssh` в исполнителе нет с перехода на 1.28.x; в BuildKit для этого используется SSH-forwarding-agent).
- **Cross-stage `--mount=type=bind,from=<stage>`** — не поддерживается (монтировать каталоги из других стадий нельзя; только `type=cache`/`secret`/`bind` в пределах текущей стадии).
- **`--network host`** в инструкции RUN — не работает (изоляция сети сохраняется; альтернатива BuildKit — `--network=host`).
- **`--security-opt`** — не поддерживается.
- **`--customPlatform`** (camelCase) — deprecated, заменен на `--custom-platform` (дефис); возможная путаница с именем `--platform`, которого в Kaniko не существовало.
- **Некоторые сложные shell-конструкции** — могут работать некорректно из-за особенностей исполнения команд внутри контейнера Kaniko (не из-за chroot — Kaniko chroot не использует).

### Проблемы с жёсткими ссылками (hardlinks)

Kaniko может некорректно обрабатывать жёсткие ссылки на системные файлы. Это проявляется при сборке образов на базе Alpine Linux или Debian, где пакетный менеджер создаёт hardlinks.

**Решение:** используйте актуальную версию форка — `FF_KANIKO_PRESERVE_HARDLINKS` (по умолчанию `true`) сохраняет hardlink-связи при `COPY --from=<stage>` и устраняет раздувание размера образа (например, для `git`-установок, где многие бинарники связаны через inode).

### Проблемы с производительностью

- Сборка больших проектов (1000+ файлов) может быть медленной из-за полного сканирования файловой системы после каждой инструкции RUN.
- **Решение:** Используйте `.dockerignore` для исключения ненужных файлов и `--snapshot-mode=redo`.

### Рекомендации по миграции

Если Kaniko не покрывает ваши потребности (отсутствие BuildKit, сложные Dockerfile), рассмотрите миграцию на **[BuildKit (Standalone)](./dockerfile_buildkit.md)** или **[Docker Buildx](./docker_buildx.md)** — эти инструменты поддерживают полный функционал Dockerfile и рекомендуются для production-сборок.

## См. также

- **[BuildKit: Современная альтернатива](./dockerfile_buildkit.md)** — сравнение и выбор инструмента.
- **[Docker-in-Docker: Анализ рисков](../docker-in-docker.md)** — детали DinD vs Kaniko.
- **[Безопасность в Dockerfile](./Docker_best_practices/security.md)** — Pod Security Standards.
- **[Бенчмарк Kaniko vs BuildKit vs Buildah в кластере](./dockerfile_build_tools_benchmark.md)** — замер времени, CPU и памяти сборки в Kubernetes с GitLab Runner.