# Progressive Delivery для Deployment

Интеграция прогрессивной доставки с Kubernetes Deployment: миграция на Argo Rollouts, совместимость с существующими Deployment и специфические паттерны.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+).
- Установленный Argo Rollouts или Flagger.
- Service Mesh (Istio/Linkerd) или Gateway API для управления трафиком.
- Базовое понимание [Deployment](./index.md).

## 1. Определения

**Progressive Delivery** — подход к доставке обновлений, при котором новые версии разворачиваются постепенно с автоматическим анализом метрик и возможностью автоматического отката при обнаружении проблем.

> Общая теория, сравнение стратегий (Rolling, Blue-Green, Canary, A/B, Shadow) и детальные примеры реализации см. в [сравнении стратегий](../../../CI-CD/Deployment_Strategies/comparison.md), [Canary Deployment](../../../CI-CD/Deployment_Strategies/canary_deployment.md), [Blue-Green Deployment](../../../CI-CD/Deployment_Strategies/blue_green_deployment.md) и [Progressive Delivery в GitOps](../../../GitOps/Concepts/progressive_delivery_gitops.md).

## 2. Базовые концепции

### Deployment vs Rollout: что меняется

| Аспект | Deployment | Rollout (Argo Rollouts) |
|:-------|:-----------|:------------------------|
| **API** | `apps/v1` | `argoproj.io/v1alpha1` |
| **Стратегия** | `RollingUpdate` / `Recreate` | `canary` / `blueGreen` с шагами |
| **Анализ** | Нет (только пробы) | AnalysisTemplate + Prometheus |
| **Откат** | Ручной (`rollout undo`) | Автоматический по метрикам |
| **Трафик** | Балансировка через Service | Управление через Gateway API/Istio |
| **CLI** | `kubectl rollout` | `kubectl argo rollouts` |

### Миграция с Deployment на Rollout

```bash
# 1. Экспортировать текущий Deployment
kubectl get deployment my-app -o yaml > my-app-deployment.yaml

# 2. Заменить kind и apiVersion
# kind: Deployment → kind: Rollout
# apiVersion: apps/v1 → apiVersion: argoproj.io/v1alpha1

# 3. Добавить секцию strategy с canary/blueGreen параметрами

# 4. Применить Rollout
kubectl apply -f my-app-rollout.yaml

# 5. Argo Rollouts автоматически подхватит существующие поды
```

**Важно:** При миграции с Deployment на Rollout:
- Rollout **заменяет** Deployment (не работает параллельно)
- Существующие поды **не пересоздаются** (происходит плавный переход)
- Service остаются без изменений
- HPA должен быть перенастроен на Rollout (не на Deployment)

### Взаимодействие с HPA

```yaml
# HPA работает с Rollout так же, как с Deployment
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app
spec:
  scaleTargetRef:
    apiVersion: argoproj.io/v1alpha1  # ← изменить с apps/v1
    kind: Rollout                      # ← изменить с Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

**Подвох:** Если HPA ссылается на Deployment, а Rollout уже создан — HPA будет конфликтовать. Всегда проверяйте `scaleTargetRef`.

### Взаимодействие с PDB

```yaml
# PDB работает с Rollout так же, как с Deployment
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: my-app
```

**Важно:** При canary-обновлении PDB может блокировать удаление старых подов. Убедитесь, что `minAvailable` совместим с `maxUnavailable` в Rollout.

### Rollback: Deployment vs Rollout

```bash
# Deployment: ручной откат
kubectl rollout undo deployment/my-app
# Результат: новая ревизия с предыдущим шаблоном

# Rollout: автоматический откат при провале анализа
# Настройка в AnalysisTemplate:
# failureLimit: 3 → после 3 неудачных проверок → автоматический откат

# Rollout: ручной откат
kubectl argo rollouts abort my-app
# Результат: возврат к стабильной версии

# Rollout: откат к конкретной версии
kubectl argo rollouts undo my-app
```

**Ключевое отличие:** Rollout откатывает **по метрикам** (automated), а Deployment — только **по времени** (progressDeadlineSeconds). Это критичное преимущество для production.

## 3. Практические сценарии

### Минимальный Rollout вместо Deployment

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: app
        image: my-registry.com/app:v1
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 500m
            memory: 512Mi
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
  strategy:
    canary:
      canaryService: my-app-canary
      stableService: my-app-stable
      trafficRouting:
        gatewayAPI:
          parentRefs:
          - name: production-gateway
            namespace: istio-system
      steps:
      - setWeight: 10
      - pause: {duration: 5m}
      - analysis:
          templates:
          - templateName: quick-check
      - setWeight: 50
      - pause: {duration: 5m}
      - analysis:
          templates:
          - templateName: full-check
      - setWeight: 100
---
apiVersion: v1
kind: Service
metadata:
  name: my-app-canary
spec:
  selector:
    app: my-app
  ports:
  - port: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: my-app-stable
spec:
  selector:
    app: my-app
  ports:
  - port: 8080
```

### AnalysisTemplate для Deployment-метрик

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: quick-check
spec:
  args:
  - name: deployment-name
  metrics:
  - name: error-rate
    interval: 1m
    count: 3
    successCondition: result[0] < 0.05
    failureLimit: 2
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          sum(rate(http_requests_total{deployment="{{args.deployment-name}}",code=~"5.."}[5m]))
          /
          sum(rate(http_requests_total{deployment="{{args.deployment-name}}"}[5m]))
  - name: readiness-ratio
    interval: 30s
    count: 3
    successCondition: result[0] >= 0.9
    failureLimit: 2
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          kube_deployment_status_replicas_ready{deployment="{{args.deployment-name}}"}
          /
          kube_deployment_spec_replicas{deployment="{{args.deployment-name}}"}
```

### Flagger: автономный canary для Deployment

```yaml
# Flagger работает поверх существующего Deployment (без замены на Rollout)
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: my-app
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment      # ← Flagger управляет Deployment
    name: my-app
  progressDeadlineSeconds: 600
  service:
    port: 8080
    targetPort: 8080
    gateways:
    - production-gateway
    hosts:
    - my-app.example.com
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
    - name: request-success-rate
      thresholdRange:
        min: 99
      interval: 1m
    - name: request-duration
      thresholdRange:
        max: 500
      interval: 1m
```

**Преимущество Flagger:** не нужно заменять Deployment на Rollout. Flagger создаетcanary-Deployment автоматически и управляет трафиком.

## 4. Дополнительная информация

### См. также
- [Canary Deployment](../../../CI-CD/Deployment_Strategies/canary_deployment.md) — детальный гайд по Canary (12 сценариев).
- [Blue-Green Deployment](../../../CI-CD/Deployment_Strategies/blue_green_deployment.md) — детальный гайд по Blue-Green (12 сценариев).
- [Canary Monitoring](../../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md) — мониторинг и автоматический gating (423 строки).
- [Progressive Delivery в GitOps](../../../GitOps/Concepts/progressive_delivery_gitops.md) — интеграция с ArgoCD/Flux (441 строка).
- [Comparison](../../../CI-CD/Deployment_Strategies/comparison.md) — сравнение всех стратегий (500 строк).
- [Advanced Rollback](./advanced_rollback_strategies.md) — стратегии отката.
- [Deployment с GitOps](./deployment_with_gitops.md) — интеграция с ArgoCD/Flux.
