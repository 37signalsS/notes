# Шардирование в Kubernetes

## Определения

**Шардирование (Sharding)** — метод разделения рабочей нагрузки или данных на изолированные группы (шарды), каждая из которых масштабируется и управляется независимо. В контексте Kubernetes это означает развертывание нескольких независимых наборов контроллеров (Deployment, StatefulSet) для обработки разных сегментов данных или трафика.

**Шард (Shard)** — логическая единица изоляции, состоящая из одного или нескольких подов, сервиса и связанных ресурсов (PVC, ConfigMap), обрабатывающая выделенный сегмент данных или трафика.

**Blast Radius (Радиус поражения)** — концепция ограничения области влияния сбоя. Шардирование минимизирует этот радиус: инцидент в одном шарде (например, из-за «тяжелого» запроса или утечки памяти) не влияет на доступность других шардов.

**Идемпотентность** — свойство операции, при котором её повторное выполнение дает тот же результат, что и первое. Это критически важно при перераспределении данных между шардами, чтобы избежать дублирования или повреждения состояния.

**Cross-shard communication (Мешардная коммуникация)** — взаимодействие между подами или сервисами, принадлежащими разным шардам. Требует явного проектирования, так как по умолчанию шарды изолированы.

**Shard skew (Перекос шардов)** — дисбаланс нагрузки между шардами, при котором один шард получает значительно больше запросов или данных, чем остальные. Является сигналом к решардингу или смене ключа шардирования.

**Hot shard (Горячий шард)** — шард, который получает непропорционально высокую нагрузку по сравнению с остальными, часто из-за неоптимального выбора ключа шардирования или всплеска активности конкретного сегмента данных.

**Связанная концепция:** **[Шардирование баз данных (Общая теория)](../../Databases/Concepts/sharding.md)**.

---

## Основные концепции

### Задачи, решаемые шардированием в Kubernetes

Шардирование в Kubernetes не только повторяет паттерны масштабирования баз данных, но и решает специфичные проблемы оркестратора:

1.  **Обход лимитов API-сервера и etcd:** Один Deployment или StatefulSet не может бесконечно масштабироваться. Ограничения включают:
    *   Лимит количества подов в одном namespace (по умолчанию зависит от конфигурации API-сервера, часто ~5000).
    *   Производительность etcd при большом количестве объектов и частых обновлений статусов.
    *   Нагрузка на `kube-scheduler` и контроллеры при массовом создании/удалении подов.
    Шардирование распределяет эти объекты по нескольким Deployment/StatefulSet, снижая нагрузку на каждый компонент.

2.  **Изоляция метрик и поведения автомасштабирования:** Группа подов с одинаковым `Deployment` имеет общий HPA. При сильно неоднородной нагрузке (например, один «тяжелый» эндпойнт vs легкие) общий HPA не может выделить ресурсы точечно. Разделение на шарды позволяет каждому сегменту масштабироваться под свои метрики.

3.  **Разделение по уровням обслуживания (Multi-tenancy):** Возможность выделять изолированные пулы ресурсов для VIP-клиентов (SLA guarantee) и остальных, используя разные Namespace, PriorityClasses и ResourceQuota.

4.  **Соблюдение регуляторных требований:** Географическое или организационное разделение данных на уровне инфраструктуры Kubernetes для соблюдения GDPR, 152-ФЗ и других нормативов без использования публичного облака.

5.  **Управление рисками при обновлениях:** Постепенное обновление шардов (rolling update) ограничивает влияние багов в новом коде только одним сегментом пользователей.

### Ключи шардирования

| Ключ | Описание | Пример |
| :--- | :--- | :--- |
| **Регион/Зона** | Географическое распределение трафика и данных | `us-west`, `eu-central`, `ru-moscow` |
| **ID клиента/Entity** | Хеширование или диапазоны идентификаторов | `user_id % 16`, `tenant_id` |
| **Тип подписки** | Разделение по уровням обслуживания (SLA) | `free`, `premium`, `enterprise` |
| **Версия API** | Шардирование для плавных миграций и Canary | `v1-stable`, `v2-beta` |
| **Хеш данных** | Равномерное распределение для кэшей или воркеров | `hash(order_id) % 8` |

### Типы шардирования в K8s

*   **Горизонтальное:** Разделение однотипных данных/нагрузки по ключу между одинаковыми наборами контроллеров.
*   **Функциональное (Вертикальное):** Разделение по типам задач (например, отдельные шарды для API, фоновых задач и генерации отчетов).
*   **Гибридное:** Сочетание обоих подходов для сверхкрупных систем.

### Архитектурные паттерны

*   **Headless Service:** Для StatefulSet шардов headless service (`clusterIP: None`) обеспечивает стабильные DNS-имена вида `<pod-name>.<service-name>.<namespace>.svc.cluster.local`, что позволяет шардам напрямую обращаться друг к другу или к репликам внутри шарда без балансировщика.
*   **ExternalName Service:** При размещении шардов в отдельных кластерах или на физических серверах `ExternalName` предоставляет стабильное DNS-имя шарда внутри кластера, маскируя реальную внешнюю конечную точку.
*   **ConfigMap/Secret per shard:** Выделение конфигурации и учетных данных под каждый шард позволяет обновлять конфиг одного шарда без влияния на остальные и упрощает аудит.
*   **Sidecar per shard pattern:** Вместо одного shared sidecar на Deployment (например, envoy, otel-agent) используется отдельный sidecar на каждый под шарда. Это изолирует ресурсы и упрощает отладку, но увеличивает потребление ресурсов кластера.
*   **Cross-shard coordinator:** Отдельный легковесный Deployment (или набор подов), который хранит маппинг `ключ → шард` и предоставляет API для маршрутизации. Это позволяет менять ключ шардирования без изменения логики клиентов.

### Ограничения и edge cases

*   **Cross-shard JOIN:** Если данные распределены по шардам, JOIN между таблицами из разных шардов должен выполняться на уровне приложения или прокси (например, Vitess). Это добавляет задержку и сложность.
*   **Распределенные транзакции:** Атомарные операции, затрагивающие несколько шардов, требуют реализации паттернов Saga или Two-Phase Commit (2PC) на стороне приложения или middleware.
*   **Горячие шарды (Hot shards):** Неравномерное распределение нагрузки приводит к перегрузке отдельных шардов. Необходимо регулярно анализировать `shard_skew` и менять ключ шардирования или количество шардов.
*   **Перераспределение без даунтайма:** Изменение количества шардов требует либо временного дублирования данных (Blue/Green), либо использования консистентного хеширования для минимизации перемещаемых данных.
*   **Граничные случаи с StatefulSet:** Удаление или переименование шарда в StatefulSet требует особой осторожности с PVC. По умолчанию PVC не удаляются вместе с StatefulSet (`persistentVolumeClaimRetentionPolicy`), что предотвращает потерю данных, но требует ручной очистки.
*   **Сетевая изоляция:** По умолчанию все поды в кластере могут взаимодействовать. Для строгой изоляции шардов требуется настройка NetworkPolicy и RBAC.

---

## Интеграция с инфраструктурой Kubernetes

### Автомасштабирование

*   **HPA (Horizontal Pod Autoscaler):** Каждый шард масштабируется независимо. Это позволяет, например, выделять больше ресурсов шарду с «активными» пользователями в их часовом поясе.
    *   Рекомендуется использовать `behavior` для настройки окон стабилизации и предотвращения дребезга при скачках нагрузки конкретного шарда.
    *   Для метрик, специфичных для шарда (например, длина очереди конкретного шарда), используйте Prometheus Adapter с фильтром по label `shard`.
*   **KEDA:** Масштабирование шардов-воркеров на основе внешних метрик (длина очереди Kafka, количество сообщений в RabbitMQ). См. **[KEDA: Практические сценарии](./keda/practical_scenarios.md)**.
*   **Karpenter / Cluster Autoscaler:** Динамическое выделение специфичных типов узлов (например, инстансы с GPU или локальными NVMe) под нужды конкретных шардов через Node Selectors и Tolerations.
    *   При использовании Karpenter можно создать отдельные NodePool'ы для шардов с разными требованиями к оборудованию.
*   **VPA (Vertical Pod Autoscaler):** Для шардов с нестабильной нагрузкой, где горизонтальное масштабирование приводит к частому созданию/удалению подов, VPA может оптимизировать `requests` и `limits`, снижая fragmentation ресурсов.

### Распределение и надежность

*   **Topology Spread Constraints:** Гарантия того, что поды одного шарда распределены по разным узлам и зонам доступности (AZ) для исключения SPOF. См. **[Управление размещением подов](../Scheduling/affinity.md)**.
*   **PriorityClasses:** Назначение высокого приоритета критическим шардам, чтобы при нехватке ресурсов в кластере в первую очередь вытеснялись поды менее важных (например, `free-tier`) шардов.
*   **PDB (Pod Disruption Budget):** Индивидуальные бюджеты для каждого шарда обеспечивают доступность минимального числа реплик при плановых работах на кластере.
*   **ResourceQuota и LimitRange:** На уровне Namespace (один шард = один Namespace) ограничивают суммарное потребление ресурсов шардом, предотвращая эгоистичное потребление ресурсов кластера.
*   **Network Policies:** Ограничивают сетевой трафик между шардами и внешним миром. Например, шард БД может принимать соединения только от шарда приложений, которому он выделен.
*   **RBAC (Role-Based Access Control):** Выделение отдельных ServiceAccount и Role/ClusterRole для каждого шарда минимизирует последствия утечки учетных данных: взломанный шард получает доступ только к своим секретам и ресурсам.

### Маршрутизация и сервис-дискавери

*   **Сервисы без селектора (Selector-less Service) + EndpointSlice:** Для шардов, размещенных вне кластера (физ. серверы, другие кластеры), создается Service без селектора, а вручную управляется EndpointSlice.
*   **Headless Service с StatefulSet:** Обеспечивает стабильную сетевую идентичность для каждого шарда и его реплик. Клиенты могут обращаться к конкретному шарду через `<statefulset-name>-<ordinal>.<service-name>`.
*   **Сервисные сетки (Service Mesh):** Istio или Linkerd (on-premise развертывание) могут маршрутировать трафик между шардами на основе заголовков или весов, а также обеспечивать взаимный TLS и observability без изменения кода приложений.

---

## Хранение данных (Persistent Storage) в шардированных системах

При шардировании приложений с состоянием (Stateful) в Kubernetes используются **StatefulSet** и **PersistentVolumeClaims (PVC)**.

### Архитектурные паттерны

1.  **Shared-Nothing (Рекомендуется):** Каждый шард имеет свои собственные тома. Это обеспечивает максимальную изоляцию.
2.  **Local Persistent Volumes:** Использование локальных SSD для шардов баз данных с целью минимизации задержек (требует управления репликацией на уровне приложения).
3.  **StorageClass per shard:** Разные типы хранилища для разных шардов (например, NVMe для «горячих» шардов с высоким IOPS, HDD для архивных).

### Пример StatefulSet для шарда БД
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db-shard-0
spec:
  serviceName: "db-shard-0-headless"
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

### Управление жизненным циклом PVC
*   `persistentVolumeClaimRetentionPolicy: WhenDeleted` (по умолчанию в K8s 1.27+): PVC удаляются вместе с шардом.
*   `persistentVolumeClaimRetentionPolicy: Retain`: PVC сохраняются после удаления StatefulSet, что позволяет переназначить их другому шарду при решардинге или аварийном восстановлении.

---

## Перераспределение данных (Resharding) в Kubernetes

Решардинг — самая сложная операция, требующая перемещения данных между шардами при изменении их количества или при перекосе нагрузки.

### Подходы к реализации

1.  **Consistent Hashing (Консистентное хеширование):** Минимизирует количество перемещаемых данных при добавлении нового шарда. Логика реализуется на стороне приложения или прокси (например, Envoy с consistent-hashing cluster).
2.  **Blue/Green Sharding:**
    *   Разворачивается новый набор шардов (Green) с новой конфигурацией.
    *   Данные синхронизируются из старых шардов (Blue) через брокер сообщений или репликацию БД.
    *   Трафик переключается на уровне Ingress/Gateway API или Service Mesh.
3.  **Использование операторов:**
    *   **Vitess:** Специализированный оператор для MySQL, автоматизирующий шардирование и решардинг.
    *   **Citus Operator:** Для PostgreSQL, позволяет добавлять узлы и перераспределять таблицы.
    *   **MongoDB Community Operator:** Позволяет масштабировать шардсеты, но требует ручного управления ключом шардирования.

### Практические рекомендации по решардингу
*   Никогда не меняйте ключ шардирования «на лету» без дублирования данных.
*   Используйте dual-write на этапе миграции: старый и новый шард одновременно получают записи, после чего выполняется бэкап и переключение.
*   При добавлении шардов сначала масштабируйте инфраструктуру (новые узлы, PVC), затем обновите конфигурацию ключа шардирования.

---

## Практические сценарии

### Сценарий 1: Региональное шардирование (Deployment + Service)

Используется для минимизации задержек и изоляции данных. Каждая группа подов работает со своей БД.

#### Манифесты

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

#### Проверка корректности развертывания
```bash
# Проверка, что поды создались и имеют нужные labels
kubectl get pods -l app=webapp -L shard

# Проверка, что сервисы направляют трафик на нужные поды
kubectl endpoints service-us
kubectl endpoints service-eu

# Проверка, что Deployment имеют нужное количество реплик
kubectl get deployment webapp-shard-us webapp-shard-eu
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

#### Проверка маршрутизации
```bash
# Проверка Ingress адреса
kubectl get ingress shard-ingress

# Проверка Gateway и HTTPRoute
kubectl get gateway main-gateway
kubectl get httproute regional-header-route

# Тест маршрутизации (предполагает наличие curl и внешнего IP)
curl -H "x-region: eu" http://<gateway-ip>/api/health
curl -H "x-region: us" http://<gateway-ip>/api/health
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
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
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
  cooldownPeriod: 300
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

#### Проверка автомасштабирования
```bash
# Проверка статуса HPA
kubectl get hpa shard-us-hpa

# Проверка статуса KEDA ScaledObject
kubectl get scaledobject high-priority-scaler

# Проверка, что масштабирование работает (при нагрузке)
kubectl get deployment webapp-shard-us -w
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

### Сценарий 5: Шардирование с StatefulSet и Headless Service

Для приложений с состоянием, требующих стабильной сетевой идентичности (например, Elasticsearch, Kafka, баз данных).

```yaml
# Headless Service для DNS-идентичности
apiVersion: v1
kind: Service
metadata:
  name: db-shard-0-headless
spec:
  clusterIP: None
  selector:
    app: postgres
    shard: "0"
  ports:
    - port: 5432
      name: postgres

# StatefulSet для шарда БД
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db-shard-0
spec:
  serviceName: "db-shard-0-headless"
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
        ports:
        - containerPort: 5432
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

### Сценарий 6: Изоляция шардов через NetworkPolicy и RBAC

Пример изоляции трафика между шардом приложений и шардом базы данных в одном namespace.

```yaml
# RBAC: ServiceAccount для шарда приложений
apiVersion: v1
kind: ServiceAccount
metadata:
  name: webapp-us-sa
  namespace: production

---
# NetworkPolicy: шард US может получать трафик только от Ingress и отправлять трафик только на US-БД
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: webapp-us-isolation
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: webapp
      shard: us
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8080
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: postgres
              shard: us
      ports:
        - protocol: TCP
          port: 5432
    # Разрешаем DNS
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

---

## Валидация и диагностика

### Проверка распределения подов по шардам
```bash
# Группировка подов по шардам
kubectl get pods --all-namespaces -L shard -o wide

# Проверка распределения по зонам доступности
kubectl get pods --all-namespaces -L topology.kubernetes.io/zone -o wide

# Проверка Topology Spread Constraints
kubectl describe deployment webapp-shard-us | grep -A 10 "Topology Spread Constraints"
```

### Проверка метрик шардов
```bash
# Если используется Prometheus Operator с sharding (например, для мониторинга)
kubectl get prometheus -n monitoring
kubectl get servicemonitor -A | grep shard

# Проверка метрик через kubectl debug (если metrics-server доступен)
kubectl top pods -l shard=us
kubectl top pods -l shard=eu
```

### Скрипт для проверки дисбаланса (shard skew)
```bash
#!/bin/bash
# Проверяет количество подов по каждому шарду и выводит дисбаланс
kubectl get pods --all-namespaces -L shard --no-headers | awk '{print $NF}' | sort | uniq -c | sort -rn
```

### Проверка изоляции сети
```bash
# Проверка NetworkPolicy
kubectl get networkpolicy -A

# Тест подключения между шардами (должен работать только разрешенный)
kubectl exec -it <pod-shard-a> -- curl -s -o /dev/null -w "%{http_code}" http://<service-shard-b>:<port>/

# Тест блокировки (должен быть таймаут или отказ)
kubectl exec -it <pod-shard-a> -- curl -s -o /dev/null -w "%{http_code}" http://<service-shard-c>:<port>/
```

---

## Мониторинг шардов

| Метрика | Описание | Зачем мониторить | Источник |
| :--- | :--- | :--- | :--- |
| `request_latency` | Задержка по конкретному шарду. | Выявление «тормозящих» сегментов инфраструктуры. | Prometheus histogram по `/api/request_duration_seconds` с label `shard`. |
| `shard_skew` | Дисбаланс нагрузки между шардами. | Сигнал к необходимости решардинга или смены ключа. | Кастомный дашборд: `count by (shard) (up{job="webapp"})` или `http_requests_total{shard=~".+"}`. |
| `pvc_usage` | Заполнение дисков в StatefulSet конкретного шарда. | Планирование расширения хранилища. | `kubelet_volume_stats_used_bytes{persistentvolumeclaim=~"data-.*"}`. |
| `error_rate` | Процент ошибок в разрезе шардов. | Изоляция проблемного кода или данных (например, баг в данных клиента). | `rate(http_requests_total{status=~"5..", shard=~".+"}[5m]) / rate(http_requests_total{shard=~".+"}[5m])`. |
| `hpa_replicas` | Количество реплик каждого шарда. | Отслеживание автомасштабирования и identification «горячих» шардов. | `kube_hpa_status_current_replicas{ hpa=~".*shard.*" }`. |

---

## Лучшие практики

1.  **Выбор ключа шардирования:** Стремитесь к равномерному распределению. Избегайте ключей с высокой кардинальностью или «горячих» ключей (например, текущая дата). Анализируйте паттерны запросов перед выбором.
2.  **Изоляция через Namespace:** Для крупных систем размещайте разные шарды в разных Namespace. Это упрощает управление лимитами (`ResourceQuota`) и безопасностью (`RBAC`).
3.  **Graceful Degradation:** Проектируйте систему так, чтобы при отказе одного шарда остальные продолжали работать, а пользователь получал частичный функционал или информативное сообщение.
4.  **Автоматизируйте решардинг:** Если система предполагает частый рост данных, используйте специализированные решения (Vitess, Citus, ProxySQL), так как ручной решардинг в Kubernetes крайне подвержен ошибкам.
5.  **Тестируйте Blast Radius:** Проводите Chaos Engineering эксперименты, отключая целые шарды, чтобы убедиться в отсутствии каскадных сбоев.
6.  **ResourceQuota и LimitRange:** Ограничивайте ресурсы каждого шарда, чтобы предотвратить потребление всех ресурсов кластера одним сегментом.
7.  **Сетевая изоляция:** По умолчанию используйте `deny-all` NetworkPolicy в namespace шарда и явно разрешайте только необходимые соединения.
8.  **Стабильные имена:** Используйте Headless Service и StatefulSet для приложений с состоянием, чтобы обеспечить стабильную сетевую идентичность шардов.
9.  **Мониторинг skew:** Настройте алерты на превышение порога дисбаланса между шардами (например, если количество запросов к одному шарду в 2 раза превышает среднее).
10. **Секретная изоляция:** Используйте отдельные ServiceAccount и RBAC для каждого шарда. Храните конфигурацию шарда в отдельном ConfigMap и Secret, чтобы изменение одного шарда не затрагивало другие.

---

## Troubleshooting

### Проблема: Неравномерное распределение нагрузки (Hot shard)
**Симптомы:** Один шард показывает значительно более высокую утилизацию CPU/памяти, большую задержку или количество ошибок, чем остальные.

**Причины:**
*   Неудачный ключ шардирования (например, `tenant_id % 3` при сильно неравномерном распределении tenant'ов).
*   Наличие «виртуальных горячих ключей» (например, популярный товар в e-commerce, на который приходится 30% запросов).
*   Неправильная конфигурация HPA (слишком высокий порог масштабирования).

**Решение:**
1.  Проанализируйте метрики `shard_skew` и `request_latency` по каждому шарду.
2.  Если проблема в ключе — перейдите на консистентное хеширование или добавьте второй уровень шардирования.
3.  Если проблема в данных — перераспределите горячие ключи (например, используйте денормализацию или кэширование).
4.  Если проблема в HPA — уменьшите `averageUtilization` или перейдите на кастомные метрики (очередь, RPS).

### Проблема: Поды шарда остаются в Pending
**Симптомы:** `kubectl get pods` показывает `Pending`, `kubectl describe pod` показывает `0/X nodes are available: Insufficient cpu/memory`.

**Причины:**
*   Недостаточно ресурсов в кластере (ResourceQuota или физические лимиты узлов).
*   NodeSelector или Taints/Tolerations не соответствуют доступным узлам.
*   Topology Spread Constraints не могут быть выполнены из-за нехватки узлов в нужных зонах.

**Решение:**
1.  Проверьте `kubectl describe node` на предмет доступных ресурсов.
2.  Проверьте `kubectl get resourcequota` в namespace шарда.
3.  Временно ослабьте `maxSkew` в Topology Spread Constraints или уменьшите количество реплик.
4.  Если используется Karpenter/CA — проверьте, добавлены ли новые узлы.

### Проблема: Не работает маршрутизация трафика
**Симптомы:** Запросы попадают не в тот шард или возвращают 404/502.

**Причины:**
*   Некорректные labels в Service или Ingress/Gateway API.
*   Отсутствующие или неправильные DNS-записи.
*   Конфликт портов или неверный `targetPort`.

**Решение:**
1.  Проверьте `kubectl get endpoints <service-name>` — должны быть адреса подов.
2.  Проверьте `kubectl describe ingress` или `kubectl describe httproute` на предмет ошибок синхронизации.
3.  Проверьте `kubectl get svc` и `kubectl describe svc` на предмет корректности селектора и портов.

### Проблема: Утечка данных между шардами
**Симптомы:** Поды шарда A могут получить доступ к данным шарда B, что нарушает изоляцию.

**Причины:**
*   Отсутствие NetworkPolicy или слишком широкие правила (`allow-all`).
*   Общий Secret/ConfigMap между шардами.
*   Использование одного ServiceAccount для всех шардов.

**Решение:**
1.  Внедрите `default-deny` NetworkPolicy в каждый namespace шарда.
2.  Используйте отдельные Secret и ConfigMap для каждого шарда.
3.  Создайте отдельный ServiceAccount для каждого шарда и привяжите его через `serviceAccountName`.

### Проблема: Решардинг приводит к даунтайму
**Симптомы:** При добавлении/удалении шардов часть запросов возвращает 500 или 503.

**Причины:**
*   Переключение трафика произошло до завершения синхронизации данных.
*   Клиентское кэширование старых адресов шардов.
*   Отсутствие graceful shutdown на стороне приложения.

**Решение:**
1.  Используйте Blue/Green подход: разверните новые шарды, синхронизируйте данные, убедитесь в работоспособности, затем переключите трафик.
2.  Настройте `preStop` hook и `terminationGracePeriodSeconds` для graceful shutdown.
3.  Уменьшите TTL кэширования DNS на клиенте (или используйте Service Mesh с умным маршрутизатором).

---

## Дополнительная информация

### Ссылки

*   [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) — современный стандарт трафика.
*   [Sharding Patterns (Microservices.io)](https://microservices.io/patterns/data/sharding.html) — теоретическая база.
*   [Karpenter Documentation](https://karpenter.sh/) — управление узлами под специфичные нагрузки.
*   **[Обзор автоскейлинга в K8s](./overview_concepts.md)** — общие принципы.
*   **[Шаблон воркеров с очередями](./workers_queue_pattern.md)** — реализация паттерна обработки.
*   **[Управление размещением подов (Topology Spread)](../Scheduling/affinity.md)** — детали топологического планирования.
*   **[Шардирование баз данных](../../Databases/Concepts/sharding.md)** — теория и методы распределения данных.
