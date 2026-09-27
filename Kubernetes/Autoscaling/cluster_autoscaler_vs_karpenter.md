# Cluster Autoscaler vs Karpenter: сравнительный анализ

## Определения

**Cluster Autoscaler (CA)** — контроллер Kubernetes, масштабирующий кластер через абстракцию Node Groups (ASG, MIG, VMSS). Работает по принципу «ожидания Pending-подов» и добавления/удаления узлов из предопределённых групп.

**Karpenter** — контроллер Kubernetes от AWS, реализующий JIT-provisioning (just-in-time) узлов без абстракции Node Groups. Анализирует требования подов и создает узлы «под конкретный под», обеспечивая оптимальный binpacking.

---

## Предварительные требования

| Компонент | Cluster Autoscaler | Karpenter |
|-----------|-------------------|-----------|
| Kubernetes | 1.27+ | 1.25+ (рекомендуется 1.28+) |
| Провайдер | Любой (on-prem через Cluster API) | AWS, Azure, Alibaba Cloud |
| Доступ к API провайдера | Обязателен (IAM, credentials) | Обязателен (IAM, credentials) |
| CRD | Нет (ConfigMap для expander) | NodePool, EC2NodeClass (AWS) |

---

## Теоретический блок

### Архитектурные различия

```
Cluster Autoscaler:
  HPA → Pending Pod → CA видит → Выбирает Node Group → Запрашивает API провайдера
                                                      └── Создаёт узел из группы

Karpenter:
  HPA → Pending Pod → Karpenter видит → Анализирует Pod Requirements
                                      ├── CPU, Memory, GPU, Taints, Affinity
                                      ├── Выбирает тип инстанса (fleet API)
                                      └── Создаёт узел "под конкретный под"
```

### Ключевые различия

| Характеристика | Cluster Autoscaler | Karpenter |
|----------------|-------------------|-----------|
| **Архитектура** | Node Groups (ASG/MIG/VMSS) | JIT-provisioning без групп |
| **Скорость scale-up** | 3–10 минут | 45–90 секунд |
| **Binpacking** | Ограничен размером группы | Оптимальный (под конкретный pod) |
| **Стоимость** | Зависит от группы (on-demand/spot) | Динамический выбор (spot, spot fallback) |
| **On-premise** | Да (через Cluster API, Metal3) | Нет (только облако) |
| **Гибкость узлов** | Фиксированные типы в группе | Динамический выбор типа инстанса |
| **Scale-down** | ~10 минут cooldown | ~30 секунд (после graceful shutdown) |
| **Поддержка DRA** | Да (с 1.32) | Да |
| **ProvisioningRequest** | Да (Beta с 1.30) | Частичная |
| **Конфигурация** | Высокая (Node Groups, Expanders) | Низкая (NodePool) |
| **HA / Leader Election** | Встроенное (Lease, replicas > 1) | Несколько реплик через webhooks |

### When to Use Each

| Сценарий | Рекомендация | Обоснование |
|----------|-------------|-------------|
| **AWS (EKS)** | Karpenter | Лучший binpacking, быстрый scale-up, динамический выбор инстансов |
| **Azure (AKS)** | Karpenter | Поддержка AKS с 2024, JIT-provisioning |
| **On-premise (bare-metal)** | CA + Cluster API | Karpenter не поддерживает bare-metal |
| **Multi-cloud / hybrid** | CA | Единая конфигурация для разных провайдеров |
| **Batch-нагрузки (Volcano)** | CA + ProvisioningRequest | CA поддерживает ProvisioningRequest для batch |
| **GPU/TPU workload** | Karpenter | Динамический выбор GPU-инстансов |
| **Spot-инстансы** | Karpenter | Автоматический fallback на on-demand |
| **Стабильная инфраструктура** | CA | Node Groups обеспечивают предсказуемость |

### Сравнение масштабирования

```
Cluster Autoscaler:
  Time →  0s    60s    120s   180s   300s
          │      │      │      │      │
          Pod    CA     API    Node   Ready
          Pending detects call   Created

Karpenter:
  Time →  0s    15s    30s    45s    60s
          │      │      │      │      │
          Pod    Karp   Fleet  Node   Ready
          Pending enter  API   Created
```

### Binpacking: CA vs Karpenter

**Cluster Autoscaler:**
- Узлы в предопределённых группах (например, m5.xlarge × 10)
- CA не может изменить тип узла внутри группы
- При нехватке ресурсов добавляет узел из группы → может создать «неподходящий» узел

**Karpenter:**
- Анализирует `nodeSelector`, `nodeAffinity`, `tolerations`, resource requests
- Динамически выбирает тип инстанса (m5.xlarge, c5.2xlarge, r5.large)
- Создаёт узел «под конкретный под» → оптимальный binpacking

---

## Практический блок

### Конфигурация Cluster Autoscaler

```yaml
# Deployment CA
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.31.0
          command:
            - ./cluster-autoscaler
            - --v=4
            - --cloud-provider=aws
            - --skip-nodes-with-local-storage=false
            - --expander=priority
            - --balance-similar-node-groups
            - --scale-down-delay-after-add=5m
            - --scale-down-unneeded-time=10m
            - --max-node-provision-time=15m
            - --nodes=2:20:my-worker-group
```

### Конфигурация Karpenter

```yaml
# NodePool для Karpenter
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: default
spec:
  template:
    spec:
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot", "on-demand"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["2"]
      nodeClassRef:
        name: default
  disruption:
    consolidationPolicy: WhenUnderutilized
    expireAfter: 720h
  limits:
    cpu: "100"
    memory: 200Gi
---
# EC2NodeClass
apiVersion: karpenter.k8s.aws/v1beta1
kind: EC2NodeClass
metadata:
  name: default
spec:
  amiFamily: AL2
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
```

### Миграция с CA на Karpenter

```bash
# 1. Установите Karpenter рядом с CA
helm install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --namespace kube-system \
  --set settings.clusterName=my-cluster

# 2. Создайте NodePool для Karpenter
kubectl apply -f nodepool.yaml

# 3. Постепенно переносите workload на Karpenter-узлы
# Добавьте taint на CA-узлы
kubectl taint nodes ca-node node-role=ca:NoSchedule

# 4. Проверьте, что поды мигрируют на Karpenter-узлы
kubectl get pods -o wide | grep ca-node

# 5. Удалите CA
helm uninstall cluster-autoscaler -n kube-system

# 6. Удалите Node Groups (если cloud)
```

### Сравнение конфигурации масштабирования

| Параметр | Cluster Autoscaler | Karpenter |
|----------|-------------------|-----------|
| **Min nodes** | `--nodes=2:20:group` | `spec.limits.cpu` |
| **Max nodes** | `--max-nodes-total=100` | `spec.limits.cpu`, `spec.limits.memory` |
| **Scale-down delay** | `--scale-down-delay-after-add=5m` | `spec.disruption.consolidationPolicy` |
| **Expander** | `--expander=priority` | Динамический (fleet API) |
| **Node labels** | Фиксированы в группе | `spec.template.spec.requirements` |
| **Taints** | Фиксированы в группе | `spec.template.spec.taints` |

---

## Дополнительная информация

### Когда НЕЛЬЗЯ использовать Karpenter

1. **On-premise / bare-metal** — Karpenter не поддерживает
2. **GCP** — используйте Node Auto-Provisioning (NAP)
3. **Старые версии Kubernetes** — Karpenter требует 1.25+
4. **Сложные Node Groups с фиксированными типами** — CA проще для стабильной инфраструктуры
5. **Multi-cluster без облачного провайдера** — CA + Cluster API

### Cost-анализ

| Фактор | Cluster Autoscaler | Karpenter |
|--------|-------------------|-----------|
| **Spot-инстансы** | Ручная настройка ASG | Автоматический fallback |
| **Binpacking** | Средний (группы) | Высокий (JIT) |
| **Over-provisioning** | Высокий (фиксированные группы) | Низкий (динамический выбор) |
| **Instance selection** | Ручной | Автоматический (cost-optimized) |

### См. также

- [Cluster Autoscaler: Глубокое погружение](cluster_autoscaler_detailed.md) — полная документация CA
- [Karpenter: Обзор](Karpenter/overview.md) — архитектура и концепции Karpenter
- [Karpenter: Установка](Karpenter/installation.md) — пошаговая установка
- [Overview: Архитектура](overview_concepts.md) — общая архитектура autoscaling
- [On-premise Autoscaling](on_premise_autoscaling.md) — масштабирование в on-premise
