# Установка и конфигурация Karpenter

## Определения

**Karpenter Helm Chart** — официальный пакет для развёртывания Karpenter в кластере Kubernetes. Управляет установкой контроллера, вебхуков (webhook) и необходимых ресурсов RBAC (Role-Based Access Control — управление доступом на основе ролей).

**NodePool** — ресурс CRD (Custom Resource Definition), определяющий параметры масштабирования (типы инстансов, зоны, лимиты ресурсов). Подробное описание концепции см. в **[Обзор и основные концепции Karpenter](./overview.md)**.

**EC2NodeClass** — ресурс CRD для AWS (Amazon Web Services), определяющий инфраструктурную конфигурацию узлов: AMI (Amazon Machine Image — образ системы), IAM-роль, подсети и группы безопасности.

## Основные концепции

### Предварительные требования

**Кластер EKS (Elastic Kubernetes Service)** — требуется версия Kubernetes 1.24 или выше и совместимость с Karpenter v1.x.

**IAM-роли (Identity and Access Management)** — необходимы две роли: для контроллера Karpenter (доступ к API облака) и для создаваемых узлов (права для работы компонентов Kubernetes на ноде).

**Helm v3+** — инструмент для управления пакетами Kubernetes, необходим для установки Karpenter.

**Очередь SQS (Simple Queue Service)** — используется в AWS для обработки событий прерывания (interruption handling), таких как уведомления о вытеснении spot-инстансов.

### Архитектура развёртывания

Karpenter устанавливается в отдельное пространство имён (namespace) `karpenter`. Контроллер работает как Deployment и взаимодействует с API облачного провайдера (AWS EC2, IAM, SQS, CloudFormation).

## Практические сценарии

### Установка Karpenter в AWS EKS

#### Шаг 1: Создание IAM-ролей

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

#### Шаг 3: Создание NodePool

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

  # Шаблон узла
  template:
    spec:
      # Типы инстансов (от дешёвых к дорогим)
      instanceTypes:
        - m5.large
        - m5.xlarge
        - m6i.large
        - m6i.xlarge

      # Ссылка на конфигурацию облачного уровня
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default

      # Требования к узлам
      requirements:
        - key: "topology.kubernetes.io/zone"
          operator: In
          values: ["us-west-2a", "us-west-2b"]

        # Использование только on-demand инстансов
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"]

  # Стратегия консолидации
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m

  # Вес NodePool (для выбора между несколькими пулами)
  weight: 100
```

#### Шаг 4: Создание EC2NodeClass

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  # Семейство AMI
  amiFamily: AL2023
  amiSelectorTerms:
    - alias: al2023@latest

  # IAM-роль для узлов
  role: KarpenterNodeRole

  # Выбор подсетей по тегам
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster

  # Выбор групп безопасности
  securityGroupSelectorTerms:
    - tags:
        aws:eks:cluster-name: my-cluster

  # Настройка дисковой подсистемы EBS (Elastic Block Store)
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true

  # Настройки метаданных инстанса (IMDSv2 — Instance Metadata Service version 2)
  metadataOptions:
    httpEndpoint: enabled
    httpProtocolIPv6: disabled
    httpPutResponseHopLimit: 2
    httpTokens: required
```

### Сценарий: Экономия на пакетных задачах через spot-инстансы

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
      # Список подходящих типов инстансов
      instanceTypes:
        - c5.large
        - c5.xlarge
        - c6i.large

      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default

      requirements:
        # Принудительное использование spot-инстансов
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot"]

  disruption:
    consolidationPolicy: WhenEmpty
    expireAfter: 24h # Ротация узлов каждые 24 часа
```

### Сценарий: Масштабирование GPU-узлов

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
      # Специализированные GPU-инстансы
      instanceTypes:
        - g5.xlarge
        - g5.2xlarge
        - g6.xlarge

      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: gpu-node-class

      requirements:
        # Проверка наличия GPU (Graphics Processing Unit)
        - key: "nvidia.com/gpu"
          operator: Exists

        # Использование on-demand для стабильности обучения моделей
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"]
```

## Дополнительная информация

### Диагностика и мониторинг

**Просмотр логов контроллера:**

```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100
```

**Список существующих NodePool:**

```bash
kubectl get nodepool
```

**Просмотр узлов, созданных Karpenter:**

```bash
kubectl get nodes -l karpenter.sh/nodepool=default
```

**События жизненного цикла узлов:**

```bash
kubectl get events -n karpenter --sort-by='.lastTimestamp'
```

### Метрики мониторинга

| Метрика | Описание |
|---------|----------|
| `karpenter_nodepool_usage_cpu` | Использование CPU в разрезе NodePool |
| `karpenter_nodepool_usage_memory` | Использование памяти в разрезе NodePool |
| `karpenter_pods_state` | Состояние подов, ожидающих назначения на узлы |
| `karpenter_nodes_total` | Общее количество управляемых узлов |
| `karpenter_disruption_actions_total` | Статистика операций консолидации и удаления |
| `karpenter_provisioning_latency_seconds` | Время с момента Pending пода до готовности узла |

### Лучшие практики

- **Разделение нагрузок** — создавайте отдельные NodePool для критических сервисов, пакетных задач и GPU-нагрузок.
- **Включение консолидации** — используйте `consolidationPolicy: WhenEmptyOrUnderutilized` для автоматической экономии средств.
- **Контроль лимитов** — всегда задавайте `spec.limits` в NodePool, чтобы избежать неконтролируемого роста затрат при сбоях.
- **Обновление AMI** — используйте алиасы (alias) в `amiSelectorTerms` для автоматического получения последних патчей безопасности.
- **Мониторинг Pending** — настройте алерты на наличие подов в состоянии `Pending` более 5 минут, это может сигнализировать о проблемах с правами IAM или квотами облака.

### Ссылки

- **[Обзор и основные концепции Karpenter](./overview.md)** — архитектура и отличия от Cluster Autoscaler.
- **[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — альтернативный инструмент масштабирования.
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — защита подов при операциях консолидации.
