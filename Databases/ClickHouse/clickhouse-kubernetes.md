# ClickHouse в Kubernetes

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**ClickHouseInstallation (CHI)** — основной Custom Resource (CR) в Altinity Operator, описывающий топологию кластера: количество шардов и реплик, версию ClickHouse, шаблоны подов и хранилищ.

**ClickHouseKeeperInstallation (CHK)** — CR для развертывания ансамбля ClickHouse Keeper. Оператор автоматически создает StatefulSet, Service и PVC для каждого узла Keeper.

**CRD (Custom Resource Definition)** — механизм расширения Kubernetes API. Altinity Operator регистрирует четыре CRD: `clickhouseinstallations`, `clickhousekeeperinstallations`, `clickhouseinstallationtemplates` и `clickhouseoperatorconfigurations`.

**StatefulSet** — контроллер Kubernetes для запуска stateful-приложений с устойчивыми сетевыми идентификаторами (`pod-0`, `pod-1`...) и постоянным хранилищем. Оператор создает отдельный StatefulSet для каждого шарда ClickHouse и для ансамбля Keeper.

**Headless Service** — сервис Kubernetes без ClusterIP, который возвращает DNS-записи всех подов. Оператор создает Headless Service для каждого шарда, что позволяет узлам обращаться друг к другу по стабильным DNS-именам (`pod-name.service-name.namespace.svc.cluster.local`).

**Local PV (Local Persistent Volume)** — том, привязанный к конкретному узлу Kubernetes. Для on-prem кластеров это обеспечивает максимальную производительность I/O, так как данные хранятся на локальных NVMe дисках узла без сетевых переходов.

## Архитектура и принцип работы

Altinity Operator управляет жизненным циклом ClickHouse кластера через reconciliation loop:

1. **Создание CR:** SRE/разработчик создает `ClickHouseInstallation` и `ClickHouseKeeperInstallation` в Kubernetes.
2. **Reconcile:** Оператор обнаруживает новые/измененные CR и запускает reconcile.
3. **Генерация ресурсов:** На основе манифеста CHI оператор генерирует:
   - StatefulSet для каждого шарда ClickHouse
   - StatefulSet для Keeper (если используется CHK)
   - Services (Headless + ClusterIP) для доступа
   - ConfigMap с `config.xml` и `users.xml`
   - PVC через VolumeClaimTemplates
4. **Применение:** Ресурсы применяются в Kubernetes. При изменении `shardsCount` или `replicasCount` оператор выполняет rolling update без простоя.
5. **Мониторинг:** Оператор экспортирует метрики в Prometheus и обновляет статус CR (`.status`).

**Ключевое ограничение:** Оператор управляет только инфраструктурными изменениями (поды, конфиги, версии). Решардинг данных при добавлении нового шарда выполняется отдельно (см. [Кластерное управление](./clickhouse-cluster.md)).

## Предварительные требования

**Инфраструктура:**
- **Kubernetes:** 1.25+ (kubeadm, k3s, Rancher или другое on-prem решение).
- **Helm:** 3.12+ для установки оператора.
- **kubectl:** настроен на целевой кластер.
- **Хранилище:** StorageClass для динамического provisioning PVC (для on-prem: local-path-provisioner, hostpath-provisioner или кастомный StorageClass на базе NVMe).
- **Сеть:** 10 Gbps и выше между узлами. Низкая задержка (<1 ms) внутри кластера критична для репликации.
- **DNS:** Стабильное разрешение внутренних имен. Убедитесь, что CoreDNS/kube-dns работает корректно.

**Аппаратное обеспечение (на один узел ClickHouse):**
- **CPU:** 16+ ядер с поддержкой SSE 4.2 и AVX-512.
- **RAM:** 128+ ГБ (ClickHouse выполняет агрегации в памяти; нехватка RAM ведет к External Aggregation и падению производительности в 10–50 раз).
- **Диски:** NVMe SSD. Критично для фоновых слияний (merge) и синхронизации реплик. Задержки HDD вызывают `Too many parts` и отставание репликации.
- **Сеть:** 10 Gbps.

### Предварительная проверка перед развёртыванием

Перед установкой выполните чеклист:

1. **Kernel parameters:**
   ```bash
   # Проверка THP
   cat /sys/kernel/mm/transparent_hugepage/enabled
   # → always [madvise] never  (должно быть "never")
   
   # Проверка net.core.somaxconn
   sysctl net.core.somaxconn
   # → должно быть >= 65535
   
   # Проверка vm.max_map_count
   sysctl vm.max_map_count
   # → должно быть >= 262144
   ```
   Подробности — **[Производительность](./clickhouse-performance.md#системные-требования-и-подготовка-ос)**.

2. **CPU isolation (для on-prem):**
   ```bash
   # Проверка доступных CPU
   cat /sys/devices/system/cpu/isolated/cpus
   # → 0-7  (изолированы для ClickHouse через CPU manager)
   ```
   Используйте `static` CPU manager policy и `cpuPinning` в pod-шаблонах.

3. **Disk I/O:**
   ```bash
   # Проверка IOPS на целевых дисках
   dd if=/dev/zero of=/tmp/test bs=1M count=1000 oflag=direct
   # → должно быть > 500 MB/s для NVMe
   ```

## Практические сценарии

### Установка оператора

Рекомендуемый способ — через Helm:

```bash
# 1. Добавление репозитория Altinity
helm repo add altinity https://helm.altinity.com
helm repo update

# 2. Установка оператора в dedicated namespace
helm upgrade --install clickhouse-operator \
  altinity/altinity-clickhouse-operator \
  --version 0.27.3 \
  --namespace clickhouse \
  --create-namespace
# → Release "clickhouse-operator" has been installed. Namespace: clickhouse
```

**Валидация:**
```bash
kubectl get deployment -n clickhouse
# → clickhouse-operator-altinity-clickhouse-operator   1/1     1/1
```

### Развертывание ClickHouse Keeper (CHK)

Для Production категорически не рекомендуется использовать встроенный Keeper внутри подов ClickHouse. Развертывайте отдельный ансамбль из 3 узлов.

```yaml
# keeper.yaml
apiVersion: "clickhouse-keeper.altinity.com/v1"
kind: "ClickHouseKeeperInstallation"
metadata:
  name: "pro-keeper"
  namespace: "clickhouse"
spec:
  configuration:
    clusters:
      - name: "keeper-cluster"
        layout:
          replicasCount: 3
    settings:
      keeper_server/coordination_settings/raft_logs_level: "information"
      keeper_server/coordination_settings/operation_timeout_ms: "10000"
  templates:
    podTemplate: "keeper-pod"
    volumeClaimTemplate: "keeper-storage"
  podTemplates:
    - name: "keeper-pod"
      spec:
        containers:
          - name: "clickhouse-keeper"
            image: "clickhouse/clickhouse-keeper:26.9"
            resources:
              requests:
                memory: "1Gi"
                cpu: "1"
              limits:
                memory: "4Gi"
                cpu: "2"
  volumeClaimTemplates:
    - name: "keeper-storage"
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: "20Gi"
        storageClassName: "local-path" # on-prem: используйте StorageClass вашего кластера на базе NVMe
```

**Валидация:**
```bash
kubectl apply -f keeper.yaml -n clickhouse
# → clickhousekeeperinstallation.clickhouse-keeper.altinity.com/pro-keeper created

kubectl get chk -n clickhouse
# → NAME        STATUS    REPLICAS   AGE
# → pro-keeper  Completed 3/3        2m

kubectl get statefulsets -n clickhouse | grep chk
# → chk-pro-keeper-keeper-cluster-0-0   3/3     3m
```

### Развертывание кластера ClickHouse (CHI)

Оператор автоматически связывает CHI с CHK по имени ресурса, избавляя от необходимости прописывать IP-адреса вручную.

```yaml
# cluster.yaml
apiVersion: "clickhouse.altinity.com/v1"
kind: "ClickHouseInstallation"
metadata:
  name: "production-cluster"
  namespace: "clickhouse"
spec:
  configuration:
    zookeeper:
      keeper:
        name: "pro-keeper" # Ссылка на CHK
  clusters:
    - name: "main-cluster"
      layout:
        shardsCount: 2
        replicasCount: 2
  defaults:
    templates:
      podTemplate: "ha-pod-template"
      dataVolumeClaimTemplate: "storage-template"
  templates:
     podTemplates:
       - name: "ha-pod-template"
         spec:
           securityContext:
             runAsUser: 101
             runAsGroup: 101
             fsGroup: 101
             fsGroupChangePolicy: "OnRootMismatch"
             supplementalGroups: [101]
           affinity:
             podAntiAffinity:
               requiredDuringSchedulingIgnoredDuringExecution:
                 - labelSelector:
                     matchExpressions:
                       - key: "clickhouse.altinity.com/chi"
                         operator: In
                         values: ["production-cluster"]
                   topologyKey: "kubernetes.io/hostname"
             nodeAffinity:
               requiredDuringSchedulingIgnoredDuringExecution:
                 nodeSelectorTerms:
                   - matchExpressions:
                       - key: "node-role.kubernetes.io/clickhouse"
                         operator: In
                         values: ["ssd-nvme"]
           containers:
             - name: "clickhouse"
               image: "clickhouse/clickhouse-server:26.9"
               securityContext:
                 readOnlyRootFilesystem: false
                 capabilities:
                   drop: ["ALL"]
                   add: ["SYS_NICE", "NET_BIND_SERVICE"]
               resources:
                 requests:
                   cpu: "8"
                   memory: "32Gi"
                 limits:
                   cpu: "8"
                   memory: "32Gi"
    volumeClaimTemplates:
      - name: "storage-template"
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: "500Gi"
          storageClassName: "local-path" # on-prem: используйте Local PV или быстрый SSD StorageClass
```

**Валидация:**
```bash
kubectl apply -f cluster.yaml -n clickhouse
# → clickhouseinstallation.clickhouse.altinity.com/production-cluster configured

kubectl get chi -n clickhouse
# → NAME                 CLUSTERS   SHARDS   REPLICAS   TOTAL   STATUS
# → production-cluster   1          2        2          4       Completed

kubectl get pods -n clickhouse -l clickhouse.altinity.com/chi=production-cluster
# → NAME                                          READY   STATUS
# → chi-production-cluster-main-cluster-0-0-0     1/1     Running
# → chi-production-cluster-main-cluster-0-1-0     1/1     Running
# → chi-production-cluster-main-cluster-1-0-0     1/1     Running
# → chi-production-cluster-main-cluster-1-1-0     1/1     Running

# Проверка работоспособности через clickhouse-client
kubectl exec -it chi-production-cluster-main-cluster-0-0-0 -n clickhouse -- clickhouse-client --query "SELECT version()"
# → 26.9.4.3
```

### Подключение к кластеру

**Изнутри кластера:**
```bash
# Узнать имя сервиса
kubectl get svc -n clickhouse | grep chi-production-cluster
# → chi-production-cluster-main-cluster-0-0-0.operator.svc.cluster.local:8123
```

**Извне кластера (Port Forward для отладки):**
```bash
kubectl port-forward svc/chi-production-cluster-main-cluster-0-0-0 8123:8123 -n clickhouse
# → Forwarding from 127.0.0.1:8123 -> 8123

clickhouse-client --host 127.0.0.1 --port 8123
```

> **Важно:** Port Forward подходит только для отладки. Для Production используйте Ingress, NodePort или LoadBalancer с TLS.

### Масштабирование

Добавление шарда:
1. Измените `shardsCount` в манифесте CHI.
2. Примените изменения: `kubectl apply -f cluster.yaml`.
3. Оператор создаст новый StatefulSet и конфиги.
4. **Вручную перенесите данные** через `clickhouse-copier` или `INSERT ... SELECT` (решардинг не выполняется автоматически).

### Обновление без простоя (Rolling Update)

1. Измените версию образа в CHI манифесте.
2. Примените: `kubectl apply -f cluster.yaml`.
3. Оператор выполнит rolling update по репликам.
4. Перед обновлением следующей реплики убедитесь, что текущая догнала очередь репликации (`absolute_delay` в `system.replicas` близок к 0).

### Удаление кластера (Cleanup)

```bash
# Удаление CHI (оператор удалит все связанные ресурсы)
kubectl delete chi production-cluster -n clickhouse
kubectl delete chk pro-keeper -n clickhouse

# Удаление namespace (опционально)
kubectl delete namespace clickhouse

# Удаление CRDs (при полном деинсталлировании оператора)
kubectl delete crd clickhouseinstallations.clickhouse.altinity.com
kubectl delete crd clickhousekeeperinstallations.clickhouse-keeper.altinity.com
kubectl delete crd clickhouseinstallationtemplates.clickhouse.altinity.com
kubectl delete crd clickhouseoperatorconfigurations.clickhouse.altinity.com
```

### Резервное копирование и восстановление

Для K8s используйте `clickhouse-backup` в виде CronJob. Подробности архитектуры бэкапов — **[Бэкапы и восстановление](./clickhouse-backup.md)**.

**Создание service account для бэкапа:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: "clickhouse-backup"
  namespace: "clickhouse"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: "clickhouse-backup"
  namespace: "clickhouse"
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/exec"]
    verbs: ["get", "list", "create"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: "clickhouse-backup"
  namespace: "clickhouse"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: "clickhouse-backup"
subjects:
  - kind: ServiceAccount
    name: "clickhouse-backup"
    namespace: "clickhouse"
```

**CronJob для ежедневных бэкапов:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: "clickhouse-backup"
  namespace: "clickhouse"
spec:
  schedule: "0 2 * * *"  # Ежедневно в 02:00
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: "clickhouse-backup"
          restartPolicy: "OnFailure"
          containers:
            - name: "backup"
              image: "altinity/clickhouse-backup:latest"
              command: [
                "sh", "-c",
                "clickhouse-backup create && clickhouse-backup upload"
              ]
              env:
                - name: "CLICKHOUSE_HOST"
                  value: "http://clickhouse-cluster:8123"
                - name: "BACKUP_STORAGE"
                  value: "s3://clickhouse-backups/"
              volumeMounts:
                - name: "config"
                  mountPath: "/etc/clickhouse-backup"
              resources:
                requests:
                  cpu: "1"
                  memory: "2Gi"
                limits:
                  cpu: "2"
                  memory: "4Gi"
          volumes:
            - name: "config"
              configMap:
                name: "clickhouse-backup-config"
```

**Восстановление из бэкапа:**
```bash
# 1. Список удалённых бэкапов
kubectl exec -n clickhouse -it <clickhouse-pod> -- clickhouse-backup list --remote

# 2. Скачивание и восстановление
kubectl exec -n clickhouse -it <clickhouse-pod> -- clickhouse-backup download <backup-name>
kubectl exec -n clickhouse -it <clickhouse-pod> -- clickhouse-backup restore <backup-name>
  # → Воспользоваться [Руководством по восстановлению](./clickhouse-backup.md#clickhouse-backup-автоматизация)
```

**Резервное копирование Keeper:**
```bash
# 1. Проверка состояния Keeper
kubectl exec -n clickhouse -it chk-pro-keeper-keeper-cluster-0-0 -- \
  clickhouse-keeper-client --host localhost --port 2181 ruok
# → imok

# 2. Копирование coordination data через shared volume или rsync sidecar
  # Подробности — [Бэкап ClickHouse Keeper](./clickhouse-backup.md#бэкап-clickhouse-keeper)
```

## Мониторинг и диагностика

Altinity Operator включает встроенный экспортер метрик. Для интеграции с Prometheus Operator создайте ServiceMonitor и PrometheusRule:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: "ServiceMonitor"
metadata:
  name: "clickhouse-monitor"
  namespace: "clickhouse"
spec:
  selector:
    matchLabels:
      clickhouse.altinity.com/chi: production-cluster
  endpoints:
    - port: "metrics"
      interval: "30s"
---
apiVersion: monitoring.coreos.com/v1
kind: "PrometheusRule"
metadata:
  name: "clickhouse-alerts"
  namespace: "clickhouse"
spec:
  groups:
    - name: "clickhouse.rules"
      rules:
        - alert: "ClickHouseReplicaLag"
          expr: 'count by (chi) (clickhouse_replica_absolute_delay > 60)'
          for: "5m"
          labels:
            severity: "warning"
          annotations:
            summary: "ClickHouse replica lag detected"
            description: "Replica on {{ $labels.pod }} has absolute_delay > 60s"
        - alert: "ClickHousePodCrash"
          expr: 'count by (pod) (kube_pod_status_ready{condition="true"} == 0) > 0'
          for: "2m"
          labels:
            severity: "critical"
          annotations:
            summary: "ClickHouse pod not ready"
            description: "Pod {{ $labels.pod }} is not ready"
```

- **Endpoint метрик:** По умолчанию доступен на порту `8888`.
- **Дашборды:** Рекомендуется использовать официальный Altinity ClickHouse Dashboard для Grafana.
- **Ключевые метрики для алертов:**
  - `absolute_delay > 60` в `system.replicas` — отставание репликации
  - `ReplicaInReadonly` — реплика перешла в read-only
  - `MergeTreePartsErrors` — ошибки слияния частей

## Устранение неисправностей

### Pod в состоянии CrashLoopBackOff

```bash
kubectl logs -n clickhouse chi-production-cluster-main-cluster-0-0-0
# Проверьте последние строки логов на предмет ошибок конфигурации или нехватки памяти
```

**Частые причины:**
- Недостаточно памяти (OOMKilled): увеличьте лимиты в `resources.limits.memory`.
- Неверный `config.xml`: проверьте, что макросы и путь к Keeper корректны.
- Порт уже занят: убедитесь, что нет конфликтов портов 8123/9000/9009 внутри пода.

### PVC в состоянии Pending

```bash
kubectl get pvc -n clickhouse
kubectl describe pvc <pvc-name> -n clickhouse
```

**Частые причины:**
- Отсутствует StorageClass: создайте или укажите существующий `storageClassName`.
- Недостаточно места на локальном диске: проверьте `df -h` на узлах.
- Доступен только `ReadWriteOnce`, но под пытается запуститься на другом узле: используйте `podAntiAffinity` для привязки пода к узлу с PVC.

### Keeper не готов (CHK в статусе In Progress)

```bash
kubectl describe chk pro-keeper -n clickhouse
```

**Частые причины:**
- Кворум не сформирован: убедитесь, что запущены минимум 2 из 3 узлов Keeper.
- Сетевая разрывость: проверьте, что порт 2181 доступен между узлами Keeper.
- Конфликт `server_id`: каждый узел Keeper должен иметь уникальный `server_id` от 1 до N.

### Реплика в read-only

```sql
SELECT database, table, is_readonly, absolute_delay, queue_size
FROM system.replicas
WHERE is_readonly = 1;
```

**Решение:**
```sql
SYSTEM RESTORE REPLICA <database>.<table>;
```

### Сетевые разрывы между шардами

```bash
# Проверка DNS
kubectl exec -it <pod> -- nslookup chi-production-cluster-main-cluster-0-0-0.operator.svc.cluster.local

# Проверка портов
kubectl exec -it <pod> -- nc -zv <replica-host> 9000
```

### Не хватает памяти (OOMKilled)

```bash
kubectl describe pod <pod-name> -n clickhouse | grep -A5 "OOM"
```

**Частые причины:**
- `max_server_memory_usage` превышает лимит контейнера: ограничьте до 80% лимита памяти.
- External Aggregation: не хватает RAM для больших GROUP BY — добавьте узлы или используйте `partial_merge_aggregation`.

### ClickHouse Operator не реагирует на изменения

```bash
kubectl describe chi production-cluster -n clickhouse
# Проверка статуса reconcile в .status
kubectl logs deployment/clickhouse-operator-altinity-clickhouse-operator -n clickhouse
```

**Частые причины:**
- CRD версия не поддерживается оператором: проверьте `--version` в Helm chart.
- Оператор застрял в infinite loop: добавьте `--runtime.MaxNilchanCapacity` в env оператора.

### PVC не удаляется после удаления CHI

```bash
kubectl get pvc -n clickhouse | grep <chi-name>
kubectl patch pvc <pvc-name> -n clickhouse -p '{"metadata":{"finalizers":null}}'
```

**Причина:** PVC имеет finalizer от StorageClass или внешнего provisioner. Используйте `volumeClaimReclaimPolicy: Delete` или удалите finalizer вручную.

### Сетевой таймаут между подами

```bash
# Проверка latency между репликами
kubectl exec -it <pod-0> -- iperf3 -c <pod-1> -t 10
```

**Решение:** используйте `hostNetwork: true` для подов ClickHouse или настройте CNI с меньшим overhead.

## Лучшие практики

1.  **Используйте отдельный CHK:** Для Production развертывайте ClickHouse Keeper в отдельном `ClickHouseKeeperInstallation`. Встроенный Keeper подходит только для dev-сред и single-node кластеров.
2.  **Всегда включайте `internal_replication = true`:** В конфигурации шарда это снижает сложность записи и предотвращает несогласованность при сетевых сбоях.
3.  **Используйте макросы через CRD:** Оператор автоматически подставляет макросы `{cluster}`, `{shard}`, `{replica}`. Не хардкодьте имена в DDL.
4.  **Мониторьте `absolute_delay`:** Добавьте алерт в Prometheus на `absolute_delay > 60` в `system.replicas`.
5.  **Настраивайте `insert_distributed_sync`:** Для критичных данных включите синхронную запись в `Distributed`-таблицы, чтобы избегать потерь при отказе узла.
6.  **Используйте Local PV для Keeper:** Raft-логи требуют постоянной синхронизации на диск (`fsync`). Задержки HDD напрямую влияют на латентность записи в кластер.
7.  **Настраивайте `operation_timeout_ms`:** При высокой нагрузке увеличьте таймаут в Keeper до 10000–30000 ms, чтобы предотвратить ложные срабатывания таймаута.
8.  **Устанавливайте `requests` равными `limits`:** Это гарантирует Guaranteed QoS и предотвращает throttling ClickHouse.
9.  **Держите `max_server_memory_usage` ниже лимита памяти:** Оставьте запас 10–15% для ОС и фоновых процессов.
   10. **Тестируйте восстановление после сбоя Keeper:** Раз в квартал останавливайте 2 из 3 узлов Keeper и убеждайтесь, что кластер корректно переходит в read-only и восстанавливается.
   11. **Настраивайте `securityContext` в подах:** `runAsUser`/`fsGroup` предотвращают проблемы с правами на PVC; `readOnlyRootFilesystem: false` — необходим для ClickHouse (требует writable `/var/lib/clickhouse`).
   12. **Используйте `nodeAffinity` для on-prem:** Привязывайте поды ClickHouse на узлы с NVMe, используя теги `node-role.kubernetes.io/clickhouse=ssd-nvme`.
   13. **Настраивайте бэкапы через CronJob:** Автоматизируйте `clickhouse-backup create + upload` ежедневно; тестируйте restore минимум раз в квартал.
   14. **Ограничивайте `max_server_memory_usage`:** Установите 70–80% лимита контейнера, чтобы оставить память для ОС и фоновых процессов.

## Дополнительная информация

### Связанные разделы

- **Репликация и шардирование:** **[Кластерное управление ClickHouse](./clickhouse-cluster.md)**.
- **Эксплуатация и обслуживание:** **[Эксплуатация ClickHouse](./clickhouse-operations.md)**.
- **Бэкапы и восстановление:** **[Бэкапы](./clickhouse-backup.md)**.
- **Архитектура движков:** **[Архитектура ClickHouse](./clickhouse-architecture.md)**.
- **Производительность:** **[Производительность ClickHouse](./clickhouse-performance.md)**.

### Ограничения и известные особенности

- **Нет автоматического решардинга:** Добавление нового шарда требует ручного переноса данных через `clickhouse-copier` или `INSERT ... SELECT`.
- **ReplicatedMergeTree не заменяет стандартный MergeTree:** Для нереплицируемых таблиц используйте обычный `MergeTree`, чтобы избежать накладных расходов на координацию.
- **Data Skew сложно исправить после загрузки:** Неправильный ключ шардирования приводит к перекосу нагрузки, который можно устранить только через полный решардинг.
- **Keeper — единая точка отказа по метаданным:** При потере кворума Keeper кластер становится read-only. Это не приводит к потере данных, но блокирует все записи.
- **Сетевые разрывы между шардами:** ClickHouse не поддерживает multi-master запись между шардами. Каждый шард должен быть доступен из любой точки кластера с задержкой <1 ms.

### Системные пути и файлы (Linux)

При on-prem установке через оператор:

- **Данные внутри пода:** `/var/lib/clickhouse/` (разделы `data/`, `system/`, `format_schemas/`, `dictionaries/`)
- **Логи:** `/var/log/clickhouse-server/` (`clickhouse-server.log`, `clickhouse-client.log`, `stderr.log`)
- **Конфигурация:** `/etc/clickhouse-server/`
  - Основные файлы: `config.xml`, `users.xml`
  - Кастомные настройки: `config.d/*.xml`, `users.d/*.xml`
- **Секреты и ключи:** `/etc/clickhouse-server/ssl/` (сертификаты TLS)
- **Systemd unit (на хосте):** `clickhouse-server.service` (если установлен не в контейнере)

**Важно:** не редактируйте `config.xml` напрямую — используйте файлы в `config.d/` для переопределения параметров.
