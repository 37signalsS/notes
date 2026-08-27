# Crossplane: Управление ресурсами Kubernetes

## Определения

**provider-kubernetes** — это специализированный провайдер Crossplane для управления нативными объектами Kubernetes (Namespaces, ConfigMaps, Deployments, CRD, любыми ресурсами через `Object`) как внутри текущего кластера, так и в удаленных кластерах. Он позволяет использовать декларативный подход Crossplane для оркестрации самих ресурсов Kubernetes, обеспечивая единый интерфейс управления инфраструктурой и приложениями из одного control plane.

В 2026 году провайдер полностью интегрирован с архитектурой **Crossplane v2.x** и выпущен в версии **v1.3.0** (август 2026). С v1.0.0 провайдер совместим с Crossplane v2: поддерживает Namespaced Managed Resources, Server-Side Apply (SSA) для бесконфликтной синхронизации, а также новые API-группы `kubernetes.m.crossplane.io` (namespace-scoped MR и `ClusterProviderConfig`) наряду с классическими cluster-scoped `kubernetes.crossplane.io`. В v1.0.0 также была **удалена поддержка External Secret Store (ESS)** — креденшелы теперь только через `Secret` (см. раздел «Безопасность»).

## Базовые концепции

### Ключевые сценарии использования

- **Мультикластерная оркестрация (Fleet Management):** Централизованное управление парком кластеров из одной точки (Control Plane) — создание Namespace, ConfigMap, RBAC, операторов в десятках кластеров по одному манифесту.
- **Композиция приложений:** Создание высокоуровневых абстракций (XRD), объединяющих облачную инфраструктуру (например, Yandex PostgreSQL) и ресурсы K8s (Secrets, ConfigMaps, Deployments) в единый заявленный ресурс.
- **Импорт существующих ресурсов:** Использование режима `Observe`/`ObserveOnly` для отслеживания ресурсов, созданных вне Crossplane (системные Namespace, Ingress-контроллеры), без их изменения.
- **Соблюдение стандартов:** Гарантированное развертывание обязательных системных компонентов (мониторинг, агенты безопасности, NetworkPolicy, LimitRange) во всех новых кластерах.

### Режимы управления (Management Policies)

Каждый `Object` управляется через `spec.managementPolicies` — список действий, которые Crossplane выполняет над ресурсом. Это ключевое отличие от классического «владения» ресурсом:

| Политика | Действие Crossplane |
| --- | --- |
| `All` (или `*`) | Полное управление: Create, Update, Delete, Observe, LateInitialize (значение по умолчанию) |
| `Create` | Создаёт ресурс, если его нет |
| `Update` | Применяет изменения из манифеста |
| `Delete` | Удаляет ресурс при удалении `Object` |
| `Observe` | Только читает состояние, не изменяет |
| `LateInitialize` | Дозаполняет `status` значениями, заданными облаком/кластером по умолчанию |

Комбинация `["Create","Update","Observe"]` означает «создай и поддерживай, но не удаляй» — ресурс останется в кластере после удаления `Object` из Git.

### API-группы и область видимости (Crossplane v2)

Провайдер предоставляет два набора API:

- **Классический (cluster-scoped):** `kubernetes.crossplane.io/v1alpha1` — `ProviderConfig`, `Object` видны во всём кластере. Простейший вариант, используется в большинстве примеров ниже.
- **Crossplane v2 (namespace-scoped):** `kubernetes.m.crossplane.io/v1beta1` — `Object` создаются в конкретном Namespace (изоляция команд/тенантов), а `ProviderConfig` становится namespace-scoped; добавлен cluster-scoped `ClusterProviderConfig.kubernetes.m.crossplane.io`. Если `spec.providerConfigRef.kind` не указан, по умолчанию берётся `ClusterProviderConfig` с именем `default`.

## Архитектура и принцип работы

Провайдер — это Deployment в `crossplane-system`, который реконсилирует `Object`:

1. Контроллер читает `Object`, получает `ProviderConfig` (через `spec.providerConfigRef`) и учётные данные из него.
2. Через динамический Kubernetes-клиент он применяет вложенный манифест (`spec.forProvider.manifest`) к целевому кластеру.
3. Применение использует **Server-Side Apply** с field manager `provider-kubernetes`, поэтому конфликтуют только те поля, которые явно заданы в манифесте (остальные управляются другими контроллерами — ArgoCD, HPA, операторами).
4. Состояние ресурса копируется в `status.atProvider` `Object`; готовность определяется `readinessChecks`.

Два источника идентификации (`spec.credentials.source`):
- **InjectedIdentity** — провайдер использует собственный ServiceAccount-токен (projected token через TokenRequest). RBAC всё равно нужно выдать этому SA (см. ниже).
- **Secret** — креденшелы (kubeconfig или токен) читаются из `Secret`, на который ссылается `secretRef`. Используется для удалённых кластеров.

## Практические сценарии

### Предварительные требования

- **Управляющий кластер:** Kubernetes v1.28+ с установленным Crossplane v2.x (инструкция: [Настройка Crossplane](./overview.md)).
- **Пакетный менеджер:** Helm v3.10+ (с поддержкой OCI).
- **Доступ:** Права `cluster-admin` для первичной настройки связи и RBAC провайдера (временно — позже сузить до scoped RBAC, см. раздел «Безопасность»).

### Установка провайдера

Рекомендуется использовать актуальную версию провайдера (август 2026 — **v1.3.0**):

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0
```

```bash
kubectl apply -f provider.yaml
# → provider.pkg.crossplane.io/provider-kubernetes created
```

Проверка успешной установки и здоровья провайдера:

```bash
kubectl get providers
# → NAME                 INSTALLED  HEALTHY  PACKAGE
#   provider-kubernetes  True       True     xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0

kubectl get providerrevisions
# → детали активной ревизии пакета (при HEALTHY=False см. kubectl describe providerrevisions)

kubectl -n crossplane-system get deploy -l pkg.crossplane.io/provider=provider-kubernetes
# → проверка, что под провайдера поднялся
```

> В v1.3.0 провайдер также экспонирует health (`/healthz`) и readiness (`/readyz`) пробы, а также поддерживает настраиваемую `DeletionPropagationPolicy` для `Object`.

### Конфигурация для локального кластера (In-Cluster)

Для управления ресурсами в том же кластере, где запущен Crossplane.

**1. Настройка RBAC:**
Провайдеру необходимы права для управления объектами. Создайте `ClusterRoleBinding` для ServiceAccount провайдера (имя SA генерируется автоматически):

```bash
# Получение имени ServiceAccount провайдера
SA_NAME=$(kubectl -n crossplane-system get sa -o jsonpath='{.items[?(@.metadata.annotations.pkg\.crossplane\.io/package=="provider-kubernetes")].metadata.name}')

kubectl create clusterrolebinding provider-kubernetes-admin-binding \
  --clusterrole cluster-admin \
  --serviceaccount="crossplane-system:${SA_NAME}"
```

**Принцип наименьших привилегий (рекомендуется вместо cluster-admin):** выдавайте провайдеру только те API-группы/ресурсы, которыми он реально управляет. Пример scoped `ClusterRole` (создаёт/обновляет/удаляет namespaces, configmaps, deployments, а читает всё для Observe):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: provider-kubernetes-scoped
rules:
  - apiGroups: [""]
    resources: ["namespaces", "configmaps", "secrets", "serviceaccounts"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["get", "list", "watch"]   # только чтение для режимов Observe/ObserveOnly
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: provider-kubernetes-scoped-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: provider-kubernetes-scoped
subjects:
  - kind: ServiceAccount
    name: <SA_NAME>
    namespace: crossplane-system
```

**2. Создание ProviderConfig:**

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: InjectedIdentity
```

### Конфигурация для внешнего кластера (Multi-cluster)

Управление удаленным кластером через `kubeconfig`.

**1. Создание секрета с учетными данными:**

```bash
kubectl -n crossplane-system create secret generic remote-cluster-kubeconfig \
  --from-file=kubeconfig=/path/to/remote/kubeconfig
```

> **Важно:** провайдер читает `kubeconfig` как статичные креденшелы. Kubeconfig с `exec`-плагином аутентификации (например, `aws eks get-token`, `gcloud`, Teleport `tbot`) **не сработает внутри пода провайдера**, так как в нём нет соответствующих бинарей/переменных окружения. Используйте статичный токен/клиентский сертификат или ServiceAccount-токен целевого кластера, либо вынесите получение кредов в External Secrets Operator (см. [GitOps Integration](./gitops_integration.md)).

**2. Создание ProviderConfig для удаленного кластера:**

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: remote-cluster-config
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: remote-cluster-kubeconfig
      key: kubeconfig
```

### Управление объектами (Resource Management)

Основной тип ресурса — `Object`. В 2026 году рекомендуется использовать **Management Policies** для точного контроля жизненного цикла.

**Пример: Создание Namespace с политикой «не удалять в облаке»:**

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: staging-namespace
spec:
  managementPolicies: ["Create", "Update", "Observe"] # Ресурс останется в K8s при удалении Object в Crossplane
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: staging-app
        labels:
          managed-by: crossplane
  providerConfigRef:
    name: remote-cluster-config
```

**Пример: реальный рабочий объект (ConfigMap + Deployment) в удалённом кластере:**

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: app-configmap
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: app-config
        namespace: staging-app
      data:
        LOG_LEVEL: info
  providerConfigRef:
    name: remote-cluster-config
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: app-deployment
spec:
  forProvider:
    manifest:
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: web
        namespace: staging-app
      spec:
        replicas: 2
        selector:
          matchLabels: { app: web }
        template:
          metadata:
            labels: { app: web }
          spec:
            containers:
              - name: web
                image: nginx:1.27
  providerConfigRef:
    name: remote-cluster-config
```

**Политика удаления (DeletionPropagationPolicy, v1.3.0+):** управляет тем, как Kubernetes удаляет объект при удалении `Object` из Crossplane (`spec.forProvider.deletionPropagationPolicy`): `Background` (по умолчанию — зависимые удаляются асинхронно), `Foreground` (сначала зависимые, потом объект), `Orphan` (оставить зависимые).

```yaml
spec:
  forProvider:
    deletionPropagationPolicy: Foreground
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: staging-app
```

Полная проверка жизненного цикла — см. раздел «Отладка».

## Продвинутые возможности

### Server-Side Apply (SSA)
Для предотвращения конфликтов с другими контроллерами (например, ArgoCD или HPA) провайдер использует SSA. Это позволяет Crossplane управлять только теми полями, которые явно указаны в манифесте `Object`. При конфликте владения полем provider-kubernetes принудительно забирает владение (force conflicts). Подробнее: [SSA в provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes/blob/main/docs/server-side-apply.md).

### Readiness Checks (Проверки готовности)
Вы можете определить, когда ресурс считается готовым, на основе полей вложенного объекта:

```yaml
spec:
  readinessChecks:
    - type: MatchString
      fieldPath: "status.phase"
      matchString: "Active"
```

Другие типы: `MatchCondition` (проверка условия по `status.conditions`), `MatchTrue`/`MatchFalse`, `NonEmpty`, `None`.

### Передача данных (Patching в композициях)
Передача учетных данных из облачных ресурсов в ресурсы Kubernetes:

```yaml
# Фрагмент Composition (v2.x)
- name: kubernetes-secret
  base:
    apiVersion: kubernetes.crossplane.io/v1alpha1
    kind: Object
    spec:
      forProvider:
        manifest:
          apiVersion: v1
          kind: Secret
          metadata:
            namespace: default
  patches:
    - fromFieldPath: "status.atProvider.connectionString"
      toFieldPath: "spec.forProvider.manifest.data.DB_URL"
      transforms:
        - type: string
          string:
            type: Convert
            convert: ToBase64
```

### Namespace-scoped MR и ClusterProviderConfig (Crossplane v2)
Изоляция тенантов: `Object` в неймспейсе + `ProviderConfig` в том же неймспейсе, либо cluster-scoped `ClusterProviderConfig`:

```yaml
apiVersion: kubernetes.m.crossplane.io/v1beta1
kind: Object
metadata:
  name: tenant-namespace
  namespace: team-a
spec:
  providerConfigRef:
    name: cluster-default      # ссылается на ClusterProviderConfig
    kind: ClusterProviderConfig
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: team-a-apps
```

### ObservedObjectCollection (только чтение)
Новый тип для агрегации состояния нескольких объектов без управления ими (read-only инвентаризация кластеров):

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ObservedObjectCollection
metadata:
  name: cluster-inventory
spec:
  providerConfigRef:
    name: remote-cluster-config
  apiVersion: v1
  kind: Namespace
```

## Безопасность и отладка

### Безопасность
- **Принцип наименьших привилегий:** Избегайте `cluster-admin`. Создавайте специфичные `ClusterRole`/`Role` для провайдера, ограниченные нужными API-группами (пример выше).
- **Namespace-scoped изоляция:** В Crossplane v2 создавайте `Object` в конкретных Namespace (`kubernetes.m.crossplane.io`) для изоляции команд и лимитов ресурсов.
- **Креденшелы только через Secret:** ESS (External Secret Store) в provider-kubernetes удалён с v1.0.0. Источником кредов может быть только `Secret` (локально — `InjectedIdentity`, для удалённых кластеров — `kubeconfig`/`token` в Secret). Для безопасной доставки кредов используйте External Secrets Operator + Vault или SOPS (см. [управление секретами в GitOps](../secrets_encryption.md) и [GitOps Integration](./gitops_integration.md)).
- **Не коммитьте kubeconfig в Git:** храните `remote-cluster-kubeconfig` вне репозитория; в GitOps-сценариях генерируйте его через ESO или шифруйте SOPS.

### Отладка
Просмотр состояния всех управляемых объектов:
```bash
kubectl get objects
```

Детальный анализ конкретного ресурса и событий (Events):
```bash
kubectl describe object <name>
```

Проверка логов провайдера (критично при ошибках доступа в удаленные кластеры):
```bash
kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-kubernetes -c provider-kubernetes
```

Состояние и события ProviderConfig и самого провайдера:
```bash
kubectl get providerconfig
kubectl describe providerconfig <name>
kubectl describe provider provider-kubernetes
```

Трассировка цепочки реконсиляции (входит ли ресурс в желаемое состояние):
```bash
crossplane alpha trace object <name>
```

### Troubleshooting

| Симптом | Вероятная причина | Диагностика / решение |
| --- | --- | --- |
| `Object` в `Creating` вечно | Неверный `ProviderConfig`/креденшелы или нет RBAC | `kubectl describe providerconfig`, `kubectl -n crossplane-system get secret`, проверить RBAC SA, логи провайдера |
| `Synced=False`, ошибка `forbidden` | Недостаточно прав у SA провайдера | Расширить scoped `ClusterRole` под нужные API-группы/ресурсы |
| Удалённый кластер недоступен | `exec`-плагин в kubeconfig / нет сети | Заменить kubeconfig на статичные креды; проверить сеть из пода провайдера |
| Конфликт полей с ArgoCD | Оба контроллера пишут одно поле | SSA: оставить поле только в одном источнике или использовать `force` со стороны provider-kubernetes |
| `HEALTHY=False` у провайдера | Проблема ревизии пакета | `kubectl describe providerrevisions`, проверить `package` и совместимость с Crossplane v2 |
| Ресурс не удаляется при удалении `Object` | `managementPolicies` без `Delete` (или `DeletionPropagationPolicy`) | Добавить `Delete` в `managementPolicies` либо удалить ресурс вручную |
| `ObservedGeneration` не меняется | `ObserveOnly`/`Observe` — режим только чтения | Ожидаемо; перейти на `All` для управления |

## Дополнительная информация

- [Crossplane Overview](./overview.md) — фундаментальные концепции.
- [GitOps Integration](./gitops_integration.md) — совместная работа с ArgoCD и Flux, безопасная доставка кредов (ESO/SOPS).
- [Yandex Cloud Provider](./provider_yandex_cloud_setup.md) — пример настройки облачного провайдера.

Внешние ресурсы:
- [Provider Kubernetes Docs](https://docs.crossplane.io/latest/packages/providers/)
- [GitHub: provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes)
- [Server-Side Apply в provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes/blob/main/docs/server-side-apply.md)
