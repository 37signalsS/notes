# kind — тестирование ResourceQuota и LimitRange

## Определения

**ResourceQuota** — объект Kubernetes, ограничивающий суммарное потребление ресурсов (CPU, RAM, количество объектов) в рамках конкретного Namespace. Предотвращает «эгоистичное» потребление ресурсов одним проектом.

**LimitRange** — объект Kubernetes, задающий минимальные и максимальные значения `requests` и `limits` для контейнеров в Namespace. Если разработчик не указал ресурсы в манифесте, LimitRange подставляет значения по умолчанию.

**Requests** — минимальный объём ресурсов (CPU/RAM), который гарантируется контейнеру при планировании на узел.

**Limits** — максимальный объём ресурсов, который контейнер может потребить. При превышении RAM-лимита под будет завершён (OOMKilled).

---

## Основные концепции

### Зачем тестировать ResourceQuota/LimitRange в kind

kind позволяет безопасно тестировать политики контроля ресурсов:

- Проверить, что квоты действительно блокируют превышение лимитов
- Отработать ошибки `exceeded quota` и `Insufficient cpu/memory`
- Настроить LimitRange для автоматической подстановки requests/limits
- Протестировать взаимодействие квот с HPA и autoscaling

### Порядок создания объектов

```
Namespace → LimitRange → ResourceQuota → Pod/Deployment
```

> **Важно:** LimitRange и ResourceQuota должны быть созданы ДО подов, иначе поды без указания ресурсов будут отклонены.

### Типы ограничений

| Объект | Ограничает | Пример |
|:---|:---|:---|
| **ResourceQuota** | Суммарные ресурсы в Namespace | `cpu=10, memory=20Gi, pods=50` |
| **LimitRange** | Ресурсы одного контейнера | `min=100m/128Mi, max=2/4Gi` |

---

## Практические сценарии

### Создание кластера для тестирования

```bash
kind create cluster --name quota-test
```

### Сценарий 1: Базовая ResourceQuota

```yaml
# resource-quota.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-backend
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: backend-quota
  namespace: team-backend
spec:
  hard:
    # Ресурсы
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    # Объекты
    pods: "20"
    services: "10"
    configmaps: "20"
    secrets: "20"
    persistentvolumeclaims: "5"
```

```bash
kubectl apply -f resource-quota.yaml

# Проверка текущего потребления
kubectl describe resourcequota backend-quota -n team-backend
# → Name:                   backend-quota
# → Resource                Used  Hard
# → --------                ----  ----
# → limits.cpu              0     8
# → limits.memory           0     16Gi
# → pods                    0     20
# → requests.cpu            0     4
# → requests.memory         0     8Gi

# Попытка создания пода без ресурсов (должна быть отклонена, если LimitRange настроен)
kubectl run test-pod --image=nginx --namespace=team-backend
# → Error: pods "test-pod" is forbidden: failed quota: backend-quota: must specify limits.cpu,limits.memory,requests.cpu,requests.memory
```

### Сценарий 2: LimitRange с дефолтными значениями

```yaml
# limit-range.yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: backend-limits
  namespace: team-backend
spec:
  limits:
  - type: Container
    # Минимальные значения (обязательны для указания)
    min:
      cpu: 100m
      memory: 128Mi
    # Максимальные значения
    max:
      cpu: "2"
      memory: 4Gi
    # Значения по умолчанию (подставляются, если не указаны)
    default:
      cpu: 500m
      memory: 512Mi
    # Default request (если не указаны requests)
    defaultRequest:
      cpu: 250m
      memory: 256Mi
```

```bash
kubectl apply -f limit-range.yaml

# Теперь под БЕЗ указания ресурсов создаётся (LimitRange подставляет дефолты)
kubectl run auto-pod --image=nginx --namespace=team-backend
# → pod/auto-pod created

# Проверка: ресурсы подставлены автоматически
kubectl get pod auto-pod -n team-backend -o jsonpath='{.spec.containers[0].resources}'
# → {"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"250m","memory":"256Mi"}}

# Попытка превысить max (должна быть отклонена)
kubectl run huge-pod --image=nginx --namespace=team-backend --overrides='{"spec":{"containers":[{"name":"huge-pod","image":"nginx","resources":{"limits":{"cpu":"4","memory":"8Gi"}}}]}'
# → Error: pods "huge-pod" is forbidden: container "huge-pod" max cpu (2) is greater than limit (2)
```

### Сценарий 3: Блокировка масштабирования из-за квоты

```yaml
# test-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-app
  namespace: team-backend
spec:
  replicas: 5
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: app
        image: nginx
        resources:
          requests:
            cpu: 1
            memory: 1Gi
```

```bash
kubectl apply -f test-deployment.yaml

# Проверка: сколько подов реально запущено
kubectl get pods -n team-backend
# → NAME                          READY   STATUS    RESTARTS   AGE
# → backend-app-xxxxx-yyyyy       1/1     Running   0          30s
# → backend-app-xxxxx-zzzzz       1/1     Running   0          30s
# → backend-app-xxxxx-aaaa        1/1     Running   0          30s
# → backend-app-xxxxx-bbbb        0/1     Pending   0          30s  ← exceeds quota

# Проверка квоты: исчерпана
kubectl describe resourcequota backend-quota -n team-backend
# → Name:                   backend-quota
# → Resource                Used  Hard
# → --------                ----  ----
# → pods                    4     20
# → requests.cpu            4     4    ← исчерпано!
# → requests.memory         4Gi   8Gi

# Попытка масштабирования до 10 (все равно будет ограничено квотой)
kubectl scale deployment backend-app --replicas=10 -n team-backend
# → deployment.apps/backend-app scaled
# Но реально: поды будут в Pending из-за нехватки CPU в квоте
```

### Сценарий 4: Взаимодействие ResourceQuota с HPA

```yaml
# hpa-test-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hpa-app
  namespace: team-backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: hpa-app
  template:
    metadata:
      labels:
        app: hpa-app
    spec:
      containers:
      - name: app
        image: nginx
        resources:
          requests:
            cpu: 500m
            memory: 256Mi
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-app
  namespace: team-backend
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hpa-app
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

```bash
kubectl apply -f hpa-test-deployment.yaml

# Проблема: ResourceQuota может заблокировать scale-up
# Расчёт: maxReplicas (10) × requests.cpu (500m) = 5 CPU
# Но квота: requests.cpu = 4 CPU ← недостаточно!

# Решение: увеличить квоту
kubectl patch resourcequota backend-quota -n team-backend --type='json' -p='[
  {"op":"replace","path":"/spec/hard/requests.cpu","value":"8"},
  {"op":"replace","path":"/spec/hard/limits.cpu","value":"16"},
  {"op":"replace","path":"/spec/hard/requests.memory","value":"16Gi"},
  {"op":"replace","path":"/spec/hard/limits.memory","value":"32Gi"}
]'
```

### Сценарий 5: Диагностика проблем с квотами

**Типичные ошибки:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `exceeded quota: backend-quota` | Суммарные ресурсы превышают лимит | Увеличить ResourceQuota или уменьшить requests подов |
| `must specify limits.cpu,limits.memory` | LimitRange требует явного указания ресурсов | Добавить `resources.limits` в манифест |
| `Insufficient cpu` | Недостаточно CPU для scheduling | Уменьшить requests или добавить узлы |
| `pod count exceeds quota` | Лимит на количество подов исчерпан | Увеличить `pods` в ResourceQuota |

**Команды диагностики:**

```bash
# Проверка ResourceQuota во всех неймспейсах
kubectl get resourcequotas --all-namespaces

# Детальный просмотр конкретной квоты
kubectl describe resourcequota backend-quota -n team-backend

# Проверка LimitRange
kubectl get limitranges -n team-backend
kubectl describe limitrange backend-limits -n team-backend

# Проверка: какие поды ожидают из-за квоты
kubectl get pods -n team-backend --field-selector=status.phase=Pending

# Просмотр событий (ошибки квоты)
kubectl get events -n team-backend --field-selector reason=FailedCreate
```

### Сценарий 6: Очистка квоты перед удалением Namespace

```bash
# ResourceQuota блокирует удаление Namespace, если есть поды в Terminating
# Сначала удалите все поды
kubectl delete pods --all -n team-backend

# Затем удалите ResourceQuota
kubectl delete resourcequota backend-quota -n team-backend

# Удалите Namespace
kubectl delete namespace team-backend
```

---

## Дополнительная информация

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура и внутреннее устройство узлов
- [QoS, LimitRange и Requests/Limits](../../Scheduling/qos_limit_and_requests.md) — полная теория
- [ResourceQuota и RBAC](../../Security/rbac/resource_quota_rbac.md) — управление квотами через RBAC
- [Cluster Autoscaler и ResourceQuota](../../Autoscaling/cluster_autoscaler_detailed.md) — взаимодействие CA с квотами
- [HPA и ResourceQuota](../../Autoscaling/HPA/hpa_advanced.md) — взаимодействие HPA с квотами
- [Официальная документация ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
