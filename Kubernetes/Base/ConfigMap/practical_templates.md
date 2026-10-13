# Готовые шаблоны ConfigMap для типовых сервисов

**Актуально для:** Kubernetes 1.28–1.32+

## Определения

**Шаблон конфигурации ConfigMap** — протестированный в промышленной эксплуатации манифест Kubernetes ConfigMap, содержащий валидную конфигурацию системного или прикладного сервиса (Nginx, HAProxy, Prometheus, Alertmanager, Patroni, Redis, CoreDNS, Fluent Bit) с оптимальными настройками производительности, надежности и безопасности.

**Проекция тома ConfigMap (ConfigMap Volume Projection)** — механизм монтирования данных ConfigMap в файловую систему контейнера в виде каталога файлов. Kubelet поддерживает атомарное обновление содержимого через замену символических ссылок (`..data`), если том смонтирован без использования `subPath`.

**Монтирование через subPath** — монтирование отдельного ключа ConfigMap в виде изолированного файла без перекрытия родительского каталога. Ключевое ограничение: Kubelet связывает иноду файла при старте контейнера, поэтому файлы, смонтированные через `subPath`, **не получают автоматических обновлений** при изменении ConfigMap в кластере.

**Горячая перезагрузка (Hot Reload / In-place Reload)** — перечитывание конфигурационных файлов процессом приложения без перезапуска и уничтожения контейнера (через отправку сигналов POSIX `SIGHUP`/`SIGUSR1` или вызов локального HTTP-эндпоинта `/-/reload`).

**Неизменяемый ConfigMap (Immutable ConfigMap)** — объект ConfigMap с атрибутом `immutable: true`. Запрещает последующие изменения данных в API-сервере, снижает нагрузку на `etcd` и контроллеры Kubelet (отключает постоянный polling), гарантируя защиту от случайного конфигурационного дрейфа.

**Окно расхождения конфигураций (Config Skew Window)** — интервал времени между обновлением ConfigMap в API Kubernetes и монтированием новых данных на всех узлах и подах кластера (зависит от периода синхронизации Kubelet и TTL кэшей).

**Подстановка переменных окружения (Runtime Environment Expansion)** — механизм раскрытия значений из переменных окружения (включая переданные из Kubernetes Secret) внутри текстовых конфигураций либо нативно приложением (например, `Alertmanager` с флагом `--config.expand-external-variables`), либо на этапе инициализации пода через `initContainer`.

---

## Основные концепции

### Архитектура доставки конфигураций в контейнеры

```
                                      +-----------------------------------------+
                                      |         Kubernetes API Server           |
                                      +--------------------+--------------------+
                                                           |
                                               Watch / List Events
                                                           v
                                      +--------------------+--------------------+
                                      |          Kubelet Volume Manager         |
                                      +--------------------+--------------------+
                                                           |
                           Atomic Symlink Swap             | Direct Bind Mount
                         (Auto-updated in 60-90s)          | (Static, NO auto-update)
                                   |                       |
                                   v                       v
                      +------------------------+  +------------------------+
                      |   Каталог (Volume)     |  |     subPath Mount      |
                      |  /etc/nginx/conf.d/    |  | /etc/nginx/nginx.conf  |
                      |  ..data -> ..data_123  |  | (прямой bind к иноде)  |
                      +------------------------+  +------------------------+
                                   |                       |
                                   +-----------+-----------+
                                               |
                                               v
                                   +-----------------------+
                                   |   Процесс в Pod'е     |
                                   | (Nginx, Prometheus...) |
                                   +-----------------------+
```

1. **Жизненный цикл монтирования томов:** Kubelet создает во временной директории пода служебную структуру каталогов: `..data_<timestamp>`, ссылку `..data` и ссылки на отдельные файлы. При обновлении ConfigMap Kubelet создает новую директорию `..data_<new_timestamp>` и атомарно переключает симлинк `..data`.
2. **Монтирование каталога против `subPath`:**
   - **Монтирование каталога (Directory Mount):** Перекрывает целевой каталог в образе контейнера. Подходит для специализированных папок расширений (`/etc/nginx/conf.d/`, `/etc/coredns/custom/`, `/etc/prometheus/rules/`). Автоматически обновляется на диске Kubelet'ом.
   - **Монтирование через `subPath`:** Позволяет подменить единичный файл (например, `/etc/nginx/nginx.conf`), сохранив остальные системные файлы базового образа. Автоматически Kubelet'ом **не обновляется**; применение изменений требует пересоздания пода (`kubectl rollout restart`).
3. **Реакция приложений на изменения:**
   - **Служба поддерживает SIGHUP/сигналы:** (Nginx, HAProxy) процесс перечитывает файл без разрыва активных соединений.
   - **Служба поддерживает HTTP reload:** (Prometheus, Alertmanager) вызов вебхука `/-/reload` заставляет демон перечитать конфигурацию.
   - **Служба требует перезапуска процесса:** (PostgreSQL, Redis для большинства параметров) требуется управляемый перезапуск пода через контроллер (Deployment, StatefulSet).
4. **Безопасное разделение ConfigMap и Secret:**
   - Пароли, закрытые ключи и токены никогда не должны храниться в открытом виде в ConfigMap.
   - Для интеграций используется связка: базовый шаблон в ConfigMap + секреты из Secret, монтируемые как переменные окружения или изолированные тома с правами `0400`.

---

## Практические сценарии

### Сценарий 1: Nginx — Production Reverse Proxy и Web Server

Production-шаблон Nginx в качестве внутреннего L7 Reverse Proxy и шлюза статики. Разделен на базовый `nginx.conf` (монтируется через `subPath` с тюнингом производительности и отключением root-привилегий) и виртуальный хост `default.conf` (монтируется как том в `/etc/nginx/conf.d/` для поддержки горячей перезагрузки).

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-proxy-config
  namespace: production
  labels:
    app.kubernetes.io/name: nginx-proxy
    app.kubernetes.io/component: ingress-proxy
    app.kubernetes.io/managed-by: gitops
immutable: true
data:
  nginx.conf: |
    worker_processes auto;
    worker_rlimit_nofile 65535;
    pid /tmp/nginx.pid;
    error_log /var/log/nginx/error.log warn;

    events {
        worker_connections 8192;
        multi_accept on;
        use epoll;
    }

    http {
        include /etc/nginx/mime.types;
        default_type application/octet-stream;

        log_format main_json escape=json '{'
            '"time_local":"$time_local",'
            '"remote_addr":"$remote_addr",'
            '"request":"$request",'
            '"status":$status,'
            '"body_bytes_sent":$body_bytes_sent,'
            '"request_time":$request_time,'
            '"upstream_response_time":"$upstream_response_time",'
            '"http_referrer":"$http_referer",'
            '"http_user_agent":"$http_user_agent"'
        '}';

        access_log /var/log/nginx/access.log main_json;

        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
        keepalive_timeout 65;
        keepalive_requests 1000;
        types_hash_max_size 2048;
        server_tokens off;

        client_max_body_size 16M;
        client_body_buffer_size 128k;

        # Сжатие Gzip
        gzip on;
        gzip_vary on;
        gzip_proxied any;
        gzip_comp_level 5;
        gzip_min_length 256;
        gzip_types
            application/atom+xml
            application/javascript
            application/json
            application/rss+xml
            application/vnd.ms-fontobject
            application/x-font-ttf
            application/x-web-app-manifest+json
            application/xhtml+xml
            application/xml
            font/opentype
            image/svg+xml
            image/x-icon
            text/css
            text/plain
            text/x-component;

        include /etc/nginx/conf.d/*.conf;
    }

  default.conf: |
    upstream backend_app {
        server app-service.production.svc.cluster.local:8080;
        keepalive 64;
    }

    server {
        listen 8080 default_server;
        server_name _;

        # Healthcheck для Kubernetes Readiness и Liveness Probe
        location = /healthz {
            access_log off;
            add_header Content-Type text/plain;
            return 200 'ok';
        }

        # Nginx stub_status для Prometheus-экспортера
        location = /stub_status {
            stub_status;
            access_log off;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }

        location / {
            proxy_pass http://backend_app;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 5s;
            proxy_send_timeout 30s;
            proxy_read_timeout 30s;
            proxy_next_upstream error timeout http_502 http_503 http_504;
        }
    }
```

#### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-proxy
  namespace: production
  labels:
    app.kubernetes.io/name: nginx-proxy
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: nginx-proxy
  template:
    metadata:
      labels:
        app: nginx-proxy
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 101 # nginx unprivileged
        runAsGroup: 101
        fsGroup: 101
      containers:
      - name: nginx
        image: nginx:1.26-alpine
        ports:
        - containerPort: 8080
          name: http
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 3
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 15
        volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/nginx.conf
          subPath: nginx.conf
          readOnly: true
        - name: vhost-volume
          mountPath: /etc/nginx/conf.d
          readOnly: true
        - name: tmp-volume
          mountPath: /tmp
        - name: cache-volume
          mountPath: /var/cache/nginx
        - name: logs-volume
          mountPath: /var/log/nginx
      volumes:
      - name: config-volume
        configMap:
          name: nginx-proxy-config
          defaultMode: 0440
      - name: vhost-volume
        configMap:
          name: nginx-proxy-config
          items:
          - key: default.conf
            path: default.conf
          defaultMode: 0440
      - name: tmp-volume
        emptyDir: {}
      - name: cache-volume
        emptyDir: {}
      - name: logs-volume
        emptyDir: {}
```

#### Проверка и эксплуатация

```bash
# Валидация синтаксиса конфигурации внутри работающего пода
kubectl exec -n production deploy/nginx-proxy -c nginx -- nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка ответа readiness-пробы
kubectl exec -n production deploy/nginx-proxy -c nginx -- wget -qO- http://127.0.0.1:8080/healthz
# → ok

# Перезагрузка конфигурации виртуальных хостов без перезапуска пода (Hot Reload)
kubectl exec -n production deploy/nginx-proxy -c nginx -- nginx -s reload
# → 2026/10/13 19:30:00 [notice] 1#1: signal 1 (SIGHUP) received, reconfiguring
```

---

### Сценарий 2: HAProxy — Высокопроизводительный L4/L7 Балансировщик нагрузки

Шаблон HAProxy для отказоустойчивой балансировки трафика внутри кластера или на внешние bare-metal бэкенды. Включает многопоточность (`nbthread`), сокет управления для runtime-диагностики, встроенный health checking бэкендов и страницу статистики.

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: haproxy-config
  namespace: networking
  labels:
    app.kubernetes.io/name: haproxy
    app.kubernetes.io/component: load-balancer
immutable: true
data:
  haproxy.cfg: |
    global
        log stdout format raw local0 info
        maxconn 32768
        stats socket /tmp/haproxy.sock mode 660 level admin expose-fd listeners
        stats timeout 30s
        user haproxy
        group haproxy
        nbthread 4
        hard-stop-after 10s

    defaults
        log global
        mode http
        option httplog
        option dontlognull
        option http-server-close
        option forwardfor except 127.0.0.0/8
        retries 3
        timeout connect 5s
        timeout client  30s
        timeout server  30s
        timeout http-request 10s
        timeout http-keep-alive 60s

    frontend stats
        mode http
        bind *:8404
        stats enable
        stats uri /stats
        stats refresh 10s
        stats show-node
        http-request use-service prometheus-exporter if { path /metrics }
        monitor-uri /healthz

    frontend http_front
        bind *:8080
        mode http
        option forwardfor
        http-request set-header X-Forwarded-Proto http
        default_backend http_back

    backend http_back
        mode http
        balance roundrobin
        option httpchk GET /healthz
        http-check expect status 200
        default-server inter 3s fall 3 rise 2 maxconn 1024
        server srv1 app-backend-0.app-backend.production.svc.cluster.local:8080 check
        server srv2 app-backend-1.app-backend.production.svc.cluster.local:8080 check
        server srv3 app-backend-2.app-backend.production.svc.cluster.local:8080 check backup
```

#### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: haproxy-lb
  namespace: networking
  labels:
    app.kubernetes.io/name: haproxy
spec:
  replicas: 2
  selector:
    matchLabels:
      app: haproxy-lb
  template:
    metadata:
      labels:
        app: haproxy-lb
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 99 # haproxy user
        runAsGroup: 99
        fsGroup: 99
      containers:
      - name: haproxy
        image: haproxy:3.0-alpine
        ports:
        - containerPort: 8080
          name: http
        - containerPort: 8404
          name: stats
        resources:
          requests:
            cpu: 200m
            memory: 128Mi
          limits:
            cpu: 1000m
            memory: 512Mi
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8404
          initialDelaySeconds: 2
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8404
          initialDelaySeconds: 5
          periodSeconds: 10
        volumeMounts:
        - name: haproxy-cfg
          mountPath: /usr/local/etc/haproxy/haproxy.cfg
          subPath: haproxy.cfg
          readOnly: true
        - name: tmp-dir
          mountPath: /tmp
      volumes:
      - name: haproxy-cfg
        configMap:
          name: haproxy-config
          defaultMode: 0440
      - name: tmp-dir
        emptyDir: {}
```

#### Проверка и эксплуатация

```bash
# Валидация конфигурации через бинарник HAProxy
kubectl exec -n networking deploy/haproxy-lb -c haproxy -- haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Получение статуса бэкендов через сокет управления
kubectl exec -n networking deploy/haproxy-lb -c haproxy -- sh -c 'echo "show stat" | nc -U /tmp/haproxy.sock' | head -n 5
# → # pxname,svname,qcur,qmax,scur,smax,slim,stot,bin,bout,dreq,dresp,ereq,econ,eresp...
# → stats,FRONTEND,,,0,1,32768,4,196,1512,0,0,0,,,,0,0,0,,,,,OPEN,,,,,,,,,
# → http_front,FRONTEND,,,0,3,32768,12,840,4120,0,0,0,,,,0,0,0,,,,,OPEN,,,,,,,,,

# Проверка метрик в формате Prometheus
kubectl exec -n networking deploy/haproxy-lb -c haproxy -- wget -qO- http://127.0.0.1:8404/metrics | head -n 5
# → # HELP haproxy_process_nbthread Number of threads
# → # TYPE haproxy_process_nbthread gauge
# → haproxy_process_nbthread 4
```

---

### Сценарий 3: Prometheus — Scrape-конфигурация и Service Discovery

Production-шаблон конфигурации Prometheus (совместим с версиями v2.51+ и v3.x). Включает Service Discovery для подов Kubernetes на основе аннотаций, сбор метрик Node Exporter, скрейпинг CoreDNS и правила фильтрации меток (relabeling).

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-core-config
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
                - alertmanager.monitoring.svc.cluster.local:9093

    scrape_configs:
      # Мониторинг собственного сервера Prometheus
      - job_name: 'prometheus'
        static_configs:
          - targets: ['localhost:9090']

      # Сбор метрик CoreDNS
      - job_name: 'coredns'
        kubernetes_sd_configs:
          - role: endpoints
            namespaces:
              names:
                - kube-system
        relabel_configs:
          - source_labels: [__meta_kubernetes_service_name]
            action: keep
            regex: kube-dns
          - source_labels: [__meta_kubernetes_endpoint_port_name]
            action: keep
            regex: metrics

      # Универсальный сбор метрик с аннотированных подов в кластере
      - job_name: 'kubernetes-pods'
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          # Скрейпить только поды с аннотацией prometheus.io/scrape = "true"
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: true
          # Переопределение пути метрик (по умолчанию /metrics)
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
            action: replace
            target_label: __metrics_path__
            regex: (.+)
          # Определение схемы (http/https)
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scheme]
            action: replace
            target_label: __scheme__
            regex: (https?)
          # Переопределение порта скрейпинга
          - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            regex: ([^:]+)(?::\d+)?;(\d+)
            replacement: $1:$2
            target_label: __address__
          # Извлечение метаданных кластера в постоянные метки
          - source_labels: [__meta_kubernetes_namespace]
            action: replace
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            action: replace
            target_label: pod
          - source_labels: [__meta_kubernetes_pod_node_name]
            action: replace
            target_label: node
```

#### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus-server
  namespace: monitoring
  labels:
    app.kubernetes.io/name: prometheus
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
      serviceAccountName: prometheus-k8s
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534 # nobody
        runAsGroup: 65534
        fsGroup: 65534
      containers:
      - name: prometheus
        image: prom/prometheus:v3.13.2
        args:
          - '--config.file=/etc/prometheus/prometheus.yml'
          - '--storage.tsdb.path=/prometheus'
          - '--storage.tsdb.retention.time=15d'
          - '--web.enable-lifecycle'
          - '--web.console.libraries=/usr/share/prometheus/console_libraries'
          - '--web.console.templates=/usr/share/prometheus/consoles'
        ports:
        - containerPort: 9090
          name: web
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi
        readinessProbe:
          httpGet:
            path: /-/ready
            port: 9090
          initialDelaySeconds: 5
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /-/healthy
            port: 9090
          initialDelaySeconds: 30
          periodSeconds: 15
        volumeMounts:
        - name: config-volume
          mountPath: /etc/prometheus
          readOnly: true
        - name: storage-volume
          mountPath: /prometheus
      volumes:
      - name: config-volume
        configMap:
          name: prometheus-core-config
          defaultMode: 0440
      - name: storage-volume
        emptyDir: {}
```

#### Проверка и эксплуатация

```bash
# Валидация конфигурации через встроенную утилиту promtool
kubectl exec -n monitoring deploy/prometheus-server -c prometheus -- promtool check config /etc/prometheus/prometheus.yml
# → Checking /etc/prometheus/prometheus.yml
# →   SUCCESS: 0 rule files found

# Проверка статуса готовности сервера (TSDB replay завершен)
kubectl exec -n monitoring deploy/prometheus-server -c prometheus -- wget -qO- http://127.0.0.1:9090/-/ready
# → Prometheus is Ready.

# Перезагрузка конфигурации на лету через эндпоинт жизненного цикла (Hot Reload)
kubectl exec -n monitoring deploy/prometheus-server -c prometheus -- wget -qO- --post-data='' http://127.0.0.1:9090/-/reload
# → (код возврата 200 OK, в логах появляется сообщение: "Completed loading of configuration file")
```

---

### Сценарий 4: Alertmanager — Маршрутизация алертов и безопасная интеграция с Secrets

Шаблон Alertmanager с многоуровневым деревом маршрутизации, правилами подавления (`inhibit_rules`) и безопасной интеграцией секретов. Использование переменной `${SLACK_WEBHOOK_URL}` и `${SMTP_PASSWORD}` требует передачи флага `--config.expand-external-variables` демону Alertmanager (версии 0.27+).

#### ConfigMap

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
      smtp_smarthost: 'mail.corp.internal:587'
      smtp_from: 'alertmanager@corp.internal'
      smtp_auth_username: 'alertmanager'
      smtp_auth_password: '${SMTP_AUTH_PASSWORD}'

    route:
      receiver: 'blackhole'
      group_by: ['alertname', 'namespace', 'job']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      routes:
        - matchers:
            - severity = critical
          receiver: 'oncall-team'
          repeat_interval: 1h
        - matchers:
            - severity = warning
          receiver: 'chat-notifications'
          repeat_interval: 6h

    inhibit_rules:
      # Подавлять предупреждения о сервисе, если узел или namespace недоступен целиком
      - source_matchers:
          - alertname = "NodeDown"
        target_matchers:
          - severity = "warning"
        equal: ['node']

      - source_matchers:
          - severity = "critical"
        target_matchers:
          - severity = "warning"
        equal: ['alertname', 'namespace']

    receivers:
      - name: 'blackhole'

      - name: 'oncall-team'
        email_configs:
          - to: 'sre-oncall@corp.internal'
            send_resolved: true
        webhook_configs:
          - url: '${WEBHOOK_ONCALL_URL}'
            send_resolved: true

      - name: 'chat-notifications'
        webhook_configs:
          - url: '${WEBHOOK_CHAT_URL}'
            send_resolved: true
```

#### Secret и Deployment

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-secrets
  namespace: monitoring
type: Opaque
stringData:
  SMTP_AUTH_PASSWORD: "SuperSecretSmtpPassword"
  WEBHOOK_ONCALL_URL: "http://webhook.internal/oncall"
  WEBHOOK_CHAT_URL: "http://webhook.internal/chat"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
      containers:
      - name: alertmanager
        image: prom/alertmanager:v0.27.0
        args:
          - '--config.file=/etc/alertmanager/alertmanager.yml'
          - '--storage.path=/alertmanager'
          - '--web.listen-address=0.0.0.0:9093'
          - '--config.expand-external-variables'
        envFrom:
        - secretRef:
            name: alertmanager-secrets
        ports:
        - containerPort: 9093
          name: http
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 256Mi
        readinessProbe:
          httpGet:
            path: /-/ready
            port: 9093
          initialDelaySeconds: 3
          periodSeconds: 5
        volumeMounts:
        - name: config
          mountPath: /etc/alertmanager
          readOnly: true
        - name: data
          mountPath: /alertmanager
      volumes:
      - name: config
        configMap:
          name: alertmanager-config
          defaultMode: 0440
      - name: data
        emptyDir: {}
```

#### Проверка и эксплуатация

```bash
# Валидация синтаксиса через amtool с поддержкой подстановки переменных
kubectl exec -n monitoring deploy/alertmanager -c alertmanager -- amtool check-config /etc/alertmanager/alertmanager.yml
# → Checking '/etc/alertmanager/alertmanager.yml'  SUCCESS
# → Found 0 custom templates

# Проверка дерева маршрутов в Alertmanager
kubectl exec -n monitoring deploy/alertmanager -c alertmanager -- amtool route show --config.file=/etc/alertmanager/alertmanager.yml
# → Routing tree:
# → default: blackhole
# →   severity = critical: oncall-team
# →   severity = warning: chat-notifications
```

---

### Сценарий 5: PostgreSQL (Patroni/Spilo) — Параметры СУБД для High Availability

Шаблон параметров ядра PostgreSQL и конфигурации Patroni для развертывания отказоустойчивого кластера СУБД в Kubernetes без облачных зависимостей. Использует нативный Kubernetes API в качестве Distributed Configuration Store (DCS). Образы поставляются из GitHub Container Registry (`ghcr.io/zalando/spilo-16:3.3-p1`).

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-patroni-config
  namespace: databases
  labels:
    app.kubernetes.io/name: postgresql
    app.kubernetes.io/component: ha-database
immutable: true
data:
  postgresql.conf: |
    # Параметры соединений и сетевой адресации
    listen_addresses = '*'
    port = 5432
    max_connections = 250

    # Управление оперативной памятью (для пода с 4Gi RAM)
    shared_buffers = 1GB
    effective_cache_size = 3GB
    work_mem = 16MB
    maintenance_work_mem = 256MB
    temp_file_limit = 2GB

    # Write-Ahead Log (WAL) и репликация
    wal_level = replica
    max_wal_size = 4GB
    min_wal_size = 1GB
    checkpoint_completion_target = 0.9
    checkpoint_timeout = 15min
    wal_keep_size = 2GB
    hot_standby = on
    max_wal_senders = 10
    max_replication_slots = 10

    # Оптимизация дискового ввода-вывода
    random_page_cost = 1.1
    effective_io_concurrency = 200

    # Логирование для эксплуатации и SRE
    logging_collector = on
    log_destination = 'stderr'
    log_min_duration_statement = 250
    log_checkpoints = on
    log_connections = on
    log_disconnections = on
    log_lock_waits = on
    log_temp_files = 0
    log_line_prefix = '%m [%p] %q%u@%d '

  pg_hba.conf: |
    # TYPE  DATABASE        USER            ADDRESS                 METHOD
    local   all             all                                     scram-sha-256
    host    all             all             127.0.0.1/32            scram-sha-256
    host    all             all             ::1/128                 scram-sha-256
    host    replication     standby         10.0.0.0/8              scram-sha-256
    host    all             all             10.0.0.0/8              scram-sha-256

  patroni.yaml: |
    scope: pg-ha-cluster
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
        synchronous_mode: false
        postgresql:
          use_pg_rewind: true
          use_slots: true
          parameters:
            shared_buffers: 1GB
            wal_level: replica
            max_connections: 250
    postgresql:
      listen: 0.0.0.0:5432
      connect_address: ${POD_IP}:5432
      data_dir: /home/postgres/pgdata/pgroot/data
      bin_dir: /usr/lib/postgresql/16/bin
      authentication:
        superuser:
          username: postgres
          password: ${PG_SUPERUSER_PASSWORD}
        replication:
          username: standby
          password: ${PG_REPLICATION_PASSWORD}
      custom_conf: /etc/postgresql/custom/postgresql.conf
      pg_hba:
        - local all all scram-sha-256
        - host all all 10.0.0.0/8 scram-sha-256
        - host replication standby 10.0.0.0/8 scram-sha-256
```

#### StatefulSet (фрагмент интеграции)

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql-cluster
  namespace: databases
spec:
  serviceName: postgresql-cluster
  replicas: 3
  selector:
    matchLabels:
      app: postgresql-cluster
  template:
    metadata:
      labels:
        app: postgresql-cluster
        application: spilo
    spec:
      serviceAccountName: postgres-spilo
      containers:
      - name: spilo
        image: ghcr.io/zalando/spilo-16:3.3-p1
        ports:
        - containerPort: 5432
          name: postgres
        - containerPort: 8008
          name: patroni-api
        env:
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: SCOPE
          value: "pg-ha-cluster"
        - name: DCS_ENABLE_KUBERNETES_API
          value: "true"
        - name: KUBERNETES_USE_CONFIGMAPS
          value: "true"
        volumeMounts:
        - name: patroni-config
          mountPath: /etc/postgresql/custom
          readOnly: true
        - name: pgdata
          mountPath: /home/postgres/pgdata
        readinessProbe:
          httpGet:
            path: /readiness
            port: 8008
          initialDelaySeconds: 15
          periodSeconds: 5
      volumes:
      - name: patroni-config
        configMap:
          name: postgres-patroni-config
          defaultMode: 0440
  volumeClaimTemplates:
  - metadata:
      name: pgdata
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi
```

#### Проверка и эксплуатация

```bash
# Проверка состояния кластера Patroni через CLI
kubectl exec -n databases postgresql-cluster-0 -c spilo -- patronictl list
# → + Member               + Host        + Role    + State   + TL + Lag in MB +
# → | postgresql-cluster-0 | 10.244.1.20 | Leader  | running |  1 |           |
# → | postgresql-cluster-1 | 10.244.2.15 | Replica | running |  1 |         0 |
# → | postgresql-cluster-2 | 10.244.3.10 | Replica | running |  1 |         0 |
# → +----------------------+-------------+---------+---------+----+-----------+

# Проверка примененных параметров PostgreSQL
kubectl exec -n databases postgresql-cluster-0 -c spilo -- psql -U postgres -c "SHOW shared_buffers;"
# →  shared_buffers
# → ----------------
# →  1GB
# → (1 row)
```

---

### Сценарий 6: Redis — Высокопроизводительный кэш и брокер

Production-шаблон Redis 7.x для автономного запуска в качестве кэша или брокера задач. Настроен на работу под непривилегированным пользователем, с явным ограничением оперативной памяти (`maxmemory`), политикой вытеснения ключей (`maxmemory-policy allkeys-lru`) и отключением потенциально опасных команд.

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-cache-config
  namespace: caching
  labels:
    app.kubernetes.io/name: redis
    app.kubernetes.io/component: cache
immutable: true
data:
  redis.conf: |
    # Сетевые параметры
    bind 0.0.0.0
    port 6379
    protected-mode yes
    tcp-backlog 511
    timeout 0
    tcp-keepalive 300

    # Управление оперативной памятью (под квоту пода 512Mi)
    maxmemory 384mb
    maxmemory-policy allkeys-lru
    maxmemory-samples 7

    # Снимки данных на диск (RDB Persistence)
    save 900 1
    save 300 10
    save 60 10000
    stop-writes-on-bgsave-error yes
    rdbcompression yes
    rdbchecksum yes
    dbfilename dump.rdb
    dir /data

    # Append Only File (AOF) - отключен для чистого кэша, включен для очередей
    appendonly no

    # Логирование
    loglevel notice
    logfile ""

    # Тюнинг фоновых задач
    hz 10
    dynamic-hz yes
    lazyfree-lazy-eviction yes
    lazyfree-lazy-expire yes
    lazyfree-lazy-server-del yes

    # Безопасность: запрет опасных команд в production
    rename-command FLUSHDB ""
    rename-command FLUSHALL ""
    rename-command DEBUG ""
```

#### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-cache
  namespace: caching
  labels:
    app.kubernetes.io/name: redis
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
      securityContext:
        runAsNonRoot: true
        runAsUser: 999 # redis user
        runAsGroup: 999
        fsGroup: 999
      containers:
      - name: redis
        image: redis:7-alpine
        command: ["redis-server", "/etc/redis/redis.conf"]
        ports:
        - containerPort: 6379
          name: redis
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        readinessProbe:
          exec:
            command: ["sh", "-c", "redis-cli ping | grep -q PONG"]
          initialDelaySeconds: 3
          periodSeconds: 5
        livenessProbe:
          exec:
            command: ["sh", "-c", "redis-cli ping | grep -q PONG"]
          initialDelaySeconds: 10
          periodSeconds: 15
        volumeMounts:
        - name: redis-config
          mountPath: /etc/redis/redis.conf
          subPath: redis.conf
          readOnly: true
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-config
        configMap:
          name: redis-cache-config
          defaultMode: 0440
      - name: redis-data
        emptyDir: {}
```

#### Проверка и эксплуатация

```bash
# Проверка отклика Redis
kubectl exec -n caching deploy/redis-cache -c redis -- redis-cli ping
# → PONG

# Проверка примененных лимитов памяти
kubectl exec -n caching deploy/redis-cache -c redis -- redis-cli config get maxmemory
# → 1) "maxmemory"
# → 2) "402653184"

# Проверка политики вытеснения ключей
kubectl exec -n caching deploy/redis-cache -c redis -- redis-cli config get maxmemory-policy
# → 1) "maxmemory-policy"
# → 2) "allkeys-lru"
```

---

### Сценарий 7: CoreDNS — Кастомные зоны и Split-DNS для On-Premises периметра

Шаблон кастомной конфигурации DNS (`coredns-custom` ConfigMap). Позволяет сисадминам и инженерам эксплуатирующих служб расширять стандартный `Corefile` кластера без модификации системного манифеста Kubernetes Control Plane: перенаправлять внутренние корпоративные зоны (`*.corp.internal`), переопределять статические IP внешних балансировщиков через плагин `hosts` и настраивать split-horizon резолвинг.

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns-custom
  namespace: kube-system
  labels:
    addonmanager.kubernetes.io/mode: EnsureExists
    k8s-app: kube-dns
data:
  # Кастомная зона для внутреннего корпоративного периметра
  corp.server: |
    corp.internal:53 {
        errors
        cache 30
        forward . 10.10.0.10 10.10.0.11 {
            max_concurrent 1000
        }
        prometheus :9153
    }

  # Переопределение локальных статических хостов внутри кластера
  static-hosts.override: |
    hosts {
        10.0.100.50 s3-storage.corp.internal
        10.0.100.51 registry.corp.internal
        10.0.100.52 gitlab.corp.internal
        fallthrough
    }
```

#### Проверка и валидация

```bash
# Проверка считывания кастомных блоков CoreDNS
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50 | grep -E "plugin|reload"
# → [INFO] plugin/reload: Running configuration SHA512 = 9a2b...
# → [INFO] Reloading
# → [INFO] Reloading complete

# Тестирование резолвинга корпоративной зоны из тестового пода
kubectl run dns-test --image=busybox:1.36 --restart=Never --rm -it -- nslookup gitlab.corp.internal
# → Server:         10.96.0.10
# → Address:        10.96.0.10:53
# → Name:   gitlab.corp.internal
# → Address: 10.0.100.52
```

---

### Сценарий 8: Fluent Bit — Агент сбора логов на узлах (DaemonSet)

Шаблон агента сбора логов Fluent Bit, оптимизированный для работы в bare-metal/on-premise кластерах Kubernetes. Конфигурация считывает системные контейнерные логи (`/var/log/pods`), парсит формат CRI (CRI-O / containerd), обогащает записи метаданными Kubernetes API и передает их в агрегатор логов (например, VictoriaLogs или централизованный syslog).

#### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-agent-config
  namespace: logging
  labels:
    app.kubernetes.io/name: fluent-bit
immutable: true
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush         1
        Log_Level     info
        Daemon        off
        Parsers_File  /fluent-bit/etc/parsers.conf
        Storage.path  /var/log/fluent-bit/buffer
        Storage.sync  normal
        Storage.checksum off
        Storage.backlog.mem_limit 15M

    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/pods/*/*/*.log
        multiline.parser  cri
        DB                /var/log/fluent-bit/flb_kube.db
        Mem_Buf_Limit     50MB
        Skip_Long_Lines   On
        Refresh_Interval  10

    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix     kube.var.log.pods.
        Merge_Log           On
        Merge_Log_Key       log_processed
        Keep_Log            Off
        K8S-Logging.Parser  On
        K8S-Logging.Exclude On

    [OUTPUT]
        Name          stdout
        Match         kube.*
        Format        json_lines

  parsers.conf: |
    [PARSER]
        Name        cri
        Format      regex
        Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L%z
```

#### DaemonSet (фрагмент)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app.kubernetes.io/name: fluent-bit
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
      tolerations:
      - key: node-role.kubernetes.io/control-plane
        operator: Exists
        effect: NoSchedule
      containers:
      - name: fluent-bit
        image: fluent/fluent-bit:3.1
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        volumeMounts:
        - name: config
          mountPath: /fluent-bit/etc/
        - name: varlog
          mountPath: /var/log
          readOnly: true
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: fluent-bit-agent-config
          defaultMode: 0440
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
```

#### Проверка и эксплуатация

```bash
# Проверка логов агента Fluent Bit на узле
kubectl logs -n logging -l app=fluent-bit --tail=30
# → [2026/10/13 19:35:00] [ info] [engine] started (pid=1)
# → [2026/10/13 19:35:00] [ info] [input:tail:tail.0] inotify_fs_add(): wd=1 /var/log/pods

# Проверка парсинга и обогащения метаданными Kubernetes
kubectl logs -n logging -l app=fluent-bit --tail=5 | grep "kubernetes"
# → {"time":"...","stream":"stdout","log":"...","kubernetes":{"pod_name":"...","namespace_name":"production"}}
```

---

### Сценарий 9: Паттерн динамической шаблонизации через InitContainer (`envsubst`)

Паттерн для сервисов, которые не поддерживают нативное чтение переменных окружения внутри файлов конфигурации (например, старые версии демонов, статические web-серверы или специализированный софт), но требуют инъекции паролей из `Secret` в тело конфигурации. Исходный шаблон без секретов хранится в `ConfigMap`, а результирующий рабочий файл генерируется в `emptyDir` перед стартом основного контейнера.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dynamic-templated-app
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dynamic-app
  template:
    metadata:
      labels:
        app: dynamic-app
    spec:
      initContainers:
      - name: render-config
        image: alpine:3.20
        command: ["/bin/sh", "-c"]
        args:
          - |
            apk add --no-cache gettext
            envsubst < /config-template/app.conf.tpl > /rendered-config/app.conf
            chmod 0400 /rendered-config/app.conf
        envFrom:
        - secretRef:
            name: app-db-credentials
        volumeMounts:
        - name: raw-template
          mountPath: /config-template
          readOnly: true
        - name: shared-rendered-dir
          mountPath: /rendered-config
      containers:
      - name: main-app
        image: alpine:3.20
        command: ["/bin/sh", "-c", "cat /etc/app/app.conf && sleep 3600"]
        volumeMounts:
        - name: shared-rendered-dir
          mountPath: /etc/app
          readOnly: true
      volumes:
      - name: raw-template
        configMap:
          name: app-template-config
          defaultMode: 0440
      - name: shared-rendered-dir
        emptyDir:
          medium: Memory
```

---

## Операции и команды

Сводка команд для проверки синтаксиса шаблонов, отладки монтирования и отправки сигналов обновления в production-окружениях:

### Предварительная валидация манифестов

| Задача | Команда | Ожидаемый результат / Описание |
|---|---|---|
| Проверка синтаксиса через API | `kubectl apply --dry-run=server -f <manifest.yaml>` | `# → configmap/<name> configured (server dry run)` |
| Строгая проверка схемы Kubernetes | `kubeconform -summary -strict -kubernetes-version 1.30.0 <manifest.yaml>` | `# → Summary: 1 resources found, 1 valid, 0 invalid` |
| Поиск отличий перед применением | `kubectl diff -f <manifest.yaml>` | Возвращает diff в формате unified diff |

### Валидация синтаксиса специализированными линтерами

```bash
# Валидация Nginx
kubectl exec deploy/nginx-proxy -c nginx -- nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok

# Валидация HAProxy
kubectl exec deploy/haproxy-lb -c haproxy -- haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Валидация конфигурации Prometheus
kubectl exec deploy/prometheus-server -c prometheus -- promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS: 0 rule files found

# Валидация конфигурации Alertmanager
kubectl exec deploy/alertmanager -c alertmanager -- amtool check-config /etc/alertmanager/alertmanager.yml
# → SUCCESS: 0 rule files found
```

### Отладка смонтированных файлов внутри Pod

```bash
# Проверка структуры ссылок атомарного тома (каталог)
kubectl exec deploy/nginx-proxy -c nginx -- ls -la /etc/nginx/conf.d/
# → lrwxrwxrwx 1 root root ..data -> ..2026_10_13_19_40_00.123456789
# → lrwxrwxrwx 1 root root default.conf -> ..data/default.conf

# Проверка целевого пути симлинка
kubectl exec deploy/nginx-proxy -c nginx -- readlink -f /etc/nginx/conf.d/default.conf
# → /etc/nginx/conf.d/..2026_10_13_19_40_00.123456789/default.conf

# Проверка хэша содержимого файла
kubectl exec deploy/nginx-proxy -c nginx -- sha256sum /etc/nginx/conf.d/default.conf
```

### Управление жизненным циклом и Rollout

```bash
# Перезагрузка Nginx без рестарта пода (Hot Reload через SIGHUP)
kubectl exec deploy/nginx-proxy -c nginx -- nginx -s reload

# Перезагрузка Prometheus через HTTP API
kubectl exec deploy/prometheus-server -c prometheus -- wget -qO- --post-data='' http://localhost:9090/-/reload

# Плавный перезапуск контроллера для применения subPath или immutable ConfigMap
kubectl rollout restart deployment/nginx-proxy -n production
# → deployment.apps/nginx-proxy restarted

# Отслеживание завершения плавного перезапуска
kubectl rollout status deployment/nginx-proxy -n production --timeout=90s
# → deployment "nginx-proxy" successfully rolled out
```

---

## Диагностика и устранение неполадок

| Проблема | Диагностика | Причина | Решение |
|---|---|---|---|
| `CreateContainerConfigError` | `kubectl describe pod <name>` → `Events` | Указанный в `volumes.configMap.name` или `envFrom` ConfigMap не существует в данном namespace. | Проверьте namespace и имя ConfigMap. Примените манифест ConfigMap перед запуском Deployment. |
| **Mount Shadowing** (пропали системные файлы образа) | `kubectl exec <pod> -- ls /etc/nginx` показывает только примонтированный файл | Том смонтирован напрямую в `/etc/nginx` вместо подпапки (`/etc/nginx/conf.d`) или без `subPath`. | Монтируйте в подкаталоги расширений либо используйте `subPath: nginx.conf` для точечной замены файла. |
| Файл в поде **не обновляется** после изменения ConfigMap | `kubectl exec <pod> -- cat /path/to/file` показывает старую версию | Файл смонтирован через `subPath`. Kubelet не синхронизирует иноды файлов, подключенных через bind mount. | Выполните `kubectl rollout restart deployment/<name>` либо перейдите на монтирование каталога без `subPath`. |
| Изменение тома не дошло до приложения | `ls -la` показывает новый симлинк `..data`, но сервис отдает старые ответы | Приложение прочитало файл при старте и держит дескриптор в памяти, не слушая inotify/SIGHUP. | Отправьте сигнал `SIGHUP` процессору (`nginx -s reload`) или выполните `kubectl rollout restart`. |
| `CrashLoopBackOff` при старте | `kubectl logs <pod> -c <container> --previous` | Синтаксическая ошибка в теле конфига (пропущенная точка с запятой, невалидный YAML/JSON). | Запустите линтер (`nginx -t`, `promtool check config`) на этапе CI/CD до применения манифеста в кластере. |
| `Read-only file system` | Логи пода содержат ошибку записи в лог-файл или pid-файл | Сервис пытается писать временные данные в каталог, смонтированный с `readOnly: true`. | Перенесите логи и pid в отдельные тома `emptyDir` (например, `/tmp`, `/var/cache`, `/var/log`). |
| Переменная `${SECRET_VAL}` не раскрывается в конфиге | В логах сервиса ошибка аутентификации со строкой `${SECRET_VAL}` | Демон не поддерживает автоматическую подстановку ENV в текстовые конфиги. | Используйте флаг поддержки (например, `--config.expand-external-variables` в Alertmanager) или InitContainer `envsubst`. |
| Ошибка размера ConfigMap (> 1 MiB) | `Error from server (RequestEntityTooLarge): ... limit 1048576 bytes` | Размер данных в ConfigMap превышает жесткое ограничение `etcd` (1 MiB на объект). | Разделите конфиг на несколько ConfigMap, сожмите данные (`gzip`) или вынесите файлы на PersistentVolume. |

---

## Лучшие практики

1. **Используйте `immutable: true` в паре с GitOps:**
   Объявление объекта неизменяемым блокирует модификации «на лету» через `kubectl edit`, исключает конфигурационный дрейф между подами и снимает нагрузку с Control Plane `etcd`. Обновление выполняется через генерацию нового имени с суффиксом хэша контента (Kustomize `configMapGenerator` или Helm sha256).
2. **Всегда монтируйте с `readOnly: true` и `defaultMode: 0440`:**
   Предотвращает случайную перезапись конфигурации процессами внутри контейнера. Права `0440` гарантируют доступ для чтения владельцу и группе, исключая доступ для посторонних процессов при многопользовательском запуске.
3. **Запускайте сервисы от Non-Root пользователей:**
   Все шаблоны должны явно декларировать `securityContext`: `runAsNonRoot: true`, `allowPrivilegeEscalation: false`. Для каталогов, требующих записи (логи, кэши, сокеты, pid-файлы), монтируйте изолированные тома `emptyDir` с выделенными путями (`/tmp`, `/var/cache`).
4. **Согласовывайте лимиты памяти в ConfigMap с ресурсами Pod:**
   Внутренние лимиты демонов (`maxmemory` в Redis, `shared_buffers` в PostgreSQL, `worker_connections` в Nginx/HAProxy) должны составлять не более **70–80%** от значения `resources.limits.memory` пода. Это оставляет резерв операционной системе и контейнерному рантайму, предотвращая падение по `OOMKilled`.
5. **Предотвращайте Mount Shadowing:**
   Никогда не монтируйте том ConfigMap целиком в системные корневые директории (`/etc`, `/usr`). Всегда монтируйте в выделенные директории для оверлеев (`/etc/nginx/conf.d`, `/etc/coredns/custom`) либо монтируйте файл точечно.
6. **Разделяйте статику и секреты:**
   Строго разделяйте неконфиденциальные параметры (таймауты, буферы, маршруты) и чувствительные данные (пароли, закрытые ключи, токены доступа). Секреты должны монтироваться исключительно из объектов `Secret`.

---

## Дополнительная информация

### Матрица поддержки Hot Reload и методов перезагрузки

| Сервис | Hot Reload | Метод отправки сигнала / триггер | Рекомендуемый тип монтирования |
|---|---|---|---|
| **Nginx** | Да | `nginx -s reload` или сигнал `SIGHUP` | Каталог `/etc/nginx/conf.d` + `subPath` для `nginx.conf` |
| **HAProxy** | Да | Сигнал `SIGHUP` (POSIX signal) | Том `subPath` с правами `0440` |
| **Prometheus** | Да | POST-запрос на `/-/reload` (`--web.enable-lifecycle`) | Каталог `/etc/prometheus` без `subPath` |
| **Alertmanager** | Да | POST-запрос на `/-/reload` | Каталог `/etc/alertmanager` без `subPath` |
| **PostgreSQL (Patroni)** | Частично | `patronictl reload` (для динамических параметров) | Каталог `/etc/postgresql/custom` |
| **Redis** | Нет (требует рестарт) | `kubectl rollout restart deployment/redis` | `subPath: redis.conf` с правами `0440` |
| **CoreDNS** | Да | Автоматически через плагин `reload` (период 2s) | ConfigMap `coredns-custom` (каталог) |
| **Fluent Bit** | Да | POST-запрос на HTTP-эндпоинт или рестарт пода | Каталог `/fluent-bit/etc/` |

### Автоматический перезапуск через Stakater Reloader

Для сервисов, которые не имеют встроенного inotify-демона, автоматический перезапуск пода при обновлении ConfigMap реализуется через аннотации Stakater Reloader:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-cache
  namespace: caching
  annotations:
    configmap.reloader.stakater.com/reload: "redis-cache-config"
spec:
  # ...
```

> Подробнее о сценариях применения Reloader: [Reloader Usage Scenarios](../../ToolsUtilities/reloader/reloader_usage_scenarios.md)

### См. также

* [Создание ConfigMap](./creation.md) — декларативные и императивные подходы, Kustomize generator.
* [Использование ConfigMap в подах](./pod_usage.md) — детали монтирования томов, atomic symlinks и переменные окружения.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии распространения обновлений и окно расхождения.
* [Неизменяемые ConfigMap](./immutable.md) — глубокий разбор `immutable: true` и оптимизация etcd.
* [Работа с большими конфигурациями](./large_configs.md) — обход лимита 1 MiB в etcd, сжатие и внешние хранилища.
* [Лучшие практики ConfigMap](./best_practices.md) — архитектурные паттерны и стандарты безопасности.
* [HAProxy — архитектура и параметры](../../../WebServers/haproxy_overview.md) — детальный разбор stick tables и многопоточности HAProxy.
* [Zalando Spilo манифесты](../../../Databases/PostgreSQL/Operations/zalando_spilo_manifests.md) — развертывание отказоустойчивого PostgreSQL через прямые манифесты.
