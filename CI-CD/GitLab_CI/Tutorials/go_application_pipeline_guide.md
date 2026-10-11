# Руководство по CI/CD пайплайну для Go-приложения

**Актуально для:** GitLab 19.x, Go 1.27+, Kubernetes 1.27+

## Определения

**Go Pipeline** — автоматизированный процесс жизненного цикла приложения на языке Go, включающий валидацию кода, многоуровневое тестирование, сборку артефактов и доставку в Kubernetes.

**Ключевые компоненты:**
- **`golangci-lint`**: Основной инструмент статического анализа, объединяющий десятки линтеров (unused, errcheck, staticcheck и др.) для Go.
- **`govulncheck`**: Официальный инструмент от команды Go для поиска известных уязвимостей в зависимостях на основе базы данных Go Vulnerability Database.
- **Race Detector**: Встроенный в Go инструмент для обнаружения ошибок синхронизации памяти (Data Races) во время выполнения тестов.
- **Fuzz Testing**: Метод тестирования, при котором в функции передаются случайные данные для поиска крайних случаев и ошибок сегментации. Встроен в Go с версии 1.18.
- **SBOM (Software Bill of Materials)**: Формализованный перечень всех библиотек и зависимостей, необходимый для аудита безопасности и соответствия (Compliance).
- **GitLab Agent (KAS)**: Современный метод интеграции, обеспечивающий доступ к кластеру через безопасный туннель без передачи статических `KUBECONFIG` в переменные.
- **`id_tokens` (OIDC)** — современный механизм аутентификации (стандарт 2026 года), позволяющий GitLab Runner безопасно взаимодействовать с внешними системами без использования долгоживущих секретов.

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
- **Docker/Kaniko:** Раннер с Docker Executor или Kubernetes Executor (Kaniko работает без привилегий).
- **Go:** Версии 1.27+ (для fuzz testing и `go.work`).

**Инструменты (автоматически устанавливаются в CI):**
- `golangci-lint` — статический анализ (устанавливается через Docker-образ `golangci/golangci-lint`).
- `govulncheck` — проверка уязвимостей (устанавливается через `go install`).
- `syft` — генерация SBOM (устанавливается через `go install`).

**Переменные CI/CD (Settings > CI/CD > Variables):**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `KUBE_CONTEXT` | Variable | Имя контекста Kubernetes в GitLab (формат: `group/project/k8s-agent:agent-name`). |
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

**2. Dockerfile (Go 1.27 + Distroless):**
```dockerfile
# Stage 1: Build
FROM golang:1.27-alpine AS builder

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

**Валидация Docker-образа:**
```bash
# Проверка размера образа (должен быть < 20 МБ для distroless)
docker images go-app:latest
# → go-app   latest   <digest>   2-5MB

# Проверка, что бинарник статически слинкован
docker run --rm --entrypoint "" go-app:latest file /app/main
# → /app/main: ELF 64-bit LSB executable, Go BuildID=..., statically linked

# Проверка безопасности: нет shell и пакетного менеджера
docker run --rm --entrypoint "" go-app:latest ls /bin/sh
# → ls: /bin/sh: No such file or directory

# Проверка работоспособности
docker run --rm -p 8080:8080 go-app:latest &
curl http://localhost:8080/health
# → {"status":"ok"}
```

### Шаг 3: Конфигурация пайплайна (.gitlab-ci.yml)

В современной версии (2026) рекомендуется использовать `extends` для повторного использования кода и `id_tokens` для безопасной аутентификации.

```yaml
variables:
  GOPATH: $CI_PROJECT_DIR/.go
  GOLANGCI_LINT_CACHE: $CI_PROJECT_DIR/.golangci-lint
  GO_BUILD_CACHE: $CI_PROJECT_DIR/.cache/go-build
  KUBE_CONTEXT: "my-org/infrastructure/k8s-agents:my-agent"

default:
  image: golang:1.27-alpine
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
  image: golangci/golangci-lint:v2.13
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
    - kubectl config use-context $KUBE_CONTEXT
    - envsubst < manifests/app.yaml | kubectl apply -f -
  rules:
    - if: $CI_COMMIT_BRANCH != "main"
  environment:
    name: dev
```

**Валидация пайплайна:**
```bash
# Проверка синтаксиса YAML через GitLab CLI (glab)
glab ci lint --file .gitlab-ci.yml
# → Valid

# Или через API GitLab
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/ci/lint" \
  --data "content=$(cat .gitlab-ci.yml)"
# → {"status":"valid","errors":[]}

# Проверка, что кэш определён корректно
# В логах job `lint` ищите:
# - Cache size: ...
# - Cache downloaded successfully

# Проверка артефактов после пайплайна
# В UI GitLab: Pipeline → job `compile` → Artifacts: bin/app, sbom.json
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

**Валидация развёртывания:**
```bash
# Проверка статуса Deployment
kubectl rollout status deployment/go-app -n app-dev --timeout=120s
# → deployment "go-app" successfully rolled out

# Проверка, что поды запущены и готовы
kubectl get pods -n app-dev -l app=go-app
# → NAME                    READY   STATUS    RESTARTS   AGE
# → go-app-xxx              1/1     Running   0          30s

# Проверка health endpoint
kubectl port-forward deployment/go-app -n app-dev 8080:8080 &
curl http://localhost:8080/health
# → {"status":"ok"}

# Проверка HPA
kubectl get hpa -n app-dev
# → NAME        REFERENCE              TARGETS   MINPODS   MAXPODS
# → go-app-hpa  Deployment/go-app      0%/70%    2         10

# Проверка Service
kubectl get svc -n app-dev go-app-service
# → NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
# → go-app-service    ClusterIP   10.43.xxx.xxx   <none>        80/TCP
```

## Технические нюансы и Тюнинг

### Детектор гонок (Race Detector)
Использование `-race` в CI критически важно для Go. Инструмент добавляет инструкции для отслеживания доступа к памяти, что позволяет обнаружить ошибки конкурентности до того, как они приведут к падению в продакшене. **Важно:** тесты с детектором гонок потребляют в 2-10 раз больше памяти и работают медленнее, учитывайте это при выборе ресурсов для раннера.

### Эффективное кэширование
Кэширование в GitLab CI для Go должно включать:
*   `$GOPATH/pkg/mod` — скачанные зависимости.
*   `~/.cache/go-build` — кэш компиляции (сильно ускоряет инкрементальные сборки).
*   `GOLANGCI_LINT_CACHE` — кэш линтера для сокращения времени валидации.

### Архитектура Runner для Go-пайплайнов

Для Go-приложений выбор executor'а определяется требованиями к изоляции, скорости и доступности ресурсов:

| Executor | Изоляция | Скорость | Рекомендация для Go |
| :--- | :--- | :--- | :--- |
| **`kubernetes`** | Высокая (Pod) | Средняя | Стандарт для production: каждый job в отдельном Pod, автоматическая очистка. |
| **`docker`** | Средняя (контейнер) | Высокая | Подходит для сред с постоянным раннером; требует DinD или Kaniko для сборки образов. |
| **`shell`** | Отсутствует | Максимальная | Только для локальных разработческих задач и сборок, требующих direct HW access. |

**SRE: Конфигурация Kubernetes Executor для Go:**
```yaml
# config.toml фрагмент
[[runners]]
  name = "go-build-runner"
  executor = "kubernetes"
  [runners.kubernetes]
    image = "golang:1.27-alpine"
    cpu_limit = "2"
    memory_limit = "4Gi"
    cpu_request = "500m"
    memory_request = "1Gi"
    service_account = "gitlab-runner"
    namespace = "gitlab-runners"
    poll_interval = 5
    cache_dir = "/cache"
```

**Важно:** Для jobs с `-race` и `go test` выделяйте минимум 2 ГБ RAM — детектор гонок может увеличить потребление памяти в 2-10 раз.

### Мониторинг и алертинг пайплайнов

**Метрики здоровья пайплайнов (Prometheus + GitLab Exporter):**
- `gitlab_ci_pipeline_duration_seconds` — время выполнения пайплайна по стадиям.
- `gitlab_ci_job_failed_total` — количество упавших задач по проектам.
- `gitlab_runner_jobs_duration_seconds` — время выполнения задач на конкретном раннере.

**Ключевые алерты:**
- `PipelineFailed` — пайплайн упал в `main` или защищённой ветке.
- `JobStuck` — задача висит в `pending` дольше `timeout` из-за нехватки раннеров.
- `RaceDetectorOOM` — job с `-race` упал по OOM (требует увеличения лимитов).
- `VulnerabilityFound` — `govulncheck` обнаружил CVE высокого/критического уровня.
- `CacheMiss` — кэш Go не восстановился (возможна проблема с Distributed Cache).

### Compliance и Supply Chain

**SBOM и артефакты:**
- Сохраняйте `sbom.json` (CycloneDX) как артефакт каждого `compile` job — это требуется для SOC2/PCI-DSS аудита.
- Настройте retention policy для артефактов: `90 дней` для SBOM, `30 дней` для бинарных файлов.
- Используйте `rules:changes` для запуска `govulncheck` и `golangci-lint` только при изменении `go.mod` или `go.sum`.

**Аудит сборки:**
- Включите audit log в GitLab для отслеживания, кто запускал деплой в production.
- Храните Docker-образы в приватном Registry с включённым vulnerability scanning.
- Используйте image tags на основе `$CI_COMMIT_SHORT_SHA`, а не `latest` — обеспечивает traceability.

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
| **Deploy не работает через KAS** | Неверный `KUBE_CONTEXT` или агент не подключен | Проверьте имя контекста в GitLab: `Operate → Kubernetes clusters`. Убедитесь, что `config.yaml` агента содержит `ci_access` для проекта. |
| **`go build: -trimpath` ломает trace** | Воспроизведение паники без исходных путей | Используйте `debug=trimpath=false` только для staging-сборок при расследовании падений. |
| **Race detector падает по OOM** | Недостаточно RAM для `-race` | Увеличьте `memory_limit` раннера до 4 ГБ или разделите race-тесты на отдельный job с увеличенными лимитами. |
| **`go test` паникает в CI, но не локально** | Отсутствуют переменные окружения или секреты | Используйте `--env` в конфигурации runner'а или `variables:` в job. Проверьте `go test -v` с локальными переменными. |
| **SBOM не генерируется** | Устаревший `syft` или неверный путь | Убедитесь, что `syft` установлен через `go install github.com/anchore/syft/cmd/syft@latest`. Проверьте путь к бинарному файлу. |
| **Pipeline зависает на `git clone`** | Large repo или нехватка диска на runner'е | Используйте `GIT_STRATEGY: fetch` и `GIT_DEPTH: 1` для поверхностного клонирования. Увеличьте диск runner'а до 50 ГБ. |
| **`govulncheck` слишком медленный** | Большой граф зависимостей | Запускайте `govulncheck` только при изменении `go.mod` через `rules:changes`. Используйте кэш: `GOCACHE`. |
| **Image pull backoff в K8s** | Неверный tag или нет доступа к Registry | Проверьте `image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}`. Убедитесь, что `imagePullSecret` настроен. |
| **`interruptible: true` не отменяет job** | Job уже запущен на runner'е | `interruptible` работает только на уровне планирования. Убедитесь, что runner'ы поддерживают отмену через API. |

### Инцидент-респонс для пайплайнов

При падении production-деплоя или критической уязвимости:

1.  **Остановка пайплайнов:** Переключите защищённую ветку в `Settings > Repository > Protected branches` и снимите флаг `Allowed to merge` на время расследования.
2.  **Откат образа:** Удалите проблемный тег через GitLab Registry API и выполните `kubectl rollout undo` в production namespace.
3.  **Аудит:** Проверьте, какой коммит и кто инициировал пайплайн: `git log --oneline $CI_COMMIT_SHA`. Проверьте audit log GitLab на предмет несанкционированных запусков.
4.  **Ротация секретов:** Если подозрение на утечку — отзовите `VAULT_TOKEN` и перегенерируйте секреты. Проверьте `vault token lookup` для compromised токенов.
5.  **Постмортем:** Зафиксируйте время инцидента, этап падения (`validate`/`test`/`deploy`), root cause и действия по исправлению. Обновите runbook.

## Лучшие практики (Best Practices)

**Безопасность:**
- Всегда запускайте `govulncheck ./...` в stage `validate` — это блокирует сборку при обнаружении известных CVE.
- Используйте `CGO_ENABLED=0` для статической линковки — исключает runtime-зависимости и снижает атакующую поверхность.
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
- Используйте structured logging (`log/slog` в Go 1.27+) для удобного парсинга в Kibana/Grafana.

**Жизненный цикл раннера (Runner Lifecycle):**
- Ротируйте `glrt-` токены раннеров каждые 90 дней. Устаревшие registration tokens отключены в GitLab 17.0+ и удалены в 20.0.
- Настройте `concurrent` и `limit` в `config.toml` для предотвращения перегрузки раннеров.
- Используйте `check_interval = 3` для быстрого подхвата задач, но не меньше 2 секунд чтобы не создавать лишнюю нагрузку на GitLab API.
- При обновлении раннера используйте rolling update: остановите приём новых задач, дождитесь завершения текущих, обновите бинарник, проверьте `gitlab-runner verify`, запустите.

**Сеть и изоляция:**
- Настройте NetworkPolicy для namespace `gitlab-runners`, разрешающую только egress к GitLab API, Container Registry и Vault.
- Используйте отдельный ServiceAccount для runner'ов с минимальными привилегиями. Не используйте `default` SA.
- Для Kubernetes Executor включите `pod_annotations` для отслеживания владельца job в Kubernetes.

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
- Если 필요ен `CGO_ENABLED=1` (например, для SQLite), используйте `golang:1.27-bookworm` вместо Alpine.
- В runtime добавьте `libc6` в образ: `FROM debian:bookworm-slim`.

**Высокая нагрузка в CI (>100 коммитов/день):**
- Используйте `rules:workflow` для дедупликации пайплайнов.
- Настройте `interruptible: true` для MR — это отменяет предыдущие запуски.
- Используйте distributed cache (S3/MinIO) вместо локального кэша раннера.

**Интеграция с ArgoCD:**
- Пайплайн CI только собирает образ и обновляет его версию в GitOps-репозитории.
- ArgoCD синхронизирует состояние кластера через Pull-модель.
- См. **[Обзор ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

**Disaster Recovery (DR):**
- Поддерживайте SLA на восстановление пайплайнов: RTO < 15 минут, RPO < 5 минут.
- Храните `config.toml` и `glrt-` токены раннеров в защищённом хранилище (HashiCorp Vault или аналоги) для быстрого восстановления.
- Регулярно тестируйте откат на предыдущий стабильный образ в staging-среде.

**Compliance и аудит:**
- Включите audit log в GitLab (`/var/log/gitlab/audit/`) для отслеживания всех запусков пайплайнов в production.
- Настройте retention для артефактов CI: `90 дней` для SBOM, `30 дней` для бинарных файлов.
- Регулярно проверяйте `bound_claims` и политики Vault (если используется OIDC) — удаляйте неиспользуемые роли.

**Сеть и DNS:**
- Используйте внутренний DNS (CoreDNS) для разрешения `gitlab.example.com` и `vault.example.com` внутри кластера.
- Настройте NetworkPolicy для namespace `gitlab-runners`, разрешающую только необходимые порты (443 для GitLab API, 5000 для Registry).
- Проверяйте egress-правила: runner'ы должны иметь доступ к GitLab API, Container Registry и Vault API.

**Гонки и детерминированность:**
- Для воспроизводимых сборок используйте `SOURCE_DATE_EPOCH` и `-trimpath`.
- Запускайте `go mod verify` в CI для проверки целостности `go.sum`.
- Используйте pinned версии базовых образов по дайджесту (`golang:1.27.1-alpine@sha256:...`) вместо тегов.

## Дополнительная информация

### GitOps и ArgoCD
Для крупных инсталляций рекомендуется переход на Pull-модель. Пайплайн CI в этом случае только собирает образ и обновляет его версию в отдельном Git-репозитории конфигураций, а **ArgoCD** синхронизирует состояние кластера. См. **[Обзор ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

### Безопасность (Supply Chain)
Генерация SBOM позволяет построить прозрачный граф зависимостей. Это фундамент для интеграции с инструментами анализа уязвимостей, такими как **Dependency Track** или **Trivy**.

### SRE: Наблюдаемость пайплайнов
- **Собитие:** Используйте GitLab CI/CD observability features для экспорта метрик в Prometheus.
- **Трейсинг:** Для investigation медленных пайплайнов используйте встроенную timeline view в GitLab UI.
- **Golden Signals:** Мониторьте latency, throughput, error rate и saturation для каждого stage пайплайна.

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — архитектура и синтаксис.
- **[Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — безопасная сборка без привилегий.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка Агентов.
- **[Dockerfile для Go: лучшие практики](../../../Docker/Dockerfile/Docker_best_practices/go.md)** — multi-stage builds, CGO, дистрибутивы, оптимизация.
- **[Целостность сборки](../../../Security/Supply_Chain_Security/build_integrity.md)** — SLSA, Provenance, аттестации.
- **[Кэширование в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)** — стратегии кэширования для Go.
- **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — архитектура, executor'ы, безопасность.
- **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — пошаговая регистрация и最佳практики.
- **[Официальная документация: Go в GitLab](https://docs.gitlab.com/ee/ci/examples/)**

