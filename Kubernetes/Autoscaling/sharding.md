# Шардирование в Kubernetes

## Определения

**Шардирование (Sharding)** — метод разделения рабочей нагрузки на изолированные группы (шарды) с независимым масштабированием и управлением. В контексте Kubernetes это обычно означает развертывание нескольких независимых наборов подов для обработки разных сегментов данных или трафика.

**Идемпотентность** — свойство операции, при котором её повторное выполнение дает тот же результат, что и первое, не вызывая ошибок или дублирования данных.

---

## Основные концепции

### Назначение шардирования

Разделение трафика по ключу шардирования позволяет:

* **Изолировать сбои** — инцидент в одном шарде (например, из-за "тяжелого" запроса клиента) не влияет на доступность других шардов.
* **Обеспечить локальность данных** — данные конкретного клиента или региона обрабатываются и хранятся в рамках одного шарда, что снижает задержки.
* **Обойти системные ограничения** — масштабирование приложения за пределы возможностей отдельных компонентов (например, когда одна база данных не справляется с нагрузкой на запись).

#### Ключи шардирования

| Ключ | Описание | Пример |
|------|----------|--------|
| **Регион пользователя** | Географическое разделение трафика | `us-west`, `eu-central`, `ap-south` |
| **ID клиента** | Хеширование или диапазоны идентификаторов | `customer_id % 10` |
| **Тип подписки** | Разделение по уровням обслуживания (SLA) | `free`, `premium`, `enterprise` |
| **Хеш данных** | Равномерное распределение нагрузки | `hash(order_id) % 8` |

#### Типы шардирования

| Тип | Описание | Сценарий использования |
|-----|----------|-------------------|
| **Горизонтальное** | Разделение однотипных данных по ключу | Мультирегиональные и высоконагруженные B2C приложения |
| **Вертикальное** | Разделение функциональности по разным сервисам | Микросервисная архитектура (функциональное разбиение) |
| **Гибридное** | Сочетание обоих подходов | Глобальные платформы со сложной логикой изоляции |

---

## Интеграция с Kubernetes

| Компонент | Роль в шардировании |
|-----------|------------|
| **HPA (Horizontal Pod Autoscaler)** | Автоматическое масштабирование каждого шарда независимо на основе CPU/Memory |
| **Pod Distribution** | Распределение подов шарда по узлам и зонам доступности для отказоустойчивости |
| **PDB (Pod Disruption Budget)** | Гарантия минимального количества доступных реплик в шарде при плановых работах |
| **Cluster Autoscaler** | Обеспечение вычислительных ресурсов при расширении шардов |

### Маршрутизация трафика

| Уровень | Реализация |
|---------|------------|
| **Ingress** | Маршрутизация на основе Hostname или пути (Path) |
| **API Gateway** | Маршрутизация на основе заголовков запроса, JWT claims или параметров API |
| **Клиентская сторона** | Клиентское приложение само определяет нужный эндпоинт шарда |
| **Service Mesh** | Использование Istio VirtualService для сложной балансировки по весам или заголовкам |

---

## Практические сценарии

### Сценарий 1: Шардирование по региону

Используется для минимизации задержек и соблюдения законодательных требований (например, GDPR) по хранению данных в конкретном регионе.

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
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "eu"
            - name: ALLOWED_REGIONS
              value: "eu-west,eu-central"
```

#### Маршрутизация на уровне Ingress

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

### Сценарий 2: Независимое масштабирование шардов

Разные шарды могут иметь разную нагрузку (например, дневные пики в разных часовых поясах). HPA настраивается для каждого шарда отдельно.

```yaml
# HPA для шарда US
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

### Сценарий 3: Разделение очередей по приоритетам

Шардирование воркеров на основе критичности задач.

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

---

## Дополнительная информация

### Мониторинг шардов

| Метрика | Описание | Порог алерта |
|---------|----------|-------|
| `request_latency` | Задержка обработки в конкретном шарде | >5 секунд |
| `error_rate` | Процент ошибок по шардам | >1% |
| `resource_utilization` | Потребление ресурсов (CPU/Memory) | >80% |

### Лучшие практики

1. **Выбор ключа шардирования:** Стремитесь к равномерному распределению трафика, чтобы избежать "горячих" шардов (hot spots).
2. **Изоляция ресурсов:** По возможности используйте раздельные базы данных или схемы для разных шардов, чтобы обеспечить полную изоляцию.
3. **Ребалансировка:** Используйте механизмы **Consistent Hashing** для минимизации перемещения данных при добавлении или удалении шардов.
4. **Dual-write:** При миграции данных между шардами применяйте стратегию двойной записи для обеспечения консистентности.

### Ссылки

* [Sharding Patterns (Microservices.io)](https://microservices.io/patterns/data/sharding.html) — теоретические основы.
* [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/) — официальная документация по автоскейлингу.
* **[Обзор автоскейлинга в K8s](./overview_concepts.md)** — общие принципы масштабирования.
