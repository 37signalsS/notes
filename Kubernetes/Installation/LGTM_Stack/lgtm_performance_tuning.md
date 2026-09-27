# Оптимизация производительности стека LGTM

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**
> - **[Оптимизация производительности](./lgtm_performance_tuning.md)** (текущий)

---

## Определения

**Retention Policy (политика удержания)** — правила определяющие, как долго данные хранятся в системе и когда они удаляются. Критически важна для управления стоимостью хранения.

**Compaction (укомплектовация)** — процесс объединения мелких файлов данных в более крупные для улучшения производительности чтения и экономии места.

**Cardinality (кардинальность)** — количество уникальных значений метки. Высокая кардинальность (миллионы уникальных значений) приводит к высокому потреблению памяти и медленным запросам.

**Sampling (сэмплирование)** — механизм сохранения не всех данных, а их выборки для снижения объема хранения при сохранении репрезентативности.

---

## Основные концепции

### Архитектура оптимизации

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                    Performance Optimization Layers                       │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 1: Сбор данных (OTel Collector)           │  │
│  │  • Sampling (head-based / tail-based)                             │  │
│  │  • Batch processing                                               │  │
│  │  • Memory limiter                                                 │  │
│  │  • Фильтрация по атрибутам                                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 2: Хранение (Prometheus/Loki/Tempo)       │  │
│  │  • Retention policies                                             │  │
│  │  • Compaction                                                     │  │
│  │  • Downsampling                                                   │  │
│  │  • Шифрование и сжатие                                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 3: Запросы (Grafana)                      │  │
│  │  • Кэширование запросов                                           │  │
│  │  • Оптимизация PromQL/LogQL/TraceQL                               │  │
│  │  • Параллельные запросы                                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 4: Инфраструктура                         │  │
│  │  • Resource requests/limits                                       │  │
│  │  • Horizontal Pod Autoscaler                                      │  │
│  │  • Storage class optimization                                     │  │
│  │  • Network optimization                                           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Ключевые метрики производительности

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Ingestion Rate** | Скорость приема данных | Стабильная, без задержек |
| **Query Latency** | Время выполнения запросов | P99 < 5s для Prometheus, < 10s для Loki |
| **Storage Usage** | Объем используемого хранилища | < 80% от общего объема |
| **Memory Usage** | Использование памяти | < 80% от лимита |
| **CPU Usage** | Использование CPU | < 70% от лимита |
| **Error Rate** | Частота ошибок | < 0.1% |

---

## Практические сценарии

### Сценарий 1: Оптимизация OTel Collector

**Цель:** Настройка конвейера обработки для максимальной производительности.

#### Шаг 1: Оптимизация batch processor

```yaml
processors:
  batch:
    timeout: 5s
    send_batch_size: 8192
    send_batch_max_size: 16384
```

#### Шаг 2: Настройка memory limiter

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 25
```

#### Шаг 3: Включение tail-based sampling для трассировок

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow
        type: latency
        latency: {threshold_ms: 1000}
      - name: probabilistic
        type: probabilistic
        probabilistic: {sampling_percentage: 10}
```

#### Шаг 4: Фильтрация ненужных атрибутов

```yaml
processors:
  attributes:
    actions:
      - key: http.request.body
        action: delete
      - key: http.response.body
        action: delete
      - key: db.statement
        action: delete
```

---

### Сценарий 2: Оптимизация Prometheus

**Цель:** Настройка retention, compaction и ресурсов.

> **Примечание:** Детали конфигурации Prometheus описаны в:
> - [Prometheus: Конфигурация](../../../Prometheus/configuration.md)
> - [Kube-Prometheus-Stack: Обзор](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)

#### Шаг 1: Настройка retention policy

```yaml
prometheus:
  prometheusSpec:
    retention: 15d
    retentionSize: "50GB"
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: fast-ssd
          resources:
            requests:
              storage: 100Gi
```

#### Шаг 2: Оптимизация compaction

```yaml
prometheus:
  prometheusSpec:
    additionalArgs:
      - --storage.tsdb.compaction间隔=30m
      - --storage.tsdb.wal-compression
```

#### Шаг 3: Настройка resource requests/limits

```yaml
prometheus:
  prometheusSpec:
    resources:
      limits:
        cpu: 2000m
        memory: 4Gi
      requests:
        cpu: 500m
        memory: 2Gi
```

#### Шаг 4: Оптимизация scrape interval

```yaml
prometheus:
  prometheusSpec:
    scrapeInterval: 30s
    evaluationInterval: 30s
```

---

### Сценарий 3: Оптимизация Loki

**Цель:** Настройка chunk, index и retention для Loki.

> **Примечание:** Детали архитектуры Loki описаны в:
> - [Loki: Обзор](../../../Loki/loki_overview.md)

#### Шаг 1: Настройка chunk store

```yaml
loki:
  storageConfig:
    chunk_store_config:
      max_look_back_period: 720h  # 30 дней
      chunk_cache_config:
        embedded_cache:
          enabled: true
          max_size_mb: 1024
```

#### Шаг 2: Оптимизация индекса

```yaml
loki:
  storageConfig:
    tsdb_shipper:
      active_index_directory: /loki/tsdb-index
      cache_location: /loki/tsdb-cache
```

#### Шаг 3: Настройка retention

```yaml
loki:
  limits_config:
    retention_period: 720h  # 30 дней
    max_query_length: 721h
    ingestion_rate_mb: 16
    ingestion_burst_size_mb: 32
```

#### Шаг 4: Оптимизация компонентов

```yaml
loki:
  read:
    replicas: 3
    resources:
      limits:
        cpu: 1000m
        memory: 2Gi
      requests:
        cpu: 250m
        memory: 512Mi
  write:
    replicas: 3
    resources:
      limits:
        cpu: 2000m
        memory: 4Gi
      requests:
        cpu: 500m
        memory: 1Gi
```

---

### Сценарий 4: Оптимизация Tempo

**Цель:** Настройка storage и compaction для Tempo.

> **Примечание:** Детали архитектуры Tempo описаны в:
> - [Tempo: Индекс](../../../Tempo/index.md)
> - [Tempo: Архитектура](../../../Tempo/architecture_operations.md)

#### Шаг 1: Настройка storage backend

```yaml
tempo:
  storage:
    trace:
      backend: s3
      s3:
        endpoint: s3.us-east-1.amazonaws.com
        region: us-east-1
        bucket: tempo-traces
      local:
        path: /var/tempo/traces
```

#### Шаг 2: Оптимизация compaction

```yaml
tempo:
  compactor:
    compaction:
      block_retention: 720h  # 30 дней
      compacted_block_retention: 24h
```

#### Шаг 3: Настройка resource requests/limits

```yaml
tempo:
  resources:
    limits:
      cpu: 1000m
      memory: 2Gi
    requests:
      cpu: 250m
      memory: 512Mi
```

#### Шаг 4: Оптимизация querier

```yaml
tempo:
  querier:
    max_concurrent: 5
    search:
      max_duration: 1h
      default_result_limit: 20
```

---

### Сценарий 5: Оптимизация Grafana

**Цель:** Настройка кэширования и рендеринга.

> **Примечание:** Детали производительности Grafana описаны в:
> - [Grafana: Производительность](../../../Grafana/grafana_performance_tuning.md)

#### Шаг 1: Настройка кэширования

```ini
[cache]
type = redis
connstring = redis://redis:6379/0
default_cache_ttl = 1h
```

#### Шаг 2: Оптимизация рендеринга

```ini
[rendering]
renderer_image_rendering = default
concurrent_render_request_limit = 15
```

#### Шаг 3: Настройка базы данных

```ini
[database]
type = postgres
host = postgres:5432
name = grafana
user = grafana
max_open_conn = 100
max_idle_conn = 10
conn_max_lifetime = 14400
```

---

### Сценарий 6: Настройка Horizontal Pod Autoscaler

**Цель:** Автоматическое масштабирование компонентов стека.

#### Шаг 1: HPA для Prometheus

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: prometheus-hpa
  namespace: monitoring
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: prometheus-prometheus-kube-prometheus-prometheus
  minReplicas: 2
  maxReplicas: 5
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
```

#### Шаг 2: HPA для Loki

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: loki-read-hpa
  namespace: loki
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: loki-read
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## Дополнительная информация

### Чек-лист оптимизации

| Компонент | Параметр | Рекомендация |
| :--- | :--- | :--- |
| **OTel Collector** | Batch size | 8192-16384 |
| **OTel Collector** | Memory limit | 80% от доступной памяти |
| **Prometheus** | Retention | 15-30 дней |
| **Prometheus** | Scrape interval | 30s |
| **Loki** | Ingestion rate | 16 MB/s на реплику |
| **Loki** | Retention | 30 дней |
| **Tempo** | Block retention | 30 дней |
| **Grafana** | Cache | Redis с TTL 1h |

### Связанные материалы

- **[Prometheus: Конфигурация](../../../Prometheus/configuration.md)** — детали настройки
- **[Loki: Обзор](../../../Loki/loki_overview.md)** — архитектура и оптимизация
- **[Tempo: Архитектура](../../../Tempo/architecture_operations.md)** — детали хранения
- **[Grafana: Производительность](../../../Grafana/grafana_performance_tuning.md)** — оптимизация Grafana

---

**Навигация по руководству:**

- **[CI/CD интеграция](./lgtm_cicd_gitops_integration.md)** (назад)
- **[Мониторинг стека](./lgtm_monitoring_self_monitoring.md)** (вперед)
