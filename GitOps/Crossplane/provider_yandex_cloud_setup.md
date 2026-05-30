# Crossplane: Настройка с провайдером Yandex Cloud

## Определения

**provider-yandex-cloud** — официальный кроссплатформенный Crossplane-провайдер от Yandex Cloud для управления ресурсами облака (Compute, **VPC (Virtual Private Cloud)**, Managed Services) через Kubernetes **API (Application Programming Interface)**.

> **Важно:** Репозиторий `crossplane-contrib/provider-yandex-cloud` архивирован (октябрь 2025). Используйте официальный провайдер от Yandex Cloud: `yandexcloud/crossplane-provider-yc`.

## Базовые концепции

### Архитектура интеграции

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     Git     │────▶│   ArgoCD    │────▶│ Crossplane  │────▶│  Yandex     │
│  Repository │     │  (Sync)     │     │ (Reconcile) │     │   Cloud     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Поддерживаемые ресурсы Yandex Cloud

- **Compute**: Виртуальные машины, группы ВМ, диски, снапшоты.
- **VPC**: Сети, подсети, статические IP-адреса.
- **Managed Services**: Kubernetes, PostgreSQL, MySQL, Redis.
- **IAM (Identity and Access Management)**: Сервисные аккаунты, API-ключи.

Обзор Crossplane и его возможностей см. в [Crossplane: обзор](./overview.md).

## Практические сценарии

### Предварительные требования

- **Кластер Kubernetes**: Локальный (Minikube, Kind) или облачный.
- **Helm**: Пакетный менеджер, должен быть установлен и настроен.
- **kubectl**: **CLI (Command Line Interface)** для Kubernetes, установлен и настроен.
- **Argo CD**: (Опционально) Развернут в кластере для реализации GitOps-подхода.
- **Yandex Cloud CLI**: Установлен и настроен (`yc init`).

### Установка Crossplane и его CLI

**Шаг 1: Добавление Helm-репозитория Crossplane**

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
```

**Шаг 2: Установка чарта Crossplane**

```bash
helm install crossplane crossplane-stable/crossplane --namespace crossplane-system --create-namespace
```

**Шаг 3: Проверка установки**

Убедитесь, что все поды в `crossplane-system` перешли в состояние `Running`:

```bash
kubectl get pods -n crossplane-system
# NAME                                           READY   STATUS    RESTARTS   AGE
# crossplane-7b8c9d4e5f-abcde                    1/1     Running   0          1m
# crossplane-rbac-manager-6f7g8h9i0j-fghij       1/1     Running   0          1m
```

**Шаг 4: Установка Crossplane CLI**

Скачайте бинарный файл для вашей ОС с [официальной страницы релизов](https://github.com/crossplane/crossplane/releases) и поместите его в директорию, доступную в `PATH`. **CLI** позволяет управлять пакетами и конфигурациями Crossplane.

### Установка и конфигурация провайдера

**Шаг 1: Установка провайдера Yandex Cloud**

Используйте **Crossplane CLI** для установки официального пакета провайдера от Yandex Cloud:

```bash
crossplane xpkg install provider xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.5.1
```

> **Примечание:** Проверьте актуальную версию на [Yandex Cloud Marketplace](https://yandex.cloud/en/marketplace/products/yc/crossplane) или [Upbound Registry](https://upbound.io/marketplace/providers/yandexcloud/crossplane-provider-yc).

**Альтернативный способ: Установка через Helm от Yandex Cloud**

```bash
helm pull oci://cr.yandex/yc-marketplace/yandex-cloud/crossplane/crossplane \
  --version v1.20.6 \
  --untar && \
helm install \
  --namespace crossplane-system \
  --create-namespace \
  --set-file providerJetYc.creds=key.json \
  crossplane ./crossplane/
```

**Шаг 2: Проверка установленных CRD (Custom Resource Definitions)**

После установки провайдера в кластере появятся новые типы ресурсов:

```bash
kubectl get crd | grep yandex-cloud.jet.crossplane.io
# computeinstances.compute.yandex-cloud.jet.crossplane.io
# kubernetesclusters.k8s.yandex-cloud.jet.crossplane.io
# managedpostgresqlclusters.sql.yandex-cloud.jet.crossplane.io
# networks.vpc.yandex-cloud.jet.crossplane.io
```

**Шаг 3: Создание сервисного аккаунта в Yandex Cloud**

- В консоли Yandex Cloud перейдите в **Identity and Access Management** → **Сервисные аккаунты**.
- Создайте аккаунт (например, `crossplane-sa`) с ролью `editor` на ваш каталог.
- Создайте **авторизованный ключ** для этого аккаунта и скачайте JSON-файл с ключами.

Или через CLI:

```bash
yc iam service-account create --name crossplane-sa
yc iam service-account key create --service-account-name crossplane-sa --output sa-key.json
yc resource-manager folder add-access-binding --name <folder-name> --role editor --service-account-id <sa-id>
```

**Шаг 4: Создание секрета с учетными данными**

Создайте секрет Kubernetes, который будет содержать скачанный JSON-ключ:

```bash
kubectl create secret generic yandex-cloud-credentials \
  --from-file=credentials=./sa-key.json \
  --namespace crossplane-system
```

**Шаг 5: Настройка ProviderConfig**

Этот ресурс связывает провайдер с учетными данными. Создайте файл `provider-config.yaml`:

```yaml
apiVersion: yandex-cloud.jet.crossplane.io/v1beta1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: Secret
    secretRef:
      name: yandex-cloud-credentials
      namespace: crossplane-system
      key: credentials
    cloudId: <YOUR_YANDEX_CLOUD_CLOUD_ID>
    folderId: <YOUR_YANDEX_CLOUD_FOLDER_ID>
```

Примените манифест:

```bash
kubectl apply -f provider-config.yaml
kubectl get providerconfig
# NAME      READY   SYNCED   AGE
# default   True    True     10s
```

### Развертывание VM с Nginx через GitOps

Этот сценарий демонстрирует, как с помощью Argo CD и Crossplane развернуть виртуальную машину в Yandex Cloud.

**Шаг 1: Подготовка Git-репозитория с манифестом**

Создайте файл `vm.yaml` в вашем Git-репозитории:

```yaml
apiVersion: compute.yandex-cloud.jet.crossplane.io/v1beta1
kind: ComputeInstance
metadata:
  name: nginx-vm
spec:
  forProvider:
    folderId: <YOUR_YANDEX_CLOUD_FOLDER_ID>
    zone: ru-central1-a
    platformId: standard-v3
    resources:
      memory: 2G
      cores: 2
      coreFraction: 20
    bootDisk:
      initializeParams:
        imageId: fd80m5rnb5lsvj0s2k91
        size: 15G
    networkInterfaces:
      - subnetId: <YOUR_SUBNET_ID>
        primaryV4Address: {}
    metadata:
      user-data: |
        #cloud-config
        packages:
          - nginx
        services:
          nginx:
            enabled: true
  providerConfigRef:
    name: default
```

**Шаг 2: Создание ArgoCD Application**

Создайте манифест `Application` для Argo CD:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: nginx-vm-from-crossplane
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-repo/your-crossplane-gitops.git
    targetRevision: HEAD
    path: crossplane/resources
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Шаг 3: Синхронизация и проверка**

После применения манифеста `Application` Argo CD начнет синхронизацию:

```bash
# Статус ArgoCD приложения
argocd app get nginx-vm-from-crossplane

# Статус ресурса Crossplane
kubectl get computeinstance nginx-vm -o yaml

# Внешний IP ВМ (появится после создания)
kubectl get computeinstance nginx-vm -o jsonpath='{.status.atProvider.externalIp}'
```

### Мониторинг и отладка

Проверьте статус ресурса:

```bash
kubectl get computeinstance nginx-vm
# NAME      READY   SYNCED   EXTERNAL-IP   AGE
# nginx-vm  True    True     158.160.45.123   5m
```

Логи провайдера:

```bash
kubectl -n crossplane-system logs -l app=crossplane-provider-yandex-cloud
```

## Дополнительная информация

Управление ресурсами Yandex Cloud: [Yandex Resource Manager](../../Yandex/Resource_Manager/overview.md). Смежные руководства: [Provider Kubernetes](./provider_kubernetes_setup.md), [Compute Cloud](../../Yandex/Compute-Cloud.md), [VPC (Virtual Private Cloud)](../../Yandex/VPC.md), [Managed Databases](../../Yandex/Managed-Databases.md).

Внешние ресурсы:

- [Yandex Cloud Provider](https://github.com/yandexcloud/crossplane-provider-yc) — официальная документация провайдера.
- [Crossplane Yandex Cloud Marketplace](https://yandex.cloud/en/marketplace/products/yc/crossplane) — поддержка в маркетплейсе.
