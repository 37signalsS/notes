# Crossplane: Composition Functions и EnvironmentConfig

**Актуально для:** Crossplane v1.17+ / v2.x (Composition Functions v1 / EnvironmentConfigs v1beta1)

## Определения

**Composition Function (функция композиции)** — независимый программный компонент (OCI-пакет `kind: Function`), выполняющий логику генерации и трансформации ресурсов в конвейере композиции. Функции заменили устаревший декларативный механизм статических шаблонов Patch & Transform (P&T), превратив композицию в программируемый конвейер с поддержкой условий, циклов, валидации и произвольной логики.

**Режим конвейера (Pipeline Mode)** — режим работы ресурса `Composition` (`spec.mode: Pipeline`), при котором обработка составного ресурса (XR) передается упорядоченной цепочке функций. В Crossplane v2.x режим конвейера является единственным поддерживаемым стандартом.

**Function Runner** — gRPC-сервис, запускаемый контроллером пакетов Crossplane в виде пода в пространстве имен `crossplane-system`, принимающий состояние ресурсов и возвращающий желаемый граф инфраструктуры.

**Контекст конвейера (Pipeline Context)** — разделяемое хранилище данных (`google.protobuf.Struct`), передаваемое от одной функции к другой по цепочке выполнения. Служит шиной обмена метаданными и переменными внутри одного цикла сверки.

**EnvironmentConfig** — кластерный ресурс Kubernetes (`kind: EnvironmentConfig`, `apiextensions.crossplane.io/v1`), содержащий типизированный набор параметров окружения (настройки дата-центра, квоты, CIDR-диапазоны, имена StorageClass, доменные суффиксы). Загружается в контекст конвейера функцией `function-environment-configs`.

**functionConfig (Input)** — встраиваемый YAML-объект в описании шага композиции (`spec.pipeline[].input`), передающий специфические параметры конфигурации конкретной функции (правила патчинга, шаблоны, селекторы).

**Наблюдаемое и желаемое состояния (Observed и Desired State)** — структуры данных gRPC-запроса: Observed State содержит фактическое состояние XR и уже существующих дочерних ресурсов в кластере; Desired State накапливает ресурсы, которые конвейер требует создать, обновить или удалить.

---

## Базовые концепции и архитектура

### Принцип работы Pipeline и gRPC-протокол

Движок композиции Crossplane исполняет конвейер функций по модели последовательного обогащения желаемого состояния:

```text
┌─────────────────┐
│   Composite     │ (Watch / Reconcile)
│ Resource (XR)   │
└────────┬────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Crossplane Composition Engine (mode: Pipeline)                         │
│                                                                        │
│   Step 1: function-environment-configs                                 │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ Вход: Observed State + Empty Context                         │     │
│   │ Действие: Загрузка EnvironmentConfig по Selector/Ref         │     │
│   │ Выход: Desired State + Context c данными окружения           │     │
│   └──────────────────────────────┬───────────────────────────────┘     │
│                                  │                                     │
│   Step 2: function-patch-and-transform (или KCL / Templating)           │
│   ┌──────────────────────────────▼───────────────────────────────┐     │
│   │ Вход: Desired State + Обогащенный Context                    │     │
│   │ Действие: Применение патчей из XR и Context в composed-ресурсы│    │
│   │ Выход: Наполненный граф желаемых ресурсов                    │     │
│   └──────────────────────────────┬───────────────────────────────┘     │
│                                  │                                     │
│   Step 3: function-auto-ready                                          │
│   ┌──────────────────────────────▼───────────────────────────────┐     │
│   │ Вход: Наблюдаемые статусы composed-ресурсов                  │     │
│   │ Действие: Агрегация condition Ready -> XR                    │     │
│   │ Выход: Финальный Desired State + XR Ready Condition          │     │
│   └──────────────────────────────────────────────────────────────┘     │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
                    [Управление Composed Resources]
                (provider-kubernetes, provider-helm, provider-sql)
```

1. **Инициация цикла сверки:** При изменении XR контроллер композиции формирует запрос `RunFunctionRequest`.
2. **Структура gRPC-сообщения:**
   - `observed`: состояние XR и дочерних ресурсов (с текущими статусами и полями, прочитанными из etcd/провайдеров).
   - `desired`: накопленное желаемое состояние composite и composed-ресурсов.
   - `context`: ассоциативный массив ключ-значение, передаваемый сквозь пайплайн.
   - `input`: манифест из `spec.pipeline[].input`.
3. **Последовательное выполнение:** Шаги конвейера выполняются строго синхронно в порядке объявления. Вывод шага $N$ (`RunFunctionResponse`) передается на вход шагу $N+1$.
4. **Атомарность:** Если любая функция возвращает фатальную ошибку (`Severity: Fatal`), конвейер прерывается, а цикл сверки XR завершается с ошибкой без применения промежуточных изменений.

### Типы и экосистема функций

| Функция | Назначение в архитектуре | Типовой сценарий (On-Prem / SRE) |
|---|---|---|
| `function-patch-and-transform` | Декларативный перенос полей и преобразования (P&T) | Базовая генерация ресурсов Kubernetes, ServiceAccount, Quota |
| `function-environment-configs` | Загрузка внешних параметров окружения в контекст | Инъекция настроек дата-центра, пулов IP, параметров Ceph/CSI |
| `function-auto-ready` | Автоматическая установка статуса готовности XR | Проверка условий `Ready: True` у всех сгенерированных ресурсов |
| `function-go-templating` | Генерация ресурсов через Go-шаблоны | Динамические списки ресурсов, сложные циклы (`range`), условия (`if`) |
| `function-kcl` | Генерация через типизированный язык KCL | Сложная платформенная логика, строгая валидация схем без компиляции |
| Кастомные функции (Go/Python) | Собственная бизнес-логика через Crossplane SDK | Запросы к внутренним IPAM, CMDB, валидация по корпоративным политикам |

### Механизм EnvironmentConfig: селекторы и слияние

`EnvironmentConfig` решает задачу разделения абстракции ресурса и специфики площадки развертывания (Dev/Stage/Prod, DC-1/DC-2):

1. **Выбор по прямому имени (`Reference`):**
   Жесткая привязка к конкретному манифесту `EnvironmentConfig`:
   ```yaml
   ref:
     name: onprem-dc1-production
   ```
2. **Выбор по селектору меток (`Selector`):**
   Динамический выбор на основе статических меток или значений из полей самого XR (`FromCompositeFieldPath`):
   ```yaml
   selector:
     mode: Single # Single (ошибка при нескольких) или Multi (слияние всех найденных)
     matchLabels:
       - type: FromCompositeFieldPath
         key: tenant
         valueFromFieldPath: spec.parameters.tenantId
       - type: Value
         key: environment
         value: production
   ```
3. **Порядок слияния (Merge Order):**
   При указании нескольких источников в списке `environmentConfigs` данные объединяются последовательно. При совпадении ключей приоритет имеет конфигурация, стоящая ниже по списку (последняя перезаписывает предыдущие). Все данные помещаются в контекст под системным ключом `apiextensions.crossplane.io/environment`.

### Управление жизненным циклом и Runtime (DeploymentRuntimeConfig)

Функции развертываются в кластере контроллером пакетов Crossplane. Для настройки системных параметров подов функций (лимиты CPU/RAM, права доступа, политики безопасности, репликация) используется ресурс `DeploymentRuntimeConfig`:

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: function-hardened-runtime
spec:
  deploymentTemplate:
    spec:
      replicas: 2
      template:
        spec:
          securityContext:
            runAsNonRoot: true
            runAsUser: 65532
            seccompProfile:
              type: RuntimeDefault
          containers:
            - name: package-runtime
              resources:
                requests:
                  cpu: 100m
                  memory: 128Mi
                limits:
                  cpu: 500m
                  memory: 512Mi
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities:
                  drop:
                    - ALL
```

Связывание пакета с настройками рантайма осуществляется через поле `spec.runtimeConfigRef` в манифесте `Function`.

---

## Практические сценарии и конфигурация

### Сценарий 1: Декларативная установка функций с привязкой к приватному реестру

В корпоративных контурах (On-Premise / Air-gapped) образы пакетов загружаются из внутреннего OCI-реестра (Harbor, Nexus) с фиксацией версий и ограничением ресурсов:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
spec:
  package: harbor.corp.internal/crossplane/function-patch-and-transform:v0.8.2
  packagePullPolicy: IfNotPresent
  runtimeConfigRef:
    name: function-hardened-runtime
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-environment-configs
spec:
  package: harbor.corp.internal/crossplane/function-environment-configs:v0.4.0
  packagePullPolicy: IfNotPresent
  runtimeConfigRef:
    name: function-hardened-runtime
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-auto-ready
spec:
  package: harbor.corp.internal/crossplane/function-auto-ready:v0.5.0
  packagePullPolicy: IfNotPresent
  runtimeConfigRef:
    name: function-hardened-runtime
```

### Сценарий 2: EnvironmentConfig для On-Premise инфраструктуры и мультитенантности

Создание объектов `EnvironmentConfig`, описывающих параметры физических площадок и квоты тенантов:

```yaml
# Глобальные параметры площадки (дата-центра)
apiVersion: apiextensions.crossplane.io/v1
kind: EnvironmentConfig
metadata:
  name: dc-spb-core
  labels:
    tier: infra
    site: dc-spb
data:
  clusterDomain: cluster.local
  dnsServer: 10.240.0.10
  storageClass: ceph-block-fast
  ingressClass: ingress-nginx-internal
---
# Параметры тенанта (команды billing)
apiVersion: apiextensions.crossplane.io/v1
kind: EnvironmentConfig
metadata:
  name: tenant-billing
  labels:
    tier: tenant
    tenant: billing
data:
  quotaCpu: "16"
  quotaMemory: 32Gi
  networkIsolation: enabled
```

### Сценарий 3: Полная Composition в режиме Pipeline (On-Premises Namespace + Quota)

Композиция формирует изолированное окружение приложения на базе `provider-kubernetes` без внешних зависимостей. Конвейер:
1. Загружает глобальный конфиг дата-центра по `Reference`.
2. Загружает параметры тенанта по `Selector` через значение `spec.parameters.tenantId` из XR.
3. Генерирует ресурсы `Namespace` и `ResourceQuota` с подстановкой значений из `EnvironmentConfig`.
4. Автоматически отслеживает готовность сгенерированных ресурсов.

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: onprem-tenant-environment
  labels:
    provider: kubernetes
spec:
  compositeTypeRef:
    apiVersion: platform.corp.internal/v1alpha1
    kind: XTenantNamespace
  mode: Pipeline
  pipeline:
    # Шаг 1: Загрузка EnvironmentConfig
    - step: load-environment
      functionRef:
        name: function-environment-configs
      input:
        apiVersion: environmentconfigs.fn.crossplane.io/v1beta1
        kind: Input
        spec:
          environmentConfigs:
            # Базовые параметры дата-центра
            - type: Reference
              ref:
                name: dc-spb-core
            # Динамические параметры конкретного тенанта
            - type: Selector
              selector:
                mode: Single
                matchLabels:
                  - type: Value
                    key: tier
                    value: tenant
                  - type: FromCompositeFieldPath
                    key: tenant
                    valueFromFieldPath: spec.parameters.tenantId

    # Шаг 2: Генерация ресурсов и применение патчей
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          # 2.1 Создание пространства имен
          - name: tenant-namespace
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
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
                fromFieldPath: spec.parameters.tenantId
                toFieldPath: spec.forProvider.manifest.metadata.name
              - type: FromEnvironmentFieldPath
                fromFieldPath: ingressClass
                toFieldPath: spec.forProvider.manifest.metadata.labels[corp.internal/ingress]

          # 2.2 Создание ResourceQuota с лимитами из EnvironmentConfig
          - name: tenant-quota
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: ResourceQuota
                    metadata:
                      name: compute-quota
                    spec:
                      hard:
                        requests.cpu: "2"
                        requests.memory: 4Gi
                        limits.cpu: "4"
                        limits.memory: 8Gi
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.tenantId
                toFieldPath: spec.forProvider.manifest.metadata.namespace
              - type: FromEnvironmentFieldPath
                fromFieldPath: quotaCpu
                toFieldPath: spec.forProvider.manifest.spec.hard[limits.cpu]
              - type: FromEnvironmentFieldPath
                fromFieldPath: quotaMemory
                toFieldPath: spec.forProvider.manifest.spec.hard[limits.memory]

    # Шаг 3: Автоматический расчет Ready-статуса
    - step: auto-ready
      functionRef:
        name: function-auto-ready
```

### Сценарий 4: Локальный Shift-Left рендеринг композиций без кластера

Локальная проверка работы функций через CLI Crossplane перед фиксацией изменений в Git:

```bash
# Подготовка окружения для рендеринга (входной XR, Composition, манифесты функций)
cat <<EOF > xr.yaml
apiVersion: platform.corp.internal/v1alpha1
kind: XTenantNamespace
metadata:
  name: billing-prod
spec:
  parameters:
    tenantId: billing
EOF

# Запуск рендера с пробросом EnvironmentConfig через флаг --extra-resources
crossplane composition render \
  xr.yaml \
  composition.yaml \
  functions.yaml \
  --extra-resources=environments.yaml \
  --include-context
```

Ожидаемый результат в консоли:
```yaml
---
apiVersion: platform.corp.internal/v1alpha1
kind: XTenantNamespace
metadata:
  name: billing-prod
status:
  conditions:
  - type: Ready
    status: "False"
    reason: WaitingForResources
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  annotations:
    crossplane.io/composition-resource-name: tenant-namespace
  name: billing-prod-tenant-namespace
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        labels:
          corp.internal/ingress: ingress-nginx-internal
          managed-by: crossplane
        name: billing
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  annotations:
    crossplane.io/composition-resource-name: tenant-quota
  name: billing-prod-tenant-quota
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: ResourceQuota
      metadata:
        name: compute-quota
        namespace: billing
      spec:
        hard:
          limits.cpu: "16"
          limits.memory: 32Gi
```

---

## Операции и команды

Таблица ключевых операций по управлению Composition Functions и отладке в кластере:

| Операция | Команда | Назначение |
|---|---|---|
| Статус функций | `kubectl get functions.pkg.crossplane.io` | Проверка установленных пакетов функций и их готовности (`INSTALLED`, `HEALTHY`) |
| Диагностика пакета | `kubectl describe function <name>` | Просмотр событий загрузки OCI-образа и создания сервиса |
| Логи пода рантайма | `kubectl logs -n crossplane-system -l pkg.crossplane.io/pkg=<name> -c package-runtime` | Чтение логов обработки gRPC-запросов конкретной функции |
| Проверка EnvironmentConfig | `kubectl get environmentconfigs -o wide` | Просмотр существующих конфигураций окружений в кластере |
| Локальный рендер | `crossplane composition render xr.yaml comp.yaml fn.yaml` | Базовый рендеринг манифестов без подключения к Kubernetes |
| Рендер с контекстом | `crossplane composition render ... --include-context` | Вывод внутреннего состояния шины контекста в итоговый YAML |
| Симуляция Observed | `crossplane composition render ... --observed-resources=dir/` | Симуляция уже созданных ресурсов для проверки логики `status` |
| Валидация схемы | `crossplane beta validate schemas manifests.yaml` | Проверка сгенерированных ресурсов на соответствие CRD схемам K8s |
| Сборка OCI-пакета | `crossplane xpkg build --package-root=. -o function.xpkg` | Локальная сборка OCI-пакета функции из Dockerfile/манифестов |
| Публикация в Harbor | `crossplane xpkg push harbor.corp.internal/crossplane/fn:v1.0.0 -f fn.xpkg` | Загрузка пакета функции в корпоративный защищенный реестр |

Примеры выполнения команд с ожидаемым выводом:

```bash
# 1. Проверка статуса установленных функций
kubectl get functions.pkg.crossplane.io
# → NAME                           INSTALLED   HEALTHY   PACKAGE                                                                    AGE
# → function-auto-ready            True        True      harbor.corp.internal/crossplane/function-auto-ready:v0.5.0                 42d
# → function-environment-configs   True        True      harbor.corp.internal/crossplane/function-environment-configs:v0.4.0        42d
# → function-patch-and-transform   True        True      harbor.corp.internal/crossplane/function-patch-and-transform:v0.8.2        42d

# 2. Локальная валидация сгенерированного вывода по схемам CRD
crossplane composition render xr.yaml composition.yaml functions.yaml \
  | crossplane beta validate schemas -
# → Total 2 resources: 2 valid, 0 invalid

# 3. Диагностика ошибок в поде функции
kubectl logs -n crossplane-system -l pkg.crossplane.io/pkg=function-patch-and-transform --tail=20
# → {"level":"info","ts":"2026-10-13T12:00:01Z","msg":"served gRPC request","step":"patch-and-transform","duration":"4.2ms"}
```

---

## Устранение неполадок (Troubleshooting)

### Типичные сбои и алгоритм диагностики

| Симптом / Ошибка | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `rpc error: code = Unavailable desc = connection error` | Под функции упал, не запустился или блокируется CNI / NetworkPolicy | `kubectl get pods -n crossplane-system -l pkg.crossplane.io/pkg=<name>` | Проверить права pull секрета в OCI-реестре; проверить статус пода функции и NetworkPolicy между контроллером и подом |
| `context deadline exceeded` при вызове функции | Функция зависла при обработке или превышен лимит времени выполнения | Проверить флаг `--function-runner-timeout` (по умолчанию 15s) в Crossplane | Оптимизировать шаблоны/KCL-скрипты; увеличить таймаут в аргументах пода Crossplane Core |
| `cannot find field in environment: "quotaCpu"` | В `EnvironmentConfig` отсутствует запрашиваемый ключ или селектор вернул 0 объектов | `crossplane composition render ... --include-context` | Проверить метки в `EnvironmentConfig` и селектор в `Composition`; добавить значение по умолчанию или проверить `transforms` |
| `multiple EnvironmentConfigs matched selector (mode: Single)` | Селектор нашел несколько объектов при строгом режиме `mode: Single` | `kubectl get environmentconfigs -l <labels>` | Уточнить метки для уникальности выборки либо переключить режим на `mode: Multi` с явным порядком слияния |
| XR зависает в `Synced: True`, `Ready: False` | Отсутствует шаг `function-auto-ready` либо один из composed-ресурсов не перешел в `Ready: True` | `kubectl describe <XR>` -> раздел `Conditions` и `Composed Resources` | Добавить `function-auto-ready` последним шагом в конвейер; устранить ошибку готовности в дочернем ресурсе |
| Под функции перезапускается по `OOMKilled` | Недостаточно оперативной памяти при обработке больших манифестов или списков | `kubectl describe pod -n crossplane-system <function-pod>` (Exit Code 137) | Увеличить `limits.memory` в привязанном `DeploymentRuntimeConfig` |

### Практические сценарии диагностики

#### 1. Ошибка связи gRPC с подом функции
Если контроллер Crossplane выводит в событиях XR:
```text
Warning  ComposeResources  ...  cannot run composition functions: cannot call RunFunction: rpc error: code = Unavailable desc = connection refused
```
1. Проверьте, существует ли сервис и под функции:
   ```bash
   kubectl get svc,pods -n crossplane-system -l pkg.crossplane.io/pkg=function-patch-and-transform
   ```
2. Если под в статусе `CrashLoopBackOff`, изучите логи контейнера:
   ```bash
   kubectl logs -n crossplane-system -l pkg.crossplane.io/pkg=function-patch-and-transform -c package-runtime
   ```
3. Если под `Running`, проверьте доступность порта 9443 из пода `crossplane` (проверка NetworkPolicy):
   ```bash
   kubectl exec -n crossplane-system deploy/crossplane -- nc -zvw3 function-patch-and-transform 9443
   # → function-patch-and-transform (10.96.120.45:9443) open
   ```

#### 2. Ошибка отсутствия данных окружения (Missing Context Key)
Если генерация падает с ошибкой:
```text
cannot compose resources: step "patch-and-transform" failed: cannot patch field: from path "storageClass" does not exist in environment
```
1. Запустите локальный рендеринг с включенным контекстом:
   ```bash
   crossplane composition render xr.yaml composition.yaml functions.yaml \
     --extra-resources=environments.yaml --include-context
   ```
2. Проверьте блок `context.apiextensions\.crossplane\.io/environment` в выводе. Если блок пустой — селектор шага `function-environment-configs` не нашел совпадений по меткам.

---

## Лучшие практики (Best Practices)

1. **Каноническая последовательность шагов конвейера:**
   Всегда организуйте конвейер функций по строгому шаблону:
   - **Шаг 1:** Загрузка окружения (`function-environment-configs`).
   - **Шаг 2..N:** Генерация и трансформация ресурсов (`function-patch-and-transform`, `function-kcl` или `function-go-templating`).
   - **Финальный шаг:** Агрегация условий готовности (`function-auto-ready`).

2. **Тюнинг отказоустойчивости и ресурсов (Hardening Runtime):**
   - Никогда не используйте функции в продакшене без привязки к `DeploymentRuntimeConfig`.
   - Задавайте явные `requests` и `limits` по CPU/Memory для подов функций, чтобы предотвратить деградацию control plane.
   - Запускайте функции минимум в 2 репликах (`replicas: 2`) для исключения простоев при перезапуске узлов.

3. **Изоляция и чистота функций (Pure Functions):**
   - Функции должны быть детерминированными и не зависеть от внешних сетевых вызовов (API серверов за пределами кластера) во время рендеринга. Любые внешние данные должны передаваться через Observed State или `EnvironmentConfig`.
   - Избегайте сохранения мутабельного состояния внутри подов функций: каждый вызов `RunFunction` должен зависеть только от входного запроса.

4. **Двухуровневая модель EnvironmentConfig:**
   - Разделяйте конфигурацию на два уровня:
     1. **Инфраструктурный уровень (Кластер/DC):** статические параметры площадки (DNS, StorageClasses, системные префиксы сетей), выбираемые по `Reference`.
     2. **Уровень тенанта (Команда/Проект):** динамические параметры (квоты, лимиты, доступы), выбираемые по `Selector` через поле `FromCompositeFieldPath`.

5. **Shift-Left проверка в GitOps CI:**
   - Встройте шаг выполнения `crossplane composition render` и `crossplane beta validate schemas` в CI пайплайн (GitLab CI, Woodpecker, Jenkins).
   - Ни один манифест `Composition` или `EnvironmentConfig` не должен попадать в GitOps-репозиторий без успешного локального прогона рендеринга.

6. **Управление пакетами в Air-Gapped контурах:**
   - Запретите скачивание пакетов из публичных реестров (`xpkg.crossplane.io`).
   - Настройте зеркалирование образов функций в корпоративный OCI-реестр с проверкой уязвимостей и подписью образов (Cosign).
   - Всегда фиксируйте точные версии пакетов (`v0.8.2`), избегая плавающих тегов (`latest`).

---

## Дополнительная информация

Официальная документация:
- [Crossplane: Compositions (Pipeline Mode)](https://docs.crossplane.io/latest/composition/compositions/)
- [Crossplane: Composition Functions Guide](https://docs.crossplane.io/latest/composition/composition-functions/)
- [Crossplane: Environment Configs](https://docs.crossplane.io/latest/composition/environment-configs/)
- [Crossplane CLI Reference: render and validate](https://docs.crossplane.io/latest/cli/command-reference/)

Смежные разделы базы знаний:
- [Управление ресурсами Kubernetes](./provider_kubernetes_setup.md) — декларативное управление объектами K8s через provider-kubernetes.
- [Мультитенантность в Crossplane](./multi_tenancy.md) — архитектура изоляции тенантов и связка с `EnvironmentConfig`.
- [Тестирование платформы](./testing_crossplane.md) — расширенные методики интеграционного тестирования и CI.
- [Интеграция с GitOps](./gitops_integration.md) — доставка манифестов и композиций через Argo CD и Flux.
- [Обзор Crossplane](./overview.md) — концептуальная архитектура Control Plane и XRD.
- [Защита зависимостей (Usage)](./usage_protection.md) — предотвращение каскадного удаления инфраструктуры.
- [Патчи, трансформы и PatchSets](./patch_transform.md) — детали `function-patch-and-transform`, типы патчей, трансформы, PatchSets.
- [Connection Details (проброс секретов)](./connection_details.md) — проброс учетных данных от MR к XR и потребителю.
- [Разработка кастомных Composition Functions](./custom_function_development.md) — создание функций на Go/Python поверх function-sdk, сборка и отладка.
