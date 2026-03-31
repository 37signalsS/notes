# Karpenter: Установка и конфигурация

## Определения

**Karpenter Helm Chart** — официальный пакет для развёртывания Karpenter в Kubernetes кластере. Управляет установкой контроллера, webhook и необходимых RBAC-ресурсов.

**EC2NodeClass** — ресурс Karpenter для AWS, определяющий конфигурацию создаваемых узлов (AMI, IAM-роль, подсети, группы безопасности).

**NodePool** — ресурс Karpenter, определяющий параметры масштабирования (типы инстансов, зоны, лимиты ресурсов).

## Основные концепции

### Предварительные требования

**Кластер EKS** — требуется Kubernetes 1.24+ и совместимость с Karpenter v1.x.

**IAM Roles** — необходимы две роли: для контроллера Karpenter и для создаваемых узлов.

**Helm v3+** — требуется для установки Karpenter через Helm chart.

**Очередь SQS** — для обработки событий прерывания (interruption handling) в AWS.

### Архитектура развёртывания

Karpenter устанавливается в отдельный namespace `karpenter`. Контроллер работает как Deployment, требует доступа к API AWS EC2, IAM, SQS, CloudFormation.

## Практические сценарии

### Установка Karpenter (AWS EKS)

#### Шаг 1: Создание IAM ролей

```bash
# Роль для Karpenter Controller
aws iam create-role \
  --role-name KarpenterControllerRole \
  --assume-role-policy-document file://trust-policy.json

# Роль для узлов Karpenter
aws iam create-role \
  --role-name KarpenterNodeRole \
  --assume-role-policy-document file://node-trust-policy.json
```

#### Шаг 2: Установка через Helm

```bash
# Добавление репозитория
helm repo add karpenter https://charts.karpenter.sh
helm repo update

# Установка Karpenter
helm upgrade --install karpenter karpenter/karpenter \
  --namespace karpenter \
  --create-namespace \
  --set serviceAccount.create=false \
  --set serviceAccount.name=karpenter-sa \
  --set settings.clusterName=my-cluster \
  --set settings.interruptionQueue=my-queue \
  --version 1.10.0
```

#### Шаг 3: Создание Node Pool

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  # Границы масштабирования
  limits:
    cpu: 1000
    memory: 1000Gi

  # Требования к узлам
  template:
    spec:
      # Типы инстансов (от дешёвых к дорогим)
      instanceTypes:
        - m5.large
        - m5.xlarge
        - m6i.large
        - m6i.xlarge

      # Зоны доступности
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default

      # Требования к топологии
      requirements:
        - key: "topology.kubernetes.io/zone"
          operator: In
          values: ["us-west-2a", "us-west-2b"]

        # Запрет spot-инстансов для критических нагрузок
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"]

  # Стратегия распределения
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m

  # Приоритет Node Pool
  weight: 100
```

#### Шаг 4: Создание EC2NodeClass

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  # AMI (образ узла)
  amiFamily: AL2023
  amiSelectorTerms:
    - alias: al2023@latest

  # Роль IAM для узлов
  role: KarpenterNodeRole

  # Подсеть
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster

  # Группа безопасности
  securityGroupSelectorTerms:
    - tags:
        aws:eks:cluster-name: my-cluster

  # Конфигурация диска
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true

  # Метаданные (IMDSv2)
  metadataOptions:
    httpEndpoint: enabled
    httpProtocolIPv6: disabled
    httpPutResponseHopLimit: 2
    httpTokens: required
```

### Сценарий 1: Масштабирование для пакетных задач

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: batch-jobs
spec:
  limits:
    cpu: 500

  template:
    spec:
      # Spot-инстансы для экономии
      instanceTypes:
        - c5.large
        - c5.xlarge
        - c6i.large

      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default

      requirements:
        # Только spot-инстансы
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot"]

  disruption:
    consolidationPolicy: WhenEmpty
    expireAfter: 24h # Принудительное обновление через 24 часа
```

### Сценарий 2: GPU-ноды для ML

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-workloads
spec:
  limits:
    cpu: 200
    memory: 1000Gi

  template:
    spec:
      # GPU-инстансы
      instanceTypes:
        - g5.xlarge
        - g5.2xlarge
        - g6.xlarge

      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: gpu-node-class

      requirements:
        # Требуется GPU
        - key: "nvidia.com/gpu"
          operator: Exists

        # Только on-demand для стабильности
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"]
```

### Сценарий 3: Мульти-зонный кластер

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: multi-zone
spec:
  template:
    spec:
      # Распределение по зонам
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: my-app

      requirements:
        # Все доступные зоны
        - key: "topology.kubernetes.io/zone"
          operator: Exists
```

## Дополнительная информация

### Диагностика и мониторинг

**Проверка логов контроллера:**
```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100
```

**Проверка Node Pool:**
```bash
kubectl get nodepool
```

**Проверка созданных узлов:**
```bash
kubectl get nodes -l karpenter.sh/nodepool=default
```

**Просмотр событий Karpenter:**
```bash
kubectl get events -n karpenter --sort-by='.lastTimestamp'
```

### Метрики для мониторинга

| Метрика | Описание |
|---------|----------|
| `karpenter_nodepool_usage_cpu` | Использовано CPU в Node Pool |
| `karpenter_nodepool_usage_memory` | Использовано памяти в Node Pool |
| `karpenter_pods_state` | Количество подов по состояниям |
| `karpenter_nodes_total` | Общее количество узлов |
| `karpenter_disruption_actions_total` | Количество операций консолидации |
| `karpenter_provisioning_latency_seconds` | Задержка создания узла |

### Лучшие практики

**Используйте несколько Node Pool** — разделяйте workloads по типам (критические, пакетные, GPU).

**Consolidation** — включите консолидацию для автоматической оптимизации затрат.

**Spot + On-Demand** — комбинируйте spot для fault-tolerant и on-demand для критических нагрузок.

**Limit Range** — устанавливайте лимиты на Node Pool для контроля затрат.

**ExpireAfter** — настройте принудительное обновление узлов для безопасности.

**Мониторинг Pending Pods** — алерты на поды в `Pending` более 2 минут.

**Используйте latest AMI** — обновляйте образы узлов автоматически через `amiSelectorTerms: alias`.

### Связанные ресурсы

**[Обзор Karpenter](./overview.md)** — концепции, архитектура, отличия от Cluster Autoscaler.

**[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — альтернативное решение для масштабирования узлов.

**[KEDA](../keda/basic_concepts.md)** — интеграция для масштабирования по внешним метрикам.
