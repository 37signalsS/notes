# CRD Prometheus

## Определения

**`kind: Prometheus`** — Custom Resource Definition для описания экземпляра Prometheus Server.

## Пример конфигурации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.10.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  resources:
    requests:
      memory: 400Mi
      cpu: 200m
    limits:
      memory: 2Gi
      cpu: 1000m
  retention: 15d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

## Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`replicas`** | Количество реплик | `2` (для HA) |
| **`version`** | Версия Prometheus | `v3.10.0` |
| **`serviceAccountName`** | ServiceAccount | `prometheus` |
| **`serviceMonitorSelector`** | Селектор ServiceMonitor | `matchLabels: {release: monitoring}` |
| **`podMonitorSelector`** | Селектор PodMonitor | `matchLabels: {release: monitoring}` |
| **`resources`** | Ресурсы CPU/memory | `requests/limits` |
| **`retention`** | Время хранения данных | `15d` |
| **`retentionSize`** | Максимальный размер данных | `50GB` |
| **`storage`** | Конфигурация хранилища | `volumeClaimTemplate` |
| **`ruleSelector`** | Селектор PrometheusRule | `matchLabels: {release: monitoring}` |
| **`alerting`** | Настройка Alertmanager | `alertmanagers: [{namespace: monitoring}]` |

## Хранилище

### VolumeClaimTemplate

```yaml
storage:
  volumeClaimTemplate:
    spec:
      storageClassName: standard
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi
```

### Ephemeral storage (без персистентности)

```yaml
storage:
  emptyDir: {}
```

## Высокая доступность

Для HA конфигурации:

```yaml
spec:
  replicas: 2
  # Включить шардирование (опционально)
  shards: 2
```

**Важно:**

* Минимум 2 реплики для HA
* StatefulSet не перезапускается при падении ноды
* Используйте external storage для долгосрочных данных

## Связанные темы

* **[Alertmanager CRD](./alertmanager.md)** — описание Alertmanager
* **[ServiceMonitor](./servicemonitor.md)** — цели для скрейпинга
* **[High Availability](../high_availability.md)** — HA конфигурация
* **[Prometheus Server](../../installation/prometheus_server_installation.md)** — базовая установка
