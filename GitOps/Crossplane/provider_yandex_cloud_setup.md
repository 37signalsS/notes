# Crossplane: Настройка с провайдером Yandex Cloud

## Определения

**provider-yandex-cloud** (`crossplane-provider-yc`) — официальный Crossplane-провайдер от Yandex Cloud, построенный на базе фреймворка Upjet (генератор «jet»-провайдеров). Он позволяет декларативно управлять ресурсами облака (Compute, VPC, Managed Services, IAM, Storage, Resource Manager) через Kubernetes API. Провайдер обеспечивает непрерывную сверку состояния (reconcile) и полную интеграцию инфраструктуры Yandex Cloud в GitOps-пайплайны.

> **Важно:** Сообщество `crossplane-contrib/provider-yandex-cloud` архивировано (октябрь 2025). Для всех новых инсталляций следует использовать официальный пакет `yandexcloud/crossplane-provider-yc` (реестр `xpkg.upbound.io`). Актуальная версия на август 2026 — **v0.14.1** (проверено по [Upbound Marketplace](https://marketplace.upbound.io/providers/yandexcloud/crossplane-provider-yc/latest); всегда сверяйте последнюю версию перед установкой, т.к. документация Yandex Cloud иногда отстаёт).

## Базовые концепции

### Архитектура интеграции

Интеграция строится на превращении Kubernetes-кластера в универсальную платформу управления (Control Plane):

```text
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     Git     │────▶│   ArgoCD    │────▶│ Crossplane  │────▶│  Yandex     │
│  Repository │     │  (Sync)     │     │ (Reconcile) │     │   Cloud     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

Провайдер — это Deployment (под в `crossplane-system`), который реконсилирует Managed Resources (MR, например `ComputeInstance`): читает `providerConfigRef`, получает креденшелы из `Secret`, вызывает Yandex Cloud API через SDK, а состояние облака копирует в `status.atProvider` MR.

### Поддерживаемые ресурсы Yandex Cloud

*   **Compute**: Виртуальные машины (`ComputeInstance`), группы ВМ, диски, образы.
*   **VPC**: Сети (`Network`), подсети (`Subnet`), таблицы маршрутизации, NAT-шлюзы, Security Groups.
*   **Managed Services**: Кластеры Kubernetes (MKS), PostgreSQL, MySQL, Redis, ClickHouse, MongoDB, Kafka.
*   **IAM**: Сервисные аккаунты, ключи, назначение ролей.
*   **Storage**: S3-совместимые бакеты.
*   **Resource Manager**: Облако (`Cloud`), каталог (`Folder`) — удобны как стабильные «якоря» для импорта.

Полный список CRD: `kubectl get crd | grep yandex-cloud.jet.crossplane.io`. Подробности по полям конкретного ресурса — `kubectl explain <kind>` или `kubectl describe crd <имя>`.

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

Проверка установки Core:
```bash
helm list -n crossplane-system
kubectl get all -n crossplane-system
```

### Установка и конфигурация провайдера Yandex Cloud

**Вариант А: Через Crossplane CLI (Рекомендуется)**

```bash
crossplane xpkg install provider xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1
```

**Вариант Б: Через Yandex Cloud Marketplace**
В консоли Managed Kubernetes выберите приложение "Crossplane". Это установит провайдер с предустановленными настройками для сети Yandex Cloud.

Проверка установки провайдера:
```bash
kubectl get providers
# → NAME                        INSTALLED  HEALTHY  PACKAGE
#   provider-yandex-cloud      True       True     xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1

kubectl get crd | grep yandex-cloud.jet.crossplane.io   # должны появиться CRD ресурсов
```

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

> **Принцип наименьших привилегий:** роль `admin` на каталог удобна для старта, но в проде сузьте её до необходимых (например, `editor` или конкретные роли: `compute.admin`, `vpc.admin`, `mdb.*.admin`, `iam.serviceAccounts.keyAdmin`). Никогда не выдавайте SA роль на уровне облака без необходимости.

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
    cloudId: <CLOUD_ID>          # опционально: облако по умолчанию
    folderId: <FOLDER_ID>        # опционально: каталог по умолчанию
    source: Secret
    secretRef:
      name: yc-creds
      namespace: crossplane-system
      key: credentials
```

> Ключ авторизованного SA (`sa-key.json`) — это JSON с `id`, `service_account_id`, `private_key`. ProviderConfig ссылается на него через `Secret`; сам ключ в открытом виде в ProviderConfig не хранится. Не коммитьте `sa-key.json` и манифест ProviderConfig с ключами в Git — используйте External Secrets Operator + Vault или SOPS (см. [GitOps Integration](./gitops_integration.md) и [управление секретами](../secrets_encryption.md)).

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

Для реализации GitOps-цикла создайте манифест `Application` (замените `repoURL` на свой репозиторий):

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

### Импорт существующих ресурсов (ObserveOnly)

Чтобы взять под управление уже созданный в облаке ресурс без его пересоздания, укажите его внешний ID через аннотацию `crossplane.io/external-name` и режим `ObserveOnly`:

```yaml
apiVersion: resourcemanager.yandex-cloud.jet.crossplane.io/v1alpha1
kind: Folder
metadata:
  name: existing-folder
  annotations:
    crossplane.io/external-name: <CLOUD_FOLDER_ID>   # существующий ID в облаке
spec:
  managementPolicy: ObserveOnly     # Crossplane только читает, не изменяет
  forProvider:
    cloudId: <CLOUD_ID>
    name: my-folder
  providerConfigRef:
    name: default
```

После проверки, что состояние совпадает, `ObserveOnly` можно заменить на `Observe`/`Update` (полное управление) или `All` (с созданием). Для «защищённых» зависимостей (folder, subnet, network), на которые ссылаются другие ресурсы, оставьте `ObserveOnly`, чтобы Crossplane не удалил их при удалении заявки.

### Политики удаления (deletionPolicy)

По умолчанию удаление MR из Kubernetes удаляет и ресурс в облаке. Чтобы оставить ресурс в облаке («осиротить»), используйте `deletionPolicy: Orphan`:

```yaml
spec:
  deletionPolicy: Orphan   # при kubectl delete ресурс в Yandex Cloud НЕ удаляется
  forProvider:
    # ...
```

Это критично для защиты состояния при случайном `kubectl delete` или `prune` в ArgoCD.

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
   kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-yandex-cloud -c provider-yandex-cloud
   ```

4. **Состояние ProviderConfig и провайдера:**
   ```bash
   kubectl get providerconfig
   kubectl describe providerconfig default
   kubectl describe provider provider-yandex-cloud
   ```

5. **Трассировка реконсиляции:**
   ```bash
   crossplane alpha trace computeinstance nginx-web-server
   ```

### Troubleshooting

| Симптом | Вероятная причина | Диагностика / решение |
| --- | --- | --- |
| `ProviderConfig` не `Healthy` | Неверный Secret/ключ или нет сети до Yandex API | `kubectl describe providerconfig`, проверить `kubectl -n crossplane-system get secret yc-creds`, логи провайдера |
| MR в `Creating` вечно | Недостаточно прав у SA (роль/квота/регион) | `kubectl describe <mr>` (Events), расширить роль SA, проверить квоты и зону |
| `Synced=False`, ошибка авторизации | Просрочен/неправильный ключ SA | Перевыпустить `yc iam key create`, обновить Secret |
| Облачный ресурс удалился при `kubectl delete` | `deletionPolicy: Delete` (по умолчанию) | Использовать `deletionPolicy: Orphan` для критичных ресурсов |
| Изменения не применяются | `managementPolicy: ObserveOnly` | Переключить на `Observe`/`Update`/`All` для управления |
| `HEALTHY=False` у провайдера | Проблема ревизии пакета/несовместимость | `kubectl describe providerrevisions`, проверить версию пакета и совместимость с Crossplane v2 |
| `kubectl get crd` пуст для yandex | Провайдер не установился | `kubectl get providers`, проверить, что пакет `v0.14.1` скачался |

## Дополнительная информация

Управление ресурсами через нативные инструменты: [Yandex Resource Manager](../../Yandex/Resource_Manager/overview.md).
Смежные настройки: [Provider Kubernetes](./provider_kubernetes_setup.md), [Интеграция с GitOps](./gitops_integration.md).

Внешние ресурсы:
* [Документация Yandex Cloud: Managed Crossplane](https://yandex.cloud/ru/docs/managed-kubernetes/operations/applications/crossplane)
* [Официальный репозиторий провайдера yandex-cloud/crossplane-provider-yc](https://github.com/yandex-cloud/crossplane-provider-yc)
* [Upbound Marketplace: crossplane-provider-yc (проверка актуальной версии)](https://marketplace.upbound.io/providers/yandexcloud/crossplane-provider-yc/latest)
* [Примеры манифестов ресурсов](https://github.com/yandex-cloud/crossplane-provider-yc/tree/main/examples)
