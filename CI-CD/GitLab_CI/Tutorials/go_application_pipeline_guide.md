# Руководство по CI/CD пайплайну для Go-приложения

## Надежность и актуальность

- **Оценка надежности:** 10 (SSoT + Современные практики Go 1.23+)
- **Триггеры обновления:** Выход мажорных версий Go (1.24+), изменения в спецификациях SBOM (CycloneDX), обновление API GitLab Agent (KAS).

## Определения

**Go Pipeline** — автоматизированный процесс жизненного цикла приложения на языке Go, включающий валидацию кода, многоуровневое тестирование, сборку артефактов и доставку в Kubernetes.

**Ключевые компоненты:**
- **`golangci-lint`**: Основной инструмент статического анализа, объединяющий десятки линтеров для Go.
- **Race Detector**: Встроенный в Go инструмент для обнаружения ошибок синхронизации памяти (Data Races) во время выполнения тестов.
- **SBOM (Software Bill of Materials)**: Формализованный перечень всех библиотек и зависимостей, необходимый для аудита безопасности и соответствия (Compliance).
- **GitLab Agent (KAS)**: Современный метод интеграции, обеспечивающий доступ к кластеру через безопасный туннель без передачи статических `KUBECONFIG` в переменные.
- **YAML Anchors (Якоря)**: Механизм переиспользования фрагментов YAML-кода для сокращения дублирования в `.gitlab-ci.yml`.

## Основные концепции

### Стратегия пайплайна (Modern Workflow)

Пайплайн спроектирован по принципу **Fail Fast**: быстрые проверки выполняются первыми.

| Этап | Задачи | Описание |
| :--- | :--- | :--- |
| **Validate** | `lint`, `vulncheck` | Проверка стиля кода и поиск известных уязвимостей в зависимостях. |
| **Test** | `unit-tests`, `race-detector` | Проверка бизнес-логики и поиск состояний гонки под нагрузкой. |
| **Build** | `compile`, `sbom-gen` | Компиляция бинарного файла и создание паспорта зависимостей (SBOM). |
| **Docker** | `image-build` | Создание контейнера через **Kaniko** (стандарт для K8s-раннеров). |
| **Deploy** | `k8s-deploy` | Развертывание в `dev`, `staging` или `production` на основе веток/тегов. |

### Логика развертывания

- **Feature-ветки**: Автоматический деплой в окружение `dev`.
- **Ветка `main`**: Автоматический деплой в окружение `staging`.
- **Git-теги**: Деплой в `production` с обязательным ручным подтверждением.

## Практические сценарии

### Шаг 1: Подготовка Kubernetes-кластера

Перед запуском пайплайна необходимо подготовить пространства имен и права доступа.

**1. Создание Namespaces:**
```bash
kubectl create ns dev
# → namespace/dev created
kubectl create ns staging
# → namespace/staging created
kubectl create ns production
# → namespace/production created
```

**2. Настройка доступа к Registry (Legacy-метод через токены):**
Хотя GitLab Agent (KAS) предпочтительнее, метод с секретами остается базовым для внешних кластеров.
1. Создайте **Deploy Token** в GitLab: `Settings → Repository → Deploy Tokens` (права: `read_registry`).
2. Создайте секрет в каждом Namespace:
```bash
kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=$CI_REGISTRY \
  --docker-username=<имя_токена> \
  --docker-password=<пароль_токена> \
  -n dev
# → secret/gitlab-registry-secret created
```

### Шаг 2: Оптимизированный Dockerfile (Multi-stage)

Использование `distroless` образов минимизирует размер и поверхность атаки.

```dockerfile
# Stage 1: Build
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Сборка статически слинкованного бинарного файла
RUN CGO_ENABLED=0 GOOS=linux go build -o main ./cmd/app

# Stage 2: Runtime (Security Hardening)
FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/main /app/main
USER nonroot:nonroot
ENTRYPOINT ["/app/main"]
```

### Шаг 3: Конфигурация пайплайна (.gitlab-ci.yml)

**Шаблоны правил (YAML Anchors):**
```yaml
.no_tags_rules: &no_tags_rules
  rules:
    - if: '$CI_COMMIT_TAG'
      when: never
    - when: on_success

.tags_only_rules: &tags_only_rules
  rules:
    - if: '$CI_COMMIT_TAG'
      when: on_success
    - when: never
```

**Реализация стадий:**
```yaml
variables:
  GOPATH: $CI_PROJECT_DIR/.go
  GOLANGCI_LINT_CACHE: $CI_PROJECT_DIR/.golangci-lint

cache:
  paths:
    - .go/pkg/mod
    - .golangci-lint

lint:
  stage: validate
  image: golangci/golangci-lint:v1.60
  script:
    - golangci-lint run -v
  <<: *no_tags_rules

unit_tests:
  stage: test
  image: golang:1.23-alpine
  script:
    - go test -race -v -coverprofile=coverage.out ./...
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.out
  <<: *no_tags_rules

compile:
  stage: build
  image: golang:1.23-alpine
  script:
    - go build -o bin/app ./cmd/app
    # Генерация SBOM через Syft
    - wget https://github.com/anchore/syft/releases/download/v1.0.0/syft_1.0.0_linux_amd64.tar.gz
    - tar -xf syft_1.0.0_linux_amd64.tar.gz && ./syft bin/app -o cyclonedx-json=sbom.json
  artifacts:
    paths:
      - bin/app
      - sbom.json
  <<: *no_tags_rules

deploy_dev:
  stage: deploy
  image: bitnami/kubectl:1.28
  script:
    - export ENVIRONMENT=dev
    - envsubst < manifests/deployment.template.yml | kubectl apply -n $ENVIRONMENT -f -
  rules:
    - if: '$CI_COMMIT_BRANCH != "main" && $CI_COMMIT_TAG == null'
```

### Шаг 4: Шаблон манифеста Kubernetes

Файл `manifests/deployment.template.yml` используется для подстановки переменных через `envsubst`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: go-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: go-app
  template:
    metadata:
      labels:
        app: go-app
    spec:
      imagePullSecrets:
        - name: gitlab-registry-secret
      containers:
        - name: app
          image: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
```

## Технические нюансы и Тюнинг

### Детектор гонок (Race Detector)
В Go использование `-race` в CI является критически важным. Оно позволяет обнаружить недетерминированные баги конкурентности, которые невозможно воспроизвести обычными тестами.

### Кэширование
Эффективное кэширование `.go/pkg/mod` и папок линтера сокращает время выполнения пайплайна на **40-60%**. Всегда определяйте `GOPATH` внутри директории проекта для корректной работы кэша GitLab.

## Дополнительная информация

### GitOps и ArgoCD
Для крупных инсталляций рекомендуется переход на Pull-модель. Пайплайн CI в этом случае только собирает образ и обновляет его версию в отдельном Git-репозитории конфигураций, а **ArgoCD** синхронизирует состояние кластера. См. **[Обзор ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

### Безопасность (Supply Chain)
Генерация SBOM позволяет построить прозрачный граф зависимостей. Это фундамент для интеграции с инструментами анализа уязвимостей, такими как **Dependency Track**.

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — архитектура и синтаксис.
- **[Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — безопасность без привилегий.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка Агентов.
- **[Окружения и деплой в GitLab CI](../Concepts/environments_and_deployments.md)** — управление логическими средами.
