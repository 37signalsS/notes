# Готовые шаблоны ConfigMap для типовых сервисов

## Определения

**Готовый шаблон ConfigMap** — проверенный в производственной эксплуатации YAML-манифест ConfigMap, содержащий конфигурацию конкретного сервиса (Nginx, Prometheus, PostgreSQL и др.) с оптимальными настройками. Шаблон позволяет избежать типовых ошибок при настройке и обеспечивает единообразие конфигурации между окружениями.

**Практический шаблон** — не только сам YAML, но и сопутствующие элементы: способ монтирования в Pod, проверка работоспособности после применения, типичные ошибки и их решение.

## Основные концепции

### Принципы выбора шаблона

1. **Разделяйте конфигурацию по логическим слоям:** Base-конфигурация (общая для всех окружений) + оверлеи (отличия для dev/stage/prod).
2. **Используйте `immutable: true`** для стабильных конфигураций. Пересоздавайте ConfigMap при изменении (Kustomize Name Hashing / Helm checksum).
3. **Валидируйте перед применением:** `kubectl apply --dry-run=server`, `kubeconform`, `promtool check config` (для Prometheus).
4. **Монтируйте с `readOnly: true`** и `defaultMode: 0440` для предотвращения локальных изменений.

### Структура шаблона

Каждый шаблон включает:
- YAML ConfigMap
- YAML Deployment/StatefulSet с монтированием
- Проверку работоспособности
- Типичные ошибки

## Практические сценарии

### Сценарий 1: Nginx — базовый reverse proxy

**ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  namespace: production
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/component: proxy
    app.kubernetes.io/managed-by: kustomize
immutable: true
data:
  nginx.conf: |
    worker_processes auto;
    error_log /var/log/nginx/error.log warn;
    pid /tmp/nginx.pid;

    events {
        worker_connections 1024;
        multi_accept on;
    }

    http {
        include /etc/nginx/mime.types;
        default_type application/octet-stream;

        log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                        '$status $body_bytes_sent "$http_referer" '
                        '"$http_user_agent" "$http_x_forwarded_for"';

        access_log /var/log/nginx/access.log main;

        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
        keepalive_timeout 65;
        types_hash_max_size 2048;

        # Gzip
        gzip on;
        gzip_vary on;
        gzip_proxied any;
        gzip_comp_level 6;
        gzip_types text/plain text/css application/json application/javascript
                   text/xml application/xml application/xml+rss text/javascript;

        include /etc/nginx/conf.d/*.conf;
    }

  default.conf: |
    upstream backend {
        server app-service:8080;
        keepalive 32;
    }

    server {
        listen 80;
        server_name _;

        # Health check для Readiness Probe
        location /healthz {
            access_log off;
            return 200 'ok';
            add_header Content-Type text/plain;
        }

        location / {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_cache_bypass $http_upgrade;
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Статика (если нужна)
        location /static/ {
            alias /usr/share/nginx/html/static/;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }
```

**Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-proxy
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx-proxy
  template:
    metadata:
      labels:
        app: nginx-proxy
      annotations:
        checksum/config: "PLACEHOLDER"  # Helm: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
      - name: nginx
        image: nginx:1.25-alpine
        ports:
        - containerPort: 80
        volumeMounts:
        - name: nginx-config
          mountPath: /etc/nginx/nginx.conf
          subPath: nginx.conf
          readOnly: true
        - name: nginx-config
          mountPath: /etc/nginx/conf.d/default.conf
          subPath: default.conf
          readOnly: true
        readinessProbe:
          httpGet:
            path: /healthz
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthz
            port: 80
          initialDelaySeconds: 10
          periodSeconds: 30
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
      volumes:
      - name: nginx-config
        configMap:
          name: nginx-config
          defaultMode: 0440
```

**Проверка:**

```bash
# Применение
kubectl apply -f nginx-configmap.yaml

# Проверка подов
kubectl get pods -l app=nginx-proxy
kubectl logs -l app=nginx-proxy --tail=20

# Проверка конфига внутри контейнера
kubectl exec deploy/nginx-proxy -- nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка структуры тома
kubectl exec deploy/nginx-proxy -- ls -la /etc/nginx/
```

**Типичные ошибки:**

| Ошибка | Причина | Решение |
|---|---|---|
| `nginx: [emerg] unknown directive "worker_connections"` | Синтаксическая ошибка в конфиге | `kubectl exec -- nginx -t` для проверки |
| Под не стартует, `OOMKilled` | Слишком высокий `worker_connections` | Уменьшите `worker_connections` или увеличьте `limits.memory` |
| Статика не обновляется после изменения ConfigMap | Используется `subPath` для nginx.conf | Используйте отдельные `subPath` для каждого файла |

---

### Сценарий 2: Prometheus — scrape конфигурация

**ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: monitoring
  labels:
    app.kubernetes.io/name: prometheus
    app.kubernetes.io/component: server
immutable: true
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
      scrape_timeout: 10s

    rule_files:
      - /etc/prometheus/rules/*.yml

    alerting:
      alertmanagers:
        - static_configs:
            - targets:
                - alertmanager:9093

    scrape_configs:
      # Мониторинг самого Prometheus
      - job_name: 'prometheus'
        static_configs:
          - targets: ['localhost:9090']

      # Kubernetes Service Discovery
      - job_name: 'kubernetes-pods'
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: true
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
            action: replace
            target_label: __metrics_path__
            regex: (.+)
          - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            target_label: __address__
            regex: ([^:]+)(?::\d+)?;(\d+)
            replacement: $1:$2
          - source_labels: [__meta_kubernetes_namespace]
            action: replace
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            action: replace
            target_label: pod

      # Node Exporter
      - job_name: 'node-exporter'
        static_configs:
          - targets: ['node-exporter:9100']

      # kube-state-metrics
      - job_name: 'kube-state-metrics'
        static_configs:
          - targets: ['kube-state-metrics:8080']
```

**Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prometheus
  template:
    metadata:
      labels:
        app: prometheus
    spec:
      serviceAccountName: prometheus
      containers:
      - name: prometheus
        image: prom/prometheus:v2.51.0
        args:
          - '--config.file=/etc/prometheus/prometheus.yml'
          - '--storage.tsdb.path=/prometheus'
          - '--storage.tsdb.retention.time=15d'
          - '--web.enable-lifecycle'
        ports:
        - containerPort: 9090
        volumeMounts:
        - name: prometheus-config
          mountPath: /etc/prometheus/prometheus.yml
          subPath: prometheus.yml
          readOnly: true
        - name: prometheus-data
          mountPath: /prometheus
        readinessProbe:
          httpGet:
            path: /-/ready
            port: 9090
          initialDelaySeconds: 10
          periodSeconds: 10
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi
      volumes:
      - name: prometheus-config
        configMap:
          name: prometheus-config
      - name: prometheus-data
        persistentVolumeClaim:
          claimName: prometheus-data
```

**Проверка:**

```bash
# Применение
kubectl apply -f prometheus-configmap.yaml

# Валидация конфига (нужен promtool)
kubectl exec deploy/prometheus -- promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS: 0 rule files found

# Проверка targets
kubectl port-forward svc/prometheus 9090:9090
# Откройте http://localhost:9090/targets

# Проверка переменных окружения
kubectl exec deploy/prometheus -- cat /etc/prometheus/prometheus.yml | head -5
```

**Типичные ошибки:**

| Ошибка | Причина | Решение |
|---|---|---|
| `context canceled` при загрузке конфига | Превышен лимит размера ConfigMap (>1 MiB) | Разбейте на несколько ConfigMap или используйте PV |
| Targets в состоянии `DOWN` | Неправильный `metrics_path` или порт | Проверьте `relabel_configs` и аннотации подов |
| `error opening config file` | Файл не смонтирован или невалиден | `kubectl exec -- cat /etc/prometheus/prometheus.yml` |

---

### Сценарий 3: PostgreSQL (Patroni/Spilo) — параметры СУБД

**ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
  namespace: databases
  labels:
    app.kubernetes.io/name: postgresql
    app.kubernetes.io/component: database
immutable: true
data:
  postgresql.conf: |
    # Слушать все интерфейсы
    listen_addresses = '*'
    port = 5432

    # Память
    shared_buffers = '256MB'
    effective_cache_size = '1GB'
    work_mem = '4MB'
    maintenance_work_mem = '128MB'

    # WAL
    wal_level = replica
    max_wal_senders = 5
    wal_keep_size = '1GB'
    hot_standby = on

    # Логирование
    log_destination = 'stderr'
    logging_collector = on
    log_directory = 'log'
    log_filename = 'postgresql-%Y-%m-%d.log'
    log_rotation_age = '1d'
    log_rotation_size = '100MB'
    log_min_duration_statement = 1000
    log_checkpoints = on
    log_connections = on
    log_disconnections = on
    log_lock_waits = on

    # Безопасность
    password_encryption = scram-sha-256

    # Производительность
    max_connections = 200
    max_worker_processes = 8
    max_parallel_workers_per_gather = 4
    max_parallel_workers = 8

  pg_hba.conf: |
    # TYPE  DATABASE  USER  ADDRESS      METHOD
    local   all       all                scram-sha-256
    host    all       all   0.0.0.0/0   scram-sha-256
    host    all       all   ::/0        scram-sha-256
    host    replication  replica  0.0.0.0/0  scram-sha-256

  patroni.yaml: |
    scope: postgresql-cluster
    name: ${HOSTNAME}

    restapi:
      listen: 0.0.0.0:8008
      connect_address: ${POD_IP}:8008

    bootstrap:
      dcs:
        ttl: 30
        loop_wait: 10
        retry_timeout: 10
        maximum_lag_on_failover: 1048576
        postgresql:
          use_pg_rewind: true
          parameters:
            max_connections: 200
            shared_buffers: 256MB
            wal_level: replica

    postgresql:
      listen: 0.0.0.0:5432
      connect_address: ${POD_IP}:5432
      data_dir: /home/postgres/pgdata/pgroot/data
      authentication:
        replication:
          username: replica
          password: ${REPLICATION_PASSWORD}
        superuser:
          username: postgres
          password: ${POSTGRES_PASSWORD}
      parameters:
        max_connections: 200
        shared_buffers: 256MB

    tags:
      nofailover: false
      noloadbalance: false
      clonefrom: false
      nosync: false
```

**StatefulSet:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: databases
spec:
  serviceName: postgresql
  replicas: 3
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
      - name: postgresql
        image: registry.opensource.zalando.net/spilo/spilo-16:3.2-p1
        ports:
        - containerPort: 5432
          name: postgresql
        - containerPort: 8008
          name: patroni
        env:
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secrets
              key: password
        - name: REPLICATION_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secrets
              key: replication-password
        volumeMounts:
        - name: postgres-config
          mountPath: /etc/postgresql
          readOnly: true
        - name: postgres-data
          mountPath: /home/postgres/pgdata
        readinessProbe:
          httpGet:
            path: /readiness
            port: 8008
          initialDelaySeconds: 30
          periodSeconds: 10
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi
      volumes:
      - name: postgres-config
        configMap:
          name: postgres-config
          defaultMode: 0440
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 20Gi
```

**Проверка:**

```bash
# Применение
kubectl apply -f postgres-configmap.yaml

# Проверка кластера Patroni
kubectl exec postgresql-0 -- patronictl list
# → +---------+---------+---------+---------+-----------+
# │  Member │   Host  │   Role  │   State │ TL │ Lag in MB
# → +---------+---------+---------+---------+-----------+
# │ postgresql-0 │ ...  │ Leader  │ running │  1 │     0
# │ postgresql-1 │ ...  │ Replica │ running │  1 │     0
# → +---------+---------+---------+---------+-----------+

# Проверка параметров
kubectl exec postgresql-0 -- psql -U postgres -c "SHOW shared_buffers;"
# →  shared_buffers
# ────────────────
#  256MB
```

---

### Сценарий 4: Alertmanager — маршрутизация алертов

**ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config
  namespace: monitoring
  labels:
    app.kubernetes.io/name: alertmanager
immutable: true
data:
  alertmanager.yml: |
    global:
      resolve_timeout: 5m
      slack_api_url: ${SLACK_WEBHOOK_URL}
      smtp_smarthost: 'smtp.gmail.com:587'
      smtp_from: 'alertmanager@example.com'
      smtp_auth_username: 'alertmanager@example.com'
      smtp_auth_password: '${SMTP_PASSWORD}'

    route:
      receiver: 'default'
      group_by: ['alertname', 'namespace', 'severity']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      routes:
        - match:
            severity: critical
          receiver: 'critical'
          repeat_interval: 1h
        - match:
            severity: warning
          receiver: 'warning'
          repeat_interval: 4h

    receivers:
      - name: 'default'
        slack_configs:
          - channel: '#alerts'
            send_resolved: true
            title: '{{ template "slack.default.title" . }}'
            text: '{{ template "slack.default.text" . }}'

      - name: 'critical'
        slack_configs:
          - channel: '#alerts-critical'
            send_resolved: true
            title: '[CRITICAL] {{ .GroupLabels.alertname }}'
            text: |
              {{ range .Alerts }}
              *Alert:* {{ .Annotations.summary }}
              *Details:* {{ .Annotations.description }}
              *Severity:* {{ .Labels.severity }}
              *Namespace:* {{ .Labels.namespace }}
              {{ end }}
        pagerduty_configs:
          - service_key: '${PAGERDUTY_KEY}'

      - name: 'warning'
        slack_configs:
          - channel: '#alerts-warning'
            send_resolved: true

    inhibit_rules:
      - source_match:
          severity: 'critical'
        target_match:
          severity: 'warning'
        equal: ['alertname', 'namespace']
```

**Проверка:**

```bash
# Валидация конфига (нужен amtool)
kubectl exec deploy/alertmanager -- amtool check-config /etc/alertmanager/alertmanager.yml

# Проверка маршрутов
kubectl exec deploy/alertmanager -- amtool route show --config.file=/etc/alertmanager/alertmanager.yml
```

---

### Сценарий 5: Redis — конфигурация кэша

**ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: caching
  labels:
    app.kubernetes.io/name: redis
immutable: true
data:
  redis.conf: |
    # Сеть
    bind 0.0.0.0
    port 6379
    tcp-backlog 511
    timeout 0
    tcp-keepalive 300

    # Память
    maxmemory 256mb
    maxmemory-policy allkeys-lru

    # Персистентность
    save 900 1
    save 300 10
    save 60 10000
    rdbcompression yes
    rdbchecksum yes
    dbfilename dump.rdb
    dir /data

    # Логирование
    loglevel notice
    logfile ""

    # Безопасность
    # requirepass ${REDIS_PASSWORD}  # Раскомментируйте в production

    # Производительность
    hz 10
    dynamic-hz yes
    lazyfree-lazy-eviction yes
    lazyfree-lazy-expire yes
```

**Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: caching
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command: ["redis-server", "/etc/redis/redis.conf"]
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: redis-config
          mountPath: /etc/redis/redis.conf
          subPath: redis.conf
          readOnly: true
        - name: redis-data
          mountPath: /data
        readinessProbe:
          exec:
            command: ["redis-cli", "ping"]
          initialDelaySeconds: 5
          periodSeconds: 10
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
      volumes:
      - name: redis-config
        configMap:
          name: redis-config
      - name: redis-data
        emptyDir: {}
```

---

### Сценарий 6: Consul Template — динамическая конфигурация Nginx

Для сценариев, где бэкенд-сервисы меняются динамически, Consul Template генерирует `nginx.conf` из Consul KV:

**ConfigMap (bootstrap-конфиг):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: consul-template-config
  namespace: infrastructure
data:
  nginx.conf.ctmpl: |
    upstream backend {
    {{- range services "app-backend" }}
      server {{ .Address }}:{{ .Port }};
    {{- end }}
    }

    server {
      listen 80;
      location / {
        proxy_pass http://backend;
      }
    }
```

> **Примечание:** Consul Template заменяет ConfigMap как источник конфигурации для динамических бэкендов. ConfigMap используется только для bootstrap-конфига самого Consul Template.

---

## Дополнительная информация

### Ссылки на существующие шаблоны

| Сервис | Файл в репозитории | Описание |
|---|---|---|
| Nginx | `WebServers/Nginx/Core/nginx_setup.md` | Полная структура `nginx.conf` |
| Nginx (reverse proxy) | `WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md` | Шаблон reverse proxy для Grafana |
| Prometheus | `Prometheus/installation/docker_stack/prometheus_config.md` | Полный `prometheus.yml` |
| Alertmanager | `Prometheus/kubernetes/examples/alertmanager-karma-manifests-tutorial/alertmanager-config.md` | Alertmanager ConfigMap |
| Grafana Dashboard | `Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md` | ConfigMap для dashboards |
| PostgreSQL (Patroni) | `Databases/PostgreSQL/Operations/zalando_spilo_manifests.md` | ConfigMap для Patroni |
| Redis | см. выше | Базовая конфигурация |

### Reloader для Hot Reload

Для сервисов, поддерживающих Hot Reload (Nginx, Prometheus, Consul), используйте Stakater Reloader:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-proxy
  annotations:
    configmap.reloader.stakater.com/reload: "nginx-config"
```

> Подробнее: [Reloader Usage Scenarios](../../ToolsUtilities/reloader/reloader_usage_scenarios.md)

### См. также

* [Создание ConfigMap](./creation.md) — декларативные и императивные подходы.
* [Использование ConfigMap в подах](./pod_usage.md) — монтирование и переменные окружения.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии обновления.
* [Работа с большими конфигурациями](./large_configs.md) — обход лимита 1 MiB.
