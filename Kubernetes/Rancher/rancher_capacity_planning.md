# Capacity Planning в Rancher

## Определения

**Capacity Planning** — процесс расчета требуемых вычислительных ресурсов (CPU, RAM, Disk, Network) для кластеров Rancher и управляемых кластеров. Включает оценку текущей нагрузки, прогнозирование роста и определение моментов расширения.

**Sizing** — определение оптимального размера ресурсов для компонентов Rancher (Rancher Server, etcd, downstream-кластеры) на основе нагрузки.

**Headroom** — запас ресурсов (обычно 20-30%) для обработки пиковых нагрузок и обеспечения отказоустойчивости.

**Quotas** — лимиты ресурсов (CPU, Memory, PV) на уровне namespace или проекта для предотвращения исчерпания ресурсов кластера.

## Базовые концепции

### Факторы, влияющие на sizing Rancher Server

| Фактор | Влияние | Рекомендация |
| :--- | :--- | :--- |
| **Количество downstream-кластеров** | Больше кластеров = больше нагрузки на Rancher Server | 150 кластеров → Small, 300 → Medium, 500 → Large |
| **Количество узлов** | Каждый узел генерирует метрики и логи | 1500 узлов → Small, 3000 → Medium |
| **Количество пользователей** | Больше пользователей = больше API-запросов | Учитывайте при sizing |
| **Fleet GitRepo** | Каждый GitRepo опрашивается каждые 5 сек | Ограничивайте число GitRepo |

### Матрица ресурсов Management-кластера

| Размер | Max кластеров | Max узлов | CPU на узел | RAM на узел |
| :--- | :--- | :--- | :--- | :--- |
| **Small** | 150 | 1500 | 4 | 16 GB |
| **Medium** | 300 | 3000 | 8 | 32 GB |
| **Large** | 500 | 5000 | 16 | 64 GB |
| **Larger** | >500 | >5000 | Специальная проработка | Специальная проработка |

**Важно:** это ресурсы **на каждый узел** Management-кластера, а не суммарные.

### Формулы расчета

**Для Rancher Server:**
```
RAM (GB) = 4 + (0.002 × number_of_clusters × nodes_per_cluster)
CPU (cores) = 2 + (0.001 × number_of_clusters × nodes_per_cluster)
```

**Для downstream-кластера:**
```
etcd RAM (GB) = 2 + (0.001 × number_of_objects)
etcd CPU (cores) = 2 + (0.0005 × number_of_objects)
Prometheus RAM (GB) = 2 + (0.001 × number_of_series)
```

**Где:**
- `number_of_objects` — количество Kubernetes-объектов (Pods, Deployments, Services).
- `number_of_series` — количество метрик в Prometheus.

## Практические сценарии

### Шаг 1: Оценка текущей нагрузки

```bash
# Проверка ресурсов Management-кластера
kubectl top nodes
# → NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → master1  1200m        15%    8Gi             50%
# → master2  1100m        13%    7.5Gi          47%
# → master3  1050m        13%    7Gi            44%

# Проверка подов Rancher
kubectl -n cattle-system top pods
# → rancher-<hash>   200m   512Mi

# Проверка etcd
kubectl -n kube-system top pods -l component=etcd
# → etcd-master1   500m   1Gi
```

### Шаг 2: Мониторинг использования ресурсов

```bash
# Prometheus: среднее использование CPU за 7 дней
avg_over_time(cpu_usage_seconds_total[7d])

# Prometheus: использование памяти
container_memory_working_set_bytes{namespace="cattle-system"}

# Grafana: дашборд "Kubernetes Cluster Monitoring"
```

### Шаг 3: Планирование расширения

**Сценарий:** текущий кластер 200 кластеров, планируется рост до 350.

```
Текущий размер: Small (150 кластеров) → не хватает!
Требуется: Medium (300 кластеров)
Действия:
1. Добавить RAM до 32 GB на узел
2. Добавить CPU до 8 cores на узел
3. Рассмотреть выделенные etcd-узлы
```

### Шаг 4: Настройка Resource Quotas

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: project-quota
  namespace: production
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    limits.cpu: "16"
    limits.memory: 32Gi
    persistentvolumeclaims: "10"
    pods: "50"
```

### Шаг 5: Планирование Prometheus

**Для downstream-кластера с 1000 подов:**
```
Prometheus RAM = 2 + (0.001 × 10000 series) = 12 GB
Prometheus CPU = 2 + (0.0005 × 10000) = 7 cores
Prometheus Disk = 50 GB (15 дней retention)
```

### Шаг 6: Планирование etcd

**Для кластера с 5000 объектов:**
```
etcd RAM = 2 + (0.001 × 5000) = 7 GB
etcd CPU = 2 + (0.0005 × 5000) = 4.5 cores
etcd Disk = SSD/NVMe, минимум 50 GB
etcd IOPS: fsync < 10ms (обязательно!)
```

### Шаг 7: Проверка disk space

```bash
# Проверка PV
kubectl get pvc -A
# → cattle-monitoring-system   prometheus-rancher-monitoring-prometheus-0   Bound   50Gi

# Проверка disk usage на узле
df -h
# → /dev/sda1   100G   65G   35G   65%   /

# Проверка etcd disk
sudo fio --name=test --rw=write --bs=4k --size=128m --fdatasync=1 --runtime=10
# → fsync latency < 10ms
```

### Шаг 8: Автоматическое масштабирование

**Cluster Autoscaler:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.28.0
          command:
            - ./cluster-autoscaler
            - --v=4
            - --cloud-provider=aws
            - --skip-nodes-with-local-storage=false
            - --expander=least-waste
            - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/my-cluster
```

### Шаг 9: Мониторинг capacity

**Prometheus recording rules:**
```yaml
groups:
  - name: capacity_planning
    rules:
      - record: node:cpu_utilization:ratio
        expr: 1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

      - record: node:memory_utilization:ratio
        expr: 1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)

      - record: node:disk_utilization:ratio
        expr: 1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})
```

**Алерты:**
```yaml
groups:
  - name: capacity_alerts
    rules:
      - alert: HighCPUUtilization
        expr: node:cpu_utilization:ratio > 0.85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High CPU utilization on {{ $labels.instance }}"

      - alert: HighMemoryUtilization
        expr: node:memory_utilization:ratio > 0.85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High memory utilization on {{ $labels.instance }}"

      - alert: DiskSpaceLow
        expr: node:disk_utilization:ratio > 0.85
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk space low on {{ $labels.instance }}"
```

## Диагностика и устранение неполадок

### Rancher Server потребляет много ресурсов

```bash
# Проверка подов Rancher
kubectl -n cattle-system top pods
# → rancher-<hash>   2000m   2Gi   (высокое потребление!)

# Причина: возможно, много Watch-соединений от downstream-кластеров
# Решение: увеличить ресурсы или оптимизировать количество downstream-кластеров
```

### etcd не справляется с нагрузкой

```bash
# Проверка etcd metrics
kubectl -n kube-system top pods -l component=etcd

# Проверка fsync latency
# Prometheus: etcd_disk_wal_fsync_duration_seconds
# Если > 10ms — проблема с диском!

# Решение: перейти на NVMe, увеличить IOPS
```

### Prometheus OOMKilled

```bash
# Проверка
kubectl -n cattle-monitoring-system get pods
# → prometheus-<hash>   0/2   OOMKilled

# Решение:
# 1. Увеличить limits памяти
# 2. Уменьшить retention
# 3. Включить Agent Mode с Remote Write
```

## Дополнительная информация

### Рекомендации по Capacity Planning

1. **Мониторинг:** настройте Prometheus + Grafana для отслеживания ресурсов.
2. **Headroom:** всегда резервируйте 20-30% запаса ресурсов.
3. **Регулярная оценка:** проверяйте использование ресурсов ежемесячно.
4. **Прогнозирование:** учитывайте рост числа кластеров и пользователей.
5. **SSD для etcd:** это критично для стабильности всего кластера.

### Связанные темы

- [Установка Rancher Server](./rancher_installation.md) — матрица ресурсов.
- [Мониторинг](./rancher_monitoring.md) — настройка Prometheus.
- [RKE: etcd](./rancher_rke.md) — требования к etcd.

**Внешние ресурсы:**

- [Rancher Server Requirements](https://ranchermanager.docs.rancher.com/installation-and-upgrade/installation-requirements)
- [Kubernetes Capacity Planning](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
