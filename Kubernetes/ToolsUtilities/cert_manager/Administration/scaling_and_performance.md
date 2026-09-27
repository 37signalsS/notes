# Масштабирование и производительность cert-manager

## Определения

**Capacity Planning** — процесс планирования ресурсов (CPU, память, replicas) cert-manager на основе текущей и прогнозируемой нагрузки (количество сертификатов, частота продлений, количество Issuer).

**Reconciler Workqueue** — внутренняя очередь задач контроллера cert-manager. Каждый измененный ресурс (Certificate, Issuer) добавляется в очередь для обработки. Глубина очереди (`workqueue_depth`) является ключевым индикатором перегрузки контроллера.

**Burst Capacity** — способность контроллера обрабатывать всплески нагрузки (например, массовое продление сертификатов при ротации CA или после простоя). Определяется размером workqueue и скоростью обработки.

**Horizontal Pod Autoscaler (HPA)** — механизм горизонтального масштабирования подов на основе метрик (CPU, память, кастомные метрики). Для cert-manager используется с кастомной метрикой `workqueue_depth`.

---

## Основные концепции

### Архитектурные ограничения при масштабировании

cert-manager имеет несколько архитектурных ограничений, которые проявляются при большом количестве сертификатов:

| Компонент | Ограничение | Симптом при превышении |
| :--- | :--- | :--- |
| **Controller** | Кэш всех ресурсов в памяти | OOMKilled, медленная реконсиляция |
| **Webhook** | Синхронная валидация каждого запроса | Timeout при массовом создании ресурсов |
| **Workqueue** | Ограниченная глубина очереди | Зависшие CertificateRequest, Order |
| **API Server** | QPS/Limits на API-сервер | `429 Too Many Requests` от K8s API |
| **etcd** | Скорость записи | Задержка обновления Secret |

### Факторы нагрузки

| Фактор | Влияние | Как измерить |
| :--- | :--- | :--- |
| **Количество Certificate** | Линейное потребление памяти | `kubectl get certificate -A --no-headers | wc -l` |
| **Частота продления** | Нагрузка на CA API | `rate(certmanager_http_acme_client_request_count[5m])` |
| **Количество Issuer** | Увеличение кэша | `kubectl get issuer,clusterissuer -A --no-headers | wc -l` |
| **Количество namespace** | Увеличение scope watched ресурсов | `kubectl get ns --no-headers | wc -l` |
| **Размер Secret** | Нагрузка на etcd | `kubectl get secret -A -o json | jq '.items | length'` |

### Формулы расчета ресурсов

```
# Controller:
# CPU: 1 core на ~500 активных сертификатов
# Memory: ~1MB на каждый отслеживаемый Certificate ресурс + 256Mi базовый overhead
# Memory = 256Mi + (количество_сертификатов * 1Mi)

# Webhook:
# CPU: 1 core на ~100 запросов/сек (ври массовом создании)
# Memory: 128Mi базовый + ~10Mi на 100 одновременных запросов

# Пример для кластера с 2000 сертификатов:
# controller.resources.limits.cpu = 4 cores
# controller.resources.limits.memory = 2Gi (256Mi + 2000*1Mi)
# controller.replicaCount = 3
# webhook.replicaCount = 3
# webhook.resources.limits.memory = 512Mi
```

---

## Практические сценарии

### Сценарий 1: Базовая конфигурация для Production (100–500 сертификатов)

```yaml
# values.yaml для Helm
replicaCount: 2
controller:
  replicaCount: 2
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
webhook:
  replicaCount: 2
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 250m
      memory: 256Mi
  timeoutSeconds: 10
cainjector:
  replicaCount: 1
  resources:
    requests:
      cpu: 25m
      memory: 64Mi
    limits:
      cpu: 100m
      memory: 256Mi
```

### Сценарий 2: Высоконагруженная конфигурация (1000–5000 сертификатов)

```yaml
# values.yaml
replicaCount: 3
controller:
  replicaCount: 3
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi
  extraArgs:
    - --max-concurrent-challenges=10
    - --max-concurrent-orders=10
webhook:
  replicaCount: 3
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  timeoutSeconds: 30
cainjector:
  replicaCount: 2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

### Сценарий 3: Horizontal Pod Autoscaler (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: cert-manager-hpa
  namespace: cert-manager
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: cert-manager
  minReplicas: 2
  maxReplicas: 5
  metrics:
  - type: Pods
    pods:
      metric:
        name: workqueue_depth
      target:
        type: AverageValue
        averageValue: "50"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Pods
        value: 1
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 120
```

### Сценарий 4: PodDisruptionBudget для HA

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: cert-manager-controller-pdb
  namespace: cert-manager
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: cert-manager
      app.kubernetes.io/component: controller
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: cert-manager-webhook-pdb
  namespace: cert-manager
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: cert-manager
      app.kubernetes.io/component: webhook
```

> **Конфликт с Cluster Autoscaler:** Если `minAvailable` слишком жесткий, Cluster Autoscaler не сможет завершить drain узла. Используйте `maxUnavailable: 1` для webhook в кластерах с CA.

### Сценарий 5: NetworkPolicy для снижения нагрузки

Ограничьте исходящий трафик контроллера, чтобы избежать ненужных соединений:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-egress
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app: cert-manager
  policyTypes:
  - Egress
  egress:
  # API-сервер Kubernetes
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - port: 6443
      protocol: TCP
  # ACME-серверы (Let's Encrypt)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - port: 443
      protocol: TCP
  # DNS
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

### Сценарий 6: Оптимизация запросов к API-серверу

При большом количестве сертификатов cert-manager генерирует нагрузку на API-сервер через List/Watch операции. Оптимизация:

```bash
# 1. Проверка QPS к API-серверу
kubectl get --raw /metrics | grep apiserver_request_total | grep cert-manager

# 2. Оптимизация через label selectors в Issuer
# Если возможно, используйте namespace-scoped Issuer вместо ClusterIssuer
# для уменьшения scope watch

# 3. Проверка использования памяти контроллером
kubectl top pods -n cert-manager -l app.kubernetes.io/component=controller

# 4. Проверка глубины очереди
curl -s http://localhost:9402/metrics | grep workqueue_depth
```

### Сценарий 7: Мониторинг производительности

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-performance
  namespace: cert-manager
spec:
  groups:
  - name: cert-manager-performance
    rules:
    - alert: CertManagerWorkqueueBacklog
      expr: certmanager_workqueue_depth > 100
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "cert-manager workqueue глубокий ({{ $value }} задач)"
        description: "Рассмотрите увеличение replicas или ресурсов контроллера"

    - alert: CertManagerHighMemoryUsage
      expr: |
        container_memory_working_set_bytes{namespace="cert-manager",container="cert-manager"}
        / container_spec_memory_limit_bytes{namespace="cert-manager",container="cert-manager"}
        > 0.85
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "cert-manager контроллер использует >85% памяти"

    - alert: CertManagerWebhookHighLatency
      expr: |
        histogram_quantile(0.99, sum(rate(certmanager_webhook_request_duration_seconds_bucket[5m])) by (le))
        > 2
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "cert-manager webhook P99 задержка >2s"

    - alert: CertManagerControllerDown
      expr: up{job="cert-manager"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "cert-manager контроллер недоступен"

    - alert: CertManagerHighReconcileErrors
      expr: rate(certmanager_reconcile_errors_total[5m]) > 0.1
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "cert-manager имеет высокую частоту ошибок реконсиляции"
```

---

## Дополнительная информация

### Рекомендуемая конфигурация по нагрузке

| Количество сертификатов | Controller replicas | Memory limits | CPU limits | Webhook replicas |
| :--- | :--- | :--- | :--- | :--- |
| < 100 | 1 | 256Mi | 500m | 1 |
| 100–500 | 2 | 512Mi | 500m | 2 |
| 500–2000 | 3 | 1Gi | 2000m | 3 |
| 2000–5000 | 3+ (HPA) | 2Gi+ | 2000m+ | 3+ |
| > 5000 | 5+ (HPA) | 4Gi+ | 4000m+ | 3+ (HPA) |

### Антипаттерны

| Антипаттерн | Проблема | Решение |
| :--- | :--- | :--- |
| **1 реплика webhook в Production** | Простой webhook блокирует кластер | min 2 replicas |
| **Нет PDB** | Drain узла убивает все поды cert-manager | PDB с minAvailable: 1–2 |
| **Нет лимитов памяти** | OOMKill при всплеске нагрузки | Явные requests/limits |
| **ClusterIssuer для каждого namespace** | Лишний scope watch, нагрузка на API | Issuer per namespace где возможно |
| **Один Secret на 100 сертификатов** | Конфликты при обновлении | Отдельный Secret на каждый Certificate |

### Смотрите также

- **[Администрирование cert-manager](./index.md)** — HA, PDB и общие настройки.
- **[Операции cert-manager](./operations.md)** — мониторинг и алертинг.
- **[Приватный CA: Операции](../Private_CA/operations.md)** — capacity planning для Private CA.
- **[Production Playbooks](./production_playbooks.md)** — реагирование на инциденты.
