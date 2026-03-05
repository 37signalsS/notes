# Паттерны шардирования в Kubernetes

## Определения

**Шардирование (Sharding)** — разделение рабочей нагрузки на изолированные группы (шарды) с независимым масштабированием и управлением.

**Идемпотентность** — свойство обработки задачи, при котором повторное выполнение не приводит к ошибкам или дублированию результата.

## Основные концепции

### Назначение шардирования

Разделение трафика по ключу позволяет:

* **Изолировать сбои** — проблема в одном шарде не влияет на другие
* **Обеспечить локальность данных** — данные клиента хранятся в одном шарде
* **Обойти ограничения** — масштабирование beyond limits отдельных компонентов

#### Ключи шардирования

| Ключ | Описание | Пример |
|------|----------|--------|
| **Регион пользователя** | Географическое разделение | `us-west`, `eu-central`, `ap-south` |
| **ID клиента** | Хеш или диапазон ID | `customer_id % 10` |
| **Тип подписки** | Тарифный план | `free`, `premium`, `enterprise` |
| **Хеш данных** | Равномерное распределение | `hash(order_id) % 8` |

#### Типы шардирования

| Тип | Описание | Когда использовать |
|-----|----------|-------------------|
| **Горизонтальное** | Разделение по ключу (регион, клиент) | Мультирегиональные приложения |
| **Вертикальное** | Разделение по функциональности | Микросервисная архитектура |
| **Гибридное** | Комбинация подходов | Сложные распределённые системы |

## Практические сценарии

### Сценарий 1: Шардирование по региону

```yaml
# Deployment для шарда A (US)
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
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "us"
            - name: ALLOWED_REGIONS
              value: "us-west,us-east"
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
# Deployment для шарда B (EU)
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
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "eu"
            - name: ALLOWED_REGIONS
              value: "eu-west,eu-central"
---
apiVersion: v1
kind: Service
metadata:
  name: service-eu
spec:
  selector:
    app: webapp
    shard: eu
  ports:
    - port: 80
      targetPort: 8080
```

**Маршрутизация на уровне Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shard-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
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

### Сценарий 2: Шардирование с независимым масштабированием

```yaml
# HPA для каждого шарда
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
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shard-eu-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp-shard-eu
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

### Сценарий 3: Priority Queue с несколькими очередями

```yaml
# Workers для критических задач
apiVersion: apps/v1
kind: Deployment
metadata:
  name: priority-workers
spec:
  replicas: 5
  selector:
    matchLabels:
      app: priority-workers
      priority: high
  template:
    metadata:
      labels:
        app: priority-workers
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
---
# Workers для обычных задач
apiVersion: apps/v1
kind: Deployment
metadata:
  name: standard-workers
spec:
  replicas: 3
  selector:
    matchLabels:
      app: standard-workers
      priority: normal
  template:
    metadata:
      labels:
        app: standard-workers
        priority: normal
    spec:
      containers:
        - name: worker
          image: task-processor:latest
          env:
            - name: QUEUE_NAME
              value: "standard-tasks"
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
```

## Дополнительная информация

### Интеграция с Kubernetes

| Компонент | Интеграция |
|-----------|------------|
| **[HPA](./hpa_detailed.md)** | Масштабирование шардов по CPU/memory |
| **[Pod Distribution](./pod_distribution.md)** | Распределение шардов по узлам/зонам для отказоустойчивости |
| **[Pod Disruption Budget](./pod_disruption_budget.md)** | Защита шардов при масштабировании узлов |
| **[Cluster Autoscaler](./cluster_autoscaler_detailed.md)** | Добавление узлов при масштабировании шардов |

### Маршрутизация шардов

| Уровень | Реализация |
|---------|------------|
| **Ingress** | На основе host/path (см. Сценарий 1) |
| **API Gateway** | На основе заголовков, JWT claims |
| **Клиентская** | Клиент определяет шард по ключу |
| **Service Mesh** | Istio VirtualService для маршрутизации |

### Ребалансировка

* **Планирование миграции** — постепенное перемещение данных между шардами
* **Consistent Hashing** — минимизация перемещений при изменении количества шардов
* **Dual-write** — запись в старый и новый шард во время миграции

### Мониторинг

| Метрика | Описание | Алерт |
|---------|----------|-------|
| `request_latency` | Задержка обработки по шардам | >5 секунд |
| `error_rate` | Процент ошибок по шардам | >1% |
| `replica_count` | Количество реплик в шарде | Отклонение от baseline |
| `resource_utilization` | Использование CPU/memory | >80% |

### Сценарии использования

| Сценарий | Обоснование |
|----------|-------------|
| Мультирегиональное приложение | Локальность данных, compliance (GDPR) |
| Требования к изоляции клиентов | Изоляция сбоев, безопасность |
| Обработка платежей | Изоляция + консистентность данных |
| Real-time аналитика | Разделение по временным окнам |

### Ресурсы

* [Sharding Patterns (Microservices.io)](https://microservices.io/patterns/data/sharding.html)
* [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
