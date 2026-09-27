# Высокая доступность EFK в Kubernetes

## Определения

**High Availability (HA)** — состояние системы, при котором она доступна и функционирует без прерываний в течение длительного времени. В контексте EFK это означает непрерывный сбор, хранение и визуализацию логов даже при отказе отдельных компонентов.

**Anti-Affinity** — механизм Kubernetes, предотвращающий размещение подов с определенными метками на одной ноде. Обеспечивает отказоустойчивость при падении ноды.

**Pod Disruption Budget (PDB)** — объект Kubernetes, ограничивающий количество одновременно недоступных подов при плановых операциях (обновления, drain нод).

**StatefulSet** — тип workload в Kubernetes для управления stateful-приложениями (с постоянными именами, порядковым развертыванием, persistent storage).

**ReplicaSet** — обеспечивает запуск указанного количества копий пода. StatefulSet использует ReplicaSet для каждого порядкового индекса.

**Readiness Probe** — проверка готовности пода принимать трафик. Если probe не проходит, под удаляется из Endpoints Service.

**Liveness Probe** — проверка работоспособности пода. Если probe не проходит, контейнер перезапускается.

**Pod Disruption Budget (PDB)** — гарантирует, что при плановых операциях (drain, обновление) всегда будет доступно минимальное количество подов.

## Теоретический блок

### Архитектура HA для EFK

```
┌─────────────────────────────────────────────────────────────┐
│                  Высокая доступность EFK                     │
├─────────────────────────────────────────────────────────────┤
│  Elasticsearch (3+ ноды)                                    │
│  └─ Master-eligible ноды (кворум: 2 из 3)                   │
│  └─ Data ноды (распределение шардов)                        │
│  └─ Ingest ноды (обработка документов)                      │
│  └─ Coordinating ноды (балансировка запросов)               │
│                                                             │
│  Fluent Bit (DaemonSet - 1 на узел)                         │
│  └─ Автоматическое переключение при падении ноды             │
│                                                             │
│  Kibana (2+ реплики)                                        │
│  └─ Load Balancer (Service)                                 │
│  └─ Session Affinity                                       │
└─────────────────────────────────────────────────────────────┘
```

### Ключевые принципы HA

1. **Нет Single Point of Failure (SPOF)**: каждый компонент должен иметь минимум 2 копии.
2. **Размещение на разных нодах**: Anti-Affinity правила предотвращают размещение копий на одной ноде.
3. **Автоматическое восстановление**: Readiness/Liveness probes + ReplicaSet/StatefulSet.
4. **Плановые операции**: Pod Disruption Budget гарантирует доступность при обновлениях.

### Требования к HA для компонентов EFK

| Компонент | Мин. копий | Anti-Affinity | PDB | Тип нод |
| :--- | :--- | :--- | :--- | :--- |
| **Elasticsearch (Master)** | 3 | Обязательно | minAvailable: 2 | Master-eligible |
| **Elasticsearch (Data)** | 3+ | Рекомендуется | minAvailable: 2 | Data |
| **Fluent Bit** | 1 на узел | N/A (DaemonSet) | N/A | Worker |
| **Kibana** | 2 | Рекомендуется | minAvailable: 1 | Any |

## Практический блок

### 1. Elasticsearch StatefulSet с Anti-Affinity

```yaml
# 01-elasticsearch-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
  namespace: logging
  labels:
    app: elasticsearch
spec:
  serviceName: elasticsearch
  replicas: 3
  selector:
    matchLabels:
      app: elasticsearch
  template:
    metadata:
      labels:
        app: elasticsearch
    spec:
      serviceAccountName: elasticsearch
      terminationGracePeriodSeconds: 300
      
      # Anti-Affinity: не размещать поды на одной ноде
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - elasticsearch
            topologyKey: kubernetes.io/hostname
      
      # Spread Constraints: равномерное распределение по зонам
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: elasticsearch
      
      containers:
      - name: elasticsearch
        image: docker.elastic.co/elasticsearch/elasticsearch:8.19.0
        ports:
        - containerPort: 9200
          name: http
        - containerPort: 9300
          name: transport
        
        env:
        - name: cluster.name
          value: "elasticsearch-cluster"
        - name: node.name
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: discovery.seed_hosts
          value: "elasticsearch-0.elasticsearch,elasticsearch-1.elasticsearch,elasticsearch-2.elasticsearch"
        - name: cluster.initial_master_nodes
          value: "elasticsearch-0,elasticsearch-1,elasticsearch-2"
        - name: ES_JAVA_OPTS
          value: "-Xms4g -Xmx4g"
        - name: xpack.security.enabled
          value: "true"
        
        # Readiness Probe
        readinessProbe:
          httpGet:
            path: /_cluster/health?local=true
            port: 9200
            scheme: HTTPS
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 5
        
        # Liveness Probe
        livenessProbe:
          httpGet:
            path: /_cluster/health?local=true
            port: 9200
            scheme: HTTPS
          initialDelaySeconds: 90
          periodSeconds: 20
          timeoutSeconds: 5
          failureThreshold: 5
        
        resources:
          requests:
            cpu: "2"
            memory: "8Gi"
          limits:
            cpu: "4"
            memory: "16Gi"
        
        volumeMounts:
        - name: data
          mountPath: /usr/share/elasticsearch/data
        - name: config
          mountPath: /usr/share/elasticsearch/config/elasticsearch.yml
          subPath: elasticsearch.yml
        - name: certs
          mountPath: /usr/share/elasticsearch/config/certs
      
      volumes:
      - name: config
        configMap:
          name: elasticsearch-config
      - name: certs
        secret:
          secretName: elasticsearch-certs
  
  # Volume Claim Templates
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 100Gi
```

### 2. Service для Elasticsearch

```yaml
# 02-elasticsearch-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch
  namespace: logging
  labels:
    app: elasticsearch
spec:
  type: ClusterIP
  clusterIP: None  # Headless Service для StatefulSet
  ports:
  - port: 9200
    targetPort: 9200
    name: http
  - port: 9300
    targetPort: 9300
    name: transport
  selector:
    app: elasticsearch
---
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch-client
  namespace: logging
  labels:
    app: elasticsearch
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: nlb
spec:
  type: LoadBalancer
  ports:
  - port: 9200
    targetPort: 9200
    name: http
  selector:
    app: elasticsearch
```

### 3. Pod Disruption Budget для Elasticsearch

```yaml
# 03-elasticsearch-pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: elasticsearch
  namespace: logging
  labels:
    app: elasticsearch
spec:
  minAvailable: 2  # Как минимум 2 пода должны быть доступны
  selector:
    matchLabels:
      app: elasticsearch
```

### 4. Kibana Deployment с Anti-Affinity

```yaml
# 04-kibana-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kibana
  namespace: logging
  labels:
    app: kibana
spec:
  replicas: 2
  selector:
    matchLabels:
      app: kibana
  template:
    metadata:
      labels:
        app: kibana
    spec:
      serviceAccountName: kibana
      
      # Anti-Affinity
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - kibana
              topologyKey: kubernetes.io/hostname
      
      containers:
      - name: kibana
        image: docker.elastic.co/kibana/kibana:8.19.0
        ports:
        - containerPort: 5601
          name: http
        
        env:
        - name: ELASTICSEARCH_HOSTS
          value: "http://elasticsearch:9200"
        - name: ELASTICSEARCH_USERNAME
          valueFrom:
            secretKeyRef:
              name: elasticsearch-credentials
              key: username
        - name: ELASTICSEARCH_PASSWORD
          valueFrom:
            secretKeyRef:
              name: elasticsearch-credentials
              key: password
        
        # Readiness Probe
        readinessProbe:
          httpGet:
            path: /api/status
            port: 5601
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 5
        
        # Liveness Probe
        livenessProbe:
          httpGet:
            path: /api/status
            port: 5601
          initialDelaySeconds: 90
          periodSeconds: 20
          timeoutSeconds: 5
          failureThreshold: 5
        
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        
        volumeMounts:
        - name: data
          mountPath: /usr/share/kibana/data
      
      volumes:
      - name: data
        emptyDir: {}
```

### 5. Kibana Service

```yaml
# 05-kibana-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: kibana
  namespace: logging
  labels:
    app: kibana
spec:
  type: LoadBalancer
  ports:
  - port: 5601
    targetPort: 5601
    name: http
  selector:
    app: kibana
  sessionAffinity: ClientIP  # Привязка сессии к конкретному поду
```

### 6. Pod Disruption Budget для Kibana

```yaml
# 06-kibana-pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kibana
  namespace: logging
  labels:
    app: kibana
spec:
  minAvailable: 1  # Как минимум 1 под должен быть доступен
  selector:
    matchLabels:
      app: kibana
```

### 7. Fluent Bit DaemonSet

```yaml
# 07-fluent-bit-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app: fluent-bit
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    metadata:
      labels:
        app: fluent-bit
    spec:
      serviceAccountName: fluent-bit
      
      # Tolerations для запуска на всех нодах
      tolerations:
      - operator: Exists
      
      containers:
      - name: fluent-bit
        image: fluent/fluent-bit:3.1
        ports:
        - containerPort: 2020
          name: http-metrics
        
        env:
        - name: FLUENT_ELASTICSEARCH_HOST
          value: "elasticsearch"
        - name: FLUENT_ELASTICSEARCH_PORT
          value: "9200"
        - name: FLUENT_ELASTICSEARCH_USER
          valueFrom:
            secretKeyRef:
              name: elasticsearch-credentials
              key: username
        - name: FLUENT_ELASTICSEARCH_PASSWORD
          valueFrom:
            secretKeyRef:
              name: elasticsearch-credentials
              key: password
        
        # Readiness Probe
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 2020
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        
        resources:
          requests:
            cpu: "100m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        
        volumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true
        - name: containers
          mountPath: /var/lib/docker/containers
          readOnly: true
        - name: config
          mountPath: /fluent-bit/etc/
      
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: containers
        hostPath:
          path: /var/lib/docker/containers
      - name: config
        configMap:
          name: fluent-bit-config
      
      # Запрет перемещения при drain ноды
      terminationGracePeriodSeconds: 30
```

### 8. NetworkPolicy для HA

```yaml
# 08-network-policies-ha.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: elasticsearch-ha-netpol
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
  # HTTP трафик от клиентов
  - from:
    - podSelector:
        matchLabels:
          app: kibana
    - podSelector:
        matchLabels:
          app: fluent-bit
    - podSelector:
        matchLabels:
          app: elasticsearch-exporter
    ports:
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
  # Kubernetes API
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 6443
```

### 9. Мониторинг HA

```yaml
# 09-ha-monitoring.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: elasticsearch-ha-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
  - name: elasticsearch-ha
    rules:
    # Алерт на недоступные ноды
    - alert: ElasticsearchNodesDown
      expr: elasticsearch_cluster_health_number_of_nodes < 3
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Elasticsearch: недостаточно нод"
        description: "Количество нод: {{ $value }} (требуется: 3)"
    
    # Алерт на unassigned shards
    - alert: ElasticsearchUnassignedShards
      expr: elasticsearch_cluster_health_unassigned_shards > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: есть неназначенные шарды"
        description: "Количество неназначенных шардов: {{ $value }}"
    
    # Алерт на cluster status
    - alert: ElasticsearchClusterRed
      expr: elasticsearch_cluster_health_status{color="red"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Elasticsearch: кластер в состоянии RED"
        description: "Кластер Elasticsearch находится в критическом состоянии"
    
    # Алерт на Kibana
    - alert: KibanaDown
      expr: up{job="kibana"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Kibana: недоступна"
        description: "Kibana не отвечает на запросы"
    
    # Алерт на Fluent Bit
    - alert: FluentBitDown
      expr: up{job="fluent-bit"} == 0
      for: 1m
      labels:
        severity: warning
      annotations:
        summary: "Fluent Bit: недоступен на ноде"
        description: "Fluent Bit не отвечает на ноде {{ $labels.instance }}"
```

## Дополнительная информация

### Проверка HA

```bash
# Проверка состояния кластера Elasticsearch
curl -X GET "http://elasticsearch:9200/_cluster/health?pretty" | jq '{
  cluster_name,
  status,
  number_of_nodes,
  number_of_data_nodes,
  active_shards,
  relocating_shards,
  initializing_shards,
  unassigned_shards
}'

# Проверка распределения шардов
curl -X GET "http://elasticsearch:9200/_cat/shards?v" | head -20

# Проверка Pod Disruption Budget
kubectl get pdb -n logging

# Проверка Anti-Affinity
kubectl describe pod elasticsearch-0 -n logging | grep -A 10 "Affinity"

# Проверка состояния подов
kubectl get pods -n logging -o wide

# Проверка событий
kubectl get events -n logging --sort-by='.lastTimestamp'
```

### Частые проблемы

1. **Split-brain**: Убедитесь, что кворум master-eligible нод соблюдается (N/2 + 1).
2. **Shard allocation failed**: Проверьте disk watermarks и disk usage.
3. **Kibana session loss**: Настройте session affinity в Service.
4. **Fluent Bit buffer overflow**: Увеличьте buffer size и storage.type.

### Рекомендации

1. Используйте минимум 3 ноды для Elasticsearch.
2. Настройте Anti-Affinity для всех компонентов.
3. Создайте Pod Disruption Budget для плановых операций.
4. Мониторьте состояние кластера и настраивайте алерты.
5. Регулярно тестируйте отказоустойчивость.
6. Используйте Readiness/Liveness probes для автоматического восстановления.

### Полезные ссылки

- [Elasticsearch High Availability](https://www.elastic.co/guide/en/elasticsearch/reference/current/high-availability.html)
- [Kubernetes Pod Anti-Affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#affinity-and-anti-affinity)
- [Pod Disruption Budget](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
- [ECK Best Practices](https://www.elastic.co/guide/en/cloud-on-k8s/current/k8s-best-practices.html)
- [Elasticsearch Cluster Planning](https://www.elastic.co/guide/en/elasticsearch/reference/current/cluster-planning.html)