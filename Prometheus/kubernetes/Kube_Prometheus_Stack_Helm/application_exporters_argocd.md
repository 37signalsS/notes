# Application Exporters — Argo CD Application Pattern

**Актуально для:** kube-prometheus-stack 88.x+, Argo CD v3.5+, Prometheus Operator 0.80.x

## Определения

**Application Exporter (экспортер приложения)** — отдельный компонент для сбора метрик уровня приложения (consumer lag в Kafka, hit ratio в Redis, частота операций в MongoDB, глубина очередей в RabbitMQ), который не входит в базовый состав kube-prometheus-stack.

**Application (Argo CD)** — CRD `argoproj.io/v1alpha1`, управляемый контроллером `argocd-application-controller`. Осуществляет декларативную установку, обновление и откат Helm-чартов через GitOps с поддержкой drift detection и self-healing.

**ServiceMonitor** — CRD Prometheus Operator, описывающий цель скрейпинга. Оператор Prometheus находит ServiceMonitor по метке `release: kube-prom-stack` (настраивается в `serviceMonitorSelector` ресурса `Prometheus`).

**Паттерн co-location** — развёртывание экспортера в том же namespace, что и рабочая нагрузка (workload). Это позволяет использовать короткие имена сервисов (например, `kafka.kafka.svc.cluster.local` → `kafka`) и избегает cross-namespace сетевых политик.

**AppProject (Argo CD)** — CRD `argoproj.io/v1alpha1`, определяющий логическую границу безопасности: разрешенные репозитории, целевые кластеры и типы ресурсов. Применяется для изоляции экспортеров по namespace.

## Архитектура

```
Git Repository (Argo CD source)
    │
    ▼
Application (per exporter, in workload namespace)
    │
    ├── Chart: prometheus-community/<exporter>
    ├── Values:
    │     ├── serviceMonitor.enabled: true
    │     ├── serviceMonitor.additionalLabels.release: kube-prom-stack
    │     ├── serviceMonitor.relabelings: job=<stable-name>
    │     └── resources.requests/limits
    │
    ▼
argocd-application-controller → K8s API → Pod (Exporter) + Service + ServiceMonitor
                                                        │
                                                        ▼
                                      Prometheus Operator (serviceMonitorSelector: release=kube-prom-stack)
                                                        │
                                                        ▼
                                                Prometheus Server (scrape)
```

**Поток метрик:**
1. Argo CD `argocd-application-controller` применяет `Application` в namespace рабочей нагрузки.
2. `argocd-repo-server` рендерит Helm-чарт, создаёт Deployment (экспортер), Service, ServiceMonitor.
3. ServiceMonitor получает метку `release: kube-prom-stack`.
4. Prometheus Operator (в namespace `observability`) видит ServiceMonitor через селектор.
5. Operator генерирует scrape-конфиг и передаёт Prometheus Server.
6. Prometheus опрашивает экспортер по Pull-модели.

## Почему в namespace рабочей нагрузки?

| Аргумент | Объяснение |
|---|---|
| **Сетевой доступ** | Экспортёру нужен доступ к сервису (Kafka, MongoDB, Redis, RabbitMQ). В одном namespace работает короткое DNS-имя (`kafka.kafka.svc.cluster.local` → `kafka`). |
| **RBAC изоляция** | Через `AppProject` с ограничением `destinations.namespace` на целевой namespace. |
| **Жизненный цикл** | Экспортер обновляется/удаляется вместе с рабочей нагрузкой через `syncPolicy pruning` и удаление Application. |
| **Секреты** | Пароли (ExternalSecret из Vault) хранятся в том же namespace, где они используются. |

## Практические сценарии

### Единый паттерн Application

Все экспортеры следуют одной структуре с использованием Multiple Sources для разделения чарта из внешнего Helm-репозитория и values из Git:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <exporter-name>
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: monitoring

  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: prometheus-<exporter>
    targetRevision: "<chart-version>"
    helm:
      releaseName: <exporter-name>
      valueFiles:
        - $values/values/exporters/<exporter-name>-values.yaml    # values из Git
      values: |
        serviceMonitor:
          enabled: true
          additionalLabels:
            release: kube-prom-stack                             # Ключевая метка для discovery

  destination:
    server: https://kubernetes.default.svc
    namespace: <workload-namespace>                              # НЕ observability

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - SkipDryRunOnMissingResource=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

Для каждого экспортера создаётся отдельный `Application` в namespace `argocd`, но ресурсы разворачиваются в namespace рабочей нагрузки через `destination.namespace`.

---

### 1. Kafka Exporter

**Чарт:** `prometheus-kafka-exporter` v3.0.1 (prometheus-community)
**Что собирает:** consumer lag (по партициям и группам), количество партиций топика, статус брокеров, недореплицированные партиции, частоту сообщений.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kafka-exporter
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: monitoring

  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: prometheus-kafka-exporter
    targetRevision: "3.0.1"
    helm:
      releaseName: kafka-exporter
      valueFiles:
        - $values/values/exporters/kafka-exporter-values.yaml
      values: |
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

  destination:
    server: https://kubernetes.default.svc
    namespace: kafka

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
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
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mongodb-exporter
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: monitoring

  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: prometheus-mongodb-exporter
    targetRevision: "3.8.0"
    helm:
      releaseName: mongodb-exporter
      valueFiles:
        - $values/values/exporters/mongodb-exporter-values.yaml
      values: |
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

  destination:
    server: https://kubernetes.default.svc
    namespace: db

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
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
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: redis-exporter
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: monitoring

  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: prometheus-redis-exporter
    targetRevision: "6.9.0"
    helm:
      releaseName: redis-exporter
      valueFiles:
        - $values/values/exporters/redis-exporter-values.yaml
      values: |
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

  destination:
    server: https://kubernetes.default.svc
    namespace: db

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
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
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: helm-exporter
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: monitoring

  source:
    repoURL: https://sstarcher.github.io/helm-charts
    chart: helm-exporter
    targetRevision: ""
    helm:
      releaseName: helm-exporter
      values: |
        serviceMonitor:
          create: true
          labels:
            release: kube-prom-stack

  destination:
    server: https://kubernetes.default.svc
    namespace: observability

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
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
# 1. Статус всех Application (экспортеры)
argocd app list --project monitoring

# 2. Статус конкретного экспортера
argocd app get kafka-exporter
# → Name:               kafka-exporter
# → Project:            monitoring
# → Server:             https://kubernetes.default.svc
# → Namespace:          kafka
# → Sync Status:        Synced to 3.0.1
# → Health Status:      Healthy

# 3. Принудительная синхронизация
argocd app sync kafka-exporter --refresh --prune

# 4. Все ServiceMonitor с нужной меткой
kubectl get servicemonitor -A -l release=kube-prom-stack

# 5. Убедиться, что targets видны в Prometheus
kubectl port-forward -n observability svc/kube-prom-stack-prometheus 9090:9090
# localhost:9090/targets — должны быть kafka, mongodb, redis, rabbitmq, helm-exporter
```

## Операции и команды

| Операция | Команда |
|---|---|
| Статус всех Application (экспортеры) | `argocd app list --project monitoring` |
| Статус конкретного экспортера | `argocd app get <exporter-name>` |
| Принудительная синхронизация | `argocd app sync <exporter-name> --refresh --prune` |
| Проверка манифестов перед применением | `argocd app manifest <exporter-name> \| head -50` |
| Проверка ServiceMonitor | `kubectl get servicemonitor -n <ns> <name> -o yaml` |
| Логи экспортера | `kubectl logs -n <ns> deployment/<exporter-name>` |
| Порт-форвард к экспортеру | `kubectl port-forward -n <ns> svc/<exporter-name> <port>:<port>` |

## Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| `ServiceMonitor` создан, но targets нет в Prometheus | Отсутствует метка `release: kube-prom-stack` | Добавить `additionalLabels.release: kube-prom-stack` в values |
| `ServiceMonitor` создан, но endpoints пустые | Несоответствие `selector.matchLabels` с labels Service | Проверить `kubectl get svc -n <ns> --show-labels` |
| Экспортер не подключается к сервису | Неверный DNS или порт | Проверить `kubectl exec -n <ns> deploy/<exporter> -- nc -zv <service> <port>` |
| Application `Health: Degraded` | Ошибка рендеринга чарта или недоступность репозитория | `argocd app diff <exporter-name>` и `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server` |
| `field is immutable` при синке | Конфликт метки `app.kubernetes.io/instance` между именем Application и `releaseName` | Переключить `application.resourceTrackingMethod: annotation` в `argocd-cm` |
| Метрики не обновляются | Неправильный `interval` в ServiceMonitor | Убедиться, что `interval` задан и соответствует SLA |
| Высокое потребление памяти экспортера | Слишком много метрик (например, тысячи consumer group в Kafka) | Настроить фильтры в чарте (`groupRegex`, `topicRegex`) или увеличить limits |

## Лучшие практики

1. **Co-location** — всегда разворачивайте экспортер в namespace рабочей нагрузки. Это упрощает DNS, сетевые политики и RBAC.
2. **Единая метка `release`** — используйте `release: kube-prom-stack` во всех ServiceMonitor для единообразия.
3. **Стабильный `job` label** — через `relabelings` задавайте читаемое имя (`kafka`, `mongodb`, `redis`, `rabbitmq`, `helm`). Это упрощает PromQL и дашборды.
4. **Resource limits** — всегда задавайте `requests` и `limits`. Экспортеры легко OOMKilled при всплесках кардинальности.
5. **Секреты через ExternalSecret** — никогда не коммитьте пароли в Git. Используйте `ExternalSecret` → `Secret` → values в Application.
6. **Interval под метрики** — 15s для быстрых метрик (Redis), 30s для остальных. Не ставьте меньше 10s без необходимости.
7. **Chart version Pinning** — фиксируйте версию чарта (`version: "3.0.1"`), не используйте `latest`.
8. **Recording rules** — выносите часто используемые выражения (hit ratio, lag) в `PrometheusRule` с `record:`.
9. **Multiple Sources** — используйте `$values` alias для разделения Helm-репозитория и конфигураций из Git. См. [Argo CD: Интеграция с Helm](../../GitOps/ArgoCD/helm_integration.md#сценарий-2-production-multi-source-паттерн).
10. **SkipDryRunOnMissingResource** — всегда включайте для экспортеров, создающих CRD через Helm.

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
- **[Argo CD — обзор](../../../../GitOps/ArgoCD/argocd_overview.md)** — Application, AppProject, архитектура контроллеров.
- **[ServiceMonitor CRD](../../../operator/crd/servicemonitor.md)** — справочник параметров CRD.
- **[Prometheus Operator — Концепции](../../../operator/concepts.md)** — архитектура сбора данных, serviceMonitorSelector.

---

> **Примечание:** Паттерн был конвертирован из Flux CD в Argo CD. Соответствие концепций:
> - Flux `HelmRelease` → Argo CD `Application` с `helm` source
> - Flux `HelmRepository` → Argo CD `repoURL` в `Application` (для публичных репо) или `Secret` с меткой `repository`
> - Flux `spec.serviceAccountName` → Argo CD `AppProject` с ограничением `destinations.namespace`
> - Flux `dependsOn` между Kustomization → Argo CD `prune: true` + удаление Application
> - Flux `flux get helmrelease` → `argocd app get <app>`
> - Flux `flux reconcile helmrelease` → `argocd app sync <app> --refresh --prune`