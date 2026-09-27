# Мониторинг S.M.A.R.T. в Kubernetes

## Определения

**DaemonSet для SMART-мониторинга** — объект Kubernetes, обеспечивающий запуск агента сбора метрик S.M.A.R.T. на каждой ноде кластера (или на отобранных по label). Каждый под DaemonSet имеет доступ к блочным устройствам хоста через `hostPath`-olumes или `device`-olumes.

**`smartctl_exporter` в Kubernetes** — компонент Prometheus, развёрнутый как DaemonSet, который опрашивает `smartctl` на каждой ноде и экспортирует метрики на HTTP-порт (по умолчанию `:9633/metrics`).

**Device Plugin (Kubernetes)** — плагин, предоставляющий хостовые устройства (GPU, NVMe, блочные устройства) подам через механизм `resources`. Используется, когда простого `hostPath` недостаточно для корректного контроля доступа.

---

## Базовые концепции

### Архитектура SMART-мониторинга в Kubernetes

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                     │
│                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   Node 1    │  │   Node 2    │  │   Node 3    │      │
│  │             │  │             │  │             │      │
│  │ DaemonSet:  │  │ DaemonSet:  │  │ DaemonSet:  │      │
│  │ smartctl_   │  │ smartctl_   │  │ smartctl_   │      │
│  │ exporter    │  │ exporter    │  │ exporter    │      │
│  │  ↓ :9633    │  │  ↓ :9633    │  │  ↓ :9633    │      │
│  │ Prometheus  │  │ Prometheus  │  │ Prometheus  │      │
│  │  scrape     │  │  scrape     │  │  scrape     │      │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘      │
│         │                │                │              │
│         └────────────────┼────────────────┘              │
│                          ↓                               │
│                  ┌──────────────┐                        │
│                  │  Prometheus  │                        │
│                  │  + Alerting  │                        │
│                  └──────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

### Требования к кластеру

1. **Bare metal или приватный облако:** SMART-мониторинг применим только к физическим дискам. В публичных облаках (AWS EBS, GCP Persistent Disk, Azure Disk) SMART-данные недоступны — диски являются сетевыми блочными устройствами.
2. **Доступ к `/dev/` на ноде:** Контейнер должен видеть блочные устройства хоста. Стандартный `securityContext` не предоставляет доступа — необходим `hostPath` или device plugin.
3. **Установленный `smartmontools` на ноде:** `smartctl` должен быть доступен в namespaces host-системы. В контейнере можно установить пакет, но для работы с реальными устройствами нужен доступ к `/dev/sdX` или `/dev/nvmeXnY`.

### Почему не privileged-контейнер

Запуск `smartctl` в привилегированном контейнере (`--privileged`) — это крайняя мера, которая:
- Открывает полный доступ ко всем устройствам хоста
- Нарушает принцип наименьших привилегий
- Делает уязвимым весь кластер при компрометации контейнера

Правильный подход — минимальный набор прав: `hostPath` на конкретные устройства + `SYS_RAWIO` capability.

---

## Практические сценарии

### Вариант 1: DaemonSet с hostPath (минимальный)

Самый простой вариант для небольших кластеров без GPU/PCIe-устройств:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: smartctl-exporter
  namespace: monitoring
  labels:
    app: smartctl-exporter
spec:
  selector:
    matchLabels:
      app: smartctl-exporter
  template:
    metadata:
      labels:
        app: smartctl-exporter
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9633"
    spec:
      serviceAccountName: smartctl-exporter
      tolerations:
        - operator: Exists
          effect: NoSchedule
      containers:
        - name: smartctl-exporter
          image: prometheus/smartctl_exporter:latest
          ports:
            - containerPort: 9633
              name: metrics
              protocol: TCP
          args:
            - "--smartctl.path=/usr/sbin/smartctl"
            - "--smartctl.interval=60s"
          volumeMounts:
            - name: dev
              mountPath: /dev
              readOnly: true
            - name: smartctl-bin
              mountPath: /usr/sbin/smartctl
              readOnly: true
            - name: proc
              mountPath: /proc
              readOnly: true
            - name: sys
              mountPath: /sys
              readOnly: true
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
              add: ["SYS_RAWIO"]
      volumes:
        - name: dev
          hostPath:
            path: /dev
            type: Directory
        - name: smartctl-bin
          hostPath:
            path: /usr/sbin/smartctl
            type: File
        - name: proc
          hostPath:
            path: /proc
            type: Directory
        - name: sys
          hostPath:
            path: /sys
            type: Directory
```

### Вариант 2: DaemonSet с device plugin (Enterprise)

Для кластеров, где требуется строгий контроль доступа к устройствам:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: smartctl-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: smartctl-exporter
  template:
    metadata:
      labels:
        app: smartctl-exporter
    spec:
      serviceAccountName: smartctl-exporter
      containers:
        - name: smartctl-exporter
          image: prometheus/smartctl_exporter:latest
          ports:
            - containerPort: 9633
          securityContext:
            capabilities:
              drop: ["ALL"]
              add: ["SYS_RAWIO"]
          volumeMounts:
            - name: dev-nvme
              mountPath: /dev/nvme0n1
              readOnly: true
            - name: dev-sda
              mountPath: /dev/sda
              readOnly: true
            - name: dev-sdb
              mountPath: /dev/sdb
              readOnly: true
      volumes:
        - name: dev-nvme
          hostPath:
            path: /dev/nvme0n1
            type: CharDevice
        - name: dev-sda
          hostPath:
            path: /dev/sda
            type: CharDevice
        - name: dev-sdb
          hostPath:
            path: /dev/sdb
            type: CharDevice
```

### Установка через Helm-чарт

Официальный Helm-чарт для `smartctl_exporter`:

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройкой tolerations для master-нод
helm install smartctl-exporter prometheus-community/prometheus-smartctl-exporter \
  --namespace monitoring \
  --create-namespace \
  --set tolerations[0].key=node-role.kubernetes.io/master \
  --set tolerations[0].operator=Exists \
  --set tolerations[0].effect=NoSchedule \
  --set smartctl.interval=60s
```

### ServiceMonitor для Prometheus Operator

Если в кластере используется Prometheus Operator (kube-prometheus-stack):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: smartctl-exporter
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: smartctl-exporter
  endpoints:
    - port: metrics
      interval: 60s
      path: /metrics
```

### Настройка Prometheus scrape

Если Prometheus работает standalone (не через Operator):

```yaml
# prometheus.yml
scrape_configs:
  - job_name: "smartctl"
    static_configs:
      - targets:
          - "node1:9633"
          - "node2:9633"
          - "node3:9633"
    scrape_interval: 60s
    metrics_path: /metrics
```

### PromQL-запросы для алертинга

```promql
# Критическое предупреждение NVMe
smartctl_device_critical_warning != 0

# Износ SSD превышает 80%
smartctl_device_percentage_used > 80

# Температура диска выше критического порога
smartctl_device_temperature_celsius > 70

# Доступный запас резервных блоков ниже 20%
smartctl_device_available_spare < 20

# Диск не отвечает (метрика недоступна более 5 минут)
up{job="smartctl"} == 0
```

### Node-exporter collector: альтернатива smartctl_exporter

Если `smartctl_exporter` невозможно развернуть отдельно, `node_exporter` имеет встроенный коллектор `textfile`:

```bash
# Cron-скрипт на ноде: запись метрик в файл для node_exporter
cat > /usr/local/bin/smartctl-textfile.sh << 'EOF'
#!/bin/bash
OUTFILE="/var/lib/node_exporter/textfile_collector/smartctl.prom"

echo "# HELP smartctl_device_temperature Temperature in Celsius" > "$OUTFILE"
echo "# TYPE smartctl_device_temperature gauge" >> "$OUTFILE"

for dev in /dev/sd? /dev/nvme?n?; do
  [ -e "$dev" ] || continue
  temp=$(sudo smartctl -A "$dev" --json 2>/dev/null | jq -r '.temperature // empty')
  if [ -n "$temp" ]; then
    echo "smartctl_device_temperature{device=\"$(basename $dev)\"} $temp" >> "$OUTFILE"
  fi
done
EOF
chmod +x /usr/local/bin/smartctl-textfile.sh
```

### Доступ к /dev из privileged-контейнера (крайний случай)

Если aucun другой вариант не работает:

```yaml
securityContext:
  privileged: true
  # Или более безопасно:
  capabilities:
    add: ["SYS_RAWIO"]
hostPID: false
hostNetwork: false
volumes:
  - name: dev
    hostPath:
      path: /dev
      type: Directory
```

---

## Дополнительная информация

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` в контейнере | Отсутствует `SYS_RAWIO` capability | Добавить `capabilities.add: ["SYS_RAWIO"]` |
| `smartctl` не видит устройства | `hostPath` не примонтирован | Проверить `volumeMounts` и `volumes` |
| Метрики не обновляются | `scrape_interval` слишком большой | Уменьшить до `60s` или `30s` |
| DaemonSet не запускается на master | Отсутствуют `tolerations` | Добавить toleration для `NoSchedule` |
| `Device not found` | Имя устройства изменилось (hot-plug) | Использовать `DEVICESCAN` вместо конкретных путей |

### NodeSelector и фильтрация нод

Если не все ноды нуждаются в мониторинге:

```yaml
nodeSelector:
  node-type: bare-metal
  # Или исключить виртуальные ноды:
  # cloud.google.com/gke-nodepool: ""
```

Для пропуска master-нод (control plane):

```yaml
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
```

### Безопасность

- Контейнер `smartctl_exporter` не должен иметь доступа к пользовательским данным (卷 `/data`, `/var/lib` и т.д.)
- Используйте `readOnlyRootFilesystem: true`
- Не передавайте secrets в контейнер — экспортер не требует аутентификации
- Ограничьте network policy: порт `9633` должен быть доступен только для Prometheus

### Кросс-ссылки

- [Главная страница: smartctl](./index.md) — навигация и инструменты.
- [smartctl_exporter: установка и настройка](./smartctl_exporter.md) — деплой exporter как systemd-службы или Docker-контейнера.
- [Автоматический мониторинг (smartd)](./smartd_monitoring.md) — конфигурация демона мониторинга.
- [Диагностика NVMe: AER и Reset](../nvme-errors-diagnostics.md) — анализ PCIe-ошибок, когда SMART показывает PASSED.
