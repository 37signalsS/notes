# HPA + PriorityClass + Preemption: взаимодействие при масштабировании

## Определения

**PriorityClass** — кластерный объект Kubernetes, определяющий приоритет подов при планировании и вытеснении (preemption). Поды с более высоким приоритетом вытесняют поды с низким приоритетом при нехватке ресурсов.

**Preemption** — процесс, при котором `kube-scheduler` удаляет (выселяет) поды с низким приоритетом для освобождения ресурсов под критичные поды с высоким приоритетом. Вытеснение учитывает только `PriorityClass`, а не QoS.

**Eviction** — процесс выселения пода, выполняемый `kubelet` при нехватке ресурсов на узле. В отличие от preemption, eviction учитывает QoS: сначала `BestEffort`, затем `Burstable`, затем `Guaranteed`.

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| Kubernetes | 1.27 | 1.31+ | Стабильный API `autoscaling/v2` |
| HPA | autoscaling/v2 | autoscaling/v2 | Стабильный API |
| PriorityClass | scheduling.k8s.io/v1 | scheduling.k8s.io/v1 | Глобальный кластерный ресурс |

---

## Теоретический блок

### Как HPA и PriorityClass взаимодействуют

HPA и PriorityClass работают на разных уровнях, но их взаимодействие критично для production:

```
HPA масштабирует → добавляет поды → поды планируются → scheduler учитывает PriorityClass
                                                      ├── Ресурсов хватает → под запускается
                                                      └── Ресурсов не хватает → preemption
                                                           ├── Высвободил ресурсы → под запускается
                                                           └── PDB блокирует → под в Pending
```

**Ключевые моменты:**

1. HPA создаёт новые поды без учёта их приоритета — он просто изменяет `replicas`
2. При scale-up критичный под (high priority) может вытеснить некритичный (low priority)
3. PDB защищает поды от preemption — если `disruptionsAllowed: 0`, вытеснение невозможно
4. Cluster Autoscaler добавляет узлы, когда все поды не влезают даже после preemption

### Сценарии взаимодействия

#### Сценарий 1: HPA scale-up без конфликтов

```
Deployment: min=3, max=10, HPA target CPU=70%
PriorityClass: production-high (value=1000)
Узел: 4 CPU, 16Gi RAM

HPA масштабирует до 6 подов:
  → 6 × 500m = 3000m CPU (<= 4000m)
  → Все поды размещаются
  → Preemption не требуется
```

#### Сценарий 2: Preemption при scale-up

```
Узел заполнен подами с PriorityClass: batch-low (value=100)
HPA масштабирует под с PriorityClass: production-high (value=1000)

1. HPA увеличивает replicas → под с production-high в Pending
2. Scheduler ищет узел → все заняты
3. Preemption: scheduler проверяет можно ли выселить batch-low поды
4. Если PDB позволяет → batch-low поды выселяются → production-high запускается
5. Если PDB блокирует → production-high в Pending → CA добавляет узел
```

#### Сценарий 3: Конфликт HPA + PDB + PriorityClass

```yaml
# PDB: минимум 2 пода всегда доступны
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: batch-job-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: batch-job
---
# HPA: масштабирует batch-job
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: batch-job-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: batch-job
  minReplicas: 5
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Проблема:** HPA масштабирует batch-job до 5 подов. Критичный под с `production-high` приходит и пытается вытеснить batch-low поды. PDB `minAvailable: 2` блокирует вытеснение 3 из 5 подов → критичный под не может запуститься.

**Решения:**
1. Установить `minAvailable: 1` для batch-job PDB
2. Использовать `unhealthyPodEvictionPolicy: AlwaysAllow` для нездоровых подов
3. Создать отдельную node group для критичных подов (Taints/Tolerations)

### Приоритет vs QoS при вытеснении

| Механизм | Кто выполняет | Критерий | Учитывает PDB |
|----------|---------------|----------|---------------|
| **Preemption** | kube-scheduler | Только PriorityClass (value) | Да |
| **Eviction** | kubelet | QoS: BestEffort → Burstable → Guaranteed | Да |

**Важно:** Preemption и eviction — это РАЗНЫЕ механизмы. Scheduler вытесняет по приоритету, kubelet убивает по QoS. PriorityClass НЕ влияет на eviction.

### Приоритетные группы узлов (Priority Expander)

Cluster Autoscaler может использовать PriorityClass для выбора группы узлов:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler-priority-expander
  namespace: kube-system
data:
    priorities: |-
      50:
        - ".*spot-.*"
      100:
        - ".*on-demand-.*"
```

При scale-up CA выбирает группу узлов с наивысшим приоритетом, когда несколько групп могут разместить под.

---

## Практический блок

### Настройка PriorityClass для типичных сценариев

```yaml
# Критичные production-сервисы
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-critical
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Для критичных production-сервисов (API, базы данных)"
---
# Обычные production-сервисы
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-high
value: 100000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Для обычных production-сервисов"
---
# Batch-задачи
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-low
value: 1000
globalDefault: false
preemptionPolicy: Never  # Не вытеснять другие поды
description: "Для batch-задач (On-demand, ETL)"
---
# Default (для подов без explicit priorityClassName)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: default-priority
value: 0
globalDefault: true
preemptionPolicy: PreemptLowerPriority
description: "Приоритет по умолчанию"
```

### HPA с PriorityClass

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: production-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: production-api
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
---
# Deployment с PriorityClass
apiVersion: apps/v1
kind: Deployment
metadata:
  name: production-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: production-api
  template:
    metadata:
      labels:
        app: production-api
    spec:
      priorityClassName: production-critical  # Высокий приоритет
      containers:
        - name: api
          image: my-api:latest
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1Gi
```

### PDB для защищённых от preemption подов

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: batch-job-pdb
spec:
  minAvailable: 1  # Минимум 1 под доступен (для batch можно 1)
  selector:
    matchLabels:
      app: batch-job
---
# HPA с осторожным scale-down
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: batch-job-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: batch-job
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 600  # 10 минут для batch
      policies:
        - type: Pods
          value: 1
          periodSeconds: 300
```

### Диагностика проблем

```bash
# Проверка PriorityClass подов
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.name}{" → "}{.spec.priorityClassName}{" prio="}{.spec.priority}{"\n"}{end}' | sort -t= -k3 -n

# Проверка Pending-подов с их приоритетами
kubectl get pods -A --field-selector=status.phase=Pending -o jsonpath='{range .items[*]}{.metadata.name}{" → "}{.spec.priorityClassName}{" prio="}{.spec.priority}{"\n"}{end}'

# Метрики preemption в Prometheus
# Количество попыток вытеснения
scheduler_preemption_attempts_total

# Количество подов-жертв при вытеснении
scheduler_preemption_victims_total

# Запросы вытеснений за последний час
increase(scheduler_preemption_attempts_total[1h])

# NominatedNodeName (под в процессе вытеснения)
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.name}{" → nominated="}{.status.nominatedNodeName}{"\n"}{end}' | grep -v "→ nominated=$"

# Проверка PDB
kubectl get pdb -A -o wide
```

---

## Дополнительная информация

### Типичные ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| Критичный под в Pending | PDB блокирует preemption batch-подов | Уменьшите `minAvailable` для batch PDB |
| HPA не масштабирует из-за нехватки ресурсов | CA не добавляет узлы, PriorityClass не помогает | Проверьте CA логи, увеличьте `max-nodes-total` |
| Batch поды выселяются слишком часто | `preemptionPolicy: PreemptLowerPriority` у batch | Установите `preemptionPolicy: Never` для batch |
| Preemption удаляет production поды | Production поды имеют низкий PriorityClass | Проверьте `priorityClassName` в Deployment |

### Best Practices

1. **Иерархия приоритетов:** `production-critical` > `production-high` > `default` > `batch-low`
2. **Batch поды:** Всегда используйте `preemptionPolicy: Never` для batch-задач
3. **PDB:** Настраивайте `minAvailable` так, чтобы preemption мог работать для критичных подов
4. **HPA behavior:** Настройте `stabilizationWindowSeconds` для scaleDown, чтобы не терять поды при кратковременных всплесках
5. **CA Priority Expander:** Используйте для выбора группы узлов на основе приоритета подов

### См. также

- [PriorityClass](../Concepts/priorityclass.md) — глубокое погружение в PriorityClass
- [HPA: Основы](HPA/index.md) — базовая конфигурация HPA
- [HPA: Продвинутые темы](HPA/hpa_advanced.md) — behavior, ContainerResource
- [Pod Disruption Budget](pod_disruption_budget.md) — защита при вытеснении
- [Cluster Autoscaler](cluster_autoscaler_detailed.md) — взаимодействие с CA
- [Descheduler](descheduler.md) — дефрагментация после preemption
