# Подготовка к высоким нагрузкам в Kubernetes

## Определения

**Высокая нагрузка (High Load)** в Kubernetes — состояние, при котором потребление системных ресурсов (CPU, RAM, Network, Disk IOPS) или пропускная способность компонентов Control Plane приближается к лимитам инфраструктуры или архитектурным ограничениям платформы.

Ключевым фактором является не только абсолютное число **RPS (Requests Per Second)**, но и:
*   **Пиковая нагрузка (Spikes)**: Способность системы выдерживать мгновенные всплески трафика и скорость реакции автоскейлинга.
*   **Насыщение (Saturation)**: Степень использования ресурсов, при которой время обработки запросов начинает расти экспоненциально из-за очередей.
*   **Время восстановления (MTTR)**: Скорость возврата системы в штатный режим после сбоя, вызванного перегрузкой.
*   **Давление на Control Plane**: Нагрузка на API Server, etcd и Scheduler при массовом создании подов или интенсивном обновлении статусов объектов.
*   **CFS Throttling**: Искусственное ограничение CPU планировщиком CFS (Completely Fair Scheduler) при превышении лимитов. Проявляется как рост Latency даже при низкой средней загрузке CPU.

---

## Базовые концепции

### Признаки высокой нагрузки

1.  **Latency (Задержка)**: Рост времени отклика. Часто вызван троттлингом **CPU** (CFS Throttling), даже если средняя загрузка ядер кажется низкой (< 100%).
2.  **Ошибки 5xx и таймауты**: Каскадные сбои при накоплении очередей в межсервисном взаимодействии.
3.  **OOMKilled (Out Of Memory)**: Завершение подов из-за превышения лимитов памяти или утечек под нагрузкой.
4.  **Рост очередей**: В асинхронных системах (Kafka, RabbitMQ) сообщения накапливаются быстрее, чем обрабатываются (**Consumer Lag**).
5.  **Замедление Control Plane**: Обновление **Deployment** с большим количеством реплик замедляется, так как планировщику труднее найти ресурсы.
6.  **Каскадные сбои**: Когда один сервис становится узким местом, это вызывает цепную реакцию по всем зависимым сервисам.

### Стратегии масштабирования

*   **Вертикальное масштабирование (Vertical Scaling)**: Увеличение ресурсов (CPU, RAM) для подов. 
    *   Реализуется через **VPA (Vertical Pod Autoscaler)**. 
    *   С версии **v1.31** поддерживается `In-place Pod Vertical Scaling` — изменение ресурсов без рестарта контейнера.
*   **Горизонтальное масштабирование (Horizontal Scaling)**: Увеличение количества реплик. 
    *   Реализуется через **HPA (Horizontal Pod Autoscaler)**. 
    *   Требует **Stateless**-архитектуры.
*   **Функциональное масштабирование**: Архитектурное разделение на независимо масштабируемые блоки (микросервисы, выделенные **NodePool** для разных типов задач).
*   **Параметрическое масштабирование**: Оптимизация параметров (число воркеров Nginx/PHP-FPM, настройка пулов соединений БД, тюнинг **GC**).

### Инструменты автоматизации

*   **HPA v2**: Позволяет масштабировать по CPU/RAM и кастомным метрикам. Секция `behavior` настраивает окна стабилизации (`stabilizationWindowSeconds`) для предотвращения "дребезга".
*   **KEDA (Event-driven Autoscaling)**: Масштабирование на основе событий (Kafka lag, очереди RabbitMQ, запросы в Prometheus). Поддерживает **Scale-to-Zero**.
*   **Karpenter**: Современный JIT-автоскейлер узлов. Анализирует требования подов и напрямую заказывает нужные типы узлов у провайдера, заменяя устаревший Cluster Autoscaler.
*   **PriorityClasses**: Гарантируют приоритетное выживание критических компонентов (Ingress, DNS) при дефиците ресурсов.
*   **Pod Disruption Budget (PDB)**: Ограничивает количество одновременно выключаемых подов при плановых работах или сбоях узлов.

---

## Практические сценарии

### Системный тюнинг (sysctl)

Использование `securityContext` в подах для снятия ограничений сетевого стека:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: high-load-pod
spec:
  securityContext:
    sysctls:
    - name: net.core.somaxconn
      value: "65535"  # Максимальный размер очереди прослушивания сокетов
    - name: net.ipv4.ip_local_port_range
      value: "1024 65535"  # Диапазон портов для исходящих соединений
    - name: net.ipv4.tcp_max_syn_backlog
      value: "65535"  # Защита от SYN-флуда и переполнения очереди
    - name: net.netfilter.nf_conntrack_max
      value: "1048576"  # Максимальное число отслеживаемых соединений
    - name: net.ipv4.tcp_tw_reuse
      value: "1"  # Переиспользование TIME_WAIT соединений
    - name: net.ipv4.ip_unprivileged_port_start
      value: "80"  # Разрешить порты < 1024 без root
  containers:
  - name: app
    image: nginx:latest
```

**Примечание:** Системные `sysctl` требуют特权权限 или настройки на уровне узла. В managed-кластерах доступны не все параметры.

### Настройка узлов (Node Level)

*   **TCP BBR**: Включение алгоритма контроля перегрузки сети на уровне ядра узлов для снижения задержек.
*   **Ulimits**: Настройка `nofile` (максимальное количество открытых файлов) на уровне рантайма (containerd/docker) до 1,000,000+.
*   **CPU Manager**: Использование политики `static` в kubelet для предоставления критическим подам эксклюзивных ядер CPU (минимизация context switch).
*   **Memory Manager**: Политика `static` для выделения NUMA-привязанной памяти критическим подам.
*   **Topology Manager**: Координация CPU Manager, Memory Manager и Device Manager для оптимального размещения подов в NUMA-топологии.

### Управление соединениями и ресурсами

*   **Connection Pooling**: Использование **PgBouncer** (Postgres) или **ProxySQL** (MySQL). Настраивайте пулинг как можно ближе к базе или в виде Sidecar.
*   **Keep-Alive**: Агрессивные таймауты Keep-Alive на Ingress и в приложениях для повторного использования соединений.
*   **Topology Aware Routing**: Направление трафика внутри одной зоны доступности (AZ) для минимизации задержек.
*   **Размещение подов**:
    *   **Pod Affinity**: Размещение часто общающихся сервисов на одних узлах (`topologyKey: kubernetes.io/hostname`).
    *   **Pod Anti-Affinity**: Исключение размещения подов одного сервиса на одном узле для отказоустойчивости.
    *   **Taints и Tolerations**: Использование выделенных **NodePool** для изоляции критических нагрузок от "шумных соседей" (noisy neighbors).

### Паттерны отказоустойчивости (Resilience)

1.  **Circuit Breaker (Прерыватель)**: Временная остановка запросов к тормозящему сервису через Service Mesh (**Istio** `DestinationRule`).
2.  **Load Shedding (Сброс нагрузки)**: Отдача `503 Service Unavailable` или кэша для части трафика при превышении порогов Latency.
3.  **Graceful Shutdown**: Использование `preStop` хуков и настройки `terminationGracePeriodSeconds` (60с+), чтобы под успел дообработать запросы после SIGTERM.
4.  **Retry Budget**: Ограничение количества повторных попыток для предотвращения каскадных сбоев.
5.  **Timeout Configuration**: Адаптивные таймауты на основе p99/p95 latency.

### Борьба с DDoS и аномалиями

1.  **Rate Limiting**: Лимиты на уровне Ingress (аннотации Nginx Ingress для ограничения по IP/Cookie).
2.  **WAF (Web Application Firewall)**: Использование внешних решений (Cloudflare, Qrator) или модулей для фильтрации трафика до кластера.
3.  **HPA Limits**: Установка высокого `maxReplicas`, чтобы выдержать легитимный всплеск.
4.  **API Priority and Fairness (APF)**: Встроенный механизм Kubernetes для ограничения количества запросов к API-серверу по приоритетам.

### Диагностика под нагрузкой

**Проверка троттлинга CPU:**

```bash
# Просмотр текущего потребления и сравнение с requests/limits
kubectl top pods --sort-by=cpu

# Анализ метрики container_cpu_cfs_throttled_seconds_total в Prometheus
# Рост значения при загрузке < 100% означает нехватку лимитов (Bursting)

# Проверка статуса пода
kubectl describe pod <pod-name> | grep -A 5 "Status:"
```

**Проверка OOMKilled:**

```bash
# Поиск событий завершения из-за нехватки памяти
kubectl get pods -A | grep -i "OOMKilled"

# Проверка логов ядра узла
dmesg | grep -i "oom"

# Просмотр последних событий пода
kubectl describe pod <pod-name> | grep -A 10 "Last State:"
```

**Проверка очередей и таймаутов:**

```bash
# Просмотр событий пода
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'

# Проверка подов в состоянии Pending
kubectl get pods --field-selector status.phase=Pending

# Просмотр логов контроллера планировщика
kubectl logs -n kube-system kube-scheduler-<node-name>
```

---

## Конфигурации для высоких нагрузок

### HPA v2 с Behavior

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: high-load-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: high-load-app
  minReplicas: 3
  maxReplicas: 100
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300  # 5 минут стабилизации перед уменьшением
      policies:
      - type: Percent
        value: 10  # Уменьшать не более 10% реплик за раз
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0  # Немедленное масштабирование вверх
      policies:
      - type: Percent
        value: 100  # Удвоение реплик за раз
        periodSeconds: 15
      - type: Pods
        value: 10  # Или добавление 10 подов за раз
        periodSeconds: 15
      selectPolicy: Max  # Выбирать политику с максимальным эффектом
```

### KEDA ScaledObject для Kafka

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
spec:
  scaleTargetRef:
    name: kafka-consumer
  pollingInterval: 15
  cooldownPeriod: 300
  minReplicaCount: 2
  maxReplicaCount: 50
  triggers:
  - type: kafka
    metadata:
      bootstrapServers: kafka-cluster:9092
      consumerGroup: my-consumer-group
      topic: high-load-topic
      lagThreshold: "100"
      activationLagThreshold: "10"
    authenticationRef:
      name: kafka-auth
```

### Karpenter NodePool

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: high-performance-pool
spec:
  template:
    metadata:
      labels:
        workload-type: high-load
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["on-demand"]
      - key: node.kubernetes.io/instance-type
        operator: In
        values: ["m5.2xlarge", "m5.4xlarge", "c5.2xlarge"]
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64"]
      taints:
      - key: workload-type
        value: high-load
        effect: NoSchedule
  limits:
    cpu: "1000"
    memory: 2000Gi
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 60s
  weight: 100
```

### PriorityClass для критических сервисов

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-load-critical
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Для критических сервисов высокой нагрузки"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-load-important
value: 100000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Для важных сервисов, которые должны выживать при нехватке ресурсов"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-workload
value: -100
globalDefault: false
preemptionPolicy: Never  # Не вытеснять другие поды
description: "Для фоновых задач, которые не должны вытеснять критические сервисы"
```

### Pod Disruption Budget (PDB)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: high-load-pdb
spec:
  minAvailable: "70%"  # Или maxUnavailable: "30%"
  selector:
    matchLabels:
      app: high-load-app
  unhealthyPodEvictionPolicy: Always  # Разрешать удаление нездоровых подов
```

---

## Мониторинг и алертинг

### Ключевые метрики

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `container_cpu_cfs_throttled_seconds_total` | Время троттлинга CPU | > 25% от общего времени |
| `container_memory_working_set_bytes` | Использование памяти | > 80% от limits |
| `kube_pod_container_status_terminated_reason` | Причина завершения пода | `OOMKilled` > 0 |
| `kube_deployment_status_replicas_unavailable` | Недоступные реплики | > 0 в течение 5 минут |
| `apiserver_request_duration_seconds` | Latency API-сервера | p99 > 1 секунды |
| `etcd_disk_wal_fsync_duration_seconds` | Задержка записи etcd | p99 > 10мс |

### Примеры алертов Prometheus

```yaml
groups:
- name: high-load-alerts
  rules:
  - alert: HighCPUThrottling
    expr: |
      sum(rate(container_cpu_cfs_throttled_seconds_total[5m])) by (pod) /
      sum(rate(container_cpu_usage_seconds_total[5m])) by (pod) > 0.25
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокий троттлинг CPU для пода {{ $labels.pod }}"

  - alert: HighMemoryUsage
    expr: |
      container_memory_working_set_bytes /
      container_spec_memory_limit_bytes > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокое использование памяти для пода {{ $labels.pod }}"

  - alert: PodOOMKilled
    expr: |
      kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Под {{ $labels.pod }} завершен из-за OOMKilled"
```

---

## Дополнительная информация

### Наблюдаемость (Observability)

*   **RED Метод (Сервисы)**: Rate (RPS), Errors (ошибки), Duration (Latency P99).
*   **USE Метод (Ресурсы)**: Utilization (утилизация), Saturation (насыщение/очереди), Errors (ошибки оборудования).
*   **Профилирование**: Использование Continuous Profiling (Pyroscope, Parca) для поиска узких мест в коде под нагрузкой.

### Нагрузочное тестирование

*   **Инструменты**: **k6** (современный стандарт), **JMeter** (Legacy/сложные сценарии), **fortio** (gRPC/HTTP), **hey**.
*   **PDB (Pod Disruption Budget)**: Обязательное ограничение количества одновременно выключаемых подов при работах.

### Troubleshooting: Частые ошибки

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Высокий latency при нормальном CPU | CFS Throttling | Увеличьте CPU limits или используйте Guaranteed QoS |
| OOMKilled под нагрузкой | Утечка памяти или inadequate limits | Увеличьте memory limits, проверьте приложение на утечки |
| Поды в Pending | Нехватка ресурсов в кластере | Проверьте ресурсы узлов, настройте Karpenter/Cluster Autoscaler |
| KASPI не масштабирует | Неправильные метрики или толерантность | Проверьте targetRef, метрики и stabilizationWindowSeconds |
| Каскадные сбои | Медленный или недоступный сервис | Настройте circuit breaker и retry budget |
| Высокий Consumer Lag | Недостаточно воркеров | Увеличьте количество реплик, оптимизируйте обработку |

### Best Practices

1.  **Используйте Guaranteed QoS** для latency-sensitive приложений (requests = limits).
2.  **Настраивайте HPA behavior** для предотвращения "дребезга" и каскадных масштабирований.
3.  **Применяйте PDB** для всех критических сервисов.
4.  **Мониторьте CFS Throttling** — это скрытый убийца производительности.
5.  **Тестируйте под нагрузкой** перед выводом в production.
6.  **Используйте PriorityClasses** для изоляции критических сервисов.
7.  **Настраивайте Graceful Shutdown** для корректного завершения подов.

### См. также

*   [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)
*   [API Priority and Fairness (APF)](api_priority_and_fairness.md) — защита API-сервера от шумных потребителей.
*   [Автомасштабирование в Kubernetes](../Autoscaling/overview_concepts.md)
*   [Высокая доступность](../Base/high_availability.md)
*   [Graceful Shutdown](../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md)
*   [DNS в Kubernetes](../Networking/dns_deep_dive.md)
