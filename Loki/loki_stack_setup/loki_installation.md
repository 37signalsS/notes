# Установка Loki в Kubernetes

## Подготовка

Добавьте официальный Helm-репозиторий Grafana:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

## Настройка Values для Loki

Сохраним стандартные `values` для дальнейшей кастомизации:

```bash
helm show values grafana/loki > loki_values.yaml
```

### Актуальные параметры для Loki 3.x

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| **`loki.storage.type`** | Тип хранилища | `s3`, `gcs`, `azure`, `filesystem` |
| **`loki.storage.bucketNames.chunks`** | Bucket для чанков | `loki-chunks` |
| **`loki.storage.bucketNames.ruler`** | Bucket для правил | `loki-ruler` |
| **`loki.storage.bucketNames.admin`** | Bucket для конфигураций | `loki-admin` |
| **`deploymentMode`** | Режим развертывания | `SimpleScalable` (рекомендуется) |
| **`loki.commonConfig.replication_factor`** | Фактор репликации | `3` (для HA) |
| **`read.replicas`** | Реплики для чтения | `2` |
| **`write.replicas`** | Реплики для записи | `2` |
| **`backend.replicas`** | Реплики бэкенда | `2` |

### Пример `loki_values.yaml` для production

```yaml
# loki_values.yaml
deploymentMode: SimpleScalable

loki:
  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
  commonConfig:
    replication_factor: 3
  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: s3
        schema: v13
        index:
          prefix: index_
          period: 24h

read:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

write:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

backend:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

gateway:
  enabled: true
  replicas: 2

monitoring:
  dashboards:
    enabled: true
  rules:
    enabled: true
  serviceMonitor:
    enabled: true
```

> **Примечание:** Схема `v13` с хранилищем `tsdb` — актуальная схема для Loki 3.x. Для тестовых сред можно использовать `filesystem` вместо `s3`.

## Установка Loki

Установим Loki с помощью Helm в `logging` namespace:

```bash
helm upgrade --install loki grafana/loki \
  --namespace logging \
  -f loki_values.yaml
```

### Проверка статуса

```bash
# Проверка подов
kubectl get pods -n logging -l app.kubernetes.io/name=loki

# Детальная информация
kubectl describe statefulset -n logging -l app.kubernetes.io/name=loki
```

## Связанные темы

* **[Обзор Grafana Loki](../loki_overview.md)** — архитектура, LogQL, базовые концепции
* **[Установка Promtail](promtail_installation.md)** — агент для сбора логов
* **[Установка Grafana](grafana_installation.md)** — визуализация логов
* **[Grafana Alloy](../../Grafana/grafana_alloy_overview.md)** — альтернатива Promtail
