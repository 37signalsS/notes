# Шардирование в Kubernetes

## Определения

**Шардирование (Sharding)** — метод разделения рабочей нагрузки на изолированные группы (шарды) с независимым масштабированием и управлением. В контексте Kubernetes это означает развертывание нескольких независимых наборов контроллеров (Deployment, StatefulSet) для обработки разных сегментов данных или трафика.

**Идемпотентность** — свойство операции, при котором её повторное выполнение дает тот же результат, что и первое, не вызывая ошибок или дублирования данных. Это критически важно при перераспределении данных между шардами.

**Связанная концепция:** **[Шардирование баз данных (Общая теория)](../../Databases/Concepts/sharding.md)**.

---

## Основные концепции

### Назначение шардирования

1. **Изоляция сбоев (Blast Radius Reduction)** — инцидент в одном шарде (например, из-за "тяжелого" запроса или утечки памяти) не влияет на доступность других шардов.
2. **Локальность данных** — данные конкретного клиента или региона обрабатываются в рамках одного шарда, что снижает задержки и помогает соблюдать комлпаенс (GDPR).
3. **Обойти системные ограничения** — преодоление лимитов облачных провайдеров, лимитов API Kubernetes или возможностей отдельных компонентов (например, когда одна БД или Ingress-контроллер не справляется).
4. **Управление SLA** — выделение гарантированных ресурсов для VIP-клиентов в отдельные шарды.

### Ключи шардирования

| Ключ | Описание | Пример |
|------|----------|--------|
| **Регион пользователя** | Географическое разделение трафика | `us-west`, `eu-central`, `ap-south` |
| **ID клиента** | Хеширование или диапазоны идентификаторов | `customer_id % 10` |
| **Тип подписки** | Разделение по уровням обслуживания (SLA) | `free`, `premium`, `enterprise` |
| **Хеш данных** | Равномерное распределение нагрузки | `hash(order_id) % 8` |
| **Версия API** | Шардирование для плавных миграций | `v1`, `v2-canary` |

### Типы шардирования

| Тип | Описание | Сценарий использования |
|-----|----------|-------------------|
| **Горизонтальное** | Разделение однотипных данных по ключу | Мультирегиональные и высоконагруженные B2C приложения |
| **Вертикальное** | Разделение функциональности по разным сервисам | Микросервисная архитектура (функциональное разбиение) |
| **Гибридное** | Сочетание обоих подходов | Глобальные платформы со сложной логикой изоляции |

---

## Интеграция с Kubernetes

| Компонент | Роль в шардировании |
|-----------|------------|
| **HPA (Horizontal Pod Autoscaler)** | Автоматическое масштабирование каждого шарда независимо на основе CPU/Memory. |
| **KEDA** | Масштабирование шардов-воркеров на основе внешних метрик (длина очереди, Kafka lag). См. **[KEDA: Практические сценарии](./keda/practical_scenarios.md)**. |
| **Topology Spread Constraints** | Гарантия того, что поды критических шардов не окажутся на одном узле или в одной зоне. См. **[Распределение подов](./pod_distribution.md)**. |
| **StatefulSet** | Обеспечение стабильных сетевых имен и Persistent Volumes для шардов баз данных. |
| **PDB (Pod Disruption Budget)** | Гарантия минимального количества доступных реплик в каждом шарде при плановых работах на кластере. |
| **Karpenter / Cluster Autoscaler** | Динамическое выделение специфичных ресурсов (инстансов) под нужды конкретных шардов. |

### Маршрутизация трафика

| Уровень | Реализация |
|---------|------------|
| **Ingress** | Маршрутизация на основе Hostname или пути (Path). |
| **Gateway API** | Современный стандарт (HTTPRoute), позволяющий маршрутизировать трафик по заголовкам (Headers) и весам. |
| **API Gateway** | Маршрутизация на основе JWT claims, параметров API или сложных бизнес-правил. |
| **Клиентская сторона** | Клиентское приложение или SDK само определяет нужный эндпоинт шарда через Service Discovery. |
| **Service Mesh (Istio)** | Использование VirtualService для тонкой балансировки и зеркалирования трафика между шардами. |

---

## Практические сценарии

### Сценарий 1: Региональное шардирование (Deployment + Service)

Используется для минимизации задержек и соблюдения законодательных требований.

```yaml
# Deployment для шарда США (US)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-shard-us
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      shard: us
  template:
    metadata:
      labels:
        app: webapp
        shard: us
    spec:
      containers:
        - name: app
          image: myapp:v1.2.0
          env:
            - name: SHARD_ID
              value: "us"
            - name: DB_URL
              value: "postgres-us-master:5432"
---
apiVersion: v1
kind: Service
metadata:
  name: service-us
spec:
  selector:
    app: webapp
    shard: us
  ports:
    - port: 80
      targetPort: 8080
---
# Deployment для шарда Европы (EU)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-shard-eu
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      shard: eu
  template:
    metadata:
      labels:
        app: webapp
        shard: eu
    spec:
      containers:
        - name: app
          image: myapp:v1.2.0
          env:
            - name: SHARD_ID
              value: "eu"
            - name: DB_URL
              value: "postgres-eu-master:5432"
```

### Сценарий 2: Маршрутизация (Ingress vs Gateway API)

#### Классический Ingress (на базе Host/Path)
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shard-ingress
spec:
  rules:
    - host: us.api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service-us
                port:
                  number: 80
    - host: eu.api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service-eu
                port:
                  number: 80
```

#### Современный Gateway API (маршрутизация по заголовку)
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: regional-header-route
spec:
  parentRefs:
    - name: main-gateway
  rules:
    - matches:
        - headers:
            - name: x-region
              value: "eu"
      backendRefs:
        - name: service-eu
          port: 80
    - matches:
        - headers:
            - name: x-region
              value: "us"
      backendRefs:
        - name: service-us
          port: 80
```

### Сценарий 3: Масштабирование (HPA + KEDA)

#### Стандартный HPA для CPU-интенсивного шарда
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shard-us-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp-shard-us
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

#### KEDA для воркеров (шардирование по очередям RabbitMQ)
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: high-priority-scaler
spec:
  scaleTargetRef:
    name: priority-workers
  triggers:
    - type: rabbitmq
      metadata:
        queueName: critical-tasks
        mode: QueueLength
        value: "5"
```

### Сценарий 4: Разделение воркеров по приоритетам

```yaml
# Воркеры для критических задач (High Priority)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: priority-workers
spec:
  replicas: 5
  selector:
    matchLabels:
      app: workers
      priority: high
  template:
    metadata:
      labels:
        app: workers
        priority: high
    spec:
      containers:
        - name: worker
          image: task-processor:latest
          env:
            - name: QUEUE_NAME
              value: "priority-tasks"
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
```

### Сценарий 5: Изоляция через Topology Spread Constraints

Гарантирует, что поды одного шарда не "скучкуются" на одном узле, вызывая единую точку отказа.

```yaml
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: "kubernetes.io/hostname"
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app: webapp
          shard: us
```

---

## Мониторинг шардов

| Метрика | Описание | Порог алерта |
|---------|----------|-------|
| `request_latency` | Задержка обработки в конкретном шарде. | >5 секунд (P99) |
| `error_rate` | Процент ошибок по конкретному шарду. | >1% за 5 мин |
| `resource_utilization` | Потребление CPU/Memory относительно лимитов. | >85% |
| `shard_skew` | Дисбаланс нагрузки между самым загруженным и свободным шардом. | >30% разницы |

---

## Лучшие практики

1. **Выбор ключа шардирования:** Стремитесь к равномерному распределению (Uniform Distribution). Избегайте ключей, создающих "горячие шарды" (например, дата для логов без хеша).
2. **Изоляция ресурсов:** По возможности используйте раздельные Namespace или даже отдельные кластеры для шардов с разным уровнем критичности.
3. **Ребалансировка:** Используйте **Consistent Hashing** (консистентное хеширование), чтобы при добавлении нового шарда перемещалось не более `1/N` данных.
4. **Dual-write (Двойная запись):** При миграции данных между шардами записывайте изменения в оба шарда одновременно до завершения процесса синхронизации.
5. **Circuit Breaking:** Настраивайте размыкатели цепи на уровне Service Mesh, чтобы сбой в одном шарде не перегрузил остальные при попытке перераспределения трафика.
6. **Graceful Degradation:** Если один шард недоступен, приложение должно возвращать частичный результат или понятную ошибку, не затрагивая других пользователей.

---

## Дополнительная информация

### Ссылки
* [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) — современный стандарт трафика.
* [Sharding Patterns (Microservices.io)](https://microservices.io/patterns/data/sharding.html) — теоретическая база.
* [KEDA Scalers Documentation](https://keda.sh/docs/scalers/) — типы триггеров для шардированных воркеров.
* **[Обзор автоскейлинга в K8s](./overview_concepts.md)** — общие принципы.
* **[Шаблон воркеров с очередями](./workers_queue_pattern.md)** — реализация паттерна обработки.

