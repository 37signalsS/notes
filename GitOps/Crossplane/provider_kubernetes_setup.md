# Crossplane: Управление ресурсами Kubernetes

## Определения

**provider-kubernetes** — это специализированный провайдер Crossplane для управления нативными объектами Kubernetes (Namespaces, ConfigMaps, Deployments и др.) как внутри текущего кластера, так и в удаленных кластерах. Он позволяет использовать декларативный подход Crossplane для оркестрации ресурсов самого Kubernetes, обеспечивая единый интерфейс управления инфраструктурой и приложениями.

В 2026 году провайдер полностью интегрирован с архитектурой **Crossplane v2.x**, поддерживая Namespaced Managed Resources и Server-Side Apply (SSA) для бесконфликтной синхронизации.

## Базовые концепции

### Ключевые сценарии использования

- **Мультикластерная оркестрация:** Централизованное управление парком кластеров (Fleet Management) из одной точки (Control Plane).
- **Композиция приложений:** Создание высокоуровневых абстракций (XRD), объединяющих облачную инфраструктуру (например, Yandex PostgreSQL) и ресурсы K8s (Secrets, ConfigMaps, Deployments).
- **Импорт существующих ресурсов:** Использование режима `Observe` для отслеживания ресурсов, созданных вне Crossplane (например, системных Namespace или Ingress-контроллеров).
- **Соблюдение стандартов:** Гарантированное развертывание обязательных системных компонентов (мониторинг, агенты безопасности) во всех новых кластерах.

## Практические сценарии

### Предварительные требования

- **Управляющий кластер:** Kubernetes v1.28+ с установленным Crossplane v2.4+ (инструкция: [Настройка Crossplane](./overview.md)).
- **Пакетный менеджер:** Helm v3.10+ (с поддержкой OCI).
- **Доступ:** Права `cluster-admin` для настройки первоначальных связей и RBAC провайдера.

### Установка провайдера

Рекомендуется использовать актуальную версию провайдера (август 2026):

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.2.1
```

```bash
kubectl apply -f provider.yaml
# → provider.pkg.crossplane.io/provider-kubernetes created
```

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

**Пример: Создание Namespace с политикой "не удалять в облаке":**

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

## Продвинутые возможности

### Server-Side Apply (SSA)
Для предотвращения конфликтов с другими контроллерами (например, ArgoCD или HPA) провайдер использует SSA. Это позволяет Crossplane управлять только теми полями, которые явно указаны в манифесте `Object`.

### Readiness Checks (Проверки готовности)
Вы можете определить, когда ресурс считается готовым, на основе полей вложенного объекта:

```yaml
spec:
  readinessChecks:
    - type: MatchString
      fieldPath: "status.phase"
      matchString: "Active"
```

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

## Безопасность и отладка

### Безопасность
- **Принцип наименьших привилегий:** Избегайте использования `cluster-admin`. Создавайте специфичные `ClusterRole` для провайдера, ограниченные нужными API-группами.
- **Namespaced Managed Resources:** В Crossplane v2.x создавайте `Object` в конкретных Namespace для изоляции команд и использования лимитов ресурсов.

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

## Дополнительная информация

- [Crossplane Overview](./overview.md) — фундаментальные концепции.
- [GitOps Integration](./gitops_integration.md) — совместная работа с ArgoCD и Flux.
- [Yandex Cloud Provider](./provider_yandex_cloud_setup.md) — пример настройки облачного провайдера.

Внешние ресурсы:
- [Provider Kubernetes Docs](https://docs.crossplane.io/latest/concepts/providers/)
- [GitHub: provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes)
