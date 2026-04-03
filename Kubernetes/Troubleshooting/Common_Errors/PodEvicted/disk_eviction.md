# Pod Evicted: Нехватка диска

## Definitions

**DiskPressure Eviction** — выселение подов kubelet'ом при нехватке дискового пространства на узле. Триггер — condition `DiskPressure=True`.

**Ephemeral storage** — временное хранилище узла, используемое для логов контейнеров, temporary files, `emptyDir` volumes, pull-кэша образов.

**Threshold (по умолчанию):** `< 10%` свободно или `< 1Gi` available.

## Basic Concepts

### Источники потребления диска

| Источник | Описание | Пример пути |
|----------|----------|-------------|
| Логи контейнеров | stdout/stderr вывод | `/var/log/containers/*.log` |
| `emptyDir` volumes | Временные тома подов | `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~empty-dir/` |
| Image filesystem | Кэш образов контейнеров | `/var/lib/containerd/` или `/var/lib/docker/` |
| writable layer | Записываемый слой контейнера | `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/` |
| journal logs | Системные логи узла | `/var/log/journal/` |

### Eviction thresholds в kubelet

```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  nodefs.available: "10%"      # Корневой раздел
  nodefs.inodesFree: "5%"      # Свободные inode
  imagefs.available: "15%"     # Файловая система образов
  imagefs.inodesFree: "5%"
```

| Threshold | Что мониторит | Действие при достижении |
|-----------|--------------|------------------------|
| `nodefs.available` | Свободное место на `/var/lib/kubelet` | Eviction подов с большим disk usage |
| `nodefs.inodesFree` | Свободные inode | Eviction при inode exhaustion |
| `imagefs.available` | Свободное место на образы | Очистка неиспользуемых образов + eviction |

### Порядок выселения

```
DiskPressure detected
    ↓
Eviction Manager проверяет потребление disk подами
    ↓
Сортировка: BestEffort → Burstable (по disk usage)
    ↓
Выселение подов с наибольшим потреблением диска
    ↓
Если не помогло → очистка образов (image garbage collection)
```

## Practical Scenarios

### Диагностика

**Шаг 1: Подтверждение DiskPressure**

```bash
# Проверка conditions узла
kubectl describe node <node-name> | grep -A 5 "DiskPressure"

# Быстрая проверка всех узлов
kubectl get nodes -o custom-columns=NAME:.metadata.name,DISK_PRESSURE:.status.conditions[?(@.type=="DiskPressure")].status
```

**Шаг 2: Выявление потребителя**

```bash
# Общее потребление
ssh <node-name> "df -h /var/lib/kubelet"

# Топ по размеру в kubelet
ssh <node-name> "du -sh /var/lib/kubelet/pods/* | sort -rh | head -20"

# Логи контейнеров
ssh <node-name> "du -sh /var/log/containers/* | sort -rh | head -10"

# Образы контейнеров
ssh <node-name> "crictl images | sort -k6 -rh | head -20"

# Проверка inode
ssh <node-name> "df -i /var/lib/kubelet"
```

**Шаг 3: Определение пода-виновника**

```bash
# Связь pod UID с потреблением диска
kubectl get pods -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,NODE:.spec.nodeName --all-namespaces | grep <node-name>

# emptyDir с превышением limits
kubectl get pods -o json -A | jq '.items[] | select(.spec.volumes[]? | has("emptyDir")) | {name: .metadata.name, namespace: .metadata.namespace, volumes: [.spec.volumes[] | select(.emptyDir) | {name: .name, sizeLimit: .emptyDir.sizeLimit}]}'
```

### Решение

#### Быстрая очистка

```bash
# Удаление stopped контейнеров
crictl rm $(crictl ps -a -q --state exited)

# Удаление неиспользуемых образов
crictl rmi --prune

# Очистка старых логов
ssh <node-name> "find /var/log/containers/ -name '*.log' -mtime +7 -delete"

# Очистка journal
ssh <node-name> "journalctl --vacuum-time=1d"
```

#### Настройка limits для ephemeral-storage

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
  - name: app
    image: my-app:latest
    resources:
      requests:
        ephemeral-storage: "1Gi"
      limits:
        ephemeral-storage: "5Gi"
```

> При превышении `limits.ephemeral-storage` под будет выселен с узла.

#### Настройка log rotation для containerd

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".containerd.log]
  level = "info"
  max_size = "100Mi"
  max_backups = 5
```

```bash
# Перезапуск containerd после изменения
systemctl restart containerd
```

#### Настройка log rotation для Docker

```json
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "5"
  }
}
```

## Additional Information

### Мониторинг и алерты

```yaml
# Prometheus alert
- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "DiskPressure на узле {{ $labels.node }}"

- alert: NodeFilesystemAlmostFull
  expr: node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes * 100 < 15
  for: 10m
  labels:
    severity: warning
```

### Предотвращение

| Практика | Описание |
|----------|----------|
| **Указывайте `ephemeral-storage` limits** | Контроль потребления каждым подом |
| **Ограничивайте `emptyDir.sizeLimit`** | Защита от бесконтрольного роста temporary volumes |
| **Настраивайте log rotation** | Автоматическая ротация логов контейнеров |
| **Image garbage collection** | Настройка `imageGCHighThresholdPercent` в kubelet |
| **Отдельный диск для `/var/lib/kubelet`** | Изоляция от системного раздела |

### Связанные файлы

- **Определения:** [definitions.md](./definitions.md) — типы eviction, thresholds
- **Диагностика:** [diagnostics.md](./diagnostics.md) — общий чек-лист диагностики
- **Memory eviction:** [memory_eviction.md](./memory_eviction.md) — нехватка памяти
- **Профилактика:** [prevention.md](./prevention.md) — мониторинг, best practices
- **Resource Pressure:** [resource_pressure.md](../NodeUnavailability/resource_pressure.md) — давление с точки зрения узла
- **Volume types:** [volume_types.md](../../../Base/Pod/volume_types/volume_types.md) — emptyDir и sizeLimit
