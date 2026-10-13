# Crossplane: Тестирование платформы

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Тестирование платформы Crossplane** — комплекс методологий и инструментов верификации декларативных абстракций (XRD, Composition, Composition Functions, EnvironmentConfigs) и управляемых ресурсов на всех стадиях жизненного цикла до их применения в продуктивном управляющем кластере (Control Plane).

**Crossplane CLI (`crossplane render`)** — штатная утилита командной строки (компонент `crank`), выполняющая локальный оффлайн-прогон функций композиции без подключения к Kubernetes API. Принимает на вход Composite Resource (XR), Composition и манифесты Functions, симулируя работу контроллера композиций и генерируя итоговый поток YAML с управляемыми ресурсами (аналог `helm template` для инфраструктурных графов).

**Schema Validation (`crossplane beta validate schemas`)** — механизм валидации сгенерированных манифестов на соответствие спецификациям OpenAPI v3 извлеченным из CustomResourceDefinitions (CRD) или OCI-пакетов провайдеров.

**Observed State Simulation (`--observed-resources`)** — режим симуляции внешнего или текущего состояния инфраструктуры при рендеринге, позволяющий передавать в функции композиции предзаполненные статусы ресурсов для проверки условий готовности (`Ready`), генерации зависимых полей и вычисления статусов родительского XR.

**Extra Resources Context (`--extra-resources`)** — передача внешних источников данных (в первую очередь `EnvironmentConfig`) в локальный конвейер рендеринга для симуляции шины окружения и валидации динамической подстановки параметров.

**Development Runtime (`render.crossplane.io/runtime: Development`)** — специальный режим исполнения Composition Function в `crossplane render`, при котором CLI направляет gRPC-запросы на локально запущенный процесс разработчика (на `localhost` без сборки и запуска Docker-контейнера).

**Golden Testing (Snapshot Testing)** — метод регрессионного тестирования, основанный на фиксации эталонного YAML-вывода рендера и автоматическом сравнении (`diff`) с результатом текущей сборки в CI.

**Kyverno Chainsaw** — специализированный декларативный E2E-тестовый фреймворк для Kubernetes и Crossplane, выполняющий сценарии развертывания и валидации (`try`, `catch`, `finally`, `assert`, `error`) против реального API-сервера в изолированных временных кластерах.

**KUTTL (KUbernetes Test Tool)** — декларативный инструментарий интеграционного тестирования операторов и CRD посредством последовательных шагов `step` и ассертов `assert`.

**Изолированный тестовый кластер (KinD / k3d)** — легковесный эфемерный кластер Kubernetes, разворачиваемый в контейнерах внутри CI-раннера для проведения E2E-тестов платформы без доступа к внешним облачным сервисам.

---

## Базовые концепции и архитектура

### Пирамида тестирования платформенных абстракций

Тестирование платформенных сервисов на базе Crossplane реализует стратегию «сдвига влево» (Shift-Left), предотвращая попадание синтаксических ошибок, циклических зависимостей и неконсистентных состояний в продуктивный кластер:

```text
                           ┌─────────────────────────┐
                           │        Уровень 5        │
                           │   E2E-тесты (Chainsaw)  │  Медленно, изоляция,
                           │   KinD / k3d кластеры   │  реальный apiserver
                           └────────────┬────────────┘
                                        │
                           ┌────────────┴────────────┐
                           │        Уровень 4        │
                           │  Policy Tests (Kyverno) │  Оффлайн, проверка
                           │    Проверка комплаенса  │  безопасности манифестов
                           └────────────┬────────────┘
                                        │
                           ┌────────────┴────────────┐
                           │        Уровень 3        │
                           │    Schema Validation    │  Оффлайн, соответствие
                           │     CRD / OpenAPI v3    │  схемам провайдеров
                           └────────────┬────────────┘
                                        │
                           ┌────────────┴────────────┐
                           │        Уровень 2        │
                           │      Render-тесты       │  Быстро, детерминировано,
                           │   crossplane render     │  без сети и контейнеров
                           └────────────┬────────────┘
                                        │
                           ┌────────────┴────────────┐
                           │        Уровень 1        │
                           │  Unit-тесты функций     │  Микросекунды,
                           │  (Go, Python, KCL)      │  тесты чистого кода
                           └─────────────────────────┘
```

1. **L1: Unit-тесты логики функций (Функциональный уровень)** — проверка алгоритмической логики внутри кастомных Composition Functions (на Go, Python или KCL) с помощью нативных тестовых фреймворков (`go test`, `pytest`).
2. **L2: Оффлайн Render-тестирование (Интеграция конвейера)** — проверка сборки композиции через `crossplane render`. Проверяет передачу контекста между функциями, корректность пайплайна и генерацию целевых ресурсов без запуска Kubernetes API.
3. **L3: Валидация по схемам (Синтаксический уровень)** — верификация сгенерированных манифестов через `crossplane beta validate schemas` или `kubeconform`. Гарантирует, что сгенерированные ресурсы соответствуют версиям API и спецификациям установленных CRD.
4. **L4: Валидация политик и безопасности (Уровень управления)** — анализ сгенерированного вывода на соответствие корпоративным политикам безопасности (Kyverno CLI, OPA Conftest).
5. **L5: Интеграционные E2E-тесты (Системный уровень)** — развертывание XRD, Composition и тестовых Claims в изолированном эфемерном кластере (KinD) с проверкой создания дочерних ресурсов и условий готовности (`Ready: True`) через Kyverno Chainsaw.

---

### Архитектура конвейера рендеринга и поток данных

Утилита `crossplane render` эмулирует внутренний reconciler контроллера Crossplane:

```text
┌─────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐
│ Input XR / Claim│   │ Composition (Pipeline) │   │ Functions Manifests    │
│    (xr.yaml)    │   │   (composition.yaml)   │   │    (functions.yaml)    │
└────────┬────────┘   └───────────┬────────────┘   └───────────┬────────────┘
         │                        │                            │
         └───────────────────┐    │    ┌───────────────────────┘
                             ▼    ▼    ▼
                       ┌───────────────────┐
                       │ crossplane render │◀─── [--extra-resources: EnvironmentConfig]
                       └─────────┬─────────┘◀─── [--observed-resources: текущее состояние]
                                 │
                 gRPC Stream     ▼ (Docker runner / Development runner)
                       ┌───────────────────┐
                       │ Function Pipeline │
                       │ 1. patch-and-xform│
                       │ 2. auto-ready     │
                       └─────────┬─────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │ Rendered YAML Stream  │
                     │  - Primary XR         │
                     │  - Desired Resources  │
                     └───────────┬───────────┘
                                 │ stdout
                                 ▼
                     ┌───────────────────────┐
                     │ crossplane validate / │
                     │   kyverno test / diff │
                     └───────────────────────┘
```

#### Механизм симуляции наблюдаемого состояния (Observed State)
По умолчанию `crossplane render` выполняет первый цикл согласования (Reconcile Loop 0), где наблюдаемое состояние отсутствует. Для тестирования логики, зависящей от существующих ресурсов (статусы, динамические ссылки, условия готовности):
- Манифесты существующих ресурсов подаются через флаг `--observed-resources=<dir|file>`.
- **Критическое требование:** каждый наблюдаемый ресурс обязан содержать аннотацию `crossplane.io/composition-resource-name`, значение которой совпадает с именем ресурса (`step[].name` или `base.metadata.name`) в Composition. Без этой аннотации контроллер не сможет связать наблюдаемый ресурс с ресурсом в композиции и проигнорирует его.

---

## Практические сценарии

### Подготовка инструментария (On-Premise)

Для локального тестирования и работы в CI-раннерах требуется набор бинарных утилит:

```bash
# 1. Установка Crossplane CLI (crank v2.x)
curl -sL "https://raw.githubusercontent.com/crossplane/crossplane/master/install.sh" | sh
sudo mv crossplane /usr/local/bin/

# 2. Проверка установленной версии
crossplane --version
# → Client Version: v2.4.0

# 3. Установка Kyverno Chainsaw для E2E тестирования
CHAINSAW_VERSION="v0.2.12"
curl -sL "https://github.com/kyverno/chainsaw/releases/download/${CHAINSAW_VERSION}/chainsaw_linux_amd64.tar.gz" | tar -xz
sudo mv chainsaw /usr/local/bin/
chainsaw version
# → Version: v0.2.12

# 4. Установка kubeconform для оффлайн-валидации схем Kubernetes
KUBECONFORM_VERSION="v0.6.7"
curl -sL "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" | tar -xz
sudo mv kubeconform /usr/local/bin/
kubeconform -v
# → v0.6.7
```

---

### Сценарий 1: Базовый оффлайн-рендеринг композиции

Тестирование формирования набора On-Premise ресурсов (Namespace, ResourceQuota, NetworkPolicy) для тенанта на основе Composite Resource.

#### Входные манифесты

1. Определение вызываемых функций (`tests/functions.yaml`):
```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
spec:
  package: xpkg.corp.internal/crossplane/function-patch-and-transform:v0.8.2
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-auto-ready
spec:
  package: xpkg.corp.internal/crossplane/function-auto-ready:v0.5.0
```

2. Композиция On-Premise инфраструктуры (`composition.yaml`):
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: onprem-tenants.platform.corp.internal
  labels:
    provider: kubernetes
spec:
  compositeTypeRef:
    apiVersion: platform.corp.internal/v1alpha1
    kind: XTenantNamespace
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: tenant-namespace
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              metadata:
                annotations:
                  crossplane.io/composition-resource-name: tenant-namespace
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Namespace
                    metadata:
                      labels:
                        managed-by: crossplane
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.name
                toFieldPath: spec.forProvider.manifest.metadata.name
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.environment
                toFieldPath: spec.forProvider.manifest.metadata.labels["env"]

          - name: compute-quota
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              metadata:
                annotations:
                  crossplane.io/composition-resource-name: compute-quota
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: ResourceQuota
                    metadata:
                      name: compute-quota
                    spec:
                      hard:
                        requests.cpu: "4"
                        requests.memory: 8Gi
                        limits.cpu: "8"
                        limits.memory: 16Gi
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.name
                toFieldPath: spec.forProvider.manifest.metadata.namespace

    - step: auto-ready
      functionRef:
        name: function-auto-ready
```

3. Входной Composite Resource (`tests/xr.yaml`):
```yaml
apiVersion: platform.corp.internal/v1alpha1
kind: XTenantNamespace
metadata:
  name: billing-dev-xr
spec:
  parameters:
    name: billing-dev
    environment: development
```

#### Запуск рендеринга и результат

```bash
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml
```

Ожидаемый результат:
```yaml
---
apiVersion: platform.corp.internal/v1alpha1
kind: XTenantNamespace
metadata:
  name: billing-dev-xr
status:
  conditions:
  - lastTransitionTime: "2026-10-13T18:00:00Z"
    message: 'Unready resources: tenant-namespace, compute-quota'
    reason: WaitingForResources
    status: "False"
    type: Ready
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  annotations:
    crossplane.io/composition-resource-name: tenant-namespace
  name: billing-dev-xr-tenant-namespace
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        labels:
          env: development
          managed-by: crossplane
        name: billing-dev
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  annotations:
    crossplane.io/composition-resource-name: compute-quota
  name: billing-dev-xr-compute-quota
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: ResourceQuota
      metadata:
        name: compute-quota
        namespace: billing-dev
      spec:
        hard:
          limits.cpu: "8"
          limits.memory: 16Gi
          requests.cpu: "4"
          requests.memory: 8Gi
```

---

### Сценарий 2: Тестирование с динамическим контекстом и наблюдаемым состоянием

В реальных окружениях параметры квот берутся из `EnvironmentConfig` (в зависимости от stage), а статус готовности XR вычисляется на основе статусов дочерних ресурсов.

#### 1. Подготовка конфигурации окружения (`tests/environments.yaml`)
```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: EnvironmentConfig
metadata:
  name: dev-environment
  labels:
    tier: dev
data:
  cpuLimit: "16"
  memoryLimit: "32Gi"
```

#### 2. Подготовка симулированного наблюдаемого состояния (`tests/observed.yaml`)
Симулируем, что ресурсы уже применены в кластере и перешли в статус `Ready=True`:
```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: billing-dev-xr-tenant-namespace
  annotations:
    crossplane.io/composition-resource-name: tenant-namespace
status:
  conditions:
    - type: Ready
      status: "True"
      lastTransitionTime: "2026-10-13T18:00:00Z"
      reason: Available
    - type: Synced
      status: "True"
      lastTransitionTime: "2026-10-13T18:00:00Z"
      reason: ReconcileSuccess
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: billing-dev-xr-compute-quota
  annotations:
    crossplane.io/composition-resource-name: compute-quota
status:
  conditions:
    - type: Ready
      status: "True"
      lastTransitionTime: "2026-10-13T18:00:00Z"
      reason: Available
    - type: Synced
      status: "True"
      lastTransitionTime: "2026-10-13T18:00:00Z"
      reason: ReconcileSuccess
```

#### 3. Вызов команды с флагами контекста и состояния

```bash
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml \
  --extra-resources tests/environments.yaml \
  --observed-resources tests/observed.yaml \
  --include-full-xr
```

Ожидаемый результат для статуса XR:
```yaml
---
apiVersion: platform.corp.internal/v1alpha1
kind: XTenantNamespace
metadata:
  name: billing-dev-xr
status:
  conditions:
  - lastTransitionTime: "2026-10-13T18:00:00Z"
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-10-13T18:00:00Z"
    reason: ReconcileSuccess
    status: "True"
    type: Synced
```
*Результат подтверждает:* функция `function-auto-ready` успешно распознала статус наблюдаемых ресурсов и перевела корневой XR в `Ready: "True"`.

---

### Сценарий 3: Локальная отладка кастомной функции в Development Runtime

При написании собственной функции композиции на Go или Python отладка через сборку Docker-образа замедляет цикл разработки. Режим `Development Runtime` позволяет направлять gRPC-вызовы из CLI напрямую в локально запущенный процесс.

#### 1. Определение функции с аннотацией Development
В файле `tests/dev-functions.yaml`:
```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-network-policy-generator
  annotations:
    render.crossplane.io/runtime: Development
    render.crossplane.io/runtime-development-target: "localhost:9443"
spec:
  package: xpkg.corp.internal/platform/function-network-policy-generator:v0.1.0
```

#### 2. Запуск локального сервера функции
Запустите функцию в соседнем терминале в режиме разработки:
```bash
# Для функции на Python
python -m function_network_policy --address "localhost:9443" --insecure

# Или для функции на Go
go run ./cmd/main.go --address "localhost:9443" --insecure
```

#### 3. Вызов рендеринга через локальный сокет
```bash
crossplane render tests/xr.yaml composition.yaml tests/dev-functions.yaml
```
CLI подключится к порту `localhost:9443` по gRPC, выполнит передачу `RunFunctionRequest` и выведет обработанный `RunFunctionResponse` без вызова демона Docker.

---

### Сценарий 4: Оффлайн-валидация схем CRD и манифестов

В изолированном контуре (Air-Gapped) доступ к публичным реестрам схем отсутствует. Валидация вывода рендера выполняется по локально сохраненным CRD провайдеров.

#### 1. Извлечение CRD провайдеров в оффлайн-каталог
```bash
mkdir -p schemas/crds
# Копирование CRD установленного провайдера provider-kubernetes
kubectl get crd -l pkg.crossplane.io/provider=provider-kubernetes -o yaml > schemas/crds/provider-kubernetes.yaml
```

#### 2. Валидация через crossplane beta validate
```bash
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml \
  | crossplane beta validate schemas/crds/ -
```

Вывод команды:
```text
Total 2 resources: 2 valid, 0 invalid
```

#### 3. Альтернативная строгая валидация через kubeconform
Для проверки спецификаций Kubernetes и сгенерированных манифестов `Object`:
```bash
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml > rendered-output.yaml

kubeconform \
  -strict \
  -summary \
  -schema-location default \
  -schema-location 'schemas/crds/{{ .ResourceKind }}_{{ .GroupVersion }}.json' \
  rendered-output.yaml
```

Ожидаемый вывод:
```text
Summary: 3 resources will be checked
rendered-output.yaml - XTenantNamespace billing-dev-xr: status valid
rendered-output.yaml - Object billing-dev-xr-tenant-namespace: status valid
rendered-output.yaml - Object billing-dev-xr-compute-quota: status valid
```

---

### Сценарий 5: Спецификационное тестирование (Golden / Snapshot Tests)

Для исключения непреднамеренных изменений в сгенерированных манифестах при обновлении Composition Functions используется подход Golden Files.

#### 1. Генерация эталонного снимка (Baseline)
```bash
mkdir -p tests/golden
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml > tests/golden/billing-dev.golden.yaml
```

#### 2. Скрипт автоматической верификации (`tests/run-golden-tests.sh`)
```bash
#!/usr/bin/env bash
set -euo pipefail

TEMP_OUTPUT=$(mktemp)
trap 'rm -f "${TEMP_OUTPUT}"' EXIT

crossplane render tests/xr.yaml composition.yaml tests/functions.yaml > "${TEMP_OUTPUT}"

if diff -u tests/golden/billing-dev.golden.yaml "${TEMP_OUTPUT}"; then
  echo "✔ [PASS] Golden test matches expected output."
  exit 0
else
  echo "✖ [FAIL] Render output diverged from golden snapshot!" >&2
  exit 1
fi
```

#### 3. Валидация корпоративных политик безопасности (Kyverno CLI)
Проверка сгенерированных манифестов политиками admission-контроллеров до попадания в кластер:
```bash
# Проверка отсутствия привилегированных настроек и соответствия меткам
kyverno apply policies/network-isolation.yaml --resource rendered-output.yaml
# → Applying 1 policy rule(s) to 3 resource(s)...
# → pass: 3, fail: 0, warn: 0, error: 0, skip: 0
```

---

### Сценарий 6: Декларативное E2E-тестирование в изолированном KinD-кластере (Kyverno Chainsaw)

E2E-тестирование проверяет реальное поведение Crossplane в изолированном кластере Kubernetes: от создания Claim до готовности сгенерированных нативных объектов Kubernetes.

#### 1. Создание эфемерного кластера KinD
```bash
cat <<EOF > kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
EOF

kind create cluster --name cp-e2e --config kind-config.yaml
```

#### 2. Развертывание базового контура
```bash
# Установка Crossplane Core через Helm (локальный чарт или закрытый Harbor)
helm install crossplane ./charts/crossplane --namespace crossplane-system --create-namespace --wait

# Установка CRD, XRD и Composition
kubectl apply -f apis/xrd-tenant-namespace.yaml
kubectl apply -f composition.yaml
kubectl apply -f tests/functions.yaml
```

#### 3. Декларативный тест Chainsaw (`tests/chainsaw/test-tenant.yaml`)
Kyverno Chainsaw выполняет сценарий:
- Шаг 1 (`apply`): создание Claim тенанта.
- Шаг 1 (`assert`): ожидание перехода Claim и Composite Resource в состояние `Ready=True`.
- Шаг 2 (`assert`): проверка создания нативного `Namespace` и `ResourceQuota` в кластере.
- Очистка (`finally`): удаление Claim и проверка каскадного удаления ресурсов.

```yaml
apiVersion: chainsaw.kyverno.io/v1alpha1
kind: Test
metadata:
  name: tenant-namespace-lifecycle
spec:
  steps:
    - name: create-and-assert-claim
      try:
        - apply:
            file: manifests/claim.yaml
        - assert:
            file: manifests/assert-claim-ready.yaml
    - name: verify-kubernetes-resources
      try:
        - assert:
            file: manifests/assert-namespace-exists.yaml
            timeout: 30s
        - assert:
            file: manifests/assert-quota-exists.yaml
            timeout: 30s
  finally:
    - delete:
        ref:
          apiVersion: platform.corp.internal/v1alpha1
          kind: TenantNamespace
          name: my-team-claim
          namespace: default
```

Манифест утверждения статуса (`manifests/assert-claim-ready.yaml`):
```yaml
apiVersion: platform.corp.internal/v1alpha1
kind: TenantNamespace
metadata:
  name: my-team-claim
  namespace: default
status:
  conditions:
    - type: Ready
      status: "True"
    - type: Synced
      status: "True"
```

Манифест проверки созданного пространства имен (`manifests/assert-namespace-exists.yaml`):
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: my-team-claim-prod
  labels:
    managed-by: crossplane
```

#### 4. Запуск Chainsaw
```bash
chainsaw test tests/chainsaw/ --test-dir tests/chainsaw/
```

Ожидаемый вывод:
```text
Version: v0.2.12
Loading tests...
- tenant-namespace-lifecycle (tests/chainsaw/test-tenant.yaml)
Running tests...
=== RUN   tenant-namespace-lifecycle
=== STEP  tenant-namespace-lifecycle/create-and-assert-claim
=== STEP  tenant-namespace-lifecycle/verify-kubernetes-resources
--- PASS: tenant-namespace-lifecycle (14.2s)
PASS
Tests summary: 1 passed, 0 failed, 0 skipped
```

---

### Сценарий 7: Автоматизированный CI/CD пайплайн (GitLab CI / GitHub Actions)

Пайплайн реализует полную пирамиду тестирования для On-Premise инфраструктуры:

#### Конфигурация для GitLab CI (`.gitlab-ci.yml`)

```yaml
stages:
  - lint
  - render-validate
  - policy-check
  - e2e-test

variables:
  CROSSPLANE_VERSION: "v2.4.0"
  CHAINSAW_VERSION: "v0.2.12"

# 1. Синтаксический анализ и оффлайн-рендер всех композиций
render-and-validate:
  stage: render-validate
  image: harbor.corp.internal/platform/crossplane-ci:${CROSSPLANE_VERSION}
  script:
    - echo "=== Starting Crossplane Render & Schema Validation ==="
    - |
      for comp in compositions/*.yaml; do
        echo "Processing ${comp}..."
        crossplane render tests/xr.yaml "${comp}" tests/functions.yaml > rendered.yaml
        crossplane beta validate schemas/crds/ rendered.yaml
      done
  artifacts:
    paths:
      - rendered.yaml
    expire_in: 2 hours

# 2. Проверка соответствия корпоративным политикам безопасности
security-policies:
  stage: policy-check
  image: harbor.corp.internal/platform/kyverno-cli:v1.12.0
  needs:
    - render-and-validate
  script:
    - kyverno apply policies/ --resource rendered.yaml

# 3. Интеграционный E2E тест в KinD
e2e-chainsaw:
  stage: e2e-test
  image: harbor.corp.internal/platform/dind-runner:latest
  services:
    - docker:dind
  needs:
    - security-policies
  script:
    - kind create cluster --name cp-ci-test --wait 60s
    - helm install crossplane ./charts/crossplane -n crossplane-system --create-namespace --wait
    - kubectl apply -f apis/
    - kubectl apply -f compositions/
    - kubectl apply -f tests/functions.yaml
    - chainsaw test tests/chainsaw/
  after_script:
    - kind delete cluster --name cp-ci-test || true
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

---

## Операции и команды

Справочная таблица команд для тестирования и валидации Crossplane в среде инженера:

| Операция | Команда | Назначение |
|:---|:---|:---|
| **Локальный рендеринг** | `crossplane render xr.yaml comp.yaml fn.yaml` | Базовый рендеринг графа ресурсов без Kubernetes |
| **Рендеринг с Observed** | `crossplane render ... --observed-resources=obs/` | Симуляция существующих ресурсов и их статусов |
| **Рендеринг с Extra** | `crossplane render ... --extra-resources=env.yaml` | Передача `EnvironmentConfig` и контекста в конвейер |
| **Экспорт полного XR** | `crossplane render ... --include-full-xr` | Вывод корневого XR со всеми полями статуса и условий |
| **Экспорт контекста** | `crossplane render ... --include-context` | Отладка шины внутреннего контекста между функциями |
| **Валидация по схемам** | `crossplane beta validate schemas/ manifests.yaml` | Проверка соответствия сгенерированных манифестов CRD |
| **Сравнение со снимком** | `diff -u golden.yaml <(crossplane render ...)` | Проверка отсутствия нежелательных диффов (Golden test) |
| **E2E-тест Chainsaw** | `chainsaw test tests/chainsaw/ --kubeconfig=kube.conf` | Запуск декларативного сценария проверки на кластере |
| **Очистка кластера KinD** | `kind delete cluster --name cp-e2e` | Удаление эфемерного окружения после E2E-тестирования |

### Примеры вызовов команд с ожидаемым выводом

```bash
# 1. Потоковый оффлайн-рендеринг с валидацией схем через пайплайны Unix
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml \
  | crossplane beta validate schemas/crds/ -
# → Total 2 resources: 2 valid, 0 invalid

# 2. Проверка контекста шины EnvironmentConfig
crossplane render tests/xr.yaml composition.yaml tests/functions.yaml \
  --extra-resources tests/environments.yaml \
  --include-context \
  | grep -A 10 "apiextensions.crossplane.io/environment"
# → apiextensions.crossplane.io/environment:
# →   cpuLimit: "16"
# →   memoryLimit: "32Gi"

# 3. Вызов регрессионного тестирования через diff
diff -u tests/golden/baseline.yaml <(crossplane render tests/xr.yaml composition.yaml tests/functions.yaml)
# → (пустой вывод при отсутствии расхождений; код возврата 0)

# 4. Прогон тестового набора Chainsaw с подробным протоколированием
chainsaw test tests/chainsaw/ --verbosity=debug
# → Loading tests from tests/chainsaw/...
# → Running step: 01-apply-claim... [DONE]
# → Running step: 02-assert-readiness... [DONE]
# → Summary: 1 passed, 0 failed
```

---

## Устранение неполадок (Troubleshooting)

### Сводная матрица типовых ошибок

| Ошибка / Симптом | Вероятная причина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| `cannot find observed resource in composition` | В файле из `--observed-resources` отсутствует аннотация `crossplane.io/composition-resource-name` | Проверить секцию `metadata.annotations` в манифесте наблюдаемого ресурса | Добавить аннотацию с именем, строго совпадающим с полем `name` шага в Composition |
| `cannot run composition functions: ... connection refused` | Не запущен локальный процесс функции при использовании `render.crossplane.io/runtime: Development` | Проверить порт и запуск процесса: `netstat -tulpn \| grep 9443` | Запустить процесс функции локально или убрать аннотацию Development для запуска через Docker |
| `cannot find schema for resource` | Утилита `crossplane beta validate` не находит CRD для целевой группы/версии API | Проверить наличие CRD в переданном каталоге схем | Экспортировать актуальный манифест CRD в каталог `schemas/crds/` |
| `cannot find field in environment: "..."` | В переданном `--extra-resources` манифесте `EnvironmentConfig` отсутствует требуемое поле | Проверить вывод `crossplane render ... --include-context` | Добавить ключ в блок `data` объекта `EnvironmentConfig` или предусмотреть значение по умолчанию |
| Chainsaw: `assertion timed out waiting for condition` | Дочерние ресурсы не перешли в `Ready: True` из-за блокировки контроллером или сбоя ProviderConfig | Проверить события в кластере: `kubectl describe <resource>` | Проверить логи пода провайдера, сетевые доступы и RBAC права сервисного аккаунта |

---

### Практические сценарии диагностики

#### Диагностика 1: Отсутствие аннотации связи в `--observed-resources`
**Симптом:** При вызове команды рендеринга с флагом `--observed-resources` статус корневого XR остается `Ready: False`, а условия дочерних ресурсов не обновляются.
**Причина:** Функция `function-patch-and-transform` или `function-auto-ready` сопоставляет наблюдаемые ресурсы с композицией исключительно по системной аннотации.

**Алгоритм решения:**
1. Проверьте манифест наблюдаемого ресурса:
```bash
grep -n "composition-resource-name" tests/observed.yaml
```
2. Если строка отсутствует, добавьте аннотацию:
```yaml
metadata:
  annotations:
    crossplane.io/composition-resource-name: tenant-namespace # Должно совпадать с именем в composition.yaml
```
3. Повторите запуск `crossplane render ... --observed-resources=tests/observed.yaml`.

---

#### Диагностика 2: Сбой подключения gRPC в режиме отладки функции (Development Runtime)
**Симптом:**
```text
cannot run composition functions: cannot call RunFunction: rpc error: code = Unavailable desc = connection error: desc = "transport: Error while dialing: dial tcp [::1]:9443: connect: connection refused"
```
**Причина:** CLI попытался связаться с локальным сокетом по адресу `localhost:9443`, но процесс функции не запущен либо заблокирован локальным файрволом.

**Алгоритм решения:**
1. Проверьте, слушает ли локальный процесс указанный порт:
```bash
ss -tulpn | grep 9443
# → tcp LISTEN 0 128 127.0.0.1:9443 0.0.0.0:*
```
2. Если процесс не запущен, запустите его с явным указанием адреса:
```bash
go run ./cmd/main.go --address="127.0.0.1:9443" --insecure
```
3. Если требуется запустить стандартный контейнерный рантайм вместо локального процесса, удалите из манифеста функции аннотацию `render.crossplane.io/runtime: Development`.

---

#### Диагностика 3: Таймаут ожидания готовности ресурсов в тестах Chainsaw
**Симптом:**
```text
=== STEP  tenant-namespace-lifecycle/create-and-assert-claim
--- FAIL: tenant-namespace-lifecycle (30.0s)
    operation timeout: resource platform.corp.internal/v1alpha1/TenantNamespace/my-team-claim condition Ready was not met within 30s
```
**Причина:** Ресурс `TenantNamespace` не перешел в `Ready: True` в тестовом кластере KinD.

**Алгоритм решения:**
1. Запросите дерево состояния ресурсов через утилиту трассировки:
```bash
crossplane beta trace tenantnamespace.platform.corp.internal/my-team-claim
```
Вывод покажет проблемный узел:
```text
NAME                                                 SYNCED   READY   STATUS
TenantNamespace/my-team-claim (default)              True     False   WaitingForResources
└─ XTenantNamespace/my-team-claim-q8f2p              True     False   WaitingForResources
   └─ Object/billing-dev-xr-tenant-namespace         True     False   CannotApplyManifest
```
2. Проверьте события проблемного объекта `Object`:
```bash
kubectl describe object billing-dev-xr-tenant-namespace
# → Warning  CannotApplyManifest  ...  namespaces "billing-dev" is forbidden: User "system:serviceaccount:crossplane-system:provider-kubernetes" cannot create resource "namespaces"
```
3. Решение: добавить необходимые права RBAC сервисному аккаунту `provider-kubernetes` в кластере.

---

## Лучшие практики

1. **Shift-Left и изолированный оффлайн-контур:**
   - Никогда не тестируйте композиции напрямую в продуктивном управляющем кластере.
   - Каждый PR, затрагивающий директории `apis/` или `compositions/`, обязан автоматически проходить валидацию `crossplane render` и `crossplane beta validate schemas` до этапа ревью.

2. **Принцип чистых функций и детерминизма:**
   - Любая Composition Function должна быть чистой функцией (без внешних сетевых вызовов в процессе рендеринга). Вся внешняя контекстная информация должна передаваться строго через `EnvironmentConfig` или входной XR.
   - Это гарантирует полную воспроизводимость результатов рендера в CI без зависимости от состояния внешних баз данных и сервисов.

3. **Golden Testing для всех стандартных кейсов (Matrix Testing):**
   - Для каждой композиции формируйте матрицу тестовых XR (минимальная конфигурация, максимальная квота, режим высокой доступности).
   - Храните эталонные YAML-файлы в директории `tests/golden/` под версионным контролем git. Любое изменение в эталоне должно быть осознанным и подтверждаться в diff PR.

4. **Эфемерные изолированные окружения (KinD / k3d) для E2E:**
   - Не используйте общий постоянный тестовый кластер для E2E-тестов платформы. Накопление «мусорных» ресурсов и гонки между параллельными пайплайнами искажают результаты.
   - Создавайте чистый KinD-кластер на время выполнения шага CI и гарантированно удаляйте его (`kind delete cluster`) в блоке `after_script` / `finally`.

5. **Локальный кэш схем CRD (Air-Gapped Compliance):**
   - В закрытых корпоративных сетях храните выгруженные спецификации CRD всех используемых провайдеров (`provider-kubernetes`, `provider-helm`) в репозитории платформы либо во внутреннем OCI-реестре пакетов (Harbor).
   - Привязывайте шаг `crossplane beta validate schemas` к локальному каталогу схем во избежание сетевых таймаутов при сборке.

---

## Дополнительная информация

### Официальная документация и ресурсы
- [Crossplane CLI Reference: render and validate](https://docs.crossplane.io/latest/cli/command-reference/) — официальное руководство по утилите `crossplane render`.
- [Kyverno Chainsaw Documentation](https://kyverno.github.io/chainsaw/) — документация фреймворка декларативного тестирования Kubernetes.
- [Kubeconform](https://github.com/yannh/kubeconform) — инструмент валидации манифестов Kubernetes по схемам OpenAPI v3.

### Связанные документы базы знаний
- [Обзор Crossplane](./overview.md) — фундаментальные концепции Control Plane, архитектура и базовый инструментарий.
- [Composition Functions и EnvironmentConfig](./composition_functions.md) — конвейер функций, передача контекста и трансформация манифестов.
- [Политики и Governance](./policy_governance.md) — проверка соответствия корпоративным политикам безопасности (Kyverno, Gatekeeper).
- [Интеграция с GitOps](./gitops_integration.md) — автоматизация развертывания платформы через Argo CD и Flux.
- [Настройка provider-kubernetes](./provider_kubernetes_setup.md) — управление нативными объектами Kubernetes в On-Premise инфраструктуре.
