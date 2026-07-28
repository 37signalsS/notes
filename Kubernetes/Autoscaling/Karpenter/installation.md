# Установка и конфигурация Karpenter

## Определения

**Karpenter Helm Chart** — официальный пакет для развёртывания контроллера Karpenter в кластере Kubernetes. Он управляет установкой бинарного файла контроллера, Admission Webhooks (для валидации CRD) и необходимых ресурсов RBAC (ClusterRole, RoleBinding). Начиная с версии v1.0, основным источником является OCI-репозиторий в Amazon ECR.

**NodePool** — ресурс CRD (Custom Resource Definition), пришедший на замену `Provisioner`. Он определяет «намерения» (intent) кластера по созданию узлов. NodePool позволяет задать жесткие лимиты на суммарные ресурсы (CPU, Memory), требования к инстансам (архитектура, тип, поколение) и политики прерывания (Disruption).

**EC2NodeClass** — специализированный CRD для AWS (ранее `AWSNodeTemplate`), который связывает логику NodePool с конкретной инфраструктурой VPC. Он отвечает за выбор подсетей, групп безопасности, AMI-образов, настройку дисков (EBS) и выбор IAM-роли для узла.

**NodeClaim** — объект, представляющий запрос на создание конкретного инстанса. В отличие от своего предшественника `Machine`, NodeClaim является неизменяемым (immutable). Если параметры в NodePool меняются, Karpenter создаёт новый NodeClaim вместо обновления существующего.

## Основные концепции

### Предварительные требования

**Версия Kubernetes** — требуется 1.25+. Для полной поддержки всех функций v1.x (например, In-Place Pod Resizing в связке с VPA) рекомендуется 1.27+.

**EKS Pod Identity (рекомендуется)** — современный стандарт аутентификации в AWS. В отличие от IRSA (IAM Roles for Service Accounts), Pod Identity не требует сложной настройки Trust Policy с OIDC-провайдером для каждого кластера. Права передаются через `aws-eks-pod-identity-agent` (addon), что упрощает миграцию и управление правами.

**IAM-роли**:
1.  **KarpenterControllerRole**: Должна обладать правами на `ec2:RunInstances`, `ec2:CreateFleet`, `ec2:TerminateInstances`, а также на чтение параметров из SSM (для поиска AMI) и доступ к SQS.
2.  **KarpenterNodeRole**: IAM-роль, которая будет назначена самим узлам. Она должна содержать стандартные политики `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy` и `AmazonEC2ContainerRegistryReadOnly`.

**Interruption Handling** — механизм подписки на события AWS (Spot Interruption, Instance Rebalance, Scheduled Maintenance). Реализуется через очередь Amazon SQS и правило EventBridge. Позволяет Karpenter начать перенос подов с узла за 2 минуты до его принудительного удаления AWS.

### Архитектура развёртывания

Karpenter работает как Deployment, обычно с 2 репликами для высокой доступности (HA). Он не использует стандартный `kube-scheduler` для создания узлов, а реализует собственный цикл «мониторинг -> бинпакинг -> заказ инстанса». Это позволяет сократить время появления нового узла с 2-3 минут (в случае с Cluster Autoscaler) до 45-60 секунд.

## Практические сценарии

### Полный цикл установки в AWS EKS

#### Шаг 1: Создание инфраструктуры и Pod Identity

```bash
# Создание роли контроллера (пример упрощен)
aws iam create-role --role-name KarpenterControllerRole --assume-role-policy-document ...

# Создание ассоциации Pod Identity
# Это связывает ServiceAccount 'karpenter' в namespace 'karpenter' с IAM-ролью
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --role-arn arn:aws:iam::123456789012:role/KarpenterControllerRole \
  --namespace karpenter \
  --service-account karpenter
```

#### Шаг 2: Установка контроллера через Helm (OCI)

В v1.x крайне важно использовать OCI-репозиторий, так как старый Helm-репозиторий может содержать устаревшие версии.

```bash
# Логин в ECR Public (необязательно, но предотвращает Rate Limit)
aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin oci://public.ecr.aws

# Установка
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version 1.0.1 \
  --namespace karpenter --create-namespace \
  --set settings.clusterName=my-cluster \
  --set settings.interruptionQueue=my-cluster-sqs-queue \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --set controller.resources.limits.cpu=1 \
  --set controller.resources.limits.memory=1Gi \
  --wait
```

#### Шаг 3: Конфигурация универсального NodePool

Данный пример демонстрирует использование v1 API с настроенной ротацией узлов и консолидацией.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  # Суммарные лимиты ресурсов, которыми может управлять этот NodePool
  limits:
    cpu: 1000
    memory: 1000Gi

  template:
    metadata:
      labels:
        billing-team: platform
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      
      # Требования к инстансам
      requirements:
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot", "on-demand"]
        - key: "kubernetes.io/arch"
          operator: In
          values: ["amd64", "arm64"]
        - key: "karpenter.k8s.aws/instance-category"
          operator: In
          values: ["c", "m", "r"]
        - key: "karpenter.k8s.aws/instance-generation"
          operator: Gt
          values: ["2"]

      # Ротация узлов: поле перемещено в spec.template.spec
      # Узлы будут принудительно заменены через 30 дней (лучшая практика для AMI/безопасности)
      expireAfter: 720h
      
      # Время на грациозное завершение подов при удалении узла
      terminationGracePeriod: 48h

  disruption:
    # Консолидация: заменяет узлы на более дешевые или объединяет их
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    
    # Бюджеты прерываний: контролируют темпы удаления узлов. 
    # Karpenter выбирает наиболее ограничительное значение из всех правил.
    budgets:
      - nodes: "15%" # Разрешить прерывание не более 15% узлов
      - nodes: "0"
        schedule: "@daily" # Запретить любые прерывания в первые 15 минут дня
        duration: 15m
      - nodes: "6"
        reasons: ["Underutilized"] # Ограничить количество сбоев до 6 при консолидации
```

#### Шаг 4: Конфигурация EC2NodeClass (глубокая настройка)

Этот ресурс определяет «железо» и параметры безопасности AWS.

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  # Выбор AMI. AL2023 — рекомендуемый стандарт для EKS
  amiFamily: AL2023
  amiSelectorTerms:
    - alias: al2023@latest
  
  # IAM-роль для узлов
  role: KarpenterNodeRole
  
  # Селекторы инфраструктуры (должны быть помечены в AWS соответствующими тегами)
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  
  # Настройка EBS (Encryption, Volume Type, Size)
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        iops: 3000
        throughput: 125
        encrypted: true
        deleteOnTermination: true

  # Безопасность метаданных (IMDSv2 обязателен в v1.x)
  metadataOptions:
    httpEndpoint: enabled
    httpProtocolIPv6: disabled
    httpPutResponseHopLimit: 2
    httpTokens: required # Требует токены для доступа к metadata

  # Пользовательские данные (User Data) для кастомизации узла
  userData: |
    #!/bin/bash
    echo "Custom node configuration"
```

### Сценарий: Изоляция критических нагрузок и GPU

Karpenter позволяет создавать специализированные пулы для тяжелых вычислений.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-pool
spec:
  template:
    spec:
      requirements:
        - key: "karpenter.k8s.aws/instance-gpu-manufacturer"
          operator: In
          values: ["nvidia"]
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"] # GPU обычно не берут в Spot для обучения
      taints:
        - key: "nvidia.com/gpu"
          value: "true"
          effect: "NoSchedule"
  disruption:
    consolidationPolicy: WhenEmpty # Не прерывать обучение при недогрузе CPU
```

## Дополнительная информация

### Диагностика и устранение неисправностей

**Проверка логики планирования**:
Если поды висят в `Pending`, первым делом проверьте логи контроллера. Karpenter пишет подробные сообщения о том, почему он не может подобрать инстанс (например, "no instance types found that meet requirements").

```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100 -f
```

**Работа с NodeClaims**:
NodeClaim — это "чек" на покупку инстанса. Если инстанс не создается в AWS, NodeClaim покажет ошибку API.

```bash
kubectl get nodeclaims
kubectl describe nodeclaim <name>
```

**Защита от прерываний (Disruption)**:
Если вам нужно временно запретить Karpenter удалять узел (например, идет миграция БД), используйте аннотацию:

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
| `karpenter_interruption_actions_total` | Количество реакций на события SQS | Высокая (статистика Spot) |

### Лучшие практики эксплуатации

1.  **Drift Mechanism**: Понимайте, что в v1.x дрейф включен всегда. Любое изменение в `EC2NodeClass` (например, смена Security Group) приведет к тому, что Karpenter начнет планомерно пересоздавать все узлы кластера.
2.  **Spot Diversity**: В `requirements` NodePool всегда указывайте как можно больше типов инстансов. Ограничение пула только одним типом (например, `t3.medium`) в Spot-режиме приведет к невозможности масштабирования при дефиците этого типа в AWS.
3.  **Over-provisioning**: Для сверхбыстрого масштабирования используйте `Pause Pods` (поды с низким приоритетом), которые резервируют место в кластере. Когда появляется реальный под с высоким приоритетом, Karpenter вытесняет `Pause Pod` и мгновенно размещает нагрузку.
4.  **Limits**: Всегда устанавливайте `spec.limits` в NodePool. Это ваш «предохранитель» от бесконечного счета AWS в случае, если баг в приложении вызовет бесконечный спавн подов.

### Ссылки

- **[Обзор и основные концепции Karpenter](./overview.md)** — теоретическая база.
- **[Официальная документация (v1.0)](https://karpenter.sh/v1.0/)** — справочник параметров.
- **[Karpenter Blueprints](https://github.com/aws-samples/karpenter-blueprints)** — готовые шаблоны от AWS.
