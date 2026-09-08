# KEDA + Redis: Масштабирование на основе длины очереди и Stream

## Определения

**Redis Lists Scaler** — встроенный скейлер KEDA для масштабирования подов на основе длины списка (List) в Redis. Использует команду `LLEN` для получения текущей длины очереди.

**Redis Streams Scaler** — скейлер KEDA для масштабирования на основе длины Redis Stream. Учитывает pending entries (неподтверждённые сообщения) и длину stream через команды `XLEN` и `XINFO GROUPS`.

**Redis Sentinel Scaler** — вариант подключения к Redis через Sentinel для обеспечения отказоустойчивости. При падении мастера Sentinel автоматически переключает на реплику.

**listLength** — параметр порога длины списка, при превышении которого KEDA увеличивает количество реплик. Аналог `queueLength` в RabbitMQ.

**databaseIndex** — индекс базы данных Redis (по умолчанию 0). Используется когда очереди находятся в разных БД одного Redis-инстанса.

## Теоретический блок

### Поддерживаемые типы Redis в KEDA

| Тип скейлера | Источник данных | Метрика | Типичный use case |
|:---|:---|:---|:---|
| `redis` (Lists) | `LLEN queue_name` | Длина списка | Очереди задач (BRPOPLPUSH, BLPOP) |
| `redis-streams` | `XLEN` + `XINFO GROUPS` | Длина stream + pending | Event sourcing, log aggregation |

### Архитектура взаимодействия

```text
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│    Redis     │ ◀─── │  KEDA Redis  │ ───▶ │  KEDA        │
│    Server    │      │  Scaler      │      │  Operator    │
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                    │
                                              ┌─────▼─────┐
                                              │    HPA    │
                                              └─────┬─────┘
                                                    │
                                              ┌─────▼─────┐
                                              │  Worker   │
                                              │  Pods     │
                                              └───────────┘
```

### Формула расчёта реплик

Аналогична другим скейлерам KEDA:

```text
desiredReplicas = ceil(currentReplicas × (listLength / targetValue))
```

Пример: 1 реплика, 300 сообщений в очереди, targetValue = 50:

```text
desiredReplicas = ceil(1 × (300 / 50)) = 6 реплик
```

### Параметры Redis Lists Scaler

| Параметр | Обязательный | По умолчанию | Описание |
|:---|:---|:---|:---|
| `address` | Да | — | Адрес Redis (`host:port`) |
| `listName` | Да | — | Имя списка (очереди) |
| `listLength` | Нет | `5` | Порог длины для масштабирования |
| `databaseIndex` | Нет | `0` | Индекс БД Redis |
| `password` | Нет | — | Пароль Redis (передаётся через Secret) |

### Параметры Redis Streams Scaler

| Параметр | Обязательный | По умолчанию | Описание |
|:---|:---|:---|:---|
| `address` | Да | — | Адрес Redis (`host:port`) |
| `stream` | Да | — | Имя stream |
| `consumerGroup` | Да | — | Имя consumer group |
| `lagCount` | Нет | `5` | Порог lag (pending entries) для масштабирования |
| `activationLagCount` | Нет | `0` | Порог активации из 0 реплик |
| `databaseIndex` | Нет | `0` | Индекс БД Redis |

## Практические сценарии

### Сценарий 1: Базовое масштабирование по длине List

Воркер обрабатывает задачи из Redis List (LPUSH/BRPOP паттерн):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-credentials
  namespace: app
type: Opaque
stringData:
  host: "redis-master.app.svc:6379"
  password: "redis-password"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: host
      name: redis-credentials
      key: host
    - parameter: password
      name: redis-credentials
      key: password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: redis-queue-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: task-worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 10
  pollingInterval: 15
  cooldownPeriod: 300
  triggers:
    - type: redis
      metadata:
        address: redis-master.app.svc:6379
        listName: task-queue
        listLength: "10"
        databaseIndex: "0"
      authenticationRef:
        name: redis-auth
```

### Сценарий 2: Redis Streams с Consumer Group

Event sourcing с Redis Streams — современная замена классическим очередям:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-stream-credentials
  namespace: app
type: Opaque
stringData:
  host: "redis-master.app.svc:6379"
  password: "redis-password"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-stream-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: host
      name: redis-stream-credentials
      key: host
    - parameter: password
      name: redis-stream-credentials
      key: password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: redis-stream-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: event-processor-deployment
  minReplicaCount: 0
  maxReplicaCount: 15
  pollingInterval: 10
  cooldownPeriod: 300
  triggers:
    - type: redis-streams
      metadata:
        address: redis-master.app.svc:6379
        stream: events
        consumerGroup: event-processors
        lagCount: "100"
        activationLagCount: "10"
        databaseIndex: "0"
      authenticationRef:
        name: redis-stream-auth
```

**Ключевое отличие от List:** `redis-streams` учитывает pending entries (сообщения, которые были доставлены, но не подтверждены ACK). Это защищает от ситуации, когда воркер упал и его задачи застряли в pending.

### Сценарий 3: Redis Sentinel (отказоустойчивость)

Подключение через Sentinel для автоматического failover:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-sentinel-credentials
  namespace: app
type: Opaque
stringData:
  host: "redis-sentinel.app.svc:26379"
  password: "sentinel-password"
  sentinelPassword: "sentinel-password"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-sentinel-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: host
      name: redis-sentinel-credentials
      key: host
    - parameter: password
      name: redis-sentinel-credentials
      key: password
    - parameter: sentinelPassword
      name: redis-sentinel-credentials
      key: sentinelPassword
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: redis-sentinel-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 8
  triggers:
    - type: redis
      metadata:
        address: redis-sentinel.app.svc:26379
        listName: tasks
        listLength: "20"
        sentinelPassword: "sentinel-password"
      authenticationRef:
        name: redis-sentinel-auth
```

### Сценарий 4: Через Prometheus + Redis Exporter

Альтернативный подход через Redis Exporter:

```yaml
# Установка Redis Exporter
helm install redis-exporter oliver006/redis_exporter \
  --namespace monitoring \
  --set redisAddress=redis://redis-master:6379 \
  --set redisPassword=redis-password

# ScaledObject через Prometheus Scaler
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: redis-via-prometheus
  namespace: app
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring:9090
        query: |
          redis_llen{list="task-queue"}
        threshold: "10"
```

Преимущества: единый стек метрик, история, дополнительные метрики Redis (memory, connections, hits/misses).

### Сценарий 5: Несколько очередей в разных БД

Очереди в разных индексах Redis:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-db-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 20
  triggers:
    - type: redis
      metadata:
        address: redis-master.app.svc:6379
        listName: high-priority-tasks
        listLength: "5"
        databaseIndex: "0"
      authenticationRef:
        name: redis-auth
    - type: redis
      metadata:
        address: redis-master.app.svc:6379
        listName: low-priority-tasks
        listLength: "20"
        databaseIndex: "1"
      authenticationRef:
        name: redis-auth
```

### Сценарий 6: Cron + Redis混合 (рабочие часы + очередь)

Масштабирование по расписанию + по нагрузке из очереди:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hybrid-redis-cron
  namespace: app
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: redis
      metadata:
        address: redis-master.app.svc:6379
        listName: task-queue
        listLength: "10"
      authenticationRef:
        name: redis-auth
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: "0 9 * * 1-5"
        end: "0 18 * * 1-5"
        desiredReplicas: "3"
```

## Дополнительная информация

### Диагностика

```bash
# Проверка длины очереди вручную
kubectl run -it --rm redis-debug --image=redis:7 --restart=Never -- \
  redis-cli -h redis-master.app.svc -a <password> LLEN task-queue

# Проверка pending в Streams
kubectl run -it --rm redis-debug --image=redis:7 --restart=Never -- \
  redis-cli -h redis-master.app.svc -a <password> XINFO GROUPS events

# Проверка ScaledObject
kubectl describe scaledobject redis-queue-scaler -n app

# Проверка метрик KEDA
kubectl port-forward -n keda svc/keda-metrics-server 8080:8080
curl http://localhost:8080/metrics | grep redis
```

### Типичные проблемы

**1. Scaler не подключается к Redis:**

```text
Причина: incorrect username/password, неверный порт, NetworkPolicy блокирует
Решение: проверить Secret, проверить NetworkPolicy между namespace keda и app
```

**2. listLength всегда 0:**

```text
Причина: неправильное имя списка, сообщения потребляются быстрее чем появляются
Решение: проверить LLEN через redis-cli, увеличить pollingInterval
```

**3. Consumer lag в Streams не растёт:**

```text
Причина: ACK происходит мгновенно, нет медленных воркеров
Решение: проверить XINFO GROUPS для просмотра pending, использовать lagCount вместо listLength
```

### Когда использовать Redis Lists vs Streams

| Критерий | Redis Lists | Redis Streams |
|:---|:---|:---|
| Доставка сообщений | At-most-once (BRPOP забирает) | At-least-once (с ACK) |
| Consumer groups | Нет | Да |
| Pending entries | Нет | Да |
| Replay | Нет | Да (сохраняются) |
| Сложность | Простая | Средняя |
| Use case | Простые задачи, cron | Event sourcing, audit log |

### См. также

* [KEDA: Основные концепции](./keda_concepts.md) — архитектура и компоненты
* [KEDA + Kafka](./kafka-keda-scaler.md) — масштабирование по consumer lag
* [KEDA: Практические сценарии](./practical_scenarios.md) — RabbitMQ, Prometheus, Cron
* [KEDA: FinOps-гардрейлы](./keda-finops.md) — экономика масштабирования
