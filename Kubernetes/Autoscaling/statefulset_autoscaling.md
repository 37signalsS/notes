# Масштабирование StatefulSet: HPA, KEDA и паттерны

## Определения

**StatefulSet** — контроллер Kubernetes для управления подами с именами, сохраняющимися после пересоздания, стабильными сетевыми идентификаторами и постоянными томами (PersistentVolumeClaims). Используется для Stateless-приложений, требующих стабильности: базы данных, очередей сообщений, кластеров.

**`/scale` подресурс** — Kubernetes API-эндпоинт, через который HPA и KEDA изменяют количество реплик Deployment, ReplicaSet или StatefulSet. StatefulSet реализует `/scale`, что позволяет внешним контроллерам управлять `spec.replicas`.

**Patroni** — менеджер кластеров для PostgreSQL, который управляет `spec.replicas` StatefulSet через свой контроллер. При использовании совместно с KEDA необходимо согласование логики масштабирования.

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| Kubernetes | 1.27 | 1.31+ | Стабильный `/scale` для StatefulSet |
| HPA | autoscaling/v2 | autoscaling/v2 | Поддержка StatefulSet через `scaleTargetRef` |
| Metrics Server | 0.6.0+ | 0.7.0+ | Для HPA по CPU/Memory |
| KEDA | 2.12+ | 2.14+ | Для event-driven масштабирования |

---

## Теоретический блок

### Особенности масштабирования StatefulSet

StatefulSet принципиально отличается от Deployment при масштабировании:

| Характеристika | Deployment | StatefulSet |
|----------------|------------|-------------|
| Имена подов | Случайные (hash) | Детерминированные (`pod-0`, `pod-1`) |
| Порядок удаления | Произвольный (LRU) | С конца (pod-N, pod-N-1, ...) |
| Тома | Общие (emptyDir) | Индивидуальные (PVC per pod) |
| Сеть | Сервисная (ClusterIP) | Стабильная (`pod-0.statefulset.ns.svc.cluster.local`) |
| Перезапуск при обновлении | Rolling (все поды) | Rolling (последовательно) |

**Ключевые ограничения:**

1. HPA не может удалить под с индексом `0` до тех пор, пока все остальные поды не будут удалены
2. Масштабирование вниз удаляет поды с конца, что критично для Stateful приложений (БД, очереди)
3. PersistentVolumeClaims привязаны к индексам — при масштабировании вниз PVC не удаляются автоматически
4. При масштабировании вверх поды создаются последовательно (`pod-N+1` запускается после Ready `pod-N`)

### Стратегии масштабирования StatefulSet

#### 1. HPA + StatefulSet (CPU/Memory/RPS)

HPA изменяет `spec.replicas` через `/scale` подресурс. Подходит для Stateless-приложений в StatefulSet (API-серверы, веб-frontend).

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: statefulset-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: my-statefulset
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
```

**Важно:** `stabilizationWindowSeconds: 600` для scaleDown защищает от случайного удаления подов с данными.

#### 2. KEDA + StatefulSet (event-driven)

KEDA масштабирует StatefulSet по метрикам из внешних источников (Kafka lag, RabbitMQ queue length, Prometheus).

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: kafka-consumer
  pollingInterval: 15
  cooldownPeriod: 300
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka.svc:9092
        consumerGroup: my-group
        lagThreshold: "100"
        activationLagThreshold: "10"
```

**Особенности KEDA + StatefulSet:**
- KEDA создаёт HPA для каждого ScaledObject, который управляет `/scale` StatefulSet
- `minReplicaCount` должен быть >= 1 для StatefulSet (scale-to-zero не рекомендуется для stateful приложений)
- KEDA учитывает PVC и стабильные имена при принятии решений

#### 3. Ручное масштабирование (kubectl scale)

```bash
# Масштабирование вверх
kubectl scale statefulset my-statefulset --replicas=5
# → statefulset.apps/my-statefulset scaled

# Проверка порядка создания подов
kubectl get pods -l app=my-statefulset -w
# → my-statefulset-0   Ready   1/1
# → my-statefulset-1   Ready   1/1
# → my-statefulset-2   Pending 0/1   ← создается последовательно
```

### Паттерны масштабирования для типичных стеков

#### PostgreSQL (Patroni + StatefulSet)

```yaml
# Patroni управляет репликами через StatefulSet
# KEDA мониторит и масштабирует по нагрузке
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
spec:
  serviceName: postgresql
  replicas: 3
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
        - name: postgresql
          image: postgres:16
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 4Gi
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

**Важно:** При использовании Patroni KEDA не должен управлять `spec.replicas` напрямую — Patroni контролирует количество реплик через свой API. KEDA лучше использовать через Prometheus scaler для мониторинга, а не для прямого управления.

#### Redis Cluster (StatefulSet + KEDA)

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: redis-cluster-scaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: redis-cluster
  minReplicaCount: 6
  maxReplicaCount: 12
  triggers:
    - type: redis
      metadata:
        address: redis-cluster.svc:6379
        listName: my-queue
        listLength: "1000"
```

### Конфликты и edge cases

| Сценарий | Проблема | Решение |
|----------|----------|---------|
| HPA + PVC | При scale-down PVC привязаны к индексам, не удаляются | Настройте `volumeClaimTemplates` с `Retain` policy |
| KEDA + Patroni | KEDA и Patroni конфликтуют за `spec.replicas` | KEDA = мониторинг, Patroni = управление |
| StatefulSet + PDB | PDB блокирует удаление подов при scale-down | Убедитесь `minAvailable` ≤ `minReplicas - 1` |
| StatefulSet + TopologySpread | Поды могут не разместиться из-за ограничений | Используйте `whenUnsatisfiable: ScheduleAnyway` |
| Order-aware scale-down | HPA удаляет поды не в порядке индексов | StatefulSet всегда удаляет с конца, HPA уважает это |

---

## Дополнительная информация

### Диагностика

```bash
# Проверка StatefulSet
kubectl get statefulset my-statefulset -o wide
# → NAME            READY   AGE   CONTAINERS   IMAGES
# → my-statefulset  3/3     5d    postgresql   postgres:16

# Проверка HPA для StatefulSet
kubectl get hpa statefulset-hpa -o yaml | grep -A 5 "scaleTargetRef"
# → scaleTargetRef:
# →   apiVersion: apps/v1
# →   kind: StatefulSet
# →   name: my-statefulset

# Проверка KEDA ScaledObject
kubectl get scaledobject kafka-consumer-scaler -o yaml | grep -A 3 "scaleTargetRef"
# → scaleTargetRef:
# →   apiVersion: apps/v1
# →   kind: StatefulSet
# →   name: kafka-consumer

# Проверка порядка подов
kubectl get pods -l app=my-statefulset -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase
```

### См. также

- [HPA: Основы](HPA/index.md) — базовая конфигурация HPA
- [HPA: Продвинутые темы](HPA/hpa_advanced.md) — ContainerResource, behavior
- [KEDA: Концепции](keda/keda_concepts.md) — ScaledObject, ScaledJob
- [KEDA + Kafka](keda/kafka-keda-scaler.md) — масштабирование Kafka consumer
- [KEDA + Redis](keda/redis-keda-scaler.md) — масштабирование Redis worker'ов
- [Pod Disruption Budget](pod_disruption_budget.md) — защита при scale-down
- [StatefulSet: Основные концепции](../Base/StatefulSet/statefulset_core_concepts.md) — архитектура StatefulSet
