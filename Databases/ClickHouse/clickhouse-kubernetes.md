# ClickHouse в Kubernetes

Развертывание ClickHouse в Kubernetes требует специализированного подхода к управлению состоянием (State) и сетевой связностью. Стандартом индустрии является использование **Altinity ClickHouse Operator**, который автоматизирует жизненный цикл кластера, включая управление шардами, репликацию и мониторинг.

## ClickHouse Operator (Altinity)

Оператор управляет ресурсами через Custom Resource Definitions (CRD):
1.  **`ClickHouseInstallation` (CHI):** Основной ресурс, описывающий топологию кластера (шарды, реплики), версии и конфигурации ClickHouse.
2.  **`ClickHouseKeeperInstallation` (CHK):** Специализированный ресурс для развертывания ансамбля ClickHouse Keeper (начиная с v0.24.0+).

### Установка оператора
Рекомендуемый способ установки — через Helm:
```bash
helm repo add altinity-clickhouse-operator https://docs.altinity.com/clickhouse-operator/
helm install clickhouse-operator altinity-clickhouse-operator/clickhouse-operator --namespace kube-system
```

---

## 1. Развертывание ClickHouse Keeper (CHK)

Для Production-решений категорически не рекомендуется использовать встроенный (embedded) Keeper внутри подов ClickHouse. Необходимо развертывать отдельный ансамбль из 3 или 5 узлов для обеспечения стабильности кворума Raft.

**Пример манифеста `ClickHouseKeeperInstallation`:**

```yaml
apiVersion: "clickhouse-keeper.altinity.com/v1"
kind: "ClickHouseKeeperInstallation"
metadata:
  name: "pro-keeper"
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
            image: "altinity/clickhouse-keeper:latest"
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
        storageClassName: "premium-rwo" # Рекомендуется SSD с высокими IOPS
```

---

## 2. Развертывание кластера ClickHouse (CHI)

Оператор автоматически связывает CHI с CHK по имени ресурса, избавляя от необходимости прописывать IP-адреса вручную.

**Пример манифеста `ClickHouseInstallation`:**

```yaml
apiVersion: "clickhouse.altinity.com/v1"
kind: "ClickHouseInstallation"
metadata:
  name: "production-cluster"
spec:
  configuration:
    zookeeper:
      keeper:
        name: "pro-keeper" # Ссылка на CHK выше
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
          affinity:
            podAntiAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                - labelSelector:
                    matchExpressions:
                      - key: "clickhouse.altinity.com/chi"
                        operator: In
                        values: ["production-cluster"]
                  topologyKey: "kubernetes.io/hostname"
          containers:
            - name: "clickhouse"
              image: "clickhouse/clickhouse-server:26.7"
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
          storageClassName: "local-path" # NVMe SSD для минимизации задержек
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: "500Gi"
```

---

## 3. Мониторинг и диагностика

Altinity Operator включает встроенный экспортер метрик. Для интеграции с **Prometheus Operator** необходимо создать `ServiceMonitor`.

- **Endpoint метрик:** По умолчанию доступен на порту `8888`.
- **Дашборды:** Рекомендуется использовать официальный **Altinity ClickHouse Dashboard** для Grafana.
- **ServiceMonitor (пример):**
  ```yaml
  apiVersion: monitoring.coreos.com/v1
  kind: ServiceMonitor
  metadata:
    name: clickhouse-monitor
  spec:
    selector:
      matchLabels:
        clickhouse.altinity.com/chi: production-cluster
    endpoints:
      - port: metrics
        interval: 30s
  ```

---

## 4. Лучшие практики (Production Ready)

### Управление ресурсами (QoS)
- **Guaranteed QoS:** Всегда устанавливайте `requests` равными `limits` для CPU и RAM. Это предотвращает "удушение" (throttling) ClickHouse и внезапное завершение процесса.
- **Memory Buffer:** Настраивайте параметр `<max_server_memory_usage>` (в `users.xml`) примерно на 10-15% ниже, чем лимит памяти в Kubernetes. Это дает ClickHouse запас для работы ОС и предотвращает срабатывание OOM Killer.

### Хранение данных
- **Disk Latency:** ClickHouse Keeper критически чувствителен к задержкам диска. Каждый Raft-лог должен быть синхронизирован (`fsync`) перед подтверждением записи. Используйте только SSD (NVMe).
- **Local PV:** Для достижения максимальной производительности I/O используйте локальные диски узлов (Local Persistent Volumes) вместо сетевых хранилищ (EBS/GCP PD).

### Сетевая связность
- **Headless Service:** Оператор создает Headless Service для каждого кластера, что позволяет узлам обращаться друг к другу по стабильным DNS-именам (`pod-name.svc-name`).
- **Inter-server communication:** Убедитесь, что порт `9009` открыт и доступен между всеми репликами для синхронизации данных.

### Масштабирование
- Для добавления шардов просто измените `shardsCount` в манифесте CHI. Оператор автоматически создаст новые StatefulSet и выполнит конфигурацию, но помните: **решардинг данных не выполняется автоматически** (подробнее в [Кластерном управлении](./clickhouse-cluster.md)).
