# Multi-cluster логирование с EFK в Kubernetes

## Определения

**Multi-cluster** — архитектура, в которой используется несколько кластеров Kubernetes для обеспечения отказоустойчивости, масштабирования или разделения сред.

**Centralized Logging** — подход, при котором логи со всех кластеров собираются в единую систему (Elasticsearch) для централизованного хранения и анализа.

**Log Federation** — механизм объединения логов из разных источников (кластеров) в единую систему хранения.

**Cross-Cluster Search** — возможность Elasticsearch искать данные в индексах, расположенных на других кластерах (CCS).

**Cross-Cluster Replication** — механизм репликации данных между кластерами Elasticsearch (CCR).

**Index Lifecycle Management (ILM)** — политика управления жизненным циклом индексов, применимая к multi-cluster сценариям.

**Cluster Alias** — псевдоним кластера в Elasticsearch для маршрутизации запросов между кластерами.

## Теоретический блок

### Архитектура multi-cluster логирования

```
┌─────────────────────────────────────────────────────────────┐
│              Multi-cluster логирование EFK                   │
├─────────────────────────────────────────────────────────────┤
│  Cluster A (Production)                                     │
│  └─ Fluent Bit → Elasticsearch (локальный)                  │
│       │                                                     │
│       └─→ Elasticsearch (центральный) ←─ Cluster B (Dev)    │
│                                                             │
│  Cluster B (Development)                                    │
│  └─ Fluent Bit → Elasticsearch (центральный)                │
│                                                             │
│  Cluster C (Staging)                                        │
│  └─ Fluent Bit → Elasticsearch (центральный)                │
└─────────────────────────────────────────────────────────────┘
```

### Стратегии multi-cluster логирования

| Стратегия | Описание | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Centralized Elasticsearch** | Все кластеры отправляют в один ES кластер | Простота, единая точка поиска | Single point of failure, network latency |
| **Local Elasticsearch + Federation** | Локальные ES кластеры + cross-cluster search | Отказоустойчивость, производительность | Сложность настройки, стоимость |
| **Log Aggregation Layer** | Промежуточный слой (Kafka, Fluentd) | Масштабируемость,缓冲 | Дополнительная сложность |
| **Hierarchical** | Иерархическая структура (edge → regional → global) | Масштабируемость, географическое разделение | Сложность маршрутизации |

### Ключевые considerations

1. **Network Connectivity**: сетевая связность между кластерами.
2. **DNS Resolution**: разрешение имен между кластерами.
3. **Security**: шифрование и аутентификация межкластерного трафика.
4. **Latency**: задержка сети влияет на производительность.
5. **Data Locality**: локализация данных для оптимизации поиска.
6. **Retention Policies**: единые политики удержания данных.

## Практический блок

### 1. Centralized Elasticsearch (все кластеры в один)

```yaml
# cluster-a-fluent-bit.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: logging
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush         5
        Log_Level     info
        Daemon        off
        Parsers_File  parsers.conf
        HTTP_Server   On
        HTTP_Listen   0.0.0.0
        HTTP_Port     2020
    
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        DB                /var/fluent-bit/state/flb_kube.db
        Mem_Buf_Limit     50MB
        Skip_Long_Lines   On
        Refresh_Interval  10
    
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix     kube.var.log.containers.
        Merge_Log           On
    
    [OUTPUT]
        Name            es
        Match           *
        Host            ${CENTRAL_ELASTICSEARCH_HOST}
        Port            9200
        Logstash_Format On
        Logstash_Prefix cluster-a
        Logstash_DateFormat %Y.%m.%d
        TLS             On
        TLS.verify      Off
        HTTP_User       ${ELASTICSEARCH_USER}
        HTTP_Passwd     ${ELASTICSEARCH_PASSWORD}
        Retry_Limit     False
        Workers         2
```

### 2. Cross-Cluster Search (CCS) конфигурация

```yaml
# elasticsearch-ccs-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: elasticsearch-config
  namespace: logging
data:
  elasticsearch.yml: |
    cluster.name: central-cluster
    network.host: 0.0.0.0
    
    # Cross-Cluster Search
    search.remote.cluster-a.seeds: "elasticsearch-cluster-a.svc:9300"
    search.remote.cluster-a.transport.ping_schedule: 30s
    
    search.remote.cluster-b.seeds: "elasticsearch-cluster-b.svc:9300"
    search.remote.cluster-b.transport.ping_schedule: 30s
    
    # Security
    xpack.security.enabled: true
    xpack.security.transport.ssl.enabled: true
```

```bash
# Настройка remote clusters через API
curl -X PUT "http://central-elasticsearch:9200/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{
    "persistent": {
      "cluster.remote.cluster_a.seeds": ["elasticsearch-cluster-a.svc:9300"],
      "cluster.remote.cluster_a.transport.ping_schedule": "30s"
    }
  }'

# Просмотр remote clusters
curl -X GET "http://central-elasticsearch:9200/_cat/remote_clusters?v"

# Cross-Cluster Search
curl -X GET "http://central-elasticsearch:9200/cluster_a:fluent-bit-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "match_all": {}
    }
  }'
```

### 3. Cross-Cluster Replication (CCR) конфигурация

```yaml
# elasticsearch-ccr-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: elasticsearch-config
  namespace: logging
data:
  elasticsearch.yml: |
    cluster.name: primary-cluster
    network.host: 0.0.0.0
    
    # Cross-Cluster Replication
    ccr.enabled: true
    
    # Security
    xpack.security.enabled: true
    xpack.security.transport.ssl.enabled: true
```

```bash
# Настройка leader cluster для CCR
curl -X PUT "http://leader-elasticsearch:9200/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{
    "persistent": {
      "cluster.remote.follower_cluster.seeds": ["follower-elasticsearch.svc:9300"]
    }
  }'

# Создание auto-follow pattern
curl -X PUT "http://leader-elasticsearch:9200/_ccr/auto_follow/log_pattern" \
  -H 'Content-Type: application/json' \
  -d '{
    "leader_index_patterns": ["fluent-bit-*"],
    "remote_cluster": "follower_cluster",
    "leader_index_exclusion_patterns": [],
    "follow_index_pattern": "{{leader_index}}-copy",
    "max_read_request_operation_count": 5120,
    "max_read_request_size": "32mb",
    "max_write_request_operation_count": 5120,
    "max_write_request_size": "32mb",
    "max_outstanding_read_requests": 12,
    "max_outstanding_write_requests": 9,
    "max_write_buffer_count": 240,
    "max_write_buffer_size": "512mb",
    "max_retry_delay": "10s",
    "read_poll_timeout": "10m"
  }'
```

### 4. Multi-cluster NetworkPolicy

```yaml
# multi-cluster-networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: elasticsearch-multi-cluster
  namespace: logging
spec:
  podSelector:
    matchLabels:
      app: elasticsearch
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Внутренний кластерный трафик
  - from:
    - podSelector:
        matchLabels:
          app: elasticsearch
    ports:
    - protocol: TCP
      port: 9300
  # Трафик от Fluent Bit
  - from:
    - podSelector:
        matchLabels:
          app: fluent-bit
    ports:
    - protocol: TCP
      port: 9200
  # Трафик от других кластеров
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 9300
    - protocol: TCP
      port: 9200
  egress:
  # DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
  # Внутренний кластерный трафик
  - to:
    - podSelector:
        matchLabels:
          app: elasticsearch
    ports:
    - protocol: TCP
      port: 9300
  # Трафик к другим кластерам
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 9300
    - protocol: TCP
      port: 9200
```

### 5. Multi-cluster DNS

```yaml
# multi-cluster-dns.yaml
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch-remote
  namespace: logging
  annotations:
    external-dns.alpha.kubernetes.io/hostname: elasticsearch.remote.cluster.local
spec:
  type: ExternalName
  externalName: elasticsearch.logging.svc.cluster.local
```

### 6. Мониторинг multi-cluster

```yaml
# multi-cluster-monitoring.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: elasticsearch-multi-cluster-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
  - name: elasticsearch-multi-cluster
    rules:
    # Алерт на недоступность remote cluster
    - alert: ElasticsearchRemoteClusterUnavailable
      expr: elasticsearch_cluster_health_number_of_nodes{cluster="remote"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Elasticsearch: remote cluster недоступен"
        description: "Remote cluster {{ $labels.cluster }} не отвечает"
    
    # Алерт на высокую задержку
    - alert: ElasticsearchHighLatency
      expr: elasticsearch_cluster_health_cluster_health_status{cluster="remote"} > 2
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: высокая задержка кластера"
        description: "Кластер {{ $labels.cluster }} имеет задержку"
    
    # Алерт на проблемы с CCR
    - alert: ElasticsearchCCR落后
      expr: elasticsearch_ccr_lag_time_seconds > 60
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: CCR lag detected"
        description: "Lag time: {{ $value }} seconds"
```

## Дополнительная информация

### Проверка multi-cluster

```bash
# Просмотр remote clusters
curl -X GET "http://elasticsearch:9200/_cat/remote_clusters?v"

# Просмотр CCR stats
curl -X GET "http://elasticsearch:9200/_ccr/stats" | jq .

# Просмотр CCS stats
curl -X GET "http://elasticsearch:9200/_cat/ml/job_stats?v"

# Проверка сетевой связности
kubectl exec -it elasticsearch-0 -n logging -- curl -s http://remote-elasticsearch:9200/_cluster/health

# Просмотр логов Fluent Bit на разных кластерах
kubectl logs -n logging -l app=fluent-bit --tail=100
```

### Частые проблемы

1. **Network partition**: Проверьте сетевую связность между кластерами.
2. **DNS resolution**: Убедитесь, что DNS работает между кластерами.
3. **TLS certificate**: Проверьте, что сертификаты доверяются между кластерами.
4. **Firewall rules**: Убедитесь, что правила файрвола разрешают трафик между кластерами.
5. **Latency**: Высокая задержка сети влияет на производительность CCS/CCR.

### Рекомендации

1. Используйте centralized logging для простых сценариев.
2. Используйте CCS/CCR для сложных multi-cluster сценариев.
3. Настройте сетевую связность и DNS перед включением CCS/CCR.
4. Используйте TLS для всех межкластерных соединений.
5. Мониторьте здоровье remote clusters и CCR lag.
6. Тестируйте disaster recovery сценарии.

### Полезные ссылки

- [Elasticsearch Cross-Cluster Search](https://www.elastic.co/guide/en/elasticsearch/reference/current/cross-cluster-search.html)
- [Elasticsearch Cross-Cluster Replication](https://www.elastic.co/guide/en/elasticsearch/reference/current/ccr-getting-started.html)
- [Multi-cluster Kubernetes](https://kubernetes.io/docs/tasks/administer-cluster/multiple-clusters/)
- [Fluent Bit Multi-cluster](https://docs.fluentbit.io/manual/pipeline/kubernetes)
- [Elastic Cloud on Kubernetes Multi-cluster](https://www.elastic.co/guide/en/cloud-on-k8s/current/k8s-multi-cluster.html)