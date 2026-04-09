# CRD Prometheus

## Definitions

**`kind: Prometheus`** — Custom Resource Definition в Prometheus Operator для декларативного описания экземпляра Prometheus Server. Operator создаёт StatefulSet, Service, Secret и другие Kubernetes-объекты на основе этого CRD.

**API version:** `monitoring.coreos.com/v1`

## Basic Concepts

### Принцип работы

1. Пользователь создаёт CR `Prometheus` с желаемым состоянием
2. Prometheus Operator обнаруживает изменение через watch
3. Operator генерирует scrape-конфигурацию на основе селекторов (ServiceMonitor, PodMonitor, PrometheusRule)
4. Конфигурация сохраняется в Kubernetes Secret
5. Создаётся/обновляется StatefulSet с Prometheus pod'ами
6. Sidecar `prometheus-config-reloader` автоматически перезагружает Prometheus при изменении Secret

### Селекторы целей

Prometheus CRD использует селекторы для определения какие ресурсы скрейпить:

| Селектор | Выбирает | Описание |
|---|---|---|
| `serviceMonitorSelector` | ServiceMonitor | Цели для скрейпинга через Service |
| `podMonitorSelector` | PodMonitor | Цели для скрейпинга напрямую из Pod |
| `probeSelector` | Probe | Blackbox-мониторинг |
| `scrapeConfigSelector` | ScrapeConfig | Кастомные scrape-конфигурации |
| `ruleSelector` | PrometheusRule | Recording и alerting rules |

### Связь с Alertmanager

```yaml
spec:
  alerting:
    alertmanagers:
      - namespace: monitoring
        name: alertmanager-main
        port: web
```

> **См. также:** [Alertmanager CRD](./alertmanager.md) — описание Alertmanager CRD.

## Practical Scenarios

### Базовая конфигурация

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
  podMonitorSelector:
    matchLabels:
      release: monitoring
  ruleSelector:
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

### С Alertmanager

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 1
  version: v3.10.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  alerting:
    alertmanagers:
      - namespace: monitoring
        name: alertmanager-main
        port: web
        pathPrefix: /
        apiVersion: v2
  ruleSelector:
    matchLabels:
      role: alert-rules
```

### С external labels и additional scrape configs

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 1
  externalLabels:
    cluster: production
    region: eu-west-1
    environment: prod
  additionalScrapeConfigs:
    name: additional-scrape-configs
    key: prometheus-additional.yaml
  scrapeInterval: 30s
  evaluationInterval: 30s
  retention: 15d
  retentionSize: 50GB
```

### Хранилище: VolumeClaimTemplate

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

### Хранилище: Ephemeral (без персистентности)

```yaml
storage:
  emptyDir: {}
```

### Thanos Sidecar

```yaml
spec:
  thanos:
    version: v0.37.0
    image: quay.io/thanos/thanos:v0.37.0
    resources:
      requests:
        memory: 128Mi
        cpu: 100m
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
```

> **См. также:** [High Availability](../high_availability.md) — HA и шардирование; [Thanos Overview](../../scaling/thanos_overview.md).

### Основные параметры spec

| Параметр | Описание | Пример |
|---|---|---|
| **`replicas`** | Количество реплик | `2` (для HA) |
| **`shards`** | Количество шардов | `2` (горизонтальное масштабирование) |
| **`version`** | Версия Prometheus | `v3.10.0` |
| **`image`** | Custom образ | `myregistry/prometheus:v3.10.0` |
| **`serviceAccountName`** | ServiceAccount | `prometheus` |
| **`serviceMonitorSelector`** | Селектор ServiceMonitor | `matchLabels: {release: monitoring}` |
| **`serviceMonitorNamespaceSelector`** | Namespace для ServiceMonitor | `matchNames: [default]` |
| **`podMonitorSelector`** | Селектор PodMonitor | `matchLabels: {release: monitoring}` |
| **`podMonitorNamespaceSelector`** | Namespace для PodMonitor | `matchNames: [default]` |
| **`probeSelector`** | Селектор Probe | `matchLabels: {release: monitoring}` |
| **`ruleSelector`** | Селектор PrometheusRule | `matchLabels: {release: monitoring}` |
| **`alerting`** | Конфигурация Alertmanager | См. выше |
| **`resources`** | Ресурсы CPU/memory | `requests/limits` |
| **`retention`** | Время хранения данных | `15d` |
| **`retentionSize`** | Макс. размер TSDB | `50GB` |
| **`storage`** | Конфигурация хранилища | `volumeClaimTemplate`, `emptyDir` |
| **`externalLabels`** | Глобальные лейблы | `{cluster: production}` |
| **`scrapeInterval`** | Интервал скрейпинга по умолчанию | `30s` |
| **`evaluationInterval`** | Интервал вычисления правил | `30s` |
| **`enableFeatures`** | Экспериментальные функции | `[exemplar-storage, auto-reload]` |
| **`additionalScrapeConfigs`** | Доп. scrape-конфигурации | Secret с YAML |
| **`thanos`** | Thanos Sidecar конфигурация | См. выше |
| **`secrets`** | Secret'ы для монтирования | `['tls-cert', 'bearer-token']` |
| **`securityContext`** | Security context pod'а | `runAsNonRoot: true` |

## Additional Information

### Связанные CRD

- [ServiceMonitor](./servicemonitor.md) — цели для скрейпинга через Service
- [PodMonitor](./podmonitor.md) — цели для скрейпинга напрямую из Pod
- [PrometheusRule](./prometheusrule.md) — alerting и recording rules
- [Alertmanager](./alertmanager.md) — описание Alertmanager
- [Probe](./probe.md) — blackbox-мониторинг

### High Availability и шардирование

HA-конфигурация Prometheus (реплики, шарды, Thanos Sidecar) описана в отдельном файле: [High Availability](../high_availability.md).

### Установка Prometheus Server

Базовая установка Prometheus без Operator: [Prometheus Server](../../../installation/prometheus_server_installation.md).
