# Actions Runner Controller (ARC): Эфемерные раннеры в Kubernetes

**Актуально для:** GitHub-supported ARC — Helm-чарты `gha-runner-scale-set` и `gha-runner-scale-set-controller` v0.15.0, образ раннера `ghcr.io/actions/actions-runner` v2.337.x (октябрь 2026). Legacy-режим сообщества (CRD `RunnerDeployment`/`RunnerScaleSet`, API `actions.summerwind.net/v1alpha1`, чарт `actions-runner-controller` ≤ v0.25.2) — legacy, поддерживается только сообществом (discussion #2775).

Actions Runner Controller (ARC) — Kubernetes-оператор для оркестрации и автоскейлинга self-hosted раннеров GitHub Actions. ARC создаёт эфемерные поды с раннером: под регистрируется в GitHub Actions (через JIT-токен), выполняет одну задачу и автоматически удаляется. Это устраняет основную проблему классических self-hosted раннеров — накопление «грязного» состояния между задачами и постоянные security-риски.

Проект развивается совместно GitHub Actions team и сообществом (репозиторий `actions/actions-runner-controller`). GitHub поддерживает режим **autoscaling runner scale sets** — два Helm-чарта: оператор (`gha-runner-scale-set-controller`) и runner scale set (`gha-runner-scale-set`). Прежние autoscaling-режимы на CRD `RunnerDeployment`/`RunnerScaleSet` объявлены legacy и поддерживаются только сообществом. Переход на новый режим — существенное архитектурное изменение (не минорное обновление), тестируйте его в staging перед production.

## Определения

- **Actions Runner Controller (ARC)**: Kubernetes-оператор, развёртываемый парой Helm-чартов (OCI-пакеты). Чарты публикуются только в OCI-формате; Helm-репозиториев через GitHub Pages нет.
- **Runner Scale Set**: группа раннеров, которой управляет ARC. В текущей версии — Helm-релиз чарта `gha-runner-scale-set`; имя Helm-релиза (`INSTALLATION_NAME`) используется как значение `runs-on` в workflow.
- **AutoscalingRunnerSet** (`actions.github.com/v1alpha1`): верхнеуровневый CRD, создаваемый чартом `gha-runner-scale-set`. Controller-manager обращается к API GitHub, получает/создаёт runner scale set в Actions service и создаёт Listener.
- **Listener (ghalistener)**: под, который держит HTTPS long-poll соединение с GitHub Actions Service и ждёт сообщений `Job Available`. Получив сообщение, listener масштабирует EphemeralRunnerSet через Kubernetes API.
- **EphemeralRunnerSet / EphemeralRunner** (`actions.github.com/v1alpha1`): внутренние CRD. EphemeralRunner Controller запрашивает JIT-конфигурационный токен и создаёт pod раннера; при `failed` статусе pod повторяется до 5 раз; если за 24 часа ни один раннер не принял задачу, GitHub Actions Service снимает её с назначения.
- **Эфемерный раннер (Ephemeral Runner)**: раннер, удаляемый после выполнения одной задачи. Гарантирует чистую среду для каждой задачи, как GitHub-hosted.
- **JIT-регистрация (Just-In-Time)**: регистрация раннера с токеном, живущим ровно до первого job — минимизирует риск утечки регистрационного токена.
- **Runner Group**: группа раннеров с общими правилами доступа (org-level). Имя runner scale set уникально внутри своей runner group.
- **containerMode**: режим работы с контейнерами: `dind` (Docker-in-Docker), `kubernetes` (job/service-контейнеры в отдельных подах с PV) или `kubernetes-novolume` (без PV, через lifecycle hooks).
- **Legacy RunnerDeployment** (`actions.summerwind.net/v1alpha1`): устаревший CRD прежних autoscaling-режимов. См. раздел «Legacy-режим сообщества» ниже.

## Архитектура и компоненты

### Как работает autoscaling runner scale set

```text
GitHub Actions Service
    │ (1) workflow job с runs-on: <INSTALLATION_NAME>
    ▼
controller-manager pod (namespace arc-systems)
    │ (2) вызывает API GitHub: получает runner group ID,
    │     создаёт/находит runner scale set в Actions service
    ▼
AutoscalingRunnerSet (CRD) ──► Listener pod (long-poll к GitHub)
    │ (3) получив "Job Available", listener проверяет,
    │     может ли масштабироваться, и подтверждает сообщение
    │ (4) listener через ServiceAccount/Role патчит
    │     EphemeralRunnerSet с нужным числом реплик
    ▼
EphemeralRunnerSet ──► EphemeralRunner Controller
    │ (5) запрашивает JIT-токен, создаёт runner pod
    ▼
Runner pod (ephemeral) ── регистрируется по JIT-токену,
                          получает детали job, выполняет,
                          стримит логи/статус, удаляется
```

- **controller-manager**: управляет CRD `AutoscalingRunnerSet`, создаёт Listener и следит за ресурсами.
- **Listener**: единственный компонент, постоянно общающийся с GitHub Actions Service (long-poll). Масштабирует поды на основе назначенных задач, а не CPU/Memory.
- **Runner pod**: эфемерен — после выполнения job под удаляется. Образ раннера (`ghcr.io/actions/actions-runner`) минимален (runner binaries + container hooks + Docker для dind); дополнительное ПО ставится в кастомном образе или через `actions/setup-*`.

### Ресурсы, создаваемые чартами

Чарт `gha-runner-scale-set-controller` (namespace, например, `arc-systems`): Deployment и ServiceAccount `INSTALLATION_NAME-gha-rs-controller`, ClusterRole/Role (в зависимости от `flags.watchSingleNamespace`), Role для listener.

Чарт `gha-runner-scale-set` (namespace, например, `arc-runners`): `AutoscalingRunnerSet` с именем `INSTALLATION_NAME`, Secret с github-учётными данными (если `githubConfigSecret` — объект), Role/RoleBinding для manager, ServiceAccount `INSTALLATION_NAME-gha-rs-no-permission` (для runner-пода; в kubernetes-режиме вместо него — `INSTALLATION_NAME-gha-rs-kube-mode` с правами на создание подов).

Ограничения на имена: имя runner scale set (и `AutoscalingRunnerSet`) — до 45 символов; namespace — до 63 символов; генерируемые имена ресурсов — до 63 символов.

### runs-on и метки

```yaml
# workflow.yml — runs-on равен имени Helm-релиза runner scale set
jobs:
  build:
    runs-on: arc-runner-set
    steps:
      - uses: actions/checkout@v7
      - run: make build
```

Метки задаются в `values.yaml` ключом `scaleSetLabels` (чарт рендерит их в поле CRD `runnerScaleSetLabels`):

```yaml
scaleSetLabels:
  - linux
  - gpu
  - private-network
```

```yaml
# workflow.yml — выбор по меткам
jobs:
  build:
    runs-on: [linux, gpu, private-network]
```

## Практические сценарии

### Сценарий 1: Установка controller-manager

**Предварительные требования**: Kubernetes-кластер (локально — minikube или kind), `kubectl`, Helm 3. Рекомендуется настроить сбор и хранение логов controller, listener и эфемерных раннеров до запуска в production.

```bash
NAMESPACE="arc-systems"
helm install arc \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller
```

Установка конкретной версии — флаг `--version <VERSION>` (список релизов — в GitHub Container Registry, пакет `actions-runner-controller-charts/gha-runner-scale-set-controller`). Полный список опций — в [`values.yaml`](https://github.com/actions/actions-runner-controller/blob/master/charts/gha-runner-scale-set-controller/values.yaml).

**Валидация**:

```bash
kubectl get pods -n arc-systems
# → NAME                                            READY   STATUS    RESTARTS   AGE
# → arc-gha-runner-scale-set-controller-594cdc976f-m7cjs   1/1     Running   0          64s
```

### Сценарий 2: Деплой runner scale set (PAT)

**Предварительные требования**: установленный controller (Сценарий 1); PAT (classic) со scope `repo` (для repo-раннеров) или `admin:org` (для org-раннеров).

```bash
INSTALLATION_NAME="arc-runner-set"
NAMESPACE="arc-runners"
GITHUB_CONFIG_URL="https://github.com/<your_enterprise/org/repo>"
GITHUB_PAT="<PAT>"
helm install "${INSTALLATION_NAME}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    --set githubConfigUrl="${GITHUB_CONFIG_URL}" \
    --set githubConfigSecret.github_token="${GITHUB_PAT}" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

Параметры: `INSTALLATION_NAME` — имя Helm-релиза, оно же значение `runs-on`; `githubConfigUrl` — URL сущности (репозиторий, организация или enterprise), к которой привязываются раннеры; `githubConfigSecret.github_token` — PAT (classic).

Рекомендация (security best practice): передавать секреты через Kubernetes Secret, а не plain-text в CLI:

```bash
kubectl create secret generic arc-runner-set-secret \
  --namespace arc-runners \
  --from-literal=github_token='YOUR_PAT'
```

```yaml
# values.yaml
githubConfigUrl: "https://github.com/myorg/myrepo"
githubConfigSecret: arc-runner-set-secret   # имя существующего Secret в namespace arc-runners
```

**Валидация**:

```bash
helm list -A
# → NAME            NAMESPACE       REVISION   STATUS     CHART                              APP VERSION
# → arc             arc-systems     1          deployed   gha-runner-scale-set-controller-0.15.0   0.15.0
# → arc-runner-set  arc-runners     1          deployed   gha-runner-scale-set-0.15.0              0.15.0

kubectl get pods -n arc-runners
# → NAME                                READY   STATUS    RESTARTS   AGE
# → arc-runner-set-754b578d-listener    1/1     Running   0          12s
```

Запуск тестового workflow (см. раздел «runs-on и метки») и наблюдение за созданием раннеров:

```bash
kubectl get pods -n arc-runners -w
# → NAMESPACE     NAME                          READY   STATUS    RESTARTS   AGE
# → arc-runners   arc-runner-set-rmrgw-runner-p9p5n   1/1     Running   0          21s
```

### Сценарий 3: Аутентификация через GitHub App

Для repo- и org-level scale sets рекомендуется GitHub App вместо PAT. **Enterprise-level scale sets поддерживают только PAT (classic)** — GitHub App для них недоступна.

Настройка GitHub App (owned by organization):

- Repository permissions: **Administration: Read and write** (требуется только при регистрации в repo-scope; для org-scope не нужно), **Metadata: Read-only**.
- Organization permissions: **Self-hosted runners: Read and write**.
- Homepage URL: `https://github.com/actions/actions-runner-controller`.

Создание Secret и подключение:

```bash
kubectl create secret generic arc-app-secret \
  --namespace arc-runners \
  --from-literal=github_app_id='123456' \
  --from-literal=github_app_installation_id='654321' \
  --from-literal=github_app_private_key='-----BEGIN RSA PRIVATE KEY-----...'
```

```yaml
# values.yaml
githubConfigUrl: "https://github.com/myorg"
githubConfigSecret: arc-app-secret
```

Installation ID виден на странице установки App (URL вида `https://github.com/organizations/ORG/settings/installations/INSTALLATION_ID`). Альтернатива — передать значения прямо в `values.yaml` (`githubConfigSecret.github_app_id` / `.github_app_installation_id` / `.github_app_private_key`), но это хранит приватный ключ plain-text — используйте только для отладки.

### Сценарий 4: Fine-grained PAT

Требуемые permissions fine-grained PAT:

- **Repository runners**: Administration — Read and write.
- **Organization runners**: Administration — Read; Self-hosted runners — Read and write.

Secret создаётся как в Сценарии 2 (`--from-literal=github_token='...'`), затем `githubConfigSecret: <secret-name>`.

### Сценарий 5: Runner groups

Runner scale set можно привязать к существующей runner group (org-level), чтобы управлять доступом репозиториев к раннерам:

```yaml
# values.yaml
runnerGroup: "Octo-Group"
```

Имя runner scale set уникально внутри runner group: два scale set'а с одинаковым именем возможны только в разных runner groups.

### Сценарий 6: Масштабирование (minRunners / maxRunners)

ARC не поддерживает расписание для min/max — для по расписанию используйте внешний cron, обновляющий значения через `helm upgrade`.

```yaml
# values.yaml
maxRunners: 30   # потолок: до 30 раннеров
minRunners: 20   # минимум idle-раннеров; целевое число = minRunners + назначенные job'ы
```

- Целевое число раннеров = `minRunners` + число job'ов, назначенных scale set'у; после завершения job'ов scale down до `minRunners`.
- Если обе настройки закомментированы: масштабирование вверх до числа назначенных job'ов, scale down до 0.
- `minRunners` не может превышать `maxRunners` (чарт падает с ошибкой рендера), кроме случая, когда `maxRunners` не задан.
- **Queue draining**: `maxRunners: 0` + `minRunners: 0` — новые поды не создаются, даже если есть назначенные job'ы (полезно для обслуживания кластера).

Изменение лимитов — через `helm upgrade` с новыми значениями. Ручное масштабирование подов напрямую не предусмотрено: listener управляет репликами.

### Сценарий 7: Docker-in-Docker (containerMode: dind)

Для workflow с `services:` (PostgreSQL, Redis), container job'ами и Docker-actions:

```yaml
# values.yaml
containerMode:
  type: "dind"
```

ARC автоматически инжектирует в `template`: init-контейнер `init-dind-externals`, контейнер `dind` (образ `docker:dind`, `securityContext.privileged: true` — требуется для DinD) и runner-контейнер с `DOCKER_HOST=unix:///var/run/docker.sock`. На Kubernetes **≥ v1.29** Docker daemon запускается как native sidecar container; на более старых версиях — обычный sidecar в `containers`. Значения `template.spec`, генерируемые для dind, инжектируются автоматически и не переопределяются; для кастомизации — оставьте `containerMode` пустым и скопируйте нужный PodSpec в `template` вручную. Альтернатива `docker:dind-rootless` возможна с учётом [известных ограничений](https://docs.docker.com/engine/security/rootless/#known-limitations) и `--privileged`.

### Сценарий 8: Kubernetes mode (job/service-контейнеры в отдельных подах)

В kubernetes-режиме runner-container-hooks создают отдельный под в том же namespace для service-контейнера, container job или Docker-action:

```yaml
# values.yaml — вариант с persistent volume
containerMode:
  type: "kubernetes"
  kubernetesModeWorkVolumeClaim:
    accessModes: ["ReadWriteOnce"]
    storageClassName: "dynamic-blob-storage"
    resources:
      requests:
        storage: 1Gi
```

Вариант `kubernetes-novolume` (без PV, обмен файлами через lifecycle hooks):

```yaml
containerMode:
  type: "kubernetes-novolume"
```

Особенности:

- Для `kubernetes` нужны PV с автоматическим провижинингом (для тестов — OpenEBS).
- В kubernetes-режиме workflow без `container:` падает с ошибкой `Jobs without a job container are forbidden on this runner...`. Разрешить такие job'ы можно `ACTIONS_RUNNER_REQUIRE_JOB_CONTAINER: "false"` в env runner-контейнера — **это даёт runner-поду расширенные права на Kubernetes API (создание подов, доступ к секретам), по умолчанию не делайте этого**.
- Ошибка `Access to the path /home/runner/_work/_tool is denied` при PV и non-root пользователе — решается через `securityContext.fsGroup: 123` или init-контейнер с `chown` (см. раздел «Устранение неполадок»).

### Сценарий 9: Кастомный образ раннера

Требования к кастомному образу (по официальной документации):

- базовый образ, способный запускать self-hosted runner application;
- runner binary размещён под `/home/runner/` и запускается через `/home/runner/run.sh`;
- для kubernetes-режима runner container hooks размещены под `/home/runner/k8s`;
- контейнер в PodSpec должен называться `runner` — иначе он не будет сконфигурирован для подключения к GitHub.

Пример на базе официального Dockerfile:

```dockerfile
FROM mcr.microsoft.com/dotnet/runtime-deps:6.0 as build

# Значения замените на актуальные:
# RUNNER_VERSION: https://github.com/actions/runner/releases
ARG RUNNER_VERSION=""
ARG RUNNER_ARCH="x64"
# RUNNER_CONTAINER_HOOKS_VERSION: https://github.com/actions/runner-container-hooks/releases
ARG RUNNER_CONTAINER_HOOKS_VERSION=""

ENV DEBIAN_FRONTEND=noninteractive
ENV RUNNER_MANUALLY_TRAP_SIG=1
ENV ACTIONS_RUNNER_PRINT_LOG_TO_STDOUT=1

RUN apt update -y && apt install curl unzip -y

RUN adduser --disabled-password --gecos "" --uid 1001 runner \
    && groupadd docker --gid 123 \
    && usermod -aG sudo runner \
    && usermod -aG docker runner \
    && echo "%sudo ALL=(ALL:ALL) NOPASSWD:ALL" > /etc/sudoers \
    && echo "Defaults env_keep += \"DEBIAN_FRONTEND\"" >> /etc/sudoers

WORKDIR /home/runner

RUN curl -f -L -o runner.tar.gz https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz \
    && tar xzf ./runner.tar.gz \
    && rm runner.tar.gz

RUN curl -f -L -o runner-container-hooks.zip https://github.com/actions/runner-container-hooks/releases/download/v${RUNNER_CONTAINER_HOOKS_VERSION}/actions-runner-hooks-k8s-${RUNNER_CONTAINER_HOOKS_VERSION}.zip \
    && unzip ./runner-container-hooks.zip -d ./k8s \
    && rm runner-container-hooks.zip

USER runner
```

Сборка, публикация и подключение:

```bash
docker build -t ghcr.io/<ORG>/arc-runner-custom:2.337.0 .
docker push ghcr.io/<ORG>/arc-runner-custom:2.337.0
```

```yaml
# values.yaml
template:
  spec:
    containers:
      - name: runner
        image: ghcr.io/<ORG>/arc-runner-custom:2.337.0
        command: ["/home/runner/run.sh"]
```

Вместо кастомного образа для установки Java/Node и т.п. можно использовать `actions/setup-*` прямо в workflow — это исключает необходимость собирать образ.

### Сценарий 10: Приватный реестр и imagePullSecrets

Для работы из приватного реестра скопируйте controller- и runner-образы внутрь реестра и настройте ссылки:

```yaml
# values.yaml (gha-runner-scale-set)
template:
  spec:
    containers:
      - name: runner
        image: "custom-registry.io/actions-runner:2.337.0"
        imagePullPolicy: Always
        command: ["/home/runner/run.sh"]
    imagePullSecrets:
      - name: <registry-secret-name>
```

```bash
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=<GITHUB_USERNAME> \
  --docker-password=<FINE_GRAINED_PAT> \
  -n arc-runners
```

Для controller-образа настройте `image` и `imagePullSecrets` в `values.yaml` чарта `gha-runner-scale-set-controller`. Listener наследует `imagePullPolicy` controller'а.

### Сценарий 11: Кастомные TLS-сертификаты (CA)

Если GitHub Enterprise Server использует сертификат собственного CA, инжектируйте CA в trust store controller'а и раннеров:

```yaml
# values.yaml
githubServerTLS:
  certificateFrom:
    configMapKeyRef:
      name: config-map-name
      key: ca.crt
  runnerMountPath: /usr/local/share/ca-certificates/
```

Сертификат должен быть в PEM-формате с расширением `.crt` (иначе игнорируется). ARC создаёт volume `github-server-tls-cert`, монтирует его в `runnerMountPath/<имя_сертификата>`, выставляет `NODE_EXTRA_CA_CERTS` и `RUNNER_UPDATE_CA_CERTS=1` (с runner v2.303.0 — перезагрузка сертификатов на лету). Значения, заданные вами в runner PodSpec, ARC не перезаписывает. Не работает для образов, не основанных на Debian.

### Сценарий 12: Метрики (Prometheus)

ARC экспортирует метрики в Prometheus-формате из controller-manager и listener (доступны с gha-runner-scale-set v0.5.0). Включение — в `values.yaml` чарта `gha-runner-scale-set-controller`:

```yaml
metrics:
  controllerManagerAddr: ":8080"
  listenerAddr: ":8080"
  listenerEndpoint: "/metrics"
```

| Метрика | Тип | Смысл |
|---|---|---|
| `gha_controller_pending_ephemeral_runners` | gauge | эфемерных раннеров в pending |
| `gha_controller_running_ephemeral_runners` | gauge | эфемерных раннеров в running |
| `gha_controller_failed_ephemeral_runners` | gauge | эфемерных раннеров в failed |
| `gha_controller_running_listeners` | gauge | listener'ов в running |
| `gha_assigned_jobs` | gauge | job'ов, назначенных scale set'у |
| `gha_running_jobs` | gauge | job'ов в running/queued |
| `gha_registered_runners` | gauge | зарегистрированных раннеров |
| `gha_busy_runners` | gauge | раннеров, выполняющих job |
| `gha_idle_runners` | gauge | idle-раннеров |
| `gha_min_runners` / `gha_max_runners` | gauge | настроенные лимиты |
| `gha_desired_runners` | gauge | целевое число раннеров |
| `gha_started_jobs_total` / `gha_completed_jobs_total` | counter | стартовавших/завершённых job'ов (сбрасывается при рестарте listener'а) |
| `gha_job_startup_duration_seconds` | histogram | время ожидания старта job'а на раннере (queue time) |
| `gha_job_execution_duration_seconds` | histogram | время выполнения job'ов |

Метки по умолчанию: `name`, `namespace`, `repository`, `organization`, `enterprise`, `job_name`, `event_name` (и `job_result` для counter/histogram). Метки `job_workflow_ref`, `job_workflow_name`, `job_workflow_target` подключаются опционально через `listenerMetrics` — они создают новый time series на каждую ветку/PR, включайте только если metrics-backend выдерживает кардинальность.

### Сценарий 13: High availability (active-active)

При двух кластерах в разных регионах: установите ARC в обоих, используйте одинаковый `runnerScaleSetName`, но разные runner groups:

```yaml
# values.yaml (кластер A)
runnerScaleSetName: "arc-runner-set"
runnerGroup: "runner-group-A"
```

Job'ы распределяются между scale set'ами произвольно (assignment race), алгоритм не настраивается. При падении одного кластера второй продолжает принимать job'ы без изменений конфигурации.

### Сценарий 14: Vault (Azure Key Vault, public preview)

С gha-runner-scale-set v0.12.0 учётные данные можно брать из внешнего vault (пока — Azure Key Vault). Secret в Key Vault хранится в JSON: `{"github_token": "..."}` или `{"github_app_id": "...", "github_app_installation_id": "...", "github_app_private_key": "..."}`.

```yaml
# values.yaml
githubConfigSecret: "<имя секрета в vault>"
keyVault:
  type: "azure_key_vault"
  azureKeyVault:
    clientId: <AZURE_CLIENT_ID>
    tenantId: <AZURE_TENANT_ID>
    url: <AZURE_VAULT_URL>
    certificatePath: "/akv/cert.pfx"
```

`.pfx`-сертификат должен быть доступен и controller'у, и listener'у (пересобранный образ или mount volume через `controllerManager` / `listenerTemplate`).

### Сценарий 15: Обновление ARC

Helm не поддерживает upgrade/delete CRD, поэтому обновление — переустановка:

1. Удалите все установки `gha-runner-scale-set`.
2. Дождитесь очистки ресурсов.
3. Удалите ARC (`gha-runner-scale-set-controller`).
4. Если в новой версии изменились CRD API-группы `actions.github.com` — удалите эти CRD.
5. Установите ARC заново (Сценарии 1–2).

Тестирование обновления без даунтайма — через HA-конфигурацию (Сценарий 13). Для оценки новых функций существуют canary-образы с тегом `canary-SHORT_SHA` (требуют локальных чартов с файловой системы). Экспериментальные чарты (`-experimental`) не поддерживаются для production и могут меняться без уведомления.

### Сценарий 16: Legacy-режим сообщества (autoscaling modes)

> **Статус:** legacy. Прежние autoscaling-режимы ARC (`RunnerDeployment`, `RunnerScaleSet`, `HorizontalRunnerAutoscaler`, API `actions.summerwind.net/v1alpha1`) с 2025 года поддерживаются только сообществом; GitHub поддерживает только режим autoscaling runner scale sets (discussion #2775). Применяйте только для поддержки существующих развёртываний; для новых — Helm-чарты из Сценариев 1–2.

Установка legacy-чарта (требуется предустановленный cert-manager для Admission Webhook):

```bash
# Вариант 1: манифесты (пример для v0.25.2 — последний legacy-релиз)
kubectl create -f https://github.com/actions/actions-runner-controller/releases/download/v0.25.2/actions-runner-controller.yaml

# Вариант 2: Helm
helm repo add actions-runner-controller https://actions-runner-controller.github.io/actions-runner-controller
helm upgrade --install --namespace actions-runner-system --create-namespace \
             --wait actions-runner-controller actions-runner-controller/actions-runner-controller
```

Легаси-документация (quickstart, deploying runners, authenticating, custom volumes, runner groups) — в каталоге `docs/` репозитория `actions/actions-runner-controller`.

## Команды и операции

### Helm и kubectl

| Операция | Команда |
|---|---|
| Список Helm-релизов ARC | `helm list -A` |
| Поды controller'а | `kubectl get pods -n arc-systems` |
| Поды раннеров (watch) | `kubectl get pods -n arc-runners -w` |
| AutoscalingRunnerSet | `kubectl get autoscalingrunnersets -n arc-runners` |
| EphemeralRunnerSet | `kubectl get ephemeralrunnersets -n arc-runners` |
| EphemeralRunner | `kubectl get ephemeralrunners -n arc-runners` |
| Логи controller'а | `kubectl logs -n arc-systems -l app.kubernetes.io/name=gha-runner-scale-set-controller` |
| Логи listener'а | `kubectl logs -n arc-systems -l auto-scaling-runner-set-namespace=arc-runners -l auto-scaling-runner-set-name=arc-runner-set` |
| Обновить лимиты scale set'а | `helm upgrade arc-runner-set -n arc-runners --set minRunners=5 --set maxRunners=50 oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set` |
| Удалить runner scale set | `helm uninstall arc-runner-set -n arc-runners` |
| Удалить controller | `helm uninstall arc -n arc-systems` |

Метки для фильтрации (troubleshooting): controller-под — `app.kubernetes.io/name=gha-runner-scale-set-controller`; listener — `app.kubernetes.io/component=runner-scale-set-listener`, `actions.github.com/scale-set-name=<name>`; runner-под — `app.kubernetes.io/component=runner`, `actions.github.com/scale-set-name=<name>`, `actions-ephemeral-runner=true`.

### gh CLI (проверка раннеров на стороне GitHub)

```bash
# Список self-hosted раннеров репозитория
gh api /repos/{owner}/{repo}/actions/runners --jq '.runners[].name'

# Список org-раннеров
gh api /orgs/{org}/actions/runners --jq '.runners[].name'

# Удалить раннер по ID
gh api -X POST /repos/{owner}/{repo}/actions/runners/12345/remove

# Список runner groups организации
gh api /orgs/{org}/actions/runner-groups --jq '.runner_groups[].name'
```

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| Controller Running, но listener-под не создаётся | Неверный `githubConfigSecret` или `githubConfigUrl` | Проверить логи controller'а; убедить controller в доступе к API server; proxy/Istio-sidecar должен пропускать трафик controller→API server |
| `failed to get access token for GitHub App auth: 401 Unauthorized` | NTP-drift: время узла впереди времени GitHub на несколько секунд | Настроить синхронизацию с NTP |
| `Error: INSTALLATION FAILED ... Name must have up to 45 characters` | Слишком длинное имя Helm-релиза | Сократить `INSTALLATION_NAME` (лимит 45 символов для scale set'а, 63 для namespace) |
| `Access to the path /home/runner/_work/_tool is denied` | Kubernetes mode + PV + non-root: mismatch прав на volume | `securityContext.fsGroup: 123` в PodSpec раннера, либо init-контейнер `sudo chown -R 1001:123 /home/runner/_work` |
| `Jobs without a job container are forbidden on this runner` | Kubernetes mode, workflow без `container:` | `ACTIONS_RUNNER_REQUIRE_JOB_CONTAINER: "false"` (осознанно: расширяет права runner-пода на K8s API) |
| Runner-под stuck в `Pending` | Недостаточно CPU/Memory в кластере | Увеличить `resources` в `template.spec` или добавить ноды |
| Job'ы в `queued`, раннеров нет | Достигнут `maxRunners`; не совпадают runner group или метки | Повысить `maxRunners`; проверить `runnerGroup` и `scaleSetLabels` против `runs-on` |
| `Registration error` при старте | App не установлен в org / нет permissions; PAT без нужных scope | Для App: Self-hosted runners R/W (org) + Administration R/W (repo-scope); для PAT: `repo` / `admin:org` |
| `image pull failed` | Нет `imagePullSecrets` для приватного образа | Добавить `imagePullSecrets` в `template.spec` |
| Раннеры пересоздаются после cancel workflow'а | Нормальное поведение: listener временно держит desired count, пока не получит сигнал cancel | Не требует действий; кратковременно |
| Раннер не принимает job'ы | Обновление старше 30 дней | Обновить runner-образ/чарт до актуальной версии |
| Не удаётся добавить раннера в group | Лимит 10,000 раннеров в одной runner group | Разнести по группам |

## Лучшие практики

1. **Раздельные namespace**: controller — в `arc-systems`, runner-поды — в `arc-runners` (security best practice от GitHub).
2. **GitHub App вместо PAT** для repo/org-level scale sets; enterprise-level — только PAT (classic) с минимальными scope.
3. **Секреты через Kubernetes Secret** (`githubConfigSecret: <имя>`), а не plain-text в `--set`/CLI.
4. **Сбор логов**: controller, listener и эфемерные раннеры пишут логи в stdout — настройте retention до деплоя в production.
5. **Отдельный кластер для недоверенного кода**: workflow'ы исполняют произвольный код; не делите кластер ARC с production-нагрузкой.
6. **Пинить версии**: `--version` для чартов и явные теги образов в production; использовать только released-чарты, не `master`; `-experimental`-чарты не для production.
7. **minRunners как warm pool** для latency-чувствительных пайплайнов; maxRunners — потолок затрат; scheduled-изменения — через внешний cron + `helm upgrade`.
8. **Мониторинг**: метрики `gha_*` (Сценарий 12); алерт на рост `gha_job_startup_duration_seconds` (queue time) и `gha_controller_failed_ephemeral_runners`.
9. **Network policies**: ограничьте egress раннеров — только нужные реестры/зеркала пакетов; для исходящего прокси — секция `proxy` в `values.yaml`.
10. **Кастомный образ**: наследуйтесь от `ghcr.io/actions/actions-runner`, ставьте только необходимое; где возможно — `actions/setup-*` в workflow вместо образа.
11. **Обновления в течение 30 дней**: иначе GitHub Actions перестаёт ставить job'ы в очередь на устаревшие раннеры.
12. **Cache volume**: persistent volume для кэша зависимостей (`~/.npm`, `~/.cache/go-build`) — только если это допустимо вашей моделью угроз (эфемерность теряется).

## Дополнительная информация

- **[Самостоятельные раннеры (Self-hosted Runners)](./self_hosted_runners.md)** — классическая установка self-hosted раннеров (без Kubernetes), `--ephemeral`, JIT Config.
- **[GitHub Apps](./github_apps.md)** — создание и настройка App для аутентификации ARC.
- **[GitHub Packages и GHCR](./github_packages_ghcr.md)** — pull-образов из ghcr.io в раннеры.
- **[Git автоматизация](./Git_Automation.md)** — использование App/PAT для `git push` из раннеров.
- **[Ограничения среды выполнения](./Environment_Limitations.md)** — спецификации GitHub-hosted vs self-hosted раннеров.
- **[Управление парком раннеров](../CI-CD/runner-fleet-management.md)** — governance, квоты и политики флота раннеров.
- Официальная документация: [Quickstart](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners-with-actions-runner-controller/quickstart-for-actions-runner-controller), [Deploying runner scale sets](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners-with-actions-runner-controller/deploying-runner-scale-sets-with-actions-runner-controller), [Authenticating ARC](https://docs.github.com/en/actions/how-tos/manage-runners/use-actions-runner-controller/authenticate-to-the-api), [Troubleshooting](https://docs.github.com/en/actions/tutorials/use-actions-runner-controller/troubleshoot), [Репозиторий ARC](https://github.com/actions/actions-runner-controller), [Discussion #2775 — почему старые режимы legacy](https://github.com/actions/actions-runner-controller/discussions/2775).
