# StatefulSet: Мониторинг БД через Exporter Sidecar

## Определения

**Exporter Sidecar** — паттерн развёртывания агента сбора метрик (postgres_exporter, mysqld_exporter, mongodb_exporter) как бокового контейнера внутри пода StatefulSet. Exporter подключается к БД по локальному адресу (`127.0.0.1`) и экспонирует метрики в формате Prometheus на отдельном порту, который скрапливается ServiceMonitor.

## Предварительные требования

1.  StatefulSet с работающей БД: **[Практическое руководство](./statefulset_practical_guide.md)**.
2.  Prometheus в кластере (kube-prometheus-stack или отдельный).
3.  Понимание Sidecar-паттернов: **[Sidecar Patterns](../../Base/Pod/pod_sidecar_patterns.md)**.

## Основные концепции

### Почему sidecar, а не отдельный Deployment?

| Подход | Преимущество | Недостаток |
|:---|:---|:---|
| **Sidecar в StatefulSet** | Exporter обращается к БД через `127.0.0.1` — нет сетевого overhead, не нужен Service для метрик, метрики привязаны к конкретной реплике | Увеличивает resource usage每个 пода, логика мониторинга в манифесте приложения |
| **Отдельный Deployment + Service** | Изолированная логика, общие метрики для всех реплик | Сетевой hop, нужен Service/ Endpoints, нет привязки к конкретной реплике, требуется RBAC для доступа к БД извне |

**Рекомендация:** sidecar — предпочтительный паттерн для StatefulSet, потому что каждая реплика БД уникальна (мастер/репlica, индекс) и exporter должен знать, какую реплику он мониторит.

### postgres_exporter как sidecar

**postgres_exporter** — агент, собирающий метрики PostgreSQL и экспонирующий их в формате Prometheus. Подключается к БД через regular SQL-соединение.

Ключевые метрики, пороги алертов и настройка `pg_hba.conf` описаны в **[PostgreSQL: Мониторинг через Prometheus](../../../Ansible/examples/postgresql_prometheus_monitoring.md)**. Ниже — специфика развёртывания как sidecar в Kubernetes StatefulSet.

**Манифест StatefulSet с postgres_exporter sidecar:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      # Основной контейнер PostgreSQL
      - name: postgres
        image: postgres:16
        ports:
        - containerPort: 5432
          name: postgres
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: password
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"

      # Sidecar: postgres_exporter
      - name: postgres-exporter
        image: prometheuscommunity/postgres-exporter:v0.16.0
        ports:
        - containerPort: 9187
          name: metrics
        env:
        - name: DATA_SOURCE_URI
          value: "127.0.0.1:5432/postgres?sslmode=disable"
        - name: DATA_SOURCE_USER
          value: "postgres"
        - name: DATA_SOURCE_PASS
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: password
        - name: PG_EXPORTER_EXTEND_QUERY_PATH
          value: /etc/postgres-exporter/queries.yaml
        resources:
          requests:
            cpu: "50m"
            memory: "64Mi"
          limits:
            cpu: "100m"
            memory: "128Mi"
        volumeMounts:
        - name: exporter-config
          mountPath: /etc/postgres-exporter
          readOnly: true

      volumes:
      - name: exporter-config
        configMap:
          name: postgres-exporter-queries
```

**ConfigMap с кастомными запросами:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-exporter-queries
data:
  queries.yaml: |
    pg_replication:
      query: |
        SELECT
          CASE WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn()
            THEN 0
            ELSE EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())
          END AS lag
      master: true
      metrics:
        - lag:
            usage: "GAUGE"
            description: "Replication lag in seconds"
    pg_stat_user_tables:
      query: |
        SELECT
          schemaname,
          relname,
          n_tup_ins,
          n_tup_upd,
          n_tup_del,
          n_live_tup,
          n_dead_tup
        FROM pg_stat_user_tables
      metrics:
        - schemaname:
            usage: "LABEL"
            description: "Schema name"
        - relname:
            usage: "LABEL"
            description: "Table name"
        - n_tup_ins:
            usage: "COUNTER"
            description: "Rows inserted"
        - n_tup_upd:
            usage: "COUNTER"
            description: "Rows updated"
        - n_tup_del:
            usage: "COUNTER"
            description: "Rows deleted"
        - n_live_tup:
            usage: "GAUGE"
            description: "Live rows"
        - n_dead_tup:
            usage: "GAUGE"
            description: "Dead rows"
```

**ServiceMonitor для Prometheus:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: postgres-exporter
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: postgres
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

### mysqld_exporter как sidecar

**mysqld_exporter** — агент для MySQL/MariaDB, собирающий метрики через SQL-запросы к information_schema и performance_schema.

Ключевые метрики и настройка пользователя `monitor` описаны в **[MySQL: Мониторинг](../../../Databases/MySQL/monitoring.md)**. Нише — специфика развёртывания как sidecar в Kubernetes StatefulSet.

**Манифест StatefulSet с mysqld_exporter sidecar:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  serviceName: mysql
  replicas: 3
  selector:
    matchLabels:
      app: mysql
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
      # Основной контейнер MySQL
      - name: mysql
        image: mysql:8.0
        ports:
        - containerPort: 3306
          name: mysql
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/mysql
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"

      # Sidecar: mysqld_exporter
      - name: mysqld-exporter
        image: prom/mysqld-exporter:v0.15.1
        ports:
        - containerPort: 9104
          name: metrics
        env:
        - name: DATA_SOURCE_NAME
          value: "exporter:$(MYSQL_EXPORTER_PASSWORD)@(127.0.0.1:3306)/"
        - name: MYSQL_EXPORTER_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials
              key: password
        args:
        - "--collect.info_schema.processlist"
        - "--collect.info_schema.innodb_metrics"
        - "--collect.global_status"
        - "--collect.global_variables"
        - "--collect.slave_status"
        - "--collect.engine_innodb_status"
        resources:
          requests:
            cpu: "50m"
            memory: "64Mi"
          limits:
            cpu: "100m"
            memory: "128Mi"
```

**Создание пользователя exporter в MySQL:**

```sql
-- Выполнить в init-контейнере или при первичной инициализации
CREATE USER 'exporter'@'127.0.0.1' IDENTIFIED BY 'strong-password';
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'127.0.0.1';
FLUSH PRIVILEGES;
```

**ServiceMonitor:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mysql-exporter
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: mysql
  endpoints:
  - port: metrics
    interval: 30s
```

### Native Sidecar (Kubernetes 1.29+/GA 1.33)

Для exporter'ов рекомендуется использовать **Native Sidecar** — init-контейнер с `restartPolicy: Always`. Преимущества:

1. **Порядок запуска**: exporter стартует до основного контейнера и блокирует его, пока не будет готов (readiness probe exporter'а).
2. **Порядок завершения**: при удалении пода основной контейнер получает SIGTERM первым; exporter продолжает работать до завершения всех метрик.
3. **Ресурсы**: init-контейнеры учитываются отдельно в QoS, не конкурируют за CPU/memory с основным контейнером.

```yaml
spec:
  initContainers:
  - name: postgres-exporter
    image: prometheuscommunity/postgres-exporter:v0.16.0
    restartPolicy: Always  # Native Sidecar (GA v1.33)
    ports:
    - containerPort: 9187
      name: metrics
    env:
    - name: DATA_SOURCE_URI
      value: "127.0.0.1:5432/postgres?sslmode=disable"
    - name: DATA_SOURCE_USER
      value: "postgres"
    - name: DATA_SOURCE_PASS
      valueFrom:
        secretKeyRef:
          name: postgres-credentials
          key: password
    readinessProbe:
      httpGet:
        path: /metrics
        port: 9187
      initialDelaySeconds: 5
      periodSeconds: 10
```

### Grafana Dashboard

Готовые дашборды для postgres_exporter и mysqld_exporter доступны на [grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/) (поиск по `postgres` или `mysql`). Импорт через Grafana UI: Dashboards → Import → вставить ID.

### Алерты (PrometheusRule)

Готовые PrometheusRule для postgres_exporter и mysqld_exporter с описанием каждого алерта см. в **[PostgreSQL: Мониторинг](../../../Ansible/examples/postgresql_prometheus_monitoring.md)** и **[MySQL: Мониторинг](../../../Databases/MySQL/monitoring.md)**. Для Kubernetes используется объект `PrometheusRule` вместо файлов правил:

### Практические сценарии

#### Сценарий: Мониторинг кворумной PostgreSQL (Patroni + 3 реплики)

```bash
# 1. Развернуть StatefulSet с exporter sidecar
kubectl apply -f postgres-statefulset.yaml

# 2. Проверить метрики каждой реплики
kubectl port-forward postgres-0 9187:9187 &
curl -s http://localhost:9187/metrics | grep pg_up
# → pg_up 1

kubectl port-forward postgres-1 9188:9187 &
curl -s http://localhost:9188/metrics | grep pg_stat_replication_lag
# → pg_stat_replication_lag 0.5

# 3. Проверить ServiceMonitor
kubectl get servicemonitor postgres-exporter -o yaml
# →endpoints:
#   - port: metrics
#     interval: 30s

# 4. Проверить, что Prometheus скрапливает метрики
# В Prometheus UI: Status → Targets → postgres-exporter → UP
```

#### Сценарий: Диагностика проблем с exporter'ом

```bash
# Проблема: exporter не стартует (CrashLoopBackOff)
kubectl logs postgres-0 -c postgres-exporter --previous
# → caller=main.go:170 msg="Error opening connection" err="dial tcp 127.0.0.1:5432: connect: connection refused"
# Решение: основной контейнер ещё не готов. Используйте Native Sidecar с readinessProbe.

# Проблема: метрики не скрапливаются
kubectl port-forward postgres-0 9187:9187
curl http://localhost:9187/metrics
# → пусто или ошибка
# Проверить: DATA_SOURCE_URI, DATA_SOURCE_USER, DATA_SOURCE_PASS

# Проблема: высокий CPU usage exporter'ом
# Решение: увеличить interval в ServiceMonitor (30s → 60s)
# или уменьшить количество collectors
```

## Дополнительная информация

### Ресурсы для exporter sidecar

| Ресурс | Рекомендуемое | Максимальное |
|:---|:---|:---|
| CPU request | 50m | 100m |
| Memory request | 64Mi | 128Mi |
| CPU limit | 100m | 200m |
| Memory limit | 128Mi | 256Mi |

### См. также

*   **[Sidecar Patterns](../../Base/Pod/pod_sidecar_patterns.md)** — жизненный цикл sidecar.
*   **[Native Sidecar](../../Base/Pod/pod_init_containers.md)** — Native Sidecar в Kubernetes.
*   **[postgres_exporter — Ansible](../../../Ansible/examples/postgresql_prometheus_monitoring.md)** — развёртывание через Ansible.
*   **[mysqld_exporter — мониторинг](../../../Databases/MySQL/monitoring.md)** — настройка mysqld_exporter.
*   **[Ключевые метрики StatefulSet](./statefulset_best_practices.md#ключевые-метрики-для-алертинга)** — алерты для kube-state-metrics.
*   **[Monitoring Architecture](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — архитектура сбора метрик.
