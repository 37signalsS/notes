# Crossplane: Управление ресурсами Kubernetes

## Определения

**provider-kubernetes** — кроссплатформенный Crossplane-провайдер для управления нативными ресурсами Kubernetes в любом кластере. Позволяет использовать Crossplane **Composition API (Application Programming Interface)** для создания абстракций над Kubernetes-ресурсами.

## Базовые концепции

### Сценарии использования

- **Декларативное управление компонентами кластера**: Namespace, ConfigMap, Secret, **RBAC (Role-Based Access Control)**.
- **Расширение GitOps**: Управление ресурсами, которые не поддерживаются ArgoCD/Flux напрямую.
- **Мультикластерное управление**: Централизованное управление несколькими кластерами через Crossplane.
- **Создание платформенных абстракций**: Использование **Composition API** для объединения нескольких Kubernetes-ресурсов в одну логическую единицу.

## Практические сценарии

### Предварительные требования

- **Кластер Kubernetes**: Локальный (Minikube, Kind) или облачный
- **Установленный Crossplane**: Следуйте шагам по установке из [настройки Yandex Cloud провайдера](./provider_yandex_cloud_setup.md#установка-crossplane-и-его-cli)

### Установка и конфигурация provider-kubernetes

#### Шаг 1: Установка провайдера

Создайте файл `kubernetes-provider.yaml`:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.2.0
```

Примените манифест:

```bash
kubectl apply -f kubernetes-provider.yaml
```

Проверьте статус установки (может занять 1-2 минуты):

```bash
kubectl get provider
# NAME                           INSTALLED   HEALTHY   AGE
# provider-kubernetes            True        True      30s
```

#### Шаг 2: Настройка ProviderConfig

Для управления ресурсами провайдеру требуются права администратора кластера. Создайте **ClusterRoleBinding** для **ServiceAccount (SA)** провайдера:

```bash
# Получение имени ServiceAccount провайдера
SA=$(kubectl -n crossplane-system get sa -o name | grep provider-kubernetes | sed -e 's|serviceaccount\/|crossplane-system:|g')

# Создание привязки роли
kubectl create clusterrolebinding provider-kubernetes-admin-binding --clusterrole cluster-admin --serviceaccount="${SA}"
```

Затем создайте файл `config-in-cluster.yaml` для `ProviderConfig`:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: in-cluster-config
spec:
  # Использует учетные данные ServiceAccount, под которым запущен провайдер
  credentials:
    source: InjectedIdentity
```

Примените манифест:

```bash
kubectl apply -f config-in-cluster.yaml
```

Проверьте создание:

```bash
kubectl get providerconfig
# NAME                AGE
# in-cluster-config   10s
```

### Развертывание ресурсов Kubernetes

#### Сценарий 1: Создание Namespace

Для создания нативных ресурсов Kubernetes через Crossplane используется тип `Object`.

Создайте файл `nginx-namespace.yaml`:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha2
kind: Object
metadata:
  name: nginx-namespace
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: crossplane-nginx-example
        labels:
          app.crossplane.io/example: "true"
  providerConfigRef:
    name: in-cluster-config
```

Примените и проверьте:

```bash
kubectl apply -f nginx-namespace.yaml
kubectl get ns crossplane-nginx-example # → статус Active
```

#### Сценарий 2: Создание Deployment

Создайте файл `nginx-deployment.yaml`:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha2
kind: Object
metadata:
  name: nginx-deployment
spec:
  forProvider:
    manifest:
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: nginx-deployment
        namespace: crossplane-nginx-example
        labels:
          app: nginx
      spec:
        replicas: 1
        selector:
          matchLabels:
            app: nginx
        template:
          metadata:
            labels:
              app: nginx
          spec:
            containers:
            - name: nginx
              image: nginx:1.26.4
              ports:
              - containerPort: 80
  providerConfigRef:
    name: in-cluster-config
```

Примените и проверьте:

```bash
kubectl apply -f nginx-deployment.yaml
kubectl get deployment -n crossplane-nginx-example
kubectl get pods -n crossplane-nginx-example
```

### Мониторинг и отладка

Проверьте статус ресурса Crossplane:

```bash
kubectl get object nginx-deployment -o yaml
```

Основные поля в `status`:

- `Ready: True` — ресурс успешно синхронизирован с кластером.
- `Ready: False` — возникла ошибка. Проверьте `status.conditions` для диагностики.

Просмотр логов провайдера:

```bash
kubectl -n crossplane-system logs -l app=crossplane-provider-kubernetes
```

## Дополнительная информация

Настройка провайдера для Yandex Cloud описана в [Provider Yandex Cloud](./provider_yandex_cloud_setup.md), интеграция с ArgoCD — в [GitOps Integration](./gitops_integration.md).

Внешние ресурсы:

- Официальная документация provider-kubernetes: [github.com/crossplane-contrib/provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes)
