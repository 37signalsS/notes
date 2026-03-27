# Werf: Практические сценарии

## Определения

**Werf** — инструмент для автоматизации сборки Docker-образов и развёртывания в Kubernetes. Данный документ содержит практические сценарии использования.

Базовая информация: [Werf: Автоматизация сборки и развёртывания](./werf_overview.md).

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

```
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
| **Werf** | ✅ (Dockerfile/Stapel) | ✅ (встроенный Helm) | ✅ (Go template) | ✅ (инкрементальное) |
| **Docker + Helm** | ✅ (только Dockerfile) | ✅ | ✅ | ❌ |
| **Skaffold** | ✅ | ✅ | ✅ (Jinja2) | ✅ |
| **Tilt** | ✅ | ✅ | ❌ | ✅ |

### Ограничения

- **Не поддерживает локальные registry:** Требуется внешнее хранилище (GHCR, Harbor, Docker Hub)
- **Привязка к Git:** Тегирование образов зависит от истории коммитов
- **Кривая обучения:** Stapel требует изучения нового синтаксиса

### Связанные темы

- **Docker Registry:** [Работа с registry](../../../Docker/docker_registries.md)
- **Helm templating:** [Шаблонизация в Helm](../../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
- **ImagePullSecrets:** [Создание секретов для registry](../../../Kubernetes/Base/secrets/creating_secrets.md#docker-registry-secret)
- **Deployment Strategies:** [Стратегии развёртывания](../Core_Concepts/deployment_strategies.md)
- **DevSecOps:** [Безопасность образов](../DevSecOps/sast_dast_cicd_integration.md)

### Ресурсы

- [Официальная документация werf](https://werf.io/)
- [Stapel reference](https://werf.io/documentation/reference/stapel_config.html)
- [GitHub Container Registry docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
