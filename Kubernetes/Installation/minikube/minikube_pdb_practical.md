# Minikube: PodDisruptionBudget (PDB) на практике

## Определения

**PodDisruptionBudget (PDB)** — ресурс Kubernetes, ограничивающий количество одновременно недоступных подов при **добровольных** прерываниях (planовое обслуживание, drain узла, upgrade). Не защищает от вынужденных сбоев (падение узла, OOMKill). Подробнее: [PodDisruptionBudget](../../../Autoscaling/pod_disruption_budget.md).

**Добровольное прерывание (Voluntary Disruption)** — операция, инициированная администратором или контроллером: `kubectl drain`, обновление Deployment, удаление Pod через eviction API.

**Вынужденное прерывание (Involuntary Disruption)** — сбой, не зависящий от пользователя: падение узла, потеря питания, kernel panic. PDB не действует в таких случаях.

**minAvailable** — минимальное количество подов, которые должны оставаться доступными. PDB блокирует прерывание, если доступных подов станет меньше этого значения.

**maxUnavailable** — максимальное количество подов, которые могут быть недоступны одновременно. Альтернатива `minAvailable`.

---

## Базовые концепции

### PDB в Minikube: особенности

| Параметр | Production | Minikube |
| :--- | :--- | :--- |
| **Узлы** | 3+ master, N worker | 1 (control-plane + worker) |
| **drain узла** | `kubectl drain <node>` — поды мигрируют на другие узлы | `minikube stop` — все поды удаляются без миграции |
| **PDB эффективность** | Критична (защищает от потери доступности) | Ограничена (нет других узлов для миграции) |
| **Тестирование** | Опасно в production | Безопасная лаборатория |

### Когда тестировать PDB в Minikube

- Проверка, что Deployment с PDB корректно блокирует `kubectl drain`.
- Тестирование взаимодействия PDB + Rolling Update.
- Проверка, что `maxUnavailable` корректно ограничивает количество одновременно обновляемых подов.
- Отладка deadlocks (когда PDB + обновление застревают).

---

## Практические сценарии

### Шаг 1: Создание Deployment с PDB

```yaml
# pdb-app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 100m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: web-app
spec:
  selector:
    app: web-app
  ports:
  - port: 80
    targetPort: 80
  type: NodePort
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-app-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: web-app
```

```bash
kubectl apply -f pdb-app.yaml

# Проверка PDB
kubectl get pdb
# → NAME          MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-app-pdb   2               <none>            1                     10s

# Детали PDB
kubectl describe pdb web-app-pdb
# → Name:             web-app-pdb
# → Namespace:        default
# → Min available:    2
# → Selector:         app=web-app
# → Allowances:       Pod usages under spec.minAvailable as maxUnavailable
# → Allowed disruptions:  1
# → Current:          3 pods available, 0 pods unavailable
```

### Шаг 2: Попытка drain с PDB

```bash
# Пометка узла как неschedulable (необходимо для drain)
kubectl cordon minikube
# → node/minikube cordoned

# Попытка drain (PDB заблокирует удаление подов)
kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --timeout=30s
# → node/minikube already cordoned
# → error: unable to drain node "minikube", another error has occurred:
# →   Cannot evict pod as it would violate the pod's disruption budget.
# → The pod "web-app-6d4f5c5x7b-abc12" has 3 Tolerations...

# PDB не даёт выселить поды ниже minAvailable: 2
# Из 3 подов можно выселить только 1 (3 - 2 = 1)

# Раз cordoning — отмена
kubectl uncordon minikube
```

### Шаг 3: Тестирование maxUnavailable

```yaml
# pdb-max-unavailable.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-app-pdb-max
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: web-app
```

```bash
# Удаление старого PDB и создание нового
kubectl delete pdb web-app-pdb
kubectl apply -f pdb-max-unavailable.yaml

# Проверка
kubectl get pdb web-app-pdb-max
# → NAME                MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-app-pdb-max     <none>          1                 1                     10s

# Теперь можно выселить 1 под одновременно
kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --timeout=30s
# → 1 pod будет выселен (доступно останется 2, что >= replicas - maxUnavailable)
```

### Шаг 4: PDB + Rolling Update

```yaml
# rolling-update-with-pdb.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rolling-app
spec:
  replicas: 4
  selector:
    matchLabels:
      app: rolling-app
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  template:
    metadata:
      labels:
        app: rolling-app
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        ports:
        - containerPort: 80
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: rolling-app-pdb
spec:
  minAvailable: 3
  selector:
    matchLabels:
      app: rolling-app
```

```bash
kubectl apply -f rolling-update-with-pdb.yaml

# Проверка PDB
kubectl get pdb rolling-app-pdb
# → NAME               MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → rolling-app-pdb    3               <none>            1                     10s

# Обновление Deployment (PDB + RollingUpdate)
kubectl set image deployment/rolling-app nginx=nginx:1.28

# Наблюдение за rollout
kubectl rollout status deployment/rolling-app --timeout=120s
# → Waiting for rollout to finish: 1 out of 4 new replicas have been updated...
# → Waiting for rollout to finish: 2 out of 4 new replicas have been updated...
# → deployment "rolling-app" successfully rolled out

# PDB гарантировал, что minAvailable: 3 пода были доступны на каждом этапе
kubectl get pdb rolling-app-pdb
# → NAME               MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → rolling-app-pdb    3               <none>            1                     2m
```

### Шаг 5: Диагностика PDB

```bash
# Проверка всех PDB в кластере
kubectl get pdb -A
# → NAMESPACE   NAME               MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
# → default     web-app-pdb        2               <none>            1
# → default     rolling-app-pdb    3               <none>            1

# События PDB (блокировка eviction)
kubectl get events --field-selector reason=PodDisruptionBudget -A
# → LAST SEEN   TYPE      REASON                OBJECT
# → 5m          Warning   PodDisruptionBudget   poddisruptionbudget/web-app-pdb

# Проверка доступных подов
kubectl get pods -l app=web-app -o custom-columns=\
NAME:.metadata.name,\
STATUS:.status.phase,\
READY:.status.conditions[?(@.type=="Ready")].status

# Drain с подробным выводом
kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --timeout=60s --v=7
```

### Шаг 6: PDB через kubectl drain с подтверждением

```bash
# Drain с автоматическим подтверждением (для скриптов)
echo "y" | kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --force

# Drain конкретного пода через eviction API
kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --pod-running-timeout=60s
```

### Очистка

```bash
kubectl delete pdb web-app-pdb rolling-app-pdb
kubectl delete deployment web-app rolling-app
kubectl delete service web-app
kubectl uncordon minikube
```

---

## Дополнительная информация

### См. также

- [PodDisruptionBudget](../../../Autoscaling/pod_disruption_budget.md) — полная теория
- [Deployment: Production Checklist](../../../Base/Deployment/production_checklist.md) — PDB в production
- [Node Maintenance](../../../Operations/node_maintenance.md) — drain/cordon
- [QoS и Requests/Limits](../../../Scheduling/qos_limit_and_requests.md) — влияние на PDB

### Полезные ссылки

- [PodDisruptionBudget — Official Docs](https://kubernetes.io/docs/tasks/run-application/configure-pdb/) — официальная документация
- [Disruption Budgets](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/) — концепции прерываний
