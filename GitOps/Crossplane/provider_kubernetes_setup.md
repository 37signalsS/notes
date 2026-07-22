# Crossplane: Управление ресурсами Kubernetes

## Определения

**provider-kubernetes** — это специализированный провайдер Crossplane для управления нативными объектами Kubernetes (Namespaces, ConfigMaps, Deployments и др.) как внутри текущего кластера, так и в удаленных кластерах. Он позволяет использовать декларативный подход Crossplane для оркестрации ресурсов самого Kubernetes, обеспечивая единый интерфейс управления инфраструктурой и приложениями.

## Базовые концепции

### Ключевые сценарии использования

- **Управление компонентами кластера:** Декларативное описание системных ресурсов (RBAC, секреты, квоты).
- **Мультикластерная оркестрация:** Централизованное управление парком кластеров из одной точки (Control Plane).
- **Композиция приложений:** Создание высокоуровневых абстракций (XRD), объединяющих облачную инфраструктуру и ресурсы K8s (например, S3-бакет + K8s Secret с ключами).
- **Соблюдение стандартов:** Гарантия идентичности конфигурации во всех подконтрольных кластерах через непрерывную сверку.

## Практические сценарии

### Предварительные требования

- **Управляющий кластер:** Установленный Crossplane v1.16+ (рекомендуется v2.x). Инструкция по установке: [Настройка Crossplane](./provider_yandex_cloud_setup.md).
- **Доступ:** Права `cluster-admin` в управляющем кластере.

### Установка провайдера

Создайте и примените манифест `provider.yaml` (версия актуальна на 2026 год):

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.2.0
```

```bash
kubectl apply -f provider.yaml
# → provider.pkg.crossplane.io/provider-kubernetes created
```

### Конфигурация для локального кластера (In-Cluster)

Для управления ресурсами в том же кластере, где запущен Crossplane, используется `InjectedIdentity`.

**1. Настройка прав:**
Провайдеру нужны права для создания объектов. Настройте `ClusterRoleBinding` для его `ServiceAccount`:

```bash
SA=$(kubectl -n crossplane-system get sa -o name | grep provider-kubernetes | sed -e 's|serviceaccount\/|crossplane-system:|g')
kubectl create clusterrolebinding provider-kubernetes-admin-binding \
  --clusterrole cluster-admin \
  --serviceaccount="${SA}"
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

Управление удаленным кластером осуществляется через секрет с `kubeconfig`.

**1. Создание секрета в управляющем кластере:**

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

### Управление объектами (API v1beta1)

Для создания ресурсов используется тип `Object`.

**Пример: Создание Namespace и ConfigMap во внешнем кластере:**

```yaml
apiVersion: kubernetes.crossplane.io/v1beta1
kind: Object
metadata:
  name: remote-app-ns
spec:
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
---
apiVersion: kubernetes.crossplane.io/v1beta1
kind: Object
metadata:
  name: remote-configmap
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: app-config
        namespace: staging-app
      data:
        environment: "staging"
        feature_flag: "true"
  providerConfigRef:
    name: remote-cluster-config
```

## Продвинутые возможности

### Режим только для чтения (Observe-only)

Если вы хотите, чтобы Crossplane только отслеживал состояние объекта, но не изменял его, используйте политику управления:

```yaml
spec:
  managementPolicies: ["Observe"]
```

### Использование в композициях (Patching)

В 2026 году стандартным паттерном является передача данных из облачных ресурсов в ресурсы Kubernetes через патчи. Например, передача `connection string` из Managed Database в K8s Secret.

```yaml
# Фрагмент Composition
- name: kubernetes-secret
  base:
    apiVersion: kubernetes.crossplane.io/v1beta1
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
```

## Мониторинг и отладка

Проверка статуса объектов:

```bash
kubectl get objects
# NAME             READY   SYNCED   AGE
# remote-app-ns    True    True     5m
```

Просмотр ошибок синхронизации:

```bash
kubectl describe object remote-app-ns
```

Логи контроллера провайдера:

```bash
kubectl -n crossplane-system logs -l app=crossplane-provider-kubernetes -c provider-kubernetes
```

## Дополнительная информация

- [Crossplane Overview](./overview.md) — общие концепции и архитектура.
- [GitOps Integration](./gitops_integration.md) — развертывание через ArgoCD.
- [Yandex Cloud Provider](./provider_yandex_cloud_setup.md) — управление облачной инфраструктурой.

Внешние ресурсы:
- [Provider Kubernetes GitHub](https://github.com/crossplane-contrib/provider-kubernetes)
- [Official Documentation](https://docs.crossplane.io/latest/concepts/providers/)
