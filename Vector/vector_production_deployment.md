# Vector: Production-развёртывание и эксплуатация

**Актуально для:** Vector 0.58.0

## Определения

- **DaemonSet (агент)** — один экземпляр Vector на каждом узле кластера для сбора логов локально с хоста.
- **Deployment (агрегатор)** — централизованный экземпляр Vector для тяжёлой обработки, enrichment и доставки в хранилище.
- **Health Check** — проверка работоспособности через HTTP `/health` endpoint (порт 8686 по умолчанию).
- **High Availability (HA)** — развёртывание нескольких aggregator-инстансов с балансировкой нагрузки для отказоустойчивости.
- **Graceful Shutdown** — плавное завершение: дожидание опорожнения буфера и закрытие соединений перед остановкой.
- **Rolling Update** — обновление с сохранением доступности: постепенная замена инстансов без простоя.

## Архитектура production-развертывания

Типичная production-архитектура Vector состоит из двух ролей:

```
┌─────────────┐    ┌─────────────┐
│  Node 1      │    │  Node 2      │
│  Vector Agent │   │  Vector Agent │
│  (journald,   │   │  (journald,   │
│   file, docker)│   │   file, docker)│
└──────┬───────┘   └──────┬───────┘
       │                     │
       ▼                     ▼
┌─────────────┐    ┌─────────────┐
│ Kafka        │    │ Kafka        │
│ (буфер)      │    │ (буфер)      │
└──────┬───────┘    └──────┬───────┘
       │                     │
       ├─────────────────────┤
       ▼                     ▼
┌─────────────────────────────────┐
│ Vector Aggregator (HA: 2+ инстанса) │
│ • heavy VRL transforms          │
│ • enrichment tables             │
│ • отправка в Loki/Prometheus    │
└─────────────────────────────────┘
```

**Принцип разделения ролей:**

- **Agent** (на хосте): сбор логов, first-pass parsing, локальная буферизация. Лёгкий, минимальная конфигурация.
- **Aggregator** (централизованный): тяжёлая обработка, enrichment, маршрутизация. Масштабируется отдельно.

## Развёртывание на bare-metal / VM через systemd

### Systemd unit с hardening

Базовый unit-файл с security-харднингом (подробнее в [Vector Security](./vector_security.md)):

```ini
# /etc/systemd/system/vector.service
[Unit]
Description=Vector
After=network.target
After=syslog.target

[Service]
Type=notify
ExecStart=/usr/bin/vector --config /etc/vector/vector.yaml --watch-config
Restart=always
RestartSec=5
User=vector
Group=vector
Environment=VECTOR_LOG=info

# Ресурсы
LimitNOFILE=262144
MemoryMax=4G
CPUQuota=200%

# Security hardening (см. vector_security.md для полной таблицы)
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ReadWritePaths=/var/lib/vector /var/log/vector

[Install]
WantedBy=multi-user.target
```

```bash
# Применение и проверка
sudo systemctl daemon-reload
sudo systemctl enable vector
sudo systemctl start vector
systemctl show vector -p MemoryMax,CPUQuota,LimitNOFILE
```

### Health check и readiness probe

```bash
# Health endpoint (встроенный)
curl -s http://127.0.0.1:8686/health
# → {"ok":true}

# Readiness: проверка, что буферы не переполнены
curl -s http://127.0.0.1:8686/metrics | grep "vector_buffer_utilization" | \
  awk '$2 >= 0.9 { exit 1 }'

# Liveness: проверка, что процесс отвечает
curl -sf http://127.0.0.1:8686/health || exit 1
```

### Graceful shutdown

```bash
# 1. Стандартная остановка (graceful, с таймаутом по умолчанию 30 сек)
systemctl stop vector

# 2. С пользовательским таймаутом (systemd)
systemctl kill --signal=SIGTERM --wait vector

# 3. Принудительная остановка (без graceful — ТОЛЬКО при аварии)
kill -9 $(pidof vector)
# → Потребуется восстановление disk buffer:
vector --data-dir /var/lib/vector --repair-data-dir-on-start
```

## Развёртывание в Kubernetes

### DaemonSet (Agent)

Сбор логов с каждого узла Kubernetes через CRI-логи:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: vector-agent
  namespace: observability
  labels:
    app: vector-agent
spec:
  selector:
    matchLabels:
      app: vector-agent
  template:
    metadata:
      labels:
        app: vector-agent
    spec:
      serviceAccountName: vector
     Containers:
      - name: vector
        image: timberio/vector:0.58.0-debian  # pinned версия
        securityContext:
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 1000
        env:
        - name: VECTOR_LOG
          value: "info"
        - name: HOSTNAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        volumeMounts:
        - name: config
          mountPath: /etc/vector
          readOnly: true
        - name: data
          mountPath: /var/lib/vector
        - name: logs
          mountPath: /var/log
          readOnly: true
        - name: journal
          mountPath: /var/log/journal
          readOnly: true
        - name: cri
          mountPath: /var/log/pods
          readOnly: true
        - name: secrets
          mountPath: /etc/vector/secrets
          readOnly: true
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8686
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8686
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: config
        configMap:
          name: vector-agent-config
      - name: data
        hostPath:
          path: /var/lib/vector-agent
      - name: logs
        hostPath:
          path: /var/log
      - name: journal
        hostPath:
          path: /var/log/journal
      - name: cri
        hostPath:
          path: /var/log/pods
      - name: secrets
        secret:
          secretName: vector-secrets
```

### Deployment (Aggregator) с HA

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vector-aggregator
  namespace: observability
spec:
  replicas: 2  # HA: минимум 2
  selector:
    matchLabels:
      app: vector-aggregator
  template:
    metadata:
      labels:
        app: vector-aggregator
    spec:
      serviceAccountName: vector
      containers:
      - name: vector
        image: timberio/vector:0.58.0-debian
        securityContext:
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 1000
        volumeMounts:
        - name: config
          mountPath: /etc/vector
          readOnly: true
        - name: data
          mountPath: /var/lib/vector
        - name: secrets
          mountPath: /etc/vector/secrets
          readOnly: true
        resources:
          requests:
            memory: "2Gi"
            cpu: "500m"
          limits:
            memory: "8Gi"
            cpu: "2000m"
        # Агрегаторы используют Kafka consumer group для распределения нагрузки
        # Новые реплики автоматически входят в consumer group
        livenessProbe:
          httpGet:
            path: /health
            port: 8686
          initialDelaySeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8686
          initialDelaySeconds: 10
      volumes:
      - name: config
        configMap:
          name: vector-aggregator-config
      - name: data
        persistentVolumeClaim:
          claimName: vector-aggregator-pvc
      - name: secrets
        secret:
          secretName: vector-secrets
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: vector-aggregator-pdb
  namespace: observability
spec:
  minAvailable: 1  # для replicas: 2, минимум 1 всегда жив
  selector:
    matchLabels:
      app: vector-aggregator
```

### ConfigMap с конфигурацией

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vector-agent-config
  namespace: observability
data:
  vector.yaml: |
    data_dir = "/var/lib/vector"
    api.enabled = true
    api.address = "0.0.0.0:8686"

    [sources.journald]
    type = "journald"
    include_units = ["sshd.service", "containerd.service"]

    [sources.kubernetes_logs]
    type = "file"
    include = ["/var/log/pods/*/*/*.log"]
    ignore_older = 86400

    [transforms.normalize]
    type = "remap"
    inputs = ["journald", "kubernetes_logs"]
    source = '''
      . = parse_json(string!(.message))
    '''

    [sinks.kafka]
    type = "kafka"
    inputs = ["normalize"]
    bootstrap_servers = "kafka-cluster:9092"
    topic = "logs"
```

## High Availability и масштабирование

### Agent: масштабирование по узлам

Agent работает на каждом узле — масштабирование происходит автоматически с добавлением узлов. Настройка:

```toml
# Agent: минимальная нагрузка на хост
[sources.host_metrics]
type = "host_metrics"
scrape_interval_secs = 15
collect_cpu = true
collect_memory = true
collect_disk = true
collect_network = true
# Отключить collect_filesystem для больших дисков
# collect_filesystem = false

# Локальная буферизация на случай недоступности агрегатора
[sinks.kafka]
type = "kafka"
inputs = ["normalize"]
bootstrap_servers = "kafka:9092"
topic = "logs"

[sinks.kafka.buffer]
type = "disk"
max_size = 536870912  # 512 MiB
when_full = "block"
```

### Aggregator: масштабирование через consumer groups

Для Kafka source несколько aggregator-инстансов автоматически распределяют партиции:

```yaml
# Deployment с replicas: 3+
# Kafka source с одинаковым group_id
[sources.kafka_in]
type = "kafka"
bootstrap_servers = "kafka-cluster:9092"
topics = ["logs"]
group_id = "vector-aggregator-v1"  # все реплики используют один group_id
```

**Мониторинг распределения партиций:**

```bash
# Проверка распределения consumer lag
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group vector-aggregator-v1 --describe
# → topic partition current-offset log-end-offset lag consumer-id
```

### Load balancing перед sink

Для sink без встроенной поддержки clustering используйте load balancer:

```toml
# Round-robin между несколькими Loki-репликами
[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoints = [
  "http://loki-0.loki:3100",
  "http://loki-1.loki:3100",
  "http://loki-2.loki:3100"
]
load Balancer = "round_robin"  # или "least_outstanding"
```

## Upgrade и миграция

### Процедура обновления Vector

Vector поддерживает только последнюю minor-версию. Перед обновлением проверяйте [release notes](https://github.com/vectordotdev/vector/blob/master/RELEASES.md):

```bash
# 1. Проверка текущей версии
vector --version
# → vector 0.58.0 (дата, коммит)

# 2. Backup конфигурации и data_dir
tar -czf /backup/vector-config-$(date +%Y%m%d).tar.gz /etc/vector/
rsync -a /var/lib/vector/ /backup/vector-data-$(date +%Y%m%d)/

# 3. Validate конфигурации на новой версии
vector validate /etc/vector/vector.yaml

# 4. Rolling update (K8s: обновление образа в deployment)
kubectl set image deployment/vector-aggregator vector=timberio/vector:0.58.0-debian

# 5. Проверка работы после обновления
vector top --url vector-aggregator-0:8686
```

### Откат (rollback)

```bash
# 1. Остановка Vector
systemctl stop vector

# 2. Возврат бинаря
cp /opt/vector-backup/vector-0.57.0 /usr/bin/vector

# 3. Восстановление data_dir (если есть несовместимость формата)
rm -rf /var/lib/vector/*
rsync -a /backup/vector-data-rollback/ /var/lib/vector/

# 4. Запуск и проверка
systemctl start vector
vector validate /etc/vector/vector.yaml
```

## Capacity Planning

**Пропускная способность (из [Vector Overview](./vector_overview.md#производительность-и-capacity-planning)):**

| Тип данных | Пропускная способность |
| :--- | :--- |
| Unstructured log event (~256 bytes) | ~10 MiB/s/vCPU |
| Structured log event (~768 bytes) | ~25 MiB/s/vCPU |
| Metric event (~256 bytes) | ~25 MiB/s/vCPU |

**Ресурсные требования:**

| Роль | vCPU | Memory | Disk (data_dir) | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| Agent | 1-2 | 1-2 GiB | 1-5 GiB (disk buffer) | На каждом хосте |
| Aggregator | 4-8 | 8-16 GiB | 10-50 GiB (disk buffer) | Зависит от throughput |

**Формула расчёта:**

```
events_per_sec = total_throughput_bytes / avg_event_size
vCPU_needed = events_per_sec * avg_event_size / throughput_per_vcpu
memory_needed = vCPU * 2 GiB  # стартовая точка
disk_needed = throughput_per_sec * retention_seconds * 1.3  # 30% резерв
```

Пример: 100K событий/сек, средний размер 512 байт:
```
throughput = 100000 * 512 = ~50 MiB/s
vCPU_needed = 50 / 25 = 2 vCPU (для structured logs)
memory = 2 * 2 = 4 GiB
```

## Log Rotation и обслуживание

### Ротация логов Vector

```bash
# /etc/logrotate.d/vector
/var/log/vector/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate  # не требует перезапуска Vector
}
```

### Очистка disk buffer

```bash
# Проверка размера data_dir
du -sh /var/lib/vector/
# → 2.3G /var/lib/vector/

# Проверка целостности буфера
vector --data-dir /var/lib/vector --check-data-dir
# → Data dir is valid

# Очистка при необходимости (потеря незакоммиченных событий!)
systemctl stop vector
rm -rf /var/lib/vector/buffers/*
systemctl start vector
```

## Операции и команды

### Мониторинг deployment

```bash
# 1. Проверка статуса systemd
systemctl status vector --no-pager -l

# 2. Проверка health endpoint
curl -sf http://localhost:8686/health && echo "OK"

# 3. Проверка размера буфера
curl -s http://localhost:8686/metrics | grep "buffer_size_bytes"

# 4. Проверка версии и конфигурации
vector --version
vector validate /etc/vector/vector.yaml --deny-warnings

# 5. Проверка нагрузки (K8s)
kubectl top pod -l app=vector-aggregator -n observability
```

## Устранение неполадок

### Pod stuck в CrashLoopBackOff (K8s)

**Диагностика:**

```bash
# 1. Проверка логов
kubectl logs pod/vector-aggregator-xxx -n observability --previous

# 2. Проверка конфигурации
kubectl exec pod/vector-aggregator-xxx -n observability -- vector validate

# 3. Проверка health
kubectl exec pod/vector-aggregator-xxx -n observability -- curl -s http://localhost:8686/health
```

### Disk buffer corruption после SIGKILL

**Симптом:** Vector не стартует с `error: WAL corruption detected`.

**Решение:**

```bash
# 1. Попытка автоматического восстановления
vector --data-dir /var/lib/vector --repair-data-dir-on-start

# 2. Если не помогает — очистка (потеря данных в незакоммиченном буфере)
systemctl stop vector
rm -rf /var/lib/vector/*
systemctl start vector
```

### Buffer переполняется при масштабировании

**Симптом:** `vector_buffer_utilization > 0.95` на новых репликах.

**Решение:**

1.  Увеличьте `buffer.max_size` для новых реплик.
2.  Проверьте `request.concurrency` — для агрегаторов используйте `adaptive`.
3.  Добавьте `request.rate_limit_*` для защиты downstream.

## Лучшие практики

1.  **Всегда pin версию Vector** в Docker image и systemd — избегайте `latest`.
2.  **Disk buffer для критичных пайплайнов** — всегда `buffer.type = "disk"` + `acknowledgements.enabled = true`.
3.  **Graceful shutdown в K8s:** настройте `terminationGracePeriodSeconds: 60` и preStop hook:
    ```yaml
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 15"]
    ```
4.  **PodDisruptionBudget для aggregator** — минимум 1 реплика всегда жив.
5.  **Resource limits:** Agent 1 vCPU/1GiB, Aggregator 4 vCPU/8GiB. Настраивайте в K8s и systemd.
6.  **Health checks:** используйте `/health` endpoint для liveness и readiness.
7.  **CI/CD для конфигов:** `vector validate --deny-warnings` в пайплайне (см. [vector test](./practical_scenarios.md)).
8.  **Upgrade каждые 6 недель** — проверяйте release notes на breaking changes перед обновлением.

## Дополнительная информация

- **Безопасность и харднинг:** [Vector Security](./vector_security.md)
- **Надёжность:** [Vector Reliability](./vector_reliability.md)
- **Мониторинг и алёрты:** [Meta-monitoring — Сценарий 5: Vector + Loki](../Concepts/Observability_and_Monitoring/meta-monitoring.md)
- **Обзор и архитектура:** [Vector Overview](./vector_overview.md)
- **Практические сценарии:** [Practical Scenarios](./practical_scenarios.md)
- **Systemd hardening pattern:** [Neo4j Operations — Жёсткая изоляция службы](../Databases/Neo4j/operations.md)
- **K8s DaemonSet pattern:** [DaemonSet в Kubernetes](../Kubernetes/Base/daemonset.md)
- **Официальная документация:** [Vector Kubernetes](https://vector.dev/docs/administration/deployments/kubernetes/)