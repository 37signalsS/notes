# Werf: Автоматизация сборки и развёртывания в Kubernetes

## Определения

**Werf** — это Open Source инструмент (CNCF Sandbox) для автоматизации сборки Docker-образов и развёртывания приложений в Kubernetes. Реализует концепцию Giterminism, объединяя процессы сборки, публикации и деплоя в единый, воспроизводимый конвейер.

**Nelm** — современный движок развёртывания werf, пришедший на смену форку Helm. Обеспечивает нативную поддержку Kubernetes Server-Side Apply и улучшенное отслеживание ресурсов. Nelm позволяет обрабатывать сложные сценарии слияния манифестов и предоставляет глубокую диагностику состояния ресурсов в реальном времени.

**Stapel** — продвинутый сборочный движок и формат описания образов в werf (альтернатива Dockerfile), предоставляющий декларативный синтаксис на YAML и оптимизированное кэширование на основе стадий.

**Server-Side Apply (SSA)** — механизм Kubernetes, используемый werf для применения манифестов. SSA переносит логику слияния (merge) на сторону API-сервера, решая проблемы владения полями и конфликтов между разными участниками (человек, CI, контроллер).

**Giterminism** (Git + Determinism) — фундаментальный принцип werf: состояние развёрнутого приложения должно полностью определяться состоянием Git-репозитория. Werf работает только с закоммиченными данными, что исключает влияние локальных «грязных» файлов на результат сборки.

**Werf Converge** — основная команда развёртывания, выполняющая полный цикл: сборка, публикация в registry и синхронизация состояния кластера с Git.

## Предварительные требования

### Минимальные системные требования

- **ОС:** Linux (x86_64, ARM64), macOS (Intel, Apple Silicon), Windows (WSL2)
- **RAM:** 2 ГБ свободной памяти (для локальной сборки)
- **Диск:** 10 ГБ свободного места (для кэша образов)
- **Сеть:** Доступ к Container Registry и Kubernetes API-серверу

### Необходимое ПО

| Компонент | Версия | Назначение |
| :--- | :--- | :--- |
| **Werf** | 2.x (Stable) | Основной инструмент сборки и деплоя |
| **Docker** или **Buildah** | Любая стабильная | Движок сборки образов (Docker Desktop или Podman) |
| **Git** | 2.30+ | Управление версиями (обязательно для Giterminism) |
| **kubectl** | Совпадающая с кластером | Управление Kubernetes-кластером |
| **Helm** | 3.x (опционально) | Только если используется legacy-режим без Nelm |
| **Kubernetes** | 1.25+ | Целевой кластер для развёртывания |

### Проверка окружения

```bash
# Проверка версий всех компонентов
werf version       # → 2.x.x
docker version     # → Docker version 24.x+
git --version      # → git version 2.30+
kubectl version --client  # → Client Version: v1.28+
```

### Авторизация и доступы

1. **Container Registry:** Токен доступа с правами `write:packages` (GHCR) или `push` (Harbor, GitLab)
2. **Kubernetes:** Конфигурация `~/.kube/config` с правами на целевой namespace
3. **Git:** SSH-ключ или PAT для доступа к репозиторию (для Giterminism)

## Основные концепции

### Ключевые принципы

- **Infrastructure as Code (IaC)** — вся конфигурация сборки и деплоя описывается в файлах, хранящихся в Git вместе с кодом.
- **Гитерминизм (Giterminism):**
    - Изоляция сборки от локального окружения.
    - Игнорирование файлов, не добавленных в Git (кроме режима `--dev`).
    - Использование `werf-giterminism.yaml` для явного разрешения чтения внешних файлов или переменных окружения.
- **Воспроизводимость:** гарантируется идентичность образа для одного и того же коммита.

### Архитектура werf

1. **Сборка образов:**
   - Поддержка Dockerfile и нативного формата Stapel.
   - Инкрементальная сборка с кэшированием слоёв.
   - Мультиступенчатая сборка (multi-stage).
   - **Stapel** — продвинутый сборочный движок werf, который анализирует инструкции сборки и кэширует результаты каждой стадии. При повторных сборках пересобираются только те слои, которые изменились.
   - **Стадии сборки Stapel:**
     - `beforeInstall` — подготовка окружения до установки зависимостей (например, установка системных пакетов).
     - `install` — установка зависимостей приложения (кэшируется отдельно, что ускоряет сборку при изменении только кода).
     - `beforeSetup` — подготовка перед финальной настройкой приложения.
     - `setup` — финальная настройка и компиляция образа (кэшируется отдельно).

2. **Публикация в registry:**
   - Автоматическая публикация собранных образов.
   - Поддержка OCI-совместимых registry (GitHub Container Registry, Harbor, Docker Hub, GitLab Registry).
   - **Тег на основе хэша содержимого (Content-based tagging):** werf присваивает образу тег, рассчитанный на основе содержимого образа и инструкций сборки, а не просто версию или ветку. Это гарантирует уникальность и консистентность каждой сборки.

3. **Развёртывание в Kubernetes:**
   - Встроенный Helm-совместимый движок для управления манифестами.
   - Go template для динамической подстановки имён образов и других параметров.
   - Отслеживание статуса rollout до полной готовности ресурсов.

### Основные команды werf

| Команда | Описание |
| :--- | :--- |
| `werf converge` | Объединяет build, push и deploy в одну операцию. |
| `werf plan` | Показывает планируемые изменения (аналог `terraform plan`). |
| `werf render` | Генерирует итоговые манифесты Kubernetes для проверки без деплоя. |
| `werf cleanup` | Очистка Container Registry от старых образов по настраиваемым политикам. |
| `werf run` | Запуск контейнера на основе образа проекта для локальной отладки. |
| `werf bundle` | Создание пакета (bundle) для развертывания в изолированных сетях (Air-gap). |

### Преимущества werf

| Критерий | Описание |
| :--- | :--- |
| **Единая команда** | `werf converge` объединяет build, push и deploy |
| **Кэширование** | Уникальная система кэширования стадий Stapel и переиспользование кэша в CI |
| **Безопасность** | Сборка через Buildah без root-прав и поддержка SSA |
| **Giterminism** | Гарантия соответствия состояния кластера коду в Git |
| **Nelm** | Глубокая интеграция с Kubernetes и корректная обработка состояния ресурсов |

## Практические сценарии

### Сценарий 0: Установка werf

**Установка (macOS/Linux):**

```bash
curl -sL https://werf.io/install.sh | bash
```

**Проверка установки:**

```bash
werf version
# Вывод: 2.x.x (Stable/Rock-Solid)
```

**Настройка для локальной разработки:**
Для полноценной работы рекомендуется иметь установленный Docker или альтернативный движок (например, Buildah).

### Сценарий 1: Настройка доступа к GitHub Container Registry (GHCR)

**Проблема:** Werf требует доступ для публикации образов в приватный registry.

**Решение:**

1. **Создание Personal Access Token (PAT) в GitHub:**
   Необходимо разрешение `write:packages` (или `read:packages` для pull).

2. **Аутентификация в registry:**

   ```bash
   docker login ghcr.io -u <username> -p <token>
   ```

3. **Создание Kubernetes Secret для imagePullSecrets:**

   ```bash
   kubectl create secret docker-registry registry-secret \
     --docker-server=ghcr.io \
     --docker-username=<username> \
     --docker-password=<token> \
     -n <namespace>
   ```

### Сценарий 2: Переписывание Dockerfile на Stapel

**Исходный Dockerfile (multi-stage):**

```dockerfile
# Build stage
FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o myapp

# Runtime stage
FROM alpine:3.18
COPY --from=builder /app/myapp /myapp
CMD ["/myapp"]
```

**Эквивалент на Stapel (werf.yaml):**

```yaml
project: myapp
configVersion: "1"

build:
  - image: app
    from: alpine:3.18
    import:
      - image: builder
        add: /app/myapp
        to: /myapp
    command: ["/myapp"]

  - image: builder
    from: golang:1.21
    git:
      - add: /
        to: /app
    shell:
      - cd /app && go build -o myapp
```
*Примечание: Stapel позволяет более гибко управлять импортом артефактов и кэшированием каждой инструкции.*

### Сценарий 3: Шаблонизация манифеста Kubernetes

**Проблема:** Имя образа меняется с каждой сборкой из-за content-based tagging.

**Решение:** Использовать Go template в манифесте Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
        - name: app
          image: "{{ .Values.werf.image.app }}"
      imagePullSecrets:
        - name: registry-secret
      command: ["/myapp"]
```

**Пояснение:** `{{ .Values.werf.image.app }}` — это плейсхолдер, который werf автоматически заменяет на полный путь к образу (включая Registry URL и уникальный тег) во время выполнения `werf converge`.

### Сценарий 4: Развёртывание командой werf converge

**Подготовка:**
Убедитесь, что вы авторизованы в Registry и имеете доступ к кластеру Kubernetes.

**Запуск деплоя:**

```bash
werf converge \
  --repo ghcr.io/<username>/<repo> \
  --env production \
  --namespace <namespace>
```

**Что происходит:**
1. **Анализ:** werf проверяет текущий коммит в Git и конфигурацию `werf.yaml`.
2. **Сборка:** собираются только те стадии образов, которые изменились.
3. **Публикация:** новые образы пушатся в Registry.
4. **Рендеринг:** Helm-шаблоны рендерятся с актуальными тегами образов.
5. **Применение:** Nelm применяет изменения в кластер через SSA и ждет готовности подов.

### Сценарий 5: Оптимизация размера образа

**Проблема:** Использование тяжелых базовых образов (например, `golang:1.21` весит ~800 МБ) в runtime.

**Решение:** Отделение сборочного окружения от runtime через Stapel или Multi-stage Dockerfile. В runtime используется минималистичный образ (`alpine` или `distroless`).

**Результат:** Итоговый образ уменьшается до 10-50 МБ, что ускоряет pull образов и повышает безопасность.

### Сценарий 6: Кросс-платформенная сборка

**Проблема:** Разработка ведется на Apple Silicon (ARM64), а серверы используют AMD64.

**Решение:** Использование флага `--platform` (требуется настроенный эмулятор QEMU или удаленный сборочный узел):

```bash
werf build --platform linux/amd64
```

### Сценарий 7: Режим разработки (--dev)

**Проблема:** Нужно быстро проверить код в кластере без создания коммита.

**Решение:**
```bash
werf converge --dev
```
Werf включит в сборку все незакоммиченные изменения. Теги для таких образов будут содержать префикс `dev-`.

### Сценарий 8: Предварительный просмотр изменений (werf plan)

**Решение:**
```bash
werf plan --env production
```
Выводит текстовый diff манифестов, позволяя избежать случайных деструктивных изменений в инфраструктуре.

### Сценарий 9: Валидация и откат (lint, rollback)

**Проблема:** Ошибки в шаблонах Helm или необходимость вернуться к предыдущей версии.

```bash
# Проверка синтаксиса шаблонов
werf lint --env staging

# Откат релиза
werf rollback --env production
```

### Сценарий 10: Управление жизненным циклом через аннотации

**Решение:** Использование аннотаций для управления поведением Nelm.

```yaml
metadata:
  annotations:
    werf.io/delete-policy: "delete" # Удаление ресурса вместе с релизом
    werf.io/weight: "10" # Очередность деплоя (аналог Helm hooks)
```

### Сценарий 11: Интеграция с GitLab CI/CD (Новый)

Для автоматизации в GitLab создается файл `.gitlab-ci.yml`:

```yaml
stages:
  - build_and_deploy

deploy:
  stage: build_and_deploy
  script:
    - werf converge --repo $CI_REGISTRY_IMAGE --env $CI_ENVIRONMENT_SLUG
  tags:
    - werf-runner
  only:
    - main
```
*Werf автоматически использует `CI_JOB_TOKEN` для авторизации в GitLab Registry.*

### Сценарий 12: Интеграция с GitHub Actions

**Проблема:** Автоматизация сборки и деплоя в GitHub Actions с использованием werf.

**Решение:**

1. **Создание Secret в GitHub:**
   - `GHCR_TOKEN`: PAT с правами `write:packages`
   - `KUBE_CONFIG`: Base64-закодированный `~/.kube/config`

2. **Конфигурация workflow (`.github/workflows/deploy.yml`):**

```yaml
name: Build and Deploy

on:
  push:
    branches: [main]

env:
  WERF_VERSION: "2.24"
  GHCR_IMAGE: "ghcr.io/${{ github.repository }}"

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Обязательно для Giterminism

      - name: Install werf
        run: |
          curl -s https://raw.githubusercontent.com/werf/werf/main/scripts/werf-install.sh | bash
          echo "$HOME/.werf/bin" >> $GITHUB_PATH

      - name: Login to GHCR
        run: echo "${{ secrets.GHCR_TOKEN }}" | docker login ghcr.io -u ${{ github.actor }} --password-stdin

      - name: Deploy to Kubernetes
        env:
          KUBE_CONFIG: ${{ secrets.KUBE_CONFIG }}
        run: |
          echo "$KUBE_CONFIG" | base64 -d > $HOME/.kube/config
          werf converge --repo ${{ env.WERF_IMAGE }} --env production
```

*Примечание: Установите `fetch-depth: 0` для полной истории коммитов (требуется Giterminism).*

### Сценарий 13: Очистка Container Registry

Настройка политик в `werf.yaml` для предотвращения переполнения диска:

```yaml
cleanup:
  keepPolicies:
    - references:
        tag: /.*/
        limit:
          last: 10
    - imagesPerReference:
        last: 2
```
Запуск очистки (рекомендуется запускать по расписанию в CI):
```bash
werf cleanup --repo <registry_url>
```

### Сценарий 14: Управление переменными окружения

**Проблема:** Необходимость передавать секреты и конфигурационные параметры в процесс сборки/деплоя.

**Решение:**

1. **Определение переменных в `werf.yaml`:**

```yaml
env: CI_COMMIT_SHA

---
import:
  - image: builder
    add: /app/config.json
    to: /app/config.json
    stageDependencies:
      install:
        - config.json
```

2. **Передача переменных при запуске:**

```bash
# Явное указание переменных
werf converge --env CI_COMMIT_SHA=abc123

# Использование переменных окружения.shell
export CI_COMMIT_SHA=$(git rev-parse --short HEAD)
werf converge
```

3. **Безопасная передача секретов:**

```bash
# Через Kubernetes Secret
kubectl create secret generic app-secrets \
  --from-literal=DB_PASSWORD=secret123

# В манифесте Deployment
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: app-secrets
        key: DB_PASSWORD
```

## Валидация и ожидаемые результаты

### Проверка успешной сборки

```bash
# Проверка статуса последнего деплоя
kubectl get deployments -n <namespace>
# Ожидаемый результат:
# NAME    READY   UP-TO-DATE   AVAILABLE
# myapp   1/1     1            1

# Проверка подов
kubectl get pods -n <namespace>
# Ожидаемый результат:
# NAME                     READY   STATUS    RESTARTS   AGE
# myapp-6f8b5c7d4-x2j9k   1/1     Running   0          2m
```

### Проверка через werf

```bash
# Просмотр текущего состояния релиза
werf bundle render --repo <registry_url>
# Ожидаемый результат: YAML-манифесты с актуальными тегами образов

# Проверка Diff (что изменится)
werf plan --env production
# Ожидаемый результат: текстовый diff манифестов
```

### Проверка работоспособности приложения

```bash
# Проброс порта для локальной проверки
kubectl port-forward svc/myapp 8080:8080 -n <namespace>

# Проверка health check эндпоинта
curl http://localhost:8080/health
# Ожидаемый результат: HTTP 200 OK
```

## Типичные ошибки и их решение

| Проблема | Причина | Решение |
|:---|:---|:---|
| `error: cannot use working dir` | Werf не может прочитать файлы из-за Giterminism. | Убедитесь, что все файлы добавлены в Git. Используйте `werf-giterminism.yaml` для явного разрешения внешних файлов. |
| `UNAUTHORIZED` при пушке в Registry | Невалидный или отозванный токен. | Проверьте токен доступа, убедитесь что он имеет права на запись (`write:packages` для GHCR). |
| `ImagePullBackOff` в подах | Kubernetes не может скачать образ из Registry. | Проверьте `imagePullSecrets` в манифесте Deployment, убедитесь что Secret создан в правильном namespace. |
| `Helm template failed` | Ошибка в шаблоне Helm или Go template. | Проверьте шаблоны командой `werf render --env staging`, исправьте синтаксические ошибки. |
| `Git working directory is dirty` | Незакоммиченные изменения блокируют сборку. | Закоммичьте или отмените изменения. Для разработки используйте флаг `--dev`. |
| `Docker daemon not accessible` | Werf не может подключиться к Docker daemon. | Убедитесь, что Docker запущен. Проверьте переменную `DOCKER_HOST`. |
| `No such image` при render | Образ ещё не опубликован в registry. | Сначала выполните `werf build`, затем `werf render`. |
| `Release not found` при rollback | Предыдущий релиз не существует или был удалён. | Проверьте историю релизов: `werf bundle list --repo <registry>`. |

## Диагностические команды

```bash
# Проверка статуса werf и окружения
werf version

# Просмотр логов последнего деплоя
kubectl logs -l app=myapp -n <namespace> --tail=100

# Проверка текущего состояния ресурсов
kubectl get all -n <namespace>

# Проверка событий Kubernetes (ошибки и предупреждения)
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Очистка локального кэша werf (при проблемах со сборкой)
werf cleanup --local

# Проверка конфигурации (валидация werf.yaml)
werf render --env staging 2>&1 | head -50
```

## Очистка и откат изменений

### Откат деплоя

```bash
# Откат к предыдущей версии
werf rollback --env production

# Проверка текущего статуса
kubectl get deployments -n <namespace>
```

### Удаление ресурсов

```bash
# Удаление конкретного пода (для перезапуска)
kubectl delete pod <pod-name> -n <namespace>

# Полное удаление приложения
werf dismiss --env production

# Удаление_namespace и всех ресурсов в нём
kubectl delete namespace <namespace>
```

### Очистка Container Registry

```bash
# Удаление старых образов по политике очистки
werf cleanup --repo <registry_url>

# Ручное удаление конкретного тега
# (для GHCR через API или web interface)
```

## Best Practices

1. **Версионирование конфигурации:** Храните `werf.yaml` в корне репозитория, не используйте симлинки или генерируемые файлы.
2. **Инкрементальные изменения:** Используйте `werf plan` перед деплоем для предварительного просмотра изменений.
3. **Мониторинг:** Настройте алерты на ошибки деплоя и health check приложения.
4. **Безопасность:** Храните секреты в Kubernetes Secrets, не в `werf.yaml`.
5. **Тестирование:** Используйте `werf render` для проверки манифестов без фактического деплоя.
6. **Очистка:** Настройте политики очистки registry для предотвращения переполнения диска.
7. **Документация:** Опишите процедуру отката и связи с ответственными в случае инцидентов.

## Справочник по конфигурации werf.yaml

### Структура основного конфига

```yaml
project: myapp                    # Имя проекта (уникальное в рамках registry)
configVersion: "1"                # Версия формата конфига

# Сборка образов
build:
  - image: app                    # Имя образа (для подстановки в шаблонах)
    from: alpine:3.18             # Базовый образ
    dockerfile: Dockerfile        # Альтернатива: использование Dockerfile
    context: .                    # Контекст сборки (по умолчанию .)
    
    # Импорт файлов из других образов
    import:
      - image: builder
        add: /app/myapp
        to: /myapp
        stageDependencies:
          install:
            - go.mod
            - go.sum
    
    # Git-зависимости
    git:
      - add: /
        to: /app
        stageDependencies:
          setup:
            - "**/*.go"
    
    # Shell-команды для сборки
    shell:
      - cd /app && go build -o myapp
    
    # Переменные окружения
    env:
      GOPATH: /go
      CGO_ENABLED: 0

# Публикация в registry
images:
  - name: app
    image: app                    # Ссылка на образ из секции build

# Развёртывание в Kubernetes
deploy:
  helm:
    releaseName: myapp
    set:
      replicaCount: 3
    valuesFiles:
      - .helm/values-{{ env }}.yaml
```

### Секция cleanup (Очистка registry)

```yaml
cleanup:
  keepPolicies:
    # Сохранять последние 10 тегов для всех веток
    - references:
        branch: /.*/
        limit:
          last: 10
    
    # Сохранять последние 2 образа для каждого тега
    - references:
        tag: /.*/
      imagesPerReference:
        last: 2
    
    # Сохранять образы с тегами release/*
    - references:
        tag: /^release\/.*$/
        limit:
          last: 5
```

### Секция giterminism (Разрешение внешних файлов)

```yaml
# werf-giterminism.yaml
giterminismConfigVersion: 1

# Разрешение чтения файлов из определённых директорий
allowRead:
  - path: .env
  - path: config/*.json
  - path: secrets/**
```

### Go template в манифестах

```yaml
# Шаблонизация образов в Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Project.Name }}
spec:
  replicas: {{ .Env.REPLICA_COUNT | default 2 }}
  template:
    spec:
      containers:
        - name: app
          image: "{{ .Values.werf.image.app }}"
          env:
            - name: COMMIT_SHA
              value: "{{ .Env.CI_COMMIT_SHA }}"
          resources:
            limits:
              memory: "{{ .Values.resources.memory | default "512Mi" }}"
```

### Аннотации werf для управления ресурсами

```yaml
metadata:
  annotations:
    # Удаление ресурса при удалении релиза
    werf.io/delete-policy: "delete"
    
    # Очередность деплоя (вес)
    werf.io/weight: "10"
    
    # Таймаут готовности пода
    werf.io/pod-readiness-timeout: "600"
    
    # Подключение к логам
    werf.io/log: "true"
    
    # Источник изменений (для мониторинга)
    werf.io/track: "true"
```

## Дополнительная информация

### Структура проекта werf

```text
project/
├── .werf/
│   └── werf.yaml          # Главный конфиг сборки
├── .helm/
│   ├── templates/         # Манифесты K8s
│   ├── values.yaml        # Значения по умолчанию
│   └── _helpers.tpl       # Хелперы шаблонизатора
├── werf-giterminism.yaml  # Конфиг Гитерминизма (опционально)
├── src/                   # Исходный код
└── Dockerfile             # Опционально
```

### Сравнение с альтернативами

| Инструмент | Сборщик | Движок деплоя | Server-Side Apply | Giterminism |
| :--- | :--- | :--- | :--- | :--- |
| **Werf** | Stapel/Dockerfile | **Nelm** | Да | Да |
| **Skaffold** | Docker/Jib/Buildpacks | Helm/Kubectl | Частично | Нет |
| **Helm** | Нет | Helm (3-way merge) | Нет | Нет |
| **Argo CD** | Нет | GitOps (Pull) | Да | Да |

### Ограничения и нюансы

- **Зависимость от Git:** Werf теряет свои преимущества вне Git-репозитория.
- **Хранилище стадий:** Для работы кэша требуется внешний Registry, поддерживающий хранение слоев.
- **Порог вхождения:** Понимание разницы между Dockerfile и Stapel, а также механизмов Nelm требует времени.

### Связанные темы

- [Работа с Container Registry](../../Docker/docker_registries.md)
- [Шаблонизация в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
- [Kubernetes Server-Side Apply](../../Kubernetes/Concepts/api_interaction.md)

### Ресурсы

- [Официальный сайт werf.io](https://werf.io/)
- [Документация по Nelm](https://werf.io/documentation/advanced/nelm.html)
- [Giterminism Deep Dive](https://werf.io/documentation/advanced/giterminism.html)
- [CNCF Sandbox: werf](https://www.cncf.io/projects/werf/)
- [GitHub: werf/werf](https://github.com/werf/werf)
- [ werf vs Helm vs Argo CD](https://werf.io/documentation/comparisons/werf-vs-helm.html)
