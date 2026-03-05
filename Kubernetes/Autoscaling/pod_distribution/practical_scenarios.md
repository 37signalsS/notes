# Распределение подов: Практические сценарии

## Сценарий 1: Pod Anti-Affinity для веб-приложения

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-frontend
spec:
  replicas: 5
  selector:
    matchLabels:
      app: web-frontend
  template:
    metadata:
      labels:
        app: web-frontend
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app
                    operator: In
                    values:
                      - web-frontend
              topologyKey: "kubernetes.io/hostname"
      containers:
        - name: nginx
          image: nginx:latest
```

**Результат:** Каждая реплика будет размещена на отдельном узле.

## Сценарий 2: Preferred Anti-Affinity (мягкое распределение)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
spec:
  replicas: 10
  selector:
    matchLabels:
      app: api-server
  template:
    metadata:
      labels:
        app: api-server
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - api-server
                topologyKey: "kubernetes.io/hostname"
      containers:
        - name: api
          image: api:latest
```

**Результат:** Планировщик предпочитает распределение по узлам, но может нарушить при нехватке ресурсов.

## Сценарий 3: Topology Spread для мульти-зонного кластера

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: multi-zone-app
spec:
  replicas: 9
  selector:
    matchLabels:
      app: multi-zone-app
  template:
    metadata:
      labels:
        app: multi-zone-app
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: multi-zone-app
          # Необязательно: минимальное количество доменов
          minDomains: 3
      containers:
        - name: app
          image: app:latest
```

**Результат:** Поды будут равномерно распределены по зонам (3-3-3 или 4-3-2 при нарушении).

## Сценарий 4: Комбинированное использование (Anti-Affinity + Topology Spread)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-service
spec:
  replicas: 6
  selector:
    matchLabels:
      app: critical-service
  template:
    metadata:
      labels:
        app: critical-service
    spec:
      # Распределение по узлам (жёсткое)
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app
                    operator: In
                    values:
                      - critical-service
              topologyKey: "kubernetes.io/hostname"

      # Распределение по зонам (мягкое)
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: critical-service
      containers:
        - name: app
          image: app:latest
```

**Результат:**

* Гарантированно не более 1 пода на узел (Anti-Affinity)
* Предпочтительно равномерное распределение по зонам (Topology Spread)

## Сценарий 5: Node Affinity + Pod Anti-Affinity

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-workload
spec:
  replicas: 3
  selector:
    matchLabels:
      app: gpu-workload
  template:
    metadata:
      labels:
        app: gpu-workload
    spec:
      # Только узлы с GPU
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: nvidia.com/gpu
                    operator: Exists

        # Распределение по узлам
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app
                    operator: In
                    values:
                      - gpu-workload
              topologyKey: "kubernetes.io/hostname"
      containers:
        - name: ml-training
          image: ml:latest
          resources:
            limits:
              nvidia.com/gpu: "1"
```

## Диагностика и мониторинг

### Проверка распределения подов

```bash
# Распределение по узлам
kubectl get pods -o wide -l app=my-app

# Распределение по зонам
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.nodeSelector}{"\n"}{end}' -l app=my-app

# Проверка событий планирования
kubectl get events --field-selector reason=FailedScheduling

# Описание пода с информацией о планировании
kubectl describe pod my-pod | grep -A 10 "Affinity\|Topology"
```

### Проверка Pending подов

```bash
# Поды в состоянии Pending
kubectl get pods --field-selector status.phase=Pending

# Причина ожидания
kubectl describe pod pending-pod | grep -A 5 "Events:"
```

**Типичные сообщения:**

* `0/10 nodes are available: 10 node(s) didn't match Pod Anti-Affinity rules` — невозможно выполнить Anti-Affinity
* `0/10 nodes are available: 6 node(s) didn't match topology spread constraints` — нарушение Topology Spread

## Лучшие практики

* **Используйте `topology.kubernetes.io/zone`** — для мульти-зонных кластеров.
* **Настраивайте `maxSkew` с учётом масштаба** — `1` для критических, `2-3` для обычных приложений.
* **Тестируйте поведение при отказе узла** — симулируйте сбой и проверяйте доступность.
* **Для Stateful-приложений приоритизируйте Anti-Affinity** — базы данных, очереди.
* **Комбинируйте с [PDB](pod_disruption_budget.md)** — для максимальной доступности.
* **Избегайте избыточных ограничений** — слишком жёсткие правила могут блокировать планирование.
* **Мониторьте Pending поды** — алерты на поды в `Pending` более 5 минут.

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины
* **[Основные концепции](./basic_concepts.md)** — сравнение механизмов, уровни строгости
* **[Дополнительная информация](./additional_info.md)** — интеграции, ограничения, топология

---

*Этот файл является частью декомпозированной документации. Исходный файл: [pod_distribution.md](../pod_distribution.md)*
