# Kaniko: Сборка Docker-образов без демона

> [!WARNING]
> **Статус проекта (2025):** Официальный репозиторий Google (`GoogleContainerTools/kaniko`) был **архивирован 3 июня 2025 года**. Новые функции и патчи безопасности от Google более не выпускаются. В актуальных инфраструктурах рекомендуется использовать форк от сообщества — **[osscontainertools/kaniko](https://github.com/osscontainertools/kaniko)** или мигрировать на **[BuildKit (Standalone)](./dockerfile_buildkit.md)**.

## Определения

**Kaniko** — инструмент для сборки образов контейнеров из `Dockerfile` без зависимости от Docker-демона. Он выполняет инструкции внутри пользовательского пространства (userspace), что делает его стандартом для сред с жесткими ограничениями безопасности (Kubernetes, GitLab CI), где использование привилегированных контейнеров или монтирование Docker Socket запрещено.

Ключевые особенности:
- Работает без root-прав на хосте.
- Не требует `--privileged` режима.
- Идеально совместим с **Pod Security Standards (Restricted)**.
- Использует механизм `chroot` вместо изоляции через namespaces.
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
│  │  │      chroot (эмуляция FS)       │    │  │
│  │  │  /kaniko/workspace/rootfs/       │    │  │
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
- **Dockerfile** — стандартный синтаксис Docker (Kaniko совместим с ~95% инструкций)
- **Доступ к реестру образов** (Docker Hub, GCR, Harbor, ECR и др.) — для пуша результатов

### Доступные образы Kaniko

| Образ | Назначение |
| :--- | :--- |
| `gcr.io/kaniko-project/executor:latest` | Официальный образ Google (архивирован) |
| `gcr.io/kaniko-project/executor:debug` | С поддержкой shell для отладки |
| `osscontainertools/kaniko:v1.28.0` | Актуальный форк сообщества (рекомендуется) |
| `osscontainertools/kaniko:v1.28.0-debug` | Форк + shell для отладки |

> **Рекомендация:** Используйте форк `osscontainertools` для получения актуальных обновлений безопасности. Официальный образ Google больше не обновляется.

### Проверка работоспособности

```bash
# Проверка доступа к реестру
docker login registry.example.com

# Быстрая проверка Kaniko (сборка без пуша)
docker run --rm \
  -v $(pwd):/workspace \
  osscontainertools/kaniko:v1.28.0-debug \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --no-push
# → Building... Done.
```

## Базовые концепции

### Принцип работы Kaniko (пошагово)

Главное отличие Kaniko от классического Docker заключается в том, что он **вообще не запускает контейнеры** для сборки. Вместо механизмов ядра (namespaces) он использует эмуляцию в пользовательском пространстве.

1.  **Распаковка базового образа:** При обработке инструкции `FROM`, Kaniko скачивает образ и **распаковывает** его файловую систему в рабочую директорию (обычно `/kaniko/workspace/rootfs`).
2.  **Выполнение команд (RUN) через chroot:** Для выполнения команд Kaniko использует механизм **chroot**. Процессу (например, `apk` или `apt`) сообщается, что его корневая директория — это папка с распакованным образом. 
    - Процесс «считает», что он находится в реальной ОС.
    - На самом деле он просто меняет файлы в папке на диске.
3.  **Снапшоты (Snapshots):** После каждой команды `RUN` Kaniko сравнивает текущее состояние файлов с предыдущим, вычисляет разницу (diff) и упаковывает измененные файлы в новый слой (`tar.gz`).
4.  **Multi-stage сборки и оптимизация:** 
    - **Статический анализ (Built cross stage deps):** Перед началом работы Kaniko строит карту зависимостей между стадиями. Это позволяет заранее знать, какие файлы из ранних стадий понадобятся позже.
    - **Сохранение артефактов:** При завершении стадии Kaniko физически копирует нужные файлы (логи: `Saving file <path> for later use`) во внутреннее временное хранилище.
    - **Полная очистка (Deleting filesystem):** Перед началом новой стадии Kaniko полностью удаляет содержимое рабочего пространства, оставляя только сохраненные артефакты. Это гарантирует изоляцию стадий и отсутствие лишнего мусора в финальном образе.
5.  **Формирование и отправка:** В конце процесса Kaniko собирает все слои и манифест, отправляя их в реестр через HTTP API.

### Модель эшелонированной защиты (Defense-in-depth)

Kaniko обеспечивает безопасность через несколько уровней изоляции:

1.  **Non-root запуск:** Побег из `chroot` технически невозможен для непривилегированного пользователя (UID 1000), так как техники escape требуют прав `CAP_SYS_ADMIN`.
2.  **Отсутствие привилегий ядра:** Контейнер Kaniko запускается без `--privileged`. У него нет прав на монтирование устройств или изменение параметров ядра хоста.
3.  **Ограничения оркестратора:** В Kubernetes NetworkPolicy может жестко ограничить сетевую активность процесса сборки, не позволяя ему сканировать внутреннюю сеть.

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
| `--cache-repo` | Реестр для хранения кэшированных слоёв |
| `--cache-ttl` | Время жизни кэша (по умолчанию 24h) |
| `--no-push-cache` | Отключение пуша кэша (по умолчанию false) |
| `--snapshot-mode` | Режим снапшотов: `redo` (по умолчанию, быстрый) или `full` (точный) |

### Безопасность и аутентификация

| Флаг | Описание |
| :--- | :--- |
| `--registry-certificate` | Сертификат для конкретного реестра |
| `--registry-username` | Имя пользователя для реестра |
| `--insecure` | Использовать HTTP вместо HTTPS |
| `--skip-tls-verify` | Пропустить проверку TLS-сертификата |
| `--registry-secret` | Секрет для registry |

### Сборка

| Флаг | Описание |
| :--- | :--- |
| `--build-arg` | Передача аргументов сборки |
| `--build-arg-env` | Читать аргументы из переменных окружения |
| `--build-context` | Дополнительные контексты |
| `--label` | Метаданные образа |
| `--build-secret` | Секреты сборки (монтируются в /secrets/) |
| `--ssh` | SSH-ключи для сборки |
| `--target` | Целевая стадия multi-stage |
| `--platform` | Целевая платформа |
| `--revision` | Git-ревизия для build-context |
| `--branch` | Git-ветка для build-context |
| `--git` | Расширенные Git-опции (branch, recursive) |

### Вывод

| Флаг | Описание |
| :--- | :--- |
| `--image-file` | Запись digest в файл (аналог --digest-file) |
| `--oci-image-path` | Экспорт в OCI-формат |
| `--single-snapshot` | Один снапшот на всю стадию (ускорение) |
| `--compressed-caching` | Сжатие кэшированных слоёв |
| `--use-new-run` | Использовать улучшенный механизм RUN |

### Диагностика

| Флаг | Описание |
| :--- | :--- |
| `--verbosity` | Уровень логирования (trace, debug, info, warn, error) |
| `--log-timestamp` | Добавлять временны́е метки в логи |
| `--force-build-running-cache` | Принудительное использование кэша |

### Переменные окружения

Kaniko поддерживает несколько переменных окружения для настройки без флагов:

| Переменная | Описание |
| :--- | :--- |
| `GOOGLE_APPLICATION_CREDENTIALS` | Путь к JSON-ключу сервисного аккаунта GCP (для GCR/AR) |
| `DOCKER_CONFIG` | Путь к директории с конфигурацией Docker (по умолчанию `/kaniko/.docker`) |
| `AWS_ACCESS_KEY_ID` | Ключ доступа AWS (для ECR) |
| `AWS_SECRET_ACCESS_KEY` | Секретный ключ AWS (для ECR) |
| `AWS_DEFAULT_REGION` | Регион AWS |
| `GIT_TOKEN` | Токен для доступа к приватным Git-репозиториям |
| `SRC_CONTEXT` | Источник контекста сборки (альтернатива --context) |
| `DOCKER_USERNAME` | Имя пользователя Docker Hub |
| `DOCKER_PASSWORD` | Пароль Docker Hub |

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
| **Безопасность** | Низкая | Высокая | Высокая |
| **Кэширование** | Локальное | Локальное / Remote | Только Remote |
| **Совместимость** | 100% | Высокая | Средняя (~95%) |
| **BuildKit функции** | Поддерживаются | Полная поддержка | Игнорируются |
| **Multi-arch** | Последовательно | Одновременно | Ограниченно |
| **Аттестации (SBOM)** | Нет | Да | Нет |
| **Параллелизм** | Нет | Нативный (LLB) | Последовательно |
| **Multi-stage** | Поддерживается | Поддерживается | Поддерживается |
| **Secrets** | Через ARG (небезопасно) | `type=secret` | `--build-secret` |
| **Ресурсоемкость** | Высокая | Средняя | Низкая |
| **Рекомендуемый сценарий** | Локальная разработка | CI/CD, production | Kubernetes, restricted PSS |

## Практические сценарии

### Сценарий 1: Сборка в GitLab CI (форк v1.28.0)

Рекомендуется использовать образ из форка `osscontainertools` для получения актуальных обновлений.

```yaml
build-app:
  stage: build
  image:
    # Использование актуального форка сообщества
    name: osscontainertools/kaniko:v1.28.0-debug
    entrypoint: [""]
  script:
    # Аутентификация через базовую авторизацию (base64)
    - mkdir -p /kaniko/.docker
    - |
      echo "{\"auths\":{\"$CI_REGISTRY\":{\"auth\":\"$(printf "%s:%s" "$CI_REGISTRY_USER" "$CI_REGISTRY_PASSWORD" | base64 | tr -d '\n')\"}}}" > /kaniko/.docker/config.json
    # Запуск сборки с кэшированием
    - /kaniko/executor \
        --context "dir://${CI_PROJECT_DIR}" \
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}" \
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
    osscontainertools/kaniko:v1.28.0 \
    --dockerfile=/workspace/Dockerfile \
    --context=dir:///workspace \
    --no-push
```

### Сценарий 3: Сборка с кэшированием и отправкой в Harbor

```bash
docker run \
  -v $(pwd):/workspace \
  -v $HOME/.docker/config.json:/kaniko/.docker/config.json:ro \
  osscontainertools/kaniko:v1.28.0 \
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
  osscontainertools/kaniko:v1.28.0 \
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
  osscontainertools/kaniko:v1.28.0 \
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
  osscontainertools/kaniko:v1.28.0 \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --destination=reg/app:v1 \
  --no-push
```

> **Примечание:** Kaniko корректно обрабатывает multi-stage сборки, сохраняя артефакты из предыдущих стадий. Однако из-за последовательного выполнения сборка может быть медленнее, чем в BuildKit.

### Сценарий 7: Сборка из Git-репозитория

```bash
docker run \
  osscontainertools/kaniko:v1.28.0 \
  --git=branch=main,recursive=true \
  --context=git://github.com/user/repo.git \
  --destination=reg/app:v1
```

С использованием токена:

```bash
export GIT_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

docker run \
  -e GIT_TOKEN=${GIT_TOKEN} \
  osscontainertools/kaniko:v1.28.0 \
  --git=branch=main,recursive=true \
  --context=git://github.com/user/private-repo.git \
  --destination=reg/app:v1
```

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
docker run -d -p 5000:5000 --name registry registry:2

# Сборка и отправка
docker run --rm --network host \
  -v $(pwd):/workspace \
  osscontainertools/kaniko:v1.28.0 \
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
        uses: gcr.io/kaniko-project/executor@v1.23.2
        with:
          dockerfile: Dockerfile
          context: .
          destination: myregistry.com/app:${{ github.sha }}
          cache: true
          cache-repo: myregistry.com/cache
          push-retry: 3
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
                      osscontainertools/kaniko:v1.28.0 \
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
          image: osscontainertools/kaniko:v1.28.0-debug
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

**2. Ошибка: `error building image: mkdir /kaniko/workspace/rootfs: read-only file system`**

Причина: Корневая файловая система монтирована как read-only.

Решение: Убедитесь, что контейнер Kaniko имеет доступ на запись к volume:

```bash
docker run -v $(pwd):/workspace osscontainertools/kaniko:v1.28.0 ...
```

**3. Ошибка: `error building image: failed to get reader: Get https://registry...: tls: certificate signed by unknown authority`**

Причина: Самоподписанный сертификат реестра.

Решение:

```bash
# Монтирование сертификата
docker run \
  -v /path/to/ca.crt:/kaniko/ssl/certs/ca-certificates.crt:ro \
  osscontainertools/kaniko:v1.28.0 \
  --registry-certificate=registry.example.com=/path/to/ca.crt \
  ...
```

**4. Ошибка: `error building image: mount --bind /proc/fd/...: no such file or directory`**

Причина: Kaniko не может найти необходимые системные файлы.

Решение: Убедитесь, что контейнер запущен с достаточными правами (не `--privileged`, но с необходимыми capability):

```bash
docker run --cap-add SYS_ADMIN osscontainertools/kaniko:v1.28.0 ...
```

**5. Медленная сборка大型 проектов**

Причина: Отсутствие кэширования или использование `--snapshot-mode=full`.

Решение:

```bash
# Включение кэширования
--cache=true --cache-repo=reg/cache

# Использование быстрого режима снапшотов (по умолчанию)
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
docker run --rm osscontainertools/kaniko:v1.28.0 version

# Сборка с подробным логированием
docker run --rm \
  -v $(pwd):/workspace \
  osscontainertools/kaniko:v1.28.0-debug \
  --dockerfile=/workspace/Dockerfile \
  --context=dir:///workspace \
  --no-push \
  --verbosity=trace

# Просмотр внутренней структуры образа
docker run --rm -it osscontainertools/kaniko:v1.28.0-debug shell
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

1. **Используйте форк `osscontainertools`** вместо официального образа Google (архивирован).
2. **Настройте кэширование** — всегда указывайте `--cache-repo` для ускорения повторных сборок.
3. **Используйте `--digest-file`** для интеграции с Kubernetes (точное указание образа по SHA256).
4. **Избегайте `--snapshot-mode=full`** — он медленнее `redo` и обычно не нужен.
5. **Передавайте секреты через `--build-secret`** или монтируйте в `/secrets/`, а не через `ARG`.
6. **Используйте `--verbosity=debug`** для отладки проблемных сборок.
7. **Указывайте `--push-retry=3`** для fault-tolerance в CI/CD.
8. **Регулярно обновляйте** образ Kaniko для получения патчей безопасности.

### Очистка

```bash
# Удаление локальных кэшированных образов
docker image prune -f

# Удаление временных файлов Kaniko
docker run --rm -v $(pwd):/workspace osscontainertools/kaniko:v1.28.0 \
  rm -rf /kaniko/workspace/

# Удаление кэша в реестре
# (зависит от реистра — для Harbor используйте GC, для Docker Hub — ручное удаление)
```

## Известные проблемы и совместимость

### Ограничения совместимости (~5% Dockerfile)

Kaniko **не поддерживает** следующие инструкции и функции:

- **`--mount=type=cache`** — распознаёт синтаксис BuildKit, но **игнорирует** его. Это критично для сборки тяжелых проектов (Java, Node.js, Go), где кэш пакетов теряется.
- **`--mount=type=ssh`** — не поддерживается (используйте `--ssh` флаг executor).
- **`--network host`** в инструкции RUN — не работает (Nettoy не поддерживается).
- **`--security-opt`** — не поддерживается.
- **Некоторые сложные shell-конструкции** — могут работать некорректно из-за эмуляции через chroot.

### Проблемы с жёсткими ссылками (hardlinks)

Kaniko может некорректно обрабатывать жёсткие ссылки на системные файлы. Это проявляется при сборке образов на базе Alpine Linux или Debian, где пакетный менеджер создаёт hardlinks.

**Решение:** Используйте `--snapshot-mode=full` или обновите до последней версии форка.

### Проблемы с производительностью

- Сборка大型 проектов (1000+ файлов) может быть медленной из-за полного сканирования файловой системы после каждой инструкции RUN.
- **Решение:** Используйте `.dockerignore` для исключения ненужных файлов и `--snapshot-mode=redo`.

### Рекомендации по миграции

Если Kaniko не покрывает ваши потребности (отсутствие BuildKit, сложные Dockerfile), рассмотрите миграцию на **[BuildKit (Standalone)](./dockerfile_buildkit.md)** или **[Docker Buildx](./docker_buildx.md)** — эти инструменты поддерживают полный функционал Dockerfile и рекомендуются для production-сборок.

## См. также

- **[BuildKit: Современная альтернатива](./dockerfile_buildkit.md)** — сравнение и выбор инструмента.
- **[Docker-in-Docker: Анализ рисков](../docker-in-docker.md)** — детали DinD vs Kaniko.
- **[Безопасность в Dockerfile](./Docker_best_practices/security.md)** — Pod Security Standards.