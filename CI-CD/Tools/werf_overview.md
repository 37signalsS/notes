---
reliability: 10
updated: 2026-08-01
---

# Werf: Автоматизация сборки и развёртывания в Kubernetes

## Определения

**Werf** — это Open Source инструмент (CNCF Sandbox) для автоматизации сборки Docker-образов и развёртывания приложений в Kubernetes. Реализует концепцию Giterminism, объединяя процессы сборки, публикации и деплоя.

**Nelm** — современный движок развёртывания werf, пришедший на смену форку Helm. Обеспечивает нативную поддержку Kubernetes Server-Side Apply и улучшенное отслеживание ресурсов.

**Stapel** — продвинутый сборочный движок и формат описания образов в werf (альтернатива Dockerfile), предоставляющий декларативный синтаксис на YAML и оптимизированное кэширование.

**Server-Side Apply (SSA)** — механизм Kubernetes, используемый werf для применения манифестов. SSA переносит логику слияния (merge) на сторону API-сервера, решая проблемы владения полями и конфликтов.

**Werf Converge** — основная команда развёртывания, выполняющая полный цикл: сборка, публикация в registry и синхронизация состояния кластера с Git.

## Основные концепции

### Ключевые принципы

**Infrastructure as Code (IaC)** — вся конфигурация описывается в файлах, хранящихся в Git вместе с кодом.

**Гитерминизм** (Git + Determinism) — фундаментальный принцип werf: состояние развёрнутого приложения должно полностью определяться состоянием Git-репозитория. Werf работает только с закоммиченными данными, что исключает влияние локальных «грязных» файлов на результат сборки.

### Архитектура werf

1. **Сборка образов:**
   - Поддержка Dockerfile и нативного формата Stapel
   - Инкрементальная сборка с кэшированием слоёв
   - Мультиступенчатая сборка (multi-stage)
   - **Stapel** — продвинутый сборочный движок werf, который анализирует инструкции сборки и кэширует результаты каждой стадии. При повторных сборках пересобираются только те слои, которые изменились.
   - **Стадии сборки Stapel:**
     - `beforeInstall` — подготовка окружения до установки зависимостей
     - `install` — установка зависимостей (кэшируется отдельно)
     - `beforeSetup` — подготовка перед настройкой приложения
     - `setup` — финальная настройка образа (кэшируется отдельно)

2. **Публикация в registry:**
   - Автоматическая публикация собранных образов
   - Поддержка OCI-совместимых registry (GitHub Container Registry, Harbor, Docker Hub)
   - Тегирование по commit hash, semver, custom-тегам
   - **Тег на основе хэша содержимого** — werf присваивает образу тег, рассчитанный на основе содержимого образа, а не просто версию. Это гарантирует уникальность и консистентность каждой сборки.

3. **Развёртывание в Kubernetes:**
   - Встроенный Helm для управления манифестами
   - Go template для динамической подстановки имён образов
   - Отслеживание статуса rollout

### Преимущества werf

| Критерий | Описание |
| :--- | :--- |
| **Единая команда** | `werf converge` объединяет build, push и deploy |
| **Кэширование** | Уникальная система кэширования стадий Stapel |
| **Безопасность** | Сборка через Buildah без root-прав |
| **Giterminism** | Гарантия соответствия состояния кластера коду в Git |

## Практические сценарии

### Сценарий 0: Установка werf

**Установка (macOS/Linux):**

```bash
curl -sL https://werf.io/install.sh | bash
```

Для других ОС и вариантов установки см. [официальную документацию](https://werf.io/documentation/install.html).

**Проверка установки:**

```bash
werf version
# Вывод: 2.73.2 (Rock-Solid) или 2.75.x (Stable)
```

**Настройка для локальной разработки:**

1. Перейдите на [werf.io](https://werf.io/)
2. Выберите параметры: Локальная разработка → ОС → Сборщик образов (Docker)
3. Выполните рекомендованную команду установки

### Сценарий 1: Настройка доступа к GitHub Container Registry

**Проблема:** Werf требует доступ для публикации образов в приватный registry.

**Решение:**

1. **Создание Personal Access Token в GitHub:**

   ```bash
   # Настройки профиля → Developer settings → Personal access tokens
   # Scope: write:packages (или read:packages для pull)
   ```

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
    dockerfile: Dockerfile
```

Или нативный Stapel:

```yaml
project: myapp
configVersion: "1"

build:
  - image: app
    from: alpine:3.18
    git:
      - add: /
        to: /app
    shell:
      - cd /app && go build -o myapp
    import:
      - image: builder
        add: /myapp
        to: /myapp
```

### Сценарий 3: Шаблонизация манифеста Kubernetes

**Проблема:** Имя образа меняется с каждой сборкой.

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

**Пояснение:** `{{ .Values.werf.image.app }}` — placeholder, который werf заменяет на полный путь к образу во время деплоя.

### Сценарий 4: Развёртывание командой werf converge

**Подготовка:**

```bash
# Логин в registry
docker login ghcr.io -u <username> -p <token>

# Создание secret в кластере
kubectl create secret docker-registry registry-secret \
  --docker-server=ghcr.io \
  --docker-username=<username> \
  --docker-password=<token>
```

**Запуск деплоя:**

```bash
werf converge \
  --repo ghcr.io/<username>/<repo> \
  --env production \
  --namespace <namespace>
```

**Что происходит:**

1. Анализ werf.yaml и локального кэша
2. Сборка образов (или использование кэша)
3. Публикация в GitHub Container Registry
4. Рендеринг Helm-шаблонов с подстановкой имён образов
5. Применение манифестов через `kubectl apply`
6. Отслеживание статуса rollout до завершения

### Сценарий 5: Оптимизация размера образа

**Проблема:** Сборочный образ весит ~800 МБ, runtime — ~50 МБ.

**Решение:** Multi-stage сборка через Stapel:

```yaml
build:
  - image: builder
    from: golang:1.21
    git:
      - add: /
        to: /app
    shell:
      - cd /app && CGO_ENABLED=0 go build -o myapp

  - image: app
    from: alpine:3.18
    import:
      - image: builder
        add: /app/myapp
        to: /myapp
    command: ["/myapp"]
```

**Результат:** Итоговый образ ~10-20 МБ вместо 800+ МБ.

### Сценарий 6: Кросс-платформенная сборка

**Проблема:** Несовместимость архитектур процессора. Например, разработка на macOS (ARM64), а базовый образ по умолчанию предназначен для AMD64.

**Решение:** Использование флага `--platform` для эмуляции нужной архитектуры:

```bash
werf build --platform linux/amd64
```

**Применение:**

- Кросс-платформенная разработка (ARM → AMD64)
- Сборка образов под несколько архитектур
- Тестирование на разных платформах без смены железа

### Сценарий 7: Режим разработки (--dev)

**Проблема:** Необходимость частой пересборки образа при мелких изменениях в коде без создания коммитов.

**Решение:** Использование флага `--dev`.

```bash
werf build --dev
```

**Особенности:**
- Werf игнорирует незакоммиченные изменения и выполняет сборку.
- Удобно для локальной отладки.
- **Не использовать в CI/CD.**

### Сценарий 8: Предварительный просмотр изменений (werf plan)

**Проблема:** Нужно увидеть, какие изменения будут внесены в кластер до их применения.

**Решение:** Команда `werf plan` (аналог `terraform plan`).

```bash
werf plan --env production
```

**Результат:** Вывод diff-а между текущим состоянием кластера и планируемыми манифестами.

### Сценарий 9: Валидация и откат (lint, rollback)

**Проблема:** Проверка синтаксиса перед деплоем и необходимость быстрого отката при сбое.

**Решение:** Использование нативных команд `lint` и `rollback`.

```bash
# Валидация шаблонов
werf lint --env production

# Откат к предыдущему релизу
werf rollback --env production
```

### Сценарий 10: Управление жизненным циклом через аннотации

**Проблема:** Нужно настроить зависимости между ресурсами или политику удаления.

**Решение:** Использование специальных аннотаций werf.

```yaml
metadata:
  annotations:
    # Удалить ресурс при удалении релиза, даже если он был изменен вручную
    werf.io/delete-policy: "delete"
    # Подождать готовности другого ресурса перед деплоем этого
    werf.io/deploy-on: "service/api=ready"
```

## Дополнительная информация

### Структура проекта werf

```text
project/
├── .werf/
│   └── werf.yaml          # Конфигурация сборки
├── .helm/
│   └── templates/         # Манифесты (Helm-совместимые)
│       ├── deployment.yaml
│       ├── service.yaml
│       └── _helpers.tpl
├── src/                   # Исходный код
└── Dockerfile             # Опционально
```

### Сравнение с альтернативами

| Инструмент | Сборщик | Движок деплоя | Server-Side Apply | Giterminism |
| :--- | :--- | :--- | :--- | :--- |
| **Werf** | Stapel/Dockerfile | **Nelm** | Да | Да |
| **Skaffold** | Docker/Jib/Buildpacks | Helm/Kubectl | Частично | Нет |
| **Helm** | Нет | Helm (3-way merge) | Нет | Нет |
| **Tilt** | Docker | Kubectl | Нет | Нет |

### Ограничения

- **Привязка к Git:** Полный потенциал (кэширование, тегирование) раскрывается только при работе с Git.
- **Кривая обучения:** Stapel и концепция Nelm требуют времени на освоение.
- **Хранение стадий:** Требуется внешнее хранилище (Registry) для кэширования стадий сборки.

### Связанные темы

- [Работа с Container Registry](../../Docker/docker_registries.md)
- [Шаблонизация в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
- [Операторы и SSA](../../Kubernetes/Concepts/kubernetes_operators.md)

### Ресурсы

- [Официальный сайт werf.io](https://werf.io/)
- [Документация по Nelm](https://werf.io/documentation/advanced/nelm.html)
- [CNCF Sandbox: werf](https://www.cncf.io/projects/werf/)
