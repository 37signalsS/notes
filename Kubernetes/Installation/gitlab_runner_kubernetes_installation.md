# Установка GitLab Runner в Kubernetes

**Актуально для:** GitLab Runner 17.x–19.x, Helm chart gitlab/gitlab-runner 0.63.x, Kubernetes 1.28–1.31

Руководство по развертыванию, масштабированию и оптимизации GitLab Runner в кластере Kubernetes при помощи официального Helm-чарта.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **GitLab Runner** | Агент (приложение на Go), выполняющий задачи CI/CD пайплайнов. Опрашивает GitLab по протоколу Pull (Poll), не требует входящего доступа извне. |
| **Kubernetes Executor** | Исполнитель, который для каждой задачи создает отдельный под (Pod) в кластере. Каждый под содержит pause-контейнер (сеть), helper-контейнер (управление) и контейнер задачи (job). |
| **Authentication Token** | Токен нового образца (префикс `glrt-`), заменяющий устаревшие `Registration Tokens`. Создается в UI GitLab 16.0+ (Settings → CI/CD → Runners → New instance runner). |
| **Concurrent** | Глобальный параметр (`concurrent` в `config.toml`), определяющий максимальное количество одновременно запущенных задач на один инстанс раннера. |
| **Check Interval** | Интервал (в секундах), с которым раннер опрашивает GitLab на наличие новых задач (`check_interval` в `config.toml`). По умолчанию: 3 секунды. |
| **Distributed Cache** | Механизм хранения кэша заданий во внешнем объектном хранилище (S3, MinIO, GCS) для доступа из разных подов на разных узлах. |
| **Helper Image** | Специальный образ (`gitlab/gitlab-runner-helper`), подготавливающий окружение задачи: загружает артефакты/кэш, клонирует репозиторий, загружает скрипты из GitLab. Синхронизирован с версией Runner. |
| **ServiceAccount** | Учётная запись Kubernetes, от имени которой Runner создаёт поды задач. Должна иметь права на создание/удаление подов, secrets и configmaps в namespace раннера. |
| **RBAC (Role-Based Access Control)** | Модель разрешений в Kubernetes. Runner требует Role/ClusterRole с правами на поды, секреты, configmaps и events в namespace раннера. |
| **Namespace Isolation** | Выделение отдельного пространства имён для Runner и его рабочих подов. Рекомендуется для изоляции CI/CD от production-компонентов GitLab. |
| **Pod Security Context** | Конфигурация безопасности подов задач: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`. Снижает поверхность атаки. |
| **Allowed Images** | Список образов, разрешённых для использования в задачах (`allowed_images` в `config.toml`). Предотвращает запуск произвольных/вредоносных образов. |
| **Session Server** | Компонент Runner, обеспечивающий интерактивный доступ к логам задач в реальном времени через веб-интерфейс GitLab. Настраивается через `[session_server]` в `config.toml`. |
| **Trace (Трассировка)** | Механизм отправки логов выполнения задачи из пода задачи обратно в GitLab в реальном времени. Кэшируется локально при сетевых сбоях и дозаправляется. |
| **Log Limit** | Максимальный размер лога задачи (в байтах), после которого логи обрезаются. Настраивается через `log_limit` в `config.toml` или `Runner.maximum_artifact_size`. |
| **Debug Mode** | Режим отладки Runner (`[session_server]` с `debug` + `GITLAB_TRACE`). Позволяет включить детальное логирование для устранения проблем. |
| **Deprecated Registration Token** | Устаревший метод регистрации Runner через `registration_tokens` (префикс `GR1348941`). Заменён на `authentication_token` (префикс `glrt-`) в GitLab 16.0+. |
| **External Secrets Operator (ESO)** | Kubernetes-оператор для синхронизации секретов из внешних хранилищ (Vault, AWS Secrets Manager) в нативные Kubernetes Secrets. Используется для безопасной доставки токена регистрации Runner. |
| **Flux HelmRelease** | Flux CD CRD (`helm.toolkit.fluxcd.io/v2`) для декларативного управления жизненным циклом Helm-чартов через GitOps. |
| **GitOps** | Модель управления инфраструктурой, где желаемое состояние кластера декларируется в Git, а контроллеры (Flux, ArgoCD) обеспечивают его непрерывное применение. |

---

## Основные концепции

### Преимущества Kubernetes Executor

Использование Kubernetes в качестве среды выполнения обеспечивает:
- **Автомасштабирование:** Ресурсы потребляются только во время выполнения задач.
- **Изоляция:** Каждая задача запускается в "чистом" контейнере, что исключает конфликты зависимостей.
- **Гибкость:** Возможность динамически назначать `requests/limits`, `nodeSelector` и `tolerations` для разных типов задач.
- **Ephemeral-модель:** Поды задач не хранят состояние и автоматически удаляются после завершения, что упрощает управление и предотвращает утечки ресурсов.
- **Ресурсная эффективность:** Кластер не требует выделенных серверов-раннеров; ресурсы переиспользуются совместно с другими workload'ами.

### Архитектура Runner: Manager vs Executor

```
┌─────────────────────────────────────────────────────┐
│                   GitLab Server                     │
│  (API: Poll, Schedule, Upload)                      │
└───────────────┬─────────────────────────────────────┘
                │ HTTPS (Pull-модель)
                ▼
┌─────────────────────────────────────────────────────┐
│              GitLab Runner Manager                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ Poll Worker │  │ Config Store │  │ Cache Mgr │  │
│  │ (3s poll)   │  │ (config.toml)│  │ (S3/MinIO)│  │
│  └─────────────┘  └──────────────┘  └───────────┘  │
└───────────────┬─────────────────────────────────────┘
                │ Kubernetes API
                ▼
┌─────────────────────────────────────────────────────┐
│                   Pod задачи (Job)                  │
│  ┌──────────┐  ┌────────────┐  ┌────────────────┐  │
│  │  pause   │  │   helper   │  │   job script   │  │
│  │ (network)│  │ (setup/    │  │   (your CI)    │  │
│  │          │  │  teardown) │  │                │  │
│  └──────────┘  └────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**Manager** — процесс, запущенный как Deployment в кластере. Отвечает за:
- Опрос GitLab API на наличие задач (`poll`)
- Создание/удаление подов через Kubernetes API
- Управление кэшем и артефактами
- Отправку логов обратно в GitLab (trace)

**Executor** — логический компонент, определяющий среду выполнения. При Kubernetes executor каждый job получает:
- **Pause-контейнер** — удерживает сетевой namespace (shared IP)
- **Helper-контейнер** — загружает скрипты, артефакты, кэш; управляет lifecycle
- **Job-контейнер** — выполняет шаги `script` из `.gitlab-ci.yml`

### Жизненный цикл пода задачи

```
1. Poll → Runner получает задачу из GitLab API
2. Create Pod → Kubernetes API создаёт pod с тремя контейнерами
3. Init Phase:
   a. Pause-контейнер запускается первым (сеть)
   b. Helper-контейнер загружает скрипты и артефакты
   c. Helper клонирует репозиторий (если git checkout)
4. Execute Phase:
   a. Job-контейнер выполняет шаги из script
   b. Логи стримятся через trace в GitLab
5. After Script:
   a. after_script выполняется (cleanup, артефакты)
6. Cleanup:
   a. Helper загружает артефакты и кэш
   b. Под удаляется
7. Upload → Результаты и логи доступны в UI GitLab
```

### Взаимодействие компонентов

1.  **Poll:** Раннер опрашивает GitLab по HTTPS (порт 443).
2.  **Schedule:** При получении задачи раннер через Kubernetes API создает под.
3.  **Execute:** Под выполняет шаги `script`, используя указанные образы.
4.  **Upload:** Результаты и кэш отправляются обратно в GitLab или во внешнее хранилище.

### Конфигурация Runner: config.toml

Файл `/etc/gitlab-runner/config.toml` — основной источник конфигурации. При Helm-установке параметры передаются через `values.yaml` → `runners.config`.

```toml
concurrent = 10              # Глобальный лимит задач на весь раннер
check_interval = 3           # Интервал опроса GitLab API (сек)

[session_server]
  listen_address = "[::]:8093"   # Для интерактивных логов
  advertise_address = "runner.example.com:8093"

[[runners]]
  name = "kubernetes-runner"
  url = "https://gitlab.example.com"
  token = "glrt-..."
  executor = "kubernetes"

  [runners.kubernetes]
    namespace = "gitlab-runner"
    image = "alpine:latest"
    helper_image = "gitlab/gitlab-runner-helper:x86_64-v17.0.0"
    poll_timeout = 600

    [runners.kubernetes.resources]
      [runners.kubernetes.resources.requests]
        cpu = "500m"
        memory = "1Gi"
      [runners.kubernetes.resources.limits]
        cpu = "2"
        memory = "4Gi"

    [[runners.kubernetes.volumes.pvc]]
      name = "cache-vol"
      mount_path = "/cache"
      read_only = false
```

### RBAC и ServiceAccount

Для работы Kubernetes executor необходим ServiceAccount с правами:

```yaml
# rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: gitlab-runner-sa
  namespace: gitlab-runner
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: gitlab-runner-role
  namespace: gitlab-runner
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "secrets", "configmaps"]
    verbs: ["get", "list", "watch", "create", "delete", "update", "patch"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gitlab-runner-binding
  namespace: gitlab-runner
subjects:
  - kind: ServiceAccount
    name: gitlab-runner-sa
    namespace: gitlab-runner
roleRef:
  kind: Role
  name: gitlab-runner-role
  apiGroup: rbac.authorization.k8s.io
```

> **Примечание:** При использовании Helm-чарта `gitlab-runner` ServiceAccount и RBAC создаются автоматически при `rbac.create=true`.

### Безопасность подов задач

Для production-сред рекомендуется настраивать Pod Security Context:

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "alpine:latest"
        [runners.kubernetes.pod_security_context]
          run_as_non_root = true
          run_as_user = 1000
          run_as_group = 1000
          fs_group = 1000
        [runners.kubernetes.container_security_context]
          allow_privilege_escalation = false
          read_only_root_filesystem = false
          capabilities_drop = ["ALL"]
```

### Allowed Images и Services

Ограничение списка разрешённых образов предотвращает запуск произвольного/вредоносного ПО:

```toml
[runners.kubernetes]
  allowed_images = ["my-registry.com/ci/*", "alpine:3.*", "python:3.12-*"]
  allowed_services = ["postgres:15-alpine", "redis:7-alpine"]
```

### Session Server и интерактивные логи

Session Server позволяет просматривать логи задач в реальном времени через UI GitLab:

```toml
[session_server]
  listen_address = "[::]:8093"
  advertise_address = "runner.example.com:8093"
  advertise_port = 8093
  session_timeout = 1800  # Тайм-аут сессии (сек)
```

> **Важно:** Если Session Server не настроен, логи будут доступны только после завершения задачи (без стриминга).

### Deprecated Registration Token vs Authentication Token

| Параметр | Registration Token (устаревший) | Authentication Token (актуальный) |
| :--- | :--- | :--- |
| **Префикс** | `GR1348941...` | `glrt-...` |
| **GitLab версия** | < 16.0 | ≥ 16.0 (рекомендуется) |
| **Механизм** | Одноразовый токен при регистрации | Постоянный токен, привязанный к раннеру |
| **UI** | Settings → CI/CD → Runners → Вставить токен | Settings → CI/CD → Runners → New instance runner |
| **Безопасность** | Токен может быть скомпрометирован | Токен привязан к конкретному раннеру, легче ротировать |

---

## Практические сценарии

### 1. Стандартная установка через Helm

Рекомендуется использовать отдельный `namespace` для раннера и его рабочих подов.

```bash
# Добавление репозитория
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Установка с минимальными параметрами
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  --create-namespace \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerToken="glrt-YOUR_AUTHENTICATION_TOKEN" \
  --set rbac.create=true
```

### 1а. Деплой через Flux HelmRelease (GitOps)

Для GitOps-управления Runner'ом используется Flux CD с `HelmRelease` CRD. Это обеспечивает декларативное управление, автоматический откат при сбоях и защиту от дрейфа конфигурации.

**HelmRelease манифест:**

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: gitlab-runner
  namespace: gitlab-runner
spec:
  chart:
    spec:
      chart: gitlab-runner
      version: "0.63.*"
      sourceRef:
        kind: HelmRepository
        name: gitlab
        namespace: flux-system
  values:
    gitlabUrl: "https://gitlab.example.com"
    runnerRegistrationToken: "${RUNNER_TOKEN}"
    concurrent: 10
    rbac:
      create: true
      clusterWideAccess: false
    runners:
      tags: "k8s,dev"
      locked: false
      config: |
        [[runners]]
          [runners.kubernetes]
            namespace = "gitlab-runner"
            image = "alpine:3.19"
            privileged = true
            [[runners.kubernetes.volumes.empty_dir]]
              name = "docker-certs"
              mount_path = "/certs/client"
              medium = "Memory"
```

> **Примечание:** `privileged: true` обязателен для Docker-in-Docker. В окружениях, где DinD не нужен, ставьте `privileged: false` и используйте Kaniko или Buildah.

`concurrent: 10` — максимум параллельных джоб на все поды раннера. Если джобы встают в очередь, увеличьте значение — и заодно добавьте ресурсов узлам.

### 1б. Токен регистрации через External Secrets Operator (ESO)

Никогда не вставляйте токен регистрации в values-файл или CI-переменные открытым текстом. Используйте ESO для синхронизации токена из Vault (или другого внешнего хранилища) в Kubernetes Secret, на который ссылается HelmRelease.

**ExternalSecret для GitLab Runner токена:**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: gitlab-runner-token
  namespace: gitlab-runner
spec:
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: gitlab-runner-secret
    template:
      data:
        runner-registration-token: "{{ .token }}"
  data:
    - secretKey: token
      remoteRef:
        key: infra/gitlab-runner
        property: registration_token
```

Затем ссылаемся на этот Secret в HelmRelease:

```yaml
values:
  existingRunnerSecret: gitlab-runner-secret
```

### 2. Настройка распределенного кэширования (S3/MinIO)

Без внешнего кэша данные между запусками на разных узлах будут теряться.

**Конфигурация кэша на уровне Runner (values.yaml / config.toml):**

```toml
[[runners]]
  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.infra.svc.cluster.local:9000"
      BucketName = "gitlab-runner-cache"
      Insecure = true
```

*Примечание: Секреты (AccessKey/SecretKey) рекомендуется прокидывать через существующий Kubernetes Secret (`runners.cache.secretName`).*

**Конфигурация кэша в .gitlab-ci.yml (на уровне пайплайна):**

```yaml
cache:
  key: ${CI_COMMIT_REF_SLUG}
  paths:
    - .npm/
    - vendor/
```

> **Важно:** Без кэша каждая CI-джоба заново скачивает все зависимости. С S3-кэшем повторные джобы выполняются в 3–5 раз быстрее.

### 3. Оптимизация стоимости (Spot-инстанции)

Для экономии средств задачи CI/CD можно запускать на Spot-узлах (AWS) или Preemptible-узлах (GCP/Yandex).

**Настройка через values.yaml:**

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        [runners.kubernetes.node_selector]
          "node-role.kubernetes.io/ci-worker" = "true"
        [[runners.kubernetes.tolerations]]
          key = "spot-instance"
          operator = "Exists"
          effect = "NoSchedule"
```

### 4. Безопасность и привилегии

По умолчанию раннер запускается с минимальными правами. Если требуется сборка Docker-образов, используйте **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)** вместо привилегированного режима (DinD).

**Ограничение ресурсов для задач (подробная конфигурация):**

```toml
[[runners]]
  [runners.kubernetes]
    [runners.kubernetes.pod_annotations]
      "cluster-autoscaler.kubernetes.io/safe-to-evict" = "false"
    [runners.kubernetes.build_container_resources]
      [runners.kubernetes.build_container_resources.requests]
        cpu = "500m"
        memory = "512Mi"
      [runners.kubernetes.build_container_resources.limits]
        cpu = "2"
        memory = "2Gi"
    [runners.kubernetes.helper_container_resources]
      [runners.kubernetes.helper_container_resources.requests]
        cpu = "100m"
        memory = "128Mi"
      [runners.kubernetes.helper_container_resources.limits]
        cpu = "500m"
        memory = "256Mi"
```

**Пояснения:**
- `build_container_resources` — лимиты для основного контейнера задачи (где выполняется `script`)
- `helper_container_resources` — лимиты для helper-контейнера (клонирование, кэш, артефакты)
- `Requests` без `limits` приводят к OOM kill. Слишком низкие `limits` замедляют сборки. `cpu: "2"` — разумный потолок для docker build.
- `safe-to-evict: "false"` не даёт cluster autoscaler вытеснять поды с активными джобами при уменьшении числа узлов.

**Упрощённая конфигурация (общие лимиты):**

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        cpu_requests = "500m"
        memory_requests = "1Gi"
        cpu_limit = "2"
        memory_limit = "4Gi"
```

### 4а. Docker-in-Docker (DinD) с TLS

Для сборки Docker-образов внутри Kubernetes executor требуется DinD. Рекомендуется использовать mutual TLS через общий том `emptyDir` для сертификатов.

**Конфигурация в values.yaml (Helm) или config.toml:**

```toml
[[runners]]
  [runners.kubernetes]
    namespace = "gitlab-runner"
    image = "alpine:3.19"
    privileged = true
    [[runners.kubernetes.volumes.empty_dir]]
      name = "docker-certs"
      mount_path = "/certs/client"
      medium = "Memory"
```

**Настройка в .gitlab-ci.yml:**

```yaml
# .gitlab-ci.yml
build:
  image: docker:24
  services:
    - name: docker:24-dind
      alias: docker
  variables:
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_CERTDIR: /certs
    DOCKER_TLS_VERIFY: 1
    DOCKER_CERT_PATH: /certs/client
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

Том `docker-certs` типа `emptyDir` общий для сервиса `dind` и build-контейнера — это обеспечивает mutual TLS без `--privileged` на сервисном контейнере.

### 4б. Альтернативы Docker-in-Docker

| Инструмент | Privileged | Скорость | Примечание |
| :--- | :--- | :--- | :--- |
| **Docker-in-Docker** | Да | Быстро | Требует `privileged: true`, полный доступ к ядру хоста |
| **Kaniko** | Нет | Средне | Сборка в userspace без Docker-демона, медленнее но безопаснее |
| **Buildah** | Нет | Средне | Rootless сборка, работает без демона, хорошо для OCI-образов |

> **Рекомендация:** Начинайте с **Kaniko**. В большинстве случаев он покрывает все потребности и избавляет от проблем с безопасностью. Если столкнетесь с несовместимостью — переключайтесь на **Buildah** или настраивайте **DinD** на выделенных узлах с `privileged: true`.

### 5. ImagePullSecrets для приватных реестров

Для загрузки образов из приватных реестров (Harbor, ECR, GCR) необходимо настроить `imagePullSecrets`:

```bash
# Создание секрета
kubectl create secret docker-registry gitlab-runner-pull-secret \
  --docker-server=harbor.example.com \
  --docker-username=robot_ci \
  --docker-password=<password> \
  -n gitlab-runner
```

```yaml
# values.yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image_pull_secrets = ["gitlab-runner-pull-secret"]
```

### 6. Namespace Isolation для задач

Выделение отдельного namespace для рабочих подов предотвращает конфликты и упрощает RBAC:

```yaml
# values.yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        namespace = "gitlab-ci-jobs"
        namespace_over_request_disable = false
```

```bash
# Создание namespace и ServiceAccount
kubectl create namespace gitlab-ci-jobs
kubectl create serviceaccount gitlab-runner-jobs -n gitlab-ci-jobs

# RBAC для подов задач
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-jobs-role
  namespace: gitlab-ci-jobs
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
EOF
```

### 7. Allowed Images (ограничение образов)

Для безопасности в production необходимо ограничить список разрешённых образов:

```yaml
# values.yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "alpine:3.19"
        allowed_images = ["alpine:3.*", "python:3.12-*", "node:20-*", "my-registry.com/ci/*"]
        allowed_services = ["postgres:15-alpine", "redis:7-alpine", "mysql:8.0"]
```

### 8. Session Server для интерактивных логов

Настройка Session Server позволяет просматривать логи задач в реальном времени:

```yaml
# values.yaml
runners:
  config: |
    concurrent = 10
    check_interval = 3

    [session_server]
      listen_address = "[::]:8093"
      advertise_address = "runner.example.com:8093"
      advertise_port = 8093
      session_timeout = 1800

    [[runners]]
      name = "kubernetes-runner"
      url = "https://gitlab.example.com"
      executor = "kubernetes"
```

> **Важно:** Port 8093 должен быть доступен извне (Ingress/NodePort) для доступа к логам.

### 9. Debug Mode и Trace

Включение отладки для устранения проблем с Runner:

```yaml
# values.yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "alpine:latest"
        [runners.kubernetes.pod_security_context]
          run_as_non_root = true
```

```bash
# Включение debug-режима через переменные окружения
kubectl set env deployment/gitlab-runner \
  -n gitlab-runner \
  RUNNER_DEBUG=1 \
  GITLAB_TRACE=1
```

### 10. Multiple Runners (несколько раннеров)

Для разных типов задач (build, test, deploy) можно запустить несколько раннеров:

```yaml
# values.yaml — несколько раннеров
runners:
  - name: "build-runner"
    tags: ["build", "docker"]
    runUntagged: false
    config: |
      [[runners]]
        [runners.kubernetes]
          image = "docker:24-dind"
          [runners.kubernetes.resources.limits]
            cpu = "4"
            memory = "8Gi"

  - name: "test-runner"
    tags: ["test", "python"]
    runUntagged: false
    config: |
      [[runners]]
        [runners.kubernetes]
          image = "python:3.12"
          [runners.kubernetes.resources.limits]
            cpu = "2"
            memory = "4Gi"

  - name: "deploy-runner"
    tags: ["deploy"]
    runUntagged: false
    config: |
      [[runners]]
        [runners.kubernetes]
          image = "bitnami/kubectl:latest"
          [runners.kubernetes.resources.limits]
            cpu = "500m"
            memory = "512Mi"
```

### 11. Resource Quotas для namespace

Ограничение суммарных ресурсов CI/CD в namespace предотвращает исчерпание ресурсов кластера:

```yaml
# resource-quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: gitlab-runner-quota
  namespace: gitlab-runner
spec:
  hard:
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "40"
    limits.memory: "80Gi"
    pods: "50"
    persistentvolumeclaims: "10"
```

### 12. Network Policy для изоляции CI/CD

Ограничение сетевого трафика подов задач:

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gitlab-ci-network-policy
  namespace: gitlab-ci-jobs
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: gitlab-runner
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: gitlab-runner
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 443    # HTTPS (GitLab, registry)
        - port: 80     # HTTP
        - port: 53     # DNS
```

### 13. Upgrading Runner

Обновление Runner через Helm без простоя:

```bash
# Просмотр текущей версии
helm list -n gitlab-runner

# Обновление релиза
helm upgrade gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  --reuse-values \
  --set runnerToken="glrt-NEW_TOKEN" \
  --wait --timeout 300s

# Проверка после обновления
kubectl rollout status deployment/gitlab-runner -n gitlab-runner
kubectl get pods -n gitlab-runner
```

### 14. Клонирование репозитория с подменой URL

Для работы с GitLab через Internal DNS или GitLab Agent (KAS) может потребоваться подмена URL:

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        # Подмена URL для внутреннего доступа
        [runners.kubernetes.volumes.host_path]
          name = "resolv"
          mount_path = "/etc/resolv.conf"
          read_only = true
          host_path = "/etc/resolv.conf"
```

### 15. Persisting Cache через PVC

Для хранения кэша между задачами на одном узле:

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "alpine:latest"
        [[runners.kubernetes.volumes.pvc]]
          name = "runner-cache"
          mount_path = "/cache"
          read_only = false
```

```bash
# Создание PVC для кэша
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: runner-cache
  namespace: gitlab-runner
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: standard
EOF
```

---

## Дополнительная информация

### Полезные команды для отладки

| Команда | Описание |
| :--- | :--- |
| `kubectl get pods -n gitlab-runner` | Статус подов Runner и задач |
| `kubectl describe pod <pod> -n gitlab-runner` | Детальная информация о поде (события, условия) |
| `kubectl logs -f deployment/gitlab-runner -n gitlab-runner` | Логи Runner в реальном времени |
| `kubectl logs <job-pod> -c helper -n gitlab-ci-jobs` | Логи helper-контейнера задачи |
| `kubectl logs <job-pod> -c build -n gitlab-ci-jobs` | Логи job-контейнера задачи |
| `kubectl top pods -n gitlab-runner` | Фактическое потребление ресурсов |
| `kubectl get events -n gitlab-runner --sort-by='.lastTimestamp'` | Хронология событий |
| `kubectl exec -it deployment/gitlab-runner -n gitlab-runner -- cat /etc/gitlab-runner/config.toml` | Просмотр конфигурации Runner |
| `helm status gitlab-runner -n gitlab-runner` | Статус Helm-релиза |
| `helm get values gitlab-runner -n gitlab-runner` | Текущие values релиза |
| `kubectl get pods -n gitlab-runner --field-selector=status.phase=Running` | Поды с активными джобами |
| `kubectl exec -n gitlab-runner <job-pod-name> -c build -- /bin/sh` | Зайти в под джобы (пока она работает) |
| `kubectl exec -n gitlab-runner deploy/gitlab-runner -- gitlab-runner list` | Список зарегистрированных раннеров |

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Под джобы завис в Pending** | Недостаточно ресурсов на узлах | Проверить `kubectl describe pod`, добавить узлы или уменьшить requests |
| **Docker socket not found** | Не задан `DOCKER_HOST=tcp://docker:2376`, используется unix-сокет | Убедиться, что в `.gitlab-ci.yml` задан `DOCKER_HOST: tcp://docker:2376` |
| **TLS handshake failed** | Том `docker-certs` не монтируется по одному пути в build- и dind-контейнерах | Проверить, что `emptyDir` том `docker-certs` смонтирован в оба контейнера по `/certs/client` |

### Диагностический скрипт (one-shot)

```bash
#!/bin/bash
# gitlab-runner-diagnose.sh — быстрая диагностика GitLab Runner в Kubernetes
NAMESPACE=${1:-gitlab-runner}

echo "=== Helm Release Status ==="
helm status gitlab-runner -n $NAMESPACE 2>/dev/null || echo "Release not found"

echo ""
echo "=== Runner Deployment ==="
kubectl get deployment -n $NAMESPACE -o wide

echo ""
echo "=== Runner Pods ==="
kubectl get pods -n $NAMESPACE -o wide

echo ""
echo "=== Runner Config ==="
kubectl exec -it deployment/gitlab-runner -n $NAMESPACE -- cat /etc/gitlab-runner/config.toml 2>/dev/null || echo "Cannot read config"

echo ""
echo "=== Runner Logs (last 30 lines) ==="
kubectl logs deployment/gitlab-runner -n $NAMESPACE --tail=30 2>/dev/null

echo ""
echo "=== CI Jobs Namespace ==="
kubectl get pods -n gitlab-ci-jobs 2>/dev/null || echo "Namespace gitlab-ci-jobs not found"

echo ""
echo "=== RBAC ==="
kubectl get serviceaccount -n $NAMESPACE
kubectl get rolebinding -n $NAMESPACE

echo ""
echo "=== Events (last 20) ==="
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | tail -20
```

### Runbook: инциденты по приоритетам

| Приоритет | Инцидент | Время отклика | Действия |
| :--- | :--- | :--- | :--- |
| **P1 (Critical)** | Runner недоступен, все пайплайны в очереди | 15 мин | Проверить Deployment, логи, конфигурацию. При необходимости — `helm rollback`. |
| **P1 (Critical)** | RBAC-ошибки (поды задач не создаются) | 15 мин | Проверить ServiceAccount, Role/RoleBinding, `kubectl auth can-i`. |
| **P2 (High)** | Кэш не работает, задачи выполняются дольше | 30 мин | Проверить S3/MinIO доступность, PVC, конфигурацию cache. |
| **P2 (High)** | Задачи падают с OOMKilled | 30 мин | Увеличить `memory_limit` в config.toml или limits в job spec. |
| **P3 (Medium)** | Медленное выполнение задач (latency) | 2 часа | Проверить ресурсы подов, network, storage IOPS. |
| **P3 (Medium)** | Runner не подключается к GitLab | 2 часа | Проверить `gitlabUrl`, токен, DNS, firewall. |
| **P4 (Low)** | Логи не стримятся (Session Server) | 4 часа | Проверить Session Server config, порт 8093, Ingress. |

### Эскалация (Escalation Matrix)

| Уровень | Условие | Действие |
| :--- | :--- | :--- |
| **L1 (Junior SRE)** | Типичные проблемы: Pending, OOM, конфигурация | Следовать данному runbook,搜集 логи |
| **L2 (Senior SRE)** | Не типичные проблемы, данные runbook не помогает | Глубокая диагностика, `kubectl debug`, проверка кластера |
| **L3 (Platform Team)** | Проблемы с Helm-чартом, баги, необходимость форка чарта | Обращение к GitLab Support, GitHub issue |
| **External (GitLab Support)** | Проблемы с лицензией, баги в GitLab Runner | Тикет в GitLab Support (https://support.gitlab.com) |

### Метрики для мониторинга (alerting rules)

```yaml
# gitlab-runner-alerts.yaml
groups:
  - name: gitlab-runner-health
    rules:
      - alert: GitLabRunnerDown
        expr: up{job="gitlab-runner"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GitLab Runner is down"

      - alert: GitLabRunnerHighQueueSize
        expr: gitlab_runner_queue_size > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Runner queue size > 100"

      - alert: GitLabRunnerJobDurationHigh
        expr: histogram_quantile(0.95, rate(gitlab_runner_job_duration_seconds_bucket[5m])) > 600
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Runner p95 job duration > 10 minutes"

      - alert: GitLabRunnerPodsNotReady
        expr: kube_pod_status_ready{namespace="gitlab-runner"} == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Runner pod not ready"

      - alert: GitLabRunnerJobsFailed
        expr: increase(gitlab_runner_jobs_failed_total[1h]) > 10
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Runner: >10 jobs failed in 1 hour"
```

### Часто задаваемые вопросы

**Q: Как получить доступ к поду задачи для отладки?**
```bash
# Интерактивный shell (если под ещё жив)
kubectl exec -it <job-pod> -c build -n gitlab-ci-jobs -- /bin/sh

# Или через ephemeral debug container (Kubernetes 1.23+)
kubectl debug -it <job-pod> -n gitlab-ci-jobs --image=busybox --target=build
```

**Q: Как посмотреть логи предыдущего запуска (если под упал)?**
```bash
kubectl logs <job-pod> -c build -n gitlab-ci-jobs --previous
```

**Q: Как перезапустить Runner без простоя?**
```bash
kubectl rollout restart deployment/gitlab-runner -n gitlab-runner
```

**Q: Как проверить, подключён ли Runner к GitLab?**
```bash
# Проверка логов на наличие "checking for jobs"
kubectl logs deployment/gitlab-runner -n gitlab-runner --tail=50 | grep -i "checking\|job"

# Или через API
curl -s -k -H "PRIVATE-TOKEN: <token>" https://gitlab.example.com/api/v4/runners | jq
```

**Q: Как ротировать токен Runner?**
```bash
# 1. Создайте новый токен в GitLab UI (Settings → CI/CD → Runners)
# 2. Обновите секрет
kubectl create secret generic gitlab-runner-secret \
  --from-literal=runner-token=glrt-NEW_TOKEN \
  -n gitlab-runner \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Перезапустите Runner
kubectl rollout restart deployment/gitlab-runner -n gitlab-runner
```

**Q: Как настроить Runner для работы с Harbor?**
```yaml
# values.yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image_pull_secrets = ["harbor-secret"]
        helper_image = "harbor.example.com/gitlab/gitlab-runner-helper:x86_64-v17.0.0"
```

**Q: Как ограничить количество одновременных задач?**
```toml
# config.toml
concurrent = 5  # Глобальный лимит
check_interval = 3

[[runners]]
  [runners.kubernetes]
    # Для конкретного раннера можно задать лимит через dynamic конфигурацию
```

**Q: Как проверить, что helper image доступен?**
```bash
# Проверка доступности образа
kubectl run test-helper --rm -it --image=gitlab/gitlab-runner-helper:x86_64-v17.0.0 -- echo "OK"

# Или через docker (на узле)
docker pull gitlab/gitlab-runner-helper:x86_64-v17.0.0
```

### См. также

- **[Обзор GitLab Runner и Executor](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)** — глубокая теория.
- **[Использование Docker-in-Docker](../../Docker/docker-in-docker.md)** — если Kaniko не подходит.
- **[Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)** — настройка Агента и CI/CD.
- **[Регистрация Runner](../../CI-CD/GitLab_CI/Tutorials/runner_registration.md)** — подробнее о токенах и UI.
- **[Flux CD: обзор и ключевые концепции](../../GitOps/flux.md)** — GitOps деплой через HelmRelease.
- **[External Secrets Operator (ESO)](../../Kubernetes/Base/secrets/external_managers.md)** — синхронизация секретов из Vault.
- **[Kaniko: сборка без Docker](../../Docker/Dockerfile/dockerfile_kaniko.md)** — безопасная альтернатива DinD.
