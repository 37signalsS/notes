# Установка Loki в Kubernetes

## Определения

**Loki Helm-чарт** — пакет для развертывания Loki в Kubernetes с поддержкой трёх режимов: Single Binary, Simple Scalable, Distributed.

> **⚠️ Важно (март 2026):** Репозиторий `grafana https://grafana.github.io/helm-charts` более не обновляется. Чарт Loki мигрировал на `grafana-community`.
>
> ```bash
> helm repo add grafana-community https://grafana-community.github.io/helm-charts
> helm repo update
> ```

**Текущая версия (апрель 2026):** Loki 3.x (стабильная), Helm-чарт 6.55.x+

**Подробнее:** [Обзор Grafana Loki](../loki_overview.md)

## Основные концепции

### Режимы развертывания

| Режим | Компоненты | Назначение |
| :--- | :--- | :--- |
| **Single Binary** | Все в одном поде | Тестирование, разработка, малые нагрузки |
| **Simple Scalable** (рекомендуется) | Разделение read/write/backend | Production-средние нагрузки |
| **Distributed** | Каждый компонент отдельно | Крупные production-кластеры |

### Архитектура Simple Scalable (рекомендуемый режим)

```
┌─────────┐     ┌──────────┐     ┌─────────┐
│ Gateway │────→│  Write   │────→│ Storage │
│  (RO)   │     │ (Ingester)│     │  (S3)   │
└────┬────┘     └──────────┘     └─────────┘
     │
     │     ┌──────────┐     ┌─────────┐
     └────→│   Read   │────→│  Cache  │
           │(Querier) │     │ (Redis) │
           └──────────┘     └─────────┘
           ┌──────────┐
           │ Backend  │
           │(Compactor)│
           └──────────┘
```

### Схема хранения данных

| Параметр | Loki 3.x (актуально) | Loki 2.x (устарело) |
| :--- | :--- | :--- |
| **Schema** | `v13` | `v12`, `v11` |
| **Store** | `tsdb` | `boltdb-shipper` |
| **Index period** | `24h` | `24h` |

## Практические сценарии

### Подготовка репозитория Helm

```bash
# Новый репозиторий (после 16 марта 2026)
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Просмотр значений по умолчанию
helm show values grafana-community/loki > loki_values.yaml
```

### Сценарий 1: Production — Simple Scalable с S3

**Файл `loki_values.yaml`:**

```yaml
deploymentMode: SimpleScalable

loki:
  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
    s3:
      endpoint: s3.amazonaws.com
      secretAccessKey: ${S3_SECRET_KEY}
      accessKeyId: ${S3_ACCESS_KEY}
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
  limits_config:
    retention_period: 744h  # 31 день
    max_query_series: 5000
    max_query_parallelism: 14

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

### Сценарий 2: Тестирование — Single Binary с filesystem

```yaml
deploymentMode: SingleBinary

loki:
  storage:
    type: filesystem
  commonConfig:
    replication_factor: 1
  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: index_
          period: 24h

singleBinary:
  replicas: 1
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi

gateway:
  enabled: true
  replicas: 1
```

### Установка Loki

```bash
helm upgrade --install loki grafana-community/loki \
  --namespace logging \
  --create-namespace \
  -f loki_values.yaml \
  --wait --atomic
```

### Проверка статуса

```bash
# Проверка подов
kubectl get pods -n logging -l app.kubernetes.io/name=loki

# Проверка сервисов
kubectl get svc -n logging -l app.kubernetes.io/name=loki

# Детали StatefulSet
kubectl describe statefulset -n logging -l app.kubernetes.io/name=loki

# Логи Loki
kubectl logs -n logging -l app.kubernetes.io/name=loki -f
```

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе Pending** | Отсутствуют PV или нет доступа к S3 | Проверьте состояние PVC: `kubectl get pvc -n logging` и учетные данные S3 |
| **CrashLoopBackOff** | Ошибка конфигурации схемы или хранилища | Изучите логи: `kubectl logs -n logging -l app.kubernetes.io/name=loki` |
| **Ошибка Gateway 502** | Компоненты backend еще не готовы | Дождитесь завершения инициализации всех сервисов |
| **Schema mismatch** | Некорректная дата в параметре `from` | Убедитесь, что `from` не позже даты первого запуска кластера |

### Полезные команды

```bash
# Статус релиза
helm status loki -n logging

# История обновлений
helm history loki -n logging

# Откат к предыдущей версии
helm rollback loki -n logging

# Удаление релиза
helm uninstall loki -n logging

# Просмотр значений
helm get values loki -n logging -o yaml
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Loki](../loki_overview.md) | Архитектура, LogQL, сравнение с Elasticsearch |
| [Установка Grafana](grafana_installation.md) | Визуализация логов, datasource Loki |
| [Примеры LogQL](logql_examples.md) | Запросы для анализа логов |
| [Установка Alloy](alloy_installation.md) | Рекомендуемый агент для сбора логов |
| [Документация Loki Helm](https://grafana.com/docs/loki/latest/setup/install/helm/) | Официальная документация Grafana Labs |
