# Установка и конфигурация Karpenter

## Определения

**Karpenter Helm Chart** — официальный пакет для развёртывания контроллера Karpenter в кластере Kubernetes. Он управляет установкой бинарного файла контроллера, Admission Webhooks (для валидации CRD) и необходимых ресурсов RBAC (ClusterRole, RoleBinding). Начиная с ветки v1.x, установка производится исключительно из OCI-репозиториев (Amazon ECR для AWS, Microsoft Container Registry для Azure).

**NodePool** — ресурс CRD (Custom Resource Definition), пришедший на замену `Provisioner` (v1 API). Он определяет «намерения» (intent) кластера по созданию узлов. NodePool позволяет задать жесткие лимиты на суммарные ресурсы (CPU, Memory), требования к инстансам (архитектура, тип, поколение) и политики прерывания (Disruption).

**NodeClass (EC2NodeClass / AKSNodeClass)** — специализированный CRD, который связывает логику NodePool с конкретной инфраструктурой облака. Отвечает за выбор подсетей, групп безопасности, образов ОС (AMI / ImageID), настройку дисков и привязку ролей доступа (IAM / Managed Identity).

**NodeClaim** — объект, представляющий запрос на создание конкретного инстанса. В отличие от своего предшественника `Machine`, NodeClaim является неизменяемым (immutable). Если параметры в NodePool или NodeClass меняются, Karpenter создаёт новый NodeClaim вместо обновления существующего (механизм Drift).

## Основные концепции

### Предварительные требования

**Версия Kubernetes** — для стабильной работы ветки v1.14.x требуется Kubernetes версии **1.30+**. Для поддержки In-Place Pod Resizing в связке с VPA необходимы современные версии планировщика.

**Аутентификация в облаке**:
- **AWS (Amazon Web Services):** Рекомендуется использовать **EKS Pod Identity**. В отличие от IRSA (IAM Roles for Service Accounts), Pod Identity не требует сложной настройки Trust Policy с OIDC-провайдером. Права передаются через `aws-eks-pod-identity-agent`.
- **Azure (Microsoft Azure):** Требуется включенный **Workload Identity** и User-Assigned Managed Identity с ролями `Virtual Machine Contributor`, `Network Contributor` и `Managed Identity Operator`.

**IAM-роли (AWS)**:
1.  **KarpenterControllerRole**: Должна обладать правами на `ec2:RunInstances`, `ec2:CreateFleet`, `ec2:TerminateInstances`, а также на чтение параметров из SSM и доступ к SQS.
2.  **KarpenterNodeRole**: IAM-роль, назначаемая узлам. Включает политики `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy` и `AmazonEC2ContainerRegistryReadOnly`.

**Interruption Handling (AWS SQS)** — механизм подписки на события AWS (Spot Interruption, Instance Rebalance, Scheduled Maintenance). Реализуется через очередь Amazon SQS и правило EventBridge. Позволяет Karpenter начать перенос подов за 2 минуты до принудительного удаления узла.

### Архитектура развёртывания

Karpenter работает как Deployment, обычно с 2 репликами для высокой доступности (HA). Он не использует стандартный `kube-scheduler` для создания узлов, а реализует собственный цикл «мониторинг -> бинпакинг -> вызов Cloud API». Это позволяет сократить время появления нового узла с 2-3 минут (Cluster Autoscaler) до 45-60 секунд в AWS и <3 минут в Azure.

## Практические сценарии

### Сценарий 1: Установка в AWS EKS

#### Шаг 1: Создание инфраструктуры и Pod Identity

```bash
# Создание роли контроллера (пример упрощен)
aws iam create-role --role-name KarpenterControllerRole --assume-role-policy-document ...

# Создание ассоциации Pod Identity (связывает ServiceAccount 'karpenter' с IAM-ролью)
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --role-arn arn:aws:iam::123456789012:role/KarpenterControllerRole \
  --namespace karpenter \
  --service-account karpenter
```

#### Шаг 2: Установка контроллера через Helm (OCI)

```bash
export KARPENTER_VERSION="1.14.0"

# Логин в ECR Public для предотвращения Rate Limit
aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin oci://public.ecr.aws

# Установка
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version "${KARPENTER_VERSION}" \
  --namespace karpenter --create-namespace \
  --set settings.clusterName=my-cluster \
  --set settings.interruptionQueue=my-cluster-sqs-queue \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --wait
```

#### Шаг 3: Конфигурация EC2NodeClass (AWS)

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  amiFamily: AL2023 # Рекомендуемый стандарт для EKS
  amiSelectorTerms:
    - alias: al2023@latest
  role: KarpenterNodeRole
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true
        deleteOnTermination: true
  metadataOptions:
    httpEndpoint: enabled
    httpTokens: required # Обязательно для IMDSv2
```

### Сценарий 2: Установка в Azure AKS

В 2026 году Karpenter для Azure достиг статуса GA. Установка производится из официального OCI-репозитория Microsoft.

#### Шаг 1: Установка контроллера через Helm (Azure OCI)

```bash
export KARPENTER_VERSION="1.14.0"
export CLUSTER_NAME="my-aks-cluster"
export CLUSTER_ENDPOINT=$(az aks show -n $CLUSTER_NAME -g $RG --query fqdn -o tsv)
export IDENTITY_CLIENT_ID=$(az identity show -n karpenter-identity -g $RG --query clientId -o tsv)

helm upgrade --install karpenter oci://mcr.microsoft.com/aks/karpenter/karpenter \
  --version "${KARPENTER_VERSION}" \
  --namespace kube-system \
  --create-namespace \
  --set settings.clusterName="${CLUSTER_NAME}" \
  --set settings.clusterEndpoint="${CLUSTER_ENDPOINT}" \
  --set serviceAccount.annotations."azure\.workload\.identity/client-id"="${IDENTITY_CLIENT_ID}" \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --wait
```

#### Шаг 2: Конфигурация AKSNodeClass (Azure)

```yaml
apiVersion: karpenter.azure.com/v1beta1
kind: AKSNodeClass
metadata:
  name: default
spec:
  imageFamily: Ubuntu # Или AzureLinux
  vnetSubnetID: "/subscriptions/.../resourceGroups/.../providers/Microsoft.Network/virtualNetworks/.../subnets/aks-subnet"
  osDiskSizeGB: 128
  tags:
    ManagedBy: Karpenter
```

### Сценарий 3: Конфигурация универсального NodePool

Этот NodePool может ссылаться как на `EC2NodeClass`, так и на `AKSNodeClass`.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  limits:
    cpu: 1000
    memory: 1000Gi
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws # Для Azure замените на karpenter.azure.com
        kind: EC2NodeClass       # Для Azure замените на AKSNodeClass
        name: default
      requirements:
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot", "on-demand"]
        - key: "kubernetes.io/arch"
          operator: In
          values: ["amd64", "arm64"]
      expireAfter: 720h # Ротация узлов каждые 30 дней
      terminationGracePeriod: 48h
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      - nodes: "15%" # Разрешить прерывание не более 15% узлов
      - nodes: "0"
        schedule: "@daily"
        duration: 15m
```

### Сценарий 4: Изоляция критических нагрузок и GPU

Karpenter позволяет создавать пулы для AI/ML.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-pool
spec:
  template:
    spec:
      requirements:
        - key: "karpenter.k8s.aws/instance-gpu-manufacturer" # AWS-specific
          operator: In
          values: ["nvidia"]
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"] # Spot для обучения, On-demand для инференса
      taints:
        - key: "nvidia.com/gpu"
          value: "true"
          effect: "NoSchedule"
  disruption:
    consolidationPolicy: WhenEmpty # Не прерывать обучение при недогрузе CPU
```

**Особенности для GenAI:**
- **MIG (Multi-Instance GPU)**: Указание типов инстансов, поддерживающих нарезку GPU на изолированные инстансы.
- **MPS (Multi-Process Service)**: Karpenter может подготавливать узлы с MPS для высокой плотности инференса мелких LLM (через DRA).

## Дополнительная информация

### Диагностика и устранение неисправностей

**Проверка логики планирования**:
Если поды висят в `Pending`, проверьте логи контроллера (причина отказа подбора, например "no instance types found").
```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100 -f
```

**Работа с NodeClaims**:
Если инстанс не создается в облаке, `NodeClaim` покажет ошибку API (например, квоты или IAM).
```bash
kubectl get nodeclaims
kubectl describe nodeclaim <name>
```

**Защита от прерываний (Disruption)**:
Для временного запрета удаления узла (например, при миграции БД):
```bash
kubectl annotate node <node-name> karpenter.sh/do-not-disrupt=true
```

### Ключевые метрики Prometheus

| Метрика | Значение | Критичность |
|---------|----------|-------------|
| `karpenter_nodeclaims_created_total` | Общее количество созданных запросов | Информативно |
| `karpenter_nodeclaims_terminated_total` | Количество удаленных узлов | Высокая (мониторинг Churn rate) |
| `karpenter_nodeclaims_failed_total` | Ошибки создания (Insufficient Capacity, IAM errors) | КРИТИЧЕСКИ |
| `karpenter_provisioning_scheduling_duration_seconds` | Время от Pending пода до создания NodeClaim | Средняя |
| `karpenter_interruption_actions_total` | Количество реакций на события прерывания | Высокая (статистика Spot) |

### Лучшие практики эксплуатации

1.  **Drift Mechanism**: Дрейф включен по умолчанию. Любое изменение в `NodeClass` (смена SG, VNet, AMI) приведет к планомерному пересозданию всех узлов.
2.  **Spot Diversity**: В `requirements` NodePool указывайте как можно больше типов инстансов. Ограничение пула одним типом приведет к отказу при его дефиците.
3.  **Over-provisioning**: Используйте `Pause Pods` (поды с низким приоритетом) для резервирования места. Karpenter вытеснит их и мгновенно разместит критичную нагрузку.
4.  **Limits**: Обязательно устанавливайте `spec.limits` в NodePool для защиты от бесконечного спавна узлов при ошибках конфигурации деплоймента.

### Ссылки

- **[Обзор и основные концепции Karpenter](./overview.md)** — теоретическая база и архитектура.
- **[Официальная документация (v1.x)](https://karpenter.sh/)** — справочник API.
- **[Karpenter Blueprints](https://github.com/aws-samples/karpenter-blueprints)** — готовые шаблоны от AWS.
