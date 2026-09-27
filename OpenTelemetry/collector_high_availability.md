# OpenTelemetry: Отказоустойчивость Collector

## Определения

**Отказоустойчивость (High Availability) OpenTelemetry Collector** — это архитектурные решения, обеспечивающие непрерывную работу Collector при отказах компонентов, сетевых разрывах или плановых обновлениях. Включает кластеризацию, health checks, graceful shutdown и disaster recovery.

В 2026 году HA является обязательным требованием для production-развёртывания OTel.

## Теоретический блок

### Уровни отказоустойчивости

| Уровень | Описание | RTO | RPO |
| :--- | :--- | :--- | :--- |
| **Basic** | Один экземпляр Collector | Часы | Потеря данных |
| **HA** | 3+ экземпляра за LB | Минуты | Минуты |
| **DR** | Географическое распределение | Десятки минут | Десятки минут |

### Компоненты HA

```text
HA Collector:
├── Multiple Instances (3+)
├── Load Balancer (L4/L7)
├── Health Checks
├── Graceful Shutdown
└── Persistent Queues
```

## Практические сценарии

### Сценарий 1: Кластеризация в Kubernetes

**Deployment с 3 репликами:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  selector:
    matchLabels:
      app: otel-collector
  template:
    metadata:
      labels:
        app: otel-collector
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: otel-collector
                topologyKey: kubernetes.io/hostname
      containers:
        - name: collector
          image: otel/opentelemetry-collector-contrib:0.96.0
          ports:
            - containerPort: 4317
              name: otlp
            - containerPort: 4318
              name: otlp-http
            - containerPort: 8888
              name: metrics
          livenessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 15
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "1Gi"
```

**Service с балансировкой:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  selector:
    app: otel-collector
  ports:
    - port: 4317
      targetPort: 4317
      name: otlp
    - port: 4318
      targetPort: 4318
      name: otlp-http
  sessionAffinity: None
```

### Сценарий 2: Health Checks

**Конфигурация health check extension:**

```yaml
extensions:
  health_check:
    endpoint: 0.0.0.0:13133
    response_delay: 1s

  zpages:
    endpoint: 0.0.0.0:55679

  pprof:
    endpoint: 0.0.0.0:1777

service:
  extensions: [health_check, zpages, pprof]
```

**Проверка здоровья:**

```bash
# Проверка health check
curl http://otel-collector:13133/

# Проверка zPages
curl http://otel-collector:55679/debug/tracez

# Проверка pprof
go tool pprof http://otel-collector:1777/debug/pprof/heap
```

### Сценарий 3: Graceful Shutdown

**Конфигурация graceful shutdown:**

```yaml
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
  extensions: [health_check]
```

**Настройка в Kubernetes:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: collector
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 5"]
```

### Сценарий 4: Persistent Queues

**Настройка sending_queue с file_storage:**

```yaml
exporters:
  otlp:
    endpoint: "backend:4317"
    sending_queue:
      enabled: true
      num_consumers: 10
      queue_size: 5000
      storage: file_storage

extensions:
  file_storage:
    directory: /var/lib/otelcol/file_storage
    timeout: 10s

service:
  extensions: [file_storage]
```

### Сценарий 5: Disaster Recovery

**Географическое распределение:**

```yaml
# ЦОД 1
apiVersion: v1
kind: Service
metadata:
  name: otel-collector-dc1
spec:
  selector:
    app: otel-collector
    topology.kubernetes.io/zone: dc1
  ports:
    - port: 4317

# ЦОД 2
apiVersion: v1
kind: Service
metadata:
  name: otel-collector-dc2
spec:
  selector:
    app: otel-collector
    topology.kubernetes.io/zone: dc2
  ports:
    - port: 4317
```

**Маршрутизация по приоритету:**

```yaml
exporters:
  loadbalancing:
    protocol:
      otlp:
        timeout: 10s
    resolver:
      dns:
        hostname: otel-collector-dc1
        port: 4317
        priority:
          - hostname: otel-collector-dc1
            weight: 100
          - hostname: otel-collector-dc2
            weight: 50
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Collector не проходит health check** | Ошибка в конфигурации | Проверить логи, endpoint health_check |
| **Данные теряются при перезапуске** | Отсутствует file_storage | Настроить persistent queues |
| **Неравномерная нагрузка** | Неправильная балансировка | Настроить podAntiAffinity, sessionAffinity |
| **Долгий shutdown** | Некорректное завершение | Настроить terminationGracePeriodSeconds |

### Best Practices

1. **Запускайте минимум 3 экземпляра** — для обеспечения HA.
2. **Используйте podAntiAffinity** — для распределения по нодам.
3. **Настраивайте health check** — для автоматического перезапуска.
4. **Используйте persistent queues** — для сохранения данных при перезапуске.
5. **Тестируйте disaster recovery** — проверяйте восстановление после сбоев.

### Ссылки

- [OTel Collector High Availability](https://opentelemetry.io/docs/collector/configuration/#high-availability)
- [Kubernetes Pod Anti-Affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#affinity-and-anti-affinity)
- [Graceful Shutdown](https://opentelemetry.io/docs/collector/configuration/#graceful-shutdown)
