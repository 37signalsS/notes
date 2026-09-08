# Руководство по CI/CD пайплайну для Go-приложения

## Определения

**Go Pipeline** — автоматизированный процесс жизненного цикла приложения на языке Go, включающий валидацию кода, многоуровневое тестирование, сборку артефактов и доставку в Kubernetes.

**Ключевые компоненты:**
- **`golangci-lint`**: Основной инструмент статического анализа, объединяющий десятки линтеров (unused, errcheck, staticcheck и др.) для Go.
- **`govulncheck`**: Официальный инструмент от команды Go для поиска известных уязвимостей в зависимостях на основе базы данных Go Vulnerability Database.
- **Race Detector**: Встроенный в Go инструмент для обнаружения ошибок синхронизации памяти (Data Races) во время выполнения тестов.
- **Fuzz Testing**: Метод тестирования, при котором в функции передаются случайные данные для поиска крайних случаев и ошибок сегментации. Встроен в Go с версии 1.18.
- **SBOM (Software Bill of Materials)**: Формализованный перечень всех библиотек и зависимостей, необходимый для аудита безопасности и соответствия (Compliance).
- **GitLab Agent (KAS)**: Современный метод интеграции, обеспечивающий доступ к кластеру через безопасный туннель без передачи статических `KUBECONFIG` в переменные.
- **`id_tokens` (OIDC)** — современный механизм аутентификации (стандарт 2026 года), позволяющий GitLab Runner безопасно взаимодействовать с внешними сервисами (Vault, облачные провайдеры) без использования долгоживущих секретов.

## Основные концепции

### Стратегия пайплайна (Modern Workflow)

Пайплайн спроектирован по принципу **Fail Fast**: быстрые и дешевые проверки выполняются первыми, блокируя дорогостоящие этапы сборки и деплоя при обнаружении ошибок.

| Этап | Задачи | Описание |
| :--- | :--- | :--- |
| **Validate** | `lint`, `vulncheck` | Проверка стиля кода, семантики и поиск известных уязвимостей в графе зависимостей. |
| **Test** | `unit-tests`, `race`, `fuzz` | Проверка бизнес-логики, поиск состояний гонки и фаззинг критических функций парсинга. |
| **Build** | `compile`, `sbom-gen` | Компиляция бинарного файла с оптимизацией и создание паспорта зависимостей (CycloneDX). |
| **Security** | `image-scan` | Анализ готового Docker-образа на наличие уязвимостей в системных библиотеках (OS-level). |
| **Docker** | `image-build` | Создание контейнера через **Kaniko** (безопасная сборка без привилегий в K8s). |
| **Deploy** | `k8s-deploy` | Развертывание в окружения на основе GitFlow или GitLab Flow с использованием KAS. |

### Принципы сборки Go в CI
Для обеспечения детерминированности и безопасности сборки используются:
1.  **Multi-stage Builds**: Разделение среды сборки и среды выполнения для минимизации размера образа.
2.  **CGO_ENABLED=0**: Создание статически слинкованных бинарных файлов для работы в `scratch` или `distroless` образах.
3.  **LDFLAGS**: Использование флагов `-s -w` для удаления отладочной информации и уменьшения размера файла.
4.  **Module Caching**: Переиспользование директории `$GOPATH/pkg/mod` между запусками пайплайна.

### Логика развертывания
*   **Окружение `dev`**: Автоматический деплой из feature-веток для быстрого тестирования разработчиками.
*   **Окружение `staging`**: Автоматический деплой из ветки `main` после успешного прохождения всех тестов.
*   **Окружение `production`**: Деплой при создании Git-тега (Release) с обязательным ручным подтверждением (Manual Gate).

## Практические сценарии

### Предварительные требования

**Инфраструктура:**
- **GitLab:** Версия 16.0+ (для KAS и `id_tokens`).
- **Kubernetes:** Кластер 1.27+ с доступом через kubectl или GitLab Agent (KAS).
- **Docker/Kaniko:** Раннер с Docker Executor или Kubernetes Executor (Kaniko работает без特权).
- **Go:** Версии 1.21+ (для fuzz testing и `go.work`).

**Инструменты (автоматически устанавливаются в CI):**
- `golangci-lint` — статический анализ (устанавливается через Docker-образ `golangci/golangci-lint`).
- `govulncheck` — проверка уязвимостей (устанавливается через `go install`).
- `syft` — генерация SBOM (устанавливается через `go install`).

**Переменные CI/CD (Settings > CI/CD > Variables):**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `KUBECONTEXT` | Variable | Имя контекста Kubernetes в GitLab (формат: `group/project/k8s-agent:agent-name`). |
| `CI_REGISTRY_PASSWORD` | **File** (опционально) | Пароль для приватного Registry (если не используется автоматическая авторизация). |

**Базовые знания:**
- Основы Go: модули (`go.mod`), пакеты, тестирование.
- Основы Docker: Dockerfile, multi-stage builds, `.dockerignore`.
- Основы Kubernetes: Deployment, Service, HPA, Namespace.
- Основы GitLab CI/CD: stages, rules, variables, artifacts.

### Шаг 1: Подготовка Kubernetes-кластера

В 2026 году основным методом интеграции является **GitLab Agent for Kubernetes (KAS)**. Он позволяет пайплайнам работать с API кластера через защищенный туннель без хранения секретов в GitLab.

**1. Создание Namespaces и разграничение доступа:**
```bash
# Создание целевых окружений
kubectl create ns app-dev
kubectl create ns app-staging
kubectl create ns app-prod
```

**2. Регистрация GitLab Agent:**
1.  В GitLab: `Operate → Kubernetes clusters → Connect a cluster`.
2.  Создайте файл конфигурации в репозитории: `.gitlab/agents/<agent-name>/config.yaml`.
3.  Настройте права доступа пайплайнов в `config.yaml`:
    ```yaml
    ci_access:
      projects:
        - id: my-org/my-go-app
    ```
4.  Установите агента в кластер через Helm (команда генерируется в UI GitLab).

**3. Настройка доступа к Registry (при необходимости):**
Если образы хранятся в приватном GitLab Registry, убедитесь, что в кластере создан `imagePullSecret` или настроен автоматический доступ через Агента.

### Шаг 2: Оптимизированная сборка (Multi-stage + Security)

Для Go-приложений важно исключить лишние файлы из контекста сборки и минимизировать размер итогового образа.

**1. Файл `.dockerignore`:**
```dockerfile
.git
.go
vendor
bin
*.out
Dockerfile
.gitlab-ci.yml
```

**2. Dockerfile (Go 1.23 + Distroless):**
```dockerfile
# Stage 1: Build
FROM golang:1.23-alpine AS builder

# Установка зависимостей ОС для сборки (если нужны)
RUN apk add --no-cache git ca-certificates

WORKDIR /app

# Кэширование модулей
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Сборка:
# -ldflags="-s -w": удаление таблицы символов и DWARF (уменьшение веса)
# -trimpath: удаление путей файловой системы разработчика из бинарника
RUN CGO_ENABLED=0 GOOS=linux \
    go build -ldflags="-s -w" -trimpath -o main ./cmd/app

# Stage 2: Runtime
# Использование static-debian12 для максимальной безопасности (Zero CVE)
FROM gcr.io/distroless/static-debian12:latest

COPY --from=builder /app/main /app/main
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Запуск от не привилегированного пользователя
USER nonroot:nonroot

EXPOSE 8080
ENTRYPOINT ["/app/main"]
```

### Шаг 3: Конфигурация пайплайна (.gitlab-ci.yml)

В современной версии (2026) рекомендуется использовать `extends` для повторного использования кода и `id_tokens` для безопасной аутентификации.

```yaml
variables:
  GOPATH: $CI_PROJECT_DIR/.go
  GOLANGCI_LINT_CACHE: $CI_PROJECT_DIR/.golangci-lint
  GO_BUILD_CACHE: $CI_PROJECT_DIR/.cache/go-build
  KUBECONTEXT: "my-org/infrastructure/k8s-agents:my-agent"

default:
  image: golang:1.23-alpine
  cache:
    key:
      files:
        - go.sum
    paths:
      - .go/pkg/mod
      - .golangci-lint
      - .cache/go-build

stages:
  - validate
  - test
  - build
  - deploy

.go_rules:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"

lint:
  stage: validate
  image: golangci/golangci-lint:v1.64
  script:
    - golangci-lint run -v
  extends: .go_rules

vulnerability_scan:
  stage: validate
  script:
    - go install golang.org/x/vuln/cmd/govulncheck@latest
    - govulncheck ./...
  extends: .go_rules

unit_tests:
  stage: test
  script:
    - go test -race -v -coverprofile=coverage.out ./...
  artifacts:
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.out
  extends: .go_rules

fuzz_testing:
  stage: test
  script:
    - go test -fuzz=FuzzParse -fuzztime=30s ./internal/parser
  extends: .go_rules
  allow_failure: true

compile:
  stage: build
  script:
    - go build -ldflags="-s -w" -o bin/app ./cmd/app
    # Генерация SBOM
    - go install github.com/anchore/syft/cmd/syft@latest
    - syft bin/app -o cyclonedx-json=sbom.json
  artifacts:
    paths:
      - bin/app
      - sbom.json
  extends: .go_rules

deploy_dev:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl config use-context $KUBECONTEXT
    - envsubst < manifests/app.yaml | kubectl apply -f -
  rules:
    - if: $CI_COMMIT_BRANCH != "main"
  environment:
    name: dev
```

### Шаг 4: Комплексный манифест Kubernetes

Файл `manifests/app.yaml` содержит описание всех необходимых ресурсов для работы приложения.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: go-app
  labels:
    app: go-app
spec:
  replicas: ${REPLICAS}
  selector:
    matchLabels:
      app: go-app
  template:
    metadata:
      labels:
        app: go-app
    spec:
      containers:
        - name: app
          image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
          ports:
            - containerPort: 8080
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: go-app-service
spec:
  selector:
    app: go-app
  ports:
    - port: 80
      targetPort: 8080
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: go-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: go-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## Технические нюансы и Тюнинг

### Детектор гонок (Race Detector)
Использование `-race` в CI критически важно для Go. Инструмент добавляет инструкции для отслеживания доступа к памяти, что позволяет обнаружить ошибки конкурентности до того, как они приведут к падению в продакшене. **Важно:** тесты с детектором гонок потребляют в 2-10 раз больше памяти и работают медленнее, учитывайте это при выборе ресурсов для раннера.

### Эффективное кэширование
Кэширование в GitLab CI для Go должно включать:
*   `$GOPATH/pkg/mod` — скачанные зависимости.
*   `~/.cache/go-build` — кэш компиляции (сильно ускоряет инкрементальные сборки).
*   `GOLANGCI_LINT_CACHE` — кэш линтера для сокращения времени валидации.

## Устранение неисправностей (Troubleshooting)

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`context deadline exceeded` в тестах** | Медленное выполнение с `-race` | Увеличьте таймаут: `go test -timeout 5m`. Для длинных интеграционных тестов используйте `timeout 300` на уровне job. |
| **`Permission denied` в Kaniko** | Отсутствие прав у ServiceAccount | Убедитесь, что под раннера имеет права на запись в `imagePullSecrets`. Проверьте RBAC: `kubectl auth can-i create pods`. |
| **Кэш не восстанавливается** | Разные ключи кэша | Используйте `files: [go.sum]` в качестве ключа для гарантии консистентности. Кэш привязан к ветке — не используйте `key: $CI_COMMIT_REF_SLUG` без `files`. |
| **`govulncheck` нашел уязвимость** | Уязвимая библиотека | Выполните `go get -u <library>` и обновите `go.mod`. Если патч недоступен, оцените риск и задокументируйте в Security Advisory. |
| **`no required module provides package`** | Отсутствует зависимость в `go.mod` | Выполните `go mod tidy` и закоммитьте `go.mod` + `go.sum`. В CI добавьте шаг проверки: `go mod verify`. |
| **Fuzz-тест падает с `panic`** | Найден edge case в коде | Используйте `go test -fuzz=FuzzX -fuzztime=5s` для быстрой проверки. Сохраните crash--input: `go test -run=FuzzX -fuzz=FuzzX` с фиксированным seed. |
| **`golangci-lint` не находит файлы** | Неверная директория запуска | Убедитесь, что `working_directory` соответствует корню Go-модуля. Проверьте наличие `go.mod` в текущей директории. |
| **`kubectx` не найден в образе** | Отсутствие kubectl в контейнере | Используйте `bitnami/kubectl:latest` как `image` для deploy-задач или установите `kubectl` в скрипте. |
| **Distroless образ не запускается** | Неверный ENTRYPOINT или отсутствие зависимостей | Проверьте: `docker run --rm --entrypoint "" <image> ls /app`. Убедитесь, что бинарник скомпилирован с `CGO_ENABLED=0`. |
| **`certificate signed by unknown authority`** | Отсутствуют CA-сертификаты в образе | Добавьте `COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/` в runtime-стадию Dockerfile. |
| **HPA не масштабирует поды** | Нет метрик CPU/Memory или Metrics Server не установлен | Проверьте: `kubectl top pods`. Убедитесь, что ресурсы `requests` заданы в Deployment. |
| **Deploy не работает через KAS** | Неверный `KUBECONTEXT` или агент не подключен | Проверьте имя контекста в GitLab: `Operate → Kubernetes clusters`. Убедитесь, что `config.yaml` агента содержит `ci_access` для проекта. |

## Лучшие практики (Best Practices)

**Безопасность:**
- Всегда запускайте `govulncheck ./...` в stage `validate` — это блокирует сборку при обнаружении известных CVE.
- Используйте `CGO_ENABLED=0` для статической линковки — исключает runtime-зависимости и снижает攻擊ную поверхность.
- Не храните пароли и токены в `CI/CD Variables` в открытом виде — используйте File-тип или Vault OIDC.
- Добавьте `SBOM` и `image scan` (Trivy) в pipeline для аудита Supply Chain.
- Запускайте `golangci-lint` с конфигурацией `.golangci.yml` в корне проекта — это гарантирует единый стандарт качества кода.

**Производительность:**
- Кэшируйте `$GOPATH/pkg/mod` и `~/.cache/go-build` — это сокращает время сборки на 50–70%.
- Используйте `golangci-lint run --new-from-rev=HEAD~1` в MR — это проверяет только изменённый код.
- Для fuzz-тестов задавайте `fuzztime=30s` вместо бесконечного цикла — это предотвращает зависание.
- Используйте `distroless` вместо `alpine` для runtime — образ меньше и безопаснее.

**Надёжность:**
- Используйте `extends: .go_rules` для единообразия правил запуска задач.
- Задавайте `timeout:` для каждой задачи — предотвращает зависание пайплайна.
- Используйте `retry: 2` для network-dependent задач (govulncheck, image pull).
- Тестируйте Docker-образ локально перед коммитом: `docker build -t app:test . && docker run --rm app:test`.

**Мониторинг и observability:**
- Экспортируйте метрики Go-приложения через Prometheus: `promhttp.Handler()`.
- Настройте `livenessProbe` и `readinessProbe` в Kubernetes Deployment.
- Используйте structured logging (`log/slog` в Go 1.21+) для удобного парсинга в Kibana/Grafana.

## Очистка и откат (Cleanup)

**Откат Docker-образа в Registry:**
```bash
# Удаление конкретного тега через API GitLab
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/<repo_id>/tags/<tag>"

# Полная очистка неиспользуемых образов ( garbage collection )
# Включите Cleanup Policy в GitLab: Settings > Packages and Registries > Cleanup policy
```

**Откат Kubernetes-деплоя:**
```bash
# Откат на предыдущую ревизию
kubectl rollout undo deployment/go-app -n app-prod

# Откат на конкретную ревизию
kubectl rollout undo deployment/go-app -n app-prod --to-revision=3

# Проверка истории
kubectl rollout history deployment/go-app -n app-prod
```

**Очистка артефактов CI:**
```bash
# Удаление артефактов через API (TTL)
# Настройте в Settings > CI/CD > Artifacts expiration

# Ручная очистка через крон
kubectl delete jobs -l app=gitlab-runner -n gitlab-runner
```

**Очистка кэша Go:**
```bash
# Локальная очистка
go clean -cache -testcache
go clean -modcache

# В CI: автоматически через policy expiration в Settings > CI/CD > Caching
```

## Граничные случаи (Edge Cases)

**Мультиплатформенная сборка (linux/amd64, linux/arm64):**
- Используйте `GOOS=linux GOARCH=arm64 go build` для кросс-компиляции.
- Для Kaniko: `--platform=linux/amd64,linux/arm64` с `docker buildx`.
- Не используйте QEMU-эмуляцию — нативная кросс-компиляция в 10 раз быстрее.

**Монорепозиторий (go.work, несколько модулей):**
- Используйте `rules:changes` для запуска тестов только затронутых модулей.
- Настройте `golangci-lint` с `--whole-files` для проверки всех файлов в MR.

**Интеграция с Vault (секреты):**
- Используйте OIDC для аутентификации GitLab → Vault (без статических секретов).
- См. **[Vault + Kubernetes Integration](../../../Vault/guides/vault_kubernetes_integration.md)**.

**Go-приложение с CGO (зависимости C):**
- Если 필요ен `CGO_ENABLED=1` (например, для SQLite), используйте `golang:1.23-bookworm` вместо Alpine.
- В runtime добавьте `libc6` в образ: `FROM debian:bookworm-slim`.

**Высокая нагрузка в CI (>100 коммитов/день):**
- Используйте `rules:workflow` для дедупликации пайплайнов.
- Настройте `interruptible: true` для MR — это отменяет предыдущие запуски.
- Используйте distributed cache (S3/MinIO) вместо локального кэша раннера.

**Интеграция с ArgoCD:**
- Пайплайн CI только собирает образ и обновляет его версию в GitOps-репозитории.
- ArgoCD синхронизирует состояние кластера через Pull-модель.
- См. **[Обзор ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

## Дополнительная информация

### GitOps и ArgoCD
Для крупных инсталляций рекомендуется переход на Pull-модель. Пайплайн CI в этом случае только собирает образ и обновляет его версию в отдельном Git-репозитории конфигураций, а **ArgoCD** синхронизирует состояние кластера. См. **[Обзор ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

### Безопасность (Supply Chain)
Генерация SBOM позволяет построить прозрачный граф зависимостей. Это фундамент для интеграции с инструментами анализа уязвимостей, такими как **Dependency Track** или **Trivy**.

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — архитектура и синтаксис.
- **[Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — безопасная сборка без привилегий.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка Агентов.
- **[Dockerfile для Go: лучшие практики](../../../Docker/Dockerfile/Docker_best_practices/go.md)** — multi-stage builds, CGO, дистрибутивы, оптимизация.
- **[Целостность сборки](../../../Security/Supply_Chain_Security/build_integrity.md)** — SLSA, Provenance, аттестации.
- **[Кэширование в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)** — стратегии кэширования для Go.
- **[Официальная документация: Go в GitLab](https://docs.gitlab.com/ee/ci/examples/)**

