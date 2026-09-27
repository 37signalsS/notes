# Управление ресурсами в K3s: Quota, Limits, HPA

Руководство по управлению ресурсами в K3s: ResourceQuota, LimitRange, requests/limits, Pod Disruption Budget, Horizontal Pod Autoscaler. Адаптировано для dev-окружения с ограниченными ресурсами.

Контекст: В dev-окружении K3s критично ограничивать потребление ресурсов, так как GitLab, Harbor и ArgoCD работают на одном сервере. См. [Архитектура K3s](./k3s_architecture.md), [NetworkPolicy](./k3s_network_policies.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **ResourceQuota** | Ограничение суммарного потребления ресурсов в namespace. Задает лимиты на CPU, RAM, количество подов, PVC и других объектов. |
| **LimitRange** | Установка de facto limits/requests для подов, которые не указали их явно. Предотвращает запуск подов без лимитов. |
| **requests** | Минимальные ресурсы, которые Kubernetes резервирует для пода. Используются scheduler'ом для размещения. |
| **limits** | Максимальные ресурсы, которые под может потребить. При превышении RAM — OOMKill; CPU — throttling. |
| **QoS (Quality of Service)** | Классификация подов по уровню гарантии ресурсов: Guaranteed, Burstable, BestEffort. Определяет порядок evicting при нехватке ресурсов. |
| **PodDisruptionBudget (PDB)** | Ограничение на количество одновременно недоступных подов при volunteer disruptions (drain, upgrade). Не защищает от OOMKill или node failure. |
| **HorizontalPodAutoscaler (HPA)** | Автоматическое масштабирование количества подов на основе метрик (CPU, RAM, custom). Работает через Deployment/ReplicaSet. |
| **PriorityClass** | Определение приоритета подов. Поды с низким приоритетом могут быть evicted для освобождения ресурсов подам с высоким приоритетом. |

Навигация: [Requests/Limits](../../Scheduling/qos_limit_and_requests.md) | [HPA](../../Autoscaling/HPA/index.md) | [PDB](../../Autoscaling/pod_disruption_budget.md)

---

## Основные концепции

### Модель ресурсов в K3s

```text
┌─────────────────────────────────────────────────────────────────┐
│                     K3s Node (4 CPU, 16 ГБ RAM)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  System (K3s + OS): ~2 CPU, ~4 ГБ RAM                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ K3s Control Plane (API, scheduler, controller-manager)     │  │
│  │ containerd, Flannel/CoreDNS, kubelet                       │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Доступно для приложений: ~2 CPU, ~12 ГБ RAM                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ GitLab (4 requests, 8 limits)                              │  │
│  │ Harbor (2 requests, 4 limits)                              │  │
│  │ ArgoCD (0.5 requests, 1 limits)                            │  │
│  │ Monitoring (1 requests, 3 limits)                           │  │
│  │ dev-containers (1 requests, 4 limits)                       │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ResourceQuota (namespace-level):                                │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ requests.cpu: "8", requests.memory: "12Gi"                │  │
│  │ limits.cpu: "16", limits.memory: "20Gi"                   │  │
│  │ pods: "20", services: "10"                                │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  LimitRange (namespace-level):                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Default request: cpu=100m, memory=128Mi                    │  │
│  │ Default limit: cpu=500m, memory=512Mi                      │  │
│  │ Max limit: cpu=4, memory=8Gi                               │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### QoS Classes

| QoS Class | Условие | Eviction Priority | Пример |
| :--- | :--- | :--- | :--- |
| **Guaranteed** | requests == limits для всех контейнеров | Последний (самый защищенный) | Critical-сервисы (monitoring) |
| **Burstable** | requests < limits (хотя бы для одного контейнера) | Средний | GitLab, Harbor |
| **BestEffort** | Не указаны ни requests, ни limits | Первый (самый уязвимый) | Тестовые поды |

### Приоритеты в dev-окружении

| Приоритет | Сервис | Рекомендация |
| :--- | :--- | :--- |
| **Высокий** | K3s system pods, monitoring | Guaranteed QoS, без evicting |
| **Средний** | GitLab, Harbor, ArgoCD | Burstable, с limits |
| **Низкий** | Dev-containers | Burstable, могу быть evicted |
| **最低** | Тестовые поды | BestEffort или низкий PriorityClass |

---

## Требования и предварительная подготовка

### Планирование ресурсов для dev-окружения

| Сервис | CPU Request | CPU Limit | Memory Request | Memory Limit | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **K3s (system)** | 1000m | 2000m | 2048Mi | 4096Mi | Резерв для system |
| **GitLab** | 4000m | 8000m | 4096Mi | 8192Mi | Основной потребитель |
| **Harbor** | 2000m | 4000m | 2048Mi | 4096Mi | Core + Registry + Trivy |
| **ArgoCD** | 500m | 1000m | 512Mi | 1024Mi | Легковесный |
| **Monitoring** | 1000m | 3000m | 3072Mi | 6144Mi | Prometheus + Grafana |
| **Dev-containers** | 500m | 2000m | 512Mi | 4096Mi | На каждого разработчика |
| **Итого** | ~9000m | ~20000m | ~12288Mi | ~28416Mi | Нужен сервер 4+ CPU, 16+ ГБ |

---

## Практические сценарии

### 1. ResourceQuota для namespace

```yaml
# resourcequota-dev-workspaces.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: dev-workspaces-quota
  namespace: dev-workspaces
spec:
  hard:
    # CPU
    requests.cpu: "4"
    limits.cpu: "8"
    # Память
    requests.memory: "8Gi"
    limits.memory: "16Gi"
    # Объекты
    pods: "10"
    services: "5"
    services.loadbalancers: "1"
    services.nodeports: "2"
    persistentvolumeclaims: "5"
    # Секреты и ConfigMaps
    secrets: "20"
    configmaps: "20"
```

```yaml
# resourcequota-gitlab.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: gitlab-quota
  namespace: gitlab
spec:
  hard:
    requests.cpu: "6"
    limits.cpu: "12"
    requests.memory: "8Gi"
    limits.memory: "16Gi"
    pods: "30"
    services: "10"
    persistentvolumeclaims: "10"
```

```bash
# Применение
kubectl apply -f resourcequota-dev-workspaces.yaml
kubectl apply -f resourcequota-gitlab.yaml

# Проверка использования
kubectl -n dev-workspaces get resourcequota
# → NAME                     AGE    REQUEST            LIMIT
# → dev-workspaces-quota     30s    cpu: 1/4, memory: 2Gi/8Gi   cpu: 2/8, memory: 4Gi/16Gi

# Детали
kubectl -n dev-workspaces describe resourcequota dev-workspaces-quota
# → Name:                   dev-workspaces-quota
# → Resource                Used   Hard
# --------                  ----   ----
# limits.cpu                2      8
# limits.memory             4Gi    16Gi
# pods                      2      10
# requests.cpu              1      4
# requests.memory           2Gi    8Gi
```

### 2. LimitRange для default limits

```yaml
# limitrange-dev-workspaces.yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: dev-workspace-limits
  namespace: dev-workspaces
spec:
  limits:
    - type: Container
      default:
        cpu: 500m
        memory: 512Mi
      defaultRequest:
        cpu: 100m
        memory: 128Mi
      max:
        cpu: 4
        memory: 8Gi
      min:
        cpu: 50m
        memory: 64Mi
    - type: Pod
      max:
        cpu: 8
        memory: 16Gi
    - type: PersistentVolumeClaim
      max:
        storage: 50Gi
      min:
        storage: 1Gi
```

```bash
kubectl apply -f limitrange-dev-workspaces.yaml

# Проверка
kubectl -n dev-workspaces get limitrange
# → NAME                      CREATED AT
# → dev-workspace-limits      30s

# Теперь поды БЕЗ resources автоматически получат default limits
# (но лучше всегда указывать явно!)
```

### 3. Pod Disruption Budget (PDB)

```yaml
# pdb-gitlab-webservice.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: gitlab-webservice-pdb
  namespace: gitlab
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: webservice
```

```yaml
# pdb-harbor-core.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: harbor-core-pdb
  namespace: harbor
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: harbor-core
```

```yaml
# pdb-monitoring.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: prometheus-pdb
  namespace: monitoring
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: prometheus
```

```bash
kubectl apply -f pdb-gitlab-webservice.yaml
kubectl apply -f pdb-harbor-core.yaml
kubectl apply -f pdb-monitoring.yaml

# Проверка
kubectl get pdb -A
# → NAME                     MIN AVAILABLE   MAX UNAVAILABLE   SELECTOR
# → gitlab-webservice-pdb    2               <none>            app=webservice
# → harbor-core-pdb          <none>          1                 app=harbor-core
# → prometheus-pdb           1               <none>            app.kubernetes.io/name=prometheus
```

### 4. Horizontal Pod Autoscaler (HPA)

```yaml
# hpa-gitlab-webservice.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gitlab-webservice-hpa
  namespace: gitlab
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gitlab-webservice-default
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
```

```yaml
# hpa-dev-container.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: dev-container-hpa
  namespace: dev-workspaces
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: dev-container
  minReplicas: 1
  maxReplicas: 3
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 75
```

```bash
kubectl apply -f hpa-gitlab-webservice.yaml
kubectl apply -f hpa-dev-container.yaml

# Проверка
kubectl get hpa -A
# → NAME                    REFERENCE                     TARGETS         MINPODS   MAXPODS
# → gitlab-webservice-hpa   Deployment/gitlab-webservice  45%/70%, 60%/80%   2         5
# → dev-container-hpa       Deployment/dev-container      30%/75%             1         3

# Детали
kubectl describe hpa gitlab-webservice-hpa -n gitlab
# → Metrics:   ( current / target )
# →   cpu:     45% / 70%
# →   memory:  60% / 80%
# → Conditions:
# →   Type              Status  Reason
# →   AbleToScale       True    ReadyForNewScale
# →   ScalingActive     True    ValidMetricForRecommendation
```

### 5. PriorityClass для dev-окружения

```yaml
# priorityclass-critical.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: system-critical
value: 1000000
globalDefault: false
description: "Для системных подов K3s (monitoring, ingress)"
---
# priorityclass-high.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-services
value: 100000
globalDefault: false
description: "Для GitLab, Harbor, ArgoCD"
---
# priorityclass-default.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: dev-workloads
value: 1000
globalDefault: true
description: "Для dev-контейнеров и тестовых подов"
```

```bash
kubectl apply -f priorityclass-critical.yaml

# Использование в поде
# spec:
#   priorityClassName: system-critical
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: Pod не запускается из-за ResourceQuota

```bash
# Проверка квоты
kubectl -n dev-workspaces describe resourcequota
# → Warning  FailedCreate  pod/dev-container-xxx   Error creating: pods "dev-container-xxx" is forbidden:
# → exceeded quota: dev-workspaces-quota, used: cpu: 4, requested: 5

# Решение: освободите ресурсы (уменьшите limits у других подов или увеличьте квоту)
```

### Ошибка: LimitRange конфликтует с HPA

```bash
# HPA пытается установить requests > limit → ошибка
# Решение: убедитесь, что default request < default limit в LimitRange
# И что HPA target utilization < 100%
```

### Ошибка: Pod killed из-за OOMKill

```bash
# Проверка
kubectl -n dev-workspaces get events --field-selector reason=OOMKilling
# → Ищите поды с limits.memory < фактическому потреблению

# Решение: увеличьте limits.memory или оптимизируйте приложение
kubectl -n dev-workspaces set resources deployment/dev-container \
  --limits=memory=8Gi \
  --requests=memory=2Gi
```

---

## Дополнительная информация

### Рекомендации для dev-окружения

| Практика | Рекомендация |
| :--- | :--- |
| **Всегда указывайте requests/limits** | Не полагайтесь на LimitRange defaults |
| **ResourceQuota на каждый namespace** | Предотвращает "сервис-убийца" |
| **PDB для критичных сервисов** | GitLab, Harbor, monitoring |
| **HPA осторожно** | В dev-окружении с 1 нодой HPA может быть избыточен |
| **PriorityClass** | Гарантирует, что системные поды не evict'ятся |

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **ResourceQuota** | Блокирует создание подов | Мониторьте использование через `kubectl describe resourcequota` |
| **LimitRange** | Конфликтует с HPA | Убедитесь, что HPA не превышает limits |
| **PDB + drain** | PDB блокирует drain при upgrade | Проверяйте PDB перед обновлением |
| **Одиночная нода** | HPA не может распределить нагрузку | Используйте HPA только дляreichability, не для масштабирования |

### См. также

- [Requests/Limits](../../Scheduling/qos_limit_and_requests.md) -- глубокое погружение
- [HPA](../../Autoscaling/HPA/index.md) -- полный обзор HPA
- [PDB](../../Autoscaling/pod_disruption_budget.md) -- управление disruptions
- [Архитектура K3s](./k3s_architecture.md) -- ресурсы компонентов
- [NetworkPolicy](./k3s_network_policies.md) -- сетевая изоляция
