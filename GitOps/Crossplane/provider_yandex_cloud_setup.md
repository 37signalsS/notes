# Crossplane: Настройка с провайдером Yandex Cloud

## Определения

**provider-yandex-cloud** — официальный кроссплатформенный Crossplane-провайдер от Yandex Cloud для управления ресурсами облака (Compute, VPC, Managed Services, IAM) через Kubernetes API. Он позволяет описывать инфраструктуру Yandex Cloud с помощью декларативных манифестов Kubernetes, обеспечивая полную интеграцию облака в GitOps-пайплайны.

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

- **Compute**: Виртуальные машины (`ComputeInstance`), группы ВМ, диски, снапшоты.
- **VPC**: Сети (`Network`), подсети (`Subnet`), статические IP-адреса, шлюзы.
- **Managed Services**: Кластеры Kubernetes, PostgreSQL, MySQL, Redis, ClickHouse.
- **IAM (Identity and Access Management)**: Сервисные аккаунты, роли, авторизованные ключи.
- **Storage**: Объектное хранилище (S3-бакеты).

Общий обзор технологии и архитектуры Control Plane см. в [Crossplane: Обзор](./overview.md).

## Практические сценарии

### Предварительные требования

- **Кластер Kubernetes**: Managed Service for Kubernetes или любой self-managed кластер v1.26+.
- **Helm**: Пакетный менеджер версии 3.8.0+ (с поддержкой OCI).
- **kubectl**: Настроенный доступ к управляющему кластеру.
- **Yandex Cloud CLI**: Установлен и инициализирован (`yc init`).
- **Argo CD**: (Рекомендуется) Для автоматизации развертывания через Git.

### Установка Crossplane

**Шаг 1: Добавление Helm-репозитория**

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
```

**Шаг 2: Установка в выделенный namespace**

```bash
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace
```

**Шаг 3: Проверка готовности**

Убедитесь, что основные компоненты (`crossplane` и `crossplane-rbac-manager`) запущены:

```bash
kubectl get pods -n crossplane-system
# NAME                                           READY   STATUS    RESTARTS   AGE
# crossplane-7b8c9d4e5f-abcde                    1/1     Running   0          2m
# crossplane-rbac-manager-6f7g8h9i0j-fghij       1/1     Running   0          2m
```

### Установка Crossplane CLI

Инструмент командной строки необходим для удобного управления пакетами (`xpkg`).

1. Скачайте бинарный файл для вашей ОС с [GitHub Releases](https://github.com/crossplane/crossplane/releases).
2. Переместите его в `/usr/local/bin/` или другой путь в `PATH`.
3. Проверьте установку: `crossplane --version`.

### Установка и конфигурация провайдера Yandex Cloud

**Вариант А: Установка через Crossplane CLI (Рекомендуется)**

```bash
crossplane xpkg install provider xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.0
```

**Вариант Б: Установка через Yandex Cloud Marketplace**

Если вы используете Managed Kubernetes в YC, вы можете установить приложение "Crossplane" через веб-консоль в разделе Marketplace. Это автоматически развернет провайдер и создаст необходимые секреты.

**Проверка установленных CRD:**

После установки провайдера появятся новые группы ресурсов:

```bash
kubectl get crd | grep yandex-cloud
# computeinstances.compute.yandex-cloud.jet.crossplane.io
# networks.vpc.yandex-cloud.jet.crossplane.io
# ...
```

### Настройка безопасности и доступа

**Шаг 1: Создание Сервисного Аккаунта (SA) в Yandex Cloud**

```bash
# Создание SA
yc iam service-account create --name crossplane-sa

# Назначение роли (admin или editor на каталог)
yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role admin \
  --subject serviceAccount:<SA_ID>

# Создание авторизованного ключа
yc iam key create --service-account-name crossplane-sa --output sa-key.json
```

**Шаг 2: Создание секрета в Kubernetes**

```bash
kubectl create secret generic yandex-cloud-credentials \
  --from-file=credentials=./sa-key.json \
  --namespace crossplane-system
```

**Шаг 3: Настройка ProviderConfig**

Этот объект определяет, какие учетные данные использовать для обращения к API.

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
```

### Развертывание VM с Nginx через GitOps (Детальный пример)

Этот пример демонстрирует создание виртуальной машины с использованием `cloud-config` для автоматической установки Nginx.

**Шаг 1: Манифест инфраструктуры (`vm.yaml`)**

```yaml
apiVersion: compute.yandex-cloud.jet.crossplane.io/v1beta1
kind: ComputeInstance
metadata:
  name: nginx-web-server
spec:
  forProvider:
    zone: ru-central1-a
    platformId: standard-v3
    resources:
      memory: 2G
      cores: 2
      coreFraction: 20
    bootDisk:
      initializeParams:
        imageId: fd80m5rnb5lsvj0s2k91 # Ubuntu 22.04 LTS
        size: 15G
    networkInterfaces:
      - subnetId: <YOUR_SUBNET_ID> # Ссылка на ID подсети
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

**Шаг 2: Настройка ArgoCD Application**

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
   kubectl get computeinstance nginx-web-server
   # NAME               READY   SYNCED   EXTERNAL-IP      AGE
   # nginx-web-server   True    True     158.160.20.30    5m
   ```

2. **Детальная информация об ошибках:**
   ```bash
   kubectl describe computeinstance nginx-web-server
   # Ищите секцию Status.Conditions
   ```

3. **Логи провайдера:**
   ```bash
   kubectl -n crossplane-system logs -l app=crossplane-provider-yandex-cloud
   ```

## Дополнительная информация

Управление ресурсами через нативные инструменты: [Yandex Resource Manager](../../Yandex/Resource_Manager/overview.md).
Смежные настройки: [Provider Kubernetes](./provider_kubernetes_setup.md), [Интеграция с GitOps](./gitops_integration.md).

Внешние ресурсы:
- [Официальный репозиторий yandexcloud/crossplane-provider-yc](https://github.com/yandexcloud/crossplane-provider-yc)
- [Документация Yandex Cloud: Crossplane](https://yandex.cloud/ru/docs/managed-kubernetes/operations/applications/crossplane)
