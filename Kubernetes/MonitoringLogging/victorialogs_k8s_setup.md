# Развёртывание VictoriaLogs в Kubernetes

## Определения

**VictoriaLogs Stack** — это комплексное решение для сбора, хранения и анализа журналов (логов) в среде Kubernetes. Оно спроектировано для обеспечения высокой производительности при минимальных затратах на ресурсы, что делает его предпочтительной альтернативой ELK и Loki в высоконагруженных кластерах. VictoriaLogs использует schema-less подход — автоматическое обнаружение полей без предварительного описания схемы, что критично для динамичных сред, где форматы логов меняются между версиями приложений.

**vlagent** — высокопроизводительный агент от VictoriaMetrics для сбора логов. В 2026 году он вытесняет Fluent Bit благодаря нативной поддержке LogsQL, автоматическому обнаружению контейнеров и в 4 раза более низкой нагрузке на CPU при сопоставимой пропускной способности.

---

## 1. Архитектура решения

Типовая схема в кластере 2026:
1.  **Сбор данных:** `vlagent` (DaemonSet) с включенным `-kubernetesCollector`. Он автоматически собирает логи с `/var/log/pods`, добавляя метаданные K8s (labels, annotations) без использования тяжелых sidecar-контейнеров.
2.  **Хранение:**
    *   `VLSingle` (Custom Resource) — одиночный инстанс для малых и средних нагрузок.
    *   `VLCluster` (Custom Resource) — распределенная система с независимым масштабированием компонентов приёма (`vlinsert`), хранения (`vlstorage`) и запросов (`vlselect`).
3.  **Визуализация:** Grafana с плагином `victoriametrics-logs-datasource` и встроенный веб-интерфейс **VMUI**.
4.  **Управление:** **VictoriaMetrics Operator** — обеспечивает декларативное управление всем жизненным циклом стека через CRD.

---

## 2. Подготовка и инфраструктура

Для автоматизации TLS-сертификатов и безопасного доступа по HTTPS требуется наличие `cert-manager`.

**Установка cert-manager (v1.19+):**
```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.19.2 --namespace cert-manager --create-namespace --set crds.enabled=true
```

**ClusterIssuer (Let's Encrypt):**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
```

---

## 3. Методы установки

### Вариант А: Одиночный узел (Single Node)
Подходит для большинства средних инсталляций (до нескольких ТБ логов в день). Один под выполняет все функции, что упрощает эксплуатацию.

```bash
helm upgrade --install victoria-logs-single \
  oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-single \
  --namespace victoria-logs --create-namespace --version 0.7.0
```

### Вариант Б: Кластерный режим (Cluster Mode)
Для распределения нагрузки и обеспечения высокой доступности. Позволяет масштабировать `vlinsert` (при росте трафика) и `vlstorage` (при росте объема хранения) независимо.

```bash
helm upgrade --install victoria-logs-cluster \
  oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-cluster \
  --namespace victoria-logs-cluster --create-namespace \
  -f victorialogs-cluster-values.yaml
```

**Пример Ingress в values.yaml для кластера:**
```yaml
vlselect:
  ingress:
    enabled: true
    hosts:
      - name: logs.example.com
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
    tls:
      - hosts: [logs.example.com]
        secretName: victorialogs-tls
```

### Вариант В: VictoriaMetrics Operator (Рекомендуемый для Production)
Использование оператора (v0.68+) позволяет описывать кластер как единый объект.

**Важно:** С версии **v0.68.4** (апрель 2026) изменены стандарты меток `matchLabels` для соответствия `app.kubernetes.io/component`. При обновлении может потребоваться пересоздание ресурсов (manual recreate).

**Пример CRD для развёртывания VLCluster:**
```yaml
apiVersion: operator.victoriametrics.com/v1
kind: VLCluster
metadata:
  name: victorialogs-prod
  namespace: monitoring
spec:
  clusterDomainName: cluster.local
  managedMetadata:
    labels:
      component: vlogs
  requestsLoadBalancer:
    enabled: true # Развертывание vmauth для маршрутизации
    spec:
      replicaCount: 2
  vlinsert:
    replicaCount: 3
    extraArgs:
      insert.maxLineSizeBytes: "1048576" # 1MB для длинных JSON/Stacktraces
      memory.allowedPercent: "80"
  vlselect:
    replicaCount: 3
    extraArgs:
      memory.allowedPercent: "80"
      search.maxQueryDuration: "30s"
  vlstorage:
    replicaCount: 2
    retentionPeriod: 30d
    extraArgs:
      retention.maxDiskSpaceUsageBytes: 900GiB
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 1Ti
          storageClassName: csi-cephfs-hdd
```

---

## 4. Сбор логов (DaemonSet и vlagent)

В 2026 году рекомендуется использовать **vlagent** вместо Fluent Bit для минимизации оверхеда.

### Сравнение производительности (на 10к логов/сек)
| Метрика | vlagent | Fluent Bit |
| :--- | :--- | :--- |
| **CPU** | ~0.5 core | ~2.1 cores |
| **Memory** | ~40 MiB | ~120 MiB |
| **Парсинг** | Нативный (LogsQL) | Lua/Regex |

**Установка сборщика через Helm:**
```bash
helm upgrade --install victoria-logs-collector \
  oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-collector \
  --namespace monitoring --create-namespace \
  -f collector-values.yaml
```

**Пример конфигурации collector-values.yaml:**
```yaml
vlagent:
  enabled: true
  spec:
    k8sCollector:
      enabled: true # Нативный сбор логов контейнеров (New 2026)
    remoteWrite:
      - url: http://victoria-logs-single-addr:9428/insert/jsonline?_stream_fields=pod,container,namespace
        headers:
          VL-Ignore-Fields: ["kubernetes.pod_ip", "kubernetes.node_name"] # Фильтрация лишних метаданных
    extraArgs:
      "lib.logger.format": "json"
      "insert.maxLineSizeBytes": "1048576"
```

---

## 5. Визуализация в Grafana

Для работы требуется плагин `victoriametrics-logs-datasource`. Он позволяет выполнять LogsQL запросы напрямую из Grafana Explore.

**Настройка Datasource в Helm (vmks):**
```yaml
grafana:
  plugins:
    - victoriametrics-logs-datasource
  additionalDataSources:
    - name: VictoriaLogs
      type: victoriametrics-logs-datasource
      url: http://vlselect-prod.monitoring.svc:9481  # URL сервиса vlselect
      jsonData:
        maxLines: 2000
        keepCookies: ["vlogs-tenant-id"] # Для мультитенантности
```

---

## 6. Тестирование и проверка

Для генерации тестовых данных и проверки корректности парсинга JSON используйте `flog`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flog-generator
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: flog
        image: mingrammer/flog
        args: ["--format", "json", "--loop", "--delay", "500ms"]
```

### Процедура проверки:
1.  **Доступность API:** Выполните `curl http://<vlselect-url>/select/logsql/ping` (должен вернуть `pong`).
2.  **Проверка данных:** Зайдите в VMUI (`/select/vmui`) и выполните запрос `* | limit 10`.
3.  **Логи сборщика:** Проверьте отсутствие ошибок `remote_write` в логах DaemonSet `victoria-logs-collector`.

---

## 7. Планирование ресурсов и sizing

Корректное планирование ресурсов критично для стабильной работы стека логирования. VictoriaLogs высокопроизводителен, но неправильные лимиты приводят к потере логов или простоям.

### Формула расчёта хранилища

Объём хранилища зависит от объёма логов, коэффициента сжатия и периода хранения:

```
Storage = (Logs_per_day_raw * Compression_ratio * Retention_days) + 20% reserve
```

**Типичные коэффициенты сжатия VictoriaLogs:**
| Формат логов | Сжатие | Пример: 100 GB сырых за 30 дней |
| :--- | :--- | :--- |
| JSON (структурированные) | 8-15x | 200-375 GB |
| Plain text (неструктурированные) | 5-10x | 300-600 GB |
| Multiline (stacktraces) | 10-20x | 150-300 GB |

**Пример расчёта для кластера 50 нод:**
- 50 нод * 500 MB логов/день = 25 GB/день сырых логов
- Сжатие JSON: ~10x -> 2.5 GB/день на диске
- Retention 30 дней: 75 GB + 20% = **90 GB** на кластер
- Добавьте запас на WAL и метаданные: **120 GB** рекомендуется

### Рекомендуемые ресурсы по компонентам

**VLSingle (до 50 нод, < 50 GB логов/день):**
| Ресурс | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| CPU | 2 cores | 4 cores |
| Memory | 2 GiB | 4 GiB |
| Storage | 50 GiB | 200+ GiB |
| Storage class | HDD (cold) | SSD (hot queries) |

**VLCluster (50-500+ нод):**
| Компонент | CPU | Memory | Replicas | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| `vlinsert` | 2-4 cores | 2-4 GiB | 2-3 | Масштабируется при росте трафика |
| `vlselect` | 2-4 cores | 4-8 GiB | 2-3 | Масштабируется при сложных запросах |
| `vlstorage` | 1-2 cores | 2-4 GiB | 2-3 | Масштабируется при росте объёма данных |

### Оценка CPU и Memory для vlagent (DaemonSet)

На каждую ноду:
- **CPU**: ~0.05 core при 10k логов/сек, ~0.5 core при 100k логов/сек
- **Memory**: ~40 MiB базово + ~1 MiB на 10k активных строк в буфере
- **Рекомендуемые limits**: CPU 1 core, Memory 512 MiB (с запасом на всплески)

### Влияние `_stream_fields` на потребление памяти

Количество уникальных комбинаций значений в полях потока определяет число активных streams. Каждый активный stream потребляет память в vlinsert:

```promql
# Мониторинг числа активных потоков
vl_victorialogs_stream_rows_total
```

**Правило**: Избегайте высококардинальных полей в `_stream_fields` (например, `trace_id`, `request_id`). Используйте их как обычные поля для поиска, а не для группировки потоков.

---

## 8. Безопасность

### RBAC для VictoriaLogs Operator

Оператор требует расширенных прав для управления ресурсами. Минимальный набор прав:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: victoria-logs-operator
rules:
  - apiGroups: ["operator.victoriametrics.com"]
    resources: ["vlclusters", "vlclusters/status", "vlclusters/finalizers"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: ["operator.victoriametrics.com"]
    resources: ["vlsingles", "vlsingles/status"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints", "configmaps", "secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "replicasets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### NetworkPolicy

Ограничьте сетевой доступ к компонентам VictoriaLogs:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: victoria-logs-access
  namespace: victoria-logs
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # vlselect доступен из.namespace Grafana и мониторинга
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - port: 9481
          protocol: TCP
    # vlinsert доступен из namespace с DaemonSet сборщиков
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - port: 9480
          protocol: TCP
    # VictoriaMetrics Operator доступ к API
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: victoria-logs
      ports:
        - port: 8482
          protocol: TCP
  egress:
    # DNS
    - ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Доступ к Kubernetes API (для operator)
    - ports:
        - port: 6443
          protocol: TLS
```

### TLS для компонентов

Для шифрования трафика между компонентами:

```yaml
# В values.yaml кластера:
vlinsert:
  extraArgs:
    - tls.keyFile=/etc/vl-tls/tls.key
    - tls.certFile=/etc/vl-tls/tls.crt
    - tls.clientAuthFile=/etc/vl-tls/ca.crt  # mTLS для vlstorage
vlselect:
  extraArgs:
    - tls.keyFile=/etc/vl-tls/tls.key
    - tls.certFile=/etc/vl-tls/tls.crt
```

Для автоматического управления сертификатами используйте cert-manager (см. раздел "Подготовка и инфраструктура").

### Multi-tenancy

VictoriaLogs поддерживает разделение данных по тенантам через HTTP-заголовок `X-Scope-OrgID`. Это позволяет нескольким команд или окружениям использовать общий кластер:

```yaml
# В конфигурации vlagent:
remoteWrite:
  - url: http://vlinsert:9480/insert/jsonline
    headers:
      X-Scope-OrgID: "team-a"  # или "namespace:production"
```

Для маршрутизации и контроля доступа используйте `vmauth` как точку входа перед кластером (см. [Внутреннее устройство VictoriaLogs](../../VictoriaMetrics/victorialogs_internals.md)).

---

## 9. Retention и ротация логов

### Настройка retention

Retention определяет, как долго логи хранятся на диске. В кластерном режиме настройка происходит на компоненте `vlstorage`:

```yaml
# В values.yaml кластера:
vlstorage:
  retentionPeriod: 30d  # или "30d", "6M", "1y"
  extraArgs:
    retention.maxDiskSpaceUsageBytes: 900GiB  # Жёсткий лимит диска
```

**Поведение при достижении лимитов:**
- Если `retention.maxDiskSpaceUsageBytes` достигнут, VictoriaLogs начинает удалять самые старые суточные разделы (Partition) независимо от `retentionPeriod`.
- Если `retentionPeriod` достигнут, удаляются разделы старше указанного периода.
- Приоритет: `maxDiskSpaceUsageBytes` > `retentionPeriod`. Если оба заданы, сначала проверяется дисковое пространство.

### Retention для VLSingle

```yaml
# values.yaml для single-node:
persistentVolume:
  enabled: true
  size: 200Gi
extraArgs:
  retentionPeriod: 30d
  retention.maxDiskSpaceUsageBytes: 180GiB  # ~90% от объёма PV
```

### Долгосрочное хранение (Tiered Storage)

Для сценариев, где логи нужно хранить долго ( compliance, аудит), используйте tiered storage:

```yaml
vlstorage:
  extraArgs:
    retentionPeriod: 365d
    retention.maxDiskSpaceUsageBytes: 500GiB
    # Автоматическая компакция старых данных
    storage.maxBigPartSize: 4GiB
```

Для архивирования в объектное хранилище (S3/MinIO) используйте `vmbackup` (см. раздел "Backup и восстановление").

### Мониторинг использования диска

```promql
# Использование диска vlstorage
vl_victorialogs_storage_size_bytes

# Предупреждение при заполнении > 80%
(1 - vl_victorialogs_storage_size_bytes / vl_victorialogs_storage_limit_bytes) < 0.2
```

---

## 10. Мета-мониторинг VictoriaLogs

Мониторинг самого стека логирования критичен для обеспечения его надёжности. VictoriaLogs предоставляет метрики на эндпоинте `/metrics` (порт 8482 для vlstorage, 9480 для vlinsert, 9481 для vlselect).

### ServiceMonitor для VictoriaLogs

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: victoria-logs
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  namespaceSelector:
    matchNames:
      - victoria-logs
  selector:
    matchLabels:
      app.kubernetes.io/name: victoria-logs-cluster
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
      scrapeTimeout: 25s
```

### Ключевые метрики

**Приём данных (vlinsert):**
```promql
# Пропускная способность приёма (строк/сек)
rate(vl_victorialogs_inserted_rows_total[5m])

# Ошибки приёма
rate(vl_victorialogs_insert_errors_total[5m])

# Размер буфера в памяти
vl_victorialogs_memory_allowed_bytes - vl_victorialogs_memory_available_bytes
```

**Хранение (vlstorage):**
```promql
# Размер данных на диске
vl_victorialogs_storage_size_bytes

# Скорость записи на диск (bytes/sec)
rate(vl_victorialogs_storage_disk_write_bytes_total[5m])

# Количество активных parts
vl_victorialogs_storage_parts_count
```

**Запросы (vlselect):**
```promql
# P99 задержка запросов LogsQL
histogram_quantile(0.99, rate(vl_victorialogs_query_duration_seconds_bucket[5m]))

# Количество одновременных запросов
vl_victorilogs_concurrent_queries
```

### Alerting Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: victoria-logs-alerts
  namespace: monitoring
spec:
  groups:
    - name: victoria-logs
      rules:
        # Критично: Ошибки приёма логов
        - alert: VictoriaLogsInsertErrors
          expr: rate(vl_victorialogs_insert_errors_total[5m]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "VictoriaLogs: ошибки приёма логов"

        # Предупреждение: Заполнение диска > 85%
        - alert: VictoriaLogsDiskSpaceLow
          expr: |
            vl_victorialogs_storage_size_bytes
            / vl_victorialogs_storage_limit_bytes > 0.85
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "VictoriaLogs: заполнение диска > 85%"

        # Критично: Высокая задержка запросов
        - alert: VictoriaLogsHighQueryLatency
          expr: histogram_quantile(0.99, rate(vl_victorialogs_query_duration_seconds_bucket[5m])) > 10
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "VictoriaLogs: p99 задержки запросов > 10s"

        # Предупреждение: Количество потоков превышает лимит
        - alert: VictoriaLogsStreamLimitApproaching
          expr: |
            vl_victorialogs_stream_rows_total
            / vl_victorialogs_stream_rows_limit > 0.9
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "VictoriaLogs: приближение к лимиту числа потоков"
```

---

## 11. Backup и восстановление

### Резервное копирование через vmbackup

VictoriaLogs поддерживает инкрементальное резервное копирование через утилиту `vmbackup`. Она создаёт снапшот данных и загружает их в объектное хранилище (S3, MinIO, GCS):

```yaml
apiVersion: apps/v1
kind: CronJob
metadata:
  name: victoria-logs-backup
  namespace: victoria-logs
spec:
  schedule: "0 2 * * *"  # Ежедневно в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: vmbackup
              image: victoriametrics/vmbackup:v1.110.0
              args:
                - -storageDataPath=/victoria-logs-data
                - -snapshot.createURL=http://vlstorage-0.vlstorage:8482/snapshot/create
                - -backupsPath=s3://my-backups/victoria-logs
                - -s3.endpoint=s3.amazonaws.com
                - -s3.accessKeyID=$(AWS_ACCESS_KEY_ID)
                - -s3.secretAccessKey=$(AWS_SECRET_ACCESS_KEY)
                - -s3.region=us-east-1
              env:
                - name: AWS_ACCESS_KEY_ID
                  valueFrom:
                    secretKeyRef:
                      name: aws-credentials
                      key: access-key
                - name: AWS_SECRET_ACCESS_KEY
                  valueFrom:
                    secretKeyRef:
                      name: aws-credentials
                      key: secret-key
              volumeMounts:
                - name: data
                  mountPath: /victoria-logs-data
                  readOnly: true
          restartPolicy: OnFailure
          volumes:
            - name: data
              persistentVolumeClaim:
                claimName: vlstorage-victorialogs-prod-vlstorage-0
```

### Восстановление

```bash
# 1. Остановить vlstorage
kubectl scale statefulset vlstorage -n victoria-logs --replicas=0

# 2. Запустить vmrestore
kubectl run vmrestore --rm -it \
  --image=victoriametrics/vmrestore:v1.110.0 \
  --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"vmrestore","args":["-storageDataPath=/victoria-logs-data","-src=s3://my-backups/victoria-logs","-s3.endpoint=s3.amazonaws.com","-s3.accessKeyID=KEY","-s3.secretAccessKey=SECRET"],"volumeMounts":[{"name":"data","mountPath":"/victoria-logs-data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"vlstorage-victorialogs-prod-vlstorage-0"}}]}}'

# 3. Запустить vlstorage с восстановленными данными
kubectl scale statefulset vlstorage -n victoria-logs --replicas=3
```

### Инкрементальные бэкапы

`vmbackup` автоматически создаёт инкрементальные бэкапы, загружая только изменённые данные. Это значительно экономит время и хранилище по сравнению с полными копиями.

**Рекомендуемая стратегия:**
- Ежедневные инкрементальные бэкапы (удерживать 7 дней)
- Еженедельные полные бэкапы (удерживать 4 недели)
- Ежемесячные бэкапы (удерживать 12 месяцев)

---

## 12. Мультикластерное логирование

Для организации сбора логов из нескольких кластеров Kubernetes в единый кластер VictoriaLogs используются два основных подхода.

### Подход 1: DaemonSet с remoteWrite (рекомендуемый)

vlagent в каждом кластере работает как DaemonSet и отправляет логи напрямую во внешний кластер VictoriaLogs:

```yaml
# collector-values.yaml (в каждом логируемом кластере):
vlagent:
  enabled: true
  spec:
    k8sCollector:
      enabled: true
    remoteWrite:
      - url: https://vlinsert-central.monitoring.svc:9480/insert/jsonline?_stream_fields=pod,container,namespace,cluster
        headers:
          X-Scope-OrgID: "cluster-production"
        tlsConfig:
          caFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
          serverName: vlinsert-central.monitoring.svc
        bearerTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
```

### Подход 2: Агрегация через Prometheus remote_write (для метаданных)

Если в кластере уже настроен vmagent, можно направить логи через него:

```yaml
# vmagent.yml в логируемом кластере:
scrape_configs: []
remote_write:
  - url: http://vlinsert-central:9480/insert/jsonline
```

### Централизованный кластер VLCluster

```yaml
# values.yaml для централизованного кластера:
vlinsert:
  replicaCount: 3
  extraArgs:
    insert.maxLineSizeBytes: "1048576"
vlstorage:
  replicaCount: 3
  retentionPeriod: 90d
  extraArgs:
    retention.maxDiskSpaceUsageBytes: 2TiB
vlselect:
  replicaCount: 3
  extraArgs:
    search.maxQueryDuration: "30s"
```

### Маршрутизация по namespace

Для разделения логов от разных команд используйте `_stream_fields` с `X-Scope-OrgID`:

```yaml
# vlagent в namespace team-a:
remoteWrite:
  - url: https://vlinsert-central:9480/insert/jsonline
    headers:
      X-Scope-OrgID: "team-a"
    extraArgs:
      _stream_fields: "namespace,pod,container"
```

---

## 13. Миграция с Fluent Bit и Loki

### Миграция с Fluent Bit

Fluent Bit можно переключить на отправку логов в VictoriaLogs без замены агента. VictoriaLogs совместим с Severalnines Wild endpoints:

```yaml
# fluent-bit.conf (замена OUTPUT секции):
[OUTPUT]
    Name http
    Match *
    Host vlinsert.victoria-logs.svc
    Port 9480
    URI /insert/jsonline
    Format json_lines
    Header_X-Scope-OrgID migrated-from-fluentbit
    Header_content-type application/json
```

**Альтернатива:** VictoriaLogs поддерживает протокол Loki Push API, поэтому Fluent Bit можно использовать с встроенным `loki` output-плагином, направляя его в VictoriaLogs:

```yaml
[OUTPUT]
    Name loki
    Match *
    Host vlinsert.victoria-logs.svc
    Port 9480
    Labels job=fluent-bit
    Label_Keys $cluster
    Remove_Keys $cluster
```

### Миграция с Loki

Для перехода с Loki на VictoriaLogs:

1. **Данные:** Исторические данные Loki не мигрируются напрямую. Рекомендуется запустить параллельно оба стека на период перехода (2-4 недели), пока Loki retention не истечёт.

2. **Клиенты:** Замените Promtail/Alloy на vlagent или переключите вывод Fluent Bit (см. выше).

3. **Grafana:** Замените Loki datasource на `victoriametrics-logs-datasource`. Запросы LogQL совместимы с LogsQL в большинстве случаев, но проверьте синтаксис в VMUI.

4. **Алертинг:** Перенесите alerting rules из Loki в vmalert с типом `vlogs` (LogsQL). Подробнее: [Управление правилами алертинга](../../VictoriaMetrics/vmalert_rules_management_with_manifests.md).

---

## 14. Production Best Practices

### Проверенный стек

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| VictoriaLogs | v1.0.0 | v1.15.0+ |
| VictoriaMetrics Operator | v0.50.0 | v0.68.4+ |
| Helm charts | 0.5.0 | 0.7.0+ |
| vlagent | v1.0.0 | v1.15.0+ |

### Оптимизация производительности

**Для vlinsert (высокий трафик):**
```yaml
extraArgs:
  insert.maxLineSizeBytes: "2097152"  # 2MB для длинных JSON/stacktraces
  memory.allowedPercent: "80"
  # Горячий кэш для метаданных
  search.maxConcurrentRequests: "8"
```

**Для vlselect (сложные запросы):**
```yaml
extraArgs:
  search.maxQueryDuration: "30s"
  search.maxConcurrentRequests: "8"
  memory.allowedPercent: "80"
  # Кэширование результатов
  search.cacheSize: "256MB"
```

**Для vlstorage (хранилище):**
```yaml
extraArgs:
  retention.maxDiskSpaceUsageBytes: 900GiB
  # Параллельная компакция
  storage.maxPartDuration: "1h"
  storage.maxBigPartSize: "4GiB"
```

### Pod Disruption Budget

Для обеспечения доступности при обновлениях и maintenance:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: victoria-logs-vlinsert
  namespace: victoria-logs
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: victoria-logs-cluster
      app.kubernetes.io/component: vlinsert
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: victoria-logs-vlselect
  namespace: victoria-logs
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: victoria-logs-cluster
      app.kubernetes.io/component: vlselect
```

### Хранение WAL

WAL (Write-Ahead Log) критичен для потери данных. Убедитесь, что:
- PVC для vlstorage используют быстрые диски (SSD) для WAL
- `persistentVolumeclaimTemplate` не включает WAL-директорию в долгосрочное хранилище

### Обновление стека

```bash
# 1. Обновить Operator
helm upgrade victoria-metrics-operator oci://ghcr.io/victoriametrics/helm-charts/victoria-metrics-operator \
  --namespace victoria-logs --version <new-version>

# 2. Обновить кластер (rolling update)
helm upgrade victoria-logs-cluster oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-cluster \
  --namespace victoria-logs -f values.yaml

# 3. Проверить статус
kubectl get vlcluster -n victoria-logs
kubectl get pods -n victoria-logs -l app.kubernetes.io/name=victoria-logs-cluster
```

---

## 15. Troubleshooting

### Типичные проблемы и их решения

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Потеря логов** | Логи отсутствуют в VL, но есть на нодах | Проверить логи vlagent: `kubectl logs -l app=vlogs-collector` | Увеличить `insert.maxLineSizeBytes`, проверить `_stream_fields` на высокую кардинальность |
| **Высокое потребление RAM** | OOMKill подов vlinsert | `kubectl top pod`, метрика `vl_victorialogs_memory_available_bytes` | Увеличить limits, уменьшить `memory.allowedPercent` |
| **Медленные запросы** | Timeouts в Grafana, p99 > 10s | Проверить `vl_victorialogs_query_duration_seconds_bucket` | Увеличить `vlselect.replicaCount`, оптимизировать LogsQL запросы |
| **Диск заполнен** | `No space left on device`, ошибки записи | `df -h` на нодах, метрика `vl_victorialogs_storage_size_bytes` | Уменьшить `retentionPeriod`, увеличить `retention.maxDiskSpaceUsageBytes` |
| **vlagent не отправляет** | `remote_write` ошибки в логах DaemonSet | `kubectl logs -l app=vlogs-collector \| grep -i error` | Проверить network connectivity, TLS, RBAC |
| **Высокая кардинальность streams** | Медленные запросы, рост потребления RAM | `vl_victorialogs_stream_rows_total` | Исключить высококардинальные поля из `_stream_fields` |
| **Multiline логи разбиты** | Stacktraces в виде отдельных строк | Проверить парсинг в vlagent | Настроить multiline matching в vlagent |

### Диагностические команды

```bash
# Статус кластера
kubectl get vlcluster -n victoria-logs -o yaml

# Логи vlinsert (последние ошибки)
kubectl logs -l app.kubernetes.io/component=vlinsert -n victoria-logs --tail=100 | grep -i "error\|warn"

# Проверка доступности API
kubectl port-forward svc/vlselect-prod 9481:9481 -n victoria-logs
curl http://localhost:9481/select/logsql/ping
# → pong

# Проверка текущего состояния хранилища
kubectl exec -it vlstorage-0 -n victoria-logs -- wget -qO- http://localhost:8482/metrics | grep vl_victorialogs_storage

# Проверка числа активных потоков
kubectl exec -it vlstorage-0 -n victoria-logs -- wget -qO- "http://localhost:9481/select/logsql/query?query=vl_victorialogs_stream_rows_total"
```

### Проверка здоровья компонентов

```bash
# Readiness/Liveness probes (автоматически настроены оператором):
# vlinsert: GET /insert/health -> 200 OK
# vlselect: GET /select/health -> 200 OK
# vlstorage: GET /health -> 200 OK

# Ручная проверка:
kubectl exec -it vlinsert-0 -n victoria-logs -- curl -s http://localhost:9480/insert/health
# → ok
```

---

### См. также
- **[LogsQL: руководство по запросам](../../VictoriaMetrics/logsql_overview.md)** — синтаксис и функции аналитики логов.
- **[Внутреннее устройство VictoriaLogs](../../VictoriaMetrics/victorialogs_internals.md)** — архитектура хранения, WAL, сегменты и сжатие.
- **[Архитектура мониторинга и логирования](./kubernetes-monitoring-logging-architecture.md)** — общая схема стека мониторинга в Kubernetes.
