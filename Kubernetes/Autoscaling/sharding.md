# Шардирование в Kubernetes

## Определения

**Шардирование (Sharding)** — метод разделения рабочей нагрузки или данных на изолированные группы (шарды), каждая из которых масштабируется и управляется независимо. В контексте Kubernetes это означает развертывание нескольких независимых наборов контроллеров (Deployment, StatefulSet) для обработки разных сегментов данных или трафика.

**Blast Radius (Радиус поражения)** — концепция ограничения области влияния сбоя. Шардирование минимизирует этот радиус: инцидент в одном шарде (например, из-за «тяжелого» запроса или утечки памяти) не влияет на доступность других шардов.

**Идемпотентность** — свойство операции, при котором её повторное выполнение дает тот же результат, что и первое. Это критически важно при перераспределении данных между шардами, чтобы избежать дублирования или повреждения состояния.

**Связанная концепция:** **[Шардирование баз данных (Общая теория)](../../Databases/Concepts/sharding.md)**.

---

## Основные концепции

### Назначение шардирования

1.  **Изоляция сбоев** — предотвращение каскадных аварий. Проблема в одном сегменте данных затрагивает только подмножество пользователей.
2.  **Горизонтальная масштабируемость** — преодоление системных ограничений (лимиты API Kubernetes, пропускная способность Ingress-контроллеров или возможности одной БД).
3.  **Локальность и комплаенс** — обработка данных в конкретных географических регионах для соблюдения законодательства (GDPR, 152-ФЗ) и снижения сетевых задержек.
4.  **Управление SLA (Multi-tenancy)** — выделение гарантированных и изолированных ресурсов для VIP-клиентов или критических сервисов.

### Ключи шардирования

| Ключ | Описание | Пример |
| :--- | :--- | :--- |
| **Регион/Зона** | Географическое распределение трафика и данных | `us-west`, `eu-central`, `ru-moscow` |
| **ID клиента/Entity** | Хеширование или диапазоны идентификаторов | `user_id % 16`, `tenant_id` |
| **Тип подписки** | Разделение по уровням обслуживания (SLA) | `free`, `premium`, `enterprise` |
| **Версия API** | Шардирование для плавных миграций и Canary | `v1-stable`, `v2-beta` |
| **Хеш данных** | Равномерное распределение для кэшей или воркеров | `hash(order_id) % 8` |

### Типы шардирования в K8s

-   **Горизонтальное:** Разделение однотипных данных/нагрузки по ключу между одинаковыми наборами контроллеров.
-   **Функциональное (Вертикальное):** Разделение по типам задач (например, отдельные шарды для API, фоновых задач и генерации отчетов).
-   **Гибридное:** Сочетание обоих подходов для сверхкрупных систем.

---

## Интеграция с инфраструктурой Kubernetes

### Автомасштабирование

-   **HPA (Horizontal Pod Autoscaler):** Каждый шард масштабируется независимо. Это позволяет, например, выделять больше ресурсов шарду с «активными» пользователями в их часовом поясе.
-   **KEDA:** Масштабирование шардов-воркеров на основе внешних метрик (длина очереди Kafka, количество сообщений в RabbitMQ). См. **[KEDA: Практические сценарии](./keda/practical_scenarios.md)**.
-   **Karpenter / Cluster Autoscaler:** Динамическое выделение специфичных типов узлов (например, инстансы с GPU или локальными NVMe) под нужды конкретных шардов через Node Selectors и Tolerations.

### Распределение и надежность

-   **Topology Spread Constraints:** Гарантия того, что поды одного шарда распределены по разным узлам и зонам доступности (AZ) для исключения SPOF.
-   **PriorityClasses:** Назначение высокого приоритета критическим шардам, чтобы при нехватке ресурсов в кластере в первую очередь вытеснялись поды менее важных (например, `free-tier`) шардов.
-   **PDB (Pod Disruption Budget):** Индивидуальные бюджеты для каждого шарда обеспечивают доступность минимального числа реплик при плановых работах на кластере.

---

## Практические сценарии

### Сценарий 1: Региональное шардирование (Deployment + Service)

Используется для минимизации задержек и изоляции данных. Каждая группа подов работает со своей БД.

```yaml
# Шард США (US)
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
# Шард Европа (EU)
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

### Сценарий 2: Маршрутизация трафика (Ingress vs Gateway API)

#### Классический Ingress (на базе Host/Path)
Подходит для простого разделения по доменам или путям.

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
Позволяет реализовать более гибкую логику, например, направление трафика в шард на основе региона, указанного в заголовке `x-region`.

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
Детальная настройка масштабирования для конкретного шарда воркеров, обрабатывающих критические задачи.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: high-priority-scaler
spec:
  scaleTargetRef:
    name: priority-workers
  pollingInterval: 30
  cooldownPeriod:  300
  minReplicaCount: 1
  maxReplicaCount: 50
  triggers:
    - type: rabbitmq
      metadata:
        queueName: critical-tasks
        mode: QueueLength
        value: "5"
        host: RabbitMqConnectionSecret
```

### Сценарий 4: Разделение воркеров по приоритетам

Пример функционального шардирования, где разные группы воркеров обслуживают разные очереди с разными ресурсами.

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
      priorityClassName: critical-workload
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
            limits:
              cpu: "1000m"
              memory: "2Gi"
```

---

## Хранение данных (Persistent Storage) в шардированных системах

При шардировании приложений с состоянием (Stateful) в Kubernetes используются **StatefulSet** и **PersistentVolumeClaims (PVC)**.

### Архитектурные паттерны
1.  **Shared-Nothing (Рекомендуется):** Каждый шард имеет свои собственные тома. Это обеспечивает максимальную изоляцию.
2.  **Local Persistent Volumes:** Использование локальных SSD для шардов баз данных с целью минимизации задержек (требует управления репликацией на уровне приложения).

### Пример StatefulSet для шарда БД
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db-shard-0
spec:
  serviceName: "db-shard-0"
  replicas: 3
  selector:
    matchLabels:
      app: postgres
      shard: "0"
  template:
    metadata:
      labels:
        app: postgres
        shard: "0"
    spec:
      containers:
      - name: postgres
        image: postgres:15
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "premium-rwo"
      resources:
        requests:
          storage: 100Gi
```

---

## Перераспределение данных (Resharding) в Kubernetes

Решардинг — самая сложная операция, требующая перемещения данных между шардами при изменении их количества или при перекосе нагрузки.

### Подходы к реализации
1.  **Consistent Hashing (Консистентное хеширование):** Минимизирует количество перемещаемых данных при добавлении нового шарда. Логика реализуется на стороне приложения или прокси.
2.  **Blue/Green Sharding:**
    -   Разворачивается новый набор шардов (Green) с новой конфигурацией.
    -   Данные синхронизируются из старых шардов (Blue).
    -   Трафик переключается на уровне Ingress/Gateway API.
3.  **Использование операторов:**
    -   **Vitess:** Специализированный оператор для MySQL, автоматизирующий шардирование и решардинг.
    -   **Citus Operator:** Для PostgreSQL, позволяет добавлять узлы и перераспределять таблицы.

---

## Мониторинг шардов

| Метрика | Описание | Зачем мониторить |
| :--- | :--- | :--- |
| `request_latency` | Задержка по конкретному шарду. | Выявление «тормозящих» сегментов инфраструктуры. |
| `shard_skew` | Дисбаланс нагрузки между шардами. | Сигнал к необходимости решардинга или смены ключа. |
| `pvc_usage` | Заполнение дисков в StatefulSet конкретного шарда. | Планирование расширения хранилища. |
| `error_rate` | Процент ошибок в разрезе шардов. | Изоляция проблемного кода или данных (например, баг в данных клиента). |

---

## Лучшие практики

1.  **Выбор ключа шардирования:** Стремитесь к равномерному распределению. Избегайте ключей с высокой кардинальностью или «горячих» ключей (например, текущая дата).
2.  **Изоляция через Namespace:** Для крупных систем размещайте разные шарды в разных Namespace. Это упрощает управление лимитами (`ResourceQuota`) и безопасностью (`RBAC`).
3.  **Graceful Degradation:** Проектируйте систему так, чтобы при отказе одного шарда остальные продолжали работать, а пользователь получал частичный функционал или информативное сообщение.
4.  **Автоматизируйте решардинг:** Если система предполагает частый рост данных, используйте специализированные решения (Vitess, Citus, MongoDB Atlas), так как ручной решардинг в Kubernetes крайне подвержен ошибкам.
5.  **Тестируйте Blast Radius:** Проводите Chaos Engineering эксперименты, отключая целые шарды, чтобы убедиться в отсутствии каскадных сбоев.

---

## Дополнительная информация

### Ссылки
* [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) — современный стандарт трафика.
* [Sharding Patterns (Microservices.io)](https://microservices.io/patterns/data/sharding.html) — теоретическая база.
* [Karpenter Documentation](https://karpenter.sh/) — управление узлами под специфичные нагрузки.
* **[Обзор автоскейлинга в K8s](./overview_concepts.md)** — общие принципы.
* **[Шаблон воркеров с очередями](./workers_queue_pattern.md)** — реализация паттерна обработки.
* **[Управление размещением подов (Topology Spread)](../Scheduling/affinity.md)** — детали топологического планирования.
