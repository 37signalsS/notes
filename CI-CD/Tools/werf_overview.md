# Werf: Автоматизация сборки и развёртывания в Kubernetes

## Определения

**Werf** — это инструмент для автоматизации сборки Docker-образов и развёртывания приложений в Kubernetes. Объединяет процессы сборки, публикации образов и деплоя в единую команду.

**Stapel** — формат описания сборки образов в werf. Альтернатива Dockerfile, предоставляющая декларативный синтаксис на YAML.

**Werf Converge** — основная команда развёртывания. Выполняет сборку образов, публикацию в registry, применение манифестов Kubernetes и отслеживание статуса деплоя.

## Основные концепции

### Ключевые принципы

**Infrastructure as Code (IaC)** — вся конфигурация сборки и развёртывания описывается в файлах, которые хранятся в Git вместе с кодом приложения. Это обеспечивает версионирование и повторяемость процессов.

**Гитерминизм** (Git + Determinism) — вся информация о сборке и запуске берётся только из Git как из единственного правдивого источника истины. Werf работает только с закоммиченными изменениями, что гарантирует точное знание о том, какая версия кода и конфигурации используется, и исключает случайные или локальные изменения.

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
| **Единая команда** | `werf converge` заменяет `docker build` + `docker push` + `helm upgrade` |
| **Кэширование** | Инкрементальная сборка ускоряет повторные запуски |
| **Безопасность** | Образы минимального размера за счёт multi-stage сборки |
| **GitOps-ready** | Интеграция с Git через commit-based тегирование |

## Практические сценарии

### Сценарий 0: Установка werf

**Установка (macOS):**

```bash
# Установка одной командой через curl
curl -sL https://werf.io/install.sh | bash
```

Для других ОС и вариантов установки см. [официальную документацию](https://werf.io/documentation/install.html).

**Проверка установки:**

```bash
werf version
# Вывод: 2.5.1 (или новее)
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

**Проблема:** Необходимость частой пересборки образа при мелких изменениях в коде. Делать коммит для каждого изменения неудобно.

**Решение:** Использование флага `--dev` для сборки без требования закоммиченных изменений:

```bash
werf build --dev
```

**Особенности:**

- Werf игнорирует незакоммиченные изменения и выполняет сборку
- Удобно для быстрой проверки гипотез и локальной отладки
- **Не используйте в CI/CD** — флаг только для локальной разработки

**Пример использования:**

```bash
# Внесены изменения в код, но не закоммичены
werf build --dev  # Сборка выполнится

# Для production-подобной сборки нужен коммит
git add . && git commit -m "feat: add new feature"
werf build  # Сборка с закоммиченными изменениями
```

## Дополнительная информация

### Структура проекта werf

```text
project/
├── .werf/
│   └── werf.yaml          # Конфигурация сборки
├── .helm/
│   └── templates/
│       ├── deployment.yaml
│       ├── service.yaml
│       └── _helpers.tpl
├── src/                   # Исходный код приложения
└── Dockerfile             # Опционально
```

### Сравнение с альтернативами

| Инструмент | Сборка | Деплой | Templating | Кэширование |
| :--- | :--- | :--- | :--- | :--- |
| **Werf** | Да (Dockerfile/Stapel) | Да (встроенный Helm) | Да (Go template) | Да (инкрементальное) |
| **Docker + Helm** | Да (только Dockerfile) | Да | Да | Нет |
| **Skaffold** | Да | Да | Да (Jinja2) | Да |
| **Tilt** | Да | Да | Нет | Да |

### Ограничения

- **Не поддерживает локальные registry:** Требуется внешнее хранилище (GHCR, Harbor, Docker Hub)
- **Привязка к Git:** Тегирование образов зависит от истории коммитов
- **Кривая обучения:** Stapel требует изучения нового синтаксиса

### Связанные темы

- [Работа с registry](../../Docker/docker_registries.md)
- [Шаблонизация в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
- [Стратегии развёртывания](../Core_Concepts/deployment_strategies.md)

### Ресурсы

- [Официальная документация werf](https://werf.io/)
- [Stapel reference](https://werf.io/documentation/reference/stapel_config.html)
