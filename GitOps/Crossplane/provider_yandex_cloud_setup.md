# Crossplane: Настройка с провайдером Yandex Cloud

## Определения

**provider-yandex-cloud** (`crossplane-provider-yc`) — официальный Crossplane-провайдер от Yandex Cloud, построенный на базе фреймворка Upjet. Он позволяет декларативно управлять ресурсами облака (Compute, VPC, Managed Services, IAM, Storage) через Kubernetes API. Провайдер обеспечивает непрерывную сверку состояния и полную интеграцию инфраструктуры Yandex Cloud в GitOps-пайплайны.

> **Важно:** Сообщество `crossplane-contrib/provider-yandex-cloud` архивировано (октябрь 2025). Для всех новых инсталляций в 2026 году следует использовать официальный пакет: `yandexcloud/crossplane-provider-yc`.

## Базовые концепции

### Архитектура интеграции

Интеграция строится на превращении Kubernetes-кластера в универсальную платформу управления (Control Plane):

```text
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     Git     │────▶│   ArgoCD    │────▶│ Crossplane  │────▶│  Yandex     │
│  Repository │     │  (Sync)     │     │ (Reconcile) │     │   Cloud     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Поддерживаемые ресурсы Yandex Cloud

*   **Compute**: Виртуальные машины (`ComputeInstance`), группы ВМ, диски, образы.
*   **VPC**: Сети (`Network`), подсети (`Subnet`), таблицы маршрутизации, NAT-шлюзы, Security Groups.
*   **Managed Services**: Кластеры Kubernetes (MKS), PostgreSQL, MySQL, Redis, ClickHouse, MongoDB, Kafka.
*   **IAM**: Сервисные аккаунты, ключи, назначение ролей.
*   **Storage**: S3-совместимые бакеты.

Подробное описание архитектуры и уровней абстракции (XRD, Composition) приведено в [Обзоре Crossplane](./overview.md).

## Практические сценарии

### Предварительные требования

*   **Кластер Kubernetes**: Версии 1.28+ (Managed или Self-managed).
*   **Helm**: Версии 3.10+ с поддержкой OCI.
*   **Yandex Cloud CLI**: Инициализированный профиль (`yc init`).
*   **Argo CD**: (Рекомендуется) Для реализации GitOps-пайплайна.

### Установка Crossplane Core

**1. Добавление репозитория:**
```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
```

**2. Установка в кластер:**
```bash
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace \
  --set args='{--enable-ssa-claims}' # Включение Server-Side Apply для K8s 1.28+
```

### Установка и конфигурация провайдера Yandex Cloud

**Вариант А: Через Crossplane CLI (Рекомендуется)**
Актуальная версия на август 2026 — `v0.5.1`.

```bash
crossplane xpkg install provider xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.5.1
```

**Вариант Б: Через Yandex Cloud Marketplace**
В консоли Managed Kubernetes выберите приложение "Crossplane". Это установит провайдер с предустановленными настройками для сети Yandex Cloud.

### Настройка безопасности и доступа

**1. Создание Сервисного Аккаунта (SA) в Yandex Cloud:**
```bash
# Создание SA
yc iam service-account create --name crossplane-admin

# Назначение роли admin на каталог
FOLDER_ID=$(yc config get folder-id)
SA_ID=$(yc iam service-account get crossplane-admin --format json | jq -r .id)

yc resource-manager folder add-access-binding $FOLDER_ID \
  --role admin \
  --subject serviceAccount:$SA_ID

# Генерация авторизованного ключа
yc iam key create --service-account-name crossplane-admin --output sa-key.json
```

**2. Создание секрета в Kubernetes:**
```bash
kubectl create secret generic yc-creds \
  --namespace crossplane-system \
  --from-file=credentials=./sa-key.json
```

**3. Настройка ProviderConfig:**
```yaml
apiVersion: yandex-cloud.jet.crossplane.io/v1beta1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: Secret
    secretRef:
      name: yc-creds
      namespace: crossplane-system
      key: credentials
```

### Развертывание VM с Nginx через GitOps (Детальный пример)

Пример создания виртуальной машины с использованием `cloud-config` для автоматической установки Nginx.

**1. Манифест инфраструктуры (`vm.yaml`):**

```yaml
apiVersion: compute.yandex-cloud.jet.crossplane.io/v1beta1
kind: ComputeInstance
metadata:
  name: nginx-web-server
spec:
  forProvider:
    name: nginx-web-server
    zone: ru-central1-a
    platformId: standard-v3
    resources:
      memory: 2G
      cores: 2
      coreFraction: 20
    bootDisk:
      initializeParams:
        imageId: fd80m5rnb5lsvj0s2k91 # Ubuntu 24.04 LTS
        size: 15G
    networkInterfaces:
      - subnetId: <YOUR_SUBNET_ID> # ID подсети в Yandex Cloud
        primaryV4Address: {} # Динамический публичный IP
    metadata:
      user-data: |
        #cloud-config
        package_update: true
        packages:
          - nginx
        write_files:
          - content: |
              <h1>Deployed via Crossplane</h1>
            path: /var/www/html/index.html
        runcmd:
          - systemctl enable nginx
          - systemctl start nginx
  providerConfigRef:
    name: default
```

**2. Настройка ArgoCD Application:**

Для реализации GitOps-цикла создайте манифест `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: yc-infra-stack
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/my-org/infra-gitops.git
    targetRevision: main
    path: crossplane/resources/yandex
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

### Мониторинг и отладка

1. **Проверка статуса ресурса:**
   ```bash
   kubectl get managed
   # Или специфичный ресурс:
   kubectl get computeinstance nginx-web-server
   ```

2. **Детальная информация об ошибках:**
   ```bash
   kubectl describe computeinstance nginx-web-server
   # Ищите секцию Status.Conditions и Events
   ```

3. **Логи провайдера:**
   ```bash
   kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-yandex-cloud -c provider-kubernetes
   ```

## Дополнительная информация

Управление ресурсами через нативные инструменты: [Yandex Resource Manager](../../Yandex/Resource_Manager/overview.md).
Смежные настройки: [Provider Kubernetes](./provider_kubernetes_setup.md), [Интеграция с GitOps](./gitops_integration.md).

Внешние ресурсы:
* [Документация Yandex Cloud: Managed Crossplane](https://yandex.cloud/ru/docs/managed-kubernetes/operations/applications/crossplane)
* [Репозиторий официального провайдера yandexcloud/crossplane-provider-yc](https://github.com/yandexcloud/crossplane-provider-yc)
