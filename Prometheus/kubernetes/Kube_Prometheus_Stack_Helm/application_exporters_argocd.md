# Application Exporters — FluxCD HelmRelease Pattern

**Актуально для:** kube-prometheus-stack 88.x+, Flux v2.9.x, Prometheus Operator 0.80.x

## Определения

**Application Exporter (экспортер приложения)** — отдельный компонент для сбора метрик уровня приложения (consumer lag в Kafka, hit ratio в Redis, частота операций в MongoDB, глубина очередей в RabbitMQ), который не входит в базовый состав kube-prometheus-stack.

**HelmRelease (Flux CD)** — CRD `helm.toolkit.fluxcd.io/v2` для декларативного управления жизненным циклом Helm-чартов через GitOps. Контроллер `helm-controller` рендерит чарт, применяет манифесты и отслеживает дрейф.

**ServiceMonitor** — CRD Prometheus Operator, описывающий цель скрейпинга. Оператор Prometheus находит ServiceMonitor по метке `release: kube-prom-stack` (настраивается в `serviceMonitorSelector` ресурса `Prometheus`).

**Паттерн co-location** — развёртывание экспортера в том же namespace, что и рабочая нагрузка (workload). Это позволяет использовать короткие имена сервисов (например, `kafka.kafka.svc.cluster.local`) и избегает cross-namespace сетевых политик.

## Архитектура

```
Git Repository (Flux sources)
    │
    ▼
HelmRelease (per exporter, in workload namespace)
    │
    ├── Chart: prometheus-community/<exporter>
    ├── Values:
    │     ├── serviceMonitor.enabled: true
    │     ├── serviceMonitor.additionalLabels.release: kube-prom-stack
    │     ├── serviceMonitor.relabelings: job=<stable-name>
    │     └── resources.requests/limits
    │
    ▼
helm-controller → K8s API → Pod (Exporter) + Service + ServiceMonitor
                                                      │
                                                      ▼
                                    Prometheus Operator (serviceMonitorSelector: release=kube-prom-stack)
                                                      │
                                                      ▼
                                              Prometheus Server (scrape)
```

**Поток метрик:**
1. Flux `helm-controller` применяет `HelmRelease` в namespace рабочей нагрузки.
2. Чарт создаёт Deployment (экспортер), Service, ServiceMonitor.
3. ServiceMonitor получает метку `release: kube-prom-stack`.
4. Prometheus Operator (в namespace `observability`) видит ServiceMonitor через селектор.
5. Operator генерирует scrape-конфиг и передаёт Prometheus Server.
6. Prometheus опрашивает экспортер по Pull-модели.

## Почему в namespace рабочей нагрузки?

| Аргумент | Объяснение |
|---|---|
| **Сетевой доступ** | Экспортёру нужен доступ к сервису (Kafka, MongoDB, Redis, RabbitMQ). В одном namespace работает короткое DNS-имя (`kafka.kafka.svc.cluster.local` → `kafka`). |
| **RBAC изоляция** | Flux может использовать `spec.serviceAccountName` с правами, ограниченными целевым namespace. |
| **Жизненный цикл** | Экспортер обновляется/удаляется вместе с рабочей нагрузкой через `dependsOn` в Kustomization. |
| **Секреты** | Пароли (ExternalSecret из Vault) хранятся в том же namespace, где они используются. |

## Практические сценарии

### Единый паттерн HelmRelease

Все экспортеры следуют одной структуре:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <exporter-name>
  namespace: <workload-namespace>  # НЕ observability
spec:
  interval: 15m
  timeout: 5m
  chart:
    spec:
      chart: prometheus-<exporter>
      version: "<chart-version>"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    # 1. Подключение к целевому сервису (короткое DNS-имя в том же namespace)
    <service-connection-config>

    # 2. ServiceMonitor для kube-prometheus-stack
    serviceMonitor:
      enabled: true
      additionalLabels:
        release: kube-prom-stack  # Ключевая метка для descubrimiento
      interval: 30s               # 15s для Redis (быстрые метрики)
      relabelings:
        - targetLabel: job
          replacement: <stable-job-name>  # kafka, mongodb, redis, rabbitmq

    # 3. Ресурсы
    resources:
      requests:
        cpu: <request-cpu>
        memory: <request-memory>
      limits:
        cpu: <limit-cpu>
        memory: <limit-memory>
```

---

### 1. Kafka Exporter

**Чарт:** `prometheus-kafka-exporter` v3.0.1 (prometheus-community)  
**Что собирает:** consumer lag (по партициям и группам), количество партиций топика, статус брокеров, недореплицированные партиции, частоту сообщений.

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: kafka-exporter
  namespace: kafka
spec:
  interval: 15m
  chart:
    spec:
      chart: prometheus-kafka-exporter
      version: "3.0.1"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    kafkaServer:
      - kafka.kafka.svc.cluster.local:9092
    serviceMonitor:
      enabled: true
      additionalLabels:
        release: kube-prom-stack
      interval: 30s
      relabelings:
        - targetLabel: job
          replacement: kafka
    resources:
      requests:
        cpu: 25m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
```

**Ключевые метрики для алертинга:**
- `kafka_consumergroup_lag_sum` — суммарный лаг по consumer group
- `kafka_topic_partition_under_replicated_partition` — состояние репликации
- `kafka_brokers` — количество видимых брокеров

---

### 2. MongoDB Exporter

**Чарт:** `prometheus-mongodb-exporter` v3.8.0 (prometheus-community)  
**Что собирает:** количество документов по коллекциям, лаг репликации, статистику индексов, частоту операций (insert/update/delete/query), hit ratio кэша WiredTiger, использование пула соединений.

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: mongodb-exporter
  namespace: db
spec:
  interval: 15m
  chart:
    spec:
      chart: prometheus-mongodb-exporter
      version: "3.8.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    mongodb:
      uri: "mongodb://exporter:${MONGO_EXPORTER_PASS}@mongodb.db.svc.cluster.local:27017/admin"
    serviceMonitor:
      enabled: true
      additionalLabels:
        release: kube-prom-stack
      interval: 30s
      relabelings:
        - targetLabel: job
          replacement: mongodb
    resources:
      requests:
        cpu: 25m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
```

> **Важно:** `mongodb.uri` содержит учётные данные. Значение подставляется через `ExternalSecret` из Vault и **никогда не хранится в Git открытым текстом**.

**Пользователь MongoDB для экспортера:**
```javascript
use admin
db.createUser({
  user: "exporter",
  pwd: "secure-password",
  roles: [
    { role: "clusterMonitor", db: "admin" },
    { role: "read", db: "local" }
  ]
})
```

---

### 3. Redis Exporter

**Чарт:** `prometheus-redis-exporter` v6.9.0 (prometheus-community)  
**Что собирает:** hit ratio кэша, использование памяти, вытеснения ключей, частота команд, replication lag.

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: redis-exporter
  namespace: db
spec:
  interval: 15m
  chart:
    spec:
      chart: prometheus-redis-exporter
      version: "6.9.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    redisAddress: redis://redis-master.db.svc.cluster.local:6379
    auth:
      enabled: true
      secret:
        name: redis-password
        key: redis-password
    serviceMonitor:
      enabled: true
      labels:
        release: kube-prom-stack
      interval: 15s
      relabelings:
        - targetLabel: job
          replacement: redis
    resources:
      requests:
        cpu: 10m
        memory: 32Mi
      limits:
        cpu: 100m
        memory: 64Mi
```

> **Почему `interval: 15s`:** Метрики Redis меняются быстро (hit rate, частота команд). Частый сбор даёт более точный сигнал для алертов о задержках.

**Ключевые метрики:**
- `redis_keyspace_hits_total` / `redis_keyspace_misses_total` — hit ratio кэша
- `redis_memory_used_bytes` против `redis_memory_max_bytes` — нехватка памяти
- `redis_evicted_keys_total` — вытеснения ключей (признак нехватки памяти)

**Recording rule для hit ratio Redis:**
```yaml
- record: job:redis_hit_ratio:5m
  expr: |
    rate(redis_keyspace_hits_total[5m])
    /
    (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))
```

**Алерт при падении hit ratio ниже 80%:**
```yaml
- alert: RedisLowHitRatio
  expr: job:redis_hit_ratio:5m < 0.8
  for: 10m
  labels:
    severity: warning
    event: 'Redis Low Hit Ratio |{{$value | humanize}}'
```

---

### 4. RabbitMQ (нативный Prometheus endpoint)

У RabbitMQ есть встроенный эндпоинт метрик — **отдельный экспортёр не нужен**. Включается через values чарта RabbitMQ:

```yaml
values:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      labels:
        release: kube-prom-stack
      interval: 30s
      relabelings:
        - targetLabel: job
          replacement: rabbitmq
```

**Ключевые метрики:**
- `rabbitmq_queue_messages` — сообщений в очереди (косвенный показатель consumer lag)
- `rabbitmq_queue_consumers` — активные консьюмеры (0 — очередь никто не читает)
- `rabbitmq_node_mem_alarm` — флаг memory alarm (1 = сработал)
- `rabbitmq_node_disk_free_alarm` — флаг disk alarm

---

### 5. Helm Exporter

Отслеживает версии и статусы Helm-релизов на кластерах. Развёртывается в `observability` (как служебный компонент).

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: helm-exporter
  namespace: observability
spec:
  interval: 15m
  chart:
    spec:
      chart: helm-exporter
      sourceRef:
        kind: HelmRepository
        name: sstarcher
  values:
    serviceMonitor:
      create: true
      labels:
        release: kube-prom-stack
```

**Что даёт:** по одному gauge на каждый Helm-релиз с метками `chart`, `version`, `namespace`, `status`.

**Алерт на зависшие/неуспешные релизы:**
```yaml
- alert: HelmReleaseFailed
  expr: helm_chart_info{status!="deployed"} > 0
  for: 15m
  labels:
    severity: warning
    event: 'Helm Release Failed |{{$labels.chart}}|{{$labels.namespace}}'
```

---

### HelmRepository источник (flux-system)

Все чарты берутся из репозитория `prometheus-community`, который должен быть зарегистрирован в `flux-system`:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: prometheus-community
  namespace: flux-system
spec:
  interval: 1h
  url: https://prometheus-community.github.io/helm-charts
```

Для `helm-exporter` используется отдельный репозиторий:
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: sstarcher
  namespace: flux-system
spec:
  interval: 1h
  url: https://sstarcher.github.io/helm-charts
```

## Как работает ServiceMonitor discovery

Оператор Prometheus следит за объектами `ServiceMonitor`, метки которых соответствуют `serviceMonitorSelector` в ресурсе `Prometheus`:

```yaml
# В values.yaml kube-prometheus-stack
prometheus:
  prometheusSpec:
    serviceMonitorSelector:
      matchLabels:
        release: kube-prom-stack
```

Если у `ServiceMonitor` нет этой метки, Prometheus не станет опрашивать таргет.

**Проверка:**
```bash
# Все ServiceMonitor с нужной меткой
kubectl get servicemonitor -A -l release=kube-prom-stack

# Убедиться, что targets видны в Prometheus
kubectl port-forward -n observability svc/kube-prom-stack-prometheus 9090:9090
# localhost:9090/targets — должны быть kafka, mongodb, redis, rabbitmq, helm-exporter
```

## Операции и команды

| Операция | Команда |
|---|---|
| Статус всех HelmRelease | `flux get helmreleases -A` |
| Статус конкретного релиза | `flux get helmrelease kafka-exporter -n kafka` |
| Принудительная синхронизация | `flux reconcile helmrelease kafka-exporter -n kafka --with-source` |
| Проверка манифестов перед применением | `helm template kafka-exporter prometheus-community/prometheus-kafka-exporter --namespace kafka -f values.yaml` |
| Проверка ServiceMonitor | `kubectl get servicemonitor -n kafka kafka-exporter -o yaml` |
| Логи экспортера | `kubectl logs -n kafka deployment/kafka-exporter` |
| Порт-форвард к экспортеру | `kubectl port-forward -n kafka svc/kafka-exporter 9308:9308` |

## Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| `ServiceMonitor` создан, но targets нет в Prometheus | Отсутствует метка `release: kube-prom-stack` | Добавить `additionalLabels.release: kube-prom-stack` в values |
| `ServiceMonitor` создан, но endpoints пустые | Несовпадение `selector.matchLabels` с labels Service | Проверить `kubectl get svc -n <ns> --show-labels` |
| Экспортер не подключается к сервису | Неверный DNS или порт | Проверить `kubectl exec -n <ns> deploy/<exporter> -- nc -zv <service> <port>` |
| `HelmRelease` в статусе `Ready=False` | Ошибка рендеринга чарта или недоступность репозитория | `flux logs --kind=helm-controller --level=error` |
| Метрики не обновляются | Неправильный `interval` в ServiceMonitor | Убедиться, что `interval` задан и соответствует SLA |
| Высокое потребление памяти экспортера | Слишком много метрик (например, тысячи consumer group в Kafka) | Настроить фильтры в чарте (`groupRegex`, `topicRegex`) или увеличить limits |

## Лучшие практики

1. **Co-location** — всегда развёртывайте экспортер в namespace рабочей нагрузки. Это упрощает DNS, сетевые политики и RBAC.
2. **Единая метка `release`** — используйте `release: kube-prom-stack` во всех ServiceMonitor для единообразия.
3. **Стабильный `job` label** — через `relabelings` задавайте читаемое имя (`kafka`, `mongodb`, `redis`, `rabbitmq`, `helm`). Это упрощает PromQL и дашборды.
4. **Resource limits** — всегда задавайте `requests` и `limits`. Экспортеры легко OOMKilled при всплесках кардинальности.
5. **Секреты через ExternalSecret** — никогда не коммитьте пароли в Git. Используйте `ExternalSecret` → `Secret` → `valuesFrom` в HelmRelease.
6. **Interval под метрики** — 15s для быстрых метрик (Redis), 30s для остальных. Не ставьте меньше 10s без необходимости.
7. **Chart version pinning** — фиксируйте версию чарта (`version: "3.0.1"`), не используйте `latest`.
8. **Recording rules** — выносите часто используемые выражения (hit ratio, lag) в `PrometheusRule` с `record:`.

## Дополнительная информация

### Ссылки на SSoT по каждому экспортеру

- **Kafka Exporter (подробно):** [Kafka для мониторинга](../../../../Kafka/kafka_for_monitoring.md) — systemd, Docker, Kubernetes, JMX Exporter, алерты.
- **MongoDB Exporter (подробно):** [MongoDB Monitoring](../../../../Databases/MongoDB/mongodb-monitoring.md) — Percona exporter, установка, метрики, алерты.
- **Redis Exporter (подробно):** [Redis Exporter](../../../../Prometheus/Exporters/redis_exporter.md) — standalone, Docker, Kubernetes sidecar, алерты.
- **RabbitMQ Monitoring (подробно):** [RabbitMQ Monitoring](../../../../rabbitmq/monitoring_and_alerting.md) — нативный плагин, recording rules, алерты, Loki интеграция.

### Каталог экспортеров

- **[Другие экспортеры](../../../../Prometheus/Exporters/other_exporters.md)** — полная таблица с портами, типами и ссылками на SSoT.

### Связанные темы

- **[Kube Prometheus Stack — обзор](../overview.md)** — архитектура стека, компоненты.
- **[Конфигурация встроенных экспортеров](../exporters_config.md)** — Node Exporter, kube-state-metrics, Blackbox Exporter.
- **[Flux — обзор и ключевые концепции](../../../../GitOps/flux.md)** — HelmRelease, Kustomization, bootstrap, troubleshooting.
- **[ServiceMonitor CRD](../../../operator/crd/servicemonitor.md)** — справочник параметров CRD.
- **[Prometheus Operator — Концепции](../../../operator/concepts.md)** — архитектура сбора данных, serviceMonitorSelector.