# Масштабирование и производительность Fluent Bit в Kubernetes

## Определения

**Horizontal Pod Autoscaler (HPA)** — механизм автоматического масштабирования количества подов на основе метрик (CPU, memory, custom metrics).

**Vertical Pod Autoscaler (VPA)** — механизм автоматического масштабирования ресурсов (CPU, memory) пода на основе истории использования.

**Buffer** — механизм буферизации данных в Fluent Bit перед отправкой. Обеспечивает надежность доставки при временной недоступности.destination.

**Storage** — локальное хранилище Fluent Bit для персистентных буферов. Обеспечивает выживание данных при перезапуске пода.

**Queue** — очередь задач для обработки. В контексте Fluent Bit это очередь записей для отправки в destination.

**Backpressure** — состояние, при котором данные поступают быстрее, чем обрабатываются. Fluent Bit применяет обратное давление для предотвращения переполнения памяти.

**Chunk** — базовая единица данных в Fluent Bit. Записи группируются в чанки для эффективной обработки и отправки.

**Pipeline** — конвейер обработки данных: Input → Filter → Output.

## Теоретический блок

### Архитектура масштабирования Fluent Bit

```
┌─────────────────────────────────────────────────────────────┐
│              Масштабирование Fluent Bit                      │
├─────────────────────────────────────────────────────────────┤
│  DaemonSet (1 под на узел)                                  │
│  └─ Автоматическое покрытие всех узлов                      │
│  └─ Чтение логов с локального узла                          │
│  └─ Фильтрация и маршрутизация                              │
│  └─ Отправка в Elasticsearch                                │
│                                                             │
│  Horizontal Pod Autoscaler (для дополнительных подов)        │
│  └─ Масштабирование на основе custom metrics                │
│  └─ Дополнительные поды для обработки логов                  │
│                                                             │
│  Оптимизация производительности                              │
│  └─ Буферизация и Storage                                   │
│  └─ Многопоточная обработка                                  │
│  └─ Оптимизация фильтров                                    │
└─────────────────────────────────────────────────────────────┘
```

### Ключевые метрики для масштабирования

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `fluentbit_input_records_total` | Количество записей в секунду | Зависит от SLA |
| `fluentbit_output_errors_total` | Ошибки отправки | > 0 |
| `fluentbit_output_retries_total` | Повторные попытки | > 100/min |
| `fluentbit_process_cpu_seconds_total` | Использование CPU | > 0.5 ядра |
| `fluentbit_process_resident_memory_bytes` | Использование RAM | > 256MB |
| `fluentbit_storage_chunks_total` | Количество чанков в storage | > 1000 |

### Стратегии масштабирования

| Стратегия | Описание | Использование |
| :--- | :--- | :--- |
| **DaemonSet** | 1 под на узел | Основной способ, покрытие всех узлов |
| **Deployment + HPA** | Дополнительные поды | Высокая нагрузка, специфичные обработки |
| **Оптимизация конфигурации** | Улучшение производительности | Все сценарии |
| **Вертикальное масштабирование** | Увеличение ресурсов пода | Ограничение по узлам |

## Практический блок

### 1. Оптимизированная конфигурация Fluent Bit

```yaml
# fluent-bit-optimized.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: logging
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush           5
        Log_Level       info
        Daemon          Off
        Parsers_File    parsers.conf
        HTTP_Server     On
        HTTP_Listen     0.0.0.0
        HTTP_Port       2020
        Metrics_On      On
        storage.path    /var/fluent-bit/state/
        storage.sync    normal
        storage.checksum off
        storage.max_chunks_up 128
        storage.backlog.mem_limit 10M
       cheduler.base   1
        scheduler.cap   200
        scheduler.max_threads 5
        queue.max_chunks_up 256
    
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        DB                /var/fluent-bit/state/flb_kube.db
        DB.Sync           Normal
        Mem_Buf_Limit     50MB
        Skip_Long_Lines   On
        Refresh_Interval  10
        Read_from_Head    false
        storage.type      filesystem
        storage.pause_on_chunk_overlimit On
        storage.max_disk_chunk_up_size 2M
    
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix     kube.var.log.containers.
        Merge_Log           On
        Merge_Log_Key       log_processed
        K8S-Logging.Parser  On
        K8S-Logging.Exclude Off
        Labels              On
        Annotations         Off
    
    [FILTER]
        Name          modify
        Match         *
        Rename        log message
        Rename        stream log_stream
        Rename        time @timestamp
    
    [OUTPUT]
        Name            es
        Match           *
        Host            ${FLUENT_ELASTICSEARCH_HOST}
        Port            ${FLUENT_ELASTICSEARCH_PORT}
        Logstash_Format On
        Logstash_Prefix fluent-bit
        Logstash_DateFormat %Y.%m.%d
        TLS             On
        TLS.verify      Off
        HTTP_User       ${FLUENT_ELASTICSEARCH_USER}
        HTTP_Passwd     ${FLUENT_ELASTICSEARCH_PASSWORD}
        Retry_Limit     False
        Replace_Dots    On
        Suppress_Type_Name On
        Trace_Error     On
        Workers         2
        storage.type    filesystem
        Chunk_Limit_Size 5M
        Total_Limit_Size 100M
        Upstream        upstream.conf
```

### 2. Upstream для балансировки нагрузки

```yaml
# upstream.conf
[UPSTREAM]
    Name            es_cluster
    # Несколько Elasticsearch нод для балансировки
    Node            es-node1
        Host        elasticsearch-0.elasticsearch
        Port        9200
    Node            es-node2
        Host        elasticsearch-1.elasticsearch
        Port        9200
    Node            es-node3
        Host        elasticsearch-2.elasticsearch
        Port        9200
```

### 3. Horizontal Pod Autoscaler для Fluent Bit

```yaml
# fluent-bit-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fluent-bit
  namespace: logging
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: DaemonSet
    name: fluent-bit
  minReplicas: 1
  maxReplicas: 10
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
  - type: Pods
    pods:
      metric:
        name: fluentbit_input_records_total
      target:
        type: AverageValue
        averageValue: "1000"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
```

### 4. Pod Disruption Budget

```yaml
# fluent-bit-pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: fluent-bit
  namespace: logging
spec:
  minAvailable: 50%  # Как минимум 50% подов должны быть доступны
  selector:
    matchLabels:
      app: fluent-bit
```

### 5. Мониторинг производительности

```yaml
# fluent-bit-monitoring.yaml
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
      app: fluent-bit
  namespaceSelector:
    matchNames:
    - logging
  endpoints:
  - port: http-metrics
    interval: 10s
    path: /api/v1/metrics/prometheus
---
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: fluent-bit-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
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
    
    # Алерт на backpressure
    - alert: FluentBitBackpressure
      expr: fluentbit_storage_chunks_up > 100
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Fluent Bit: обнаружена обратное давление"
        description: "Количество чанков в storage: {{ $value }}"
    
    # Алерт на повторные попытки
    - alert: FluentBitHighRetries
      expr: rate(fluentbit_output_retries_total[5m]) > 10
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Fluent Bit: высокое количество повторных попыток"
        description: "Скорость повторных попыток: {{ $value }}/сек"
```

### 6. Оптимизация для высокой нагрузки

```yaml
# fluent-bit-high-throughput.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config-high-throughput
  namespace: logging
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush           1
        Log_Level       warning
        Daemon          Off
        Parsers_File    parsers.conf
        HTTP_Server     On
        HTTP_Listen     0.0.0.0
        HTTP_Port       2020
        Metrics_On      On
        storage.path    /var/fluent-bit/state/
        storage.sync    full
        storage.max_chunks_up 256
        storage.backlog.mem_limit 50M
        scheduler.base   1
        scheduler.cap   500
        scheduler.max_threads 10
       queue.max_chunks_up 512
    
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        DB                /var/fluent-bit/state/flb_kube.db
        DB.Sync           Full
        Mem_Buf_Limit     100MB
        Skip_Long_Lines   On
        Refresh_Interval  5
        Read_from_Head    false
        storage.type      filesystem
        storage.pause_on_chunk_overlimit On
        storage.max_disk_chunk_up_size 5M
        storage.delete_irrecoverable_chunks On
    
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix     kube.var.log.containers.
        Merge_Log           Off
        K8S-Logging.Parser  Off
        K8S-Logging.Exclude Off
        Labels              Off
        Annotations         Off
    
    [OUTPUT]
        Name            es
        Match           *
        Host            ${FLUENT_ELASTICSEARCH_HOST}
        Port            ${FLUENT_ELASTICSEARCH_PORT}
        Logstash_Format On
        Logstash_Prefix fluent-bit
        Logstash_DateFormat %Y.%m.%d
        TLS             On
        TLS.verify      Off
        HTTP_User       ${FLUENT_ELASTICSEARCH_USER}
        HTTP_Passwd     ${FLUENT_ELASTICSEARCH_PASSWORD}
        Retry_Limit     False
        Replace_Dots    On
        Suppress_Type_Name On
        Trace_Error     On
        Workers         4
        storage.type    filesystem
        Chunk_Limit_Size 10M
        Total_Limit_Size 500M
        Upstream        upstream.conf
```

## Дополнительная информация

### Проверка производительности

```bash
# Просмотр метрик Fluent Bit
curl -s http://fluent-bit:2020/api/v1/metrics/prometheus | grep fluentbit

# Просмотр состояния storage
curl -s http://fluent-bit:2020/api/v1/storage | jq .

# Просмотр состояния queue
curl -s http://fluent-bit:2020/api/v1/flushes | jq .

# Просмотр логов Fluent Bit
kubectl logs -n logging -l app=fluent-bit --tail=100

# Просмотр использования ресурсов
kubectl top pods -n logging -l app=fluent-bit
```

### Частые проблемы

1. **Memory leak**: Проверьте Mem_Buf_Limit и storage.backlog.mem_limit.
2. **Backpressure**: Увеличьте buffer size и количество workers.
3. **High CPU**: Оптимизируйте фильтры и уменьшите количество processors.
4. **Data loss**: Убедитесь, что storage.type=filesystem и buffer足够大.

### Рекомендации

1. Используйте DaemonSet для основного покрытия узлов.
2. Оптимизируйте фильтры для уменьшения нагрузки.
3. Настройте buffer и storage для надежности доставки.
4. Мониторьте ключевые метрики и настраивайте алерты.
5. Регулярно обновляйте Fluent Bit до последней версии.
6. Используйте upstream для балансировки нагрузки.

### Полезные ссылки

- [Fluent Bit Documentation](https://docs.fluentbit.io/)
- [Fluent Bit Performance Tuning](https://docs.fluentbit.io/manual/administration/performance-tuning)
- [Fluent Bit Kubernetes Integration](https://docs.fluentbit.io/manual/pipeline/kubernetes)
- [Fluent Bit Monitoring](https://docs.fluentbit.io/manual/administration/monitoring)
- [Elasticsearch Output](https://docs.fluentbit.io/manual/pipeline/outputs/elasticsearch)