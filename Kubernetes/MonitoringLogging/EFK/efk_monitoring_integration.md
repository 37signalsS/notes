# Интеграция мониторинга EFK с Prometheus и Grafana

> **Актуальные версии (август 2026):** Prometheus **2.54+**, Grafana **11.x**,kube-prometheus-stack **65.x+**. Рекомендуется использовать kube-prometheus-stack для интеграции с EFK.

## Определения

**Мониторинг стека EFK** — процесс сбора, анализа и визуализации метрик производительности и состояния компонентов EFK (Elasticsearch, Fluent Bit, Kibana) для обеспечения надежности и производительности системы централизованного сбора логов.

**ServiceMonitor** — Custom Resource Definition (CRD) Prometheus Operator, описывающий, как Prometheus должен собирать метрики с конкретного сервиса. Определяет endpoint, port, interval и labels для автоматического обнаружения целей.

**PodMonitor** — CRD Prometheus Operator для сбора метрик напрямую с подов (без создания Service), что полезно для компонентов, не экспонирующих HTTP-эндпоинт через Service.

**Exporter** — компонент, преобразующий внутренние метрики приложения в формат Prometheus (text exposition format). Для Elasticsearch используется `elasticsearch_exporter`.

## Теоретический блок

### Архитектура мониторинга EFK

```
┌─────────────────────────────────────────────────────────────┐
│                    Мониторинг EFK                           │
├─────────────────────────────────────────────────────────────┤
│  Elasticsearch ──→ elasticsearch_exporter ──→ Prometheus    │
│  Fluent Bit ────→ metrics endpoint ────────→ Prometheus    │
│  Kibana ────────→ kibana_exporter ─────────→ Prometheus    │
│       │                                    │                │
│       │                                    ▼                │
│       │                              Grafana Dashboard      │
│       │                                    │                │
│       └────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### Ключевые метрики Elasticsearch

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `elasticsearch_cluster_health_status` | Состояние кластера (0=red, 1=yellow, 2=green) | != 2 |
| `elasticsearch_nodes_heap_used_percent` | Использование heap памяти нодами | > 75% |
| `elasticsearch_indices_docs_count` | Общее количество документов | > 10^9 |
| `elasticsearch_indices_indexing_rate_index_total` | Скорость индексации (документов/сек) | Зависит от SLA |
| `elasticsearch_indices_search_rate_query_total` | Скорость поиска (запросов/сек) | Зависит от SLA |
| `elasticsearch_indices_store_size_bytes` | Размер хранилища | > 80% диска |
| `elasticsearch_jvm_gc_collection_seconds` | Время сборки мусора | > 500ms |

### Ключевые метрики Fluent Bit

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `fluentbit_input_records_total` | Общее количество записанных записей | - |
| `fluentbit_input_bytes_total` | Общий объем записанных данных | - |
| `fluentbit_output_errors_total` | Количество ошибок при отправке | > 0 |
| `fluentbit_output_retries_total` | Количество повторных попыток | > 100/min |
| `fluentbit_process_cpu_seconds_total` | Использование CPU | > 0.5 ядра |
| `fluentbit_process_resident_memory_bytes` | Использование RAM | > 256MB |

### Ключевые метрики Kibana

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `kibana_status` | Статус Kibana (0=red, 1=yellow, 2=green) | != 2 |
| `kibana_http_server_requests_duration_seconds` | Время ответа HTTP-сервера | > 2s |
| `kibana_os_load15` | Средняя нагрузка за 15 минут | > 5.0 |

## Практический блок

### 1. Установка elasticsearch_exporter

#### Вариант 1: Через Helm (рекомендуется)

```yaml
# values-elasticsearch-exporter.yaml
replicaCount: 1

es:
  uri: "http://elasticsearch-master:9200"  # Внутренний адрес ES
  all: true  # Собирать метрики со всех нод
  cluster_settings: true  # Собирать настройки кластера
  indices: true  # Собирать метрики индексов
  indices_settings: true  # Собирать настройки индексов
  indices_docs: true  # Собирать количество документов
  indices_shards: true  # Собирать метрики шардов
  indices_stats: true  # Собирать статистику индексов
  thread_pool: true  # Собирать метрики thread pool
  snapshot: true  # Собирать метрики снапшотов

service:
  type: ClusterIP
  port: 9114
  labels: {}
  annotations: {}

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi

podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9114"
```

```bash
# Установка через Helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install elasticsearch-exporter prometheus-community/prometheus-elasticsearch-exporter \
  -n monitoring \
  -f values-elasticsearch-exporter.yaml \
  --create-namespace
```

#### Вариант 2: Ручной манифест

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: elasticsearch-exporter
  namespace: monitoring
  labels:
    app: elasticsearch-exporter
spec:
  replicas: 1
  selector:
    matchLabels:
      app: elasticsearch-exporter
  template:
    metadata:
      labels:
        app: elasticsearch-exporter
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9114"
    spec:
      containers:
      - name: elasticsearch-exporter
        image: quay.io/prometheuscommunity/elasticsearch-exporter:v1.7.0
        args:
        - "--es.uri=http://elasticsearch-master:9200"
        - "--es.all"
        - "--es.cluster_settings"
        - "--es.indices"
        - "--es.indices_settings"
        - "--es.indices_docs"
        - "--es.indices_shards"
        - "--es.indices_stats"
        - "--es.thread_pool"
        - "--es.snapshot"
        ports:
        - containerPort: 9114
          name: metrics
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
---
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch-exporter
  namespace: monitoring
  labels:
    app: elasticsearch-exporter
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9114"
spec:
  type: ClusterIP
  ports:
  - port: 9114
    targetPort: metrics
    name: metrics
  selector:
    app: elasticsearch-exporter
```

### 2. Настройка ServiceMonitor для Elasticsearch

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: elasticsearch-exporter
  namespace: monitoring
  labels:
    app: elasticsearch-exporter
    release: prometheus  # Метка для Prometheus Operator
spec:
  selector:
    matchLabels:
      app: elasticsearch-exporter
  namespaceSelector:
    matchNames:
    - monitoring
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

### 3. Настройка ServiceMonitor для Fluent Bit

Fluent Bit предоставляет метрики через HTTP-эндпоинт `/api/v1/metrics/prometheus`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app: fluent-bit
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: fluent-bit
  namespaceSelector:
    matchNames:
    - logging
  endpoints:
  - port: http-metrics
    interval: 30s
    path: /api/v1/metrics/prometheus
```

### 4. Настройка ServiceMonitor для Kibana

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kibana
  namespace: monitoring
  labels:
    app: kibana
    release: prometheus
spec:
  selector:
    matchLabels:
      app: kibana
  namespaceSelector:
    matchNames:
    - monitoring
  endpoints:
  - port: metrics
    interval: 30s
    path: /api/status
```

### 5. Настройка алертинга в PrometheusRule

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: elasticsearch-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
  - name: elasticsearch
    rules:
    # Алерт на unavailable shards
    - alert: ElasticsearchUnassignedShards
      expr: elasticsearch_cluster_health_unassigned_shards > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: есть неназначенные шарды"
        description: "Количество неназначенных шардов: {{ $value }}"
    
    # Алерт на red cluster status
    - alert: ElasticsearchClusterRed
      expr: elasticsearch_cluster_health_status{color="red"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Elasticsearch: кластер в состоянии RED"
        description: "Кластер Elasticsearch находится в критическом состоянии"
    
    # Алерт на высокое использование heap
    - alert: ElasticsearchHighHeapUsage
      expr: elasticsearch_jvm_memory_used_bytes{area="heap"} / elasticsearch_jvm_memory_max_bytes{area="heap"} > 0.75
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: высокое использование heap"
        description: "Использование heap памяти: {{ $value | humanizePercentage }}"
    
    # Алерт на недостаточно дискового пространства
    - alert: ElasticsearchDiskSpaceLow
      expr: elasticsearch_filesystem_data_available_bytes / elasticsearch_filesystem_data_size_bytes < 0.2
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: мало дискового пространства"
        description: "Доступно дискового пространства: {{ $value | humanizePercentage }}"
    
    # Алерт на ошибки индексации
    - alert: ElasticsearchHighIndexingErrors
      expr: rate(elasticsearch_indices_indexing_errors_total[5m]) > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: ошибки индексации"
        description: "Скорость ошибок индексации: {{ $value }}/сек"

  - name: fluent-bit
    rules:
    # Алерт на ошибки отправки
    - alert: FluentBitOutputErrors
      expr: rate(fluentbit_output_errors_total[5m]) > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Fluent Bit: ошибки отправки логов"
        description: "Скорость ошибок отправки: {{ $value }}/сек"
    
    # Алерт на высокое использование памяти
    - alert: FluentBitHighMemoryUsage
      expr: fluentbit_process_resident_memory_bytes > 256 * 1024 * 1024
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Fluent Bit: высокое использование памяти"
        description: "Использование памяти: {{ $value | humanize1024 }}B"
```

### 6. Создание дашбордов в Grafana

#### Дашборд Elasticsearch

Рекомендуемые панели:

1. **Cluster Health**: gauge для `elasticsearch_cluster_health_status`
2. **Nodes**: таблица с нодами и их состоянием
3. **Heap Usage**: time series для `elasticsearch_jvm_memory_used_bytes`
4. **Indexing Rate**: time series для `elasticsearch_indices_indexing_rate_index_total`
5. **Search Rate**: time series для `elasticsearch_indices_search_rate_query_total`
6. **Document Count**: stat для `elasticsearch_indices_docs_count`
7. **Store Size**: stat для `elasticsearch_indices_store_size_bytes`
8. **GC Time**: time series для `elasticsearch_jvm_gc_collection_seconds_sum`

#### Дашборд Fluent Bit

Рекомендуемые панели:

1. **Records In**: time series для `fluentbit_input_records_total`
2. **Bytes In**: time series для `fluentbit_input_bytes_total`
3. **Output Errors**: stat для `fluentbit_output_errors_total`
4. **Retries**: time series для `fluentbit_output_retries_total`
5. **CPU Usage**: time series для `fluentbit_process_cpu_seconds_total`
6. **Memory Usage**: time series для `fluentbit_process_resident_memory_bytes`

### 7. Экспорт метрик из Kibana

Kibana предоставляет метрики через `/api/status`. Для их сбора можно использовать `kibana_exporter`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kibana-exporter
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kibana-exporter
  template:
    metadata:
      labels:
        app: kibana-exporter
    spec:
      containers:
      - name: kibana-exporter
        image: wavestone/kibana-exporter:0.2.0
        args:
        - "--kibana.url=http://kibana:5601"
        - "--kibana.username=elastic"
        - "--kibana.password=${ELASTIC_PASSWORD}"
        ports:
        - containerPort: 9072
          name: metrics
        env:
        - name: ELASTIC_PASSWORD
          valueFrom:
            secretKeyRef:
              name: elasticsearch-credentials
              key: password
```

## Дополнительная информация

### Полезные ссылки

- [Prometheus Operator Documentation](https://prometheus-operator.dev/docs/)
- [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [elasticsearch_exporter](https://github.com/prometheus-community/elasticsearch_exporter)
- [Grafana Dashboards for Elasticsearch](https://grafana.com/grafana/dashboards/?search=elasticsearch)
- [Grafana Dashboards for Fluent Bit](https://grafana.com/grafana/dashboards/?search=fluent+bit)

### Рекомендуемые дашборды Grafana

- **Elasticsearch Cluster**: [Dashboard ID 14194](https://grafana.com/grafana/dashboards/14194)
- **Fluent Bit**: [Dashboard ID 13639](https://grafana.com/grafana/dashboards/13639)
- **Kibana**: [Dashboard ID 13581](https://grafana.com/grafana/dashboards/13581)

### Частые проблемы

1. **ServiceMonitor не находит Service**: Убедитесь, что labels в ServiceMonitor совпадают с labels в Service.
2. **Prometheus не скрейпит метрики**: Проверьте, что Prometheus Operator имеет права доступа к namespace.
3. **elasticsearch_exporter не может подключиться к ES**: Проверьте URL и учетные данные.
4. **Kibana не экспортирует метрики**: Убедитесь, что включена статистика использования в настройках Kibana.