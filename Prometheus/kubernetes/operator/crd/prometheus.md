# Prometheus — Концепции (CRD)

## Определения

**`kind: Prometheus`** — Custom Resource Definition в Prometheus Operator для декларативного описания экземпляра Prometheus Server. Operator создаёт StatefulSet, Service, Secret и другие Kubernetes-объекты на основе этого CRD.

**API version:** `monitoring.coreos.com/v1`

## Базовые концепции

### Принцип работы

1. Пользователь создаёт Custom Resource (CR) `Prometheus` с желаемым состоянием.
2. Prometheus Operator обнаруживает изменение через механизм watch в Kubernetes API.
3. Operator генерирует scrape-конфигурацию на основе селекторов (ServiceMonitor, PodMonitor, PrometheusRule).
4. Сгенерированная конфигурация сохраняется в Kubernetes Secret.
5. Создаётся или обновляется StatefulSet с pod'ами Prometheus.
6. Sidecar-контейнер `prometheus-config-reloader` автоматически перезагружает Prometheus при изменении конфигурационного Secret.

### Селекторы целей

Ресурс `Prometheus` использует селекторы для определения того, какие ресурсы будут включены в мониторинг:

| Селектор | Тип ресурса | Назначение |
|---|---|---|
| **`serviceMonitorSelector`** | ServiceMonitor | Обнаружение целей через Kubernetes Service |
| **`podMonitorSelector`** | PodMonitor | Обнаружение целей напрямую из Pod |
| **`probeSelector`** | Probe | Blackbox-мониторинг внешних целей |
| **`scrapeConfigSelector`** | ScrapeConfig | Кастомные конфигурации скрейпинга |
| **`ruleSelector`** | PrometheusRule | Правила алертинга и записи (recording rules) |

### Связь с Alertmanager

Конфигурация Alertmanager в `spec` позволяет Prometheus знать, куда отправлять уведомления:

```yaml
spec:
  alerting:
    alertmanagers:
      - namespace: monitoring
        name: alertmanager-main
        port: web
```

> **Подробнее:** [Alertmanager CRD](./alertmanager.md) — описание ресурса управления Alertmanager.

## Практические сценарии

### Базовая конфигурация экземпляра

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

### Настройка внешних лейблов и дополнительных конфигураций

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  externalLabels:
    cluster: production
    environment: prod
  additionalScrapeConfigs:
    name: additional-configs-secret
    key: prometheus-additional.yaml
  scrapeInterval: 30s
  evaluationInterval: 30s
```

### Настройка хранилища

**Персистентное хранилище (рекомендуется):**

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

**Эфемерное хранилище (данные удаляются при перезапуске):**

```yaml
storage:
  emptyDir: {}
```

### Интеграция с Thanos

Использование Thanos Sidecar для долгосрочного хранения и глобальных запросов:

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

## Дополнительная информация

### Основные параметры спецификации (spec)

| Параметр | Описание | Пример |
|---|---|---|
| **`replicas`** | Количество реплик для HA | `2` |
| **`shards`** | Количество шардов для масштабирования | `1` |
| **`version`** | Версия образа Prometheus | `v3.10.0` |
| **`serviceAccountName`** | Имя ServiceAccount с правами RBAC | `prometheus` |
| **`serviceMonitorSelector`** | Селектор для ServiceMonitor | `{matchLabels: {release: monitoring}}` |
| **`ruleSelector`** | Селектор для PrometheusRule | `{matchLabels: {role: alert-rules}}` |
| **`resources`** | Лимиты и запросы ресурсов CPU/RAM | См. пример выше |
| **`retention`** | Время хранения данных (time-based) | `15d` |
| **`retentionSize`** | Лимит размера данных (size-based) | `50GB` |
| **`storage`** | Настройка PVC или emptyDir | См. раздел Хранилище |
| **`externalLabels`** | Глобальные метки экземпляра | `{cluster: production}` |
| **`additionalScrapeConfigs`** | Ссылка на Secret с доп. конфигами | `{name: secret-name, key: key-name}` |
| **`thanos`** | Конфигурация Thanos Sidecar | См. раздел Thanos |

### Связанные ресурсы

- [ServiceMonitor](./servicemonitor.md) — мониторинг сервисов.
- [PodMonitor](./podmonitor.md) — мониторинг подов напрямую.
- [PrometheusRule](./prometheusrule.md) — управление правилами.
- [Alertmanager](./alertmanager.md) — конфигурация Alertmanager.
- [Probe](./probe.md) — blackbox-мониторинг.

### Масштабирование и отказоустойчивость

Подробная информация о настройке репликации (`replicas`), шардирования (`shards`) и обеспечении высокой доступности стека приведена в файле: [High Availability](../high_availability.md).

### Установка без Operator

Инструкции по ручной установке стандартного Prometheus Server доступны в разделе: [Prometheus Server](../../../installation/prometheus_server_installation.md).
